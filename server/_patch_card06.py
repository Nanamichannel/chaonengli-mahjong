# -*- coding: utf-8 -*-
"""Card06 Skill1「南风」服务端补丁。"""
import io
import random

P = "skills.py"
t = io.open(P, encoding="utf-8").read()


def sub(old, new):
    global t
    assert old in t, "NOT FOUND: " + old[:110]
    t = t.replace(old, new, 1)


sub('''    (5, 2): {"name": "拔北", "kind": "nuki", "timing": "draw"},
}''',
    '''    (5, 2): {"name": "拔北", "kind": "nuki", "timing": "draw"},
    (6, 1): {"name": "南风", "kind": "south_wind", "timing": "deal"},
}''')
sub('''    (5, 1): "draw", (5, 2): "draw",
}''',
    '''    (5, 1): "draw", (5, 2): "draw",
    (6, 1): "deal",
}''')
io.open(P, "w", encoding="utf-8", newline="").write(t)
print("skills.py ok")

P = "game.py"
t = io.open(P, encoding="utf-8").read()

# 1) 配牌技能选项：南风只在南场可用
sub('''        for card, skill in skills.deal_skills():
            # 在配牌动画里（窗口出现之前）就点过技能的人，不再让他重复决定
            if (int(card), int(skill)) == (3, 1) and seat in self.confident:
                continue
''',
    '''        for card, skill in skills.deal_skills():
            # 在配牌动画里（窗口出现之前）就点过技能的人，不再让他重复决定
            if (int(card), int(skill)) == (3, 1) and seat in self.confident:
                continue
            # 南风：只有南场才有这个技能
            if (int(card), int(skill)) == (6, 1) and str(self.round_wind) != "nan":
                continue
''')

# 2) 风神流程标记 kind
sub('''        self.deal_flow = {
            "seat": int(seat), "card": int(card), "skill": int(skill),
            "stage": 0, "n": 0, "target": -1,
            "targets": [(int(seat) + 1) % 4, (int(seat) + 2) % 4, (int(seat) + 3) % 4],
        }
''',
    '''        self.deal_flow = {
            "kind": "fengshen",
            "seat": int(seat), "card": int(card), "skill": int(skill),
            "stage": 0, "n": 0, "target": -1,
            "targets": [(int(seat) + 1) % 4, (int(seat) + 2) % 4, (int(seat) + 3) % 4],
        }
''')

# 3) deal_flow_view：带上 kind / kinds
sub('''    def deal_flow_view(self, seat: int) -> dict | None:
        f = self.deal_flow
        if not f or int(f.get("seat", -1)) != int(seat):
            return None
        return {"seat": int(f["seat"]), "stage": int(f["stage"]),
                "target": int(f.get("target", -1)), "n": int(f.get("n", 0)),
                "card": int(f["card"]), "skill": int(f["skill"])}
''',
    '''    def deal_flow_view(self, seat: int) -> dict | None:
        f = self.deal_flow
        if not f or int(f.get("seat", -1)) != int(seat):
            return None
        out = {"seat": int(f["seat"]), "card": int(f["card"]),
               "skill": int(f["skill"]), "kind": str(f.get("kind", "fengshen")),
               "stage": f.get("stage")}
        if "targets" in f:
            out["target"] = int(f.get("target", -1))
            out["n"] = int(f.get("n", 0))
        if "kinds" in f:
            out["kinds"] = [str(x) for x in (f.get("kinds") or [])]
        return out
''')

