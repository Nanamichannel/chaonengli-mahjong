# -*- coding: utf-8 -*-
"""Card04 Skill1「风神」：配牌时依次与下家/对家/上家交换所有风牌。"""
import io

P = "skills.py"
t = io.open(P, encoding="utf-8").read()


def sub(old, new):
    global t
    assert old in t, "NOT FOUND(skills): " + old[:100]
    t = t.replace(old, new, 1)


sub('''    (3, 2): {"name": "压制", "kind": "river_swap", "timing": "draw"},
}''',
    '''    (3, 2): {"name": "压制", "kind": "river_swap", "timing": "draw"},
    (4, 1): {"name": "风神", "kind": "deal_swap", "timing": "deal"},
}''')
sub('''    (3, 1): "deal", (3, 2): "draw",
}''',
    '''    (3, 1): "deal", (3, 2): "draw",
    (4, 1): "deal",
}''')
io.open(P, "w", encoding="utf-8", newline="").write(t)
print("skills.py ok")

# ── game.py ───────────────────────────────────────────────────
P = "game.py"
t = io.open(P, encoding="utf-8").read()

sub('''        # 配牌阶段发动的技能：庄家跳完牌之后，这些座位要先「发动 / 跳过」
''',
    '''        # 风神（Card04 Skill1）：配牌时依次跟下家/对家/上家换风牌，中途记在这里
        self.deal_flow: dict | None = None
        # 配牌阶段发动的技能：庄家跳完牌之后，这些座位要先「发动 / 跳过」
''')

sub('''        self.deal_queue = list(f.get("deal_queue") or [])
''',
    '''        self.deal_queue = list(f.get("deal_queue") or [])
        df = f.get("deal_flow")
        self.deal_flow = df if isinstance(df, dict) and df else None
''')

sub('''            "deal_queue": self.deal_queue,
''',
    '''            "deal_queue": self.deal_queue,
            "deal_flow": self.deal_flow,
''')

# 风神：启动 / 推进一步 / 收尾
sub('''    def _maybe_close_deal(self) -> None:
''',
    '''    # ── 风神（Card04 Skill1）────────────────────────────────────
    WINDS = ("dong", "nan", "xi", "bei")

    def _winds_of(self, seat: int) -> list[dict]:
        """某家手里的风牌（东南西北）。"""
        return [r for r in self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY slot", (self.round_id, seat))
            if str(r["tile"]) in self.WINDS]

    def _start_deal_swap(self, seat: int, card: int, skill: int) -> dict:
        """点「风神」：排好下家/对家/上家的顺序，选中第一个有风牌的。"""
        self.deal_flow = {
            "seat": int(seat), "card": int(card), "skill": int(skill),
            "stage": 0, "n": 0, "target": -1,
            "targets": [(int(seat) + 1) % 4, (int(seat) + 2) % 4, (int(seat) + 3) % 4],
        }
        self.note_skill(seat, card, skill)          # 全场播报 + 人物卡翻明
        self._advance_deal_flow()
        self.save_flags()
        return {"ok": True, "armed": True, "card": int(card), "skill": int(skill),
                "skill_name": skills.info(card, skill).get("name", ""),
                "kind": "deal_swap", "flow": self.deal_flow_view(seat),
                "pending": sorted(self.deal_wait)}

    def _advance_deal_flow(self) -> None:
        """跳到下一个「手里有风牌」的对手；三家都换完就收尾。"""
        f = self.deal_flow
        if not f:
            return
        while int(f["stage"]) < len(f["targets"]):
            target = int(f["targets"][int(f["stage"])])
            n = len(self._winds_of(target))
            if n > 0:
                f["n"] = n
                f["target"] = target
                return
            f["stage"] = int(f["stage"]) + 1
        self._finish_deal_flow()

    def _finish_deal_flow(self) -> None:
        f = self.deal_flow
        self.deal_flow = None
        if f:
            s = int(f["seat"])
            self.deal_wait.discard(s)
            self.deal_used.add(s)
        self.save_flags()
        self._maybe_close_deal()

    def deal_flow_view(self, seat: int) -> dict | None:
        f = self.deal_flow
        if not f or int(f.get("seat", -1)) != int(seat):
            return None
        return {"seat": int(f["seat"]), "stage": int(f["stage"]),
                "target": int(f.get("target", -1)), "n": int(f.get("n", 0)),
                "card": int(f["card"]), "skill": int(f["skill"])}

    def deal_swap(self, seat: int, stage: int, tiles: list[str]) -> dict:
        """风神的一步：把选中的 n 张手牌和 target 手里所有风牌交换。"""
        f = self.deal_flow
        if not f or int(f.get("seat", -1)) != int(seat):
            raise RuleError("现在没有在交换风牌")
        if int(stage) != int(f.get("stage", -1)):
            raise RuleError("阶段对不上，请重新选牌")
        target = int(f["targets"][int(stage)])
        winds = self._winds_of(target)
        picks = [str(t) for t in tiles]
        if len(picks) != len(winds):
            raise RuleError("要选 %d 张手牌" % len(winds))

        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, seat))
        pool: dict[str, list[int]] = {}
        for r in rows:
            pool.setdefault(str(r["tile"]), []).append(int(r["wall_seq"]))
        picked: list[tuple[str, int]] = []
        for tile in picks:
            if not pool.get(tile):
                raise RuleError(f"手里没有 {tile}")
            picked.append((tile, pool[tile].pop(0)))

        had_drawn = self.db._one(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? "
            "AND is_drawn=1 LIMIT 1", (self.round_id, seat))

        def next_slot(s: int) -> int:
            return int(self.db._one(
                "SELECT COALESCE(MAX(slot), -1) + 1 FROM round_hands "
                "WHERE round_id=? AND seat=?", (self.round_id, s)) or 0)

        with self.db.tx():
            # 我的手牌 → 对家
            for tile, wseq in picked:
                self.db.conn.execute(
                    "DELETE FROM round_hands WHERE round_id=? AND wall_seq=?",
                    (self.round_id, wseq))
                self.db.conn.execute(
                    "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
                    "VALUES(?,?,?,?,?,0)",
                    (self.round_id, target, wseq, tile, next_slot(target)))
            # 对家的风牌 → 我
            for r in winds:
                self.db.conn.execute(
                    "DELETE FROM round_hands WHERE round_id=? AND wall_seq=?",
                    (self.round_id, int(r["wall_seq"])))
                self.db.conn.execute(
                    "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
                    "VALUES(?,?,?,?,?,0)",
                    (self.round_id, seat, int(r["wall_seq"]), str(r["tile"]),
                     next_slot(seat)))
            # 庄家刚摸的那张如果被换走了，把换进来的一张标成「刚摸到」
            if had_drawn is not None:
                still = self.db._one(
                    "SELECT COUNT(*) FROM round_hands WHERE round_id=? AND wall_seq=?",
                    (self.round_id, int(had_drawn)))
                if not still:
                    seq = self.db._one(
                        "SELECT MAX(wall_seq) FROM round_hands WHERE round_id=? AND seat=?",
                        (self.round_id, seat))
                    self.db.conn.execute(
                        "UPDATE round_hands SET is_drawn=1 WHERE round_id=? AND wall_seq=?",
                        (self.round_id, int(seq)))

        got = [str(r["tile"]) for r in winds]
        f["stage"] = int(stage) + 1
        self._advance_deal_flow()
        self.save_flags()
        return {"stage": int(stage), "target": target, "count": len(winds),
                "got": got, "next": self.deal_flow_view(seat)}

    def _maybe_close_deal(self) -> None:
''')

