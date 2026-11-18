# Piper 1.8 sets its config in prepare_data, which Lightning runs on rank 0 only; the other
# ranks then fail in setup. Let setup read the config rank 0 wrote (after Lightning's barrier).
p = "/w/piper1-gpl/src/piper/train/vits/dataset.py"
s = open(p, encoding="utf-8").read()
old = "    def setup(self, stage: str) -> None:\n        assert self.piper_config is not None\n"
new = ("    def setup(self, stage: str) -> None:\n"
       "        if self.piper_config is None and self.config_path.exists():\n"
       "            from piper.config import PiperConfig\n"
       "            with open(self.config_path, \"r\", encoding=\"utf-8\") as config_file:\n"
       "                self.piper_config = PiperConfig.from_dict(json.load(config_file))\n"
       "        assert self.piper_config is not None\n")
if new not in s:
    assert s.count(old) == 1, "setup() not found as expected"
    s = s.replace(old, new)
    open(p, "w", encoding="utf-8").write(s)
print("patched")
