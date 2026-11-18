import base64

import pytest

from social_bridge.adapters.reddit import RedditAdapter
from social_bridge.base import ADAPTERS, PlatformError
from tests.fakehttp import FakeHttp

API = "https://oauth.reddit.com"
TOKEN = "https://www.reddit.com/api/v1/access_token"
S3 = "https://reddit-uploaded-media.s3-accelerate.amazonaws.com"
CFG = {"client_id": "cid", "client_secret": "sec", "username": "bot", "password": "pw"}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16


def make(**cfg):
    http = FakeHttp("reddit")
    http.add("POST", TOKEN, {"access_token": "tok", "token_type": "bearer", "expires_in": 86400, "scope": "*"})
    return RedditAdapter({**CFG, **cfg}, http), http


def ok(data=None):
    return {"json": {"errors": [], "data": data or {}}}


def listing(*children, after=None):
    return {"kind": "Listing", "data": {"after": after, "before": None, "children": list(children)}}


def test_registered():
    assert ADAPTERS["reddit"] is RedditAdapter


# ------------------------------------------------------------------ auth
def test_whoami_password_grant_headers_and_token_cache():
    a, http = make()
    http.add("GET", API + "/api/v1/me", {"name": "Bot"})
    assert a.whoami() == "u/Bot"
    tok = http.calls[0]
    assert tok["method"] == "POST" and tok["url"] == TOKEN
    assert tok["data"] == {"grant_type": "password", "username": "bot", "password": "pw"}
    assert tok["headers"]["Authorization"] == "Basic " + base64.b64encode(b"cid:sec").decode()
    me = http.last("GET", "/api/v1/me")
    assert me["headers"]["Authorization"] == "Bearer tok"
    assert me["headers"]["User-Agent"] == "python:social-bridge:v1.0 (by /u/bot)"
    a.whoami()
    assert sum(c["url"] == TOKEN for c in http.calls) == 1


def test_refresh_token_grant_and_custom_user_agent():
    a, http = make(refresh_token="rt", password="", user_agent="ua/1")
    http.add("GET", API + "/api/v1/me", {"name": "bot"})
    a.whoami()
    assert http.calls[0]["data"] == {"grant_type": "refresh_token", "refresh_token": "rt"}
    assert http.last("GET")["headers"]["User-Agent"] == "ua/1"


def test_token_error_is_platform_error():
    http = FakeHttp("reddit").add("POST", TOKEN, {"error": "invalid_grant"})
    a = RedditAdapter(CFG, http)
    with pytest.raises(PlatformError, match="invalid_grant"):
        a.whoami()


def test_401_refreshes_token_once_and_retries():
    http = FakeHttp("reddit")
    http.add("POST", TOKEN, {"access_token": "t1", "expires_in": 3600}, {"access_token": "t2", "expires_in": 3600})
    http.add("GET", API + "/api/v1/me", (401, {"message": "Unauthorized", "error": 401}), {"name": "bot"})
    a = RedditAdapter(CFG, http)
    assert a.whoami() == "u/bot"
    assert sum(c["url"] == TOKEN for c in http.calls) == 2
    assert http.last("GET")["headers"]["Authorization"] == "Bearer t2"


def test_expired_token_is_refreshed():
    a, http = make()
    http.add("GET", API + "/api/v1/me", {"name": "bot"})
    a.whoami()
    a._token_exp = 0
    a.whoami()
    assert sum(c["url"] == TOKEN for c in http.calls) == 2


# ------------------------------------------------------------------ post
def test_self_post_title_from_first_line():
    a, http = make()
    http.add("POST", API + "/api/submit", ok({"url": "https://www.reddit.com/r/test/comments/abc/hello/",
                                              "id": "abc", "name": "t3_abc"}))
    r = a.post("Hello world\n\nbody text", target="r/test")
    c = http.last("POST", "/api/submit")
    assert c["headers"]["Authorization"] == "Bearer tok"
    assert c["data"] == {"api_type": "json", "sr": "test", "title": "Hello world", "kind": "self",
                         "text": "body text", "sendreplies": "true", "resubmit": "true"}
    assert r.id == "t3_abc" and r.url == "https://www.reddit.com/r/test/comments/abc/hello/"


