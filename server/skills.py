# -*- coding: utf-8 -*-
"""角色卡技能（服务端权威）
=====================================================================
一条技能 = 一张人物卡上的 Skill1 / Skill2。客户端只负责「单击人物卡展开图标 →
单击图标」，真正的判定、发牌、算番、结算都在这里做。

通用规则（所有主动技能）
    · 只能在自己摸完牌、还没打牌的时候发动（phase=discard 且 turn=自己）
    · 发动后由服务端检查条件；条件不成立就返回 armed=False + 原因，不算出错
    · 条件成立就把技能「挂上」（Game.armed_skill），legal_actions 里会多出一个动作，
      客户端据此显示对应的按钮（比如自摸）；按下按钮才真正结算

目前实现
    Card01 Skill1「国标」
        三色三步高 / 花龙 / 五门齐 听牌时可用：
        系统替你打出一张牌、发给你一张和牌（视为自摸），
        番数上这三种牌型合起来固定算「奖励番」：门清 +2、副露 +1（复合也只算一份）。
        发哪张牌按「结算点数最大」挑；同样点数随机一张；不会发赤宝牌，也不算里宝牌。
"""

from __future__ import annotations

import json
import random

from rules import agari, patterns, yaku
from tiles import TILE_KINDS, counts_of, index_of, tiles_of

