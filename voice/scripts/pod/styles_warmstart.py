"""Build the step-0 checkpoint of her five-style voice from her phone voice (a single-speaker Piper checkpoint),
so that at step 0 every sid speaks exactly as that voice does, and the run resumes its training state.

Usage (piper-env, from /w/piper1-gpl):
  python styles_warmstart.py --ckpt keep-epoch=974.ckpt --out ws.ckpt [--num-speakers 5] [--gin 32]
      [--emb-std 0.1] [--anchor0] [--cond-lr-mult 10] [--batch-size 48] [--seed 20261124] [--report r.json]

What it writes (a checkpoint Lightning resumes with --ckpt_path, strictly):
- state_dict: every tensor of the base copied bit for bit. The new tensors are the speaker conditioning only:
    emb_g.weight                      N(0, emb-std); row 0 exactly zero with --anchor0
    dec.cond, dp.cond (plain convs)   weight and bias zero
    *.cond_layer (weight-normed)      weight_g and bias zero, weight_v as Piper initialises it (random), so the
                                      projection is exactly zero and still has a gradient into weight_g
  In piper1-gpl 46c3c71 the speaker embedding g enters the generator only through those projections, each one
  added to an activation (the text encoder takes no g), so every one of them adds exactly 0 at step 0.
- optimizer_states: the base generator optimizer's AdamW moments carried over by parameter name (the new
  tensors have none and start fresh); with --cond-lr-mult the new tensors are a second group at that multiple
  of the learning rate (styles_patch.py builds the same two groups). The discriminator's state is unchanged.
- lr_schedulers, loops, epoch, global_step: the base's, so the run continues from its epoch (the rate restart
  is PIPER_RESUME_LR's job); callbacks' state is dropped (it named the base run's folders).
- hyper_parameters: the base's with num_speakers, gin_channels, batch_size set, and no warmstart path.
"""
import argparse
import hashlib
import json
import re
import sys

import torch

from piper.train.vits.lightning import VitsModel

COND_RE = re.compile(r"(^|\.)(emb_g|cond|cond_layer)\.")


def model_from(hp):
    return VitsModel(**{k: v for k, v in hp.items() if not k.startswith("_")})


