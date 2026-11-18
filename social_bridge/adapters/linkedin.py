"""LinkedIn (REST API): member or Page posts with images, video, a document or a link card, and comments.
Polls new comments and @mentions when acting as an organization Page."""
import html
import json
import mimetypes
import os
import re
import time
import urllib.parse

from ..base import Adapter, Incoming, PlatformError, Result, register


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
