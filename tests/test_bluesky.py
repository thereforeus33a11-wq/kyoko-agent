import base64
import json
import re
import time

import pytest

from social_bridge.adapters.bluesky import BlueskyAdapter
from social_bridge.base import PlatformError
from tests.fakehttp import FakeHttp

P = "https://bsky.social/xrpc/"
ME = "did:plc:me"
BOB = "did:plc:bob"
CHAT = "did:web:api.bsky.chat#bsky_chat"


def jwt(exp, jti):
    seg = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'ES256K'})}.{seg({'exp': int(exp), 'sub': ME, 'jti': jti})}.sig"


A1, R1 = jwt(time.time() + 7200, "a1"), jwt(time.time() + 86400, "r1")
A2, R2 = jwt(time.time() + 7200, "a2"), jwt(time.time() + 86400, "r2")
SESSION = {"accessJwt": A1, "refreshJwt": R1, "handle": "me.bsky.social", "did": ME}
SESSION2 = {"accessJwt": A2, "refreshJwt": R2, "handle": "me.bsky.social", "did": ME}
BLOB1 = {"$type": "blob", "ref": {"$link": "bafkrei1"}, "mimeType": "image/png", "size": 40}
BLOB2 = {"$type": "blob", "ref": {"$link": "bafkrei2"}, "mimeType": "image/jpeg", "size": 60}

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + (640).to_bytes(4, "big") + (480).to_bytes(4, "big") + b"\x08\x02" + b"\0" * 20


def jpeg(width, height, orientation=None):
    out = b"\xff\xd8"
    if orientation:
        tiff = b"II*\x00" + (8).to_bytes(4, "little") + (1).to_bytes(2, "little") + \
            (0x0112).to_bytes(2, "little") + (3).to_bytes(2, "little") + (1).to_bytes(4, "little") + \
            orientation.to_bytes(2, "little") + b"\0\0" + b"\0" * 4
        app1 = b"Exif\x00\x00" + tiff
        out += b"\xff\xe1" + (len(app1) + 2).to_bytes(2, "big") + app1
    sof = b"\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x03" + b"\x01\x22\x00" * 3
    return out + b"\xff\xc0" + (len(sof) + 2).to_bytes(2, "big") + sof + b"\xff\xda\0\x02" + b"\0" * 10


def make(**cfg):
    http = FakeHttp("bluesky")
    http.add("POST", P + "com.atproto.server.createSession", SESSION)
    conf = {"handle": "@me.bsky.social", "app_password": "abcd-efgh-ijkl-mnop", **cfg}
    return BlueskyAdapter(conf, http), http


def calls(http, nsid):
    return [c for c in http.calls if c["url"].endswith("/" + nsid)]


def span(text, sub):
    s = text.index(sub)
    return {"byteStart": len(text[:s].encode()), "byteEnd": len(text[:s + len(sub)].encode())}


def created(http):
    return http.last("POST", "com.atproto.repo.createRecord")["json"]


# --------------------------------------------------------------------------- session
def test_login_and_whoami():
    a, http = make()
    http.add("GET", P + "com.atproto.server.getSession", {"handle": "me.bsky.social", "did": ME})
    assert a.whoami() == "@me.bsky.social"
    login = http.calls[0]
    assert login["method"] == "POST" and login["url"] == P + "com.atproto.server.createSession"
    assert login["json"] == {"identifier": "me.bsky.social", "password": "abcd-efgh-ijkl-mnop"}
    assert "Authorization" not in login["headers"]
    assert http.last("GET")["headers"]["Authorization"] == f"Bearer {A1}"
    a.whoami()
    assert len(calls(http, "com.atproto.server.createSession")) == 1


