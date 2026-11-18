import pytest

from social_bridge.adapters.lemmy import LemmyAdapter
from social_bridge.base import PlatformError
from tests.fakehttp import FakeHttp

B = "https://lemmy.test"
A = B + "/api/v3"
SITE = {"site_view": {}, "my_user": {"local_user_view": {"person": {
    "id": 1, "name": "me", "actor_id": B + "/u/me", "local": True}}}}


def make(**extra):
    http = FakeHttp("lemmy")
    cfg = {"instance": "lemmy.test/", "username": "me", "password": "pw", **extra}
    http.add("POST", A + "/user/login", {"jwt": "J1", "registration_created": False, "verify_email_sent": False})
    return LemmyAdapter(cfg, http), http


# ------------------------------------------------------------------ auth / whoami
def test_login_and_whoami():
    a, http = make()
    http.add("GET", A + "/site", SITE)
    assert a.whoami() == "me@lemmy.test"
    login, site = http.calls
    assert login["json"] == {"username_or_email": "me", "password": "pw"}
    assert site["headers"]["Authorization"] == "Bearer J1"


def test_totp_rfc6238_vector_and_login_body():
    # RFC 6238 SHA1 secret "12345678901234567890" at t=59 -> 94287082 (6 digits: 287082)
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert LemmyAdapter._totp(secret, 59) == "287082"
    assert LemmyAdapter._totp(secret.lower()[:16] + " " + secret.lower()[16:], 1111111109) == "081804"
    a, http = make(totp_secret=secret)
    http.add("GET", A + "/site", SITE)
    a.whoami()
    body = http.calls[0]["json"]
    assert len(body["totp_2fa_token"]) == 6 and body["totp_2fa_token"].isdigit()


def test_relogin_once_on_expired_token():
    a, http = make()
    http.routes[0][2] = [{"jwt": "J1"}, {"jwt": "J2"}]
    http.add("GET", A + "/site", (401, {"error": "not_logged_in"}), SITE)
    assert a.whoami() == "me@lemmy.test"
    assert [c["url"] for c in http.calls] == [A + "/user/login", A + "/site", A + "/user/login", A + "/site"]
    assert http.calls[-1]["headers"]["Authorization"] == "Bearer J2"


def test_relogin_on_not_logged_in_400_and_gives_up_after_one_retry():
    a, http = make()
    http.add("GET", A + "/site", (400, {"error": "not_logged_in"}))
    with pytest.raises(PlatformError):
        a.whoami()
    assert len([c for c in http.calls if c["url"].endswith("/user/login")]) == 2


def test_login_without_jwt_raises():
    a, http = make()
    http.routes[0][2] = [{"jwt": None, "verify_email_sent": True}]
    with pytest.raises(PlatformError, match="no token"):
        a.whoami()


# ------------------------------------------------------------------ post
def community(cid):
    return {"community_view": {"community": {"id": cid, "name": "x"}}}


def created_post(pid=42):
    return {"post_view": {"post": {"id": pid, "ap_id": f"{B}/post/{pid}"}}}


@pytest.mark.parametrize("target,query", [
    ("!tech@lemmy.test", "tech"),
    ("c/tech", "tech"),
    ("tech", "tech"),
    ("https://lemmy.test/c/tech", "tech"),
    ("c/news@other.org", "news@other.org"),
    ("!news@Other.org", "news@other.org"),
    ("https://other.org/c/news", "news@other.org"),
    ("https://lemmy.test/c/news@other.org", "news@other.org"),
    ("https://kbin.test/m/news", "news@kbin.test"),
])
def test_post_community_targets(target, query):
    a, http = make()
    http.add("GET", A + "/community", community(7))
    http.add("POST", A + "/post", created_post())
    a.post("hello", target=target, title="T")
    assert http.last("GET", "/community")["params"] == {"name": query}
    assert http.last("POST", "/post")["json"]["community_id"] == 7


def test_post_numeric_community_and_body_fields():
    a, http = make()
    http.add("POST", A + "/post", created_post(42))
    r = a.post("Title line\nbody text\n\nmore", target="12", link="https://example.com/a")
    c = http.last("POST", "/post")
    assert c["json"] == {"name": "Title line", "community_id": 12, "url": "https://example.com/a",
                         "body": "body text\n\nmore"}
    assert c["headers"]["Authorization"] == "Bearer J1"
    assert r.id == "42" and r.url == B + "/post/42"


