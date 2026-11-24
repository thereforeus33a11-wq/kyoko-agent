"""Slim copy of a Piper (piper1-gpl) training checkpoint for scoring and export: the generator's inference weights
only (model_g without the posterior encoder enc_q, which only training uses; no discriminator, no optimizer), plus
epoch, global_step and hyper_parameters. Exact: the tensors are copied, not converted.
  python slim_ckpt.py <full.ckpt> <out.gen.pt>                    make a slim
  python slim_ckpt.py --merge <slim.gen.pt> <any full.ckpt of the same run> <out.ckpt>
                                                                   rebuild a checkpoint Piper's export_onnx loads: the
                                                                   full one with the slim's tensors put in (enc_q, the
                                                                   discriminator and the optimizer are the full one's,
                                                                   and do not enter inference)
  python slim_ckpt.py --check <slim.gen.pt> <full.ckpt>            1 if every slim tensor equals the full one's
"""
import sys

import torch


def load(p):
    return torch.load(p, map_location="cpu", weights_only=False, mmap=True)


def keep(k):
    return k.startswith("model_g.") and not k.startswith("model_g.enc_q.")


def main():
    a = sys.argv[1:]
    if a[0] == "--merge":
        slim, full, out = load(a[1]), load(a[2]), a[3]
        assert slim["hyper_parameters"]["num_speakers"] == full["hyper_parameters"]["num_speakers"]
        sd = dict(full["state_dict"])
        for k, v in slim["state_dict"].items():
            assert k in sd and sd[k].shape == v.shape and sd[k].dtype == v.dtype, k
            sd[k] = v
        full["state_dict"] = sd
        full["epoch"], full["global_step"] = slim["epoch"], slim["global_step"]
        torch.save(full, out)
        print("merged", a[1], "into", a[2], "->", out, "epoch", slim["epoch"])
    elif a[0] == "--check":
        slim, full = load(a[1]), load(a[2])
        bad = [k for k, v in slim["state_dict"].items() if not torch.equal(v, full["state_dict"][k])]
        n = sum(1 for k in full["state_dict"] if keep(k))
        print("tensors", len(slim["state_dict"]), "of", n, "inference tensors; differing", len(bad), bad[:5])
        sys.exit(0 if not bad and len(slim["state_dict"]) == n else 1)
    else:
        ck = load(a[0])
        sd = {k: v.clone() for k, v in ck["state_dict"].items() if keep(k)}
        torch.save({"epoch": ck["epoch"], "global_step": ck["global_step"], "hyper_parameters": ck["hyper_parameters"],
                    "state_dict": sd, "slim": "model_g without enc_q; slim_ckpt.py --merge to export"}, a[1])
        print("slim", a[0], "->", a[1], "epoch", ck["epoch"], "tensors", len(sd),
              "MB", round(sum(v.numel() * v.element_size() for v in sd.values()) / 1e6, 1))


if __name__ == "__main__":
    main()
