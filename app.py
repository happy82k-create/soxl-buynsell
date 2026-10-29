"""SOXL 일봉 차트. 날짜를 누르면 그 날의 점수와 켜진 등을 보여 준다."""

from __future__ import annotations

import html
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from market import BARS_PATH, is_fresh, load_bars, read_meta, refresh
from signals import STAMPS, build, finished_since_2020, self_check, summarize
from trend import SOXX_PATH, build_soxx_card, load_soxx_weekly, read_soxx_meta, refresh_soxx, render_soxx_card

st.set_page_config(page_title="SOXL 매수 매도 타점", layout="wide")

STAMP_STYLE = {
    "1차": {"symbol": "triangle-up", "color": "#1d4ed8", "side": "low"},
    "2차": {"symbol": "triangle-up", "color": "#0e7490", "side": "low"},
    "3차": {"symbol": "triangle-up", "color": "#6d28d9", "side": "low"},
    "매도": {"symbol": "triangle-down", "color": "#9a3412", "side": "high"},
}


def fmt_price(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    number = float(value)
    if abs(number) >= 1:
        return f"{number:,.2f}"
    return f"{number:,.4f}"


def fmt_pct(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value) * 100:+.2f}%"


def fmt_num(value, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):.{digits}f}"


def explain(row) -> str:
    action = row.action
    if action == "1차":
        return "빈손이고 매수 점수가 4 이상이라 1차다. 가격은 이 날 종가다."
    if action in ("2차", "3차"):
        return f"직전 매수가 {fmt_price(row.ref_price)}보다 {row.drop_pct * 100:.2f}% 싸서 {action}다."
    if action == "생략":
        return (
            f"매수 점수 {int(row.buy_score)}. 직전 매수가 {fmt_price(row.ref_price)}보다 "
            f"{row.drop_pct * 100:.2f}%만 싸서 생략이다."
        )
    if action == "한도":
        return "이미 3차까지 샀다. 4차는 없다."
    if action == "매도":
        return (
            f"1차 다음 거래일 이후 매도 점수가 처음 4 이상이다. "
            f"평균 {fmt_price(row.exit_avg)}에 전량 매도. 수익률 {fmt_pct(row.exit_ret)}."
        )
    if int(row.held_n) == 0 and int(row.sell_score) >= 4:
        return "빈손이라 매도 도장은 없다."
    if int(row.held_n) > 0:
        return f"{int(row.held_n)}차까지 보유 중이다. 매도 점수 {int(row.sell_score)}."
    return "도장 없음."


def side_of(row, name: str) -> str:
    if name == "RSI":
        if row.rsi < 30:
            return "매수"
        if row.rsi > 70:
            return "매도"
    elif name == "스토캐스틱":
        if row.stoch_k < 20:
            return "매수"
        if row.stoch_k > 80:
            return "매도"
    elif name == "CCI":
        if row.cci < -100:
            return "매수"
        if row.cci > 100:
            return "매도"
    elif name == "윌리엄스":
        if row.willr < -80:
            return "매수"
        if row.willr > -20:
            return "매도"
    elif name == "볼린저":
        if pd.notna(row.bb_lower) and row.close < row.bb_lower:
            return "매수"
        if pd.notna(row.bb_upper) and row.close > row.bb_upper:
            return "매도"
    elif name == "MFI":
        if row.mfi < 20:
            return "매수"
        if row.mfi > 80:
            return "매도"
    elif name == "MACD":
        if pd.notna(row.macd) and pd.notna(row.macd_signal):
            if row.macd < row.macd_signal:
                return "매수"
            if row.macd > row.macd_signal:
                return "매도"
    return "중립"


def indicator_table(row) -> pd.DataFrame:
    bollinger = (
        f"종가 {fmt_price(row.close)} · 하단 {fmt_price(row.bb_lower)} · 상단 {fmt_price(row.bb_upper)}"
    )
    macd = f"선 {fmt_num(row.macd, 3)} · 시그널 {fmt_num(row.macd_signal, 3)}"
    rows = [
        ("RSI", fmt_num(row.rsi), side_of(row, "RSI")),
        ("스토캐스틱", fmt_num(row.stoch_k), side_of(row, "스토캐스틱")),
        ("CCI", fmt_num(row.cci), side_of(row, "CCI")),
        ("윌리엄스", fmt_num(row.willr), side_of(row, "윌리엄스")),
        ("볼린저", bollinger, side_of(row, "볼린저")),
        ("MFI", fmt_num(row.mfi), side_of(row, "MFI")),
        ("MACD", macd, side_of(row, "MACD")),
    ]
    return pd.DataFrame(rows, columns=["등", "값", "상태"])


