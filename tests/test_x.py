import base64
import json
import os
import re
import stat
import time
import urllib.parse

import pytest

from social_bridge.adapters.x import XAdapter
from social_bridge.base import PlatformError, oauth1_header
from tests.fakehttp import FakeHttp

A = "https://api.x.com"
MEDIA = A + "/2/media/upload"
O1 = {"api_key": "ck", "api_secret": "cs", "access_token": "at", "access_token_secret": "ats"}
ME = {"data": {"id": "100", "username": "bot", "name": "Bot"}}


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    """Keep the default OAuth 2.0 token file (~/.social_bridge/...) out of the real home directory."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def make(cfg=None):
    http = FakeHttp("x")
    return XAdapter(dict(O1) if cfg is None else cfg, http), http


def check_sig(call, signed_params=None):
    """Recompute the OAuth 1.0a header with the same nonce/timestamp and compare."""
    h = call["headers"]["Authorization"]
    assert h.startswith("OAuth ")
    fields = {k: urllib.parse.unquote(v) for k, v in re.findall(r'(\w+)="([^"]*)"', h)}
    expected = oauth1_header(call["method"], call["url"], consumer_key="ck", consumer_secret="cs", token="at",
                             token_secret="ats", params=signed_params, nonce=fields["oauth_nonce"],
                             timestamp=int(fields["oauth_timestamp"]))
    assert h == expected


def tweet(i, author="200", reply_to_user=None, refs=None, conv="c1", text="hi &amp; bye"):
    t = {"id": str(i), "author_id": author, "text": text, "conversation_id": conv,
         "created_at": "2026-11-18T10:00:00.000Z"}
    if reply_to_user:
        t["in_reply_to_user_id"] = reply_to_user
    if refs:
        t["referenced_tweets"] = refs
    return t


# ------------------------------------------------------------------ whoami / auth
def test_whoami_signs_oauth1():
    a, http = make()
    http.add("GET", A + "/2/users/me", ME)
    assert a.whoami() == "@bot"
    c = http.last("GET")
    assert 'oauth_consumer_key="ck"' in c["headers"]["Authorization"]
    check_sig(c)


def test_missing_config():
    a, _ = make({"api_key": "ck"})
    with pytest.raises(PlatformError, match="missing config"):
        a.whoami()


def test_oauth2_refresh_confidential_client_and_retry_on_401(tmp_path):
    tf = tmp_path / "tok.json"
    cfg = {"client_id": "cid", "client_secret": "sec", "refresh_token": "r1", "oauth2_access_token": "old",
           "token_file": str(tf)}
    a, http = make(cfg)
    http.add("GET", A + "/2/users/me", (401, {"title": "Unauthorized"}), ME)
    http.add("POST", A + "/2/oauth2/token",
             {"token_type": "bearer", "access_token": "new", "refresh_token": "r2", "expires_in": 7200})
    assert a.whoami() == "@bot"
    calls = [(c["method"], c["url"]) for c in http.calls]
    assert calls == [("GET", A + "/2/users/me"), ("POST", A + "/2/oauth2/token"), ("GET", A + "/2/users/me")]
    assert http.calls[0]["headers"]["Authorization"] == "Bearer old"
    tok = http.calls[1]
    assert tok["data"] == {"grant_type": "refresh_token", "refresh_token": "r1"}
    assert tok["headers"]["Authorization"] == "Basic " + base64.b64encode(b"cid:sec").decode()
    assert http.calls[2]["headers"]["Authorization"] == "Bearer new"
    saved = json.loads(tf.read_text())
    assert saved["refresh_token"] == "r2" and saved["access_token"] == "new"
    # a new adapter instance picks the rotated tokens up from the file
    b, http2 = make(cfg)
    http2.add("GET", A + "/2/users/me", ME)
    b.whoami()
    assert http2.last("GET")["headers"]["Authorization"] == "Bearer new"


def empty_poll_routes(http):
    http.add("GET", A + "/2/users/me", ME)
    http.add("GET", A + "/2/users/100/mentions", {"meta": {"result_count": 0}})
    http.add("GET", A + "/2/dm_events", {"meta": {"result_count": 0}})


def test_oauth2_public_client_saves_rotated_tokens_to_default_file(_home):
    cfg = {"client_id": "cid", "refresh_token": "r1"}
    a, http = make(cfg)
    http.add("POST", A + "/2/oauth2/token", {"access_token": "t1", "refresh_token": "r2", "expires_in": 7200})
    http.add("GET", A + "/2/users/me", ME)
    assert a.whoami() == "@bot"            # a plain action (no poll) refreshes and saves
    assert http.calls[0]["data"] == {"grant_type": "refresh_token", "refresh_token": "r1", "client_id": "cid"}
    assert "Authorization" not in http.calls[0]["headers"]
    assert http.last("GET")["headers"]["Authorization"] == "Bearer t1"
    files = list((_home / ".social_bridge").glob("x_oauth2_*.json"))
    assert [f.name for f in files] == [f"x_oauth2_{a._o2_seed()}.json"]
    saved = json.loads(files[0].read_text())
    assert saved["access_token"] == "t1" and saved["refresh_token"] == "r2" and saved["expires_at"] > time.time()
    assert stat.S_IMODE(os.stat(files[0]).st_mode) == 0o600
    assert not list((_home / ".social_bridge").glob("*.tmp"))

    # token reused while valid; poll state carries only cursors
    empty_poll_routes(http)
    state = {}
    a.poll(state)
    assert len([c for c in http.calls if "oauth2/token" in c["url"]]) == 1
    assert "oauth2" not in state and all(not k.startswith("_") for k in state)

    # "restart": a new instance reads the file before its first request, with no poll in between
    b, http2 = make(cfg)
    http2.add("GET", A + "/2/users/me", ME)
    assert b.whoami() == "@bot"
    assert [c["url"] for c in http2.calls] == [A + "/2/users/me"]
    assert http2.calls[0]["headers"]["Authorization"] == "Bearer t1"

    # ... and when that token has expired it refreshes with the rotated refresh token, not the configured one
    saved["expires_at"] = int(time.time()) - 10
    files[0].write_text(json.dumps(saved))
    c, http3 = make(cfg)
    http3.add("POST", A + "/2/oauth2/token", {"access_token": "t2", "refresh_token": "r3", "expires_in": 7200})
    http3.add("POST", A + "/2/dm_conversations/with/42/messages", {"data": {"dm_event_id": "9"}})
    c.dm("42", "hi")
    assert http3.calls[0]["data"]["refresh_token"] == "r2"
    assert http3.last("POST", "/messages")["headers"]["Authorization"] == "Bearer t2"
    assert json.loads(files[0].read_text())["refresh_token"] == "r3"

    # a different configured refresh token (new login) ignores the saved tokens
    d, http4 = make({"client_id": "cid", "refresh_token": "fresh"})
    http4.add("POST", A + "/2/oauth2/token", {"access_token": "t9", "refresh_token": "r9", "expires_in": 7200})
    http4.add("GET", A + "/2/users/me", ME)
    d.whoami()
    assert http4.calls[0]["data"]["refresh_token"] == "fresh"
    assert len(list((_home / ".social_bridge").glob("x_oauth2_*.json"))) == 2


def test_oauth2_uses_tokens_rotated_by_another_process(tmp_path):
    tf = tmp_path / "tok.json"
    cfg = {"client_id": "cid", "refresh_token": "r1", "oauth2_access_token": "t0", "token_file": str(tf)}
    a, http = make(cfg)
    http.add("GET", A + "/2/users/me", (401, {"title": "Unauthorized"}), ME)
    # e.g. a CLI `send` refreshed while this process was running: r1 is used up, the file holds t5/r5
    seed = a._o2_seed()
    tf.write_text(json.dumps({"access_token": "t5", "refresh_token": "r5", "expires_at": int(time.time()) + 3600,
                              "seed": seed}))
    a._o2 = {"access_token": "t0", "refresh_token": "r1", "expires_at": 0, "seed": seed}
    assert a.whoami() == "@bot"
    assert [c["url"] for c in http.calls] == [A + "/2/users/me", A + "/2/users/me"]
    assert http.calls[1]["headers"]["Authorization"] == "Bearer t5"
    assert a._o2["refresh_token"] == "r5"

    # when the file has nothing newer, a 401 refreshes with the current refresh token
    http = a.http = FakeHttp("x")
    http.add("GET", A + "/2/users/me", (401, {"title": "Unauthorized"}), ME)
    http.add("POST", A + "/2/oauth2/token", {"access_token": "t6", "refresh_token": "r6", "expires_in": 7200})
    a.whoami()
    assert [c["method"] for c in http.calls] == ["GET", "POST", "GET"]
    assert http.calls[1]["data"]["refresh_token"] == "r5"
    assert http.calls[2]["headers"]["Authorization"] == "Bearer t6"
    assert json.loads(tf.read_text())["refresh_token"] == "r6"
    # another thread that still saw the old token gets the new one without a second refresh
    assert a._refresh("t5") == "t6"
    assert len([c for c in http.calls if c["method"] == "POST"]) == 1


def test_oauth2_token_file_not_writable(tmp_path):
    blocker = tmp_path / "afile"
    blocker.write_text("")
    a, http = make({"client_id": "cid", "refresh_token": "r1", "token_file": str(blocker / "tok.json")})
    http.add("POST", A + "/2/oauth2/token", {"access_token": "t1", "refresh_token": "r2", "expires_in": 7200})
    with pytest.raises(PlatformError, match="can't save the rotated OAuth 2.0 tokens.*token_file"):
        a.whoami()


# ------------------------------------------------------------------ post
def test_post_with_title_link_and_image(tmp_path):
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    a, http = make()
    http.add("POST", MEDIA, {"data": {"id": "m1", "media_key": "3_m1"}})
    http.add("POST", A + "/2/tweets", {"data": {"id": "555", "text": "x"}})
    r = a.post("hello", title="Big news", link="https://ex.am/ple", media=[str(img)])
    up = http.calls[0]
    assert up["method"] == "POST" and up["url"] == MEDIA
    assert up["data"] == {"media_category": "tweet_image"}
    assert up["files"]["media"][0] == "pic.png" and up["files"]["media"][2] == "image/png"
    check_sig(up)   # multipart body is not part of the signature
    tw = http.last("POST", "/2/tweets")
    assert tw["json"] == {"text": "Big news\n\nhello\n\nhttps://ex.am/ple", "media": {"media_ids": ["m1"]}}
    check_sig(tw)
    assert r.id == "555" and r.url == "https://x.com/i/web/status/555"


def test_post_media_from_url_and_url_uses_handle_after_whoami():
    a, http = make()
    http.add("GET", A + "/2/users/me", ME)
    http.add("GET", "https://cdn.test/a.jpg", b"\xff\xd8\xff\xe0data")
    http.add("POST", MEDIA, {"data": {"id": "m7"}})
    http.add("POST", A + "/2/tweets", {"data": {"id": "9"}})
    a.whoami()
    r = a.post("", media=["https://cdn.test/a.jpg?x=1"])
    dl = http.last("GET", "cdn.test")
    assert "Authorization" not in dl["headers"]
    assert http.last("POST", "media")["files"]["media"][2] == "image/jpeg"
    assert http.last("POST", "/2/tweets")["json"] == {"media": {"media_ids": ["m7"]}}
    assert r.url == "https://x.com/bot/status/9"


def test_post_video_chunked_upload_with_processing(tmp_path):
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"v" * 8)
    a, http = make()
    a.CHUNK = 10
    slept = []
    http.sleep = slept.append
    http.add("POST", MEDIA + "/initialize", {"data": {"id": "77", "media_key": "7_77"}})
    http.add("POST", MEDIA + "/77/append", {})
    http.add("POST", MEDIA + "/77/finalize",
             {"data": {"id": "77", "processing_info": {"state": "pending", "check_after_secs": 2}}})
    http.add("GET", MEDIA, {"data": {"id": "77", "processing_info": {"state": "in_progress", "check_after_secs": 3}}},
             {"data": {"id": "77", "processing_info": {"state": "succeeded"}}})
    http.add("POST", A + "/2/tweets", {"data": {"id": "1"}})
    a.post("watch", media=[str(vid)])
    init = http.last("POST", "/initialize")
    assert init["json"] == {"media_type": "video/mp4", "total_bytes": 20, "media_category": "tweet_video"}
    appends = [c for c in http.calls if c["url"].endswith("/append")]
    assert [c["data"] for c in appends] == [{"segment_index": "0"}, {"segment_index": "1"}]
    assert appends[0]["files"]["media"][1] == b"\x00\x00\x00\x18ftypmp"
    status = http.last("GET", "media/upload")
    assert status["params"] == {"command": "STATUS", "media_id": "77"}
    check_sig(status, status["params"])
    assert slept == [2, 3]
    assert http.last("POST", "/2/tweets")["json"]["media"] == {"media_ids": ["77"]}


def test_post_media_processing_failure_and_too_many_media():
    a, http = make()
    with pytest.raises(PlatformError, match="at most 4"):
        a.post("x", media=["a", "b", "c", "d", "e"])
    http.add("GET", "https://cdn.test/a.gif", b"GIF89a....")
    http.add("POST", MEDIA + "/initialize", {"data": {"id": "5"}})
    http.add("POST", MEDIA + "/5/append", {})
    http.add("POST", MEDIA + "/5/finalize", {"data": {"processing_info": {"state": "failed", "error": {"code": 1}}}})
    with pytest.raises(PlatformError, match="processing failed"):
        a.post("x", media=["https://cdn.test/a.gif"])
    assert http.last("POST", "/initialize")["json"]["media_category"] == "tweet_gif"


@pytest.mark.parametrize("target,extra", [
    ("1234", {"community_id": "1234"}),
    ("https://x.com/i/communities/1500000000000000000", {"community_id": "1500000000000000000"}),
    ("https://twitter.com/jack/status/20?s=20", {"quote_tweet_id": "20"}),
])
def test_post_targets(target, extra):
    a, http = make()
    http.add("POST", A + "/2/tweets", {"data": {"id": "1"}})
    a.post("t", target=target)
    assert http.last("POST")["json"] == {"text": "t", **extra}


def test_post_bad_target():
    a, _ = make()
    with pytest.raises(PlatformError):
        a.post("t", target="r/python")


# ------------------------------------------------------------------ comment
@pytest.mark.parametrize("target", [
    "1850000000000000001",
    "https://x.com/someone/status/1850000000000000001",
    "https://twitter.com/someone/status/1850000000000000001?s=46&t=abc",
    "https://mobile.twitter.com/someone/status/1850000000000000001/photo/1",
    "x.com/i/web/status/1850000000000000001",
    "https://x.com/i/status/1850000000000000001",
])
def test_comment_targets(target):
    a, http = make()
    http.add("POST", A + "/2/tweets", {"data": {"id": "2"}})
    r = a.comment(target, "reply text")
    c = http.last("POST")
    assert c["json"] == {"text": "reply text", "reply": {"in_reply_to_tweet_id": "1850000000000000001"}}
    assert c["headers"]["Authorization"].startswith("OAuth ")
    check_sig(c)
    assert r.id == "2"


def test_comment_bad_target():
    a, _ = make()
    with pytest.raises(PlatformError):
        a.comment("https://x.com/someone", "hi")


# ------------------------------------------------------------------ dm
@pytest.mark.parametrize("target,lookup", [
    ("@amy", "amy"), ("amy", "amy"), ("https://x.com/amy", "amy"), ("https://twitter.com/@amy/", "amy"),
    ("x.com/Amy?lang=en", "Amy"), ("https://x.com/intent/user?screen_name=amy", "amy"),
])
def test_dm_resolves_usernames(target, lookup):
    a, http = make()
    http.add("GET", "re:/2/users/by/username/", {"data": {"id": "42", "username": "amy"}})
    http.add("POST", A + "/2/dm_conversations/with/42/messages",
             {"data": {"dm_conversation_id": "42-100", "dm_event_id": "900"}})
    r = a.dm(target, "hey")
    assert http.calls[0]["url"] == f"{A}/2/users/by/username/{lookup}"
    c = http.last("POST")
    assert c["json"] == {"text": "hey"}
    check_sig(c)
    assert r.id == "900" and r.url == "https://x.com/messages/42-100"
    a.dm(target, "again")
    assert len([x for x in http.calls if "by/username" in x["url"]]) == 1   # cached


@pytest.mark.parametrize("target,path", [
    ("42", "/2/dm_conversations/with/42/messages"),
    ("https://x.com/messages/compose?recipient_id=42", "/2/dm_conversations/with/42/messages"),
    ("https://x.com/i/user/42", "/2/dm_conversations/with/42/messages"),
    ("42-100", "/2/dm_conversations/42-100/messages"),
    ("https://x.com/messages/42-100", "/2/dm_conversations/42-100/messages"),
    ("https://x.com/messages/1900000000000000000", "/2/dm_conversations/1900000000000000000/messages"),
    ("https://x.com/i/chat/42-100", "/2/dm_conversations/42-100/messages"),
    ("conversation:1900000000000000000", "/2/dm_conversations/1900000000000000000/messages"),
    ("Conversation: 42-100", "/2/dm_conversations/42-100/messages"),
    ("1900000000000000000", "/2/dm_conversations/with/1900000000000000000/messages"),
])
def test_dm_ids_and_conversations(target, path):
    a, http = make()
    http.add("POST", "re:/2/dm_conversations/", {"data": {"dm_conversation_id": "c", "dm_event_id": "1"}})
    a.dm(target, "yo")
    assert [c["url"] for c in http.calls] == [A + path]


def test_dm_unknown_user():
    a, http = make()
    http.add("GET", "re:/2/users/by/username/", {"errors": [{"title": "Not Found Error"}]})
    with pytest.raises(PlatformError, match="not found"):
        a.dm("@ghost", "hi")
    with pytest.raises(PlatformError):
        a.dm("not a user!", "hi")


# ------------------------------------------------------------------ poll
def mentions_page(tweets, users, ref_tweets=(), newest=None, next_token=None):
    meta = {"result_count": len(tweets)}
    if newest:
        meta["newest_id"] = newest
    if next_token:
        meta["next_token"] = next_token
    return {"data": tweets, "includes": {"users": users, "tweets": list(ref_tweets)}, "meta": meta}


def test_poll_mentions_and_dms():
    a, http = make()
    http.add("GET", A + "/2/users/me", ME)
    users = [{"id": "200", "username": "bob"}, {"id": "100", "username": "bot"}]
    own_post = {"id": "10", "author_id": "100", "text": "my post"}
    own_reply = {"id": "11", "author_id": "100", "text": "my reply",
                 "referenced_tweets": [{"type": "replied_to", "id": "5"}]}
    page = mentions_page([
        tweet(23, reply_to_user="100", refs=[{"type": "replied_to", "id": "11"}], conv="c2"),
        tweet(22, reply_to_user="100", refs=[{"type": "replied_to", "id": "10"}], conv="10"),
        tweet(21, author="100", text="self mention"),
        tweet(20, text="@bot look"),
    ], users, [own_post, own_reply], newest="23")
    http.add("GET", A + "/2/users/100/mentions", page, mentions_page([], []))
    dms = {"data": [
        {"id": "502", "event_type": "MessageCreate", "text": "group hi", "sender_id": "300",
         "dm_conversation_id": "1900000000000000000", "created_at": "2026-11-18T10:05:00.000Z"},
        {"id": "501", "event_type": "MessageCreate", "text": "my own dm", "sender_id": "100",
         "dm_conversation_id": "100-200", "created_at": "2026-11-18T10:04:00.000Z"},
        {"id": "500", "event_type": "MessageCreate", "text": "hello &lt;3", "sender_id": "200",
         "dm_conversation_id": "100-200", "created_at": "2026-11-18T10:03:00.000Z"},
    ], "includes": {"users": [{"id": "200", "username": "bob"}, {"id": "300", "username": "cat"}]},
        "meta": {"result_count": 3}}
    http.add("GET", A + "/2/dm_events", dms)
    state = {}
    items = a.poll(state)
    by_id = {i.id: i for i in items}
    assert set(by_id) == {"20", "22", "23", "500", "502"}
    assert by_id["20"].kind == "mention" and by_id["22"].kind == "comment" and by_id["23"].kind == "reply"
    m = by_id["22"]
    assert m.author == "@bob" and m.author_id == "200" and m.text == "hi & bye" and m.thread == "10"
    assert m.url == "https://x.com/bob/status/22" and m.ts == 1794996000.0
    assert m.reply_to == {"action": "comment", "target": "22"}
    d = by_id["500"]
    assert d.kind == "dm" and d.author == "@bob" and d.text == "hello <3" and d.thread == "100-200"
    assert d.reply_to == {"action": "dm", "target": "200"} and d.url == "https://x.com/messages/100-200"
    g = by_id["502"]
    assert g.reply_to == {"action": "dm", "target": "https://x.com/messages/1900000000000000000"}
    assert a._dm_path(g.reply_to["target"]) == "/2/dm_conversations/1900000000000000000/messages"
    assert state == {"mentions_since_id": "23", "dm_since_id": "502"}
    json.dumps(state)

    mreq = http.last("GET", "/mentions")
    assert mreq["params"]["expansions"] == "author_id,referenced_tweets.id"
    assert "since_id" not in mreq["params"]
    check_sig(mreq, mreq["params"])
    dreq = http.last("GET", "/dm_events")
    assert dreq["params"]["event_types"] == "MessageCreate" and dreq["params"]["expansions"] == "sender_id"
    check_sig(dreq, dreq["params"])

    # second poll: cursor sent, nothing new, DMs at/below the cursor ignored
    assert a.poll(state) == []
    assert http.last("GET", "/mentions")["params"]["since_id"] == "23"
    assert state == {"mentions_since_id": "23", "dm_since_id": "502"}
    assert len([c for c in http.calls if c["url"].endswith("/users/me")]) == 1


def test_poll_paginates_new_items_until_cursor():
    a, http = make()
    http.add("GET", A + "/2/users/me", ME)
    users = [{"id": "200", "username": "bob"}]
    http.add("GET", A + "/2/users/100/mentions",
             mentions_page([tweet(40), tweet(39)], users, newest="40", next_token="p2"),
             mentions_page([tweet(38)], users, newest="38"))
    http.add("GET", A + "/2/dm_events",
             {"data": [{"id": "610", "text": "a", "sender_id": "200", "dm_conversation_id": "100-200"}],
              "meta": {"next_token": "d2"}},
             {"data": [{"id": "605", "text": "b", "sender_id": "200", "dm_conversation_id": "100-200"},
                       {"id": "600", "text": "old", "sender_id": "200", "dm_conversation_id": "100-200"}],
              "meta": {"next_token": "d3"}})
    state = {"mentions_since_id": "30", "dm_since_id": "600"}
    items = a.poll(state)
    assert sorted(i.id for i in items) == ["38", "39", "40", "605", "610"]
    mcalls = [c for c in http.calls if "/mentions" in c["url"]]
    assert [c["params"].get("pagination_token") for c in mcalls] == [None, "p2"]
    assert all(c["params"]["since_id"] == "30" for c in mcalls)
    dcalls = [c for c in http.calls if "/dm_events" in c["url"]]
    assert [c["params"].get("pagination_token") for c in dcalls] == [None, "d2"]
    assert state == {"mentions_since_id": "40", "dm_since_id": "610"}


def test_poll_failure_keeps_cursors_and_poll_dms_off():
    a, http = make()
    http.add("GET", A + "/2/users/me", ME)
    http.add("GET", A + "/2/users/100/mentions", mentions_page([tweet(50)], [], newest="50"))
    http.add("GET", A + "/2/dm_events", (403, {"title": "Forbidden"}))
    state = {"mentions_since_id": "1"}
    with pytest.raises(PlatformError):
        a.poll(state)
    assert state == {"mentions_since_id": "1"}

    b, http2 = make(dict(O1, poll_dms="false"))
    http2.add("GET", A + "/2/users/me", ME)
    http2.add("GET", A + "/2/users/100/mentions", mentions_page([tweet(50)], [], newest="50"))
    items = b.poll({})
    assert [i.id for i in items] == ["50"] and items[0].author == "200"
    assert items[0].url == "https://x.com/i/web/status/50"
    assert not [c for c in http2.calls if "dm_events" in c["url"]]
