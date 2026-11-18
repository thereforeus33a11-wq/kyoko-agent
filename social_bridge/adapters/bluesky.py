"""Bluesky (AT Protocol XRPC with an app password; DMs through the Bluesky chat service via the PDS)."""
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

from ..base import Adapter, Incoming, PlatformError, Result, register


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
