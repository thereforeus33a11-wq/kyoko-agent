"""Test double for social_bridge.base.Http: records requests, replays canned responses."""
import json

from social_bridge.base import Http


class FakeHttp(Http):
    """Usage:
        http = FakeHttp("reddit")
        http.add("POST", "https://oauth.reddit.com/api/submit", {"json": {...}})   # exact URL (query ignored)
        http.add("GET", "re:^https://api\\.x\\.com/2/users/", {...})              # regex prefix 're:'
        adapter = RedditAdapter(cfg, http)
        ...
        http.calls -> list of dicts: method, url, params, json, data, headers, files
    Responses are consumed in order per (method, url) route; the last one repeats.
    A response may be a dict/list (200 JSON), or a tuple (status, body) or (status, body, headers).
    Unmatched requests raise AssertionError so tests fail loudly.
    """

    def __init__(self, platform="test"):
        super().__init__(platform, max_retries=2)
        self.routes = []
        self.calls = []
        self.sleep = lambda s: None

    def add(self, method, url, *responses):
        self.routes.append([method.upper(), url, list(responses)])
        return self

    def _match(self, method, url):
        import re
        base = url.split("?", 1)[0]
        for route in self.routes:
            m, u, resps = route
            if m != method.upper():
                continue
            if u.startswith("re:"):
                if re.search(u[3:], url):
                    return route
            elif u == base or u == url:
                return route
        return None

    def _send(self, method, url, params=None, json_body=None, data=None, headers=None, files=None, auth=None):
        self.calls.append({"method": method.upper(), "url": url, "params": params, "json": json_body,
                           "data": data, "headers": headers or {}, "files": files, "auth": auth})
        route = self._match(method, url)
        if route is None:
            raise AssertionError(f"unexpected request: {method} {url}")
        resps = route[2]
        resp = resps.pop(0) if len(resps) > 1 else resps[0]
        status, headers_out = 200, {}
        if isinstance(resp, tuple):
            status, headers_out, resp = resp[0], (resp[2] if len(resp) > 2 else {}), resp[1]
        if isinstance(resp, (bytes, bytearray)):
            body = bytes(resp)
        elif resp is None:
            body = b""
        elif isinstance(resp, str):
            body = resp.encode()
        else:
            body = json.dumps(resp).encode()
        return status, headers_out, body

    def last(self, method=None, contains=""):
        for c in reversed(self.calls):
            if (method is None or c["method"] == method.upper()) and contains in c["url"]:
                return c
        raise AssertionError(f"no call {method} *{contains}*")
