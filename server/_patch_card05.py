# -*- coding: utf-8 -*-
"""Card05 Skill1「策略」服务端补丁。"""
import io

P = "skills.py"
t = io.open(P, encoding="utf-8").read()


def sub(old, new):
    global t
    assert old in t, "NOT FOUND: " + old[:100]
    t = t.replace(old, new, 1)


sub('''    (4, 2): {"name": "自风", "kind": "self_wind", "timing": "draw"},
}''',
    '''    (4, 2): {"name": "自风", "kind": "self_wind", "timing": "draw"},
    (5, 1): {"name": "策略", "kind": "strategy", "timing": "draw"},
}''')
sub('''    (4, 1): "deal", (4, 2): "draw",
}''',
    '''    (4, 1): "deal", (4, 2): "draw",
    (5, 1): "draw",
}''')
io.open(P, "w", encoding="utf-8", newline="").write(t)
print("skills.py ok")

P = "game.py"
t = io.open(P, encoding="utf-8").read()

# ── 1. 状态变量 ────────────────────────────────────────────────
sub('''        # 自风（Card04 Skill2）：发动过风神后自动生效；别人摸到我的自风 → 换一张手牌
        self.self_wind: set[int] = set()
        self.wind_swap: dict | None = None
''',
    '''        # 自风（Card04 Skill2）：发动过风神后自动生效；别人摸到我的自风 → 换一张手牌
        self.self_wind: set[int] = set()
        self.wind_swap: dict | None = None
        # 策略（Card05 Skill1）
        #   hidden  = 被别人看手牌时盖住的三张（wall_seq）
        #   counter = 「别人害我不能正常摸切」攒的次数，每点换一次额外的摸切
        #   offer   = 由于别人技能导致我手牌变动 → 可以从王牌/弃牌换一张
        #   extra   = 这一回合打完牌后再摸一张（已经用掉 1 点 counter）
        self.card05_hidden: dict[int, list[int]] = {}
        self.card05_counter: dict[int, int] = {}
        self.card05_offer: dict[int, dict] = {}
        self.card05_extra: set[int] = set()
        self.card05_pending_hide: dict[int, int] = {}
        self._c05_cache: dict[int, bool] = {}
''')

# ── 2. flags ──────────────────────────────────────────────────
sub('''        ws = f.get("wind_swap")
        self.wind_swap = ws if isinstance(ws, dict) and ws else None
''',
    '''        ws = f.get("wind_swap")
        self.wind_swap = ws if isinstance(ws, dict) and ws else None
        self.card05_hidden = {}
        for k, v in (f.get("card05_hidden") or {}).items():
            try:
                self.card05_hidden[int(k)] = [int(x) for x in (v or [])]
            except (TypeError, ValueError):
                pass
        self.card05_counter = {}
        for k, v in (f.get("card05_counter") or {}).items():
            try:
                self.card05_counter[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
        self.card05_offer = {}
        for k, v in (f.get("card05_offer") or {}).items():
            try:
                if isinstance(v, dict):
                    self.card05_offer[int(k)] = v
            except (TypeError, ValueError):
                pass
        self.card05_extra = {int(x) for x in (f.get("card05_extra") or [])
                             if int(x) in range(4)}
        self.card05_pending_hide = {}
        for k, v in (f.get("card05_pending_hide") or {}).items():
            try:
                self.card05_pending_hide[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
        self._c05_cache = {}
''')

sub('''            "wind_swap": self.wind_swap,
''',
    '''            "wind_swap": self.wind_swap,
            "card05_hidden": {str(k): v for k, v in self.card05_hidden.items()},
            "card05_counter": {str(k): v for k, v in self.card05_counter.items()},
            "card05_offer": {str(k): v for k, v in self.card05_offer.items()},
            "card05_extra": sorted(self.card05_extra),
            "card05_pending_hide": {str(k): v for k, v in self.card05_pending_hide.items()},
''')