def test_session_moves_to_pds_from_did_doc():
    http = FakeHttp("bluesky")
    doc = {"id": ME, "service": [{"id": "#atproto_pds", "type": "AtprotoPersonalDataServer",
                                  "serviceEndpoint": "https://morel.us-east.host.bsky.network"}]}
    http.add("POST", "https://pds.example/xrpc/com.atproto.server.createSession", {**SESSION, "didDoc": doc})
    http.add("GET", "https://morel.us-east.host.bsky.network/xrpc/com.atproto.server.getSession",
             {"handle": "me.bsky.social", "did": ME})
    a = BlueskyAdapter({"handle": "me.bsky.social", "app_password": "pw", "pds": "https://pds.example/"}, http)
    assert a.whoami() == "@me.bsky.social"


def test_refresh_on_expired_token_then_retry():
    a, http = make()
    http.add("GET", P + "com.atproto.server.getSession",
             (400, {"error": "ExpiredToken", "message": "Token has expired"}), {"handle": "me.bsky.social", "did": ME})
    http.add("POST", P + "com.atproto.server.refreshSession", SESSION2)
    assert a.whoami() == "@me.bsky.social"
    ref = http.last("POST", "refreshSession")
    assert ref["headers"]["Authorization"] == f"Bearer {R1}" and ref["json"] is None
    gets = calls(http, "com.atproto.server.getSession")
    assert [g["headers"]["Authorization"] for g in gets] == [f"Bearer {A1}", f"Bearer {A2}"]


def test_proactive_refresh_when_access_jwt_about_to_expire():
    http = FakeHttp("bluesky")
    http.add("POST", P + "com.atproto.server.createSession", {**SESSION, "accessJwt": jwt(time.time() + 10, "x")})
    http.add("POST", P + "com.atproto.server.refreshSession", SESSION2)
    http.add("GET", P + "com.atproto.server.getSession", {"handle": "me.bsky.social", "did": ME})
    a = BlueskyAdapter({"handle": "me.bsky.social", "app_password": "pw"}, http)
    a.whoami()
    assert not calls(http, "com.atproto.server.refreshSession")
    a.whoami()
    assert len(calls(http, "com.atproto.server.refreshSession")) == 1
    assert http.last("GET")["headers"]["Authorization"] == f"Bearer {A2}"


def test_failed_refresh_falls_back_to_new_login():
    http = FakeHttp("bluesky")
    http.add("POST", P + "com.atproto.server.createSession", SESSION, SESSION2)
    http.add("POST", P + "com.atproto.server.refreshSession", (400, {"error": "ExpiredToken", "message": "expired"}))
    http.add("GET", P + "com.atproto.server.getSession", (401, {"error": "InvalidToken", "message": "x"}),
             {"handle": "me.bsky.social", "did": ME})
    a = BlueskyAdapter({"handle": "me.bsky.social", "app_password": "pw"}, http)
    a.whoami()
    assert len(calls(http, "com.atproto.server.createSession")) == 2
    assert http.last("GET")["headers"]["Authorization"] == f"Bearer {A2}"


def test_bad_login_raises():
    http = FakeHttp("bluesky")
    http.add("POST", P + "com.atproto.server.createSession",
             (401, {"error": "AuthenticationRequired", "message": "Invalid identifier or password"}))
    a = BlueskyAdapter({"handle": "me.bsky.social", "app_password": "bad"}, http)
    with pytest.raises(PlatformError) as e:
        a.whoami()
    assert e.value.status == 401
    with pytest.raises(PlatformError):
        BlueskyAdapter({"handle": "x"}, FakeHttp()).whoami()


