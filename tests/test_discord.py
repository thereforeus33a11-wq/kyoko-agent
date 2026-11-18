import json

import pytest

from social_bridge.adapters.discord import DiscordAdapter
from social_bridge.base import ADAPTERS, PlatformError
from tests.fakehttp import FakeHttp

API = "https://discord.com/api/v10"
BOT = {"id": "999", "username": "kyo", "discriminator": "0", "bot": True}
BOB = {"id": "42", "username": "bob", "global_name": "Bob"}
AMY = {"id": "43", "username": "amy"}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 8
BASE = (1700000000000 - 1420070400000) << 22  # snowflake for unix 1700000000.000


def sf(ms=0):
    return str(BASE + (ms << 22))


def make(**cfg):
    http = FakeHttp("discord")
    http.add("GET", API + "/users/@me", BOT)
    http.add("GET", API + "/channels/100", {"id": "100", "type": 0, "guild_id": "7"})
    http.add("GET", API + "/channels/300", {"id": "300", "type": 15, "guild_id": "7"})
    return DiscordAdapter({"bot_token": "tok", **cfg}, http), http


def msg(mid, author, content="", cid="100", type=0, **kw):
    return {"id": str(mid), "channel_id": cid, "author": author, "content": content, "type": type,
            "mentions": [], "attachments": [], **kw}


def test_registered_whoami_and_headers():
    a, http = make()
    assert ADAPTERS["discord"] is DiscordAdapter
    assert a.whoami() == "kyo"
    c = http.last("GET", "/users/@me")
    assert c["headers"]["Authorization"] == "Bot tok"
    assert c["headers"]["User-Agent"].startswith("DiscordBot (")


def test_api_version_and_legacy_discriminator():
    http = FakeHttp("discord").add("GET", "https://discord.com/api/v9/users/@me",
                                   {"id": "1", "username": "old", "discriminator": "1234"})
    assert DiscordAdapter({"bot_token": "t", "api_version": "v9"}, http).whoami() == "old#1234"


# ------------------------------------------------------------------ post
def test_post_title_link_and_result():
    a, http = make()
    http.add("POST", API + "/channels/100/messages", msg(555, BOT))
    r = a.post("hello", target="100", title="News", link="https://x.y")
    c = http.last("POST")
    assert c["url"] == API + "/channels/100/messages" and c["headers"]["Authorization"] == "Bot tok"
    assert c["json"] == {"content": "**News**\nhello\n\nhttps://x.y"}
    assert r.id == "100/555" and r.url == "https://discord.com/channels/7/100/555"


@pytest.mark.parametrize("target", [
    "https://discord.com/channels/7/100", "https://ptb.discord.com/channels/7/100/555",
    "discordapp.com/channels/7/100", "<#100>", "100", None,
])
def test_post_target_parsing(target):
    a, http = make(default_channel="100")
    http.add("POST", API + "/channels/100/messages", msg(555, BOT))
    assert a.post("hi", target=target).id == "100/555"


def test_post_needs_channel():
    a, _ = make()
    with pytest.raises(PlatformError, match="default_channel"):
        a.post("hi")
    with pytest.raises(PlatformError):
        a.post("hi", target="https://discord.com/invite/abc")


def test_post_media_multipart_local_and_url(tmp_path):
    img = tmp_path / "pic.png"
    img.write_bytes(PNG)
    a, http = make()
    http.add("GET", "https://cdn.test/image", JPG)
    http.add("POST", API + "/channels/100/messages", msg(556, BOT))
    r = a.post("look", target="100", media=[str(img), "https://cdn.test/image?w=1"])
    c = http.last("POST", "/channels/100/messages")
    assert json.loads(c["data"]["payload_json"]) == {
        "content": "look", "attachments": [{"id": 0, "filename": "pic.png"}, {"id": 1, "filename": "image.jpg"}]}
    assert c["files"] == {"files[0]": ("pic.png", PNG, "image/png"), "files[1]": ("image.jpg", JPG, "image/jpeg")}
    assert c["json"] is None and r.id == "100/556"