# ── 3. 策略核心 ───────────────────────────────────────────────
sub('''    # ── 自风（Card04 Skill2）────────────────────────────────────
''',
    '''    # ── 策略（Card05 Skill1）────────────────────────────────────
    def owns_card05(self, seat: int) -> bool:
        if int(seat) not in self._c05_cache:
            self._c05_cache[int(seat)] = skills.owns_card(
                self.db, self, int(seat), 5, strict=True)
        return self._c05_cache[int(seat)]

    def card05_interfere(self, affected: int, by: int, reason: str) -> None:
        """别人的技能害我手牌变了 / 不能正常摸切：计数器 +1，并给他一次换牌机会。"""
        if int(affected) == int(by) or not self.owns_card05(affected):
            return
        a = int(affected)
        self.card05_counter[a] = int(self.card05_counter.get(a, 0)) + 1
        self.card05_offer[a] = {"by": int(by), "reason": str(reason)}
        self.save_flags()

    def card05_extra_activate(self, seat: int) -> dict:
        """花 1 点计数：这一回合切牌之后立刻再摸一张、再切一张。"""
        if self.phase != "discard" or int(seat) != int(self.turn):
            raise RuleError("现在不是你的出牌回合")
        if self.drawn_tile(seat) is None:
            raise RuleError("摸牌之后才能发动")
        if int(self.card05_counter.get(seat, 0)) <= 0:
            raise RuleError("计数器是 0，还不能发动")
        if seat in self.card05_extra:
            raise RuleError("这一回合已经发动过了")
        self.card05_counter[seat] = int(self.card05_counter.get(seat, 0)) - 1
        self.card05_extra.add(int(seat))
        self.save_flags()
        return {"extra": True, "counter": int(self.card05_counter[seat])}

    def _extra_draw(self, seat: int) -> dict:
        """额外的摸切回合：直接从牌山摸（不受技能影响），然后继续打牌。"""
        info = self._draw_next_info(seat)
        if info is None:
            return self._ryuukyoku("exhaustive")
        self.phase = "discard"
        self.turn = int(seat)
        self.save_flags()
        return self._event("draw", {"seat": int(seat), "tile": info["tile"], "extra": True})

    def _advance_after_discard(self, seat: int) -> None:
        """一张牌打完、没人鸣：如果用了「策略」的额外摸切，就自己再摸一张。"""
        if int(seat) in self.card05_extra:
            self.card05_extra.discard(int(seat))
            self.turn = int(seat)
            self.phase = "draw"
            self.save_flags()
            self._extra_draw(int(seat))
            return
        self._next_player()

    def card05_swap(self, seat: int, hand_tile: str, kind: str,
                    stack: int = 0, half: str = "top", river_seq: int = -1) -> dict:
        """从王牌 / 弃牌里挑一张，和自己的一张手牌交换（明暗状态跟着位置走）。"""
        if not self.owns_card05(seat):
            raise RuleError("这张不是你这一局的人物卡")
        if seat not in self.card05_offer:
            raise RuleError("现在没有可以交换的牌")
        if self.phase != "discard" or int(seat) != int(self.turn):
            raise RuleError("现在不是你的出牌回合")
        tile = str(hand_tile)
        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, seat))
        pick = next((r for r in rows if str(r["tile"]) == tile), None)
        if pick is None:
            raise RuleError(f"手里没有 {tile}")
        hseq = int(pick["wall_seq"])

        target_tile = ""
        tseq = -1
        down = False
        if kind == "dead":
            n = self.wall_first_stack()
            k = wallmodel.wrap_stack(int(stack))
            if not wallmodel.is_dead_stack(k, n):
                raise RuleError("这墩不是王牌")
            a, b = wallmodel.tile_nos_of_stack(k)
            no = a if str(half) == "top" else b
            tseq = wallmodel.seq_of_tile(no)
            row = self.db._row(
                "SELECT tile FROM round_wall WHERE round_id=? AND seq=? AND dealt_to IS NULL",
                (self.round_id, tseq))
            if row is None:
                raise RuleError("这张王牌已经摸走了")
            target_tile = str(row["tile"])
            down = True                                  # 王牌永远是暗置
        elif kind == "river":
            row = self.db._row(
                "SELECT seq, wall_seq, tile, called, is_riichi_tile, face_down "
                "FROM round_discards WHERE round_id=? AND seq=?",
                (self.round_id, int(river_seq)))
            if row is None:
                raise RuleError("这张牌不在牌河里")
            if int(row["called"] or 0):
                raise RuleError("已经被吃碰杠拿走的牌不能换")
            if int(row["is_riichi_tile"] or 0):
                raise RuleError("立直宣言牌不能换")
            tseq = int(row["wall_seq"])
            target_tile = str(row["tile"])
            down = bool(int(row["face_down"] or 0))
        else:
            raise RuleError("不认识的交换目标")

        with self.db.tx():
            # 位置上的牌 → 换成我的手牌（明暗保持这个位置原来的状态）
            self.db.conn.execute(
                "UPDATE round_wall SET tile=? WHERE round_id=? AND seq=?",
                (tile, self.round_id, tseq))
            if kind == "river":
                self.db.conn.execute(
                    "UPDATE round_discards SET tile=? WHERE round_id=? AND seq=?",
                    (tile, self.round_id, int(river_seq)))
            # 我的手牌 → 换成那个位置上的牌
            self.db.conn.execute(
                "UPDATE round_wall SET tile=? WHERE round_id=? AND seq=?",
                (target_tile, self.round_id, hseq))
            self.db.conn.execute(
                "UPDATE round_hands SET tile=? WHERE round_id=? AND wall_seq=?",
                (target_tile, self.round_id, hseq))
        self.card05_offer.pop(seat, None)
        self.save_flags()
        return {"hand": tile, "got": target_tile, "kind": kind,
                "face_down": down, "stack": int(stack), "half": str(half)}

    def card05_cancel(self, seat: int) -> dict:
        self.card05_offer.pop(int(seat), None)
        self.save_flags()
        return {"cancelled": True}

    def card05_view_hand(self, viewer: int, target: int) -> dict:
        """别人要看 target 的手牌：持有策略的人先挑三张盖住，这次就看不到。"""
        if target < 0 or target > 3 or int(viewer) == int(target):
            raise RuleError("对象玩家不对")
        if self.owns_card05(target) and not self.card05_hidden.get(target) \\
                and target not in self.card05_pending_hide:
            self.card05_pending_hide[int(target)] = int(viewer)
            self.save_flags()
            return {"blocked": True, "target": int(target)}
        hidden = set(int(x) for x in (self.card05_hidden.get(target) or []))
        hand = [r["tile"] for r in self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, target))
            if int(r["wall_seq"]) not in hidden]
        return {"blocked": False, "target": int(target), "hand": hand}

    def card05_hide(self, seat: int, tiles: list[str]) -> dict:
        """被看手牌时盖住最多三张。"""
        if int(seat) not in self.card05_pending_hide:
            raise RuleError("现在没有要看手牌的人")
        picks = [str(t) for t in tiles]
        if len(picks) < 1 or len(picks) > 3:
            raise RuleError("最多盖三张")
        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, seat))
        pool: dict[str, list[int]] = {}
        for r in rows:
            pool.setdefault(str(r["tile"]), []).append(int(r["wall_seq"]))
        seqs: list[int] = []
        for t in picks:
            if not pool.get(t):
                raise RuleError(f"手里没有 {t}")
            seqs.append(pool[t].pop(0))
        self.card05_hidden[int(seat)] = seqs
        self.card05_pending_hide.pop(int(seat), None)
        self.save_flags()
        return {"hidden": len(seqs)}

    # ── 自风（Card04 Skill2）────────────────────────────────────
''')

