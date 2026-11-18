import calendar

import pytest

from social_bridge.adapters.threads import ThreadsAdapter
from social_bridge.base import PlatformError
from tests.fakehttp import FakeHttp

H = "https://graph.threads.net"
G = H + "/v1.0"


def make(**cfg):
    http = FakeHttp("threads")
    conf = {"access_token": "tok", "user_id": "42", "auto_refresh": "false"}
    conf.update(cfg)
    return ThreadsAdapter(conf, http), http


def ts(sec):
    return float(calendar.timegm((2026, 1, 1, 0, 0, sec, 0, 0, 0)))


def iso(sec):
    return f"2026-01-01T00:00:{sec:02d}+0000"


def calls(http, method, url):
    return [c for c in http.calls if c["method"] == method and c["url"] == url]


def test_whoami_uses_me_and_token_param():
    a, http = make(user_id="")
    http.add("GET", G + "/me", {"id": "42", "username": "kyo"})
    assert a.whoami() == "@kyo"
    c = http.last("GET")
    assert c["url"] == G + "/me" and c["params"] == {"fields": "id,username", "access_token": "tok"}
    assert a._uid() == "42"


def test_post_text_with_title_and_link_card():
    a, http = make()
    http.add("POST", G + "/42/threads", {"id": "c1"})
    http.add("POST", G + "/42/threads_publish", {"id": "m1"})
    http.add("GET", G + "/m1", {"id": "m1", "permalink": "https://www.threads.com/@kyo/post/ABC", "shortcode": "ABC"})
    r = a.post("hello", title="T", link="https://x.y/a")
    create, publish = calls(http, "POST", G + "/42/threads")[0], http.last("POST", "threads_publish")
    assert create["data"] == {"media_type": "TEXT", "text": "T\n\nhello", "link_attachment": "https://x.y/a"}
    assert create["params"] == {"access_token": "tok"}
    assert publish["data"] == {"creation_id": "c1"} and publish["params"] == {"access_token": "tok"}
    assert r.id == "m1" and r.url == "https://www.threads.com/@kyo/post/ABC"
    assert a._codes["ABC"] == "m1"


def test_post_reply_control_and_quote_target():
    a, http = make(reply_control="mentioned_only")
    http.add("POST", G + "/42/threads", {"id": "c1"})
    http.add("POST", G + "/42/threads_publish", {"id": "m1"})
    http.add("GET", G + "/m1", {"permalink": "p"})
    a.post("look", target="999")
    assert calls(http, "POST", G + "/42/threads")[0]["data"] == {
        "media_type": "TEXT", "text": "look", "quote_post_id": "999", "reply_control": "mentioned_only"}


def test_post_single_image_waits_for_container_and_appends_link():
    a, http = make()
    http.add("POST", G + "/42/threads", {"id": "c1"})
    http.add("GET", G + "/c1", {"status": "IN_PROGRESS"}, {"status": "FINISHED"})
    http.add("POST", G + "/42/threads_publish", {"id": "m1"})
    http.add("GET", G + "/m1", {"permalink": "https://www.threads.com/@kyo/post/Q"})
    r = a.post("pic", link="https://x.y", media=["https://cdn.test/a.jpg"])
    assert calls(http, "POST", G + "/42/threads")[0]["data"] == {
        "media_type": "IMAGE", "image_url": "https://cdn.test/a.jpg", "text": "pic\n\nhttps://x.y"}
    status_calls = calls(http, "GET", G + "/c1")
    assert len(status_calls) == 2 and status_calls[0]["params"]["fields"] == "status,error_message"
    assert http.last("POST", "threads_publish")["data"] == {"creation_id": "c1"} and r.id == "m1"


def test_post_video_error_status_raises():
    a, http = make()
    http.add("POST", G + "/42/threads", {"id": "c1"})
    http.add("GET", G + "/c1", {"status": "ERROR", "error_message": "bad format"})
    with pytest.raises(PlatformError, match="bad format"):
        a.post("", media=["https://cdn.test/v.mp4"])
    assert calls(http, "POST", G + "/42/threads")[0]["data"] == {"media_type": "VIDEO",
                                                                 "video_url": "https://cdn.test/v.mp4"}


def test_post_carousel():
    a, http = make()
    http.add("POST", G + "/42/threads", {"id": "c1"}, {"id": "c2"}, {"id": "c3"})
    http.add("GET", r"re:/v1\.0/c\d$", {"status": "FINISHED"})
    http.add("POST", G + "/42/threads_publish", {"id": "m1"})
    http.add("GET", G + "/m1", {"permalink": "p"})
    a.post("two", media=["https://cdn.test/a.png", "https://cdn.test/b.mov?x=1"])
    created = [c["data"] for c in calls(http, "POST", G + "/42/threads")]
    assert created == [
        {"is_carousel_item": "true", "media_type": "IMAGE", "image_url": "https://cdn.test/a.png"},
        {"is_carousel_item": "true", "media_type": "VIDEO", "video_url": "https://cdn.test/b.mov?x=1"},
        {"media_type": "CAROUSEL", "children": "c1,c2", "text": "two"},
    ]
    assert http.last("POST", "threads_publish")["data"] == {"creation_id": "c3"}


