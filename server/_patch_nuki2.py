# -*- coding: utf-8 -*-
"""Card05 Skill2「拔北」——db/game/api 部分（skills/schema 已写）。"""
import io


def sub(t, old, new):
    assert old in t, "NOT FOUND: " + old[:100]
    return t.replace(old, new, 1)


# ── db.py 迁移 ────────────────────────────────────────────────
P = "db.py"
t = io.open(P, encoding="utf-8").read()
t = sub(t, '''        if "face_down" not in dcols:          # 换牌技能：暗置进牌河的牌
            self.conn.execute("ALTER TABLE round_discards "
                              "ADD COLUMN face_down INTEGER NOT NULL DEFAULT 0")
''',
        '''        if "face_down" not in dcols:          # 换牌技能：暗置进牌河的牌
            self.conn.execute("ALTER TABLE round_discards "
                              "ADD COLUMN face_down INTEGER NOT NULL DEFAULT 0")
        if "is_nuki" not in dcols:            # 拔北放下的北（不算振听）
            self.conn.execute("ALTER TABLE round_discards "
                              "ADD COLUMN is_nuki INTEGER NOT NULL DEFAULT 0")
''')
io.open(P, "w", encoding="utf-8", newline="").write(t)
print("db.py ok")

# ── game.py ───────────────────────────────────────────────────
P = "game.py"
t = io.open(P, encoding="utf-8").read()

t = sub(t, '''        self.card05_pending_hide: dict[int, int] = {}
        self._c05_cache: dict[int, bool] = {}
''',
        '''        self.card05_pending_hide: dict[int, int] = {}
        self.card05_nuki: dict[int, int] = {}       # 拔北次数（本局）
        self._c05_cache: dict[int, bool] = {}
''')

t = sub(t, '''        self.card05_pending_hide = {}
        for k, v in (f.get("card05_pending_hide") or {}).items():
            try:
                self.card05_pending_hide[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
        self._c05_cache = {}
''',
        '''        self.card05_pending_hide = {}
        for k, v in (f.get("card05_pending_hide") or {}).items():
            try:
                self.card05_pending_hide[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
        self.card05_nuki = {}
        for k, v in (f.get("card05_nuki") or {}).items():
            try:
                self.card05_nuki[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
        self._c05_cache = {}
''')

t = sub(t, '''            "card05_pending_hide": {str(k): v for k, v in self.card05_pending_hide.items()},
''',
        '''            "card05_pending_hide": {str(k): v for k, v in self.card05_pending_hide.items()},
            "card05_nuki": {str(k): v for k, v in self.card05_nuki.items()},
''')

t = sub(t, '''        if self.sees_face_down(seat):
            return [d["tile"] for d in self.db._rows(
                "SELECT tile FROM round_discards WHERE round_id=? AND seat=? "
                "ORDER BY seq", (self.round_id, seat))]
        return [d["tile"] for d in self.db._rows(
            "SELECT tile FROM round_discards WHERE round_id=? AND seat=? AND face_down=0 "
            "ORDER BY seq", (self.round_id, seat))]
''',
        '''        if self.sees_face_down(seat):
            return [d["tile"] for d in self.db._rows(
                "SELECT tile FROM round_discards WHERE round_id=? AND seat=? "
                "AND is_nuki=0 ORDER BY seq", (self.round_id, seat))]
        return [d["tile"] for d in self.db._rows(
            "SELECT tile FROM round_discards WHERE round_id=? AND seat=? AND face_down=0 "
            "AND is_nuki=0 ORDER BY seq", (self.round_id, seat))]
''')

