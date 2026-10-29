"""SOXX 주봉 CCI 30. 기존 장기 앱의 중기 추세 카드와 같은 계산이다."""

from __future__ import annotations

import html
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from market import DATA_DIR, _log

NY = ZoneInfo("America/New_York")
REGULAR_CLOSE = time(16, 0)
SOXX_PATH = DATA_DIR / "soxx_weekly.csv"
SOXX_META_PATH = DATA_DIR / "soxx_meta.json"
SYMBOL = "SOXX"
HISTORY_START = "2023-01-01"
CCI_PERIOD = 30
SHOWN_WEEKS = 30

CARD_CSS = """
.soxx-trend {
  color: #e7f2ee;
  font-family: "Malgun Gothic", sans-serif;
  container-type: inline-size;
  container-name: soxx;
}
.soxx-trend .trend-card {
  background: rgba(18, 38, 48, 0.92);
  border: 1px solid rgba(140, 196, 180, 0.16);
  border-radius: 14px;
  padding: 12px 10px 10px;
  margin: 8px 0 0;
}
.soxx-trend .trend-card.up { border-left: 4px solid #e2c36b; }
.soxx-trend .trend-card.down { border-left: 4px solid #3d8bfd; }
.soxx-trend .trend-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.soxx-trend .trend-name { font-size: 20px; font-weight: 700; letter-spacing: -0.03em; }
.soxx-trend .trend-signal { display: flex; align-items: center; gap: 10px; }
.soxx-trend .trend-point {
  font-family: Consolas, monospace; font-size: 22px; font-weight: 600; letter-spacing: -0.03em; line-height: 1;
}
.soxx-trend .trend-card.up .trend-point { color: #e2c36b; }
.soxx-trend .trend-card.down .trend-point { color: #8cbcff; }
.soxx-trend .trend-pill {
  min-width: 74px; text-align: center; border-radius: 999px; padding: 6px 12px;
  font-size: 22px; font-weight: 700; line-height: 1;
}
.soxx-trend .trend-card.up .trend-pill { color: #1a1406; background: #e2c36b; }
.soxx-trend .trend-card.down .trend-pill { color: #fff; background: #3d8bfd; }
.soxx-trend .trend-judge { margin: 8px 0 10px; color: #8aa39a; font-size: 13px; }
.soxx-trend .trend-judge b { color: #e7f2ee; font-family: Consolas, monospace; font-weight: 600; }
.soxx-trend .trend-scroll {
  overflow-x: auto;
  overscroll-behavior-x: contain;
  scrollbar-width: none;
}
.soxx-trend .trend-scroll::-webkit-scrollbar { display: none; }
.soxx-trend .trend-bar {
  position: relative;
  height: 22px;
  margin: 10px 2px 0;
  border-radius: 99px;
  background: rgba(140, 196, 180, 0.2);
  touch-action: none;
  cursor: pointer;
}
.soxx-trend .trend-bar[hidden] { display: none; }
.soxx-trend .trend-bar-thumb {
  position: absolute;
  top: 3px;
  height: 16px;
  left: 0;
  border-radius: 99px;
  background: #7eb6ff;
  cursor: grab;
}
.soxx-trend .trend-card.up .trend-bar-thumb { background: #e2c36b; }
.soxx-trend .trend-card.down .trend-bar-thumb { background: #3d8bfd; }
.soxx-trend .trend-cols { display: grid; gap: 3px; }
.soxx-trend .trend-col { text-align: center; min-width: 0; border-radius: 4px; padding-top: 2px; }
.soxx-trend .trend-col.down {
  background: repeating-linear-gradient(-45deg, transparent, transparent 3px, rgba(61, 139, 253, 0.38) 3px, rgba(61, 139, 253, 0.38) 5px);
}
.soxx-trend .trend-col.down.start { box-shadow: inset 3px 0 0 #7eb6ff; }
.soxx-trend .trend-date { color: #b7cfc8; font-weight: 600; letter-spacing: -0.04em; }
.soxx-trend .trend-candle { position: relative; margin: 4px 0 3px; }
.soxx-trend .trend-wick, .soxx-trend .trend-body { position: absolute; left: 50%; transform: translateX(-50%); }
.soxx-trend .trend-wick { width: 1.5px; }
.soxx-trend .trend-body { width: 8px; border-radius: 1px; }
.soxx-trend .trend-body.rise, .soxx-trend .trend-col:has(.trend-body.rise) .trend-wick { background: #e23b3b; }
.soxx-trend .trend-body.fall, .soxx-trend .trend-col:has(.trend-body.fall) .trend-wick { background: #3d8bfd; }
.soxx-trend .trend-cci { font-family: Consolas, monospace; font-weight: 700; letter-spacing: -0.04em; }
.soxx-trend .trend-cci.pos { color: #e2c36b; }
.soxx-trend .trend-cci.neg { color: #8cbcff; }
.soxx-trend .trend-mark { height: 4px; border-radius: 99px; margin: 3px 4px 2px; }
.soxx-trend .trend-mark.pos { background: #e2c36b; }
.soxx-trend .trend-mark.neg { background: #3d8bfd; }
.soxx-trend .trend-cols {
  grid-template-columns: repeat(30, minmax(72px, 1fr));
  min-width: 2280px;
}
.soxx-trend .trend-date, .soxx-trend .trend-cci { font-size: 13px; }
.soxx-trend .trend-candle { height: 96px; }
@container soxx (max-width: 520px) {
  .soxx-trend .trend-name { font-size: 18px; }
  .soxx-trend .trend-point { font-size: 20px; }
  .soxx-trend .trend-pill { font-size: 18px; min-width: 64px; padding: 6px 10px; }
  .soxx-trend .trend-judge { font-size: 14px; }
}
"""


