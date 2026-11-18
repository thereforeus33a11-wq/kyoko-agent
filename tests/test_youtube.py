import pytest

from social_bridge.adapters.youtube import YouTubeAdapter
from social_bridge.base import PlatformError
from tests.fakehttp import FakeHttp

API = "https://www.googleapis.com/youtube/v3"
UP = "https://www.googleapis.com/upload/youtube/v3"
TOKEN = "https://oauth2.googleapis.com/token"
ME = "UCme00000000000000000000"
VID = "dQw4w9WgXcQ"
OTHER_VID = "9bZkp7q19f0"
TOP = "UgzTopComment00000000004AaABAg"
SESSION = UP + "/videos?uploadType=resumable&upload_id=SESSION1"


def make(tokens=None, **cfg):
    http = FakeHttp("youtube")
    http.add("POST", TOKEN, *(tokens or [{"access_token": "at1", "expires_in": 3599, "token_type": "Bearer"}]))
    conf = {"client_id": "cid", "client_secret": "csec", "refresh_token": "rt"}
    conf.update(cfg)
    return YouTubeAdapter(conf, http), http


def add_channel(http):
    http.add("GET", API + "/channels",
             {"items": [{"id": ME, "snippet": {"title": "My Channel", "customUrl": "@mychan"}}]})


def calls(http, method, contains):
    return [c for c in http.calls if c["method"] == method and contains in c["url"]]


# ----------------------------------------------------------------- auth / whoami
def test_whoami_refreshes_token_and_returns_handle():
    a, http = make()
    add_channel(http)
    assert a.whoami() == "@mychan"
    tok = http.calls[0]
    assert tok["method"] == "POST" and tok["url"] == TOKEN
    assert tok["data"] == {"grant_type": "refresh_token", "client_id": "cid", "client_secret": "csec",
                           "refresh_token": "rt"}
    c = http.last("GET", "/channels")
    assert c["params"] == {"part": "snippet", "mine": "true"}
    assert c["headers"]["Authorization"] == "Bearer at1"


def test_whoami_falls_back_to_title_and_errors_without_channel():
    a, http = make()
    http.add("GET", API + "/channels", {"items": [{"id": ME, "snippet": {"title": "Plain"}}]})
    assert a.whoami() == "Plain"
    b, http2 = make()
    http2.add("GET", API + "/channels", {"items": []})
    with pytest.raises(PlatformError, match="no YouTube channel"):
        b.whoami()


def test_token_is_cached_and_refreshed_once_on_401():
    a, http = make(tokens=[{"access_token": "at1", "expires_in": 3599}, {"access_token": "at2", "expires_in": 3599}])
    http.add("POST", API + "/commentThreads",
             {"id": "T1"}, (401, {"error": {"code": 401, "message": "Invalid Credentials"}}), {"id": "T2"})
    assert a.comment(VID, "one").id == "T1"
    assert a.comment(VID, "two").id == "T2"
    assert len(calls(http, "POST", "oauth2.googleapis.com")) == 2
    posts = calls(http, "POST", "/commentThreads")
    assert [p["headers"]["Authorization"] for p in posts] == ["Bearer at1", "Bearer at1", "Bearer at2"]


def test_invalid_grant_gives_clear_error():
    a, http = make(tokens=[(400, {"error": "invalid_grant",
                                  "error_description": "Token has been expired or revoked."})])
    with pytest.raises(PlatformError, match="invalid_grant.*expired or revoked"):
        a.whoami()


def test_google_error_body_is_summarised():
    a, http = make()
    http.add("POST", API + "/commentThreads", (403, {"error": {
        "code": 403, "message": "The video has disabled comments.",
        "errors": [{"reason": "commentsDisabled", "domain": "youtube.commentThread"}]}}))
    with pytest.raises(PlatformError, match="HTTP 403 commentsDisabled: The video has disabled comments") as e:
        a.comment(VID, "hi")
    assert e.value.status == 403


