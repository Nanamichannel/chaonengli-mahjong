# -*- coding: utf-8 -*-
"""给所有技能标注发动时机：配牌 / 摸牌 / 结算。"""
import io

P = "skills.py"
t = io.open(P, encoding="utf-8").read()


def sub(old, new):
    global t
    assert old in t, "NOT FOUND: " + old[:100]
    t = t.replace(old, new, 1)


sub('''REGISTRY: dict[tuple[int, int], dict] = {
    (1, 1): {"name": "国标", "kind": "pattern_tsumo",
             "patterns": ("五门齐", "花龙", "三色三步高")},
    (3, 1): {"name": "自信", "kind": "confidence"},
    (3, 2): {"name": "压制", "kind": "river_swap"},
}''',
    '''REGISTRY: dict[tuple[int, int], dict] = {
    (1, 1): {"name": "国标", "kind": "pattern_tsumo",
             "patterns": ("五门齐", "花龙", "三色三步高"), "timing": "draw"},
    (3, 1): {"name": "自信", "kind": "confidence", "timing": "deal"},
    (3, 2): {"name": "压制", "kind": "river_swap", "timing": "draw"},
}

# 每个 Skill 的发动时机（配牌 / 摸牌 / 结算）。
#   deal   = 配牌阶段（庄家跳完牌之后、第一次切牌之前）
#   draw   = 摸牌后、打牌前
#   settle = 结算时（和牌/流局结算）
TIMING: dict[tuple[int, int], str] = {
    (1, 1): "draw", (1, 2): "draw",
    (2, 1): "draw", (2, 2): "draw",
    (3, 1): "deal", (3, 2): "draw",
}

TIMING_CN = {"deal": "配牌", "draw": "摸牌", "settle": "结算"}


def timing(card: int, skill: int) -> str:
    return TIMING.get((int(card), int(skill)), "draw")


def timing_cn(card: int, skill: int) -> str:
    return TIMING_CN.get(timing(card, skill), "摸牌")


def deal_skills() -> list[tuple[int, int]]:
    """所有「配牌阶段发动」的技能（card, skill）。"""
    return sorted(k for k, v in TIMING.items() if v == "deal")''')

io.open(P, "w", encoding="utf-8", newline="").write(t)
print("skills.py ok")