def test_media_limits():
    a, _ = make()
    with pytest.raises(PlatformError, match="at most 10"):
        a.post("x", target="100", media=[f"/tmp/{i}.png" for i in range(11)])
    with pytest.raises(PlatformError, match="not found"):
        a.post("x", target="100", media=["/nope/missing.png"])


def test_long_text_split_first_chunk_carries_attachments(tmp_path):
    img = tmp_path / "a.gif"
    img.write_bytes(b"GIF89a")
    a, http = make()
    http.add("POST", API + "/channels/100/messages", msg(1, BOT), msg(2, BOT))
    r = a.post("a" * 1500 + "\n" + "b" * 1500, target="100", media=[str(img)])
    calls = [c for c in http.calls if c["url"].endswith("/channels/100/messages")]
    assert json.loads(calls[0]["data"]["payload_json"])["content"] == "a" * 1500
    assert calls[1]["json"] == {"content": "b" * 1500} and calls[1]["files"] is None
    assert r.id == "100/1" and len(r.raw["messages"]) == 2


def test_forum_post_creates_thread(tmp_path):
    a, http = make()
    http.add("POST", API + "/channels/300/threads",
             {"id": "301", "type": 11, "message": {"id": "301", "channel_id": "301"}},
             {"id": "302", "type": 11, "message": {"id": "302", "channel_id": "302"}})
    r = a.post("body text", target="300", title="My Title")
    c = http.last("POST", "/threads")
    assert c["json"] == {"name": "My Title", "message": {"content": "body text"}}
    assert r.id == "301/301" and r.url == "https://discord.com/channels/7/301"
    img = tmp_path / "p.png"
    img.write_bytes(PNG)
    a.post("first line\nmore", target="300", media=[str(img)])
    c = http.last("POST", "/threads")
    assert json.loads(c["data"]["payload_json"]) == {
        "name": "first line", "message": {"content": "first line\nmore", "attachments": [{"id": 0, "filename": "p.png"}]}}
    assert list(c["files"]) == ["files[0]"]


# ------------------------------------------------------------------ comment
@pytest.mark.parametrize("target", [
    "100/555", "100-555", "100:555", "https://discord.com/channels/7/100/555",
    "https://canary.discord.com/channels/7/100/555?x=1", "https://discordapp.com/channels/7/100/555",
])
def test_comment_targets(target):
    a, http = make()
    http.add("POST", API + "/channels/100/messages", msg(560, BOT))
    r = a.comment(target, "reply")
    assert http.last("POST")["json"] == {"content": "reply", "message_reference": {
        "message_id": "555", "channel_id": "100", "fail_if_not_exists": False}}
    assert r.id == "100/560" and r.url == "https://discord.com/channels/7/100/560"


def test_comment_into_thread_without_reference():
    a, http = make()
    http.add("POST", API + "/channels/100/messages", msg(561, BOT))
    a.comment("https://discord.com/channels/7/100", "in thread")
    assert http.last("POST")["json"] == {"content": "in thread"}
    with pytest.raises(PlatformError):
        a.comment("not-a-target", "x")


def test_discord_error_message_surfaces():
    a, http = make()
    http.add("POST", API + "/channels/100/messages", (403, {"message": "Missing Permissions", "code": 50013}))
    with pytest.raises(PlatformError) as e:
        a.comment("100/555", "x")
    assert "Missing Permissions (code 50013)" in str(e.value) and e.value.status == 403


# ------------------------------------------------------------------ dm
DM_CHANNEL = {"id": "500", "type": 1, "recipients": [BOB]}


