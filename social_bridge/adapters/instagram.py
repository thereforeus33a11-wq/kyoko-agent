"""Instagram professional accounts (Business / Creator): posts, Reels, carousels, stories, comments, DMs."""
import hashlib
import logging
import mimetypes
import os
import re
import time
import urllib.parse
from datetime import datetime

from ..base import Adapter, Incoming, PlatformError, Result, register


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