# (card_no, skill_no) -> 技能定义
REGISTRY: dict[tuple[int, int], dict] = {
    (1, 1): {"name": "国标", "kind": "pattern_tsumo",
             "patterns": ("五门齐", "花龙", "三色三步高"), "timing": "draw"},
    (3, 1): {"name": "自信", "kind": "confidence", "timing": "deal"},
    (3, 2): {"name": "压制", "kind": "river_swap", "timing": "draw"},
    (4, 1): {"name": "风神", "kind": "deal_swap", "timing": "deal"},
    (4, 2): {"name": "自风", "kind": "self_wind", "timing": "draw"},
    (5, 1): {"name": "策略", "kind": "strategy", "timing": "draw"},
    (5, 2): {"name": "拔北", "kind": "nuki", "timing": "draw"},
    (6, 1): {"name": "南风", "kind": "south_wind", "timing": "deal"},
    (6, 2): {"name": "坚韧", "kind": "tenacity", "timing": "settle"},
    (7, 1): {"name": "降神", "kind": "oracle_suit", "timing": "deal"},
    (7, 2): {"name": "恶灵", "kind": "oracle_lock", "timing": "settle"},
    (8, 1): {"name": "决斗", "kind": "duel", "timing": "draw"},
    (8, 2): {"name": "决斗标记", "kind": "duel_mark", "timing": "settle"},
    (9, 1): {"name": "间合守", "kind": "swap_own_river", "timing": "draw"},
    (9, 2): {"name": "间合攻", "kind": "swap_other_river", "timing": "draw"},
    (10, 1): {"name": "鬼门", "kind": "kaimon", "timing": "draw"},
    (10, 2): {"name": "四喜", "kind": "four_joy", "timing": "draw"},
    (11, 1): {"name": "魔术", "kind": "dora_swap", "timing": "draw"},
    (11, 2): {"name": "快手", "kind": "river_side", "timing": "draw"},
    (12, 1): {"name": "海神", "kind": "haishin", "timing": "deal"},
    (12, 2): {"name": "X神", "kind": "x_skip", "timing": "draw"},
    (13, 1): {"name": "破发", "kind": "pofa", "timing": "other_riichi"},
    (13, 2): {"name": "渣和", "kind": "dawa", "timing": "settle"},
    (14, 1): {"name": "点燃", "kind": "ignite", "timing": "deal"},
    (14, 2): {"name": "炸裂", "kind": "blast", "timing": "draw"},
    (15, 1): {"name": "钓鱼", "kind": "fishing", "timing": "draw"},
    (15, 2): {"name": "上钩", "kind": "hook", "timing": "settle"},
    (16, 1): {"name": "传承", "kind": "inherit", "timing": "draw"},
    (16, 2): {"name": "多面", "kind": "multi_face", "timing": "settle"},
    (17, 1): {"name": "研究", "kind": "research", "timing": "deal"},
    (17, 2): {"name": "看破", "kind": "sight", "timing": "any"},
    (18, 1): {"name": "枷锁", "kind": "shackle", "timing": "deal"},
    (18, 2): {"name": "连接", "kind": "link", "timing": "draw"},
    (19, 1): {"name": "深山", "kind": "deep_mountain", "timing": "draw"},
    (19, 2): {"name": "浓雾", "kind": "fog", "timing": "draw"},
    (20, 1): {"name": "前路", "kind": "prophecy", "timing": "draw"},
    (20, 2): {"name": "感知", "kind": "sense", "timing": "draw"},
    (21, 1): {"name": "迷途之家", "kind": "gift", "timing": "settle"},
    (21, 2): {"name": "馈赠", "kind": "gift_bonus", "timing": "settle"},
    (22, 1): {"name": "先负", "kind": "xianfu", "timing": "discard"},
    (22, 2): {"name": "友引", "kind": "youyin", "timing": "draw"},
    (23, 1): {"name": "加热", "kind": "heat", "timing": "draw"},
    (23, 2): {"name": "暖气", "kind": "warm", "timing": "settle"},
    (25, 1): {"name": "宝牌运", "kind": "dora_luck", "timing": "deal"},
    (25, 2): {"name": "宝牌的集合", "kind": "dora_luck2", "timing": "deal"},
    (26, 1): {"name": "云外镜", "kind": "c26_sight", "timing": "deal"},
    (26, 2): {"name": "天梯", "kind": "c26_streak", "timing": "deal"},
    (27, 1): {"name": "调包", "kind": "c27_swap", "timing": "draw"},
    (27, 2): {"name": "命中", "kind": "c27_bomb", "timing": "draw"},
    (28, 1): {"name": "满贯", "kind": "c28_gate", "timing": "deal"},
    (28, 2): {"name": "蜕变", "kind": "c28_step", "timing": "settle"},
    (29, 1): {"name": "加速", "kind": "c29_chi_any", "timing": "draw"},
    (29, 2): {"name": "精算", "kind": "c29_closed", "timing": "settle"},
    (30, 1): {"name": "向听", "kind": "c30_flow", "timing": "deal"},
    (30, 2): {"name": "W立", "kind": "c30_wriichi", "timing": "settle"},
    (31, 1): {"name": "封堵", "kind": "c31_block", "timing": "any"},
    (31, 2): {"name": "阻止", "kind": "c31_stop", "timing": "any"},
    (32, 1): {"name": "新手运", "kind": "c32_flow", "timing": "deal"},
    (32, 2): {"name": "无知", "kind": "c32_green", "timing": "settle"},
    (33, 1): {"name": "染手", "kind": "c33_river_group", "timing": "draw"},
    (33, 2): {"name": "记忆", "kind": "c33_memory", "timing": "discard"},
    (34, 1): {"name": "厄运", "kind": "c34_silence", "timing": "discard"},
    (34, 2): {"name": "海底", "kind": "c34_last", "timing": "discard"},
    (35, 1): {"name": "流势", "kind": "c35_sort", "timing": "discard"},
    (35, 2): {"name": "逆势", "kind": "c35_half", "timing": "settle"},
    (36, 1): {"name": "思路", "kind": "c36_watch", "timing": "any"},
    (36, 2): {"name": "故意", "kind": "c36_pay", "timing": "discard"},
    (37, 1): {"name": "岭上开花", "kind": "c37_rinshan", "timing": "discard"},
    (37, 2): {"name": "强运", "kind": "c37_swap4", "timing": "draw"},
    (38, 1): {"name": "重整", "kind": "c38_dora3", "timing": "discard"},
    (38, 2): {"name": "逆袭", "kind": "c38_double", "timing": "settle"},
    (40, 1): {"name": "透视", "kind": "c40_peek", "timing": "discard"},
    (41, 1): {"name": "复制", "kind": "c41_copy", "timing": "any"},
    (41, 2): {"name": "局终", "kind": "c41_pay", "timing": "settle"},
    (43, 1): {"name": "NO MISS", "kind": "c43_taatsu", "timing": "discard"},
    (44, 1): {"name": "弃子", "kind": "c44_waive", "timing": "settle"},
    (44, 2): {"name": "电报", "kind": "c44_reveal", "timing": "draw"},
    (45, 1): {"name": "神境", "kind": "c45_river13", "timing": "draw"},
    (45, 2): {"name": "替身", "kind": "c45_standin", "timing": "discard"},
    (46, 1): {"name": "恶听", "kind": "c46_evilwait", "timing": "discard"},
    (46, 2): {"name": "赤里", "kind": "c46_ura", "timing": "settle"},
    (39, 1): {"name": "隐形", "kind": "c39_stealth", "timing": "discard"},
    (39, 2): {"name": "无视", "kind": "c39_fakeriichi", "timing": "any"},
    (42, 1): {"name": "理论战", "kind": "c42_lock", "timing": "deal"},
    (42, 2): {"name": "夺目", "kind": "c42_dealer", "timing": "discard"},
    (40, 2): {"name": "同盟", "kind": "c40_ally", "timing": "discard"},
    (43, 2): {"name": "免疫", "kind": "c43_immune", "timing": "any"},
}