t = sub(t, '''    def card05_swap(self, seat: int, hand_tile: str, kind: str,
''',
        '''    def card05_nuki(self, seat: int) -> dict:
        """拔北：把一张北放到牌河（不算振听、不鸣牌），从正常牌山补一张再打。"""
        if not self.owns_card05(seat):
            raise RuleError("这张不是你这一局的人物卡")
        if self.phase != "discard" or int(seat) != int(self.turn):
            raise RuleError("现在不是你的出牌回合")
        row = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile='bei' "
            "ORDER BY is_drawn DESC, wall_seq DESC LIMIT 1", (self.round_id, int(seat)))
        if row is None:
            raise RuleError("手里没有北")
        hseq = int(row["wall_seq"])
        with self.db.tx():
            self.db.conn.execute(
                "DELETE FROM round_hands WHERE round_id=? AND wall_seq=?",
                (self.round_id, hseq))
            dseq = int(self.db._one(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM round_discards WHERE round_id=?",
                (self.round_id,)) or 1)
            self.db.conn.execute(
                "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
                " is_tsumogiri, is_riichi_tile, face_down, called, is_nuki)"
                " VALUES(?,?,?,?,?,0,0,0,0,1)",
                (self.round_id, dseq, int(seat), hseq, "bei"))
        self.card05_nuki[int(seat)] = int(self.card05_nuki.get(int(seat), 0)) + 1
        if self.armed_skill and int(self.armed_skill.get("seat", -1)) == int(seat):
            self.armed_skill = None
            self._skill_cache = None
        self.press_win.discard(seat)
        # 从正常牌山补一张（不是岭上）
        info = self._draw_next_info(seat)
        if info is None:
            self.save_flags()
            return self._event("ryuukyoku", {"reason": "exhaustive"})
        self.phase = "discard"
        self.turn = int(seat)
        owner = self._self_wind_owner(seat, info["tile"])
        if owner is not None:
            self.wind_swap = {"owner": int(owner), "from": int(seat), "tile": info["tile"]}
            self.phase = "wind_swap"
        self.save_flags()
        return {"nuki": int(self.card05_nuki[int(seat)]), "drawn": info["tile"],
                "discard_seq": dseq}

    def card05_swap(self, seat: int, hand_tile: str, kind: str,
''')

t = sub(t, '''        # ── Card03 Skill1「自信」：和牌者番数双倍 ──
''',
        '''        # ── Card05 Skill2「拔北」：本局拔过几次就 +几番 ──
        nuki = int(self.card05_nuki.get(winner, 0))
        if nuki > 0 and not res.get("yakuman"):
            res["yaku"] = list(res.get("yaku") or []) + [{"name": "拔北", "han": nuki}]
            res["han"] = int(res["han"]) + nuki
            res["pays"] = score.payments(
                res["han"], res["fu"], is_dealer=(winner == self.dealer),
                tsumo=(result == "tsumo"), yakuman=0,
                kiriage_mangan=bool(self.rules.get("kiriage_mangan")))
            res["nuki"] = nuki
        # ── Card03 Skill1「自信」：和牌者番数双倍 ──
''')

t = sub(t, '''                           "hidden": len(self.card05_hidden.get(seat) or []),
                       },
''',
        '''                           "hidden": len(self.card05_hidden.get(seat) or []),
                           "nuki": int(self.card05_nuki.get(seat, 0)),
                       },
''')
io.open(P, "w", encoding="utf-8", newline="").write(t)
print("game.py ok")

# ── api_cli.py ────────────────────────────────────────────────
P = "api_cli.py"
t = io.open(P, encoding="utf-8").read()
t = sub(t, '''def op_card05_swap(db: DB, req: dict) -> dict:
''',
        '''def op_card05_nuki(db: DB, req: dict) -> dict:
    """Card05 Skill2「拔北」：把手里的北放出去，从正常牌山补一张。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.card05_nuki(seat)
    return {"ok": True, "nuki": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card05_swap(db: DB, req: dict) -> dict:
''')
t = sub(t, '''    "card05_swap": op_card05_swap,
''',
        '''    "card05_swap": op_card05_swap,
    "card05_nuki": op_card05_nuki,
''')
io.open(P, "w", encoding="utf-8", newline="").write(t)
print("api_cli.py ok")
