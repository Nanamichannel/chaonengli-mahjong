# -*- coding: utf-8 -*-
"""回填 round_wall.entity：旧局没有实体编号，按 kind 计数补上，使 ID 与 TileBank 一致。"""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import db

d = db.DB()
RED = ("0m", "0p", "0s")
SRC = ("5m", "5p", "5s")

round_ids = [r["round_id"] for r in d._rows("SELECT round_id FROM rounds ORDER BY round_id")]
for rid in round_ids:
    wall = d._rows(
        "SELECT seq, tile, entity FROM round_wall WHERE round_id=? ORDER BY seq",
        (rid,))
    if not wall:
        continue
    # 若所有 entity 都非空则跳过
    if all((w["entity"] or "").strip() for w in wall):
        continue
    counter = {}
    for w in wall:
        t = w["tile"]
        if t in RED:
            entity = f"{t}01"
        else:
            n = counter.get(t, 0) + 1
            counter[t] = n
            entity = f"{t}{n:02d}"
        d.conn.execute(
            "UPDATE round_wall SET entity=? WHERE round_id=? AND seq=?",
            (entity, rid, w["seq"]))
    d.conn.commit()

# 校验：每个局的 entity 集合应与 build_entities 一致
from tiles import build_entities
expect = set(build_entities(red_fives=True))
bad = []
for rid in round_ids:
    ent = [r["entity"] for r in d._rows(
        "SELECT entity FROM round_wall WHERE round_id=? ORDER BY seq", (rid,))]
    if len(ent) == 136:
        if set(ent) != expect:
            bad.append((rid, "mismatch", sorted(expect - set(ent))[:5]))
    elif ent and not all(e for e in ent):
        bad.append((rid, "has empty", len([e for e in ent if not e])))
print("backfilled rounds:", len(round_ids))
print("expect entities:", len(expect))
print("bad:", bad if bad else "NONE")