# 每个 Skill 的发动时机（配牌 / 摸牌 / 结算）。
#   deal   = 配牌阶段（庄家跳完牌之后、第一次切牌之前）
#   draw   = 摸牌后、打牌前
#   settle = 结算时（和牌/流局结算）
TIMING: dict[tuple[int, int], str] = {
    (1, 1): "draw", (1, 2): "draw",
    (2, 1): "draw", (2, 2): "draw",
    (3, 1): "deal", (3, 2): "draw",
    (4, 1): "deal", (4, 2): "draw",
    (5, 1): "draw", (5, 2): "draw",
    (6, 1): "deal", (6, 2): "settle",
    (7, 1): "deal", (7, 2): "settle",
    (8, 1): "draw", (8, 2): "settle",
    (9, 1): "draw", (9, 2): "draw",
    (10, 1): "draw", (10, 2): "draw",
    (11, 1): "draw", (11, 2): "draw",
    (12, 1): "deal", (12, 2): "draw",
    (13, 1): "draw", (13, 2): "settle",
    (14, 1): "deal", (14, 2): "draw",
    (15, 1): "draw", (15, 2): "settle",
    (16, 1): "draw", (16, 2): "settle",
    (17, 1): "deal", (17, 2): "draw",
    (18, 1): "deal", (18, 2): "draw",
    (19, 1): "draw", (19, 2): "draw",
    (20, 1): "draw", (20, 2): "draw",
    (21, 1): "settle", (21, 2): "settle",
    (22, 1): "draw", (22, 2): "draw",
    (23, 1): "draw", (23, 2): "settle",
    (24, 1): "draw", (24, 2): "draw",
    (25, 1): "deal", (25, 2): "deal",
    (26, 1): "deal", (26, 2): "deal",
    (27, 1): "draw", (27, 2): "draw",
    (28, 1): "deal", (28, 2): "settle",
    (29, 1): "draw", (29, 2): "settle",
    (30, 1): "deal", (30, 2): "settle",
    (31, 1): "draw", (31, 2): "draw",
    (32, 1): "deal", (32, 2): "settle",
    (33, 1): "draw", (33, 2): "discard",
    (34, 1): "discard", (34, 2): "discard",
    (35, 1): "discard", (35, 2): "settle",
    (36, 1): "any",
    (36, 2): "discard",
    (37, 1): "discard",
    (37, 2): "draw",
    (38, 1): "discard",
    (38, 2): "settle",
    (40, 1): "discard",
    (41, 1): "any",
    (41, 2): "settle",
    (43, 1): "discard",
    (44, 1): "settle",
    (44, 2): "draw",
    (45, 1): "draw",
    (45, 2): "discard",
    (46, 1): "discard",
    (46, 2): "settle",
    (39, 1): "discard",
    (39, 2): "any",
    (42, 1): "deal",
    (42, 2): "discard",
    (40, 2): "discard",
    (43, 2): "any",
}

