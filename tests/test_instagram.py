import json
import time

import pytest

from social_bridge.adapters.instagram import InstagramAdapter
from social_bridge.base import PlatformError
from tests.fakehttp import FakeHttp

G = "https://graph.instagram.com/v24.0"
FB = "https://graph.facebook.com/v24.0"
IG = "1784"
ME = {"id": "app_scoped_9", "user_id": IG, "username": "mybrand"}


def make(**cfg):
    http = FakeHttp("instagram")
    conf = {"access_token": "igtok"}
    conf.update(cfg)
    a = InstagramAdapter({k: v for k, v in conf.items() if v is not None}, http)
    if not conf.get("login"):
        http.add("GET", G + "/me", ME)
    return a, http


def published(http, base=G, cid="c1", mid="m1"):
    http.add("GET", f"{base}/{cid}", {"status_code": "FINISHED", "id": cid})
    http.add("POST", f"{base}/{IG}/media_publish", {"id": mid})
    http.add("GET", f"{base}/{mid}", {"permalink": f"https://www.instagram.com/p/{mid.upper()}/"})


def test_whoami_uses_me_user_id_and_username():
    a, http = make()
    assert a.whoami() == "@mybrand"
    c = http.last("GET")
    assert c["url"] == G + "/me" and c["params"] == {"fields": "user_id,username"}
    assert c["headers"]["Authorization"] == "Bearer igtok"
    assert a._me()["id"] == IG and len(http.calls) == 1


def test_post_single_image_container_then_publish():
    a, http = make()
    http.add("POST", G + f"/{IG}/media", {"id": "c1"})
    published(http)
    r = a.post("caption here", title="T", link="https://l.test", media=["https://cdn.test/a.jpg"])
    create = http.calls[1]
    assert create["method"] == "POST" and create["url"] == G + f"/{IG}/media"
    assert create["json"] == {"caption": "T\n\ncaption here\n\nhttps://l.test", "image_url": "https://cdn.test/a.jpg"}
    assert http.calls[2]["params"] == {"fields": "status_code,status"}
    assert http.last("POST", "media_publish")["json"] == {"creation_id": "c1"}
    assert r.id == "m1" and r.url == "https://www.instagram.com/p/M1/"


def test_post_reel_waits_until_finished():
    a, http = make()
    http.add("POST", G + f"/{IG}/media", {"id": "c1"})
    http.add("GET", G + "/c1", {"status_code": "IN_PROGRESS"}, {"status_code": "IN_PROGRESS"},
             {"status_code": "FINISHED"})
    http.add("POST", G + f"/{IG}/media_publish", {"id": "m1"})
    http.add("GET", G + "/m1", {"permalink": "https://www.instagram.com/reel/X/"})
    slept = []
    http.sleep = slept.append
    r = a.post("clip", media=["https://cdn.test/v.mp4"])
    assert http.calls[1]["json"] == {"media_type": "REELS", "caption": "clip", "video_url": "https://cdn.test/v.mp4"}
    assert slept == [5, 5] and r.url == "https://www.instagram.com/reel/X/"


def test_post_container_error_raises():
    a, http = make()
    http.add("POST", G + f"/{IG}/media", {"id": "c1"})
    http.add("GET", G + "/c1", {"status_code": "ERROR", "status": "Error: unsupported format"})
    with pytest.raises(PlatformError, match="ERROR"):
        a.post("x", media=["https://cdn.test/v.mov"])
    assert not [c for c in http.calls if "media_publish" in c["url"]]


def test_post_carousel_with_video_child():
    a, http = make()
    http.add("POST", G + f"/{IG}/media", {"id": "k1"}, {"id": "k2"}, {"id": "c1"})
    http.add("GET", G + "/k2", {"status_code": "FINISHED"})
    published(http)
    a.post("album", media=["https://cdn.test/1.jpg", "https://cdn.test/2.mp4"])
    creates = [c["json"] for c in http.calls if c["method"] == "POST" and c["url"].endswith("/media")]
    assert creates == [
        {"is_carousel_item": True, "image_url": "https://cdn.test/1.jpg"},
        {"media_type": "VIDEO", "is_carousel_item": True, "video_url": "https://cdn.test/2.mp4"},
        {"media_type": "CAROUSEL", "children": "k1,k2", "caption": "album"},
    ]
    assert not [c for c in http.calls if c["url"] == G + "/k1"]   # image children are not polled


