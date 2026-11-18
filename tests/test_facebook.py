import base64
import hashlib
import hmac
import json

import pytest

from social_bridge.adapters.facebook import FacebookAdapter
from social_bridge.base import PlatformError
from tests.fakehttp import FakeHttp

G = "https://graph.facebook.com/v24.0"
GV = "https://graph-video.facebook.com/v24.0"
PAGE = "111"


def make(**cfg):
    http = FakeHttp("facebook")
    conf = {"page_id": PAGE, "page_access_token": "ptok"}
    conf.update(cfg)
    return FacebookAdapter({k: v for k, v in conf.items() if v is not None}, http), http


def test_whoami_discovers_page_from_page_token():
    a, http = make(page_id=None)
    http.add("GET", G + "/me", {"id": PAGE, "name": "My Page", "username": "mypage"})
    assert a.whoami() == "My Page (@mypage)"
    c = http.last("GET")
    assert c["params"] == {"fields": "id,name,username"}
    assert c["headers"]["Authorization"] == "Bearer ptok"
    assert a._page_id() == PAGE and len(http.calls) == 1


def test_post_text_title_and_link():
    a, http = make()
    http.add("POST", G + f"/{PAGE}/feed", {"id": f"{PAGE}_222"})
    r = a.post("hello", title="Title", link="https://example.com")
    c = http.last("POST")
    assert c["json"] == {"message": "Title\n\nhello", "link": "https://example.com"}
    assert c["headers"]["Authorization"] == "Bearer ptok" and c["params"] is None
    assert r.id == f"{PAGE}_222" and r.url == f"https://www.facebook.com/{PAGE}/posts/222"


def test_appsecret_proof_is_sent():
    a, http = make(app_secret="sec")
    http.add("POST", G + f"/{PAGE}/feed", {"id": f"{PAGE}_1"})
    a.post("x")
    proof = hmac.new(b"sec", b"ptok", hashlib.sha256).hexdigest()
    assert http.last("POST")["params"] == {"appsecret_proof": proof}


def test_post_single_photo_url_and_local_file(tmp_path):
    a, http = make()
    http.add("POST", G + f"/{PAGE}/photos", {"id": "900", "post_id": f"{PAGE}_901"},
             {"id": "902", "post_id": f"{PAGE}_903"})
    r = a.post("pic", media=["https://cdn.test/a.jpg"], link="https://l.test")
    c = http.last("POST")
    assert c["data"] == {"published": "true", "caption": "pic\n\nhttps://l.test", "url": "https://cdn.test/a.jpg"}
    assert c["files"] is None and r.id == f"{PAGE}_901"
    img = tmp_path / "b.png"
    img.write_bytes(b"PNGDATA")
    r = a.post("local", media=[str(img)])
    c = http.last("POST")
    assert c["data"] == {"published": "true", "caption": "local"}
    assert c["files"] == {"source": ("b.png", b"PNGDATA", "image/png")}
    assert r.url == f"https://www.facebook.com/{PAGE}/posts/903"


def test_post_multiple_photos_uses_attached_media():
    a, http = make()
    http.add("POST", G + f"/{PAGE}/photos", {"id": "1"}, {"id": "2"})
    http.add("POST", G + f"/{PAGE}/feed", {"id": f"{PAGE}_9"})
    r = a.post("two", media=["https://c.test/1.jpg", "https://c.test/2.jpg"])
    uploads = [c for c in http.calls if c["url"].endswith("/photos")]
    assert [u["data"]["published"] for u in uploads] == ["false", "false"]
    assert "caption" not in uploads[0]["data"]
    assert http.last("POST", "/feed")["json"] == {"message": "two",
                                                  "attached_media": [{"media_fbid": "1"}, {"media_fbid": "2"}]}
    assert r.id == f"{PAGE}_9"


