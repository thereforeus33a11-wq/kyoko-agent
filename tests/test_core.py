import json
import threading
import urllib.request

import pytest

from social_bridge.base import Adapter, Incoming, Result
from social_bridge.core import Bridge, Responder
from social_bridge.server import call_tool, serve, tool_schemas
from tests.fakehttp import FakeHttp


class Dummy(Adapter):
    name = "dummy"
    label = "Dummy"
    actions = ("post", "comment", "dm")
    poll_interval = 0
    target_help = {"dm": "username"}

    def __init__(self):
        super().__init__({})
        self.sent = []
        self.queue = []

    def whoami(self):
        return "me"

    def post(self, text, target=None, title=None, link=None, media=None):
        self.sent.append(("post", target, text))
        return Result(id="p1", url="https://d/p1")

    def comment(self, target, text):
        self.sent.append(("comment", target, text))
        return Result(id="c1")

    def dm(self, target, text):
        if target == "boom":
            raise RuntimeError("blocked")
        self.sent.append(("dm", target, text))
        return Result(id="d1")

    def poll(self, state):
        out, self.queue = self.queue, []
        return out


@pytest.fixture
def bridge(tmp_path):
    return Bridge({"mode": "review", "replay_backlog": True}, data_dir=tmp_path, adapters={"dummy": Dummy()})


def incoming(i, kind="dm"):
    return Incoming(platform="dummy", kind=kind, id=str(i), author="bob", text=f"hi {i}",
                    reply_to={"action": "dm", "target": "bob"}, thread="t-bob")


def test_review_mode_holds_until_approved(bridge):
    a = bridge.submit("dummy", "dm", "hello", target="bob")
    assert a["status"] == "pending" and bridge.adapters["dummy"].sent == []
    done = bridge.approve(a["id"], text="hello edited")
    assert done["status"] == "sent" and done["original_text"] == "hello"
    assert bridge.adapters["dummy"].sent == [("dm", "bob", "hello edited")]


def test_auto_mode_sends_immediately_and_pause_holds(bridge):
    bridge.set_mode("auto")
    assert bridge.submit("dummy", "post", "x")["status"] == "sent"
    bridge.set_paused(True)
    assert bridge.submit("dummy", "post", "y")["status"] == "pending"


def test_reject_and_failure(bridge):
    a = bridge.submit("dummy", "dm", "x", target="bob")
    assert bridge.reject(a["id"])["status"] == "rejected"
    with pytest.raises(ValueError):
        bridge.approve(a["id"])
    b = bridge.submit("dummy", "dm", "x", target="boom")
    assert bridge.approve(b["id"])["status"] == "failed"


def test_validation(bridge):
    from social_bridge.base import PlatformError
    with pytest.raises(PlatformError):
        bridge.submit("nope", "post", "x")
    with pytest.raises(PlatformError):
        bridge.submit("dummy", "dm", "x")  # missing target


def test_inbox_dedup_reply_and_history(bridge):
    d = bridge.adapters["dummy"]
    d.queue = [incoming(1), incoming(2)]
    assert len(bridge.poll_once("dummy")) == 2
    d.queue = [incoming(2), incoming(3)]
    assert [i["seq"] for i in bridge.poll_once("dummy")] == [3]
    page = bridge.inbox_after(1)
    assert [i["seq"] for i in page["items"]] == [2, 3] and page["next"] == 3
    a = bridge.reply(3, "yo")
    bridge.approve(a["id"])
    hist = bridge.history("dummy", "t-bob")
    assert hist[-1] == {"role": "assistant", "text": "yo", "ts": hist[-1]["ts"]}
    assert [h["text"] for h in hist[:3]] == ["hi 1", "hi 2", "hi 3"]


def test_state_persists(tmp_path):
    b1 = Bridge({"replay_backlog": True}, data_dir=tmp_path, adapters={"dummy": Dummy()})
    b1.adapters["dummy"].queue = [incoming(1)]
    b1.poll_once("dummy")
    a = b1.submit("dummy", "post", "persist me")
    b2 = Bridge({}, data_dir=tmp_path, adapters={"dummy": Dummy()})
    assert b2.actions[a["id"]]["text"] == "persist me"
    assert b2.inbox_after(0)["items"][0]["text"] == "hi 1"
    b2.adapters["dummy"].queue = [incoming(1)]
    assert b2.poll_once("dummy") == []  # seen ids survive restart


def test_tools(bridge):
    names = [t["function"]["name"] for t in tool_schemas(bridge)]
    assert "social_post" in names and "social_reply" in names
    a = call_tool(bridge, "social_dm", json.dumps({"platform": "dummy", "target": "bob", "text": "hey"}))
    assert call_tool(bridge, "social_action_status", {"id": a["id"]})["status"] == "pending"


def test_responder_drafts_reply_through_queue(bridge):
    http = FakeHttp("responder").add("POST", "http://llm/v1/chat/completions",
                                     {"choices": [{"message": {"content": "hey bob!"}}]})
    r = Responder(bridge, {"url": "http://llm/v1/chat/completions", "model": "m"}, http=http)
    bridge.adapters["dummy"].queue = [incoming(1)]
    item = bridge.poll_once("dummy")[0]
    r.handle(item)
    pending = bridge.snapshot()["pending"]
    assert pending[0]["text"] == "hey bob!" and pending[0]["target"] == "bob"
    assert http.calls[0]["json"]["messages"][-1]["content"].endswith("bob: hi 1")


def test_http_server_roundtrip(bridge):
    httpd = serve(bridge, "127.0.0.1", 0, token="sekret")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def req(path, body=None, token="sekret"):
        r = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                   headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read() or b"null") if "json" in resp.headers["Content-Type"] else resp.read()
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    assert req("/v1/state", token="bad")[0] == 401
    code, html = req("/")
    assert code == 200 and b"Social Bridge" in html
    code, a = req("/v1/tool", {"name": "social_post", "arguments": {"platform": "dummy", "text": "hi"}})
    assert code == 200 and a["status"] == "pending"
    assert req("/v1/state")[1]["pending"][0]["id"] == a["id"]
    code, done = req(f"/v1/actions/{a['id']}/approve", {"text": "hi!"})
    assert done["status"] == "sent"
    assert req("/v1/actions", {"platform": "dummy", "action": "fly", "text": "x"})[0] == 422
    httpd.shutdown()


def test_first_poll_skips_backlog(tmp_path):
    b = Bridge({}, data_dir=tmp_path, adapters={"dummy": Dummy()})
    b.adapters["dummy"].queue = [incoming(1), incoming(2)]
    assert b.poll_once("dummy") == []
    b.adapters["dummy"].queue = [incoming(2), incoming(3)]
    assert [i["id"] for i in b.poll_once("dummy")] == ["3"]