# 4) 南风：启动 / 选牌种 / 选两张手牌并结算
sub('''    def _advance_deal_flow(self) -> None:
''',
    '''    def _start_south_wind(self, seat: int, card: int, skill: int) -> dict:
        """南场配牌：先指定两种牌，再选两张手牌，按 下家→对家→上家 强制交换。"""
        self.deal_flow = {
            "kind": "south_wind",
            "seat": int(seat), "card": int(card), "skill": int(skill),
            "stage": "kinds", "kinds": [],
            "targets": [(int(seat) + 1) % 4, (int(seat) + 2) % 4, (int(seat) + 3) % 4],
        }
        self.note_skill(seat, card, skill)
        self.save_flags()
        return {"ok": True, "armed": True, "card": int(card), "skill": int(skill),
                "skill_name": skills.info(card, skill).get("name", ""),
                "kind": "south_wind", "flow": self.deal_flow_view(seat),
                "pending": sorted(self.deal_wait)}

    def south_wind_kinds(self, seat: int, kinds: list[str]) -> dict:
        f = self.deal_flow
        if not f or str(f.get("kind")) != "south_wind" or int(f.get("seat", -1)) != int(seat):
            raise RuleError("现在不是南风的选牌阶段")
        if str(f.get("stage")) != "kinds":
            raise RuleError("已经选过牌种了")
        picks = [str(k) for k in kinds]
        if len(picks) != 2 or len(set(picks)) != 2:
            raise RuleError("要指定两种不同的牌")
        for k in picks:
            if k not in TILE_KINDS:
                raise RuleError(f"没有这种牌：{k}")
        f["kinds"] = picks
        f["stage"] = "hand"
        self.save_flags()
        return {"kinds": picks, "flow": self.deal_flow_view(seat)}

    def south_wind_swap(self, seat: int, hand_tiles: list[str]) -> dict:
        """选两张手牌，按顺序跟下家/对家/上家换「指定的两种牌」，换满两张就结束。"""
        f = self.deal_flow
        if not f or str(f.get("kind")) != "south_wind" or int(f.get("seat", -1)) != int(seat):
            raise RuleError("现在不是南风的换牌阶段")
        if str(f.get("stage")) != "hand":
            raise RuleError("还没指定牌种")
        picks = [str(t) for t in hand_tiles]
        if len(picks) != 2:
            raise RuleError("要选两张手牌")
        rows = self.db._rows(
            "SELECT wall_seq, tile, is_drawn FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, int(seat)))
        pool: dict[str, list[dict]] = {}
        for r in rows:
            pool.setdefault(str(r["tile"]), []).append(dict(r))
        mine: list[dict] = []
        for t in picks:
            if not pool.get(t):
                raise RuleError(f"手里没有 {t}")
            mine.append(pool[t].pop(0))
        random.shuffle(mine)

        had_drawn = next((int(r["wall_seq"]) for r in rows if int(r["is_drawn"] or 0)), None)
        kinds = set(str(x) for x in (f.get("kinds") or []))
        log: list[dict] = []
        incoming: list[int] = []

        def next_slot(s: int) -> int:
            return int(self.db._one(
                "SELECT COALESCE(MAX(slot), -1) + 1 FROM round_hands "
                "WHERE round_id=? AND seat=?", (self.round_id, s)) or 0)

        with self.db.tx():
            for opp in [int(x) for x in f["targets"]]:
                if not mine:
                    break
                opp_rows = self.db._rows(
                    "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
                    "ORDER BY slot", (self.round_id, opp))
                matches = [dict(r) for r in opp_rows if str(r["tile"]) in kinds]
                if not matches:
                    continue
                random.shuffle(matches)
                while mine and matches:
                    my = mine.pop()
                    their = matches.pop()
                    # 我的手牌 → 对家
                    self.db.conn.execute(
                        "DELETE FROM round_hands WHERE round_id=? AND wall_seq=?",
                        (self.round_id, int(my["wall_seq"])))
                    self.db.conn.execute(
                        "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
                        "VALUES(?,?,?,?,?,0)",
                        (self.round_id, opp, int(my["wall_seq"]), str(my["tile"]),
                         next_slot(opp)))
                    # 对家的指定牌 → 我
                    self.db.conn.execute(
                        "DELETE FROM round_hands WHERE round_id=? AND wall_seq=?",
                        (self.round_id, int(their["wall_seq"])))
                    self.db.conn.execute(
                        "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
                        "VALUES(?,?,?,?,?,0)",
                        (self.round_id, int(seat), int(their["wall_seq"]), str(their["tile"]),
                         next_slot(seat)))
                    incoming.append(int(their["wall_seq"]))
                    log.append({"from": opp, "gave": str(my["tile"]),
                                "got": str(their["tile"])})
            # 刚摸的那张被换走了 → 换进来的牌顶上
            if had_drawn is not None and incoming:
                still = self.db._one(
                    "SELECT COUNT(*) FROM round_hands WHERE round_id=? AND seat=? "
                    "AND wall_seq=?", (self.round_id, int(seat), int(had_drawn)))
                if not still:
                    self.db.conn.execute(
                        "UPDATE round_hands SET is_drawn=1 WHERE round_id=? AND wall_seq=?",
                        (self.round_id, int(incoming[-1])))

        self.deal_flow = None
        self.deal_wait.discard(int(seat))
        self.deal_used.add(int(seat))
        self.save_flags()
        self._maybe_close_deal()
        return {"swaps": log, "count": len(log)}

    def _advance_deal_flow(self) -> None:
''')

# 5) deal_action：南风走自己的流程
sub('''        if (int(card), int(skill)) == (4, 1):
            return self._start_deal_swap(seat, int(card), int(skill))
''',
    '''        if (int(card), int(skill)) == (4, 1):
            return self._start_deal_swap(seat, int(card), int(skill))
        if (int(card), int(skill)) == (6, 1):
            return self._start_south_wind(seat, int(card), int(skill))
''')

io.open(P, "w", encoding="utf-8", newline="").write(t)
print("game.py ok")

# ── api_cli ───────────────────────────────────────────────────
P = "api_cli.py"
t = io.open(P, encoding="utf-8").read()
sub('''def op_card05_nuki(db: DB, req: dict) -> dict:
''',
    '''def op_south_wind_kinds(db: DB, req: dict) -> dict:
    """Card06 Skill1「南风」：指定两种牌。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.south_wind_kinds(seat, [str(k) for k in (req.get("kinds") or [])])
    return {"ok": True, "south_wind": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_south_wind_swap(db: DB, req: dict) -> dict:
    """Card06 Skill1「南风」：选两张手牌，跟三家按顺序换。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.south_wind_swap(seat, [str(t) for t in (req.get("tiles") or [])])
    return {"ok": True, "south_wind": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_card05_nuki(db: DB, req: dict) -> dict:
''')
sub('''    "card05_nuki": op_card05_nuki,
''',
    '''    "card05_nuki": op_card05_nuki,
    "south_wind_kinds": op_south_wind_kinds,
    "south_wind_swap": op_south_wind_swap,
''')
io.open(P, "w", encoding="utf-8", newline="").write(t)
print("api_cli.py ok")