# deal_action：风神走自己的流程；流程中不再接受别的决定
sub('''        if self.phase != "deal_skill":
            raise RuleError("现在不是配牌技能阶段")
        if seat not in self.deal_wait:
''',
    '''        if self.phase != "deal_skill":
            raise RuleError("现在不是配牌技能阶段")
        if self.deal_flow and int(self.deal_flow.get("seat", -1)) == int(seat):
            return {"ok": True, "busy": True, "pending": sorted(self.deal_wait),
                    "flow": self.deal_flow_view(seat)}      # 风神还在换牌
        if seat not in self.deal_wait:
''')

sub('''        if not any(int(o["card"]) == int(card) and int(o["skill"]) == int(skill)
                   for o in opts):
            raise RuleError("这个技能不是配牌阶段发动的")
        r = self.arm_skill(seat, int(card), int(skill))
''',
    '''        if not any(int(o["card"]) == int(card) and int(o["skill"]) == int(skill)
                   for o in opts):
            raise RuleError("这个技能不是配牌阶段发动的")
        if (int(card), int(skill)) == (4, 1):
            return self._start_deal_swap(seat, int(card), int(skill))
        r = self.arm_skill(seat, int(card), int(skill))
''')

# state_for：风神进度 + 流程中不重复给「开始」
sub('''                           "mine": (self._deal_skill_options(seat)
                                    if (self.phase == "deal_skill"
                                        and seat in self.deal_wait) else []),
                       },
''',
    '''                           "mine": (self._deal_skill_options(seat)
                                    if (self.phase == "deal_skill"
                                        and seat in self.deal_wait
                                        and not (self.deal_flow
                                                 and int(self.deal_flow.get("seat", -1)) == seat))
                                    else []),
                       },
                       # 风神：正在跟谁换、还差几张
                       "deal_flow": self.deal_flow_view(seat),
''')

io.open(P, "w", encoding="utf-8", newline="").write(t)
print("game.py ok")

# ── api_cli.py ────────────────────────────────────────────────
P = "api_cli.py"
t = io.open(P, encoding="utf-8").read()
sub('''def op_deal_skill(db: DB, req: dict) -> dict:
''',
    '''def op_deal_swap(db: DB, req: dict) -> dict:
    """Card04 Skill1「风神」：这一步选中的手牌 ↔ 对手所有风牌。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    tiles = [str(t) for t in (req.get("tiles") or [])]
    r = g.deal_swap(seat, int(req.get("stage", -1)), tiles)
    return {"ok": True, "deal_swap": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_deal_skill(db: DB, req: dict) -> dict:
''')
sub('''    "deal_skill": op_deal_skill,
''',
    '''    "deal_skill": op_deal_skill,
    "deal_swap": op_deal_swap,
''')
io.open(P, "w", encoding="utf-8", newline="").write(t)
print("api_cli.py ok")
