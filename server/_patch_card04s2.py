# -*- coding: utf-8 -*-
"""Card04 Skill2「自风」：风神发动后自动生效，别人摸到我的自风就换牌。"""
import io

P = "skills.py"
t = io.open(P, encoding="utf-8").read()


def sub(old, new):
    global t
    assert old in t, "NOT FOUND: " + old[:100]
    t = t.replace(old, new, 1)


sub('''    (4, 1): {"name": "风神", "kind": "deal_swap", "timing": "deal"},
}''',
    '''    (4, 1): {"name": "风神", "kind": "deal_swap", "timing": "deal"},
    (4, 2): {"name": "自风", "kind": "self_wind", "timing": "draw"},
}''')
sub('''    (4, 1): "deal",
}''',
    '''    (4, 1): "deal", (4, 2): "draw",
}''')
io.open(P, "w", encoding="utf-8", newline="").write(t)
print("skills.py ok")

P = "game.py"
t = io.open(P, encoding="utf-8").read()

# 状态变量
sub('''        # 风神（Card04 Skill1）：配牌时依次跟下家/对家/上家换风牌，中途记在这里
        self.deal_flow: dict | None = None
''',
    '''        # 风神（Card04 Skill1）：配牌时依次跟下家/对家/上家换风牌，中途记在这里
        self.deal_flow: dict | None = None
        # 自风（Card04 Skill2）：发动过风神后自动生效；别人摸到我的自风 → 换一张手牌
        self.self_wind: set[int] = set()
        self.wind_swap: dict | None = None
''')

sub('''        df = f.get("deal_flow")
        self.deal_flow = df if isinstance(df, dict) and df else None
''',
    '''        df = f.get("deal_flow")
        self.deal_flow = df if isinstance(df, dict) and df else None
        self.self_wind = {int(x) for x in (f.get("self_wind") or [])
                          if int(x) in range(4)}
        ws = f.get("wind_swap")
        self.wind_swap = ws if isinstance(ws, dict) and ws else None
''')

sub('''            "deal_flow": self.deal_flow,
''',
    '''            "deal_flow": self.deal_flow,
            "self_wind": sorted(self.self_wind),
            "wind_swap": self.wind_swap,
''')

# 风神发动 → 自风自动生效
sub('''        self.note_skill(seat, card, skill)          # 全场播报 + 人物卡翻明
        self._advance_deal_flow()
''',
    '''        self.self_wind.add(int(seat))               # 自风：风神发动后自动生效
        self.note_skill(seat, card, skill)          # 全场播报 + 人物卡翻明
        self._advance_deal_flow()
''')

# 摸牌触发：普通摸牌
sub('''        self.phase = "discard"
        return self._event("draw", {"seat": seat, "tile": got, "board": moved})
''',
    '''        owner = self._self_wind_owner(seat, got)
        if owner is not None:
            self.wind_swap = {"owner": int(owner), "from": int(seat), "tile": got}
            self.phase = "wind_swap"
            return self._event("draw", {"seat": seat, "tile": got, "board": moved,
                                        "self_wind": owner})
        self.phase = "discard"
        return self._event("draw", {"seat": seat, "tile": got, "board": moved})
''')

# 摸牌触发：岭上
sub('''        self.last_was_rinshan = True
        self.phase = "discard"
        ev = self._event(kind, {"seat": seat, "tile": tile, "drawn": got,
                                "rinshan": True})
''',
    '''        self.last_was_rinshan = True
        self.phase = "discard"
        owner = self._self_wind_owner(seat, got)
        if owner is not None:
            self.wind_swap = {"owner": int(owner), "from": int(seat), "tile": got}
            self.phase = "wind_swap"
        ev = self._event(kind, {"seat": seat, "tile": tile, "drawn": got,
                                "rinshan": True})
''')