@pytest.mark.parametrize("target,sr", [
    ("r/Python", "Python"), ("/r/Python/", "Python"), ("Python", "Python"),
    ("https://www.reddit.com/r/Python/", "Python"), ("https://old.reddit.com/r/Python/comments/x/y/", "Python"),
    ("reddit.com/r/Python", "Python"), ("u/bot", "u_bot"), (None, "u_bot"), ("", "u_bot"),
])
def test_post_subreddit_targets(target, sr):
    a, http = make()
    http.add("POST", API + "/api/submit", ok({"name": "t3_x", "url": "u"}))
    a.post("t", target=target, title="T")
    assert http.last("POST", "/api/submit")["data"]["sr"] == sr


def test_link_post_with_title():
    a, http = make()
    http.add("POST", API + "/api/submit", ok({"name": "t3_l", "id": "l", "url": "u"}))
    r = a.post("", target="test", title="A link", link="https://example.com/a")
    d = http.last("POST", "/api/submit")["data"]
    assert d["kind"] == "link" and d["url"] == "https://example.com/a" and d["title"] == "A link"
    assert "text" not in d and r.id == "t3_l"


def test_post_errors_surface():
    a, http = make()
    http.add("POST", API + "/api/submit", {"json": {"errors": [
        ["SUBREDDIT_NOEXIST", "that subreddit doesn't exist", "sr"]], "data": {}}})
    with pytest.raises(PlatformError, match=r"SUBREDDIT_NOEXIST: that subreddit doesn't exist \[sr\]"):
        a.post("x", target="r/nope", title="t")


def test_bad_subreddit_target():
    a, _ = make()
    with pytest.raises(PlatformError):
        a.post("x", target="https://example.com/r", title="t")


def _lease(key, asset_id):
    return {"args": {"action": "//reddit-uploaded-media.s3-accelerate.amazonaws.com",
                     "fields": [{"name": "key", "value": key}, {"name": "policy", "value": "p"}]},
            "asset": {"asset_id": asset_id, "websocket_url": "wss://ws.example/x"}}


def test_single_image_upload_and_submit(tmp_path):
    img = tmp_path / "cat.png"
    img.write_bytes(PNG)
    a, http = make()
    http.add("POST", API + "/api/media/asset.json", _lease("k/cat.png", "as1"))
    http.add("POST", S3, (201, b"<PostResponse><Location>x</Location></PostResponse>"))
    http.add("POST", API + "/api/submit", ok({"user_submitted_page": "https://www.reddit.com/user/bot/submitted/",
                                              "websocket_url": "wss://ws.example/y"}))
    http.add("GET", API + "/user/bot/submitted", listing(), listing(
        {"kind": "t3", "data": {"name": "t3_old", "title": "Cat", "subreddit": "pics", "created_utc": 1.0}},
        {"kind": "t3", "data": {"name": "t3_img", "id": "img", "title": "Cat", "subreddit": "pics",
                                "created_utc": 4102444800.0, "permalink": "/r/pics/comments/img/cat/"}}))
    r = a.post("Cat\nsuch cat", target="r/pics", media=[str(img)])
    lease = http.last("POST", "/api/media/asset.json")
    assert lease["data"] == {"filepath": "cat.png", "mimetype": "image/png"}
    up = http.last("POST", S3)
    assert up["data"] == {"key": "k/cat.png", "policy": "p"} and up["files"]["file"] == ("cat.png", PNG, "image/png")
    assert "Authorization" not in up["headers"]
    d = http.last("POST", "/api/submit")["data"]
    assert d["kind"] == "image" and d["url"] == S3 + "/k/cat.png" and d["title"] == "Cat" and d["text"] == "such cat"
    assert r.id == "t3_img" and r.url == "https://www.reddit.com/r/pics/comments/img/cat/"


