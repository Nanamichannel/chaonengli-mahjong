# -*- coding: utf-8 -*-
"""配牌技能窗口 + 技能播报 + 人物卡翻明。"""
import io

P = "game.py"
t = io.open(P, encoding="utf-8").read()


def sub(old, new):
    global t
    assert old in t, "NOT FOUND: " + old[:110]
    t = t.replace(old, new, 1)


# ── 1. 状态变量 ────────────────────────────────────────────────
sub('''        self.press_used: set[int] = set()
        self.press_win: set[int] = set()
        self._sees_cache: dict[int, bool] = {}
''',
    '''        self.press_used: set[int] = set()
        self.press_win: set[int] = set()
        self._sees_cache: dict[int, bool] = {}
        # 配牌阶段发动的技能：庄家跳完牌之后，这些座位要先「发动 / 跳过」
        self.deal_wait: set[int] = set()
        self.deal_used: set[int] = set()
        self.deal_queue: list[dict] = []       # 发动顺序（按这个顺序结算）
        # 技能播报（全场）：客户端看到 id 变了就弹字幕
        self.broadcast: dict | None = None
        self.broadcast_id = 0
        # 人物卡翻明（第一次发动技能后，别人视角永久翻面）
        self._revealed_cache: set[int] = set()
        self._owns_cache: dict[tuple[int, int], bool] = {}
''')

# ── 2. load_flags / save_flags ────────────────────────────────
sub('''        self.press_win = {int(x) for x in (f.get("press_win") or [])
                          if int(x) in range(4)}
        self._sees_cache = {}
''',
    '''        self.press_win = {int(x) for x in (f.get("press_win") or [])
                          if int(x) in range(4)}
        self._sees_cache = {}
        self._owns_cache = {}
        self.deal_wait = {int(x) for x in (f.get("deal_wait") or [])
                          if int(x) in range(4)}
        self.deal_used = {int(x) for x in (f.get("deal_used") or [])
                          if int(x) in range(4)}
        self.deal_queue = list(f.get("deal_queue") or [])
        b = f.get("broadcast")
        self.broadcast = b if isinstance(b, dict) and b else None
        self.broadcast_id = int(f.get("broadcast_id", 0) or 0)
        self._revealed_cache = self._load_revealed()
''')

sub('''            "press_used": sorted(self.press_used),
            "press_win": sorted(self.press_win),
''',
    '''            "press_used": sorted(self.press_used),
            "press_win": sorted(self.press_win),
            "deal_wait": sorted(self.deal_wait),
            "deal_used": sorted(self.deal_used),
            "deal_queue": self.deal_queue,
            "broadcast": self.broadcast,
            "broadcast_id": self.broadcast_id,
''')

# ── 3. 配牌阶段结束 → 开窗口 ─────────────────────────────────
sub('''        self.round_phase = "play"                             # 配牌 → 切牌
        self.turn = self.dealer                               # 轮到庄家打牌
        self.phase = "discard"
        return self.reveal_dora()
''',
    '''        self.round_phase = "play"                             # 配牌 → 切牌
        self.turn = self.dealer                               # 轮到庄家打牌
        self.phase = "discard"
        # 有「配牌阶段发动」技能的人要先决定（发动 / 跳过），之后庄家才能切牌
        self.deal_wait = set()
        self.deal_used = set()
        self.deal_queue = []
        self._open_deal_window()
        return self.reveal_dora()
''')

# ── 4. 配牌窗口 / 播报 / 翻明 ────────────────────────────────
sub('''    # ── 压制（Card03 Skill2）──────────────────────────────────
''',
    '''    # ── 配牌阶段技能窗口（Card03 Skill1 等）────────────────────
    def _deal_skill_options(self, seat: int) -> list[dict]:
        """这个座位在配牌阶段能发动的技能。"""
        out = []
        for card, skill in skills.deal_skills():
            key = (int(seat), int(card))
            if key not in self._owns_cache:
                self._owns_cache[key] = skills.owns_card(
                    self.db, self, int(seat), int(card), strict=True)
            if not self._owns_cache[key]:
                continue
            out.append({"card": int(card), "skill": int(skill),
                        "name": skills.info(card, skill).get("name", ""),
                        "timing": "deal"})
        return out

    def _open_deal_window(self) -> None:
        """庄家跳完牌：把「有配牌技能的人」列出来，等他们发动或跳过。"""
        self.deal_wait = set()
        for s in range(4):
            if self._deal_skill_options(s):
                self.deal_wait.add(s)
        if self.deal_wait:
            self.phase = "deal_skill"

    def deal_action(self, seat: int, action: str,
                    card: int = 0, skill: int = 0) -> dict:
        """配牌窗口里某一家做出选择：发动技能（use）或跳过（skip）。"""
        if self.phase != "deal_skill":
            raise RuleError("现在不是配牌技能阶段")
        if seat not in self.deal_wait:
            return {"ok": True, "done": True, "pending": sorted(self.deal_wait)}
        if action == "skip":
            self.deal_wait.discard(seat)
            self.deal_used.add(seat)
            self.save_flags()
            self._maybe_close_deal()
            return {"ok": True, "skipped": True, "pending": sorted(self.deal_wait)}
        if action != "use":
            raise RuleError("不认识的配牌动作")
        opts = self._deal_skill_options(seat)
        if not any(int(o["card"]) == int(card) and int(o["skill"]) == int(skill)
                   for o in opts):
            raise RuleError("这个技能不是配牌阶段发动的")
        r = self.arm_skill(seat, int(card), int(skill))
        if not r.get("armed", False):
            r["pending"] = sorted(self.deal_wait)     # 没发动成功就还等他
            return r
        # 「按发动先后顺序结算」：每个技能都是即时生效的，这里按调用顺序记账
        self.deal_queue.append({"seat": seat, "card": int(card), "skill": int(skill)})
        self.deal_wait.discard(seat)
        self.deal_used.add(seat)
        self.save_flags()
        self._maybe_close_deal()
        return {**r, "pending": sorted(self.deal_wait)}

    def _maybe_close_deal(self) -> None:
        if self.phase == "deal_skill" and not self.deal_wait:
            self.phase = "discard"                    # 所有人都发动完/跳过 → 庄家切牌
            self.turn = self.dealer
            self.save_flags()

    # ── 技能播报 + 人物卡翻明 ──────────────────────────────────
    def _load_revealed(self) -> set[int]:
        row = self.db._row("SELECT value FROM meta WHERE key='revealed_seats'")
        if not row:
            return set()
        try:
            return {int(x) for x in (json.loads(row["value"]) or [])
                    if int(x) in range(4)}
        except (ValueError, TypeError):
            return set()

    def note_skill(self, seat: int, card: int, skill: int) -> None:
        """技能发动：全场播报 + 这个人的人物卡永久翻明。"""
        name = skills.info(card, skill).get("name", "")
        self.broadcast_id += 1
        wind = ["dong", "nan", "xi", "bei"][(int(seat) - self.dealer) % 4]
        self.broadcast = {"id": self.broadcast_id, "seat": int(seat),
                          "wind": wind, "card": int(card), "skill": int(skill),
                          "name": name}
        if seat not in self._revealed_cache:
            self._revealed_cache.add(int(seat))
            with self.db.tx():
                self.db.conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES('revealed_seats', ?)",
                    (json.dumps(sorted(self._revealed_cache)),))
        self.save_flags()

    # ── 压制（Card03 Skill2）──────────────────────────────────
''')

