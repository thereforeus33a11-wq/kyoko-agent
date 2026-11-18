"""Lemmy (HTTP API v3, Lemmy 0.19+). Signs in with username + password and sends the JWT as a Bearer token."""
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

from ..base import Adapter, Incoming, PlatformError, Result, register


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