def test_gallery_from_urls():
    a, http = make()
    http.add("GET", "https://img.example/a.jpg", b"\xff\xd8\xff\xe0jpeg")
    http.add("GET", "https://img.example/b", PNG)
    http.add("POST", API + "/api/media/asset.json", _lease("k/a", "as1"), _lease("k/b", "as2"))
    http.add("POST", S3, (201, b""))
    http.add("POST", API + "/api/submit_gallery_post.json",
             ok({"url": "https://www.reddit.com/r/pics/comments/gal/two/", "id": "t3_gal"}))
    r = a.post("two pics", target="pics", title="Two", media=["https://img.example/a.jpg", "https://img.example/b"])
    leases = [c["data"] for c in http.calls if c["url"].endswith("/api/media/asset.json")]
    assert leases == [{"filepath": "a.jpg", "mimetype": "image/jpeg"}, {"filepath": "b.png", "mimetype": "image/png"}]
    body = http.last("POST", "submit_gallery_post")["json"]
    assert body["sr"] == "pics" and body["title"] == "Two" and body["api_type"] == "json" and body["text"] == "two pics"
    assert [i["media_id"] for i in body["items"]] == ["as1", "as2"]
    assert r.id == "t3_gal" and r.url.endswith("/comments/gal/two/")


def test_video_needs_poster_then_submits(tmp_path):
    vid, poster = tmp_path / "v.mp4", tmp_path / "p.png"
    vid.write_bytes(MP4)
    poster.write_bytes(PNG)
    a, http = make()
    with pytest.raises(PlatformError, match="poster"):
        a.post("x", target="r/v", title="V", media=[str(vid)])
    http.add("POST", API + "/api/media/asset.json", _lease("k/v", "a1"), _lease("k/p", "a2"))
    http.add("POST", S3, (201, b""))
    http.add("POST", API + "/api/submit", ok({"user_submitted_page": "https://www.reddit.com/user/bot/submitted/"}))
    http.add("GET", API + "/user/bot/submitted", listing())
    r = a.post("", target="r/v", title="V", media=[str(vid), str(poster)])
    d = http.last("POST", "/api/submit")["data"]
    assert d["kind"] == "video" and d["url"] == S3 + "/k/v" and d["video_poster_url"] == S3 + "/k/p"
    assert r.id == "" and r.url == "https://www.reddit.com/user/bot/submitted/"


