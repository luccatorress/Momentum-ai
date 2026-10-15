from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import os, secrets, base64
from pydantic import BaseModel, Field
from typing import Literal
import random, math, time, hmac, hashlib, urllib.parse
import httpx

app = FastAPI(title="Momentum AI", version="0.2.0")

# Private-site gate: set MOMENTUM_USER and MOMENTUM_PASSWORD in the hosting dashboard.
# Fail closed when secrets are missing. Use only behind HTTPS in production.
@app.middleware("http")
async def private_site_auth(request: Request, call_next):
    username = os.getenv("MOMENTUM_USER", "")
    password = os.getenv("MOMENTUM_PASSWORD", "")
    if not username or not password:
        return JSONResponse(
            status_code=503,
            content={"detail": "Acesso privado não configurado. Defina MOMENTUM_USER e MOMENTUM_PASSWORD."}
        )
    auth = request.headers.get("authorization", "")
    valid = False
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
            supplied_user, supplied_password = decoded.split(":", 1)
            valid = secrets.compare_digest(supplied_user, username) and secrets.compare_digest(supplied_password, password)
        except Exception:
            valid = False
    if not valid:
        return JSONResponse(
            status_code=401,
            content={"detail": "Autenticação necessária."},
            headers={"WWW-Authenticate": 'Basic realm="Momentum AI", charset="UTF-8"'}
        )
    return await call_next(request)
app.mount("/static", StaticFiles(directory="static"), name="static")
orders = []
virtual_balance = 1000.0

@app.get("/", response_class=HTMLResponse)
def home():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()

@app.get("/api/status")
def status():
    return {
        "app": "Momentum AI",
        "mode": "paper-trading",
        "market_data": "synthetic-demo",
        "broker_connected": False,
        "live_execution_enabled": False,
        "virtual_balance": round(virtual_balance, 2),
        "message": "Dados sintéticos demonstrativos; nenhuma corretora conectada."
    }

def ema(values, period):
    k = 2 / (period + 1)
    out = []
    for i, v in enumerate(values):
        out.append(v if i == 0 else v*k + out[-1]*(1-k))
    return out

def rsi(values, period=14):
    if len(values) <= period:
        return 50.0
    diffs = [values[i] - values[i-1] for i in range(1, len(values))]
    gains = sum(max(x, 0) for x in diffs[-period:]) / period
    losses = sum(max(-x, 0) for x in diffs[-period:]) / period
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return 100 - (100 / (1 + rs))