# ----------------------------------------------------------------- comment
@pytest.mark.parametrize("target", [
    VID,
    f"https://www.youtube.com/watch?v={VID}&t=42s",
    f"https://youtu.be/{VID}?si=abcDEF",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/live/{VID}?feature=share",
    f"https://m.youtube.com/watch?v={VID}",
    f"music.youtube.com/watch?v={VID}&list=RDabc",
    f"https://www.youtube-nocookie.com/embed/{VID}",
    f"youtube.com/watch?v={VID}",
    f"  https://www.youtube.com/watch?feature=shared&v={VID}  ",
])
def test_comment_top_level_from_ids_and_urls(target):
    a, http = make()
    http.add("POST", API + "/commentThreads", {"id": TOP, "snippet": {"videoId": VID}})
    r = a.comment(target, "great video")
    c = http.last("POST", "/commentThreads")
    assert c["params"] == {"part": "snippet"}
    assert c["json"] == {"snippet": {"videoId": VID, "topLevelComment": {"snippet": {"textOriginal": "great video"}}}}
    assert c["headers"]["Authorization"] == "Bearer at1"
    assert r.id == TOP and r.url == f"https://www.youtube.com/watch?v={VID}&lc={TOP}"


def test_comment_reply_to_comment_id():
    a, http = make()
    http.add("POST", API + "/comments", {"id": TOP + ".AbCdEfGhIjK", "snippet": {"parentId": TOP, "videoId": VID}})
    r = a.comment(TOP, "thanks")
    c = http.last("POST", "/comments")
    assert c["params"] == {"part": "snippet"}
    assert c["json"] == {"snippet": {"parentId": TOP, "textOriginal": "thanks"}}
    assert r.id == TOP + ".AbCdEfGhIjK"
    assert r.url == f"https://www.youtube.com/watch?v={VID}&lc={TOP}.AbCdEfGhIjK"


def test_comment_reply_from_lc_url():
    a, http = make()
    http.add("POST", API + "/comments", {"id": TOP + ".Zz", "snippet": {"parentId": TOP}})
    r = a.comment(f"https://www.youtube.com/watch?v={VID}&lc={TOP}", "thanks")
    assert http.last("POST", "/comments")["json"]["snippet"]["parentId"] == TOP
    assert r.url == f"https://www.youtube.com/watch?v={VID}&lc={TOP}.Zz"


def test_reply_to_a_reply_uses_thread_id_and_mentions_author():
    a, http = make()
    add_channel(http)
    reply_id = TOP + ".9xYzReply01"
    http.add("GET", API + "/comments", {"items": [{"id": reply_id, "snippet": {
        "authorDisplayName": "@bob", "authorChannelId": {"value": "UCbob"}}}]})
    http.add("POST", API + "/comments", {"id": TOP + ".new1"}, {"id": TOP + ".new2"})
    a.comment(f"https://youtu.be/{VID}?lc={reply_id}", "agreed")
    g = http.last("GET", "/comments")
    assert g["params"] == {"part": "snippet", "id": reply_id, "textFormat": "plainText"}
    assert http.last("POST", "/comments")["json"] == {"snippet": {"parentId": TOP, "textOriginal": "@bob agreed"}}
    a.comment(reply_id, "@Bob already tagged")
    assert http.last("POST", "/comments")["json"]["snippet"]["textOriginal"] == "@Bob already tagged"


@pytest.mark.parametrize("target", [
    "https://www.youtube.com/post/UgkxAbCdEfGhIjKlMnOpQrStUvWxYz",
    "https://www.youtube.com/@somechannel",
    "https://www.youtube.com/watch?v=short",
    "not a target!",
    "",
])
def test_comment_bad_targets(target):
    a, http = make()
    with pytest.raises(PlatformError):
        a.comment(target, "x")
    assert http.calls == []


def test_dm_not_supported():
    a, _ = make()
    assert "dm" not in a.actions
    with pytest.raises(PlatformError):
        a.dm("someone", "hi")


