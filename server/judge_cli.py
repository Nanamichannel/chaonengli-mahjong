# -*- coding: utf-8 -*-
"""
役种判定接口（独立、可单独测试）
=====================================================================
输入一副和牌型，输出：役种、番数、符数（含明细）、点数。

命令行：
    python judge_cli.py --hand "123m456m789m234p55s" --win 2p
    python judge_cli.py --hand "11223344556677m" --win 7m
    python judge_cli.py --hand "111m222m333p444s55z" --win 5z --tsumo --dealer
    python judge_cli.py --hand "123m456m789m123p11s" --win 1s --riichi --tsumo \
        --seat-wind dong --round-wind dong --dora "1s"
    python judge_cli.py --hand "234m567m234p567s22s" --win 2s --melds "pon:111z"
    python judge_cli.py --hand "..." --json          # 只输出 JSON（给程序用）

写法说明：
    手牌      123m456m789m234p55s    0m/0p/0s = 赤 5；1z~7z = 东南西北白发中
    和牌张    2p（也可以写 中 / dong）
    副露      chi:234p,pon:555z,minkan:1111m,ankan:1111m,kakan:1111m
    暗牌 13 张时会自动把「和牌张」补进去；暗牌 14 张时「和牌张」只表示是哪张和的。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                       # 让 Godot / 管道里拿到 UTF-8（不然中文会乱码）
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from tiles import counts_of, format_hand, index_of, parse_hand, sort_tiles   # noqa: E402
from tiles import TILE_KINDS                                                 # noqa: E402
from rules import agari, yaku                                                # noqa: E402


def set_text(s) -> str:
    """面子 → 看得懂的写法：('run',0) → '123m'，('triplet',31) → '555z'"""
    kind, i = s[0], s[1]
    if kind == "run":
        tiles = [TILE_KINDS[i], TILE_KINDS[i + 1], TILE_KINDS[i + 2]]
    else:
        tiles = [TILE_KINDS[i]] * (4 if kind == "kan" else 3)
    return ("杠 " if kind == "kan" else "") + format_hand(tiles)

HONOR_ALIAS = {
    "东": "dong", "南": "nan", "西": "xi", "北": "bei", "白": "bai", "发": "fa", "中": "zhong",
    "dong": "dong", "nan": "nan", "xi": "xi", "bei": "bei", "bai": "bai", "fa": "fa",
    "zhong": "zhong", "east": "dong", "south": "nan", "west": "xi", "north": "bei",
    "d": "dong", "n": "nan", "x": "xi", "b": "bei", "h": "bai", "f": "fa", "z": "zhong",
}
WINDS = ("dong", "nan", "xi", "bei")


def warid(text: str) -> str:
    """把用户写的单张牌变成内部 id：2p / 0s / 1z / 中 / dong 都认。"""
    t = (text or "").strip()
    if not t:
        raise ValueError("和牌张不能为空")
    if t in HONOR_ALIAS:
        return HONOR_ALIAS[t]
    out = parse_hand(t)
    if len(out) != 1:
        raise ValueError(f"和牌张只能写一张：{text}")
    return out[0]


def parse_melds(spec: str) -> list[dict]:
    """'chi:234p,pon:555z,ankan:1111m' → 副露列表"""
    melds: list[dict] = []
    for part in (spec or "").replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"副露写法不对：{part}（应该像 chi:234p、pon:555z、ankan:1111m）")
        kind, tiles_text = part.split(":", 1)
        kind = kind.strip().lower()
        if kind not in ("chi", "pon", "minkan", "ankan", "kakan"):
            raise ValueError(f"不认识的副露类型：{kind}（可用 chi/pon/minkan/ankan/kakan）")
        tiles = parse_hand(tiles_text.strip())
        if kind != "ankan" and len(tiles) != 3 and kind != "minkan" and kind != "kakan":
            raise ValueError(f"{kind} 应该是 3 张；杠要写 4 张")
        melds.append({"kind": kind, "tiles": tiles})
    return melds


def judge_request(req: dict) -> dict:
    """核心接口：dict 进 → dict 出（judge_cli 和测试脚本都用它）"""
    out: dict = {"ok": False}
    try:
        tiles = parse_hand(req.get("hand", ""))
        if not tiles:
            raise ValueError("手牌不能为空")
        melds = parse_melds(req.get("melds", ""))
        win = warid(req["win"]) if req.get("win") else tiles[-1]
        if len(tiles) + 3 * len(melds) == 13:          # 暗牌 13 张 → 补上和牌张
            tiles = tiles + [win]
        out["hand"] = format_hand(sort_tiles(tiles))
        out["win"] = win
        out["tsumo"] = bool(req.get("tsumo"))
        out["melds"] = [f'{m["kind"]}:{format_hand(m["tiles"])}' for m in melds]

        total = len(tiles) + 3 * len(melds)
        if total != 14:
            out["error"] = (f"牌数不对：暗牌 {len(tiles)} 张 + 副露 {len(melds)} 组 "
                            f"= {total} 张（一共应该是 14 张）")
            return out

        counts = counts_of(tiles)
        if not agari.is_winning(counts, melds):
            out["error"] = "这不是和牌型"
            if len(tiles) == 14:                       # 顺便告诉他差什么
                c13 = counts_of(tiles[:-1])
                waits = agari.winning_tiles(c13, melds)
                out["try_waits"] = waits
            return out

        ctx = {
            "counts": counts, "tiles": tiles, "melds": melds, "win_index": index_of(win),
            "is_dealer": bool(req.get("dealer")), "tsumo": bool(req.get("tsumo")),
            "seat_wind": req.get("seat_wind", "dong"), "round_wind": req.get("round_wind", "dong"),
            "riichi": bool(req.get("riichi")), "double_riichi": bool(req.get("double_riichi")),
            "ippatsu": bool(req.get("ippatsu")), "last_tile": bool(req.get("last_tile")),
            "rinshan": bool(req.get("rinshan")), "chankan": bool(req.get("chankan")),
            "tenhou": req.get("tenhou"),
            "dora_indicators": parse_hand(req["dora"]) if req.get("dora") else [],
            "ura_indicators": parse_hand(req["ura"]) if req.get("ura") else [],
            "rules": {"kuitan": not req.get("no_kuitan"),
                      "kiriage_mangan": bool(req.get("kiriage")),
                      "red_fives": True, "double_yakuman": True},
        }
        res = yaku.judge(ctx)
        if not res.get("yaku"):
            out["error"] = "没有役（无役不能和牌）"
            return out
        out.update({
            "ok": True, "yaku": res["yaku"], "han": res["han"], "fu": res["fu"],
            "yakuman": res.get("yakuman", 0), "points": res["pays"],
            "fu_items": res.get("fu_items", []),
            "sets": [list(s) for s in res.get("sets", [])], "pair": res.get("pair"),
            "wait": res.get("wait"),
            "sets_text": [set_text(s) for s in res.get("sets", [])],
            "pair_text": TILE_KINDS[res["pair"]] if res.get("pair", -1) >= 0 else "",
        })
        return out
    except Exception as e:                              # 输入写错也友好报出来
        out["error"] = f"{type(e).__name__}: {e}"
        return out


# ── 命令行 ──────────────────────────────────────────────────────────────────
def _pretty(req: dict, r: dict) -> str:
    L = []
    mode = "自摸" if r.get("tsumo") else "荣和"
    head = f'和牌型：{r.get("hand", "?")}    （{mode} {r.get("win", "?")}）'
    if r.get("melds"):
        head += "   副露：" + "、".join(r["melds"])
    head += (f'   场风 {"东南西北"[WINDS.index(req.get("round_wind", "dong"))]}'
             f' / 自风 {"东南西北"[WINDS.index(req.get("seat_wind", "dong"))]}')
    if req.get("dealer"):
        head += " / 亲家"
    L.append(head)
    if not r.get("ok"):
        L.append("判定：✗ " + str(r.get("error")))
        if r.get("try_waits"):
            L.append("提示：这副牌现在听 " + "、".join(r["try_waits"]))
        return "\n".join(L)

    L.append("役种：" + "、".join(f'{y["name"]} {y["han"]}番' for y in r["yaku"]))
    if r.get("yakuman"):
        L.append(f'番数：役满 ×{r["yakuman"]}')
    else:
        L.append(f'番数：{r["han"]} 番　　符数：{r["fu"]} 符')
        if r.get("fu_items"):
            L.append("符数明细：" + " + ".join(f"{n} {v}" for n, v in r["fu_items"])
                     + f' → 进位到 {r["fu"]} 符')
    p = r["points"]
    if "each" in p and "from_dealer" not in p:         # 荣和
        who = "亲家" if req.get("dealer") else "子家"
        L.append(f'点数：{who}{mode} {p["total"]} 点（放铳者付 {p["total"]}）')
    else:                                              # 自摸
        who = "亲家" if req.get("dealer") else "子家"
        if p.get("from_dealer") == p.get("from_other"):
            L.append(f'点数：{who}自摸 {p["each"]} 点all（共 {p["total"]}）')
        else:
            L.append(f'点数：{who}自摸 亲付 {p["from_dealer"]} / 子付 {p["from_other"]}'
                     f'（共 {p["total"]}）')
    if p.get("limit"):
        L.append(f'段位：{p["limit"]}')
    if r.get("sets_text"):
        waits_cn = {"ryanmen": "两面", "kanchan": "嵌张", "penchan": "边张",
                    "tanki": "单骑", "shanpon": "双碰", "none": "—"}
        L.append("拆解：" + "、".join(r["sets_text"]) + f'　雀头 {r.get("pair_text")}'
                 f'　听牌形 {waits_cn.get(r.get("wait"), r.get("wait"))}')
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="麻将役种/番/符/点 判定")
    ap.add_argument("--hand", default="", help="手牌，如 123m456m789m234p55s")
    ap.add_argument("--win", default="", help="和牌那张，如 2p / 中 / dong")
    ap.add_argument("--melds", default="", help="副露，如 chi:234p,pon:555z")
    ap.add_argument("--dora", default="", help="宝牌指示牌，如 1s（多张连着写 1s5p）")
    ap.add_argument("--ura", default="", help="里宝牌指示牌")
    ap.add_argument("--tsumo", action="store_true", help="自摸（默认荣和）")
    ap.add_argument("--dealer", action="store_true", help="亲家（默认子家）")
    ap.add_argument("--seat-wind", default="auto",
                    choices=list(WINDS) + ["auto"],
                    help="自风（默认 auto：亲家=场风，子家=南）")
    ap.add_argument("--round-wind", default="dong", choices=list(WINDS), help="场风，默认 dong")
    ap.add_argument("--riichi", action="store_true")
    ap.add_argument("--double-riichi", action="store_true")
    ap.add_argument("--ippatsu", action="store_true")
    ap.add_argument("--last-tile", action="store_true", help="海底摸月 / 河底捞鱼")
    ap.add_argument("--rinshan", action="store_true", help="岭上开花")
    ap.add_argument("--chankan", action="store_true", help="抢杠")
    ap.add_argument("--no-kuitan", action="store_true", help="食断不成立")
    ap.add_argument("--kiriage", action="store_true", help="切上满贯")
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    ap.add_argument("--out", default="",
                    help="把 JSON 写到这个文件（Godot 里读不到管道输出，就用这个）")
    a = ap.parse_args()

    req = {k: getattr(a, k.replace("-", "_")) for k in
           ("hand", "win", "melds", "dora", "ura", "tsumo", "dealer", "riichi",
            "double_riichi", "ippatsu", "last_tile", "rinshan", "chankan",
            "no_kuitan", "kiriage")}
    req["seat_wind"] = (a.round_wind if a.dealer else "nan") if a.seat_wind == "auto" else a.seat_wind
    req["round_wind"] = a.round_wind
    r = judge_request(req)
    if a.out:                                   # 先写文件：即使控制台写不出来也不影响
        try:
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(r, f, ensure_ascii=False)
        except Exception as e:                  # noqa: BLE001
            print(f"写文件失败：{e}", file=sys.stderr)
    try:
        print(json.dumps(r, ensure_ascii=False) if a.json else _pretty(req, r))
    except Exception:                           # noqa: BLE001
        pass                                    # 控制台编码有问题就算了，文件里是好的
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
