"""CLI: python -m social_bridge [init|check|serve|tools|send]"""
import argparse
import json
import logging
import sys
from pathlib import Path

from .base import ADAPTERS
from . import adapters  # noqa: F401  (registers every platform)
from .core import Bridge, Responder
from .server import call_tool, serve, tool_schemas

DEFAULT_CONFIG = "social_bridge.json"


def template():
    return {
        "mode": "review",
        "host": "127.0.0.1",
        "port": 8765,
        "api_token": "",
        "data_dir": "social_data",
        "responder": {
            "enabled": False,
            "url": "http://127.0.0.1:11434/v1/chat/completions",
            "model": "llama3.1:8b",
            "api_key": "",
            "system_prompt": "",
            "platforms": [],
            "kinds": ["dm", "mention", "comment", "reply"],
        },
        "platforms": {
            name: {"enabled": False, **{k: "" for k in cls.config_keys}}
            for name, cls in sorted(ADAPTERS.items())
        },
    }


def load_config(path):
    p = Path(path)
    if not p.exists():
        sys.exit(f"No config at {p}. Run: python -m social_bridge init")
    return json.loads(p.read_text())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="social_bridge")
    ap.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="write a config template listing every platform's settings")
    sub.add_parser("check", help="log in to every enabled platform and print the account name")
    sub.add_parser("platforms", help="list supported platforms and their settings")
    s = sub.add_parser("serve", help="run the API + dashboard + inbox polling")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    sub.add_parser("tools", help="print the tool definitions to give your AI")
    snd = sub.add_parser("send", help="send something right now (skips the queue)")
    snd.add_argument("platform")
    snd.add_argument("action", choices=["post", "comment", "dm"])
    snd.add_argument("text")
    snd.add_argument("--target")
    snd.add_argument("--title")
    snd.add_argument("--link")
    snd.add_argument("--media", nargs="*")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "init":
        p = Path(args.config)
        if p.exists():
            sys.exit(f"{p} already exists")
        p.write_text(json.dumps(template(), indent=2))
        print(f"Wrote {p}. Fill in the platforms you want and set \"enabled\": true.")
        return
    if args.cmd == "platforms":
        for name, cls in sorted(ADAPTERS.items()):
            print(f"\n{cls.label} ({name}) — actions: {', '.join(cls.actions)}")
            for k, d in cls.config_keys.items():
                print(f"  {k}: {d}")
            for act, d in cls.target_help.items():
                print(f"  target for {act}: {d}")
        return

    cfg = load_config(args.config)
    bridge = Bridge(cfg)
    if args.cmd == "check":
        for name, st in bridge.check().items():
            print(f"{name:12} {'OK  ' + str(st['account']) if not st['error'] else 'FAIL ' + st['error']}")
        return
    if args.cmd == "tools":
        print(json.dumps(tool_schemas(bridge), indent=2))
        return
    if args.cmd == "send":
        opts = {k: getattr(args, k) for k in ("title", "link", "media") if getattr(args, k)}
        bridge.mode = "auto"
        a = bridge.submit(args.platform, args.action, args.text, target=args.target, opts=opts, source="cli")
        print(json.dumps(a, indent=2, default=str))
        return
    if args.cmd == "serve":
        bridge.check()
        if (cfg.get("responder") or {}).get("enabled"):
            Responder(bridge, cfg["responder"]).attach()
        bridge.start()
        httpd = serve(bridge, args.host or cfg.get("host", "127.0.0.1"), args.port or cfg.get("port", 8765),
                      cfg.get("api_token", ""))
        print(f"Dashboard: http://{httpd.server_address[0]}:{httpd.server_address[1]}/   (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            bridge.stop()


if __name__ == "__main__":
    main()

__all__ = ["main", "call_tool"]
