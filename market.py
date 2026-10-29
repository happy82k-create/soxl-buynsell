"""야후 SOXL 일봉을 받아 data/ 에 둔다. 저장소에는 넣지 않는다."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
BARS_PATH = DATA_DIR / "soxl_daily.csv"
META_PATH = DATA_DIR / "meta.json"
LOG_PATH = DATA_DIR / "update.log"
SEOUL = ZoneInfo("Asia/Seoul")
TICKER = "SOXL"
HISTORY_START = "2010-01-01"


def now_seoul() -> datetime:
    return datetime.now(SEOUL)


def _log(message: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = now_seoul().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {message}\n")


def read_meta() -> dict:
    if not META_PATH.exists():
        return {}
    try:
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_meta(payload: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def is_fresh(meta: dict | None = None, at: datetime | None = None) -> bool:
    meta = read_meta() if meta is None else meta
    updated = meta.get("updated_at")
    if not updated or meta.get("error") or not BARS_PATH.exists():
        return False
    moment = at.astimezone(SEOUL) if at else now_seoul()
    six = moment.replace(hour=6, minute=0, second=0, microsecond=0)
    if moment < six:
        six = six - timedelta(days=1)
    try:
        stamped = datetime.fromisoformat(updated)
    except ValueError:
        return False
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=SEOUL)
    return stamped.astimezone(SEOUL) >= six


def _flatten_download(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.droplevel(-1)
    frame = frame.reset_index()
    frame.columns = [str(column).strip().lower().replace(" ", "_") for column in frame.columns]
    date_column = next((name for name in ("date", "datetime", "index") if name in frame.columns), None)
    if date_column is None:
        raise RuntimeError(f"날짜 열이 없다. 실제 열: {list(frame.columns)}")
    frame = frame.rename(columns={date_column: "date"})
    missing = [name for name in ("date", "open", "high", "low", "close", "volume") if name not in frame.columns]
    if missing:
        raise RuntimeError(f"일봉 열 부족: {missing}. 실제 열: {list(frame.columns)}")
    out = frame[["date", "open", "high", "low", "close", "volume"]].copy()
    dates = pd.to_datetime(out["date"])
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_convert("America/New_York").dt.tz_localize(None)
    out["date"] = dates.dt.normalize()
    for name in ("open", "high", "low", "close", "volume"):
        out[name] = pd.to_numeric(out[name], errors="coerce")
    out = out.dropna(subset=["date", "open", "high", "low", "close"])
    out["volume"] = out["volume"].fillna(0)
    out = out.drop_duplicates("date", keep="last").sort_values("date")
    return out.reset_index(drop=True)


def fetch_bars() -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(
        TICKER,
        start=HISTORY_START,
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError("야후에서 SOXL 일봉을 받지 못했다.")
    bars = _flatten_download(raw)
    if bars.empty:
        raise RuntimeError("받은 일봉이 비어 있다.")
    return bars


def load_bars() -> pd.DataFrame:
    if not BARS_PATH.exists():
        raise FileNotFoundError("저장된 일봉이 없다.")
    bars = pd.read_csv(BARS_PATH, parse_dates=["date"])
    bars["date"] = pd.to_datetime(bars["date"]).dt.normalize()
    return bars.sort_values("date").reset_index(drop=True)


def refresh() -> pd.DataFrame:
    previous = read_meta()
    try:
        bars = fetch_bars()
    except Exception as exc:
        failed = {
            "updated_at": previous.get("updated_at"),
            "last_bar": previous.get("last_bar"),
            "rows": previous.get("rows"),
            "error": str(exc),
        }
        _write_meta(failed)
        _log(f"실패 {exc}")
        raise
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = BARS_PATH.with_suffix(".csv.tmp")
    bars.to_csv(temporary, index=False, date_format="%Y-%m-%d")
    temporary.replace(BARS_PATH)
    last_bar = pd.Timestamp(bars.iloc[-1]["date"]).strftime("%Y-%m-%d")
    meta = {
        "updated_at": now_seoul().isoformat(timespec="seconds"),
        "last_bar": last_bar,
        "rows": int(len(bars)),
        "error": None,
    }
    _write_meta(meta)
    _log(f"받음 rows={len(bars)} last_bar={last_bar}")
    return bars
