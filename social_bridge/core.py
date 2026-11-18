"""The bridge: holds platform adapters, the approval queue, the inbox the AI reads, and the live feed."""
import json
import logging
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from .base import ADAPTERS, Http, Incoming, PlatformError

log = logging.getLogger("social_bridge")

MODES = ("review", "auto")


class Bridge:
    def __init__(self, config, data_dir=None, adapters=None):
        self.config = config
        self.mode = config.get("mode", "review")
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.paused = False
        self.lock = threading.RLock()
        self.dir = Path(data_dir or config.get("data_dir", "social_data"))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.adapters = adapters if adapters is not None else self._build_adapters()
        self.platform_status = {name: {"account": None, "error": None} for name in self.adapters}

        self.actions = {}                         # id -> action dict
        self.inbox = deque(maxlen=2000)           # incoming dicts with "seq"
        self.feed = deque(maxlen=500)             # dashboard timeline
        self.seq = 0
        self.poll_state = {}
        self.seen = {}                            # platform -> deque of seen incoming ids
        self._threads = []
        self._stop = threading.Event()
        self._listeners = []                      # callables(incoming_dict) e.g. the responder
        self._load()

    # ------------------------------------------------------------------ setup
    def _build_adapters(self):
        built = {}
        for name, pconf in (self.config.get("platforms") or {}).items():
            if not pconf or not pconf.get("enabled"):
                continue
            cls = ADAPTERS.get(name)
            if cls is None:
                log.warning("unknown platform in config: %s", name)
                continue
            built[name] = cls(pconf, Http(name, user_agent=pconf.get("user_agent") or f"social-bridge/1.0 ({name})"))
        return built

    def _load(self):
        state_file = self.dir / "state.json"
        if state_file.exists():
            state = json.loads(state_file.read_text())
            self.poll_state = state.get("poll_state", {})
            self.seq = state.get("seq", 0)
            self.seen = {k: deque(v, maxlen=5000) for k, v in state.get("seen", {}).items()}
            self.mode = state.get("mode", self.mode)
        actions_file = self.dir / "actions.json"
        if actions_file.exists():
            self.actions = {a["id"]: a for a in json.loads(actions_file.read_text())}
        for name, fname in (("inbox", "inbox.jsonl"), ("feed", "feed.jsonl")):
            path = self.dir / fname
            if path.exists():
                target = getattr(self, name)
                for line in path.read_text().splitlines()[-target.maxlen:]:
                    try:
                        target.append(json.loads(line))
                    except ValueError:
                        pass

    def _save(self):
        with self.lock:
            (self.dir / "state.json").write_text(json.dumps({
                "poll_state": self.poll_state, "seq": self.seq, "mode": self.mode,
                "seen": {k: list(v) for k, v in self.seen.items()},
            }))
            recent = sorted(self.actions.values(), key=lambda a: a["created"])[-1000:]
            self.actions = {a["id"]: a for a in recent}
            (self.dir / "actions.json").write_text(json.dumps(recent))

    def _append(self, fname, entry):
        with open(self.dir / fname, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _event(self, kind, **data):
        entry = {"ts": time.time(), "kind": kind, **data}
        with self.lock:
            self.feed.append(entry)
            self._append("feed.jsonl", entry)
        return entry

    # --------------------------------------------------------------- outgoing
    def submit(self, platform, action, text, target=None, opts=None, source="agent", context=None):
        """Queue an outgoing action. In auto mode (and not paused) it is executed right away."""
        adapter = self.adapters.get(platform)
        if adapter is None:
            raise PlatformError(platform, f"platform not enabled. Enabled: {', '.join(self.adapters) or 'none'}")
        if action not in adapter.actions:
            raise PlatformError(platform, f"'{action}' not available on {platform}. Available: {', '.join(adapter.actions)}")
        if action in ("comment", "dm") and not target:
            raise PlatformError(platform, f"'{action}' needs a target")
        if not (text or "").strip() and not (opts or {}).get("media"):
            raise PlatformError(platform, "text is empty")
        a = {
            "id": uuid.uuid4().hex[:10], "platform": platform, "action": action, "target": target,
            "text": text, "opts": opts or {}, "status": "pending", "source": source, "context": context,
            "created": time.time(), "updated": time.time(), "result": None, "error": None,
        }
        with self.lock:
            self.actions[a["id"]] = a
        self._event("queued", action=_public(a))
        if self.mode == "auto" and not self.paused:
            return self.execute(a["id"])
        self._save()
        return a

    def approve(self, action_id, text=None):
        with self.lock:
            a = self._get(action_id)
            if a["status"] != "pending":
                raise ValueError(f"action {action_id} is {a['status']}")
            if text is not None and text != a["text"]:
                a["original_text"], a["text"] = a["text"], text
            a["status"] = "approved"
        return self.execute(action_id)

    def reject(self, action_id, reason=""):
        with self.lock:
            a = self._get(action_id)
            if a["status"] != "pending":
                raise ValueError(f"action {action_id} is {a['status']}")
            a.update(status="rejected", error=reason or None, updated=time.time())
        self._event("rejected", action=_public(a))
        self._save()
        return a

    def execute(self, action_id):
        with self.lock:
            a = self._get(action_id)
            if a["status"] not in ("pending", "approved"):
                raise ValueError(f"action {action_id} is {a['status']}")
            a["status"] = "sending"
        adapter = self.adapters[a["platform"]]
        try:
            if a["action"] == "post":
                o = a["opts"]
                res = adapter.post(a["text"], target=a["target"], title=o.get("title"), link=o.get("link"),
                                   media=o.get("media"))
            elif a["action"] == "comment":
                res = adapter.comment(a["target"], a["text"])
            else:
                res = adapter.dm(a["target"], a["text"])
            a.update(status="sent", result=res.to_dict(), updated=time.time())
            self._event("sent", action=_public(a))
        except Exception as e:  # noqa: BLE001 - any adapter failure is reported, not raised
            log.exception("send failed")
            a.update(status="failed", error=str(e), updated=time.time())
            self._event("failed", action=_public(a))
        self._save()
        return a

    def _get(self, action_id):
        a = self.actions.get(action_id)
        if a is None:
            raise KeyError(f"no action {action_id}")
        return a

    def reply(self, seq, text):
        """Answer an inbox item using its own reply_to instructions."""
        item = next((i for i in self.inbox if i["seq"] == int(seq)), None)
        if item is None:
            raise KeyError(f"no inbox item {seq}")
        rt = item["reply_to"]
        return self.submit(item["platform"], rt["action"], text, target=rt["target"],
                           context={"in_reply_to": int(seq), "thread": item["thread"], "author": item["author"],
                                    "text": item["text"]})

    # --------------------------------------------------------------- incoming
    def ingest(self, platform, items):
        new = []
        with self.lock:
            seen = self.seen.setdefault(platform, deque(maxlen=5000))
            for it in items:
                if it.id in seen:
                    continue
                seen.append(it.id)
                self.seq += 1
                d = it.to_dict()
                d["seq"] = self.seq
                d["received"] = time.time()
                self.inbox.append(d)
                self._append("inbox.jsonl", d)
                new.append(d)
        for d in new:
            self._event("incoming", item=d)
            for fn in list(self._listeners):
                try:
                    fn(d)
                except Exception:  # noqa: BLE001
                    log.exception("listener failed")
        if new:
            self._save()
        return new

    def poll_once(self, platform):
        adapter = self.adapters[platform]
        state = self.poll_state.setdefault(platform, {})
        try:
            items = adapter.poll(state)
            self.platform_status[platform]["error"] = None
        except Exception as e:  # noqa: BLE001
            log.warning("poll %s failed: %s", platform, e)
            self.platform_status[platform]["error"] = str(e)
            return []
        if not state.get("_primed"):
            # First successful poll ever: whatever already exists is history, not new messages.
            state["_primed"] = True
            if not self.config.get("replay_backlog"):
                with self.lock:
                    seen = self.seen.setdefault(platform, deque(maxlen=5000))
                    seen.extend(it.id for it in items)
                self._save()
                return []
        return self.ingest(platform, items)

    def inbox_after(self, after=0, platform=None, limit=50):
        with self.lock:
            items = [i for i in self.inbox if i["seq"] > int(after) and (not platform or i["platform"] == platform)]
        items = items[:limit]
        return {"items": items, "next": items[-1]["seq"] if items else int(after)}

    def history(self, platform, thread, limit=30):
        """Incoming + sent messages for one conversation, oldest first (for building AI context)."""
        out = []
        with self.lock:
            for e in self.feed:
                if e["kind"] == "incoming" and e["item"]["platform"] == platform and e["item"]["thread"] == thread:
                    out.append({"role": "user", "author": e["item"]["author"], "text": e["item"]["text"], "ts": e["ts"]})
                elif e["kind"] == "sent" and e["action"]["platform"] == platform and \
                        (e["action"].get("context") or {}).get("thread") == thread:
                    out.append({"role": "assistant", "text": e["action"]["text"], "ts": e["ts"]})
        return out[-limit:]

    # ------------------------------------------------------------- lifecycle
    def check(self):
        for name, adapter in self.adapters.items():
            try:
                self.platform_status[name].update(account=adapter.whoami(), error=None)
            except Exception as e:  # noqa: BLE001
                self.platform_status[name].update(error=str(e))
        return self.platform_status

    def start(self):
        self._stop.clear()
        for name, adapter in self.adapters.items():
            if adapter.poll_interval <= 0:
                continue
            t = threading.Thread(target=self._poll_loop, args=(name, adapter.poll_interval), daemon=True,
                                 name=f"poll-{name}")
            t.start()
            self._threads.append(t)

    def stop(self):
        self._stop.set()

    def _poll_loop(self, name, interval):
        interval = int(self.config["platforms"].get(name, {}).get("poll_interval", interval)) \
            if self.config.get("platforms") else interval
        while not self._stop.is_set():
            self.poll_once(name)
            self._stop.wait(interval)

    def set_mode(self, mode):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.mode = mode
        self._event("mode", mode=mode)
        self._save()

    def set_paused(self, paused):
        self.paused = bool(paused)
        self._event("paused" if paused else "resumed")

    def on_incoming(self, fn):
        self._listeners.append(fn)

    def snapshot(self, feed_limit=150):
        with self.lock:
            pending = [_public(a) for a in sorted(self.actions.values(), key=lambda a: a["created"])
                       if a["status"] == "pending"]
            return {
                "mode": self.mode, "paused": self.paused,
                "platforms": {n: {"label": a.label, "actions": list(a.actions), **self.platform_status[n]}
                              for n, a in self.adapters.items()},
                "pending": pending,
                "feed": list(self.feed)[-feed_limit:],
            }


def _public(a):
    return {k: v for k, v in a.items() if k != "opts" or v}


class Responder:
    """Optional built-in auto-replier: drafts answers to incoming items with any OpenAI-compatible chat endpoint.

    Drafts go through the same queue, so review mode still holds them for approval.
    """

    def __init__(self, bridge, conf, http=None):
        self.bridge = bridge
        self.conf = conf
        self.http = http or Http("responder", timeout=conf.get("timeout", 120))
        self.platforms = set(conf.get("platforms") or [])
        self.kinds = set(conf.get("kinds") or ["dm", "mention", "comment", "reply"])
        self.pool = threading.Semaphore(int(conf.get("concurrency", 2)))

    def attach(self):
        self.bridge.on_incoming(lambda item: threading.Thread(target=self.handle, args=(item,), daemon=True).start())

    def handle(self, item):
        if self.platforms and item["platform"] not in self.platforms:
            return
        if item["kind"] not in self.kinds or self.bridge.paused:
            return
        with self.pool:
            try:
                text = self.draft(item)
            except Exception as e:  # noqa: BLE001
                self.bridge._event("responder_error", error=str(e), seq=item["seq"])
                return
            if not text:
                return
            rt = item["reply_to"]
            self.bridge.submit(item["platform"], rt["action"], text, target=rt["target"], source="responder",
                               context={"in_reply_to": item["seq"], "thread": item["thread"],
                                        "author": item["author"], "text": item["text"]})

    def draft(self, item):
        messages = [{"role": "system", "content": self.conf.get("system_prompt") or
                     "You are chatting on social media. Reply naturally and briefly."}]
        for h in self.bridge.history(item["platform"], item["thread"])[:-1]:
            content = h["text"] if h["role"] == "assistant" else f"{h['author']}: {h['text']}"
            messages.append({"role": h["role"], "content": content})
        messages.append({"role": "user", "content":
                         f"[{item['platform']} {item['kind']}] {item['author']}: {item['text']}"})
        headers = {"Content-Type": "application/json"}
        if self.conf.get("api_key"):
            headers["Authorization"] = f"Bearer {self.conf['api_key']}"
        body = {"model": self.conf.get("model", ""), "messages": messages}
        body.update(self.conf.get("params") or {})
        resp = self.http.post(self.conf["url"], json=body, headers=headers)
        return (resp["choices"][0]["message"]["content"] or "").strip()
