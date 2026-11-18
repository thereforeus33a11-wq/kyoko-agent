# Social Bridge

Lets an AI agent post, comment and DM on social platforms through one local API, while you watch everything live and approve it on a dashboard.

```
 your AI (OpenDroid etc.) ──tool calls──▶ Social Bridge ──official APIs──▶ Reddit, X, YouTube, Facebook, ...
                                            │   ▲
                         dashboard / approve│   │ inbox: DMs, mentions, comments, replies
                                            ▼   │
                                           you
```

Two ways to get it:
- **One file:** `dist/social_bridge.py`. Copy it anywhere and run it. It needs only `pip install requests`.
- **Package:** the `social_bridge/` folder (`python -m social_bridge ...`). Use this one if you want to edit it.

## Quick start

```bash
pip install requests
python social_bridge.py init        # writes social_bridge.json with a section for every platform
# fill in the platforms you want, set "enabled": true
python social_bridge.py check       # logs in everywhere and prints the account names
python social_bridge.py serve       # dashboard + API at http://127.0.0.1:8765
```

On Android (Termux): `pkg install python && pip install requests`, then the same commands. Open the dashboard in the phone's browser.

`python social_bridge.py platforms` lists every platform's settings, with where to get each key and what target format each action takes.

## Oversight

Open `http://127.0.0.1:8765/`.

- **Waiting for approval:** every post, comment or DM the AI makes lands here first. You can edit the text, then tap **Send** or **Reject**.
- **Live feed:** shows incoming messages (📥) and what was sent (📤). Failed sends show the error.
- **Review / Auto:** in review mode everything waits for you. In auto mode it sends immediately and still shows in the feed.
- **Pause:** stops auto-sending. Anything new waits in the queue.
- Everything is also saved to disk in `social_data/`: `feed.jsonl`, `inbox.jsonl` and `actions.json`.

## Hooking up your AI

### Option A: tool calling (any agent that supports OpenAI-style tools)
1. `GET /v1/tools` (or `python social_bridge.py tools`) returns the tool definitions. Register them with your agent.
2. When the agent calls a tool, forward it as-is:
   ```
   POST /v1/tool   {"name": "social_dm", "arguments": {"platform": "reddit", "target": "someuser", "text": "hey"}}
   ```
   The response is the queued action (`status: pending | sent | failed`).

| Tool | What it does |
|---|---|
| `social_platforms` | connected platforms, accounts, supported actions |
| `social_post` | new post (`platform`, `text`, optional `target`, `title`, `link`, `media`) |
| `social_comment` | comment on / reply to a post or comment (`target` = ID or URL) |
| `social_dm` | direct message (`target` = user) |
| `social_inbox` | new DMs, mentions, comments and replies since `after` |
| `social_reply` | answer an inbox item by its `seq` (the right action and target are picked automatically) |
| `social_history` | recent back-and-forth in one conversation thread |
| `social_action_status` | whether a queued action was sent, rejected or failed |

Typical agent loop: call `social_inbox(after=N)`, then `social_history` if it needs context, then `social_reply(seq, text)`, and repeat with `after = next`.

### Option B: built-in responder
If your app exposes an OpenAI-compatible chat endpoint (or you run Ollama, LM Studio, llama.cpp server, OpenRouter, etc.), the bridge can draft replies to everything that comes in by itself. Set this in `social_bridge.json`:

```json
"responder": {
  "enabled": true,
  "url": "http://127.0.0.1:11434/v1/chat/completions",
  "model": "llama3.1:8b",
  "api_key": "",
  "system_prompt": "Your persona here",
  "platforms": [],
  "kinds": ["dm", "mention", "comment", "reply"]
}
```
`platforms: []` means all platforms. Drafts go through the same queue, so in review mode you still approve each one.

### Option C: plain HTTP
```bash
curl -X POST localhost:8765/v1/actions -d '{"platform":"x","action":"post","text":"hello"}'
curl 'localhost:8765/v1/inbox?after=0'
curl -X POST localhost:8765/v1/reply -d '{"seq":12,"text":"thanks!"}'
curl -X POST localhost:8765/v1/actions/<id>/approve -d '{"text":"edited text"}'
curl -X POST localhost:8765/v1/mode -d '{"mode":"auto"}'
```
If `api_token` is set in the config, add `-H "Authorization: Bearer <token>"`. The dashboard asks for the token once.

## Config reference (top level)

| Key | Default | |
|---|---|---|
| `mode` | `review` | `review` or `auto` |
| `host` / `port` | `127.0.0.1` / `8765` | use `0.0.0.0` to reach the dashboard from another device on your network |
| `api_token` | empty | require `Authorization: Bearer <token>` on the API |
| `data_dir` | `social_data` | logs and state |
| `replay_backlog` | `false` | when `false`, the first poll of each platform marks existing messages as already seen |
| `platforms.<name>.poll_interval` | per platform | seconds between inbox checks (`0` = never poll) |

## Platforms

<!-- PLATFORM_TABLE -->

## Adding a platform
Subclass `Adapter` in `social_bridge/adapters/<name>.py` (see `mastodon.py`), decorate it with `@register`, add the module name to `_MODULES` in `adapters/__init__.py`, then run `python tools/build_single_file.py` to rebuild the single file. Tests use `tests/fakehttp.py`: `python -m pytest -q tests`.