# --------------------------------------------------------------------------- post
def test_post_text_with_facets_and_langs():
    a, http = make(langs="en, de")
    http.add("GET", P + "com.atproto.identity.resolveHandle", {"did": BOB},
             (400, {"error": "InvalidRequest", "message": "Unable to resolve handle"}))
    http.add("POST", P + "com.atproto.repo.createRecord",
             {"uri": f"at://{ME}/app.bsky.feed.post/3kpost", "cid": "bafyp", "validationStatus": "valid"})
    text = "héllo @bob.test 👍🏽 see https://example.com/a_(b). and #News! (@nobody.test) mail x@y.com"
    r = a.post(text)
    c = http.last("POST", "createRecord")
    assert c["headers"]["Authorization"] == f"Bearer {A1}"
    body = c["json"]
    assert body["repo"] == ME and body["collection"] == "app.bsky.feed.post"
    rec = body["record"]
    assert rec["$type"] == "app.bsky.feed.post" and rec["text"] == text and rec["langs"] == ["en", "de"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", rec["createdAt"])
    assert "embed" not in rec and "reply" not in rec
    assert rec["facets"] == [
        {"index": span(text, "@bob.test"), "features": [{"$type": "app.bsky.richtext.facet#mention", "did": BOB}]},
        {"index": span(text, "https://example.com/a_(b)"),
         "features": [{"$type": "app.bsky.richtext.facet#link", "uri": "https://example.com/a_(b)"}]},
        {"index": span(text, "#News"), "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": "News"}]},
    ]
    assert [c["params"] for c in calls(http, "com.atproto.identity.resolveHandle")] == \
        [{"handle": "bob.test"}, {"handle": "nobody.test"}]
    assert r.id == f"at://{ME}/app.bsky.feed.post/3kpost"
    assert r.url == "https://bsky.app/profile/me.bsky.social/post/3kpost"


def test_post_title_becomes_first_line():
    a, http = make()
    http.add("POST", P + "com.atproto.repo.createRecord", {"uri": f"at://{ME}/app.bsky.feed.post/1", "cid": "c"})
    a.post("body", title="Headline")
    assert created(http)["record"]["text"] == "Headline\n\nbody"
    assert "langs" not in created(http)["record"] and "facets" not in created(http)["record"]


def test_grapheme_counting_and_length_limit():
    assert BlueskyAdapter._graphemes("👍🏽🇺🇸👨‍👩‍👧e\u0301\r\nab") == 7
    a, http = make()
    with pytest.raises(PlatformError, match="300"):
        a.post("a" * 301)
    with pytest.raises(PlatformError, match="1000"):
        a.dm("convo:x", "b" * 1001)
    assert http.calls == []
    http.add("POST", P + "com.atproto.repo.createRecord", {"uri": f"at://{ME}/app.bsky.feed.post/1", "cid": "c"})
    a.post("👍🏽" * 300)  # 300 graphemes, 2400 bytes: allowed
    assert created(http)["record"]["text"] == "👍🏽" * 300


def test_post_images_from_file_and_url_with_link(tmp_path):
    a, http = make()
    png = tmp_path / "chart.png"
    png.write_bytes(PNG)
    jpg = jpeg(200, 100, orientation=6)  # rotated 90 degrees: displayed 100x200
    http.add("GET", "https://img.test/p/photo.jpg", jpg)
    http.add("POST", P + "com.atproto.repo.uploadBlob", {"blob": BLOB1}, {"blob": BLOB2})
    http.add("POST", P + "com.atproto.repo.createRecord", {"uri": f"at://{ME}/app.bsky.feed.post/3kimg", "cid": "c"})
    r = a.post("pics", link="https://example.com", media=[str(png), "https://img.test/p/photo.jpg"])
    ups = calls(http, "com.atproto.repo.uploadBlob")
    assert [u["data"] for u in ups] == [PNG, jpg]
    assert [u["headers"]["Content-Type"] for u in ups] == ["image/png", "image/jpeg"]
    assert all(u["headers"]["Authorization"] == f"Bearer {A1}" for u in ups)
    rec = created(http)["record"]
    assert rec["text"] == "pics\n\nhttps://example.com"
    assert rec["facets"][0]["features"][0]["uri"] == "https://example.com"
    assert rec["embed"] == {"$type": "app.bsky.embed.images", "images": [
        {"alt": "", "image": BLOB1, "aspectRatio": {"width": 640, "height": 480}},
        {"alt": "", "image": BLOB2, "aspectRatio": {"width": 100, "height": 200}}]}
    assert r.url.endswith("/post/3kimg")