# ── 4. 画板转移钩子 ─────────────────────────────────────────
sub('''            b.setdefault("delivered", []).append(tile)
            b.setdefault("pending", []).append({"tile": tile, "seq": seq})
            self.save_flags()
            return {"owner": owner, "tile": tile}
''',
    '''            b.setdefault("delivered", []).append(tile)
            b.setdefault("pending", []).append({"tile": tile, "seq": seq})
            self.card05_interfere(seat, owner, "画板")     # 策略：别人害我重摸
            self.save_flags()
            return {"owner": owner, "tile": tile}
''')

# ── 5. 打牌后：额外摸切 ─────────────────────────────────────
sub('''        self.pending_kuikae = None
        self.last_was_rinshan = False                        # 牌都打出去了，岭上开花的机会就没了
''',
    '''        self.pending_kuikae = None
        self.card05_offer.pop(seat, None)                    # 打牌了，换牌机会作废
        self.last_was_rinshan = False                        # 牌都打出去了，岭上开花的机会就没了
''')

sub('''        if not opts:
            self._next_player()
            return
''',
    '''        if not opts:
            self._advance_after_discard(from_seat)
            return
''')

sub('''        if p.get("resume") is not None:
            # 这个窗口不是「打牌」引起的（是换牌把暗置牌放进牌河）
            # → 没人荣和就回到换牌的人继续打牌，不能跳到他下家
            self.turn = int(p["resume"])
            self.phase = "discard"
            return self._event("claim_none", {})
        self._next_player()
        return self._event("claim_none", {})
''',
    '''        if p.get("resume") is not None:
            # 这个窗口不是「打牌」引起的（是换牌把暗置牌放进牌河）
            # → 没人荣和就回到换牌的人继续打牌，不能跳到他下家
            self.turn = int(p["resume"])
            self.phase = "discard"
            return self._event("claim_none", {})
        self._advance_after_discard(int(p["from"]))
        return self._event("claim_none", {})
''')

# 有人真正鸣牌 → 额外摸切作废
sub('''        if ron_seats:
            take = ron_seats if self.rules.get("multi_ron") else ron_seats[:1]
''',
    '''        if ron_seats:
            self.card05_extra.discard(int(p["from"]))
            take = ron_seats if self.rules.get("multi_ron") else ron_seats[:1]
''')
sub('''        if best:
            _, s, a = best
''',
    '''        if best:
            self.card05_extra.discard(int(p["from"]))
            _, s, a = best
''')

# ── 6. state_for ─────────────────────────────────────────────
sub('''                       # 自风：风神发动后自动生效；现在是不是在等我和别人换牌
                       "self_wind": seat in self.self_wind,
                       "wind_swap": self.wind_swap_view(),
''',
    '''                       # 自风：风神发动后自动生效；现在是不是在等我和别人换牌
                       "self_wind": seat in self.self_wind,
                       "wind_swap": self.wind_swap_view(),
                       # 策略：剩余次数 / 换牌机会 / 额外摸切是否已挂上 / 是否要我盖牌
                       "card05": {
                           "counter": int(self.card05_counter.get(seat, 0)),
                           "offer": self.card05_offer.get(seat),
                           "extra": seat in self.card05_extra,
                           "hide_request": seat in self.card05_pending_hide,
                           "hidden": len(self.card05_hidden.get(seat) or []),
                       },
''')

io.open(P, "w", encoding="utf-8", newline="").write(t)
print("game.py ok")
