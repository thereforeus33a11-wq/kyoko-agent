"""Discord bot account over the REST API only (no gateway connection)."""
import json
import logging
import mimetypes
import os
import re
import time
import urllib.parse

from ..base import Adapter, Incoming, PlatformError, Result, register


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
