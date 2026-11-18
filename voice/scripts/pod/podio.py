"""Move files to and from a Runpod pod through the API's exec call only (no SSH, no open ports).
The key is read from /tmp/claude-0/secret/rp_key and never printed.

  python podio.py exec <pod> '<shell command>' [timeout]
  python podio.py up   <pod> <local file> <remote file>
  python podio.py down <pod> <remote file> <local file>
"""
import base64
import random, hashlib, json, os, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

API = "https://api.runpod.io/v2"
KEY = open("/tmp/claude-0/secret/rp_key").read().strip()
ARG = 4000          # chars per argv entry (limit 4096)
ARGS_PER_CALL = 23  # keeps the request body under the 100 KB limit
DOWN_BYTES = 720 * 1024  # stdout cap is 1 MiB; base64 of this fits


def call(method, path, body=None, tries=12):
    data = json.dumps(body).encode() if body is not None else None
    for t in range(tries):
        req = urllib.request.Request(API + path, data=data, method=method, headers={
            "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:300]
            if e.code in (409, 429, 500, 502, 503, 504) and t < tries - 1:
                # back off for real: the API's Retry-After is often 1 s, too short when several transfers share the limit
                time.sleep(max(float(e.headers.get("Retry-After") or 0), min(2 ** t, 60)) + random.random()); continue
            raise RuntimeError(f"{method} {path}: HTTP {e.code} {msg}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if t < tries - 1:
                time.sleep(2 + 2 * t); continue
            raise


def run(pod, argv, timeout=25):
    return call("POST", f"/pods/{pod}/exec", {"command": argv, "timeoutSeconds": timeout})


def sh(pod, cmd, timeout=25):
    return run(pod, ["sh", "-c", cmd], timeout)


def upload(pod, local, remote):
    raw = open(local, "rb").read()
    digest = hashlib.sha256(raw).hexdigest()
    b64 = base64.b64encode(raw).decode()
    per = ARG * ARGS_PER_CALL
    parts = [b64[i:i + per] for i in range(0, len(b64), per)]
    tmp = remote + ".parts"
    sh(pod, f"rm -rf '{tmp}' && mkdir -p '{tmp}' '{os.path.dirname(remote) or '.'}'")
    writer = "import sys;open(sys.argv[1],'w').write(''.join(sys.argv[2:]))"

    def put(k):
        chunk = parts[k]
        args = [chunk[i:i + ARG] for i in range(0, len(chunk), ARG)]
        r = run(pod, ["python3", "-c", writer, f"{tmp}/{k:06d}"] + args)
        if r.get("exitCode") != 0:
            raise RuntimeError(f"part {k}: {r}")

    t0 = time.time()
    with ThreadPoolExecutor(6) as ex:
        for n, _ in enumerate(ex.map(put, range(len(parts)))):
            if n % 25 == 0:
                print(f"  {n}/{len(parts)} parts, {time.time() - t0:.0f}s", flush=True)
    r = sh(pod, f"cat '{tmp}'/* | base64 -d > '{remote}' && rm -rf '{tmp}' && sha256sum '{remote}'")
    ok = digest in r.get("stdout", "")
    print(f"up {local} -> {remote}: {len(raw)} bytes, {len(parts)} calls, {time.time() - t0:.0f}s, sha256 {'OK' if ok else 'MISMATCH ' + str(r)}")
    if not ok:
        sys.exit(1)


def download(pod, remote, local):
    # A big file's hash can take longer than one call may run: use a precomputed <file>.sha256 when there is one.
    r = sh(pod, f"stat -c %s '{remote}' && (cat '{remote}.sha256' 2>/dev/null || sha256sum '{remote}')")
    lines = r["stdout"].split()
    size, digest = int(lines[0]), lines[1]
    n = (size + DOWN_BYTES - 1) // DOWN_BYTES
    blk = 8192  # DOWN_BYTES is a multiple of this

    def get(k):
        cmd = f"dd if='{remote}' bs={blk} skip={k * DOWN_BYTES // blk} count={DOWN_BYTES // blk} 2>/dev/null | base64 -w0"
        r = sh(pod, cmd)
        if r.get("exitCode") != 0 or r.get("truncated"):
            raise RuntimeError(f"chunk {k}: {str(r)[:200]}")
        return base64.b64decode(r["stdout"])

    t0 = time.time()
    with ThreadPoolExecutor(4) as ex:
        chunks = []
        for k, c in enumerate(ex.map(get, range(n))):
            chunks.append(c)
            if k % 25 == 0:
                print(f"  {k}/{n} chunks, {time.time() - t0:.0f}s", flush=True)
    data = b"".join(chunks)
    os.makedirs(os.path.dirname(os.path.abspath(local)), exist_ok=True)
    open(local, "wb").write(data)
    ok = hashlib.sha256(data).hexdigest() == digest and len(data) == size
    print(f"down {remote} -> {local}: {size} bytes, {n} calls, {time.time() - t0:.0f}s, sha256 {'OK' if ok else 'MISMATCH'}")
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
            print("[timed out waiting; command may still run]")
        sys.exit(r.get("exitCode") or 0)
    elif op == "up":
        upload(pod, sys.argv[3], sys.argv[4])
    elif op == "down":
        download(pod, sys.argv[3], sys.argv[4])
