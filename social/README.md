# Supervised social bridge (Discord)

Lets the agent post, comment and DM on Discord, while you watch and approve everything.

## How oversight works
- Every incoming message the bot sees is mirrored to your private **oversight channel** (📥).
- Every outgoing message is a **draft** there first: ✅ sends it, ❌ drops it, replying to the draft sends your edited text.
- `!mode watch` makes it auto-send (still mirrored with 📤); `!mode review` goes back to approve-first.
- Full transcripts are saved as JSONL in `social_data/transcripts/`.

## Who it can talk to
- **Anyone who DMs it, @mentions it, or replies to it** — it answers (after your approval in review mode).
- **Bot-started DMs** (`!dm`) only go to people who opted in: they DMed the bot first, are in `ALLOWED_DM_USERS`, or you ran `!optin` after they agreed. `!stop` from them blocks all further DMs.
- The first DM to each person starts with an "I'm an AI" line (`DISCLOSURE` setting).
- New-DM rate limit (`MAX_NEW_DMS_PER_HOUR`, default 5).

The reason for these limits: Discord bans bots that send unsolicited DMs, and its terms require bots to be clearly labelled as bots.

## Setup
1. https://discord.com/developers/applications → New Application → Bot → copy the token.
   Turn on **Message Content Intent** under Privileged Gateway Intents.
2. OAuth2 → URL Generator → scopes `bot`; permissions: Send Messages, Read Message History, Add Reactions, View Channels. Invite it to your server.
3. Make a private channel only you and the bot can see, and copy its ID (enable Developer Mode in Discord to see Copy ID).
4. `cp social/.env.example social/.env` and fill it in.
5. `ollama pull llama3.1:8b` (or set `OLLAMA_MODEL` to your own model, e.g. one built from `Ollama_Modelfile`).
6. `pip install -r social/requirements.txt && python -m social`

## Your friend
Have them join the server (or share one with the bot) and DM it. That opts them in automatically.

## Overseer commands (in the oversight channel)
| Command | Does |
|---|---|
| `!post <channel_id> <topic>` | Drafts a new post in that channel |
| `!comment <channel_id> <message_id> <guidance>` | Drafts a reply to a specific message |
| `!dm <user_id> <angle>` | Drafts a DM opener (opted-in users only) |
| `!optin` / `!optout <user_id>` | Manage DM consent |
| `!mode review\|watch` | Approve-first or auto-send |
| `!pause` / `!resume` | Stop/start replying (still logs) |
| `!status` | Current state |