def test_post_story():
    a, http = make()
    http.add("POST", G + f"/{IG}/media", {"id": "c1"})
    published(http)
    r = a.post("ignored", target="story", media=["https://cdn.test/s.jpg"])
    assert http.calls[1]["json"] == {"media_type": "STORIES", "image_url": "https://cdn.test/s.jpg"}
    assert r.id == "m1" and r.raw == {"items": [{"id": "m1"}]}


def test_post_local_video_uses_resumable_upload(tmp_path):
    a, http = make()
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"VIDEO")
    http.add("POST", G + f"/{IG}/media", {"id": "c1", "uri": "https://rupload.facebook.com/ig-api-upload/v24.0/c1"})
    http.add("POST", "https://rupload.facebook.com/ig-api-upload/v24.0/c1", {"success": True})
    published(http)
    a.post("local", media=[str(f)])
    assert http.calls[1]["json"] == {"media_type": "REELS", "caption": "local", "upload_type": "resumable"}
    up = http.last("POST", "rupload")
    assert up["data"] == b"VIDEO"
    assert up["headers"]["Authorization"] == "OAuth igtok"
    assert up["headers"]["offset"] == "0" and up["headers"]["file_size"] == "5"


def test_post_errors_without_media_local_image_and_bad_target(tmp_path):
    a, http = make()
    with pytest.raises(PlatformError, match="at least one"):
        a.post("text only")
    img = tmp_path / "a.jpg"
    img.write_bytes(b"x")
    with pytest.raises(PlatformError, match="public http"):
        a.post("x", media=[str(img)])
    with pytest.raises(PlatformError, match="unknown post target"):
        a.post("x", target="somewhere", media=["https://c.test/a.jpg"])
    assert not [c for c in http.calls if c["method"] == "POST"]


def test_comment_targets():
    a, http = make()
    http.add("POST", "re:/replies$", {"id": "r1"})
    http.add("POST", "re:/comments$", {"id": "n1"})
    http.add("GET", G + f"/{IG}/media",
             {"data": [{"id": "500", "shortcode": "AAA", "permalink": "https://www.instagram.com/p/AAA/"}],
              "paging": {"cursors": {"after": "cur"}, "next": "https://next"}},
             {"data": [{"id": "600", "shortcode": "BBB", "permalink": "https://www.instagram.com/reel/BBB/"}]})
    r = a.comment("comment:178", "thanks")
    c = http.last("POST")
    assert c["url"] == G + "/178/replies" and c["json"] == {"message": "thanks"} and r.id == "r1"
    a.comment("179", "hi")
    assert http.last("POST")["url"] == G + "/179/comments"
    a.comment("media:180", "hi")
    assert http.last("POST")["url"] == G + "/180/comments"
    r = a.comment("https://www.instagram.com/reel/BBB/?igsh=abc", "nice")
    assert http.last("POST")["url"] == G + "/600/comments" and r.url == "https://www.instagram.com/reel/BBB/"
    pages = [c for c in http.calls if c["url"] == G + f"/{IG}/media"]
    assert pages[0]["params"] == {"fields": "id,shortcode,permalink", "limit": 50}
    assert pages[1]["params"]["after"] == "cur"
    r = a.comment("https://www.instagram.com/mybrand/p/AAA/c/181/", "re")
    assert http.last("POST")["url"] == G + "/181/replies" and r.url == "https://www.instagram.com/p/AAA/"
    with pytest.raises(PlatformError):
        a.comment("https://example.com/x", "no")


def test_comment_on_unknown_shortcode():
    a, http = make()
    http.add("GET", G + f"/{IG}/media", {"data": []})
    with pytest.raises(PlatformError, match="ZZZ"):
        a.comment("https://instagram.com/p/ZZZ", "x")


