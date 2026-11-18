"""Tumblr (API v2, OAuth 1.0a user tokens; posts are created in the Neue Post Format)."""
import html
import json
import mimetypes
import os
import re
import urllib.parse

from ..base import Adapter, Incoming, PlatformError, Result, oauth1_header, register


@register
class TumblrAdapter(Adapter):
    name = "tumblr"
    label = "Tumblr"
    actions = ("post", "comment")
    poll_interval = 120  # new API consumers are limited to 1,000 requests/hour and 5,000/day
    config_keys = {
        "consumer_key": "www.tumblr.com/oauth/apps -> 'Register application' (any website and default callback "
                        "URL, e.g. https://localhost/) -> the app's 'OAuth Consumer Key'",
        "consumer_secret": "same app on www.tumblr.com/oauth/apps -> 'Show secret key' -> Secret Key",
        "oauth_token": "api.tumblr.com/console -> enter the consumer key and secret -> Authenticate -> Allow -> "
                       "'Show keys' -> Token",
        "oauth_token_secret": "same 'Show keys' panel on api.tumblr.com/console -> Token Secret",
        "blog": "(optional) blog to act as: name (myblog), myblog.tumblr.com, custom domain or blog URL "
                "(default: the account's primary blog)",
        "post_state": "(optional) state for new posts and reblogs: published | queue | draft | private "
                      "(default published)",
        "tags": "(optional) comma-separated tags added to every new post and reblog",
    }
    target_help = {
        "post": "omit to post to your blog; or the name of another blog you can post to (secondary or group blog)",
        "comment": "post URL (https://www.tumblr.com/<blog>/<id>, https://<blog>.tumblr.com/post/<id>/..., custom "
                   "domain /post/<id>) or <blog>/<post_id>. Tumblr's API has no reply endpoint, so this reblogs the "
                   "post to your blog with your text added; write @blogname in the text to mention a blog",
    }

    API = "https://api.tumblr.com/v2"
    # activity-feed types we surface -> Incoming kind (also sent as the endpoint's types[] filter)
    KINDS = {"reply": "comment", "reblog_with_content": "comment", "conversational_note": "reply",
             "mention_in_reply": "mention", "mention_in_post": "mention"}
    PAGES = 5  # notification pages fetched per poll
    # types whose content is a post on the sender's blog (post_id) rather than a note on target_post_id
    ON_SENDER = ("reblog_with_content", "mention_in_post")
    MENTION = re.compile(r"(?<![\w@./])@([A-Za-z0-9][A-Za-z0-9-]{0,31})")

    def __init__(self, config, http=None):
        super().__init__(config, http)
        self._blog = None   # {"name", "uuid"} of the blog we act as
        self._own = set()   # lower-cased name and uuid of every blog on the account
        self._uuids = {}    # blog name -> uuid, for @mentions

    # ------------------------------------------------------------- transport
    def _api(self, method, path, params=None, **kw):
        ck, cs, tok, tsec = self.need("consumer_key", "consumer_secret", "oauth_token", "oauth_token_secret")
        url = self.API + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True, safe="~", quote_via=urllib.parse.quote)
        auth = oauth1_header(method, url, consumer_key=ck, consumer_secret=cs, token=tok, token_secret=tsec)
        res = self.http.request(method, url, headers={"Authorization": auth}, **kw)
        return res.get("response", res) if isinstance(res, dict) else res

    # ------------------------------------------------------------- helpers
    def _ident(self, value):
        """Blog name / hostname / blog URL / uuid -> API blog identifier (name.tumblr.com, custom domain, t:uuid)."""
        v = str(value or "").strip()
        if re.match(r"(?i)https?://", v):
            parts = urllib.parse.urlsplit(v)
            host = parts.netloc.lower().split(":")[0]
            if host in ("tumblr.com", "www.tumblr.com"):
                seg = [s for s in parts.path.split("/") if s]
                while seg and seg[0] in ("blog", "view"):
                    seg = seg[1:]
                v = seg[0] if seg else ""
            else:
                v = host
        v = v.strip("/").lstrip("@")
        if v.startswith("t:"):
            return v
        v = v.lower()
        if not v:
            raise PlatformError(self.name, f"can't read a blog from {value!r}")
        return v if "." in v else f"{v}.tumblr.com"

    def _mine(self):
        if self._blog is None:
            user = self._api("GET", "/user/info").get("user") or {}
            blogs = user.get("blogs") or []
            want = self.config.get("blog")
            if want:
                ident = self._ident(want)
                pick = next((b for b in blogs if ident in self._blog_idents(b)), None)
                if pick is None:
                    names = ", ".join(b.get("name", "") for b in blogs) or "none"
                    raise PlatformError(self.name, f"blog {want!r} is not one of this account's blogs ({names})")
            else:
                pick = next((b for b in blogs if b.get("primary")), blogs[0] if blogs else None)
                if pick is None:
                    raise PlatformError(self.name, "this account has no blogs")
            self._own = {(b.get("name") or "").lower() for b in blogs} | {b.get("uuid") for b in blogs}
            self._own.discard("")
            self._own.discard(None)
            self._blog = {"name": pick["name"], "uuid": pick.get("uuid") or ""}
        return self._blog

    @staticmethod
    def _blog_idents(b):
        name = (b.get("name") or "").lower()
        host = urllib.parse.urlsplit(b.get("url") or "").netloc.lower()
        return {f"{name}.tumblr.com", b.get("uuid"), host}

    def _my_ident(self):
        return self._ident(self.config.get("blog") or self._mine()["name"])

    def _post_url(self, ident, pid):
        if ident.endswith(".tumblr.com"):
            return f"https://www.tumblr.com/{ident[:-len('.tumblr.com')]}/{pid}"
        if ident.startswith("t:"):
            if self._blog and self._blog["uuid"] == ident:
                return f"https://www.tumblr.com/{self._blog['name']}/{pid}"
            return ""
        return f"https://{ident}/post/{pid}"

    def _post_ref(self, target):
        """Post URL or blog/post_id -> (blog identifier, post id)."""
        t = str(target).strip()
        if re.match(r"(?i)https?://", t):
            parts = urllib.parse.urlsplit(t)
            host = parts.netloc.lower().split(":")[0]
            seg = [s for s in parts.path.split("/") if s]
            if host in ("tumblr.com", "www.tumblr.com"):
                while seg and seg[0] in ("blog", "view"):
                    seg = seg[1:]
                if len(seg) >= 3 and seg[1] == "post":
                    seg = [seg[0]] + seg[2:]
                if len(seg) >= 2 and seg[1].isdigit():
                    return self._ident(seg[0]), seg[1]
            else:
                if "post" in seg:
                    i = seg.index("post")
                    if i + 1 < len(seg) and seg[i + 1].isdigit():
                        return self._ident(host), seg[i + 1]
                if seg and seg[0].isdigit():
                    return self._ident(host), seg[0]
        else:
            m = re.match(r"^@?([^/\s]+)/(?:post/)?(\d+)/?$", t)
            if m:
                return self._ident(m.group(1)), m.group(2)
        raise PlatformError(self.name, f"can't read a post from {target!r}: use a post URL or <blog>/<post_id>")

    def _blog_uuid(self, name):
        key = name.lower()
        if key not in self._uuids:
            try:
                info = self._api("GET", f"/blog/{key}.tumblr.com/info")
                self._uuids[key] = ((info.get("blog") if isinstance(info, dict) else None) or {}).get("uuid") or ""
            except PlatformError:
                self._uuids[key] = ""
        return self._uuids[key]

    def _text_blocks(self, text):
        """Paragraphs -> NPF text blocks; @blogname becomes a mention when the blog exists."""
        blocks = []
        for para in re.split(r"\n\s*\n", (text or "").strip()):
            para = para.strip()
            if not para:
                continue
            block = {"type": "text", "text": para}
            fmt = []
            for m in self.MENTION.finditer(para):
                uuid = self._blog_uuid(m.group(1))
                if uuid:
                    fmt.append({"start": m.start(), "end": m.end(), "type": "mention", "blog": {"uuid": uuid}})
            if fmt:
                block["formatting"] = fmt
            blocks.append(block)
        return blocks

    def _media_blocks(self, media):
        """Image URLs are referenced directly; local files and other remote media are uploaded as multipart parts."""
        blocks, files = [], {}
        for i, item in enumerate(media or []):
            src = str(item).strip()
            remote = bool(re.match(r"(?i)https?://", src))
            path = urllib.parse.urlsplit(src).path if remote else src
            mime = mimetypes.guess_type(path)[0] or ""
            kind = mime.split("/")[0] if mime else ("image" if remote else "")
            if kind not in ("image", "video", "audio"):
                raise PlatformError(self.name, f"unsupported media {src!r}: Tumblr posts take images, video or audio")
            if remote and kind == "image":
                blocks.append({"type": "image", "media": [{"url": src}]})
                continue
            if remote:
                data = self.http.get(src, raw=True)
            else:
                if not os.path.isfile(src):
                    raise PlatformError(self.name, f"media file not found: {src}")
                with open(src, "rb") as f:
                    data = f.read()
            ident = f"media{i}"
            obj = {"type": mime, "identifier": ident}
            blocks.append({"type": kind, "media": [obj] if kind == "image" else obj})
            files[ident] = (os.path.basename(path) or ident, data, mime)
        return blocks, files

    def _create(self, ident, content, files=None, **extra):
        body = {"content": content}
        if self.config.get("post_state"):
            body["state"] = self.config["post_state"]
        if self.config.get("tags"):
            body["tags"] = self.config["tags"]
        body.update(extra)
        if files:
            parts = {"json": (None, json.dumps(body), "application/json")}
            parts.update(files)
            res = self._api("POST", f"/blog/{ident}/posts", files=parts)
        else:
            res = self._api("POST", f"/blog/{ident}/posts", json=body)
        pid = str(res.get("id_string") or res.get("id") or "") if isinstance(res, dict) else ""
        return Result(id=pid, url=self._post_url(ident, pid) if pid else "", raw=res if isinstance(res, dict) else {})

    def _fetch_post(self, ident, pid):
        res = self._api("GET", f"/blog/{ident}/posts", params={"id": pid, "npf": "true"})
        posts = res.get("posts") or []
        if not posts:
            raise PlatformError(self.name, f"post {pid} on {ident} not found")
        return res, posts[0]

    def _post_text(self, blog, pid):
        try:
            _, p = self._fetch_post(self._ident(blog), pid)
        except PlatformError:
            return ""
        return "\n\n".join(b.get("text", "") for b in p.get("content") or [] if b.get("type") == "text")

    @staticmethod
    def _tumblr_plain(text):
        text = re.sub(r"<br\s*/?>", "\n", text or "")
        text = re.sub(r"</p>\s*<p>", "\n\n", text)
        return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()

    # ------------------------------------------------------------- actions
    def whoami(self):
        return self._mine()["name"]

    def post(self, text, target=None, title=None, link=None, media=None):
        ident = self._ident(target) if target else self._my_ident()
        content = []
        if title:
            content.append({"type": "text", "subtype": "heading1", "text": title.strip()})
        mblocks, files = self._media_blocks(media)
        content += mblocks
        content += self._text_blocks(text)
        if link:
            content.append({"type": "link", "url": link})
        if not content:
            raise PlatformError(self.name, "nothing to post")
        return self._create(ident, content, files)

    def comment(self, target, text):
        ident, pid = self._post_ref(target)
        res, p = self._fetch_post(ident, pid)
        uuid = (p.get("blog") or {}).get("uuid") or (res.get("blog") or {}).get("uuid")
        key = p.get("reblog_key")
        if not uuid or not key:
            raise PlatformError(self.name, f"post {pid} on {ident} can't be reblogged (no reblog key)")
        return self._create(self._my_ident(), self._text_blocks(text), parent_tumblelog_uuid=uuid,
                            parent_post_id=str(p.get("id_string") or p.get("id") or pid), reblog_key=key)

    def poll(self, state):
        me = self._mine()
        ident = self._my_ident()
        since = int(state.get("since") or 0)
        # when the previous poll hit the page cap, carry on from where it stopped down to `since`
        resume = state.get("resume") or {}
        cursor = dict(resume.get("query") or {})
        newest = max(since, int(resume.get("newest") or 0))
        out, ids = [], set()
        for _ in range(self.PAGES):
            res = self._api("GET", f"/blog/{ident}/notifications", params={"types[]": list(self.KINDS), **cursor})
            res = res if isinstance(res, dict) else {}
            notes = res.get("notifications") or []
            for n in notes:
                ts = int(n.get("timestamp") or 0)
                newest = max(newest, ts)
                if ts < since:
                    continue
                item = self._incoming(n, me)
                if item and item.id not in ids:
                    ids.add(item.id)
                    out.append(item)
            nxt = ((res.get("_links") or {}).get("next") or {}).get("query_params")
            oldest = min((int(n.get("timestamp") or 0) for n in notes), default=0)
            if not since or not notes or not nxt or oldest < since:
                state.pop("resume", None)
                state["since"] = newest
                break
            cursor = {k: v for k, v in nxt.items() if not k.startswith("types")}
        else:
            state["resume"] = {"query": cursor, "newest": newest}
        out.sort(key=lambda i: i.ts)
        return out

    def _incoming(self, n, me):
        t = n.get("type") or ""
        kind = self.KINDS.get(t)
        sender = n.get("from_tumblelog_name") or ""
        if not kind or not sender:
            return None
        if sender.lower() in self._own or n.get("from_tumblelog_uuid") in self._own:
            return None
        target_blog = n.get("target_tumblelog_name") or me["name"]
        target_pid = str(n.get("target_post_id") or "")
        if t in self.ON_SENDER:
            blog, pid = sender, str(n.get("post_id") or target_pid)
        else:
            blog, pid = target_blog, target_pid
        if not pid:
            return None
        if t == "reply" and target_blog.lower() != me["name"].lower():
            kind = "reply"
        text = n.get("reply_text") or n.get("added_text") or ""
        if not text and t in self.ON_SENDER:
            text = self._post_text(blog, pid)
        thread = f"{target_blog}/{target_pid}" if target_pid and t != "mention_in_post" else f"{blog}/{pid}"
        ts = n.get("timestamp") or 0
        nid = str(n.get("id") or f"{t}:{n.get('from_tumblelog_uuid') or sender}:{pid}:{ts}")
        return Incoming(
            platform=self.name, kind=kind, id=nid, author=sender, author_id=str(n.get("from_tumblelog_uuid") or ""),
            text=self._tumblr_plain(text), url=f"https://www.tumblr.com/{blog}/{pid}", thread=thread, ts=float(ts),
            reply_to={"action": "comment", "target": f"{blog}/{pid}"}, raw=n,
        )