TIMING_CN = {"deal": "配牌", "draw": "摸牌", "settle": "结算", "discard": "切牌"}


def timing(card: int, skill: int) -> str:
    return TIMING.get((int(card), int(skill)), "draw")


def timing_cn(card: int, skill: int) -> str:
    return TIMING_CN.get(timing(card, skill), "摸牌")


def deal_skills() -> list[tuple[int, int]]:
    """所有「配牌阶段发动」的技能（card, skill）。"""
    return sorted(k for k, v in TIMING.items() if v == "deal")

PATTERN_NAMES = ("五门齐", "花龙", "三色三步高")


def has(card: int, skill: int) -> bool:
    return (int(card), int(skill)) in REGISTRY


def info(card: int, skill: int) -> dict:
    return REGISTRY.get((int(card), int(skill)), {})


# ────────────────────────── 人物卡归属 ──────────────────────────
def _round_index(wind: str, number: int) -> int:
    """半庄第几场 → 用第几号主战卡（0..3）：东一/东二→0，东三/东四→1 …"""
    base = {"dong": 0, "nan": 4, "xi": 8, "bei": 12}.get(wind, 0)
    return min((base + max(1, min(4, int(number))) - 1) >> 1, 3)

def _round_no(wind: str, number: int) -> int:
    """半庄第几局（0..7）：东一=0 东二=1 东三=2 东四=3，南一=4 … 南四=7。

    本场（连庄 honba）不算 —— 风场不变，人物卡寿命也就不变。"""
    base = {"dong": 0, "nan": 4, "xi": 8, "bei": 12}.get(wind, 0)
    return base + max(1, min(4, int(number))) - 1


def order_of(db, seat: int) -> list[int]:
    """这家选的 5 张卡（前 4 张按角色轮换 = 主战，第 5 张 = 协战）"""
    row = db._row("SELECT value FROM meta WHERE key='lobby_state'")
    if not row:
        return []
    try:
        seats = (json.loads(row["value"]) or {}).get("seats") or []
        return [int(v) for v in (seats[int(seat)].get("order") or [])]
    except (ValueError, TypeError, AttributeError, IndexError):
        return []


def card_slot(db, g, seat: int, card: int) -> int:
    """这张卡在这个座位的「格位」：0 = 主战 / 1 = 协战 / 2 = 其它。

    ★ 用户口径：主战卡和协战卡**同时**要问的时候，**主战先于协战**。
      格位就是顺序本身 —— 所有「谁先问」的地方按格位排，不用再写 if/else 比较。
      拿不到大厅卡序（直连测试 / 还没选卡）→ 一律当 0，等于「按座位顺序」的老行为。
    """
    order = order_of(db, int(seat))
    if len(order) < 5:
        return 0
    if int(card) == order[_round_index(g.round_wind, g.round["number"])]:
        return 0
    if int(card) == order[4]:
        return 1
    return 2