def test_dm_body_and_tag():
    a, http = make(message_tag="HUMAN_AGENT")
    http.add("POST", G + f"/{IG}/messages", {"recipient_id": "55", "message_id": "mid.1"})
    r = a.dm("55", "hello")
    c = http.last("POST")
    assert c["json"] == {"recipient": {"id": "55"}, "message": {"text": "hello"},
                         "messaging_type": "MESSAGE_TAG", "tag": "HUMAN_AGENT"}
    assert c["headers"]["Authorization"] == "Bearer igtok" and r.id == "mid.1"


def test_dm_by_username_profile_url_and_conversation_id():
    a, http = make()
    http.add("GET", G + f"/{IG}/conversations", {"data": [{"id": "conv1", "participants": {"data": [
        {"username": "mybrand", "id": IG}, {"username": "Bob.Smith", "id": "55"}]}}]})
    http.add("GET", G + "/aWdfZAG06MTpJR01lc3NhZA2VUaHJlYWQ6MTc4NDE0MDU5NjY", {"participants": {"data": [
        {"username": "mybrand", "id": IG}, {"username": "amy", "id": "66"}]}})
    http.add("POST", G + f"/{IG}/messages", {"message_id": "x"})
    a.dm("@bob.smith", "a")
    assert http.last("POST")["json"]["recipient"] == {"id": "55"}
    assert http.last("GET", "conversations")["params"] == {"platform": "instagram", "fields": "participants",
                                                            "limit": 50}
    a.dm("https://www.instagram.com/bob.smith/", "b")
    assert http.last("POST")["json"]["recipient"] == {"id": "55"}
    a.dm("aWdfZAG06MTpJR01lc3NhZA2VUaHJlYWQ6MTc4NDE0MDU5NjY", "c")
    assert http.last("POST")["json"]["recipient"] == {"id": "66"}
    with pytest.raises(PlatformError, match="nobody"):
        a.dm("@nobody", "d")


def test_facebook_login_mode_hosts_discovery_and_page_messaging():
    a, http = make(login="facebook", page_id="321")
    http.add("GET", FB + "/321", {"instagram_business_account": {"id": IG, "username": "mybrand"}, "id": "321"})
    http.add("POST", FB + f"/{IG}/media", {"id": "c1"})
    published(http, base=FB)
    http.add("POST", FB + "/321/messages", {"message_id": "m"})
    assert a.whoami() == "@mybrand"
    assert http.calls[0]["params"] == {"fields": "instagram_business_account{id,username}"}
    a.post("x", media=["https://cdn.test/a.jpg"])
    a.dm("55", "hi")
    assert http.last("POST")["url"] == FB + "/321/messages"
    assert all(c["url"].startswith(FB) for c in http.calls)


def test_facebook_login_with_configured_ig_user_id():
    a, http = make(login="facebook", page_id="321", ig_user_id=IG)
    http.add("GET", FB + f"/{IG}", {"id": IG, "username": "mybrand"})
    assert a.whoami() == "@mybrand"
    assert http.last("GET")["params"] == {"fields": "id,username"}


def test_token_refresh_on_190_and_retry():
    a, http = make()
    http.add("POST", G + f"/{IG}/messages", (400, {"error": {"code": 190, "message": "expired"}}), {"message_id": "ok"})
    http.add("GET", "https://graph.instagram.com/refresh_access_token",
             {"access_token": "newtok", "token_type": "bearer", "expires_in": 5184000})
    r = a.dm("55", "x")
    ref = http.last("GET", "refresh_access_token")
    assert ref["params"] == {"grant_type": "ig_refresh_token", "access_token": "igtok"}
    posts = [c for c in http.calls if c["method"] == "POST"]
    assert [p["headers"]["Authorization"] for p in posts] == ["Bearer igtok", "Bearer newtok"]
    assert r.id == "ok"


def test_failed_refresh_raises_original_error():
    a, http = make()
    http.add("POST", G + f"/{IG}/messages", (400, {"error": {"code": 190, "message": "expired"}}))
    http.add("GET", "https://graph.instagram.com/refresh_access_token", (400, {"error": {"code": 190}}))
    with pytest.raises(PlatformError, match="messages"):
        a.dm("55", "x")