def test_post_video_goes_to_graph_video_host(tmp_path):
    a, http = make()
    http.add("POST", GV + f"/{PAGE}/videos", {"id": "77"}, {"id": "78"})
    r = a.post("watch", title="My video", media=["https://c.test/v.mp4?sig=1"])
    c = http.last("POST")
    assert c["data"] == {"description": "watch", "title": "My video", "file_url": "https://c.test/v.mp4?sig=1"}
    assert r.url == f"https://www.facebook.com/{PAGE}/videos/77"
    vid = tmp_path / "clip.mov"
    vid.write_bytes(b"MOV")
    a.post("", media=[str(vid)])
    c = http.last("POST")
    assert c["files"]["source"][:2] == ("clip.mov", b"MOV") and c["data"] == {}


def test_post_rejects_mixed_video_and_foreign_target_and_missing_file():
    a, http = make()
    with pytest.raises(PlatformError, match="on its own"):
        a.post("x", media=["https://c.test/v.mp4", "https://c.test/p.jpg"])
    http.add("GET", G + "/otherpage", {"id": "999"})
    with pytest.raises(PlatformError, match="configured Page"):
        a.post("x", target="https://www.facebook.com/otherpage")
    with pytest.raises(PlatformError, match="not found"):
        a.post("x", media=["/no/such/file.jpg"])


def test_post_target_own_page_is_accepted():
    a, http = make()
    http.add("POST", G + f"/{PAGE}/feed", {"id": f"{PAGE}_5"})
    a.post("x", target=f"https://www.facebook.com/profile.php?id={PAGE}")
    a.post("y", target=PAGE)
    assert len(http.calls) == 2


@pytest.mark.parametrize("target,obj", [
    (f"{PAGE}_222", f"{PAGE}_222"),
    ("222_333", "222_333"),
    ("444", "444"),
    (f"https://www.facebook.com/permalink.php?story_fbid=222&id={PAGE}", f"{PAGE}_222"),
    (f"https://m.facebook.com/story.php?story_fbid=222&id={PAGE}", f"{PAGE}_222"),
    (f"https://www.facebook.com/{PAGE}/posts/222/", f"{PAGE}_222"),
    ("https://www.facebook.com/photo/?fbid=555&set=a.1", "555"),
    ("https://www.facebook.com/photo.php?fbid=555", "555"),
    ("https://www.facebook.com/watch/?v=666", "666"),
    ("https://www.facebook.com/reel/777", "777"),
    ("https://www.facebook.com/mypage/videos/some-title/888/", "888"),
    ("https://www.facebook.com/mypage/photos/a.12/999/", "999"),
    (f"https://www.facebook.com/{PAGE}/posts/222?comment_id=333", "222_333"),
    (f"https://www.facebook.com/{PAGE}/posts/222?comment_id=333&reply_comment_id=444", "222_333"),
    ("https://www.facebook.com/photo?fbid=555&comment_id=" +
     base64.b64encode(b"comment:555_666").decode().rstrip("="), "555_666"),
])
def test_comment_target_parsing(target, obj):
    a, http = make()
    http.add("POST", f"re:^{G}/[0-9_]+/comments$", {"id": "x_1"})
    a.comment(target, "hi")
    c = http.last("POST")
    assert c["url"] == f"{G}/{obj}/comments" and c["json"] == {"message": "hi"}


def test_comment_vanity_page_url_and_pfbid_lookup():
    a, http = make()
    http.add("GET", G + "/mypage", {"id": PAGE})
    http.add("GET", G + f"/{PAGE}/feed", {"data": [
        {"id": f"{PAGE}_1", "permalink_url": "https://www.facebook.com/mypage/posts/pfbid0zzz"},
        {"id": f"{PAGE}_2", "permalink_url": "https://www.facebook.com/mypage/posts/pfbid0abc"}]})
    http.add("POST", f"re:^{G}/[0-9_]+/comments$", {"id": "222_5"})
    a.comment("https://www.facebook.com/mypage/posts/222", "a")
    assert http.last("POST")["url"] == f"{G}/{PAGE}_222/comments"
    a.comment("https://www.facebook.com/mypage/posts/pfbid0abc?comment_id=7", "b")
    assert http.last("POST")["url"] == f"{G}/2_7/comments"
    assert http.last("GET", "/feed")["params"] == {"fields": "id,permalink_url", "limit": 100}
    with pytest.raises(PlatformError):
        a.comment("https://www.facebook.com/share/p/abc/", "c")
    with pytest.raises(PlatformError):
        a.comment("not a target", "c")


