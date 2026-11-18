"""Local HTTP API for the AI + the oversight dashboard."""
import json
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .base import PlatformError
from .dashboard import DASHBOARD_HTML

log = logging.getLogger("social_bridge")


def tool_schemas(bridge=None):
    """OpenAI-style function/tool definitions. Hand these to the AI so it can call the bridge."""
    platforms = sorted(bridge.adapters) if bridge else []
    pl = {"type": "string", "description": "Platform name" + (f": one of {', '.join(platforms)}" if platforms else "")}
    if platforms:
        pl["enum"] = platforms
    targets = ""
    if bridge:
        lines = []
        for name, a in sorted(bridge.adapters.items()):
            for act, desc in (a.target_help or {}).items():
                lines.append(f"{name}.{act}: {desc}")
        targets = " Target formats: " + "; ".join(lines) if lines else ""

    def fn(name, desc, props, required):
        return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
            "type": "object", "properties": props, "required": required}}}

    return [
        fn("social_platforms", "List connected platforms, the account on each, and which actions each supports.",
           {}, []),
        fn("social_post", "Publish a new post." + targets, {
            "platform": pl,
            "text": {"type": "string", "description": "Post body"},
            "target": {"type": "string", "description": "Where to post (subreddit, page, channel...). Omit for own profile/feed."},
            "title": {"type": "string", "description": "Title, for platforms that need one (e.g. Reddit)"},
            "link": {"type": "string", "description": "Optional URL to attach"},
            "media": {"type": "array", "items": {"type": "string"}, "description": "Optional image file paths or URLs"},
        }, ["platform", "text"]),
        fn("social_comment", "Comment on / reply to a post or comment." + targets, {
            "platform": pl,
            "target": {"type": "string", "description": "ID or URL of the post/comment to reply to"},
            "text": {"type": "string"},
        }, ["platform", "target", "text"]),
        fn("social_dm", "Send a direct message to a user." + targets, {
            "platform": pl,
            "target": {"type": "string", "description": "User handle / ID / conversation ID"},
            "text": {"type": "string"},
        }, ["platform", "target", "text"]),
        fn("social_inbox", "Get new DMs, mentions, comments and replies. Pass the `next` value from the previous call as `after`.", {
            "after": {"type": "integer", "description": "Only items with seq greater than this", "default": 0},
            "platform": {"type": "string", "description": "Optional platform filter"},
        }, []),
        fn("social_reply", "Reply to an inbox item (uses the right action and target automatically).", {
            "seq": {"type": "integer", "description": "The inbox item's seq"},
            "text": {"type": "string"},
        }, ["seq", "text"]),
        fn("social_history", "Get the recent back-and-forth in one conversation thread.", {
            "platform": pl, "thread": {"type": "string", "description": "The inbox item's `thread` value"},
        }, ["platform", "thread"]),
        fn("social_action_status", "Check whether a queued post/comment/DM was approved, sent, rejected or failed.", {
            "id": {"type": "string"},
        }, ["id"]),
    ]


def call_tool(bridge, name, args):
    """Execute one tool call. Returns a JSON-able result."""
    args = args or {}
    if isinstance(args, str):
        args = json.loads(args or "{}")
    if name == "social_platforms":
        return bridge.snapshot(feed_limit=0)["platforms"]
    if name == "social_post":
        opts = {k: args[k] for k in ("title", "link", "media") if args.get(k)}
        return bridge.submit(args["platform"], "post", args.get("text", ""), target=args.get("target"), opts=opts)
    if name == "social_comment":
        return bridge.submit(args["platform"], "comment", args["text"], target=args["target"])
    if name == "social_dm":
        return bridge.submit(args["platform"], "dm", args["text"], target=args["target"])
    if name == "social_inbox":
        return bridge.inbox_after(args.get("after", 0), args.get("platform"))
    if name == "social_reply":
        return bridge.reply(args["seq"], args["text"])
    if name == "social_history":
        return bridge.history(args["platform"], args["thread"])
    if name == "social_action_status":
        return bridge._get(args["id"])
    raise KeyError(f"unknown tool {name}")