def test_post_remote_community_falls_back_to_resolve_object():
    a, http = make()
    http.add("GET", A + "/community", (404, {"error": "couldnt_find_community"}))
    http.add("GET", A + "/resolve_object", {"community": {"community": {"id": 99}}})
    http.add("POST", A + "/post", created_post())
    a.post("x", target="!news@far.away", title="T")
    assert http.last("GET", "/resolve_object")["params"] == {"q": "!news@far.away"}
    assert http.last("POST", "/post")["json"]["community_id"] == 99


def test_post_default_community_and_missing_target():
    a, http = make(community="!tech@lemmy.test")
    http.add("GET", A + "/community", community(3))
    http.add("POST", A + "/post", created_post())
    a.post("only text")
    assert http.last("POST", "/post")["json"] == {"name": "only text", "community_id": 3}
    b, _ = make()
    with pytest.raises(PlatformError, match="community"):
        b.post("x")


def test_post_media_uploads_local_files_to_pictrs(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"PNG")
    a, http = make()
    http.add("POST", B + "/pictrs/image", {"msg": "ok", "files": [{"file": "abc.png", "delete_token": "d"}]})
    http.add("POST", A + "/post", created_post())
    a.post("caption", target="5", title="Pics", media=[str(img), "https://cdn.test/b.jpg"])
    up = http.last("POST", "/pictrs/image")
    assert up["files"] == {"images[]": ("a.png", b"PNG", "image/png")}
    assert up["headers"]["Authorization"] == "Bearer J1" and up["headers"]["Cookie"] == "jwt=J1"
    assert http.last("POST", "/post")["json"] == {
        "name": "Pics", "community_id": 5, "url": B + "/pictrs/image/abc.png",
        "body": "caption\n\n![](https://cdn.test/b.jpg)"}


def test_post_with_link_puts_all_media_in_body_and_long_title():
    a, http = make()
    http.add("POST", A + "/post", created_post())
    a.post("x" * 250, target="5", link="https://l.test", media=["https://cdn.test/1.jpg"])
    body = http.last("POST", "/post")["json"]
    assert len(body["name"]) == 200 and body["url"] == "https://l.test"
    assert body["body"] == "x" * 250 + "\n\n![](https://cdn.test/1.jpg)"


def test_post_missing_media_file(tmp_path):
    a, http = make()
    with pytest.raises(PlatformError, match="not found"):
        a.post("x", target="5", media=[str(tmp_path / "nope.png")])


# ------------------------------------------------------------------ comment
def created_comment(cid=77):
    return {"comment_view": {"comment": {"id": cid, "ap_id": f"{B}/comment/{cid}"}}, "recipient_ids": []}


@pytest.mark.parametrize("target,body", [
    ("post:5", {"content": "hi", "post_id": 5}),
    ("5", {"content": "hi", "post_id": 5}),
    (B + "/post/5", {"content": "hi", "post_id": 5}),
    (B + "/post/5?scrollToComments=true", {"content": "hi", "post_id": 5}),
])
def test_comment_on_post(target, body):
    a, http = make()
    http.add("POST", A + "/comment", created_comment())
    r = a.comment(target, "hi")
    assert http.last("POST", "/comment")["json"] == body
    assert r.id == "77" and r.url == B + "/comment/77"


@pytest.mark.parametrize("target", ["comment:9", B + "/comment/9", B + "/post/5/9"])
def test_comment_reply_to_comment_looks_up_post(target):
    a, http = make()
    http.add("GET", A + "/comment", {"comment_view": {"comment": {"id": 9, "post_id": 5}}})
    http.add("POST", A + "/comment", created_comment())
    a.comment(target, "hi")
    assert http.last("GET", "/comment")["params"] == {"id": 9}
    assert http.last("POST", "/comment")["json"] == {"content": "hi", "post_id": 5, "parent_id": 9}


def test_comment_remote_urls_resolve():
    a, http = make()
    http.add("GET", A + "/resolve_object", {"comment": {"comment": {"id": 31, "post_id": 30}}},
             {"post": {"post": {"id": 40}}})
    http.add("POST", A + "/comment", created_comment())
    a.comment("https://lemmy.world/comment/123456", "a")
    assert http.last("GET", "/resolve_object")["params"] == {"q": "https://lemmy.world/comment/123456"}
    assert http.last("POST", "/comment")["json"] == {"content": "a", "post_id": 30, "parent_id": 31}
    a.comment("https://lemmy.world/post/999", "b")
    assert http.last("POST", "/comment")["json"] == {"content": "b", "post_id": 40}


