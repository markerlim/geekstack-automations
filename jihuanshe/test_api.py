"""
Read-only smoke tests for the Jihuanshe API, run against YOUR OWN account.

Setup — two ways to authenticate, pick one:

  1. Log in with your own credentials (tests the real login flow):
        export JHS_ENV=uat            # or "prod" / "testing"
        export JHS_USERNAME="<your own account identifier>"
        export JHS_PASSWORD="<your own account password>"

  2. Or reuse a token you've already captured from your own logged-in
     session, if step 1's login endpoint turns out to be encrypted:
        export JHS_ENV=uat
        export JHS_TOKEN="<your own bearer token>"

    pip install requests pytest
    pytest jihuanshe/test_api.py -v -s

Scope, deliberately:
    - Only GET / read-oriented endpoints are exercised (card-versions,
      ranking, profile, dashboard, static config). Nothing that places
      orders, ships packages, deletes products, or moves money is called.
    - Tests don't assert on response bodies before knowing this API's
      real shapes — first run is exploratory: it records status code and
      whether the body decoded as JSON (plaintext) or looks encrypted,
      per jihuanshe-api-notes.md. Tighten the assertions once you've seen
      real output from your own account.
    - If JHS_TOKEN isn't set, authenticated tests are skipped rather than
      failing, so this file is safe to run without credentials.
"""
import os

import pytest

from client import JihuansheClient

pytestmark = pytest.mark.skipif(
    os.environ.get("JHS_SKIP_LIVE") == "1",
    reason="JHS_SKIP_LIVE=1 set; skipping live network calls",
)


def _report(name: str, resp) -> None:
    kind = "encrypted/opaque" if resp.looks_encrypted else ("json" if resp.json_body is not None else "empty")
    print(f"\n[{name}] status={resp.status_code} body_kind={kind} content-type={resp.headers.get('Content-Type')}")


@pytest.fixture(scope="module")
def client() -> JihuansheClient:
    c = JihuansheClient()
    username = os.environ.get("JHS_USERNAME")
    password = os.environ.get("JHS_PASSWORD")
    if not c.token and username and password:
        resp = c.login(username, password)
        _report("auto-login", resp)
    return c


@pytest.fixture(scope="module")
def require_token(client):
    if not client.token:
        pytest.skip(
            "No token available — set JHS_USERNAME/JHS_PASSWORD to log in, "
            "or JHS_TOKEN to reuse a captured token"
        )


class TestLogin:
    """Exercises the real login flow with your own credentials, if provided."""

    def test_login_flow(self):
        username = os.environ.get("JHS_USERNAME")
        password = os.environ.get("JHS_PASSWORD")
        if not (username and password):
            pytest.skip("JHS_USERNAME/JHS_PASSWORD not set")

        c = JihuansheClient(token="")
        resp = c.login(username, password)
        _report("login", resp)

        if resp.looks_encrypted:
            pytest.xfail("api/market/auth appears to return an encrypted/opaque body")

        assert resp.status_code == 200
        assert c.token, "login succeeded but no recognizable token field was found in the response"


class TestUnauthenticatedConfig:
    """Static/public config — should not need a token."""

    def test_configs_games(self, client):
        resp = client.get("configs/games")
        _report("configs/games", resp)
        assert resp.status_code in (200, 401, 403, 404)


class TestMarketReads:
    """Read-oriented market endpoints, own-account authenticated."""

    def test_card_versions(self, client, require_token):
        resp = client.get("api/market/card-versions")
        _report("card-versions", resp)
        assert resp.status_code != 500

    def test_ranking(self, client, require_token):
        resp = client.get("api/market/ranking")
        _report("ranking", resp)
        assert resp.status_code != 500

    def test_ranking_general(self, client, require_token):
        resp = client.get("api/market/rankingGeneral")
        _report("rankingGeneral", resp)
        assert resp.status_code != 500

    def test_user_profile(self, client, require_token):
        resp = client.get("api/market/users")
        _report("users", resp)
        assert resp.status_code != 500


class TestAuthBehavior:
    """Logic checks: confirm auth is actually enforced where expected."""

    def test_card_versions_requires_auth_or_is_public(self):
        # Deliberately no token: either it's public (200) or it's gated (401/403).
        # A 500 here would indicate a server error unrelated to auth.
        anon_client = JihuansheClient(token="")
        resp = anon_client.get("api/market/card-versions")
        _report("card-versions (anon)", resp)
        assert resp.status_code in (200, 401, 403)

    def test_dashboard_requires_auth(self):
        anon_client = JihuansheClient(token="")
        resp = anon_client.get("dashboard")
        _report("dashboard (anon)", resp)
        assert resp.status_code in (401, 403, 404)


class TestEncryptionDetection:
    """
    Empirically confirms which endpoints return plaintext JSON vs the
    encrypted payloads described in jihuanshe-api-notes.md. This does
    NOT attempt to decrypt anything — it only inspects whether the raw
    body parses as JSON.
    """

    @pytest.mark.parametrize(
        "path",
        [
            "configs/games",
            "api/market/card-versions",
            "api/market/ranking",
        ],
    )
    def test_body_shape(self, client, path):
        resp = client.get(path)
        _report(f"shape:{path}", resp)
        # No assertion — this test exists to print findings via -s/-v.
        # Run with: pytest jihuanshe/test_api.py -v -s
