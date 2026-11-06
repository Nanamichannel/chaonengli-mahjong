# -*- coding: utf-8 -*-
"""Card32 S1【新手运】+ S2【无知】自测。

跑法：cd N:\\apps\\tianma\\server; python test_card32.py
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game, RuleError  # noqa: E402
import skills  # noqa: E402
import test_card30 as t30  # noqa: E402
import test_game as tg  # noqa: E402
from tiles import parse_hand  # noqa: E402

PASS = FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def judge(tag, hand14, win_tile, *, tsumo=False, card=32, pon=None):
    """判番 + 跑结算链，返回 res（带无知的效果）。

    hand14 是「和了之后的 14 张」；这里扣掉一张和牌张当手牌（荣和是 13 + 1）。
    pon=牌种 → 先给 0 号位摆一组明刻（这样就不是四暗刻，只留对对和）。
    """
    db, rid = t30.setup(tag, card=card)
    tiles = parse_hand(hand14)
    if pon is not None:
        for _ in range(3):                 # 明刻那三张从手牌里拿掉
            tiles.remove(pon)
    wt = win_tile
    if wt in tiles:
        tiles.remove(wt)
    if pon is not None:
        with db.tx():
            db.conn.execute(
                "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
                "tiles_json,rot_index,seqs_json) VALUES(?,0,0,'pon',?,3,?,0,'[]')",
                (rid, pon, '["%s","%s","%s"]' % (pon, pon, pon)))
    tg.set_hand(db, rid, 0, tiles)
    with db.tx():                        # 防天和：先塞一张已经打过的牌
        db.conn.execute(
            "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
            " is_tsumogiri, is_riichi_tile, face_down, called)"
            " VALUES(?,900,1,901,'1z',1,0,0,0)", (rid,))
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
    g = Game(db, rid)
    g.round_phase = "play"
    g.phase, g.turn = "discard", 0
    base = g._judge_win(0, win_tile, tsumo=tsumo)
    if base is None:
        return None, g
    return g.settle_preview(0, None, "tsumo" if tsumo else "ron", base, dry_run=True), g


def main() -> int:
    print("=" * 78)
    print(" Card32 S1【新手运】+ S2【无知】")
    print("=" * 78)

    print("\n① 注册")
    check("S1 名字", skills.info(32, 1).get("name"), "新手运")
    check("S2 名字", skills.info(32, 2).get("name"), "无知")
    check("新手运在配牌阶段", skills.timing(32, 1), "deal")
    check("无知在结算阶段", skills.timing(32, 2), "settle")

    # ── ② 新手运：下家 → 对家 → 上家 ─────────────────────────────────
    print("\n② 新手运：顺序 / 只能交幺九 / 换一张")
    db, rid = t30.setup("c32a", card=32)
    g = Game(db, rid)
    r = g._c32s1_arm(0)
    check("arm 回 targets（下家→对家→上家）", r.get("targets"), [1, 2, 3])
    f = g.deal_flow or {}
    check("第一个问下家", int(f.get("target", -1)), 1)
    check("一次只交 1 张", (int(f.get("min", 0)), int(f.get("max", 0))), (1, 1))
    v1 = g.deal_flow_view(1) or {}
    check("1 号位看到「交牌」", v1.get("role"), "give")
    check("我这边是等对方交牌", ((g.deal_flow_view(0) or {}).get("sub")), "give")

    err = ""
    try:
        g._c32s1_arm(0)                  # 流程没结束，不能再来一次
    except RuleError as e:
        err = str(e)
    check("流程进行中不能重复 arm", "正在进行" in err)

    err = ""
    try:
        g.c32s1_give(1, "6m")            # 6m 不是幺九
    except RuleError as e:
        err = str(e)
    check("交非幺九被拒", "幺九" in err)
    err = ""
    try:
        g.c32s1_give(2, "2z")            # 不该 2 号位交
    except RuleError as e:
        err = str(e)
    check("没轮到的那家不能交", err != "")

    r2 = g.c32s1_give(1, "dong")         # 1 号位手里的 1z
    check("交牌成功", r2.get("tile"), "dong")
    check("轮到我换牌", str((g.deal_flow or {}).get("sub")), "swap")
    my_tile = g.hand(0)[0]
    r3 = g.c32s1_swap(0, my_tile)
    check("换到了 东", r3.get("got"), "dong")
    g2 = Game(db, rid)
    check("我手里多了 东", "dong" in g2.hand(0), True)
    check("1 号位拿到我那张", my_tile in g2.hand(1), True)
    check("接着问对家", int((g2.deal_flow or {}).get("target", -1)), 2)
    check("stage 前进到 1", int((g2.deal_flow or {}).get("stage", -1)), 1)

    print("\n③ 三家走完 → 收尾；没有幺九的那家跳过")
    g2.c32s1_give(2, "nan")
    g2.c32s1_swap(0, g2.hand(0)[0])
    g3 = Game(db, rid)
    g3.c32s1_give(3, "xi")
    g3.c32s1_swap(0, g3.hand(0)[0])
    g4 = Game(db, rid)
    check("流程结束", g4.deal_flow, None)
    check("我不再等配牌", 0 in g4.deal_wait, False)

    print("\n④ AI 代交：没人的座位交第一张幺九")
    db2, rid2 = t30.setup("c32b", card=32)
    h = Game(db2, rid2)
    h._c32s1_arm(0)
    ra = h.c32s1_auto(1)
    check("代交了一张", ra.get("tile"), "dong")

    print("\n④b API 入口：客户端复用 c30 面板，发的是 tiles 数组")
    import api_cli
    db3, rid3 = t30.setup("c32h", card=32)
    Game(db3, rid3)._c32s1_arm(0)
    rr = api_cli.handle({"op": "c32s1_give", "seat": 1, "tiles": ["dong"],
                         "round_id": rid3}, db3.path)
    check("API 交牌 ok", bool(rr.get("ok")), True)
    check("API 交牌拿到东", (rr.get("c32") or {}).get("tile"), "dong")
    st0 = api_cli.handle({"op": "state", "seat": 0, "round_id": rid3}, db3.path)
    check("API 之后轮到我换牌",
          str(((st0.get("state") or {}).get("deal_flow") or {}).get("sub")), "swap")
    rr2 = api_cli.handle({"op": "c32s1_swap", "seat": 0,
                          "hand": (st0.get("state") or {}).get("hand", [""])[0],
                          "tile": "dong", "round_id": rid3}, db3.path)
    check("API 换牌 ok", bool(rr2.get("ok")), True)
    check("API 换牌拿到东", (rr2.get("c32") or {}).get("got"), "dong")

    # ── ⑤ 无知：对对和 → 四暗刻 ────────────────────────────────────
    print("\n⑤ 无知：对对和按四暗刻算")
    res, _g = judge("c32c", "111m222m333p444s55z", "bai", pon="1m")
    names = [y["name"] for y in (res or {}).get("yaku", [])]
    check("判出来了", bool(res), True)
    check("有对对和", any("对对和" in n for n in names), True)
    check("升级成四暗刻", ("无知" in names), True)
    check("是役满", int((res or {}).get("yakuman", 0)) >= 1, True)

    print("\n⑥ 无知：索子清一色按绿一色算")
    res2, _g = judge("c32d", "234s234s567s888s66s", "6s")
    names2 = [y["name"] for y in (res2 or {}).get("yaku", [])]
    check("有清一色", any("清一色" in n for n in names2), True)
    check("升级成绿一色", ("无知" in names2), True)
    check("是役满", int((res2 or {}).get("yakuman", 0)), 1)

    print("\n⑦ 无知：索子 + 只有发财的混一色 → 绿一色")
    res3, _g = judge("c32e", "234s234s567s888s66z", "fa")
    names3 = [y["name"] for y in (res3 or {}).get("yaku", [])]
    check("有混一色", any("混一色" in n for n in names3), True)
    check("升级成绿一色", ("无知" in names3), True)

    print("\n⑧ 无知：索子只有发的混一色 + 对对和 → 绿一色四暗刻（双倍役满）")
    # 碰了 2s（明刻）→ 只是对对和/三暗刻；字牌只有发 → 混一色。
    # 无知两条都命中：四暗刻（无知）+ 绿一色（无知）= 双倍役满（亲家荣和 96000）。
    res4, _g = judge("c32f", "222s333s555s888s66z", "fa", pon="2s")
    names4 = [y["name"] for y in (res4 or {}).get("yaku", [])]
    check("本来是对对和", any(n.startswith("对对和") for n in names4), True)
    check("本来是混一色", any(n.startswith("混一色") for n in names4), True)
    check("升级成无知（四暗刻）", ("无知" in names4), True)
    check("两条命中也只写一条无知", names4.count("无知"), 1)
    check("役满 2 倍", int((res4 or {}).get("yakuman", 0)), 2)
    check("点数 = 双倍役满", int(((res4 or {}).get("pays") or {}).get("total", 0)), 96000)

    print("\n⑧b 无知：本来就四暗刻 + 绿一色 → 不重复加（还是 2 倍）")
    res4b, _g = judge("c32f2", "222s333s444s888s66s", "6s")
    names4b = [y["name"] for y in (res4b or {}).get("yaku", [])]
    check("本来就有四暗刻", any(n.startswith("四暗刻") for n in names4b), True)
    check("本来就有绿一色", any(n.startswith("绿一色") for n in names4b), True)
    check("不再叠（役满 2 倍）", int((res4b or {}).get("yakuman", 0)), 2)
    check("没有无知字样", any("无知" in n for n in names4b), False)

    print("\n⑨ 没这张卡的人不吃这套")
    res5, _g = judge("c32g", "111m222m333p444s55z", "bai", card=6, pon="1m")
    names5 = [y["name"] for y in (res5 or {}).get("yaku", [])]
    check("没有无知升级", any("无知" in n for n in names5), False)
    check("还是普通对对和", int((res5 or {}).get("yakuman", 0)), 0)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
