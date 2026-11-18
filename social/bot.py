"""Discord bridge with a human overseer.

Everything the AI wants to say becomes a *draft* in your private oversight channel:
  ✅ react  -> send it
  ❌ react  -> drop it
  reply to the draft with text -> send your edited version instead
Incoming messages are mirrored there too, so you see the whole interaction live.

Overseer commands (type them in the oversight channel):
  !post <channel_id> <what to post about>
  !comment <channel_id> <message_id> <what to say>
  !dm <user_id> <what to open with>        (user must be opted in)
  !optin <user_id> / !optout <user_id>
  !mode review|watch
  !pause / !resume
  !status
People talking to the bot can type !stop to opt out of DMs, or !start to opt back in.
"""
import logging
from dataclasses import dataclass

import discord

from .brain import Brain
from .config import Config
from .store import Store

log = logging.getLogger("social")
APPROVE, REJECT = "✅", "❌"


@dataclass
class Draft:
    convo: str                       # transcript / history key
    target: discord.abc.Messageable  # where it will be sent
    text: str
    reply_to: discord.Message | None = None
    recipient_id: int | None = None  # set for DMs (used for disclosure)


class SocialBot(discord.Client):
    def __init__(self, cfg: Config):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        intents.members = False
        super().__init__(intents=intents)
        self.cfg = cfg
        self.mode = cfg.mode
        self.paused = False
        self.brain = Brain(cfg.ollama_model, cfg.system_prompt, cfg.ollama_host)
        self.store = Store(cfg.data_dir, cfg.history_turns, cfg.allowed_dm_users)
        self.pending: dict[int, Draft] = {}  # oversight message id -> draft
        self.oversight: discord.TextChannel | None = None

    # ------------------------------------------------------------------ setup
    async def on_ready(self):
        ch = self.get_channel(self.cfg.oversight_channel_id) or await self.fetch_channel(self.cfg.oversight_channel_id)
        self.oversight = ch
        await ch.send(f"🟢 Online as **{self.user}** · mode `{self.mode}` · model `{self.cfg.ollama_model}`")
        log.info("Logged in as %s", self.user)

    # --------------------------------------------------------------- messages
    async def on_message(self, msg: discord.Message):
        if msg.author.bot:
            return
        if msg.channel.id == self.cfg.oversight_channel_id:
            if msg.author.id == self.cfg.overseer_id:
                await self.handle_overseer(msg)
            return

        is_dm = isinstance(msg.channel, discord.DMChannel)
        mentioned = self.user in msg.mentions
        replied_to_me = (
            msg.reference is not None
            and isinstance(msg.reference.resolved, discord.Message)
            and msg.reference.resolved.author.id == self.user.id
        )
        if not (is_dm or mentioned or replied_to_me):
            return

        uid = msg.author.id
        text = msg.clean_content.replace(f"@{self.user.display_name}", "").strip()
        convo = f"dm-{uid}" if is_dm else f"ch-{msg.channel.id}"

        if is_dm and text.lower() == "!stop":
            self.store.opt_out(uid)
            await msg.channel.send("Got it — I won't message you again unless you type `!start`.")
            await self.mirror(f"🚫 {msg.author} opted out of DMs.")
            return
        if is_dm and text.lower() == "!start":
            self.store.opt_in(uid)
            await msg.channel.send("You're opted back in. 👋")
            await self.mirror(f"✅ {msg.author} opted in to DMs.")
            return
        if is_dm and uid not in self.store.opted_out:
            self.store.opt_in(uid)  # they started the conversation

        speaker = msg.author.display_name
        self.store.add(convo, "user", f"{speaker}: {text}", who=str(msg.author))
        where = "DM" if is_dm else f"#{getattr(msg.channel, 'name', msg.channel.id)}"
        await self.mirror(f"📥 **{msg.author}** ({where}): {text}")

        if self.paused:
            return
        async with msg.channel.typing():
            reply = await self.brain.write(list(self.store.history[convo]))
        await self.submit(Draft(convo, msg.channel, reply,
                                reply_to=None if is_dm else msg,
                                recipient_id=uid if is_dm else None))

    # ------------------------------------------------------- overseer commands
    async def handle_overseer(self, msg: discord.Message):
        # Replying to a pending draft = send this edited text instead.
        if msg.reference and msg.reference.message_id in self.pending:
            draft = self.pending.pop(msg.reference.message_id)
            draft.text = msg.content
            await self.deliver(draft)
            await msg.add_reaction("📤")
            return

        parts = msg.content.split(maxsplit=1)
        if not parts or not parts[0].startswith("!"):
            return
        cmd, rest = parts[0].lower(), (parts[1] if len(parts) > 1 else "")
        try:
            if cmd == "!post":
                ch_id, topic = rest.split(maxsplit=1)
                ch = await self.fetch_channel(int(ch_id))
                convo = f"ch-{ch.id}"
                text = await self.brain.write(list(self.store.history[convo]),
                                              f"Write a new post for this channel about: {topic}")
                await self.submit(Draft(convo, ch, text))
            elif cmd == "!comment":
                ch_id, m_id, note = rest.split(maxsplit=2)
                ch = await self.fetch_channel(int(ch_id))
                target = await ch.fetch_message(int(m_id))
                convo = f"ch-{ch.id}"
                self.store.add(convo, "user", f"{target.author.display_name}: {target.clean_content}",
                               who=str(target.author))
                text = await self.brain.write(list(self.store.history[convo]),
                                              f"Reply to the last message. Guidance: {note}")
                await self.submit(Draft(convo, ch, text, reply_to=target))
            elif cmd == "!dm":
                u_id, opener = rest.split(maxsplit=1)
                uid = int(u_id)
                if not self.store.may_dm(uid):
                    await msg.reply("⛔ That user hasn't opted in. Ask them to DM the bot first, "
                                    "or `!optin` them once they've agreed.")
                    return
                if not self.store.take_dm_slot(self.cfg.max_new_dms_per_hour):
                    await msg.reply("⏳ Hourly DM limit reached.")
                    return
                user = await self.fetch_user(uid)
                convo = f"dm-{uid}"
                text = await self.brain.write(list(self.store.history[convo]),
                                              f"Start a DM conversation with {user.display_name}. Angle: {opener}")
                await self.submit(Draft(convo, await user.create_dm(), text, recipient_id=uid))
            elif cmd == "!optin":
                self.store.opt_in(int(rest)); await msg.add_reaction("👍")
            elif cmd == "!optout":
                self.store.opt_out(int(rest)); await msg.add_reaction("👍")
            elif cmd == "!mode" and rest in ("review", "watch"):
                self.mode = rest; await msg.reply(f"Mode → `{rest}`")
            elif cmd == "!pause":
                self.paused = True; await msg.reply("⏸️ Paused: incoming messages are logged but not answered.")
            elif cmd == "!resume":
                self.paused = False; await msg.reply("▶️ Resumed.")
            elif cmd == "!status":
                await msg.reply(f"mode `{self.mode}` · paused `{self.paused}` · "
                                f"pending drafts `{len(self.pending)}` · opted-in `{len(self.store.opted_in)}`")
            else:
                await msg.reply("Unknown command. See the top of social/bot.py for the list.")
        except (ValueError, discord.HTTPException) as e:
            await msg.reply(f"⚠️ {type(e).__name__}: {e}")

    # ------------------------------------------------------------ draft flow
    async def submit(self, draft: Draft):
        dest = self.describe(draft)
        if self.mode == "watch":
            await self.deliver(draft)
            return
        card = await self.oversight.send(
            f"📝 **Draft → {dest}**\n>>> {draft.text}\n"
            f"\n{APPROVE} send · {REJECT} drop · reply to this message to edit"
        )
        self.pending[card.id] = draft
        await card.add_reaction(APPROVE)
        await card.add_reaction(REJECT)

    async def on_raw_reaction_add(self, ev: discord.RawReactionActionEvent):
        if ev.user_id != self.cfg.overseer_id or ev.message_id not in self.pending:
            return
        emoji = str(ev.emoji)
        if emoji == APPROVE:
            await self.deliver(self.pending.pop(ev.message_id))
        elif emoji == REJECT:
            draft = self.pending.pop(ev.message_id)
            self.store.log(draft.convo, {"role": "rejected", "content": draft.text})
            await self.mirror(f"🗑️ Dropped draft → {self.describe(draft)}")

    async def deliver(self, draft: Draft):
        if draft.recipient_id and not self.store.may_dm(draft.recipient_id):
            await self.mirror(f"⛔ Not sent: {draft.recipient_id} has opted out.")
            return
        text = draft.text
        first_contact = draft.recipient_id and draft.recipient_id not in self.store.disclosed
        if first_contact and self.cfg.disclosure:
            text = f"{self.cfg.disclosure}\n\n{text}"
        try:
            if draft.reply_to:
                await draft.reply_to.reply(text, mention_author=False)
            else:
                await draft.target.send(text)
        except discord.HTTPException as e:
            await self.mirror(f"⚠️ Send failed → {self.describe(draft)}: {e}")
            return
        if first_contact:
            self.store.disclosed.add(draft.recipient_id)
            self.store.save()
        self.store.add(draft.convo, "assistant", draft.text, who="bot")
        await self.mirror(f"📤 **Sent → {self.describe(draft)}**: {draft.text}")

    # --------------------------------------------------------------- helpers
    def describe(self, d: Draft) -> str:
        if d.recipient_id:
            return f"DM <@{d.recipient_id}>"
        name = getattr(d.target, "name", None)
        suffix = " (reply)" if d.reply_to else ""
        return (f"#{name}" if name else str(d.target)) + suffix

    async def mirror(self, text: str):
        if self.oversight:
            await self.oversight.send(text[:2000], allowed_mentions=discord.AllowedMentions.none())


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    cfg = Config.from_env()
    SocialBot(cfg).run(cfg.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
