"""Patch Piper 1.8 (piper1-gpl 46c3c71) for her five-style voice (styles as speaker ids), the way mixed_patch.py
patches it. Run after ddp_patch.py, mos_patch.py and mixed_patch.py. Idempotent. Every change is off unless its
variable is set, so the patched Piper trains exactly as before without them.

1. configure_optimizers: with PIPER_STYLE_COND_LR_MULT=M, the generator's speaker conditioning (emb_g and every
   cond / cond_layer projection: the parameters a single-speaker voice does not have) is a second parameter
   group at M times the learning rate; everything her voice already had stays in the first group at the rate
   itself. The group carries "lr_mult", so the rate restart below keeps the ratio.
2. _mixed_patch_resume_lr: a restarted rate is multiplied by each group's lr_mult (1 when there is none).
3. on_train_start: with PIPER_STYLE_ANCHOR0=1, sid 0 stays at no conditioning: emb_g row 0 and the bias of every
   conditioning projection must start at exactly zero (styles_warmstart.py --anchor0 writes them so) and their
   gradients are zeroed, so they stay zero. The conditioning a style adds is then W e_sid, and for sid 0 it is
   nothing: sid 0 is the shared network alone, as keep-epoch=974 was. (The biases are redundant: each
   conditioning sum is added where the layer already has a bias of its own.)
4. With PIPER_STYLE_REPORT=1, one log line per training epoch: batches and steps per second, how many lines of
   each sid were trained and how many batches held every sid, the mean |conditioning| each sid gets in the
   decoder, duration predictor, flow and posterior encoder, and the peak GPU memory. Reporting only.
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


lt = f"{ROOT}/vits/lightning.py"
s = open(lt, encoding="utf-8").read()
assert "[mixed_patch] restart the learning rate" in s, "apply mixed_patch.py first"

print("cond lr group:", patch(lt, '''            torch.optim.AdamW(
                self.model_g.parameters(),
                lr=self.hparams.learning_rate,''', '''            torch.optim.AdamW(
                self._styles_patch_g_params(),  # [styles_patch] cond lr group
                lr=self.hparams.learning_rate,''', "[styles_patch] cond lr group"))

print("resume lr keeps lr_mult:", patch(lt, '''                group["lr"] = lr * scale
''', '''                group["lr"] = lr * scale * group.get("lr_mult", 1.0)  # [styles_patch] lr_mult
''', "[styles_patch] lr_mult"))

print("start, count, report:", patch(lt, '''    def on_train_start(self) -> None:
        self._reassert_scheduler_gammas()
        self._mixed_patch_resume_lr()
''', '''    def on_train_start(self) -> None:
        self._reassert_scheduler_gammas()
        self._mixed_patch_resume_lr()
        self._styles_patch_start()

    # [styles_patch] her styles as speaker ids
    _STYLES_COND = r"(^|\\.)(emb_g|cond|cond_layer)\\."

    def _styles_patch_g_params(self):
        """[styles_patch] the generator's parameters; with PIPER_STYLE_COND_LR_MULT the speaker conditioning is a
        second group at that multiple of the learning rate."""
        import os
        import re

        mult = os.environ.get("PIPER_STYLE_COND_LR_MULT")
        if not mult:
            return self.model_g.parameters()
        mult = float(mult)
        cond_re = re.compile(self._STYLES_COND)
        named = list(self.model_g.named_parameters())
        shared = [p for n, p in named if not cond_re.search(n)]
        cond = [p for n, p in named if cond_re.search(n)]
        assert cond, "[styles_patch] PIPER_STYLE_COND_LR_MULT is set but the model has no speaker conditioning"
        _LOGGER.info(
            "[styles_patch] generator: %s shared tensors at the learning rate, %s conditioning tensors at %sx",
            len(shared), len(cond), mult,
        )
        return [
            {"params": shared, "lr_mult": 1.0},
            {"params": cond, "lr": self.hparams.learning_rate * mult, "lr_mult": mult},
        ]

    def _styles_patch_start(self) -> None:
        """[styles_patch] anchor sid 0 at no conditioning (PIPER_STYLE_ANCHOR0=1); start the report."""
        import os
        import re
        import time

        self._styles_report = None
        if os.environ.get("PIPER_STYLE_REPORT") == "1":
            self._styles_report = {"t0": time.time(), "t_last": None, "batches": 0, "counts": None, "all": None}
        if os.environ.get("PIPER_STYLE_ANCHOR0") != "1" or getattr(self, "_styles_anchored", False):
            return
        g = self.model_g
        assert g.n_speakers > 1, "[styles_patch] PIPER_STYLE_ANCHOR0 needs a multi-speaker model"
        cond_re = re.compile(self._STYLES_COND)
        with torch.no_grad():
            assert float(g.emb_g.weight[0].abs().max()) == 0.0, "[styles_patch] emb_g[0] is not zero"

        def zero_row0(grad):
            grad = grad.clone()
            grad[0] = 0
            return grad

        g.emb_g.weight.register_hook(zero_row0)
        biases = 0
        for name, p in g.named_parameters():
            if cond_re.search(name) and name.endswith(".bias"):
                with torch.no_grad():
                    assert float(p.abs().max()) == 0.0, f"[styles_patch] {name} is not zero"
                p.register_hook(torch.zeros_like)
                biases += 1
        self._styles_anchored = True
        _LOGGER.info("[styles_patch] sid 0 anchored: emb_g[0] and %s conditioning biases held at zero", biases)

    def _styles_patch_count(self, batch) -> None:
        """[styles_patch] count the sids trained this epoch (on the GPU; read once per epoch)."""
        st = getattr(self, "_styles_report", None)
        if st is None or batch.speaker_ids is None:
            return
        import time

        c = torch.bincount(batch.speaker_ids.detach().view(-1), minlength=self.model_g.n_speakers)
        a = (c > 0).all().long()
        st["counts"] = c if st["counts"] is None else st["counts"] + c
        st["all"] = a if st["all"] is None else st["all"] + a
        st["batches"] += 1
        if st["batches"] == 1:
            st["t_first"] = time.time()
        st["t_last"] = time.time()

    def _styles_patch_report(self) -> None:
        """[styles_patch] one line per epoch (PIPER_STYLE_REPORT=1). Reporting only: never stops a run."""
        import os
        import time

        if os.environ.get("PIPER_STYLE_REPORT") != "1":
            return
        st = getattr(self, "_styles_report", None) or {}
        try:
            msg = [f"epoch {self.current_epoch}"]
            if st.get("batches"):
                wall = time.time() - st["t0"]
                n = st["batches"]
                steady = (n - 1) / max(1e-6, st["t_last"] - st["t_first"]) if n > 1 else 0.0
                msg.append(f"{n} batches, epoch wall {wall:.1f} s, {steady:.2f} it/s between first and last batch")
                msg.append(f"lines per sid {st['counts'].tolist()}, batches holding every sid {int(st['all'])}/{n}")
            g = self.model_g
            if g.n_speakers > 1:
                with torch.no_grad():
                    e = g.emb_g.weight.detach().float().unsqueeze(-1)

                    def mean_abs(layer):
                        return layer(e).abs().mean(dim=(1, 2)).tolist()

                    flow = [mean_abs(f.enc.cond_layer) for f in g.flow.flows if hasattr(f, "enc")]
                    flow = [sum(v) / len(flow) for v in zip(*flow)]
                    parts = {"dec": mean_abs(g.dec.cond), "dp": mean_abs(g.dp.cond), "flow": flow,
                             "enc_q": mean_abs(g.enc_q.enc.cond_layer)}
                msg.append("mean |cond| per sid " + ", ".join(
                    f"{k} " + " ".join(f"{v:.3g}" for v in vals) for k, vals in parts.items()))
                msg.append("|emb| per sid " + " ".join(f"{v:.3g}" for v in g.emb_g.weight.detach().norm(dim=1).tolist()))
            if torch.cuda.is_available():
                msg.append(f"peak GPU memory {torch.cuda.max_memory_allocated() / 2**30:.1f} GiB allocated, "
                           f"{torch.cuda.max_memory_reserved() / 2**30:.1f} GiB reserved")
            _LOGGER.info("[styles_patch] %s", "; ".join(msg))
        except Exception:  # pragma: no cover - reporting only
            _LOGGER.warning("[styles_patch] report failed", exc_info=True)
        self._styles_report = {"t0": time.time(), "t_last": None, "batches": 0, "counts": None, "all": None}
''', "[styles_patch] her styles as speaker ids"))

print("count in training_step:", patch(lt, '''        opt_g, opt_d = self.optimizers()
        loss_g, loss_d, metrics = self._compute_loss(batch)
''', '''        opt_g, opt_d = self.optimizers()
        loss_g, loss_d, metrics = self._compute_loss(batch)
        self._styles_patch_count(batch)  # [styles_patch]
''', "self._styles_patch_count(batch)"))

print("report at epoch end:", patch(lt, '''    def on_train_epoch_end(self) -> None:
''', '''    def on_train_epoch_end(self) -> None:
        self._styles_patch_report()  # [styles_patch]
''', "self._styles_patch_report()"))
