import os
import threading
import time
from datetime import datetime, timezone

import pandas as pd

BASE_DIR = os.path.join(os.path.dirname(__file__), "history")
os.makedirs(BASE_DIR, exist_ok=True)

_lock = threading.Lock()

# last cumulative volume per symbol, for computing per-bucket deltas
_last = {}   # symbol -> {"call_volume": int, "put_volume": int}

# dedupe: don't write more than one row per symbol per N seconds,
# even if the user's browser auto-refreshes faster
MIN_WRITE_INTERVAL = 30   # seconds
_last_write = {}          # symbol -> bucket ts


def _safe_symbol(symbol: str) -> str:
    return symbol.replace(":", "_").replace("/", "_")


def _day_path(symbol: str, ts: int) -> str:
    d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    folder = os.path.join(BASE_DIR, _safe_symbol(symbol))
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{d}.parquet")


import os
import threading
import time
from datetime import datetime, timezone
import pandas as pd

BASE_DIR = os.path.join(os.path.dirname(__file__), "history")
os.makedirs(BASE_DIR, exist_ok=True)

_lock = threading.Lock()
_last_write = {}    
MIN_WRITE_INTERVAL = 15   # 15s bucket so charts update faster

def _safe_symbol(symbol: str) -> str:
    return symbol.replace(":", "_").replace("/", "_")

def _day_path(symbol: str, ts: int) -> str:
    d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    folder = os.path.join(BASE_DIR, _safe_symbol(symbol))
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{d}.parquet")

def record(symbol: str, snapshot: dict):
    now = int(time.time())
    bucket = (now // MIN_WRITE_INTERVAL) * MIN_WRITE_INTERVAL

    # Deduplicate within the same 15s bucket
    if _last_write.get(symbol) == bucket:
        return
    _last_write[symbol] = bucket

    # Parse net exposures (they are nested under 'net')
    net = snapshot.get("net") or {}
    net_delta = net.get("delta_exposure") or snapshot.get("net_delta_exp") or 0
    net_gamma = net.get("gamma_exposure") or snapshot.get("net_gamma_exp") or 0

    # Compute volume from rows if missing at the top level
    rows = snapshot.get("rows") or []
    call_vol = snapshot.get("call_volume")
    put_vol  = snapshot.get("put_volume")
    if call_vol is None or put_vol is None:
        call_vol = sum(r.get("volume", 0) or 0 for r in rows if r.get("type") == "CE")
        put_vol  = sum(r.get("volume", 0) or 0 for r in rows if r.get("type") == "PE")

    row = pd.DataFrame([{
        "ts":            bucket,
        "symbol":        symbol,
        "spot":          float(snapshot.get("spot") or 0),
        "net_delta_exp": float(net_delta),
        "net_gamma_exp": float(net_gamma),
        "call_oi_total": float(snapshot.get("call_oi_total") or 0),
        "put_oi_total":  float(snapshot.get("put_oi_total") or 0),
        "call_volume":   float(call_vol or 0),
        "put_volume":    float(put_vol or 0),
        "max_pain":      float(snapshot.get("max_pain") or 0) or None,
    }])

    path = _day_path(symbol, bucket)

    with _lock:
        if os.path.exists(path):
            old = pd.read_parquet(path)
            old = old[old["ts"] != bucket]
            out = pd.concat([old, row], ignore_index=True).sort_values("ts")
        else:
            out = row
        out.to_parquet(path, index=False)

def history(symbol: str, since_ts: int = 0) -> list[dict]:
    folder = os.path.join(BASE_DIR, _safe_symbol(symbol))
    if not os.path.isdir(folder):
        return []
    files = sorted(
        os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".parquet")
    )
    frames = []
    for fp in files:
        try:
            df = pd.read_parquet(fp)
            if "ts" in df.columns:
                df = df[df["ts"] >= since_ts]
            frames.append(df)
        except Exception as e:
            print(f"[recorder] read {fp}: {e}")
    if not frames:
        return []
    return pd.concat(frames, ignore_index=True).sort_values("ts").to_dict("records")

def history(symbol: str, since_ts: int = 0) -> list[dict]:
    folder = os.path.join(BASE_DIR, _safe_symbol(symbol))
    if not os.path.isdir(folder):
        return []
    files = sorted(
        os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".parquet")
    )
    frames = []
    for fp in files:
        try:
            df = pd.read_parquet(fp)
            if "ts" in df.columns:
                df = df[df["ts"] >= since_ts]
            frames.append(df)
        except Exception as e:
            print(f"[recorder] read {fp}: {e}")
    if not frames:
        return []
    return pd.concat(frames, ignore_index=True).sort_values("ts").to_dict("records")