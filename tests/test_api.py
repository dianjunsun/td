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


def test_position_book_keeps_cost_price_and_size(client):
    opened = client.post("/api/positions", json={
        "code": "600519",
        "name": "贵州茅台",
        "asset_type": "large_cap",
        "action": "trade",
        "side": "buy",
        "trade_date": "2026-11-24",
        "price": 100,
        "shares": 200,
    })
    assert opened.status_code == 200, opened.text
    added = client.post("/api/positions", json={
        "code": "600519",
        "name": "贵州茅台",
        "asset_type": "growth",
        "action": "trade",
        "side": "buy",
        "trade_date": "2026-11-25",
        "price": 110,
        "shares": 100,
    })
    assert added.status_code == 200, added.text
    marked = client.post("/api/positions", json={
        "code": "600519",
        "name": "贵州茅台",
        "asset_type": "growth",
        "action": "price",
        "trade_date": "2026-11-26",
        "price": 90,
    })
    assert marked.status_code == 200, marked.text
    snapshot = client.get("/api/snapshot", params={"as_of": "2026-11-26"}).json()
    plan = snapshot["plans"][0]
    assert plan["code"] == "600519"
    assert plan["asset_type"] == "growth"
    assert plan["view"]["shares"] == 300
    assert plan["view"]["c"] == pytest.approx(103.3333, abs=0.0001)
    assert plan["view"]["last_price"] == 90
    logged = client.get("/api/activity").json()
    assert [(item["action"], item["subject"]) for item in logged["items"]] == [
        ("记入", "买入单只股票"),
        ("记入", "买入单只股票"),
    ]
    assert [(row["side"], row["price"], row["shares"]) for row in plan["fills"]] == [
        ("buy", 100, 200),
        ("buy", 110, 100),
    ]
    too_many = client.post("/api/positions", json={
        "code": "600519",
        "asset_type": "growth",
        "action": "trade",
        "side": "sell",
        "trade_date": "2026-11-26",
        "price": 90,
        "shares": 301,
    })
    assert too_many.status_code == 400
    assert "超过持仓" in too_many.json()["detail"]


def test_fill_edits_stay_with_the_owner_unless_admin(client):
    opened = client.post("/api/positions", json={
        "code": "600519",
        "name": "贵州茅台",
        "asset_type": "large_cap",
        "action": "trade",
        "side": "buy",
        "trade_date": "2026-11-24",
        "price": 100,
        "shares": 10,
    })
    assert opened.status_code == 200, opened.text
    snap = client.get("/api/snapshot", params={"as_of": "2026-11-24"}).json()
    fill_id = snap["plans"][0]["fills"][0]["id"]
    edited = client.patch(f"/api/positions/fills/{fill_id}", json={
        "side": "buy",
        "trade_date": "2026-11-24",
        "price": 120,
        "shares": 10,
    })
    assert edited.status_code == 200, edited.text
    again = client.get("/api/snapshot", params={"as_of": "2026-11-24"}).json()
    assert again["plans"][0]["view"]["c"] == 120
    log = client.get("/api/activity").json()
    assert log["admin"] is True
    assert any(item["action"] == "修改" and item["subject"] == "修改单只股票" and item["code"] == "600519" for item in log["items"])

    other = client.raw.post("/api/auth/register", json={"username": "other2", "password": "secret2"})
    assert other.status_code == 200, other.text
    token = other.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    denied = client.raw.post(
        f"/api/positions/fills/{fill_id}/withdraw",
        params={"owner_id": "1"},
        headers=headers,
    )
    assert denied.status_code == 403
    created = client.raw.post("/api/positions", headers=headers, json={
        "code": "000001",
        "name": "平安银行",
        "asset_type": "large_cap",
        "action": "trade",
        "side": "buy",
        "trade_date": "2026-11-24",
        "price": 10,
        "shares": 100,
    })
    assert created.status_code == 200, created.text
    foreign = client.raw.get("/api/snapshot", params={"as_of": "2026-11-24"}, headers=headers).json()
    foreign_id = foreign["plans"][0]["fills"][0]["id"]
    withdrawn = client.post(f"/api/positions/fills/{foreign_id}/withdraw", params={"owner_id": other.json()["user"]["id"]})
    assert withdrawn.status_code == 200, withdrawn.text
    combined = client.get("/api/activity").json()
    assert any(item["owner_name"] == "other2" and item["action"] == "撤回" and item["subject"] == "买入单只股票" for item in combined["items"])
    hidden = client.raw.get("/api/activity", headers=headers).json()
    assert hidden["admin"] is False
    assert all(item["owner_name"] == "other2" for item in hidden["items"])


def test_capital_flows_move_cash_without_typing_assets(client):
    put_account(client, cash=1_000_000, nav=1_000_000)
    opened = client.post("/api/capital", json={
        "contributor": "张三",
        "occurred_at": "2026-11-27T09:30",
        "kind": "in",
        "amount": 200000,
        "note": "首笔",
    })
    assert opened.status_code == 200, opened.text
    book = opened.json()
    assert book["cash"] == 1_200_000
    assert book["contributed"] == 200000
    assert book["opening"] == 1_000_000
    assert book["contributors"][0]["name"] == "张三"
    assert book["flows"][0]["kind_label"] == "出资"
    bought = client.post("/api/positions", json={
        "code": "600519",
        "name": "贵州茅台",
        "asset_type": "large_cap",
        "action": "trade",
        "side": "buy",
        "trade_date": "2026-11-24",
        "price": 100,
        "shares": 100,
    })
    assert bought.status_code == 200, bought.text
    after_trade = client.get("/api/capital").json()
    assert after_trade["cash"] == 1_190_000
    assert after_trade["trade_cash"] == -10000
    assert after_trade["opening"] == 1_000_000
    flow_id = book["flows"][0]["id"]
    edited = client.patch(f"/api/capital/{flow_id}", json={
        "contributor": "李四",
        "occurred_at": "2026-11-27T10:00",
        "kind": "in",
        "amount": 150000,
    })
    assert edited.status_code == 200, edited.text
    assert edited.json()["cash"] == 1_140_000
    assert edited.json()["contributors"][0]["name"] == "李四"
    too_much = client.post("/api/capital", json={
        "contributor": "张三",
        "occurred_at": "2026-11-27T11:00",
        "kind": "out",
        "amount": 2_000_000,
    })
    assert too_much.status_code == 400
    assert "负数" in too_much.json()["detail"]
    withdrawn = client.post(f"/api/capital/{flow_id}/withdraw")
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["cash"] == 990_000
    assert withdrawn.json()["flows"] == []
    logged = client.get("/api/activity").json()
    pairs = [(item["action"], item["subject"]) for item in logged["items"]]
    assert ("记入", "出资") in pairs
    assert ("修改", "出资") in pairs
    assert ("撤回", "出资") in pairs
    other = client.raw.post("/api/auth/register", json={"username": "cashother", "password": "secret2"})
    denied = client.raw.post("/api/capital", headers={"Authorization": f"Bearer {other.json()['token']}"}, json={
        "contributor": "外人",
        "occurred_at": "2026-11-27T12:00",
        "kind": "in",
        "amount": 1,
        "owner_id": "1",
    })
    assert denied.status_code == 403


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