def test_local_media_is_rejected_without_requests():
    a, http = make()
    with pytest.raises(PlatformError, match="public http"):
        a.post("x", media=["/tmp/a.jpg"])
    assert http.calls == []


def test_comment_by_id_and_by_url():
    a, http = make()
    http.add("POST", G + "/42/threads", {"id": "c1"})
    http.add("POST", G + "/42/threads_publish", {"id": "m5"})
    http.add("GET", G + "/m5", {"permalink": "p"})
    http.add("GET", G + "/42/threads", {"data": [{"id": "m9", "shortcode": "XyZ_1"}]})
    a.comment("123", "hi")
    assert calls(http, "POST", G + "/42/threads")[-1]["data"] == {"media_type": "TEXT", "text": "hi",
                                                                  "reply_to_id": "123"}
    a.comment("https://www.threads.com/@bob/post/XyZ_1?xmt=abc", "yo")
    assert calls(http, "POST", G + "/42/threads")[-1]["data"]["reply_to_id"] == "m9"
    lookup = calls(http, "GET", G + "/42/threads")[0]
    assert lookup["params"]["limit"] == 50 and "shortcode" in lookup["params"]["fields"]
    # second time comes from the cache
    a.comment("https://threads.net/@bob/post/XyZ_1", "again")
    assert len(calls(http, "GET", G + "/42/threads")) == 1


def test_comment_url_lookup_through_replies_and_mentions_then_fails():
    a, http = make()
    http.add("GET", G + "/42/threads", {"data": []})
    http.add("GET", G + "/42/replies", {"data": []})
    http.add("GET", G + "/42/mentions", {"data": [{"id": "77", "permalink": "https://www.threads.com/@z/post/MEN"}]})
    http.add("POST", G + "/42/threads", {"id": "c1"})
    http.add("POST", G + "/42/threads_publish", {"id": "m5"})
    http.add("GET", G + "/m5", {"permalink": "p"})
    a.comment("https://www.threads.com/@z/post/MEN", "hi")
    assert calls(http, "POST", G + "/42/threads")[-1]["data"]["reply_to_id"] == "77"
    with pytest.raises(PlatformError, match="media id"):
        a.comment("https://www.threads.com/@z/post/NOPE", "hi")
    with pytest.raises(PlatformError):
        a.comment("not a target", "hi")


def test_token_refresh_on_expired_token_then_retry():
    a, http = make()
    http.add("GET", G + "/me", (400, {"error": {"code": 190, "message": "expired"}}), {"id": "42", "username": "kyo"})
    http.add("GET", H + "/refresh_access_token", {"access_token": "new", "expires_in": 5184000})
    assert a.whoami() == "@kyo"
    ref = http.last("GET", "refresh_access_token")
    assert ref["params"] == {"grant_type": "th_refresh_token", "access_token": "tok"}
    assert http.last("GET", "/me")["params"]["access_token"] == "new"


def test_short_lived_token_exchanged_with_app_secret():
    a, http = make(app_secret="sec")
    http.add("GET", H + "/access_token", {"access_token": "long", "expires_in": 5184000})
    http.add("GET", G + "/me", {"id": "42", "username": "kyo"})
    a.whoami()
    assert http.calls[0]["params"] == {"grant_type": "th_exchange_token", "client_secret": "sec",
                                       "access_token": "tok"}
    assert http.last("GET", "/me")["params"]["access_token"] == "long"


def empty_routes(http):
    http.add("GET", G + "/me", {"id": "42", "username": "kyo"})
    for edge in ("threads", "replies", "mentions"):
        http.add("GET", f"{G}/42/{edge}", {"data": []})


def test_refreshed_token_is_kept_in_state_across_restarts():
    a, http = make(auto_refresh=None)
    empty_routes(http)
    http.add("GET", H + "/refresh_access_token", {"access_token": "new"})
    state = {}
    assert a.poll(state) == []
    assert state["access_token"] == "new" and state["token_seed"] and state["token_refreshed"] > 0
    assert http.last("GET", "/me")["params"]["access_token"] == "new"

    b, http2 = make(auto_refresh=None)
    empty_routes(http2)
    b.poll(state)
    assert not any("refresh_access_token" in c["url"] for c in http2.calls)
    assert http2.last("GET", "/me")["params"]["access_token"] == "new"

    c, http3 = make(access_token="other", auto_refresh="false")
    empty_routes(http3)
    c.poll(state)
    assert "access_token" not in state and http3.last("GET", "/me")["params"]["access_token"] == "other"


