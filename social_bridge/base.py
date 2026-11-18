"""Shared building blocks for platform adapters: data types, HTTP client, OAuth1 signing, registry."""
import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
from dataclasses import asdict, dataclass, field

import requests

ACTIONS = ("post", "comment", "dm")
ADAPTERS = {}  # platform name -> Adapter subclass


def register(cls):
    """Class decorator: makes an adapter available under cls.name."""
    ADAPTERS[cls.name] = cls
    return cls


class PlatformError(Exception):
    def __init__(self, platform, message, status=None, body=None):
        super().__init__(f"[{platform}] {message}")
        self.platform = platform
        self.status = status
        self.body = body


class NotSupported(PlatformError):
    pass


@dataclass
class Result:
    """What an outgoing action produced."""
    id: str
    url: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self):
        return {"id": self.id, "url": self.url}


@dataclass
class Incoming:
    """Something that arrived for the account: a DM, a mention, a comment or reply on our content."""
    platform: str
    kind: str          # "dm" | "mention" | "comment" | "reply"
    id: str            # platform-native id of this item (used for de-duplication)
    author: str        # human-readable handle / name
    text: str
    reply_to: dict     # how to answer it: {"action": "comment" | "dm", "target": "<target string>"}
    author_id: str = ""
    url: str = ""
    thread: str = ""   # conversation key used to group history (e.g. DM convo id, post id)
    ts: float = 0.0    # unix seconds (0 if unknown)
    raw: dict = field(default_factory=dict)

    def to_dict(self):
        d = asdict(self)
        d.pop("raw", None)
        return d


class Http:
    """requests wrapper: JSON by default, retries on 429/5xx (honours Retry-After), raises PlatformError."""

    def __init__(self, platform, timeout=30, max_retries=3, user_agent="social-bridge/1.0"):
        self.platform = platform
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent
        self.session = requests.Session()
        self.sleep = time.sleep

    # Tests replace this. Returns (status, headers, body_bytes).
    def _send(self, method, url, params=None, json_body=None, data=None, headers=None, files=None, auth=None):
        resp = self.session.request(method, url, params=params, json=json_body, data=data, headers=headers,
                                    files=files, auth=auth, timeout=self.timeout)
        return resp.status_code, dict(resp.headers), resp.content

    def request(self, method, url, *, params=None, json=None, data=None, headers=None, files=None, auth=None,
                raw=False):
        hdrs = {"User-Agent": self.user_agent}
        hdrs.update(headers or {})
        attempt = 0
        while True:
            status, resp_headers, body = self._send(method, url, params=params, json_body=json, data=data,
                                                    headers=hdrs, files=files, auth=auth)
            if (status == 429 or status >= 500) and attempt < self.max_retries:
                attempt += 1
                wait = _retry_after(resp_headers, attempt)
                self.sleep(wait)
                continue
            if status >= 400:
                text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)
                try:
                    parsed = json_loads(text)
                except ValueError:
                    parsed = text
                raise PlatformError(self.platform, f"HTTP {status} on {method} {url}: {text[:500]}", status, parsed)
            if raw:
                return body
            if not body:
                return {}
            text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)
            try:
                return json_loads(text)
            except ValueError:
                return text

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def put(self, url, **kw):
        return self.request("PUT", url, **kw)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)


def json_loads(text):
    return json.loads(text)


def _retry_after(headers, attempt):
    lowered = {k.lower(): v for k, v in (headers or {}).items()}
    for key in ("retry-after", "x-ratelimit-reset-after"):
        if key in lowered:
            try:
                return min(float(lowered[key]), 120.0)
            except ValueError:
                pass
    return min(2.0 ** attempt, 60.0)


def pct(value):
    """RFC 3986 percent-encoding as required by OAuth 1.0a."""
    return urllib.parse.quote(str(value), safe="~-._")


def oauth1_header(method, url, *, consumer_key, consumer_secret, token, token_secret, params=None,
                  nonce=None, timestamp=None):
    """Build an OAuth 1.0a HMAC-SHA1 Authorization header.

    `params` = form-encoded body params (application/x-www-form-urlencoded) that must be signed.
    Query-string params in `url` are signed automatically. JSON bodies are never signed.
    """
    parts = urllib.parse.urlsplit(url)
    base_url = f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path}"
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(timestamp or int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    pairs += list((params or {}).items()) + list(oauth.items())
    encoded = sorted((pct(k), pct(v)) for k, v in pairs)
    param_string = "&".join(f"{k}={v}" for k, v in encoded)
    base_string = "&".join([method.upper(), pct(base_url), pct(param_string)])
    key = f"{pct(consumer_secret)}&{pct(token_secret)}"
    oauth["oauth_signature"] = base64.b64encode(
        hmac.new(key.encode(), base_string.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{pct(k)}="{pct(v)}"' for k, v in sorted(oauth.items()))


class Adapter:
    """Base class for a platform. Subclasses set the class attributes and override what they support.

    Target conventions (strings, so an AI can pass them straight through):
      post(text, target=...)   target = where to post (subreddit, page id, channel id...) or None for own profile/feed
      comment(target, text)    target = id or URL of the thing being replied to
      dm(target, text)         target = user handle / id / conversation id
    """
    name = ""            # config key, e.g. "reddit"
    label = ""           # display name, e.g. "Reddit"
    actions = ()         # subset of ACTIONS this adapter implements
    poll_interval = 60   # seconds between poll() calls
    config_keys = {}     # key -> description; descriptions starting with "(optional)" are optional
    target_help = {}     # action -> human/AI-readable description of the target format

    def __init__(self, config, http=None):
        self.config = dict(config or {})
        self.http = http or Http(self.name)

    # --- helpers -----------------------------------------------------------
    def need(self, *keys):
        missing = [k for k in keys if not self.config.get(k)]
        if missing:
            raise PlatformError(self.name, f"missing config: {', '.join(missing)}")
        return [self.config[k] for k in keys]

    def unsupported(self, what):
        raise NotSupported(self.name, f"{what} is not supported on {self.label or self.name}")

    # --- interface -----------------------------------------------------------
    def whoami(self):
        """Return the account name this adapter is acting as. Used by `check` and the dashboard."""
        raise NotImplementedError

    def post(self, text, target=None, title=None, link=None, media=None):
        self.unsupported("post")

    def comment(self, target, text):
        self.unsupported("comment")

    def dm(self, target, text):
        self.unsupported("dm")

    def poll(self, state):
        """Return new Incoming items. `state` is a dict the bridge persists between calls (cursors, seen ids)."""
        return []
