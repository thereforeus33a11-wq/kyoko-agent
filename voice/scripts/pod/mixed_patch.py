"""Patch Piper 1.8 (piper1-gpl 46c3c71) for her bilingual fine-tune, the way ddp_patch.py patches it.
Run after ddp_patch.py and mos_patch.py. Idempotent. Every change is off unless its variable is set,
so the patched Piper trains exactly as before without them.

1. dataset.py, phonemize step: with PIPER_MIXED_DIR (the folder holding mix_phonemize.py,
   en_phonemize.py and en_ipa_table.json) and PIPER_CMUDICT set, phoneme_type "japanese" reads each
   line with MixedPhonemizer: her Japanese still goes through the same JapanesePhonemizer (a pure
   Japanese sentence is passed whole, byte-identical to before), English through the table. A line
   it cannot read stops the run instead of being trained silently wrong.
2. dataset.py, split: with PIPER_VAL_IDS (a file of wav names, one per line) those utterances are the
   validation set (the first num_test_examples of them the test set) and everything else trains,
   instead of a random split.
3. __main__.py: with PIPER_KEEP_EVERY=N, also keep a checkpoint every N epochs (in PIPER_KEEP_DIR),
   next to Piper's last.ckpt and best-val_mel ones.
4. lightning.py: with PIPER_RESUME_LR on a resumed run, the generator learning rate restarts at that
   value (the discriminator's at the same ratio as configured) and anneals to PIPER_RESUME_LR_FINAL
   (a ratio, default 0.33) of it over the epochs left. A finished 800-epoch run otherwise continues at
   its end-of-anneal 1e-5 and keeps decaying.
"""
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/w/piper1-gpl/src/piper/train"


def patch(path, old, new, marker):
    s = open(path, encoding="utf-8").read()
    if marker in s:
        return "already"
    assert s.count(old) == 1, f"{path}: anchor not found exactly once:\n{old[:200]}"
    open(path, "w", encoding="utf-8").write(s.replace(old, new))
    return "patched"


ds = f"{ROOT}/vits/dataset.py"
print("phonemize:", patch(ds, '''            japanese_phonemizer = JapanesePhonemizer()

            def phonemize(text: str) -> list[list[str]]:
                return japanese_phonemizer.phonemize(text)
''', '''            japanese_phonemizer = JapanesePhonemizer()

            def phonemize(text: str) -> list[list[str]]:
                return japanese_phonemizer.phonemize(text)

            # [mixed_patch] her lines in Japanese, English or both, read as her phone reads them.
            if os.environ.get("PIPER_MIXED_DIR"):
                import sys as _sys

                _sys.path.insert(0, os.environ["PIPER_MIXED_DIR"])
                from mix_phonemize import MixedPhonemizer

                mixed_phonemizer = MixedPhonemizer(
                    os.path.join(os.environ["PIPER_MIXED_DIR"], "en_ipa_table.json"),
                    os.environ["PIPER_CMUDICT"],
                    ja=japanese_phonemizer,
                )

                def phonemize(text: str) -> list[list[str]]:
                    phonemes = mixed_phonemizer.phonemize(text)
                    if phonemes is None:
                        raise ValueError(f"[mixed_patch] line cannot be read: {text!r}")
                    return phonemes
''', "[mixed_patch] her lines"))

print("split, ids:", patch(ds, '''        all_utts: list[CachedUtterance] = []
''', '''        all_utts: list[CachedUtterance] = []
        utt_ids: list[str] = []  # [mixed_patch] for a fixed validation list
''', "[mixed_patch] for a fixed validation list"))

print("split, keep id:", patch(ds, '''                all_utts.append(
                    CachedUtterance(
                        phoneme_ids_path=phoneme_ids_path,''', '''                utt_ids.append(utt_id)  # [mixed_patch] keep id
                all_utts.append(
                    CachedUtterance(
                        phoneme_ids_path=phoneme_ids_path,''', "[mixed_patch] keep id"))

