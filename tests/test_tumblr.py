import json
import re
import urllib.parse

import pytest

from social_bridge.adapters.tumblr import TumblrAdapter
from social_bridge.base import PlatformError, oauth1_header
from tests.fakehttp import FakeHttp

A = "https://api.tumblr.com/v2"
CFG = {"consumer_key": "ck", "consumer_secret": "cs", "oauth_token": "at", "oauth_token_secret": "ats",
       "blog": "MyBlog"}
USER = {"meta": {"status": 200, "msg": "OK"}, "response": {"user": {"name": "owner", "blogs": [
    {"name": "owner", "uuid": "t:own", "url": "https://owner.tumblr.com/", "primary": True},
    {"name": "myblog", "uuid": "t:me", "url": "https://myblog.tumblr.com/", "primary": False}]}}}


def make(**extra):
    http = FakeHttp("tumblr")
    return TumblrAdapter({**CFG, **extra}, http), http


def check_sig(call):
    """Recompute the OAuth 1.0a header (query string included, JSON/multipart bodies unsigned) and compare."""
    h = call["headers"]["Authorization"]
    assert h.startswith("OAuth ")
    fields = {k: urllib.parse.unquote(v) for k, v in re.findall(r'(\w+)="([^"]*)"', h)}
    expected = oauth1_header(call["method"], call["url"], consumer_key="ck", consumer_secret="cs", token="at",
                             token_secret="ats", nonce=fields["oauth_nonce"], timestamp=int(fields["oauth_timestamp"]))
    assert h == expected


def created(pid):
    return (201, {"meta": {"status": 201, "msg": "Created"}, "response": {"id": pid, "state": "published"}})


def query(call):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(call["url"]).query))


TYPES = ["reply", "reblog_with_content", "conversational_note", "mention_in_reply", "mention_in_post"]


def notif_query(call):
    """-> (types[] values in order, other query params)."""
    pairs = urllib.parse.parse_qsl(urllib.parse.urlsplit(call["url"]).query)
    return [v for k, v in pairs if k == "types[]"], {k: v for k, v in pairs if k != "types[]"}


# ------------------------------------------------------------------ whoami
def test_whoami_picks_configured_blog_and_signs():
    a, http = make()
    http.add("GET", A + "/user/info", USER)
    assert a.whoami() == "myblog"
    c = http.last("GET")
    assert c["url"] == A + "/user/info" and 'oauth_consumer_key="ck"' in c["headers"]["Authorization"]
    check_sig(c)


def test_whoami_defaults_to_primary_blog_and_rejects_foreign_blog():
    a, http = make(blog="")
    http.add("GET", A + "/user/info", USER)
    assert a.whoami() == "owner"
    b, http2 = make(blog="https://someoneelse.tumblr.com/")
    http2.add("GET", A + "/user/info", USER)
    with pytest.raises(PlatformError, match="not one of this account's blogs"):
        b.whoami()


def test_blog_identifier_forms():
    a, _ = make()
    assert a._ident("MyBlog") == "myblog.tumblr.com"
    assert a._ident("myblog.tumblr.com") == "myblog.tumblr.com"
    assert a._ident("https://www.tumblr.com/myblog") == "myblog.tumblr.com"
    assert a._ident("https://www.tumblr.com/blog/view/myblog") == "myblog.tumblr.com"
    assert a._ident("https://MyBlog.tumblr.com/") == "myblog.tumblr.com"
    assert a._ident("https://www.example.com/") == "www.example.com"
    assert a._ident("t:AbC") == "t:AbC"


# ------------------------------------------------------------------ post
def test_post_text_title_link_tags_and_state():
    a, http = make(post_state="queue", tags="bot,news")
    http.add("POST", A + "/blog/myblog.tumblr.com/posts", created("7001"))
    r = a.post("first para\n\nsecond\nline", title="Head", link="https://x.y/z")
    c = http.last("POST")
    check_sig(c)
    assert c["json"] == {"content": [
        {"type": "text", "subtype": "heading1", "text": "Head"},
        {"type": "text", "text": "first para"},
        {"type": "text", "text": "second\nline"},
        {"type": "link", "url": "https://x.y/z"}], "state": "queue", "tags": "bot,news"}
    assert r.id == "7001" and r.url == "https://www.tumblr.com/myblog/7001"


