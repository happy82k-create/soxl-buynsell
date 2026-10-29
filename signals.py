"""SOXL 일봉 점수와 매수·매도 도장.

등 7개를 종가 기준으로 센다. 한 방향이 4개 이상이면 그 방향 점수다.
매수는 3차까지, 매도는 보유분을 한 번에 모두 판다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SCORE_MIN = 4
DROP_MIN = 0.03
STAMPS = ("1차", "2차", "3차", "매도")

LIGHT_ORDER = ("RSI", "스토캐스틱", "CCI", "윌리엄스", "볼린저", "MFI", "MACD")


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def _mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int = 14) -> pd.Series:
    typical = (high + low + close) / 3.0
    money = typical * volume.replace(0, np.nan)
    direction = typical.diff()
    positive = money.where(direction > 0, 0).rolling(period).sum()
    negative = money.where(direction < 0, 0).rolling(period).sum()
    ratio = positive / negative.replace(0, np.nan)
    return 100 - 100 / (1 + ratio)


def add_indicators(bars: pd.DataFrame) -> pd.DataFrame:
    df = bars.sort_values("date").reset_index(drop=True).copy()
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)

    df["rsi"] = _rsi(close, 14)

    lowest = low.rolling(14).min()
    highest = high.rolling(14).max()
    span = (highest - lowest).replace(0, np.nan)
    df["stoch_k"] = 100.0 * (close - lowest) / span
    df["willr"] = -100.0 * (highest - close) / span

    typical = (high + low + close) / 3.0
    typical_mean = typical.rolling(20).mean()
    typical_dev = typical.rolling(20).apply(
        lambda window: np.mean(np.abs(window - window.mean())), raw=True
    )
    df["cci"] = (typical - typical_mean) / (0.015 * typical_dev.replace(0, np.nan))

    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    df["bb_upper"] = mid + 2.0 * std
    df["bb_lower"] = mid - 2.0 * std

    df["mfi"] = _mfi(high, low, close, volume, 14)

    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    df["macd"] = macd
    df["macd_signal"] = macd.ewm(span=9, adjust=False).mean()

    buy_flags = pd.DataFrame(
        {
            "RSI": df["rsi"] < 30,
            "스토캐스틱": df["stoch_k"] < 20,
            "CCI": df["cci"] < -100,
            "윌리엄스": df["willr"] < -80,
            "볼린저": close < df["bb_lower"],
            "MFI": df["mfi"] < 20,
            "MACD": df["macd"] < df["macd_signal"],
        }
    ).fillna(False)
    sell_flags = pd.DataFrame(
        {
            "RSI": df["rsi"] > 70,
            "스토캐스틱": df["stoch_k"] > 80,
            "CCI": df["cci"] > 100,
            "윌리엄스": df["willr"] > -20,
            "볼린저": close > df["bb_upper"],
            "MFI": df["mfi"] > 80,
            "MACD": df["macd"] > df["macd_signal"],
        }
    ).fillna(False)
    df["buy_score"] = buy_flags.sum(axis=1).astype(int)
    df["sell_score"] = sell_flags.sum(axis=1).astype(int)
    df["buy_lights"] = buy_flags.apply(lambda row: ", ".join(LIGHT_ORDER[i] for i, on in enumerate(row.to_numpy()) if on), axis=1)
    df["sell_lights"] = sell_flags.apply(lambda row: ", ".join(LIGHT_ORDER[i] for i, on in enumerate(row.to_numpy()) if on), axis=1)
    return df


def _fill_text(fill_date: pd.Timestamp, fill_price: float) -> str:
    text = f"{fill_price:.2f}" if fill_price >= 1 else f"{fill_price:.4f}"
    return f"{fill_date.strftime('%Y-%m-%d')} {text}"


def _cheaper(close: float, last: float) -> bool:
    return close <= last * (1 - DROP_MIN)


def apply_stamps(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict | None]:
    df = frame.sort_values("date").reset_index(drop=True)
    holding: list[tuple[pd.Timestamp, float]] = []
    first_buy: pd.Timestamp | None = None
    last_price: float | None = None
    rows: list[dict] = []
    trades: list[dict] = []

    for record in df.itertuples(index=False):
        date = pd.Timestamp(record.date).normalize()
        close = float(record.close)
        buy_score = int(record.buy_score)
        sell_score = int(record.sell_score)
        held_n = len(holding)
        ref = last_price
        drop = ((ref - close) / ref) if ref else np.nan
        action = ""
        exit_avg = np.nan
        exit_ret = np.nan

        can_sell = held_n > 0 and first_buy is not None and date > first_buy and sell_score >= SCORE_MIN
        if can_sell:
            prices = [price for _, price in holding]
            exit_avg = float(sum(prices) / len(prices))
            exit_ret = (close - exit_avg) / exit_avg
            action = "매도"
            trades.append(
                {
                    "entry_date": holding[0][0].strftime("%Y-%m-%d"),
                    "exit_date": date.strftime("%Y-%m-%d"),
                    "avg_price": exit_avg,
                    "ret": float(exit_ret),
                    "fills": " | ".join(_fill_text(fill_date, fill_price) for fill_date, fill_price in holding),
                    "legs": len(holding),
                }
            )
            holding = []
            first_buy = None
            last_price = None
        elif held_n == 0 and buy_score >= SCORE_MIN:
            action = "1차"
            holding = [(date, close)]
            first_buy = date
            last_price = close
        elif held_n >= 3 and buy_score >= SCORE_MIN:
            action = "한도"
        elif held_n > 0 and buy_score >= SCORE_MIN:
            if _cheaper(close, float(ref)):
                action = "2차" if held_n == 1 else "3차"
                holding.append((date, close))
                last_price = close
            else:
                action = "생략"

        rows.append(
            {
                "held_n": held_n,
                "action": action,
                "ref_price": np.nan if ref is None else float(ref),
                "drop_pct": drop,
                "exit_avg": exit_avg,
                "exit_ret": exit_ret,
            }
        )

    out = df.copy()
    extra = pd.DataFrame(rows)
    for column in extra.columns:
        out[column] = extra[column].to_numpy()

    position = None
    if holding:
        prices = [price for _, price in holding]
        position = {
            "fills": [
                {"date": fill_date.strftime("%Y-%m-%d"), "price": float(price)} for fill_date, price in holding
            ],
            "avg_price": float(sum(prices) / len(prices)),
            "last_price": float(last_price),
        }
    trades_df = pd.DataFrame(trades, columns=["entry_date", "exit_date", "avg_price", "ret", "fills", "legs"])
    return out, trades_df, position


def build(bars: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict | None]:
    return apply_stamps(add_indicators(bars))


def finished_since_2020(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades
    done = trades[trades["exit_date"] >= "2020-01-01"].copy()
    return done.reset_index(drop=True)


def summarize(trades: pd.DataFrame) -> dict:
    done = finished_since_2020(trades)
    if done.empty:
        return {"count": 0, "compound": None, "worst_2022": None, "worst_date": None, "worst_ret": None}
    returns = done["ret"].astype(float)
    compound = float((1.0 + returns).prod() - 1.0)
    in_2022 = done[done["exit_date"].str.startswith("2022")]
    worst_2022 = float(in_2022["ret"].min()) if not in_2022.empty else None
    worst_idx = returns.idxmin()
    return {
        "count": int(len(done)),
        "compound": compound,
        "worst_2022": worst_2022,
        "worst_date": str(done.loc[worst_idx, "exit_date"]),
        "worst_ret": float(done.loc[worst_idx, "ret"]),
    }


def self_check() -> None:
    """가상 사이클. 2차는 정확히 3%, 매도 수익률은 -7/97."""
    sample = pd.DataFrame(
        [
            ("2024-02-01", 102.0, 1, 5, ""),
            ("2024-02-02", 100.0, 5, 0, "1차"),
            ("2024-02-05", 101.5, 0, 2, ""),
            ("2024-02-06", 98.0, 5, 0, "생략"),
            ("2024-02-07", 97.0, 4, 0, "2차"),
            ("2024-02-08", 90.0, 2, 0, ""),
            ("2024-02-09", 95.0, 4, 0, "생략"),
            ("2024-02-12", 94.0, 6, 0, "3차"),
            ("2024-02-13", 91.0, 4, 0, "한도"),
            ("2024-02-14", 93.0, 1, 3, ""),
            ("2024-02-15", 90.0, 0, 4, "매도"),
            ("2024-02-16", 92.0, 0, 5, ""),
            ("2024-02-20", 88.0, 4, 0, "1차"),
        ],
        columns=["date", "close", "buy_score", "sell_score", "expect"],
    )
    sample["date"] = pd.to_datetime(sample["date"])
    out, trades, position = apply_stamps(sample)
    got = out["action"].tolist()
    expected = sample["expect"].tolist()
    if got != expected:
        raise AssertionError(f"도장 불일치\n기대 {expected}\n결과 {got}")
    if len(trades) != 1:
        raise AssertionError(f"끝난 거래 {len(trades)}건")
    ret = float(trades.iloc[0]["ret"])
    if abs(ret - (-7.0 / 97.0)) > 1e-9:
        raise AssertionError(f"수익률 {ret}")
    if abs(float(trades.iloc[0]["avg_price"]) - 97.0) > 1e-9:
        raise AssertionError("평균 단가")
    if position is None or len(position["fills"]) != 1 or position["fills"][0]["price"] != 88.0:
        raise AssertionError(f"다음 1차 {position}")
    if int(trades.iloc[0]["legs"]) != 3:
        raise AssertionError("3차까지가 아니다")


if __name__ == "__main__":
    self_check()
    print("self_check ok")
