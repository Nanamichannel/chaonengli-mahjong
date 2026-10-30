# -*- coding: utf-8 -*-
import io

P = "api_cli.py"
t = io.open(P, encoding="utf-8").read()


def sub(old, new):
    global t
    assert old in t, "NOT FOUND: " + old[:100]
    t = t.replace(old, new, 1)


# 1) Card01 Skill2 发动 → 播报 + 翻明
sub('''    hits = skills.target_hits(g, target, tiles)
    g.mark_skill_used(seat, 1, 2)
    g.save_flags()
''',
    '''    hits = skills.target_hits(g, target, tiles)
    g.mark_skill_used(seat, 1, 2)
    g.note_skill(seat, 1, 2)
    g.save_flags()
''')

# 2) 新 op：配牌阶段技能窗口
sub('''def op_press(db: DB, req: dict) -> dict:
''',
    '''def op_deal_skill(db: DB, req: dict) -> dict:
    """配牌阶段技能窗口：发动（use）或跳过（skip）。"""
    rid = req.get("round_id") or _get_round_id(db)
    g = _game(db, rid)
    seat = int(req.get("seat", 0))
    action = str(req.get("action", "skip"))
    r = g.deal_action(seat, action, int(req.get("card", 0) or 0),
                      int(req.get("skill", 0) or 0))
    return {"ok": True, "deal_skill": r, "state": g.state_for(seat), "events": [],
            "result": g.result, "round_id": rid}


def op_press(db: DB, req: dict) -> dict:
''')

sub('''    "press": op_press,
''',
    '''    "press": op_press,
    "deal_skill": op_deal_skill,
''')

# 3) op_step：配牌窗口里没人的座位自动跳过
sub('''        elif g.phase == "claim":
''',
    '''        elif g.phase == "deal_skill":
            pending = getattr(g, "deal_wait", set())
            if seat in pending:
                ev = None                                    # 等我决定（发动 / 跳过）
            else:
                others = ([s for s in sorted(pending) if s not in humans]
                          if auto else [])
                ev = g.deal_action(others[0], "skip") if others else None
        elif g.phase == "claim":
''')

io.open(P, "w", encoding="utf-8", newline="").write(t)
print("api_cli.py ok")