def _poll_routes(http):
    http.add("GET", "https://graph.instagram.com/refresh_access_token", (400, {"error": {"message": "too new"}}))
    http.add("GET", G + f"/{IG}/conversations", {"data": [
        {"id": "conv1", "updated_time": "2026-11-18T10:05:00+0000", "messages": {"data": [
            {"id": "mm3", "message": "my answer", "from": {"username": "mybrand", "id": IG},
             "created_time": "2026-11-18T10:05:00+0000"},
            {"id": "mm2", "message": "hey there", "from": {"username": "bob", "id": "55"},
             "created_time": "2026-11-18T10:04:00+0000"}]}},
        {"id": "conv2", "updated_time": "2026-11-18T09:00:00+0000", "messages": {"data": [
            {"id": "mm1", "from": {"username": "amy", "id": "66"}, "created_time": "2026-11-18T09:00:00+0000"}]}}]})
    http.add("GET", G + f"/{IG}/media", {"data": [{
        "id": "500", "permalink": "https://www.instagram.com/p/AAA/", "timestamp": "2026-11-17T10:00:00+0000",
        "comments": {"data": [
            {"id": "c1", "text": "love it", "username": "bob", "from": {"id": "55", "username": "bob"},
             "timestamp": "2026-11-18T10:01:00+0000", "replies": {"data": [
                 {"id": "c2", "text": "thanks bob", "username": "mybrand", "from": {"id": IG, "username": "mybrand"},
                  "timestamp": "2026-11-18T10:02:00+0000"},
                 {"id": "c3", "text": "same", "username": "amy", "timestamp": "2026-11-18T10:03:00+0000"}]}},
            {"id": "c4", "text": "my own note", "username": "mybrand", "timestamp": "2026-11-18T10:00:00+0000",
             "replies": {"data": [
                 {"id": "c5", "text": "replying to you", "username": "cy", "from": {"id": "77", "username": "cy"},
                  "timestamp": "2026-11-18T10:06:00+0000"}]}}]}}]})


def test_poll_kinds_reply_to_and_cursors():
    a, http = make()
    _poll_routes(http)
    state = {}
    items = a.poll(state)
    by_id = {i.id: i for i in items}
    assert set(by_id) == {"mm2", "mm1", "c1", "c3", "c5"}          # own mm3 / c2 / c4 filtered
    assert [i.ts for i in items] == sorted(i.ts for i in items)
    dm = by_id["mm2"]
    assert (dm.kind, dm.thread, dm.author, dm.author_id) == ("dm", "conv1", "@bob", "55")
    assert dm.reply_to == {"action": "dm", "target": "55"}
    assert by_id["mm1"].text == "[attachment]"
    c1 = by_id["c1"]
    assert c1.kind == "comment" and c1.thread == "500" and c1.url == "https://www.instagram.com/p/AAA/"
    assert c1.reply_to == {"action": "comment", "target": "comment:c1"} and c1.author == "@bob"
    assert by_id["c3"].kind == "comment" and by_id["c3"].reply_to["target"] == "comment:c1"
    assert by_id["c5"].kind == "reply" and by_id["c5"].reply_to == {"action": "comment", "target": "comment:c4"}
    conv = http.last("GET", "conversations")["params"]
    assert conv["platform"] == "instagram" and "messages.limit(10)" in conv["fields"]
    assert "replies" in http.last("GET", "/media")["params"]["fields"]
    assert state["dm_since"] == a._ts("2026-11-18T10:05:00+0000")
    assert state["comments_since"] == a._ts("2026-11-18T10:06:00+0000")
    assert json.loads(json.dumps(state)) == state and not [k for k in state if k.startswith("_")]
    again = a.poll(state)
    assert {i.id for i in again} == {"c5"}
    assert len([c for c in http.calls if "refresh_access_token" in c["url"]]) == 1   # failed refresh: retry tomorrow
    assert state["token_refresh_tried"] > 0 and "access_token" not in state


def test_reply_to_target_from_poll_is_accepted_by_comment():
    a, http = make()
    _poll_routes(http)
    items = {i.id: i for i in a.poll({})}
    http.add("POST", G + "/c4/replies", {"id": "r9"})
    r = a.comment(items["c5"].reply_to["target"], "hi")
    assert http.last("POST")["url"] == G + "/c4/replies" and r.id == "r9"
    assert r.url == "https://www.instagram.com/p/AAA/"