def test_post_to_other_blog_with_image_url_and_mention():
    a, http = make()
    http.add("GET", A + "/blog/bob.tumblr.com/info", {"response": {"blog": {"name": "bob", "uuid": "t:bob"}}})
    http.add("GET", A + "/blog/ghost.tumblr.com/info", (404, {"meta": {"status": 404}, "response": []}))
    http.add("POST", A + "/blog/www.side.example/posts", created(55))
    r = a.post("hi @bob and @ghost, mail me@x.com", target="https://www.side.example/",
               media=["https://img.test/a/pic.png?size=2"])
    body = http.last("POST")["json"]
    assert body["content"][0] == {"type": "image", "media": [{"url": "https://img.test/a/pic.png?size=2"}]}
    assert body["content"][1] == {"type": "text", "text": "hi @bob and @ghost, mail me@x.com", "formatting": [
        {"start": 3, "end": 7, "type": "mention", "blog": {"uuid": "t:bob"}}]}
    assert r.id == "55" and r.url == "https://www.side.example/post/55"
    assert len([c for c in http.calls if "/info" in c["url"]]) == 2


def test_post_local_media_uses_multipart_json_part(tmp_path):
    img = tmp_path / "cat.jpg"
    img.write_bytes(b"JPEGDATA")
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"MP4DATA")
    a, http = make()
    http.add("POST", A + "/blog/myblog.tumblr.com/posts", created("9"))
    a.post("look", media=[str(img), str(vid)])
    c = http.last("POST")
    check_sig(c)  # multipart body is not part of the signature
    assert c["json"] is None
    files = c["files"]
    name, payload, ctype = files["json"]
    assert name is None and ctype == "application/json"
    assert json.loads(payload)["content"] == [
        {"type": "image", "media": [{"type": "image/jpeg", "identifier": "media0"}]},
        {"type": "video", "media": {"type": "video/mp4", "identifier": "media1"}},
        {"type": "text", "text": "look"}]
    assert files["media0"] == ("cat.jpg", b"JPEGDATA", "image/jpeg")
    assert files["media1"] == ("clip.mp4", b"MP4DATA", "video/mp4")


def test_post_media_errors(tmp_path):
    a, http = make()
    with pytest.raises(PlatformError, match="not found"):
        a.post("x", media=[str(tmp_path / "missing.png")])
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"%PDF")
    with pytest.raises(PlatformError, match="images, video or audio"):
        a.post("x", media=[str(doc)])
    assert http.calls == []


# ------------------------------------------------------------------ comment (reblog with comment)
@pytest.mark.parametrize("target,ident,pid", [
    ("https://www.tumblr.com/bob/7123456789/some-slug", "bob.tumblr.com", "7123456789"),
    ("https://tumblr.com/bob/7123456789", "bob.tumblr.com", "7123456789"),
    ("https://bob.tumblr.com/post/7123456789/some-slug?source=share", "bob.tumblr.com", "7123456789"),
    ("https://www.tumblr.com/blog/view/bob/7123456789", "bob.tumblr.com", "7123456789"),
    ("https://blog.example.org/post/7123456789", "blog.example.org", "7123456789"),
    ("bob/7123456789", "bob.tumblr.com", "7123456789"),
    ("@bob/post/7123456789", "bob.tumblr.com", "7123456789"),
])
def test_post_ref_parsing(target, ident, pid):
    a, _ = make()
    assert a._post_ref(target) == (ident, pid)


def test_post_ref_rejects_bare_id():
    a, _ = make()
    with pytest.raises(PlatformError, match="blog"):
        a._post_ref("7123456789")


