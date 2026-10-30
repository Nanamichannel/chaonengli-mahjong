import io

p = "game.py"
t = io.open(p, encoding="utf-8").read()


def sub(old, new):
    global t
    assert old in t, old[:80]
    t = t.replace(old, new, 1)


# ── 1) 振听只看「正常打出的牌」：换牌暗置进牌河的不算 ─────────────
sub('''    def discards(self, seat: int) -> list[str]:
        return [d["tile"] for d in self.db._rows(
            "SELECT tile FROM round_discards WHERE round_id=? AND seat=? ORDER BY seq",
            (self.round_id, seat))]
''', '''    def discards(self, seat: int) -> list[str]:
        return [d["tile"] for d in self.db._rows(
            "SELECT tile FROM round_discards WHERE round_id=? AND seat=? ORDER BY seq",
            (self.round_id, seat))]

    def discards_for_furiten(self, seat: int) -> list[str]:
        """振听只看自己真正打出去的牌。

        换牌技能（Card02 Skill2）会把我的手牌**暗置**塞进别人的牌河，
        那不是他打出来的牌，不能让他因此额外振听。
        """
        return [d["tile"] for d in self.db._rows(
            "SELECT tile FROM round_discards WHERE round_id=? AND seat=? AND face_down=0 "
            "ORDER BY seq", (self.round_id, seat))]

    def draw_count(self, seat: int) -> int:
        """这一局这个座位摸过几次牌（用来判断「第十三巡前」）。"""
        return int(self.db._one(
            "SELECT COUNT(*) FROM round_actions WHERE round_id=? AND seat=? AND action='draw'",
            (self.round_id, seat)) or 0)
''')

sub('''        return tenpai.furiten_info(self.hand_counts(seat), self.melds(seat),
                                   self.discards(seat),''',
    '''        return tenpai.furiten_info(self.hand_counts(seat), self.melds(seat),
                                   self.discards_for_furiten(seat),''')

sub('''        if calls.is_permanent_furiten(c13, melds, self.discards(seat)):''',
    '''        if calls.is_permanent_furiten(c13, melds, self.discards_for_furiten(seat)):''')

sub('''        if calls.is_permanent_furiten(self.hand_counts(seat), self.melds(seat),
                                      self.discards(seat)):''',
    '''        if calls.is_permanent_furiten(self.hand_counts(seat), self.melds(seat),
                                      self.discards_for_furiten(seat)):''')

# ── 2) 换牌技能（Card02 Skill2）──────────────────────────────────
anchor = '''    def _board_take(self, seat: int) -> dict | None:
'''
assert anchor in t
new_methods = '''    def swap_river(self, seat: int, hand_tiles: list[str],
                   river_seqs: list[int]) -> dict:
        """Card02 Skill2：三张手牌暗置换进牌河，对应的三张牌河牌进手牌。

        · 只能在第十三巡前（自己摸牌次数 <= 12）、摸牌后、本小局一次
        · 换进来的牌河牌不算「打出去的牌」→ 不发生额外振听（见 discards_for_furiten）
        """
        if self.phase != "discard" or seat != self.turn:
            raise RuleError("现在不是你的出牌回合")
        if self.drawn_tile(seat) is None:
            raise RuleError("摸牌之后才能发动")
        if self.skill_used(seat, 2, 2):
            raise RuleError("这个技能本局已经用过了")
        if self.draw_count(seat) > 12:
            raise RuleError("第十三巡之后不能发动")
        picks = [str(t) for t in hand_tiles]
        if len(picks) != 3:
            raise RuleError("要选三张手牌")
        seqs = [int(s) for s in river_seqs]
        if len(seqs) != 3 or len(set(seqs)) != 3:
            raise RuleError("要选三张不同的牌河牌")

        # 手牌：同一种牌可以选多张，按张数扣
        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, seat))
        pool: dict[str, list[int]] = {}
        for r in rows:
            pool.setdefault(str(r["tile"]), []).append(int(r["wall_seq"]))
        hand_rows: list[tuple[str, int]] = []
        for tile in picks:
            if not pool.get(tile):
                raise RuleError(f"手里没有 {tile}")
            hand_rows.append((tile, pool[tile].pop(0)))

        # 牌河
        river: dict[int, dict] = {}
        for r in self.db._rows(
                "SELECT seq, seat, wall_seq, tile, called, is_riichi_tile, face_down "
                "FROM round_discards WHERE round_id=? ORDER BY seq", (self.round_id,)):
            river[int(r["seq"])] = r
        river_rows = []
        for s in seqs:
            row = river.get(s)
            if row is None:
                raise RuleError("这张牌不在牌河里")
            if int(row["called"] or 0):
                raise RuleError("已经被吃碰杠拿走的牌不能换")
            if int(row["is_riichi_tile"] or 0):
                raise RuleError("立直宣言牌不能换")
            if int(row["face_down"] or 0):
                raise RuleError("暗牌不能再换")
            river_rows.append(row)

        with self.db.tx():
            for (tile, hseq), row in zip(hand_rows, river_rows):
                # 手牌 → 暗置进牌河（占用被换走那张的位置）
                self.db.conn.execute(
                    "DELETE FROM round_hands WHERE round_id=? AND wall_seq=?",
                    (self.round_id, hseq))
                self.db.conn.execute(
                    "UPDATE round_discards SET wall_seq=?, tile=?, face_down=1, is_tsumogiri=0 "
                    "WHERE round_id=? AND seq=?",
                    (hseq, tile, self.round_id, int(row["seq"])))
                # 牌河那张 → 进我的手牌（不是摸进来的）
                slot = self.db._one(
                    "SELECT COALESCE(MAX(slot), -1) + 1 FROM round_hands "
                    "WHERE round_id=? AND seat=?", (self.round_id, seat)) or 0
                self.db.conn.execute(
                    "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
                    "VALUES(?,?,?,?,?,0)",
                    (self.round_id, seat, int(row["wall_seq"]), str(row["tile"]), int(slot)))
        self.mark_skill_used(seat, 2, 2)
        self.save_flags()
        return {"hand": picks, "river": seqs,
                "got": [str(r["tile"]) for r in river_rows]}

''' + anchor
t = t.replace(anchor, new_methods, 1)

io.open(p, "w", encoding="utf-8", newline="").write(t)
print("game.py ok")

# ── 3) api_cli：op=swap ─────────────────────────────────────────
p = "api_cli.py"
t = io.open(p, encoding="utf-8").read()
anchor2 = '''def op_tenpai(db: DB, req: dict) -> dict:
'''
assert anchor2 in t
new_op = '''def op_swap(db: DB, req: dict) -> dict:
    """Card02 Skill2：三张手牌暗置换进牌河，换回三张牌河牌。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    hand_tiles = [str(t) for t in (req.get("hand_tiles") or [])]
    river = [int(x) for x in (req.get("river") or [])]
    r = g.swap_river(seat, hand_tiles, river)
    return {"ok": True, "swap": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


''' + anchor2
t = t.replace(anchor2, new_op, 1)

old_ops = '''    "board": op_board,
'''
new_ops = '''    "board": op_board,
    "swap": op_swap,
'''
assert old_ops in t
t = t.replace(old_ops, new_ops, 1)
io.open(p, "w", encoding="utf-8", newline="").write(t)
print("api_cli.py ok")
