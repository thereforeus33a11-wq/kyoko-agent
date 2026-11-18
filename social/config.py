"""Settings, read from environment variables (or a .env file next to this package)."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _ids(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(" ", "").split(",") if x}


@dataclass
class Config:
    discord_token: str
    overseer_id: int                 # your Discord user ID: only you can approve or command
    oversight_channel_id: int        # private channel where drafts and transcripts show up
    ollama_model: str = "llama3.1:8b"
    ollama_host: str | None = None
    system_prompt: str = ""
    mode: str = "review"             # review = you approve every message; watch = auto-send, mirrored to you
    disclosure: str = "🤖 Heads up: I'm an AI. A human reviews this conversation."
    allowed_dm_users: set[int] = field(default_factory=set)
    max_new_dms_per_hour: int = 5
    history_turns: int = 20
    data_dir: Path = Path("social_data")

    @classmethod
    def from_env(cls) -> "Config":
        _load_dotenv(Path(__file__).resolve().parent / ".env")
        prompt = os.environ.get("SYSTEM_PROMPT", "")
        prompt_file = os.environ.get("SYSTEM_PROMPT_FILE")
        if prompt_file and Path(prompt_file).exists():
            prompt = Path(prompt_file).read_text()
        mode = os.environ.get("MODE", "review").lower()
        if mode not in ("review", "watch"):
            raise SystemExit("MODE must be 'review' or 'watch'")
        try:
            return cls(
                discord_token=os.environ["DISCORD_TOKEN"],
                overseer_id=int(os.environ["OVERSEER_ID"]),
                oversight_channel_id=int(os.environ["OVERSIGHT_CHANNEL_ID"]),
                ollama_model=os.environ.get("OLLAMA_MODEL", "llama3.1:8b"),
                ollama_host=os.environ.get("OLLAMA_HOST") or None,
                system_prompt=prompt or "You are a friendly, casual chat companion on Discord. Keep replies short.",
                mode=mode,
                disclosure=os.environ.get("DISCLOSURE", cls.disclosure),
                allowed_dm_users=_ids(os.environ.get("ALLOWED_DM_USERS", "")),
                max_new_dms_per_hour=int(os.environ.get("MAX_NEW_DMS_PER_HOUR", "5")),
                history_turns=int(os.environ.get("HISTORY_TURNS", "20")),
                data_dir=Path(os.environ.get("DATA_DIR", "social_data")),
            )
        except KeyError as e:
            raise SystemExit(f"Missing required setting: {e.args[0]} (see social/.env.example)")