def test_poll_refreshes_token_and_persists_it_in_state():
    a, http = make()
    http.add("GET", "https://graph.instagram.com/refresh_access_token", {"access_token": "fresh", "expires_in": 1})
    http.add("GET", G + f"/{IG}/conversations", {"data": []})
    http.add("GET", G + f"/{IG}/media", {"data": []})
    state = {}
    a.poll(state)
    assert state["access_token"] == "fresh" and state["token_refreshed"] > 0
    assert http.last("GET", "/media")["headers"]["Authorization"] == "Bearer fresh"
    n = len(http.calls)
    a.poll(state)                      # no second refresh within a week
    assert not [c for c in http.calls[n:] if "refresh_access_token" in c["url"]]
    # a restarted adapter adopts the stored token
    b, http2 = make()
    http2.add("GET", G + f"/{IG}/conversations", {"data": []})
    http2.add("GET", G + f"/{IG}/media", {"data": []})
    b.poll(state)
    assert http2.last("GET", "/media")["headers"]["Authorization"] == "Bearer fresh"
    assert not [c for c in http2.calls if "refresh_access_token" in c["url"]]
    # a new token in config drops the stored one
    c, http3 = make(access_token="other")
    http3.add("GET", "https://graph.instagram.com/refresh_access_token", (400, {"error": {"code": 190}}))
    http3.add("GET", G + f"/{IG}/conversations", {"data": []})
    http3.add("GET", G + f"/{IG}/media", {"data": []})
    c.poll(state)
    assert "access_token" not in state and state["token_refresh_tried"] <= time.time()
    assert http3.last("GET", "/media")["headers"]["Authorization"] == "Bearer other"


def test_poll_failing_media_keeps_dms_and_comment_cursor():
    a, http = make()
    _poll_routes(http)
    media = http.routes[-1][2][0]
    http.routes[-1][2] = [(500, {"error": {"message": "down"}})] * 3 + [media]
    state = {}
    items = a.poll(state)
    assert {i.id for i in items} == {"mm2", "mm1"}
    assert state["dm_since"] == a._ts("2026-11-18T10:05:00+0000") and "comments_since" not in state
    again = a.poll(state)                                   # /media works again: comments are not lost
    assert {i.id for i in again} == {"c1", "c3", "c5"}
    assert state["comments_since"] == a._ts("2026-11-18T10:06:00+0000")


def test_poll_failing_conversations_does_not_move_dm_cursor():
    a, http = make()
    _poll_routes(http)
    convs = http.routes[-2][2][0]
    http.routes[-2][2] = [(403, {"error": {"code": 10, "message": "no permission"}}), convs]
    state = {"dm_since": 7.0}
    items = a.poll(state)
    assert {i.id for i in items} == {"c1", "c3", "c5"}
    assert state["dm_since"] == 7.0 and state["comments_since"] == a._ts("2026-11-18T10:06:00+0000")
    again = a.poll(state)
    assert {i.id for i in again} == {"mm2", "mm1", "c5"}
    assert state["dm_since"] == a._ts("2026-11-18T10:05:00+0000")


def test_poll_all_sections_failing_raises_but_saves_refreshed_token():
    a, http = make()
    http.add("GET", "https://graph.instagram.com/refresh_access_token", (400, {"error": {"message": "too new"}}),
             {"access_token": "fresh"})
    http.add("GET", G + f"/{IG}/conversations", (400, {"error": {"code": 190}}), (500, {"error": {}}))
    http.add("GET", G + f"/{IG}/media", (500, {"error": {"message": "down"}}))
    state = {"dm_since": 1.0, "comments_since": 2.0}
    with pytest.raises(PlatformError, match="conversations"):
        a.poll(state)
    assert state["dm_since"] == 1.0 and state["comments_since"] == 2.0
    assert state["access_token"] == "fresh"                 # token refreshed mid-poll is still persisted
    assert http.last("GET", "/media")["headers"]["Authorization"] == "Bearer fresh"
