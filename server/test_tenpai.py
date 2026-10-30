"""听牌 / 有役听牌 / 振听 自测：python test_tenpai.py"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from rules import tenpai
from tiles import counts_of, parse_hand

OK = 0
FAIL = 0


def check(name: str, got, want) -> None:
    global OK, FAIL
    if got == want:
        OK += 1
        print(f"[ok]   {name}: {got}")
    else:
        FAIL += 1
        print(f"[FAIL] {name}: got {got!r}   want {want!r}")


def main() -> int:
    # ── 1. 听牌 / 听什么 / 有役听牌 ──
    r = tenpai.tenpai_report(parse_hand("123m456m789m23p55s"))
    check("听牌判定（两面听 1p/4p）", r["tenpai"], True)
    check("听的牌", r["waits"], ["1p", "4p"])
    check("有役听牌（平和+一气）", r["has_yaku_ron"], True)
    check("荣和有役的牌", r["yaku_ron"], ["1p", "4p"])
    check("荣和那手的番数（4p）", r["detail"]["4p"]["ron"]["han"], 3)
    check("荣和那手的役种（4p）", r["detail"]["4p"]["ron"]["yaku"], ["平和", "一气通贯"])
    check("最高那手（含自摸）的番数", r["best"]["han"], 4)

    # ── 2. 无役听牌：荣和没役、自摸有役（门清自摸和）──
    r2 = tenpai.tenpai_report(parse_hand("234m567m234s99s44z"))
    check("无役听牌：能听", r2["tenpai"], True)
    check("无役听牌：听的牌", r2["waits"], ["9s", "bei"])
    check("无役听牌：荣和有役的牌 = 空", r2["yaku_ron"], [])
    check("无役听牌：荣和无役标记", r2["noyaku_ron"], True)
    check("无役听牌：自摸有役（门清自摸）", r2["yaku_tsumo"], ["9s", "bei"])
    check("无役听牌：is_tenpai_with_yaku(荣和) = False",
          tenpai.is_tenpai_with_yaku(parse_hand("234m567m234s99s44z")), False)
    check("无役听牌：is_tenpai_with_yaku(自摸也算) = True",
          tenpai.is_tenpai_with_yaku(parse_hand("234m567m234s99s44z"), tsumo_ok=True), True)

    # ── 3. 未听牌 ──
    r3 = tenpai.tenpai_report(parse_hand("147m258s369p1234z"))
    check("未听牌", r3["tenpai"], False)
    check("未听牌：没有待牌", r3["waits"], [])

    # ── 4. 振听：自己的牌河里有待牌（永久）──
    f = tenpai.furiten_info(counts_of(parse_hand("123m456m789m23p55s")), [],
                            ["1p", "9m"])
    check("永久振听", f["furiten"], True)
    check("永久振听：命中的待牌", f["hit"], ["1p"])
    check("永久振听：待牌不受影响", f["waits"], ["1p", "4p"])
    f2 = tenpai.furiten_info(counts_of(parse_hand("123m456m789m23p55s")), [], ["9m"])
    check("牌河无待牌 → 不振听", f2["furiten"], False)

    # ── 5. 同巡振听（见逃）/ 立直振听 ──
    f3 = tenpai.furiten_info(counts_of(parse_hand("123m456m789m23p55s")), [], [],
                             temp=True)
    check("同巡振听", (f3["furiten"], f3["temporary"]), (True, True))
    f4 = tenpai.furiten_info(counts_of(parse_hand("123m456m789m23p55s")), [], [],
                             riichi=True)
    check("立直后见逃（永久）", (f4["furiten"], f4["riichi"]), (True, True))

    # ── 6. 荣和能不能：有役 / 无役 / 振听 ──
    a = tenpai.ron_availability(parse_hand("123m456m789m23p55s"), "4p", [], [])
    check("荣和：有役可和", (a["ok"], a["win"]["han"], a["win"]["yaku"]),
          (True, 3, ["平和", "一气通贯"]))
    b = tenpai.ron_availability(parse_hand("234m567m234s99s44z"), "9s", [], [])
    check("荣和：无役不能和", (b["ok"], b["reason"].startswith("无役")), (False, True))
    c = tenpai.ron_availability(parse_hand("123m456m789m23p55s"), "4p", [], ["4p"])
    check("荣和：振听不能和", (c["ok"], c["reason"][:2]), (False, "振听"))

    # ── 7. 副露后的听牌（碰了一副东）──
    melds = [{"kind": "pon", "tiles": ["dong", "dong", "dong"], "called_tile": "dong",
              "from_seat": 1, "rot_index": 0}]
    r4 = tenpai.tenpai_report(parse_hand("234m567m78s99s"), melds)
    check("副露后听牌（10 张 + 1 副）", r4["tenpai"], True)
    check("副露后：役牌 场风东 有役", r4["has_yaku_ron"], True)
    check("副露后听什么", r4["waits"], ["6s", "9s"])

    print(f"\n{OK} 项通过 / {FAIL} 项失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
