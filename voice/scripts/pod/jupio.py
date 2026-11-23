"""Run commands on a Runpod pod and move files to and from it through the pod's own Jupyter server,
using Jupyter's plain HTTPS file API only (no WebSocket, no SSH, no Runpod exec).

For pods whose Runpod API key may not run commands (the API's exec call answers 403), from a machine
whose proxy carries no WebSockets. Same commands as podio.py:

  python jupio.py exec <pod> '<shell command>' [timeout seconds, default 25]
  python jupio.py up   <pod> <local file> <remote file>
  python jupio.py down <pod> <remote file> <local file>

How it runs a command: a small job runner (runner.sh below) lives on the pod in /root/jupio. It is started
once, by starting a Jupyter kernel whose kernel spec launches it. A command is written as a job file into its
queue through the file API; the runner runs it under `timeout` and leaves stdout, stderr and the exit code in
its done folder, which are read back and deleted.

The pod's Jupyter is reached at https://<pod>-8888.proxy.runpod.net. Its token is never read or printed
here: the session's network proxy adds it to every request to that host (a network secret saved for it),
so the header below carries only a placeholder.
"""
import base64, hashlib, json, os, sys, time, uuid, urllib.error, urllib.parse, urllib.request

AUTH = {"Authorization": "Token proxy-injected", "User-Agent": "kyoko-jupio/1.0"}
D = "root/jupio"                              # the runner's folder, relative to Jupyter's root ("/")
SPEC = "usr/local/share/jupyter/kernels/jupio-runner"  # Jupyter refuses hidden paths such as ~/.local
CHUNK = 8 * 1024 * 1024                       # bytes per chunk of Jupyter's chunked upload

RUNNER = r"""#!/bin/bash
# jupio's job runner: runs each job file dropped into queue/, leaves .out .err .rc in done/.
D=/root/jupio; mkdir -p $D/queue $D/run $D/done
echo $$ > $D/runner.pid
while true; do
  date +%s > $D/heartbeat
  for f in $D/queue/*.job; do
    [ -e "$f" ] || continue
    id=$(basename "$f" .job)
    mv "$f" "$D/run/$id.job" 2>/dev/null || continue
    (
      t=$(head -1 "$D/run/$id.job"); tail -n +2 "$D/run/$id.job" > "$D/run/$id.sh"
      cd /workspace 2>/dev/null || cd /
      timeout --kill-after=5 "$t" bash "$D/run/$id.sh" > "$D/run/$id.out" 2> "$D/run/$id.err" < /dev/null
      echo $? > "$D/run/$id.rc.tmp"
      mv "$D/run/$id.out" "$D/run/$id.err" "$D/done/"
      mv "$D/run/$id.rc.tmp" "$D/done/$id.rc"
      rm -f "$D/run/$id.job" "$D/run/$id.sh"
    ) &
  done
  sleep 0.3
done
"""

KERNEL = {
    "argv": ["bash", "-c",
             # By pid file, not pgrep -f: this very command line names runner.sh, so pgrep would find itself.
             "{ kill -0 $(cat /root/jupio/runner.pid 2>/dev/null) 2>/dev/null || setsid nohup bash /root/jupio/runner.sh "
             ">/root/jupio/runner.log 2>&1 < /dev/null & } ; exec sleep infinity", "{connection_file}"],
    "display_name": "jupio runner",
    "language": "bash",
}


def base(pod):
    return f"https://{pod}-8888.proxy.runpod.net"