def test_post_video(tmp_path):
    a, http = make()
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\0" * 40
    f = tmp_path / "clip.mp4"
    f.write_bytes(mp4)
    vblob = {"$type": "blob", "ref": {"$link": "bafv"}, "mimeType": "video/mp4", "size": len(mp4)}
    http.add("POST", P + "com.atproto.repo.uploadBlob", {"blob": vblob})
    http.add("POST", P + "com.atproto.repo.createRecord", {"uri": f"at://{ME}/app.bsky.feed.post/v", "cid": "c"})
    a.post("watch", media=str(f))
    up = http.last("POST", "uploadBlob")
    assert up["data"] == mp4 and up["headers"]["Content-Type"] == "video/mp4"
    assert created(http)["record"]["embed"] == {"$type": "app.bsky.embed.video", "video": vblob}


def test_media_errors(tmp_path):
    a, http = make()
    png = tmp_path / "a.png"
    png.write_bytes(PNG)
    with pytest.raises(PlatformError, match="at most 4"):
        a.post("x", media=[str(png)] * 5)
    big = tmp_path / "big.png"
    big.write_bytes(PNG + b"\0" * 1000001)
    with pytest.raises(PlatformError, match="limit"):
        a.post("x", media=[str(big)])
    mov = tmp_path / "m.mov"
    mov.write_bytes(b"\x00\x00\x00\x14ftypqt  " + b"\0" * 20)
    with pytest.raises(PlatformError, match="MP4"):
        a.post("x", media=[str(mov)])
    mp4 = tmp_path / "m.mp4"
    mp4.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\0" * 20)
    with pytest.raises(PlatformError, match="one video"):
        a.post("x", media=[str(mp4), str(png)])
    with pytest.raises(PlatformError, match="can't read media"):
        a.post("x", media=[str(tmp_path / "missing.png")])
    assert not calls(http, "com.atproto.repo.uploadBlob")


def test_post_link_card_from_open_graph():
    a, http = make()
    page = (b'<html><head><title>Fallback</title><meta property="og:title" content="A &amp; B">'
            b"<meta content='Short desc' name='description'><meta property=\"og:image\" content=\"/img/card.png\">"
            b"</head></html>")
    http.add("GET", "https://news.test/story", page)
    http.add("GET", "https://news.test/img/card.png", PNG)
    http.add("POST", P + "com.atproto.repo.uploadBlob", {"blob": BLOB1})
    http.add("POST", P + "com.atproto.repo.createRecord", {"uri": f"at://{ME}/app.bsky.feed.post/l", "cid": "c"})
    a.post("read this", link="https://news.test/story")
    rec = created(http)["record"]
    assert rec["text"] == "read this"
    assert rec["embed"] == {"$type": "app.bsky.embed.external", "external": {
        "uri": "https://news.test/story", "title": "A & B", "description": "Short desc", "thumb": BLOB1}}
    assert http.last("POST", "uploadBlob")["headers"]["Content-Type"] == "image/png"


def test_post_link_card_when_page_unreachable_uses_title():
    a, http = make()
    http.add("GET", "https://down.test/x", (404, "nope"))
    http.add("POST", P + "com.atproto.repo.createRecord", {"uri": f"at://{ME}/app.bsky.feed.post/l", "cid": "c"})
    a.post("look", link="https://down.test/x", title="My title")
    assert created(http)["record"]["embed"]["external"] == {
        "uri": "https://down.test/x", "title": "My title", "description": ""}
    assert created(http)["record"]["text"] == "look"


def test_image_size_formats():
    gif = b"GIF89a" + (30).to_bytes(2, "little") + (20).to_bytes(2, "little") + b"\0" * 10
    vp8x = b"RIFF\0\0\0\0WEBPVP8X" + b"\0" * 8 + (99).to_bytes(3, "little") + (49).to_bytes(3, "little")
    assert BlueskyAdapter._image_size(gif) == (30, 20)
    assert BlueskyAdapter._image_size(vp8x) == (100, 50)
    assert BlueskyAdapter._image_size(jpeg(300, 150)) == (300, 150)
    assert BlueskyAdapter._image_size(b"garbage") is None