def hover_line(row) -> str:
    action = row.action or "없음"
    buy = row.buy_lights or "없음"
    sell = row.sell_lights or "없음"
    return (
        f"{row.date_str}<br>"
        f"시가 {fmt_price(row.open)}  고가 {fmt_price(row.high)}<br>"
        f"저가 {fmt_price(row.low)}  종가 {fmt_price(row.close)}<br>"
        f"판정 {action}<br>"
        f"매수 {int(row.buy_score)} · {buy}<br>"
        f"매도 {int(row.sell_score)} · {sell}<br>"
        f"{explain(row)}"
    )


def make_chart(view: pd.DataFrame) -> go.Figure:
    hover = [hover_line(row) for row in view.itertuples(index=False)]
    figure = go.Figure()
    figure.add_trace(
        go.Candlestick(
            x=view["date"],
            open=view["open"],
            high=view["high"],
            low=view["low"],
            close=view["close"],
            name="SOXL",
            customdata=view["date_str"].to_numpy().reshape(-1, 1),
            hovertext=hover,
            hoverinfo="text",
            increasing_line_color="#0f766e",
            decreasing_line_color="#b91c1c",
            increasing_fillcolor="#0f766e",
            decreasing_fillcolor="#b91c1c",
        )
    )
    for stamp in STAMPS:
        part = view[view["action"] == stamp]
        if part.empty:
            continue
        style = STAMP_STYLE[stamp]
        y_value = part["low"] * 0.985 if style["side"] == "low" else part["high"] * 1.015
        part_hover = [hover_line(row) for row in part.itertuples(index=False)]
        figure.add_trace(
            go.Scatter(
                x=part["date"],
                y=y_value,
                mode="markers+text",
                name=stamp,
                text=[stamp] * len(part),
                textposition="bottom center" if style["side"] == "low" else "top center",
                textfont={"color": style["color"], "size": 12},
                marker={"symbol": style["symbol"], "size": 12, "color": style["color"]},
                customdata=part["date_str"].to_numpy().reshape(-1, 1),
                hovertext=part_hover,
                hoverinfo="text",
            )
        )
    figure.update_layout(
        margin={"l": 8, "r": 16, "t": 36, "b": 8},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        xaxis_rangeslider_visible=True,
        hovermode="closest",
        dragmode="pan",
        clickmode="event+select",
        font={"family": "Malgun Gothic, sans-serif"},
        yaxis_title="가격",
        xaxis_title="날짜",
        height=680,
        uirevision="soxl",
        hoverlabel={"font": {"family": "Malgun Gothic, sans-serif", "size": 14}},
    )
    figure.update_yaxes(automargin=True)
    figure.update_xaxes(automargin=True, rangebreaks=[{"bounds": ["sat", "mon"]}])
    return figure


def clicked_date(event) -> str | None:
    if event is None:
        return None
    selection = getattr(event, "selection", None)
    if selection is None and isinstance(event, dict):
        selection = event.get("selection")
    if selection is None:
        return None
    points = selection.get("points", []) if isinstance(selection, dict) else getattr(selection, "points", None)
    if not points:
        return None
    point = points[0]
    if not isinstance(point, dict):
        return None
    custom = point.get("customdata")
    if isinstance(custom, (list, tuple)) and custom:
        return str(custom[0])[:10]
    if isinstance(custom, str):
        return custom[:10]
    raw = point.get("x")
    return str(raw)[:10] if raw else None


def slice_span(daily: pd.DataFrame, span: str) -> pd.DataFrame:
    if span == "전체":
        return daily
    if span == "2020년부터":
        return daily[daily["date"] >= "2020-01-01"]
    last = daily["date"].max()
    days = 365 if span == "최근 1년" else 365 * 3
    return daily[daily["date"] >= last - pd.Timedelta(days=days)]


@st.cache_data(show_spinner=False)
def cached_build(stamp: str) -> tuple[pd.DataFrame, pd.DataFrame, dict | None]:
    bars = load_bars()
    return build(bars)