# ----------------------------------------------------------------- post (video upload)
def test_post_uploads_video_resumable_in_chunks(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"0123456789")
    a, http = make(privacy="unlisted", made_for_kids="false", notify_subscribers="false")
    a.UPLOAD_CHUNK = 4
    http.add("POST", UP + "/videos", (200, {}, {"Location": SESSION}))
    http.add("PUT", UP + "/videos", (308, b"", {"Range": "bytes=0-3"}), (308, b"", {"Range": "bytes=0-7"}),
             (200, {"id": "NEWVID12345", "status": {"uploadStatus": "uploaded"}}))
    r = a.post("My <b>title</b> line\nmore text", link="https://x.y", media=[str(f)])
    init = http.last("POST", "/upload/youtube/v3/videos")
    assert init["url"] == UP + "/videos"
    assert init["params"] == {"part": "snippet,status", "notifySubscribers": "false", "uploadType": "resumable"}
    assert init["headers"]["Authorization"] == "Bearer at1"
    assert init["headers"]["X-Upload-Content-Type"] == "video/mp4"
    assert init["headers"]["X-Upload-Content-Length"] == "10"
    assert init["json"] == {
        "snippet": {"title": "My ‹b›title‹/b› line",
                    "description": "My ‹b›title‹/b› line\nmore text\n\nhttps://x.y",
                    "categoryId": "22"},
        "status": {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False}}
    puts = calls(http, "PUT", "upload_id=SESSION1")
    assert [p["data"] for p in puts] == [b"0123", b"4567", b"89"]
    assert [p["headers"]["Content-Range"] for p in puts] == ["bytes 0-3/10", "bytes 4-7/10", "bytes 8-9/10"]
    assert all(p["headers"]["Content-Type"] == "video/mp4" and p["headers"]["Authorization"] == "Bearer at1"
               for p in puts)
    assert r.id == "NEWVID12345" and r.url == "https://www.youtube.com/watch?v=NEWVID12345"


def test_post_upload_resumes_after_server_error_and_refreshes_on_401(tmp_path):
    f = tmp_path / "clip.mov"
    f.write_bytes(b"0123456789")
    a, http = make(tokens=[{"access_token": "at1", "expires_in": 3599}, {"access_token": "at2", "expires_in": 3599}])
    a.UPLOAD_CHUNK = 4
    http.add("POST", UP + "/videos", (401, {"error": {"code": 401, "message": "expired"}}),
             (200, {}, {"location": SESSION}))
    http.add("PUT", UP + "/videos", (503, {"error": {"code": 503, "message": "backend"}}),
             (308, b"", {"Range": "bytes=0-3"}), (308, b"", {"Range": "bytes=0-7"}), (201, {"id": "NEWVID12345"}))
    a.config["made_for_kids"] = None  # unset -> field omitted, channel default applies
    r = a.post("", title="Explicit", media=[str(f)])
    inits = calls(http, "POST", "/upload/youtube/v3/videos")
    assert [i["headers"]["Authorization"] for i in inits] == ["Bearer at1", "Bearer at2"]
    assert inits[-1]["json"]["snippet"]["title"] == "Explicit"
    assert inits[-1]["json"]["status"] == {"privacyStatus": "public"}
    assert inits[-1]["params"] == {"part": "snippet,status", "uploadType": "resumable"}
    puts = calls(http, "PUT", "upload_id=SESSION1")
    assert [p["headers"]["Content-Range"] for p in puts] == [
        "bytes 0-3/10", "bytes */10", "bytes 4-7/10", "bytes 8-9/10"]
    assert puts[1]["data"] == b""
    assert r.id == "NEWVID12345"