# --------------------------------------------------------------------------- comment
def test_comment_on_url_replies_in_thread():
    a, http = make()
    parent = f"at://{BOB}/app.bsky.feed.post/3kparent"
    root = "at://did:plc:carol/app.bsky.feed.post/3kroot"
    http.add("GET", P + "com.atproto.identity.resolveHandle", {"did": BOB})
    http.add("GET", P + "app.bsky.feed.getPosts", {"posts": [{
        "uri": parent, "cid": "cidP", "author": {"did": BOB, "handle": "bob.test"},
        "record": {"text": "q", "reply": {"root": {"uri": root, "cid": "cidR"}, "parent": {"uri": root, "cid": "cidR"}}},
        "viewer": {}}]})
    http.add("POST", P + "com.atproto.repo.createRecord", {"uri": f"at://{ME}/app.bsky.feed.post/3kre", "cid": "c"})
    r = a.comment("https://bsky.app/profile/bob.test/post/3kparent?ref_src=embed", "agreed")
    assert http.last("GET", "resolveHandle")["params"] == {"handle": "bob.test"}
    assert http.last("GET", "getPosts")["params"] == {"uris": [parent]}
    rec = created(http)["record"]
    assert rec["text"] == "agreed"
    assert rec["reply"] == {"root": {"uri": root, "cid": "cidR"}, "parent": {"uri": parent, "cid": "cidP"}}
    assert r.id == f"at://{ME}/app.bsky.feed.post/3kre" and r.url == "https://bsky.app/profile/me.bsky.social/post/3kre"


def test_comment_on_at_uri_top_level_post_and_did_url():
    a, http = make()
    uri = f"at://{BOB}/app.bsky.feed.post/3ktop"
    http.add("GET", P + "app.bsky.feed.getPosts", {"posts": [{"uri": uri, "cid": "cidT", "record": {"text": "t"}}]})
    http.add("POST", P + "com.atproto.repo.createRecord", {"uri": f"at://{ME}/app.bsky.feed.post/x", "cid": "c"})
    a.comment(uri, "hi")
    assert created(http)["record"]["reply"] == {"root": {"uri": uri, "cid": "cidT"}, "parent": {"uri": uri, "cid": "cidT"}}
    a.comment(f"https://bsky.app/profile/{BOB}/post/3ktop", "again")
    assert http.last("GET", "getPosts")["params"] == {"uris": [uri]}
    assert not calls(http, "com.atproto.identity.resolveHandle")


def test_comment_falls_back_to_get_record_and_rejects_bad_target():
    a, http = make()
    uri = f"at://{BOB}/app.bsky.feed.post/3knew"
    http.add("GET", P + "app.bsky.feed.getPosts", {"posts": []})
    http.add("GET", P + "com.atproto.repo.getRecord", {"uri": uri, "cid": "cidN", "value": {"text": "n"}})
    http.add("POST", P + "com.atproto.repo.createRecord", {"uri": f"at://{ME}/app.bsky.feed.post/x", "cid": "c"})
    a.comment(uri, "first")
    assert http.last("GET", "getRecord")["params"] == {"repo": BOB, "collection": "app.bsky.feed.post", "rkey": "3knew"}
    assert created(http)["record"]["reply"]["parent"] == {"uri": uri, "cid": "cidN"}
    with pytest.raises(PlatformError, match="can't read a post"):
        a.comment("https://bsky.app/profile/bob.test", "x")


def test_comment_reply_restricted():
    a, http = make()
    uri = f"at://{BOB}/app.bsky.feed.post/3kgate"
    http.add("GET", P + "app.bsky.feed.getPosts",
             {"posts": [{"uri": uri, "cid": "c", "record": {}, "viewer": {"replyDisabled": True}}]})
    with pytest.raises(PlatformError, match="restricted"):
        a.comment(uri, "hi")
    assert not calls(http, "com.atproto.repo.createRecord")


