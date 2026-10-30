# -*- coding: utf-8 -*-
"""
服务器端麻将规则引擎
=====================================================================
    tiles.py           牌的基础（在上一层，数据库层也用它）
    rules.agari        和牌 / 听牌 / 牌型拆解
    rules.calls        吃 / 碰 / 杠 / 振听 / 食い替え / 九种九牌
    rules.yaku         役种判定
    rules.score        符数 / 翻数 → 点数

客户端（Godot）以后只负责显示和把玩家的操作发上来，判定全部在这里做。
"""

from rules import agari, calls, tenpai, yaku      # noqa: F401

__all__ = ["agari", "calls", "yaku", "score", "tenpai"]