def test_comment_result_urls():
    a, http = make()
    http.add("POST", G + f"/{PAGE}_222/comments", {"id": "222_333"})
    http.add("POST", G + "/222_333/comments", {"id": "222_444"})
    r = a.comment(f"{PAGE}_222", "top")
    assert r.id == "222_333" and r.url == f"https://www.facebook.com/{PAGE}/posts/222?comment_id=333"
    r = a.comment("222_333", "reply")
    assert r.url == f"https://www.facebook.com/{PAGE}/posts/222?comment_id=333&reply_comment_id=444"


def test_dm_send_api_body_and_message_tag():
    a, http = make()
    http.add("POST", G + f"/{PAGE}/messages", {"recipient_id": "42", "message_id": "m_1"})
    r = a.dm("42", "hey")
    c = http.last("POST")
    assert c["json"] == {"recipient": {"id": "42"}, "messaging_type": "RESPONSE", "message": {"text": "hey"}}
    assert c["headers"]["Authorization"] == "Bearer ptok" and r.id == "m_1"
    a2, http2 = make(message_tag="HUMAN_AGENT")
    http2.add("POST", G + f"/{PAGE}/messages", {"message_id": "m_2"})
    a2.dm("42", "later")
    assert http2.last("POST")["json"] == {"recipient": {"id": "42"}, "messaging_type": "MESSAGE_TAG",
                                          "message": {"text": "later"}, "tag": "HUMAN_AGENT"}


def test_dm_to_conversation_id_resolves_participant():
    a, http = make()
    http.add("GET", G + "/t_123", {"participants": {"data": [{"id": PAGE, "name": "Me"}, {"id": "42", "name": "Bob"}]}})
    http.add("POST", G + f"/{PAGE}/messages", {"message_id": "m_3"})
    a.dm("t_123", "yo")
    assert http.last("GET")["params"] == {"fields": "participants"}
    assert http.last("POST")["json"]["recipient"] == {"id": "42"}
    with pytest.raises(PlatformError):
        a.dm("https://www.facebook.com/bob", "x")


def test_page_token_derived_from_user_token_and_refreshed_on_190():
    a, http = make(page_access_token=None, user_access_token="utok", app_id="app", app_secret="sec")
    http.add("GET", G + "/oauth/access_token", {"access_token": "long_u"}, {"access_token": "long_u2"})
    http.add("GET", G + f"/{PAGE}", {"access_token": "p1"}, {"access_token": "p2"})
    expired = (400, {"error": {"message": "Session has expired", "type": "OAuthException", "code": 190}})
    http.add("POST", G + f"/{PAGE}/feed", expired, {"id": f"{PAGE}_1"})
    r = a.post("hi")
    ex = http.calls[0]
    assert ex["params"] == {"grant_type": "fb_exchange_token", "client_id": "app", "client_secret": "sec",
                            "fb_exchange_token": "utok"}
    derive = http.calls[1]
    assert derive["headers"]["Authorization"] == "Bearer long_u" and derive["params"]["fields"] == "access_token"
    posts = [c for c in http.calls if c["method"] == "POST"]
    assert [p["headers"]["Authorization"] for p in posts] == ["Bearer p1", "Bearer p2"]
    assert posts[1]["params"]["appsecret_proof"] == hmac.new(b"sec", b"p2", hashlib.sha256).hexdigest()
    assert r.id == f"{PAGE}_1"


def test_auth_error_without_user_token_is_raised():
    a, http = make()
    http.add("POST", G + f"/{PAGE}/feed", (400, {"error": {"code": 190, "message": "bad"}}))
    with pytest.raises(PlatformError) as e:
        a.post("x")
    assert e.value.status == 400 and len(http.calls) == 1


