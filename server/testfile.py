# -*- coding: utf-8 -*-
"""Test.txt：本地测试用的「指定内容」读取器
=====================================================================
文件放在项目根目录（server/ 的上一级），格式很简单：

    [人物卡]
    01 08              ← 选卡那 20 张里一定包含这两个编号，其余随机补满 20

    [手牌]
    0: 1m2m3m4p5p6p7s8s9s1z1z2z2z     ← 0 号位第一局（东一 0 本场）的起始手牌
    1: 2m3m4m5p6p7p8s9s1s2z2z3z3z
    2: ...
    3: ...

    [牌山]
    1m 2p 3s ...       ← 按牌山顺序写（第 1 个 = 编号 1），不足 136 张的其余随机

规则：
    · 某一节不写 / 写成空的 / 整个文件没有 → 这一项按正常随机（和正式一样）
    · 写了就优先用写的，剩下的随机补齐
    · 以 # 开头的行是注释

手牌写法：紧凑式（1m2m3m / 77z）或空格分隔（1m 2m 3m / dong）；也认实体编号（1m01）。
座位 0/1/2/3 = 我 / 下家 / 对家 / 上家；庄家（0 号位）可以写 14 张，第 14 张就是摸到的那张。
"""

from __future__ import annotations

import os
import re

from tiles import (HONOR_FROM_Z, HONORS, RED_FIVES, TILE_KINDS, build_entities,
                   entity_kind, entity_tile, kind_of)

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(os.path.dirname(HERE), "Test.txt")      # 项目根目录

ALL_ENTITIES = set(build_entities())
HONOR_NAMES = set(HONORS) | set(HONOR_FROM_Z)

_SECTION_ALIASES = {
    "人物卡": "cards", "人物": "cards", "卡": "cards", "cards": "cards",
    "手牌": "hands", "起始手牌": "hands", "hands": "hands",
    "牌山": "wall", "牌墙": "wall", "wall": "wall",
    "代打": "auto", "电脑代打": "auto", "auto": "auto",
}


# ────────────────────────── 牌名解析 ──────────────────────────
def _norm_token(tok: str) -> str | None:
    """一个写法 → 规则层牌名（1m / 0p / dong…）。认实体编号（1m01）和中文风牌。"""
    tok = tok.strip()
    if not tok:
        return None
    if tok in ALL_ENTITIES:                     # 1m01 / 0p01
        return entity_tile(tok)
    if tok in TILE_KINDS:                       # 1m / 0m / dong
        return tok
    if tok in HONOR_FROM_Z:                     # 1z..7z
        return HONOR_FROM_Z[tok]
    m = re.fullmatch(r"([0-9])([mps])", tok)
    if m:
        n, s = m.group(1), m.group(2)
        return f"0{s}" if n == "0" else f"{n}{s}"
    return None


def _expand_compact(tok: str) -> list[str] | None:
    """'123m77z' → ['1m','2m','3m','zhong','zhong']；不是紧凑式返回 None。"""
    if (not tok or not any(c in "mpsz" for c in tok)
            or not all(c.isdigit() or c in "mpsz" for c in tok)):
        return None
    out: list[str] = []
    buf = ""
    for ch in tok:
        if ch.isdigit():
            buf += ch
        else:
            for d in buf:
                if ch == "z":
                    if d in HONOR_FROM_Z:
                        out.append(HONOR_FROM_Z[d])
                else:
                    out.append(f"0{ch}" if d == "0" else f"{d}{ch}")
            buf = ""
    if buf:                                     # 结尾还有数字没接花色 → 不是紧凑式
        return None
    return out


def parse_tiles(text: str) -> list[str]:
    """'123m456p77z' / '1m 2m 3m' / '1m01 2p02' → 牌名列表。"""
    out: list[str] = []
    for raw in re.split(r"[\s,，]+", (text or "").strip()):
        if not raw:
            continue
        # 紧凑式：123m / 456p / 77z / 123m77z
        packed = _expand_compact(raw)
        if packed is not None:
            out += packed
            continue
        one = _norm_token(raw)
        if one:
            out.append(one)
    return out


# ────────────────────────── 读文件 ──────────────────────────
_CACHE: dict = {"key": None, "data": None}


