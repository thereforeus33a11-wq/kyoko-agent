import json

import pytest

from social_bridge.adapters.telegram import TelegramAdapter
from social_bridge.base import ADAPTERS, PlatformError
from tests.fakehttp import FakeHttp

TOKEN = "123456:ABC-def"
API = f"https://api.telegram.org/bot{TOKEN}"
ME = {"ok": True, "result": {"id": 123456, "is_bot": True, "first_name": "Kyo", "username": "kyobot"}}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


def make(**cfg):
    http = FakeHttp("telegram")
    http.add("POST", API + "/getMe", ME)
    return TelegramAdapter({"bot_token": TOKEN, **cfg}, http), http


def sent(mid=5, chat=None):
    return {"ok": True, "result": {"message_id": mid, "date": 1700000000,
                                   "chat": chat or {"id": -1001234, "type": "channel", "username": "chan"}}}


def test_registered_and_whoami():
    a, http = make()
    assert ADAPTERS["telegram"] is TelegramAdapter
    assert a.whoami() == "@kyobot"
    c = http.last("POST")
    assert c["url"] == API + "/getMe" and c["json"] == {}


def test_error_uses_description_and_hides_token():
    a, http = make()
    http.add("POST", API + "/sendMessage",
             (400, {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}))
    with pytest.raises(PlatformError) as e:
        a.dm("42", "hi")
    assert "chat not found" in str(e.value) and TOKEN not in str(e.value) and e.value.status == 400

    http.add("POST", API + "/sendPhoto", (403, "<html>forbidden</html>"))
    with pytest.raises(PlatformError) as e:
        a.post("x", target="@chan", media=["https://img.test/a.jpg"])
    assert TOKEN not in str(e.value) and "<token>" in str(e.value)


def test_ok_false_body_raises():
    a, http = make()
    http.add("POST", API + "/sendMessage", {"ok": False, "description": "Forbidden: bot was blocked by the user"})
    with pytest.raises(PlatformError, match="blocked"):
        a.dm("42", "hi")


def test_migrated_group_retries_with_new_chat_id():
    a, http = make()
    http.add("POST", API + "/sendMessage",
             (400, {"ok": False, "description": "Bad Request: group chat was upgraded to a supergroup chat",
                    "parameters": {"migrate_to_chat_id": -1009}}),
             sent(3, {"id": -1009, "type": "supergroup"}))
    r = a.post("hi", target="-55")
    assert [c["json"]["chat_id"] for c in http.calls if "sendMessage" in c["url"]] == [-55, -1009]
    assert r.id == "-1009:3" and r.url == "https://t.me/c/9/3"


# ------------------------------------------------------------------ post
def test_post_default_chat_title_and_link():
    a, http = make(default_chat="@chan")
    http.add("POST", API + "/sendMessage", sent(5))
    r = a.post("hello", title="News", link="https://x.y")
    c = http.last("POST", "sendMessage")
    assert c["json"] == {"chat_id": "@chan", "text": "News\n\nhello\n\nhttps://x.y",
                         "entities": [{"type": "bold", "offset": 0, "length": 4}]}
    assert r.id == "-1001234:5" and r.url == "https://t.me/chan/5"


@pytest.mark.parametrize("target,chat", [
    ("https://t.me/mychannel", "@mychannel"), ("t.me/s/mychannel", "@mychannel"), ("mychannel", "@mychannel"),
    ("-1001234", -1001234), ("https://t.me/c/1234/99", -1001234), ("telegram.me/mychannel", "@mychannel"),
])
def test_post_target_parsing(target, chat):
    a, http = make()
    http.add("POST", API + "/sendMessage", sent())
    a.post("hi", target=target)
    assert http.last("POST", "sendMessage")["json"]["chat_id"] == chat


def test_post_without_target_or_default_fails():
    a, _ = make()
    with pytest.raises(PlatformError, match="default_chat"):
        a.post("hi")
    with pytest.raises(PlatformError, match="invite"):
        a.post("hi", target="https://t.me/+AbCdEf")


@pytest.mark.parametrize("target", [
    "https://t.me/joinchat/AAAAAEkk2WdoDrB4-Q8-gg", "t.me/JoinChat/AAAAAEkk", "https://t.me/addstickers/MyPack",
    "https://t.me/share/url?url=https://x.y", "https://t.me/boost/mychannel", "https://t.me/addlist/abcDEF",
])
def test_post_rejects_reserved_tme_links(target):
    a, http = make()
    with pytest.raises(PlatformError, match="invite links can't be used"):
        a.post("hi", target=target)
    assert not any("sendMessage" in c["url"] for c in http.calls)


