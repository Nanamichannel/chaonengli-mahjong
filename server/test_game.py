# -*- coding: utf-8 -*-
"""
对局流程自测：4 家机器人连打 + 定向验证（自摸 / 荣和 / 碰 / 立直 / 振听 / 流局）
运行：python test_game.py
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from db import DB
from game import Game, RuleError
from tiles import counts_of, parse_hand
from rules import calls, wallmodel

OK = FAIL = 0
HERE = os.path.dirname(os.path.abspath(__file__))
_OPEN_DBS: list = []


def check(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name}" + (f"  ({extra})" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {extra}")


def fresh_db(tag: str) -> DB:
    path = os.path.join(HERE, "data", f"_test_{tag}.db")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)
    db = DB(path)
    db.init_schema()
    # 四个座位都算「有人在操作」（时间戳写未来，测试跑久了也不会过期）。
    # 需要验证「AI 持有看破」的测试自己删掉对应座位的 lease 即可。
    stamp = "%.3f:%d" % (time.time() + 3600.0, os.getpid())
    with db.tx():
        for _s in range(4):
            db.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)",
                ("seat_lease_%d" % _s, stamp))
    _OPEN_DBS.append(db)
    return db


def new_round(db: DB, seed: int = 0):
    uids = [db.create_user(f"bot{seed}_{i}") for i in range(4)]
    room = db.create_room(uids[0])
    for u in uids[1:]:
        db.join_room(room["room_code"], u)
    match = db.start_match(room["room_id"], seed=seed)
    rid = db.start_round(match, "dong", 1, honba=0, dealer_seat=0, seed=seed)
    g = Game(db, rid)
    g.start()
    while not g.deal_done():        # 配牌交给服务端（带骰子的那套）
        g.deal_step()
    return rid, match, uids


_FAKE_SEQ = [900]          # 测试用的假 wall_seq：只增不减，两次 set_hand 不会撞号


def set_hand(db: DB, rid: int, seat: int, tiles: list[str], drawn: str | None = None):
    """测试用：把这个座位的手牌换成指定的牌。

    每张牌给一个「假编号」（>=900，避开真牌山的 0..135）。
    编号只增不减 —— 这样「同一张物理牌只有一个编号」在测试里也成立。
    """
    with db.tx():
        db.conn.execute("DELETE FROM round_hands WHERE round_id=? AND seat=?", (rid, seat))
        for i, t in enumerate(tiles):
            _FAKE_SEQ[0] += 1
            db.conn.execute(
                "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
                "VALUES(?,?,?,?,?,?)",
                (rid, seat, _FAKE_SEQ[0], t, i,
                 1 if (drawn and t == drawn and i == len(tiles) - 1) else 0))


def to_draw(g: Game, seat: int) -> Game:
    """测试用：把局面摆成「seat 该摸牌」（配牌已经由服务端做完了）。"""
    g.turn = seat
    g.phase = "draw"
    g.save_flags()
    return g


def set_next_draw(db: DB, rid: int, tile: str):
    """测试用：把「服务端下一个要摸的那张」换成指定牌（按编号找 seq）。"""
    with db.tx():
        g = Game(db, rid)
        no = wallmodel.next_live_no(g.next_no, g.wall_first_stack())
        db.conn.execute("UPDATE round_wall SET tile=? WHERE round_id=? AND seq=?",
                        (tile, rid, wallmodel.seq_of_tile(no)))


def clear_claims(g: Game) -> None:
    while g.phase == "claim" and g.pending:
        seat = next((s for s in g.pending["options"] if s not in g.pending["answers"]), None)
        if seat is None:
            g._resolve_claims()
            return
        g.pass_claim(seat)


def advance_to(g: Game, seat: int) -> bool:
    """推进到「指定座位出牌」为止（沿途的鸣牌窗口全部 pass 掉）。"""
    for _ in range(30):
        if g.phase == "discard" and g.turn == seat:
            return True
        if g.phase == "ended":
            return False
        if g.phase == "claim":
            clear_claims(g)
        else:
            g.advance()
    return False


# ══════════════════════════════════════════════════════════════════════════
def play_round(db: DB, rid: int, claim_prob: float = 0.6, seed: int = 0):
    """四个机器人打一局：能自摸就自摸、偶尔吃碰、其余摸切。"""
    g = Game(db, rid)
    g.start()
    rng = random.Random(seed)
    steps = 0
    while g.phase != "ended" and steps < 800:
        steps += 1
        if g.phase == "draw":
            g.advance()
            continue
        if g.phase == "claim":
            seat = next((s for s in g.pending["options"] if s not in g.pending["answers"]), None)
            if seat is None:
                g._resolve_claims()
                continue
            acts = {a["action"] for a in g.legal_actions(seat)}
            if "ron" in acts:
                g.act(seat, "ron")
            elif (acts & {"pon", "chi", "minkan"}) and rng.random() < claim_prob:
                pick = sorted(acts & {"pon", "minkan", "chi"},
                              key=lambda a: {"minkan": 0, "pon": 1, "chi": 2}[a])[0]
                g.act(seat, pick)
            else:
                g.pass_claim(seat)
            continue
        seat = g.turn
        acts = {a["action"] for a in g.legal_actions(seat)}
        if "tsumo" in acts:
            g.act(seat, "tsumo")
        else:
            g.act(seat, "discard")                      # 摸切
    return g, steps


def main():
    print("=" * 70)
    print(" 天才麻将少女 · 对局流程自测")
    print("=" * 70)

    # ── 1. 机器人连打 20 局 ────────────────────────────────────────────────
    print("\n[1] 四个机器人连打 20 局（不同牌山）")
    db = fresh_db("flow")
    ends, bad = {}, []
    for seed in range(20):
        rid, match, _ = new_round(db, seed=seed)
        g, steps = play_round(db, rid, seed=seed)
        key = (g.result or {}).get("result", "none")
        ends[key] = ends.get(key, 0) + 1
        total = sum(s["score"] for s in db._rows(
            "SELECT score FROM match_seats WHERE match_id=?", (match,)))
        acts = [a["seq"] for a in db.replay(rid)]
        if total != 140000 or acts != list(range(1, len(acts) + 1)) or g.phase != "ended":
            bad.append((seed, total, len(acts), g.phase))
    check("20 局全部正常结束", not bad, f"结局分布 {ends} {bad[:2]}")
    check("每局总分都 = 140000，动作日志不跳号", not bad)

    # ── 2. 自摸和牌 ────────────────────────────────────────────────────────
    print("\n[2] 自摸和牌（定向：庄家听 1s，牌山下一张就是 1s）")
    db2 = fresh_db("win")
    rid, match, _ = new_round(db2, seed=3)
    set_hand(db2, rid, 0, parse_hand("123m456m789m123p1s"))
    set_next_draw(db2, rid, "1s")
    g = to_draw(Game(db2, rid), 0)
    g.advance()
    acts = {a["action"] for a in g.legal_actions(0)}
    check("摸到后出现「自摸」选项", "tsumo" in acts, str(sorted(acts)))
    ev = g.act(0, "tsumo")
    check("自摸结算成功", ev["event"] == "tsumo", str([y["name"] for y in ev["yaku"]]))
    check("第一巡自摸 = 天和（役满）",
          any("天和" in y["name"] for y in ev["yaku"]) and ev["points"].get("yakuman") == 1,
          str([y["name"] for y in ev["yaku"]]))
    check("亲家役满 = 48000 点", ev["points"]["total"] == 48000, str(ev["points"]["total"]))
    sc = {s["seat"]: s["score"] for s in db2.public_state(rid)["scores"]}
    check("亲家自摸收三家钱", sc[0] > 35000 and all(sc[s] < 35000 for s in (1, 2, 3)), str(sc))

    # ── 3. 荣和 ────────────────────────────────────────────────────────────
    print("\n[3] 荣和（别人打出我听的牌）")
    db3 = fresh_db("ron")
    rid, match, _ = new_round(db3, seed=5)
    set_hand(db3, rid, 0, parse_hand("123m456m789m123p1s"))
    set_hand(db3, rid, 1, parse_hand("234m567m234p55s"), drawn="1s")
    set_hand(db3, rid, 1, parse_hand("234m567m234p55s") + ["1s"], drawn="1s")
    # 0 号位摸到 9s 再摸切：否则随机摸到 1s 会把自己的听牌打掉 → 振听（历史 flaky）
    set_next_draw(db3, rid, "9s")
    g = to_draw(Game(db3, rid), 0)
    check("推进到 0 号位出牌", advance_to(g, 0))
    g.act(0, "discard")
    clear_claims(g)
    check("推进到 1 号位出牌", advance_to(g, 1))
    g.act(1, "discard", tile="1s")
    opts = {o["action"] for o in (g.pending or {}).get("options", {}).get(0, [])}
    check("给 0 号位弹出「荣和」", "ron" in opts, str(opts))
    ev = g.act(0, "ron")
    check("荣和结算成功", ev["event"] == "ron" and ev["from"] == 1,
          str([y["name"] for y in ev["yaku"]]))
    sc = {s["seat"]: s["score"] for s in db3.public_state(rid)["scores"]}
    check("只由放铳的人付钱", sc[0] > 35000 and sc[1] < 35000 and sc[2] == 35000, str(sc))

    # ── 4. 碰 + 食い替え ──────────────────────────────────────────────────
    print("\n[4] 碰（+ 碰完不能打碰来的那张）")
    db4 = fresh_db("pon")
    rid, match, _ = new_round(db4, seed=7)
    set_hand(db4, rid, 0, parse_hand("123m456m789m123p1s"))
    set_hand(db4, rid, 1, parse_hand("234m567m234p22s") + ["5m"], drawn="5m")
    set_hand(db4, rid, 2, parse_hand("5m5m1p2p3p4p6p7p1s2s3s9s9s"))
    g = to_draw(Game(db4, rid), 0)
    advance_to(g, 0)
    g.act(0, "discard")
    clear_claims(g)
    advance_to(g, 1)
    g.act(1, "discard", tile="5m")
    opts = {o["action"] for o in (g.pending or {}).get("options", {}).get(2, [])}
    check("给 2 号位弹出「碰」", "pon" in opts, str(opts))
    ev = g.act(2, "pon")
    check("碰成功", ev["event"] == "pon", str(ev))
    check("碰完只剩 11 张手牌", len(g.hand(2)) == 11, str(len(g.hand(2))))
    check("轮到碰的人打牌", g.turn == 2 and g.phase == "discard")
    check("数据库里记了一副副露",
          db4._one("SELECT COUNT(*) FROM round_melds WHERE round_id=? AND seat=2", (rid,)) == 1)
    try:
        g.act(2, "discard", tile="5m")
        check("食い替え：不能打碰来的那张", False)
    except RuleError:
        check("食い替え：不能打碰来的那张", True)
    g.act(2, "discard", tile="9s")
    check("打别的牌没问题", g.turn != 2 or g.phase == "claim", f"turn={g.turn} phase={g.phase}")
    check("牌河里多了一张 9s",
          db4._one("SELECT COUNT(*) FROM round_discards WHERE round_id=? AND seat=2", (rid,)) == 1)

    # ── 5. 立直 / 振听 ────────────────────────────────────────────────────
    print("\n[5] 立直 / 振听")
    db5 = fresh_db("riichi")
    rid, match, _ = new_round(db5, seed=11)
    set_hand(db5, rid, 0, parse_hand("123m456m789m123p12s"), drawn="2s")
    g = to_draw(Game(db5, rid), 0)
    g.advance()
    acts = {a["action"] for a in g.legal_actions(0)}
    check("能立直时提示立直", "riichi" in acts, str(sorted(acts)))
    g.act(0, "riichi", tile="2s")
    check("立直记录已写入",
          db5._one("SELECT COUNT(*) FROM round_riichi WHERE round_id=? AND seat=0", (rid,)) == 1)
    check("宣言牌在牌河里是横置的",
          db5._one("SELECT is_riichi_tile FROM round_discards WHERE round_id=? ORDER BY seq DESC "
                   "LIMIT 1", (rid,)) == 1)
    check("扣了 1000 点供托",
          db5._one("SELECT score FROM match_seats WHERE match_id=? AND seat=0", (match,)) == 34000)
    with db5.tx():
        db5.conn.execute("INSERT INTO round_discards(round_id,seq,seat,wall_seq,tile) "
                         "VALUES(?,999,0,999,'1s')", (rid,))
    set_hand(db5, rid, 0, parse_hand("123m456m789m123p1s"))
    check("振听判定：牌河里有 1s → 不能荣和 1s",
          not calls.can_ron(counts_of(parse_hand("123m456m789m123p1s")), [], ["1s"], "1s"))

    # ── 6. 荒牌流局 ────────────────────────────────────────────────────────
    print("\n[6] 荒牌流局")
    db6 = fresh_db("exhaust")
    rid, match, _ = new_round(db6, seed=13)
    g = to_draw(Game(db6, rid), 0)
    advance_to(g, 0)
    g.act(0, "discard")
    clear_claims(g)
    with db6.tx():                                         # 把牌山摸空
        db6.conn.execute("UPDATE rounds SET live_left=0 WHERE round_id=?", (rid,))
        db6.conn.execute("UPDATE round_wall SET dealt_to=0 WHERE round_id=? AND zone='live' "
                         "AND draw_no IS NOT NULL", (rid,))
    g.advance()
    check("自动判荒牌流局", g.phase == "ended" and g.result["result"] == "ryuukyoku",
          str(g.result))
    tot = sum(s["score"] for s in db6.public_state(rid)["scores"])
    check("流局后总分仍 = 140000", tot == 140000, str(tot))

    # ── 7. 杠的规则：暗杠 / 加杠 / 抢杠 ────────────────────────────────────
    print("\n[7] 杠：加杠 + 抢杠")
    db7 = fresh_db("kan")
    rid, match, _ = new_round(db7, seed=17)
    set_hand(db7, rid, 0, parse_hand("234m67m456p789s11z"))      # 等 5m / 8m
    set_hand(db7, rid, 1, parse_hand("123m456p789s1s5m"))        # 11 张 + 手里第 4 张 5m
    with db7.tx():                                               # 假装 1 号位已经碰过 5m
        db7.conn.execute(
            "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
            "tiles_json,rot_index) VALUES(?,0,1,'pon','5m',2,'[\"5m\",\"5m\",\"5m\"]',0)",
            (rid,))
    set_next_draw(db7, rid, "9p")
    g = to_draw(Game(db7, rid), 0)
    advance_to(g, 0)
    g.act(0, "discard")                     # 摸切，保持听 5m
    clear_claims(g)
    advance_to(g, 1)
    acts = {a["action"] for a in g.legal_actions(1)}
    check("碰过之后能加杠", "kakan" in acts, str(sorted(acts)))
    ev = g.act(1, "kakan", tile="5m")
    check("加杠被抢 → 直接荣和", ev["event"] == "chankan", str(ev.get("event")))
    check("役种里有抢杠", any("抢杠" in y["name"] for y in ev["yaku"]),
          str([y["name"] for y in ev["yaku"]]))
    check("点炮的是加杠那家", ev["from"] == 1 and ev["seat"] == 0, str(ev))
    check("杠没有真的成立（没多出一副副露）",
          db7._one("SELECT COUNT(*) FROM round_melds WHERE round_id=? AND seat=1", (rid,)) == 1)

    # ── 8. 特殊流局 ───────────────────────────────────────────────────────
    print("\n[8] 特殊流局：四风连打 / 四家立直 / 四杠散了")
    db8 = fresh_db("sufon")
    rid, match, _ = new_round(db8, seed=19)
    for s in range(4):
        set_hand(db8, rid, s, parse_hand("123m456p789s123s") + ["dong"])
    g = to_draw(Game(db8, rid), 0)
    for s in range(4):
        advance_to(g, s)
        g.act(s, "discard", tile="dong")
        clear_claims(g)
    check("四风连打 → 流局", g.phase == "ended" and g.result["reason"] == "sufon_renda",
          str(g.result))

    db9 = fresh_db("sucha")
    rid, match, _ = new_round(db9, seed=23)
    set_hand(db9, rid, 0, parse_hand("123m456m789m123p12s"), drawn="2s")
    with db9.tx():
        for s in (1, 2, 3):
            db9.conn.execute("INSERT INTO round_riichi(round_id, seat, declared_seq) "
                             "VALUES(?,?,0)", (rid, s))
    g = to_draw(Game(db9, rid), 0)
    advance_to(g, 0)
    g.act(0, "riichi", tile="2s")
    check("四家立直 → 流局", g.phase == "ended" and g.result["reason"] == "sucha_riichi",
          str(g.result))

    db10 = fresh_db("sukan")
    rid, match, _ = new_round(db10, seed=29)
    with db10.tx():
        for s in (0, 1):
            for m in range(2):
                db10.conn.execute(
                    "INSERT INTO round_melds(round_id,meld_id,seat,kind,called_tile,from_seat,"
                    "tiles_json,rot_index) VALUES(?,?,?,'ankan','1m',?,"
                    "'[\"1m\",\"1m\",\"1m\",\"1m\"]',-1)", (rid, m, s, s))
    g = Game(db10, rid)
    g._check_abortive()
    check("两家各两个杠 → 四杠散了", g.phase == "ended" and g.result["reason"] == "sukan_santan",
          str(g.result))

    # ── 9. 双立直 ─────────────────────────────────────────────────────────
    print("\n[9] 双立直（第一巡立直）")
    db11 = fresh_db("dbl")
    rid, match, _ = new_round(db11, seed=31)
    set_hand(db11, rid, 0, parse_hand("123m456m789m123p12s"), drawn="2s")
    g = to_draw(Game(db11, rid), 0)
    advance_to(g, 0)
    g.act(0, "riichi", tile="2s")
    check("第一巡立直 → 记成双立直", 0 in g.double_riichi, str(g.double_riichi))

    print("\n" + "=" * 70)
    print(f" 结果：{OK} 项通过，{FAIL} 项失败")
    print("=" * 70)
    # 把测试用的临时库删掉，别留在 data 目录里（先关连接，不然 Windows 删不掉）
    for d in _OPEN_DBS:
        try:
            d.close()
        except Exception:
            pass
    data_dir = os.path.join(HERE, "data")
    if os.path.isdir(data_dir):
        for f in os.listdir(data_dir):
            if f.startswith("_test_"):
                try:
                    os.remove(os.path.join(data_dir, f))
                except OSError:
                    pass
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
