"""Mastodon (and any Mastodon-API server: Pleroma, Akkoma, GoToSocial...)."""
import html
import re

from ..base import Adapter, Incoming, PlatformError, Result, register


@register
class MastodonAdapter(Adapter):
    name = "mastodon"
    label = "Mastodon"
    actions = ("post", "comment", "dm")
    poll_interval = 60
    config_keys = {
        "instance": "Server base URL, e.g. https://mastodon.social",
        "access_token": "Preferences -> Development -> New application (scopes: read write) -> access token",
        "visibility": "(optional) default post visibility: public | unlisted | private (default public)",
    }
    target_help = {
        "post": "omit (posts to your own timeline)",
        "comment": "status ID or status URL to reply to",
        "dm": "account handle like @user@server or user (local)",
    }

    # ------------------------------------------------------------- helpers
    def _base(self):
        (instance,) = self.need("instance")
        return instance.rstrip("/")

    def _h(self):
        (tok,) = self.need("access_token")
        return {"Authorization": f"Bearer {tok}"}

    def _api(self, method, path, **kw):
        return self.http.request(method, f"{self._base()}{path}", headers=self._h(), **kw)

    @staticmethod
    def _mastodon_text(content):
        text = re.sub(r"<br\s*/?>", "\n", content or "")
        text = re.sub(r"</p>\s*<p>", "\n\n", text)
        return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()

    def _status_id(self, target):
        target = str(target).strip()
        m = re.search(r"/(\d+)/?$", target)
        if target.isdigit():
            return target
        if m:
            # URL from another server: resolve through search so we get the local ID
            if not target.startswith(self._base()):
                res = self._api("GET", "/api/v2/search", params={"q": target, "resolve": "true", "type": "statuses"})
                if res.get("statuses"):
                    return res["statuses"][0]["id"]
            return m.group(1)
        raise PlatformError(self.name, f"can't read a status id from {target!r}")

    def _upload(self, path_or_url):
        if re.match(r"https?://", path_or_url):
            content = self.http.get(path_or_url, raw=True)
            files = {"file": (path_or_url.rsplit("/", 1)[-1] or "image", content)}
        else:
            files = {"file": open(path_or_url, "rb")}
        try:
            return self._api("POST", "/api/v2/media", files=files)["id"]
        finally:
            f = files["file"]
            if hasattr(f, "close"):
                f.close()

    def _create(self, text, **extra):
        body = {"status": text, "visibility": extra.pop("visibility", self.config.get("visibility") or "public")}
        body.update({k: v for k, v in extra.items() if v})
        res = self._api("POST", "/api/v1/statuses", json=body)
        return Result(id=str(res["id"]), url=res.get("url") or "", raw=res)

    # ------------------------------------------------------------- actions
    def whoami(self):
        me = self._api("GET", "/api/v1/accounts/verify_credentials")
        return "@" + me["acct"]

    def post(self, text, target=None, title=None, link=None, media=None):
        if link:
            text = f"{text}\n\n{link}"
        media_ids = [self._upload(m) for m in (media or [])]
        return self._create(text, media_ids=media_ids, spoiler_text=title)

    def comment(self, target, text):
        sid = self._status_id(target)
        parent = self._api("GET", f"/api/v1/statuses/{sid}")
        handle = "@" + parent["account"]["acct"]
        if handle.lower() not in text.lower():
            text = f"{handle} {text}"
        vis = parent.get("visibility") if parent.get("visibility") in ("direct", "private", "unlisted") else None
        return self._create(text, in_reply_to_id=sid, **({"visibility": vis} if vis else {}))

    def dm(self, target, text):
        handle = "@" + str(target).lstrip("@")
        if handle.lower() not in text.lower():
            text = f"{handle} {text}"
        return self._create(text, visibility="direct")

    def poll(self, state):
        params = {"limit": 40, "types[]": ["mention"]}
        if state.get("since_id"):
            params["since_id"] = state["since_id"]
        notes = self._api("GET", "/api/v1/notifications", params=params)
        out = []
        for n in sorted(notes, key=lambda n: int(n["id"])):
            st = n.get("status")
            if not st:
                continue
            is_dm = st.get("visibility") == "direct"
            acct = st["account"]["acct"]
            kind = "dm" if is_dm else ("reply" if st.get("in_reply_to_id") else "mention")
            out.append(Incoming(
                platform=self.name, kind=kind, id=str(st["id"]), author="@" + acct,
                author_id=str(st["account"]["id"]), text=self._mastodon_text(st.get("content")),
                url=st.get("url") or "", thread=str(st.get("conversation_id") or st.get("in_reply_to_id") or st["id"]),
                reply_to={"action": "dm" if is_dm else "comment", "target": acct if is_dm else str(st["id"])},
                raw=n,
            ))
        if notes:
            state["since_id"] = str(max(int(n["id"]) for n in notes))
        return out
