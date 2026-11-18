import time
import urllib.parse

import pytest

from social_bridge.adapters.linkedin import LinkedInAdapter
from social_bridge.base import PlatformError
from tests.fakehttp import FakeHttp

R = "https://api.linkedin.com/rest"
USERINFO = "https://api.linkedin.com/v2/userinfo"
TOKEN = "https://www.linkedin.com/oauth/v2/accessToken"
ME = "urn:li:person:abc"
ORG = "urn:li:organization:5"


def make(**cfg):
    http = FakeHttp("linkedin")
    conf = {"access_token": "tok", "author_urn": ME, "linkedin_version": "202608"}
    conf.update(cfg)
    return LinkedInAdapter(conf, http), http


def q(urn):
    return urllib.parse.quote(urn, safe="")


def created(urn="urn:li:share:77"):
    return (201, None, {"x-restli-id": urn})


def posted(http):
    return http.last("POST", "/rest/posts")["json"]


def test_whoami_member_from_userinfo_and_no_polling():
    a, http = make(author_urn="")
    http.add("GET", USERINFO, {"sub": "abc", "name": "Kyo Ko"})
    assert a.whoami() == "Kyo Ko" and a._author() == ME
    assert len(http.calls) == 1
    h = http.calls[0]["headers"]
    assert h["Authorization"] == "Bearer tok" and "LinkedIn-Version" not in h
    assert a.poll_interval == 0 and a.poll({}) == []


def test_whoami_organization():
    a, http = make(author_urn=ORG)
    http.add("GET", R + "/organizations/5", {"localizedName": "Acme"})
    assert a.poll_interval == 600
    assert a.whoami() == "Acme (urn:li:organization:5)"
    b, http2 = make(author_urn=ORG)
    http2.add("GET", R + "/organizations/5", (403, {"message": "no access"}))
    assert b.whoami() == ORG


