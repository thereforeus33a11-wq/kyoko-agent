import pytest

from social_bridge.base import PlatformError, oauth1_header
from tests.fakehttp import FakeHttp


def test_oauth1_matches_twitter_reference_vector():
    # https://developer.x.com/en/docs/authentication/oauth-1-0a/creating-a-signature
    h = oauth1_header(
        "POST", "https://api.twitter.com/1.1/statuses/update.json?include_entities=true",
        consumer_key="xvz1evFS4wEEPTGEFPHBog",
        consumer_secret="kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
        token="370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
        token_secret="LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE",
        params={"status": "Hello Ladies + Gentlemen, a signed OAuth request!"},
        nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg", timestamp=1318622958)
    assert 'oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"' in h


def test_http_retries_429_then_succeeds():
    http = FakeHttp("t").add("GET", "https://x.test/a", (429, {}, {"Retry-After": "1"}), {"ok": 1})
    assert http.get("https://x.test/a") == {"ok": 1}
    assert len(http.calls) == 2


def test_http_raises_platform_error():
    http = FakeHttp("t").add("GET", "https://x.test/a", (403, {"error": "nope"}))
    with pytest.raises(PlatformError) as e:
        http.get("https://x.test/a")
    assert e.value.status == 403 and e.value.body == {"error": "nope"}