# 自风：判定 / 交换 / 跳过 / 视图
sub('''    # ── 风神（Card04 Skill1）────────────────────────────────────
''',
    '''    # ── 自风（Card04 Skill2）────────────────────────────────────
    def seat_wind(self, seat: int) -> str:
        """这个座位的自风（庄家=东，逆时针 南西北）。"""
        return ["dong", "nan", "xi", "bei"][(int(seat) - self.dealer) % 4]

    def _self_wind_owner(self, drawer: int, tile: str) -> int | None:
        """drawer 摸到 tile：有没有人要发动「自风」？"""
        t = str(tile)
        if t not in self.WINDS:
            return None
        for owner in sorted(self.self_wind):
            if int(owner) == int(drawer):
                continue
            if self.is_riichi(owner):
                continue                       # 立直后失效
            if self.seat_wind(owner) == t:
                return int(owner)
        return None

    def wind_swap_view(self) -> dict | None:
        w = self.wind_swap
        if not w:
            return None
        return {"owner": int(w["owner"]), "from": int(w["from"]),
                "tile": str(w["tile"])}

    def wind_swap_apply(self, seat: int, tile: str) -> dict:
        """自风交换：我选一张手牌，跟对方刚摸到的自风换。"""
        w = self.wind_swap
        if self.phase != "wind_swap" or not w:
            raise RuleError("现在没有要换的自风")
        if int(w.get("owner", -1)) != int(seat):
            raise RuleError("这不是你的自风交换")
        drawer = int(w["from"])
        wind = str(w["tile"])

        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, seat))
        pick = next((r for r in rows if str(r["tile"]) == str(tile)), None)
        if pick is None:
            raise RuleError(f"手里没有 {tile}")

        wrow = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? "
            "AND tile=? ORDER BY is_drawn DESC, wall_seq DESC LIMIT 1",
            (self.round_id, drawer, wind))
        if wrow is None:
            raise RuleError("摸到的那张自风已经不在对方手里了")

        def next_slot(s: int) -> int:
            return int(self.db._one(
                "SELECT COALESCE(MAX(slot), -1) + 1 FROM round_hands "
                "WHERE round_id=? AND seat=?", (self.round_id, s)) or 0)

        with self.db.tx():
            # 我的手牌 → 对方（算他刚摸到的那张）
            self.db.conn.execute(
                "DELETE FROM round_hands WHERE round_id=? AND wall_seq=?",
                (self.round_id, int(pick["wall_seq"])))
            self.db.conn.execute(
                "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
                "VALUES(?,?,?,?,?,1)",
                (self.round_id, drawer, int(pick["wall_seq"]), str(pick["tile"]),
                 next_slot(drawer)))
            # 对方摸到的自风 → 我
            self.db.conn.execute(
                "DELETE FROM round_hands WHERE round_id=? AND wall_seq=?",
                (self.round_id, int(wrow["wall_seq"])))
            self.db.conn.execute(
                "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
                "VALUES(?,?,?,?,?,0)",
                (self.round_id, seat, int(wrow["wall_seq"]), wind, next_slot(seat)))

        self.wind_swap = None
        self.phase = "discard"
        self.turn = drawer
        self.save_flags()
        return {"tile": str(tile), "got": wind, "from": drawer}

    def wind_swap_pass(self) -> dict:
        """没人操作时兜底：不换，摸牌的人继续打。"""
        w = self.wind_swap
        if not w:
            return self._event("claim_none", {})
        drawer = int(w["from"])
        self.wind_swap = None
        self.phase = "discard"
        self.turn = drawer
        self.save_flags()
        return {"event": "wind_swap_pass", "seat": drawer, "tile": str(w["tile"])}

    # ── 风神（Card04 Skill1）────────────────────────────────────
''')

# state_for
sub('''                       # 风神：正在跟谁换、还差几张
                       "deal_flow": self.deal_flow_view(seat),
''',
    '''                       # 风神：正在跟谁换、还差几张
                       "deal_flow": self.deal_flow_view(seat),
                       # 自风：风神发动后自动生效；现在是不是在等我和别人换牌
                       "self_wind": seat in self.self_wind,
                       "wind_swap": self.wind_swap_view(),
''')

io.open(P, "w", encoding="utf-8", newline="").write(t)
print("game.py ok")

# ── api_cli ───────────────────────────────────────────────────
P = "api_cli.py"
t = io.open(P, encoding="utf-8").read()
sub('''def op_deal_swap(db: DB, req: dict) -> dict:
''',
    '''def op_wind_swap(db: DB, req: dict) -> dict:
    """Card04 Skill2「自风」：用我的一张手牌，换对方刚摸到的自风。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    r = g.wind_swap_apply(seat, str(req.get("tile", "")))
    return {"ok": True, "wind_swap": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_deal_swap(db: DB, req: dict) -> dict:
''')
sub('''    "deal_swap": op_deal_swap,
''',
    '''    "deal_swap": op_deal_swap,
    "wind_swap": op_wind_swap,
''')

sub('''        elif g.phase == "deal_skill":
''',
    '''        elif g.phase == "wind_swap":
            w = getattr(g, "wind_swap", None) or {}
            owner = int(w.get("owner", -1))
            if owner == seat:
                ev = None                                  # 等我自己选牌
            elif owner not in humans and auto:
                ev = g.wind_swap_pass()                    # 没人在操作 → 兜底跳过
            else:
                ev = None
        elif g.phase == "deal_skill":
''')
io.open(P, "w", encoding="utf-8", newline="").write(t)
print("api_cli.py ok")