# --------------------------------------------------------------------------- dm
def test_dm_to_handle_goes_through_chat_proxy():
    a, http = make()
    http.add("GET", P + "com.atproto.identity.resolveHandle", {"did": BOB})
    http.add("GET", P + "chat.bsky.convo.getConvoForMembers", {"convo": {"id": "cv1", "rev": "r1"}})
    http.add("POST", P + "chat.bsky.convo.sendMessage", {"id": "msg1", "rev": "r2", "text": "x"})
    text = "hi, see https://x.test/a"
    r = a.dm("@bob.test", text)
    g = http.last("GET", "getConvoForMembers")
    assert g["params"] == {"members": [BOB]}
    assert g["headers"]["atproto-proxy"] == CHAT and g["headers"]["Authorization"] == f"Bearer {A1}"
    s = http.last("POST", "sendMessage")
    assert s["headers"]["atproto-proxy"] == CHAT
    assert s["json"] == {"convoId": "cv1", "message": {"text": text, "facets": [
        {"index": span(text, "https://x.test/a"),
         "features": [{"$type": "app.bsky.richtext.facet#link", "uri": "https://x.test/a"}]}]}}
    assert r.id == "msg1" and r.url == "https://bsky.app/messages/cv1"


def test_dm_target_forms():
    a, http = make()
    http.add("GET", P + "com.atproto.identity.resolveHandle", {"did": "did:plc:al"})
    http.add("GET", P + "chat.bsky.convo.getConvoForMembers", {"convo": {"id": "cvX"}})
    http.add("POST", P + "chat.bsky.convo.sendMessage", {"id": "m"})
    a.dm("convo:abc123", "yo")
    assert http.last("POST", "sendMessage")["json"]["convoId"] == "abc123"
    a.dm("https://bsky.app/messages/xyz789", "yo")
    assert http.last("POST", "sendMessage")["json"]["convoId"] == "xyz789"
    assert not calls(http, "chat.bsky.convo.getConvoForMembers")
    a.dm("https://bsky.app/profile/did:plc:carol", "yo")
    assert http.last("GET", "getConvoForMembers")["params"] == {"members": ["did:plc:carol"]}
    a.dm("al", "yo")
    assert http.last("GET", "resolveHandle")["params"] == {"handle": "al.bsky.social"}
    assert http.last("GET", "getConvoForMembers")["params"] == {"members": ["did:plc:al"]}
    a.dm("al.bsky.social", "again")  # cached
    assert len(calls(http, "com.atproto.identity.resolveHandle")) == 1


def test_dm_without_chat_scope_gives_clear_error():
    a, http = make()
    http.add("POST", P + "chat.bsky.convo.sendMessage", (400, {"error": "InvalidToken", "message": "Bad token method"}))
    with pytest.raises(PlatformError, match="direct messages"):
        a.dm("convo:abc", "hi")
    assert not calls(http, "com.atproto.server.refreshSession")


# --------------------------------------------------------------------------- poll
def note(uri, reason, at, author=BOB, handle="bob.test", reply=None, text="hey"):
    rec = {"$type": "app.bsky.feed.post", "text": text, "createdAt": at}
    if reply:
        rec["reply"] = {"root": {"uri": reply[0], "cid": "c0"}, "parent": {"uri": reply[1], "cid": "c1"}}
    return {"uri": uri, "cid": "cx", "reason": reason, "indexedAt": at, "isRead": False, "record": rec,
            "author": {"did": author, "handle": handle}}


def log_msg(rev, mid, sender, text="hello", convo="cv1", at="2026-11-18T10:03:00.000Z", deleted=False):
    msg = {"$type": "chat.bsky.convo.defs#" + ("deletedMessageView" if deleted else "messageView"), "id": mid,
           "rev": rev, "sender": {"did": sender}, "sentAt": at}
    if not deleted:
        msg["text"] = text
    return {"$type": "chat.bsky.convo.defs#logCreateMessage", "rev": rev, "convoId": convo, "message": msg}