def load(path: str | None = None) -> dict:
    """读 Test.txt → {"cards": [...], "hands": {seat: [tile...]}, "wall": [...],
                      "auto_ai": True/False}

    文件不存在 / 读不了 → 三项都是空（= 全部随机）。
    按「路径 + 修改时间」缓存：四个窗口每秒都会问一次，别每次都读盘。
    """
    out: dict = {"cards": [], "hands": {}, "wall": [], "auto_ai": True}
    p = path or PATH
    try:
        key = (p, os.path.getmtime(p))
    except OSError:
        return out
    if _CACHE.get("key") == key:
        return dict(_CACHE["data"])
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return out

    section = ""
    wall_tokens: list[str] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("[") and s.endswith("]"):
            section = _SECTION_ALIASES.get(s[1:-1].strip(), "")
            continue
        if section == "cards":
            for tok in re.split(r"[\s,，]+", s):
                if tok.isdigit():
                    n = int(tok)
                    if 1 <= n <= 46 and n not in out["cards"]:
                        out["cards"].append(n)
        elif section == "hands":
            m = re.match(r"^\s*([0-3])\s*[:：]\s*(.+)$", s)
            if m:
                tiles = parse_tiles(m.group(2))
                if tiles:
                    out["hands"][int(m.group(1))] = tiles
        elif section == "wall":
            wall_tokens += parse_tiles(s)
        elif section == "auto":
            v = s.strip().lower()
            if v in ("关", "关闭", "off", "0", "false", "no", "否", "不代打"):
                out["auto_ai"] = False
            elif v in ("开", "开启", "on", "1", "true", "yes", "是", "代打"):
                out["auto_ai"] = True
    out["wall"] = wall_tokens[:136]
    _CACHE["key"] = key
    _CACHE["data"] = dict(out)
    return out


def auto_ai() -> bool:
    """没有客户端连接的座位，要不要服务器替他摸切（默认：要）。"""
    return bool(load().get("auto_ai", True))


# ────────────────────────── 写进牌山 ──────────────────────────
def _matches(entity: str, want: str) -> bool:
    """这张物理牌是不是想要的（want 可以是实体编号，也可以是牌种）。"""
    if want in ALL_ENTITIES:
        return entity == want
    return entity_kind(entity) == want


def apply_wall(db, round_id: int, targets: dict[int, str]) -> int:
    """把牌山里指定 seq 的牌换成指定牌种；136 张实体编号不会重复。

    targets = {seq: 牌种 / 实体编号}。返回实际改了几张。

    做法不是「逐张互换」（那样想要的牌如果正好都在别的指定位上就换不到），
    而是：先把 136 张实体按牌种分组，指定位置直接从分组里取，剩下的按原顺序填回去。
    这样只要整副牌里够张，指定的位置就一定能拿到想要的牌。
    """
    rows = db._rows("SELECT seq, entity, tile FROM round_wall WHERE round_id=? ORDER BY seq",
                    (round_id,))
    if not rows:
        return 0
    seqs = [int(r["seq"]) for r in rows]
    ents = [r["entity"] or (r["tile"] + f"{int(r['seq']):02d}") for r in rows]
    pool: dict[str, list[str]] = {}
    for e in ents:
        pool.setdefault(entity_kind(e), []).append(e)

    assigned: list[str | None] = [None] * len(seqs)
    # 1) 精确到「哪一张物理牌」的写法（1m01）先占位
    for i, seq in enumerate(seqs):
        want = targets.get(seq)
        if not want or want not in ALL_ENTITIES:
            continue
        lst = pool.get(entity_kind(want))
        if lst and want in lst:
            lst.remove(want)
            assigned[i] = want
    # 2) 按牌种占位
    for i, seq in enumerate(seqs):
        if assigned[i] is not None:
            continue
        want = targets.get(seq)
        if not want or want in ALL_ENTITIES:
            continue
        lst = pool.get(want)
        if lst:
            assigned[i] = lst.pop(0)
    # 3) 其余位置用剩下的牌（保持原来的先后顺序）
    used = {e for e in assigned if e is not None}
    leftover = [e for e in ents if e not in used]
    it = iter(leftover)
    final = [a if a is not None else next(it, "") for a in assigned]
    if any(not e for e in final):
        return 0

    changed = sum(1 for i, e in enumerate(final) if e != ents[i])
    with db.tx():
        for i, seq in enumerate(seqs):
            db.conn.execute(
                "UPDATE round_wall SET entity=?, tile=? WHERE round_id=? AND seq=?",
                (final[i], entity_tile(final[i]), round_id, seq))
    return changed


def hand_targets(g) -> dict[int, str]:
    """Test.txt 的 [手牌] → {牌山 seq: 牌种}，按这一局的配牌顺序算出来。"""
    spec = load()
    hands = spec.get("hands") or {}
    if not hands:
        return {}
    nos: dict[int, list[int]] = {0: [], 1: [], 2: [], 3: []}
    for st in g.deal_plan()["steps"]:
        nos[int(st["seat"])] += list(st["tiles"])
        if st.get("jump"):
            nos[int(st["seat"])].append(int(st["jump"]))
    out: dict[int, str] = {}
    for seat, tiles in hands.items():
        for no, tile in zip(nos.get(int(seat), []), tiles):
            out[int(no) - 1] = tile                 # seq = 编号 - 1
    return out


def wall_targets() -> dict[int, str]:
    """Test.txt 的 [牌山] → {seq: 牌种}（按顺序，第 1 个 = 编号 1）。"""
    spec = load()
    return {i: t for i, t in enumerate(spec.get("wall") or [])}


def cards() -> list[int]:
    return list(load().get("cards") or [])


def eligible_kinds() -> list[str]:
    """牌名全集（给测试用）。"""
    return list(TILE_KINDS)


__all__ = ["PATH", "load", "parse_tiles", "apply_wall", "hand_targets", "wall_targets",
           "cards", "auto_ai", "kind_of", "RED_FIVES"]