def ensure_bars(force: bool) -> tuple[pd.DataFrame, dict]:
    meta = read_meta()
    failed = st.session_state.get("fetch_error")
    if (force or not is_fresh(meta)) and (force or not failed):
        try:
            with st.spinner("SOXL 일봉을 받는 중"):
                refresh()
            st.session_state["fetch_error"] = None
        except Exception as exc:
            st.session_state["fetch_error"] = str(exc)
        meta = read_meta()
    error = st.session_state.get("fetch_error") or meta.get("error")
    try:
        bars = load_bars()
    except FileNotFoundError:
        st.error(error or "저장된 일봉이 없고, 야후에서 받지도 못했다.")
        st.stop()
    if error:
        st.warning(f"최근 수신에 실패해서 저장분을 보여 준다. {error}")
    return bars, meta


def ensure_soxx(force: bool) -> None:
    meta = read_soxx_meta()
    soxx_meta = {"updated_at": meta.get("updated_at"), "error": meta.get("error")}
    stale = not SOXX_PATH.exists() or not is_fresh(soxx_meta)
    if not force and not stale:
        return
    if not force and st.session_state.get("soxx_error"):
        return
    try:
        with st.spinner("SOXX 주봉을 받는 중"):
            refresh_soxx()
        st.session_state["soxx_error"] = None
    except Exception as exc:
        st.session_state["soxx_error"] = str(exc)


def render_soxx_slot() -> None:
    error = st.session_state.get("soxx_error")
    try:
        card = build_soxx_card(load_soxx_weekly())
    except FileNotFoundError:
        card = None
    if card is None:
        detail = f" {error}" if error else ""
        st.caption(f"SOXX 주봉 CCI를 아직 그리지 못했다.{detail}")
        return
    st.html(render_soxx_card(card))


@st.fragment(run_every=timedelta(minutes=1))
def watch_morning_update() -> None:
    meta = read_meta()
    current = meta.get("updated_at")
    seen = st.session_state.get("seen_updated_at")
    if seen is None:
        st.session_state["seen_updated_at"] = current
        return
    stamp_changed = current != seen
    needs_fetch = not is_fresh(meta) and not st.session_state.get("fetch_error")
    if stamp_changed or needs_fetch:
        st.session_state["seen_updated_at"] = current
        st.rerun()


def _tone(label: str) -> str:
    if label == "매수":
        return "buy"
    if label == "매도":
        return "sell"
    return "flat"


def render_day(row) -> None:
    action = row.action or "도장 없음"
    lights = []
    for record in indicator_table(row).itertuples(index=False):
        tone = _tone(str(record.상태))
        lights.append(
            "<tr>"
            f"<th>{html.escape(str(record.등))}</th>"
            f"<td>{html.escape(str(record.값))}</td>"
            f'<td><span class="tone {tone}">{html.escape(str(record.상태))}</span></td>'
            "</tr>"
        )
    st.html(
        '<section class="day-panel">'
        f'<h3 class="day-date">{html.escape(str(row.date_str))}</h3>'
        f'<p class="day-action"><b>{html.escape(action)}</b> · 종가 {html.escape(fmt_price(row.close))}</p>'
        '<div class="day-scores">'
        f'<div class="score buy"><span>매수 점수</span><strong>{int(row.buy_score)}</strong></div>'
        f'<div class="score sell"><span>매도 점수</span><strong>{int(row.sell_score)}</strong></div>'
        "</div>"
        f'<p class="day-explain">{html.escape(explain(row))}</p>'
        f'<table class="day-lights"><tbody>{"".join(lights)}</tbody></table>'
        "</section>"
    )


def render_trade_cards(done: pd.DataFrame) -> None:
    cards = []
    for row in done.itertuples(index=False):
        ret = float(row.ret)
        tone = "buy" if ret >= 0 else "sell"
        cards.append(
            f'<article class="trade-card {tone}">'
            f'<div class="trade-top"><b>{html.escape(str(row.entry_date))}</b>'
            f'<span class="tone {tone}">{html.escape(fmt_pct(ret))}</span></div>'
            f"<p>평균 {html.escape(fmt_price(row.avg_price))} · 매도 {html.escape(str(row.exit_date))}</p>"
            f'<p class="trade-fills">{html.escape(str(row.fills))}</p>'
            "</article>"
        )
    st.html(f'<div class="trade-list">{"".join(cards)}</div>')