def test_poll_kinds_threads_reply_to_and_cursors():
    a, http = make()
    post = lambda did, rk: f"at://{did}/app.bsky.feed.post/{rk}"
    my_top, my_reply, other_root = post(ME, "top"), post(ME, "myre"), post("did:plc:carol", "root")
    page1 = {"cursor": "c1", "notifications": [
        note(post(BOB, "n5"), "reply", "2026-11-18T10:05:00.000Z", reply=(other_root, my_reply)),
        note(post(BOB, "n4"), "reply", "2026-11-18T10:04:00.000Z", reply=(my_top, my_top)),
        note(post(ME, "n3"), "mention", "2026-11-18T10:03:30.000Z", author=ME, handle="me.bsky.social"),
        note(post("did:plc:dave", "n2"), "quote", "2026-11-18T10:02:00.000Z", author="did:plc:dave",
             handle="dave.test"),
        note(post("did:plc:erin", "n1"), "mention", "2026-11-18T10:01:00.000Z", author="did:plc:erin",
             handle="handle.invalid"),
    ]}
    page2 = {"cursor": "c2", "notifications": [
        note(post(BOB, "n0"), "mention", "2026-11-18T10:00:00.000Z", reply=(other_root, other_root)),
        # older than notif_at but inside the 15-minute overlap window (late-indexed): still returned
        note(post(BOB, "late"), "mention", "2026-11-18T09:45:00.000Z"),
        # older than the overlap window: dropped, and paging stops here
        note(post(BOB, "old"), "mention", "2026-11-18T09:44:59.000Z"),
    ]}
    page3 = {"cursor": "c3", "notifications": [note(post(BOB, "older"), "mention", "2026-11-18T09:00:00.000Z")]}
    http.add("GET", P + "app.bsky.notification.listNotifications", page1, page2, page3)
    http.add("GET", P + "chat.bsky.convo.getLog", {"cursor": "rev105", "logs": [
        log_msg("rev100", "m0", BOB),
        log_msg("rev101", "m1", BOB, text="hello there"),
        log_msg("rev102", "m2", ME, text="mine"),
        {"$type": "chat.bsky.convo.defs#logDeleteMessage", "rev": "rev103", "convoId": "cv1",
         "message": {"id": "m1", "rev": "rev103", "sender": {"did": BOB}}},
        log_msg("rev104", "m4", BOB, deleted=True),
        {"$type": "chat.bsky.convo.defs#logReadMessage", "rev": "rev105", "convoId": "cv1"},
    ]})
    http.add("GET", P + "app.bsky.actor.getProfiles", {"profiles": [{"did": BOB, "handle": "bob.test"}]})
    state = {"notif_at": "2026-11-18T10:00:00.000Z", "chat_rev": "rev100"}
    items = a.poll(state)

    assert [(i.kind, i.id) for i in items] == [
        ("mention", post(BOB, "late")), ("mention", post(BOB, "n0")), ("mention", post("did:plc:erin", "n1")),
        ("mention", post("did:plc:dave", "n2")), ("dm", "m1"),
        ("comment", post(BOB, "n4")), ("reply", post(BOB, "n5"))]
    by_id = {i.id: i for i in items}
    n5, n4, n2, n1, dm = by_id[post(BOB, "n5")], by_id[post(BOB, "n4")], by_id[post("did:plc:dave", "n2")], \
        by_id[post("did:plc:erin", "n1")], by_id["m1"]
    assert n5.thread == other_root and n5.author == "@bob.test" and n5.author_id == BOB
    assert n5.reply_to == {"action": "comment", "target": post(BOB, "n5")}
    assert n5.url == "https://bsky.app/profile/bob.test/post/n5" and n5.text == "hey"
    assert n5.ts == BlueskyAdapter._ts("2026-11-18T10:05:00.000Z") > 0
    assert n4.thread == my_top and n2.thread == post("did:plc:dave", "n2")
    assert n1.author == "@did:plc:erin" and n1.url == "https://bsky.app/profile/did:plc:erin/post/n1"
    assert dm.thread == "cv1" and dm.author == "@bob.test" and dm.author_id == BOB and dm.text == "hello there"
    assert dm.reply_to == {"action": "dm", "target": "convo:cv1"} and dm.url == "https://bsky.app/messages/cv1"
    assert dm.ts == BlueskyAdapter._ts("2026-11-18T10:03:00.000Z")

    ln = calls(http, "app.bsky.notification.listNotifications")
    assert ln[0]["params"] == {"limit": 50, "reasons": ["mention", "reply", "quote"]}
    assert ln[1]["params"]["cursor"] == "c1" and len(ln) == 2
    log = http.last("GET", "getLog")
    assert log["params"] == {"cursor": "rev100"} and log["headers"]["atproto-proxy"] == CHAT
    assert http.last("GET", "getProfiles")["params"] == {"actors": [BOB]}
    assert state == {"notif_at": "2026-11-18T10:05:00.000Z", "chat_rev": "rev105"}
    assert json.loads(json.dumps(state)) == state