def test_post_from_url_with_thumbnail_and_playlist(tmp_path):
    thumb = tmp_path / "cover.jpg"
    thumb.write_bytes(b"JPEGDATA")
    a, http = make(category_id="20")
    http.add("GET", "https://cdn.example/media/My%20Clip.mp4", b"VIDEOBYTES")
    http.add("POST", UP + "/videos", (200, {}, {"Location": SESSION}))
    http.add("PUT", UP + "/videos", (200, {"id": "NEWVID12345"}))
    http.add("POST", UP + "/thumbnails/set", {"items": [{"default": {"url": "u"}}]})
    http.add("POST", API + "/playlistItems", {"id": "PLI1"})
    r = a.post("", target="https://www.youtube.com/playlist?list=PLabcdefghijklmnop",
               media=["https://cdn.example/media/My%20Clip.mp4", str(thumb)])
    init = http.last("POST", "/upload/youtube/v3/videos")
    assert init["json"]["snippet"]["title"] == "My Clip" and init["json"]["snippet"]["categoryId"] == "20"
    assert http.last("PUT")["data"] == b"VIDEOBYTES"
    t = http.last("POST", "/thumbnails/set")
    assert t["params"] == {"videoId": "NEWVID12345", "uploadType": "media"}
    assert t["data"] == b"JPEGDATA" and t["headers"]["Content-Type"] == "image/jpeg"
    p = http.last("POST", "/playlistItems")
    assert p["params"] == {"part": "snippet"}
    assert p["json"] == {"snippet": {"playlistId": "PLabcdefghijklmnop",
                                     "resourceId": {"kind": "youtube#video", "videoId": "NEWVID12345"}}}
    assert r.raw["playlist_item"] == {"id": "PLI1"}


def test_post_thumbnail_failure_does_not_fail_post(tmp_path):
    v = tmp_path / "a.mp4"
    v.write_bytes(b"x")
    img = tmp_path / "a.png"
    img.write_bytes(b"p")
    a, http = make()
    http.add("POST", UP + "/videos", (200, {}, {"Location": SESSION}))
    http.add("PUT", UP + "/videos", (200, {"id": "NEWVID12345"}))
    http.add("POST", UP + "/thumbnails/set", (403, {"error": {"code": 403, "message": "not verified",
                                                              "errors": [{"reason": "forbidden"}]}}))
    r = a.post("hello", media=[str(v), str(img)])
    assert r.id == "NEWVID12345" and "forbidden" in r.raw["thumbnail_error"]


def test_post_target_own_channel_means_no_playlist(tmp_path):
    v = tmp_path / "a.mp4"
    v.write_bytes(b"x")
    a, http = make()
    add_channel(http)
    http.add("POST", UP + "/videos", (200, {}, {"Location": SESSION}))
    http.add("PUT", UP + "/videos", (200, {"id": "NEWVID12345"}))
    a.post("hello", target="@mychan", media=[str(v)])
    assert not calls(http, "POST", "/playlistItems")


@pytest.mark.parametrize("media", [None, [], ["a.mp4", "b.mp4"], ["a.jpg"], ["a.mp4", "b.jpg", "c.png"]])
def test_post_requires_exactly_one_video(media):
    a, http = make()
    with pytest.raises(PlatformError, match="exactly one video"):
        a.post("text", media=media)
    assert http.calls == []


def test_post_missing_file():
    a, _ = make()
    with pytest.raises(PlatformError, match="not found"):
        a.post("text", media=["/nonexistent/clip.mp4"])


# ----------------------------------------------------------------- poll
def cm(cid, author_id, name, text, published, video=VID):
    return {"id": cid, "snippet": {"authorDisplayName": name, "authorChannelId": {"value": author_id},
                                   "textDisplay": text, "publishedAt": published, "videoId": video}}


def thread(tid, top, replies=(), total=None, channel=ME, video=VID):
    t = {"id": tid, "snippet": {"channelId": channel, "videoId": video, "topLevelComment": top,
                                "totalReplyCount": len(replies) if total is None else total}}
    if replies:
        t["replies"] = {"comments": list(replies)}
    return t


