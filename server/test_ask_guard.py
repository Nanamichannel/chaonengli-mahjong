# -*- coding: utf-8 -*-
"""静态守卫：摸牌前询问「弹出来不能被自动跳过」。

背景（2026-11-06 现场）：P3 把 `draw_tile()` 改成「看到询问锁 → 当成玩家跳过」，
结果 state 同步末尾的 `_auto_draw_if_my_turn()` 一调，刚弹出来的海神/降神面板
就被自己关掉 → 表现成「摸牌前不问我」。

这里不跑对局，只读 `main.gd` 源码断言三条不变量，防止再犯：
  ① draw_tile 的询问锁分支必须先看「面板开没开」
  ② _drop_pre_draw_ask 的面板开着时拒绝丢弃
  ③ _pre_draw_panel_open 覆盖全部 7 种摸牌前面板

用法：cd server; python test_ask_guard.py
"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, "main.gd")
SKILLPANEL = os.path.join(ROOT, "skill_panel.gd")
KANSHOU = os.path.join(ROOT, "kan_shou.gd")
TILEPIECE = os.path.join(ROOT, "tile_piece.gd")
KANCAM = os.path.join(ROOT, "kan_shou_camera.gd")
UISFX = os.path.join(ROOT, "ui_sfx.gd")
PROJECT = os.path.join(ROOT, "project.godot")
PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}")


def block(src: str, start: str, end: str) -> str:
    """取 start 之后、end 之前的那一段（找不到就回空串）。"""
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i + len(start))
    if j < 0:
        return src[i:]
    return src[i:j]


def main() -> int:
    print("=" * 70)
    print(" 天才麻将少女 · 摸牌前询问：静态守卫")
    print("=" * 70)

    src = io.open(MAIN, encoding="utf-8").read()

    print("\n① draw_tile：询问锁挡着时要先看面板开没开")
    dt = block(src, "func draw_tile() -> void:", "func _perf_sample")
    check("draw_tile 存在", bool(dt))
    check("含 _prompt_blocked 分支", "_prompt_blocked()" in dt)
    check("分支里先判 _pre_draw_panel_open", "_pre_draw_panel_open()" in dt)
    check("分支里才调 _drop_pre_draw_ask", "_drop_pre_draw_ask()" in dt)
    # 顺序：panel_open 必须在 drop 之前（否则又会先丢）
    i_panel = dt.find("_pre_draw_panel_open()")
    i_drop = dt.find("_drop_pre_draw_ask()")
    check("panel_open 在 drop 之前", 0 <= i_panel < i_drop)

    print("\n② _drop_pre_draw_ask：面板开着就拒绝丢弃")
    dd = block(src, "func _drop_pre_draw_ask() -> bool:", "func _hs_drop_ask")
    check("_drop_pre_draw_ask 存在", bool(dd))
    check("开头有 _pre_draw_panel_open 守卫", "_pre_draw_panel_open()" in dd)
    check("守卫里带 hs_active", "hs_active" in dd)
    check("守卫在发请求之前",
          dd.find("_pre_draw_panel_open()") < dd.find("pre_draw_skip"))

    print("\n③ _pre_draw_panel_open 覆盖 7 种摸牌前面板")
    pp = block(src, "func _pre_draw_panel_open() -> bool:", "func _pre_draw_watchdog")
    for name, token in (("降神 oracle_ui", "oracle_ui"),
                        ("间合 c09_active", "c09_active"),
                        ("炸裂 zl_active", "zl_active"),
                        ("天梯 c26_active", "c26_active"),
                        ("海神 hs_active", "hs_active"),
                        ("未来 future_ask_ui", "future_ask_ui"),
                        ("未来 future_active", "future_active"),
                        ("神境 c45_panel", "c45_panel")):
        check(f"覆盖 {name}", token in pp)

    print("\n④ 询问面板由 state 驱动（客户端不再自己判断时机）")
    check("有 _pre_draw_asks_sync", "func _pre_draw_asks_sync" in src)
    check("srv_apply_state 里调用了它", "_pre_draw_asks_sync(st2)" in src)
    g = block(src, "func _pre_draw_gate() -> bool:", "func draw_tile")
    check("_pre_draw_gate 只判面板", "_pre_draw_panel_open()" in g)
    check("_pre_draw_gate 不再自己调技能闸门", "call(m)" not in g)

    print("\n⑤ 每个摸牌前闸门都认遮罩（否则盖了遮罩还照样弹面板）")
    import re
    gates = [m for m in re.finditer(r"^func (_\w*gate_before_draw)\(", src, re.M)]
    check("摸牌前闸门 >= 10 个", len(gates) >= 10)
    for m in gates:
        name = m.group(1)
        i = m.start()
        j = src.find("\nfunc ", i + 10)
        body = src[i:j if j > 0 else len(src)]
        if name.startswith("_hs_gate"):
            # 海神 12-1：用户口径「摸牌前必须问、屏蔽不掉」，不判遮罩是对的
            check(f"{name}（海神）不判遮罩", "is_skill_muted(" not in body)
            continue
        check(f"{name} 认遮罩", "is_skill_muted(" in body)

    print("\n⑥ 取消统一（用户口径 2026-11-15）")
    check("有 _cancel_top_ask 三态调度器", "func _cancel_top_ask() -> String:" in src)
    for t in ('return "canceled"', 'return "blocked"', 'return "none"'):
        check(f"三态分支 {t}", t in src)
    check("拦截询问按 aid 逐条放行", '_kp_answer(best, "pass")' in src)
    check("不再用 kangpo_answer(use=false)", '\"op\": \"kangpo_answer\"' not in src)
    kps = block(src, "func _kp_skip() -> void:", "func _kp_close")
    check("_kp_skip 委托统一调度器", "_cancel_one_intercept()" in kps)
    i_match = src.find("match _cancel_top_ask():")
    i_disc = src.find("quick_discard_drawn()", i_match) if i_match > 0 else -1
    check("右键先取消、none 才摸切", 0 <= i_match < i_disc)
    check("ESC = 全局取消", "if _k.keycode == KEY_ESCAPE:" in src)
    check("强制态闸门 _force_busy", "func _force_busy() -> bool:" in src)
    check("取消按钮在确认右侧", "func cancel_btn_rect(aspect: float) -> Rect2:" in src)
    check("强制态灰按钮", "if not enabled:\n\t\tb.disabled = true" in src)
    sp = io.open(SKILLPANEL, encoding="utf-8").read()
    check("SkillPanel 内置取消按钮", "var cbtn: TextureButton" in sp and "mk_cancel_btn" in sp)
    check("SkillPanel 取消回调", "func _do_cancel() -> void:" in sp)
    proj = io.open(PROJECT, encoding="utf-8").read()
    check("长按=右键 已移除", "mobile_input" not in proj)
    ks = io.open(KANSHOU, encoding="utf-8").read()
    check("鉴赏右上角跳过按钮", "SKIP_TEX" in ks and "func _make_skip_ui() -> void:" in ks)
    check("鉴赏放大态点空白缩回", "_big.get_global_rect().has_point(mp)" in ks)
    check("触屏手牌：单击=悬浮（等上浮再过牌）",
          "_tap_hover_fresh" in src and "if _tap_hover_idx == int(index) and _tap_hover_fresh:" in src)
    tp = io.open(TILEPIECE, encoding="utf-8").read()
    check("手牌悬浮音在移动端强行播", 'UiSfx.play("hover", UiSfx.DEFAULT_DB, true)' in tp)
    us = io.open(UISFX, encoding="utf-8").read()
    check("ui_sfx.play 有 force 口子", "volume_db := DEFAULT_DB, force := false" in us
          and "and not force" in us)
    check("立直切牌走同一条链", "if riichi_selecting:\n\t\treturn false" not in src)
    kc = io.open(KANCAM, encoding="utf-8").read()
    check("鉴赏：拖动 = 中键拖动（触屏平移）",
          "InputEventScreenDrag" in kc and "TOUCH_DRAG_TOL" in kc
          and "tap_blocked_until" in kc)
    check("鉴赏：拖动后不误触发点按", "func _tap_blocked() -> bool:" in ks)
    check("小鲸鱼开关一次点按只切一次",
          "func _round_info_btn_toggled() -> void:" in src
          and "_round_info_eat_btn" in src
          and "_round_info_btn.pressed.connect(_round_info_btn_toggled)" in src)

    print("\n" + "=" * 70)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
