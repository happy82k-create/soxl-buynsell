"""아침 6시 작업이 호출하는 일봉 갱신."""

from __future__ import annotations

from market import refresh
from signals import build, self_check, summarize
from trend import build_soxx_card, refresh_soxx


def main() -> None:
    self_check()
    bars = refresh()
    _daily, trades, position = build(bars)
    stats = summarize(trades)
    legs = 0 if position is None else len(position["fills"])
    print(
        f"last_bar={bars.iloc[-1]['date'].strftime('%Y-%m-%d')} "
        f"trades_since_2020={stats['count']} "
        f"compound={stats['compound']} "
        f"worst_2022={stats['worst_2022']} "
        f"open_legs={legs}"
    )
    try:
        card = build_soxx_card(refresh_soxx())
    except Exception as exc:
        print(f"soxx_error={exc}")
        return
    if card is None:
        print("soxx_error=확정 주봉이 30주보다 짧다")
        return
    print(
        f"soxx_close={card['close']} soxx_cci={card['cci']} "
        f"soxx_direction={card['direction']} soxx_as_of={card['as_of_label']}"
    )


if __name__ == "__main__":
    main()