def test_poll_returns_late_indexed_notification_behind_cursor():
    a, http = make(poll_dms="false")
    b_uri, a_uri = "at://did:plc:bob/app.bsky.feed.post/b", "at://did:plc:bob/app.bsky.feed.post/a"
    first = {"notifications": [note(b_uri, "mention", "2026-11-18T10:05:01.000Z")]}
    # A sorts after B because its sortAt (min of createdAt and index time) is earlier
    second = {"notifications": [note(b_uri, "mention", "2026-11-18T10:05:01.000Z"),
                                note(a_uri, "mention", "2026-11-18T10:04:59.000Z")]}
    http.add("GET", P + "app.bsky.notification.listNotifications", first, second)
    state = {"notif_at": "2026-11-18T10:00:00.000Z"}
    assert [i.id for i in a.poll(state)] == [b_uri]
    assert state == {"notif_at": "2026-11-18T10:05:01.000Z"}
    items = a.poll(state)
    assert [i.id for i in items] == [a_uri, b_uri]          # B is a repeat; the bridge drops it by id
    assert state == {"notif_at": "2026-11-18T10:05:01.000Z"}


def test_first_poll_primes_cursors_and_second_poll_uses_them():
    a, http = make()
    http.add("GET", P + "chat.bsky.convo.getLog", {"cursor": "rev09", "logs": []},
             {"cursor": "rev10", "logs": [log_msg("rev10", "m10", BOB)]})
    http.add("GET", P + "app.bsky.notification.listNotifications",
             {"cursor": "c1", "notifications": [note("at://did:plc:bob/app.bsky.feed.post/a", "mention",
                                                     "2026-11-18T09:00:00.000Z")]},
             {"notifications": []})
    http.add("GET", P + "app.bsky.actor.getProfiles", {"profiles": [{"did": BOB, "handle": "bob.test"}]})
    state = {}
    a.poll(state)
    assert http.last("GET", "getLog")["params"] == {}
    assert len(calls(http, "app.bsky.notification.listNotifications")) == 1
    assert state == {"chat_rev": "rev09", "notif_at": "2026-11-18T09:00:00.000Z"}
    items = a.poll(state)
    assert http.last("GET", "getLog")["params"] == {"cursor": "rev09"}
    assert [(i.kind, i.id) for i in items] == [("dm", "m10")]
    assert state == {"chat_rev": "rev10", "notif_at": "2026-11-18T09:00:00.000Z"}


def test_poll_without_dms_and_cursor_not_committed_on_failure():
    a, http = make(poll_dms="false")
    http.add("GET", P + "app.bsky.notification.listNotifications", {"notifications": []})
    state = {}
    assert a.poll(state) == []
    assert not calls(http, "chat.bsky.convo.getLog")

    b, http2 = make()
    http2.add("GET", P + "chat.bsky.convo.getLog", {"cursor": "rev2", "logs": [log_msg("rev2", "m2", BOB)]})
    http2.add("GET", P + "app.bsky.actor.getProfiles", {"profiles": []})
    http2.add("GET", P + "app.bsky.notification.listNotifications", (502, "bad gateway"))
    state = {"chat_rev": "rev1"}
    with pytest.raises(PlatformError):
        b.poll(state)
    assert state == {"chat_rev": "rev1"}