def test_dm_opens_channel_once_and_accepts_target_forms():
    a, http = make()
    http.add("POST", API + "/users/@me/channels", DM_CHANNEL)
    http.add("POST", API + "/channels/500/messages", msg(600, BOT, cid="500"))
    r = a.dm("42", "hi")
    assert http.last("POST", "/users/@me/channels")["json"] == {"recipient_id": "42"}
    assert http.last("POST", "/channels/500/messages")["json"] == {"content": "hi"}
    assert r.id == "500/600" and r.url == "https://discord.com/channels/@me/500/600"
    a.dm("<@!42>", "again")
    a.dm("https://discord.com/users/42", "again")
    a.dm("https://discord.com/channels/@me/500", "again")
    assert sum(c["url"].endswith("/users/@me/channels") for c in http.calls) == 1
    assert sum(c["url"].endswith("/channels/500/messages") for c in http.calls) == 4
    with pytest.raises(PlatformError, match="unknown Discord user"):
        a.dm("@stranger", "hi")


# ------------------------------------------------------------------ poll
def test_first_poll_starts_watch_channels_from_now_without_backlog():
    a, http = make(watch_channels="100, https://discord.com/channels/7/200")
    state = {}
    assert a.poll(state) == []
    assert set(state["after"]) == {"100", "200"} and all(v.isdigit() for v in state["after"].values())
    assert not any("/messages" in c["url"] for c in http.calls)


def test_poll_kinds_reply_to_cursor_and_own_filtered():
    a, http = make(watch_channels="100")
    state = {"after": {"100": sf(0)}}
    http.add("POST", API + "/users/@me/channels", DM_CHANNEL)
    http.add("POST", API + "/channels/500/messages", msg(sf(1), BOT, cid="500"))
    a.dm("42", "hello bob")
    http.add("GET", API + "/channels/100/messages", [
        msg(sf(9), BOT, "mine <@999>"),
        msg(sf(8), AMY, "", type=7),
        msg(sf(7), AMY, "random chatter"),
        msg(sf(6), BOB, "thanks!", type=19, referenced_message=msg(sf(0), BOT, "orig")),
        msg(sf(5), AMY, "<@999> hi <:wave:123> <@42>", mentions=[BOT, BOB]),
    ], [])
    http.add("GET", API + "/channels/500/messages", [msg(sf(3), BOB, "hey there", cid="500"),
                                                     msg(sf(1), BOT, "hello bob", cid="500")], [])
    items = a.poll(state)
    assert [i.kind for i in items] == ["dm", "mention", "reply"]
    dm, mention, reply = items
    assert dm.reply_to == {"action": "dm", "target": "42"} and dm.thread == "500" and dm.author == "bob"
    assert dm.url == f"https://discord.com/channels/@me/500/{sf(3)}" and dm.ts == 1700000000.003
    assert mention.text == "@kyo hi :wave: @bob" and mention.author_id == "43"
    assert mention.reply_to == {"action": "comment", "target": f"100/{sf(5)}"} and mention.thread == "100"
    assert mention.url == f"https://discord.com/channels/7/100/{sf(5)}"
    assert reply.reply_to == {"action": "comment", "target": f"100/{sf(6)}"}
    assert state["after"] == {"100": sf(9), "500": sf(3)} and state["dm_channels"] == {"500": "42"}
    gets = {c["url"]: c["params"] for c in http.calls if c["method"] == "GET" and "/messages" in c["url"]}
    assert gets[API + "/channels/500/messages"] == {"after": sf(1), "limit": 50}
    assert gets[API + "/channels/100/messages"] == {"after": sf(0), "limit": 50}
    a.poll(state)
    assert http.last("GET", "/channels/100/messages")["params"]["after"] == sf(9)
    # usernames seen while polling can be used as dm targets
    assert state["users"]["bob"] == "42"
    a.dm("@Bob", "hi again")
    assert http.last("POST", "/channels/500/messages")["json"] == {"content": "hi again"}


def test_poll_pages_full_batches():
    a, http = make(watch_channels="100")
    page = [msg(sf(i), AMY, "<@999> yo", mentions=[BOT]) for i in range(50, 0, -1)]
    http.add("GET", API + "/channels/100/messages", page, [msg(sf(51), AMY, "<@999> last")])
    state = {"after": {"100": sf(0)}}
    items = a.poll(state)
    assert len(items) == 51 and items[-1].id == sf(51) and state["after"]["100"] == sf(51)
    params = [c["params"]["after"] for c in http.calls if c["url"].endswith("/channels/100/messages")]
    assert params == [sf(0), sf(50)]


