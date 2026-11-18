"""Threads (Meta Threads API): posts (text, link card, image, video, carousel, quote) and replies.
Polls replies to the account's recent posts and replies, and @mentions."""
import calendar
import hashlib
import mimetypes
import os
import re
import time
import urllib.parse

from ..base import Adapter, Incoming, PlatformError, Result, register


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