def test_comment_reblogs_with_text():
    a, http = make()
    http.add("GET", A + "/blog/bob.tumblr.com/posts", {"response": {
        "blog": {"name": "bob", "uuid": "t:bob"},
        "posts": [{"id": 7123456789, "id_string": "7123456789", "reblog_key": "rk1",
                   "blog": {"name": "bob", "uuid": "t:bob"}}]}})
    http.add("POST", A + "/blog/myblog.tumblr.com/posts", created("8000"))
    r = a.comment("https://bob.tumblr.com/post/7123456789/slug", "agreed")
    g = http.last("GET")
    assert query(g) == {"id": "7123456789", "npf": "true"}
    check_sig(g)  # query string is signed
    c = http.last("POST")
    assert c["json"] == {"content": [{"type": "text", "text": "agreed"}], "parent_tumblelog_uuid": "t:bob",
                         "parent_post_id": "7123456789", "reblog_key": "rk1"}
    assert r.id == "8000" and r.url == "https://www.tumblr.com/myblog/8000"


def test_comment_missing_post():
    a, http = make()
    http.add("GET", A + "/blog/bob.tumblr.com/posts", {"response": {"posts": []}})
    with pytest.raises(PlatformError, match="not found"):
        a.comment("bob/1", "x")


def test_dm_not_supported():
    a, _ = make()
    assert "dm" not in a.actions
    with pytest.raises(PlatformError):
        a.dm("bob", "hi")


# ------------------------------------------------------------------ poll
def note(nid, typ, ts, frm="bob", **kw):
    n = {"id": nid, "type": typ, "timestamp": ts, "unread": True, "from_tumblelog_name": frm,
         "from_tumblelog_uuid": "t:" + frm, "target_tumblelog_name": "myblog", "target_tumblelog_uuid": "t:me",
         "target_post_id": "100"}
    n.update(kw)
    return n


def test_poll_kinds_threads_reply_to_and_cursor():
    a, http = make()
    http.add("GET", A + "/user/info", USER)
    page1 = {"response": {"notifications": [
        note("n6", "like", 1006),
        note("n5", "reply", 1005, reply_text="nice <b>post</b> &amp; more"),
        note("n4", "reblog_with_content", 1004, frm="amy", post_id="200", added_text="adding this"),
        note("n3", "reblog_with_content", 1003, frm="cat", post_id="300"),
        note("n2", "mention_in_post", 1002, frm="dan", post_id="400", target_post_id=None,
             added_text="hey @myblog"),
        note("n1", "reply", 1001, frm="myblog", reply_text="my own reply"),
        note("n1b", "reply", 1001, frm="Owner", reply_text="reply from the account's primary blog"),
        note("n1c", "reblog_with_content", 1001, frm="renamed", from_tumblelog_uuid="t:own", post_id="900",
             added_text="reblog from the primary blog under a name we haven't seen"),
        note("n1d", "mention_in_post", 1001, frm="owner", post_id="901", target_post_id=None,
             added_text="@myblog from my other blog"),
        note("n0", "mention_in_reply", 1000, frm="eve", target_tumblelog_name="zed", target_post_id="500",
             reply_text="@myblog look"),
    ], "_links": {"next": {"href": "/v2/blog/myblog.tumblr.com/notifications?before=1000",
                           "query_params": {"before": "1000"}}}}}
    http.add("GET", A + "/blog/myblog.tumblr.com/notifications", page1)
    http.add("GET", A + "/blog/cat.tumblr.com/posts", {"response": {"posts": [
        {"id_string": "300", "content": [{"type": "text", "text": "cat says"}, {"type": "image", "media": []},
                                         {"type": "text", "text": "hi"}]}]}})
    state = {}
    items = a.poll(state)
    by = {i.id: i for i in items}
    assert [i.id for i in items] == ["n0", "n2", "n3", "n4", "n5"]  # oldest first; like and all own blogs dropped
    assert state["since"] == 1006
    assert by["n5"].kind == "comment" and by["n5"].text == "nice post & more" and by["n5"].author == "bob"
    assert by["n5"].reply_to == {"action": "comment", "target": "myblog/100"} and by["n5"].thread == "myblog/100"
    assert by["n5"].url == "https://www.tumblr.com/myblog/100" and by["n5"].ts == 1005.0
    assert by["n4"].kind == "comment" and by["n4"].text == "adding this"
    assert by["n4"].reply_to == {"action": "comment", "target": "amy/200"} and by["n4"].thread == "myblog/100"
    assert by["n3"].text == "cat says\n\nhi"  # fetched from the reblog itself
    assert by["n2"].kind == "mention" and by["n2"].reply_to["target"] == "dan/400" and by["n2"].thread == "dan/400"
    assert by["n0"].kind == "mention" and by["n0"].reply_to["target"] == "zed/500"
    assert by["n0"].author_id == "t:eve"
    # reply_to targets are accepted by comment()
    assert a._post_ref(by["n4"].reply_to["target"]) == ("amy.tumblr.com", "200")
    # first poll has no cursor: a single page, no pagination
    assert len([c for c in http.calls if "/notifications" in c["url"]]) == 1
    nc = http.last("GET", "/notifications")
    check_sig(nc)  # repeated types[] params are signed
    assert notif_query(nc) == (TYPES, {})  # only the surfaced activity types are requested
    assert "resume" not in state


