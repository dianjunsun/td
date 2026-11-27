from decimal import Decimal

from td_core.quotes import Quote, QuoteError, QuoteRouter


def test_register_login_and_reject_strangers(client):
    denied = client.raw.get("/api/snapshot")
    assert denied.status_code == 401

    logged = client.raw.post("/api/auth/login", json={"username": "tester", "password": "secret1"})
    assert logged.status_code == 200
    me = client.get("/api/auth/me")
    assert me.json()["username"] == "tester"

    wrong = client.raw.post("/api/auth/login", json={"username": "tester", "password": "nope"})
    assert wrong.status_code == 401
    duplicate = client.raw.post("/api/auth/register", json={"username": "tester", "password": "secret1"})
    assert duplicate.status_code == 400


def test_two_users_keep_separate_books(client):
    client.post("/api/instruments", json={
        "code": "DEMO", "name": "示例股份", "asset_type": "large_cap", "industry": "消费", "theme": "龙头",
    })
    other = client.raw.post("/api/auth/register", json={"username": "other", "password": "secret2"})
    token = other.json()["token"]
    theirs = client.raw.get("/api/snapshot", headers={"Authorization": f"Bearer {token}"})
    assert theirs.status_code == 200
    assert theirs.json()["instruments"] == []
    mine = client.get("/api/snapshot")
    assert mine.json()["instruments"][0]["code"] == "DEMO"

    client.post("/api/auth/logout")
    assert client.get("/api/snapshot").status_code == 401


def test_user_can_rename_and_change_password(client):
    other = client.raw.post("/api/auth/register", json={"username": "renamer", "password": "secret2"})
    assert other.status_code == 200, other.text
    token = other.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    again = client.raw.post("/api/auth/login", json={"username": "renamer", "password": "secret2"})
    stale = {"Authorization": f"Bearer {again.json()['token']}"}
    renamed = client.raw.post("/api/auth/username", headers=headers, json={"username": "renamed", "password": "secret2"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["username"] == "renamed"
    assert client.raw.post("/api/auth/login", json={"username": "renamer", "password": "secret2"}).status_code == 401
    taken = client.raw.post("/api/auth/username", headers=headers, json={"username": "tester", "password": "secret2"})
    assert taken.status_code == 400
    changed = client.raw.post("/api/auth/password", headers=headers, json={"old_password": "secret2", "new_password": "secret3"})
    assert changed.status_code == 200, changed.text
    assert client.raw.get("/api/auth/me", headers=headers).status_code == 200
    assert client.raw.get("/api/auth/me", headers=stale).status_code == 401
    assert client.raw.post("/api/auth/login", json={"username": "renamed", "password": "secret2"}).status_code == 401
    logged = client.raw.post("/api/auth/login", json={"username": "renamed", "password": "secret3"})
    assert logged.status_code == 200
    denied = client.raw.patch("/api/users/1", headers=headers, json={"username": "nope"})
    assert denied.status_code == 403
    reset = client.patch("/api/users/" + other.json()["user"]["id"], json={"password": "secret9", "username": "managed"})
    assert reset.status_code == 200, reset.text
    assert reset.json()["username"] == "managed"
    assert client.raw.get("/api/auth/me", headers=headers).status_code == 401
    assert client.raw.post("/api/auth/login", json={"username": "managed", "password": "secret9"}).status_code == 200
    own = client.patch("/api/users/1", json={"password": "secret1"})
    assert own.status_code == 400


def test_watchlist_stays_on_the_signed_in_book(client):
    added = client.post("/api/watchlist", json={"code": "600519", "name": "贵州茅台", "market": "SH"})
    assert added.status_code == 200
    assert added.json()[0]["code"] == "600519"
    other = client.raw.post("/api/auth/register", json={"username": "watcher", "password": "secret2"})
    token = other.json()["token"]
    theirs = client.raw.get("/api/watchlist", headers={"Authorization": f"Bearer {token}"})
    assert theirs.json() == []
    removed = client.delete("/api/watchlist/600519")
    assert removed.json() == []


def test_quote_endpoint_uses_the_configured_router(client):
    class Fake:
        name = "fake"
        label = "测试源"

        def quote(self, code):
            if code == "000000":
                raise QuoteError("没有这只股票")
            return Quote(
                code="600519", market="SH", name="贵州茅台", price=Decimal("1457.28"),
                prev_close=None, open=None, high=None, low=None, vwap=None,
                as_of="2026-11-24 14:52:23", source="fake", source_label="测试源",
            )

    client.raw.app.state.quotes = QuoteRouter([Fake()])
    missing_source = client.get("/api/quotes/600519")
    assert missing_source.status_code == 400
    assert "请选择行情源" in missing_source.json()["detail"]
    found = client.get("/api/quotes/600519", params={"source": "fake"})
    assert found.status_code == 200
    assert found.json()["name"] == "贵州茅台"
    assert found.json()["source_label"] == "测试源"
    missing = client.get("/api/quotes/000000", params={"source": "fake"})
    assert missing.status_code == 400
    assert "没有这只股票" in missing.json()["detail"]
