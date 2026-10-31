# -*- coding: utf-8 -*-
"""复制品 / 传承品「独立配额」回归测试（方案 C）

口径（用户 2026-10-31）：
  · 原技能一份一次性配额，复制 / 传承来的那一份**另算一份**
  · 两者分开记：used_skills（原）/ used_copy（复制品），键同形 "card-skill-seat"
  · 客户端点左侧复制品图标时带 copy=true → 服务端把这一下记到 used_copy
  · 都用完才算「用尽」（skill_used = True）
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

import api_cli                                            # noqa: E402
import game as game_mod                                   # noqa: E402
from game import Game                                     # noqa: E402
import test_game as tg                                    # noqa: E402
import test_chuancheng_copy as tc                         # noqa: E402

PASS = 0
FAIL = 0


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got={got!r} want={want!r}")


def fresh(tag):
    """一个干净的局：0 号位同时有 16（传承）/ 41（复制）/ 24（一次性原技能）"""
    db, rid = tc.make(tag, 880)
    g = Game(db, rid)
    g.granted = {0: {16, 41, 24}, 1: {24}}
    g.cc_copy = {}
    g.c41_copies = {}
    g.cc_grants = set()
    g.used_skills = set()
    g.used_copy = set()
    g.yanjiu = {}
    g.save_flags()
    return db, rid, Game(db, rid)


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · 复制品 / 传承品 独立配额（方案 C）")
    print("=" * 70)

    print("\n① 原技能用掉 → 只动 used_skills，复制品额度还在")
    db, rid, g = fresh("ccq1")
    g.req_copy_key = ""
    g.note_use(0, 24, 1, gate=False)
    check("used_skills 记上原技能", "24-1-0" in g.used_skills)
    check("used_copy 还是空", g.used_copy, set())
    check("原技能那份已用（orig_used=True）", g.orig_used(0, 24, 1))
    check("复制品那份没用（copy_used=False）", g.copy_used(0, 24, 1), False)

    print("\n② 复制 / 传承过来（记住：传承必然是同一个座位同一个卡号）")
    g.cc_grants.add("24-1-0")
    check("有复制品了（copy_granted）", g.copy_granted(0, 24, 1))
    check("复制品那份额度还在（skill_used=False）", g.skill_used(0, 24, 1), False)
    check("原技能用过不影响复制品", g.skill_used(0, 24, 1), False)
    check("按复制品查：还没用", g.copy_used(0, 24, 1), False)
    db.close()

    print("\n③ 点复制品图标发动（req_copy_key 命中）→ 记到 used_copy")
    db, rid, g = fresh("ccq2")
    g.note_use(0, 24, 1, gate=False)          # 原技能
    g.cc_grants.add("24-1-0")
    g.req_copy_key = "24-1"                   # 客户端 copy=true
    check("复制品这发放行（skill_used=False）", g.skill_used(0, 24, 1), False)
    g.note_use(0, 24, 1, gate=False)
    check("复制品记到 used_copy", "24-1-0" in g.used_copy)
    check("used_skills 没被重复写", g.used_skills, {"24-1-0"})
    check("两份都用完 → skill_used=True", g.skill_used(0, 24, 1))
    g.req_copy_key = ""
    check("普通入口也判用尽", g.skill_used(0, 24, 1))
    db.close()

    print("\n④ 复制品先用、原技能后用：互不吞额度")
    db, rid, g = fresh("ccq3")
    g.cc_grants.add("24-1-0")
    g.req_copy_key = "24-1"
    g.note_use(0, 24, 1, gate=False)          # 先用复制品
    check("复制品用掉", g.copy_used(0, 24, 1))
    check("原技能没用", g.orig_used(0, 24, 1), False)
    g.req_copy_key = ""                       # 回到普通入口再看
    check("原技能还能用", g.skill_used(0, 24, 1), False)
    g.note_use(0, 24, 1, gate=False)          # 再用原技能
    check("原技能用掉", g.orig_used(0, 24, 1))
    check("两份都用完", g.skill_used(0, 24, 1))
    db.close()

    print("\n⑤ 别家的同一张卡不受影响")
    db, rid, g = fresh("ccq4")
    g.cc_grants.add("24-1-0")
    g.req_copy_key = "24-1"
    g.note_use(0, 24, 1, gate=False)
    check("1 号位的 24-1 没被动过", g.skill_used(1, 24, 1), False)
    check("1 号位 used_copy 空", g.copy_used(1, 24, 1), False)
    db.close()

    print("\n⑥ 没有复制品时，用一次就彻底不能再发动")
    db, rid, g = fresh("ccq5")
    g.note_use(0, 24, 1, gate=False)
    check("skill_used=True", g.skill_used(0, 24, 1))
    db.close()

    print("\n⑦ state 下发：原技能 / 复制品 分两个列表")
    db, rid, g = fresh("ccq6")
    g.note_use(0, 24, 1, gate=False)
    g.cc_grants.add("24-1-0")
    g.req_copy_key = "24-1"
    g.note_use(0, 24, 1, gate=False)
    st = Game(db, rid).state_for(0)
    check("used_skills 只含原技能", "24-1-0" in (st.get("used_skills") or []))
    check("copy_used 里有复制品", "24-1-0" in (st.get("copy_used") or []))
    check("copy_granted 里有复制品", "24-1-0" in (st.get("copy_granted") or []))
    st1 = Game(db, rid).state_for(1)
    check("别人看不到我的复制品", st1.get("copy_used") or [], [])
    check("别人看不到我复制了啥", st1.get("copy_granted") or [], [])
    db.close()

    print("\n⑧ 客户端 copy=true → op 反查出 (card, skill)")
    check("skill2 → (1,2)", api_cli._op_skill_pair("skill2", {}), (1, 2))
    check("chuancheng → (16,1)", api_cli._op_skill_pair("chuancheng", {}), (16, 1))
    check("deal_skill 带 card/skill", api_cli._op_skill_pair(
        "deal_skill", {"card": 24, "skill": 1}), (24, 1))
    check("state 没有技能", api_cli._op_skill_pair("state", {}), None)
    check("card09_swap 看 req.skill", api_cli._op_skill_pair(
        "card09_swap", {"skill": 2}), (9, 2))

    print("\n⑨ 请求结束后标记要清空（不能漏到下一次）")
    db, rid, _g = fresh("ccq7")
    api_cli.handle({"op": "state", "seat": 0, "round_id": rid}, db.path)
    check("没带 copy → 空", game_mod.REQ_COPY_KEY, "")
    api_cli.handle({"op": "state", "seat": 0, "round_id": rid, "copy": True}, db.path)
    check("state 反查不到技能 → 仍然空", game_mod.REQ_COPY_KEY, "")

    # 探针 op：直接看「派发时 Game 能不能读到这个标记」
    seen = {}

    def _probe(db2, req):
        seen["key"] = game_mod.REQ_COPY_KEY
        seen["game_key"] = Game(db2, req["round_id"]).req_copy_key
        return {"ok": True, "state": None, "events": [], "result": None,
                "round_id": req["round_id"]}

    api_cli.OPS["__probe"] = _probe
    api_cli.handle({"op": "__probe", "seat": 0, "round_id": rid,
                    "card": 24, "skill": 1, "copy": True}, db.path)
    check("带 copy=true → 派发时是 24-1", seen.get("key"), "24-1")
    check("Game 实例也拿到了", seen.get("game_key"), "24-1")
    api_cli.handle({"op": "__probe", "seat": 0, "round_id": rid,
                    "card": 24, "skill": 1}, db.path)
    check("不带 copy → 派发时为空", seen.get("key"), "")
    check("请求结束后清空", game_mod.REQ_COPY_KEY, "")
    db.close()

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
