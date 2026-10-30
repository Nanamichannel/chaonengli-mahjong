# -*- coding: utf-8 -*-
import io

P = "game.py"
t = io.open(P, encoding="utf-8").read()
old = '''        self.confident.add(seat)
        self.save_flags()
        return {"ok": True, "armed": True, "card": int(card), "skill": int(skill),
                "skill_name": name, "kind": "confidence", "confident": True}
'''
new = '''        self.confident.add(seat)
        self.note_skill(seat, card, skill)          # 全场播报 + 人物卡翻明
        self.save_flags()
        return {"ok": True, "armed": True, "card": int(card), "skill": int(skill),
                "skill_name": name, "kind": "confidence", "confident": True}
'''
assert old in t
t = t.replace(old, new, 1)
io.open(P, "w", encoding="utf-8", newline="").write(t)
print("game.py ok")

P = "test_deal_skill.py"
t = io.open(P, encoding="utf-8").read()
old = '''    check("没人有配牌技能时不能调用", g7.deal_action(0, "skip").get("done"), True)
'''
new = '''    try:
        g7.deal_action(0, "skip")
        check("没人有配牌技能时不能调用", False)
    except Exception as e:
        check("没人有配牌技能时不能调用", "配牌技能阶段" in str(e))
'''
assert old in t
t = t.replace(old, new, 1)
io.open(P, "w", encoding="utf-8", newline="").write(t)
print("test ok")
