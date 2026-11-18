#!/usr/bin/env python3
"""Social Bridge (single-file build) — lets an AI post, comment and DM across social platforms,
with a live oversight dashboard.  Requires: pip install requests

    python social_bridge.py init      # writes social_bridge.json
    python social_bridge.py check     # logs in to each enabled platform
    python social_bridge.py serve     # API + dashboard on http://127.0.0.1:8765
    python social_bridge.py tools     # tool definitions for your AI
"""
# ============================================================================
# social_bridge/base.py — Shared building blocks for platform adapters: data types, HTTP client, OAuth1 signing, registry.
# ============================================================================
import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
from dataclasses import asdict, dataclass, field

import requests

ACTIONS = ("post", "comment", "dm")
ADAPTERS = {}  # platform name -> Adapter subclass


def register(cls):
    """Class decorator: makes an adapter available under cls.name."""
    ADAPTERS[cls.name] = cls
    return cls


class PlatformError(Exception):
    def __init__(self, platform, message, status=None, body=None):
        super().__init__(f"[{platform}] {message}")
        self.platform = platform
        self.status = status
        self.body = body


class NotSupported(PlatformError):
    pass


@dataclass
class Result:
    """What an outgoing action produced."""
    id: str
    url: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self):
        return {"id": self.id, "url": self.url}


@dataclass
class Incoming:
    """Something that arrived for the account: a DM, a mention, a comment or reply on our content."""
    platform: str
    kind: str          # "dm" | "mention" | "comment" | "reply"
    id: str            # platform-native id of this item (used for de-duplication)
    author: str        # human-readable handle / name
    text: str
    reply_to: dict     # how to answer it: {"action": "comment" | "dm", "target": "<target string>"}
    author_id: str = ""
    url: str = ""
    thread: str = ""   # conversation key used to group history (e.g. DM convo id, post id)
    ts: float = 0.0    # unix seconds (0 if unknown)
    raw: dict = field(default_factory=dict)

    def to_dict(self):
        d = asdict(self)
        d.pop("raw", None)
        return d


class Http:
    """requests wrapper: JSON by default, retries on 429/5xx (honours Retry-After), raises PlatformError."""

    def __init__(self, platform, timeout=30, max_retries=3, user_agent="social-bridge/1.0"):
        self.platform = platform
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent
        self.session = requests.Session()
        self.sleep = time.sleep

    # Tests replace this. Returns (status, headers, body_bytes).
    def _send(self, method, url, params=None, json_body=None, data=None, headers=None, files=None, auth=None):
        resp = self.session.request(method, url, params=params, json=json_body, data=data, headers=headers,
                                    files=files, auth=auth, timeout=self.timeout)
        return resp.status_code, dict(resp.headers), resp.content

    def request(self, method, url, *, params=None, json=None, data=None, headers=None, files=None, auth=None,
                raw=False):
        hdrs = {"User-Agent": self.user_agent}
        hdrs.update(headers or {})
        attempt = 0
        while True:
            status, resp_headers, body = self._send(method, url, params=params, json_body=json, data=data,
                                                    headers=hdrs, files=files, auth=auth)
            if (status == 429 or status >= 500) and attempt < self.max_retries:
                attempt += 1
                wait = _retry_after(resp_headers, attempt)
                self.sleep(wait)
                continue
            if status >= 400:
                text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)
                try:
                    parsed = json_loads(text)
                except ValueError:
                    parsed = text
                raise PlatformError(self.platform, f"HTTP {status} on {method} {url}: {text[:500]}", status, parsed)
            if raw:
                return body
            if not body:
                return {}
            text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)
            try:
                return json_loads(text)
            except ValueError:
                return text

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def put(self, url, **kw):
        return self.request("PUT", url, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)


def json_loads(text):
    return json.loads(text)


def _retry_after(headers, attempt):
    lowered = {k.lower(): v for k, v in (headers or {}).items()}
    for key in ("retry-after", "x-ratelimit-reset-after"):
        if key in lowered:
            try:
                return min(float(lowered[key]), 120.0)
            except ValueError:
                pass
    return min(2.0 ** attempt, 60.0)


def pct(value):
    """RFC 3986 percent-encoding as required by OAuth 1.0a."""
    return urllib.parse.quote(str(value), safe="~-._")