def make_handler(bridge, token=""):
    class Handler(BaseHTTPRequestHandler):
        server_version = "social-bridge/1.0"

        def log_message(self, fmt, *a):
            log.debug("%s %s", self.address_string(), fmt % a)

        # ---------------------------------------------------------- helpers
        def _send(self, code, payload, ctype="application/json"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authed(self):
            if not token:
                return True
            got = self.headers.get("Authorization", "")
            q = parse_qs(urlsplit(self.path).query)
            return got == f"Bearer {token}" or q.get("token", [""])[0] == token

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            return json.loads(raw or b"{}")

        def _run(self, fn):
            try:
                self._send(200, fn())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, {"error": str(e)})
            except PlatformError as e:
                self._send(422, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                log.exception("handler error")
                self._send(500, {"error": str(e)})

        # ---------------------------------------------------------- routes
        def do_GET(self):
            url = urlsplit(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path in ("/", "/index.html"):
                return self._send(200, DASHBOARD_HTML.encode(), "text/html; charset=utf-8")
            if url.path == "/health":
                return self._send(200, {"ok": True, "time": time.time()})
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            routes = {
                "/v1/state": lambda: bridge.snapshot(int(q.get("feed", 150))),
                "/v1/tools": lambda: tool_schemas(bridge),
                "/v1/platforms": lambda: call_tool(bridge, "social_platforms", {}),
                "/v1/inbox": lambda: bridge.inbox_after(int(q.get("after", 0)), q.get("platform"),
                                                        int(q.get("limit", 50))),
                "/v1/history": lambda: bridge.history(q["platform"], q["thread"]),
            }
            if url.path in routes:
                return self._run(routes[url.path])
            if url.path.startswith("/v1/actions/"):
                return self._run(lambda: bridge._get(url.path.rsplit("/", 1)[1]))
            self._send(404, {"error": "not found"})

        def do_POST(self):
            url = urlsplit(self.path)
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            try:
                body = self._body()
            except ValueError:
                return self._send(400, {"error": "invalid JSON"})
            p = url.path
            if p == "/v1/tool":
                return self._run(lambda: call_tool(bridge, body["name"], body.get("arguments")))
            if p == "/v1/actions":
                return self._run(lambda: bridge.submit(body["platform"], body["action"], body.get("text", ""),
                                                       target=body.get("target"), opts=body.get("opts"),
                                                       source=body.get("source", "agent")))
            if p == "/v1/reply":
                return self._run(lambda: bridge.reply(body["seq"], body["text"]))
            if p.startswith("/v1/actions/") and p.endswith("/approve"):
                aid = p.split("/")[3]
                return self._run(lambda: bridge.approve(aid, body.get("text")))
            if p.startswith("/v1/actions/") and p.endswith("/reject"):
                aid = p.split("/")[3]
                return self._run(lambda: bridge.reject(aid, body.get("reason", "")))
            if p == "/v1/mode":
                return self._run(lambda: (bridge.set_mode(body["mode"]), bridge.snapshot(0))[1])
            if p == "/v1/pause":
                return self._run(lambda: (bridge.set_paused(body.get("paused", True)), bridge.snapshot(0))[1])
            if p == "/v1/poll":
                return self._run(lambda: {n: bridge.poll_once(n) for n in
                                          ([body["platform"]] if body.get("platform") else list(bridge.adapters))})
            if p == "/v1/check":
                return self._run(bridge.check)
            self._send(404, {"error": "not found"})

    return Handler


def serve(bridge, host="127.0.0.1", port=8765, token=""):
    httpd = ThreadingHTTPServer((host, port), make_handler(bridge, token))
    log.info("dashboard + API on http://%s:%s", host, port)
    return httpd
