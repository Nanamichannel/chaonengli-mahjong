# -*- coding: utf-8 -*-
"""配牌窗口：已经在配牌动画里发动过的人不再重复等。"""
import io

P = "game.py"
t = io.open(P, encoding="utf-8").read()
old = '''        for card, skill in skills.deal_skills():
            key = (int(seat), int(card))
'''
new = '''        for card, skill in skills.deal_skills():
            # 在配牌动画里（窗口出现之前）就点过技能的人，不再让他重复决定
            if (int(card), int(skill)) == (3, 1) and seat in self.confident:
                continue
            key = (int(seat), int(card))
'''
assert old in t
t = t.replace(old, new, 1)
io.open(P, "w", encoding="utf-8", newline="").write(t)
print("ok")