def test_poll_second_round_filters_old_and_paginates():
    a, http = make()
    http.add("GET", A + "/user/info", USER)
    http.add("GET", A + "/blog/myblog.tumblr.com/notifications",
             {"response": {"notifications": [note("n9", "reply", 2009, reply_text="new"),
                                              note("n8", "reply", 2008, reply_text="newer page 1")],
                           "_links": {"next": {"query_params": {"before": "2008"}}}}},
             {"response": {"notifications": [note("n7", "reply", 2001, reply_text="page 2"),
                                              note("n5", "reply", 1500, reply_text="old")],
                           "_links": {"next": {"query_params": {"before": "1500"}}}}})
    state = {"since": 2000}
    items = a.poll(state)
    assert [i.id for i in items] == ["n7", "n8", "n9"]
    calls = [c for c in http.calls if "/notifications" in c["url"]]
    assert len(calls) == 2 and notif_query(calls[1]) == (TYPES, {"before": "2008"})
    check_sig(calls[1])
    assert state == {"since": 2009}


def page(ts_list, before=None):
    p = {"notifications": [note(f"n{ts}", "reply", ts, reply_text=f"r{ts}") for ts in ts_list]}
    if before:
        p["_links"] = {"next": {"href": f"/v2/blog/myblog.tumblr.com/notifications?before={before}",
                                "query_params": {"before": str(before), "types": TYPES}}}
    return {"response": p}


def test_poll_page_cap_resumes_from_where_it_stopped():
    a, http = make()
    http.add("GET", A + "/user/info", USER)
    # 6 pages between the cursor (1000) and now: more than one poll fetches
    pages = [page([1600 - 100 * i, 1550 - 100 * i], before=1550 - 100 * i) for i in range(6)]
    pages[-1] = page([1100, 1050, 990], before=990)
    http.add("GET", A + "/blog/myblog.tumblr.com/notifications", *pages, page([1700], before=1700),
             page([1650, 1590], before=1590))
    state = {"since": 1000}
    first = a.poll(state)
    assert [i.id for i in first] == [f"n{t}" for t in sorted([1600, 1550, 1500, 1450, 1400, 1350, 1300, 1250,
                                                               1200, 1150])]
    # cursor not moved past the unscanned range; the next page's `before` is kept instead
    assert state == {"since": 1000, "resume": {"query": {"before": "1150"}, "newest": 1600}}
    second = a.poll(state)
    assert [i.id for i in second] == ["n1050", "n1100"]
    calls = [c for c in http.calls if "/notifications" in c["url"]]
    assert len(calls) == 6 and notif_query(calls[5]) == (TYPES, {"before": "1150"})
    check_sig(calls[5])
    assert state == {"since": 1600}  # sweep finished: cursor jumps to the newest seen when it started
    third = a.poll(state)
    assert [i.id for i in third] == ["n1650", "n1700"]
    assert notif_query(http.last("GET", "/notifications")) == (TYPES, {"before": "1700"})
    assert state == {"since": 1700}


def test_poll_without_ids_builds_stable_ids():
    a, http = make()
    http.add("GET", A + "/user/info", USER)
    n = note(None, "reply", 3000, reply_text="x")
    http.add("GET", A + "/blog/myblog.tumblr.com/notifications", {"response": {"notifications": [n]}})
    first = a.poll({})[0].id
    second = a.poll({})[0].id
    assert first == second == "reply:t:bob:100:3000"
