"""Facebook Pages via the Graph API: Page posts, comments, Messenger DMs; polls Messenger, comments and tags."""
import base64
import hashlib
import hmac
import logging
import mimetypes
import os
import re
import urllib.parse
from datetime import datetime

from ..base import Adapter, Incoming, PlatformError, Result, register


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