def oauth1_header(method, url, *, consumer_key, consumer_secret, token, token_secret, params=None,
                  nonce=None, timestamp=None):
    """Build an OAuth 1.0a HMAC-SHA1 Authorization header.

    `params` = form-encoded body params (application/x-www-form-urlencoded) that must be signed.
    Query-string params in `url` are signed automatically. JSON bodies are never signed.
    """
    parts = urllib.parse.urlsplit(url)
    base_url = f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path}"
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(timestamp or int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    pairs += list((params or {}).items()) + list(oauth.items())
    encoded = sorted((pct(k), pct(v)) for k, v in pairs)
    param_string = "&".join(f"{k}={v}" for k, v in encoded)
    base_string = "&".join([method.upper(), pct(base_url), pct(param_string)])
    key = f"{pct(consumer_secret)}&{pct(token_secret)}"
    oauth["oauth_signature"] = base64.b64encode(
        hmac.new(key.encode(), base_string.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{pct(k)}="{pct(v)}"' for k, v in sorted(oauth.items()))


class Adapter:
    """Base class for a platform. Subclasses set the class attributes and override what they support.

    Target conventions (strings, so an AI can pass them straight through):
      post(text, target=...)   target = where to post (subreddit, page id, channel id...) or None for own profile/feed
      comment(target, text)    target = id or URL of the thing being replied to
      dm(target, text)         target = user handle / id / conversation id
    """
    name = ""            # config key, e.g. "reddit"
    label = ""           # display name, e.g. "Reddit"
    actions = ()         # subset of ACTIONS this adapter implements
    poll_interval = 60   # seconds between poll() calls
    config_keys = {}     # key -> description; descriptions starting with "(optional)" are optional
    target_help = {}     # action -> human/AI-readable description of the target format

    def __init__(self, config, http=None):
        self.config = dict(config or {})
        self.http = http or Http(self.name)

    # --- helpers -----------------------------------------------------------
    def need(self, *keys):
        missing = [k for k in keys if not self.config.get(k)]
        if missing:
            raise PlatformError(self.name, f"missing config: {', '.join(missing)}")
        return [self.config[k] for k in keys]

    def unsupported(self, what):
        raise NotSupported(self.name, f"{what} is not supported on {self.label or self.name}")

    # --- interface -----------------------------------------------------------
    def whoami(self):
        """Return the account name this adapter is acting as. Used by `check` and the dashboard."""
        raise NotImplementedError

    def post(self, text, target=None, title=None, link=None, media=None):
        self.unsupported("post")

    def comment(self, target, text):
        self.unsupported("comment")

    def dm(self, target, text):
        self.unsupported("dm")

    def poll(self, state):
        """Return new Incoming items. `state` is a dict the bridge persists between calls (cursors, seen ids)."""
        return []


# ============================================================================
# social_bridge/adapters/reddit.py — Reddit (OAuth2 'script' app with password grant, or any app with a refresh token; API host oauth.reddit.com).
# ============================================================================
import base64
import html
import mimetypes
import os
import re
import time
import urllib.parse



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


# ============================================================================
# social_bridge/adapters/x.py — X (Twitter) API v2: posts, replies, DMs; polls mentions and the DM inbox.
# ============================================================================
import base64
import hashlib
import html
import json
import mimetypes
import os
import re
import threading
import time
from datetime import datetime



@register
class XAdapter(Adapter):
    name = "x"
    label = "X (Twitter)"
    actions = ("post", "comment", "dm")
    poll_interval = 300
    config_keys = {
        "api_key": "OAuth 1.0a API Key (Consumer Key): developer.x.com -> Developer Portal -> Projects & Apps -> "
                   "your App -> Keys and tokens -> Consumer Keys. First set User authentication settings -> "
                   "App permissions to 'Read and write and Direct message'",
        "api_secret": "OAuth 1.0a API Key Secret: same place as api_key (Keys and tokens -> Consumer Keys)",
        "access_token": "OAuth 1.0a Access Token of the account: Keys and tokens -> Authentication Tokens -> "
                        "Access Token and Secret -> Generate (regenerate after changing App permissions)",
        "access_token_secret": "OAuth 1.0a Access Token Secret: generated together with access_token",
        "client_id": "(optional) OAuth 2.0 Client ID, used instead of the four OAuth 1.0a keys: "
                     "Keys and tokens -> OAuth 2.0 Client ID and Client Secret",
        "client_secret": "(optional) OAuth 2.0 Client Secret (confidential clients only: Web App / Automated App "
                         "or Bot): Keys and tokens -> OAuth 2.0 Client ID and Client Secret",
        "refresh_token": "(optional) OAuth 2.0 refresh token of the account, from your Authorization Code + PKCE "
                         "login with scopes tweet.read tweet.write users.read dm.read dm.write media.write "
                         "offline.access",
        "oauth2_access_token": "(optional) current OAuth 2.0 user access token; used until it expires, then "
                               "refresh_token is used",
        "token_file": "(optional) path of the JSON file where the rotated OAuth 2.0 tokens are saved after every "
                      "refresh and read back on start (default ~/.social_bridge/x_oauth2_<hash of refresh_token>"
                      ".json)",
        "poll_dms": "(optional) false to skip reading DMs when polling (default true)",
    }
    target_help = {
        "post": "omit to post on your own timeline; a Community id or x.com/i/communities/<id> URL to post in "
                "that Community; a post URL (x.com/<user>/status/<id>) to quote that post",
        "comment": "post id or post URL (x.com/<user>/status/<id>, twitter.com/..., x.com/i/web/status/<id>) "
                   "to reply to",
        "dm": "@username, numeric user id or x.com/<username> profile URL; a one-to-one conversation id "
              "'<id>-<id>'; for a group conversation the x.com/messages/<conversation_id> URL or "
              "'conversation:<conversation_id>'",
    }

    API = "https://api.x.com"
    TOKEN_URL = "https://api.x.com/2/oauth2/token"
    MEDIA_URL = "https://api.x.com/2/media/upload"
    WEB = "https://x.com"
    CHUNK = 4 * 1024 * 1024
    MAX_PAGES = 5
    MAX_MEDIA_WAIT = 600
    TWEET_FIELDS = "created_at,author_id,conversation_id,in_reply_to_user_id,referenced_tweets,note_tweet"
    DM_FIELDS = "id,text,event_type,sender_id,dm_conversation_id,created_at"
    OAUTH1_KEYS = ("api_key", "api_secret", "access_token", "access_token_secret")
    TOKEN_DIR = "~/.social_bridge"
    O2_FIELDS = ("access_token", "refresh_token", "expires_at")
    RESERVED = {"i", "intent", "home", "messages", "search", "explore", "notifications", "settings", "compose",
                "hashtag", "share", "login", "signup", "tos", "privacy"}

    def __init__(self, config, http=None):
        super().__init__(config, http)
        self._me = None          # {"id", "username"}
        self._ids = {}           # lowercased username -> user id
        self._o2 = None          # OAuth 2.0 tokens: access_token, refresh_token, expires_at, seed
        self._o2_lock = threading.Lock()

    # ------------------------------------------------------------- auth
    def _oauth1(self):
        return all(self.config.get(k) for k in self.OAUTH1_KEYS)

    def _auth(self, method, url, params):
        if self._oauth1():
            c = self.config
            return {"Authorization": oauth1_header(
                method, url, consumer_key=c["api_key"], consumer_secret=c["api_secret"], token=c["access_token"],
                token_secret=c["access_token_secret"], params={k: str(v) for k, v in (params or {}).items()})}
        return {"Authorization": f"Bearer {self._bearer()}"}

    def _o2_seed(self):
        """Fingerprint of the configured OAuth 2.0 tokens; saved tokens from an older login are ignored."""
        src = f"{self.config.get('refresh_token') or ''}|{self.config.get('oauth2_access_token') or ''}"
        return hashlib.sha256(src.encode()).hexdigest()[:16]

    def _token_path(self):
        path = self.config.get("token_file") or os.path.join(self.TOKEN_DIR, f"x_oauth2_{self._o2_seed()}.json")
        return os.path.expanduser(path)

    def _o2_load(self):
        """Tokens saved by the latest refresh of this process or another one (e.g. a CLI command)."""
        try:
            with open(self._token_path(), encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            return {}
        if not isinstance(saved, dict) or saved.get("seed") != self._o2_seed():
            return {}
        return {k: saved[k] for k in self.O2_FIELDS if k in saved}

    def _o2_save(self):
        path = self._token_path()
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            os.makedirs(os.path.dirname(path) or ".", mode=0o700, exist_ok=True)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._o2, f)
            os.replace(tmp, path)
        except OSError as e:
            raise PlatformError(self.name, f"can't save the rotated OAuth 2.0 tokens to {path} ({e}); "
                                           "set token_file to a writable path") from e

    def _o2_state(self):
        if self._o2 is None:
            c = self.config
            if not c.get("client_id") or not (c.get("refresh_token") or c.get("oauth2_access_token")):
                raise PlatformError(self.name, "missing config: api_key, api_secret, access_token, "
                                               "access_token_secret (OAuth 1.0a) or client_id + refresh_token "
                                               "(OAuth 2.0)")
            self._o2 = {"access_token": c.get("oauth2_access_token") or "", "refresh_token": c.get("refresh_token")
                        or "", "expires_at": 0, "seed": self._o2_seed()}
            self._o2.update(self._o2_load())
        return self._o2

    @staticmethod
    def _o2_valid(o2):
        return bool(o2["access_token"]) and (not o2["expires_at"] or o2["expires_at"] - 60 > time.time())

    def _bearer(self):
        o2 = self._o2_state()
        return o2["access_token"] if self._o2_valid(o2) else self._refresh(o2["access_token"])

    def _refresh(self, stale=None):
        """Get a new access token; `stale` is the one that expired or was rejected."""
        with self._o2_lock:
            o2 = self._o2_state()
            saved = self._o2_load()
            if saved.get("access_token") and any(saved.get(k) != o2[k] for k in self.O2_FIELDS):
                o2.update(saved)          # another process refreshed since we last read the file
            if o2["access_token"] != (stale or "") and self._o2_valid(o2):
                return o2["access_token"]  # already refreshed by another thread or process
            if not o2["refresh_token"]:
                raise PlatformError(self.name, "OAuth 2.0 access token expired or rejected and no refresh_token "
                                               "is set")
            client_id = self.config["client_id"]
            data = {"grant_type": "refresh_token", "refresh_token": o2["refresh_token"]}
            headers = {}
            if self.config.get("client_secret"):
                basic = base64.b64encode(f"{client_id}:{self.config['client_secret']}".encode()).decode()
                headers["Authorization"] = f"Basic {basic}"
            else:
                data["client_id"] = client_id
            res = self.http.post(self.TOKEN_URL, data=data, headers=headers)
            if not isinstance(res, dict) or not res.get("access_token"):
                raise PlatformError(self.name, f"token refresh failed: {res}", body=res)
            # X rotates refresh tokens: the old one stops working once a new one is issued, so save at once.
            o2.update(access_token=res["access_token"],
                      refresh_token=res.get("refresh_token") or o2["refresh_token"],
                      expires_at=int(time.time()) + int(res.get("expires_in") or 7200))
            self._o2_save()
            return o2["access_token"]

    def _api(self, method, path, *, params=None, retry=True, **kw):
        url = path if path.startswith("https://") else self.API + path
        headers = self._auth(method, url, params)
        try:
            return self.http.request(method, url, params=params, headers=headers, **kw)
        except PlatformError as e:
            if e.status == 401 and retry and not self._oauth1():
                self._refresh(headers["Authorization"].split(" ", 1)[1])
                return self._api(method, path, params=params, retry=False, **kw)
            raise

    # ------------------------------------------------------------- helpers
    def _my(self):
        if not self._me:
            self.whoami()
        return self._me

    def _flag(self, key, default=True):
        v = self.config.get(key)
        if v is None or v == "":
            return default
        if isinstance(v, str):
            return v.strip().lower() not in ("0", "false", "no", "off")
        return bool(v)

    def _status_url(self, tweet_id, username=None):
        username = username or (self._me or {}).get("username")
        return f"{self.WEB}/{username}/status/{tweet_id}" if username else f"{self.WEB}/i/web/status/{tweet_id}"

    @staticmethod
    def _ts(value):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0

    @staticmethod
    def _tweet_text(t):
        return html.unescape((t.get("note_tweet") or {}).get("text") or t.get("text") or "").strip()

    def _tweet_id(self, target):
        t = str(target or "").strip()
        if re.fullmatch(r"\d+", t):
            return t
        m = re.search(r"/status(?:es)?/(\d+)", t)
        if m:
            return m.group(1)
        raise PlatformError(self.name, f"can't read a post id from {target!r}")

    def _post_target(self, target):
        t = str(target or "").strip()
        if not t or t.lower() in ("me", "profile", "timeline"):
            return {}
        m = re.search(r"/i/communities/(\d+)", t)
        if m or re.fullmatch(r"\d+", t):
            return {"community_id": m.group(1) if m else t}
        if re.search(r"/status(?:es)?/\d+", t):
            return {"quote_tweet_id": self._tweet_id(t)}
        raise PlatformError(self.name, f"can't read a Community or post to quote from {target!r}")

    def _user_id(self, username):
        key = username.lower()
        if key not in self._ids:
            res = self._api("GET", f"/2/users/by/username/{username}")
            d = (res or {}).get("data") or {}
            if not d.get("id"):
                raise PlatformError(self.name, f"user @{username} not found", body=res)
            self._ids[key] = str(d["id"])
        return self._ids[key]

    def _participant(self, t):
        m = re.search(r"[?&](?:recipient_id|user_id)=(\d+)", t) or re.search(r"/i/user/(\d+)", t)
        if m:
            return m.group(1)
        if re.fullmatch(r"\d+", t):
            return t
        m = re.search(r"[?&]screen_name=@?([A-Za-z0-9_]{1,15})(?:&|$)", t)
        if m:
            return self._user_id(m.group(1))
        m = re.match(r"(?i)^(?:https?://)?(?:www\.|mobile\.)?(?:x|twitter)\.com/@?([A-Za-z0-9_]{1,15})(?:[/?#]|$)", t)
        if m and m.group(1).lower() not in self.RESERVED:
            return self._user_id(m.group(1))
        m = re.fullmatch(r"@?([A-Za-z0-9_]{1,15})", t)
        if m:
            return self._user_id(m.group(1))
        raise PlatformError(self.name, f"can't read an X user from {t!r}")

    def _dm_path(self, target):
        t = str(target or "").strip()
        m = (re.fullmatch(r"(?i)(?:dm_)?conversation:\s*(\d+(?:-\d+)?)", t)
             or re.search(r"/(?:messages|i/chat)/(\d+(?:-\d+)?)(?:[/?#]|$)", t))
        conv = m.group(1) if m else (t if re.fullmatch(r"\d+-\d+", t) else None)
        if conv:
            return f"/2/dm_conversations/{conv}/messages"
        return f"/2/dm_conversations/with/{self._participant(t)}/messages"

    # ------------------------------------------------------------- media
    @staticmethod
    def _media_type(name, data):
        head = bytes(data[:16])
        for sig, mtype in ((b"\x89PNG", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF8", "image/gif")):
            if head.startswith(sig):
                return mtype
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return "image/webp"
        if head[4:8] == b"ftyp":
            return "video/quicktime" if head[8:10] == b"qt" else "video/mp4"
        return mimetypes.guess_type(name)[0] or "application/octet-stream"

    def _media_id(self, res):
        d = (res or {}).get("data") or res or {}
        mid = d.get("id") or d.get("media_id_string") or d.get("media_id")
        if not mid:
            raise PlatformError(self.name, f"media upload returned no id: {res}", body=res)
        return str(mid)

    def _upload(self, src):
        src = str(src)
        if re.match(r"(?i)https?://", src):
            data = self.http.get(src, raw=True)
            fname = src.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1] or "media"
        else:
            with open(os.path.expanduser(src), "rb") as f:
                data = f.read()
            fname = os.path.basename(src)
        mtype = self._media_type(fname, data)
        if mtype.startswith("image/") and mtype != "image/gif":
            res = self._api("POST", self.MEDIA_URL, data={"media_category": "tweet_image"},
                            files={"media": (fname, data, mtype)})
            return self._media_id(res)
        if mtype == "image/gif":
            category = "tweet_gif"
        elif mtype.startswith("video/"):
            category = "tweet_video"
        else:
            raise PlatformError(self.name, f"unsupported media type {mtype} for {src}")
        return self._upload_chunked(data, mtype, category)

    def _upload_chunked(self, data, mtype, category):
        init = self._api("POST", f"{self.MEDIA_URL}/initialize",
                         json={"media_type": mtype, "total_bytes": len(data), "media_category": category})
        mid = self._media_id(init)
        for i, off in enumerate(range(0, len(data), self.CHUNK)):
            self._api("POST", f"{self.MEDIA_URL}/{mid}/append", data={"segment_index": str(i)},
                      files={"media": ("blob", data[off:off + self.CHUNK], "application/octet-stream")})
        res = self._api("POST", f"{self.MEDIA_URL}/{mid}/finalize")
        info = ((res or {}).get("data") or res or {}).get("processing_info")
        waited = 0
        while info and info.get("state") in ("pending", "in_progress"):
            if waited >= self.MAX_MEDIA_WAIT:
                raise PlatformError(self.name, f"media {mid} still processing after {waited}s")
            delay = max(1, int(info.get("check_after_secs") or 1))
            self.http.sleep(delay)
            waited += delay
            res = self._api("GET", self.MEDIA_URL, params={"command": "STATUS", "media_id": mid})
            info = ((res or {}).get("data") or res or {}).get("processing_info")
        if info and info.get("state") == "failed":
            raise PlatformError(self.name, f"media processing failed: {info.get('error') or info}", body=res)
        return mid

    # ------------------------------------------------------------- actions
    def whoami(self):
        res = self._api("GET", "/2/users/me")
        d = (res or {}).get("data") or {}
        if not d.get("id"):
            raise PlatformError(self.name, f"unexpected /2/users/me response: {res}", body=res)
        self._me = {"id": str(d["id"]), "username": d.get("username") or ""}
        return "@" + self._me["username"]

    def _create(self, body):
        res = self._api("POST", "/2/tweets", json=body)
        d = (res or {}).get("data") or {}
        if not d.get("id"):
            raise PlatformError(self.name, f"post failed: {res}", body=res)
        return Result(id=str(d["id"]), url=self._status_url(d["id"]), raw=res)

    def post(self, text, target=None, title=None, link=None, media=None):
        text = text or ""
        if title:
            text = f"{title}\n\n{text}" if text else title
        if link:
            text = f"{text}\n\n{link}" if text else link
        body = {"text": text} if text.strip() else {}
        body.update(self._post_target(target))
        media = list(media or [])
        if len(media) > 4:
            raise PlatformError(self.name, "X accepts at most 4 media items per post")
        if media:
            body["media"] = {"media_ids": [self._upload(m) for m in media]}
        return self._create(body)

    def comment(self, target, text):
        return self._create({"text": text, "reply": {"in_reply_to_tweet_id": self._tweet_id(target)}})

    def dm(self, target, text):
        # X only delivers to users who accept DMs from this account; otherwise the API answers 403.
        res = self._api("POST", self._dm_path(target), json={"text": text})
        d = (res or {}).get("data") or {}
        if not d.get("dm_event_id"):
            raise PlatformError(self.name, f"dm failed: {res}", body=res)
        conv = d.get("dm_conversation_id") or ""
        return Result(id=str(d["dm_event_id"]), url=f"{self.WEB}/messages/{conv}" if conv else "", raw=res)

    # ------------------------------------------------------------- polling
    def poll(self, state):
        me = self._my()
        cursors = {}
        items = self._poll_mentions(me, state, cursors)
        if self._flag("poll_dms"):
            items += self._poll_dms(me, state, cursors)
        state.update(cursors)
        return sorted(items, key=lambda i: (i.ts, int(i.id) if i.id.isdigit() else 0))

    def _poll_mentions(self, me, state, cursors):
        since = state.get("mentions_since_id")
        params = {"max_results": "100" if since else "10", "expansions": "author_id,referenced_tweets.id",
                  "tweet.fields": self.TWEET_FIELDS, "user.fields": "username"}
        if since:
            params["since_id"] = since
        tweets, users, refs, newest = [], {}, {}, None
        for _ in range(self.MAX_PAGES if since else 1):
            res = self._api("GET", f"/2/users/{me['id']}/mentions", params=params) or {}
            meta = res.get("meta") or {}
            newest = newest or meta.get("newest_id")
            tweets += res.get("data") or []
            inc = res.get("includes") or {}
            users.update({str(u["id"]): u.get("username") or "" for u in inc.get("users") or []})
            refs.update({str(t["id"]): t for t in inc.get("tweets") or []})
            if not since or not meta.get("next_token"):
                break
            params = dict(params, pagination_token=meta["next_token"])
        if tweets:
            newest = max([int(t["id"]) for t in tweets] + [int(newest or 0)])
        if newest:
            cursors["mentions_since_id"] = str(newest)

        out = []
        for t in tweets:
            author_id = str(t.get("author_id") or "")
            if author_id == me["id"]:
                continue
            kind = "mention"
            if str(t.get("in_reply_to_user_id") or "") == me["id"]:
                parent_id = next((str(r["id"]) for r in t.get("referenced_tweets") or []
                                  if r.get("type") == "replied_to"), None)
                parent = refs.get(parent_id)
                parent_is_reply = parent and any(r.get("type") == "replied_to"
                                                 for r in parent.get("referenced_tweets") or [])
                kind = "comment" if parent and not parent_is_reply else "reply"
            username = users.get(author_id) or ""
            tid = str(t["id"])
            out.append(Incoming(
                platform=self.name, kind=kind, id=tid, author="@" + username if username else author_id,
                author_id=author_id, text=self._tweet_text(t), url=self._status_url(tid, username or "i/web"),
                thread=str(t.get("conversation_id") or tid), ts=self._ts(t.get("created_at")),
                reply_to={"action": "comment", "target": tid}, raw=t,
            ))
        return out

    def _poll_dms(self, me, state, cursors):
        since = state.get("dm_since_id")
        params = {"max_results": "100" if since else "20", "event_types": "MessageCreate",
                  "dm_event.fields": self.DM_FIELDS, "expansions": "sender_id", "user.fields": "username"}
        events, users = [], {}
        for _ in range(self.MAX_PAGES if since else 1):
            res = self._api("GET", "/2/dm_events", params=params) or {}
            inc = res.get("includes") or {}
            users.update({str(u["id"]): u.get("username") or "" for u in inc.get("users") or []})
            reached = False
            for e in res.get("data") or []:
                if since and int(e["id"]) <= int(since):
                    reached = True
                    break
                events.append(e)
            next_token = (res.get("meta") or {}).get("next_token")
            if reached or not since or not next_token:
                break
            params = dict(params, pagination_token=next_token)
        if events:
            cursors["dm_since_id"] = str(max(int(e["id"]) for e in events))

        out = []
        for e in events:
            sender = str(e.get("sender_id") or "")
            if sender == me["id"] or e.get("event_type", "MessageCreate") != "MessageCreate":
                continue
            conv = str(e.get("dm_conversation_id") or "")
            one_to_one = not conv or re.fullmatch(r"\d+-\d+", conv)
            username = users.get(sender) or ""
            out.append(Incoming(
                platform=self.name, kind="dm", id=str(e["id"]), author="@" + username if username else sender,
                author_id=sender, text=html.unescape(e.get("text") or "").strip(),
                url=f"{self.WEB}/messages/{conv}" if conv else "", thread=conv or sender,
                ts=self._ts(e.get("created_at")),
                reply_to={"action": "dm", "target": sender if one_to_one else f"{self.WEB}/messages/{conv}"},
                raw=e,
            ))
        return out


# ============================================================================
# social_bridge/adapters/youtube.py — YouTube (Data API v3 with an OAuth2 refresh token): video uploads, comments and comment replies.
# ============================================================================
import calendar
import html
import io
import json
import mimetypes
import os
import re
import time
import urllib.parse



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


# ============================================================================
# social_bridge/adapters/facebook.py — Facebook Pages via the Graph API: Page posts, comments, Messenger DMs; polls Messenger, comments and tags.
# ============================================================================
import base64
import hashlib
import hmac
import logging
import mimetypes
import os
import re
import urllib.parse
from datetime import datetime



# The Graph API publishes only as a Page; personal profiles cannot post through it.
@register
class FacebookAdapter(Adapter):
    name = "facebook"
    label = "Facebook Page"
    actions = ("post", "comment", "dm")
    poll_interval = 120
    config_keys = {
        "page_access_token": "Long-lived Page access token: developers.facebook.com -> My Apps -> Create App (Business "
                             "type) -> Tools -> Graph API Explorer: select the app, Generate Access Token with "
                             "pages_show_list, pages_read_engagement, pages_read_user_content, pages_manage_posts, "
                             "pages_manage_engagement, pages_messaging; open it in the Access Token Debugger -> "
                             "Extend Access Token, then GET /me/accounts with that token and copy your Page's "
                             "access_token (it does not expire)",
        "page_id": "(optional) Page ID: your Page -> About -> Page transparency, or the id next to the Page in "
                   "GET /me/accounts. Discovered from page_access_token when omitted; required with "
                   "user_access_token",
        "user_access_token": "(optional) user access token used instead of page_access_token: Graph API Explorer -> "
                             "Generate Access Token (same permissions). The Page token is derived from it and "
                             "re-derived when it stops working",
        "app_id": "(optional) App ID: App Dashboard -> App settings -> Basic. With app_secret, a short-lived "
                  "user_access_token is exchanged for a long-lived one",
        "app_secret": "(optional) App Secret: App Dashboard -> App settings -> Basic -> App secret -> Show. Also "
                      "sent as appsecret_proof (needed when 'Require App Secret' is on in Advanced settings)",
        "api_version": "(optional) Graph API version (default v24.0)",
        "message_tag": "(optional) Messenger message tag for DMs, e.g. HUMAN_AGENT (sends with "
                       "messaging_type=MESSAGE_TAG; HUMAN_AGENT needs the Human Agent permission)",
        "poll_posts": "(optional) how many recent Page posts to check for new comments (default 10)",
        "poll_mentions": "(optional) false to skip polling posts the Page is tagged in (default true)",
    }
    target_help = {
        "post": "omit (publishes on the configured Page's feed)",
        "comment": "Page post id (<pageid>_<postid>), comment id (<postid>_<commentid>, answers in that comment's "
                   "thread), photo/video id, or a facebook.com URL: permalink.php?story_fbid=..&id=.., "
                   "/<page>/posts/<id>, /photo?fbid=.., /watch?v=.., /reel/<id>, /<page>/videos/<id>; "
                   "a URL with ?comment_id=.. answers that comment",
        "dm": "Page-scoped user id (PSID) of someone who messaged the Page, or a Messenger conversation id (t_...)",
    }

    GRAPH = "https://graph.facebook.com"
    GRAPH_VIDEO = "https://graph-video.facebook.com"
    WEB = "https://www.facebook.com"
    DEFAULT_VERSION = "v24.0"
    VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".wmv", ".flv", ".3gp", ".mpeg", ".mpg"}
    MSG_FIELDS = "id,updated_time,messages.limit(10){id,message,from,created_time}"
    COMMENT_FIELDS = ("id,permalink_url,updated_time,comments.filter(stream).order(reverse_chronological).limit(50)"
                      "{id,from,message,created_time,permalink_url,parent{id,from}}")
    TAGGED_FIELDS = "id,message,from,created_time,permalink_url"

    def __init__(self, config, http=None):
        super().__init__(config, http)
        self._tok = None   # Page access token in use
        self._me = None    # {"id", "name", "username"} of the Page

    # ------------------------------------------------------------- auth / transport
    def _ver(self):
        v = str(self.config.get("api_version") or self.DEFAULT_VERSION).strip()
        return v if v.startswith("v") else "v" + v

    def _call(self, method, url, token, params=None, **kw):
        p = dict(params or {})
        secret = self.config.get("app_secret")
        if secret:
            p["appsecret_proof"] = hmac.new(str(secret).encode(), token.encode(), hashlib.sha256).hexdigest()
        return self.http.request(method, url, params=p or None, headers={"Authorization": f"Bearer {token}"}, **kw)

    @staticmethod
    def _auth_error(e):
        err = e.body.get("error") if isinstance(e.body, dict) else None
        return e.status == 401 or (isinstance(err, dict) and err.get("code") in (102, 190))

    def _derive_page_token(self):
        user, page = self.need("user_access_token", "page_id")
        if self.config.get("app_id") and self.config.get("app_secret"):
            res = self.http.get(f"{self.GRAPH}/{self._ver()}/oauth/access_token", params={
                "grant_type": "fb_exchange_token", "client_id": self.config["app_id"],
                "client_secret": self.config["app_secret"], "fb_exchange_token": user})
            user = res["access_token"]
        res = self._call("GET", f"{self.GRAPH}/{self._ver()}/{page}", user, params={"fields": "access_token"})
        if not res.get("access_token"):
            raise PlatformError(self.name, f"no Page access token returned for Page {page}")
        return res["access_token"]

    def _token(self):
        if not self._tok:
            if self.config.get("page_access_token"):
                self._tok = self.config["page_access_token"]
            elif self.config.get("user_access_token"):
                self._tok = self._derive_page_token()
            else:
                self.need("page_access_token")
        return self._tok

    def _api(self, method, path, host=None, **kw):
        url = f"{host or self.GRAPH}/{self._ver()}{path}"
        try:
            return self._call(method, url, self._token(), **kw)
        except PlatformError as e:
            if not (self._auth_error(e) and self.config.get("user_access_token")):
                raise
        self._tok = self._derive_page_token()
        return self._call(method, url, self._tok, **kw)

    # ------------------------------------------------------------- helpers
    def _page(self):
        if self._me is None:
            pid = self.config.get("page_id")
            self._me = self._api("GET", f"/{pid}" if pid else "/me", params={"fields": "id,name,username"})
        return self._me

    def _page_id(self):
        return str(self.config.get("page_id") or self._page()["id"])

    @staticmethod
    def _ts(value):
        if not value:
            return 0.0
        if isinstance(value, (int, float)) or str(value).isdigit():
            return float(value)
        s = str(value).replace("Z", "+0000")
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                return datetime.strptime(s, fmt).timestamp()
            except ValueError:
                pass
        return 0.0

    @staticmethod
    def _is_url(m):
        return bool(re.match(r"https?://", m, re.I))

    def _is_video(self, m):
        path = urllib.parse.urlsplit(m).path if self._is_url(m) else m
        return os.path.splitext(path)[1].lower() in self.VIDEO_EXT or \
            (mimetypes.guess_type(path)[0] or "").startswith("video/")

    def _file(self, path):
        if not os.path.isfile(path):
            raise PlatformError(self.name, f"media file not found: {path}")
        with open(path, "rb") as f:
            data = f.read()
        return {"source": (os.path.basename(path), data, mimetypes.guess_type(path)[0] or "application/octet-stream")}

    def _post_url(self, pid):
        pid = str(pid)
        if "_" in pid:
            owner, post = pid.split("_", 1)
            return f"{self.WEB}/{owner}/posts/{post}"
        return f"{self.WEB}/{pid}"

    def _comment_url(self, parent, cid):
        obj, _, c = str(cid).partition("_")
        if not c:
            return ""
        parts = str(parent).split("_")
        if len(parts) == 2 and parts[1] == obj:          # commented on a post <owner>_<obj>
            return f"{self.WEB}/{parts[0]}/posts/{obj}?comment_id={c}"
        owner = self.config.get("page_id") or (self._me or {}).get("id")
        if not owner:
            return ""
        if len(parts) == 2 and parts[0] == obj:          # replied to comment <obj>_<parent>
            return f"{self.WEB}/{owner}/posts/{obj}?comment_id={parts[1]}&reply_comment_id={c}"
        return f"{self.WEB}/{owner}/posts/{obj}?comment_id={c}"

    # ------------------------------------------------------------- target parsing
    def _resolve_page(self, ref, fallback=True):
        if ref.isdigit():
            return ref
        own = self._me or {}
        if ref.lower() in (str(own.get("username") or "").lower(), str(own.get("id") or "")):
            return str(own["id"])
        try:
            return str(self._api("GET", f"/{ref}", params={"fields": "id"})["id"])
        except PlatformError:
            if not fallback:
                raise
            return self._page_id()

    def _find_pfbid(self, pfbid):
        res = self._api("GET", f"/{self._page_id()}/feed", params={"fields": "id,permalink_url", "limit": 100})
        for p in res.get("data", []):
            if pfbid in (p.get("permalink_url") or ""):
                return str(p["id"])
        raise PlatformError(self.name, f"no recent Page post matches {pfbid}; pass the post id (<pageid>_<postid>)")

    def _post_from(self, owner, pid):
        if pid.startswith("pfbid"):
            return self._find_pfbid(pid)
        if "_" in pid or not pid.isdigit():
            return pid
        return f"{self._resolve_page(owner) if owner else self._page_id()}_{pid}"

    def _comment_from(self, comment, post):
        if comment.isdigit():
            if post and re.fullmatch(r"\d+(?:_\d+)?", post):
                return f"{post.split('_')[-1]}_{comment}"
            raise PlatformError(self.name, "can't build a comment id from this URL; pass <postid>_<commentid>")
        try:
            decoded = base64.b64decode(comment + "=" * (-len(comment) % 4), altchars=b"-_").decode()
        except (ValueError, UnicodeDecodeError):
            decoded = ""
        m = re.fullmatch(r"comment:(\d+_\d+)", decoded)
        if not m:
            raise PlatformError(self.name, f"can't read comment_id {comment!r}")
        return m.group(1)

    def _object_id(self, target):
        t = str(target).strip()
        if re.fullmatch(r"\d+(?:_\d+)?", t):
            return t
        if not re.match(r"(?:https?://)?(?:[\w-]+\.)*(?:facebook\.com|fb\.com)(?:/|$)", t, re.I):
            raise PlatformError(self.name, f"can't read a Facebook post or comment id from {t!r}")
        u = urllib.parse.urlsplit(t if "://" in t else "https://" + t)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        segs = [s for s in u.path.split("/") if s]
        post = None
        if q.get("story_fbid"):
            post = self._post_from(q.get("id"), q["story_fbid"])
        elif q.get("fbid"):
            post = q["fbid"]
        elif q.get("v"):
            post = q["v"]
        elif "posts" in segs[:-1]:
            i = segs.index("posts")
            post = self._post_from(segs[i - 1] if i > 0 else None, segs[i + 1])
        else:
            nums = [s for s in segs if re.fullmatch(r"\d+(?:_\d+)?", s)]
            post = nums[-1] if nums else None
        if q.get("comment_id"):
            return self._comment_from(q["comment_id"], post)
        if post:
            return post
        raise PlatformError(self.name, f"can't read a Facebook post or comment id from {t!r}")

    def _psid(self, target, page):
        t = str(target).strip()
        if t.isdigit():
            return t
        if t.startswith("t_"):
            res = self._api("GET", f"/{t}", params={"fields": "participants"})
            for p in (res.get("participants") or {}).get("data", []):
                if str(p.get("id")) != page:
                    return str(p["id"])
            raise PlatformError(self.name, f"no other participant in conversation {t}")
        raise PlatformError(self.name, f"DM target must be a PSID or a conversation id (t_...), got {t!r}")

    # ------------------------------------------------------------- uploads
    def _upload_photo(self, page, m, caption=None, published=True):
        fields = {"published": "true" if published else "false"}
        if caption:
            fields["caption"] = caption
        if self._is_url(m):
            fields["url"] = m
            return self._api("POST", f"/{page}/photos", data=fields)
        return self._api("POST", f"/{page}/photos", data=fields, files=self._file(m))

    def _upload_video(self, page, m, description=None, title=None):
        fields = {}
        if description:
            fields["description"] = description
        if title:
            fields["title"] = title
        if self._is_url(m):
            fields["file_url"] = m
            return self._api("POST", f"/{page}/videos", host=self.GRAPH_VIDEO, data=fields)
        return self._api("POST", f"/{page}/videos", host=self.GRAPH_VIDEO, data=fields, files=self._file(m))

    # ------------------------------------------------------------- actions
    def whoami(self):
        me = self._page()
        name = me.get("name") or str(me.get("id"))
        return f"{name} (@{me['username']})" if me.get("username") else name

    def post(self, text, target=None, title=None, link=None, media=None):
        page = self._page_id()
        if target and str(target).strip():
            t = str(target).strip().rstrip("/")
            ref = urllib.parse.parse_qs(urllib.parse.urlsplit(t).query).get("id", [t.rsplit("/", 1)[-1]])[0]
            if self._resolve_page(ref, fallback=False) != page:
                raise PlatformError(self.name, f"posts can only be published on the configured Page ({page})")
        media = [str(m) for m in (media or [])]
        if not media:
            body = {"message": "\n\n".join(p for p in (title, text) if p)}
            if link:
                body["link"] = link
            res = self._api("POST", f"/{page}/feed", json=body)
            return Result(id=str(res["id"]), url=self._post_url(res["id"]), raw=res)
        videos = [m for m in media if self._is_video(m)]
        if videos:
            if len(media) > 1:
                raise PlatformError(self.name, "a video has to be posted on its own (no other media in the post)")
            desc = "\n\n".join(p for p in (text, link) if p)
            res = self._upload_video(page, videos[0], description=desc, title=title)
            vid = str(res["id"])
            return Result(id=vid, url=f"{self.WEB}/{page}/videos/{vid}", raw=res)
        message = "\n\n".join(p for p in (title, text, link) if p)
        if len(media) == 1:
            res = self._upload_photo(page, media[0], caption=message)
            pid = str(res.get("post_id") or res["id"])
            return Result(id=pid, url=self._post_url(pid), raw=res)
        ids = [str(self._upload_photo(page, m, published=False)["id"]) for m in media]
        body = {"message": message, "attached_media": [{"media_fbid": i} for i in ids]}
        res = self._api("POST", f"/{page}/feed", json=body)
        return Result(id=str(res["id"]), url=self._post_url(res["id"]), raw=res)

    def comment(self, target, text):
        oid = self._object_id(target)
        res = self._api("POST", f"/{oid}/comments", json={"message": text})
        cid = str(res.get("id", ""))
        return Result(id=cid, url=self._comment_url(oid, cid), raw=res)

    def dm(self, target, text):
        page = self._page_id()
        body = {"recipient": {"id": self._psid(target, page)}, "messaging_type": "RESPONSE", "message": {"text": text}}
        # Messenger enforces a 24-hour reply window; message tags extend it for specific use cases.
        if self.config.get("message_tag"):
            body["messaging_type"] = "MESSAGE_TAG"
            body["tag"] = self.config["message_tag"]
        res = self._api("POST", f"/{page}/messages", json=body)
        return Result(id=str(res.get("message_id", "")), url="", raw=res)

    # ------------------------------------------------------------- polling
    def poll(self, state):
        page = self._page_id()
        sections = [self._poll_dms, self._poll_comments]
        if str(self.config.get("poll_mentions", True)).strip().lower() not in ("false", "0", "no", "off"):
            sections.append(self._poll_tagged)
        # Each section works on a copy of state: a failing endpoint keeps its cursor and does not drop
        # what the other sections fetched. Cursors are committed only once every section has run.
        out, staged, errors = [], {}, []
        for section in sections:
            cur = dict(state)
            try:
                items = section(page, cur)
            except Exception as e:  # noqa: BLE001
                errors.append(e)
                logging.getLogger("social_bridge").warning("facebook %s: %s", section.__name__.strip("_"), e)
                continue
            out += items
            staged.update({k: v for k, v in cur.items() if state.get(k) != v})
        if errors and len(errors) == len(sections):
            raise errors[0]
        state.update(staged)
        out.sort(key=lambda i: i.ts)
        return out

    def _poll_dms(self, page, state):
        since = float(state.get("dm_since") or 0)
        res = self._api("GET", f"/{page}/conversations",
                        params={"platform": "messenger", "fields": self.MSG_FIELDS, "limit": 25})
        out, newest = [], since
        for conv in res.get("data", []):
            if conv.get("updated_time") and self._ts(conv["updated_time"]) < since:
                continue
            for m in (conv.get("messages") or {}).get("data", []):
                ts = self._ts(m.get("created_time"))
                newest = max(newest, ts)
                frm = m.get("from") or {}
                if ts < since or str(frm.get("id")) == page:
                    continue
                out.append(Incoming(
                    platform=self.name, kind="dm", id=str(m["id"]), author=frm.get("name") or str(frm.get("id", "")),
                    author_id=str(frm.get("id", "")), text=m.get("message") or "[attachment]", thread=str(conv["id"]),
                    ts=ts, reply_to={"action": "dm", "target": str(frm.get("id", ""))}, raw=m))
        state["dm_since"] = newest
        return out

    def _poll_comments(self, page, state):
        since = float(state.get("comments_since") or 0)
        res = self._api("GET", f"/{page}/feed",
                        params={"fields": self.COMMENT_FIELDS, "limit": int(self.config.get("poll_posts") or 10)})
        out, newest = [], since
        for post in res.get("data", []):
            if post.get("updated_time") and self._ts(post["updated_time"]) < since:
                continue
            for c in (post.get("comments") or {}).get("data", []):
                ts = self._ts(c.get("created_time"))
                newest = max(newest, ts)
                frm = c.get("from") or {}
                if ts < since or str(frm.get("id")) == page:
                    continue
                parent = c.get("parent")
                if parent:
                    kind = "reply" if str((parent.get("from") or {}).get("id")) == page else "comment"
                    target = str(parent["id"])
                else:
                    kind, target = "comment", str(c["id"])
                out.append(Incoming(
                    platform=self.name, kind=kind, id=str(c["id"]), author=frm.get("name") or "Facebook user",
                    author_id=str(frm.get("id", "")), text=c.get("message") or "",
                    url=c.get("permalink_url") or self._comment_url(post["id"], c["id"]), thread=str(post["id"]),
                    ts=ts, reply_to={"action": "comment", "target": target}, raw=c))
        state["comments_since"] = newest
        return out

    def _poll_tagged(self, page, state):
        since = float(state.get("mentions_since") or 0)
        res = self._api("GET", f"/{page}/tagged", params={"fields": self.TAGGED_FIELDS, "limit": 25})
        out, newest = [], since
        for p in res.get("data", []):
            ts = self._ts(p.get("created_time"))
            newest = max(newest, ts)
            frm = p.get("from") or {}
            if ts < since or str(frm.get("id")) == page:
                continue
            out.append(Incoming(
                platform=self.name, kind="mention", id=str(p["id"]), author=frm.get("name") or str(frm.get("id", "")),
                author_id=str(frm.get("id", "")), text=p.get("message") or "",
                url=p.get("permalink_url") or self._post_url(p["id"]), thread=str(p["id"]), ts=ts,
                reply_to={"action": "comment", "target": str(p["id"])}, raw=p))
        state["mentions_since"] = newest
        return out


# ============================================================================
# social_bridge/adapters/instagram.py — Instagram professional accounts (Business / Creator): posts, Reels, carousels, stories, comments, DMs.
# ============================================================================
import hashlib
import logging
import mimetypes
import os
import re
import time
import urllib.parse
from datetime import datetime



@register
class InstagramAdapter(Adapter):
    name = "instagram"
    label = "Instagram"
    actions = ("post", "comment", "dm")
    poll_interval = 120
    config_keys = {
        "access_token": "Instagram user access token (long-lived, 60 days, refreshed automatically): "
                        "developers.facebook.com -> My Apps -> your app -> Instagram -> API setup with Instagram "
                        "login -> 2. Generate access tokens -> Add account -> Generate token (permissions "
                        "instagram_business_basic, instagram_business_content_publish, "
                        "instagram_business_manage_comments, instagram_business_manage_messages). With "
                        "login=facebook: a Page access token of the Facebook Page linked to the Instagram account "
                        "(Graph API Explorer -> Get Page Access Token, permissions instagram_basic, "
                        "instagram_content_publish, instagram_manage_comments, instagram_manage_messages, "
                        "pages_show_list, pages_read_engagement)",
        "ig_user_id": "(optional) Instagram professional account id; discovered from the token when omitted "
                      "(GET /me?fields=user_id,username, or the Page's instagram_business_account)",
        "login": "(optional) instagram (default: Instagram API with Instagram Login, graph.instagram.com) | "
                 "facebook (Instagram account linked to a Facebook Page, graph.facebook.com)",
        "page_id": "(optional) login=facebook only, then required: id of the linked Facebook Page (Page -> About -> "
                   "Page transparency, or GET /me/accounts)",
        "api_version": "(optional) Graph API version (default v24.0)",
        "message_tag": "(optional) message tag for DMs, e.g. HUMAN_AGENT (sends with messaging_type=MESSAGE_TAG; "
                       "needs the Human Agent permission)",
        "poll_media": "(optional) how many recent posts to check for new comments (default 10)",
    }
    target_help = {
        "post": "omit for a feed post (one video = Reel, several items = carousel), or 'story'. Needs media: "
                "public http(s) image/video URLs, or local video files",
        "comment": "media id, media:<id> or an instagram.com/p/<shortcode>/ (/reel/...) URL of one of your posts to "
                   "comment on it; comment:<comment_id> or a .../p/<shortcode>/c/<comment_id>/ URL to reply to "
                   "a comment",
        "dm": "Instagram-scoped user id (IGSID) of someone who messaged you, their @username or instagram.com/"
              "<username> URL (looked up in your conversations), or a conversation id",
    }

    IG_GRAPH = "https://graph.instagram.com"
    FB_GRAPH = "https://graph.facebook.com"
    REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
    RUPLOAD = "https://rupload.facebook.com/ig-api-upload"
    DEFAULT_VERSION = "v24.0"
    VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp", ".mpeg", ".mpg"}
    WAIT_TRIES = 120
    WAIT_SECONDS = 5
    MAX_PAGES = 5
    REFRESH_EVERY = 7 * 86400
    MSG_FIELDS = "id,updated_time,messages.limit(10){id,message,from,created_time}"
    MEDIA_FIELDS = ("id,permalink,timestamp,comments.limit(50){id,text,username,from,timestamp,"
                    "replies.limit(50){id,text,username,from,timestamp}}")

    def __init__(self, config, http=None):
        super().__init__(config, http)
        self._tok = None          # token in use (a refreshed one once refreshed)
        self._refreshed_at = 0.0
        self._me_cache = None     # {"id", "username", "ids"}
        self._links = {}          # media / comment id -> media permalink

    # ------------------------------------------------------------- auth / transport
    def _fb(self):
        return str(self.config.get("login") or "instagram").strip().lower() == "facebook"

    def _ver(self):
        v = str(self.config.get("api_version") or self.DEFAULT_VERSION).strip()
        return v if v.startswith("v") else "v" + v

    def _graph(self):
        return f"{self.FB_GRAPH if self._fb() else self.IG_GRAPH}/{self._ver()}"

    def _token(self):
        if not self._tok:
            (self._tok,) = self.need("access_token")
        return self._tok

    def _call(self, method, url, **kw):
        return self.http.request(method, url, headers={"Authorization": f"Bearer {self._token()}"}, **kw)

    @staticmethod
    def _auth_error(e):
        err = e.body.get("error") if isinstance(e.body, dict) else None
        return e.status == 401 or (isinstance(err, dict) and err.get("code") in (102, 190))

    def _api(self, method, path, **kw):
        url = self._graph() + path
        try:
            return self._call(method, url, **kw)
        except PlatformError as e:
            if self._fb() or not self._auth_error(e) or not self._refresh():
                raise
        return self._call(method, url, **kw)

    def _refresh(self):
        """Refresh the long-lived Instagram Login token (it must be at least 24h old and not expired)."""
        try:
            res = self.http.get(self.REFRESH_URL, params={"grant_type": "ig_refresh_token",
                                                          "access_token": self._token()})
        except PlatformError:
            return False
        if not isinstance(res, dict) or not res.get("access_token"):
            return False
        self._tok = res["access_token"]
        self._refreshed_at = time.time()
        return True

    def _sync_token(self, state, refresh=True):
        """Keep the refreshed token in the bridge's poll state so it survives restarts."""
        if self._fb():
            return
        seed = hashlib.sha256(str(self.config.get("access_token") or "").encode()).hexdigest()[:16]
        if state.get("token_seed") != seed:
            for k in ("access_token", "token_refreshed", "token_refresh_tried"):
                state.pop(k, None)
            state["token_seed"] = seed
        if state.get("access_token") and not self._refreshed_at:
            self._tok = state["access_token"]
            self._refreshed_at = float(state.get("token_refreshed") or 1)
        now = time.time()
        if refresh and now - max(self._refreshed_at, float(state.get("token_refreshed") or 0)) > self.REFRESH_EVERY \
                and now - float(state.get("token_refresh_tried") or 0) > 86400:
            state["token_refresh_tried"] = now
            self._refresh()
        if self._refreshed_at > float(state.get("token_refreshed") or 0):
            state["access_token"] = self._tok
            state["token_refreshed"] = self._refreshed_at

    # ------------------------------------------------------------- helpers
    def _me(self):
        if self._me_cache is None:
            cfg_id = str(self.config.get("ig_user_id") or "")
            if not self._fb():
                res = self._api("GET", "/me", params={"fields": "user_id,username"})
                me = {"id": cfg_id or str(res.get("user_id") or res.get("id")), "username": res.get("username") or "",
                      "ids": {str(res.get("user_id") or ""), str(res.get("id") or "")}}
            elif cfg_id:
                res = self._api("GET", f"/{cfg_id}", params={"fields": "id,username"})
                me = {"id": cfg_id, "username": res.get("username") or "", "ids": set()}
            else:
                (page,) = self.need("page_id")
                res = self._api("GET", f"/{page}", params={"fields": "instagram_business_account{id,username}"})
                acct = res.get("instagram_business_account")
                if not acct:
                    raise PlatformError(self.name, f"Facebook Page {page} has no linked Instagram professional account")
                me = {"id": str(acct["id"]), "username": acct.get("username") or "", "ids": set()}
            me["ids"] = {i for i in me["ids"] | {me["id"]} if i}
            self._me_cache = me
        return self._me_cache

    def _msg_node(self):
        if self._fb():
            (page,) = self.need("page_id")
            return str(page)
        return self._me()["id"]

    @staticmethod
    def _own(item, me):
        frm = item.get("from") or {}
        uid = str(frm.get("id") or "")
        uname = str(frm.get("username") or item.get("username") or "").lower()
        return (bool(uid) and uid in me["ids"]) or (bool(uname) and uname == me["username"].lower())

    @staticmethod
    def _ts(value):
        if not value:
            return 0.0
        if isinstance(value, (int, float)) or str(value).isdigit():
            return float(value)
        s = str(value).replace("Z", "+0000")
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                return datetime.strptime(s, fmt).timestamp()
            except ValueError:
                pass
        return 0.0

    @staticmethod
    def _is_url(m):
        return bool(re.match(r"https?://", m, re.I))

    def _is_video(self, m):
        path = urllib.parse.urlsplit(m).path if self._is_url(m) else m
        return os.path.splitext(path)[1].lower() in self.VIDEO_EXT or \
            (mimetypes.guess_type(path)[0] or "").startswith("video/")

    @staticmethod
    def _after(res):
        paging = res.get("paging") or {}
        return (paging.get("cursors") or {}).get("after") if paging.get("next") else None

    # ------------------------------------------------------------- publishing
    def _container(self, ig, m, media_type=None, caption=None, carousel=False):
        body = {}
        if media_type:
            body["media_type"] = media_type
        if carousel:
            body["is_carousel_item"] = True
        if caption:
            body["caption"] = caption
        video = self._is_video(m)
        if self._is_url(m):
            body["video_url" if video else "image_url"] = m
            return str(self._api("POST", f"/{ig}/media", json=body)["id"])
        if not video:
            raise PlatformError(self.name, f"{m}: the Instagram API only takes images as public http(s) URLs")
        if not os.path.isfile(m):
            raise PlatformError(self.name, f"media file not found: {m}")
        with open(m, "rb") as f:
            data = f.read()
        body["upload_type"] = "resumable"
        res = self._api("POST", f"/{ig}/media", json=body)
        cid = str(res["id"])
        self.http.post(res.get("uri") or f"{self.RUPLOAD}/{self._ver()}/{cid}", data=data, headers={
            "Authorization": f"OAuth {self._token()}", "offset": "0", "file_size": str(len(data))})
        return cid

    def _wait(self, cid):
        for _ in range(self.WAIT_TRIES):
            st = self._api("GET", f"/{cid}", params={"fields": "status_code,status"})
            code = st.get("status_code")
            if code in ("FINISHED", "PUBLISHED"):
                return
            if code in ("ERROR", "EXPIRED"):
                msg = f"media container {cid} {code}: {st.get('status') or ''}".strip()
                raise PlatformError(self.name, msg, body=st)
            self.http.sleep(self.WAIT_SECONDS)
        waited = self.WAIT_TRIES * self.WAIT_SECONDS
        raise PlatformError(self.name, f"media container {cid} not ready after {waited}s")

    def _publish(self, ig, cid):
        self._wait(cid)
        res = self._api("POST", f"/{ig}/media_publish", json={"creation_id": cid})
        mid = str(res["id"])
        try:
            url = self._api("GET", f"/{mid}", params={"fields": "permalink"}).get("permalink") or ""
        except PlatformError:
            url = ""
        if url:
            self._links[mid] = url
        return Result(id=mid, url=url, raw=res)

    # ------------------------------------------------------------- target parsing
    def _find_media(self, shortcode):
        params = {"fields": "id,shortcode,permalink", "limit": 50}
        for _ in range(self.MAX_PAGES):
            res = self._api("GET", f"/{self._me()['id']}/media", params=params)
            for m in res.get("data", []):
                if m.get("shortcode") == shortcode or f"/{shortcode}/" in (m.get("permalink") or ""):
                    return m
            after = self._after(res)
            if not after:
                break
            params = dict(params, after=after)
        raise PlatformError(self.name,
                            f"no post with shortcode {shortcode} among this account's media; pass a media id")

    def _comment_target(self, target):
        t = str(target).strip()
        m = re.fullmatch(r"(comment|reply|media|post):\s*([\w.-]+)", t, re.I)
        if m:
            return ("media" if m.group(1).lower() in ("media", "post") else "comment"), m.group(2), ""
        if t.isdigit():
            return "media", t, ""
        m = re.match(r"(?:https?://)?(?:www\.|m\.)?instagram\.com/(?:[\w.]+/)?(p|reels?|tv)/([\w-]+)/?"
                     r"(?:c/(\d+)/?)?", t, re.I)
        if not m:
            raise PlatformError(self.name, f"can't read a media or comment id from {t!r}")
        kind, shortcode, cid = m.group(1).lower(), m.group(2), m.group(3)
        link = f"https://www.instagram.com/{'reel' if kind.startswith('reel') else kind}/{shortcode}/"
        if cid:
            return "comment", cid, link
        media = self._find_media(shortcode)
        return "media", str(media["id"]), media.get("permalink") or link

    def _other_participant(self, participants):
        me = self._me()
        for p in participants:
            if not self._own({"from": p}, me):
                return str(p["id"])
        raise PlatformError(self.name, "no other participant in that conversation")

    def _igsid_for(self, username):
        params = {"platform": "instagram", "fields": "participants", "limit": 50}
        for _ in range(self.MAX_PAGES):
            res = self._api("GET", f"/{self._msg_node()}/conversations", params=params)
            for conv in res.get("data", []):
                for p in (conv.get("participants") or {}).get("data", []):
                    if str(p.get("username") or "").lower() == username.lower():
                        return str(p["id"])
            after = self._after(res)
            if not after:
                break
            params = dict(params, after=after)
        raise PlatformError(self.name, f"no conversation with @{username}; pass their IGSID")

    def _recipient(self, target):
        t = str(target).strip()
        if t.isdigit():
            return t
        m = re.fullmatch(r"(?:https?://)?(?:www\.)?instagram\.com/([\w.]+)/?(?:\?.*)?", t, re.I)
        if m:
            t = "@" + m.group(1)
        if t.startswith("@") or re.fullmatch(r"[\w.]{1,30}", t):
            return self._igsid_for(t.lstrip("@"))
        res = self._api("GET", f"/{t}", params={"fields": "participants"})
        return self._other_participant((res.get("participants") or {}).get("data", []))

    # ------------------------------------------------------------- actions
    def whoami(self):
        return "@" + (self._me()["username"] or self._me()["id"])

    def post(self, text, target=None, title=None, link=None, media=None):
        media = [str(m) for m in (media or [])]
        if not media:
            raise PlatformError(self.name, "Instagram posts need at least one image or video")
        where = str(target or "feed").strip().lower()
        ig = self._me()["id"]
        if where in ("story", "stories"):
            done = [self._publish(ig, self._container(ig, m, media_type="STORIES")) for m in media]
            return Result(id=done[0].id, url=done[0].url, raw={"items": [d.raw for d in done]})
        if where not in ("feed", "post", "reel", "reels", "carousel"):
            raise PlatformError(self.name, f"unknown post target {target!r}: omit it or use 'story'")
        caption = "\n\n".join(p for p in (title, text, link) if p)
        if len(media) == 1:
            m = media[0]
            cid = self._container(ig, m, media_type="REELS" if self._is_video(m) else None, caption=caption)
        else:
            children = []
            for m in media:
                video = self._is_video(m)
                child = self._container(ig, m, media_type="VIDEO" if video else None, carousel=True)
                if video:
                    self._wait(child)
                children.append(child)
            body = {"media_type": "CAROUSEL", "children": ",".join(children)}
            if caption:
                body["caption"] = caption
            cid = str(self._api("POST", f"/{ig}/media", json=body)["id"])
        return self._publish(ig, cid)

    def comment(self, target, text):
        kind, oid, link = self._comment_target(target)
        res = self._api("POST", f"/{oid}/{'replies' if kind == 'comment' else 'comments'}", json={"message": text})
        return Result(id=str(res.get("id", "")), url=link or self._links.get(oid, ""), raw=res)

    def dm(self, target, text):
        body = {"recipient": {"id": self._recipient(target)}, "message": {"text": text}}
        # Instagram enforces a 24-hour reply window after the user's last message; tags extend it.
        if self.config.get("message_tag"):
            body["messaging_type"] = "MESSAGE_TAG"
            body["tag"] = self.config["message_tag"]
        res = self._api("POST", f"/{self._msg_node()}/messages", json=body)
        return Result(id=str(res.get("message_id", "")), url="", raw=res)

    # ------------------------------------------------------------- polling
    def poll(self, state):
        self._sync_token(state)
        me = self._me()
        # Each section works on a copy of state: a failing endpoint keeps its cursor and does not drop
        # what the other section fetched. Cursors are committed only once both sections have run.
        sections = (self._poll_dms, self._poll_comments)
        out, staged, errors = [], {}, []
        for section in sections:
            cur = dict(state)
            try:
                items = section(cur, me)
            except Exception as e:  # noqa: BLE001
                errors.append(e)
                logging.getLogger("social_bridge").warning("instagram %s: %s", section.__name__.strip("_"), e)
                continue
            out += items
            staged.update({k: v for k, v in cur.items() if state.get(k) != v})
        self._sync_token(state, refresh=False)
        if len(errors) == len(sections):
            raise errors[0]
        state.update(staged)
        out.sort(key=lambda i: i.ts)
        return out

    def _poll_dms(self, state, me):
        since = float(state.get("dm_since") or 0)
        res = self._api("GET", f"/{self._msg_node()}/conversations",
                        params={"platform": "instagram", "fields": self.MSG_FIELDS, "limit": 20})
        out, newest = [], since
        for conv in res.get("data", []):
            if conv.get("updated_time") and self._ts(conv["updated_time"]) < since:
                continue
            for m in (conv.get("messages") or {}).get("data", []):
                ts = self._ts(m.get("created_time"))
                newest = max(newest, ts)
                frm = m.get("from") or {}
                if ts < since or self._own(m, me):
                    continue
                uname = frm.get("username") or ""
                out.append(Incoming(
                    platform=self.name, kind="dm", id=str(m["id"]), author="@" + uname if uname else str(frm.get("id")),
                    author_id=str(frm.get("id") or ""), text=m.get("message") or "[attachment]", thread=str(conv["id"]),
                    ts=ts, reply_to={"action": "dm", "target": str(frm.get("id") or "")}, raw=m))
        state["dm_since"] = newest
        return out

    def _poll_comments(self, state, me):
        since = float(state.get("comments_since") or 0)
        res = self._api("GET", f"/{me['id']}/media",
                        params={"fields": self.MEDIA_FIELDS, "limit": int(self.config.get("poll_media") or 10)})
        out, newest = [], since

        def add(c, kind, parent_id, media):
            nonlocal newest
            ts = self._ts(c.get("timestamp"))
            newest = max(newest, ts)
            if ts < since or self._own(c, me):
                return
            frm = c.get("from") or {}
            uname = c.get("username") or frm.get("username") or ""
            out.append(Incoming(
                platform=self.name, kind=kind, id=str(c["id"]), author="@" + uname if uname else str(frm.get("id")),
                author_id=str(frm.get("id") or ""), text=c.get("text") or "", url=media.get("permalink") or "",
                thread=str(media["id"]), ts=ts, reply_to={"action": "comment", "target": f"comment:{parent_id}"},
                raw=c))

        for media in res.get("data", []):
            link = media.get("permalink") or ""
            for c in (media.get("comments") or {}).get("data", []):
                if link:
                    self._links[str(c["id"])] = link
                mine = self._own(c, me)
                add(c, "comment", c["id"], media)
                for r in (c.get("replies") or {}).get("data", []):
                    add(r, "reply" if mine else "comment", c["id"], media)
            if link:
                self._links[str(media["id"])] = link
        state["comments_since"] = newest
        return out


# ============================================================================
# social_bridge/adapters/threads.py — Threads (Meta Threads API): posts (text, link card, image, video, carousel, quote) and replies.
# ============================================================================
import calendar
import hashlib
import mimetypes
import os
import re
import time
import urllib.parse



@register
class ThreadsAdapter(Adapter):
    name = "threads"
    label = "Threads"
    actions = ("post", "comment")  # the Threads API has no direct-message endpoints
    poll_interval = 120
    config_keys = {
        "access_token": "Long-lived Threads user access token (valid 60 days, refreshed automatically while the "
                        "bridge runs): developers.facebook.com -> My Apps -> Create App -> use case 'Access the "
                        "Threads API' -> Use cases -> Customize -> Permissions: add threads_basic, "
                        "threads_content_publish, threads_read_replies, threads_manage_replies, "
                        "threads_manage_mentions; App roles -> Roles -> Add People -> Threads Tester (accept in the "
                        "Threads app: Settings -> Account -> Website permissions -> Invites); then Use cases -> "
                        "Customize -> Settings -> User Token Generator -> Generate access token",
        "user_id": "(optional) numeric Threads user id; looked up with GET /me when omitted",
        "app_secret": "(optional) Threads app secret: App Dashboard -> App settings -> Basic -> Threads app secret. "
                      "When set, a short-lived access_token is exchanged for a long-lived one on first use",
        "api_version": "(optional) Threads API version (default v1.0)",
        "reply_control": "(optional) who may reply to new posts: everyone | accounts_you_follow | mentioned_only | "
                         "parent_post_author_only | followers_only (default: everyone)",
        "poll_posts": "(optional) how many of your most recent posts are watched for replies (default 10)",
        "poll_replies": "(optional) how many of your most recent replies are watched for answers (default 10)",
        "poll_mentions": "(optional) false to skip polling @mentions (default true)",
        "auto_refresh": "(optional) false to never refresh the access token (default true)",
    }
    target_help = {
        "post": "omit (publishes on your profile); or a Threads post id or URL to publish a quote post of it",
        "comment": "Threads media id of the post or reply to answer, or its URL "
                   "(https://www.threads.com/@user/post/<code>; URLs resolve for your own posts and replies, posts "
                   "you are mentioned in, and anything seen by poll)",
    }

    API = "https://graph.threads.net"
    DEFAULT_VERSION = "v1.0"
    VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".wmv", ".flv", ".3gp", ".mpeg", ".mpg"}
    OWN_FIELDS = "id,permalink,shortcode,timestamp"
    POST_FIELDS = OWN_FIELDS + ",media_type"   # /{user_id}/threads also lists reposts (media_type REPOST_FACADE)
    REPLY_FIELDS = ("id,text,username,permalink,shortcode,timestamp,media_type,replied_to,root_post,"
                    "is_reply_owned_by_me")
    MENTION_FIELDS = "id,text,username,permalink,shortcode,timestamp,media_type,replied_to,root_post"
    URL_RE = re.compile(r"threads\.(?:net|com)/(?:@[\w.]+/post|t)/([A-Za-z0-9_-]+)", re.I)
    REFRESH_EVERY = 7 * 86400   # long-lived tokens last 60 days; refresh needs a token at least 24h old

    def __init__(self, config, http=None):
        super().__init__(config, http)
        self._tok = None
        self._refreshed_at = 0.0
        self._me_cache = None
        self._codes = {}   # shortcode -> media id, from everything seen

    # ------------------------------------------------------------- config helpers
    def _ver(self):
        v = str(self.config.get("api_version") or self.DEFAULT_VERSION).strip()
        return v if v.startswith("v") else "v" + v

    def _flag(self, key, default=True):
        v = self.config.get(key)
        if v is None or v == "":
            return default
        if isinstance(v, str):
            return v.strip().lower() not in ("0", "false", "no", "off")
        return bool(v)

    def _int(self, key, default):
        try:
            return max(1, int(self.config.get(key) or default))
        except (TypeError, ValueError):
            return default

    # ------------------------------------------------------------- auth / transport
    def _token(self):
        if self._tok is None:
            (tok,) = self.need("access_token")
            self._tok = tok
            if self.config.get("app_secret"):
                self._exchange()
        return self._tok

    def _exchange(self):
        """Short-lived -> long-lived token. Fails harmlessly when the token is already long-lived."""
        try:
            res = self.http.get(f"{self.API}/access_token", params={
                "grant_type": "th_exchange_token", "client_secret": self.config["app_secret"],
                "access_token": self._tok})
        except PlatformError:
            return False
        if isinstance(res, dict) and res.get("access_token"):
            self._tok = res["access_token"]
            self._refreshed_at = time.time()
            return True
        return False

    def _refresh(self):
        """Extend the long-lived token by 60 days (the token must be at least 24h old and not expired)."""
        try:
            res = self.http.get(f"{self.API}/refresh_access_token", params={
                "grant_type": "th_refresh_token", "access_token": self._token()})
        except PlatformError:
            return False
        if not isinstance(res, dict) or not res.get("access_token"):
            return False
        self._tok = res["access_token"]
        self._refreshed_at = time.time()
        return True

    def _sync_token(self, state):
        """Keep the refreshed token in the bridge's poll state so it survives restarts."""
        seed = hashlib.sha256(str(self.config.get("access_token") or "").encode()).hexdigest()[:16]
        if state.get("token_seed") != seed:
            for k in ("access_token", "token_refreshed", "token_refresh_tried"):
                state.pop(k, None)
            state["token_seed"] = seed
        stored = float(state.get("token_refreshed") or 0)
        if state.get("access_token") and stored > self._refreshed_at:
            self._tok, self._refreshed_at = state["access_token"], stored
        now = time.time()
        if self._flag("auto_refresh") and now - self._refreshed_at > self.REFRESH_EVERY and \
                now - float(state.get("token_refresh_tried") or 0) > 86400:
            state["token_refresh_tried"] = now
            self._refresh()
        if self._refreshed_at > float(state.get("token_refreshed") or 0):
            state["access_token"] = self._tok
            state["token_refreshed"] = self._refreshed_at

    @staticmethod
    def _auth_error(e):
        err = e.body.get("error") if isinstance(e.body, dict) else None
        return e.status == 401 or (isinstance(err, dict) and err.get("code") == 190)

    def _call(self, method, path, params=None, **kw):
        p = dict(params or {})
        p["access_token"] = self._token()
        return self.http.request(method, f"{self.API}/{self._ver()}{path}", params=p, **kw)

    def _api(self, method, path, **kw):
        try:
            return self._call(method, path, **kw)
        except PlatformError as e:
            if not self._auth_error(e) or not self._refresh():
                raise
        return self._call(method, path, **kw)

    def _list(self, path, fields, limit=None, **params):
        p = {"fields": fields, **params}
        if limit:
            p["limit"] = limit
        res = self._api("GET", path, params=p)
        data = res.get("data") if isinstance(res, dict) else None
        return [x for x in (data or []) if isinstance(x, dict) and x.get("id")]

    # ------------------------------------------------------------- helpers
    def _me(self):
        if self._me_cache is None:
            res = self._api("GET", "/me", params={"fields": "id,username"})
            self._me_cache = {"id": str(res.get("id") or ""), "username": res.get("username") or ""}
        return self._me_cache

    def _uid(self):
        return str(self.config.get("user_id") or self._me()["id"])

    @staticmethod
    def _ts(value):
        """'2024-07-04T15:12:01+0000' -> unix seconds."""
        m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?(Z|([+-])(\d\d):?(\d\d))?$", str(value or ""))
        if not m:
            return 0.0
        ts = calendar.timegm(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S"))
        if m.group(3):
            off = int(m.group(4)) * 3600 + int(m.group(5)) * 60
            ts -= off if m.group(3) == "+" else -off
        return float(ts)

    def _remember(self, item):
        if str(item.get("media_type") or "").upper() == "REPOST_FACADE":
            return
        code = item.get("shortcode")
        if not code:
            m = self.URL_RE.search(item.get("permalink") or "")
            code = m.group(1) if m else None
        if code and item.get("id"):
            if len(self._codes) >= 5000:
                self._codes.pop(next(iter(self._codes)))
            self._codes[code] = str(item["id"])

    def _media_id(self, target):
        t = str(target).strip()
        if t.isdigit():
            return t
        m = self.URL_RE.search(t)
        if not m:
            raise PlatformError(self.name, f"can't read a Threads media id or post URL from {t!r}")
        code = m.group(1)
        if code in self._codes:
            return self._codes[code]
        uid = self._uid()
        lookups = ((f"/{uid}/threads", self.POST_FIELDS, False), (f"/{uid}/replies", self.OWN_FIELDS, False),
                   (f"/{uid}/mentions", "id,permalink,shortcode", True))
        for path, fields, optional in lookups:
            try:
                for it in self._list(path, fields, 50):
                    self._remember(it)
            except PlatformError:
                if not optional:
                    raise
            if code in self._codes:
                return self._codes[code]
        raise PlatformError(self.name, f"{t} is not among your recent posts, replies or mentions, and the API has no "
                                       f"URL lookup; pass the numeric media id instead")

    def _media_fields(self, url):
        path = urllib.parse.urlsplit(url).path
        is_video = os.path.splitext(path)[1].lower() in self.VIDEO_EXT or \
            (mimetypes.guess_type(path)[0] or "").startswith("video/")
        return {"media_type": "VIDEO", "video_url": url} if is_video else {"media_type": "IMAGE", "image_url": url}

    def _container(self, **fields):
        data = {k: v for k, v in fields.items() if v not in (None, "")}
        res = self._api("POST", f"/{self._uid()}/threads", data=data)
        return str(res["id"])

    def _wait(self, cid, timeout=600):
        """Media containers are processed asynchronously; publishing before FINISHED fails."""
        waited, delay = 0.0, 2.0
        while True:
            st = self._api("GET", f"/{cid}", params={"fields": "status,error_message"})
            status = str(st.get("status") or "").upper() if isinstance(st, dict) else ""
            if status in ("FINISHED", "PUBLISHED", ""):
                return
            if status in ("ERROR", "EXPIRED"):
                raise PlatformError(self.name, f"media container {cid} {status.lower()}: "
                                               f"{st.get('error_message') or 'no details'}", body=st)
            if waited >= timeout:
                raise PlatformError(self.name, f"media container {cid} still {status} after {int(waited)}s")
            self.http.sleep(delay)
            waited += delay
            delay = min(delay * 2, 20.0)

    def _publish(self, text, media=(), **fields):
        if not media:
            cid = self._container(media_type="TEXT", text=text, **fields)
        elif len(media) == 1:
            cid = self._container(text=text, **self._media_fields(media[0]), **fields)
            self._wait(cid)
        else:
            children = [self._container(is_carousel_item="true", **self._media_fields(m)) for m in media]
            for c in children:
                self._wait(c)
            cid = self._container(media_type="CAROUSEL", children=",".join(children), text=text, **fields)
            self._wait(cid)
        res = self._api("POST", f"/{self._uid()}/threads_publish", data={"creation_id": cid})
        mid = str(res["id"])
        info = {}
        try:
            info = self._api("GET", f"/{mid}", params={"fields": "permalink,shortcode"})
            self._remember({"id": mid, **info})
        except PlatformError:
            pass
        return Result(id=mid, url=(info or {}).get("permalink") or "",
                      raw={"creation_id": cid, **res, **(info or {})})

    # ------------------------------------------------------------- actions
    def whoami(self):
        return "@" + self._me()["username"]

    def post(self, text, target=None, title=None, link=None, media=None):
        text = (text or "").strip()
        if title:
            text = f"{title}\n\n{text}".strip()
        media = [str(m).strip() for m in (media or []) if m]
        for m in media:
            if not re.match(r"https?://", m, re.I):
                raise PlatformError(self.name, f"Threads only takes media as public http(s) URLs (the API downloads "
                                               f"image_url/video_url itself); can't upload local file {m}")
        fields = {}
        if target:
            fields["quote_post_id"] = self._media_id(target)
        if self.config.get("reply_control"):
            fields["reply_control"] = str(self.config["reply_control"]).strip()
        if link and media:
            if link not in text:
                text = f"{text}\n\n{link}".strip()
        elif link:
            fields["link_attachment"] = link   # link preview card; TEXT posts only
        return self._publish(text, media, **fields)

    def comment(self, target, text):
        return self._publish(text, reply_to_id=self._media_id(target))

    def poll(self, state):
        self._sync_token(state)
        me = self._me()
        uid = self._uid()
        my_name = me["username"].lower()
        since = float(state.get("since") or 0)

        posts = [p for p in self._list(f"/{uid}/threads", self.POST_FIELDS, self._int("poll_posts", 10))
                 if str(p.get("media_type") or "").upper() != "REPOST_FACADE"]
        mine = self._list(f"/{uid}/replies", self.OWN_FIELDS + ",root_post", self._int("poll_replies", 10))
        roots = {str(p["id"]) for p in posts}
        own = roots | {str(p["id"]) for p in mine}
        for p in posts + mine:
            self._remember(p)

        def fetch(path):
            try:
                return self._list(path, self.REPLY_FIELDS, reverse="true")
            except PlatformError:
                return []   # one unreadable (deleted or restricted) post does not fail the whole poll

        batch = []   # (source, item, root id)
        for p in posts:
            for r in fetch(f"/{p['id']}/conversation"):
                batch.append(("conversation", r, str(p["id"])))
        for p in mine:
            root = str((p.get("root_post") or {}).get("id") or "")
            if root in roots:
                continue   # already covered by that post's conversation
            for r in fetch(f"/{p['id']}/replies"):
                batch.append(("reply", r, root or str(p["id"])))
        if self._flag("poll_mentions"):
            for r in self._list(f"/{uid}/mentions", self.MENTION_FIELDS, 25):
                batch.append(("mention", r, ""))

        def is_own(r):
            return r.get("is_reply_owned_by_me") is True or (r.get("username") or "").lower() == my_name

        own |= {str(r["id"]) for _, r, _ in batch if is_own(r)}
        out, seen, newest = [], set(), since
        for source, r, root in batch:
            rid = str(r["id"])
            if rid in seen or rid in own:
                continue
            seen.add(rid)
            self._remember(r)
            ts = self._ts(r.get("timestamp"))
            newest = max(newest, ts)
            if since and ts and ts < since:
                continue
            parent = str((r.get("replied_to") or {}).get("id") or "")
            if parent and parent in roots:
                kind = "comment"
            elif parent and parent in own:
                kind = "reply"
            else:
                kind = "mention" if source == "mention" else "comment"
            text = (r.get("text") or "").strip() or f"[{str(r.get('media_type') or 'media').lower()}]"
            out.append(Incoming(
                platform=self.name, kind=kind, id=rid, author="@" + (r.get("username") or ""), text=text,
                url=r.get("permalink") or "", thread=str((r.get("root_post") or {}).get("id") or root or rid),
                ts=ts, reply_to={"action": "comment", "target": rid}, raw=r,
            ))
        state["since"] = newest
        return out


# ============================================================================
# social_bridge/adapters/bluesky.py — Bluesky (AT Protocol XRPC with an app password; DMs through the Bluesky chat service via the PDS).
# ============================================================================
import base64
import calendar
import html
import json
import mimetypes
import os
import re
import time
import unicodedata
import urllib.parse



@register
class BlueskyAdapter(Adapter):
    name = "bluesky"
    label = "Bluesky"
    actions = ("post", "comment", "dm")
    poll_interval = 30  # 2-3 requests per poll; the PDS allows 3000 requests / 5 min per IP
    config_keys = {
        "handle": "account handle, e.g. alice.bsky.social (the account's DID or login email also work)",
        "app_password": "bsky.app -> Settings -> Privacy and security -> App passwords -> Add App Password "
                        "(https://bsky.app/settings/app-passwords); tick 'Allow access to your direct messages' "
                        "for dm and DM polling",
        "pds": "(optional) PDS URL to log in through (default https://bsky.social); set it for a self-hosted PDS",
        "langs": "(optional) comma-separated post language codes, e.g. en or en,de (default: not set)",
        "poll_dms": "(optional) include DMs in poll: true | false (default true; needs an app password with "
                    "direct message access)",
    }
    target_help = {
        "post": "omit (posts to your own profile feed)",
        "comment": "post URL https://bsky.app/profile/<handle-or-did>/post/<rkey> or at://<did>/app.bsky.feed.post/"
                   "<rkey> (replies in that post's thread)",
        "dm": "handle (alice.bsky.social or @alice.bsky.social), DID, profile URL, or an existing conversation as "
              "convo:<id> or https://bsky.app/messages/<id>",
    }

    WEB = "https://bsky.app"
    DEFAULT_PDS = "https://bsky.social"
    CHAT_PROXY = "did:web:api.bsky.chat#bsky_chat"
    POST = "app.bsky.feed.post"
    POST_GRAPHEMES, POST_BYTES = 300, 3000
    DM_GRAPHEMES, DM_BYTES = 1000, 10000
    IMAGE_BYTES = 1000000
    VIDEO_BYTES = 100000000
    MAX_IMAGES = 4
    NOTIF_REASONS = ("mention", "reply", "quote")
    # indexedAt is the appview sortAt (min of createdAt and index time), so late-indexed
    # notifications can sort before the newest one already seen; re-scan this many seconds.
    NOTIF_OVERLAP = 900

    def __init__(self, config, http=None):
        super().__init__(config, http)
        self._access = None
        self._refresh = None
        self._access_exp = 0.0
        self._did = None
        self._handle = None
        self._pds = None
        self._dids = {}      # handle -> did
        self._handles = {}   # did -> handle

    # ------------------------------------------------------------- session / transport
    def _login_base(self):
        return (self.config.get("pds") or self.DEFAULT_PDS).strip().rstrip("/")

    @staticmethod
    def _jwt_exp(token):
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
        except (IndexError, ValueError, KeyError, TypeError, AttributeError):
            return 0.0

    @staticmethod
    def _pds_from_doc(doc):
        for svc in (doc or {}).get("service") or []:
            if str(svc.get("id", "")).endswith("#atproto_pds") and \
                    re.match(r"https?://", str(svc.get("serviceEndpoint", ""))):
                return svc["serviceEndpoint"].rstrip("/")
        return None

    def _set_session(self, res):
        if not isinstance(res, dict) or not res.get("accessJwt"):
            raise PlatformError(self.name, f"login failed: {res}", body=res)
        self._access = res["accessJwt"]
        self._refresh = res.get("refreshJwt") or self._refresh
        self._access_exp = self._jwt_exp(self._access)
        self._did = res.get("did") or self._did
        self._handle = res.get("handle") or self._handle
        # Requests go to the account's own PDS (from its DID document), as the official clients do.
        self._pds = self._pds_from_doc(res.get("didDoc")) or self._pds or self._login_base()
        if self._did and self._handle:
            self._handles[self._did] = self._handle
            self._dids[self._handle.lower()] = self._did

    def _create_session(self):
        handle, password = self.need("handle", "app_password")
        res = self.http.post(self._login_base() + "/xrpc/com.atproto.server.createSession",
                             json={"identifier": handle.strip().lstrip("@"), "password": password})
        self._set_session(res)

    def _refresh_session(self):
        if self._refresh:
            try:
                res = self.http.post((self._pds or self._login_base()) + "/xrpc/com.atproto.server.refreshSession",
                                     headers={"Authorization": f"Bearer {self._refresh}"})
                self._set_session(res)
                return
            except PlatformError as e:
                if e.status not in (400, 401):
                    raise
                self._refresh = None
        self._create_session()

    def _ensure_session(self):
        if not self._access:
            self._create_session()
        elif self._access_exp and time.time() > self._access_exp - 60:
            self._refresh_session()

    @staticmethod
    def _err(e):
        body = e.body if isinstance(e.body, dict) else {}
        return str(body.get("error") or ""), str(body.get("message") or "")

    def _token_error(self, e):
        code, msg = self._err(e)
        if "Bad token" in msg:  # scope problem (e.g. no DM access); a new token won't help
            return False
        return e.status == 401 or (e.status == 400 and code in ("ExpiredToken", "InvalidToken"))

    def _xrpc(self, method, nsid, *, chat=False, **kw):
        self._ensure_session()
        headers = dict(kw.pop("headers", None) or {})
        if chat:
            headers["atproto-proxy"] = self.CHAT_PROXY
        headers["Authorization"] = f"Bearer {self._access}"
        try:
            return self.http.request(method, f"{self._pds}/xrpc/{nsid}", headers=headers, **kw)
        except PlatformError as e:
            if not self._token_error(e):
                raise
        self._refresh_session()
        headers["Authorization"] = f"Bearer {self._access}"
        return self.http.request(method, f"{self._pds}/xrpc/{nsid}", headers=headers, **kw)

    def _chat(self, method, nsid, **kw):
        try:
            return self._xrpc(method, nsid, chat=True, **kw)
        except PlatformError as e:
            code, msg = self._err(e)
            if "Bad token" in msg:
                raise PlatformError(self.name, f"chat refused ({msg}): this app password has no DM access; create "
                                               "one with 'Allow access to your direct messages' ticked",
                                    e.status, e.body) from e
            raise

    # ------------------------------------------------------------- identifiers / targets
    def _did_for(self, actor):
        actor = urllib.parse.unquote(str(actor or "")).strip().lstrip("@").strip()
        if not actor:
            raise PlatformError(self.name, "empty handle")
        if actor.lower().startswith("did:"):
            return actor
        key = actor.lower()
        if "." not in key:
            key += ".bsky.social"
        if key not in self._dids:
            res = self._xrpc("GET", "com.atproto.identity.resolveHandle", params={"handle": key})
            if not res.get("did"):
                raise PlatformError(self.name, f"can't resolve handle {actor!r}", body=res)
            self._dids[key] = res["did"]
            self._handles.setdefault(res["did"], key)
        return self._dids[key]

    def _post_uri(self, target):
        t = str(target or "").strip()
        m = re.match(r"^(?:at://)?([^/\s?#]+)/app\.bsky\.feed\.post/([A-Za-z0-9._:~-]+)", t) or \
            re.search(r"/profile/([^/\s?#]+)/post/([A-Za-z0-9._:~-]+)", t)
        if not m:
            raise PlatformError(self.name, f"can't read a post from {target!r}; pass a bsky.app post URL or at:// URI")
        return f"at://{self._did_for(m.group(1))}/{self.POST}/{m.group(2)}"

    @staticmethod
    def _uri_did(uri):
        m = re.match(r"^at://([^/]+)", str(uri or ""))
        return m.group(1) if m else ""

    def _post_url(self, uri, handle=None):
        m = re.match(r"^at://([^/]+)/app\.bsky\.feed\.post/([^/?#]+)", str(uri or ""))
        if not m:
            return ""
        actor = handle if handle and handle != "handle.invalid" else m.group(1)
        return f"{self.WEB}/profile/{actor}/post/{m.group(2)}"

    def _convo_id(self, target):
        t = str(target or "").strip()
        m = re.match(r"^convo:(\S+)$", t, re.I) or re.search(r"/messages/([A-Za-z0-9._:~-]+)", t)
        if m:
            return m.group(1)
        m = re.search(r"/profile/([^/\s?#]+)", t) or re.match(r"^at://([^/\s]+)", t)
        did = self._did_for(m.group(1) if m else t)
        res = self._chat("GET", "chat.bsky.convo.getConvoForMembers", params={"members": [did]})
        convo = (res.get("convo") or {}).get("id")
        if not convo:
            raise PlatformError(self.name, f"no conversation available with {target!r}", body=res)
        return convo

    def _handle_of(self, dids):
        missing = [d for d in dict.fromkeys(dids) if d and d not in self._handles]
        for i in range(0, len(missing), 25):
            try:
                res = self._xrpc("GET", "app.bsky.actor.getProfiles", params={"actors": missing[i:i + 25]})
            except PlatformError:
                continue
            for p in res.get("profiles") or []:
                if p.get("did") and p.get("handle"):
                    self._handles[p["did"]] = p["handle"]
        return {d: self._handles.get(d) or d for d in dids}

    # ------------------------------------------------------------- text helpers
    @staticmethod
    def _graphemes(text):
        """Approximate extended-grapheme-cluster count (what Bluesky's 300 limit counts)."""
        count, prev, ri_open = 0, None, False
        for ch in text:
            cp = ord(ch)
            is_ri = 0x1F1E6 <= cp <= 0x1F1FF
            joins = prev is not None and (
                unicodedata.category(ch) in ("Mn", "Me", "Mc") or cp == 0x200D or prev == 0x200D
                or 0xFE00 <= cp <= 0xFE0F or 0x1F3FB <= cp <= 0x1F3FF or 0xE0020 <= cp <= 0xE007F
                or 0xE0100 <= cp <= 0xE01EF or (prev == 0x0D and cp == 0x0A) or (is_ri and ri_open))
            if not joins:
                count += 1
            ri_open = is_ri and not (joins and ri_open)
            prev = cp
        return count

    def _check_len(self, text, max_graphemes, max_bytes, what):
        n = self._graphemes(text)
        if n > max_graphemes:
            raise PlatformError(self.name, f"{what} is {n} characters; Bluesky allows {max_graphemes}")
        size = len(text.encode("utf-8"))
        if size > max_bytes:
            raise PlatformError(self.name, f"{what} is {size} bytes; Bluesky allows {max_bytes}")

    def _facets(self, text):
        """Rich-text facets for links, @mentions and #tags (UTF-8 byte offsets)."""
        def span(start, end):
            return {"byteStart": len(text[:start].encode("utf-8")), "byteEnd": len(text[:end].encode("utf-8"))}

        facets = []
        for m in re.finditer(r"(?:^|(?<=[\s(]))(https?://[^\s<>\"]+)", text, re.I):
            url = m.group(1)
            while url and (url[-1] in ".,;:!?\"'" or (url[-1] == ")" and "(" not in url)):
                url = url[:-1]
            if re.match(r"https?://[^/\s]+\.[^/\s]+", url, re.I):
                facets.append({"index": span(m.start(1), m.start(1) + len(url)),
                               "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]})
        label = r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
        for m in re.finditer(r"(?:^|(?<=[\s(]))@(" + label + r"(?:\." + label + r")+)", text):
            handle = m.group(1)
            if handle.rsplit(".", 1)[-1].isdigit():
                continue
            try:
                did = self._did_for(handle)
            except PlatformError:
                continue
            facets.append({"index": span(m.start(), m.end(1)),
                           "features": [{"$type": "app.bsky.richtext.facet#mention", "did": did}]})
        for m in re.finditer(r"(?:^|(?<=\s))[#＃]([^\s#＃]+)", text):
            tag = m.group(1)
            while tag and unicodedata.category(tag[-1]).startswith("P"):
                tag = tag[:-1]
            if not tag or tag.isdigit() or len(tag) > 64:
                continue
            facets.append({"index": span(m.start(), m.start(1) + len(tag)),
                           "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag}]})
        return sorted(facets, key=lambda f: f["index"]["byteStart"])

    @staticmethod
    def _now():
        t = time.time()
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{int(t % 1 * 1000):03d}Z"

    @staticmethod
    def _ts(value):
        m = re.match(r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(\.\d+)?(Z|[+-]\d\d:?\d\d)?$",
                     str(value or "").strip(), re.I)
        if not m:
            return 0.0
        ts = calendar.timegm(tuple(int(g) for g in m.groups()[:6]) + (0, 0, 0)) + float(m.group(7) or 0)
        tz = (m.group(8) or "Z").upper()
        if tz != "Z":
            ts -= (1 if tz[0] == "+" else -1) * (int(tz[1:3]) * 3600 + int(tz[-2:]) * 60)
        return float(ts)

    def _flag(self, key, default):
        v = self.config.get(key)
        if v is None or v == "":
            return default
        return str(v).strip().lower() not in ("false", "0", "no", "off")

    # ------------------------------------------------------------- media
    @staticmethod
    def _sniff(data):
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if data[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        if data[4:8] == b"ftyp":
            brand = data[8:12]
            if brand in (b"avif", b"avis"):
                return "image/avif"
            if brand in (b"heic", b"heix", b"mif1", b"msf1", b"heim", b"heis", b"hevc", b"hevx"):
                return "image/heic"
            if brand == b"qt  ":
                return "video/quicktime"
            return "video/mp4"
        if data[:4] == b"\x1a\x45\xdf\xa3":
            return "video/webm"
        return None

    @classmethod
    def _image_size(cls, data):
        """(width, height) as displayed, for PNG / GIF / WebP / JPEG; None if unknown."""
        try:
            size = None
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                size = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
            elif data[:6] in (b"GIF87a", b"GIF89a"):
                size = int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
            elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
                chunk = data[12:16]
                if chunk == b"VP8X":
                    size = 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
                elif chunk == b"VP8 ":
                    size = (int.from_bytes(data[26:28], "little") & 0x3FFF,
                            int.from_bytes(data[28:30], "little") & 0x3FFF)
                elif chunk == b"VP8L":
                    b = data[21:25]
                    size = (1 + (((b[1] & 0x3F) << 8) | b[0]),
                            1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6)))
            elif data[:2] == b"\xff\xd8":
                size = cls._jpeg_size(data)
        except IndexError:
            return None
        return size if size and size[0] > 0 and size[1] > 0 else None

    @classmethod
    def _jpeg_size(cls, data):
        i, n, orientation, size = 2, len(data), 1, None
        while i + 4 <= n:
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker == 0xFF:
                i += 1
                continue
            if marker in (0xD9, 0xDA):
                break
            if 0xD0 <= marker <= 0xD7 or marker == 0x01:
                i += 2
                continue
            seg = int.from_bytes(data[i + 2:i + 4], "big")
            body = data[i + 4:i + 2 + seg]
            if marker == 0xE1 and body[:6] == b"Exif\x00\x00":
                orientation = cls._exif_orientation(body[6:]) or orientation
            elif 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                size = int.from_bytes(body[3:5], "big"), int.from_bytes(body[1:3], "big")
                break
            i += 2 + seg
        if size and orientation in (5, 6, 7, 8):
            size = size[1], size[0]
        return size

    @staticmethod
    def _exif_orientation(tiff):
        order = {b"II": "little", b"MM": "big"}.get(bytes(tiff[:2]))
        if not order:
            return None
        off = int.from_bytes(tiff[4:8], order)
        for k in range(int.from_bytes(tiff[off:off + 2], order)):
            e = off + 2 + 12 * k
            if e + 12 > len(tiff):
                break
            if int.from_bytes(tiff[e:e + 2], order) == 0x0112:
                return int.from_bytes(tiff[e + 8:e + 10], order)
        return None

    def _load_media(self, src):
        src = str(src).strip()
        if re.match(r"https?://", src, re.I):
            data = self.http.get(src, raw=True)
            name = urllib.parse.unquote(urllib.parse.urlsplit(src).path.rsplit("/", 1)[-1]) or "media"
        else:
            path = os.path.expanduser(src)
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError as e:
                raise PlatformError(self.name, f"can't read media file {src!r}: {e}") from e
            name = os.path.basename(path)
        mime = self._sniff(data) or mimetypes.guess_type(name)[0] or "application/octet-stream"
        return name, data, mime

    def _upload(self, data, mime):
        res = self._xrpc("POST", "com.atproto.repo.uploadBlob", data=data, headers={"Content-Type": mime})
        if not isinstance(res, dict) or not res.get("blob"):
            raise PlatformError(self.name, f"blob upload failed: {res}", body=res)
        return res["blob"]

    def _media_embed(self, media):
        items = [self._load_media(m) for m in media]
        videos = [it for it in items if it[2].startswith("video/")]
        if videos:
            if len(items) > 1:
                raise PlatformError(self.name, "a Bluesky post takes either one video or up to 4 images")
            name, data, mime = videos[0]
            if mime != "video/mp4":
                raise PlatformError(self.name, f"{name}: Bluesky video embeds must be MP4 (got {mime})")
            if len(data) > self.VIDEO_BYTES:
                raise PlatformError(self.name, f"{name} is {len(data)} bytes; Bluesky's video limit is 100 MB")
            # Uploaded straight to the PDS as a blob; the AppView processes it for playback.
            return {"$type": "app.bsky.embed.video", "video": self._upload(data, mime)}
        if len(items) > self.MAX_IMAGES:
            raise PlatformError(self.name, f"Bluesky allows at most {self.MAX_IMAGES} images per post")
        for name, data, mime in items:
            if not mime.startswith("image/"):
                raise PlatformError(self.name, f"{name}: unsupported media type {mime} (images or one MP4 video)")
            if len(data) > self.IMAGE_BYTES:
                raise PlatformError(self.name, f"{name} is {len(data)} bytes; Bluesky's image limit is "
                                               f"{self.IMAGE_BYTES} bytes")
        images = []
        for name, data, mime in items:
            img = {"alt": "", "image": self._upload(data, mime)}
            size = self._image_size(data)
            if size:
                img["aspectRatio"] = {"width": size[0], "height": size[1]}
            images.append(img)
        return {"$type": "app.bsky.embed.images", "images": images}

    @staticmethod
    def _page_meta(page, base):
        meta = {}
        for tag in re.findall(r"<meta\b[^>]*>", page, re.I):
            attrs = {k.lower(): html.unescape(a or b or c) for k, a, b, c in
                     re.findall(r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'>]+))", tag)}
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            if key and attrs.get("content"):
                meta.setdefault(key, attrs["content"].strip())
        title = meta.get("og:title") or meta.get("twitter:title") or ""
        if not title:
            m = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
            title = html.unescape(m.group(1)) if m else ""
        image = meta.get("og:image") or meta.get("og:image:url") or meta.get("twitter:image") or ""
        return {"title": " ".join(title.split()),
                "description": meta.get("og:description") or meta.get("twitter:description")
                or meta.get("description") or "",
                "image": urllib.parse.urljoin(base, image) if image else ""}

    def _external_embed(self, link, title=None):
        """Link card; title/description/thumbnail read from the page's Open Graph tags when reachable."""
        meta = {}
        try:
            body = self.http.get(link, raw=True, headers={"Accept": "text/html"})
            if isinstance(body, (bytes, bytearray)):
                meta = self._page_meta(bytes(body[:1000000]).decode("utf-8", "replace"), link)
        except Exception:  # noqa: BLE001 - the card is optional decoration
            meta = {}
        ext = {"uri": link, "title": title or meta.get("title") or link, "description": meta.get("description") or ""}
        if meta.get("image"):
            try:
                data = self.http.get(meta["image"], raw=True)
                mime = self._sniff(data) or ""
                if mime.startswith("image/") and len(data) <= self.IMAGE_BYTES:
                    ext["thumb"] = self._upload(data, mime)
            except Exception:  # noqa: BLE001
                pass
        return {"$type": "app.bsky.embed.external", "external": ext}

    # ------------------------------------------------------------- records
    def _create_post(self, text, embed=None, reply=None):
        self._ensure_session()
        record = {"$type": self.POST, "text": text, "createdAt": self._now()}
        facets = self._facets(text)
        if facets:
            record["facets"] = facets
        langs = [x.strip() for x in str(self.config.get("langs") or "").split(",") if x.strip()]
        if langs:
            record["langs"] = langs[:3]
        if reply:
            record["reply"] = reply
        if embed:
            record["embed"] = embed
        res = self._xrpc("POST", "com.atproto.repo.createRecord",
                         json={"repo": self._did, "collection": self.POST, "record": record})
        return Result(id=res["uri"], url=self._post_url(res["uri"], self._handle), raw=res)

    def _fetch_post(self, uri):
        posts = self._xrpc("GET", "app.bsky.feed.getPosts", params={"uris": [uri]}).get("posts") or []
        if posts:
            return posts[0]
        m = re.match(r"^at://([^/]+)/([^/]+)/([^/]+)$", uri)
        res = self._xrpc("GET", "com.atproto.repo.getRecord",
                         params={"repo": m.group(1), "collection": m.group(2), "rkey": m.group(3)})
        if not res.get("cid"):
            raise PlatformError(self.name, f"post not found: {uri}", body=res)
        return {"uri": res.get("uri") or uri, "cid": res["cid"], "record": res.get("value") or {}}

    # ------------------------------------------------------------- actions
    def whoami(self):
        res = self._xrpc("GET", "com.atproto.server.getSession")
        self._handle = res.get("handle") or self._handle
        self._did = res.get("did") or self._did
        return "@" + (self._handle or self._did)

    def post(self, text, target=None, title=None, link=None, media=None):
        """Post to the own feed. title: link-card title when link is given, else a first line.
        link: link card (or appended to the text when media is attached)."""
        text = (text or "").strip()
        media = [media] if isinstance(media, str) else list(media or [])
        if title and not link:
            text = f"{title}\n\n{text}" if text else title
        if link and media and link not in text:
            text = f"{text}\n\n{link}" if text else link
        self._check_len(text, self.POST_GRAPHEMES, self.POST_BYTES, "post")
        if media:
            embed = self._media_embed(media)
        elif link:
            embed = self._external_embed(link, title)
        else:
            embed = None
        return self._create_post(text, embed=embed)

    def comment(self, target, text):
        text = (text or "").strip()
        self._check_len(text, self.POST_GRAPHEMES, self.POST_BYTES, "reply")
        parent = self._fetch_post(self._post_uri(target))
        if (parent.get("viewer") or {}).get("replyDisabled"):
            raise PlatformError(self.name, f"the author has restricted who can reply to {parent['uri']}")
        ref = {"uri": parent["uri"], "cid": parent["cid"]}
        root = ((parent.get("record") or {}).get("reply") or {}).get("root") or ref
        return self._create_post(text, reply={"root": {"uri": root["uri"], "cid": root["cid"]}, "parent": ref})

    def dm(self, target, text):
        text = (text or "").strip()
        self._check_len(text, self.DM_GRAPHEMES, self.DM_BYTES, "message")
        convo = self._convo_id(target)
        message = {"text": text}
        facets = self._facets(text)
        if facets:
            message["facets"] = facets
        res = self._chat("POST", "chat.bsky.convo.sendMessage", json={"convoId": convo, "message": message})
        return Result(id=str(res.get("id") or ""), url=f"{self.WEB}/messages/{convo}", raw=res)

    # ------------------------------------------------------------- polling
    def poll(self, state):
        self._ensure_session()
        dms, chat_rev = [], state.get("chat_rev")
        if self._flag("poll_dms", True):
            dms, chat_rev = self._poll_dms(chat_rev)
        notes, notif_at = self._poll_notifications(state.get("notif_at"))
        # cursors are committed only after both calls succeeded
        if chat_rev:
            state["chat_rev"] = chat_rev
        if notif_at:
            state["notif_at"] = notif_at
        return sorted(notes + dms, key=lambda i: i.ts)

    def _poll_notifications(self, since):
        # Repeats inside the overlap window are removed by the bridge's id de-duplication.
        cutoff = self._ts(since) - self.NOTIF_OVERLAP if since else None
        fresh, newest, cursor = [], since, None
        for _ in range(5):
            params = {"limit": 50, "reasons": list(self.NOTIF_REASONS)}
            if cursor:
                params["cursor"] = cursor
            res = self._xrpc("GET", "app.bsky.notification.listNotifications", params=params)
            notes = res.get("notifications") or []
            reached_old = False
            for n in notes:
                at = self._ts(n.get("indexedAt"))
                if cutoff is not None and at < cutoff:
                    reached_old = True
                    continue
                fresh.append(n)
                if newest is None or at > self._ts(newest):
                    newest = n.get("indexedAt")
            cursor = res.get("cursor")
            if reached_old or cutoff is None or not notes or not cursor:
                break
        items = [self._note_item(n) for n in fresh]
        return [i for i in items if i], newest

    def _note_item(self, n):
        author = n.get("author") or {}
        if n.get("reason") not in self.NOTIF_REASONS or author.get("did") == self._did or not n.get("uri"):
            return None
        rec = n.get("record") or {}
        reply = rec.get("reply") or {}
        root = (reply.get("root") or {}).get("uri") or ""
        if n["reason"] == "reply":
            parent = (reply.get("parent") or {}).get("uri") or ""
            mine = self._uri_did(parent) == self._did
            kind = "reply" if mine and parent != root else "comment"
        else:
            kind = "mention"
        handle = author.get("handle") if author.get("handle") not in (None, "", "handle.invalid") else author.get("did")
        if author.get("did") and author.get("handle"):
            self._handles.setdefault(author["did"], author["handle"])
        return Incoming(
            platform=self.name, kind=kind, id=n["uri"], author="@" + str(handle), author_id=author.get("did") or "",
            text=rec.get("text") or "", url=self._post_url(n["uri"], handle), thread=root or n["uri"],
            ts=self._ts(rec.get("createdAt")) or self._ts(n.get("indexedAt")),
            reply_to={"action": "comment", "target": n["uri"]}, raw=n)

    def _poll_dms(self, rev):
        # Without a cursor getLog returns the current head cursor (how the Bluesky app initialises).
        res = self._chat("GET", "chat.bsky.convo.getLog", params={"cursor": rev} if rev else {})
        logs = res.get("logs") or []
        revs = [r for r in [rev, res.get("cursor")] + [ev.get("rev") for ev in logs] if isinstance(r, str) and r]
        newest = max(revs) if revs else None
        msgs = []
        for ev in logs:
            r = ev.get("rev")
            if rev and isinstance(r, str) and r <= rev:
                continue
            if not str(ev.get("$type", "")).endswith("#logCreateMessage"):
                continue
            m = ev.get("message") or {}
            if str(m.get("$type", "")).endswith("#deletedMessageView") or "text" not in m:
                continue
            sender = (m.get("sender") or {}).get("did") or ""
            if not sender or sender == self._did:
                continue
            msgs.append((ev.get("convoId") or m.get("convoId") or "", m, sender))
        handles = self._handle_of([s for _, _, s in msgs]) if msgs else {}
        out = []
        for convo, m, sender in msgs:
            out.append(Incoming(
                platform=self.name, kind="dm", id=str(m.get("id")), author="@" + handles.get(sender, sender),
                author_id=sender, text=m.get("text") or "", url=f"{self.WEB}/messages/{convo}" if convo else "",
                thread=convo, ts=self._ts(m.get("sentAt")),
                reply_to={"action": "dm", "target": f"convo:{convo}"}, raw={"convoId": convo, **m}))
        return out, newest


# ============================================================================
# social_bridge/adapters/mastodon.py — Mastodon (and any Mastodon-API server: Pleroma, Akkoma, GoToSocial...).
# ============================================================================
import html
import re



@register
class MastodonAdapter(Adapter):
    name = "mastodon"
    label = "Mastodon"
    actions = ("post", "comment", "dm")
    poll_interval = 60
    config_keys = {
        "instance": "Server base URL, e.g. https://mastodon.social",
        "access_token": "Preferences -> Development -> New application (scopes: read write) -> access token",
        "visibility": "(optional) default post visibility: public | unlisted | private (default public)",
    }
    target_help = {
        "post": "omit (posts to your own timeline)",
        "comment": "status ID or status URL to reply to",
        "dm": "account handle like @user@server or user (local)",
    }

    # ------------------------------------------------------------- helpers
    def _base(self):
        (instance,) = self.need("instance")
        return instance.rstrip("/")

    def _h(self):
        (tok,) = self.need("access_token")
        return {"Authorization": f"Bearer {tok}"}

    def _api(self, method, path, **kw):
        return self.http.request(method, f"{self._base()}{path}", headers=self._h(), **kw)

    @staticmethod
    def _mastodon_text(content):
        text = re.sub(r"<br\s*/?>", "\n", content or "")
        text = re.sub(r"</p>\s*<p>", "\n\n", text)
        return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()

    def _status_id(self, target):
        target = str(target).strip()
        m = re.search(r"/(\d+)/?$", target)
        if target.isdigit():
            return target
        if m:
            # URL from another server: resolve through search so we get the local ID
            if not target.startswith(self._base()):
                res = self._api("GET", "/api/v2/search", params={"q": target, "resolve": "true", "type": "statuses"})
                if res.get("statuses"):
                    return res["statuses"][0]["id"]
            return m.group(1)
        raise PlatformError(self.name, f"can't read a status id from {target!r}")

    def _upload(self, path_or_url):
        if re.match(r"https?://", path_or_url):
            content = self.http.get(path_or_url, raw=True)
            files = {"file": (path_or_url.rsplit("/", 1)[-1] or "image", content)}
        else:
            files = {"file": open(path_or_url, "rb")}
        try:
            return self._api("POST", "/api/v2/media", files=files)["id"]
        finally:
            f = files["file"]
            if hasattr(f, "close"):
                f.close()

    def _create(self, text, **extra):
        body = {"status": text, "visibility": extra.pop("visibility", self.config.get("visibility") or "public")}
        body.update({k: v for k, v in extra.items() if v})
        res = self._api("POST", "/api/v1/statuses", json=body)
        return Result(id=str(res["id"]), url=res.get("url") or "", raw=res)

    # ------------------------------------------------------------- actions
    def whoami(self):
        me = self._api("GET", "/api/v1/accounts/verify_credentials")
        return "@" + me["acct"]

    def post(self, text, target=None, title=None, link=None, media=None):
        if link:
            text = f"{text}\n\n{link}"
        media_ids = [self._upload(m) for m in (media or [])]
        return self._create(text, media_ids=media_ids, spoiler_text=title)

    def comment(self, target, text):
        sid = self._status_id(target)
        parent = self._api("GET", f"/api/v1/statuses/{sid}")
        handle = "@" + parent["account"]["acct"]
        if handle.lower() not in text.lower():
            text = f"{handle} {text}"
        vis = parent.get("visibility") if parent.get("visibility") in ("direct", "private", "unlisted") else None
        return self._create(text, in_reply_to_id=sid, **({"visibility": vis} if vis else {}))

    def dm(self, target, text):
        handle = "@" + str(target).lstrip("@")
        if handle.lower() not in text.lower():
            text = f"{handle} {text}"
        return self._create(text, visibility="direct")

    def poll(self, state):
        params = {"limit": 40, "types[]": ["mention"]}
        if state.get("since_id"):
            params["since_id"] = state["since_id"]
        notes = self._api("GET", "/api/v1/notifications", params=params)
        out = []
        for n in sorted(notes, key=lambda n: int(n["id"])):
            st = n.get("status")
            if not st:
                continue
            is_dm = st.get("visibility") == "direct"
            acct = st["account"]["acct"]
            kind = "dm" if is_dm else ("reply" if st.get("in_reply_to_id") else "mention")
            out.append(Incoming(
                platform=self.name, kind=kind, id=str(st["id"]), author="@" + acct,
                author_id=str(st["account"]["id"]), text=self._mastodon_text(st.get("content")),
                url=st.get("url") or "", thread=str(st.get("conversation_id") or st.get("in_reply_to_id") or st["id"]),
                reply_to={"action": "dm" if is_dm else "comment", "target": acct if is_dm else str(st["id"])},
                raw=n,
            ))
        if notes:
            state["since_id"] = str(max(int(n["id"]) for n in notes))
        return out


# ============================================================================
# social_bridge/adapters/telegram.py — Telegram Bot API (bot account; updates fetched with getUpdates).
# ============================================================================
import json
import logging
import mimetypes
import os
import re
import urllib.parse



@register
class TelegramAdapter(Adapter):
    name = "telegram"
    label = "Telegram"
    actions = ("post", "comment", "dm")
    poll_interval = 15  # getUpdates has no published quota; short polling every 15 s keeps latency low
    config_keys = {
        "bot_token": "Telegram app -> chat with @BotFather -> /newbot (or /mybots -> your bot -> API Token) -> "
                     "token like 123456789:AA...; the bot must have no webhook set (updates are read with "
                     "getUpdates). To receive plain @mentions in groups: @BotFather -> /mybots -> Bot Settings "
                     "-> Group Privacy -> Turn off, or make the bot a group admin",
        "default_chat": "(optional) chat used by post when no target is given: @channelusername or numeric chat "
                        "id such as -1001234567890 (the thread value of an incoming item from that chat); "
                        "channels need the bot added as admin with 'Post Messages'",
        "api_base": "(optional) Bot API server URL (default https://api.telegram.org; set it for a self-hosted "
                    "telegram-bot-api server)",
    }
    target_help = {
        "post": "@channelusername, numeric chat id (-100... for channels/supergroups) or a t.me/<username> "
                "link; omit to use default_chat",
        "comment": "message to reply to: <chat_id>:<message_id> (chat id numeric or @username) or a message link "
                   "t.me/<username>/<id>, t.me/c/<internal_id>/<id>, t.me/<channel>/<post>?comment=<id>",
        "dm": "numeric user/chat id, or @username / t.me/<username> of a user who has messaged the bot "
              "(bots can't start chats with users by username)",
    }

    API = "https://api.telegram.org"
    TEXT_LIMIT = 4096
    CAPTION_LIMIT = 1024
    ALBUM_MAX = 10
    SEND = {"photo": "sendPhoto", "video": "sendVideo", "animation": "sendAnimation", "audio": "sendAudio",
            "document": "sendDocument"}
    ALLOWED_UPDATES = ["message", "edited_message", "channel_post"]
    PLACEHOLDERS = ("photo", "video", "animation", "voice", "video_note", "audio", "document", "sticker",
                    "location", "venue", "contact", "poll", "dice", "story")
    LINK = re.compile(r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/(.+)$", re.I)
    USERNAME = r"[A-Za-z]\w{3,31}"
    # t.me first path segments that are link types, not chat usernames
    RESERVED = frozenset(("joinchat", "addstickers", "addemoji", "addtheme", "addlist", "share", "proxy", "socks",
                          "setlanguage", "login", "invoice", "boost", "confirmphone", "contact", "giftcode", "nft"))

    def __init__(self, config, http=None):
        super().__init__(config, http)
        self._me_cache = None
        self._users = {}       # lowercased username -> user id (people who messaged the bot privately)
        self._channels = set()  # channels this bot posts to: "<id>" and "@username" (lowercase)
        if self.config.get("default_chat"):
            try:
                self._remember_channel_ref(self._chat(self.config["default_chat"]))
            except PlatformError:
                pass

    # ------------------------------------------------------------- transport
    def _call(self, method, body=None, files=None):
        (token,) = self.need("bot_token")
        url = f"{(self.config.get('api_base') or self.API).rstrip('/')}/bot{token}/{method}"
        body = {k: v for k, v in (body or {}).items() if v is not None}
        for attempt in (0, 1):
            try:
                if files:
                    data = {k: v if isinstance(v, str) else json.dumps(v) for k, v in body.items()}
                    res = self.http.post(url, data=data, files=files)
                else:
                    res = self.http.post(url, json=body)
            except PlatformError as e:
                err = e.body if isinstance(e.body, dict) else {}
                moved = (err.get("parameters") or {}).get("migrate_to_chat_id")
                if moved and attempt == 0 and "chat_id" in body:
                    body = dict(body, chat_id=moved)  # group was upgraded to a supergroup
                    continue
                msg = err.get("description") or str(e).replace(token, "<token>")
                raise PlatformError(self.name, f"{method}: {msg}", e.status, e.body) from None
            except Exception as e:  # noqa: BLE001 - network errors carry the URL, which contains the token
                raise PlatformError(self.name, f"{method}: {str(e).replace(token, '<token>')}") from None
            if not isinstance(res, dict) or not res.get("ok"):
                desc = res.get("description") if isinstance(res, dict) else str(res)[:300]
                raise PlatformError(self.name, f"{method}: {desc}", body=res)
            return res.get("result")

    def _me(self):
        if self._me_cache is None:
            self._me_cache = self._call("getMe")
        return self._me_cache

    # ------------------------------------------------------------- text helpers
    @staticmethod
    def _u16(text):
        return len((text or "").encode("utf-16-le")) // 2

    @staticmethod
    def _chunks(text, limit):
        """Split text into pieces of at most `limit` UTF-16 units, preferring paragraph/line/word breaks."""
        text = text or ""
        out = []
        while TelegramAdapter._u16(text) > limit:
            n, units = 0, 0
            for ch in text:
                w = 2 if ord(ch) > 0xFFFF else 1
                if units + w > limit:
                    break
                units += w
                n += 1
            for sep in ("\n\n", "\n", " "):
                idx = text.rfind(sep, 0, n)
                if idx > n // 2:
                    n = idx
                    break
            out.append(text[:n].rstrip())
            text = text[n:].lstrip()
        if text or not out:
            out.append(text)
        return out

    def _compose(self, text, title=None, link=None):
        text = text or ""
        if link:
            text = f"{text}\n\n{link}" if text.strip() else link
        entities = None
        if title:
            text = f"{title}\n\n{text}" if text else title
            entities = [{"type": "bold", "offset": 0, "length": self._u16(title)}]
        return text, entities

    # ------------------------------------------------------------- target parsing
    def _chat(self, target):
        t = str(target or "").strip()
        if not t:
            raise PlatformError(self.name, "no chat given (pass a target or set default_chat)")
        m = self.LINK.match(t)
        if m:
            parts = [p for p in urllib.parse.urlsplit("https://t.me/" + m.group(1)).path.split("/") if p]
            if parts and parts[0] == "s":
                parts = parts[1:]
            if len(parts) >= 2 and parts[0] == "c" and parts[1].isdigit():
                return int("-100" + parts[1])
            if parts and parts[0].lower() not in self.RESERVED and re.fullmatch(self.USERNAME, parts[0]):
                return "@" + parts[0]
            raise PlatformError(self.name, f"can't read a chat from {t!r} (invite links can't be used; add the "
                                           f"bot to the chat and use its id)")
        if re.fullmatch(r"-?\d+", t):
            return int(t)
        if re.fullmatch("@?" + self.USERNAME, t):
            return "@" + t.lstrip("@")
        raise PlatformError(self.name, f"can't read a chat from {t!r}")

    def _message_ref(self, target):
        """-> (chat_id, message_id) from '<chat>:<id>', a t.me message link or a tg:// link."""
        t = str(target or "").strip()
        if t.lower().startswith("tg://"):
            u = urllib.parse.urlsplit(t)
            q = urllib.parse.parse_qs(u.query)
            post = (q.get("post") or [""])[0]
            if u.netloc == "privatepost" and (q.get("channel") or [""])[0].isdigit() and post.isdigit():
                return int("-100" + q["channel"][0]), int(post)
            if u.netloc == "resolve" and q.get("domain") and post.isdigit():
                return "@" + q["domain"][0], int(post)
        m = self.LINK.match(t)
        if m:
            u = urllib.parse.urlsplit("https://t.me/" + m.group(1))
            parts = [p for p in u.path.split("/") if p]
            if parts and parts[0] == "s":
                parts = parts[1:]
            q = urllib.parse.parse_qs(u.query)
            if len(parts) >= 3 and parts[0] == "c" and parts[1].isdigit() and parts[-1].isdigit():
                chat, mid = int("-100" + parts[1]), int(parts[-1])
            elif len(parts) >= 2 and parts[0].lower() not in self.RESERVED and \
                    re.fullmatch(self.USERNAME, parts[0]) and parts[-1].isdigit():
                chat, mid = "@" + parts[0], int(parts[-1])
            else:
                raise PlatformError(self.name, f"can't read a message from link {t!r}")
            comment = (q.get("comment") or [""])[0]
            if comment.isdigit():
                # comment under a channel post: it lives in the channel's linked discussion group
                linked = (self._call("getChat", {"chat_id": chat}) or {}).get("linked_chat_id")
                if not linked:
                    raise PlatformError(self.name, f"{chat} has no linked discussion group")
                chat, mid = linked, int(comment)
            return chat, mid
        m = re.fullmatch(rf"(@?{self.USERNAME}|-?\d+)[:/](\d+)", t)
        if m:
            c = m.group(1)
            return (int(c) if re.fullmatch(r"-?\d+", c) else "@" + c.lstrip("@")), int(m.group(2))
        raise PlatformError(self.name, f"can't read a message from {t!r}; use <chat_id>:<message_id> or a "
                                       f"t.me message link")

    def _dm_chat(self, target):
        t = str(target or "").strip()
        m = self.LINK.match(t)
        if m:
            t = m.group(1).split("/")[0].split("?")[0]
        if re.fullmatch(r"-?\d+", t):
            return int(t)
        name = t.lstrip("@").lower()
        if name in self._users:
            return int(self._users[name])
        # Bot API: bots address users only by numeric id, and only after the user has started the bot.
        raise PlatformError(self.name, f"no chat id known for {target!r}: Telegram bots can message a user only by "
                                       f"numeric id, after that user has messaged the bot")

    # ------------------------------------------------------------- sending
    def _send_text(self, chat, text, entities=None, reply_to=None):
        msgs = []
        for i, chunk in enumerate(self._chunks(text, self.TEXT_LIMIT)):
            body = {"chat_id": chat, "text": chunk}
            if i == 0:
                if entities and entities[0]["length"] <= self._u16(chunk):
                    body["entities"] = entities
                if reply_to:
                    body["reply_parameters"] = {"message_id": reply_to}
            msgs.append(self._call("sendMessage", body))
        return msgs

    @staticmethod
    def _kind(name, default):
        mime = mimetypes.guess_type(name)[0] or ""
        if not mime:
            return default
        if mime == "image/gif":
            return "animation"
        if mime in ("image/jpeg", "image/png", "image/webp"):
            return "photo"
        return {"video": "video", "audio": "audio"}.get(mime.split("/")[0], "document")

    def _media(self, src):
        """-> (kind, URL string or (filename, bytes, mime) for upload)."""
        src = str(src)
        if re.match(r"https?://", src, re.I):
            return self._kind(urllib.parse.urlsplit(src).path, "photo"), src
        if not os.path.isfile(src):
            raise PlatformError(self.name, f"media file not found: {src}")
        name = os.path.basename(src)
        with open(src, "rb") as f:
            content = f.read()
        return self._kind(name, "document"), (name, content, mimetypes.guess_type(name)[0] or
                                              "application/octet-stream")

    def _send_media(self, chat, text, entities, media):
        if len(media) > self.ALBUM_MAX:
            raise PlatformError(self.name, f"a Telegram album holds at most {self.ALBUM_MAX} media items "
                                           f"(got {len(media)})")
        items = [self._media(src) for src in media]
        fits = self._u16(text) <= self.CAPTION_LIMIT
        caption, cap_entities = (text or None, entities) if fits else (None, None)
        if len(items) == 1:
            kind, src = items[0]
            body = {"chat_id": chat, "caption": caption, "caption_entities": cap_entities}
            files = None
            if isinstance(src, tuple):
                files = {kind: src}
            else:
                body[kind] = src
            msgs = [self._call(self.SEND[kind], body, files=files)]
        else:
            kinds = {k for k, _ in items}
            if not (kinds <= {"photo", "video"} or kinds in ({"document"}, {"audio"})):
                raise PlatformError(self.name, "a Telegram album can mix photos and videos, or hold only documents "
                                               "or only audio files (GIFs must be sent alone)")
            group, files = [], {}
            for i, (kind, src) in enumerate(items):
                entry = {"type": kind, "media": src}
                if isinstance(src, tuple):
                    files[f"file{i}"] = src
                    entry["media"] = f"attach://file{i}"
                if i == 0 and caption:
                    entry["caption"] = caption
                    if cap_entities:
                        entry["caption_entities"] = cap_entities
                group.append(entry)
            msgs = list(self._call("sendMediaGroup", {"chat_id": chat, "media": group}, files=files or None))
        if text and not fits:
            msgs += self._send_text(chat, text, entities)
        return msgs

    @staticmethod
    def _msg_url(chat, message_id):
        if chat.get("type") == "private":
            return ""
        if chat.get("username"):
            return f"https://t.me/{chat['username']}/{message_id}"
        cid = str(chat.get("id", ""))
        if cid.startswith("-100"):
            return f"https://t.me/c/{cid[4:]}/{message_id}"
        return ""

    def _result(self, msgs):
        first = msgs[0]
        chat = first.get("chat") or {}
        return Result(id=f"{chat.get('id')}:{first['message_id']}", url=self._msg_url(chat, first["message_id"]),
                      raw=first if len(msgs) == 1 else {"messages": msgs})

    def _remember_channel_ref(self, ref):
        self._channels.add(ref.lower() if isinstance(ref, str) else str(ref))

    # ------------------------------------------------------------- actions
    def whoami(self):
        me = self._me()
        return "@" + me["username"] if me.get("username") else me.get("first_name", "")

    def post(self, text, target=None, title=None, link=None, media=None):
        chat = self._chat(target or self.config.get("default_chat"))
        text, entities = self._compose(text, title, link)
        msgs = self._send_media(chat, text, entities, list(media)) if media else self._send_text(chat, text, entities)
        sent_chat = msgs[0].get("chat") or {}
        if sent_chat.get("type") == "channel":
            self._remember_channel_ref(sent_chat["id"])
            if sent_chat.get("username"):
                self._remember_channel_ref("@" + sent_chat["username"])
        return self._result(msgs)

    def comment(self, target, text):
        chat, mid = self._message_ref(target)
        return self._result(self._send_text(chat, text, reply_to=mid))

    def dm(self, target, text):
        return self._result(self._send_text(self._dm_chat(target), text))

    # ------------------------------------------------------------- polling
    def _text(self, msg):
        text = msg.get("text") or msg.get("caption") or ""
        for key in self.PLACEHOLDERS:
            if key in msg:
                label = f"[sticker {msg[key].get('emoji', '')}]".replace(" ]", "]") if key == "sticker" else f"[{key}]"
                return f"{label} {text}".strip()
        return text

    @staticmethod
    def _author(msg):
        sc = msg.get("sender_chat")
        if sc:  # anonymous admin, channel, or post forwarded from a linked channel
            return ("@" + sc["username"]) if sc.get("username") else sc.get("title", ""), str(sc.get("id", ""))
        frm = msg.get("from") or {}
        name = ("@" + frm["username"]) if frm.get("username") else \
            " ".join(p for p in (frm.get("first_name"), frm.get("last_name")) if p)
        return name, str(frm.get("id", ""))

    def _mentions_me(self, msg, text, me):
        for e in (msg.get("entities") or []) + (msg.get("caption_entities") or []):
            if e.get("type") == "text_mention" and (e.get("user") or {}).get("id") == me["id"]:
                return True
        uname = me.get("username")
        return bool(uname and re.search(rf"(?<![\w@])@{re.escape(uname)}(?!\w)", text, re.I))

    def _own_channel(self, chat):
        return str(chat.get("id")) in self._channels or \
            bool(chat.get("username")) and ("@" + chat["username"].lower()) in self._channels

    def _incoming(self, upd, me):
        edited = "edited_message" in upd
        msg = upd.get("message") or upd.get("edited_message") or upd.get("channel_post")
        if not msg or not msg.get("chat"):
            return None
        if (msg.get("from") or {}).get("id") == me["id"]:
            return None
        chat = msg["chat"]
        cid, mid = str(chat["id"]), msg["message_id"]
        text = self._text(msg)
        author, author_id = self._author(msg)
        if chat.get("type") == "private":
            kind, thread = "dm", cid
            reply_to = {"action": "dm", "target": cid}
            frm = msg.get("from") or {}
            if frm.get("username"):
                self._users.pop(frm["username"].lower(), None)
                self._users[frm["username"].lower()] = frm["id"]
        else:
            parent = msg.get("reply_to_message") or {}
            if (parent.get("from") or {}).get("id") == me["id"]:
                kind = "reply"
            elif self._mentions_me(msg, text, me):
                kind = "mention"
            elif parent.get("is_automatic_forward") and self._own_channel(parent.get("sender_chat") or {}):
                kind = "comment"  # comment under one of our channel posts, in the linked discussion group
            else:
                return None
            reply_to = {"action": "comment", "target": f"{cid}:{mid}"}
            thread = f"{cid}:{msg['message_thread_id']}" if msg.get("message_thread_id") else cid
        return Incoming(
            platform=self.name, kind=kind, id=f"{cid}:{mid}" + (f":e{msg.get('edit_date', 0)}" if edited else ""),
            author=author, author_id=author_id, text=text, url=self._msg_url(chat, mid), thread=thread,
            ts=float(msg.get("edit_date") if edited and msg.get("edit_date") else msg.get("date") or 0),
            reply_to=reply_to, raw=upd,
        )

    def poll(self, state):
        me = self._me()
        users = state.setdefault("users", {})
        users.update(self._users)
        for k in list(users)[:-2000]:
            del users[k]
        self._users = users
        chans = state.setdefault("channels", [])
        chans.extend(sorted(c for c in self._channels if c not in chans))
        del chans[:-100]
        self._channels = set(chans)
        out = []
        for page in range(5):
            body = {"timeout": 0, "limit": 100, "allowed_updates": self.ALLOWED_UPDATES}
            if state.get("offset"):
                body["offset"] = state["offset"]
            try:
                updates = self._call("getUpdates", body) or []
            except PlatformError as e:
                if page == 0:
                    raise  # nothing read yet; the offset is unchanged
                # earlier pages already moved the offset: return what they produced
                logging.getLogger("social_bridge").warning("telegram poll: %s", e)
                break
            for upd in updates:
                state["offset"] = max(int(state.get("offset") or 0), int(upd["update_id"]) + 1)
                try:
                    item = self._incoming(upd, me)
                except Exception as e:  # noqa: BLE001 - the offset is already past upd; keep the rest
                    logging.getLogger("social_bridge").warning("telegram: skipped update %s: %r",
                                                               upd.get("update_id"), e)
                    continue
                if item:
                    out.append(item)
            if len(updates) < 100:
                break
        return out


# ============================================================================
# social_bridge/adapters/discord.py — Discord bot account over the REST API only (no gateway connection).
# ============================================================================
import json
import logging
import mimetypes
import os
import re
import time
import urllib.parse



@register
class DiscordAdapter(Adapter):
    name = "discord"
    label = "Discord"
    actions = ("post", "comment", "dm")
    poll_interval = 20  # one GET per polled channel; Discord allows 50 requests/s per bot plus per-route buckets
    config_keys = {
        "bot_token": "discord.com/developers/applications -> your application -> Bot -> Reset Token -> copy. Add the "
                     "bot to a server from OAuth2 -> URL Generator (scope: bot; permissions: View Channels, Send "
                     "Messages, Send Messages in Threads, Create Public Threads, Read Message History, Attach Files)",
        "default_channel": "(optional) channel id used by post when no target is given (Discord app: User Settings "
                           "-> Advanced -> Developer Mode on, then right-click the channel -> Copy Channel ID)",
        "watch_channels": "(optional) comma-separated channel ids polled for messages that mention the bot or reply "
                          "to it (channels the bot posts or comments in are polled automatically). Replies that "
                          "don't ping the bot are readable only with Bot -> Privileged Gateway Intents -> Message "
                          "Content Intent turned on",
        "dm_users": "(optional) comma-separated user ids whose DMs with the bot are polled from the start "
                    "(right-click user -> Copy User ID); DM channels opened by dm are polled automatically",
        "api_version": "(optional) REST API version (default 10)",
        "user_agent": "(optional) User-Agent header (default DiscordBot (social-bridge, 1.0))",
    }
    target_help = {
        "post": "channel id or channel link https://discord.com/channels/<guild>/<channel> (in a forum channel this "
                "creates a new post named by title); omit to use default_channel",
        "comment": "message to reply to: <channel_id>/<message_id> or a message link "
                   "https://discord.com/channels/<guild|@me>/<channel>/<message>; a bare thread/channel id or link "
                   "sends into that thread without replying to a specific message",
        "dm": "user id, <@id> mention, https://discord.com/users/<id>, username of someone the bot has seen, or a "
              "DM channel link https://discord.com/channels/@me/<channel>",
    }

    WEB = "https://discord.com"
    TEXT_LIMIT = 2000
    MAX_FILES = 10
    EPOCH_MS = 1420070400000
    PAGE = 50
    FORUM_TYPES = (15, 16)      # GUILD_FORUM, GUILD_MEDIA
    MESSAGE_TYPES = (0, 19)     # DEFAULT, REPLY (system messages are skipped)
    TRACK_MAX = 50              # auto-tracked channels / DM channels kept in poll state
    LINK = re.compile(r"^(?:https?://)?(?:(?:www|ptb|canary)\.)?discord(?:app)?\.com/(.+)$", re.I)

    def __init__(self, config, http=None):
        super().__init__(config, http)
        self._me_cache = None
        self._chan_cache = {}   # channel id -> channel object
        self._dm_by_user = {}   # user id -> DM channel id
        self._users = {}        # lowercased username -> user id
        self._track = {}        # channel id -> {"after", "kind": dm|thread|channel, "user"}; merged in poll

    # ------------------------------------------------------------- transport
    def _api(self, method, path, **kw):
        (token,) = self.need("bot_token")
        ver = str(self.config.get("api_version") or "10").lstrip("v")
        headers = {"Authorization": f"Bot {token}",
                   "User-Agent": self.config.get("user_agent") or "DiscordBot (social-bridge, 1.0)"}
        try:
            return self.http.request(method, f"{self.WEB}/api/v{ver}{path}", headers=headers, **kw)
        except PlatformError as e:
            b = e.body if isinstance(e.body, dict) else {}
            if not b.get("message"):
                raise
            detail = b["message"] + (f" (code {b['code']})" if b.get("code") else "")
            if b.get("errors"):
                detail += " " + json.dumps(b["errors"], separators=(",", ":"))[:300]
            raise PlatformError(self.name, f"{method} {path}: {detail}", e.status, e.body) from None

    def _me(self):
        if self._me_cache is None:
            self._me_cache = self._api("GET", "/users/@me")
        return self._me_cache

    def _channel(self, cid):
        if cid not in self._chan_cache:
            self._chan_cache[cid] = self._api("GET", f"/channels/{cid}")
        return self._chan_cache[cid]

    def _guild_of(self, cid):
        try:
            return self._channel(cid).get("guild_id") or "@me"
        except PlatformError:
            return ""

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _chunks(text, limit):
        """Split text into pieces of at most `limit` UTF-16 units, preferring paragraph/line/word breaks."""
        def units(s):
            return len(s.encode("utf-16-le")) // 2
        text = text or ""
        out = []
        while units(text) > limit:
            n, used = 0, 0
            for ch in text:
                w = 2 if ord(ch) > 0xFFFF else 1
                if used + w > limit:
                    break
                used += w
                n += 1
            for sep in ("\n\n", "\n", " "):
                idx = text.rfind(sep, 0, n)
                if idx > n // 2:
                    n = idx
                    break
            out.append(text[:n].rstrip())
            text = text[n:].lstrip()
        if text or not out:
            out.append(text)
        return out

    def _ts(self, snowflake):
        return ((int(snowflake) >> 22) + self.EPOCH_MS) / 1000.0

    def _snowflake_now(self):
        return str((int(time.time() * 1000) - self.EPOCH_MS) << 22)

    def _link_parts(self, target):
        m = self.LINK.match(target)
        if not m:
            return None
        return [p for p in urllib.parse.urlsplit("https://x/" + m.group(1)).path.split("/") if p]

    # ------------------------------------------------------------- target parsing
    def _channel_target(self, target):
        t = str(target or "").strip()
        if not t:
            raise PlatformError(self.name, "no channel given (pass a target or set default_channel)")
        parts = self._link_parts(t)
        if parts and parts[0] == "channels" and len(parts) >= 3 and parts[2].isdigit():
            return parts[2]
        m = re.fullmatch(r"<#(\d+)>|(\d+)", t)
        if m:
            return m.group(1) or m.group(2)
        raise PlatformError(self.name, f"can't read a channel from {t!r}")

    def _message_target(self, target):
        """-> (channel id, message id or None)."""
        t = str(target or "").strip()
        parts = self._link_parts(t)
        if parts:
            if parts[0] == "channels" and len(parts) >= 3 and parts[2].isdigit():
                mid = parts[3] if len(parts) > 3 and parts[3].isdigit() else None
                return parts[2], mid
            raise PlatformError(self.name, f"can't read a message from link {t!r}")
        m = re.fullmatch(r"(\d+)\s*[/:\-]\s*(\d+)", t)  # Shift+Copy ID gives <channel>-<message>
        if m:
            return m.group(1), m.group(2)
        m = re.fullmatch(r"<#(\d+)>|(\d+)", t)
        if m:
            return m.group(1) or m.group(2), None
        raise PlatformError(self.name, f"can't read a message from {t!r}; use <channel_id>/<message_id> or a "
                                       f"message link")

    def _user_target(self, target):
        """-> ("user", user id) or ("channel", DM channel id)."""
        t = str(target or "").strip()
        parts = self._link_parts(t)
        if parts:
            if parts[0] == "users" and len(parts) >= 2 and parts[1].isdigit():
                return "user", parts[1]
            if parts[0] == "channels" and len(parts) >= 3 and parts[1] == "@me" and parts[2].isdigit():
                return "channel", parts[2]
            raise PlatformError(self.name, f"can't read a user from link {t!r}")
        m = re.fullmatch(r"<@!?(\d+)>|(\d+)", t)
        if m:
            return "user", m.group(1) or m.group(2)
        uid = self._users.get(t.lstrip("@").lower())
        if uid:
            return "user", uid
        raise PlatformError(self.name, f"unknown Discord user {t!r}; use a user id (usernames work only for people "
                                       f"the bot has seen)")

    def _id_list(self, value, parse):
        items = value if isinstance(value, (list, tuple)) else re.split(r"[\s,]+", str(value or ""))
        return [parse(str(i)) for i in items if str(i).strip()]

    # ------------------------------------------------------------- sending
    @staticmethod
    def _sniff(content):
        head = bytes(content[:16])
        for sig, ext in ((b"\x89PNG", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"GIF8", ".gif"), (b"%PDF", ".pdf")):
            if head.startswith(sig):
                return ext
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return ".webp"
        if head[4:8] == b"ftyp":
            return ".mov" if head[8:10] == b"qt" else ".mp4"
        return ""

    def _load(self, src):
        src = str(src)
        if re.match(r"https?://", src, re.I):
            content = self.http.get(src, raw=True)
            name = os.path.basename(urllib.parse.urlsplit(src).path) or "file"
        else:
            if not os.path.isfile(src):
                raise PlatformError(self.name, f"media file not found: {src}")
            with open(src, "rb") as f:
                content = f.read()
            name = os.path.basename(src)
        if "." not in name:
            name += self._sniff(content)
        return name, content, mimetypes.guess_type(name)[0] or "application/octet-stream"

    def _files(self, media):
        media = list(media or [])
        if len(media) > self.MAX_FILES:
            raise PlatformError(self.name, f"a Discord message holds at most {self.MAX_FILES} attachments "
                                           f"(got {len(media)})")
        return [self._load(m) for m in media]

    def _multipart(self, path, payload, files, attach_to=None):
        holder = payload[attach_to] if attach_to else payload
        holder["attachments"] = [{"id": i, "filename": f[0]} for i, f in enumerate(files)]
        return self._api("POST", path, data={"payload_json": json.dumps(payload)},
                         files={f"files[{i}]": f for i, f in enumerate(files)})

    def _send(self, cid, text, reference=None, media=None):
        files = self._files(media)
        msgs = []
        for i, chunk in enumerate(self._chunks(text, self.TEXT_LIMIT)):
            payload = {"content": chunk} if chunk else {}
            if i == 0 and reference:
                payload["message_reference"] = reference
            if i == 0 and files:
                msgs.append(self._multipart(f"/channels/{cid}/messages", payload, files))
            else:
                msgs.append(self._api("POST", f"/channels/{cid}/messages", json=payload))
        return msgs

    def _result(self, cid, msgs):
        m = msgs[0]
        guild = self._guild_of(cid)
        return Result(id=f"{cid}/{m['id']}", url=f"{self.WEB}/channels/{guild}/{cid}/{m['id']}" if guild else "",
                      raw=m if len(msgs) == 1 else {"messages": msgs})

    def _remember(self, cid, first_id, kind, user=None):
        """Track a channel we sent to so poll() picks up answers after our message."""
        prev = self._track.get(cid)
        after = prev["after"] if prev and int(prev["after"]) < int(first_id) else str(first_id)
        self._track[cid] = {"after": after, "kind": kind, "user": user or (prev or {}).get("user")}

    def _open_dm(self, uid):
        if uid not in self._dm_by_user:
            ch = self._api("POST", "/users/@me/channels", json={"recipient_id": uid})
            self._chan_cache[ch["id"]] = ch
            self._dm_by_user[uid] = ch["id"]
        return self._dm_by_user[uid]

    # ------------------------------------------------------------- actions
    def whoami(self):
        me = self._me()
        d = me.get("discriminator")
        return me["username"] + (f"#{d}" if d and d != "0" else "")

    def post(self, text, target=None, title=None, link=None, media=None):
        cid = self._channel_target(target or self.config.get("default_channel"))
        text = text or ""
        if link:
            text = f"{text}\n\n{link}" if text.strip() else link
        ch = self._channel(cid)
        if ch.get("type") in self.FORUM_TYPES:
            chunks = self._chunks(text, self.TEXT_LIMIT)
            name = (title or text.strip().split("\n", 1)[0] or "Post")[:100]
            payload = {"name": name, "message": {"content": chunks[0]} if chunks[0] else {}}
            files = self._files(media)
            if files:
                thread = self._multipart(f"/channels/{cid}/threads", payload, files, attach_to="message")
            else:
                thread = self._api("POST", f"/channels/{cid}/threads", json=payload)
            tid = thread["id"]
            first = thread.get("message") or {"id": tid}
            for chunk in chunks[1:]:
                self._api("POST", f"/channels/{tid}/messages", json={"content": chunk})
            self._chan_cache[tid] = {"id": tid, "type": 11, "guild_id": ch.get("guild_id"), "parent_id": cid}
            self._remember(tid, first["id"], "thread")
            guild = ch.get("guild_id") or "@me"
            return Result(id=f"{tid}/{first['id']}", url=f"{self.WEB}/channels/{guild}/{tid}", raw=thread)
        if title:
            text = f"**{title}**\n{text}" if text else f"**{title}**"
        msgs = self._send(cid, text, media=media)
        self._remember(cid, msgs[0]["id"], "dm" if ch.get("type") == 1 else "channel", self._recipient(ch))
        return self._result(cid, msgs)

    def comment(self, target, text):
        cid, mid = self._message_target(target)
        ch = self._channel(cid)
        ref = {"message_id": mid, "channel_id": cid, "fail_if_not_exists": False} if mid else None
        msgs = self._send(cid, text, reference=ref)
        self._remember(cid, msgs[0]["id"], "dm" if ch.get("type") == 1 else "channel", self._recipient(ch))
        return self._result(cid, msgs)

    def dm(self, target, text):
        # Discord only delivers bot DMs to users who share a server with the bot and allow DMs from it.
        kind, ident = self._user_target(target)
        if kind == "user":
            uid, cid = ident, self._open_dm(ident)
        else:
            cid = ident
            uid = self._recipient(self._channel(cid))
        msgs = self._send(cid, text)
        self._remember(cid, msgs[0]["id"], "dm", uid)
        return self._result(cid, msgs)

    @staticmethod
    def _recipient(ch):
        if ch.get("type") != 1:
            return None
        rec = ch.get("recipients") or []
        return str(rec[0]["id"]) if rec else None

    # ------------------------------------------------------------- polling
    @staticmethod
    def _timestamp_text(match):
        """<t:N[:style]> -> 'YYYY-MM-DD HH:MM UTC'; values the platform can't convert are left as written."""
        try:
            return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(match.group(1))))
        except (OverflowError, ValueError, OSError):
            return match.group(0)

    @staticmethod
    def _plain(m):
        text = m.get("content") or ""
        names = {u.get("id"): u.get("username") for u in m.get("mentions") or []}
        text = re.sub(r"<@!?(\d+)>", lambda x: "@" + (names.get(x.group(1)) or x.group(1)), text)
        text = re.sub(r"<@&\d+>", "@role", text)
        text = re.sub(r"<#(\d+)>", r"#\1", text)
        text = re.sub(r"<a?(:\w+:)\d+>", r"\1", text)
        text = re.sub(r"<t:(-?\d+)(?::\w)?>", DiscordAdapter._timestamp_text, text)
        extra = [a["url"] for a in m.get("attachments") or [] if a.get("url")]
        extra += [f"[sticker {s.get('name', '')}]" for s in m.get("sticker_items") or []]
        return "\n".join([text.strip()] + extra).strip()

    def _incoming(self, m, cid, bot_id, is_dm, is_thread):
        author = m.get("author") or {}
        if str(author.get("id")) == bot_id or m.get("type", 0) not in self.MESSAGE_TYPES:
            return None
        aid = str(author.get("id", ""))
        if is_dm:
            kind, reply_to = "dm", {"action": "dm", "target": aid}
        else:
            ref = m.get("referenced_message") or {}
            content = m.get("content") or ""
            if str((ref.get("author") or {}).get("id")) == bot_id:
                kind = "reply"
            elif any(str(u.get("id")) == bot_id for u in m.get("mentions") or []) or \
                    re.search(rf"<@!?{bot_id}>", content):
                kind = "mention"
            elif is_thread:
                kind = "comment"  # message in a forum post the bot created
            else:
                return None
            reply_to = {"action": "comment", "target": f"{cid}/{m['id']}"}
        if author.get("username"):
            self._users.pop(author["username"].lower(), None)
            self._users[author["username"].lower()] = aid
        guild = "@me" if is_dm else self._guild_of(cid)
        return Incoming(
            platform=self.name, kind=kind, id=str(m["id"]), author=author.get("username", ""), author_id=aid,
            text=self._plain(m), url=f"{self.WEB}/channels/{guild}/{cid}/{m['id']}" if guild else "",
            thread=cid, ts=self._ts(m["id"]), reply_to=reply_to, raw=m,
        )

    def _fetch(self, cid, after):
        out = []
        for _ in range(5):
            try:
                batch = self._api("GET", f"/channels/{cid}/messages", params={"after": after[cid], "limit": self.PAGE})
            except PlatformError:
                if out:  # keep what was already read; the cursor stays at its last message
                    break
                raise
            if not batch:
                break
            batch = sorted(batch, key=lambda x: int(x["id"]))
            out.extend(batch)
            after[cid] = str(batch[-1]["id"])
            if len(batch) < self.PAGE:
                break
        return out

    def poll(self, state):
        bot_id = str(self._me()["id"])
        after = state.setdefault("after", {})          # channel id -> last seen message id
        dms = state.setdefault("dm_channels", {})      # DM channel id -> user id
        chans = state.setdefault("channels", [])       # guild channels/threads the bot sent to
        threads = state.setdefault("threads", [])      # forum posts created by the bot
        users = state.setdefault("users", {})
        users.update(self._users)
        for k in list(users)[:-2000]:
            del users[k]
        self._users = users
        watch = self._id_list(self.config.get("watch_channels"), self._channel_target)
        dm_users = self._id_list(self.config.get("dm_users"), lambda v: self._user_target(v)[1])

        for uid in dm_users:
            if uid not in dms.values():
                dms[self._open_dm(uid)] = uid
        for cid, info in self._track.items():
            if info["kind"] == "dm":
                dms[cid] = info["user"] or dms.get(cid) or ""
            else:
                if cid in chans:
                    chans.remove(cid)
                chans.append(cid)
                if info["kind"] == "thread" and cid not in threads:
                    threads.append(cid)
            after.setdefault(cid, info["after"])
        self._track = {}
        while len(chans) > self.TRACK_MAX:
            old = chans.pop(0)
            if old in threads:
                threads.remove(old)
            if old not in watch and old not in dms:
                after.pop(old, None)
        for old in [c for c, u in dms.items() if u not in dm_users][:-self.TRACK_MAX]:
            dms.pop(old)
            after.pop(old, None)
        for cid, uid in dms.items():
            if uid:
                self._dm_by_user[uid] = cid

        out, errors = [], []
        for cid in dict.fromkeys(watch + chans + list(dms)):
            if cid not in after:
                after[cid] = self._snowflake_now()  # newly watched: start from now
                continue
            try:
                msgs = self._fetch(cid, after)
            except PlatformError as e:
                if e.status in (403, 404) and cid not in watch:
                    # channel deleted or no longer visible: stop tracking it
                    for lst in (chans, threads):
                        if cid in lst:
                            lst.remove(cid)
                    dms.pop(cid, None)
                    after.pop(cid, None)
                    logging.getLogger("social_bridge").warning("discord: stopped polling %s: %s", cid, e)
                else:
                    errors.append(e)
                continue
            if msgs and cid in dms:
                dms[cid] = dms.pop(cid)  # most recently active DM channels are kept longest
            for m in msgs:
                try:
                    item = self._incoming(m, cid, bot_id, cid in dms, cid in threads)
                except Exception as e:  # noqa: BLE001 - the cursor is already past m; keep the rest of the batch
                    logging.getLogger("social_bridge").warning("discord: skipped message %s in %s: %r",
                                                               m.get("id"), cid, e)
                    continue
                if item:
                    out.append(item)
        if errors and not out:
            raise errors[0]
        for e in errors:
            logging.getLogger("social_bridge").warning("discord poll: %s", e)
        out.sort(key=lambda i: i.ts)
        return out


# ============================================================================
# social_bridge/adapters/linkedin.py — LinkedIn (REST API): member or Page posts with images, video, a document or a link card, and comments.
# ============================================================================
import html
import json
import mimetypes
import os
import re
import time
import urllib.parse



@register
class LinkedInAdapter(Adapter):
    name = "linkedin"
    label = "LinkedIn"
    actions = ("post", "comment")  # LinkedIn's messaging API is limited to approved partners
    # Reading comments/mentions needs r_organization_social, which only covers Pages, so member
    # accounts get poll_interval 0 per instance (see __init__).
    poll_interval = 600
    config_keys = {
        "access_token": "OAuth 2.0 access token (valid 60 days): linkedin.com/developers/apps -> Create app -> "
                        "Products: request 'Share on LinkedIn' and 'Sign In with LinkedIn using OpenID Connect' "
                        "(for a Page also 'Community Management API') -> then linkedin.com/developers/tools/oauth/"
                        "token-generator -> pick the app, scopes openid profile w_member_social (Page: add "
                        "w_organization_social r_organization_social) -> Request access token",
        "author_urn": "(optional) who posts and comments: default urn:li:person:<id> of the token's member (from "
                      "/v2/userinfo); set urn:li:organization:<id> to act as a Page you administer (the id is in "
                      "the Page admin URL linkedin.com/company/<id>/admin). Polling only works for a Page",
        "linkedin_version": "(optional) LinkedIn-Version header YYYYMM (default: two months before the current "
                            "month, stepping back automatically if LinkedIn reports it as nonexistent)",
        "refresh_token": "(optional) refresh token, only issued to apps with programmatic refresh enabled (shown "
                         "next to the access token in the token generator); the access token is renewed from it",
        "client_id": "(optional, with refresh_token) app -> Auth tab -> Client ID",
        "client_secret": "(optional, with refresh_token) app -> Auth tab -> Primary Client Secret",
        "visibility": "(optional) PUBLIC | CONNECTIONS (default PUBLIC; CONNECTIONS is for member posts only)",
        "poll_posts": "(optional) how many recent Page posts are checked for new comments (default 5)",
        "poll_mentions": "(optional) false to skip polling Page @mentions (default true)",
    }
    target_help = {
        "post": "omit to post as author_urn (default: you); or urn:li:organization:<id>, a numeric organization id "
                "or a linkedin.com/company/<id or name> URL to post as that Page",
        "comment": "post URN (urn:li:activity:.., urn:li:share:.., urn:li:ugcPost:..) or post URL "
                   "(linkedin.com/feed/update/urn:li:activity:<id>/ or linkedin.com/posts/<slug>-activity-<id>-..); "
                   "a comment URN urn:li:comment:(urn:li:activity:<id>,<id>) or a URL with ?commentUrn=.. replies "
                   "in that comment's thread",
    }

    API = "https://api.linkedin.com"
    REST = API + "/rest"
    WEB = "https://www.linkedin.com"
    TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
    VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".wmv", ".flv", ".3gp", ".mpeg", ".mpg"}
    DOC_EXT = {".pdf", ".doc", ".docx", ".ppt", ".pptx"}
    RESERVED_RE = r"[\\|{}@\[\]()<>#*_~]"   # Little Text Format control characters in post commentary

    def __init__(self, config, http=None):
        super().__init__(config, http)
        self._tok = None
        self._exp = 0.0
        self._rt = None
        self._ver = None
        self._ver_steps = 0
        self._author_urn = None
        self._ui = None
        if not self._org_like(self.config.get("author_urn")):
            self.poll_interval = 0

    # ------------------------------------------------------------- config helpers
    @staticmethod
    def _org_like(value):
        v = str(value or "").strip()
        return bool(v) and ("organization" in v or v.isdigit() or bool(re.search(r"/(company|showcase)/", v)))

    def _flag(self, key, default=True):
        v = self.config.get(key)
        if v is None or v == "":
            return default
        if isinstance(v, str):
            return v.strip().lower() not in ("0", "false", "no", "off")
        return bool(v)

    def _int(self, key, default):
        try:
            return max(1, int(self.config.get(key) or default))
        except (TypeError, ValueError):
            return default

    def _version(self):
        if self._ver is None:
            v = str(self.config.get("linkedin_version") or "").strip()
            if not v:
                t = time.gmtime()
                y, m = (t.tm_year, t.tm_mon - 2) if t.tm_mon > 2 else (t.tm_year - 1, t.tm_mon + 10)
                v = f"{y}{m:02d}"
            self._ver = v
        return self._ver

    @staticmethod
    def _prev_version(v):
        y, m = int(v[:4]), int(v[4:6]) - 1
        return f"{y - 1}12" if m < 1 else f"{y}{m:02d}"

    @staticmethod
    def _q(urn):
        return urllib.parse.quote(str(urn), safe="")

    # ------------------------------------------------------------- auth / transport
    def _can_refresh(self):
        return all(self.config.get(k) for k in ("refresh_token", "client_id", "client_secret"))

    def _refresh(self):
        rt, cid, secret = self.need("refresh_token", "client_id", "client_secret")
        res = self.http.post(self.TOKEN_URL, data={"grant_type": "refresh_token", "refresh_token": self._rt or rt,
                                                   "client_id": cid, "client_secret": secret})
        if not isinstance(res, dict) or not res.get("access_token"):
            raise PlatformError(self.name, "token refresh returned no access_token", body=res)
        self._tok = res["access_token"]
        self._exp = time.time() + float(res["expires_in"]) if res.get("expires_in") else 0.0
        self._rt = res.get("refresh_token") or self._rt
        return self._tok

    def _token(self):
        if self._tok and self._exp and time.time() > self._exp - 300 and self._can_refresh():
            self._refresh()
        if not self._tok:
            if self.config.get("access_token"):
                self._tok = self.config["access_token"]
            elif self._can_refresh():
                self._refresh()
            else:
                self.need("access_token")
        return self._tok

    @staticmethod
    def _delay(headers, attempt):
        try:
            return min(float(headers.get("retry-after")), 120.0)
        except (TypeError, ValueError):
            return min(2.0 ** attempt, 60.0)

    def _send(self, method, url, *, params=None, json_body=None, data=None, headers=None, rest=True, auth=True):
        """One request -> (lower-cased response headers, parsed body). Retries 429/5xx, renews the token once on
        401 and, when no linkedin_version is configured, steps back a month on NONEXISTENT_VERSION."""
        attempt, renewed = 0, False
        while True:
            hdrs = {"User-Agent": self.http.user_agent}
            if auth:
                hdrs["Authorization"] = f"Bearer {self._token()}"
            if rest:
                hdrs.update({"LinkedIn-Version": self._version(), "X-Restli-Protocol-Version": "2.0.0"})
            hdrs.update(headers or {})
            status, rh, body = self.http._send(method, url, params=params, json_body=json_body, data=data,
                                               headers=hdrs)
            rh = {str(k).lower(): v for k, v in (rh or {}).items()}
            text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body or "")
            if (status == 429 or status >= 500) and attempt < self.http.max_retries:
                attempt += 1
                self.http.sleep(self._delay(rh, attempt))
                continue
            if status == 401 and auth and not renewed and self._can_refresh():
                renewed = True
                self._refresh()
                continue
            if rest and status in (400, 426) and "NONEXISTENT_VERSION" in text and \
                    not self.config.get("linkedin_version") and self._ver_steps < 12:
                self._ver_steps += 1
                self._ver = self._prev_version(self._version())
                continue
            try:
                parsed = json.loads(text) if text.strip() else {}
            except ValueError:
                parsed = text
            if status >= 400:
                where = url.split("?", 1)[0]   # upload URLs carry signatures in the query
                raise PlatformError(self.name, f"HTTP {status} on {method} {where}: {text[:500]}", status, parsed)
            return rh, parsed

    def _api(self, method, url, **kw):
        res = self._send(method, url, **kw)[1]
        return res if isinstance(res, dict) else {}

    # ------------------------------------------------------------- identity
    def _userinfo(self):
        if self._ui is None:
            self._ui = self._api("GET", f"{self.API}/v2/userinfo", rest=False)
        return self._ui

    def _author(self):
        if self._author_urn is None:
            cfg = self.config.get("author_urn")
            if cfg:
                self._author_urn = self._entity(cfg)
            else:
                sub = self._userinfo().get("sub")
                if not sub:
                    raise PlatformError(self.name, "/v2/userinfo returned no member id (token needs openid profile)")
                self._author_urn = f"urn:li:person:{sub}"
        return self._author_urn

    def _entity(self, value):
        """Member/organization URN, numeric organization id or company/showcase Page URL -> URN."""
        v = urllib.parse.unquote(str(value).strip())
        m = re.search(r"urn:li:(person|organization|organizationBrand):([\w-]+)", v)
        if m:
            return f"urn:li:{m.group(1)}:{m.group(2)}"
        if v.isdigit():
            return f"urn:li:organization:{v}"
        m = re.search(r"linkedin\.com/(?:company|showcase)/([^/?#]+)", v, re.I)
        if m:
            ref = m.group(1)
            if ref.isdigit():
                return f"urn:li:organization:{ref}"
            res = self._api("GET", f"{self.REST}/organizations", params={"q": "vanityName", "vanityName": ref})
            els = res.get("elements") or []
            if els and els[0].get("id"):
                return f"urn:li:organization:{els[0]['id']}"
            raise PlatformError(self.name, f"no organization found for {ref!r}; pass urn:li:organization:<id>")
        raise PlatformError(self.name, f"can't read an organization or member URN from {value!r}")

    # ------------------------------------------------------------- text
    @classmethod
    def _little(cls, text):
        """Plain text -> Little Text Format (posts' commentary): escape control characters, keep #hashtags."""
        def esc(s):
            return re.sub(cls.RESERVED_RE, lambda m: "\\" + m.group(0), s)

        def sub(m):
            if m.group(1):
                return "{hashtag|\\#|" + esc(m.group(1)) + "}"
            return "\\" + m.group(0)
        return re.sub(r"(?<![\w#])#(\w+)|" + cls.RESERVED_RE, sub, text or "")

    @staticmethod
    def _plain(text):
        """Little Text Format -> plain text."""
        t = re.sub(r"@\[((?:\\.|[^\]])*)\]\([^)]*\)", r"@\1", text or "")
        t = re.sub(r"\{hashtag\|\\?#\|((?:\\.|[^}])*)\}", r"#\1", t)
        return re.sub(r"\\(.)", r"\1", t).strip()

    def _page_meta(self, link):
        """Best-effort og:title / og:description of a link, for the article card."""
        try:
            raw = self.http.get(link, raw=True, headers={"Accept": "text/html"})
        except Exception:  # noqa: BLE001 - the card still works with the URL as title
            return {}
        page = raw[:500000].decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        out = {}
        tags = re.findall(r"<meta\b[^>]*>", page, re.I)
        for key in ("title", "description"):
            for tag in tags:
                if re.search(rf"""(?:property|name)\s*=\s*["'](?:og:|twitter:)?{key}["']""", tag, re.I):
                    m = re.search(r"""content\s*=\s*(["'])(.*?)\1""", tag, re.I | re.S)
                    if m and m.group(2).strip():
                        out[key] = html.unescape(m.group(2)).strip()
                        break
        if "title" not in out:
            m = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
            if m and m.group(1).strip():
                out["title"] = html.unescape(m.group(1)).strip()
        return out

    # ------------------------------------------------------------- media
    @staticmethod
    def _is_url(m):
        return bool(re.match(r"https?://", m, re.I))

    def _kind(self, m):
        path = urllib.parse.urlsplit(m).path if self._is_url(m) else m
        ext = os.path.splitext(path)[1].lower()
        if ext in self.DOC_EXT:
            return "document"
        if ext in self.VIDEO_EXT or (mimetypes.guess_type(path)[0] or "").startswith("video/"):
            return "video"
        return "image"

    def _read(self, m):
        if self._is_url(m):
            return self.http.get(m, raw=True)
        if not os.path.isfile(m):
            raise PlatformError(self.name, f"media file not found: {m}")
        with open(m, "rb") as f:
            return f.read()

    def _put(self, url, data):
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        own_host = host == "linkedin.com" or host.endswith(".linkedin.com")
        return self._send("PUT", url, data=data, headers={"Content-Type": "application/octet-stream"},
                          rest=False, auth=own_host)[0]

    def _upload(self, m, kind, owner):
        data = self._read(m)
        if kind == "video":
            return self._upload_video(data, owner)
        coll, key = ("images", "image") if kind == "image" else ("documents", "document")
        res = self._api("POST", f"{self.REST}/{coll}", params={"action": "initializeUpload"},
                        json_body={"initializeUploadRequest": {"owner": owner}})
        v = res.get("value") or {}
        if not v.get("uploadUrl") or not v.get(key):
            raise PlatformError(self.name, f"{coll} initializeUpload returned no uploadUrl", body=res)
        self._put(v["uploadUrl"], data)
        return v[key]

    def _upload_video(self, data, owner):
        res = self._api("POST", f"{self.REST}/videos", params={"action": "initializeUpload"}, json_body={
            "initializeUploadRequest": {"owner": owner, "fileSizeBytes": len(data), "uploadCaptions": False,
                                        "uploadThumbnail": False}})
        v = res.get("value") or {}
        urn, parts = v.get("video"), v.get("uploadInstructions") or []
        if not urn or not parts:
            raise PlatformError(self.name, "videos initializeUpload returned no upload instructions", body=res)
        etags = []
        for p in parts:
            first, last = int(p.get("firstByte") or 0), int(p.get("lastByte", len(data) - 1))
            etags.append(self._put(p["uploadUrl"], data[first:last + 1]).get("etag", ""))
        self._api("POST", f"{self.REST}/videos", params={"action": "finalizeUpload"}, json_body={
            "finalizeUploadRequest": {"video": urn, "uploadToken": v.get("uploadToken") or "",
                                      "uploadedPartIds": etags}})
        self._wait_video(urn)
        return urn

    def _wait_video(self, urn, timeout=600):
        waited, delay = 0.0, 3.0
        while True:
            status = str(self._api("GET", f"{self.REST}/videos/{self._q(urn)}").get("status") or "").upper()
            if status in ("AVAILABLE", ""):
                return
            if "FAIL" in status:
                raise PlatformError(self.name, f"video {urn} processing failed ({status})")
            if waited >= timeout:
                raise PlatformError(self.name, f"video {urn} still {status} after {int(waited)}s")
            self.http.sleep(delay)
            waited += delay
            delay = min(delay * 2, 20.0)

    # ------------------------------------------------------------- targets
    def _comment_target(self, target):
        """-> (post URN, parent comment URN or None)."""
        t = str(target).strip()
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(t).query) if self._is_url(t) else {}
        for c in query.get("commentUrn", []) + query.get("dashCommentUrn", []) + [urllib.parse.unquote(t)]:
            m = re.search(r"urn:li:comment:\((?:urn:li:)?(activity|share|ugcPost):(\d+),(\d+)\)", c)
            if m:
                obj = f"urn:li:{m.group(1)}:{m.group(2)}"
                return obj, f"urn:li:comment:({obj},{m.group(3)})"
            m = re.search(r"urn:li:fsd_comment:\((\d+),urn:li:(activity|share|ugcPost):(\d+)\)", c)
            if m:
                obj = f"urn:li:{m.group(2)}:{m.group(3)}"
                return obj, f"urn:li:comment:({obj},{m.group(1)})"
        u = urllib.parse.unquote(t)
        m = re.search(r"urn:li:(activity|share|ugcPost):(\d+)", u) or \
            re.search(r"(activity|share|ugcPost)-(\d{8,})", u)
        if m:
            return f"urn:li:{m.group(1)}:{m.group(2)}", None
        if u.isdigit():
            return f"urn:li:activity:{u}", None
        raise PlatformError(self.name, f"can't read a post or comment URN from {t!r}")

    @staticmethod
    def _curn(c, obj):
        return c.get("commentUrn") or c.get("$URN") or f"urn:li:comment:({c.get('object') or obj},{c.get('id')})"

    def _comment_url(self, obj, curn):
        return f"{self.WEB}/feed/update/{obj}/?commentUrn={self._q(curn)}"

    # ------------------------------------------------------------- actions
    def whoami(self):
        author = self._author()
        if author.startswith("urn:li:organization:"):
            try:
                org = self._api("GET", f"{self.REST}/organizations/{author.rsplit(':', 1)[1]}")
            except PlatformError as e:
                if e.status != 403:
                    raise
                return author
            return f"{org.get('localizedName') or author} ({author})"
        ui = self._userinfo()
        return ui.get("name") or " ".join(x for x in (ui.get("given_name"), ui.get("family_name")) if x) or author

    def post(self, text, target=None, title=None, link=None, media=None):
        author = self._entity(target) if target else self._author()
        text = (text or "").strip()
        media = [str(m).strip() for m in (media or []) if m]
        kinds = [self._kind(m) for m in media]
        if len(media) > 1 and set(kinds) != {"image"}:
            raise PlatformError(self.name, "a LinkedIn post holds several images, or a single video or document")
        content = None
        if media:
            urns = [self._upload(m, k, author) for m, k in zip(media, kinds)]
            if kinds[0] == "image":
                if title:
                    text = f"{title}\n\n{text}".strip()
                content = {"media": {"id": urns[0]}} if len(urns) == 1 else \
                    {"multiImage": {"images": [{"id": u} for u in urns]}}
            else:
                name = os.path.basename(urllib.parse.urlsplit(media[0]).path if self._is_url(media[0]) else media[0])
                content = {"media": {"id": urns[0], "title": title or name}}
            if link and link not in text:
                text = f"{text}\n\n{link}".strip()
        elif link:
            meta = self._page_meta(link)
            content = {"article": {"source": link, "title": title or meta.get("title") or link}}
            if meta.get("description"):
                content["article"]["description"] = meta["description"]
        elif title:
            text = f"{title}\n\n{text}".strip()
        body = {
            "author": author,
            "commentary": self._little(text),
            "visibility": str(self.config.get("visibility") or "PUBLIC").upper(),
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                             "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        if content:
            body["content"] = content
        headers, res = self._send("POST", f"{self.REST}/posts", json_body=body)
        urn = urllib.parse.unquote(headers.get("x-restli-id") or headers.get("x-linkedin-id") or
                                   (res.get("id") if isinstance(res, dict) else "") or "")
        return Result(id=urn, url=f"{self.WEB}/feed/update/{urn}/" if urn else "",
                      raw={"id": urn, **(res if isinstance(res, dict) else {})})

    def comment(self, target, text):
        obj, parent = self._comment_target(target)
        body = {"actor": self._author(), "object": obj, "message": {"text": text}}
        if parent:
            body["parentComment"] = parent
        headers, res = self._send("POST", f"{self.REST}/socialActions/{self._q(parent or obj)}/comments",
                                  json_body=body)
        res = res if isinstance(res, dict) else {}
        urn = res.get("commentUrn") or res.get("$URN") or ""
        if not urn:
            rid = urllib.parse.unquote(headers.get("x-restli-id") or str(res.get("id") or ""))
            urn = rid if rid.startswith("urn:") else (f"urn:li:comment:({obj},{rid})" if rid else "")
        return Result(id=urn, url=self._comment_url(obj, urn) if urn else f"{self.WEB}/feed/update/{obj}/", raw=res)

    # ------------------------------------------------------------- polling (Pages)
    def _comments(self, urn):
        res = self._api("GET", f"{self.REST}/socialActions/{self._q(urn)}/comments", params={"count": 100})
        return [c for c in (res.get("elements") or []) if isinstance(c, dict)]

    def _comment_item(self, c, kind, post, reply_target):
        curn = self._curn(c, post)
        actor = str(c.get("actor") or (c.get("created") or {}).get("actor") or "")
        ms = int((c.get("created") or {}).get("time") or 0)
        return Incoming(platform=self.name, kind=kind, id=curn, author=actor, author_id=actor,
                        text=str((c.get("message") or {}).get("text") or "").strip(),
                        url=self._comment_url(c.get("object") or post, curn), thread=post, ts=ms / 1000.0,
                        reply_to={"action": "comment", "target": reply_target}, raw=c)

    def _mention(self, n, author):
        act = str(n.get("generatedActivity") or "")
        m = re.search(r"urn:li:comment:\((urn:li:\w+:\d+),(\d+)\)", act)
        if m:
            c = self._api("GET", f"{self.REST}/socialActions/{self._q(m.group(1))}/comments/{m.group(2)}")
            if not c or c.get("actor") == author:
                return None
            c.setdefault("commentUrn", act)
            return self._comment_item(c, "mention", str(n.get("sourcePost") or m.group(1)),
                                      c.get("parentComment") or act)
        if re.match(r"urn:li:(share|ugcPost|activity):\d+$", act):
            p = self._api("GET", f"{self.REST}/posts/{self._q(act)}")
            if not p or p.get("author") == author:
                return None
            ms = int(p.get("publishedAt") or p.get("createdAt") or n.get("lastModifiedAt") or 0)
            return Incoming(platform=self.name, kind="mention", id=act, author=str(p.get("author") or ""),
                            author_id=str(p.get("author") or ""), text=self._plain(p.get("commentary")),
                            url=f"{self.WEB}/feed/update/{act}/", thread=act, ts=ms / 1000.0,
                            reply_to={"action": "comment", "target": act}, raw=p)
        return None

    def poll(self, state):
        author = self._author()
        if not author.startswith("urn:li:organization:"):
            return []
        since = int(state.get("since_ms") or 0)
        newest, counts, new_counts = since, state.get("counts") or {}, {}
        pending, new_pending = state.get("pending") or {}, {}   # comment URN -> cursor when its replies were deferred
        found, known, nested_budget = {}, set(), 25   # known: every comment URN listed this round

        def add(item, cursor=True, floor=None):
            nonlocal newest
            ms = int(item.ts * 1000)
            if cursor:
                newest = max(newest, ms)
                lo = since if floor is None else floor
                if lo and ms and ms < lo:
                    return
            found.setdefault(item.id, item)

        res = self._api("GET", f"{self.REST}/posts", params={
            "author": author, "q": "author", "count": self._int("poll_posts", 5), "sortBy": "LAST_MODIFIED"})
        for p in res.get("elements") or []:
            post = str(p.get("id") or "")
            if not post:
                continue
            for c in self._comments(post):
                curn, mine = self._curn(c, post), c.get("actor") == author
                known.add(curn)
                if not mine:
                    add(self._comment_item(c, "comment", post, curn))
                summary = c.get("commentsSummary") or {}
                total = summary.get("aggregatedTotalComments", summary.get("totalFirstLevelComments"))
                if total == 0 or (total is not None and counts.get(curn) == total and curn not in pending):
                    new_counts[curn] = total
                    continue
                if nested_budget <= 0:   # replies not fetched: keep the old count so the next poll fetches them
                    if curn in counts:
                        new_counts[curn] = counts[curn]
                    if since:
                        new_pending[curn] = int(pending.get(curn, since))
                    continue
                nested_budget -= 1
                replies = self._comments(curn)
                if total is not None:
                    new_counts[curn] = total
                floor = pending.get(curn)
                ours = mine or any(r.get("actor") == author for r in replies)
                for r in replies:
                    known.add(self._curn(r, post))
                    if r.get("actor") != author:
                        add(self._comment_item(r, "reply" if ours else "comment", post, curn),
                            floor=None if floor is None else int(floor))

        if self._flag("poll_mentions"):
            now_ms = int(time.time() * 1000)
            start = int(state.get("mentions_ms") or now_ms - 7 * 86400000) - 3600000   # late-indexed overlap
            url = (f"{self.REST}/organizationalEntityNotifications?q=criteria"
                   f"&actions=List(SHARE_MENTION,COMMENT_MENTION)&organizationalEntity={self._q(author)}"
                   f"&timeRange=(start:{start},end:{now_ms})&count=50")
            for n in self._api("GET", url).get("elements") or []:
                if str(n.get("generatedActivity") or "") in known:
                    continue   # a comment on our own post, already handled above
                try:
                    item = self._mention(n, author)
                except PlatformError:
                    continue   # the mentioning post/comment is not readable (deleted or restricted)
                if item:
                    add(item, cursor=False)   # the notification time window is the cursor here
            state["mentions_ms"] = now_ms

        state["since_ms"] = newest
        state["counts"] = new_counts
        state["pending"] = new_pending
        return sorted(found.values(), key=lambda i: i.ts)


# ============================================================================
# social_bridge/adapters/tumblr.py — Tumblr (API v2, OAuth 1.0a user tokens; posts are created in the Neue Post Format).
# ============================================================================
import html
import json
import mimetypes
import os
import re
import urllib.parse



@register
class TumblrAdapter(Adapter):
    name = "tumblr"
    label = "Tumblr"
    actions = ("post", "comment")
    poll_interval = 120  # new API consumers are limited to 1,000 requests/hour and 5,000/day
    config_keys = {
        "consumer_key": "www.tumblr.com/oauth/apps -> 'Register application' (any website and default callback "
                        "URL, e.g. https://localhost/) -> the app's 'OAuth Consumer Key'",
        "consumer_secret": "same app on www.tumblr.com/oauth/apps -> 'Show secret key' -> Secret Key",
        "oauth_token": "api.tumblr.com/console -> enter the consumer key and secret -> Authenticate -> Allow -> "
                       "'Show keys' -> Token",
        "oauth_token_secret": "same 'Show keys' panel on api.tumblr.com/console -> Token Secret",
        "blog": "(optional) blog to act as: name (myblog), myblog.tumblr.com, custom domain or blog URL "
                "(default: the account's primary blog)",
        "post_state": "(optional) state for new posts and reblogs: published | queue | draft | private "
                      "(default published)",
        "tags": "(optional) comma-separated tags added to every new post and reblog",
    }
    target_help = {
        "post": "omit to post to your blog; or the name of another blog you can post to (secondary or group blog)",
        "comment": "post URL (https://www.tumblr.com/<blog>/<id>, https://<blog>.tumblr.com/post/<id>/..., custom "
                   "domain /post/<id>) or <blog>/<post_id>. Tumblr's API has no reply endpoint, so this reblogs the "
                   "post to your blog with your text added; write @blogname in the text to mention a blog",
    }

    API = "https://api.tumblr.com/v2"
    # activity-feed types we surface -> Incoming kind (also sent as the endpoint's types[] filter)
    KINDS = {"reply": "comment", "reblog_with_content": "comment", "conversational_note": "reply",
             "mention_in_reply": "mention", "mention_in_post": "mention"}
    PAGES = 5  # notification pages fetched per poll
    # types whose content is a post on the sender's blog (post_id) rather than a note on target_post_id
    ON_SENDER = ("reblog_with_content", "mention_in_post")
    MENTION = re.compile(r"(?<![\w@./])@([A-Za-z0-9][A-Za-z0-9-]{0,31})")

    def __init__(self, config, http=None):
        super().__init__(config, http)
        self._blog = None   # {"name", "uuid"} of the blog we act as
        self._own = set()   # lower-cased name and uuid of every blog on the account
        self._uuids = {}    # blog name -> uuid, for @mentions

    # ------------------------------------------------------------- transport
    def _api(self, method, path, params=None, **kw):
        ck, cs, tok, tsec = self.need("consumer_key", "consumer_secret", "oauth_token", "oauth_token_secret")
        url = self.API + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True, safe="~", quote_via=urllib.parse.quote)
        auth = oauth1_header(method, url, consumer_key=ck, consumer_secret=cs, token=tok, token_secret=tsec)
        res = self.http.request(method, url, headers={"Authorization": auth}, **kw)
        return res.get("response", res) if isinstance(res, dict) else res

    # ------------------------------------------------------------- helpers
    def _ident(self, value):
        """Blog name / hostname / blog URL / uuid -> API blog identifier (name.tumblr.com, custom domain, t:uuid)."""
        v = str(value or "").strip()
        if re.match(r"(?i)https?://", v):
            parts = urllib.parse.urlsplit(v)
            host = parts.netloc.lower().split(":")[0]
            if host in ("tumblr.com", "www.tumblr.com"):
                seg = [s for s in parts.path.split("/") if s]
                while seg and seg[0] in ("blog", "view"):
                    seg = seg[1:]
                v = seg[0] if seg else ""
            else:
                v = host
        v = v.strip("/").lstrip("@")
        if v.startswith("t:"):
            return v
        v = v.lower()
        if not v:
            raise PlatformError(self.name, f"can't read a blog from {value!r}")
        return v if "." in v else f"{v}.tumblr.com"

    def _mine(self):
        if self._blog is None:
            user = self._api("GET", "/user/info").get("user") or {}
            blogs = user.get("blogs") or []
            want = self.config.get("blog")
            if want:
                ident = self._ident(want)
                pick = next((b for b in blogs if ident in self._blog_idents(b)), None)
                if pick is None:
                    names = ", ".join(b.get("name", "") for b in blogs) or "none"
                    raise PlatformError(self.name, f"blog {want!r} is not one of this account's blogs ({names})")
            else:
                pick = next((b for b in blogs if b.get("primary")), blogs[0] if blogs else None)
                if pick is None:
                    raise PlatformError(self.name, "this account has no blogs")
            self._own = {(b.get("name") or "").lower() for b in blogs} | {b.get("uuid") for b in blogs}
            self._own.discard("")
            self._own.discard(None)
            self._blog = {"name": pick["name"], "uuid": pick.get("uuid") or ""}
        return self._blog

    @staticmethod
    def _blog_idents(b):
        name = (b.get("name") or "").lower()
        host = urllib.parse.urlsplit(b.get("url") or "").netloc.lower()
        return {f"{name}.tumblr.com", b.get("uuid"), host}

    def _my_ident(self):
        return self._ident(self.config.get("blog") or self._mine()["name"])

    def _post_url(self, ident, pid):
        if ident.endswith(".tumblr.com"):
            return f"https://www.tumblr.com/{ident[:-len('.tumblr.com')]}/{pid}"
        if ident.startswith("t:"):
            if self._blog and self._blog["uuid"] == ident:
                return f"https://www.tumblr.com/{self._blog['name']}/{pid}"
            return ""
        return f"https://{ident}/post/{pid}"

    def _post_ref(self, target):
        """Post URL or blog/post_id -> (blog identifier, post id)."""
        t = str(target).strip()
        if re.match(r"(?i)https?://", t):
            parts = urllib.parse.urlsplit(t)
            host = parts.netloc.lower().split(":")[0]
            seg = [s for s in parts.path.split("/") if s]
            if host in ("tumblr.com", "www.tumblr.com"):
                while seg and seg[0] in ("blog", "view"):
                    seg = seg[1:]
                if len(seg) >= 3 and seg[1] == "post":
                    seg = [seg[0]] + seg[2:]
                if len(seg) >= 2 and seg[1].isdigit():
                    return self._ident(seg[0]), seg[1]
            else:
                if "post" in seg:
                    i = seg.index("post")
                    if i + 1 < len(seg) and seg[i + 1].isdigit():
                        return self._ident(host), seg[i + 1]
                if seg and seg[0].isdigit():
                    return self._ident(host), seg[0]
        else:
            m = re.match(r"^@?([^/\s]+)/(?:post/)?(\d+)/?$", t)
            if m:
                return self._ident(m.group(1)), m.group(2)
        raise PlatformError(self.name, f"can't read a post from {target!r}: use a post URL or <blog>/<post_id>")

    def _blog_uuid(self, name):
        key = name.lower()
        if key not in self._uuids:
            try:
                info = self._api("GET", f"/blog/{key}.tumblr.com/info")
                self._uuids[key] = ((info.get("blog") if isinstance(info, dict) else None) or {}).get("uuid") or ""
            except PlatformError:
                self._uuids[key] = ""
        return self._uuids[key]

    def _text_blocks(self, text):
        """Paragraphs -> NPF text blocks; @blogname becomes a mention when the blog exists."""
        blocks = []
        for para in re.split(r"\n\s*\n", (text or "").strip()):
            para = para.strip()
            if not para:
                continue
            block = {"type": "text", "text": para}
            fmt = []
            for m in self.MENTION.finditer(para):
                uuid = self._blog_uuid(m.group(1))
                if uuid:
                    fmt.append({"start": m.start(), "end": m.end(), "type": "mention", "blog": {"uuid": uuid}})
            if fmt:
                block["formatting"] = fmt
            blocks.append(block)
        return blocks

    def _media_blocks(self, media):
        """Image URLs are referenced directly; local files and other remote media are uploaded as multipart parts."""
        blocks, files = [], {}
        for i, item in enumerate(media or []):
            src = str(item).strip()
            remote = bool(re.match(r"(?i)https?://", src))
            path = urllib.parse.urlsplit(src).path if remote else src
            mime = mimetypes.guess_type(path)[0] or ""
            kind = mime.split("/")[0] if mime else ("image" if remote else "")
            if kind not in ("image", "video", "audio"):
                raise PlatformError(self.name, f"unsupported media {src!r}: Tumblr posts take images, video or audio")
            if remote and kind == "image":
                blocks.append({"type": "image", "media": [{"url": src}]})
                continue
            if remote:
                data = self.http.get(src, raw=True)
            else:
                if not os.path.isfile(src):
                    raise PlatformError(self.name, f"media file not found: {src}")
                with open(src, "rb") as f:
                    data = f.read()
            ident = f"media{i}"
            obj = {"type": mime, "identifier": ident}
            blocks.append({"type": kind, "media": [obj] if kind == "image" else obj})
            files[ident] = (os.path.basename(path) or ident, data, mime)
        return blocks, files

    def _create(self, ident, content, files=None, **extra):
        body = {"content": content}
        if self.config.get("post_state"):
            body["state"] = self.config["post_state"]
        if self.config.get("tags"):
            body["tags"] = self.config["tags"]
        body.update(extra)
        if files:
            parts = {"json": (None, json.dumps(body), "application/json")}
            parts.update(files)
            res = self._api("POST", f"/blog/{ident}/posts", files=parts)
        else:
            res = self._api("POST", f"/blog/{ident}/posts", json=body)
        pid = str(res.get("id_string") or res.get("id") or "") if isinstance(res, dict) else ""
        return Result(id=pid, url=self._post_url(ident, pid) if pid else "", raw=res if isinstance(res, dict) else {})

    def _fetch_post(self, ident, pid):
        res = self._api("GET", f"/blog/{ident}/posts", params={"id": pid, "npf": "true"})
        posts = res.get("posts") or []
        if not posts:
            raise PlatformError(self.name, f"post {pid} on {ident} not found")
        return res, posts[0]

    def _post_text(self, blog, pid):
        try:
            _, p = self._fetch_post(self._ident(blog), pid)
        except PlatformError:
            return ""
        return "\n\n".join(b.get("text", "") for b in p.get("content") or [] if b.get("type") == "text")

    @staticmethod
    def _tumblr_plain(text):
        text = re.sub(r"<br\s*/?>", "\n", text or "")
        text = re.sub(r"</p>\s*<p>", "\n\n", text)
        return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()

    # ------------------------------------------------------------- actions
    def whoami(self):
        return self._mine()["name"]

    def post(self, text, target=None, title=None, link=None, media=None):
        ident = self._ident(target) if target else self._my_ident()
        content = []
        if title:
            content.append({"type": "text", "subtype": "heading1", "text": title.strip()})
        mblocks, files = self._media_blocks(media)
        content += mblocks
        content += self._text_blocks(text)
        if link:
            content.append({"type": "link", "url": link})
        if not content:
            raise PlatformError(self.name, "nothing to post")
        return self._create(ident, content, files)

    def comment(self, target, text):
        ident, pid = self._post_ref(target)
        res, p = self._fetch_post(ident, pid)
        uuid = (p.get("blog") or {}).get("uuid") or (res.get("blog") or {}).get("uuid")
        key = p.get("reblog_key")
        if not uuid or not key:
            raise PlatformError(self.name, f"post {pid} on {ident} can't be reblogged (no reblog key)")
        return self._create(self._my_ident(), self._text_blocks(text), parent_tumblelog_uuid=uuid,
                            parent_post_id=str(p.get("id_string") or p.get("id") or pid), reblog_key=key)

    def poll(self, state):
        me = self._mine()
        ident = self._my_ident()
        since = int(state.get("since") or 0)
        # when the previous poll hit the page cap, carry on from where it stopped down to `since`
        resume = state.get("resume") or {}
        cursor = dict(resume.get("query") or {})
        newest = max(since, int(resume.get("newest") or 0))
        out, ids = [], set()
        for _ in range(self.PAGES):
            res = self._api("GET", f"/blog/{ident}/notifications", params={"types[]": list(self.KINDS), **cursor})
            res = res if isinstance(res, dict) else {}
            notes = res.get("notifications") or []
            for n in notes:
                ts = int(n.get("timestamp") or 0)
                newest = max(newest, ts)
                if ts < since:
                    continue
                item = self._incoming(n, me)
                if item and item.id not in ids:
                    ids.add(item.id)
                    out.append(item)
            nxt = ((res.get("_links") or {}).get("next") or {}).get("query_params")
            oldest = min((int(n.get("timestamp") or 0) for n in notes), default=0)
            if not since or not notes or not nxt or oldest < since:
                state.pop("resume", None)
                state["since"] = newest
                break
            cursor = {k: v for k, v in nxt.items() if not k.startswith("types")}
        else:
            state["resume"] = {"query": cursor, "newest": newest}
        out.sort(key=lambda i: i.ts)
        return out

    def _incoming(self, n, me):
        t = n.get("type") or ""
        kind = self.KINDS.get(t)
        sender = n.get("from_tumblelog_name") or ""
        if not kind or not sender:
            return None
        if sender.lower() in self._own or n.get("from_tumblelog_uuid") in self._own:
            return None
        target_blog = n.get("target_tumblelog_name") or me["name"]
        target_pid = str(n.get("target_post_id") or "")
        if t in self.ON_SENDER:
            blog, pid = sender, str(n.get("post_id") or target_pid)
        else:
            blog, pid = target_blog, target_pid
        if not pid:
            return None
        if t == "reply" and target_blog.lower() != me["name"].lower():
            kind = "reply"
        text = n.get("reply_text") or n.get("added_text") or ""
        if not text and t in self.ON_SENDER:
            text = self._post_text(blog, pid)
        thread = f"{target_blog}/{target_pid}" if target_pid and t != "mention_in_post" else f"{blog}/{pid}"
        ts = n.get("timestamp") or 0
        nid = str(n.get("id") or f"{t}:{n.get('from_tumblelog_uuid') or sender}:{pid}:{ts}")
        return Incoming(
            platform=self.name, kind=kind, id=nid, author=sender, author_id=str(n.get("from_tumblelog_uuid") or ""),
            text=self._tumblr_plain(text), url=f"https://www.tumblr.com/{blog}/{pid}", thread=thread, ts=float(ts),
            reply_to={"action": "comment", "target": f"{blog}/{pid}"}, raw=n,
        )


# ============================================================================
# social_bridge/adapters/lemmy.py — Lemmy (HTTP API v3, Lemmy 0.19+). Signs in with username + password and sends the JWT as a Bearer token.
# ============================================================================
import base64
import hashlib
import hmac
import mimetypes
import os
import re
import struct
import time
import urllib.parse
from datetime import datetime, timezone



@register
class LemmyAdapter(Adapter):
    name = "lemmy"
    label = "Lemmy"
    actions = ("post", "comment", "dm")
    poll_interval = 60  # 3 GETs per poll; instance default limit for API calls is 180/min per IP
    config_keys = {
        "instance": "base URL of the Lemmy server the account is on, e.g. https://lemmy.world",
        "username": "account username (or email) you sign in with on that server",
        "password": "account password (Lemmy has no app tokens; the bridge signs in through /api/v3/user/login)",
        "totp_secret": "(optional) only when two-factor auth is on: the base32 'secret=' value of the otpauth:// "
                       "link shown in Settings -> Account -> Two-factor authentication when you enabled it",
        "community": "(optional) default community for posts without a target, e.g. !technology@lemmy.world",
        "mark_read": "(optional) mark fetched replies, mentions and messages as read on Lemmy: true | false "
                     "(default true)",
    }
    target_help = {
        "post": "community as !name@instance, c/name, c/name@instance, name (on your instance) or community URL "
                "(any instance); omit to use the configured default community",
        "comment": "post or comment URL from any instance, post:<id> / comment:<id> (ids on your instance) or a "
                   "bare post id",
        "dm": "user as @name@instance, u/name, name (on your instance), profile URL (any instance) or person:<id>",
    }

    API = "/api/v3"
    # (state key, path, list key, record key, mark-as-read path, mark-as-read id field)
    STREAMS = (
        ("reply_id", "/user/replies", "replies", "comment_reply", "/comment/mark_as_read", "comment_reply_id"),
        ("mention_id", "/user/mention", "mentions", "person_mention", "/user/mention/mark_as_read",
         "person_mention_id"),
        ("pm_id", "/private_message/list", "private_messages", "private_message", "/private_message/mark_as_read",
         "private_message_id"),
    )

    def __init__(self, config, http=None):
        super().__init__(config, http)
        self._jwt = None
        self._person = None

    # ------------------------------------------------------------- auth / transport
    def _base(self):
        (inst,) = self.need("instance")
        inst = inst.strip().rstrip("/")
        return inst if re.match(r"(?i)https?://", inst) else "https://" + inst

    def _host(self):
        return urllib.parse.urlsplit(self._base()).netloc.lower()

    @staticmethod
    def _totp(secret, now=None):
        """RFC 6238 code (SHA1, 6 digits, 30 s), as Lemmy generates for 2FA."""
        s = re.sub(r"\s", "", secret).upper()
        key = base64.b32decode(s + "=" * (-len(s) % 8))
        digest = hmac.new(key, struct.pack(">Q", int((now if now is not None else time.time()) // 30)),
                          hashlib.sha1).digest()
        off = digest[-1] & 0x0F
        return f"{(struct.unpack('>I', digest[off:off + 4])[0] & 0x7FFFFFFF) % 1000000:06d}"

    def _login(self):
        user, pw = self.need("username", "password")
        body = {"username_or_email": user, "password": pw}
        if self.config.get("totp_secret"):
            body["totp_2fa_token"] = self._totp(self.config["totp_secret"])
        res = self.http.post(self._base() + self.API + "/user/login", json=body)
        if not isinstance(res, dict) or not res.get("jwt"):
            raise PlatformError(self.name, "login returned no token (email verification or registration "
                                           "approval pending?)", body=res)
        self._jwt = res["jwt"]
        return self._jwt

    @staticmethod
    def _expired(e):
        return e.status == 401 or (isinstance(e.body, dict) and e.body.get("error") == "not_logged_in")

    def _call(self, method, url, cookie=False, retry=True, **kw):
        tok = self._jwt or self._login()
        headers = {"Authorization": f"Bearer {tok}"}
        if cookie:
            headers["Cookie"] = f"jwt={tok}"
        try:
            return self.http.request(method, url, headers=headers, **kw)
        except PlatformError as e:
            if retry and self._expired(e):
                self._jwt = None
                return self._call(method, url, cookie=cookie, retry=False, **kw)
            raise

    def _api(self, method, path, **kw):
        res = self._call(method, self._base() + self.API + path, **kw)
        return res if isinstance(res, dict) else {}

    # ------------------------------------------------------------- helpers
    def _me(self):
        if self._person is None:
            site = self._api("GET", "/site")
            person = ((site.get("my_user") or {}).get("local_user_view") or {}).get("person")
            if not person:
                raise PlatformError(self.name, "not signed in: GET /site returned no my_user")
            self._person = person
        return self._person

    def _handle(self, person):
        actor = person.get("actor_id") or person.get("ap_id") or ""
        host = urllib.parse.urlsplit(actor).netloc.lower() or self._host()
        return f"{person.get('name')}@{host}"

    @staticmethod
    def _lemmy_ts(value):
        if not value:
            return 0.0
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    @staticmethod
    def _actor(value):
        """'!name@host', '@name@host', 'c/name', 'u/name@host', 'name', or a /c/ /m/ /u/ /@name URL
        -> (name, host or ''). Returns (None, '') for a URL of another shape."""
        v = str(value).strip()
        if re.match(r"(?i)https?://", v):
            parts = urllib.parse.urlsplit(v)
            seg = [urllib.parse.unquote(s) for s in parts.path.split("/") if s]
            if len(seg) >= 2 and seg[0].lower() in ("c", "m", "u", "user", "community"):
                v = seg[1]
            elif len(seg) == 1 and seg[0].startswith("@"):
                v = seg[0]
            else:
                return None, ""
            name, _, host = v.lstrip("!@").partition("@")
            return name, (host or parts.netloc).lower()
        v = re.sub(r"(?i)^/?(?:c|m|u|user)/", "", v).lstrip("!@")
        name, _, host = v.partition("@")
        return name, host.lower()

    def _resolve(self, q, key):
        res = self._api("GET", "/resolve_object", params={"q": q})
        view = res.get(key)
        if not view:
            raise PlatformError(self.name, f"{q!r} did not resolve to a {key}")
        return view

    def _community_id(self, target):
        t = str(target).strip()
        m = re.match(r"(?i)^(?:community:)?(\d+)$", t)
        if m:
            return int(m.group(1))
        name, host = self._actor(t)
        if not name:
            return self._resolve(t, "community")["community"]["id"]
        local = not host or host == self._host()
        try:
            view = self._api("GET", "/community", params={"name": name if local else f"{name}@{host}"}) \
                .get("community_view")
        except PlatformError:
            if local:
                raise
            view = None
        if view:
            return view["community"]["id"]
        if local:
            raise PlatformError(self.name, f"community {t!r} not found")
        return self._resolve(f"!{name}@{host}", "community")["community"]["id"]

    def _person_id(self, target):
        t = str(target).strip()
        m = re.match(r"(?i)^(?:person:|user:)?(\d+)$", t)
        if m:
            return int(m.group(1))
        name, host = self._actor(t)
        if not name:
            return self._resolve(t, "person")["person"]["id"]
        local = not host or host == self._host()
        try:
            view = self._api("GET", "/user", params={"username": name if local else f"{name}@{host}",
                                                    "limit": 1}).get("person_view")
        except PlatformError:
            if local:
                raise
            view = None
        if view:
            return view["person"]["id"]
        if local:
            raise PlatformError(self.name, f"user {t!r} not found")
        return self._resolve(f"@{name}@{host}", "person")["person"]["id"]

    def _comment_target(self, target):
        """-> (post_id, parent comment id or None)."""
        t = str(target).strip()
        if t.isdigit():
            return int(t), None
        m = re.match(r"(?i)^(post|comment)[:_]\s*(\d+)$", t)
        if m:
            kind, num = m.group(1).lower(), int(m.group(2))
        elif re.match(r"(?i)https?://", t):
            parts = urllib.parse.urlsplit(t)
            mm = re.match(r"^/(post|comment)/(\d+)(?:/(\d+))?/?$", parts.path)
            if mm and parts.netloc.lower() == self._host():
                if mm.group(1) == "post" and mm.group(3):
                    kind, num = "comment", int(mm.group(3))
                else:
                    kind, num = mm.group(1), int(mm.group(2))
            else:
                if mm:
                    # ActivityPub ids are /post/<id> and /comment/<id>; lemmy-ui's /post/<post>/<comment>
                    # comment-context route and query strings are not part of them
                    kind, num = ("comment", mm.group(3)) if mm.group(1) == "post" and mm.group(3) \
                        else (mm.group(1), mm.group(2))
                    t = f"{parts.scheme}://{parts.netloc}/{kind}/{num}"
                res = self._api("GET", "/resolve_object", params={"q": t})
                if res.get("comment"):
                    c = res["comment"]["comment"]
                    return c["post_id"], c["id"]
                if res.get("post"):
                    return res["post"]["post"]["id"], None
                raise PlatformError(self.name, f"{t!r} did not resolve to a post or comment")
        else:
            raise PlatformError(self.name, f"can't read a post or comment from {t!r}")
        if kind == "post":
            return num, None
        c = self._api("GET", "/comment", params={"id": num})["comment_view"]["comment"]
        return c["post_id"], c["id"]

    def _upload(self, src):
        """Remote URLs are used as-is; local files go to the instance's pict-rs image store."""
        if re.match(r"(?i)https?://", src):
            return src
        if not os.path.isfile(src):
            raise PlatformError(self.name, f"media file not found: {src}")
        with open(src, "rb") as f:
            data = f.read()
        mime = mimetypes.guess_type(src)[0] or "application/octet-stream"
        res = self._call("POST", self._base() + "/pictrs/image", cookie=True,
                         files={"images[]": (os.path.basename(src), data, mime)})
        files = res.get("files") if isinstance(res, dict) else None
        if not files or (res.get("msg") not in (None, "ok")):
            raise PlatformError(self.name, f"image upload failed: {res!r}"[:300], body=res)
        return f"{self._base()}/pictrs/image/{files[0]['file']}"

    def _item(self, rec_key, row, me):
        creator = row.get("creator") or {}
        if creator.get("id") == me.get("id"):
            return None
        author = self._handle(creator)
        if rec_key == "private_message":
            pm = row.get("private_message") or {}
            if pm.get("deleted"):
                return None
            return Incoming(
                platform=self.name, kind="dm", id=f"pm:{pm['id']}", author=author,
                author_id=str(creator.get("id", "")), text=(pm.get("content") or "").strip(),
                thread=f"dm:{author}", ts=self._lemmy_ts(pm.get("published")),
                reply_to={"action": "dm", "target": author}, raw=row,
            )
        c = row.get("comment") or {}
        if c.get("deleted") or c.get("removed"):
            return None
        if rec_key == "person_mention":
            kind = "mention"
        else:
            kind = "comment" if len((c.get("path") or "0").split(".")) <= 2 else "reply"
        post_id = c.get("post_id") or (row.get("post") or {}).get("id")
        return Incoming(
            platform=self.name, kind=kind, id=f"comment:{c['id']}", author=author,
            author_id=str(creator.get("id", "")), text=(c.get("content") or "").strip(),
            url=f"{self._base()}/comment/{c['id']}", thread=f"post:{post_id}",
            ts=self._lemmy_ts(c.get("published")), reply_to={"action": "comment", "target": f"comment:{c['id']}"},
            raw=row,
        )

    # ------------------------------------------------------------- actions
    def whoami(self):
        return self._handle(self._me())

    def post(self, text, target=None, title=None, link=None, media=None):
        community = target or self.config.get("community")
        if not community:
            raise PlatformError(self.name, "posts go to a community: pass a target like !name@instance")
        cid = self._community_id(community)
        urls = [self._upload(str(m).strip()) for m in media or []]
        text = (text or "").strip()
        name = (title or "").strip()
        if not name:
            first, _, rest = text.partition("\n")
            name, text = first.strip(), rest.strip()
        if not name:
            raise PlatformError(self.name, "a post needs a title (or text whose first line becomes the title)")
        if len(name) > 200:  # Lemmy's title limit
            text = "\n\n".join(x for x in (name, text) if x)
            name = name[:199].rstrip() + "…"
        body = {"name": name, "community_id": cid}
        main = link or (urls.pop(0) if urls else None)
        if main:
            body["url"] = main
        text = "\n\n".join(x for x in [text] + [f"![]({u})" for u in urls] if x)
        if text:
            body["body"] = text
        res = self._api("POST", "/post", json=body)
        p = res["post_view"]["post"]
        return Result(id=str(p["id"]), url=p.get("ap_id") or f"{self._base()}/post/{p['id']}", raw=res)

    def comment(self, target, text):
        post_id, parent_id = self._comment_target(target)
        body = {"content": text, "post_id": post_id}
        if parent_id:
            body["parent_id"] = parent_id
        res = self._api("POST", "/comment", json=body)
        c = res["comment_view"]["comment"]
        return Result(id=str(c["id"]), url=c.get("ap_id") or f"{self._base()}/comment/{c['id']}", raw=res)

    def dm(self, target, text):
        rid = self._person_id(target)
        res = self._api("POST", "/private_message", json={"content": text, "recipient_id": rid})
        pm = res["private_message_view"]["private_message"]
        return Result(id=str(pm["id"]), url="", raw=res)

    def poll(self, state):
        me = self._me()
        mark = str(self.config.get("mark_read", "true")).strip().lower() not in ("false", "0", "no", "off")
        out, ids = [], set()
        for key, path, list_key, rec_key, mark_path, mark_field in self.STREAMS:
            params = {"unread_only": "false", "page": 1, "limit": 50}
            if path != "/private_message/list":
                params["sort"] = "New"
            rows = self._api("GET", path, params=params).get(list_key) or []
            primed = key in state  # never mark the pre-existing backlog as read
            cursor = int(state.get(key) or 0)
            top = cursor
            for row in rows:
                rec = row.get(rec_key) or {}
                rid = int(rec.get("id") or 0)
                top = max(top, rid)
                if rid <= cursor:
                    continue
                item = self._item(rec_key, row, me)
                if item is None:
                    continue
                if item.id not in ids:
                    ids.add(item.id)
                    out.append(item)
                if mark and primed and not rec.get("read"):
                    try:
                        self._api("POST", mark_path, json={mark_field: rid, "read": True})
                    except PlatformError:
                        pass
            state[key] = top
        out.sort(key=lambda i: i.ts)
        return out


# ============================================================================
# social_bridge/core.py — The bridge: holds platform adapters, the approval queue, the inbox the AI reads, and the live feed.
# ============================================================================
import json
import logging
import threading
import time
import uuid
from collections import deque
from pathlib import Path


log = logging.getLogger("social_bridge")

MODES = ("review", "auto")


class Bridge:
    def __init__(self, config, data_dir=None, adapters=None):
        self.config = config
        self.mode = config.get("mode", "review")
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.paused = False
        self.lock = threading.RLock()
        self.dir = Path(data_dir or config.get("data_dir", "social_data"))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.adapters = adapters if adapters is not None else self._build_adapters()
        self.platform_status = {name: {"account": None, "error": None} for name in self.adapters}

        self.actions = {}                         # id -> action dict
        self.inbox = deque(maxlen=2000)           # incoming dicts with "seq"
        self.feed = deque(maxlen=500)             # dashboard timeline
        self.seq = 0
        self.poll_state = {}
        self.seen = {}                            # platform -> deque of seen incoming ids
        self._threads = []
        self._stop = threading.Event()
        self._listeners = []                      # callables(incoming_dict) e.g. the responder
        self._load()

    # ------------------------------------------------------------------ setup
    def _build_adapters(self):
        built = {}
        for name, pconf in (self.config.get("platforms") or {}).items():
            if not pconf or not pconf.get("enabled"):
                continue
            cls = ADAPTERS.get(name)
            if cls is None:
                log.warning("unknown platform in config: %s", name)
                continue
            built[name] = cls(pconf, Http(name, user_agent=pconf.get("user_agent") or f"social-bridge/1.0 ({name})"))
        return built

    def _load(self):
        state_file = self.dir / "state.json"
        if state_file.exists():
            state = json.loads(state_file.read_text())
            self.poll_state = state.get("poll_state", {})
            self.seq = state.get("seq", 0)
            self.seen = {k: deque(v, maxlen=5000) for k, v in state.get("seen", {}).items()}
            self.mode = state.get("mode", self.mode)
        actions_file = self.dir / "actions.json"
        if actions_file.exists():
            self.actions = {a["id"]: a for a in json.loads(actions_file.read_text())}
        for name, fname in (("inbox", "inbox.jsonl"), ("feed", "feed.jsonl")):
            path = self.dir / fname
            if path.exists():
                target = getattr(self, name)
                for line in path.read_text().splitlines()[-target.maxlen:]:
                    try:
                        target.append(json.loads(line))
                    except ValueError:
                        pass

    def _save(self):
        with self.lock:
            (self.dir / "state.json").write_text(json.dumps({
                "poll_state": self.poll_state, "seq": self.seq, "mode": self.mode,
                "seen": {k: list(v) for k, v in self.seen.items()},
            }))
            recent = sorted(self.actions.values(), key=lambda a: a["created"])[-1000:]
            self.actions = {a["id"]: a for a in recent}
            (self.dir / "actions.json").write_text(json.dumps(recent))

    def _append(self, fname, entry):
        with open(self.dir / fname, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _event(self, kind, **data):
        entry = {"ts": time.time(), "kind": kind, **data}
        with self.lock:
            self.feed.append(entry)
            self._append("feed.jsonl", entry)
        return entry

    # --------------------------------------------------------------- outgoing
    def submit(self, platform, action, text, target=None, opts=None, source="agent", context=None):
        """Queue an outgoing action. In auto mode (and not paused) it is executed right away."""
        adapter = self.adapters.get(platform)
        if adapter is None:
            raise PlatformError(platform, f"platform not enabled. Enabled: {', '.join(self.adapters) or 'none'}")
        if action not in adapter.actions:
            raise PlatformError(platform, f"'{action}' not available on {platform}. Available: {', '.join(adapter.actions)}")
        if action in ("comment", "dm") and not target:
            raise PlatformError(platform, f"'{action}' needs a target")
        if not (text or "").strip() and not (opts or {}).get("media"):
            raise PlatformError(platform, "text is empty")
        a = {
            "id": uuid.uuid4().hex[:10], "platform": platform, "action": action, "target": target,
            "text": text, "opts": opts or {}, "status": "pending", "source": source, "context": context,
            "created": time.time(), "updated": time.time(), "result": None, "error": None,
        }
        with self.lock:
            self.actions[a["id"]] = a
        self._event("queued", action=_public(a))
        if self.mode == "auto" and not self.paused:
            return self.execute(a["id"])
        self._save()
        return a

    def approve(self, action_id, text=None):
        with self.lock:
            a = self._get(action_id)
            if a["status"] != "pending":
                raise ValueError(f"action {action_id} is {a['status']}")
            if text is not None and text != a["text"]:
                a["original_text"], a["text"] = a["text"], text
            a["status"] = "approved"
        return self.execute(action_id)

    def reject(self, action_id, reason=""):
        with self.lock:
            a = self._get(action_id)
            if a["status"] != "pending":
                raise ValueError(f"action {action_id} is {a['status']}")
            a.update(status="rejected", error=reason or None, updated=time.time())
        self._event("rejected", action=_public(a))
        self._save()
        return a

    def execute(self, action_id):
        with self.lock:
            a = self._get(action_id)
            if a["status"] not in ("pending", "approved"):
                raise ValueError(f"action {action_id} is {a['status']}")
            a["status"] = "sending"
        adapter = self.adapters[a["platform"]]
        try:
            if a["action"] == "post":
                o = a["opts"]
                res = adapter.post(a["text"], target=a["target"], title=o.get("title"), link=o.get("link"),
                                   media=o.get("media"))
            elif a["action"] == "comment":
                res = adapter.comment(a["target"], a["text"])
            else:
                res = adapter.dm(a["target"], a["text"])
            a.update(status="sent", result=res.to_dict(), updated=time.time())
            self._event("sent", action=_public(a))
        except Exception as e:  # noqa: BLE001 - any adapter failure is reported, not raised
            log.exception("send failed")
            a.update(status="failed", error=str(e), updated=time.time())
            self._event("failed", action=_public(a))
        self._save()
        return a

    def _get(self, action_id):
        a = self.actions.get(action_id)
        if a is None:
            raise KeyError(f"no action {action_id}")
        return a

    def reply(self, seq, text):
        """Answer an inbox item using its own reply_to instructions."""
        item = next((i for i in self.inbox if i["seq"] == int(seq)), None)
        if item is None:
            raise KeyError(f"no inbox item {seq}")
        rt = item["reply_to"]
        return self.submit(item["platform"], rt["action"], text, target=rt["target"],
                           context={"in_reply_to": int(seq), "thread": item["thread"], "author": item["author"],
                                    "text": item["text"]})

    # --------------------------------------------------------------- incoming
    def ingest(self, platform, items):
        new = []
        with self.lock:
            seen = self.seen.setdefault(platform, deque(maxlen=5000))
            for it in items:
                if it.id in seen:
                    continue
                seen.append(it.id)
                self.seq += 1
                d = it.to_dict()
                d["seq"] = self.seq
                d["received"] = time.time()
                self.inbox.append(d)
                self._append("inbox.jsonl", d)
                new.append(d)
        for d in new:
            self._event("incoming", item=d)
            for fn in list(self._listeners):
                try:
                    fn(d)
                except Exception:  # noqa: BLE001
                    log.exception("listener failed")
        if new:
            self._save()
        return new

    def poll_once(self, platform):
        adapter = self.adapters[platform]
        state = self.poll_state.setdefault(platform, {})
        try:
            items = adapter.poll(state)
            self.platform_status[platform]["error"] = None
        except Exception as e:  # noqa: BLE001
            log.warning("poll %s failed: %s", platform, e)
            self.platform_status[platform]["error"] = str(e)
            return []
        if not state.get("_primed"):
            # First successful poll ever: whatever already exists is history, not new messages.
            state["_primed"] = True
            if not self.config.get("replay_backlog"):
                with self.lock:
                    seen = self.seen.setdefault(platform, deque(maxlen=5000))
                    seen.extend(it.id for it in items)
                self._save()
                return []
        return self.ingest(platform, items)

    def inbox_after(self, after=0, platform=None, limit=50):
        with self.lock:
            items = [i for i in self.inbox if i["seq"] > int(after) and (not platform or i["platform"] == platform)]
        items = items[:limit]
        return {"items": items, "next": items[-1]["seq"] if items else int(after)}

    def history(self, platform, thread, limit=30):
        """Incoming + sent messages for one conversation, oldest first (for building AI context)."""
        out = []
        with self.lock:
            for e in self.feed:
                if e["kind"] == "incoming" and e["item"]["platform"] == platform and e["item"]["thread"] == thread:
                    out.append({"role": "user", "author": e["item"]["author"], "text": e["item"]["text"], "ts": e["ts"]})
                elif e["kind"] == "sent" and e["action"]["platform"] == platform and \
                        (e["action"].get("context") or {}).get("thread") == thread:
                    out.append({"role": "assistant", "text": e["action"]["text"], "ts": e["ts"]})
        return out[-limit:]

    # ------------------------------------------------------------- lifecycle
    def check(self):
        for name, adapter in self.adapters.items():
            try:
                self.platform_status[name].update(account=adapter.whoami(), error=None)
            except Exception as e:  # noqa: BLE001
                self.platform_status[name].update(error=str(e))
        return self.platform_status

    def start(self):
        self._stop.clear()
        for name, adapter in self.adapters.items():
            if adapter.poll_interval <= 0:
                continue
            t = threading.Thread(target=self._poll_loop, args=(name, adapter.poll_interval), daemon=True,
                                 name=f"poll-{name}")
            t.start()
            self._threads.append(t)

    def stop(self):
        self._stop.set()

    def _poll_loop(self, name, interval):
        interval = int(self.config["platforms"].get(name, {}).get("poll_interval", interval)) \
            if self.config.get("platforms") else interval
        while not self._stop.is_set():
            self.poll_once(name)
            self._stop.wait(interval)

    def set_mode(self, mode):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.mode = mode
        self._event("mode", mode=mode)
        self._save()

    def set_paused(self, paused):
        self.paused = bool(paused)
        self._event("paused" if paused else "resumed")

    def on_incoming(self, fn):
        self._listeners.append(fn)

    def snapshot(self, feed_limit=150):
        with self.lock:
            pending = [_public(a) for a in sorted(self.actions.values(), key=lambda a: a["created"])
                       if a["status"] == "pending"]
            return {
                "mode": self.mode, "paused": self.paused,
                "platforms": {n: {"label": a.label, "actions": list(a.actions), **self.platform_status[n]}
                              for n, a in self.adapters.items()},
                "pending": pending,
                "feed": list(self.feed)[-feed_limit:],
            }


def _public(a):
    return {k: v for k, v in a.items() if k != "opts" or v}


class Responder:
    """Optional built-in auto-replier: drafts answers to incoming items with any OpenAI-compatible chat endpoint.

    Drafts go through the same queue, so review mode still holds them for approval.
    """

    def __init__(self, bridge, conf, http=None):
        self.bridge = bridge
        self.conf = conf
        self.http = http or Http("responder", timeout=conf.get("timeout", 120))
        self.platforms = set(conf.get("platforms") or [])
        self.kinds = set(conf.get("kinds") or ["dm", "mention", "comment", "reply"])
        self.pool = threading.Semaphore(int(conf.get("concurrency", 2)))

    def attach(self):
        self.bridge.on_incoming(lambda item: threading.Thread(target=self.handle, args=(item,), daemon=True).start())

    def handle(self, item):
        if self.platforms and item["platform"] not in self.platforms:
            return
        if item["kind"] not in self.kinds or self.bridge.paused:
            return
        with self.pool:
            try:
                text = self.draft(item)
            except Exception as e:  # noqa: BLE001
                self.bridge._event("responder_error", error=str(e), seq=item["seq"])
                return
            if not text:
                return
            rt = item["reply_to"]
            self.bridge.submit(item["platform"], rt["action"], text, target=rt["target"], source="responder",
                               context={"in_reply_to": item["seq"], "thread": item["thread"],
                                        "author": item["author"], "text": item["text"]})

    def draft(self, item):
        messages = [{"role": "system", "content": self.conf.get("system_prompt") or
                     "You are chatting on social media. Reply naturally and briefly."}]
        for h in self.bridge.history(item["platform"], item["thread"])[:-1]:
            content = h["text"] if h["role"] == "assistant" else f"{h['author']}: {h['text']}"
            messages.append({"role": h["role"], "content": content})
        messages.append({"role": "user", "content":
                         f"[{item['platform']} {item['kind']}] {item['author']}: {item['text']}"})
        headers = {"Content-Type": "application/json"}
        if self.conf.get("api_key"):
            headers["Authorization"] = f"Bearer {self.conf['api_key']}"
        body = {"model": self.conf.get("model", ""), "messages": messages}
        body.update(self.conf.get("params") or {})
        resp = self.http.post(self.conf["url"], json=body, headers=headers)
        return (resp["choices"][0]["message"]["content"] or "").strip()


# ============================================================================
# social_bridge/dashboard.py — Oversight dashboard (single self-contained page).
# ============================================================================
DASHBOARD_HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Social Bridge</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#16181d;--mute:#6b7280;--line:#e3e6ea;--acc:#2563eb;--ok:#16a34a;--bad:#dc2626;--warn:#d97706;--in:#eef4ff;--out:#effaf3}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--fg:#e8eaee;--mute:#9aa1ad;--line:#272b35;--acc:#60a5fa;--ok:#4ade80;--bad:#f87171;--warn:#fbbf24;--in:#152033;--out:#13261b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
h1{font-size:16px;margin:0 auto 0 0}h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--mute);margin:18px 0 8px}
main{max-width:860px;margin:0 auto;padding:0 16px 40px}
button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;padding:6px 12px;cursor:pointer}
button.on{background:var(--acc);border-color:var(--acc);color:#fff}button.ok{background:var(--ok);border-color:var(--ok);color:#fff}button.bad{color:var(--bad)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:10px}
.meta{font-size:12px;color:var(--mute);display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.tag{display:inline-block;font-size:11px;font-weight:600;padding:1px 7px;border-radius:99px;background:var(--line);color:var(--fg)}
textarea{width:100%;min-height:80px;font:inherit;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px;margin:8px 0;resize:vertical}
.row{display:flex;gap:8px;flex-wrap:wrap}.ctx{font-size:13px;border-left:3px solid var(--line);padding-left:8px;margin-top:6px;color:var(--mute);white-space:pre-wrap}
.ev{padding:8px 10px;border-radius:10px;margin-bottom:6px;white-space:pre-wrap;word-break:break-word}
.ev.incoming{background:var(--in)}.ev.sent{background:var(--out)}.ev.failed{border:1px solid var(--bad)}.ev.rejected{opacity:.6}
.plats{display:flex;flex-wrap:wrap;gap:6px}.plat{font-size:13px;padding:4px 10px;border-radius:99px;border:1px solid var(--line);background:var(--card)}
.plat.err{border-color:var(--bad)}.empty{color:var(--mute);font-size:14px}a{color:var(--acc)}
#tok{display:none}
</style></head><body>
<header><h1>Social Bridge</h1>
<span class="meta">Mode</span><button id="m-review">Review</button><button id="m-auto">Auto</button>
<button id="pause">Pause</button><button id="poll">Poll now</button></header>
<main>
<div id="tok" class="card">API token: <input id="tokin" type="password"> <button id="toksave">Save</button></div>
<h2>Platforms</h2><div id="plats" class="plats"></div>
<h2>Waiting for approval <span id="pc"></span></h2><div id="pending"></div>
<h2>Live feed</h2><div id="feed"></div>
</main>
<script>
const $=s=>document.querySelector(s);let tok='';try{tok=localStorage.getItem('sb_token')||''}catch(e){}
const H=()=>tok?{'Authorization':'Bearer '+tok,'Content-Type':'application/json'}:{'Content-Type':'application/json'};
async function api(p,body){const r=await fetch(p,{method:body?'POST':'GET',headers:H(),body:body?JSON.stringify(body):undefined});
 if(r.status===401){$('#tok').style.display='block';throw new Error('unauthorized')}return r.json()}
$('#toksave').onclick=()=>{tok=$('#tokin').value;try{localStorage.setItem('sb_token',tok)}catch(e){};$('#tok').style.display='none';load()};
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const t=ts=>new Date(ts*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
const editing=new Set();let last=null;
function pend(a){const c=a.context?`<div class="ctx">↪ ${esc(a.context.author)}: ${esc(a.context.text)}</div>`:'';
 return `<div class="card" data-id="${a.id}"><div class="meta"><span class="tag">${esc(a.platform)}</span><b>${esc(a.action)}</b>
 ${a.target?'→ '+esc(a.target):''}${a.opts&&a.opts.title?' · title: '+esc(a.opts.title):''}<span>· ${esc(a.source)} · ${t(a.created)}</span></div>${c}
 <textarea>${esc(a.text)}</textarea><div class="row"><button class="ok" data-do="approve">Send</button><button class="bad" data-do="reject">Reject</button></div></div>`}
function ev(e){if(e.kind==='incoming'){const i=e.item;return `<div class="ev incoming"><div class="meta"><span class="tag">${esc(i.platform)}</span>📥 ${esc(i.kind)} · <b>${esc(i.author)}</b> · ${t(e.ts)} · #${i.seq}${i.url?` · <a href="${esc(i.url)}" target="_blank" rel="noopener">open</a>`:''}</div>${esc(i.text)}</div>`}
 if(['sent','failed','rejected','queued'].includes(e.kind)){const a=e.action;const icon={sent:'📤',failed:'⚠️',rejected:'🗑️',queued:'📝'}[e.kind];
  const link=a.result&&a.result.url?` · <a href="${esc(a.result.url)}" target="_blank" rel="noopener">open</a>`:'';
  return `<div class="ev ${e.kind}"><div class="meta"><span class="tag">${esc(a.platform)}</span>${icon} ${e.kind} ${esc(a.action)} ${a.target?'→ '+esc(a.target):''} · ${t(e.ts)}${link}</div>${esc(a.text)}${a.error?`<div class="ctx">${esc(a.error)}</div>`:''}</div>`}
 return `<div class="ev"><div class="meta">${esc(e.kind)} ${esc(e.mode||e.error||'')} · ${t(e.ts)}</div></div>`}
async function load(){let s;try{s=await api('/v1/state?feed=150')}catch(e){return}
 $('#m-review').className=s.mode==='review'?'on':'';$('#m-auto').className=s.mode==='auto'?'on':'';
 $('#pause').textContent=s.paused?'Resume':'Pause';$('#pause').className=s.paused?'on':'';
 $('#plats').innerHTML=Object.entries(s.platforms).map(([n,p])=>`<span class="plat ${p.error?'err':''}" title="${esc(p.error||'')}">${esc(p.label||n)}${p.account?' · '+esc(p.account):''} <small>(${p.actions.join(', ')})</small></span>`).join('')||'<span class="empty">No platforms enabled. Edit social_bridge.json.</span>';
 $('#pc').textContent=s.pending.length?`(${s.pending.length})`:'';
 const box=$('#pending');const ids=s.pending.map(a=>a.id).join();
 if(ids!==last){[...box.children].forEach(c=>{if(!s.pending.find(a=>a.id===c.dataset.id))c.remove()});
  s.pending.forEach(a=>{if(!box.querySelector(`[data-id="${a.id}"]`))box.insertAdjacentHTML('beforeend',pend(a))});last=ids}
 if(!s.pending.length)box.innerHTML='<div class="empty">Nothing waiting.</div>';
 $('#feed').innerHTML=s.feed.slice().reverse().filter(e=>e.kind!=='queued').map(ev).join('')||'<div class="empty">No activity yet.</div>'}
$('#pending').onclick=async e=>{const b=e.target.closest('button');if(!b)return;const card=b.closest('.card');const id=card.dataset.id;b.disabled=true;
 if(b.dataset.do==='approve')await api(`/v1/actions/${id}/approve`,{text:card.querySelector('textarea').value});
 else await api(`/v1/actions/${id}/reject`,{});card.remove();last=null;load()};
$('#m-review').onclick=()=>api('/v1/mode',{mode:'review'}).then(load);$('#m-auto').onclick=()=>api('/v1/mode',{mode:'auto'}).then(load);
$('#pause').onclick=()=>api('/v1/pause',{paused:$('#pause').textContent==='Pause'}).then(load);
$('#poll').onclick=()=>api('/v1/poll',{}).then(load);
load();setInterval(load,2500);
</script></body></html>
"""


# ============================================================================
# social_bridge/server.py — Local HTTP API for the AI + the oversight dashboard.
# ============================================================================
import json
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


log = logging.getLogger("social_bridge")


def tool_schemas(bridge=None):
    """OpenAI-style function/tool definitions. Hand these to the AI so it can call the bridge."""
    platforms = sorted(bridge.adapters) if bridge else []
    pl = {"type": "string", "description": "Platform name" + (f": one of {', '.join(platforms)}" if platforms else "")}
    if platforms:
        pl["enum"] = platforms
    targets = ""
    if bridge:
        lines = []
        for name, a in sorted(bridge.adapters.items()):
            for act, desc in (a.target_help or {}).items():
                lines.append(f"{name}.{act}: {desc}")
        targets = " Target formats: " + "; ".join(lines) if lines else ""

    def fn(name, desc, props, required):
        return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
            "type": "object", "properties": props, "required": required}}}

    return [
        fn("social_platforms", "List connected platforms, the account on each, and which actions each supports.",
           {}, []),
        fn("social_post", "Publish a new post." + targets, {
            "platform": pl,
            "text": {"type": "string", "description": "Post body"},
            "target": {"type": "string", "description": "Where to post (subreddit, page, channel...). Omit for own profile/feed."},
            "title": {"type": "string", "description": "Title, for platforms that need one (e.g. Reddit)"},
            "link": {"type": "string", "description": "Optional URL to attach"},
            "media": {"type": "array", "items": {"type": "string"}, "description": "Optional image file paths or URLs"},
        }, ["platform", "text"]),
        fn("social_comment", "Comment on / reply to a post or comment." + targets, {
            "platform": pl,
            "target": {"type": "string", "description": "ID or URL of the post/comment to reply to"},
            "text": {"type": "string"},
        }, ["platform", "target", "text"]),
        fn("social_dm", "Send a direct message to a user." + targets, {
            "platform": pl,
            "target": {"type": "string", "description": "User handle / ID / conversation ID"},
            "text": {"type": "string"},
        }, ["platform", "target", "text"]),
        fn("social_inbox", "Get new DMs, mentions, comments and replies. Pass the `next` value from the previous call as `after`.", {
            "after": {"type": "integer", "description": "Only items with seq greater than this", "default": 0},
            "platform": {"type": "string", "description": "Optional platform filter"},
        }, []),
        fn("social_reply", "Reply to an inbox item (uses the right action and target automatically).", {
            "seq": {"type": "integer", "description": "The inbox item's seq"},
            "text": {"type": "string"},
        }, ["seq", "text"]),
        fn("social_history", "Get the recent back-and-forth in one conversation thread.", {
            "platform": pl, "thread": {"type": "string", "description": "The inbox item's `thread` value"},
        }, ["platform", "thread"]),
        fn("social_action_status", "Check whether a queued post/comment/DM was approved, sent, rejected or failed.", {
            "id": {"type": "string"},
        }, ["id"]),
    ]


def call_tool(bridge, name, args):
    """Execute one tool call. Returns a JSON-able result."""
    args = args or {}
    if isinstance(args, str):
        args = json.loads(args or "{}")
    if name == "social_platforms":
        return bridge.snapshot(feed_limit=0)["platforms"]
    if name == "social_post":
        opts = {k: args[k] for k in ("title", "link", "media") if args.get(k)}
        return bridge.submit(args["platform"], "post", args.get("text", ""), target=args.get("target"), opts=opts)
    if name == "social_comment":
        return bridge.submit(args["platform"], "comment", args["text"], target=args["target"])
    if name == "social_dm":
        return bridge.submit(args["platform"], "dm", args["text"], target=args["target"])
    if name == "social_inbox":
        return bridge.inbox_after(args.get("after", 0), args.get("platform"))
    if name == "social_reply":
        return bridge.reply(args["seq"], args["text"])
    if name == "social_history":
        return bridge.history(args["platform"], args["thread"])
    if name == "social_action_status":
        return bridge._get(args["id"])
    raise KeyError(f"unknown tool {name}")


def make_handler(bridge, token=""):
    class Handler(BaseHTTPRequestHandler):
        server_version = "social-bridge/1.0"

        def log_message(self, fmt, *a):
            log.debug("%s %s", self.address_string(), fmt % a)

        # ---------------------------------------------------------- helpers
        def _send(self, code, payload, ctype="application/json"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authed(self):
            if not token:
                return True
            got = self.headers.get("Authorization", "")
            q = parse_qs(urlsplit(self.path).query)
            return got == f"Bearer {token}" or q.get("token", [""])[0] == token

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            return json.loads(raw or b"{}")

        def _run(self, fn):
            try:
                self._send(200, fn())
            except (KeyError, ValueError, TypeError) as e:
                self._send(400, {"error": str(e)})
            except PlatformError as e:
                self._send(422, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                log.exception("handler error")
                self._send(500, {"error": str(e)})

        # ---------------------------------------------------------- routes
        def do_GET(self):
            url = urlsplit(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path in ("/", "/index.html"):
                return self._send(200, DASHBOARD_HTML.encode(), "text/html; charset=utf-8")
            if url.path == "/health":
                return self._send(200, {"ok": True, "time": time.time()})
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            routes = {
                "/v1/state": lambda: bridge.snapshot(int(q.get("feed", 150))),
                "/v1/tools": lambda: tool_schemas(bridge),
                "/v1/platforms": lambda: call_tool(bridge, "social_platforms", {}),
                "/v1/inbox": lambda: bridge.inbox_after(int(q.get("after", 0)), q.get("platform"),
                                                        int(q.get("limit", 50))),
                "/v1/history": lambda: bridge.history(q["platform"], q["thread"]),
            }
            if url.path in routes:
                return self._run(routes[url.path])
            if url.path.startswith("/v1/actions/"):
                return self._run(lambda: bridge._get(url.path.rsplit("/", 1)[1]))
            self._send(404, {"error": "not found"})

        def do_POST(self):
            url = urlsplit(self.path)
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            try:
                body = self._body()
            except ValueError:
                return self._send(400, {"error": "invalid JSON"})
            p = url.path
            if p == "/v1/tool":
                return self._run(lambda: call_tool(bridge, body["name"], body.get("arguments")))
            if p == "/v1/actions":
                return self._run(lambda: bridge.submit(body["platform"], body["action"], body.get("text", ""),
                                                       target=body.get("target"), opts=body.get("opts"),
                                                       source=body.get("source", "agent")))
            if p == "/v1/reply":
                return self._run(lambda: bridge.reply(body["seq"], body["text"]))
            if p.startswith("/v1/actions/") and p.endswith("/approve"):
                aid = p.split("/")[3]
                return self._run(lambda: bridge.approve(aid, body.get("text")))
            if p.startswith("/v1/actions/") and p.endswith("/reject"):
                aid = p.split("/")[3]
                return self._run(lambda: bridge.reject(aid, body.get("reason", "")))
            if p == "/v1/mode":
                return self._run(lambda: (bridge.set_mode(body["mode"]), bridge.snapshot(0))[1])
            if p == "/v1/pause":
                return self._run(lambda: (bridge.set_paused(body.get("paused", True)), bridge.snapshot(0))[1])
            if p == "/v1/poll":
                return self._run(lambda: {n: bridge.poll_once(n) for n in
                                          ([body["platform"]] if body.get("platform") else list(bridge.adapters))})
            if p == "/v1/check":
                return self._run(bridge.check)
            self._send(404, {"error": "not found"})

    return Handler


def serve(bridge, host="127.0.0.1", port=8765, token=""):
    httpd = ThreadingHTTPServer((host, port), make_handler(bridge, token))
    log.info("dashboard + API on http://%s:%s", host, port)
    return httpd


# ============================================================================
# social_bridge/__main__.py — CLI: python -m social_bridge [init|check|serve|tools|send]
# ============================================================================
import argparse
import json
import logging
import sys
from pathlib import Path


DEFAULT_CONFIG = "social_bridge.json"


def template():
    return {
        "mode": "review",
        "host": "127.0.0.1",
        "port": 8765,
        "api_token": "",
        "data_dir": "social_data",
        "responder": {
            "enabled": False,
            "url": "http://127.0.0.1:11434/v1/chat/completions",
            "model": "llama3.1:8b",
            "api_key": "",
            "system_prompt": "",
            "platforms": [],
            "kinds": ["dm", "mention", "comment", "reply"],
        },
        "platforms": {
            name: {"enabled": False, **{k: "" for k in cls.config_keys}}
            for name, cls in sorted(ADAPTERS.items())
        },
    }


def load_config(path):
    p = Path(path)
    if not p.exists():
        sys.exit(f"No config at {p}. Run: python -m social_bridge init")
    return json.loads(p.read_text())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="social_bridge")
    ap.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="write a config template listing every platform's settings")
    sub.add_parser("check", help="log in to every enabled platform and print the account name")
    sub.add_parser("platforms", help="list supported platforms and their settings")
    s = sub.add_parser("serve", help="run the API + dashboard + inbox polling")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    sub.add_parser("tools", help="print the tool definitions to give your AI")
    snd = sub.add_parser("send", help="send something right now (skips the queue)")
    snd.add_argument("platform")
    snd.add_argument("action", choices=["post", "comment", "dm"])
    snd.add_argument("text")
    snd.add_argument("--target")
    snd.add_argument("--title")
    snd.add_argument("--link")
    snd.add_argument("--media", nargs="*")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "init":
        p = Path(args.config)
        if p.exists():
            sys.exit(f"{p} already exists")
        p.write_text(json.dumps(template(), indent=2))
        print(f"Wrote {p}. Fill in the platforms you want and set \"enabled\": true.")
        return
    if args.cmd == "platforms":
        for name, cls in sorted(ADAPTERS.items()):
            print(f"\n{cls.label} ({name}) — actions: {', '.join(cls.actions)}")
            for k, d in cls.config_keys.items():
                print(f"  {k}: {d}")
            for act, d in cls.target_help.items():
                print(f"  target for {act}: {d}")
        return

    cfg = load_config(args.config)
    bridge = Bridge(cfg)
    if args.cmd == "check":
        for name, st in bridge.check().items():
            print(f"{name:12} {'OK  ' + str(st['account']) if not st['error'] else 'FAIL ' + st['error']}")
        return
    if args.cmd == "tools":
        print(json.dumps(tool_schemas(bridge), indent=2))
        return
    if args.cmd == "send":
        opts = {k: getattr(args, k) for k in ("title", "link", "media") if getattr(args, k)}
        bridge.mode = "auto"
        a = bridge.submit(args.platform, args.action, args.text, target=args.target, opts=opts, source="cli")
        print(json.dumps(a, indent=2, default=str))
        return
    if args.cmd == "serve":
        bridge.check()
        if (cfg.get("responder") or {}).get("enabled"):
            Responder(bridge, cfg["responder"]).attach()
        bridge.start()
        httpd = serve(bridge, args.host or cfg.get("host", "127.0.0.1"), args.port or cfg.get("port", 8765),
                      cfg.get("api_token", ""))
        print(f"Dashboard: http://{httpd.server_address[0]}:{httpd.server_address[1]}/   (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            bridge.stop()


if __name__ == "__main__":
    main()
