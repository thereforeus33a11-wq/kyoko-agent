"""YouTube (Data API v3 with an OAuth2 refresh token): video uploads, comments and comment replies.

YouTube has no messaging API, so there is no dm action and no community-post endpoint.
"""
import calendar
import html
import io
import json
import mimetypes
import os
import re
import time
import urllib.parse

from ..base import Adapter, Incoming, PlatformError, Result, register


@register
class YouTubeAdapter(Adapter):
    name = "youtube"
    label = "YouTube"
    actions = ("post", "comment")
    poll_interval = 300  # default Data API quota is 10,000 units/day; one poll costs about 2-5 units
    config_keys = {
        "client_id": "console.cloud.google.com -> APIs & Services -> Library -> enable 'YouTube Data API v3'; then "
                     "Google Auth Platform -> Clients -> Create client (type 'Web application' with authorized "
                     "redirect URI https://developers.google.com/oauthplayground, or 'Desktop app') -> Client ID",
        "client_secret": "the same OAuth client (Google Auth Platform -> Clients -> your client) -> Client secret",
        "refresh_token": "refresh token of the channel's Google account for this client, scopes "
                         "https://www.googleapis.com/auth/youtube.force-ssl and "
                         "https://www.googleapis.com/auth/youtube.upload. OAuth Playground: "
                         "developers.google.com/oauthplayground -> gear icon -> tick 'Use your own OAuth "
                         "credentials', enter client_id/client_secret -> type both scopes into 'Input your own "
                         "scopes' -> Authorize APIs (sign in, pick the channel) -> 'Exchange authorization code for "
                         "tokens' -> Refresh token. Desktop clients: installed-app flow with a loopback redirect, "
                         "access_type=offline&prompt=consent, code exchanged at https://oauth2.googleapis.com/token. "
                         "While the app's publishing status is 'Testing' (Google Auth Platform -> Audience) the "
                         "account must be a test user and Google expires the refresh token after 7 days",
        "privacy": "(optional) privacyStatus for uploads: public | unlisted | private (default public)",
        "category_id": "(optional) video category ID for uploads (default 22 = People & Blogs; IDs from "
                       "videoCategories.list)",
        "made_for_kids": "(optional) status.selfDeclaredMadeForKids for uploads: true | false (default: the "
                         "channel's own setting)",
        "notify_subscribers": "(optional) notify subscribers about uploads: true | false (default true)",
    }
    target_help = {
        "post": "omit to upload to the authorized channel, or a playlist ID / playlist URL (...?list=PL...) to also "
                "add the video to that playlist. media = exactly one video file path or URL (plus optionally one "
                ".jpg/.png used as custom thumbnail); title = video title (default: first line of text); "
                "text (+ link) = description",
        "comment": "video ID or video URL (watch?v=, youtu.be/, /shorts/, /live/, /embed/, m./music.youtube.com) "
                   "for a new top-level comment; comment ID (Ug...), reply ID (Ug....xxx) or a video URL with "
                   "&lc=<comment id> to reply in that comment's thread",
    }

    API = "https://www.googleapis.com/youtube/v3"
    UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    WEB = "https://www.youtube.com"
    VIDEO_ID = r"[A-Za-z0-9_-]{11}"
    UPLOAD_CHUNK = 16 * 1024 * 1024  # resumable upload chunk; Google requires a multiple of 256 KiB
    UPLOAD_RETRIES = 5
    OVERLAP = 600       # seconds re-scanned behind the cursor: comments can appear in the API a little late
    MAX_PAGES = 3       # pages of 100 per listing per poll
    WATCH_MAX = 100     # threads we commented in that poll() re-checks for replies (50 per request)
    WATCH_DAYS = 30

    def __init__(self, config, http=None):
        super().__init__(config, http)
        self._token = None
        self._token_exp = 0.0
        self._channel = None
        self._new_threads = []  # thread ids comment() wrote to; poll() moves them into state["watch"]

    # ------------------------------------------------------------- auth / transport
    def _access_token(self):
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        client_id, secret, refresh = self.need("client_id", "client_secret", "refresh_token")
        try:
            res = self.http.post(self.TOKEN_URL, data={"grant_type": "refresh_token", "client_id": client_id,
                                                       "client_secret": secret, "refresh_token": refresh})
        except PlatformError as e:
            body = e.body if isinstance(e.body, dict) else {}
            if body.get("error") in ("invalid_grant", "invalid_client", "unauthorized_client"):
                why = body.get("error_description") or "refresh_token revoked, expired or issued to another client"
                raise PlatformError(self.name, f"token refresh failed ({body['error']}): {why}",
                                    e.status, e.body) from None
            raise
        if not isinstance(res, dict) or not res.get("access_token"):
            raise PlatformError(self.name, f"token refresh failed: {res}", body=res)
        self._token = res["access_token"]
        self._token_exp = time.time() + float(res.get("expires_in") or 3600)
        return self._token

    def _google_error(self, e):
        err = e.body.get("error") if isinstance(e.body, dict) else None
        if not isinstance(err, dict):
            return e
        reasons = ", ".join(x["reason"] for x in err.get("errors") or [] if isinstance(x, dict) and x.get("reason"))
        prefix = f"HTTP {e.status} {reasons}" if reasons else f"HTTP {e.status}"
        return PlatformError(self.name, f"{prefix}: {err.get('message') or ''}", e.status, e.body)

    def _api(self, method, url, *, headers=None, auth_retry=True, **kw):
        full = url if url.startswith("https://") else self.API + url
        hdrs = {"Authorization": f"Bearer {self._access_token()}"}
        hdrs.update(headers or {})
        try:
            return self.http.request(method, full, headers=hdrs, **kw)
        except PlatformError as e:
            if e.status == 401 and auth_retry:
                self._token = None
                return self._api(method, url, headers=headers, auth_retry=False, **kw)
            raise self._google_error(e) from None

    def _send_raw(self, method, url, *, params=None, json_body=None, data=None, headers=None, retries=0,
                  auth_retry=True):
        """Request that returns (status, lower-cased headers, parsed body) and treats 3xx (308) as success.

        Calls Http._send directly because Http.request returns only the body, and resumable uploads need the
        Location / Range response headers.
        """
        hdrs = {"User-Agent": self.http.user_agent, "Authorization": f"Bearer {self._access_token()}"}
        hdrs.update(headers or {})
        attempt = 0
        while True:
            status, resp_headers, body = self.http._send(method, url, params=params, json_body=json_body, data=data,
                                                         headers=hdrs)
            if (status == 429 or status >= 500) and attempt < retries:
                attempt += 1
                self.http.sleep(min(2.0 ** attempt, 60.0))
                continue
            break
        lowered = {str(k).lower(): v for k, v in (resp_headers or {}).items()}
        text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body or "")
        try:
            parsed = json.loads(text) if text.strip() else {}
        except ValueError:
            parsed = text
        if status == 401 and auth_retry:
            self._token = None
            return self._send_raw(method, url, params=params, json_body=json_body, data=data, headers=headers,
                                  retries=retries, auth_retry=False)
        if status >= 400:
            raise self._google_error(PlatformError(
                self.name, f"HTTP {status} on {method} {url.split('?', 1)[0]}: {text[:500]}", status, parsed))
        return status, lowered, parsed

    def _me(self):
        if not self._channel:
            res = self._api("GET", "/channels", params={"part": "snippet", "mine": "true"})
            items = (res.get("items") or []) if isinstance(res, dict) else []
            if not items:
                raise PlatformError(self.name, "the authorized Google account has no YouTube channel")
            sn = items[0].get("snippet") or {}
            handle = (sn.get("customUrl") or "").strip()
            if handle and not handle.startswith("@"):
                handle = "@" + handle
            self._channel = {"id": items[0]["id"], "handle": handle, "title": sn.get("title") or ""}
        return self._channel

    # ------------------------------------------------------------- parsing helpers
    @classmethod
    def _parse_target(cls, target):
        """-> (video_id | None, comment_id | None). A comment_id may be a reply id '<thread id>.<reply>'."""
        t = str(target or "").strip()
        if re.match(r"(?:https?://)?(?:[\w-]+\.)*(?:youtube\.com|youtu\.be|youtube-nocookie\.com)(?:[/?#]|$)",
                    t, re.I):
            u = urllib.parse.urlsplit(t if "://" in t else "https://" + t)
            q = urllib.parse.parse_qs(u.query)
            if re.match(r"/(?:post/|channel/[^/]+/community|@[^/]+/community)", u.path):
                raise PlatformError(cls.name, "the API cannot comment on community posts")
            lc = (q.get("lc") or [""])[0].strip()
            vid = (q.get("v") or [""])[0].strip()
            if u.netloc.lower().split(":")[0].endswith("youtu.be"):
                vid = u.path.strip("/").split("/")[0]
            if not vid:
                m = re.match(r"/(?:shorts|live|embed|v|e|video|watch)/([A-Za-z0-9_-]{11})(?:[/?#]|$)", u.path)
                vid = m.group(1) if m else ""
            if vid and not re.fullmatch(cls.VIDEO_ID, vid):
                raise PlatformError(cls.name, f"invalid video id in {target!r}")
            if lc and not re.fullmatch(r"[A-Za-z0-9_-]{12,}(?:\.[A-Za-z0-9_-]+)?", lc):
                raise PlatformError(cls.name, f"invalid comment id in {target!r}")
            if not vid and not lc:
                raise PlatformError(cls.name, f"can't read a video or comment id from {target!r}")
            return vid or None, lc or None
        if re.fullmatch(cls.VIDEO_ID, t):
            return t, None
        if re.fullmatch(r"[A-Za-z0-9_-]{12,}(?:\.[A-Za-z0-9_-]+)?", t):
            return None, t
        raise PlatformError(cls.name, f"can't read a video or comment id from {target!r}")

    def _playlist_id(self, target):
        t = str(target or "").strip()
        if not t or t.lower() in ("me", "self", "channel"):
            return None
        if "://" in t or re.match(r"(?:[\w-]+\.)*(?:youtube\.com|youtu\.be)/", t, re.I):
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(t if "://" in t else "https://" + t).query)
            pl = (q.get("list") or [""])[0].strip()
            if pl:
                return pl
            raise PlatformError(self.name, f"post target must be a playlist ID or playlist URL, got {target!r}")
        me = self._me()
        if t in (me["id"],) or (me["handle"] and t.lstrip("@").lower() == me["handle"].lstrip("@").lower()):
            return None
        if re.fullmatch(r"[A-Za-z0-9_-]{12,64}", t):
            return t
        raise PlatformError(self.name, f"post target must be a playlist ID or playlist URL, got {target!r}")

    @staticmethod
    def _media_name(src):
        if re.match(r"https?://", src, re.I):
            return urllib.parse.unquote(urllib.parse.urlsplit(src).path.rsplit("/", 1)[-1])
        return os.path.basename(src[7:] if src.startswith("file://") else src)

    def _mime(self, src):
        return mimetypes.guess_type(self._media_name(src))[0] or ""

    def _open_media(self, src):
        """-> (binary file object, size, name) for a local path or an http(s) URL."""
        if re.match(r"https?://", src, re.I):
            data = self.http.get(src, raw=True)
            return io.BytesIO(data), len(data), self._media_name(src)
        path = os.path.expanduser(src[7:] if src.startswith("file://") else src)
        if not os.path.isfile(path):
            raise PlatformError(self.name, f"media file not found: {src}")
        return open(path, "rb"), os.path.getsize(path), os.path.basename(path)

    @staticmethod
    def _flag(value):
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    @staticmethod
    def _clean(text):
        # The API rejects '<' and '>' in titles and descriptions.
        return (text or "").replace("<", "\u2039").replace(">", "\u203a")

    @staticmethod
    def _youtube_text(value):
        t = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
        t = re.sub(r"</?(?:a|b|i|s|u|p|span|strong|em)(?:\s[^>]*)?>", "", t, flags=re.I)
        return html.unescape(t).strip()

    @staticmethod
    def _ts(value):
        """RFC 3339 timestamp -> unix seconds (0.0 if missing)."""
        m = re.match(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(\.\d+)?(Z|[+-]\d\d:?\d\d)?",
                     str(value or ""))
        if not m:
            return 0.0
        secs = calendar.timegm(tuple(int(x) for x in m.groups()[:6])) + float(m.group(7) or 0)
        tz = m.group(8) or "Z"
        if tz != "Z":
            hours, minutes = int(tz[1:3]), int(tz[-2:])
            secs -= (1 if tz[0] == "+" else -1) * (hours * 3600 + minutes * 60)
        return secs

    @staticmethod
    def _published(c):
        return ((c or {}).get("snippet") or {}).get("publishedAt")

    @staticmethod
    def _author_id(c):
        return ((c.get("snippet") or {}).get("authorChannelId") or {}).get("value") or ""

    @staticmethod
    def _mentions(text, handle):
        if not handle:
            return False
        return re.search(r"(?<![\w.@-])" + re.escape(handle) + r"(?![\w-]|\.\w)", text or "", re.I) is not None

    def _comment_url(self, video_id, comment_id):
        if not video_id:
            return ""
        return f"{self.WEB}/watch?v={video_id}" + (f"&lc={comment_id}" if comment_id else "")

    # ------------------------------------------------------------- upload
    def _upload_video(self, src, meta, params):
        fh, size, name = self._open_media(src)
        try:
            if not size:
                raise PlatformError(self.name, f"media file is empty: {src}")
            guessed = mimetypes.guess_type(name)[0] or ""
            mime = guessed if guessed.startswith("video/") else "application/octet-stream"
            _, hdrs, _ = self._send_raw(
                "POST", self.UPLOAD + "/videos", params=dict(params, uploadType="resumable"), json_body=meta,
                headers={"Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": mime,
                         "X-Upload-Content-Length": str(size)}, retries=self.http.max_retries)
            session = hdrs.get("location")
            if not session:
                raise PlatformError(self.name, "upload session was not created (no Location header)")
            offset, failures, stalls = 0, 0, 0
            while True:
                try:
                    if failures:  # ask the server how much it has before resuming
                        status, hdrs, body = self._send_raw("PUT", session, data=b"",
                                                            headers={"Content-Range": f"bytes */{size}"})
                    else:
                        fh.seek(offset)
                        chunk = fh.read(self.UPLOAD_CHUNK)
                        status, hdrs, body = self._send_raw(
                            "PUT", session, data=chunk,
                            headers={"Content-Type": mime,
                                     "Content-Range": f"bytes {offset}-{offset + len(chunk) - 1}/{size}"})
                except (OSError, PlatformError) as e:
                    status_code = getattr(e, "status", None) or 0
                    if isinstance(e, PlatformError) and status_code != 429 and status_code < 500:
                        raise
                    failures += 1
                    if failures > self.UPLOAD_RETRIES:
                        raise
                    self.http.sleep(min(2.0 ** failures, 60.0))
                    continue
                if status in (200, 201):
                    if not isinstance(body, dict) or not body.get("id"):
                        raise PlatformError(self.name, f"upload finished without a video id: {body}", body=body)
                    return body
                m = re.search(r"(\d+)\s*-\s*(\d+)", hdrs.get("range") or "")
                new_offset = int(m.group(2)) + 1 if m else 0
                stalls = stalls + 1 if (not failures and new_offset <= offset) else 0
                if stalls > self.UPLOAD_RETRIES:
                    raise PlatformError(self.name, "upload is not progressing (server keeps the same offset)")
                offset, failures = new_offset, 0
        finally:
            fh.close()

    def _set_thumbnail(self, video_id, src):
        fh, _, name = self._open_media(src)
        try:
            data = fh.read()
        finally:
            fh.close()
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        return self._api("POST", self.UPLOAD + "/thumbnails/set",
                         params={"videoId": video_id, "uploadType": "media"}, data=data, headers={"Content-Type": mime})

    # ------------------------------------------------------------- actions
    def whoami(self):
        me = self._me()
        return me["handle"] or me["title"]

    def post(self, text, target=None, title=None, link=None, media=None):
        items = [str(m).strip() for m in (media or []) if str(m or "").strip()]
        images = [m for m in items if self._mime(m).startswith("image/")]
        videos = [m for m in items if m not in images]
        if len(videos) != 1 or len(images) > 1:
            raise PlatformError(self.name, "post uploads a video: media must hold exactly one video file path or URL "
                                           "(plus optionally one image as thumbnail); the API has no text posts")
        playlist = self._playlist_id(target)
        description = (text or "").strip()
        if link:
            description = f"{description}\n\n{link}".strip()
        first_line = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
        name = (title or "").strip() or first_line or os.path.splitext(self._media_name(videos[0]))[0] or "Video"
        snippet = {
            "title": self._clean(name)[:100],  # API limits: title 100 characters, description 5000 bytes
            "description": self._clean(description).encode("utf-8")[:5000].decode("utf-8", "ignore"),
            "categoryId": str(self.config.get("category_id") or "22"),
        }
        # API projects that have not passed YouTube's compliance audit get uploads locked to private.
        status = {"privacyStatus": str(self.config.get("privacy") or "public").strip().lower()}
        if self.config.get("made_for_kids") not in (None, ""):
            status["selfDeclaredMadeForKids"] = self._flag(self.config["made_for_kids"])
        params = {"part": "snippet,status"}
        notify = self.config.get("notify_subscribers")
        if notify not in (None, "") and not self._flag(notify):
            params["notifySubscribers"] = "false"
        res = self._upload_video(videos[0], {"snippet": snippet, "status": status}, params)
        vid = res["id"]
        raw = dict(res)
        if images:
            try:
                raw["thumbnail"] = self._set_thumbnail(vid, images[0])
            except PlatformError as e:  # the video is already up; report instead of failing the post
                raw["thumbnail_error"] = str(e)
        if playlist:
            try:
                raw["playlist_item"] = self._api("POST", "/playlistItems", params={"part": "snippet"}, json={
                    "snippet": {"playlistId": playlist, "resourceId": {"kind": "youtube#video", "videoId": vid}}})
            except PlatformError as e:
                raw["playlist_error"] = str(e)
        return Result(id=vid, url=f"{self.WEB}/watch?v={vid}", raw=raw)

    def _with_mention(self, reply_id, text):
        """Replies to a reply start with '@author', as the YouTube apps do."""
        try:
            res = self._api("GET", "/comments",
                            params={"part": "snippet", "id": reply_id, "textFormat": "plainText"})
            items = res.get("items") or []
            if not items:
                return text
            author = (items[0].get("snippet") or {}).get("authorDisplayName") or ""
            if not author.startswith("@") or self._author_id(items[0]) == self._me()["id"]:
                return text
        except PlatformError:
            return text
        return text if author.lower() in text.lower() else f"{author} {text}"

    def comment(self, target, text):
        vid, cid = self._parse_target(target)
        if cid:
            parent = cid.split(".", 1)[0]  # replies always attach to the top-level comment (= thread id)
            if "." in cid:
                text = self._with_mention(cid, text)
            res = self._api("POST", "/comments", params={"part": "snippet"},
                            json={"snippet": {"parentId": parent, "textOriginal": text}})
            thread = parent
            vid = vid or (res.get("snippet") or {}).get("videoId") or ""
        else:
            res = self._api("POST", "/commentThreads", params={"part": "snippet"}, json={
                "snippet": {"videoId": vid, "topLevelComment": {"snippet": {"textOriginal": text}}}})
            thread = res.get("id") or ""
        new_id = res.get("id") or ""
        if thread:
            self._new_threads.append(thread)
        return Result(id=new_id, url=self._comment_url(vid, new_id), raw=res)

    # ------------------------------------------------------------- polling
    def _thread_replies(self, thread_id):
        out, token = [], None
        for _ in range(self.MAX_PAGES):
            params = {"part": "snippet", "parentId": thread_id, "maxResults": 100, "textFormat": "plainText"}
            if token:
                params["pageToken"] = token
            res = self._api("GET", "/comments", params=params)
            out += res.get("items") or []
            token = res.get("nextPageToken")
            if not token:
                break
        return out

    def _watchlist(self, state):
        watch = dict(state.get("watch") or {})
        now = time.time()
        while self._new_threads:
            watch[self._new_threads.pop(0)] = now
        horizon = now - self.WATCH_DAYS * 86400
        keep = sorted(((k, v) for k, v in watch.items() if v >= horizon), key=lambda kv: kv[1])[-self.WATCH_MAX:]
        return dict(keep)

    def poll(self, state):
        me = self._me()
        since = state.get("since")
        cutoff = float(since) - self.OVERLAP if since else None

        # 1) comment threads on our own videos, newest first
        threads, token = [], None
        for _ in range(self.MAX_PAGES if cutoff is not None else 1):
            params = {"part": "snippet,replies", "allThreadsRelatedToChannelId": me["id"], "order": "time",
                      "maxResults": 100, "textFormat": "plainText"}
            if token:
                params["pageToken"] = token
            res = self._api("GET", "/commentThreads", params=params)
            page = res.get("items") or []
            threads += page
            token = res.get("nextPageToken")
            if not token or not page or cutoff is None:
                break
            oldest = min(self._ts(self._published((t.get("snippet") or {}).get("topLevelComment"))) for t in page)
            if oldest <= cutoff:
                break
        own_threads = {t.get("id") for t in threads}

        # 2) threads we commented in elsewhere (or outside the window above)
        watch = self._watchlist(state)
        extra = [tid for tid in watch if tid not in own_threads]
        for i in range(0, len(extra), 50):
            chunk = extra[i:i + 50]
            res = self._api("GET", "/commentThreads",
                            params={"part": "snippet,replies", "id": ",".join(chunk), "textFormat": "plainText"})
            got = res.get("items") or []
            threads += got
            for gone in set(chunk) - {t.get("id") for t in got}:
                watch.pop(gone, None)
        state["watch"] = watch

        counts, new_counts = state.get("counts") or {}, {}
        recent = set(state.get("recent") or [])  # ids already returned inside the overlap window
        out, window, latest = [], [], float(since or 0)
        for t in threads:
            tid = t.get("id") or ""
            sn = t.get("snippet") or {}
            top = sn.get("topLevelComment") or {}
            video_id = sn.get("videoId") or (top.get("snippet") or {}).get("videoId") or ""
            replies = (t.get("replies") or {}).get("comments") or []
            total = int(sn.get("totalReplyCount") or 0)
            # the inline replies are only a subset; fetch the rest when the count changed since last poll
            if cutoff is not None and total > len(replies) and counts.get(tid) != total:
                replies = self._thread_replies(tid) or replies
            new_counts[tid] = total
            on_own_video = tid in own_threads or sn.get("channelId") == me["id"]
            top_is_mine = self._author_id(top) == me["id"]
            my_reply_times = [self._ts(self._published(r)) for r in replies if self._author_id(r) == me["id"]]
            for c, is_top in [(top, True)] + [(r, False) for r in replies]:
                if not c:
                    continue
                csn = c.get("snippet") or {}
                ts = self._ts(csn.get("publishedAt"))
                latest = max(latest, ts)
                if self._author_id(c) == me["id"] or (cutoff is not None and ts <= cutoff):
                    continue
                text = self._youtube_text(csn.get("textDisplay") or csn.get("textOriginal"))
                if is_top:
                    if not on_own_video:
                        continue
                    kind = "comment"
                elif top_is_mine or tid in watch or any(m < ts for m in my_reply_times):
                    kind = "reply"
                elif self._mentions(text, me["handle"]):
                    kind = "mention"
                elif on_own_video:
                    kind = "comment"
                else:
                    continue
                cid = c.get("id") or tid
                window.append((cid, ts))
                if cid in recent:
                    continue
                out.append(Incoming(
                    platform=self.name, kind=kind, id=cid, author=csn.get("authorDisplayName") or "",
                    author_id=self._author_id(c), text=text,
                    url=self._comment_url(video_id or csn.get("videoId") or "", cid), thread=tid, ts=ts,
                    reply_to={"action": "comment", "target": cid}, raw=t if is_top else c,
                ))
        state["counts"] = new_counts
        state["since"] = latest or time.time()
        state["recent"] = sorted({cid for cid, ts in window if ts > state["since"] - self.OVERLAP})
        out.sort(key=lambda i: i.ts)
        return out