def test_missing_token_config():
    a, _ = make(page_access_token=None)
    with pytest.raises(PlatformError, match="missing config: page_access_token"):
        a.post("x")


def _feeds():
    convs = {"data": [
        {"id": "t_1", "updated_time": "2026-11-18T10:05:00+0000", "messages": {"data": [
            {"id": "m_3", "message": "thanks", "from": {"id": PAGE, "name": "My Page"},
             "created_time": "2026-11-18T10:05:00+0000"},
            {"id": "m_2", "message": "hello page", "from": {"id": "42", "name": "Bob"},
             "created_time": "2026-11-18T10:04:00+0000"},
            {"id": "m_1", "message": "old", "from": {"id": "42", "name": "Bob"},
             "created_time": "2026-11-18T09:00:00+0000"}]}},
        {"id": "t_2", "updated_time": "2026-11-18T08:00:00+0000", "messages": {"data": [
            {"id": "m_0", "from": {"id": "43", "name": "Amy"}, "created_time": "2026-11-18T08:00:00+0000"}]}},
    ]}
    feed = {"data": [{"id": f"{PAGE}_222", "permalink_url": "https://fb/p/222",
                      "updated_time": "2026-11-18T10:06:00+0000",
                      "comments": {"data": [
                          {"id": "222_5", "from": {"id": "42", "name": "Bob"}, "message": "reply to you",
                           "created_time": "2026-11-18T10:06:00+0000",
                           "parent": {"id": "222_3", "from": {"id": PAGE, "name": "My Page"}}},
                          {"id": "222_4", "from": {"id": PAGE, "name": "My Page"}, "message": "mine",
                           "created_time": "2026-11-18T10:03:00+0000"},
                          {"id": "222_3", "from": {"id": "44", "name": "Cy"}, "message": "nice post",
                           "created_time": "2026-11-18T10:02:00+0000", "permalink_url": "https://fb/c/3"},
                          {"id": "222_6", "from": {"id": "45", "name": "Di"}, "message": "me too",
                           "created_time": "2026-11-18T10:02:30+0000", "parent": {"id": "222_3", "from": {"id": "44"}}},
                      ]}}]}
    tagged = {"data": [{"id": "999_1", "message": "shoutout @My Page", "from": {"id": "999", "name": "Other Page"},
                        "created_time": "2026-11-18T10:01:00+0000", "permalink_url": "https://fb/t/1"}]}
    return convs, feed, tagged


def test_poll_kinds_threads_reply_to_and_cursor():
    a, http = make()
    convs, feed, tagged = _feeds()
    http.add("GET", G + f"/{PAGE}/conversations", convs)
    http.add("GET", G + f"/{PAGE}/feed", feed)
    http.add("GET", G + f"/{PAGE}/tagged", tagged)
    state = {}
    items = a.poll(state)
    by_id = {i.id: i for i in items}
    assert set(by_id) == {"m_2", "m_1", "m_0", "222_5", "222_3", "222_6", "999_1"}   # own m_3 / 222_4 filtered
    assert [i.ts for i in items] == sorted(i.ts for i in items)
    dm = by_id["m_2"]
    assert (dm.kind, dm.thread, dm.author, dm.author_id) == ("dm", "t_1", "Bob", "42")
    assert dm.reply_to == {"action": "dm", "target": "42"} and dm.text == "hello page"
    assert by_id["m_0"].text == "[attachment]"
    rep = by_id["222_5"]
    assert rep.kind == "reply" and rep.thread == f"{PAGE}_222"
    assert rep.reply_to == {"action": "comment", "target": "222_3"}
    assert rep.url == f"https://www.facebook.com/{PAGE}/posts/222?comment_id=5"
    top = by_id["222_3"]
    assert top.kind == "comment" and top.reply_to == {"action": "comment", "target": "222_3"}
    assert top.url == "https://fb/c/3" and top.author == "Cy"
    assert by_id["222_6"].kind == "comment" and by_id["222_6"].reply_to["target"] == "222_3"
    men = by_id["999_1"]
    assert men.kind == "mention" and men.reply_to == {"action": "comment", "target": "999_1"}
    assert men.thread == "999_1" and men.url == "https://fb/t/1"
    conv_call = http.last("GET", "/conversations")
    assert conv_call["params"]["platform"] == "messenger" and "messages.limit(10)" in conv_call["params"]["fields"]
    assert "filter(stream)" in http.last("GET", "/feed")["params"]["fields"]
    assert state["dm_since"] == a._ts("2026-11-18T10:05:00+0000")
    assert state["comments_since"] == a._ts("2026-11-18T10:06:00+0000")
    assert state["mentions_since"] == a._ts("2026-11-18T10:01:00+0000")
    # second poll: only things at/after the cursors come back
    again = a.poll(state)
    assert {i.id for i in again} == {"222_5", "999_1"}
    assert json.loads(json.dumps(state)) == state