# ── 5. 自信：配牌窗口也算「配牌阶段」───────────────────────────
sub('''        if self.phase == "ended" or self.round_phase != "deal":
            return {"ok": True, "armed": False,
                    "reason": "「%s」只能在配牌阶段发动" % name}
''',
    '''        if (self.phase == "ended"
                or (self.round_phase != "deal" and self.phase != "deal_skill")):
            return {"ok": True, "armed": False,
                    "reason": "「%s」只能在配牌阶段发动" % name}
''')

# ── 6. 发动成功的几个入口都播报 + 翻明 ────────────────────────
# 6.1 arm_skill（Card01 Skill1 / Card03 Skill1）
sub('''        self.armed_skill = {"seat": seat, "card": int(card), "skill": int(skill),
                            "discard": plan["discard"], "win": plan["win"]}
        self.save_flags()
''',
    '''        self.armed_skill = {"seat": seat, "card": int(card), "skill": int(skill),
                            "discard": plan["discard"], "win": plan["win"]}
        self.note_skill(seat, card, skill)
        self.save_flags()
''')

# 6.2 Card02 Skill1 画板
sub('''        self.boards[seat] = {"tiles": picks, "delivered": [], "pending": []}
        self.mark_skill_used(seat, 2, 1)
        self.save_flags()
''',
    '''        self.boards[seat] = {"tiles": picks, "delivered": [], "pending": []}
        self.mark_skill_used(seat, 2, 1)
        self.note_skill(seat, 2, 1)
        self.save_flags()
''')

# 6.3 Card02 Skill2 换牌
sub('''        self.mark_skill_used(seat, 2, 2)
        self.swaps = self.swaps or {}
''',
    '''        self.mark_skill_used(seat, 2, 2)
        self.note_skill(seat, 2, 2)
        self.swaps = self.swaps or {}
''')

# 6.4 Card03 Skill2 压制
sub('''        if mode == "once":
            self.press_used.add(seat)
        self.press_win.add(seat)               # 换进来的牌就是「刚摸到的」：自摸不算边坎符
        self.save_flags()
''',
    '''        if mode == "once":
            self.press_used.add(seat)
        self.press_win.add(seat)               # 换进来的牌就是「刚摸到的」：自摸不算边坎符
        self.note_skill(seat, 3, 2)
        self.save_flags()
''')

# ── 7. state_for：配牌窗口 / 播报 / 翻明 ──────────────────────
sub('''                       # 压制：一次性那段用过没有 / 暗置牌对我是不是明牌
                       "press_used": seat in self.press_used,
                       "sees_face_down": self.sees_face_down(seat),
''',
    '''                       # 压制：一次性那段用过没有 / 暗置牌对我是不是明牌
                       "press_used": seat in self.press_used,
                       "sees_face_down": self.sees_face_down(seat),
                       # 配牌阶段技能：还有谁没决定 / 我能发动什么
                       "deal_skill": {
                           "pending": (sorted(self.deal_wait)
                                       if self.phase == "deal_skill" else []),
                           "mine": (self._deal_skill_options(seat)
                                    if (self.phase == "deal_skill"
                                        and seat in self.deal_wait) else []),
                       },
                       # 技能播报（全场共用一个 id，客户端只看 id 变没变）
                       "broadcast": self.broadcast,
                       # 已经翻明的人物卡（别人视角不再盖住）
                       "revealed": sorted(self._revealed_cache),
''')

io.open(P, "w", encoding="utf-8", newline="").write(t)
print("game.py ok")