def candles_for(asset, n=120):
    # Reproducible-ish synthetic series, not market prices.
    seed = sum(ord(c) for c in asset) + int(time.time() // 60)
    rng = random.Random(seed)
    base = {"BTC/USD": 67000, "ETH/USD": 3200, "EUR/USD": 1.08}.get(asset, 100)
    vals, candles = [], []
    price = base
    for i in range(n):
        drift = 0.00012 if (i // 18) % 2 == 0 else -0.00008
        price *= 1 + drift + rng.gauss(0, 0.0018)
        o = vals[-1] if vals else base
        c = price
        spread = abs(rng.gauss(0, base*0.001))
        candles.append({"t": i, "open": round(o, 5), "high": round(max(o,c)+spread,5),
                        "low": round(min(o,c)-spread,5), "close": round(c,5),
                        "volume": round(rng.uniform(50,200),2)})
        vals.append(c)
    return candles

def analyze(asset, timeframe, strategy):
    candles = candles_for(asset)
    closes = [c["close"] for c in candles]
    e9, e21, e50 = ema(closes,9), ema(closes,21), ema(closes,50)
    # MACD histogram: EMA12 - EMA26 minus signal EMA9
    macd_line = [a-b for a,b in zip(ema(closes,12), ema(closes,26))]
    signal_line = ema(macd_line,9)
    hist = macd_line[-1] - signal_line[-1]
    rv = rsi(closes)
    mom = (closes[-1] / closes[-6] - 1) * 100
    long_score = sum([e9[-1] > e21[-1], e21[-1] > e50[-1], mom > 0, hist > 0, rv > 50])
    short_score = sum([e9[-1] < e21[-1], e21[-1] < e50[-1], mom < 0, hist < 0, rv < 50])
    threshold = 4 if strategy != "Momentum" else 3
    if long_score >= threshold and long_score > short_score:
        signal, reason = "LONG", "Momentum e médias favorecem alta no conjunto sintético."
    elif short_score >= threshold and short_score > long_score:
        signal, reason = "SHORT", "Momentum e médias favorecem baixa no conjunto sintético."
    else:
        signal, reason = "NO SIGNAL", "Indicadores sem confluência suficiente."
    return {
        "asset": asset, "timeframe": timeframe, "strategy": strategy,
        "signal": signal, "reason": reason,
        "price": closes[-1], "rsi14": round(rv,2), "momentum_pct": round(mom,4),
        "ema9": round(e9[-1],5), "ema21": round(e21[-1],5), "ema50": round(e50[-1],5),
        "macd_histogram": round(hist,6), "score": max(long_score,short_score),
        "confidence": "não calibrada",
        "data_mode": "SYNTHETIC DEMO",
        "candles": candles[-60:]
    }


BINANCE_PUBLIC_BASE = "https://api.binance.com"
BINANCE_DEMO_BASE = "https://demo-api.binance.com"

def binance_public_candles(symbol: str, interval: str, limit: int = 120):
    # Real public market data. No API key is needed for public klines.
    response = httpx.get(
        f"{BINANCE_PUBLIC_BASE}/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=10.0,
    )
    response.raise_for_status()
    rows = response.json()
    return [{
        "t": int(row[0]),
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
    } for row in rows]

def market_candles(asset: str, timeframe: str, limit: int = 120):
    symbol = {"BTC/USDT":"BTCUSDT", "ETH/USDT":"ETHUSDT", "BNB/USDT":"BNBUSDT"}.get(asset)
    interval = {"1 min":"1m", "5 min":"5m", "15 min":"15m"}.get(timeframe, "5m")
    if not symbol:
        raise HTTPException(status_code=400, detail="Ativo não suportado.")
    try:
        return binance_public_candles(symbol, interval, limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Falha ao obter candles públicos da Binance: {type(e).__name__}")

def analyze_real_market(asset: str, timeframe: str, strategy: str):
    candles = market_candles(asset, timeframe, 120)
    closes = [c["close"] for c in candles]
    e9, e21, e50 = ema(closes,9), ema(closes,21), ema(closes,50)
    macd_line = [a-b for a,b in zip(ema(closes,12), ema(closes,26))]
    signal_line = ema(macd_line,9)
    hist = macd_line[-1] - signal_line[-1]
    rv = rsi(closes)
    mom = (closes[-1] / closes[-6] - 1) * 100
    long_score = sum([e9[-1] > e21[-1], e21[-1] > e50[-1], mom > 0, hist > 0, rv > 50])
    short_score = sum([e9[-1] < e21[-1], e21[-1] < e50[-1], mom < 0, hist < 0, rv < 50])
    threshold = 4 if strategy != "Momentum" else 3
    if long_score >= threshold and long_score > short_score:
        signal, reason = "LONG", "Confluência de indicadores favorece viés de alta; não garante continuidade."
    elif short_score >= threshold and short_score > long_score:
        signal, reason = "SHORT", "Confluência de indicadores favorece viés de baixa; não garante continuidade."
    else:
        signal, reason = "NO SIGNAL", "Indicadores sem confluência suficiente."
    return {
        "asset": asset, "timeframe": timeframe, "strategy": strategy,
        "signal": signal, "reason": reason, "price": closes[-1],
        "rsi14": round(rv,2), "momentum_pct": round(mom,4),
        "ema9": round(e9[-1],8), "ema21": round(e21[-1],8), "ema50": round(e50[-1],8),
        "macd_histogram": round(hist,8), "score": max(long_score,short_score),
        "confidence": "não calibrada", "data_mode": "BINANCE PUBLIC MARKET DATA",
        "candles": candles[-60:]
    }

def signed_demo_request(method: str, path: str, params: dict):
    api_key = os.getenv("BINANCE_DEMO_API_KEY", "")
    api_secret = os.getenv("BINANCE_DEMO_API_SECRET", "")
    if not api_key or not api_secret:
        raise HTTPException(status_code=503, detail="Configure BINANCE_DEMO_API_KEY e BINANCE_DEMO_API_SECRET no painel de hospedagem. Use chaves do Binance Demo Trading, nunca as chaves da conta real.")
    payload = dict(params)
    payload["timestamp"] = int(time.time() * 1000)
    payload["recvWindow"] = 5000
    query = urllib.parse.urlencode(payload)
    payload["signature"] = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    try:
        response = httpx.request(
            method, f"{BINANCE_DEMO_BASE}{path}",
            params=payload if method.upper() == "GET" else None,
            data=payload if method.upper() != "GET" else None,
            headers={"X-MBX-APIKEY": api_key},
            timeout=10.0,
        )
        if response.status_code >= 400:
            # Don't return credentials or signed request details.
            raise HTTPException(status_code=502, detail=f"Binance Demo rejeitou a solicitação (HTTP {response.status_code}): {response.text[:300]}")
        return response.json() if response.text else {}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Falha na API Binance Demo: {type(e).__name__}")

class AnalyzeRequest(BaseModel):
    asset: Literal["BTC/USDT","ETH/USDT","BNB/USDT"] = "BTC/USD"
    timeframe: Literal["1 min","5 min","15 min"] = "5 min"
    strategy: Literal["Momentum","Confluência","Tendência"] = "Momentum"

class PaperOrderRequest(BaseModel):
    asset: Literal["BTC/USDT","ETH/USDT","BNB/USDT"]
    side: Literal["LONG","SHORT"]
    amount: float = Field(gt=0, le=10000)
    timeframe: Literal["1 min","5 min","15 min"] = "5 min"

@app.post("/api/analyze")
def analyze_endpoint(req: AnalyzeRequest):
    return analyze_real_market(req.asset, req.timeframe, req.strategy)

@app.get("/api/binance/status")
def binance_status():
    return {
        "market_data": "public Binance REST API",
        "demo_order_api_configured": bool(os.getenv("BINANCE_DEMO_API_KEY") and os.getenv("BINANCE_DEMO_API_SECRET")),
        "demo_base_url": BINANCE_DEMO_BASE,
        "live_trading_enabled": False
    }

class DemoOrderRequest(BaseModel):
    asset: Literal["BTC/USDT","ETH/USDT","BNB/USDT"]
    side: Literal["BUY","SELL"]
    quote_amount: float = Field(gt=0, le=100)
    confirm_demo: bool = False

@app.post("/api/binance/demo-order")
def binance_demo_order(req: DemoOrderRequest):
    # Hard cap and explicit confirmation. Uses demo-only host, never production.
    if not req.confirm_demo:
        raise HTTPException(status_code=400, detail="Confirme explicitamente que esta ordem será enviada apenas ao ambiente Binance Demo.")
    symbol = {"BTC/USDT":"BTCUSDT","ETH/USDT":"ETHUSDT","BNB/USDT":"BNBUSDT"}[req.asset]
    if req.quote_amount > 100:
        raise HTTPException(status_code=400, detail="Limite máximo de demonstração: 100 USDT por ordem.")
    # Binance Spot market BUY can use quoteOrderQty. Market SELL requires base quantity;
    # for SELL, derive quantity from current public price and round conservatively.
    params = {"symbol": symbol, "side": req.side, "type": "MARKET"}
    if req.side == "BUY":
        params["quoteOrderQty"] = f"{req.quote_amount:.2f}"
    else:
        candles = market_candles(req.asset, "1 min", 2)
        price = candles[-1]["close"]
        try:
            info = httpx.get(f"{BINANCE_PUBLIC_BASE}/api/v3/exchangeInfo", params={"symbol": symbol}, timeout=10.0)
            info.raise_for_status()
            symbol_info = info.json()["symbols"][0]
            lot_filter = next(f for f in symbol_info["filters"] if f["filterType"] == "LOT_SIZE")
            step = float(lot_filter["stepSize"])
            raw_qty = (req.quote_amount / price)
            qty = math.floor(raw_qty / step) * step
            precision = max(0, len(lot_filter["stepSize"].rstrip("0").split(".")[-1]) if "." in lot_filter["stepSize"] else 0)
        except Exception as e:
            raise HTTPException(status_code=502, detail="Não foi possível validar a precisão da quantidade para este ativo.")
        if qty <= 0:
            raise HTTPException(status_code=400, detail="Quantidade calculada é muito pequena para as regras do ativo.")
        params["quantity"] = f"{qty:.{precision}f}"
    result = signed_demo_request("POST", "/api/v3/order", params)
    return {"environment":"BINANCE DEMO — VIRTUAL FUNDS", "symbol":symbol, "result":result, "live_trading_enabled":False}

@app.get("/api/paper-orders")
def list_paper_orders():
    return {"orders": orders, "virtual_balance": round(virtual_balance, 2)}

@app.post("/api/paper-orders")
def create_paper_order(req: PaperOrderRequest):
    global virtual_balance
    if req.amount > virtual_balance:
        raise HTTPException(status_code=400, detail="Valor acima do saldo virtual disponível.")
    signal = analyze(req.asset, req.timeframe, "Momentum")
    entry = signal["price"]
    # Deterministic illustrative settlement, not a prediction: outcomes are random and explicitly simulated.
    rng = random.Random(time.time_ns())
    win = rng.random() < 0.5
    payout = round(req.amount * 0.7, 2) if win else -round(req.amount, 2)
    virtual_balance = round(virtual_balance + payout, 2)
    item = {
        "id": len(orders)+1, "asset": req.asset, "side": req.side,
        "amount": round(req.amount,2), "entry_demo": entry,
        "timeframe": req.timeframe, "outcome_demo": "WIN (aleatório)" if win else "LOSS (aleatório)",
        "pnl_demo": payout, "balance_after": virtual_balance,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "PAPER ONLY"
    }
    orders.insert(0,item)
    return item