@pytest.mark.parametrize("url,q", [
    # lemmy-ui comment-context link from another instance -> that instance's /comment/<id> AP id
    ("https://lemmy.world/post/999/123456", "https://lemmy.world/comment/123456"),
    ("https://lemmy.world/post/999/123456/?scrollToComments=true#c", "https://lemmy.world/comment/123456"),
    ("https://lemmy.world/comment/123456?context=3", "https://lemmy.world/comment/123456"),
    # other shapes (Mastodon, kbin...) go through unchanged
    ("https://mast.test/@bob/112233", "https://mast.test/@bob/112233"),
])
def test_comment_remote_comment_links_resolve_ap_id(url, q):
    a, http = make()
    http.add("GET", A + "/resolve_object", {"comment": {"comment": {"id": 31, "post_id": 30}}})
    http.add("POST", A + "/comment", created_comment())
    a.comment(url, "a")
    assert http.last("GET", "/resolve_object")["params"] == {"q": q}
    assert not [c for c in http.calls if c["url"] == A + "/comment" and c["method"] == "GET"]
    assert http.last("POST", "/comment")["json"] == {"content": "a", "post_id": 30, "parent_id": 31}


def test_comment_remote_post_url_drops_query():
    a, http = make()
    http.add("GET", A + "/resolve_object", {"post": {"post": {"id": 40}}})
    http.add("POST", A + "/comment", created_comment())
    a.comment("https://lemmy.world/post/999?scrollToComments=true", "b")
    assert http.last("GET", "/resolve_object")["params"] == {"q": "https://lemmy.world/post/999"}
    assert http.last("POST", "/comment")["json"] == {"content": "b", "post_id": 40}


def test_comment_bad_target():
    a, _ = make()
    with pytest.raises(PlatformError):
        a.comment("hello world", "x")


# ------------------------------------------------------------------ dm
def person(pid):
    return {"person_view": {"person": {"id": pid, "name": "x"}}}


@pytest.mark.parametrize("target,username", [
    ("@bob@other.org", "bob@other.org"),
    ("bob@other.org", "bob@other.org"),
    ("u/bob@other.org", "bob@other.org"),
    ("https://other.org/u/bob", "bob@other.org"),
    ("https://mast.test/@bob", "bob@mast.test"),
    ("u/amy", "amy"),
    ("amy", "amy"),
    ("amy@lemmy.test", "amy"),
    (B + "/u/amy", "amy"),
])
def test_dm_targets(target, username):
    a, http = make()
    http.add("GET", A + "/user", person(8))
    http.add("POST", A + "/private_message", {"private_message_view": {"private_message": {"id": 300}}})
    r = a.dm(target, "hey")
    assert http.last("GET", "/user")["params"] == {"username": username, "limit": 1}
    assert http.last("POST", "/private_message")["json"] == {"content": "hey", "recipient_id": 8}
    assert r.id == "300"


def test_dm_by_id_and_remote_resolve_fallback():
    a, http = make()
    http.add("GET", A + "/user", (404, {"error": "couldnt_find_person"}))
    http.add("GET", A + "/resolve_object", {"person": {"person": {"id": 55}}})
    http.add("POST", A + "/private_message", {"private_message_view": {"private_message": {"id": 1}}})
    a.dm("person:12", "a")
    assert http.last("POST")["json"]["recipient_id"] == 12
    a.dm("@zed@far.away", "b")
    assert http.last("GET", "/resolve_object")["params"] == {"q": "@zed@far.away"}
    assert http.last("POST")["json"]["recipient_id"] == 55


def test_dm_unknown_local_user_raises():
    a, http = make()
    http.add("GET", A + "/user", (404, {"error": "couldnt_find_person"}))
    with pytest.raises(PlatformError):
        a.dm("ghost", "x")


# ------------------------------------------------------------------ poll
BOB = {"id": 2, "name": "bob", "actor_id": "https://other.org/u/bob"}
AMY = {"id": 3, "name": "amy", "actor_id": B + "/u/amy"}
ME = {"id": 1, "name": "me", "actor_id": B + "/u/me"}


def reply(rid, cid, path, creator=BOB, read=False, **c):
    return {"comment_reply": {"id": rid, "comment_id": cid, "read": read, "published": "2026-11-18T10:00:00Z"},
            "comment": {"id": cid, "post_id": 5, "path": path, "content": f" text {cid} ",
                        "published": "2026-11-18T10:00:0%dZ" % (cid % 10), **c},
            "creator": creator, "post": {"id": 5}}


def mention(mid, cid, creator=AMY, read=False):
    return {"person_mention": {"id": mid, "comment_id": cid, "read": read},
            "comment": {"id": cid, "post_id": 6, "path": "0.%d" % cid, "content": "hi @me@lemmy.test",
                        "published": "2026-11-18T09:00:00.123456Z"},
            "creator": creator, "post": {"id": 6}}


