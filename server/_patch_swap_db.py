import io

# ══════════════════════════════════════════════════════════════════════
# 1) schema.sql：牌河里的牌可能是「暗置」的（换牌技能放进去的）
# ══════════════════════════════════════════════════════════════════════
p = "schema.sql"
t = io.open(p, encoding="utf-8").read()
old = '''    is_riichi_tile INTEGER NOT NULL DEFAULT 0
'''
if old not in t:
    raise SystemExit("schema: 找不到 is_riichi_tile 列")
t = t.replace(old, '''    is_riichi_tile INTEGER NOT NULL DEFAULT 0,
    face_down   INTEGER NOT NULL DEFAULT 0,      -- 1 = 暗牌（换牌技能放进牌河的）
''', 1)
io.open(p, "w", encoding="utf-8", newline="").write(t)
print("schema.sql ok")

# ══════════════════════════════════════════════════════════════════════
# 2) db.py：迁移 + discard(face_down) + public_state + entity_states
# ══════════════════════════════════════════════════════════════════════
p = "db.py"
t = io.open(p, encoding="utf-8").read()


def sub(old, new):
    global t
    assert old in t, old[:80]
    t = t.replace(old, new, 1)


sub('''        wcols = {r["name"] for r in self._rows("PRAGMA table_info(round_wall)")}
''', '''        dcols = {r["name"] for r in self._rows("PRAGMA table_info(round_discards)")}
        if "face_down" not in dcols:          # 换牌技能：暗置进牌河的牌
            self.conn.execute("ALTER TABLE round_discards "
                              "ADD COLUMN face_down INTEGER NOT NULL DEFAULT 0")
        wcols = {r["name"] for r in self._rows("PRAGMA table_info(round_wall)")}
''')

sub('''    def discard(self, round_id: int, seat: int, wall_seq: int | None = None,
                riichi_tile: bool = False, client_action_id: str | None = None) -> dict | None:
''', '''    def discard(self, round_id: int, seat: int, wall_seq: int | None = None,
                riichi_tile: bool = False, face_down: bool = False,
                client_action_id: str | None = None) -> dict | None:
''')

sub('''            self.conn.execute(
                "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, is_tsumogiri, "
                "is_riichi_tile) VALUES(?,?,?,?,?,?,?)",
                (round_id, nxt, seat, row["wall_seq"], row["tile"], tsumogiri,
                 1 if riichi_tile else 0),
            )
''', '''            self.conn.execute(
                "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, is_tsumogiri, "
                "is_riichi_tile, face_down) VALUES(?,?,?,?,?,?,?,?)",
                (round_id, nxt, seat, row["wall_seq"], row["tile"], tsumogiri,
                 1 if riichi_tile else 0, 1 if face_down else 0),
            )
''')

sub('''            "discards": self._rows(
                "SELECT seq, seat, tile, is_tsumogiri, is_riichi_tile, called "
                "FROM round_discards WHERE round_id=? ORDER BY seq", (round_id,)),
''', '''            "discards": self._rows(
                "SELECT seq, seat, tile, is_tsumogiri, is_riichi_tile, called, face_down "
                "FROM round_discards WHERE round_id=? ORDER BY seq", (round_id,)),
''')

sub('''        for r in self._rows(
                "SELECT seq, wall_seq, seat, is_riichi_tile FROM round_discards "
                "WHERE round_id=? AND called=0 ORDER BY seq", (round_id,)):
            s = int(r["seat"])
            slot = int(river_counter.get(s, 0))
            river_counter[s] = slot + 1
            discards[int(r["wall_seq"])] = {
                "seat": s, "is_riichi_tile": r["is_riichi_tile"], "slot": slot,
            }
''', '''        for r in self._rows(
                "SELECT seq, wall_seq, seat, is_riichi_tile, face_down FROM round_discards "
                "WHERE round_id=? AND called=0 ORDER BY seq", (round_id,)):
            s = int(r["seat"])
            slot = int(river_counter.get(s, 0))
            river_counter[s] = slot + 1
            discards[int(r["wall_seq"])] = {
                "seat": s, "is_riichi_tile": r["is_riichi_tile"], "slot": slot,
                "discard_seq": int(r["seq"]), "face_down": int(r["face_down"] or 0),
            }
''')

sub('''            elif seq in discards:
                d = discards[seq]
                st.update({"loc": "river", "seat": d["seat"], "form": "river",
                           "rotated": bool(d["is_riichi_tile"]), "slot": d["slot"]})
''', '''            elif seq in discards:
                d = discards[seq]
                st.update({"loc": "river", "seat": d["seat"], "form": "river",
                           "rotated": bool(d["is_riichi_tile"]), "slot": d["slot"],
                           "discard_seq": d["discard_seq"], "face_down": d["face_down"]})
''')

io.open(p, "w", encoding="utf-8", newline="").write(t)
print("db.py ok")
