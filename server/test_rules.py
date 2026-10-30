# -*- coding: utf-8 -*-
"""
规则引擎自测：和牌 / 听牌 / 吃碰杠 / 役种 / 符数 / 点数
运行：python test_rules.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from tiles import counts_of, index_of, parse_hand
from rules import agari, calls, yaku
from rules.score import calc_fu, payments

OK = FAIL = 0


def check(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name}" + (f"  ({extra})" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {extra}")


def judge(text, win, *, melds=(), tsumo=False, is_dealer=False, **kw):
    tiles = parse_hand(text)
    ctx = {"counts": counts_of(tiles), "tiles": tiles, "win_index": index_of(win),
           "melds": list(melds), "is_dealer": is_dealer, "tsumo": tsumo,
           "seat_wind": "dong", "round_wind": "dong", "rules": {"kuitan": True}}
    ctx.update(kw)
    return yaku.judge(ctx)


def names(res):
    return [y["name"] for y in res.get("yaku", [])]


def main():
    print("=" * 70)
    print(" 天马麻将 · 规则引擎自测")
    print("=" * 70)

    # ── 1. 和牌 / 听牌 ──────────────────────────────────────────────────────
    print("\n[1] 和牌判定 / 听牌判定")
    check("4 面子 + 雀头 = 和牌", agari.is_winning(counts_of(parse_hand("123m456m789m123p11s"))))
    check("少一张不是和牌",
          not agari.is_winning(counts_of(parse_hand("123m456m789m123p1s"))))
    check("七对子", agari.is_winning(counts_of(parse_hand("11223344556677m"))))
    check("四张一样不算两对（不是七对子）",
          not agari.is_chiitoitsu(counts_of(parse_hand("11112233445566m"))))
    check("国士无双", agari.is_winning(counts_of(parse_hand("119m19p19s1234567z"))))
    check("国士缺一张不对", not agari.is_winning(counts_of(parse_hand("19m19p19s1234567z"))))

    t = counts_of(parse_hand("123m456m789m123p1s"))
    check("听牌", agari.is_tenpai(t))
    check("听牌张算得对", agari.winning_tiles(t) == ["1s"], str(agari.winning_tiles(t)))
    t2 = counts_of(parse_hand("234m567m234p5678s"))
    check("两面听两张", set(agari.winning_tiles(t2)) == {"5s", "8s"}, str(agari.winning_tiles(t2)))
    mel = [{"kind": "pon", "tiles": ["5m", "5m", "5m"]}]
    t3 = counts_of(parse_hand("123m789m123p1s"))
    check("有副露时按「4 − 副露数」个面子算",
          agari.is_tenpai(t3, mel) and agari.winning_tiles(t3, mel) == ["1s"],
          str(agari.winning_tiles(t3, mel)))

    # ── 2. 吃 / 碰 / 杠 / 振听 / 食い替え ───────────────────────────────────
    print("\n[2] 吃 / 碰 / 杠 / 振听 / 食い替え")
    check("吃：3m 能吃 2m4m", calls.chi_options(parse_hand("234m55s78p"), "3m") == [["2m", "4m"]])
    check("吃：字牌不能吃", calls.chi_options(parse_hand("234m55s78p"), "1z") == [])
    opts = calls.chi_options(parse_hand("4s0s5s"), "6s")
    check("赤 5 和普通 5 分成两组（4s 能和 0s 或 5s 各成一组）", len(opts) == 2, str(opts))
    check("碰：优先两张一样的",
          calls.pon_options(parse_hand("5m5m1p"), "5m")[0] == ["5m", "5m"],
          str(calls.pon_options(parse_hand("5m5m1p"), "5m")))
    check("碰：赤 5 + 普通 5 也能碰", calls.can_pon(parse_hand("0s5s"), "5s"),
          str(calls.pon_options(parse_hand("0s5s"), "5s")))
    check("明杠：手里 3 张", calls.minkan_options(parse_hand("7p7p7p"), "7p") != [])
    check("暗杠：手里 4 张", calls.ankan_options(parse_hand("4s4s4s4s")) == ["4s"])
    check("加杠：碰过又摸到第 4 张",
          calls.kakan_options(parse_hand("9m1p"), [{"kind": "pon", "tiles": ["9m"] * 3}]) == ["9m"])
    check("食い替え：不能打和吃用的牌凑成顺子的那张",
          not calls.can_discard_after_call("5p", "chi", "5p", ["3p", "4p"]))
    check("食い替え：无关的牌可以打", calls.can_discard_after_call("9s", "chi", "5p", ["3p", "4p"]))
    check("振听：自己牌河里有听牌张",
          calls.is_permanent_furiten(counts_of(parse_hand("123m456m789m123p1s")), [], ["1s"]))
    check("不振听：牌河里没有听牌张",
          not calls.is_permanent_furiten(counts_of(parse_hand("123m456m789m123p1s")), [], ["2m"]))
    check("九种九牌", calls.can_kyuushu_kyuuhai(counts_of(parse_hand("19m19p19s1234567z")), []))

    # ── 3. 役种 ────────────────────────────────────────────────────────────
    print("\n[3] 役种")
    r = judge("123m456m789m234p55s", "2p")
    check("平和（门清 + 全顺子 + 两面 + 非役牌雀头）",
          "平和" in names(r), f'{names(r)} {r["han"]}翻 {r["fu"]}符')
    r = judge("123m456m789m234p55s", "2p",
              melds=[{"kind": "chi", "tiles": ["1m", "2m", "3m"]}])
    r2 = judge("456m789m234p55s", "2p", melds=[{"kind": "chi", "tiles": ["1m", "2m", "3m"]}])
    check("副露之后没有平和", "平和" not in names(r2), str(names(r2)))
    r = judge("123m456m789m555z22s", "bai")
    check("役牌 白", any(n.startswith("役牌") for n in names(r)), str(names(r)))
    r = judge("123m456m789m111z22s", "dong")
    check("场风/自风（东）算役牌", any("东" in n for n in names(r)), str(names(r)))
    r = judge("234m567m234p567s22s", "2s")
    check("断幺九", "断幺九" in names(r), str(names(r)))
    r = judge("11223344556677m", "7m")
    check("七对子（25 符）", "七对子" in names(r) and r["fu"] == 25,
          f'{names(r)} {r["han"]}翻 {r["fu"]}符')
    r = judge("112233m456p789s11z", "dong")
    check("一杯口", "一杯口" in names(r), str(names(r)))
    r = judge("123m123p123s456m77z", "zhong")
    check("三色同顺", "三色同顺" in names(r), str(names(r)))
    r = judge("123m456m789m111p11z", "1p")
    check("一气通贯", "一气通贯" in names(r), str(names(r)))
    r = judge("111m222m333p444s55z", "4s", tsumo=True)
    check("四暗刻 = 役满", r["yakuman"] >= 1, str(names(r)))
    r = judge("111m999m111p999s11s", "1s")
    check("清老头 = 役满", any(n.startswith("清老头") for n in names(r)), str(names(r)))
    r = judge("119m19p19s1234567z", "1m")
    check("国士无双 = 役满", r["yakuman"] >= 1 and any("国士" in n for n in names(r)),
          str(names(r)))
    r = judge("555z666z777z111m11p", "1p")
    check("大三元 = 役满", any("大三元" in n for n in names(r)), str(names(r)))
    r = judge("234m567m234p567s22s", "2s", dora_indicators=["1s"])
    check("宝牌加番（指示牌 1s → 宝牌 2s，手里两张）",
          "宝牌" in names(r) and r["han"] == 3, f'{names(r)} {r["han"]}翻')
    no_yaku = judge("456m678p234s99p", "9p", melds=[{"kind": "pon", "tiles": ["1m"] * 3}])
    check("没有役就不能和", no_yaku["yaku"] == [], str(names(no_yaku)))
    r = judge("234m567m234p567s0s5s", "5s", tsumo=True)
    check("赤宝牌加番（手牌里有 0s）", "宝牌" in names(r), f'{names(r)} {r["han"]}翻')
    r = judge("123m456m789m234p55s", "2p", riichi=True, ippatsu=True, tsumo=False)
    check("立直 + 一发", "立直" in names(r) and "一发" in names(r), str(names(r)))
    r = judge("123m456m789m234p55s", "2p", tsumo=True, first_turn=True, tenhou="tenhou")
    check("天和 = 役满", r["yakuman"] >= 1, str(names(r)))

    # ── 4. 符数 / 点数（对标准点数表） ──────────────────────────────────────
    print("\n[4] 符数 / 点数")
    cases = [
        ("子 30符1番 荣和", 1, 30, dict(is_dealer=False, tsumo=False), 1000),
        ("子 40符1番 荣和", 1, 40, dict(is_dealer=False, tsumo=False), 1300),
        ("子 25符2番 荣和（七对子）", 2, 25, dict(is_dealer=False, tsumo=False), 1600),
        ("子 30符4番 荣和", 4, 30, dict(is_dealer=False, tsumo=False), 7700),
        ("子 40符4番 = 满贯", 4, 40, dict(is_dealer=False, tsumo=False), 8000),
        ("亲 30符4番 荣和", 4, 30, dict(is_dealer=True, tsumo=False), 11600),
        ("子 20符2番 自摸（400/700）", 2, 20, dict(is_dealer=False, tsumo=True), 1500),
        ("子 20符3番 自摸（700/1300）", 3, 20, dict(is_dealer=False, tsumo=True), 2700),
        ("亲 20符2番 自摸（700 全付）", 2, 20, dict(is_dealer=True, tsumo=True), 2100),
        ("子 3番70符 = 满贯", 3, 70, dict(is_dealer=False, tsumo=False), 8000),
        ("子 5番满贯", 5, 30, dict(is_dealer=False, tsumo=False), 8000),
        ("子 6番跳满", 6, 30, dict(is_dealer=False, tsumo=False), 12000),
        ("子 8番倍满", 8, 30, dict(is_dealer=False, tsumo=False), 16000),
        ("子 11番三倍满", 11, 30, dict(is_dealer=False, tsumo=False), 24000),
        ("子 13番累计役满", 13, 30, dict(is_dealer=False, tsumo=False), 32000),
    ]
    for label, han, fu, kw, want in cases:
        got = payments(han, fu, **kw)["total"]
        check(label, got == want, f"算出 {got}，应为 {want}")

    check("役满 子家 = 32000",
          payments(0, 0, is_dealer=False, tsumo=False, yakuman=1)["total"] == 32000)
    check("役满 亲家 = 48000",
          payments(0, 0, is_dealer=True, tsumo=False, yakuman=1)["total"] == 48000)
    check("亲 20符2番 自摸每人 700", payments(2, 20, is_dealer=True, tsumo=True)["each"] == 700)

    sets = [("run", 0), ("triplet", 4), ("kan", 27), ("run", 9)]
    fu = calc_fu(sets=sets, pair_index=31, concealed_flags=[True] * 4, closed_hand=True,
                 tsumo=False, wait="ryanmen", is_pinfu=False, is_chiitoitsu=False,
                 round_wind="dong", seat_wind="dong")
    check("符数：底20+门清10+雀头2+暗刻4+字牌暗杠32 = 70符", fu == 70, f"{fu}符")
    fu2 = calc_fu(sets=[("run", 0), ("run", 3)], pair_index=4, concealed_flags=[True, True],
                  closed_hand=True, tsumo=False, wait="ryanmen", is_pinfu=True,
                  is_chiitoitsu=False, round_wind="dong", seat_wind="dong")
    check("符数：平和荣和 = 30符", fu2 == 30, f"{fu2}符")
    fu3 = calc_fu(sets=[("run", 0), ("run", 3)], pair_index=4, concealed_flags=[True, True],
                  closed_hand=True, tsumo=True, wait="ryanmen", is_pinfu=True,
                  is_chiitoitsu=False, round_wind="dong", seat_wind="dong")
    check("符数：平和自摸 = 20符", fu3 == 20, f"{fu3}符")
    fu4 = calc_fu(sets=[("run", 0), ("triplet", 9)], pair_index=4, concealed_flags=[True, False],
                  closed_hand=False, tsumo=False, wait="kanchan", is_pinfu=False,
                  is_chiitoitsu=False, round_wind="dong", seat_wind="dong")
    check("符数：副露 + 明刻4 + 嵌张2 = 30符（食い平和）", fu4 == 30, f"{fu4}符")

    print("\n" + "=" * 70)
    print(f" 结果：{OK} 项通过，{FAIL} 项失败")
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