def cards_in_order(db, g, seat: int) -> list[int]:
    """这家本局能用的卡，**按结算顺序排好**：主战 → 协战 → 传承来的。

    所有「先主战、后协战」的地方都遍历这个列表，顺序自然成立：
      · 配牌窗口（_deal_skill_options）
      · 摸到的牌被谁抢（_intercept_kinds）
    拿不到大厅卡序时返回「全部卡」（按卡号）＝老行为，不会让技能凭空消失。
    """
    out: list[int] = []
    order = order_of(db, int(seat))
    if len(order) >= 5:
        _mute = int(support_muted(db, g, int(seat)))
        for c in (order[_round_index(g.round_wind, g.round["number"])], order[4]):
            if int(c) > 0 and int(c) not in out and int(c) != _mute:
                out.append(int(c))
    for c in sorted((getattr(g, "granted", None) or {}).get(int(seat)) or set()):
        if int(c) > 0 and int(c) not in out:
            out.append(int(c))                       # 传承来的排最后
    if out:
        return out
    # 没有卡序（直连测试 / 还没选卡）→ 当作 1..33 都能用，按卡号排（= 老行为）
    return list(range(1, 34))


def _char_use(db) -> dict:
    row = db._row("SELECT value FROM meta WHERE key='char_use'")
    if not row:
        return {}
    try:
        return json.loads(row["value"]) or {}
    except (ValueError, TypeError):
        return {}


def note_char_use(db, seat: int, card: int) -> None:
    """记下「这张卡第一次发动技能是在哪个角色（两局）」"""
    row = db._row("SELECT value FROM meta WHERE key='round_meta'")
    used = _char_use(db)
    key = f"{int(seat)}:{int(card)}"
    if key in used:
        return
    used[key] = 0
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('char_use', ?)",
                        (json.dumps(used, ensure_ascii=False),))


def set_char_use(db, seat: int, card: int, ri: int) -> None:
    used = _char_use(db)
    used[f"{int(seat)}:{int(card)}"] = int(ri)
    with db.tx():
        db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('char_use', ?)",
                        (json.dumps(used, ensure_ascii=False),))


# ────────────────────────── 协战卡手动遮罩 ──────────────────────────
# 协战卡只活两个风场，出场时机很关键 → 玩家可以长按人物卡把它「遮罩」掉：
# 遮罩期间这张卡的**一切技能判定都不成立**（等同这个座位没有这张卡）。
SUPPORT_MUTE_KEY = "support_mute"


def support_card(db, seat: int) -> int:
    """这一家的协战卡卡号（order 的第 5 张）；拿不到卡序 → 0。"""
    order = order_of(db, int(seat))
    return int(order[4]) if len(order) >= 5 else 0


def support_mute_map(db) -> dict[int, int]:
    """{seat: 被遮罩的协战卡卡号}（跨局保留；卡换了就自动失效）"""
    row = db._row("SELECT value FROM meta WHERE key=?", (SUPPORT_MUTE_KEY,))
    if not row:
        return {}
    try:
        raw = json.loads(str(row["value"])) or {}
    except (ValueError, TypeError):
        return {}
    out: dict[int, int] = {}
    for k, v in (raw if isinstance(raw, dict) else {}).items():
        try:
            s, c = int(k), int(v)
        except (TypeError, ValueError):
            continue
        if s in range(4) and c > 0:
            out[s] = c
    return out


def set_support_mute(db, seat: int, card: int) -> None:
    """card > 0 → 遮罩这张协战卡；card <= 0 → 取消这个座位的遮罩。"""
    cur = support_mute_map(db)
    s = int(seat)
    if int(card) > 0:
        cur[s] = int(card)
    else:
        cur.pop(s, None)
    with db.tx():
        db.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            (SUPPORT_MUTE_KEY,
             json.dumps({str(k): int(v) for k, v in cur.items()}, ensure_ascii=False)))