def test_post_text_headers_body_and_little_text_escaping():
    a, http = make()
    http.add("POST", R + "/posts", created())
    r = a.post("Hi (all) #News @bob_x, C# 100%")
    c = http.last("POST")
    assert c["headers"]["Authorization"] == "Bearer tok"
    assert c["headers"]["LinkedIn-Version"] == "202608" and c["headers"]["X-Restli-Protocol-Version"] == "2.0.0"
    assert c["json"] == {
        "author": ME,
        "commentary": "Hi \\(all\\) {hashtag|\\#|News} \\@bob\\_x, C\\# 100%",
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    assert r.id == "urn:li:share:77" and r.url == "https://www.linkedin.com/feed/update/urn:li:share:77/"


def test_post_title_prepended_and_visibility():
    a, http = make(visibility="connections")
    http.add("POST", R + "/posts", created())
    a.post("body", title="Head")
    assert posted(http)["commentary"] == "Head\n\nbody" and posted(http)["visibility"] == "CONNECTIONS"


def test_post_link_becomes_article_with_page_metadata():
    a, http = make()
    http.add("GET", "https://ex.test/a", b'<html><head><title>T</title><meta property="og:title" '
                                         b'content="Big &amp; News"><meta name="description" content="d"></head>')
    http.add("POST", R + "/posts", created())
    a.post("read", link="https://ex.test/a")
    assert posted(http)["content"] == {"article": {"source": "https://ex.test/a", "title": "Big & News",
                                                   "description": "d"}}
    assert posted(http)["commentary"] == "read"
    a.post("read", link="https://ex.test/a", title="Mine")
    assert posted(http)["content"]["article"]["title"] == "Mine"


def test_post_link_metadata_failure_falls_back_to_url():
    a, http = make()
    http.add("GET", "https://ex.test/b", (404, "nope"))
    http.add("POST", R + "/posts", created())
    a.post("x", link="https://ex.test/b")
    assert posted(http)["content"] == {"article": {"source": "https://ex.test/b", "title": "https://ex.test/b"}}


def test_post_as_organization_from_target():
    a, http = make()
    http.add("POST", R + "/posts", created())
    http.add("GET", R + "/organizations", {"elements": [{"id": 99}]})
    a.post("hi", target="https://www.linkedin.com/company/12345/admin/")
    assert posted(http)["author"] == "urn:li:organization:12345"
    a.post("hi", target="urn:li:organization:7")
    assert posted(http)["author"] == "urn:li:organization:7"
    a.post("hi", target="https://www.linkedin.com/company/acme-co/")
    assert posted(http)["author"] == "urn:li:organization:99"
    assert http.last("GET", "/organizations")["params"] == {"q": "vanityName", "vanityName": "acme-co"}


def test_post_images_upload_then_multiimage(tmp_path):
    f = tmp_path / "a.png"
    f.write_bytes(b"PNGDATA")
    a, http = make()
    http.add("POST", R + "/images",
             {"value": {"uploadUrl": "https://www.linkedin.com/dms-uploads/i1?sig=x", "image": "urn:li:image:1"}},
             {"value": {"uploadUrl": "https://www.linkedin.com/dms-uploads/i2?sig=y", "image": "urn:li:image:2"}})
    http.add("PUT", "https://www.linkedin.com/dms-uploads/i1", (201, None))
    http.add("PUT", "https://www.linkedin.com/dms-uploads/i2", (201, None))
    http.add("GET", "https://cdn.test/b.jpg", b"JPGDATA")
    http.add("POST", R + "/posts", created())
    a.post("pics", title="T", media=[str(f), "https://cdn.test/b.jpg"])
    init = [c for c in http.calls if c["url"] == R + "/images"]
    assert [c["params"] for c in init] == [{"action": "initializeUpload"}] * 2
    assert init[0]["json"] == {"initializeUploadRequest": {"owner": ME}}
    puts = [c for c in http.calls if c["method"] == "PUT"]
    assert [c["data"] for c in puts] == [b"PNGDATA", b"JPGDATA"]
    assert puts[0]["headers"]["Authorization"] == "Bearer tok" and "LinkedIn-Version" not in puts[0]["headers"]
    assert puts[0]["headers"]["Content-Type"] == "application/octet-stream"
    body = posted(http)
    assert body["content"] == {"multiImage": {"images": [{"id": "urn:li:image:1"}, {"id": "urn:li:image:2"}]}}
    assert body["commentary"] == "T\n\npics"


def test_post_single_image_as_organization_owner(tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"J")
    a, http = make(author_urn=ORG)
    http.add("POST", R + "/images", {"value": {"uploadUrl": "https://www.linkedin.com/up/1", "image": "urn:li:image:1"}})
    http.add("PUT", "https://www.linkedin.com/up/1", (201, None))
    http.add("POST", R + "/posts", created())
    a.post("x", media=[str(f)])
    assert http.last("POST", "/rest/images")["json"] == {"initializeUploadRequest": {"owner": ORG}}
    assert posted(http)["content"] == {"media": {"id": "urn:li:image:1"}} and posted(http)["author"] == ORG


def test_post_video_multipart_upload_finalize_and_wait(tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"0123456789")
    a, http = make()
    http.add("POST", R + "/videos",
             {"value": {"video": "urn:li:video:9", "uploadToken": "ut", "uploadInstructions": [
                 {"uploadUrl": "https://up.test/p1", "firstByte": 0, "lastByte": 5},
                 {"uploadUrl": "https://up.test/p2", "firstByte": 6, "lastByte": 9}]}},
             (200, None))
    http.add("PUT", "https://up.test/p1", (200, None, {"ETag": "e1"}))
    http.add("PUT", "https://up.test/p2", (200, None, {"ETag": "e2"}))
    http.add("GET", R + "/videos/" + q("urn:li:video:9"), {"status": "PROCESSING"}, {"status": "AVAILABLE"})
    http.add("POST", R + "/posts", created("urn:li:ugcPost:5"))
    r = a.post("watch", title="My vid", link="https://x.y", media=[str(f)])
    vids = [c for c in http.calls if c["url"] == R + "/videos"]
    assert vids[0]["params"] == {"action": "initializeUpload"}
    assert vids[0]["json"] == {"initializeUploadRequest": {"owner": ME, "fileSizeBytes": 10,
                                                           "uploadCaptions": False, "uploadThumbnail": False}}
    puts = [c for c in http.calls if c["method"] == "PUT"]
    assert [c["data"] for c in puts] == [b"012345", b"6789"] and "Authorization" not in puts[0]["headers"]
    assert vids[1]["params"] == {"action": "finalizeUpload"}
    assert vids[1]["json"] == {"finalizeUploadRequest": {"video": "urn:li:video:9", "uploadToken": "ut",
                                                         "uploadedPartIds": ["e1", "e2"]}}
    assert len([c for c in http.calls if c["method"] == "GET"]) == 2
    body = posted(http)
    assert body["content"] == {"media": {"id": "urn:li:video:9", "title": "My vid"}}
    assert body["commentary"] == "watch\n\nhttps://x.y" and r.id == "urn:li:ugcPost:5"


def test_post_document_and_mixed_media_rejected(tmp_path):
    d = tmp_path / "deck.pdf"
    d.write_bytes(b"%PDF")
    a, http = make()
    http.add("POST", R + "/documents", {"value": {"uploadUrl": "https://www.linkedin.com/up/d",
                                                  "document": "urn:li:document:3"}})
    http.add("PUT", "https://www.linkedin.com/up/d", (201, None))
    http.add("POST", R + "/posts", created())
    a.post("slides", media=[str(d)])
    assert posted(http)["content"] == {"media": {"id": "urn:li:document:3", "title": "deck.pdf"}}
    n = len(http.calls)
    with pytest.raises(PlatformError, match="several images"):
        a.post("x", media=[str(d), "https://cdn.test/a.png"])
    with pytest.raises(PlatformError, match="not found"):
        a.post("x", media=[str(tmp_path / "missing.png")])
    assert len(http.calls) == n


@pytest.mark.parametrize("target, obj", [
    ("https://www.linkedin.com/feed/update/urn:li:activity:7123456789/", "urn:li:activity:7123456789"),
    ("https://www.linkedin.com/feed/update/urn%3Ali%3Aactivity%3A42/", "urn:li:activity:42"),
    ("https://www.linkedin.com/posts/jane-doe_ai-news-activity-7123456789012345678-AbCd?utm_source=share",
     "urn:li:activity:7123456789012345678"),
    ("https://www.linkedin.com/embed/feed/update/urn:li:share:555", "urn:li:share:555"),
    ("urn:li:ugcPost:666", "urn:li:ugcPost:666"),
    ("7123456789", "urn:li:activity:7123456789"),
])
def test_comment_on_post_targets(target, obj):
    a, http = make()
    http.add("POST", "re:/rest/socialActions/.+/comments$",
             (201, {"commentUrn": f"urn:li:comment:({obj},100)", "id": "100"}, {"x-restli-id": "100"}))
    r = a.comment(target, "hi (there)")
    c = http.last("POST")
    assert c["url"] == f"{R}/socialActions/{q(obj)}/comments"
    assert c["json"] == {"actor": ME, "object": obj, "message": {"text": "hi (there)"}}
    assert c["headers"]["LinkedIn-Version"] == "202608"
    assert r.id == f"urn:li:comment:({obj},100)"
    assert r.url == f"https://www.linkedin.com/feed/update/{obj}/?commentUrn={q(r.id)}"


@pytest.mark.parametrize("target", [
    "https://www.linkedin.com/feed/update/urn:li:activity:42/?commentUrn=urn%3Ali%3Acomment%3A%28activity%3A42"
    "%2C99%29&dashCommentUrn=urn%3Ali%3Afsd_comment%3A%2899%2Curn%3Ali%3Aactivity%3A42%29",
    "https://www.linkedin.com/feed/update/urn:li:activity:42/?dashCommentUrn=urn%3Ali%3Afsd_comment%3A%2899"
    "%2Curn%3Ali%3Aactivity%3A42%29",
    "urn:li:comment:(urn:li:activity:42,99)",
    "urn:li:comment:(activity:42,99)",
])
def test_comment_reply_in_comment_thread(target):
    a, http = make()
    http.add("POST", "re:/rest/socialActions/.+/comments$", (201, None, {"x-restli-id": "123"}))
    r = a.comment(target, "re")
    parent = "urn:li:comment:(urn:li:activity:42,99)"
    c = http.last("POST")
    assert c["url"] == f"{R}/socialActions/{q(parent)}/comments"
    assert c["json"] == {"actor": ME, "object": "urn:li:activity:42", "message": {"text": "re"},
                         "parentComment": parent}
    assert r.id == "urn:li:comment:(urn:li:activity:42,123)"


def test_comment_bad_target():
    a, _ = make()
    with pytest.raises(PlatformError):
        a.comment("https://www.linkedin.com/in/someone/", "x")


def test_token_refresh_on_401_and_upfront():
    a, http = make(refresh_token="rt", client_id="cid", client_secret="cs")
    http.add("POST", R + "/posts", (401, {"message": "expired"}), created())
    http.add("POST", TOKEN, {"access_token": "new", "expires_in": 5184000, "refresh_token": "rt2"})
    r = a.post("x")
    tok = http.last("POST", "oauth/v2/accessToken")
    assert tok["data"] == {"grant_type": "refresh_token", "refresh_token": "rt", "client_id": "cid",
                           "client_secret": "cs"}
    assert http.last("POST", "/rest/posts")["headers"]["Authorization"] == "Bearer new" and r.id
    assert a._rt == "rt2"

    b, http2 = make(access_token="", refresh_token="rt", client_id="cid", client_secret="cs")
    http2.add("POST", TOKEN, {"access_token": "fresh", "expires_in": 100})
    http2.add("POST", R + "/posts", created())
    b.post("y")
    assert http2.calls[0]["url"] == TOKEN and http2.last("POST", "/rest/posts")["headers"]["Authorization"] == \
        "Bearer fresh"
    b.post("z")   # expires within 5 minutes -> renewed before the call
    assert len([c for c in http2.calls if c["url"] == TOKEN]) == 2

    c, http3 = make()
    http3.add("POST", R + "/posts", (401, {"message": "expired"}))
    with pytest.raises(PlatformError) as e:
        c.post("x")
    assert e.value.status == 401


def test_default_version_steps_back_when_nonexistent():
    a, http = make(linkedin_version="")
    http.add("POST", R + "/posts", (426, {"status": 426, "code": "NONEXISTENT_VERSION", "message": "inactive"}),
             created())
    a.post("x")
    t = time.gmtime()
    y, m = (t.tm_year, t.tm_mon - 2) if t.tm_mon > 2 else (t.tm_year - 1, t.tm_mon + 10)
    first, second = [c["headers"]["LinkedIn-Version"] for c in http.calls]
    assert first == f"{y}{m:02d}" and second == LinkedInAdapter._prev_version(first)
    assert LinkedInAdapter._prev_version("202601") == "202512"


def test_retries_5xx():
    a, http = make()
    http.add("POST", R + "/posts", (503, "busy"), created())
    assert a.post("x").id == "urn:li:share:77" and len(http.calls) == 2


def comment(cid, actor, ms, text="t", total=None, parent=None, obj="urn:li:activity:10"):
    c = {"actor": actor, "commentUrn": f"urn:li:comment:({obj},{cid})", "id": str(cid), "object": obj,
         "created": {"actor": actor, "time": ms}, "message": {"text": text}}
    if total is not None:
        c["commentsSummary"] = {"aggregatedTotalComments": total}
    if parent:
        c["parentComment"] = parent
    return c


def test_poll_organization_comments_replies_mentions_and_cursor():
    a, http = make(author_urn=ORG)
    c1, c2 = "urn:li:comment:(urn:li:activity:10,101)", "urn:li:comment:(urn:li:activity:10,102)"
    http.add("GET", R + "/posts", {"elements": [{"id": "urn:li:share:1"}]})
    http.add("GET", f"{R}/socialActions/{q('urn:li:share:1')}/comments", {"elements": [
        comment(101, "urn:li:person:bob", 1000000, "Great (really)", total=2),
        comment(102, ORG, 1001000, "thanks", total=1),
        comment(103, "urn:li:person:amy", 1002000, "meh", total=0),
    ]})
    http.add("GET", f"{R}/socialActions/{q(c1)}/comments", {"elements": [
        comment(104, ORG, 1002500, "we reply", parent=c1),
        comment(105, "urn:li:person:bob", 1003000, "cool", parent=c1),
    ]})
    http.add("GET", f"{R}/socialActions/{q(c2)}/comments", {"elements": [
        comment(106, "urn:li:person:zed", 1004000, "q?", parent=c2)]})
    http.add("GET", R + "/organizationalEntityNotifications", {"elements": [
        {"action": "SHARE_MENTION", "generatedActivity": "urn:li:share:900", "lastModifiedAt": 1005000},
        {"action": "COMMENT_MENTION", "generatedActivity": "urn:li:comment:(urn:li:activity:800,801)",
         "sourcePost": "urn:li:share:800"},
        {"action": "COMMENT_MENTION", "generatedActivity": c1},
        {"action": "SHARE_MENTION", "generatedActivity": "urn:li:share:901"},
    ]})
    http.add("GET", f"{R}/posts/{q('urn:li:share:900')}", {
        "author": "urn:li:person:eve", "publishedAt": 1005000,
        "commentary": "Thanks @[Acme](urn:li:organization:5) {hashtag|\\#|AI} \\(yes\\)"})
    http.add("GET", f"{R}/socialActions/{q('urn:li:activity:800')}/comments/801", {
        "actor": "urn:li:person:joe", "message": {"text": "cc Acme"}, "created": {"time": 1006000},
        "object": "urn:li:activity:800"})
    http.add("GET", f"{R}/posts/{q('urn:li:share:901')}", (404, {"message": "gone"}))

    state = {}
    items = a.poll(state)
    got = {i.id: (i.kind, i.thread, i.author, i.reply_to["target"]) for i in items}
    assert got == {
        c1: ("comment", "urn:li:share:1", "urn:li:person:bob", c1),
        "urn:li:comment:(urn:li:activity:10,103)": ("comment", "urn:li:share:1", "urn:li:person:amy",
                                                     "urn:li:comment:(urn:li:activity:10,103)"),
        "urn:li:comment:(urn:li:activity:10,105)": ("reply", "urn:li:share:1", "urn:li:person:bob", c1),
        "urn:li:comment:(urn:li:activity:10,106)": ("reply", "urn:li:share:1", "urn:li:person:zed", c2),
        "urn:li:share:900": ("mention", "urn:li:share:900", "urn:li:person:eve", "urn:li:share:900"),
        "urn:li:comment:(urn:li:activity:800,801)": ("mention", "urn:li:share:800", "urn:li:person:joe",
                                                     "urn:li:comment:(urn:li:activity:800,801)"),
    }
    assert all(i.reply_to["action"] == "comment" for i in items)
    first = next(i for i in items if i.id == c1)
    assert first.text == "Great (really)" and first.ts == 1000.0
    assert first.url == f"https://www.linkedin.com/feed/update/urn:li:activity:10/?commentUrn={q(c1)}"
    assert next(i for i in items if i.id == "urn:li:share:900").text == "Thanks @Acme #AI (yes)"
    assert state["since_ms"] == 1004000 and state["counts"] == {
        c1: 2, c2: 1, "urn:li:comment:(urn:li:activity:10,103)": 0}
    listing = [c for c in http.calls if c["url"] == R + "/posts"][0]
    assert listing["params"] == {"author": ORG, "q": "author", "count": 5, "sortBy": "LAST_MODIFIED"}
    note = http.last("GET", "organizationalEntityNotifications")["url"]
    assert "actions=List(SHARE_MENTION,COMMENT_MENTION)" in note and f"organizationalEntity={q(ORG)}" in note
    assert "timeRange=(start:" in note and state["mentions_ms"] > 0

    again = a.poll(state)
    assert {i.kind for i in again} == {"mention"}     # comments behind the cursor, unchanged threads not refetched
    assert len([c for c in http.calls if c["url"] == f"{R}/socialActions/{q(c1)}/comments"]) == 1
    start = int(note.split("timeRange=(start:")[1].split(",")[0])
    start2 = int(http.last("GET", "organizationalEntityNotifications")["url"].split("timeRange=(start:")[1]
                 .split(",")[0])
    assert start2 > start


def test_poll_mentions_can_be_disabled():
    a, http = make(author_urn=ORG, poll_mentions="false")
    http.add("GET", R + "/posts", {"elements": []})
    assert a.poll({}) == []
    assert not any("Notifications" in c["url"] for c in http.calls)


def test_little_text_round_trip():
    raw = "a_b *c* ~d~ \\ | {x} [y] <z> #tag_1 (#no)"
    esc = LinkedInAdapter._little(raw)
    assert esc == ("a\\_b \\*c\\* \\~d\\~ \\\\ \\| \\{x\\} \\[y\\] \\<z\\> {hashtag|\\#|tag\\_1} "
                   "\\({hashtag|\\#|no}\\)")
    assert LinkedInAdapter._plain(esc.replace("{hashtag|\\#|tag\\_1}", "#tag_1").replace(
        "{hashtag|\\#|no}", "#no")) == raw


def test_poll_defers_nested_fetches_over_budget_and_surfaces_them_next_poll():
    state, top = {}, [f"urn:li:comment:(urn:li:activity:10,{100 + i})" for i in range(30)]

    def run(total):
        a, http = make(author_urn=ORG, poll_mentions="false")
        http.add("GET", R + "/posts", {"elements": [{"id": "urn:li:share:1"}]})
        http.add("GET", f"{R}/socialActions/{q('urn:li:share:1')}/comments", {"elements": [
            comment(100 + i, f"urn:li:person:u{i}", 1000000 + i * 1000, total=total) for i in range(30)]})
        for i, curn in enumerate(top):
            replies = [comment(1000 + i, "urn:li:person:old", 1020000 - i, parent=curn)]
            if total == 2:
                replies.append(comment(2000 + i, "urn:li:person:new", 2000000 - i, parent=curn))
            http.add("GET", f"{R}/socialActions/{q(curn)}/comments", {"elements": replies})
        items = a.poll(state)
        nested = [c["url"] for c in http.calls if "comment%3A" in c["url"]]
        return [i for i in items if i.id not in top], nested   # top-level comments are covered elsewhere

    items, nested = run(1)                      # first poll: 25 nested lists fetched, 5 deferred
    assert len(nested) == 25 and len(state["counts"]) == 25 and state["pending"] == {}
    assert state["since_ms"] == 1029000
    items, nested = run(1)                      # the 5 deferred threads are fetched now
    assert nested == [f"{R}/socialActions/{q(c)}/comments" for c in top[25:]]
    assert items == [] and len(state["counts"]) == 30
    assert run(1)[1] == []                      # nothing changed: no nested fetches

    items, nested = run(2)                      # a new reply in every thread; budget covers 25 of them
    assert len(nested) == 25 and {i.id for i in items} == {
        f"urn:li:comment:(urn:li:activity:10,{2000 + i})" for i in range(25)}
    assert state["pending"] == {c: 1029000 for c in top[25:]}
    assert all(state["counts"][c] == 1 for c in top[25:]) and state["since_ms"] == 2000000

    items, nested = run(2)                      # deferred replies are older than the cursor but still returned
    assert nested == [f"{R}/socialActions/{q(c)}/comments" for c in top[25:]]
    assert [(i.id, i.kind, i.reply_to["target"]) for i in sorted(items, key=lambda i: i.id)] == [
        (f"urn:li:comment:(urn:li:activity:10,{2000 + i})", "comment", top[i]) for i in range(25, 30)]
    assert state["pending"] == {} and set(state["counts"].values()) == {2}
    assert run(2) == ([], [])
