from social_bridge.adapters.mastodon import MastodonAdapter
from tests.fakehttp import FakeHttp

B = "https://m.test"


def make():
    http = FakeHttp("mastodon")
    return MastodonAdapter({"instance": B + "/", "access_token": "tok"}, http), http


def test_post_with_title_and_link():
    a, http = make()
    http.add("POST", B + "/api/v1/statuses", {"id": "9", "url": B + "/@me/9"})
    r = a.post("hello", title="cw", link="https://x.y")
    c = http.last("POST")
    assert c["json"] == {"status": "hello\n\nhttps://x.y", "visibility": "public", "spoiler_text": "cw"}
    assert c["headers"]["Authorization"] == "Bearer tok" and r.id == "9"


def test_comment_mentions_author_and_dm_is_direct():
    a, http = make()
    http.add("GET", B + "/api/v1/statuses/5", {"id": "5", "account": {"acct": "bob@x.y"}, "visibility": "public"})
    http.add("POST", B + "/api/v1/statuses", {"id": "6"}, {"id": "7"})
    a.comment(B + "/@bob/5", "nice")
    assert http.last("POST")["json"] == {"status": "@bob@x.y nice", "visibility": "public", "in_reply_to_id": "5"}
    a.dm("@amy@z.w", "hey")
    assert http.last("POST")["json"] == {"status": "@amy@z.w hey", "visibility": "direct"}


def test_poll_cursor_and_kinds():
    a, http = make()
    st = lambda i, vis="public", rep=None: {"id": str(i), "type": "mention", "status": {
        "id": str(i * 10), "visibility": vis, "in_reply_to_id": rep, "content": "<p>hi &amp; bye</p>",
        "account": {"acct": "bob", "id": "1"}, "url": "u", "conversation_id": "c"}}
    http.add("GET", B + "/api/v1/notifications", [st(3, "direct"), st(2, rep="1")], [])
    state = {}
    items = a.poll(state)
    assert [i.kind for i in items] == ["reply", "dm"] and items[0].text == "hi & bye"
    assert items[1].reply_to == {"action": "dm", "target": "bob"} and state["since_id"] == "3"
    a.poll(state)
    assert http.last("GET")["params"]["since_id"] == "3"
