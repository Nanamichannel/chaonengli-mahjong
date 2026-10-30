# -*- coding: utf-8 -*-
"""换牌原子操作（服务端）

所有「两张牌的牌面对调 / 一张牌换个位置」都从这里走，禁止各技能自己拼 SQL。

为什么必须统一（历史 bug 清单）：
  · 只改 round_hands.tile 不改 round_wall.tile → 样式换了、实体编号没换，场上凭空多一张
  · 只改 round_wall.tile 不改 round_discards.tile → 牌河还显示旧牌
  · 换了宝牌指示牌却没重算 round_dora   → 宝牌信息错
  · 换了别人的手牌却没通知「策略」(Card05 S1) → 对方拿不到换牌机会

定位一律用 wall_seq（物理牌编号），不用牌名：同名 4 张时按牌名找牌会找错。
三张视图表（都以 wall_seq 关联）必须同时保持一致：
    round_wall.tile      实体真实牌面
    round_hands.tile     手牌视图
    round_discards.tile  牌河视图
"""
from __future__ import annotations

from db import DB


def tile_of(db: DB, rid: int, seq: int) -> str | None:
    """这个物理编号现在是什么牌（优先 round_wall，取不到再退回视图表）。"""
    row = db._row("SELECT tile FROM round_wall WHERE round_id=? AND seq=?", (int(rid), int(seq)))
    if row:
        return str(row["tile"])
    row = db._row("SELECT tile FROM round_hands WHERE round_id=? AND wall_seq=?",
                  (int(rid), int(seq)))
    if row:
        return str(row["tile"])
    row = db._row("SELECT tile FROM round_discards WHERE round_id=? AND wall_seq=?",
                  (int(rid), int(seq)))
    return str(row["tile"]) if row else None


def river_wall_seq(db: DB, rid: int, river_seq: int) -> int:
    row = db._row("SELECT wall_seq FROM round_discards WHERE round_id=? AND seq=?",
                  (int(rid), int(river_seq)))
    if row is None:
        raise KeyError(f"牌河没有这一张（seq={river_seq}）")
    return int(row["wall_seq"])


def swap_faces(db: DB, rid: int, seq_a: int, seq_b: int) -> set[int]:
    """把两张物理牌的**牌面**对调（位置/归属/明暗都不动）。

    手牌 ⇄ 牌河、手牌 ⇄ 牌山/王牌、牌山内部对调，全都用这个。
    """
    a, b = int(seq_a), int(seq_b)
    if a == b:
        return set()
    ta = tile_of(db, rid, a)
    tb = tile_of(db, rid, b)
    if ta is None or tb is None:
        raise KeyError(f"物理牌不存在：seq={a}/{b}")
    with db.tx():
        # round_wall 里没有这行（测试夹具的假编号）时，这条 UPDATE 自然是空操作
        db.conn.execute("UPDATE round_wall SET tile=? WHERE round_id=? AND seq=?",
                        (tb, int(rid), a))
        db.conn.execute("UPDATE round_wall SET tile=? WHERE round_id=? AND seq=?",
                        (ta, int(rid), b))
        # 手牌视图 / 牌河视图（两者都按 wall_seq 关联）
        for seq, tile in ((a, tb), (b, ta)):
            db.conn.execute(
                "UPDATE round_hands SET tile=? WHERE round_id=? AND wall_seq=?",
                (tile, int(rid), seq))
            db.conn.execute(
                "UPDATE round_discards SET tile=? WHERE round_id=? AND wall_seq=?",
                (tile, int(rid), seq))
    return {a, b}


def swap_hand_river(db: DB, rid: int, hand_seq: int, river_seq: int,
                    face_down: bool | None = None) -> dict:
    """手牌一张 ⇄ 牌河一张（牌面对调）。face_down=None 保持牌河原来的明暗。"""
    rseq = river_wall_seq(db, rid, river_seq)
    got = tile_of(db, rid, rseq)
    gave = tile_of(db, rid, int(hand_seq))
    seqs = swap_faces(db, rid, int(hand_seq), rseq)
    if face_down is not None:
        with db.tx():
            db.conn.execute(
                "UPDATE round_discards SET face_down=? WHERE round_id=? AND seq=?",
                (1 if face_down else 0, int(rid), int(river_seq)))
    return {"got": got, "gave": gave, "seqs": seqs, "river_seq": int(river_seq),
            "hand_seq": int(hand_seq)}