def test_unsupported_media_type(tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.7")
    a, _ = make()
    with pytest.raises(PlatformError, match="unsupported media"):
        a.post("x", target="r/a", title="t", media=[str(f)])


# ------------------------------------------------------------------ comment
@pytest.mark.parametrize("target,thing", [
    ("t1_abc", "t1_abc"), ("T3_ABC", "t3_abc"), ("t4_m1", "t4_m1"), ("abc123", "t3_abc123"),
    ("https://www.reddit.com/r/test/comments/abc123/some_title/def456/", "t1_def456"),
    ("https://new.reddit.com/r/test/comments/abc123/comment/def456/?context=3", "t1_def456"),
    ("https://old.reddit.com/r/test/comments/abc123/some_title/", "t3_abc123"),
    ("https://sh.reddit.com/r/test/comments/abc123", "t3_abc123"),
    ("https://m.reddit.com/r/test/comments/abc123/t/?utm_source=share", "t3_abc123"),
    ("https://www.reddit.com/user/someone/comments/abc123/title/", "t3_abc123"),
    ("https://www.reddit.com/gallery/abc123", "t3_abc123"),
    ("https://redd.it/abc123", "t3_abc123"), ("redd.it/abc123", "t3_abc123"),
    ("reddit.com/comments/abc123", "t3_abc123"),
    ("/r/test/comments/abc123/x/def456/?context=3", "t1_def456"),
    ("https://www.reddit.com/message/messages/m1", "t4_m1"),
    ("https://www.reddit.com/r/test/comments/abc123/some_title/comment/def456/", "t1_def456"),
    ("https://www.reddit.com/r/test/comments/abc123/comment/", "t3_abc123"),
    ("https://www.reddit.com/r/test/comments/abc123/slug/comment/", "t3_abc123"),
])
def test_comment_target_parsing(target, thing):
    a, http = make()
    http.add("POST", API + "/api/comment", ok({"things": [{"kind": "t1", "data": {
        "id": "c9", "name": "t1_c9", "permalink": "/r/test/comments/abc123/x/c9/"}}]}))
    r = a.comment(target, "nice")
    c = http.last("POST", "/api/comment")
    assert c["data"] == {"api_type": "json", "thing_id": thing, "text": "nice"}
    assert c["headers"]["Authorization"] == "Bearer tok"
    assert r.id == "t1_c9" and r.url == "https://www.reddit.com/r/test/comments/abc123/x/c9/"


@pytest.mark.parametrize("target", ["https://example.com/comments/abc", "t2_abc", "not an id!"])
def test_comment_bad_target(target):
    a, _ = make()
    with pytest.raises(PlatformError):
        a.comment(target, "x")


def test_comment_share_link_is_resolved():
    a, http = make()
    http.add("GET", "https://www.reddit.com/r/test/s/AbCdEf12",
             b'<html><head><link rel="canonical" href="https://www.reddit.com/r/test/comments/p1/t/comment/c1/"/>')
    http.add("POST", API + "/api/comment", ok({"things": [{"kind": "t1", "data": {"name": "t1_c2"}}]}))
    a.comment("https://www.reddit.com/r/test/s/AbCdEf12", "hi")
    assert http.last("POST", "/api/comment")["data"]["thing_id"] == "t1_c1"


def test_comment_errors_surface():
    a, http = make()
    http.add("POST", API + "/api/comment", {"json": {"errors": [["THREAD_LOCKED", "comments are locked", None]]}})
    with pytest.raises(PlatformError, match="THREAD_LOCKED"):
        a.comment("t3_abc", "x")


# ------------------------------------------------------------------ dm
@pytest.mark.parametrize("target,to", [
    ("u/alice", "alice"), ("/u/alice", "alice"), ("alice", "alice"), ("@alice", "alice"),
    ("https://www.reddit.com/user/alice/", "alice"), ("reddit.com/u/alice", "alice"), ("r/test", "/r/test"),
])
def test_dm_compose_targets(target, to):
    a, http = make()
    text = "Hello there, this is a fairly long first line that goes past sixty characters\nsecond"
    http.add("POST", API + "/api/compose", ok())
    dest = "#test" if to.startswith("/r/") else to
    http.add("GET", API + "/message/sent", listing(
        {"kind": "t4", "data": {"id": "m0", "name": "t4_m0", "dest": dest, "body": "older"}},
        {"kind": "t4", "data": {"id": "m7", "name": "t4_m7", "dest": dest, "body": text}}))
    r = a.dm(target, text)
    c = http.last("POST", "/api/compose")
    assert c["data"] == {"api_type": "json", "to": to, "text": text,
                         "subject": "Hello there, this is a fairly long first line that goes..."}
    assert len(c["data"]["subject"]) <= 60
    assert r.id == "t4_m7" and r.url == "https://www.reddit.com/message/messages/m7"


def test_dm_reply_in_thread_with_t4():
    a, http = make()
    http.add("POST", API + "/api/comment", ok({"things": [{"kind": "t4", "data": {"id": "m2", "name": "t4_m2"}}]}))
    r = a.dm("t4_m1", "ok")
    assert http.last("POST", "/api/comment")["data"] == {"api_type": "json", "thing_id": "t4_m1", "text": "ok"}
    assert r.id == "t4_m2" and r.url == "https://www.reddit.com/message/messages/m2"
    a.dm("https://www.reddit.com/message/messages/m1", "again")
    assert http.last("POST", "/api/comment")["data"]["thing_id"] == "t4_m1"


def test_dm_sent_lookup_failure_still_returns_result():
    a, http = make()
    http.add("POST", API + "/api/compose", ok())
    http.add("GET", API + "/message/sent", (500, {"error": 500}))
    r = a.dm("alice", "hi")
    assert r.id == "" and http.last("POST", "/api/compose")["data"]["subject"] == "hi"


def test_dm_errors_surface_and_bad_target():
    a, http = make()
    http.add("POST", API + "/api/compose", {"json": {"errors": [["USER_DOESNT_EXIST", "that user doesn't exist", "to"]]}})
    with pytest.raises(PlatformError, match="USER_DOESNT_EXIST"):
        a.dm("ghost", "hi")
    with pytest.raises(PlatformError):
        a.dm("https://example.com/user/x", "hi")


# ------------------------------------------------------------------ poll
def _pm(i, author, created, subject="hello", first=None, new=True):
    return {"kind": "t4", "data": {"id": i, "name": "t4_" + i, "author": author, "author_fullname": "t2_" + author,
                                   "subject": subject, "body": "pm " + i, "created_utc": created, "dest": "bot",
                                   "first_message_name": first, "new": new, "was_comment": False}}


def _cm(i, typ, created, author="carol", new=True):
    subject = typ.replace("_", " ")
    return {"kind": "t1", "data": {"id": i, "name": "t1_" + i, "author": author, "body": "c " + i, "type": typ,
                                   "subject": subject, "created_utc": created, "new": new, "was_comment": True,
                                   "context": f"/r/test/comments/post1/title/{i}/?context=3", "parent_id": "t1_x"}}


def test_poll_kinds_threads_reply_to_and_cursor():
    a, http = make()
    first_page = listing(
        _cm("c3", "post_reply", 105.0), _pm("m2", "alice", 104.0, subject="re: hello", first="t4_m1"),
        _cm("c2", "comment_reply", 103.0, new=False), _cm("c1", "username_mention", 102.0),
        _pm("m9", "bot", 106.0), _pm("m1", "alice", 101.0))
    http.add("GET", API + "/message/inbox", first_page, listing(_cm("c4", "comment_reply", 110.0), _pm("m8", "bot", 109.0)))
    http.add("POST", API + "/api/read_message", {})
    state = {}
    items = a.poll(state)
    assert [i.id for i in items] == ["t4_m1", "t1_c1", "t1_c2", "t4_m2", "t1_c3"]
    assert [i.kind for i in items] == ["dm", "mention", "reply", "dm", "comment"]
    m1, c1, c2, m2, c3 = items
    assert m1.text == "hello\n\npm m1" and m2.text == "pm m2"
    assert m1.thread == m2.thread == "t4_m1"
    assert m1.reply_to == {"action": "dm", "target": "t4_m1"} and m2.reply_to == {"action": "dm", "target": "t4_m2"}
    assert m1.author == "u/alice" and m1.author_id == "t2_alice" and m1.ts == 101.0
    assert m1.url == "https://www.reddit.com/message/messages/m1"
    assert c1.thread == c2.thread == c3.thread == "t3_post1"
    assert c1.reply_to == {"action": "comment", "target": "t1_c1"}
    assert c1.url == "https://www.reddit.com/r/test/comments/post1/title/c1/?context=3"
    assert all(i.author != "u/bot" for i in items)
    assert state == {"since": 106.0}
    get = http.last("GET", "/message/inbox")
    assert get["params"]["mark"] == "false" and get["headers"]["Authorization"] == "Bearer tok"
    assert http.last("POST", "/api/read_message")["data"] == {"id": "t4_m1,t1_c1,t4_m2,t1_c3"}
    # every item the reply_to points at is accepted by this adapter
    assert a._thing(c1.reply_to["target"]) == "t1_c1" and a._thing(m1.reply_to["target"], kinds=("t4",)) == "t4_m1"

    items = a.poll(state)
    assert [i.id for i in items] == ["t1_c4"] and state["since"] == 110.0


T = 1_700_000_000.0


def test_poll_window_keeps_late_items_and_drops_stale():
    a, http = make()
    http.add("GET", API + "/message/inbox", listing(
        _cm("c9", "comment_reply", T + 20),
        _cm("late", "username_mention", T - 600),                 # mention delivered after the cursor moved
        _cm("seen", "comment_reply", T - 1800, new=False),        # inside the window: bridge de-duplicates it
        _cm("stale", "comment_reply", T - 7200, new=False),       # older than the window and already read
        _cm("approved", "post_reply", T - 86400),                 # approved from the spam queue days later
        _pm("mine", "bot", T - 300)))
    http.add("POST", API + "/api/read_message", {})
    state = {"since": T}
    items = a.poll(state)
    assert [i.id for i in items] == ["t1_approved", "t1_seen", "t1_late", "t1_c9"]
    assert [i.kind for i in items] == ["comment", "reply", "mention", "reply"]
    assert state["since"] == T + 20
    assert http.last("POST", "/api/read_message")["data"] == {"id": "t1_approved,t1_late,t1_c9"}


def test_poll_pagination_continues_past_new_items_and_stops_at_handled_ones():
    a, http = make()
    http.add("GET", API + "/message/inbox",
             listing(_cm("c5", "comment_reply", T + 50), _cm("c4", "username_mention", T - 5000), after="t1_c4"),
             listing(_cm("c3", "comment_reply", T + 10), _cm("c2", "comment_reply", T - 4000, new=False),
                     after="t1_c2"),
             listing(_cm("c1", "comment_reply", T - 9000)))
    http.add("POST", API + "/api/read_message", {})
    state = {"since": T}
    items = a.poll(state)
    assert [i.id for i in items] == ["t1_c4", "t1_c3", "t1_c5"] and state["since"] == T + 50
    inbox_calls = [c for c in http.calls if c["url"].endswith("/message/inbox")]
    assert len(inbox_calls) == 2 and inbox_calls[1]["params"]["after"] == "t1_c4"


def test_poll_mark_read_off_and_pagination():
    a, http = make(mark_read="false")
    http.add("GET", API + "/message/inbox",
             listing(_cm("c2", "comment_reply", T + 30), after="t1_c2"),
             listing(_cm("c1", "comment_reply", T - 100), _cm("c0", "comment_reply", T - 4000, new=False),
                     after="t1_c0"),
             listing(_cm("cx", "comment_reply", T - 9000)))
    state = {"since": T}
    items = a.poll(state)
    assert [i.id for i in items] == ["t1_c1", "t1_c2"] and state["since"] == T + 30
    inbox_calls = [c for c in http.calls if c["url"].endswith("/message/inbox")]
    assert len(inbox_calls) == 2 and inbox_calls[1]["params"]["after"] == "t1_c2"
    assert not any(c["url"].endswith("/api/read_message") for c in http.calls)


def test_poll_mark_read_off_does_not_trust_new_for_pagination():
    a, http = make(mark_read="0")
    http.add("GET", API + "/message/inbox",
             listing(_cm("c2", "comment_reply", T + 30), _cm("c1", "comment_reply", T - 4000), after="t1_c1"),
             listing(_cm("c0", "comment_reply", T - 9000)))
    items = a.poll({"since": T})
    assert [i.id for i in items] == ["t1_c1", "t1_c2"]
    assert len([c for c in http.calls if c["url"].endswith("/message/inbox")]) == 1


def test_config_keys_mark_optional_credentials():
    keys = RedditAdapter.config_keys
    assert not keys["client_id"].startswith("(optional)")
    for k in ("client_secret", "username", "password", "refresh_token", "user_agent", "mark_read"):
        assert keys[k].startswith("(optional)"), k
    assert "unless refresh_token" in keys["username"] and "unless refresh_token" in keys["password"]


def test_poll_uses_whoami_when_no_username():
    a, http = make(username="", refresh_token="rt")
    http.add("GET", API + "/api/v1/me", {"name": "Bot"})
    http.add("GET", API + "/message/inbox", listing(_pm("m1", "bot", 5.0), _pm("m2", "dan", 6.0, new=False)))
    items = a.poll({})
    assert [i.id for i in items] == ["t4_m2"]