def pm(pid, creator, read=False, deleted=False):
    return {"private_message": {"id": pid, "content": f"pm {pid}", "read": read, "deleted": deleted,
                                "published": "2026-11-18T11:00:00", "creator_id": creator["id"]},
            "creator": creator, "recipient": ME}


def routes(http, replies, mentions, pms):
    http.add("GET", A + "/site", SITE)
    http.add("GET", A + "/user/replies", *replies)
    http.add("GET", A + "/user/mention", *mentions)
    http.add("GET", A + "/private_message/list", *pms)
    for path in ("/comment/mark_as_read", "/user/mention/mark_as_read", "/private_message/mark_as_read"):
        http.add("POST", A + path, {})


def test_poll_kinds_threads_reply_to_and_own_filtered():
    a, http = make()
    routes(http,
           [{"replies": [reply(11, 21, "0.20.21"), reply(10, 20, "0.20"), reply(9, 19, "0.19", deleted=True)]}],
           [{"mentions": [mention(4, 21), mention(3, 30)]}],
           [{"private_messages": [pm(102, ME), pm(101, BOB), pm(100, AMY, deleted=True)]}])
    state = {}
    items = a.poll(state)
    by = {i.id: i for i in items}
    assert set(by) == {"comment:21", "comment:20", "comment:30", "pm:101"}
    assert by["comment:21"].kind == "reply" and by["comment:20"].kind == "comment"
    assert by["comment:30"].kind == "mention" and by["comment:30"].author == "amy@lemmy.test"
    c = by["comment:21"]
    assert c.author == "bob@other.org" and c.author_id == "2" and c.text == "text 21"
    assert c.thread == "post:5" and c.url == B + "/comment/21"
    assert c.reply_to == {"action": "comment", "target": "comment:21"}
    d = by["pm:101"]
    assert d.kind == "dm" and d.thread == "dm:bob@other.org"
    assert d.reply_to == {"action": "dm", "target": "bob@other.org"}
    assert d.ts == 1794999600.0  # naive timestamps are UTC
    assert by["comment:30"].ts == pytest.approx(1794992400.123456)
    assert [i.ts for i in items] == sorted(i.ts for i in items)
    assert state == {"reply_id": 11, "mention_id": 4, "pm_id": 102}
    q = http.last("GET", "/user/replies")["params"]
    assert q == {"unread_only": "false", "page": 1, "limit": 50, "sort": "New"}
    assert "sort" not in http.last("GET", "/private_message/list")["params"]
    # first poll never marks the backlog as read
    assert not [c for c in http.calls if "mark_as_read" in c["url"]]
    # reply_to targets are accepted by comment()/dm()
    http.add("GET", A + "/comment", {"comment_view": {"comment": {"id": 21, "post_id": 5}}})
    assert a._comment_target(c.reply_to["target"]) == (5, 21)


def test_poll_advances_cursor_and_marks_new_items_read():
    a, http = make()
    routes(http,
           [{"replies": [reply(12, 22, "0.22"), reply(11, 21, "0.20.21", read=True)]}],
           [{"mentions": [mention(4, 21)]}],
           [{"private_messages": [pm(103, ME), pm(102, BOB)]}])
    state = {"reply_id": 11, "mention_id": 4, "pm_id": 101}
    items = a.poll(state)
    assert [i.id for i in items] == ["comment:22", "pm:102"]
    assert state == {"reply_id": 12, "mention_id": 4, "pm_id": 103}
    marks = [(c["url"].replace(A, ""), c["json"]) for c in http.calls if "mark_as_read" in c["url"]]
    assert marks == [("/comment/mark_as_read", {"comment_reply_id": 12, "read": True}),
                     ("/private_message/mark_as_read", {"private_message_id": 102, "read": True})]


def test_poll_mark_read_disabled_and_mark_failure_ignored():
    a, http = make(mark_read="false")
    routes(http, [{"replies": [reply(12, 22, "0.22")]}], [{"mentions": []}], [{"private_messages": []}])
    a.poll({"reply_id": 1})
    assert not [c for c in http.calls if "mark_as_read" in c["url"]]
    b, http2 = make()
    http2.add("GET", A + "/site", SITE)
    http2.add("GET", A + "/user/replies", {"replies": [reply(12, 22, "0.22")]})
    http2.add("GET", A + "/user/mention", {"mentions": []})
    http2.add("GET", A + "/private_message/list", {"private_messages": []})
    http2.add("POST", A + "/comment/mark_as_read", (400, {"error": "couldnt_update_comment"}))
    assert [i.id for i in b.poll({"reply_id": 1})] == ["comment:22"]