def swap_hand_wall(db: DB, rid: int, hand_seq: int, wall_seq: int) -> dict:
    """手牌一张 ⇄ 牌山/王牌一张（牌面对调）。"""
    got = tile_of(db, rid, int(wall_seq))
    gave = tile_of(db, rid, int(hand_seq))
    seqs = swap_faces(db, rid, int(hand_seq), int(wall_seq))
    return {"got": got, "gave": gave, "seqs": seqs, "hand_seq": int(hand_seq),
            "wall_seq": int(wall_seq)}


def swap_wall_wall(db: DB, rid: int, seq_a: int, seq_b: int) -> dict:
    got = tile_of(db, rid, int(seq_b))
    gave = tile_of(db, rid, int(seq_a))
    seqs = swap_faces(db, rid, int(seq_a), int(seq_b))
    return {"got": got, "gave": gave, "seqs": seqs}


def swap_hand_hand(db: DB, rid: int, seat_a: int, hand_seq_a: int,
                   seat_b: int, hand_seq_b: int) -> dict:
    """两家手牌互换。口径：`hand_seq_a` 是 seat_a 自己的那张（拿出去给 seat_b），
    `hand_seq_b` 是 seat_b 自己的那张（换给 seat_a）。

    不是「换牌面」，而是「换归属」：只把两行 round_hands 的 seat 对调，
    牌面不动（牌面就是实体牌本身，归属变了牌自然就跟着走）。
    """
    a, b = int(hand_seq_a), int(hand_seq_b)
    ta, tb = tile_of(db, rid, a), tile_of(db, rid, b)
    if ta is None or tb is None:
        raise KeyError(f"物理牌不存在：seq={a}/{b}")
    # ★ 只手牌**归属**对调，牌面不动。
    #   以前这里「换归属 + 再把牌面也对调」→ 两张都回到原主（净零），
    #   测出来就是「手牌根本没换」（深山 / 海神借牌 / 宝牌的集合 / 向听 全受影响）。
    with db.tx():
        db.conn.execute("UPDATE round_hands SET seat=? WHERE round_id=? AND wall_seq=?",
                        (int(seat_b), int(rid), a))
        db.conn.execute("UPDATE round_hands SET seat=? WHERE round_id=? AND wall_seq=?",
                        (int(seat_a), int(rid), b))
    # got = 我（seat_a）换到手的那张 → 是 b 那张；gave = 我拿出去的 a 那张
    return {"got": tb, "gave": ta, "seqs": {a, b}}


def move_river_to_hand(db: DB, rid: int, river_seq: int, seat: int) -> dict:
    """把牌河里的一张牌**收进手里**（那一格空出来，不补牌）。友引 / 画板用。"""
    row = db._row(
        "SELECT seq, wall_seq, tile, called, face_down FROM round_discards "
        "WHERE round_id=? AND seq=?", (int(rid), int(river_seq)))
    if row is None:
        raise KeyError(f"牌河没有这一张（seq={river_seq}）")
    tile, wseq = str(row["tile"]), int(row["wall_seq"])
    with db.tx():
        db.conn.execute("DELETE FROM round_discards WHERE round_id=? AND seq=?",
                        (int(rid), int(river_seq)))
        db.conn.execute("UPDATE round_hands SET is_drawn=0 WHERE round_id=? AND seat=?",
                        (int(rid), int(seat)))
        slot = (db._one(
            "SELECT COALESCE(MAX(slot), -1) + 1 FROM round_hands WHERE round_id=? AND seat=?",
            (int(rid), int(seat))) or 0)
        db.conn.execute(
            "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
            "VALUES(?,?,?,?,?,1)", (int(rid), int(seat), wseq, tile, int(slot)))
    return {"got": tile, "seqs": {wseq}, "river_seq": int(river_seq)}
