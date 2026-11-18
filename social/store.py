"""Opt-in state, rolling chat history, and append-only transcripts."""
import json
import time
from collections import defaultdict, deque
from pathlib import Path


class Store:
    def __init__(self, data_dir: Path, history_turns: int, allowed: set[int]):
        self.dir = data_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "transcripts").mkdir(exist_ok=True)
        self.state_file = self.dir / "state.json"
        state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        self.opted_in: set[int] = set(state.get("opted_in", [])) | allowed
        self.opted_out: set[int] = set(state.get("opted_out", []))
        self.disclosed: set[int] = set(state.get("disclosed", []))
        self.history: dict[str, deque] = defaultdict(lambda: deque(maxlen=history_turns))
        self.dm_starts: deque[float] = deque()

    def save(self) -> None:
        self.state_file.write_text(json.dumps({
            "opted_in": sorted(self.opted_in),
            "opted_out": sorted(self.opted_out),
            "disclosed": sorted(self.disclosed),
        }, indent=2))

    # --- consent -------------------------------------------------------
    def opt_in(self, uid: int) -> None:
        self.opted_out.discard(uid)
        self.opted_in.add(uid)
        self.save()

    def opt_out(self, uid: int) -> None:
        self.opted_in.discard(uid)
        self.opted_out.add(uid)
        self.save()

    def may_dm(self, uid: int) -> bool:
        return uid in self.opted_in and uid not in self.opted_out

    def take_dm_slot(self, per_hour: int) -> bool:
        now = time.time()
        while self.dm_starts and now - self.dm_starts[0] > 3600:
            self.dm_starts.popleft()
        if len(self.dm_starts) >= per_hour:
            return False
        self.dm_starts.append(now)
        return True

    # --- conversation --------------------------------------------------
    def add(self, convo: str, role: str, content: str, who: str = "") -> None:
        self.history[convo].append({"role": role, "content": content})
        self.log(convo, {"role": role, "who": who, "content": content})

    def log(self, convo: str, entry: dict) -> None:
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **entry}
        with open(self.dir / "transcripts" / f"{convo}.jsonl", "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