def http(pod, method, path, body=None, tries=8, raw=False, ok404=False):
    data = json.dumps(body).encode() if body is not None else None
    for t in range(tries):
        req = urllib.request.Request(base(pod) + path, data=data, method=method,
                                     headers={**AUTH, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                out = r.read()
                return out if raw else (json.loads(out) if out else {})
        except urllib.error.HTTPError as e:
            if e.code == 404 and ok404:
                return None
            msg = e.read().decode(errors="replace")[:300]
            if e.code in (429, 500, 502, 503, 504, 520, 522, 524) and t < tries - 1:
                time.sleep(min(2 ** t, 30)); continue
            raise RuntimeError(f"{method} {path}: HTTP {e.code} {msg}")
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if t < tries - 1:
                time.sleep(2 + 2 * t); continue
            raise


def q(path):
    return urllib.parse.quote(path.lstrip("/"))


def put_text(pod, path, text):
    http(pod, "PUT", "/api/contents/" + q(path), {"type": "file", "format": "text", "content": text})


def mkdirs(pod, path):
    parts = path.strip("/").split("/")
    for i in range(1, len(parts) + 1):
        p = "/".join(parts[:i])
        if http(pod, "GET", "/api/contents/" + q(p) + "?content=0", ok404=True) is None:
            http(pod, "PUT", "/api/contents/" + q(p), {"type": "directory"})


def read_file(pod, path):
    return http(pod, "GET", "/files/" + q(path), raw=True)


def delete(pod, path):
    http(pod, "DELETE", "/api/contents/" + q(path), ok404=True)


def beat(pod):
    hb = http(pod, "GET", "/api/contents/" + q(f"{D}/heartbeat") + "?content=1&format=text", ok404=True)
    return hb["content"].strip() if hb else None


def runner_alive(pod):
    """True when the runner's heartbeat (whole seconds, rewritten every 0.3 s) moves within about 2.5 s.
    A positive check is remembered for a minute, so a run of commands does not pay for it each time."""
    seen = f"/tmp/claude-0/secret/jupio_alive_{pod}"
    if os.path.exists(seen) and time.time() - os.path.getmtime(seen) < 60:
        return True
    first = beat(pod)
    if first is None:
        return False
    for _ in range(5):
        time.sleep(0.6)
        if beat(pod) != first:
            os.makedirs(os.path.dirname(seen), mode=0o700, exist_ok=True)
            open(seen, "w").close()
            return True
    return False


def ensure_runner(pod):
    if runner_alive(pod):
        return
    mkdirs(pod, f"{D}/queue"); mkdirs(pod, f"{D}/done"); mkdirs(pod, SPEC)
    put_text(pod, f"{D}/runner.sh", RUNNER)
    put_text(pod, f"{SPEC}/kernel.json", json.dumps(KERNEL, indent=1))
    http(pod, "POST", "/api/kernels", {"name": "jupio-runner"})
    for _ in range(40):
        time.sleep(0.5)
        if http(pod, "GET", "/api/contents/" + q(f"{D}/heartbeat") + "?content=0", ok404=True):
            return
    raise RuntimeError("the job runner did not start on the pod")


def sh(pod, cmd, timeout=25):
    """Run a shell command on the pod; returns {stdout, stderr, exitCode, timedOut} like podio.py."""
    ensure_runner(pod)
    jid = uuid.uuid4().hex
    put_text(pod, f"{D}/queue/{jid}.job", f"{int(timeout)}\n{cmd}\n")
    deadline = time.time() + timeout + 60
    delay = 0.3
    while time.time() < deadline:
        rc = http(pod, "GET", "/api/contents/" + q(f"{D}/done/{jid}.rc") + "?content=1&format=text", ok404=True)
        if rc:
            code = int(rc["content"].strip() or 1)
            out = read_file(pod, f"{D}/done/{jid}.out").decode(errors="replace")
            err = read_file(pod, f"{D}/done/{jid}.err").decode(errors="replace")
            for ext in ("rc", "out", "err"):
                delete(pod, f"{D}/done/{jid}.{ext}")
            timed = code in (124, 137)
            return {"stdout": out, "stderr": err, "exitCode": None if timed else code, "timedOut": timed}
        time.sleep(delay)
        delay = min(delay * 1.5, 3)
    return {"stdout": "", "stderr": "", "exitCode": None, "timedOut": True}


def upload(pod, local, remote):
    raw = open(local, "rb").read()
    digest = hashlib.sha256(raw).hexdigest()
    parent = os.path.dirname(remote.rstrip("/"))
    if parent and parent != "/":
        mkdirs(pod, parent)
    t0 = time.time()
    n = max(1, (len(raw) + CHUNK - 1) // CHUNK)
    for k in range(n):
        part = raw[k * CHUNK:(k + 1) * CHUNK]
        body = {"type": "file", "format": "base64", "content": base64.b64encode(part).decode()}
        if n > 1:
            body["chunk"] = -1 if k == n - 1 else k + 1
        http(pod, "PUT", "/api/contents/" + q(remote), body)
        if k % 5 == 0 and n > 1:
            print(f"  {k + 1}/{n} chunks, {time.time() - t0:.0f}s", flush=True)
    r = sh(pod, f"sha256sum '{remote}'", 600)
    ok = digest in r.get("stdout", "")
    print(f"up {local} -> {remote}: {len(raw)} bytes, {n} chunks, {time.time() - t0:.0f}s, sha256 {'OK' if ok else 'MISMATCH ' + str(r)[:300]}")
    if not ok:
        sys.exit(1)


def download(pod, remote, local):
    r = sh(pod, f"stat -c %s '{remote}' && (cat '{remote}.sha256' 2>/dev/null || sha256sum '{remote}')", 600)
    size, digest = int(r["stdout"].split()[0]), r["stdout"].split()[1]
    t0 = time.time()
    data = read_file(pod, remote)
    os.makedirs(os.path.dirname(os.path.abspath(local)), exist_ok=True)
    open(local, "wb").write(data)
    ok = hashlib.sha256(data).hexdigest() == digest and len(data) == size
    print(f"down {remote} -> {local}: {size} bytes, {time.time() - t0:.0f}s, sha256 {'OK' if ok else 'MISMATCH'}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    op, pod = sys.argv[1], sys.argv[2]
    if op == "exec":
        r = sh(pod, sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 25)
        sys.stdout.write(r.get("stdout", ""))
        if r.get("stderr"):
            sys.stderr.write(r["stderr"])
        if r.get("timedOut"):
            print("[timed out: the command was stopped]")
        sys.exit(r.get("exitCode") or 0)
    elif op == "up":
        upload(pod, sys.argv[3], sys.argv[4])
    elif op == "down":
        download(pod, sys.argv[3], sys.argv[4])