LAYOUT_HTML = """
<style id="soxl-layout">
footer[data-testid="stFooter"] { display: none; }
[data-testid="stCaptionContainer"] { font-size: 0.98rem; line-height: 1.5; }
[data-testid="stAlert"] p { font-size: 1.05rem; line-height: 1.45; }

.day-panel { color: #102027; }
.day-date { margin: 0.15rem 0 0.25rem; font-size: 1.45rem; letter-spacing: -0.03em; }
.day-action { margin: 0 0 0.7rem; font-size: 1.05rem; }
.day-scores { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.score {
  border-radius: 12px; padding: 8px 10px 6px;
  background: #fff; border: 1px solid #d7e2df;
}
.score span { display: block; color: #5c726c; font-size: 0.82rem; }
.score strong { display: block; font-size: 2rem; line-height: 1.1; letter-spacing: -0.04em; }
.score.buy strong { color: #1d4ed8; }
.score.sell strong { color: #9a3412; }
.day-explain { margin: 0.75rem 0; font-size: 0.98rem; line-height: 1.5; }
.day-lights { width: 100%; border-collapse: collapse; font-size: 0.95rem; }
.day-lights th, .day-lights td { text-align: left; padding: 7px 4px; border-bottom: 1px solid #e4eeeb; vertical-align: top; }
.day-lights th { width: 5.2rem; font-weight: 700; }
.tone { display: inline-block; min-width: 2.6rem; text-align: center; border-radius: 999px; padding: 2px 8px; font-weight: 700; font-size: 0.85rem; }
.tone.buy { color: #1d4ed8; background: #dbe7ff; }
.tone.sell { color: #9a3412; background: #ffedd5; }
.tone.flat { color: #475569; background: #e8eef2; }

.trade-list { display: grid; gap: 8px; }
.trade-card { border: 1px solid #d7e2df; border-left-width: 5px; border-radius: 12px; padding: 10px 12px; background: #fff; }
.trade-card.buy { border-left-color: #0f766e; }
.trade-card.sell { border-left-color: #b91c1c; }
.trade-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 1.05rem; }
.trade-card p { margin: 0.3rem 0 0; line-height: 1.4; }
.trade-fills { color: #526660; font-size: 0.92rem; }

.soxl-mark {
  display: flex;
  align-items: center;
  gap: 14px;
  width: fit-content;
  max-width: 100%;
  padding: 8px 18px 8px 10px;
  border-radius: 18px;
  background: #102027;
  color: #f7fbf9;
}
.soxl-mark-icon { position: relative; width: 78px; height: 58px; flex: 0 0 auto; }
.soxl-mark-icon .c1, .soxl-mark-icon .c2, .soxl-mark-icon .c3 {
  position: absolute; top: 0; width: 14px; height: 58px;
}
.soxl-mark-icon .wick, .soxl-mark-icon .body { position: absolute; left: 50%; transform: translateX(-50%); border-radius: 2px; }
.soxl-mark-icon .wick { width: 2px; }
.soxl-mark-icon .body { width: 12px; }
.soxl-mark-icon .c1 { left: 14px; }
.soxl-mark-icon .c2 { left: 39px; }
.soxl-mark-icon .c3 { left: 64px; }
.soxl-mark-icon .c1 .wick { top: 8px; height: 34px; background: #e23b3b; }
.soxl-mark-icon .c1 .body { top: 14px; height: 16px; background: #e23b3b; }
.soxl-mark-icon .c2 .wick { top: 2px; height: 42px; background: #14b8a6; }
.soxl-mark-icon .c2 .body { top: 10px; height: 24px; background: #14b8a6; }
.soxl-mark-icon .c3 .wick { top: 12px; height: 32px; background: #e23b3b; }
.soxl-mark-icon .c3 .body { top: 18px; height: 14px; background: #e23b3b; }
.soxl-mark-icon .buy, .soxl-mark-icon .sell {
  position: absolute; width: 0; height: 0;
  border-left: 6px solid transparent; border-right: 6px solid transparent;
}
.soxl-mark-icon .buy { left: 33px; top: 48px; border-bottom: 8px solid #3d8bfd; }
.soxl-mark-icon .sell { left: 58px; top: 2px; border-top: 8px solid #ffb089; }
.soxl-mark-name {
  font-size: 1.85rem;
  font-weight: 800;
  letter-spacing: -0.045em;
  line-height: 1;
}
.soxl-mark-phrase {
  display: flex;
  gap: 8px;
  margin-top: 5px;
  font-size: 1.15rem;
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 1;
}
.soxl-mark-phrase .buy { color: #8cbcff; }
.soxl-mark-phrase .sell { color: #ffb089; }
.soxl-mark-phrase .point { color: #e2c36b; }

.st-key-soxx_mobile { display: none !important; }
.st-key-trades_mobile { display: none !important; }

@media (min-width: 900px) {
  [data-testid="stMainBlockContainer"] {
    max-width: 1600px;
    padding-left: 1.4rem;
    padding-right: 1.4rem;
  }
  .st-key-page_head [data-testid="stHorizontalBlock"] { align-items: center; }
  .st-key-chart_row .js-plotly-plot { height: min(760px, max(640px, 70vh)) !important; }
  .st-key-chart_row [data-testid="stHorizontalBlock"] { align-items: flex-start; gap: 1.1rem; }
  .st-key-chart_row [data-testid="stColumn"]:last-child {
    position: sticky;
    top: 0.75rem;
    background: #f4f8f6;
    border: 1px solid #d7e2df;
    border-radius: 16px;
    padding: 6px 14px 12px;
  }
  .st-key-soxx_desktop { margin-top: 0.3rem; }
  .st-key-trades_desktop [data-testid="stDataFrame"] { font-size: 15px; }
}

@media (max-width: 899px) {
  header[data-testid="stHeader"] { display: none !important; }
  .day-lights th { width: auto; white-space: nowrap; padding-right: 12px; }
  [data-testid="stMainBlockContainer"] {
    padding-left: 0.55rem;
    padding-right: 0.55rem;
    padding-top: 0.8rem;
  }
  .soxl-mark { gap: 10px; padding: 8px 12px 8px 8px; }
  .soxl-mark-name { font-size: 1.45rem; }
  .soxl-mark-phrase { font-size: 1.02rem; gap: 6px; }
  .st-key-page_head [data-testid="stHorizontalBlock"],
  .st-key-chart_row [data-testid="stHorizontalBlock"],
  .st-key-stats_row [data-testid="stHorizontalBlock"] {
    flex-direction: column !important;
    gap: 0.35rem !important;
  }
  .st-key-page_head [data-testid="stColumn"],
  .st-key-chart_row [data-testid="stColumn"],
  .st-key-stats_row [data-testid="stColumn"] {
    width: 100% !important;
    flex: 1 1 100% !important;
    min-width: 0 !important;
  }
  .st-key-span_radio div[role="radiogroup"] { flex-wrap: wrap; row-gap: 0.2rem; }
  .st-key-span_radio label { font-size: 1.02rem; }
  [data-testid="stAlert"] { padding: 0.7rem 0.8rem; }
  [data-testid="stAlert"] p, [data-testid="stCaptionContainer"] { font-size: 1.02rem; }
  .st-key-soxx_mobile { display: block !important; }
  .st-key-soxx_desktop { display: none !important; }
  .st-key-chart_row [data-testid="stColumn"]:last-child {
    background: #f4f8f6;
    border: 1px solid #d7e2df;
    border-radius: 16px;
    padding: 4px 12px 12px;
    margin-top: 0.45rem;
  }
  .day-date { font-size: 1.7rem; }
  .day-action, .day-explain { font-size: 1.08rem; }
  .score strong { font-size: 2.35rem; }
  .day-lights { font-size: 1.05rem; }
  .day-lights th, .day-lights td { padding: 9px 4px; }
  .st-key-stats_row [data-testid="stMetricValue"] { font-size: 1.7rem; }
  .st-key-chart_row .js-plotly-plot { height: min(560px, max(430px, 58vh)) !important; }
  .st-key-trades_desktop { display: none !important; }
  .st-key-trades_mobile { display: block !important; }
  h2 { font-size: 1.3rem !important; }
}
</style>
<script>
(function () {
  function mobile() { return window.matchMedia("(max-width: 899px)").matches; }
  function fitChart() {
    document.querySelectorAll(".js-plotly-plot").forEach(function (gd) {
      if (!window.Plotly || !gd.layout || gd.dataset.soxlBusy === "1") return;
      var phone = mobile();
      var boxH = Math.round(gd.getBoundingClientRect().height);
      if (!boxH) return;
      var sliderOn = !phone;
      var sliderNow = !(gd.layout.xaxis && gd.layout.xaxis.rangeslider && gd.layout.xaxis.rangeslider.visible === false);
      var stamp = (phone ? "m" : "d") + ":" + boxH + ":" + (sliderOn ? "s" : "n");
      var svg = gd.querySelector("svg.main-svg");
      var svgH = svg ? Math.round(svg.getBoundingClientRect().height) : 0;
      if (gd.dataset.soxlStamp === stamp && Math.abs(svgH - boxH) < 12 && sliderNow === sliderOn) return;
      var attempt = Number(gd.dataset.soxlAttempt || "0");
      if (attempt > 8) return;
      gd.dataset.soxlBusy = "1";
      gd.dataset.soxlAttempt = String(attempt + 1);
      var stamps = [];
      (gd.data || []).forEach(function (trace, index) {
        if (trace.mode && String(trace.mode).indexOf("markers") >= 0) stamps.push(index);
      });
      window.Plotly.relayout(gd, {
        height: boxH,
        "xaxis.rangeslider.visible": sliderOn,
        "legend.font.size": phone ? 13 : 12,
        "xaxis.tickfont.size": phone ? 12 : 13,
        "yaxis.tickfont.size": phone ? 12 : 13,
        "hoverlabel.font.size": phone ? 15 : 14
      }).then(function () {
        var drawn = gd.querySelector("svg.main-svg");
        var drawnH = drawn ? Math.round(drawn.getBoundingClientRect().height) : 0;
        if (Math.abs(drawnH - boxH) < 12) {
          gd.dataset.soxlStamp = stamp;
          gd.dataset.soxlAttempt = "0";
          [250, 700, 1400].forEach(function (delay) {
            setTimeout(function () {
              var again = gd.querySelector("svg.main-svg");
              var againH = again ? Math.round(again.getBoundingClientRect().height) : 0;
              if (Math.abs(againH - boxH) < 12) return;
              delete gd.dataset.soxlStamp;
              delete gd.dataset.soxlAttempt;
              fit();
            }, delay);
          });
        }
        var bar = gd.querySelector(".modebar");
        if (bar) bar.style.display = phone ? "none" : "";
        if (!stamps.length) return null;
        return window.Plotly.restyle(gd, {
          "textfont.size": phone ? 14 : 12,
          "marker.size": phone ? 16 : 13
        }, stamps);
      }).catch(function () {
        delete gd.dataset.soxlStamp;
      }).finally(function () {
        delete gd.dataset.soxlBusy;
        var drawn = gd.querySelector("svg.main-svg");
        var drawnH = drawn ? Math.round(drawn.getBoundingClientRect().height) : 0;
        if (Math.abs(drawnH - boxH) >= 12 && Number(gd.dataset.soxlAttempt || "0") <= 8) {
          setTimeout(fit, 150);
        }
      });
    });
  }
  function fitWeeks() {
    document.querySelectorAll(".trend-scroll").forEach(function (el) {
      if (!el.getClientRects().length || el.dataset.soxlScrolled === "1") return;
      el.scrollLeft = el.scrollWidth;
      el.dataset.soxlScrolled = "1";
    });
  }
  function syncWeekBars() {
    document.querySelectorAll(".trend-scroll").forEach(function (scroll) {
      var bar = scroll.parentElement && scroll.parentElement.querySelector(".trend-bar");
      if (!bar) return;
      var thumb = bar.querySelector(".trend-bar-thumb");
      var max = Math.max(0, scroll.scrollWidth - scroll.clientWidth);
      if (scroll.clientWidth < 8 || max <= 1) {
        bar.hidden = true;
        return;
      }
      bar.hidden = false;
      var width = Math.max(48, bar.clientWidth * (scroll.clientWidth / scroll.scrollWidth));
      width = Math.min(width, bar.clientWidth);
      var travel = Math.max(1, bar.clientWidth - width);
      thumb.style.width = width + "px";
      thumb.style.transform = "translateX(" + ((scroll.scrollLeft / max) * travel) + "px)";
      bar.setAttribute("aria-valuenow", String(Math.round((scroll.scrollLeft / max) * 100)));
      if (bar.dataset.bound === "1") return;
      bar.dataset.bound = "1";
      bar.tabIndex = 0;
      scroll.addEventListener("scroll", function () { syncWeekBars(); }, { passive: true });
      bar.addEventListener("keydown", function (event) {
        var step = Math.max(48, scroll.clientWidth * 0.35);
        if (event.key === "ArrowLeft") scroll.scrollLeft -= step;
        if (event.key === "ArrowRight") scroll.scrollLeft += step;
      });
      bar.addEventListener("pointerdown", function (event) {
        if (event.button !== undefined && event.button !== 0) return;
        event.preventDefault();
        bar.setPointerCapture(event.pointerId);
        var thumbRect = thumb.getBoundingClientRect();
        var onThumb = event.clientX >= thumbRect.left && event.clientX <= thumbRect.right;
        var originX = event.clientX;
        if (!onThumb) {
          var span = Math.max(1, bar.clientWidth - thumb.offsetWidth);
          var limit = Math.max(0, scroll.scrollWidth - scroll.clientWidth);
          var ratio = (event.clientX - bar.getBoundingClientRect().left - thumb.offsetWidth / 2) / span;
          scroll.scrollLeft = Math.min(limit, Math.max(0, ratio * limit));
          originX = event.clientX;
        }
        var originScroll = scroll.scrollLeft;
        function move(ev) {
          var span = Math.max(1, bar.clientWidth - thumb.offsetWidth);
          var limit = Math.max(0, scroll.scrollWidth - scroll.clientWidth);
          scroll.scrollLeft = originScroll + ((ev.clientX - originX) / span) * limit;
          syncWeekBars();
        }
        function end() {
          bar.removeEventListener("pointermove", move);
          bar.removeEventListener("pointerup", end);
          bar.removeEventListener("pointercancel", end);
          syncWeekBars();
        }
        bar.addEventListener("pointermove", move);
        bar.addEventListener("pointerup", end);
        bar.addEventListener("pointercancel", end);
      });
    });
  }
  function fit() { fitChart(); fitWeeks(); syncWeekBars(); }
  function schedule() {
    clearTimeout(window.__soxlMut);
    window.__soxlMut = setTimeout(fit, 60);
  }
  if (window.__soxlOnResize) window.removeEventListener("resize", window.__soxlOnResize);
  window.__soxlOnResize = function () {
    clearTimeout(window.__soxlResize);
    window.__soxlResize = setTimeout(function () {
        document.querySelectorAll(".js-plotly-plot").forEach(function (gd) {
          delete gd.dataset.soxlStamp;
          delete gd.dataset.soxlAttempt;
        });
      document.querySelectorAll(".trend-scroll").forEach(function (el) { delete el.dataset.soxlScrolled; });
      fit();
    }, 160);
  };
  window.addEventListener("resize", window.__soxlOnResize);
  if (window.__soxlObserver) window.__soxlObserver.disconnect();
  window.__soxlObserver = new MutationObserver(schedule);
  window.__soxlObserver.observe(document.body, {childList: true, subtree: true});
  schedule();
})();
</script>
"""


