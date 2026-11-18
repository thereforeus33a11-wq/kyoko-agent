"""Telegram Bot API (bot account; updates fetched with getUpdates)."""
import json
import logging
import mimetypes
import os
import re
import urllib.parse

from ..base import Adapter, Incoming, PlatformError, Result, register


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