def test_poll_survives_out_of_range_timestamp_and_bad_message():
    a, http = make(watch_channels="100, 200")
    http.add("GET", API + "/channels/200", {"id": "200", "type": 0, "guild_id": "7"})
    http.add("GET", API + "/channels/100/messages", [
        msg(sf(3), AMY, "<@999> ok", mentions=[BOT]),
        msg(sf(2), BOB, "<@999> <t:99999999999999999999> <t:100000000000000000:R>", mentions=[BOT]),
        msg(sf(1), AMY, "<@999> meet <t:1700000000:R>", mentions=[BOT], attachments=["not-a-dict"]),
    ])
    http.add("GET", API + "/channels/200/messages", [msg(sf(4), BOB, "<@999> at <t:1700000000:F>", cid="200",
                                                         mentions=[BOT])])
    state = {"after": {"100": sf(0), "200": sf(0)}}
    items = a.poll(state)
    assert [(i.id, i.text) for i in items] == [
        (sf(2), "@kyo <t:99999999999999999999> <t:100000000000000000:R>"),
        (sf(3), "@kyo ok"),
        (sf(4), "@kyo at 2023-11-14 22:13 UTC"),
    ]
    assert state["after"] == {"100": sf(3), "200": sf(4)}


def test_poll_comments_on_own_forum_post_and_commented_channel():
    a, http = make()
    http.add("POST", API + "/channels/300/threads", {"id": sf(1), "type": 11, "message": {"id": sf(1)}})
    a.post("my post", target="300", title="T")
    http.add("POST", API + "/channels/100/messages", msg(sf(2), BOT))
    a.comment("100/1", "joining in")
    http.add("GET", API + f"/channels/{sf(1)}/messages", [
        msg(sf(4), AMY, "great post", cid=sf(1)), msg(sf(3), BOB, "agree", cid=sf(1))])
    http.add("GET", API + "/channels/100/messages", [
        msg(sf(5), AMY, "not for you"), msg(sf(6), BOB, "ok", type=19, referenced_message=msg(sf(2), BOT))])
    state = {}
    items = a.poll(state)
    assert [(i.kind, i.thread) for i in items] == [("comment", sf(1)), ("comment", sf(1)), ("reply", "100")]
    assert items[0].reply_to == {"action": "comment", "target": f"{sf(1)}/{sf(3)}"}
    assert items[0].url == f"https://discord.com/channels/7/{sf(1)}/{sf(3)}"
    assert state["channels"] == [sf(1), "100"] and state["threads"] == [sf(1)]
    assert http.last("GET", f"/channels/{sf(1)}/messages")["params"]["after"] == sf(1)


def test_poll_drops_deleted_dm_channel_and_raises_for_watch_errors():
    a, http = make(watch_channels="100")
    http.add("GET", API + "/channels/500/messages", (404, {"message": "Unknown Channel", "code": 10003}))
    state = {"after": {"500": "1", "100": "1"}, "dm_channels": {"500": "42"}}
    http.add("GET", API + "/channels/100/messages", [], (403, {"message": "Missing Access", "code": 50001}))
    assert a.poll(state) == []
    assert state["dm_channels"] == {} and "500" not in state["after"]
    with pytest.raises(PlatformError, match="Missing Access"):
        a.poll(state)


def test_dm_users_are_polled_from_start():
    a, http = make(dm_users="42")
    http.add("POST", API + "/users/@me/channels", DM_CHANNEL)
    state = {}
    a.poll(state)
    assert state["dm_channels"] == {"500": "42"} and state["after"]["500"].isdigit()
    http.add("GET", API + "/channels/500/messages", [msg(sf(3), BOB, "hi", cid="500",
                                                         attachments=[{"url": "https://cdn.test/f.png"}])])
    items = a.poll(state)
    assert items[0].kind == "dm" and items[0].text == "hi\nhttps://cdn.test/f.png"
    assert sum(c["url"].endswith("/users/@me/channels") for c in http.calls) == 1