print("split:", patch(ds, '''        n = len(full_dataset)
        valid_set_size = int(n * self.validation_split)
        num_test = min(self.num_test_examples, max(0, n - valid_set_size - 1))
        train_set_size = n - valid_set_size - num_test
        self.train_dataset, self.test_dataset, self.val_dataset = random_split(
            full_dataset, [train_set_size, num_test, valid_set_size]
        )
''', '''        n = len(full_dataset)
        if os.environ.get("PIPER_VAL_IDS"):
            # [mixed_patch] fixed split: the listed utterances validate, all others train.
            from torch.utils.data import Subset

            with open(os.environ["PIPER_VAL_IDS"], "r", encoding="utf-8") as ids_file:
                wanted = {line.strip() for line in ids_file if line.strip()}
            val_idx = [i for i, u in enumerate(utt_ids) if u in wanted]
            train_idx = [i for i, u in enumerate(utt_ids) if u not in wanted]
            assert val_idx, "[mixed_patch] none of PIPER_VAL_IDS is in the CSV"
            self.train_dataset = Subset(full_dataset, train_idx)
            self.test_dataset = Subset(full_dataset, val_idx[: self.num_test_examples])
            self.val_dataset = Subset(full_dataset, val_idx)
            _LOGGER.info("[mixed_patch] fixed split: %s train, %s validation", len(train_idx), len(val_idx))
            return
        valid_set_size = int(n * self.validation_split)
        num_test = min(self.num_test_examples, max(0, n - valid_set_size - 1))
        train_set_size = n - valid_set_size - num_test
        self.train_dataset, self.test_dataset, self.val_dataset = random_split(
            full_dataset, [train_set_size, num_test, valid_set_size]
        )
''', "[mixed_patch] fixed split"))

main = f"{ROOT}/__main__.py"
print("keep every:", patch(main, '''def _default_callbacks() -> list:
''', '''def _default_callbacks() -> list:
    """[mixed_patch] Piper's callbacks, plus one checkpoint every PIPER_KEEP_EVERY epochs."""
    import os

    callbacks = _piper_default_callbacks()
    every = int(os.environ.get("PIPER_KEEP_EVERY", "0") or 0)
    if every > 0:
        callbacks.append(
            ModelCheckpoint(
                dirpath=os.environ.get("PIPER_KEEP_DIR") or None,
                monitor=None,
                # mode only makes the callback's state key unique (Piper's last.ckpt one is
                # monitor=None, every 1 epoch, mode "min"); with no monitor it ranks nothing.
                mode="max",
                save_top_k=-1,
                every_n_epochs=every,
                filename="keep-epoch={epoch}",
                auto_insert_metric_name=False,
            )
        )
    return callbacks


def _piper_default_callbacks() -> list:
''', "[mixed_patch] Piper's callbacks"))

lt = f"{ROOT}/vits/lightning.py"
print("resume lr:", patch(lt, '''    def on_train_start(self) -> None:
        self._reassert_scheduler_gammas()
''', '''    def on_train_start(self) -> None:
        self._reassert_scheduler_gammas()
        self._mixed_patch_resume_lr()

    def _mixed_patch_resume_lr(self) -> None:
        """[mixed_patch] restart the learning rate of a resumed run (PIPER_RESUME_LR)."""
        import os

        lr = os.environ.get("PIPER_RESUME_LR")
        if not lr or self.current_epoch <= 0:
            return
        lr = float(lr)
        final = float(os.environ.get("PIPER_RESUME_LR_FINAL", "0.33"))
        # On a resumed run current_epoch still names the last finished epoch here.
        left = max(1, int(self.trainer.max_epochs) - int(self.current_epoch) - 1)
        gamma = final ** (1.0 / left)
        optimizers = self.optimizers()
        schedulers = self.lr_schedulers()
        if not isinstance(optimizers, (list, tuple)):
            optimizers = [optimizers]
        if not isinstance(schedulers, (list, tuple)):
            schedulers = [schedulers]
        scales = [1.0, self.hparams.learning_rate_d / self.hparams.learning_rate]
        for optimizer, scheduler, scale in zip(optimizers, schedulers, scales):
            optimizer = getattr(optimizer, "optimizer", optimizer)
            for group in optimizer.param_groups:
                group["lr"] = lr * scale
            scheduler.gamma = gamma
            scheduler._last_lr = [group["lr"] for group in optimizer.param_groups]
        self._resolved_gammas = [gamma, gamma]
        _LOGGER.info(
            "[mixed_patch] resumed at epoch %s: learning rate %s, annealing to %sx over %s epochs (gamma %.6f)",
            self.current_epoch, lr, final, left, gamma,
        )
''', "[mixed_patch] restart the learning rate"))