def test_poll_kinds_threads_reply_to_cursor_and_own_filtering():
    a, http = make()
    add_channel(http)
    first = {"items": [thread("UgOld", cm("UgOld", "UCbob", "@bob", "old", "2026-11-18T09:00:00Z"))]}
    second = {"nextPageToken": "p2", "items": [
        thread("UgA", cm("UgA", "UCalice", "@alice", "<b>love</b> it &amp; more", "2026-11-18T10:00:00Z")),
        thread("UgB", cm("UgB", ME, "@mychan", "pinned note", "2026-11-18T08:00:00Z"),
               [cm("UgB.r1", "UCbob", "@bob", "thanks", "2026-11-18T10:01:00Z")]),
        thread("UgC", cm("UgC", "UCcarl", "@carl", "q", "2026-11-18T07:00:00Z"),
               [cm("UgC.r0", "UCx", "@x", "first", "2026-11-18T07:30:00Z")], total=4),
        thread("UgD", cm("UgD", "UCfay", "@fay", "hm", "2026-11-18T06:00:00Z"),
               [cm("UgD.r1", "UCgus", "@gus", "nice", "2026-11-18T10:05:00Z")]),
        thread("UgE", cm("UgE", ME, "@mychan", "my own", "2026-11-18T10:06:00Z")),
    ]}
    watched = {"items": [thread("UgW", cm("UgW", ME, "@mychan", "hi", "2026-11-18T09:58:00Z", OTHER_VID),
                                [cm("UgW.r1", "UChank", "@hank", "hello back", "2026-11-18T10:07:00Z", OTHER_VID)],
                                channel="UCother", video=OTHER_VID)]}
    http.add("GET", API + "/commentThreads", first, second, watched, {"items": []})
    http.add("GET", API + "/comments", {"items": [
        cm("UgC.r0", "UCx", "@x", "first", "2026-11-18T07:30:00Z"),
        cm("UgC.r2", "UCdan", "@dan", "hey @MyChan look", "2026-11-18T10:02:00Z"),
        cm("UgC.r3", ME, "@mychan", "me too", "2026-11-18T10:03:00Z"),
        cm("UgC.r4", "UCerin", "@erin", "ok", "2026-11-18T10:04:00Z"),
    ]})
    http.add("POST", API + "/commentThreads", {"id": "UgW", "snippet": {"videoId": OTHER_VID}})

    state = {}
    items = a.poll(state)
    assert [i.id for i in items] == ["UgOld"]
    assert state["since"] == YouTubeAdapter._ts("2026-11-18T09:00:00Z")
    assert state["counts"] == {"UgOld": 0}
    p = http.last("GET", "/commentThreads")["params"]
    assert p == {"part": "snippet,replies", "allThreadsRelatedToChannelId": ME, "order": "time",
                 "maxResults": 100, "textFormat": "plainText"}

    a.comment(OTHER_VID, "hi")  # puts the new thread on the watch list
    n_before = len(http.calls)
    items = a.poll(state)
    got = [(i.kind, i.id, i.thread, i.reply_to["target"], i.author) for i in items]
    assert got == [
        ("comment", "UgA", "UgA", "UgA", "@alice"),
        ("reply", "UgB.r1", "UgB", "UgB.r1", "@bob"),
        ("mention", "UgC.r2", "UgC", "UgC.r2", "@dan"),
        ("reply", "UgC.r4", "UgC", "UgC.r4", "@erin"),
        ("comment", "UgD.r1", "UgD", "UgD.r1", "@gus"),
        ("reply", "UgW.r1", "UgW", "UgW.r1", "@hank"),
    ]
    assert all(i.reply_to["action"] == "comment" for i in items)
    assert items[0].text == "love it & more" and items[0].author_id == "UCalice"
    assert items[0].url == f"https://www.youtube.com/watch?v={VID}&lc=UgA"
    assert items[-1].url == f"https://www.youtube.com/watch?v={OTHER_VID}&lc=UgW.r1"
    assert items[0].ts == YouTubeAdapter._ts("2026-11-18T10:00:00Z")
    new_calls = http.calls[n_before:]
    tl = [c for c in new_calls if c["method"] == "GET" and c["url"].endswith("/commentThreads")]
    assert len(tl) == 2  # oldest thread on page 1 is behind the cursor -> no page 2
    assert tl[1]["params"] == {"part": "snippet,replies", "id": "UgW", "textFormat": "plainText"}
    exp = [c for c in new_calls if c["url"].endswith("/comments")]
    assert len(exp) == 1 and exp[0]["params"] == {"part": "snippet", "parentId": "UgC", "maxResults": 100,
                                                  "textFormat": "plainText"}
    assert state["since"] == YouTubeAdapter._ts("2026-11-18T10:07:00Z")
    assert state["counts"]["UgC"] == 4 and "UgW" in state["watch"]

    # third poll: nothing new; reply counts unchanged -> no reply expansion; deleted watched thread dropped
    http.routes = [r for r in http.routes if not r[1].endswith("/commentThreads")]
    http.add("GET", API + "/commentThreads", second, {"items": []})
    n_before = len(http.calls)
    assert a.poll(state) == []
    assert not [c for c in http.calls[n_before:] if c["url"].endswith("/comments")]
    assert http.last("GET", "/commentThreads")["params"]["id"] == "UgW"
    assert state["watch"] == {}
    assert state["since"] == YouTubeAdapter._ts("2026-11-18T10:07:00Z")


