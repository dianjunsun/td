import pytest
from fastapi.testclient import TestClient


class Authed:
    def __init__(self, raw, token: str):
        self.raw = raw
        self.token = token

    def _headers(self, headers):
        merged = {"Authorization": f"Bearer {self.token}"}
        if headers:
            merged.update(headers)
        return merged

    def get(self, url, **kwargs):
        kwargs["headers"] = self._headers(kwargs.get("headers"))
        return self.raw.get(url, **kwargs)

    def post(self, url, **kwargs):
        kwargs["headers"] = self._headers(kwargs.get("headers"))
        return self.raw.post(url, **kwargs)

    def put(self, url, **kwargs):
        kwargs["headers"] = self._headers(kwargs.get("headers"))
        return self.raw.put(url, **kwargs)

    def delete(self, url, **kwargs):
        kwargs["headers"] = self._headers(kwargs.get("headers"))
        return self.raw.delete(url, **kwargs)

    def patch(self, url, **kwargs):
        kwargs["headers"] = self._headers(kwargs.get("headers"))
        return self.raw.patch(url, **kwargs)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TD_DATA_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("TD_REDIS", "memory")
    monkeypatch.setenv("TD_LEGACY", str(tmp_path / "missing.db"))
    monkeypatch.setenv("TD_QUOTES", "eastmoney,sina")
    from td_api.main import create_app

    app = create_app()
    with TestClient(app) as raw:
        registered = raw.post("/api/auth/register", json={"username": "tester", "password": "secret1"})
        assert registered.status_code == 200, registered.text
        yield Authed(raw, registered.json()["token"])


def put_account(client, **extra):
    payload = {
        "nav": 1_000_000,
        "cash": 1_000_000,
        "regime_intent": "aggressive",
        "regime_evidence": "手册示例",
        "risk_budget_pct": 0.015,
        "as_of": "2026-11-23",
    }
    payload.update(extra)
    response = client.put("/api/account", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def add_instrument(client, **extra):
    payload = {
        "code": "DEMO",
        "name": "示例股份",
        "asset_type": "large_cap",
        "industry": "消费",
        "theme": "龙头",
    }
    payload.update(extra)
    response = client.post("/api/instruments", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def plan_body(instrument_id, **extra):
    payload = {
        "instrument_id": instrument_id,
        "thesis": "成熟公司现金流稳定",
        "catalyst": "需求回升",
        "risks": ["需求不及预期", "估值压缩", "行业政策"],
        "invalidation": "收盘跌破建仓逻辑或财务恶化",
        "horizon": "数月",
        "w_approved": 100000,
        "entry_days": 5,
        "reference_price": 100,
        "liquidity_ok": True,
        "as_of": "2026-11-23",
    }
    payload.update(extra)
    return payload