TITLE_HTML = """
<div class="soxl-mark">
  <div class="soxl-mark-icon" aria-hidden="true">
    <div class="c1"><i class="wick"></i><i class="body"></i></div>
    <div class="c2"><i class="wick"></i><i class="body"></i></div>
    <div class="c3"><i class="wick"></i><i class="body"></i></div>
    <i class="buy"></i>
    <i class="sell"></i>
  </div>
  <div>
    <div class="soxl-mark-name">SOXL</div>
    <div class="soxl-mark-phrase"><span class="buy">매수</span><span class="sell">매도</span><span class="point">타점</span></div>
  </div>
</div>
"""


def main() -> None:
    if not st.session_state.get("rules_checked"):
        self_check()
        st.session_state["rules_checked"] = True

    st.html(LAYOUT_HTML, unsafe_allow_javascript=True)
    with st.container(key="page_head"):
        title_col, button_col = st.columns([4, 1])
        title_col.html(TITLE_HTML)
        force = button_col.button("다시 받기", width="stretch")
    bars, meta = ensure_bars(force)
    ensure_soxx(force)
    del bars
    st.session_state["seen_updated_at"] = meta.get("updated_at")
    watch_morning_update()
    daily, trades, position = cached_build(str(meta.get("updated_at") or BARS_PATH.stat().st_mtime))
    daily = daily.copy()
    daily["date_str"] = daily["date"].dt.strftime("%Y-%m-%d")
    latest = daily.iloc[-1]
    updated = meta.get("updated_at") or "없음"
    if updated != "없음":
        updated = updated.replace("T", " ").removesuffix("+09:00")
    st.caption(
        f"수신 {updated} · 마지막 봉 {latest.date_str} · 매일 06:00에 일봉을 다시 받는다. "
        "가격은 분할을 반영한 수정 주가다."
    )

    latest_action = latest.action or "도장 없음"
    banner = (
        f"최근 봉 {latest.date_str} · {latest_action} · 종가 {fmt_price(latest.close)} · "
        f"매수 {int(latest.buy_score)} · 매도 {int(latest.sell_score)}"
    )
    if latest.action == "매도":
        st.error(banner)
    elif latest.action in ("1차", "2차", "3차"):
        st.success(banner)
    elif latest.action in ("생략", "한도"):
        st.warning(banner)
    else:
        st.info(banner)
    if position:
        fills = ", ".join(f"{item['date']} {fmt_price(item['price'])}" for item in position["fills"])
        st.caption(f"보유 {len(position['fills'])}차 · 평균 {fmt_price(position['avg_price'])} · {fills}")
    else:
        st.caption("빈손. 매수 점수 4 이상을 기다린다.")

    span = st.radio(
        "구간",
        ["최근 1년", "최근 3년", "2020년부터", "전체"],
        horizontal=True,
        index=0,
        key="span_radio",
    )
    view = slice_span(daily, span).reset_index(drop=True)
    with st.container(key="chart_row"):
        chart_col, detail_col = st.columns([3.15, 1], gap="medium")
        with chart_col:
            event = st.plotly_chart(
                make_chart(view),
                width="stretch",
                on_select="rerun",
                selection_mode="points",
                theme=None,
                key="soxl_chart",
                config={
                    "scrollZoom": True,
                    "displaylogo": False,
                    "responsive": True,
                    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                },
            )
            st.caption("캔들 도장은 1차, 2차, 3차, 매도다. 생략과 한도는 그 날에 커서를 올리면 보인다.")
            with st.container(key="soxx_mobile"):
                render_soxx_slot()
        picked = clicked_date(event)
        if picked:
            st.session_state["picked"] = picked
        chosen = st.session_state.get("picked") or latest.date_str
        match = daily[daily["date_str"] == chosen]
        with detail_col:
            if match.empty:
                st.write("날짜를 누르면 매수 점수, 매도 점수, 켜진 등 이름이 여기 나온다.")
            else:
                render_day(match.iloc[0])
    with st.container(key="soxx_desktop"):
        render_soxx_slot()

    st.header("2020년 이후 끝난 거래")
    done = finished_since_2020(trades).sort_values("exit_date", ascending=False)
    stats = summarize(trades)
    with st.container(key="stats_row"):
        metric_a, metric_b, metric_c = st.columns(3)
        metric_a.metric("끝난 거래", f"{stats['count']}건")
        metric_b.metric("누적 수익률", "—" if stats["compound"] is None else fmt_pct(stats["compound"]))
        metric_c.metric("2022년 가장 큰 손실", "—" if stats["worst_2022"] is None else fmt_pct(stats["worst_2022"]))
    st.caption("누적은 끝난 거래 수익률을 순서대로 곱한 값이다. 평균 단가는 같은 수량의 산술평균이다.")
    if done.empty:
        st.write("2020년 이후 끝난 거래가 없다.")
    else:
        table = pd.DataFrame(
            {
                "매수일": done["entry_date"],
                "평균 단가": done["avg_price"].map(fmt_price),
                "매도일": done["exit_date"],
                "수익률": done["ret"].map(fmt_pct),
                "체결": done["fills"],
            }
        )

        def paint_return(value: str) -> str:
            if str(value).startswith("-"):
                return "color: #9a3412; font-weight: 700"
            if str(value).startswith("+"):
                return "color: #0f766e; font-weight: 700"
            return ""

        with st.container(key="trades_desktop"):
            st.dataframe(
                table.style.map(paint_return, subset=["수익률"]),
                hide_index=True,
                width="stretch",
                column_config={
                    "매수일": st.column_config.TextColumn(width="small"),
                    "평균 단가": st.column_config.TextColumn(width="small"),
                    "매도일": st.column_config.TextColumn(width="small"),
                    "수익률": st.column_config.TextColumn(width="small"),
                    "체결": st.column_config.TextColumn(width="large"),
                },
            )
        with st.container(key="trades_mobile"):
            render_trade_cards(done)


main()