def test_poll_pages_while_newer_than_cursor():
    a, http = make()
    add_channel(http)
    page1 = {"nextPageToken": "p2", "items": [
        thread("UgN1", cm("UgN1", "UCa", "@a", "x", "2026-11-18T12:00:00Z"))]}
    page2 = {"items": [thread("UgN2", cm("UgN2", "UCb", "@b", "y", "2026-11-18T11:30:00Z"))]}
    http.add("GET", API + "/commentThreads", page1, page2)
    state = {"since": YouTubeAdapter._ts("2026-11-18T11:00:00Z")}
    items = a.poll(state)
    assert [i.id for i in items] == ["UgN2", "UgN1"]
    pages = calls(http, "GET", "/commentThreads")
    assert "pageToken" not in pages[0]["params"] and pages[1]["params"]["pageToken"] == "p2"
    assert state["since"] == YouTubeAdapter._ts("2026-11-18T12:00:00Z")


def test_poll_first_run_does_not_expand_replies_and_sets_cursor_when_empty():
    a, http = make()
    add_channel(http)
    http.add("GET", API + "/commentThreads", {"items": []})
    state = {}
    assert a.poll(state) == []
    assert state["since"] > 0 and state["watch"] == {} and state["counts"] == {}
    assert not calls(http, "GET", "/comments")


def test_youtube_text_and_timestamps():
    assert YouTubeAdapter._youtube_text('a<br>b <a href="x">link</a> &quot;q&quot; <3') == 'a\nb link "q" <3'
    assert YouTubeAdapter._ts("2026-11-18T10:00:00Z") == 1794996000.0
    assert YouTubeAdapter._ts("2026-11-18T11:00:00.5+01:00") == 1794996000.5
    assert YouTubeAdapter._ts("") == 0.0


def test_poll_catches_late_indexed_comment_once():
    a, http = make()
    add_channel(http)
    t1 = thread("UgL1", cm("UgL1", "UCa", "@a", "first", "2026-11-18T10:05:00Z"))
    late = thread("UgL0", cm("UgL0", "UCb", "@b", "late", "2026-11-18T10:03:00Z"))
    http.add("GET", API + "/commentThreads", {"items": [t1]}, {"items": [t1, late]}, {"items": [t1, late]})
    state = {"since": YouTubeAdapter._ts("2026-11-18T10:00:00Z")}
    assert [i.id for i in a.poll(state)] == ["UgL1"]
    assert state["recent"] == ["UgL1"]
    assert [i.id for i in a.poll(state)] == ["UgL0"]  # older than the cursor but inside the overlap window
    assert state["recent"] == ["UgL0", "UgL1"]
    assert a.poll(state) == []