def support_muted(db, g, seat: int) -> int:
    """这个座位「现在被遮罩的协战卡」卡号；0 = 没遮（或那张卡已经换掉了）。

    同一笔请求里会问很多次（legal_actions / state / 每个技能判定），
    所以在 Game 上挂一个缓存；改了遮罩的那一笔请求自己就是新的 Game，不会读到旧的。
    """
    cur = support_card(db, int(seat))
    if cur <= 0:
        return 0
    cache = getattr(g, "_support_mute_cache", None) if g is not None else None
    if cache is None:
        cache = support_mute_map(db)
        try:
            if g is not None:
                g._support_mute_cache = cache
        except Exception:                                    # noqa: BLE001
            pass
    return cur if int(cache.get(int(seat), 0)) == cur else 0


def char_expired(db, g, seat: int, card: int) -> bool:
    """这张卡是不是已经「过了存活的两个风场」→ 永久失效。

    一张卡存活两个风场（= 两个小局）：用过的那一局 + 下一局，第三局起失效。
    用户口径：东一..东四 / 南一..南四 各算一个风场，本场（连庄）不影响。
    """
    used = _char_use(db)
    key = f"{int(seat)}:{int(card)}"
    if key not in used:
        return False
    return _round_no(g.round_wind, g.round["number"]) > int(used[key]) + 1


def owns_card(db, g, seat: int, card: int, *, strict: bool = False) -> bool:
    """这张人物卡是不是这个座位这一局能用的（主战卡或协战卡）。

    没有大厅数据（比如直连测试）就不拦。
    strict=True：拿不到卡序时按「没有」算 —— 被动效果（比如压制看暗置牌）
    必须真的持有这张卡，不能因为没选卡就对所有人开放。
    """
    granted = getattr(g, "granted", None) or {}
    if int(card) in (granted.get(int(seat)) or set()):
        return True                                   # 传承：本小局当成我的卡
    poked = getattr(g, "poked", None) or set()
    if f"{int(seat)}:{int(card)}" in poked:
        return False                                  # 看破：本小局剔除
    row = db._row("SELECT value FROM meta WHERE key='lobby_state'")
    if not row:
        return not strict
    try:
        lobby = json.loads(row["value"])
        seats = lobby.get("seats") or []
        if seat < 0 or seat >= len(seats):
            return not strict
        order = [int(v) for v in (seats[seat].get("order") or [])]
    except (ValueError, TypeError, AttributeError):
        return not strict
    if len(order) < 5:
        return not strict
    ri = _round_index(g.round_wind, g.round["number"])
    if int(card) not in (order[ri], order[4]):
        return False
    # 协战卡被玩家手动遮罩 → 这张卡的一切技能判定都不成立
    if int(card) == int(order[4]) and int(support_muted(db, g, int(seat))) == int(card):
        return False
    return not char_expired(db, g, seat, int(card))     # 两风场寿命


# ────────────────────────── 算分 ──────────────────────────
def _ctx(g, seat: int, tiles14: list[str], melds, win_tile: str) -> dict:
    """技能和牌的评分上下文：自摸、带奖励番、不算里宝牌、不发赤宝牌。"""
    return {
        "counts": counts_of(tiles14),
        "tiles": list(tiles14),
        "melds": list(melds),
        "win_index": index_of(win_tile),
        "is_dealer": seat == g.dealer,
        "tsumo": True,
        "seat_wind": ["dong", "nan", "xi", "bei"][(seat - g.dealer) % 4],
        "round_wind": g.round_wind,
        "riichi": False, "ippatsu": False, "double_riichi": False,
        "last_tile": False, "rinshan": False, "chankan": False,
        "tenhou": None,
        "dora_indicators": g.revealed_dora("dora"),
        "ura_indicators": [],                    # 不考虑里宝牌
        "rules": g.rules,
        "pattern_bonus": True,                   # ← 打开五门齐 / 花龙 / 三色三步高
    }


def _patterns_of(res: dict) -> list[str]:
    found: list[str] = []
    for y in (res.get("yaku") or []):
        for part in str(y.get("name", "")).split("、"):
            if part in PATTERN_NAMES and part not in found:
                found.append(part)
    return [n for n in PATTERN_NAMES if n in found]