def test_poll_kinds_threads_reply_to_and_cursor():
    a, http = make()
    http.add("GET", G + "/me", {"id": "42", "username": "kyo"})
    http.add("GET", G + "/42/threads", {"data": [{"id": "p1", "shortcode": "P1", "timestamp": iso(1)}]})
    http.add("GET", G + "/42/replies", {"data": [{"id": "r1", "root_post": {"id": "x9"}},
                                                  {"id": "r2", "root_post": {"id": "p1"}}]})
    http.add("GET", G + "/p1/conversation", {"data": [
        {"id": "c1", "text": "nice", "username": "bob", "timestamp": iso(10), "replied_to": {"id": "p1"},
         "root_post": {"id": "p1"}, "permalink": "https://www.threads.com/@bob/post/C1"},
        {"id": "r2", "text": "thanks", "username": "kyo", "is_reply_owned_by_me": True, "timestamp": iso(20),
         "replied_to": {"id": "c1"}, "root_post": {"id": "p1"}},
        {"id": "c2", "text": "yw", "username": "bob", "timestamp": iso(30), "replied_to": {"id": "r2"},
         "root_post": {"id": "p1"}},
        {"id": "c3", "username": "amy", "media_type": "IMAGE", "timestamp": iso(25), "replied_to": {"id": "c1"},
         "root_post": {"id": "p1"}},
    ]})
    http.add("GET", G + "/r1/replies", {"data": [
        {"id": "d1", "text": "answer", "username": "zed", "timestamp": iso(40), "replied_to": {"id": "r1"},
         "root_post": {"id": "x9"}}]})
    http.add("GET", G + "/42/mentions", {"data": [
        {"id": "m1", "text": "hey @kyo", "username": "eve", "timestamp": iso(50),
         "permalink": "https://www.threads.com/@eve/post/M1"},
        {"id": "c2", "text": "yw", "username": "bob", "timestamp": iso(30)},
        {"id": "m2", "text": "self", "username": "Kyo", "timestamp": iso(55)},
    ]})
    state = {}
    items = a.poll(state)
    got = {i.id: (i.kind, i.thread, i.author) for i in items}
    assert got == {"c1": ("comment", "p1", "@bob"), "c2": ("reply", "p1", "@bob"), "c3": ("comment", "p1", "@amy"),
                   "d1": ("reply", "x9", "@zed"), "m1": ("mention", "m1", "@eve")}
    c1 = next(i for i in items if i.id == "c1")
    assert c1.reply_to == {"action": "comment", "target": "c1"} and c1.ts == ts(10)
    assert c1.url == "https://www.threads.com/@bob/post/C1" and c1.text == "nice"
    assert next(i for i in items if i.id == "c3").text == "[image]"
    assert state["since"] == ts(50)
    conv = http.last("GET", "/p1/conversation")
    assert conv["params"]["reverse"] == "true" and "is_reply_owned_by_me" in conv["params"]["fields"]
    assert not any(c["url"] == G + "/r2/replies" for c in http.calls)
    assert http.last("GET", "/42/threads")["params"]["limit"] == 10
    assert a._codes["C1"] == "c1"   # URLs seen in poll resolve without lookups later

    again = a.poll(state)
    assert [i.id for i in again] == ["m1"] and state["since"] == ts(50)


def test_poll_mentions_can_be_disabled():
    a, http = make(poll_mentions="false")
    http.add("GET", G + "/me", {"id": "42", "username": "kyo"})
    http.add("GET", G + "/42/threads", {"data": []})
    http.add("GET", G + "/42/replies", {"data": []})
    assert a.poll({}) == []
    assert not any("mentions" in c["url"] for c in http.calls)


def test_timestamp_parsing():
    assert ThreadsAdapter._ts("2026-01-01T02:00:00+0200") == ts(0)
    assert ThreadsAdapter._ts("2026-01-01T00:00:05Z") == ts(5)
    assert ThreadsAdapter._ts("") == 0.0


def test_poll_skips_reposts_and_survives_unreadable_post():
    a, http = make(poll_mentions="false")
    http.add("GET", G + "/me", {"id": "42", "username": "kyo"})
    http.add("GET", G + "/42/threads", {"data": [
        {"id": "p1", "shortcode": "P1", "media_type": "TEXT_POST", "timestamp": iso(1)},
        {"id": "rp", "shortcode": "OTHER", "media_type": "REPOST_FACADE", "timestamp": iso(2)},
        {"id": "p2", "shortcode": "P2", "media_type": "IMAGE", "timestamp": iso(3)},
    ]})
    http.add("GET", G + "/42/replies", {"data": []})
    http.add("GET", G + "/p1/conversation", (400, {"error": {"code": 100, "message": "unsupported get request"}}))
    http.add("GET", G + "/p2/conversation", {"data": [
        {"id": "c1", "text": "hi", "username": "bob", "timestamp": iso(10), "replied_to": {"id": "p2"},
         "root_post": {"id": "p2"}}]})
    items = a.poll({})
    assert [(i.id, i.kind, i.thread) for i in items] == [("c1", "comment", "p2")]
    assert not any(c["url"] == G + "/rp/conversation" for c in http.calls)
    assert "media_type" in http.last("GET", "/42/threads")["params"]["fields"]
    assert "OTHER" not in a._codes and a._codes["P2"] == "p2"
