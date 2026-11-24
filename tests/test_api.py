import pytest

from tests.conftest import add_instrument, plan_body, put_account


def plan_of(snapshot, plan_id):
    return next(item for item in snapshot["plans"] if item["id"] == plan_id)


def test_chapter12_flow_and_cooling_rejection(client):
    put_account(client)
    instrument_id = add_instrument(client)
    preview = client.post("/api/plans/preview", json=plan_body(instrument_id)).json()
    assert preview["errors"] == []
    assert preview["w_max"] == pytest.approx(109090.91, abs=0.001)
    assert preview["slices"] == [20000, 20000, 20000, 20000, 20000]
    assert preview["entry_lines"]["up"] == 120
    assert preview["entry_lines"]["pause"] == 92
    assert preview["entry_lines"]["cancel"] == 90

    missing = client.post("/api/plans", json=plan_body(instrument_id, invalidation=""))
    assert missing.status_code == 400
    assert "失效条件" in missing.json()["detail"]
    too_big = client.post("/api/plans", json=plan_body(instrument_id, w_approved=110000))
    assert too_big.status_code == 400
    assert "W_max" in too_big.json()["detail"]

    created = client.post("/api/plans", json=plan_body(instrument_id))
    assert created.status_code == 200, created.text
    plan_id = created.json()["id"]
    bought = client.post(
        f"/api/plans/{plan_id}/fills",
        json={
            "side": "buy",
            "trade_date": "2026-11-23",
            "session": "am",
            "price": 100,
            "shares": 200,
            "vwap": 100,
            "reason": "entry",
        },
    )
    assert bought.status_code == 200, bought.text
    chased = client.post(
        f"/api/plans/{plan_id}/fills",
        json={
            "side": "buy",
            "trade_date": "2026-11-24",
            "session": "am",
            "price": 104,
            "shares": 100,
            "vwap": 100,
            "reason": "entry",
        },
    )
    assert chased.status_code == 400
    assert "3%" in chased.json()["detail"]

    for day, price in (("2026-11-24", 130), ("2026-11-25", 117)):
        marked = client.post(
            f"/api/plans/{plan_id}/marks",
            json={"trade_date": day, "price": price, "source": "手工收盘", "kind": "close"},
        )
        assert marked.status_code == 200, marked.text

    snapshot = client.get("/api/snapshot", params={"as_of": "2026-11-25"}).json()
    view = plan_of(snapshot, plan_id)["view"]
    assert view["p0"] == 100
    assert view["h"] == 130
    assert view["r"] == 130
    assert view["tier_prices"]["d10"] == 117
    assert view["tier_prices"]["d15"] == 110.5
    assert view["tier_prices"]["d20"] == 104
    assert view["sell_need"] == 100
    assert any("原始持仓的 50%" in item["detail"] for item in snapshot["actions"])
    assert snapshot["quarterly"]["evaluation_ready"] is False

    sold = client.post(
        f"/api/plans/{plan_id}/fills",
        json={
            "side": "sell",
            "trade_date": "2026-11-25",
            "session": "pm",
            "price": 117,
            "shares": 100,
            "reason": "tier1",
        },
    )
    assert sold.status_code == 200, sold.text
    after = client.get("/api/snapshot", params={"as_of": "2026-11-25"}).json()
    cooled = plan_of(after, plan_id)["view"]
    assert cooled["cooling_active"] is True
    assert cooled["cooling_until"] == "2026-12-09"
    assert cooled["shares"] == 100

    rejected = client.post(
        f"/api/plans/{plan_id}/fills",
        json={
            "side": "buy",
            "trade_date": "2026-11-26",
            "session": "am",
            "price": 110,
            "shares": 100,
            "vwap": 110,
            "reason": "entry",
        },
    )
    assert rejected.status_code == 400
    assert "冷静期" in rejected.json()["detail"]
    breach = client.post(
        f"/api/plans/{plan_id}/fills",
        json={
            "side": "buy",
            "trade_date": "2026-11-26",
            "session": "am",
            "price": 110,
            "shares": 100,
            "vwap": 110,
            "reason": "entry",
            "record_breach": True,
            "off_rule_reason": "情绪买回",
        },
    )
    assert breach.status_code == 200, breach.text
    flagged = client.get("/api/snapshot", params={"as_of": "2026-11-26"}).json()
    assert flagged["quarterly"]["off_rule_count"] == 1
    assert flagged["quarterly"]["stats"] is None


def test_defensive_neutral_and_correlation(client):
    put_account(client, regime_intent="defensive")
    instrument_id = add_instrument(client)
    blocked = client.post("/api/plans", json=plan_body(instrument_id))
    assert blocked.status_code == 400
    assert "防守" in blocked.json()["detail"]

    put_account(client, regime_intent="neutral")
    preview = client.post("/api/plans/preview", json=plan_body(instrument_id)).json()
    assert preview["executable_now"] == 50000
    assert any("50%" in note for note in preview["notes"])

    put_account(client, regime_intent="aggressive")
    first = client.post("/api/plans", json=plan_body(instrument_id))
    assert first.status_code == 200, first.text
    second_id = add_instrument(client, code="DEMO2", name="同类股份", theme="另一个主题")
    second = client.post("/api/plans", json=plan_body(second_id))
    assert second.status_code == 200, second.text
    buy = client.post(
        f"/api/plans/{first.json()['id']}/fills",
        json={"side": "buy", "trade_date": "2026-11-23", "price": 100, "shares": 100, "vwap": 100, "reason": "entry"},
    )
    assert buy.status_code == 200, buy.text
    crowded = client.post(
        f"/api/plans/{second.json()['id']}/fills",
        json={"side": "buy", "trade_date": "2026-11-23", "price": 100, "shares": 100, "vwap": 100, "reason": "entry"},
    )
    assert crowded.status_code == 400
    assert "高度相关" in crowded.json()["detail"]
    weekend = client.post(
        f"/api/plans/{second.json()['id']}/fills",
        json={"side": "buy", "trade_date": "2026-11-28", "price": 100, "shares": 100, "vwap": 100, "reason": "entry"},
    )
    assert weekend.status_code == 400
    assert "交易日" in weekend.json()["detail"]


def test_rule_version_changes_sizing_and_can_return_to_v2(client):
    catalog = client.get("/api/rules")
    assert catalog.status_code == 200, catalog.text
    original = catalog.json()
    assert original["versions"][0]["name"] == "V2.0"
    params = original["versions"][0]["params"]
    params["asset_caps"]["large_cap"] = 0.08
    saved = client.post("/api/rules", json={"name": "更紧的大盘上限", "note": "验收可配置", "params": params})
    assert saved.status_code == 200, saved.text
    assert saved.json()["active"] is True
    put_account(client)
    instrument_id = add_instrument(client)
    preview = client.post("/api/plans/preview", json=plan_body(instrument_id)).json()
    assert preview["w_max"] == pytest.approx(80000, abs=0.001)
    restored = client.post(f"/api/rules/{original['active_id']}/activate")
    assert restored.status_code == 200, restored.text
    again = client.post("/api/plans/preview", json=plan_body(instrument_id)).json()
    assert again["w_max"] == pytest.approx(109090.91, abs=0.001)
    listed = client.get("/api/rules").json()
    assert [item["name"] for item in listed["versions"]] == ["V2.0", "更紧的大盘上限"]
    assert listed["versions"][0]["active"] is True