# ────────────────────────── Card01 Skill1「国标」 ──────────────────────────
def card01_s1_plans(g, seat: int) -> list[dict]:
    """找出所有「点数并列最高」的方案（同点数随机时用得到）。

    没有能做成那三种番的听牌 → 空列表。
    """
    hand = g.hand(seat)
    melds = g.melds(seat)
    if len(hand) % 3 != 2:                     # 必须是「刚摸完」的 14 张
        return None
    counts = counts_of(hand)
    if sum(counts) + 3 * len(melds) != 14:     # 暗牌 + 副露 = 14 张
        return None

    best_total = -1
    plans: list[dict] = []
    for d in range(34):
        if counts[d] == 0:
            continue
        counts[d] -= 1
        for w in range(34):
            if counts[w] >= 4:                 # 手里已有 4 张，发不出第 5 张
                continue
            counts[w] += 1
            if agari.is_winning(counts, melds):
                tiles14 = tiles_of(counts)
                res = yaku.judge(_ctx(g, seat, tiles14, melds, TILE_KINDS[w]))
                pats = _patterns_of(res) if res else []
                if pats:
                    total = int((res.get("pays") or {}).get("total", 0))
                    plan = {
                        "discard": TILE_KINDS[d], "win": TILE_KINDS[w],
                        "res": res, "patterns": pats, "total": total,
                        "han_bonus": 2 if agari.is_closed(melds) else 1,
                    }
                    if total > best_total:
                        best_total = total
                        plans = [plan]
                    elif total == best_total:
                        plans.append(plan)
            counts[w] -= 1
        counts[d] += 1

    return plans


def card01_s1_plan(g, seat: int) -> dict | None:
    """随机取一个最优方案（同点数随机一张牌）。"""
    plans = card01_s1_plans(g, seat)
    return random.choice(plans) if plans else None


def card01_s1_bonus_for(g, seat: int) -> int:
    """奖励番：门清 +2、副露 +1（播报用）。"""
    return 2 if agari.is_closed(g.melds(seat)) else 1


# ────────────────────────── Card01 Skill2「避开」──────────────────────────
def target_hits(g, target: int, tiles: list[str]) -> list[int]:
    """tiles 里有哪几张是这个座位的铳张（= 他在听的牌）。

    只回答「你选的这两张」，不把对方的听牌整份给客户端 —— 技能描述里
    「听牌不显示」，客户端只知道这两张是不是危险牌。
    """
    waits = set(agari.winning_tiles(g.hand_counts(target), g.melds(target)))
    return [i for i, tile in enumerate(tiles) if str(tile) in waits]


# ────────────────────────── 执行 ──────────────────────────
def execute_pattern_tsumo(db, g, seat: int, plan: dict) -> dict:
    """替玩家打出一张、把和牌那张「发」进手里，返回已算好的结算结果。

    和牌那张没有真实牌山编号（技能发的），给一个负数 wall_seq 存进 round_hands，
    这样 state 里的手牌是 14 张、副露/牌河也都对得上。
    """
    rid = g.round_id
    discard = str(plan["discard"])
    win = str(plan["win"])

    row = db._row("SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
                  "ORDER BY is_drawn DESC, wall_seq LIMIT 1", (rid, seat, discard))
    if row is None:
        raise ValueError("手里没有这张牌")
    db.discard(rid, seat, wall_seq=int(row["wall_seq"]))

    with db.tx():
        mn = db._one("SELECT COALESCE(MIN(wall_seq), 0) FROM round_hands WHERE round_id=?",
                     (rid,))
        seq = min(int(mn or 0), 0) - 1
        db.conn.execute(
            "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
            "VALUES(?,?,?,?,?,1)", (rid, seat, seq, win, 999))
    return plan["res"]
