from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from datetime import datetime, timezone
from Quantlib import fyers_util
from oi_screener_utils import implied_volatility, bs_greeks
import recorder

f = fyers_util.fyers_util()
LOT_SIZE = 50
RISK_FREE = 0.1

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
def index():
    return FileResponse("index.html")

@app.get("/option-chain")
def get_option_chain(symbol: str):
    try:
        data = f.option_chain(symbol)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upstream error: {e}")

    if data.get("code") != 200 or data.get("s") != "ok":
        raise HTTPException(status_code=502, detail=data.get("message", "bad upstream response"))

    payload = data["data"]
    options = payload.get("optionsChain", [])

    expiries = sorted(
        ({"ts": int(e["expiry"]), "date": e["date"], "flag": e["expiry_flag"]} for e in payload.get("expiryData", [])),
        key=lambda x: x["ts"],
    )

    spot_row = next((o for o in options if o.get("option_type") == ""), None)
    if spot_row is None:
        raise HTTPException(status_code=502, detail="no spot row")

    spot = float(spot_row["ltp"])
    now = datetime.now(timezone.utc)
    expiry_ts = expiries[0]["ts"] if expiries else int(now.timestamp())
    T = max(expiry_ts - now.timestamp(), 0) / (365 * 24 * 3600)
    
    # PREVENT GREEKS FROM ZEROING OUT ON EXPIRY DAY
    if T <= 0:
        T = 1.0 / (365 * 24)

    rows = []
    net_delta_exp = 0.0
    net_gamma_exp = 0.0
    call_oi_total = 0
    put_oi_total  = 0

    for o in options:
        if o.get("option_type") not in ("CE", "PE"):
            continue

        iv = implied_volatility(option_price=o["ltp"], S=spot, K=o["strike_price"], T=T, r=RISK_FREE, option_type=o["option_type"])
        
        if iv > 0:
            delta, gamma, vega, theta = bs_greeks(spot, o["strike_price"], T, RISK_FREE, iv, o["option_type"])
        else:
            delta = gamma = vega = theta = 0.0

        delta_exp = delta * o["oi"] * LOT_SIZE
        gamma_exp = gamma * o["oi"] * LOT_SIZE * spot
        net_delta_exp += delta_exp
        net_gamma_exp += gamma_exp

        oi = o.get("oi", 0) or 0
        if o["option_type"] == "CE":
            call_oi_total += oi
        else:
            put_oi_total += oi

        rows.append({
            "strike": o["strike_price"],
            "type": o["option_type"],
            "ltp": o["ltp"],
            "ltpchp": o.get("ltpchp", 0),
            "oi": oi,
            "oich": o.get("oich", 0),
            "oichp": o.get("oichp", 0),
            "volume": o.get("volume", 0),
            "iv": round(iv * 100, 2),
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "vega": round(vega, 3),
            "theta": round(theta, 3),
            "delta_exposure": round(delta_exp, 0),
            "gamma_exposure": round(gamma_exp, 0),
        })

    pcr = round(put_oi_total / call_oi_total, 4) if call_oi_total else 0.0

    strikes_all = sorted({r["strike"] for r in rows})
    ce_oi_map = {r["strike"]: r["oi"] for r in rows if r["type"] == "CE"}
    pe_oi_map = {r["strike"]: r["oi"] for r in rows if r["type"] == "PE"}

    max_pain_strike = None
    max_pain_value = None
    if strikes_all:
        for P in strikes_all:
            total_pain = sum((P - K) * ce_oi_map.get(K, 0) if P > K else (K - P) * pe_oi_map.get(K, 0) for K in strikes_all)
            if max_pain_value is None or total_pain < max_pain_value:
                max_pain_value = total_pain
                max_pain_strike = P

    response = {
        "symbol": symbol,
        "spot": round(spot, 2),
        "spot_chp": spot_row.get("ltpchp", 0),
        "spot_ch": spot_row.get("ltpch", 0),
        "call_oi_total": call_oi_total,
        "put_oi_total": put_oi_total,
        "pcr": pcr,
        "expiries": expiries,
        "active_expiry_ts": expiry_ts,
        "T_years": T,
        "rows": rows,
        "net": {"delta_exposure": round(net_delta_exp, 0), "gamma_exposure": round(net_gamma_exp, 0)},
        "max_pain": max_pain_strike,
        "max_pain_value": max_pain_value,
        "server_ts": datetime.now(timezone.utc).isoformat(),
    }

    try:
        recorder.record(symbol, response)
    except Exception as e:
        print(f"[recorder] {symbol}: {e}")

    return response

@app.get("/history")
def get_history(symbol: str, since: int = 0):
    return recorder.history(symbol, since)