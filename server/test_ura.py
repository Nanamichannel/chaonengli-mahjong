# -*- coding: utf-8 -*-
"""里宝牌判定（服务端规则）：
   ✗ 没立直和牌 → 里宝牌一张都不算
   ✓ 立直和牌   → 里宝牌计入番数（detail 里能看到「里宝牌 n」）
   另外：state_for 不会把里宝牌指示牌泄露给没立直的人
跑法： python test_ura.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game  # noqa: E402
import test_game as tg  # noqa: E402

PASS = FAIL = 0
_OPEN_DBS: list = []

# 13 张听牌手牌：123m 456m 789m + 22p 34p → 听 2p/5p（平和 + 一气通贯）
HAND13 = "123m456m789m2234p"
RON_TILE = "5p"
URA_INDICATOR = "1m"        # 指示牌 1m → 里宝牌是 2m（手里正好有一张 2m）


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def dora_entry(res: dict) -> dict:
    for y in (res or {}).get("yaku", []):
        if y.get("name") == "宝牌":
            return y
    return {}


def cleanup() -> None:
    """把测试用的临时库删掉，别留在 data 目录里（先关连接，不然 Windows 删不掉）"""
    for d in _OPEN_DBS:
        try:
            d.close()
        except Exception:
            pass
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    if os.path.isdir(data_dir):
        for f in os.listdir(data_dir):
            if f.startswith("_test_ura"):
                try:
                    os.remove(os.path.join(data_dir, f))
                except OSError:
                    pass


def setup(tag: str, riichi: bool, ura: bool):
    """摆一副「听 2p/5p、手上有一张 2m」的牌；宝牌指示牌全清掉，只按需要翻里宝牌。"""
    db = tg.fresh_db(tag)
    _OPEN_DBS.append(db)
    rid, _m, _ = tg.new_round(db, seed=13)
    tg.set_hand(db, rid, 0, tg.parse_hand(HAND13) + ["9s"], drawn="9s")
    g = Game(db, rid)
    g.turn = 0
    g.phase = "discard"
    g.save_flags()
    g.act(0, "riichi" if riichi else "discard", tile="9s")
    tg.clear_claims(g)
    with db.tx():                                   # 开局翻的那张表宝牌也不要，保持干净
        db.conn.execute("DELETE FROM round_dora WHERE round_id=?", (rid,))
    if ura:
        db.add_dora(rid, "ura", 0, URA_INDICATOR, "2m")
    g.dora_revealed = 1 if ura else 0
    g.save_flags()
    return db, rid, g


def judge(g: Game) -> dict:
    """上家（1 号位）打出 5p，我荣和。"""
    g._open_claim_window(1, RON_TILE, 3)
    return g._judge_win(0, RON_TILE, tsumo=False)


def show(res: dict) -> None:
    names = [y["name"] for y in res["yaku"]]
    det = dora_entry(res).get("detail", {})
    print("        役：%s  番：%s  符：%s  宝牌明细：%s"
          % (names, res.get("han"), res.get("fu"), det))


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · 立直和牌后的里宝牌")
    print("=" * 70)

    # ── 1. 立直和牌 + 里宝牌指示牌翻开 ────────────────────────────────
    db, rid, g = setup("ura_riichi", riichi=True, ura=True)
    check("立直已记录", g.is_riichi(0), True)
    check("里宝牌指示牌 = 1m", g.revealed_dora("ura"), [URA_INDICATOR])
    check("表宝牌指示牌一张都没有", g.revealed_dora("dora"), [])
    g._open_claim_window(1, RON_TILE, 3)
    acts = {o["action"] for o in (g.pending["options"].get(0) or [])}
    check("上家打 5p 能荣和", "ron" in acts, True)

    res = g._judge_win(0, RON_TILE, tsumo=False)
    check("和牌成立（有役）", res is not None, True)
    names = [y["name"] for y in (res or {}).get("yaku", [])]
    det = dora_entry(res or {}).get("detail", {})
    if res:
        show(res)
    check("役里有立直（首巡立直会记成双立直）", "立直" in names or "双立直" in names, True)
    check("里宝牌 = 1（手里那张 2m）", det.get("里宝牌", 0), 1)
    check("表宝牌 = 0（没翻表指示牌）", det.get("宝牌", 0), 0)
    check("赤宝牌 = 0", det.get("赤宝牌", 0), 0)
    han_ura = (res or {}).get("han", -1)

    # 走完整条路（act → 结算 → result），确认 result 里也带着里宝牌明细
    g.act(0, "ron")
    r = g.result or {}
    check("结算结果是荣和", r.get("result"), "ron")
    check("result 里带着里宝牌明细", dora_entry(r).get("detail", {}).get("里宝牌", 0), 1)

    # ── 2. 同样立直，但没翻里宝牌指示牌 ───────────────────────────────
    db2, rid2, g2 = setup("ura_none", riichi=True, ura=False)
    check("（对照）没有里宝牌指示牌", g2.revealed_dora("ura"), [])
    res2 = judge(g2)
    check("（对照）和牌成立", res2 is not None, True)
    if res2:
        show(res2)
    det2 = dora_entry(res2 or {}).get("detail", {})
    check("（对照）里宝牌 = 0", det2.get("里宝牌", 0), 0)
    check("（对照）没有宝牌这项（表/赤/里全是 0）", det2, {})
    check("有里宝牌指示牌时正好多 1 番", han_ura - (res2 or {}).get("han", 0), 1)

    # ── 3. 没立直：里宝牌指示牌翻着也不算 ─────────────────────────────
    db3, rid3, g3 = setup("ura_plain", riichi=False, ura=True)
    check("（对照）没有立直", g3.is_riichi(0), False)
    check("（对照）里宝牌指示牌同样翻开了", g3.revealed_dora("ura"), [URA_INDICATOR])
    res3 = judge(g3)
    check("（对照）和牌成立", res3 is not None, True)
    if res3:
        show(res3)
    names3 = [y["name"] for y in (res3 or {}).get("yaku", [])]
    det3 = dora_entry(res3 or {}).get("detail", {})
    check("（对照）没有立直这个役", "立直" not in names3 and "双立直" not in names3, True)
    check("（对照）里宝牌不算", det3.get("里宝牌", 0), 0)
    check("（对照）宝牌明细整体是空的", det3, {})

    # ── 4. 里宝牌指示牌不对没立直的人泄露 ─────────────────────────────
    st_plain = g3.state_for(0)
    st_riichi = Game(db, rid).state_for(0)
    st_other = Game(db, rid).state_for(1)
    check("没立直的人：state 里 ura 是空的", st_plain.get("ura"), [])
    check("立直的人：state 里能看到里宝牌指示牌", st_riichi.get("ura"), [URA_INDICATOR])
    check("立直局里，别家（没立直）看不到 ura", st_other.get("ura"), [])

    print()
    print(f"{PASS} 项通过 / {FAIL} 项失败")
    cleanup()
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
