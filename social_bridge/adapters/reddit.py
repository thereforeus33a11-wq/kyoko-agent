"""Reddit (OAuth2 'script' app with password grant, or any app with a refresh token; API host oauth.reddit.com)."""
import base64
import html
import mimetypes
import os
import re
import time
import urllib.parse

from ..base import Adapter, Incoming, PlatformError, Result, register


@register
class RedditAdapter(Adapter):
    name = "reddit"
    label = "Reddit"
    actions = ("post", "comment", "dm")
    poll_interval = 60  # Reddit enforces 100 requests/min per OAuth client id
    config_keys = {
        "client_id": "reddit.com/prefs/apps -> 'create another app...' -> type 'script', redirect uri "
                     "http://localhost:8080 -> the ID shown under the app name ('personal use script')",
        "client_secret": "(optional) same app on reddit.com/prefs/apps -> 'secret'; required for 'script' and "
                         "'web app' types, leave empty only for an 'installed app' used with refresh_token",
        "username": "(optional) Reddit username of the account (without u/); required unless refresh_token is "
                    "set; for the password grant it must be a developer of the script app",
        "password": "(optional) password of that account; required unless refresh_token is set (password grant; "
                    "accounts with 2FA must use refresh_token instead)",
        "refresh_token": "(optional) alternative to username + password: a permanent refresh token for this app "
                         "from the OAuth code flow (duration=permanent, scopes: identity submit privatemessages "
                         "history read)",
        "user_agent": "(optional) User-Agent sent to Reddit (default python:social-bridge:v1.0 (by /u/<username>))",
        "mark_read": "(optional) mark fetched inbox items as read on Reddit: true | false (default true)",
    }
    target_help = {
        "post": "subreddit as r/name, name or a subreddit URL; omit to post to your own profile",
        "comment": "post or comment permalink (www/old/new/sh.reddit.com, redd.it, /s/ share link), or fullname "
                   "t3_<id> (post), t1_<id> (comment), t4_<id> (private message); a bare id is a post id",
        "dm": "username as u/name, name or profile URL; r/name messages that subreddit's moderators; "
              "t4_<id> or a message URL replies inside that conversation",
    }

    API = "https://oauth.reddit.com"
    TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
    WEB = "https://www.reddit.com"
    # Inbox notifications can arrive after newer ones (async mention processing, items approved from the
    # spam/AutoModerator queue keep their original created_utc), so poll looks back this far past the cursor.
    LATE_WINDOW = 3600
    INBOX_KINDS = {"username_mention": "mention", "comment_reply": "reply", "post_reply": "comment",
                   "username mention": "mention", "comment reply": "reply", "post reply": "comment"}

    def __init__(self, config, http=None):
        super().__init__(config, http)
        self._token = None
        self._token_exp = 0.0
        self._refresh = self.config.get("refresh_token") or None
        self._account = None

    # ------------------------------------------------------------- auth / transport
    def _ua(self):
        if self.config.get("user_agent"):
            return self.config["user_agent"]
        user = self._clean_user(self.config.get("username") or "") or self._account
        return f"python:social-bridge:v1.0 (by /u/{user})" if user else "python:social-bridge:v1.0"

    def _access_token(self):
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        (client_id,) = self.need("client_id")
        secret = self.config.get("client_secret") or ""
        if self._refresh:
            data = {"grant_type": "refresh_token", "refresh_token": self._refresh}
        else:
            user, password = self.need("username", "password")
            data = {"grant_type": "password", "username": self._clean_user(user), "password": password}
        basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
        res = self.http.post(self.TOKEN_URL, data=data,
                             headers={"Authorization": f"Basic {basic}", "User-Agent": self._ua()})
        if not isinstance(res, dict) or not res.get("access_token"):
            err = res.get("error_description") or res.get("error") if isinstance(res, dict) else res
            raise PlatformError(self.name, f"token request failed: {err}", body=res)
        self._token = res["access_token"]
        self._token_exp = time.time() + float(res.get("expires_in") or 3600)
        if self._refresh and res.get("refresh_token"):
            self._refresh = res["refresh_token"]
        return self._token

    def _api(self, method, path, *, retry=True, **kw):
        headers = {"Authorization": f"Bearer {self._access_token()}", "User-Agent": self._ua()}
        try:
            return self.http.request(method, self.API + path, headers=headers, **kw)
        except PlatformError as e:
            if e.status == 401 and retry:
                self._token = None
                return self._api(method, path, retry=False, **kw)
            raise

    def _data(self, res):
        """Unwrap an api_type=json response; raise its json.errors."""
        j = res.get("json") if isinstance(res, dict) else None
        if not isinstance(j, dict):
            return res if isinstance(res, dict) else {}
        errors = j.get("errors") or []
        if errors:
            parts = []
            for e in errors:
                if isinstance(e, (list, tuple)):
                    msg = ": ".join(str(x) for x in e[:2] if x)
                    parts.append(msg + (f" [{e[2]}]" if len(e) > 2 and e[2] else ""))
                else:
                    parts.append(str(e))
            raise PlatformError(self.name, "; ".join(parts), body=res)
        return j.get("data") or {}

    # ------------------------------------------------------------- target parsing
    @staticmethod
    def _clean_user(value):
        return re.sub(r"^/?(?:u|user)/", "", str(value or "").strip().lstrip("@"), flags=re.I).strip("/")

    @staticmethod
    def _path_of(target):
        t = str(target).strip()
        if "://" in t or re.match(r"(?:[\w-]+\.)*(?:reddit\.com|redd\.it)(?:/|$)", t, re.I):
            return urllib.parse.urlsplit(t if "://" in t else "https://" + t).path, True
        return "/" + t.lstrip("/@"), False

    def _subreddit(self, target):
        t = str(target or "").strip()
        if not t:
            return "u_" + self._account_name()
        path, is_url = self._path_of(t)
        m = re.match(r"/r/([A-Za-z0-9_]+)", path, re.I)
        if m:
            return m.group(1)
        m = re.match(r"/(?:u|user)/([A-Za-z0-9_-]+)", path, re.I)
        if m:
            return "u_" + m.group(1)
        m = re.fullmatch(r"/([A-Za-z0-9_-]+)/?", path)
        if m and not is_url:
            return m.group(1)
        raise PlatformError(self.name, f"can't read a subreddit from {target!r}")

    @staticmethod
    def _recipient(target):
        t = str(target or "").strip()
        path, is_url = RedditAdapter._path_of(t)
        m = re.match(r"/r/([A-Za-z0-9_]+)", path, re.I)
        if m:
            return "/r/" + m.group(1)
        m = re.match(r"/(?:u|user)/([A-Za-z0-9_-]+)", path, re.I)
        if m:
            return m.group(1)
        m = re.fullmatch(r"/([A-Za-z0-9_-]+)/?", path)
        if m and not is_url:
            return m.group(1)
        return None

    @staticmethod
    def _parse_url(target):
        """Fullname from a Reddit URL or path; "share" for an /s/ share link; None if not recognised."""
        t = str(target).strip()
        if "://" not in t:
            t = (RedditAdapter.WEB + t) if t.startswith("/") else "https://" + t
        parts = urllib.parse.urlsplit(t)
        host = (parts.hostname or "").lower()
        path = parts.path
        if host in ("redd.it", "www.redd.it"):
            m = re.match(r"/([a-z0-9]+)/?$", path, re.I)
            return ("t3_" + m.group(1).lower()) if m else None
        if host != "reddit.com" and not host.endswith(".reddit.com"):
            return None
        m = re.search(r"/comments/([a-z0-9]+)((?:/[^/]*)*)", path, re.I)
        if m:
            # /comments/<post>[/<slug>][/comment]/<comment>/
            rest = [seg for seg in m.group(2).split("/") if seg]
            if "comment" in rest[:2] and rest.index("comment") + 1 < len(rest):
                rest = rest[rest.index("comment") + 1:]
            else:
                rest = rest[1:]
            if rest and rest[0].lower() != "comment" and re.fullmatch(r"[a-z0-9]+", rest[0], re.I):
                return "t1_" + rest[0].lower()
            return "t3_" + m.group(1).lower()
        m = re.match(r"/gallery/([a-z0-9]+)", path, re.I)
        if m:
            return "t3_" + m.group(1).lower()
        m = re.match(r"/message/messages/([a-z0-9]+)", path, re.I)
        if m:
            return "t4_" + m.group(1).lower()
        if re.match(r"/(?:r|u|user)/[^/]+/s/[A-Za-z0-9]+", path, re.I):
            return "share"
        return None

    def _thing(self, target, kinds=("t1", "t3", "t4")):
        t = str(target or "").strip()
        m = re.fullmatch(r"(t\d)_([a-z0-9]+)", t, re.I)
        if m:
            if m.group(1).lower() in kinds:
                return t.lower()
        elif re.fullmatch(r"[a-z0-9]{1,13}", t, re.I):
            if "t3" in kinds:
                return "t3_" + t.lower()
        else:
            found = self._parse_url(t)
            if found == "share":
                found = self._resolve_share(t)
            if found and found[:2] in kinds:
                return found
        raise PlatformError(self.name, f"can't read a Reddit {'/'.join(kinds)} target from {target!r}")

    def _resolve_share(self, target):
        url = target if "://" in target else (self.WEB + target if target.startswith("/") else "https://" + target)
        try:
            page = self.http.get(url, raw=True, headers={"User-Agent": self._ua()})
        except PlatformError as e:
            raise PlatformError(self.name, f"couldn't open share link {url} (HTTP {e.status}); "
                                           f"pass the full permalink") from e
        text = page.decode("utf-8", "replace") if isinstance(page, (bytes, bytearray)) else str(page)
        for pat in (r'<link[^>]*rel="canonical"[^>]*href="([^"]+)"',
                    r'<link[^>]*href="([^"]+)"[^>]*rel="canonical"',
                    r'<meta[^>]*property="og:url"[^>]*content="([^"]+)"'):
            m = re.search(pat, text, re.I)
            if m:
                found = self._parse_url(html.unescape(m.group(1)))
                if found and found != "share":
                    return found
        raise PlatformError(self.name, f"couldn't resolve share link {url}; pass the full permalink")

    @staticmethod
    def _shorten(text, limit):
        if len(text) <= limit:
            return text
        cut = text[:limit - 3]
        if " " in cut[limit // 2:]:
            cut = cut.rsplit(" ", 1)[0]
        return cut.rstrip(" ,;:.-") + "..."

    def _account_name(self):
        if not self._account:
            if self.config.get("username"):
                self._account = self._clean_user(self.config["username"])
            else:
                self.whoami()
        return self._account

    # ------------------------------------------------------------- media
    @staticmethod
    def _sniff(b):
        if b[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if b[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        if b[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"
        if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
            return "image/webp"
        if b[4:8] == b"ftyp":
            return "video/quicktime" if b[8:10] == b"qt" else "video/mp4"
        return None

    def _load(self, src):
        src = str(src)
        if re.match(r"https?://", src, re.I):
            content = self.http.get(src, raw=True)
            filename = urllib.parse.unquote(urllib.parse.urlsplit(src).path.rsplit("/", 1)[-1]) or "upload"
        else:
            path = os.path.expanduser(src)
            with open(path, "rb") as fh:
                content = fh.read()
            filename = os.path.basename(path)
        mime = self._sniff(content) or mimetypes.guess_type(filename)[0]
        if not mime or not mime.startswith(("image/", "video/")):
            raise PlatformError(self.name, f"unsupported media type {mime or 'unknown'} for {src}")
        if "." not in filename:
            filename += mimetypes.guess_extension(mime) or ""
        return filename, content, mime

    def _upload(self, item):
        """Media asset upload: lease from Reddit, then multipart POST to the returned S3 URL. -> (url, asset_id)"""
        filename, content, mime = item
        res = self._api("POST", "/api/media/asset.json", data={"filepath": filename, "mimetype": mime})
        args = (res or {}).get("args") or {}
        action = args.get("action") or ""
        fields = {f["name"]: f["value"] for f in args.get("fields") or []}
        if not action or "key" not in fields:
            raise PlatformError(self.name, "media upload lease is missing action/key", body=res)
        upload_url = action if action.startswith("http") else "https:" + action
        self.http.post(upload_url, data=fields, files={"file": (filename, content, mime)}, raw=True)
        return f"{upload_url}/{fields['key']}", str(((res.get("asset") or {}).get("asset_id")) or "")

    def _post_media(self, data, text, media):
        items = [self._load(m) for m in media]
        videos = [i for i in items if i[2].startswith("video/")]
        images = [i for i in items if i[2].startswith("image/")]
        if videos:
            if len(videos) > 1 or len(images) > 1:
                raise PlatformError(self.name, "a Reddit video post takes one video plus one poster image")
            if not images:
                raise PlatformError(self.name, "a Reddit video post needs a poster image: pass media=[video, image]")
            data.update(kind="video", url=self._upload(videos[0])[0], video_poster_url=self._upload(images[0])[0])
        elif len(images) == 1:
            data.update(kind="image", url=self._upload(images[0])[0])
        else:
            return self._post_gallery(data, text, images)
        if text:
            data["text"] = text
        started = time.time()
        res = self._api("POST", "/api/submit", data=data)
        d = self._data(res)
        if d.get("name") or d.get("id"):
            return Result(id=d.get("name") or f"t3_{d['id']}", url=d.get("url") or "", raw=res)
        # Media posts are created asynchronously; the response only carries a websocket URL.
        return self._find_submission(data["sr"], data["title"], started, res, d.get("user_submitted_page") or "")

    def _post_gallery(self, data, text, images):
        if len(images) > 20:
            raise PlatformError(self.name, "a Reddit gallery takes at most 20 images")
        body = {"api_type": "json", "sr": data["sr"], "title": data["title"], "sendreplies": True,
                "nsfw": False, "spoiler": False, "show_error_list": True, "validate_on_submit": True,
                "items": [{"media_id": self._upload(i)[1], "caption": "", "outbound_url": ""} for i in images]}
        if text:
            body["text"] = text
        res = self._api("POST", "/api/submit_gallery_post.json", json=body)
        d = self._data(res)
        url = d.get("url") or ""
        name = str(d.get("name") or d.get("id") or "")
        if name and not name.startswith("t3_"):
            name = "t3_" + name
        if not name and url:
            parsed = self._parse_url(url)
            name = parsed if parsed and parsed != "share" else ""
        return Result(id=name, url=url, raw=res)

    def _find_submission(self, sr, title, started, res, fallback_url):
        sleep = getattr(self.http, "sleep", time.sleep)
        for attempt in range(3):
            try:
                listing = self._api("GET", f"/user/{self._account_name()}/submitted",
                                    params={"limit": 10, "sort": "new", "raw_json": 1})
            except PlatformError:
                break
            for ch in (listing.get("data") or {}).get("children") or []:
                d = ch.get("data") or {}
                if d.get("title") == title and str(d.get("subreddit") or "").lower() == sr.lower() \
                        and float(d.get("created_utc") or 0) >= started - 120:
                    return Result(id=d.get("name") or f"t3_{d.get('id')}", url=self.WEB + (d.get("permalink") or ""),
                                  raw=res)
            if attempt < 2:
                sleep(2)
        return Result(id="", url=fallback_url, raw=res)

    # ------------------------------------------------------------- results
    def _reply_result(self, res):
        things = self._data(res).get("things") or []
        first = things[0] if things else {}
        d = first.get("data") or {}
        name = d.get("name") or (f"{first.get('kind')}_{d['id']}" if d.get("id") else "")
        if name.startswith("t4_"):
            url = f"{self.WEB}/message/messages/{name[3:]}"
        else:
            url = self.WEB + d["permalink"] if d.get("permalink") else ""
        return Result(id=name, url=url, raw=res)

    def _sent_result(self, to, text, res):
        dest = to.lower().replace("/r/", "#")
        try:
            listing = self._api("GET", "/message/sent", params={"limit": 10, "raw_json": 1})
        except PlatformError:
            return Result(id="", url="", raw=res)
        for ch in (listing.get("data") or {}).get("children") or []:
            d = ch.get("data") or {}
            if str(d.get("dest") or "").lower() == dest and (d.get("body") or "").strip() == text.strip():
                return Result(id=d.get("name") or f"t4_{d.get('id')}",
                              url=f"{self.WEB}/message/messages/{d.get('id')}", raw=res)
        return Result(id="", url="", raw=res)

    # ------------------------------------------------------------- actions
    def whoami(self):
        me = self._api("GET", "/api/v1/me", params={"raw_json": 1})
        self._account = me["name"]
        return "u/" + me["name"]

    def post(self, text, target=None, title=None, link=None, media=None):
        sr = self._subreddit(target)
        text = (text or "").strip()
        if not title:
            first, _, rest = text.partition("\n")
            first = first.strip()
            if not first:
                raise PlatformError(self.name, "a Reddit post needs a title")
            if len(first) <= 300:
                title, text = first, rest.strip()
            else:
                title = self._shorten(first, 300)
        data = {"api_type": "json", "sr": sr, "title": title.strip()[:300], "sendreplies": "true",
                "resubmit": "true"}
        if media:
            if link:
                text = f"{text}\n\n{link}".strip()
            return self._post_media(data, text, list(media))
        if link:
            data.update(kind="link", url=link)
            if text:
                data["text"] = text
        else:
            data.update(kind="self", text=text)
        res = self._api("POST", "/api/submit", data=data)
        d = self._data(res)
        name = d.get("name") or (f"t3_{d['id']}" if d.get("id") else "")
        return Result(id=name, url=d.get("url") or "", raw=res)

    def comment(self, target, text):
        thing = self._thing(target)
        res = self._api("POST", "/api/comment", data={"api_type": "json", "thing_id": thing, "text": text})
        return self._reply_result(res)

    def dm(self, target, text):
        t = str(target or "").strip()
        if re.fullmatch(r"t4_[a-z0-9]+", t, re.I) or "/message/messages/" in t:
            thing = self._thing(t, kinds=("t4",))
            res = self._api("POST", "/api/comment", data={"api_type": "json", "thing_id": thing, "text": text})
            return self._reply_result(res)
        to = self._recipient(t)
        if not to:
            raise PlatformError(self.name, f"can't read a Reddit username from {target!r}")
        first = (text or "").strip().split("\n", 1)[0].strip()
        subject = self._shorten(first, 60)
        res = self._api("POST", "/api/compose",
                        data={"api_type": "json", "to": to, "subject": subject or "(no subject)", "text": text})
        self._data(res)
        return self._sent_result(to, text, res)

    def _mark_read(self):
        return str(self.config.get("mark_read", "true")).lower() not in ("false", "0", "no", "off")

    def poll(self, state):
        me = self._account_name().lower()
        mark = self._mark_read()
        since = float(state.get("since") or 0)
        window = since - self.LATE_WINDOW if since else 0

        def created_of(ch):
            return float((ch.get("data") or {}).get("created_utc") or 0)

        def handled(ch):
            # With mark_read on, new=True means this adapter has not returned the item yet.
            return created_of(ch) < window and not (mark and (ch.get("data") or {}).get("new"))

        children, after = [], None
        for _ in range(5):
            params = {"limit": 100, "raw_json": 1, "mark": "false"}
            if after:
                params["after"] = after
            listing = self._api("GET", "/message/inbox", params=params)
            data = (listing or {}).get("data") or {}
            page = data.get("children") or []
            children += page
            after = data.get("after")
            if not since or not after or not page or any(handled(c) for c in page):
                break
        out, newest = [], since
        for ch in children:
            d = ch.get("data") or {}
            created = created_of(ch)
            newest = max(newest, created)
            if (created < window and not d.get("new")) or str(d.get("author") or "").lower() == me:
                continue
            item = self._incoming(ch.get("kind"), d, created)
            if item:
                out.append(item)
        out.sort(key=lambda i: i.ts)
        if newest:
            state["since"] = newest
        unread = [i.id for i in out if i.raw.get("new")]
        if unread and mark:
            try:
                self._api("POST", "/api/read_message", data={"id": ",".join(unread)})
            except PlatformError:
                pass
        return out

    def _incoming(self, kind, d, created):
        name = d.get("name") or f"{kind}_{d.get('id')}"
        author = ("u/" + d["author"]) if d.get("author") else ("r/" + d["subreddit"] if d.get("subreddit") else "")
        body = (d.get("body") or "").strip()
        if kind == "t4":
            first = d.get("first_message_name")
            subject = (d.get("subject") or "").strip()
            return Incoming(
                platform=self.name, kind="dm", id=name, author=author, author_id=d.get("author_fullname") or "",
                text=f"{subject}\n\n{body}" if subject and not first else body,
                url=f"{self.WEB}/message/messages/{d.get('id')}", thread=first or name, ts=created,
                reply_to={"action": "dm", "target": name}, raw=d,
            )
        if kind == "t1":
            ctx = d.get("context") or ""
            m = re.search(r"/comments/([a-z0-9]+)", ctx, re.I)
            thread = ("t3_" + m.group(1).lower()) if m else (d.get("link_id") or d.get("parent_id") or name)
            kind_ = self.INBOX_KINDS.get(d.get("type") or "") or \
                self.INBOX_KINDS.get(str(d.get("subject") or "").lower(), "reply")
            return Incoming(
                platform=self.name, kind=kind_, id=name, author=author, author_id=d.get("author_fullname") or "",
                text=body, url=(self.WEB + ctx) if ctx else "", thread=thread, ts=created,
                reply_to={"action": "comment", "target": name}, raw=d,
            )
        return None