def test_long_text_is_split():
    a, http = make()
    http.add("POST", API + "/sendMessage", sent(1), sent(2), sent(3))
    r = a.post("a" * 3000 + "\n\n" + "b" * 3000, target="@chan")
    calls = [c["json"]["text"] for c in http.calls if "sendMessage" in c["url"]]
    assert calls == ["a" * 3000, "b" * 3000]
    assert r.id == "-1001234:1" and len(r.raw["messages"]) == 2
    # words: split on spaces; emoji count as two UTF-16 units
    text = ("word " * 900).strip() + " " + "\U0001F600" * 2100
    a.dm("1", text)
    calls = [c["json"]["text"] for c in http.calls if "sendMessage" in c["url"]][2:]
    assert all(len(t.encode("utf-16-le")) // 2 <= 4096 for t in calls)
    assert "".join(calls).replace(" ", "") == text.replace(" ", "") and len(calls) == 3


def test_post_single_local_photo_is_multipart(tmp_path):
    img = tmp_path / "pic.png"
    img.write_bytes(PNG)
    a, http = make()
    http.add("POST", API + "/sendPhoto", sent(7))
    r = a.post("look", target="@chan", title="T", media=[str(img)])
    c = http.last("POST", "sendPhoto")
    assert c["files"] == {"photo": ("pic.png", PNG, "image/png")}
    assert c["data"] == {"chat_id": "@chan", "caption": "T\n\nlook",
                         "caption_entities": json.dumps([{"type": "bold", "offset": 0, "length": 1}])}
    assert r.id == "-1001234:7"


def test_post_single_url_video_is_json():
    a, http = make()
    http.add("POST", API + "/sendVideo", sent(8))
    a.post("clip", target="@chan", media=["https://cdn.test/v/clip.mp4?sig=1"])
    c = http.last("POST", "sendVideo")
    assert c["json"] == {"chat_id": "@chan", "caption": "clip", "video": "https://cdn.test/v/clip.mp4?sig=1"}
    assert c["files"] is None


def test_post_album_mixes_upload_and_url(tmp_path):
    img = tmp_path / "a.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 8)
    a, http = make()
    http.add("POST", API + "/sendMediaGroup", {"ok": True, "result": [sent(10)["result"], sent(11)["result"]]})
    r = a.post("album", target="-1001234", media=[str(img), "https://img.test/b.png"])
    c = http.last("POST", "sendMediaGroup")
    assert c["data"]["chat_id"] == "-1001234"
    assert json.loads(c["data"]["media"]) == [
        {"type": "photo", "media": "attach://file0", "caption": "album"},
        {"type": "photo", "media": "https://img.test/b.png"}]
    assert list(c["files"]) == ["file0"] and c["files"]["file0"][0] == "a.jpg"
    assert r.id == "-1001234:10" and len(r.raw["messages"]) == 2


def test_album_validation():
    a, _ = make()
    with pytest.raises(PlatformError, match="mix photos and videos"):
        a.post("x", target="@chan", media=["https://a.test/1.jpg", "https://a.test/2.pdf"])
    with pytest.raises(PlatformError, match="at most 10"):
        a.post("x", target="@chan", media=[f"https://a.test/{i}.jpg" for i in range(11)])
    with pytest.raises(PlatformError, match="not found"):
        a.post("x", target="@chan", media=["/nope/missing.png"])


def test_long_caption_goes_in_follow_up_message():
    a, http = make()
    http.add("POST", API + "/sendPhoto", sent(20))
    http.add("POST", API + "/sendMessage", sent(21))
    r = a.post("y" * 1500, target="@chan", media=["https://img.test/p.jpg"])
    assert "caption" not in http.last("POST", "sendPhoto")["json"]
    assert http.last("POST", "sendMessage")["json"]["text"] == "y" * 1500
    assert r.id == "-1001234:20"


# ------------------------------------------------------------------ comment / dm
@pytest.mark.parametrize("target,chat,mid", [
    ("-1001234:45", -1001234, 45), ("@chan:45", "@chan", 45), ("chan/45", "@chan", 45),
    ("https://t.me/chan/45", "@chan", 45), ("https://t.me/c/1234/45", -1001234, 45),
    ("t.me/c/1234/9/45", -1001234, 45), ("https://t.me/chan/45?single", "@chan", 45),
    ("tg://privatepost?channel=1234&post=45", -1001234, 45), ("tg://resolve?domain=chan&post=45", "@chan", 45),
])
def test_comment_targets(target, chat, mid):
    a, http = make()
    http.add("POST", API + "/sendMessage", sent(46))
    r = a.comment(target, "reply")
    assert http.last("POST", "sendMessage")["json"] == {"chat_id": chat, "text": "reply",
                                                        "reply_parameters": {"message_id": mid}}
    assert r.id == "-1001234:46"


def test_comment_on_channel_post_comment_uses_linked_group():
    a, http = make()
    http.add("POST", API + "/getChat", {"ok": True, "result": {"id": -1001234, "linked_chat_id": -1005555}})
    http.add("POST", API + "/sendMessage", sent(8, {"id": -1005555, "type": "supergroup", "username": "chatgrp"}))
    r = a.comment("https://t.me/chan/45?comment=7", "thanks")
    assert http.last("POST", "getChat")["json"] == {"chat_id": "@chan"}
    assert http.last("POST", "sendMessage")["json"]["reply_parameters"] == {"message_id": 7}
    assert http.last("POST", "sendMessage")["json"]["chat_id"] == -1005555
    assert r.url == "https://t.me/chatgrp/8"


def test_comment_bad_target():
    a, _ = make()
    with pytest.raises(PlatformError):
        a.comment("https://t.me/chan", "x")
    with pytest.raises(PlatformError):
        a.comment("not a target", "x")
    for link in ("https://t.me/joinchat/12345", "https://t.me/addstickers/123"):
        with pytest.raises(PlatformError, match="can't read a message"):
            a.comment(link, "x")


def test_dm_by_id_and_learned_username():
    a, http = make()
    http.add("POST", API + "/sendMessage", sent(3, {"id": 777, "type": "private", "username": "bob"}))
    r = a.dm("777", "hey")
    assert http.last("POST", "sendMessage")["json"] == {"chat_id": 777, "text": "hey"}
    assert r.id == "777:3" and r.url == ""
    with pytest.raises(PlatformError, match="numeric id"):
        a.dm("@bob", "hey")
    http.add("POST", API + "/getUpdates", {"ok": True, "result": [
        {"update_id": 1, "message": {"message_id": 1, "date": 1, "chat": {"id": 777, "type": "private"},
                                     "from": {"id": 777, "username": "Bob"}, "text": "hi"}}]})
    state = {}
    a.poll(state)
    assert state["users"] == {"bob": 777}
    a.dm("@BOB", "again")
    a.dm("https://t.me/bob", "again")
    assert [c["json"]["chat_id"] for c in http.calls if "sendMessage" in c["url"]] == [777, 777, 777]


# ------------------------------------------------------------------ poll
def upd(uid, chat, mid, text=None, frm=None, key="message", **extra):
    msg = {"message_id": mid, "date": 1700000000 + uid, "chat": chat, **extra}
    if frm is not None:
        msg["from"] = frm
    if text is not None:
        msg["text"] = text
    return {"update_id": uid, key: msg}


BOB = {"id": 777, "is_bot": False, "first_name": "Bob", "username": "bob"}
AMY = {"id": 888, "is_bot": False, "first_name": "Amy", "last_name": "Lee"}
BOT = {"id": 123456, "is_bot": True, "first_name": "Kyo", "username": "kyobot"}
GROUP = {"id": -100500, "type": "supergroup", "title": "Group"}
PUB = {"id": -100600, "type": "supergroup", "title": "Pub", "username": "pubgrp"}
PRIV = {"id": 777, "type": "private", "first_name": "Bob", "username": "bob"}
CHANNEL = {"id": -1001234, "type": "channel", "title": "Chan", "username": "chan"}


def test_poll_kinds_threads_reply_to_and_cursor():
    a, http = make(default_chat="@chan")
    updates = [
        upd(10, PRIV, 1, "hello bot", BOB),
        upd(11, GROUP, 7, "hey @KyoBot what's up", AMY),
        upd(12, PUB, 8, "thanks", BOB, reply_to_message={"message_id": 5, "from": BOT, "chat": PUB},
            message_thread_id=5),
        upd(13, GROUP, 9, "unrelated chatter", BOB),
        upd(14, GROUP, 10, "my own message @kyobot", BOT),
        upd(15, GROUP, 11, "nice post", AMY, reply_to_message={
            "message_id": 3, "is_automatic_forward": True, "sender_chat": CHANNEL, "chat": GROUP},
            message_thread_id=3),
        upd(16, PRIV, 2, frm=BOB, photo=[{"file_id": "f"}], caption="look"),
        upd(17, GROUP, 7, "hey @kyobot (edited)", AMY, key="edited_message", edit_date=1700000100),
        upd(18, GROUP, 12, "email me@kyobot.com", AMY),
        upd(19, CHANNEL, 40, "shoutout @kyobot", key="channel_post", sender_chat=CHANNEL),
    ]
    http.add("POST", API + "/getUpdates", {"ok": True, "result": updates}, {"ok": True, "result": []})
    state = {}
    items = a.poll(state)
    body = http.last("POST", "getUpdates")["json"]
    assert body == {"timeout": 0, "limit": 100, "allowed_updates": ["message", "edited_message", "channel_post"]}
    assert [(i.kind, i.id) for i in items] == [
        ("dm", "777:1"), ("mention", "-100500:7"), ("reply", "-100600:8"), ("comment", "-100500:11"),
        ("dm", "777:2"), ("mention", "-100500:7:e1700000100"), ("mention", "-1001234:40")]
    dm, mention, reply, comment, photo, edited, chan = items
    assert dm.reply_to == {"action": "dm", "target": "777"} and dm.thread == "777" and dm.author == "@bob"
    assert dm.author_id == "777" and dm.ts == 1700000010.0 and dm.url == ""
    assert mention.reply_to == {"action": "comment", "target": "-100500:7"} and mention.thread == "-100500"
    assert mention.author == "Amy Lee" and mention.url == "https://t.me/c/500/7"
    assert reply.url == "https://t.me/pubgrp/8" and reply.thread == "-100600:5"
    assert comment.thread == "-100500:3" and comment.reply_to["target"] == "-100500:11"
    assert photo.text == "[photo] look"
    assert edited.ts == 1700000100.0
    assert chan.author == "@chan" and chan.url == "https://t.me/chan/40"
    assert state["offset"] == 20
    a.poll(state)
    assert http.last("POST", "getUpdates")["json"]["offset"] == 20


def test_comment_kind_needs_own_channel():
    a, http = make()
    other = {"id": -1009999, "type": "channel", "title": "Other"}
    http.add("POST", API + "/getUpdates", {"ok": True, "result": [
        upd(1, GROUP, 11, "nice post", AMY, reply_to_message={
            "message_id": 3, "is_automatic_forward": True, "sender_chat": other, "chat": GROUP})]})
    assert a.poll({}) == []
    # once the bot has posted to that channel, comments under its posts are picked up
    http.add("POST", API + "/sendMessage", sent(4, other))
    a.post("hi", target="-1009999")
    state = {}
    items = a.poll(state)
    assert [i.kind for i in items] == ["comment"] and "-1009999" in state["channels"]


def test_poll_pages_through_full_batches():
    a, http = make()
    first = [upd(i, PRIV, i, "m", BOB) for i in range(1, 101)]
    http.add("POST", API + "/getUpdates", {"ok": True, "result": first},
             {"ok": True, "result": [upd(101, PRIV, 101, "m", BOB)]})
    state = {}
    items = a.poll(state)
    assert len(items) == 101 and state["offset"] == 102
    offsets = [c["json"].get("offset") for c in http.calls if "getUpdates" in c["url"]]
    assert offsets == [None, 101]


def test_poll_keeps_read_updates_when_later_page_fails():
    a, http = make()
    first = [upd(i, PRIV, i, "m", BOB) for i in range(1, 101)]
    http.add("POST", API + "/getUpdates", {"ok": True, "result": first},
             (502, {"ok": False, "error_code": 502, "description": "Bad Gateway"}))
    state = {}
    items = a.poll(state)
    assert len(items) == 100 and [i.id for i in items][-1] == "777:100"
    assert state["offset"] == 101
    http.routes = [r for r in http.routes if not r[1].endswith("/getUpdates")]
    http.add("POST", API + "/getUpdates", {"ok": True, "result": [upd(101, PRIV, 101, "next", BOB)]})
    assert [i.id for i in a.poll(state)] == ["777:101"]
    assert http.last("POST", "getUpdates")["json"]["offset"] == 101 and state["offset"] == 102


def test_poll_first_page_error_raises_and_keeps_offset():
    a, http = make()
    http.add("POST", API + "/getUpdates", (502, {"ok": False, "error_code": 502, "description": "Bad Gateway"}))
    state = {"offset": 50}
    with pytest.raises(PlatformError, match="Bad Gateway") as e:
        a.poll(state)
    assert TOKEN not in str(e.value) and state["offset"] == 50


def test_poll_skips_malformed_update_without_losing_others():
    a, http = make()
    http.add("POST", API + "/getUpdates", {"ok": True, "result": [
        upd(1, PRIV, 1, "first", BOB),
        {"update_id": 2, "message": {"message_id": 2, "date": 1, "chat": {"type": "private"}, "text": "bad"}},
        upd(3, PRIV, 3, "third", BOB),
    ]})
    state = {}
    assert [i.id for i in a.poll(state)] == ["777:1", "777:3"] and state["offset"] == 4


def test_sticker_placeholder_and_text_mention():
    a, http = make()
    http.add("POST", API + "/getUpdates", {"ok": True, "result": [
        upd(1, PRIV, 1, frm=BOB, sticker={"emoji": "😀"}),
        upd(2, GROUP, 2, "Kyo hi", AMY, entities=[{"type": "text_mention", "offset": 0, "length": 3,
                                                    "user": BOT}]),
    ]})
    items = a.poll({})
    assert items[0].text == "[sticker 😀]" and items[1].kind == "mention"
