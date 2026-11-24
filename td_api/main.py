"""本地交易纪律台。"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from td_api.auth import AuthError, AuthStore
from td_api.books import Books
from td_api.service import Service, ServiceError, parse_day
from td_core.quotes import QuoteError, build_router

DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


class AccountIn(BaseModel):
    nav: float
    cash: float
    regime_intent: str
    regime_evidence: str = ""
    special_reason: str = ""
    special_exit: str = ""
    trend_weakened: bool = False
    assumption_failed: bool = False
    risk_budget_pct: float = 0.015
    as_of: str | None = None


class InstrumentIn(BaseModel):
    code: str
    name: str
    asset_type: str
    industry: str = ""
    theme: str = ""
    high_vol: bool = False
    liquidity_note: str = ""


class PlanIn(BaseModel):
    instrument_id: int
    thesis: str = ""
    catalyst: str = ""
    risks: list[str] = Field(default_factory=list)
    invalidation: str = ""
    horizon: str = ""
    w_approved: float
    entry_days: int
    reference_price: float | None = None
    liquidity_ok: bool = False
    industry_ok: bool = False
    fundamental_ok: bool = False
    new_fact: str = ""
    market_price: float | None = None
    as_of: str | None = None


class FillIn(BaseModel):
    side: str
    trade_date: str
    session: str = "am"
    price: float
    shares: float
    vwap: float | None = None
    reason: str | None = None
    slippage: float | None = None
    note: str = ""
    record_breach: bool = False
    off_rule_reason: str = ""


class MarkIn(BaseModel):
    trade_date: str
    price: float
    source: str
    kind: str = "close"
    note: str = ""


class FlagIn(BaseModel):
    structure_ok: bool | None = None
    up_review_ok: bool | None = None
    industry_ok: bool | None = None
    fundamental_ok: bool | None = None


class NoteIn(BaseModel):
    note: str


class RuleIn(BaseModel):
    name: str
    note: str = ""
    params: dict


class ReentryIn(BaseModel):
    w_approved: float
    industry_ok: bool = False
    fundamental_ok: bool = False
    as_of: str | None = None


class MissedIn(BaseModel):
    missed_rebound: float


class CorporateIn(BaseModel):
    instrument_id: int
    action_date: str
    kind: str
    price_factor: float
    share_factor: float
    note: str = ""


class WeeklyIn(BaseModel):
    week_ending: str
    exposure_note: str = ""
    correlation_note: str = ""
    decision: str


class AuthIn(BaseModel):
    username: str
    password: str


class WatchIn(BaseModel):
    code: str
    name: str = ""
    market: str = ""


class QuotesIn(BaseModel):
    source: str = ""
    codes: list[str] = Field(default_factory=list)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        auth = AuthStore.connect(os.environ.get("TD_REDIS", "redis://127.0.0.1:6379/0"))
        auth.ping()
        app.state.auth = auth
        app.state.books = Books(os.environ.get("TD_DATA_DIR", "data/users"))
        app.state.quotes = build_router()
        yield

    app = FastAPI(title="个人交易纪律台", version="2.0.0", lifespan=lifespan)

    @app.exception_handler(ServiceError)
    async def _service_error(_request: Request, exc: ServiceError):
        return JSONResponse(status_code=400, content={"detail": exc.message})

    @app.exception_handler(AuthError)
    async def _auth_error(_request: Request, exc: AuthError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.exception_handler(QuoteError)
    async def _quote_error(_request: Request, exc: QuoteError):
        return JSONResponse(status_code=400, content={"detail": exc.message})

    def current_user(request: Request):
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        user = request.app.state.auth.user_for_token(token)
        if user is None:
            raise AuthError("请先登录")
        request.state.token = token
        return user

    def svc(request: Request) -> Service:
        user = current_user(request)
        return request.app.state.books.service_for(user.id)

    @app.get("/api/health")
    def health(request: Request):
        return {
            "ok": True,
            "version": "V2.0",
            "redis": True,
            "quotes": request.app.state.quotes.describe(),
        }

    @app.post("/api/auth/register")
    def register(request: Request, body: AuthIn):
        user, token = request.app.state.auth.register(body.username, body.password)
        return {"token": token, "user": {"id": user.id, "username": user.username}}

    @app.post("/api/auth/login")
    def login(request: Request, body: AuthIn):
        user, token = request.app.state.auth.login(body.username, body.password)
        return {"token": token, "user": {"id": user.id, "username": user.username}}

    @app.post("/api/auth/logout")
    def logout(request: Request):
        current_user(request)
        request.app.state.auth.logout(request.state.token)
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(request: Request):
        user = current_user(request)
        return {"id": user.id, "username": user.username}

    @app.get("/api/quote-sources")
    def quote_sources(request: Request):
        current_user(request)
        return request.app.state.quotes.describe()

    @app.get("/api/quotes/{code}")
    def quote(request: Request, code: str, source: str = ""):
        current_user(request)
        return request.app.state.quotes.quote(code, source).to_dict()

    @app.get("/api/market/search")
    def market_search(request: Request, q: str = "", source: str = ""):
        current_user(request)
        return [item.to_dict() for item in request.app.state.quotes.search(q, source)]

    @app.get("/api/market/chart")
    def market_chart(request: Request, code: str, source: str = "", period: str = "day"):
        current_user(request)
        return request.app.state.quotes.chart(source, code, period).to_dict()

    @app.get("/api/market/daily")
    def market_daily(request: Request, code: str, source: str = ""):
        current_user(request)
        series = request.app.state.quotes.daily(source, code)
        return {"adjust": series.adjust, "bars": [bar.to_dict() for bar in series.bars]}

    @app.get("/api/market/board")
    def market_board(request: Request, source: str = "", sort: str = "gainers"):
        current_user(request)
        return [item.to_dict() for item in request.app.state.quotes.board(source, sort)]

    @app.post("/api/market/quotes")
    def market_quotes(request: Request, body: QuotesIn):
        current_user(request)
        return [item.to_dict() for item in request.app.state.quotes.quotes(body.source, body.codes[:30])]

    @app.get("/api/watchlist")
    def watchlist(request: Request):
        return svc(request).list_watch()

    @app.post("/api/watchlist")
    def add_watch(request: Request, body: WatchIn):
        return svc(request).add_watch(body.model_dump())

    @app.delete("/api/watchlist/{code}")
    def remove_watch(request: Request, code: str):
        return svc(request).remove_watch(code)

    @app.get("/api/handbook")
    def handbook(request: Request):
        return svc(request).handbook()

    @app.get("/api/rules")
    def rules(request: Request):
        return svc(request).rule_catalog()

    @app.post("/api/rules")
    def save_rules(request: Request, body: RuleIn):
        return svc(request).save_rule_version(body.model_dump())

    @app.post("/api/rules/{version_id}/activate")
    def activate_rules(request: Request, version_id: int):
        return svc(request).activate_rule_version(version_id)

    @app.get("/api/snapshot")
    def snapshot(request: Request, as_of: str | None = None):
        return svc(request).snapshot(parse_day(as_of) if as_of else None)

    @app.put("/api/account")
    def update_account(request: Request, body: AccountIn):
        return svc(request).update_account(body.model_dump())

    @app.post("/api/instruments")
    def create_instrument(request: Request, body: InstrumentIn):
        return svc(request).create_instrument(body.model_dump())

    @app.post("/api/plans/preview")
    def preview_plan(request: Request, body: PlanIn):
        return svc(request).preview_plan(body.model_dump())

    @app.post("/api/plans")
    def create_plan(request: Request, body: PlanIn):
        return svc(request).create_plan(body.model_dump())

    @app.post("/api/plans/{plan_id}/fills")
    def add_fill(request: Request, plan_id: int, body: FillIn):
        return svc(request).add_fill(plan_id, body.model_dump())

    @app.post("/api/plans/{plan_id}/marks")
    def add_mark(request: Request, plan_id: int, body: MarkIn):
        return svc(request).add_mark(plan_id, body.model_dump())

    @app.post("/api/plans/{plan_id}/flags")
    def set_flags(request: Request, plan_id: int, body: FlagIn):
        payload = body.model_dump(exclude_none=True)
        return svc(request).set_flags(plan_id, payload)

    @app.post("/api/plans/{plan_id}/abandon")
    def abandon(request: Request, plan_id: int):
        return svc(request).abandon(plan_id)

    @app.post("/api/plans/{plan_id}/veto")
    def veto(request: Request, plan_id: int, body: NoteIn):
        return svc(request).veto(plan_id, body.model_dump())

    @app.post("/api/plans/{plan_id}/reentry")
    def reentry(request: Request, plan_id: int, body: ReentryIn):
        return svc(request).approve_reentry(plan_id, body.model_dump())

    @app.post("/api/plans/{plan_id}/missed")
    def missed(request: Request, plan_id: int, body: MissedIn):
        return svc(request).set_missed(plan_id, body.model_dump())

    @app.post("/api/corporate-actions")
    def corporate(request: Request, body: CorporateIn):
        return svc(request).add_corporate_action(body.model_dump())

    @app.post("/api/reviews/weekly")
    def weekly(request: Request, body: WeeklyIn):
        return svc(request).add_weekly(body.model_dump())

    @app.post("/api/rule-notes")
    def rule_note(request: Request, body: NoteIn):
        return svc(request).add_rule_note(body.model_dump())

    @app.get("/")
    def index():
        page = DIST / "index.html"
        if page.exists():
            return FileResponse(page)
        return HTMLResponse("<p>前端还没构建。在 web 目录执行 npm install 和 npm run build。</p>")

    assets = DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    return app


app = create_app()


def main() -> None:
    import uvicorn

    print("交易纪律台 http://127.0.0.1:8765")
    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