def week_friday(start: date) -> date:
    return start + timedelta(days=(4 - start.weekday()) % 7)


def week_closed(start: date, now: datetime | None = None) -> bool:
    now_ny = (now or datetime.now(NY)).astimezone(NY)
    close_at = datetime.combine(week_friday(start), REGULAR_CLOSE, tzinfo=NY)
    return now_ny >= close_at


def _weekly_cci(bars: list[tuple]) -> list[float | None]:
    typical = [(bar[2] + bar[3] + bar[4]) / 3 for bar in bars]
    values: list[float | None] = []
    for index in range(len(bars)):
        if index + 1 < CCI_PERIOD:
            values.append(None)
            continue
        window = typical[index + 1 - CCI_PERIOD : index + 1]
        average = sum(window) / CCI_PERIOD
        deviation = sum(abs(price - average) for price in window) / CCI_PERIOD
        values.append(None if deviation == 0 else (typical[index] - average) / (0.015 * deviation))
    return values


def _flatten_weekly(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.droplevel(-1)
    frame = frame.reset_index()
    frame.columns = [str(column).strip().lower().replace(" ", "_") for column in frame.columns]
    date_column = next((name for name in ("date", "datetime", "index") if name in frame.columns), None)
    if date_column is None:
        raise RuntimeError(f"날짜 열이 없다. 실제 열: {list(frame.columns)}")
    frame = frame.rename(columns={date_column: "date"})
    missing = [name for name in ("date", "open", "high", "low", "close") if name not in frame.columns]
    if missing:
        raise RuntimeError(f"주봉 열 부족: {missing}. 실제 열: {list(frame.columns)}")
    out = frame[["date", "open", "high", "low", "close"]].copy()
    dates = pd.to_datetime(out["date"])
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_convert("America/New_York").dt.tz_localize(None)
    out["date"] = dates.dt.normalize()
    for name in ("open", "high", "low", "close"):
        out[name] = pd.to_numeric(out[name], errors="coerce")
    out = out.dropna(subset=["date", "open", "high", "low", "close"])
    out = out.drop_duplicates("date", keep="last").sort_values("date")
    return out.reset_index(drop=True)


def fetch_soxx_weekly() -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(
        SYMBOL,
        start=HISTORY_START,
        interval="1wk",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if raw is None or raw.empty:
        raise RuntimeError("야후에서 SOXX 주봉을 받지 못했다.")
    bars = _flatten_weekly(raw)
    if bars.empty:
        raise RuntimeError("받은 SOXX 주봉이 비어 있다.")
    closed = [week_closed(pd.Timestamp(day).date()) for day in bars["date"]]
    bars = bars.loc[closed].reset_index(drop=True)
    if bars.empty:
        raise RuntimeError("확정된 SOXX 주봉이 없다.")
    return bars


def read_soxx_meta() -> dict:
    if not SOXX_META_PATH.exists():
        return {}
    try:
        return json.loads(SOXX_META_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def load_soxx_weekly() -> pd.DataFrame:
    if not SOXX_PATH.exists():
        raise FileNotFoundError("저장된 SOXX 주봉이 없다.")
    bars = pd.read_csv(SOXX_PATH, parse_dates=["date"])
    bars["date"] = pd.to_datetime(bars["date"]).dt.normalize()
    return bars.sort_values("date").reset_index(drop=True)


def refresh_soxx() -> pd.DataFrame:
    bars = fetch_soxx_weekly()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = SOXX_PATH.with_suffix(".csv.tmp")
    bars.to_csv(temporary, index=False, date_format="%Y-%m-%d")
    temporary.replace(SOXX_PATH)
    last = pd.Timestamp(bars.iloc[-1]["date"]).strftime("%Y-%m-%d")
    SOXX_META_PATH.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
                "last_week": last,
                "rows": int(len(bars)),
                "error": None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _log(f"SOXX 주봉 rows={len(bars)} last_week={last}")
    return bars


def build_soxx_card(bars: pd.DataFrame | None = None) -> dict | None:
    frame = load_soxx_weekly() if bars is None else bars
    rows = []
    for record in frame.itertuples(index=False):
        start = pd.Timestamp(record.date).date()
        if not week_closed(start):
            continue
        rows.append((start, float(record.open), float(record.high), float(record.low), float(record.close)))
    paired = [(bar, value) for bar, value in zip(rows, _weekly_cci(rows)) if value is not None]
    if len(paired) < SHOWN_WEEKS:
        return None
    shown = paired[-SHOWN_WEEKS:]
    last_bar, last_value = shown[-1]
    last_cci = int(round(last_value))
    friday = week_friday(last_bar[0])
    weeks = []
    for bar, value in shown:
        ended = week_friday(bar[0])
        weeks.append(
            {
                "label": f"{ended.month}/{ended.day}",
                "open": round(bar[1], 2),
                "high": round(bar[2], 2),
                "low": round(bar[3], 2),
                "close": round(bar[4], 2),
                "cci": int(round(value)),
            }
        )
    return {
        "symbol": SYMBOL,
        "direction": "up" if last_cci >= 0 else "down",
        "close": round(last_bar[4], 2),
        "cci": last_cci,
        "as_of_label": f"{friday.month}월 {friday.day}일 주봉",
        "weeks": weeks,
    }


def _signed(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def render_soxx_card(card: dict) -> str:
    weeks = card["weeks"]
    high = max(week["high"] for week in weeks)
    low = min(week["low"] for week in weeks)
    span = high - low or 1
    previous_down = False
    columns = []
    for week in weeks:
        down = week["cci"] < 0
        started = down and not previous_down
        previous_down = down
        def place(price: float, high=high, span=span) -> float:
            return ((high - price) / span) * 64 + 4

        top = place(week["high"])
        bottom = place(week["low"])
        body_top = place(max(week["open"], week["close"]))
        body_bottom = place(min(week["open"], week["close"]))
        side = "rise" if week["close"] >= week["open"] else "fall"
        sign = "neg" if down else "pos"
        klass = "trend-col" + (" down" if down else "") + (" start" if started else "")
        columns.append(
            f'<div class="{klass}"><div class="trend-date">{html.escape(week["label"])}</div>'
            f'<div class="trend-candle">'
            f'<div class="trend-wick" style="top:{top / 72 * 100:.2f}%;height:{max(1, bottom - top) / 72 * 100:.2f}%"></div>'
            f'<div class="trend-body {side}" style="top:{body_top / 72 * 100:.2f}%;height:{max(2, body_bottom - body_top) / 72 * 100:.2f}%"></div>'
            f'</div><div class="trend-cci {sign}">{_signed(week["cci"])}</div>'
            f'<div class="trend-mark {sign}"></div></div>'
        )
    direction = "down" if card["direction"] == "down" else "up"
    word = "하락" if direction == "down" else "상승"
    body = (
        f'<article class="trend-card {direction}">'
        f'<div class="trend-head"><div class="trend-name">{html.escape(card["symbol"])}</div>'
        f'<div class="trend-signal"><span class="trend-point">{card["close"]:,.2f}</span>'
        f'<div class="trend-pill">{word}</div></div></div>'
        f'<p class="trend-judge">판단 CCI <b>{_signed(card["cci"])}</b> · {html.escape(card["as_of_label"])}</p>'
        f'<div class="trend-scroll"><div class="trend-cols">{"".join(columns)}</div></div>'
        f'<div class="trend-bar" hidden role="scrollbar" aria-label="주봉 좌우 이동" aria-valuemin="0" aria-valuemax="100">'
        f'<div class="trend-bar-thumb"></div></div>'
        f"</article>"
    )
    return f'<div class="soxx-trend"><style>{CARD_CSS}</style>{body}</div>'
