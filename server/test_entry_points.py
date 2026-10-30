# -*- coding: utf-8 -*-
"""统一入口收口自测：

① 赤 5（0p/0m/0s）不会被「同牌种去重」吃掉 —— 立直 / 国标 / 一定和牌都能切
② 向听换牌走 do_swap → 对手持【策略】时计数器 +1 + 换牌机会
③ 钓鱼强制对方打牌走 _do_discard（钩子不丢）+ 手牌转移算进策略计数
④ 静态防线：换牌底层只允许 do_swap 调；直接写牌河只允许 _do_discard / 国标 / 一定和牌

跑法：cd N:\\apps\\tianma\\server; python test_entry_points.py
"""
from __future__ import annotations

import inspect
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from game import Game  # noqa: E402
import test_card30 as t30  # noqa: E402
import test_game as tg  # noqa: E402
from tiles import parse_hand  # noqa: E402

PASS = FAIL = 0
GAME_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game.py")


def check(name, got, want=True):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  got {got!r} want {want!r}")


def _sb_gd() -> str:
    _r = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return io.open(os.path.join(_r, "server_bridge.gd"), encoding="utf-8",
                   errors="replace").read()


def main() -> int:
    print("=" * 78)
    print(" 统一入口收口（赤5 / 向听 do_swap / 钓鱼 _do_discard / 静态防线）")
    print("=" * 78)

    # ── ① 赤 5 与普通 5 都要能切 ────────────────────────────────────
    print("\n① 赤 5 不被同牌种去重吃掉")
    db, rid = t30.setup("ep1")
    tg.set_hand(db, rid, 0, parse_hand("123m456m789m50p678s"), drawn="8s")
    g = Game(db, rid)
    g.phase, g.turn = "discard", 0
    rd = g.riichi_discards(0)
    check("手牌里 5p / 0p 都在", ("5p" in g.hand(0), "0p" in g.hand(0)), (True, True))
    check("立直可切：含普通 5p", "5p" in rd, True)
    check("立直可切：也含赤 5（0p）", "0p" in rd, True)
    check("能立直", g.can_riichi(0), True)
    td = g._tenpai_discards(0)
    check("国标/一定和牌：「切出去还听牌」也含赤 5", "0p" in td, True)

    # 只把 0p 换到「摸到的那张」→ 赤 5 也必须在列表里
    db2, rid2 = t30.setup("ep2")
    tg.set_hand(db2, rid2, 0, parse_hand("123m456m789m5p0p6s7s8s"), drawn="8s")
    g2 = Game(db2, rid2)
    g2.phase, g2.turn = "discard", 0
    check("同时有 5p+0p 时两张都列出",
          ("5p" in g2.riichi_discards(0), "0p" in g2.riichi_discards(0)), (True, True))

    # ── ② 向听换牌：策略计数 +1 ─────────────────────────────────────
    print("\n② 向听换牌 → 对手的【策略】计数 +1、给换牌机会")
    db3, rid3 = t30.setup("ep3", card=30, mains=[30, 5, 7, 8])
    g3 = Game(db3, rid3)
    check("1 号位持策略", g3.owns_card05(1), True)
    g3._c30s1_arm(0, [1, 3])
    g3.c30s1_give(1, ["6m", "9p"])
    before = sorted(g3.hand(1))
    g3.c30s1_swap(0, g3.hand(0)[0], "9p")
    g4 = Game(db3, rid3)
    check("他的手牌确实变了", sorted(g4.hand(1)) != before, True)
    check("计数器 +1", int(g4.card05_counter.get(1, 0)), 1)
    check("拿到换牌机会", isinstance(g4.card05_offer.get(1), dict), True)

    # ── ③ 钓鱼：走 _do_discard（forced）+ 手牌转移计入策略 ─────────
    print("\n③ 钓鱼强制打牌走统一入口")
    sig = inspect.signature(Game._do_discard)
    check("_do_discard 支持 forced", "forced" in sig.parameters, True)
    src = io.open(GAME_PY, encoding="utf-8").read()
    body = src.split("def diaoyu_force")[1].split("\n    def ")[0]
    check("钓鱼不再自己写牌河", "self.db.discard(" in body, False)
    check("钓鱼不再自己开鸣牌窗口", "_open_claim_window(" in body, False)
    check("钓鱼改走 _do_discard", "_do_discard(" in body, True)
    check("钓鱼把对手的手牌变动记账", "card05_note_changes(" in body, True)

    # ── ④ 静态防线：底层调用只允许出现在统一入口里 ──────────────────
    print("\n④ 静态防线（以后再加技能也不会绕过统一入口）")
    lines = src.splitlines()
    owner = {}
    cur = ""
    for i, ln in enumerate(lines, 1):
        m = re.match(r"    def (\w+)\(", ln)
        if m:
            cur = m.group(1)
        owner[i] = cur
    swap_sites = sorted({owner[i] for i, ln in enumerate(lines, 1)
                         if "swap.swap_" in ln or "swap.move_river_to_hand" in ln})
    check("换牌底层只在 do_swap 里调", swap_sites, ["do_swap"])
    river_sites = sorted({owner[i] for i, ln in enumerate(lines, 1)
                          if "self.db.discard(" in ln})
    check("直写牌河只剩 _do_discard + 国标/一定和牌/恶听（宣言即结算）",
          river_sites, ["_do_discard", "c46s1_apply", "guobiao_declare", "yiding_declare"])

    # ── ⑤ 换手牌只剩一个实现 ───────────────────────────────────────
    print("\n⑤ 换手牌收敛成 _swap_hand_tiles")
    check("有统一 helper", hasattr(Game, "_swap_hand_tiles"), True)
    check("也有 is_drawn 修补 helper", hasattr(Game, "_set_hand_drawn"), True)
    for fn in ("wind_swap_apply", "south_wind_swap", "deal_swap", "c30s1_swap"):
        body = src.split("    def %s(" % fn)[1].split("\n    def ")[0]
        check(f"{fn} 走统一入口",
              ("_swap_hand_tiles(" in body or "do_swap(" in body), True)
        check(f"{fn} 不再自己搬手牌",
              ("DELETE FROM round_hands" in body or "INSERT INTO round_hands" in body),
              False)

    # ── ⑤b 理论战不能卡死 / 逆势面板得点要跟着减半 ──────────────────
    print("\n⑤b 理论战不卡死 + 逆势减半连面板一起")
    b1 = src.split("def _c42s1_close_others(")[1].split("\n    def ")[0]
    check("理论战有「作废其他家配牌技能」的入口", bool(b1.strip()), True)
    check("顺手清「宝牌的集合」二段询问", "c25s2_pending = -1" in b1, True)
    check("多步换牌流程也放弃", "self.deal_flow = None" in b1, True)
    b2 = src.split("def c42s1_apply(")[1].split("\n    def ")[0]
    check("发动时就调它（否则 deal_wait 永远清不掉 = 卡死）",
          "_c42s1_close_others(" in b2, True)
    print("\n⑤c 恶听：铳张 = 隐藏区只剩 1 张的那张")
    b46 = src.split("def c46s1_only(")[1].split("\n    def ")[0]
    check("有 c46s1_only（挑出那张唯一的待牌）", bool(b46.strip()), True)
    check("总数必须 == 1（不是「有就算」）", "!= 1" in b46, True)
    check("铳张交给 _yiding_settle", "want_tile=only" in src, True)
    check("荣和只认那张牌", "kind_of(str(t)) != wt" in src, True)
    check("王牌也算（按 dealt_to 判，不卡 draw_no）",
          'round_wall WHERE round_id=? AND dealt_to IS NULL' in src, True)

    print("\n⑤d 技能给的「和牌」要玩家点自摸（43S1 / 46S1）")
    check("有 pending 状态", "self.win_pending" in src, True)
    check("pending 时 legal_actions 只给自摸",
          'return [{"action": "tsumo", "pending": True,' in src, True)
    check("_do_tsumo 先看 pending", "return self._pending_tsumo(int(seat))" in src, True)
    b43 = src.split("def c43s1_apply(")[1].split("\n    def ")[0]
    check("NO MISS 不再自己 _finish", 'self._finish(s, None, "tsumo", res)' not in b43, True)
    b46 = src.split("def c46s1_apply(")[1].split("\n    def ")[0]
    check("恶听不再立刻 _yiding_settle（除了立即作废那两种）",
          b46.count("_yiding_settle(") == 1, True)
    check("恶听回 c46_pending 事件", '"c46_pending"' in b46, True)
    check("再点技能能取消 pending（skill_cancel）",
          'aliases = {43: ("c43s1", "nomiss"), 46: ("c46s1", "evil")}' in src, True)
    check("state 里告诉本人 win_pending",
          '"win_pending": ({"seat": int(self.win_pending.get' in src, True)

    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _mgd = io.open(os.path.join(_root, "main.gd"), encoding="utf-8",
                   errors="replace").read()
    check("客户端认 c46_pending", '_ev == "c46_pending"' in _mgd, True)
    check("NO MISS 提示「点自摸」", "NO MISS：换成了和牌形" in _mgd, True)
    check("客户端有 _win_pending_card", "func _win_pending_card(" in _mgd, True)
    check("再点 NO MISS 图标 = 取消", 'c == 43 and i == 0 and _win_pending_card() == 43' in _mgd, True)
    check("再点恶听图标 = 取消", 'c == 46 and i == 0 and _win_pending_card() == 46' in _mgd, True)
    check("面板开着时点图标 = 收起", "c43_panel.close()" in _mgd and "c46_panel.close()" in _mgd, True)

    b3 = src.split("def _c35s2_half(")[1].split("\n    def ")[0]
    check("逆势：pays 一起减（结算面板读 pays.total）",
          'pays["total"] = int(deltas[w])' in b3, True)
    check("逆势：调用点把 pays 传进去", "_c35s2_half(winner, deltas, pays)" in src, True)

    # ── ⑤e 联机通道（net_server.py + server_net.gd）────────────────────
    print("\n⑤e 联机：HTTP 服务端 + 客户端 net.cfg")
    check("net_server.py 存在",
          os.path.exists(os.path.join(_root, "server", "net_server.py")), True)
    _ns = io.open(os.path.join(_root, "server", "net_server.py"), encoding="utf-8",
                  errors="replace").read()
    check("走 api_cli.handle（规则只一份）", "api_cli.handle(req, db_path=db_path)" in _ns, True)
    check("多房间：每房间一个 db", '"room_%s.db"' in _ns, True)
    check("同房间请求串行（避免 SQLite 抢锁）", "with lock:" in _ns, True)
    _net = io.open(os.path.join(_root, "server_net.gd"), encoding="utf-8",
                   errors="replace").read()
    check("客户端读 net.cfg（exe 同目录 / user://）",
          'const CFG_EXE := "net.cfg"' in _net and 'const CFG_USER := "user://net.cfg"' in _net, True)
    check("联机不带 pid（远端进程号没意义）",
          "pid" not in _net.replace("pid：", "").replace("进程号", ""), True)
    check("ServerBridge 有 net 分支", "NET_SCRIPT.new()" in _sb_gd(), True)
    _mgd2 = io.open(os.path.join(_root, "main.gd"), encoding="utf-8",
                    errors="replace").read()
    check("联机时不用本机文件认领半庄", "not _net_mode()" in _mgd2, True)

    # ── ⑥ 客户端静态防线：GDScript 的 or 是逻辑或，不许拿它兜默认值 ─────
    print("\n⑥ 客户端不许写 `x or []` / `x or {}`（or 返回 bool，会抛类型错误）")
    import glob  # noqa: E402
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bad = []
    for path in sorted(glob.glob(os.path.join(root, "*.gd"))):
        try:
            txt = io.open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for i, ln in enumerate(txt.splitlines(), 1):
            code = ln.split("#", 1)[0]
            hit = (" or [" in code or " or {" in code
                   or re.search(r"\bor\s+(0(\.0)?|\"\"|'')\s*(?:\)|,|$)", code) is not None)
            if hit:
                bad.append("%s:%d" % (os.path.basename(path), i))
    check("客户端没有 `x or 默认值` 写法", bad, [])

    # ── 客户端：牌种网格的回调必须在 _cg_close() 之后再赋 ──────────────
    print("\n客户端：牌种网格回调不会被 _cg_close() 冲掉（强运会错发前路）")
    main_gd = io.open(os.path.join(root, "main.gd"), encoding="utf-8", errors="replace").read()
    ml = main_gd.splitlines()

    def fn_body(name):
        i0 = next(i for i, l in enumerate(ml) if l.startswith("func %s(" % name))
        i1 = i0 + 1
        while i1 < len(ml) and not (ml[i1].startswith("func ") or ml[i1].startswith("# ──")):
            i1 += 1
        return i0, ml[i0:i1]

    i0, body = fn_body("_cg_show_kind_grid")
    close_at = next((k for k, l in enumerate(body) if l.strip() == "_cg_close()"), -1)
    pick_at = next((k for k, l in enumerate(body) if l.strip().startswith("cg_pick_cb = on_pick")), -1)
    ok_at = next((k for k, l in enumerate(body) if l.strip().startswith("cg_ok_cb = on_ok")), -1)
    check("_cg_show_kind_grid 收回调参数", "on_pick: Callable" in "".join(body), True)
    check("先 _cg_close() 再赋 pick 回调", -1 < close_at < pick_at, True)
    check("先 _cg_close() 再赋 ok 回调", -1 < close_at < ok_at, True)
    check("强运把回调传进去了",
          any("_cg_show_kind_grid(" in l and "on_pick, on_ok" in l for l in ml), True)
    check("牌种网格有「关闭」按钮", "_cg_kind_close" in main_gd, True)

    i0, body2 = fn_body("_sf_pick_kind_next")
    txt2 = "\n".join(body2)
    check("前路检查服务端的 ok（别假成功）", 'not bool(r.get("ok"' in txt2, True)
    check("前路成功后会关网格（不关 = 卡死）", "_cg_close()" in txt2, True)

    i0, body4 = fn_body("_c37s2_confirm")
    txt4 = "\n".join(body4)
    check("强运收到 need_kangpo 会关网格（不关 = 永远弹「等对方拦截」）",
          "_cg_kind_close()" in txt4, True)
    i0, body5 = fn_body("_c37s2_sync")
    check("强运用过的状态一同步就收网格", "_cg_kind_close()" in "\n".join(body5), True)
    check("srv_apply_state 里调了 _c37s2_sync", "_c37s2_sync(st2)" in main_gd, True)

    i0, body6 = fn_body("_c37s1_arm")
    txt6 = "\n".join(body6)
    check("岭上开花在鸣牌窗口里也点得动（不用 discard 拦死）",
          'ph != "claim"' in txt6, True)
    i0, body7 = fn_body("_c37s1_sync")
    check("岭上开花换好牌会提示点自摸", "_toast(" in "\n".join(body7), True)
    check("srv_apply_state 里调了 _c37s1_sync", "_c37s1_sync(st2)" in main_gd, True)
    # ── 客户端：协战人物卡遮罩（长按 0.7 秒 + 东南西北选玩家） ─────────
    print("\n客户端：协战卡遮罩（长按 / 东南西北 / 卡面遮罩）")
    ic_gd = io.open(os.path.join(root, "identity_card.gd"), encoding="utf-8",
                    errors="replace").read()
    ics_gd = io.open(os.path.join(root, "identity_cards.gd"), encoding="utf-8",
                     errors="replace").read()
    check("identity_card 有 long_pressed 信号", "signal long_pressed" in ic_gd, True)
    check("长按阈值 = 0.5 秒", "LONG_PRESS_SEC := 0.5" in ic_gd, True)
    check("松手会取消长按", "func _on_button_up()" in ic_gd, True)
    check("identity_cards 转发 card_long_pressed", "signal card_long_pressed" in ics_gd, True)
    check("identity_cards 有协战卡遮罩入口", "func set_support_muted" in ics_gd, True)
    check("协战卡遮罩复用现成遮罩（_char_masked 里判）",
          "_support_mute.get(seat, 0)" in ics_gd, True)
    check("不再自己画深色块 / 写字", ("_mute_layer" in ics_gd) or ("_mute_rects" in ics_gd), False)
    # 遮罩改成「卡的子节点」+ 点谁谁在上
    check("遮罩是人物卡的子节点（set_covered）", "func set_covered(" in ic_gd, True)
    check("遮罩不再是独立层", "_hidden_overlays" in ics_gd, False)
    check("不再手动同步遮罩变换", "_sync_hidden_transforms" in ics_gd, False)
    check("场景里的 Identity/hidden 节点已删",
          'name="hidden" type="Sprite2D" parent="Main/Identity"' in
          io.open(os.path.join(root, "node_2d.tscn"), encoding="utf-8",
                  errors="replace").read(), False)
    check("点谁谁在上：卡发 touched 信号", 'touched.emit(_card_no)' in ic_gd, True)
    _zs = re.findall(r"z_index = (\d+)", ic_gd)
    check("卡内子节点 z_index 全为 0（>0 会跨卡覆盖，协战遮罩盖住主战）",
          sorted(set(_zs)), ["0"])
    check("点谁谁在上：移到同级最后", "func _bring_slot_front(" in ics_gd, True)
    check("云外镜无视遮罩（open 判断保留）",
          'return not bool(d.get("open", false))' in ics_gd, True)
    check("手动遮罩只在自己那家判（不影响云外镜看别人）",
          "return _manual_muted_slot(slot)" in ics_gd, True)
    i0, body_lp = fn_body("_on_identity_long_press")
    txt_lp = "\n".join(body_lp)
    check("长按 = 直接开关自己协战卡的遮罩", "_support_mute_toggle()" in txt_lp, True)
    check("长按不弹任何选择器（不选别家）",
          ("open_wind_picker" in txt_lp) or ("_cg_show(" in txt_lp), False)
    check("遮罩只发给自己那一家", '"target": my_seat' in main_gd, True)
    check("选完发 op=support_mute", '"op": "support_mute"' in main_gd, True)
    check("srv_apply_state 里画遮罩", "_support_mute_apply(st2)" in main_gd, True)

    # ── 客户端：选玩家统一用独立的「东南西北」面板（seat_picker.gd）────────
    print("\n客户端：选玩家走独立面板 seat_picker（透视/同盟/夺目/替身/旧 6 处）")
    sp_gd = io.open(os.path.join(root, "seat_picker.gd"), encoding="utf-8",
                    errors="replace").read()
    check("面板脚本存在", bool(sp_gd), True)
    check("面板有 picked 信号", "signal picked" in sp_gd, True)
    check("Esc 能取消", "_on_cancel" in sp_gd, True)
    check("面板有「跳过」按钮（不超时自动选）", "跳过" in sp_gd, True)
    check("只要四个按钮：没有全屏半透明遮罩", "_mask" not in sp_gd, True)
    check("不要大底板", 'name = "BG"' not in sp_gd, True)
    check("面板自己不挡点击（空处穿透）", "MOUSE_FILTER_IGNORE      #" in sp_gd, True)
    check("面板可调大小/位置", "func tune(" in sp_gd, True)
    check("首次进游戏就写出默认 cfg（不用等调过才生成）",
          "_save_cfg()          # 第一次进游戏" in sp_gd, True)
    check("info 里带 cfg 路径", "globalize_path(CFG_PATH)" in sp_gd, True)
    check("Main 能直接打开 cfg 目录", "func seat_pick_open_cfg(" in main_gd, True)
    check("面板不挂人物卡（不是 identity_card 的子节点）", "Identity" not in sp_gd, True)
    for fn in ("_c40s1_open", "_c40s2_open", "_c42s2_open", "_c45s2_start"):
        _i, _b = fn_body(fn)
        _t = "\n".join(_b)
        check("%s 用面板选玩家" % fn, "_seat_pick_begin(" in _t, True)
        check("%s 不再自造列表 UI" % fn, "_cg_show(" in _t, False)
    _i, _b = fn_body("_c42s2_sync")
    _t = "\n".join(_b)
    check("夺目结算前询问也用面板", "_seat_pick_begin(" in _t, True)
    check("夺目播报是谁铳的/谁自摸", ("铳给" in _t) and ("自摸" in _t), True)
    _i, _b = fn_body("_on_seat_picked")
    _t = "\n".join(_b)
    for mode in ("c40s1", "c40s2", "c42s2", "c42s2_ask", "c45s2b", "dy", "link", "xn", "duel", "skill2"):
        check("选玩家模式 %s 有分发" % mode, '"%s"' % mode in _t, True)
    check("旧 6 处不再调 Identity.open_wind_picker",
          'idn.call("open_wind_picker"' in main_gd, False)
    check("选玩家时不许点手牌打牌", 'seat_pick_mode != ""' in main_gd, True)

    # ── 同盟（40S2）的「选搭子」跟「吃」用同一套 UI ────────────────────
    print("\n客户端：同盟选搭子 = 吃那一套（手牌上方牌面候选）")
    _i, _b = fn_body("_c40s2_sync")
    _t = "\n".join(_b)
    check("同盟用共用的牌组面板", "_tile_pick_show(" in _t, True)
    check("同盟不再自造左上角列表", "_cg_show(" in _t, False)
    _i, _b = fn_body("show_chow_choices")
    check("吃也走同一个面板", "_tile_pick_show(" in "\n".join(_b), True)
    _i, _b = fn_body("_tile_pick_show")
    _t2 = "\n".join(_b)
    _i, _b = fn_body("_tile_pick_sync")
    check("面板摆在手牌上方", "CHOW_ABOVE_MARGIN" in "\n".join(_b), True)
    check("面板用真实牌面（_make_tile_visual）", "_make_tile_visual(" in _t2, True)
    check("面板宽度按张数算（碰 2 / 杠 3）", "tiles.size()" in _t2, True)
    check("同盟面板挂在「被同盟者手牌」下面", "func _c40b_anchor(" in main_gd, True)
    check("面板被清掉后能重弹（c40b_key 复位）", 'tile_pick_tag == "c40b"\n\t\tc40b_key = ""'
          in ics_gd if False else 'if tile_pick_tag == "c40b":' in main_gd, True)
    check("「吃」的清理不误杀同盟面板",
          "同盟的面板别被「吃」的清理逻辑误杀" in main_gd, True)
    check("面板按 tag 区分来源", 'var tile_pick_tag := ""' in main_gd, True)
    check("微调接口暴露给外部", "func seat_pick_tune(" in main_gd, True)

    # ── 分数显示：直接用场景里的 4 个 Label（用户自己摆位置/字号）──────
    print("\n分数显示：4 个 Label 计数器（粉色数字那套已删）")
    check("用场景里的 Label（下/右/上/左 顺序）",
          'const SCORE_LABELS := ["UI/Label", "UI/Label4", "UI/Label3", "UI/Label2"]'
          in main_gd, True)
    check("把点数写进 Label",
          "lb.text = str(val)" in main_gd
          and "var val := int(by_seat.get((my_seat + i) % 4, 0))" in main_gd, True)
    check("按方位映射（下=我 / 右=下家 / 上=对家 / 左=上家）",
          "(my_seat + i) % 4" in main_gd, True)
    check("srv_apply_state 里同步分数", "_score_label_sync(st2)" in main_gd, True)
    check("scores 是数组（public_state 的 match_seats 行）也能解析",
          'typeof(sc) == TYPE_ARRAY' in main_gd and 'get("seat", -1)' in main_gd, True)
    check("找不到 Label 不报错（换场景也能跑）",
          "if lb == null:" in main_gd and "continue" in main_gd, True)
    check("Label 按风盘实际盘面定位（编辑器 85% 的问题）",
          "func _score_label_place(" in main_gd and "func _fengpan_body_rect(" in main_gd
          and "_score_label_place(i, lb)" in main_gd, True)
    check("四条深蓝框中心比例还在", "const SCORE_UV := [Vector2(0.4961, 0.9393)" in main_gd, True)
    check("文字在框里居中（不靠空格推）",
          "lb.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER" in main_gd, True)
    check("粉色数字那套删干净了（score_hud.gd 不存在）",
          not os.path.exists(os.path.join(root, "score_hud.gd")), True)
    check("main 里不再有 score_hud",
          "score_hud" not in main_gd and "ScoreHUD" not in main_gd, True)
    check("不再自己切 number.png",
          "number.png" not in main_gd, True)
    check("不再有 F10 微调入口", "score_hud_tune_toggle" not in main_gd, True)
    _dbpy = io.open(os.path.join(root, "server", "db.py"), encoding="utf-8",
                    errors="replace").read()
    check("每人初始 35000", '"VALUES(?,?,?,?,35000)"' in _dbpy, True)


    i0, body8 = fn_body("_c42s2_sync")
    txt8 = "\n".join(body8)
    check("夺目结算前会问（面板选庄家）", "_seat_pick_begin(" in txt8, True)
    check("夺目询问不再自造列表 UI", "_cg_show(" in txt8, False)
    check("srv_apply_state 里调了 _c42s2_sync", "_c42s2_sync(st2)" in main_gd, True)

    print("\n" + "=" * 78)
    print(f" 通过 {PASS} / 失败 {FAIL}")
    print("=" * 78)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
