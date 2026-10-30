# -*- coding: utf-8 -*-
"""副露之后「手牌张数 + 还能不能和」的回归测试。

不变量（杠 4 张按 4 张实张算）：
    自己回合、刚摸完 / 刚鸣完（该打牌）：暗牌 + 副露实张 = 14 + 杠数
    非自己回合、等待中（随时可荣和）    ：暗牌 + 副露实张 = 13 + 杠数
  并且：等待中的那张被打出来时，窗口里必须有 ron（除非自己振听）。

跑法： python test_meld_flow.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError  # noqa: E402
import test_game as tg  # noqa: E402
from rules import wallmodel  # noqa: E402
from tiles import parse_hand  # noqa: E402

PASS = FAIL = 0
_OPEN_DBS: list = []
BAD: list = []


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def fresh(tag):
    db = tg.fresh_db(tag)
    _OPEN_DBS.append(db)
    rid, _m, _u = tg.new_round(db, seed=13)
    return db, rid


def set_next_rinshan(db, rid, tile: str) -> None:
    """把「下一张要摸的岭上牌」换成指定牌。

    骰子是每次随机投的 → 岭上会摸到什么是随机的 → 断言会偶发失败；
    固定成一张「这手牌里没有、也不是待牌」的牌，测试就完全可复现。
    """
    g = Game(db, rid)
    nos = wallmodel.rinshan_tile_nos(g.wall_first_stack())
    if g.rinshan_used >= len(nos):
        return
    with db.tx():
        db.conn.execute("UPDATE round_wall SET tile=? WHERE round_id=? AND seq=?",
                        (tile, rid, wallmodel.seq_of_tile(nos[g.rinshan_used])))


def opp_discard(db, rid, tile: str, seat: int = 3):
    """让某家真打一张牌出来（牌河里会有真实记录 → 被鸣的那张才查得到物理编号）

    默认用 3 号位（上家）：吃只能吃上家，0 号位要能吃就得是 3 号位打的。
    """
    g = Game(db, rid)
    tg.set_hand(db, rid, seat, parse_hand("111m345s678p99s") + [tile], drawn=tile)
    g.turn = seat
    g.phase = "discard"
    g.save_flags()
    g.act(seat, "discard", tile=tile)
    return g


def window(g, tile, frm=3):
    """开一个鸣牌窗口（frm 打出 tile），返回给我的可选项"""
    g._open_claim_window(1, tile, frm)
    return [a["action"] for a in (g.pending or {}).get("options", {}).get(0, [])]


def settle(g):
    """把窗口里还没答的人过掉，让窗口结算"""
    p = g.pending
    if not p:
        return
    for s in list(p["options"]):
        if s not in p["answers"]:
            g.pass_claim(s)


def at_discard(db, rid, seat=0):
    g = Game(db, rid)
    g.turn = seat
    g.phase = "discard"
    g.save_flags()
    return g


def check_seqs(g, name, seat=0):
    """副露里每张牌都要有自己的物理编号，而且编号指回牌山时牌面要对得上。

    （编号 = wall_seq，round_wall.seq。加杠之后这一组是 4 张，就该有 4 个编号。）
    """
    for m in g.melds(seat):
        tiles = list(m["tiles"])
        seqs = list(m.get("seqs") or [])
        real = [q for q in seqs if q is not None]
        ok = (len(seqs) == len(tiles) and None not in seqs and len(set(real)) == len(real))
        if not ok:
            BAD.append("%s 的编号" % name)
        check("%s：%s 的 %d 张各有各的物理编号" % (name, m["kind"], len(tiles)), ok, True)
        print("         %s → 牌面 %s / 编号 %s" % (m["kind"], tiles, seqs))


def shapes(g, name, seat=0):
    n = len(g.hand(seat)) + sum(len(m["tiles"]) for m in g.melds(seat))
    k = len(g.db._rows("SELECT 1 FROM round_melds WHERE round_id=? AND seat=? "
                       "AND kind IN ('minkan','ankan','kakan')", (g.round_id, seat)))
    ok = n in (14 + k, 13 + k)
    if not ok:
        BAD.append(name)
    print("  %-34s 暗牌 %2d + 副露 %-12s = %2d 张（杠 %d，应 %d/%d）%s"
          % (name, len(g.hand(seat)),
             ",".join(m["kind"] + str(len(m["tiles"])) for m in g.melds(seat)) or "-",
             n, k, 14 + k, 13 + k, "" if ok else "  ★★ 张数不对"))
    return ok


def discard_any(g, prefer: str = "", keep=()) -> str:
    """该我打牌：优先打 prefer（一般是刚摸的岭上牌），绝不打 keep 里的牌（食い替え 会拦）"""
    cand = [prefer] if prefer and prefer not in keep else []
    cand += [t for t in (g.drawn_tile(0) or "", *g.hand(0)) if t and t not in keep]
    for t in cand:
        try:
            g.act(0, "discard", tile=t)
            return t
        except RuleError:
            continue
    raise AssertionError("打不出任何牌")


def can_ron(g, tile, name):
    g2 = Game(g.db, g.round_id)
    g2.turn = 1
    g2.phase = "discard"
    opts = window(g2, tile)
    res = g2._judge_win(0, tile, tsumo=False)
    yaku = None if res is None else [y["name"] for y in res["yaku"]]
    furiten = g2.furiten(0)
    ok = "ron" in opts
    if not ok:
        BAD.append(name)
    print("  %-32s 窗口=%-16s 役=%-20s 振听=%s %s"
          % (name, opts, yaku, furiten.get("permanent"), "OK" if ok else "★★ 没有荣和"))
    return ok


def main() -> int:
    print("=" * 78)
    print(" 天才麻将少女 · 副露之后的手牌张数 / 还能不能和")
    print("=" * 78)

    # ── ① 吃：对手打 6m，我拿 4m5m 吃；吃完打掉 9s，听 3m ────────────────
    print("\n① 吃（对手打 6m 我吃；打 9s 之后听 3m）")
    db, rid = fresh("meld_chi")
    tg.set_hand(db, rid, 0, parse_hand("12m45m789m234p55s") + ["9s"])
    g = opp_discard(db, rid, "6m")            # 别家真打 6m 出来
    print("  窗口给我:", [o["action"] for o in (g.pending or {}).get("options", {}).get(0, [])])
    g.act(0, "chi", tiles=["4m", "5m"])
    settle(g)
    shapes(g, "吃之后（该打牌）")
    check("吃之后手牌", sorted(g.hand(0)), sorted(parse_hand("12m789m234p55s") + ["9s"]))
    g.act(0, "discard", tile="9s")
    shapes(g, "吃后打完（等待中）")
    check("吃后打完手牌", sorted(g.hand(0)), sorted(parse_hand("12m789m234p55s")))
    can_ron(g, "3m", "吃后别家打 3m")

    # ── ② 碰：对手打白我碰；打掉 9s，听 5s ──────────────────────────────
    print("\n② 碰（对手打白我碰；打 9s 之后听 5s）")
    db, rid = fresh("meld_pon")
    tg.set_hand(db, rid, 0, parse_hand("123m456m789m5s") + ["9s", "bai", "bai"])
    g = opp_discard(db, rid, "bai")          # 别家真打白出来
    print("  窗口给我:", [o["action"] for o in (g.pending or {}).get("options", {}).get(0, [])])
    g.act(0, "pon", tiles=["bai", "bai"])
    settle(g)
    shapes(g, "碰之后（该打牌）")
    g.act(0, "discard", tile="9s")
    shapes(g, "碰后打完（等待中）")
    check("碰后打完手牌", sorted(g.hand(0)), sorted(parse_hand("123m456m789m5s")))
    check_seqs(g, "碰")
    can_ron(g, "5s", "碰后别家打 5s")

    # ── ③ 暗杠：手里 4 张 2p ───────────────────────────────────────────
    print("\n③ 暗杠（手里 4 张 2p）")
    db, rid = fresh("meld_ankan")
    tg.set_hand(db, rid, 0, parse_hand("2222p345m678m234s") + ["5s"], drawn="5s")
    set_next_rinshan(db, rid, "1s")
    g = at_discard(db, rid)
    shapes(g, "暗杠之前（14 张）")
    g.act(0, "ankan", tile="2p")
    shapes(g, "暗杠之后（该打牌，已补岭上）")
    check("暗杠后确实摸到了一张岭上牌", g.drawn_tile(0) is not None, True)
    check_seqs(g, "暗杠")
    discard_any(g, g.drawn_tile(0) or "", keep=("5s",))
    shapes(g, "暗杠后打完（等待中）")
    can_ron(g, "5s", "暗杠后别家打 5s")

    # ── ④ 明杠：对手打第 4 张 2p ───────────────────────────────────────
    print("\n④ 明杠（手里 3 张 2p，对手打第 4 张）")
    db, rid = fresh("meld_minkan")
    tg.set_hand(db, rid, 0, parse_hand("222p345m678m234s") + ["5s"])
    set_next_rinshan(db, rid, "1s")
    # 让 1 号位真的打一张 2p 出来（牌河里要有真实记录，才验得了「被杠走的牌」）
    tg.set_hand(db, rid, 1, parse_hand("111m345s678p99s") + ["2p"], drawn="2p")
    g = Game(db, rid)
    g.turn = 1
    g.phase = "discard"
    g.save_flags()
    g.act(1, "discard", tile="2p")
    print("  1 号位打出 2p，窗口给我:",
          [o["action"] for o in (g.pending or {}).get("options", {}).get(0, [])])
    g.act(0, "minkan")
    settle(g)
    shapes(g, "明杠之后（该打牌，应补岭上）")
    check("明杠后确实摸到了一张岭上牌", g.drawn_tile(0) is not None, True)
    check("明杠后该我打牌", g.phase, "discard")
    # 被杠走的那张牌：牌河里要标成「已被拿走」（客户端据此把它从牌河隐藏掉，
    # 不然「牌河 1 张 + 副露 4 张」看起来像出现了 5 张同种牌）
    row = g.db._row("SELECT called, called_by, called_kind, tile FROM round_discards "
                    "WHERE round_id=? ORDER BY seq DESC LIMIT 1", (rid,))
    check("被杠的那张在牌河里标成「已被拿走」", int(row["called"]), 1)
    check("记录是谁杠走的", int(row["called_by"]), 0)
    check("记录是明杠", row["called_kind"], "minkan")
    check_seqs(g, "明杠")
    discard_any(g, g.drawn_tile(0) or "", keep=("5s",))
    shapes(g, "明杠后打完（等待中）")
    can_ron(g, "5s", "明杠后别家打 5s")

    # ── ⑤ 加杠：碰白之后又摸到第 4 张白 ────────────────────────────────
    print("\n⑤ 加杠（碰白之后又摸到第 4 张白）")
    db, rid = fresh("meld_kakan")
    tg.set_hand(db, rid, 0, parse_hand("123m456m789m5s") + ["9s", "bai", "bai"])
    g = Game(db, rid)
    window(g, "bai")
    g.act(0, "pon", tiles=["bai", "bai"])
    settle(g)
    g.act(0, "discard", tile="9s")
    kept = g.hand(0)
    set_next_rinshan(db, rid, "1s")
    tg.set_hand(db, rid, 0, kept + ["bai"], drawn="bai")
    g2 = at_discard(db, rid)
    print("  可选项:", [a["action"] for a in g2.legal_actions(0)])
    shapes(g2, "加杠之前（14 张）")
    g2.act(0, "kakan", tile="bai")
    shapes(g2, "加杠之后（该打牌，已补岭上）")
    check("加杠后确实摸到了一张岭上牌", g2.drawn_tile(0) is not None, True)
    discard_any(g2, g2.drawn_tile(0) or "", keep=("5s",))
    shapes(g2, "加杠后打完（等待中）")
    can_ron(g2, "5s", "加杠后别家打 5s")

    # ── ⑥ 杠之后翻宝牌：每开一次杠都要多翻一张 ──────────────────────────
    print("\n⑥ 开杠要翻新宝牌指示牌")
    db, rid = fresh("meld_dora")
    tg.set_hand(db, rid, 0, parse_hand("2222p345m678m234s") + ["5s"], drawn="5s")
    set_next_rinshan(db, rid, "1s")
    g = at_discard(db, rid)
    before = len(g.revealed_dora("dora"))
    g.act(0, "ankan", tile="2p")
    after = len(Game(db, rid).revealed_dora("dora"))
    check("暗杠后表宝牌指示牌多了一张", after, before + 1)

    db, rid = fresh("meld_dora2")
    tg.set_hand(db, rid, 0, parse_hand("222p345m678m234s") + ["5s"])
    set_next_rinshan(db, rid, "1s")
    g = Game(db, rid)
    window(g, "2p")
    before = len(g.revealed_dora("dora"))
    g.act(0, "minkan")
    settle(g)
    after = len(Game(db, rid).revealed_dora("dora"))
    check("明杠后表宝牌指示牌多了一张", after, before + 1)

    # ── ⑦ 岭上开花：自摸算 1 番，荣和不成立 ────────────────────────────
    print("\n⑦ 岭上开花只算自摸")
    from rules import tenpai  # noqa: E402
    hand10 = parse_hand("345m678m234s5s")          # 暗牌 10 张，听 5s
    melds = [{"kind": "ankan", "tiles": ["2p"] * 4, "called_tile": "2p",
              "from_seat": 0, "rot_index": -1}]
    tsu = tenpai.win_summary(hand10, melds, "5s", True, {"rinshan": True})
    ron = tenpai.win_summary(hand10, melds, "5s", False, {"rinshan": True})
    check("自摸（刚摸到岭上牌）算岭上开花",
          "岭上开花" in (tsu or {}).get("yaku", []), True)
    check("荣和不算岭上开花", "岭上开花" in (ron or {}).get("yaku", []), False)

    # ── ⑧ 暗杠字牌：手里还有别的字牌时，不能把别的字牌杠进去 ────────────
    print("\n⑧ 暗杠西风（手里还有东/南/白）")
    db, rid = fresh("meld_ankan_honor")
    tg.set_hand(db, rid, 0, ["dong", "xi", "bai", "xi", "nan", "xi", "xi",
                             "1m", "2m", "3m", "4m", "5m", "6m", "9p"], drawn="9p")
    set_next_rinshan(db, rid, "1s")
    g = at_discard(db, rid)
    g.act(0, "ankan", tile="xi")
    m = g.melds(0)[0]["tiles"]
    check("暗杠的 4 张全是西风", m, ["xi"] * 4)
    check("杠完手里不该再有西风", "xi" in g.hand(0), False)
    rest = [t for t in g.hand(0) if t != (g.drawn_tile(0) or "")]   # 不含刚补的岭上牌
    check("手里别的字牌一张都没少", sorted(t for t in rest
          if t in ("dong", "nan", "bai")), ["bai", "dong", "nan"])
    check_seqs(g, "暗杠西风")
    shapes(g, "暗杠西风之后（该打牌）")

    # ── ⑨ 加杠：碰了 5m 之后摸到赤 5，也能杠进去 ────────────────────────
    print("\n⑨ 加杠赤 5（碰了 5m，摸到 0m）")
    db, rid = fresh("meld_kakan_red")
    # 手牌 123m 678m 99m 123p + 5m5m（不能有别的 5m，不然杠到哪张说不清）
    tg.set_hand(db, rid, 0, parse_hand("123m67899m123p") + ["5m", "5m"])
    g = opp_discard(db, rid, "5m")           # 别家真打 5m 出来
    g.act(0, "pon", tiles=["5m", "5m"])
    settle(g)
    g.act(0, "discard", tile="1p")
    set_next_rinshan(db, rid, "1s")
    tg.set_hand(db, rid, 0, list(g.hand(0)) + ["0m"], drawn="0m")
    g2 = at_discard(db, rid)
    check("摸到赤 5 也能加杠", "kakan" in [a["action"] for a in g2.legal_actions(0)], True)
    g2.act(0, "kakan", tile="5m")
    tiles = [m for m in g2.melds(0) if m["kind"] == "kakan"][0]["tiles"]
    check("加杠把那张赤 5 接了进去", "0m" in tiles, True)
    check("杠上 4 张", len(tiles), 4)
    rest2 = [t for t in g2.hand(0) if t != (g2.drawn_tile(0) or "")]
    check("手里不该再留着赤 5", "0m" in rest2, False)
    check_seqs(g2, "加杠赤 5")

    # ── ⑩ 连杠：加杠 → 补岭上 → 岭上那张正好能再杠一次 → 允许继续加杠 ────
    print("\n⑩ 连杠（碰了 5m 和 9s，先杠 5m，岭上补到第 4 张 9s）")
    db, rid = fresh("meld_kakan_chain")
    # 13 张：123m 456m 789m + 5m5m + 9s9s
    tg.set_hand(db, rid, 0, parse_hand("123m456m789m") + ["5m", "5m", "9s", "9s"])
    g = opp_discard(db, rid, "5m")           # 别家真打 5m
    g.act(0, "pon", tiles=["5m", "5m"])
    settle(g)
    g.act(0, "discard", tile="7m")
    opp_discard(db, rid, "9s")               # 别家真打 9s
    g = Game(db, rid)
    g.act(0, "pon", tiles=["9s", "9s"])
    settle(g)
    g.act(0, "discard", tile="8m")
    check("两副碰都在手上", [m["kind"] for m in g.melds(0)], ["pon", "pon"])
    # 摸到赤 5（和碰过的 5m 同种）→ 能加杠；下一张岭上牌固定成 9s（第二副碰的第 4 张）
    set_next_rinshan(db, rid, "9s")
    # 别家手牌固定成「不听 9s」的牌：不然第二次加杠 9s 会被抢杠（本来也是对的规则），
    # 把连杠这段冲掉。
    for _s2 in (1, 2, 3):
        tg.set_hand(db, rid, _s2, parse_hand("123m456m789m123p1s"))
    tg.set_hand(db, rid, 0, list(g.hand(0)) + ["0m"], drawn="0m")
    g2 = at_discard(db, rid)
    acts = [a["action"] for a in g2.legal_actions(0)]
    check("摸到赤 5 能加杠", "kakan" in acts, True)
    dora0 = len(Game(db, rid).revealed_dora("dora"))
    hand0 = len(g2.hand(0))
    g2.act(0, "kakan", tile="5m")
    check("第一次加杠后该我打牌", g2.phase, "discard")
    check("第一次加杠后手牌多一张（补了岭上）", len(g2.hand(0)), hand0)
    check("第一次加杠后翻了一张新宝牌",
          len(Game(db, rid).revealed_dora("dora")), dora0 + 1)
    acts2 = [a for a in g2.legal_actions(0)]
    print("        加杠之后的可选项:", [a["action"] for a in acts2])
    kakan2 = [a for a in acts2 if a["action"] == "kakan"]
    check("岭上补到第 4 张 9s → 还能接着加杠", bool(kakan2), True)
    if kakan2:
        check("第二次加杠说的是 9s", kakan2[0].get("tile", ""), "9s")
        g2.act(0, "kakan", tile="9s")
        kinds = [m["kind"] for m in g2.melds(0)]
        check("两副副露都是杠", kinds, ["kakan", "kakan"])
        check("每副都是 4 张", [len(m["tiles"]) for m in g2.melds(0)], [4, 4])
        check("第二次加杠又翻了一张新宝牌",
              len(Game(db, rid).revealed_dora("dora")), dora0 + 2)
        check("连杠之后还是要我打牌", g2.phase, "discard")
        shapes(g2, "连杠之后（该打牌）")
        check_seqs(g2, "连杠")

    print()
    print("张数 / 荣和 有问题的地方：", BAD or "无")
    print(f"{PASS} 项通过 / {FAIL} 项失败")

    for d in _OPEN_DBS:
        try:
            d.close()
        except Exception:
            pass
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    for f in os.listdir(data_dir):
        if f.startswith("_test_meld_"):
            try:
                os.remove(os.path.join(data_dir, f))
            except OSError:
                pass
    return 1 if (FAIL or BAD) else 0


if __name__ == "__main__":
    raise SystemExit(main())
