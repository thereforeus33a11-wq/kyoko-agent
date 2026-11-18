"""X (Twitter) API v2: posts, replies, DMs; polls mentions and the DM inbox."""
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

from ..base import Adapter, Incoming, PlatformError, Result, oauth1_header, register


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