def digest(sd):
    h = hashlib.sha256()
    for k in sorted(sd):
        h.update(k.encode())
        h.update(sd[k].detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--num-speakers", type=int, default=5)
    ap.add_argument("--gin", type=int, default=32)
    ap.add_argument("--emb-std", type=float, default=0.1)
    ap.add_argument("--anchor0", action="store_true")
    ap.add_argument("--cond-lr-mult", type=float, default=None)
    ap.add_argument("--batch-size", type=int, default=None)
    ap.add_argument("--seed", type=int, default=20261124)
    ap.add_argument("--report", default=None)
    a = ap.parse_args()

    ck = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    hp_old = dict(ck["hyper_parameters"])
    assert int(hp_old.get("num_speakers", 1)) == 1 and int(hp_old.get("gin_channels", 0)) == 0, "base is not single-speaker"
    old_sd = ck["state_dict"]

    old = model_from(hp_old)
    old.load_state_dict(old_sd, strict=True)
    old_names = [n for n, _ in old.model_g.named_parameters()]
    opt_g = ck["optimizer_states"][0]
    assert len(opt_g["param_groups"]) == 1 and len(opt_g["param_groups"][0]["params"]) == len(old_names)
    for i, n in enumerate(old_names):  # the base optimizer's index i is the base model's i-th parameter
        st = opt_g["state"].get(i)
        if st is not None:
            assert tuple(st["exp_avg"].shape) == tuple(old_sd["model_g." + n].shape), f"optimizer state {i} is not {n}"

    hp_new = dict(hp_old, num_speakers=a.num_speakers, gin_channels=a.gin, warmstart_ckpt=None, vocoder_warmstart_ckpt=None)
    if a.batch_size:
        hp_new["batch_size"] = a.batch_size
    torch.manual_seed(a.seed)
    new = model_from(hp_new)
    new_sd = new.state_dict()

    fresh, init = [], {}
    gen = torch.Generator().manual_seed(a.seed)
    for k in new_sd:
        if k in old_sd:
            assert new_sd[k].shape == old_sd[k].shape, f"shape differs: {k}"
            new_sd[k] = old_sd[k].clone()
            continue
        assert k.startswith("model_g.") and COND_RE.search(k[len("model_g."):]), f"new tensor that is not speaker conditioning: {k}"
        fresh.append(k)
        if k.endswith("emb_g.weight"):
            w = torch.randn(new_sd[k].shape, generator=gen) * a.emb_std
            if a.anchor0:
                w[0] = 0
            new_sd[k] = w
            init[k] = f"N(0, {a.emb_std})" + (", row 0 zero" if a.anchor0 else "")
        elif k.endswith((".cond.weight", ".cond.bias", ".cond_layer.bias", ".cond_layer.weight_g")):
            new_sd[k] = torch.zeros_like(new_sd[k])
            init[k] = "zero"
        elif k.endswith(".cond_layer.weight_v"):
            init[k] = "Piper's own init (random direction; its scale weight_g is zero)"
        else:
            raise SystemExit(f"no rule for new tensor {k}")
    gone = [k for k in old_sd if k not in new_sd]
    assert not gone, f"base tensors with no place in the new model: {gone[:5]}"
    new.load_state_dict(new_sd, strict=True)
    for k in old_sd:
        assert torch.equal(new.state_dict()[k], old_sd[k]), k

    # The projections really are zero: every sid's conditioning adds nothing.
    g = new.model_g
    with torch.no_grad():
        e = g.emb_g.weight.unsqueeze(-1)
        outs = {"dec.cond": g.dec.cond(e), "dp.cond": g.dp.cond(e), "enc_q.cond_layer": g.enc_q.enc.cond_layer(e)}
        for i, f in enumerate(g.flow.flows):
            if hasattr(f, "enc"):
                outs[f"flow.flows.{i}.cond_layer"] = f.enc.cond_layer(e)
        zero_check = {k: float(v.abs().max()) for k, v in outs.items()}
    assert all(v == 0.0 for v in zero_check.values()), zero_check

    # Optimizer: carry the generator's AdamW moments over by name.
    new_named = [n for n, _ in g.named_parameters()]
    cond_names = [n for n in new_named if COND_RE.search(n)]
    assert sorted("model_g." + n for n in cond_names) == sorted(fresh), "conditioning tensors are not exactly the new ones"
    if a.cond_lr_mult:
        groups = [[n for n in new_named if not COND_RE.search(n)], cond_names]
    else:
        groups = [new_named]
    old_index = {n: i for i, n in enumerate(old_names)}
    g0 = opt_g["param_groups"][0]
    state, param_groups, j = {}, [], 0
    for gi, names in enumerate(groups):
        mult = 1.0 if gi == 0 else a.cond_lr_mult
        pg = {k: v for k, v in g0.items() if k != "params"}
        pg["params"] = list(range(j, j + len(names)))
        if a.cond_lr_mult:
            pg["lr_mult"] = mult
            pg["lr"] = g0["lr"] * mult
            pg["initial_lr"] = g0["initial_lr"] * mult
        for n in names:
            if n in old_index and old_index[n] in opt_g["state"]:
                state[j] = opt_g["state"][old_index[n]]
            j += 1
        param_groups.append(pg)
    carried = len(state)
    assert carried == len(opt_g["state"]), "some optimizer state was not carried over"
    ck["optimizer_states"][0] = {"state": state, "param_groups": param_groups}
    sch = dict(ck["lr_schedulers"][0])
    if a.cond_lr_mult:
        sch["base_lrs"] = [sch["base_lrs"][0], sch["base_lrs"][0] * a.cond_lr_mult]
        sch["_last_lr"] = [sch["_last_lr"][0], sch["_last_lr"][0] * a.cond_lr_mult]
    ck["lr_schedulers"][0] = sch

    ck["state_dict"] = new_sd
    ck["hyper_parameters"] = hp_new
    ck.pop("callbacks", None)
    torch.save(ck, a.out)

    n_new = sum(new_sd[k].numel() for k in fresh)
    infer_new = sum(new_sd[k].numel() for k in fresh if ".enc_q." not in k and not k.endswith("weight_g"))
    rep = {
        "base": a.ckpt, "out": a.out, "epoch": ck["epoch"], "global_step": ck["global_step"],
        "num_speakers": a.num_speakers, "gin_channels": a.gin, "emb_std": a.emb_std, "anchor0": a.anchor0,
        "cond_lr_mult": a.cond_lr_mult, "batch_size": hp_new.get("batch_size"),
        "copied_tensors": len(old_sd), "copied_bit_exact": True, "base_digest": digest(old_sd),
        "new_digest_of_copied": digest({k: new_sd[k] for k in old_sd}),
        "new_tensors": {k: [list(new_sd[k].shape), init[k]] for k in fresh},
        "new_params": n_new, "new_params_in_the_phone_graph_about": infer_new,
        "conditioning_output_max_abs_at_step0": zero_check,
        "optimizer": {"groups": [len(x) for x in groups], "moments_carried": carried,
                      "lrs": [pg["lr"] for pg in param_groups]},
    }
    assert rep["base_digest"] == rep["new_digest_of_copied"]
    if a.report:
        json.dump(rep, open(a.report, "w"), indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k != "new_tensors"}, indent=1))
    print("new tensors:", len(fresh))


if __name__ == "__main__":
    sys.exit(main())