def test_poll_mentions_can_be_disabled():
    a, http = make(poll_mentions="false", poll_posts=3)
    http.add("GET", G + f"/{PAGE}/conversations", {"data": []})
    http.add("GET", G + f"/{PAGE}/feed", {"data": []})
    assert a.poll({}) == []
    assert http.last("GET", "/feed")["params"]["limit"] == 3
    assert not [c for c in http.calls if c["url"].endswith("/tagged")]


def test_api_version_override():
    a, http = make(api_version="25.0")
    http.add("POST", "https://graph.facebook.com/v25.0/111/feed", {"id": "111_1"})
    a.post("x")
    assert http.last("POST")["url"].startswith("https://graph.facebook.com/v25.0/")


def test_poll_failing_tagged_keeps_other_sections_and_its_own_cursor():
    a, http = make()
    convs, feed, tagged = _feeds()
    http.add("GET", G + f"/{PAGE}/conversations", convs)
    http.add("GET", G + f"/{PAGE}/feed", feed)
    http.add("GET", G + f"/{PAGE}/tagged", *[(500, {"error": {"message": "down"}})] * 3, tagged)
    state = {"mentions_since": 5.0}
    items = a.poll(state)
    assert {i.id for i in items} == {"m_2", "m_1", "m_0", "222_5", "222_3", "222_6"}
    assert state["dm_since"] == a._ts("2026-11-18T10:05:00+0000")
    assert state["comments_since"] == a._ts("2026-11-18T10:06:00+0000")
    assert state["mentions_since"] == 5.0                     # failed section: cursor unchanged
    again = a.poll(state)                                     # /tagged works again: its item is not lost
    assert {i.id for i in again} == {"222_5", "999_1"}
    assert state["mentions_since"] == a._ts("2026-11-18T10:01:00+0000")


def test_poll_failing_feed_does_not_move_comment_cursor():
    a, http = make()
    convs, feed, tagged = _feeds()
    http.add("GET", G + f"/{PAGE}/conversations", convs)
    http.add("GET", G + f"/{PAGE}/feed", (403, {"error": {"code": 10, "message": "no permission"}}), feed)
    http.add("GET", G + f"/{PAGE}/tagged", tagged)
    state = {}
    items = a.poll(state)
    assert {i.id for i in items} == {"m_2", "m_1", "m_0", "999_1"}
    assert "comments_since" not in state and state["dm_since"] == a._ts("2026-11-18T10:05:00+0000")
    again = a.poll(state)
    assert {i.id for i in again} == {"222_5", "222_3", "222_6", "999_1"}   # 999_1 sits at its cursor
    assert state["comments_since"] == a._ts("2026-11-18T10:06:00+0000")


def test_poll_raises_and_keeps_state_when_every_section_fails():
    a, http = make()
    for path in ("conversations", "feed", "tagged"):
        http.add("GET", G + f"/{PAGE}/{path}", (500, {"error": {"message": "down"}}))
    state = {"dm_since": 1.0, "comments_since": 2.0, "mentions_since": 3.0}
    with pytest.raises(PlatformError, match="HTTP 500"):
        a.poll(state)
    assert state == {"dm_since": 1.0, "comments_since": 2.0, "mentions_since": 3.0}
