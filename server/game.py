# -*- coding: utf-8 -*-
"""
权威服务器对局流程（状态机）
=====================================================================
所有判定都在这里做：该谁摸、能打什么、能不能吃碰杠、能不能和、和了多少钱。
客户端只能「请求」，服务器说了算。

一回合：
    draw（服务器自动帮该家摸）→ discard（该家打牌/立直/自摸/杠）
      → 有人打牌后开「鸣牌窗口」claim（其余三家可以荣和/碰/杠/吃）
      → 没人鸣 → 下一家摸；有人鸣 → 鸣的那家出牌

用法：
    g = Game(db, round_id); g.start()
    while g.phase != "ended":
        if g.phase == "draw": g.advance()
        else: g.act(seat, "discard", tile="5m")     # 或 chi/pon/ron/pass…
    g.state_for(0)
"""

from __future__ import annotations

import json
import math
import time
import random

from db import DB
from rules import agari, calls, score, swap, tenpai, wallmodel, yaku
import skills

import testfile
from tiles import (TILE_KINDS, counts_of, dora_from_indicator, index_of,
                   is_honor, is_red, kind_of, tile_number)   # noqa: E402

# 技能在结算时能交给判番函数的「开关」：只允许改这几个 ctx 键，
# 防止技能把 counts / tiles / melds 这些核心字段改坏。
#   pattern_bonus → 五门齐 / 花龙 / 三色三步高 算番（国标 Card01 S1 专有）
_CTX_EXTRA_KEYS = {"pattern_bonus", "dora_void_kan", "dora_bonus_han"}


def is_taatsu(tiles) -> bool:
    """2 张是不是「搭子」：对子 / 两面 / 嵌张 / 边张。

    · 数牌：同花色且数字差 ≤ 2（差 0 = 对子）
    · 字牌：只有成对才算
    """
    ts = [str(t) for t in (tiles or [])]
    if len(ts) != 2:
        return False
    try:
        ia = index_of(kind_of(ts[0]))
        ib = index_of(kind_of(ts[1]))
    except KeyError:
        return False
    if ia >= 27 or ib >= 27:                  # 字牌
        return ia == ib
    if ia // 9 != ib // 9:                    # 不同花色
        return False
    return abs(ia - ib) <= 2


def _apply_judge_opts(ctx: dict, opts: dict | None) -> None:
    """把技能给的判番开关合进 ctx（白名单，静默忽略不认识的键）。"""
    for k, v in (opts or {}).items():
        if k in _CTX_EXTRA_KEYS:
            ctx[k] = v

# 鸣牌优先级：荣和最高，其次碰/杠，最后吃；同级按离放铳者的远近
CLAIM_PRIORITY = {"ron": 3, "minkan": 2, "pon": 2, "chi": 1}

# ── 场次（半庄的第几场）──────────────────────────────────────────────
# 对外只保留两个信息：东一..东四 / 南一..南四，以及几本场。
ROUND_WIND_CN = {"dong": "东", "nan": "南", "xi": "西", "bei": "北"}
ROUND_NUM_CN = ("一", "二", "三", "四")


def round_name(wind: str, number: int) -> str:
    """dong/1 → 东一，nan/4 → 南四。"""
    w = ROUND_WIND_CN.get(wind, "东")
    n = ROUND_NUM_CN[number - 1] if 1 <= number <= 4 else str(number)
    return f"{w}{n}"



# 「发动点在配牌」的技能：只看破一次（降神 7-1 / 点燃(炸裂) 14-1 / 炸裂 14-2 / 海神 12-1）
# 配牌技能阶段等人类决定的最长时间：超了就自动跳过（否则整局卡在配牌阶段）
DEAL_SKILL_TIMEOUT = 20.0
YOUYIN_MELD_TIMEOUT = 20.0         # 友引段1 摊面子等太久 → 服务端自己收尾
FUTURE_N = 5                        # 未来（24S2）：调接下来 5 张牌山
FUTURE_TIMEOUT = 30.0               # 已经发动、等着排序：太久没动就放弃（别卡死整桌）
C26_TIMEOUT = 30.0                  # 天梯（26S2）：摸牌前排牌山，太久没动就直接摸
C26_N0 = 1                          # 天梯计数器 n 的初始值（用户口径：从 1 开始 → 第一次排 2 张）

ONCE_PAIRS = {(7, 1), (14, 1), (14, 2), (12, 1),
              (3, 2)}      # 压制：可以多次换牌，看破只问一次


class RuleError(Exception):
    """玩家动作不合规则。"""


# 流局原因 → 存进 rounds.result 的名字。
#   · 荒牌流局（牌山摸完）→ "ryuukyoku"：本场 +1，亲家听牌就连庄
#   · 途中流局（九种九牌/四风连打/四家立直/四杠散了/三家和了）→ 用原因名本身：
#     本场不动、亲家不动（重打这一局），立直供托退还本人
# 之所以要分开存：op="next" 必须能一眼看出「是荒牌还是途中」，否则没法算连庄。
def _draw_result_name(reason: str) -> str:
    return "ryuukyoku" if reason == "exhaustive" else reason


# 暖系 = 牌面画里有红色：所有万子、红中、赤宝、5s/7s/9s；其余为冷系
WARM_KINDS = ({f"{n}m" for n in range(1, 10)} | {"0m", "0p", "0s", "zhong",
                                                 "5s", "7s", "9s"})
COLD_KINDS = [k for k in TILE_KINDS if k not in WARM_KINDS]


# 本次请求「点的是复制品 / 传承品的图标」（客户端带 copy=true）时，
# api_cli 会在这里写 "card-skill"，Game.__init__ 拷到实例上。
# 用处：原技能与复制品各有一份一次性配额，两本账（used_skills / used_copy）
# 必须能分辨「这一下花的是哪一份」，否则同座位同卡号时必然混在一起。
REQ_COPY_KEY = ""


class Game:
    def __init__(self, db: DB, round_id: int, rules: dict | None = None):
        self.db = db
        self.round_id = round_id
        # 这一发请求点的是复制品吗（"card-skill"）；空 = 原技能
        self.req_copy_key = REQ_COPY_KEY
        self.rules = {"kuitan": True, "kiriage_mangan": False, "red_fives": True,
                      "double_yakuman": True, "atozuke": False, "multi_ron": False,
                      **(rules or {})}
        r = db._row("SELECT * FROM rounds WHERE round_id=?", (round_id,))
        if not r:
            raise ValueError("这一局不存在")
        self.round = r
        self.match_id = r["match_id"]
        self.dealer = r["dealer_seat"]
        self.round_wind = r["wind"]
        self.turn = r["turn_seat"] if r["turn_seat"] is not None else self.dealer
        self.phase = "ended" if r["status"] != "playing" else "draw"
        self.pending = None                    # 鸣牌窗口
        self.pending_kuikae = None             # 刚鸣完，不能打哪张
        self.temp_furiten: set[int] = set()    # 同巡振听
        self.riichi_furiten: set[int] = set()  # 立直后见逃 → 永久振听
        self.ippatsu: set[int] = set()
        self.first_draw_done: set[int] = set()
        self.last_was_rinshan = False
        self.chankan_now = False
        self.double_riichi: set[int] = set()
        self.result = None
        self._start_wind: str | None = None
        # 技能：客户端点了技能图标、条件成立后先挂在这里，
        # legal_actions 会多出一个动作（比如 skill_tsumo），按下按钮才结算
        self.armed_skill: dict | None = None
        self.win_pending: dict | None = None      # 技能给的和牌：等玩家点「自摸」
        self._skill_cache = None
        # 一次性技能（本小局用过就不能再用）："card-skill-seat"
        self.used_skills: set[str] = set()
        # 复制来的技能（Card41 复制 / Card16 传承）：每个复制品有**自己一份**一次性配额。
        # key 与 used_skills 同形（"card-skill-seat"）：在 cc_grants 里 = 这是复制来的技能，
        # 「用过没有」看 used_copy，不看原技能那份 used_skills。
        self.cc_grants: set[str] = set()
        self.used_copy: set[str] = set()
        # 画板（Card02 Skill1）：seat -> {"tiles":[3] 指定的牌种,
        #                               "delivered":[已给过我的],
        #                               "pending":[{"tile","seq"}] 压在我卡下、等我摸的明牌}
        self.boards: dict[int, dict] = {}
        self.swaps: dict[int, dict] = {}       # 换牌记录（重发请求时用来幂等）
        # 自信（Card03 Skill1）：配牌阶段发动，整小局有效（和牌番数双倍 / 失点双倍）
        self.confident: set[int] = set()
        # 压制（Card03 Skill2）：明牌 / 暗置牌共用同一套换牌动作，
        #   press_used = 这次摸牌已经换过了（每次摸牌后只能换一次）
        #   press_win  = 刚换完牌、这一手自摸不算边张/嵌张符（打牌后清除）
        # 魔术（Card11 Skill1）：换过指示牌、还没打出牌 → 这一手和牌算「交换后直接和牌」
        #   c11_win = 座位号；交换后立刻自摸/（理论上）荣和都按自摸结算，且不计边/坎/吊 2 符
        # 海神（Card12 S1）：被动借牌 offer + 主动挪宝进度 + 和牌门闸
        # 深山（19S1）开关、浓雾（19S2）、前路（20S1）、感知（20S2）
        self.shenshan: set[int] = set()
        self.shenshan_offer: dict | None = None
        self.nongwu: dict | None = None
        self.qianlu: dict | None = None
        self.gift: dict[int, int] = {}
        # 一定和牌（上钩 / 前路 / 馈赠3 / 先负 共用）
        # 一定和牌：yiding = 持有「可以宣言」的权限；yiding_src = 权限来自哪个技能
        self.yiding: set[int] = set()
        self.yiding_src: dict[int, list] = {}
        # 先负（22S1）
        self.xianfu_armed: int | None = None
        self.xianfu_pending: dict | None = None
        # 一发（24S1）：宣告后「牌山/王牌里确实有我的胡张」→ 一发自摸窗口开启
        self.c24_armed: int = -1
        self.c25_on: set[int] = set()      # 宝牌运（25S1）：本局开启（切宝牌要罚点）
        self.c25s2_on: set[int] = set()    # 宝牌的集合（25S2）：本局开启
        self.c25s2_pending: int = -1       # 配牌阶段等「宝牌的集合」结算的家
        self.c25s2_offer: dict | None = None   # 别人摸到宝牌 → 等我去换
        self.future_armed: int = -1            # 未来（24S2）：已经发动、等玩家排序的家
        self.future_deadline: float = 0.0
        # 天梯（26S2）：配牌开启 → 每次自己摸牌前先排「接下来 1+n 张」
        self.c26s2_on: set[int] = set()
        self.c26_n: dict[int, int] = {}        # 连续和牌次数 n（初始 0）
        self.c26_last: dict[int, int] = {}     # 上一次和牌的得点（-1 = 还没有）
        self.c26_done: dict[int, int] = {}     # 这一巡排过了（记当时的 next_no）
        self.c26_deadline: float = 0.0
        # 调包 / 命中（27S1 / 27S2）：标记 + 手切计数
        self.c27_mark: dict[int, int] = {}    # 我 → 被我标记的那一家
        self.c27_cnt: dict[int, int] = {}     # 我 → 他被手切了几张
        self.c27_s2: set[int] = set()         # 发动过命中的家（之后不能手切）
        # 满贯（28S1）：本局开启 → 任何人和牌都要先「番数结算到满贯」才允许结算
        self.c28s1_on: set[int] = set()
        # 电报（44S2）：本局宣言明牌的家（别人都看得到他的手牌）
        self.c44s2_on: set[int] = set()
        # 神境（45S1）：本局打开的家（不能立直 / 只能自摸 / 得点上限）
        self.c45s1_on: set[int] = set()
        self.c45s1_last: dict = {}      # 看破放行后重放同一个 op 用
        # 替身（45S2）：指定「第一位（摸牌后由别人决定切牌）」+「第二位（指定切哪张）」
        self.c45s2: dict | None = None
        self.c45s2_wait: int = -1          # 正在等第二位指定切牌的第一位玩家
        self.c45s2_deadline: float = 0.0
        # ── 拦截树（Activation）：看破 / 封堵 / 阻止 / 免疫 统一走这里 ──
        self.acts: dict[str, dict] = {}      # id -> 节点
        self.act_seq: int = 0
        self.act_gated: set[str] = set()   # 已经问过的 "seat:card:skill"
        # 免疫（43S2）：别人发动「指向我」的技能时问我一句
        self.c43s2_uses: dict[int, int] = {}       # 还能用几次（默认 2）
        self.c43s2_imm: dict[int, set[str]] = {}   # 我免疫哪些 "card-skill"
        self.c43_ask: dict | None = None           # 等谁回答
        self.c43_imm_ctx: dict | None = None       # 并进看破面板时用的上下文
        self.c43_pending: dict | None = None       # 被挂起的那次发动
        # 同盟（40S2）：{"by": 我, "target": 被我指定的人}；本局持续
        self.c40s2: dict | None = None
        self.c40s2_offer: dict | None = None      # 多组搭子时等我挑
        self.c40s2_deadline: float = 0.0
        # 理论战（42S1）：本局所有技能封死（已发动的配牌技能作废）
        self.c42s1_on: bool = False
        # 夺目（42S2）：结算时把哪个座位当庄家（-1 = 就是真庄家）
        self.c42s2_target: int = -1
        # 夺目：结算前挂起的那一次询问 {"winner","loser","result","res","waiting","ts"}
        self.c42s2_settle: dict | None = None
        # 夺目：这一小局已经问过的人（问过就不再问，跳过的也算）
        self.c42s2_asked: set[int] = set()
        # 隐形（39S1）：本局打出的一切牌都不能被鸣/被荣，也不造成振听
        self.c39s1_on: bool = False
        # 加速（29S1）：无视距离吃的询问；精算（29S2）是被动，无状态
        self.c29s1_offer: dict | None = None   # {seat, tile, discard_seq, from, choices}
        self.c29s1_asked: set[str] = set()     # "seat:discard_seq"（跳过就别再问同一张）
        # 友引（22S2）
        self.youyin_offer: dict | None = None
        # 21S2 段2（馈赠换牌）：offer = 正在等回答；used = 已经发动过（发动一次为止）
        self.gift_offer: dict | None = None
        # 22S2 段1：鸣牌窗口里点了技能（armed）→ 副露后要一起把手里面子摊出来
        self.youyin_meld_armed: int = -1
        self.youyin_meld_done: set[int] = set()   # 段1 本小局用过了
        self.pending_rinshan: set[int] = set()    # 杠完要补岭上（友引摊完才补）
        self.youyin_meld_offer: dict | None = None
        self.youyin_meld_deadline: float = 0.0   # 摊面子的截止时间（超时自动收尾）
        self.gift_used: set[int] = set()
        self.gift_asked: set[str] = set()      # 「这一巡已经问过」的钥匙
        self.youyin_asked: set[str] = set()
        # 加热（23S1）
        self.heat_kind: str = ""
        self.ignite_ok: bool = False          # 点燃：本局炸裂是否可用
        self.ignite_done: bool = False        # 点燃：本小局已经摇过（不能再摇）
        self.po10_next: int = 0               # 点燃：本小局攒的点数（下一小局才能用）
        self.po10_init: bool = False          # 点燃：本小局是否已做过点数结转
        self.reveal_hands: dict[int, set[int]] = {}   # 观看者 -> 能看谁的明牌
        self.kangpo_ask: dict | None = None   # 看破的待询问
        self.kangpo_pass: set[str] = set()    # 已经问过、放行的发动（防止重复问）
        # 配牌时问过看破的技能（降神/炸裂/海神）：之后不再问，也不能再被看破
        self.kangpo_once: set[str] = set()
        self.haishin_on: bool = False         # 海神：本小局配牌时开启了吗
        # 「现在真的有人在操作」的座位（由 api_cli 按 seat_lease 注入）。
        # None = 不知道（测试直接 new Game）→ 谁有看破卡都问；
        # set() = 只有这些座位是人，其余是 AI（AI 不发动技能、也不回答看破）。
        self.human_seats: set[int] | None = None
        self.kangpo_pending: dict | None = None   # 被看破挡下的那次发动
        self.zhalie_mark: str = ""            # 炸裂「这一巡已经用过」的标记
        self._c19_cache: dict[int, bool] = {}
        self._c20_cache: dict[int, bool] = {}
        self._c21_cache: dict[int, bool] = {}
        self._c22_cache: dict[int, bool] = {}
        self._c23_cache: dict[int, bool] = {}
        # 传承（Card16 S1）：本小局「借来的」技能卡；看破（Card17 S2）：被剔除的技能
        self.granted: dict[int, set[int]] = {}
        # 传承（Card16 S1）：这张卡本小局「变成」谁 —— {座位: {"card": c, "skill": k}}
        self.cc_copy: dict[int, dict] = {}
        self.poked: set[str] = set()
        self.no_win: set[int] = set()
        # 研究（Card17 S1）：能随时看谁的手牌
        self.yanjiu: dict[int, int] = {}
        # 枷锁（Card18 S1）：本局期待的番数；连接（Card18 S2）：与谁平分
        self.jiasuo: dict[int, int] = {}
        self.link: dict[int, int] = {}
        self._c16_cache: dict[int, bool] = {}
        self._c17_cache: dict[int, bool] = {}
        self._c18_cache: dict[int, bool] = {}
        # 点燃（Card14 S1）：失败攒的修正点数；炸裂（S2）每次发动都要过骰子
        self.po10_pts: int = 0
        self.po10_last: list[int] = []
        # 钓鱼（Card15 S1）：本小局还能不能用
        self.diaoyu_locked: bool = False
        self._c14_cache: dict[int, bool] = {}
        self._c15_cache: dict[int, bool] = {}
        # 破发（Card13 S1）：别人立直之后开一个窗口，等他打完这一张再关
        self.pofa_window: dict | None = None
        # 破发询问（逐个问）：{"declarer", "waiting": [座位...], "ts"}
        self.pofa_ask: dict | None = None
        self.pofa_discard_pending: int | None = None   # 破发副露完，等我暗置打出
        self._c13_cache: dict[int, bool] = {}
        self.haishin_offer: dict | None = None
        self.haishin_step: dict[int, int] = {}
        self.haishin_gate: int | None = None
        self._c12_cache: dict[int, bool] = {}
        # X神（Card12 S2）：被跳过的摸切次数
        self.x_skip: dict[int, int] = {}
        self.c11_win: int | None = None
        self._c11_cache: dict[int, bool] = {}
        self.press_used: set[int] = set()
        self.press_win: set[int] = set()
        self._sees_cache: dict[int, bool] = {}
        # 风神（Card04 Skill1）：配牌时依次跟下家/对家/上家换风牌，中途记在这里
        self.deal_flow: dict | None = None
        # Card31 S2【阻止】：每个持有者对每名玩家**每小局**最多一次
        self.c31s2_used: dict[int, set[int]] = {}
        self.c31s2_stopped: dict[str, str] = {}     # A7: 本回合已被【阻止】的技能
        self.c33s1_on: set[int] = set()       # 染手：本小局用过的人
        self.c33s1_last: dict = {}            # 染手：上次的请求（看破放行重放用）
        self.c33s2_armed: int = -1            # 记忆：等着把下一张打暗置的人
        self.c34_by: int = -1                 # 厄运：发动者（本人不受影响）
        self.c34_left: int = 0                # 厄运：发动者还要摸几次牌（3→0）
        self.c34_charges: dict[int, int] = {}  # 厄运：本小局每个座位还剩几次可发（默认 1）
        self.c34s2_on: int = -1               # 海底：谁触发了（-1 没有）
        self.c34s2_seq: int = -1              # 海底：锁定的铳张（牌山 seq）
        self.c34s2_tile: str = ""            # 海底：锁定的铳张牌面
        self.c34s2_fired: bool = False        # 海底：本小局触发过没有
        self.c34s2_why: str = ""              # 海底：这次为什么没触发（诊断用）
        self.c34s2_why_seat: int = -1
        # 流势（Card35 S1）：每副露一次就排一次「接下来 4 张」，不限次数
        self.c35_pending: int = -1            # 谁要排（-1 = 没有）
        self.c35_mark: int = 0                # 每次副露 +1（客户端靠它判重）
        self.c35_deadline: float = 0.0        # 超时自动放弃
        # 思路（Card36 S1）：我看到谁的手牌（viewer → {seat}）；自己打出一张就清空
        self.c36_watch: dict[int, set[int]] = {}
        # 故意（Card36 S2）：谁开着（-1 = 没有）；开启后打出的一张牌要判「支付」
        self.c36s2_on: int = -1
        # 岭上开花（Card37 S1）：换好牌、等玩家点『自摸』（-1 = 没有）
        self.c37s1_ready: int = -1
        # 岭上开花：在**鸣牌窗口**里点过技能的那一家 —— 这一手明杠真的开成之后，
        # 由 _apply_claim 接着走「摸岭上 → 换和牌张」。（-1 = 没有）
        self.c37s1_auto: int = -1
        # _apply_claim 里做完上面那一段的结果（给 c37s1_arm 的回包用）
        self._c37_auto_result: dict = {}
        # 透视（Card40 S1）：三家各一个计数器（初始 1）；看谁的手牌中就记在 c40_show
        self.c40_cnt: dict[int, dict[int, int]] = {}
        # 复制（Card41 S1）：别人宣告技能时挂询问；c41_copies = 我已经复制到的技能
        # 每人一叠「可以复制的技能」（延迟复制：技能照常生效，我随时来挑）
        self.c41_ask: dict[int, list[dict]] = {}
        self.c41_copies: dict[int, list[dict]] = {}
        # NO MISS（43S1）：结算中的临时标记（不计边坎吊的 2 符）
        self.c43s1_win: set[int] = set()
        self.c40_show: dict[int, set[int]] = {}
        # 自风（Card04 Skill2）：发动过风神后自动生效；别人摸到我的自风 → 换一张手牌
        self.self_wind: set[int] = set()
        self.wind_swap: dict | None = None
        # 策略（Card05 Skill1）
        #   hidden  = 被别人看手牌时盖住的三张（wall_seq）
        #   counter = 「别人害我不能正常摸切」攒的次数，每点换一次额外的摸切
        #   offer   = 由于别人技能导致我手牌变动 → 可以从王牌/弃牌换一张
        #   extra   = 这一回合打完牌后再摸一张（已经用掉 1 点 counter）
        self.card05_hidden: dict[int, list[int]] = {}
        self.card05_counter: dict[int, int] = {}
        self.card05_offer: dict[int, dict] = {}
        self.card05_extra: set[int] = set()
        self.card05_pending_hide: dict[int, int] = {}
        self.nuki_count: dict[int, int] = {}       # 拔北次数（本局）
        self.must_tsumogiri: set[int] = set()   # 换牌用过后本局只能摸切
        self._c05_cache: dict[int, bool] = {}
        self._tenac_cache: dict[int, bool] = {}   # Card06 S2「坚韧」是否持有
        self.oracle: dict[int, dict] = {}         # Card07 S1「降神」：座位 -> {suit,on,dice}
        self.duel: dict | None = None             # Card08 S1「决斗」：{by, target}
        self.c10s2: dict[int, dict] = {}          # Card10 S2「四喜」：{count, ready, reveal}
        self.c10_used: set[str] = set()           # Card10「鬼门」：换过的「座位:东/北」
        self._c10_cache: dict[int, bool] = {}
        self.c09_next: dict[int, int] = {}        # Card09：下一次只能用哪个（1/2）
        self.c09_rows: set[str] = set()           # Card09：换过的「某家牌河第几行」
        self.c09_turn: str = ""                   # Card09：这一巡已经用过（"座位-我的打牌数"）
        self._c09_cache: dict[int, bool] = {}
        self.duel_marks: set[int] = set()         # Card08 S2：有「决斗标记」的座位
        self.duel_counter: dict[int, int] = {}    # Card08 S2：计数器（别人胡牌 +标记数）
        self._duel_card_cache: dict[int, bool] = {}
        # 配牌阶段发动的技能：庄家跳完牌之后，这些座位要先「发动 / 跳过」
        self.deal_wait: set[int] = set()
        self.deal_used: set[int] = set()
        self.deal_deadline: float = 0.0     # 配牌技能阶段的截止时间（超时自动跳过）
        self.deal_queue: list[dict] = []       # 发动顺序（按这个顺序结算）
        # 技能播报（全场）：客户端看到 id 变了就弹字幕
        self.broadcast: dict | None = None
        self.broadcast_id = 0
        # 人物卡翻明（第一次发动技能后，别人视角永久翻面）
        self._revealed_cache: set[int] = set()
        self._owns_cache: dict[tuple[int, int], bool] = {}
        # 牌山（骰子 / 配牌进度 / 牌山前面 / 岭上 / 宝牌）
        self.dice: tuple[int, int] | None = None
        self.deal_i = 0
        self.next_no = 0
        self.rinshan_used = 0
        self.dora_revealed = 0
        self.round_phase = "end" if r["status"] != "playing" else "deal"
        self.load_flags()

    # ── 临时状态落库（服务器一次请求一个进程，内存里的东西不能只放内存）──
    def load_flags(self) -> None:
        f = self.db.load_round_flags(self.round_id)
        self.temp_furiten = set(f.get("temp_furiten", []))
        self.riichi_furiten = set(f.get("riichi_furiten", []))
        self.ippatsu = set(f.get("ippatsu", []))
        self.first_draw_done = set(f.get("first_draw_done", []))
        self.double_riichi = set(f.get("double_riichi", []))
        self.last_was_rinshan = bool(f.get("last_was_rinshan", False))
        self.chankan_now = bool(f.get("chankan_now", False))
        arm = f.get("armed_skill")
        self.armed_skill = arm if isinstance(arm, dict) and arm else None
        _wp = f.get("win_pending")
        self.win_pending = _wp if isinstance(_wp, dict) and _wp else None
        self._skill_cache = None
        self.used_skills = set(f.get("used_skills") or [])
        self.cc_grants = {str(x) for x in (f.get("cc_grants") or [])}
        self.used_copy = {str(x) for x in (f.get("used_copy") or [])}
        self.swaps = {int(k): v for k, v in (f.get("swaps") or {}).items()
                      if isinstance(v, dict)}
        self.confident = {int(x) for x in (f.get("confident") or [])
                          if int(x) in range(4)}
        self.press_used = {int(x) for x in (f.get("press_used") or [])
                           if int(x) in range(4)}
        self.press_win = {int(x) for x in (f.get("press_win") or [])
                          if int(x) in range(4)}
        cw = f.get("c11_win")
        self.c11_win = int(cw) if (cw is not None and int(cw) in range(4)) else None
        self._c11_cache = {}
        self._c12_cache = {}
        ho = f.get("haishin_offer")
        self.haishin_offer = ho if isinstance(ho, dict) else None
        self.haishin_step = {int(k): int(v) for k, v in (f.get("haishin_step") or {}).items()}
        self.shenshan = {int(x) for x in (f.get("shenshan") or [])}
        so = f.get("shenshan_offer")
        self.shenshan_offer = so if isinstance(so, dict) else None
        nw = f.get("nongwu")
        self.nongwu = nw if isinstance(nw, dict) else None
        ql = f.get("qianlu")
        self.qianlu = ql if isinstance(ql, dict) else None
        self.gift = {int(k): int(v) for k, v in (f.get("gift") or {}).items()}
        self.yiding = {int(x) for x in (f.get("yiding") or [])}
        self.yiding_src = {int(k): [int(v[0]), int(v[1])]
                           for k, v in (f.get("yiding_src") or {}).items()
                           if isinstance(v, (list, tuple)) and len(v) >= 2}
        xa = f.get("xianfu_armed")
        self.xianfu_armed = int(xa) if (xa is not None and int(xa) in range(4)) else None
        xp = f.get("xianfu_pending")
        self.xianfu_pending = xp if isinstance(xp, dict) else None
        self.c24_armed = int(f.get("c24_armed", -1))
        if self.c24_armed not in range(4):
            self.c24_armed = -1
        self.c25_on = {int(x) for x in (f.get("c25_on") or [])
                       if int(x) in range(4)}
        self.c25s2_on = {int(x) for x in (f.get("c25s2_on") or [])
                         if int(x) in range(4)}
        cp2 = f.get("c25s2_pending", -1)
        self.c25s2_pending = int(cp2) if (cp2 is not None
                                          and int(cp2) in range(4)) else -1
        co2 = f.get("c25s2_offer")
        self.c25s2_offer = co2 if isinstance(co2, dict) and co2 else None
        fa = f.get("future_armed", -1)
        self.future_armed = int(fa) if (fa is not None and int(fa) in range(4)) else -1
        self.future_deadline = float(f.get("future_deadline", 0) or 0)
        self.c26s2_on = {int(x) for x in (f.get("c26s2_on") or [])
                         if int(x) in range(4)}
        self.c26_n = {int(k): int(v) for k, v in (f.get("c26_n") or {}).items()}
        self.c26_last = {int(k): int(v) for k, v in (f.get("c26_last") or {}).items()}
        self.c26_done = {int(k): int(v) for k, v in (f.get("c26_done") or {}).items()}
        self.c26_deadline = float(f.get("c26_deadline", 0) or 0)
        self.c27_mark = {int(k): int(v) for k, v in (f.get("c27_mark") or {}).items()}
        self.c27_cnt = {int(k): int(v) for k, v in (f.get("c27_cnt") or {}).items()}
        self.c27_s2 = {int(x) for x in (f.get("c27_s2") or []) if int(x) in range(4)}
        self.c28s1_on = {int(x) for x in (f.get("c28s1_on") or []) if int(x) in range(4)}
        self.c44s2_on = {int(x) for x in (f.get("c44s2_on") or []) if int(x) in range(4)}
        self.c45s1_on = {int(x) for x in (f.get("c45s1_on") or []) if int(x) in range(4)}
        self.c45s1_last = dict(f.get("c45s1_last") or {})
        _c45s2 = f.get("c45s2")
        self.c45s2 = _c45s2 if isinstance(_c45s2, dict) and _c45s2 else None
        _c45s2w = f.get("c45s2_wait", -1)
        self.c45s2_wait = int(_c45s2w) if (_c45s2w is not None
                                           and int(_c45s2w) in range(4)) else -1
        self.c45s2_deadline = float(f.get("c45s2_deadline", 0) or 0)
        self.c39s1_on = bool(f.get("c39s1_on", False))
        self.c42s1_on = bool(f.get("c42s1_on", False))
        self.c43s2_uses = {int(k): int(v) for k, v in
                          (f.get("c43s2_uses") or {}).items()}
        self.c43s2_imm = {int(k): {str(x) for x in v} for k, v in
                          (f.get("c43s2_imm") or {}).items()}
        _acts = f.get("acts")
        self.acts = {str(k): dict(v) for k, v in (_acts or {}).items()
                     if isinstance(v, dict)}
        self.act_seq = int(f.get("act_seq", 0) or 0)
        self.act_gated = {str(x) for x in (f.get("act_gated") or [])}
        _c43i = f.get("c43_imm_ctx")
        self.c43_imm_ctx = _c43i if isinstance(_c43i, dict) and _c43i else None
        _c43a = f.get("c43_ask")
        self.c43_ask = _c43a if isinstance(_c43a, dict) and _c43a else None
        _c43p = f.get("c43_pending")
        self.c43_pending = _c43p if isinstance(_c43p, dict) and _c43p else None
        _c40s2 = f.get("c40s2")
        self.c40s2 = _c40s2 if isinstance(_c40s2, dict) and _c40s2 else None
        _c40o = f.get("c40s2_offer")
        self.c40s2_offer = _c40o if isinstance(_c40o, dict) and _c40o else None
        self.c40s2_deadline = float(f.get("c40s2_deadline", 0) or 0)
        _c42t = f.get("c42s2_target", -1)
        self.c42s2_target = int(_c42t) if (_c42t is not None
                                            and int(_c42t) in range(4)) else -1
        _c42p = f.get("c42s2_settle")
        self.c42s2_settle = _c42p if isinstance(_c42p, dict) and _c42p else None
        self.c42s2_asked = {int(x) for x in (f.get("c42s2_asked") or [])
                            if int(x) in range(4)}
        co = f.get("c29s1_offer")
        self.c29s1_offer = co if isinstance(co, dict) else None
        self.c29s1_asked = {str(x) for x in (f.get("c29s1_asked") or [])}
        yo = f.get("youyin_offer")
        self.youyin_offer = yo if isinstance(yo, dict) else None
        go = f.get("gift_offer")
        self.gift_offer = go if isinstance(go, dict) else None
        self.gift_used = {int(x) for x in (f.get("gift_used") or [])}
        self.gift_asked = {str(x) for x in (f.get("gift_asked") or [])}
        self.youyin_meld_armed = int(f.get("youyin_meld_armed", -1))
        self.youyin_meld_done = {int(x) for x in (f.get("youyin_meld_done") or [])
                                 if int(x) in range(4)}
        self.pending_rinshan = {int(x) for x in (f.get("pending_rinshan") or [])
                                if int(x) in range(4)}
        ymo = f.get("youyin_meld_offer")
        self.youyin_meld_offer = ymo if isinstance(ymo, dict) else None
        self.youyin_meld_deadline = float(f.get("youyin_meld_deadline", 0) or 0)
        self.youyin_asked = {str(x) for x in (f.get("youyin_asked") or [])}
        self.heat_kind = str(f.get("heat_kind", "") or "")
        self.ignite_ok = bool(f.get("ignite_ok", False))
        self.ignite_done = bool(f.get("ignite_done", False))
        self.reveal_hands = {int(k): {int(x) for x in v}
                             for k, v in (f.get("reveal_hands") or {}).items()}
        ka = f.get("kangpo_ask")
        self.kangpo_ask = ka if isinstance(ka, dict) else None
        self.kangpo_pass = {str(x) for x in (f.get("kangpo_pass") or [])}
        self.kangpo_once = {str(x) for x in (f.get("kangpo_once") or [])}
        self.haishin_on = bool(f.get("haishin_on", False))
        kp = f.get("kangpo_pending")
        self.kangpo_pending = kp if isinstance(kp, dict) else None
        self.zhalie_mark = str(f.get("zhalie_mark", "") or "")
        self._c19_cache = {}
        self._c20_cache = {}
        self._c21_cache = {}
        self._c22_cache = {}
        self._c23_cache = {}
        self.granted = {int(k): {int(x) for x in v}
                        for k, v in (f.get("granted") or {}).items()}
        self.cc_copy = {int(k): {"card": int(v.get("card", 0)),
                                 "skill": int(v.get("skill", 0))}
                        for k, v in (f.get("cc_copy") or {}).items()
                        if int(v.get("card", 0)) > 0}
        self.poked = {str(x) for x in (f.get("poked") or [])}
        self.no_win = {int(x) for x in (f.get("no_win") or [])}
        self.yanjiu = {int(k): int(v) for k, v in (f.get("yanjiu") or {}).items()}
        self.jiasuo = {int(k): int(v) for k, v in (f.get("jiasuo") or {}).items()}
        self.link = {int(k): int(v) for k, v in (f.get("link") or {}).items()}
        self._c16_cache = {}
        self._c17_cache = {}
        self._c18_cache = {}
        if not bool(f.get("po10_init", False)):
            d = self._po10_load()
            self.po10_pts = int(d.get("now", 0)) + int(d.get("next", 0))
            self.po10_next = 0
            self._po10_save()
            self.po10_init = True
        else:
            self.po10_pts = int(f.get("po10_pts", 0) or 0)
            self.po10_next = int(f.get("po10_next", 0) or 0)
            self.po10_init = True
        self.po10_last = [int(x) for x in (f.get("po10_last") or [])]
        self.diaoyu_locked = bool(f.get("diaoyu_locked", False))
        self._c14_cache = {}
        self._c15_cache = {}
        pw = f.get("pofa_window")
        self.pofa_window = pw if isinstance(pw, dict) else None
        pa = f.get("pofa_ask")
        self.pofa_ask = pa if isinstance(pa, dict) else None
        pdp = f.get("pofa_discard_pending")
        self.pofa_discard_pending = int(pdp) if (pdp is not None and int(pdp) in range(4)) else None
        self._c13_cache = {}
        hg = f.get("haishin_gate")
        self.haishin_gate = int(hg) if (hg is not None and int(hg) in range(4)) else None
        self.x_skip = {int(k): int(v) for k, v in (f.get("x_skip") or {}).items()}
        self._sees_cache = {}
        self._owns_cache = {}
        self.deal_wait = {int(x) for x in (f.get("deal_wait") or [])
                          if int(x) in range(4)}
        self.deal_deadline = float(f.get("deal_deadline", 0) or 0)
        self.deal_used = {int(x) for x in (f.get("deal_used") or [])
                          if int(x) in range(4)}
        self.deal_queue = list(f.get("deal_queue") or [])
        df = f.get("deal_flow")
        self.deal_flow = df if isinstance(df, dict) and df else None
        self.c31s2_used = {int(k): set(int(x) for x in v)
                           for k, v in (f.get("c31s2_used") or {}).items()}
        self.c31s2_stopped = dict(f.get("c31s2_stopped") or {})
        self.c33s1_on = {int(x) for x in (f.get("c33s1_on") or [])}
        self.c33s1_last = dict(f.get("c33s1_last") or {})
        _c33s2 = f.get("c33s2_armed")
        self.c33s2_armed = -1 if _c33s2 is None else int(_c33s2)
        _c34by = f.get("c34_by")
        self.c34_by = -1 if _c34by is None else int(_c34by)
        self.c34_left = int(f.get("c34_left", 0) or 0)
        self.c34_charges = {int(k): int(v) for k, v in (f.get("c34_charges") or {}).items()}
        _c2on = f.get("c34s2_on")
        self.c34s2_on = -1 if _c2on is None else int(_c2on)
        self.c34s2_seq = int(f.get("c34s2_seq", -1) or -1)
        self.c34s2_tile = str(f.get("c34s2_tile", "") or "")
        self.c34s2_fired = bool(f.get("c34s2_fired", False))
        _c35p = f.get("c35_pending")
        self.c35_pending = -1 if _c35p is None else int(_c35p)
        self.c35_mark = int(f.get("c35_mark", 0) or 0)
        self.c35_deadline = float(f.get("c35_deadline", 0) or 0)
        self.c36_watch = {int(k): {int(x) for x in v if int(x) in range(4)}
                          for k, v in (f.get("c36_watch") or {}).items()}
        _c36on = f.get("c36s2_on")
        self.c36s2_on = -1 if _c36on is None else int(_c36on)
        _c37r = f.get("c37s1_ready")
        self.c37s1_ready = -1 if _c37r is None else int(_c37r)
        _c37a = f.get("c37s1_auto")
        self.c37s1_auto = -1 if _c37a is None else int(_c37a)
        self.c40_cnt = {}
        for _k, _v in (f.get("c40_cnt") or {}).items():
            try:
                self.c40_cnt[int(_k)] = {int(a): int(b) for a, b in (_v or {}).items()}
            except (TypeError, ValueError):
                pass
        self.c40_show = {int(k): {int(x) for x in v if int(x) in range(4)}
                         for k, v in (f.get("c40_show") or {}).items()}
        self.c41_ask = {}
        for _k, _v in (f.get("c41_ask") or {}).items():
            try:
                _sdk = int(_k)
            except Exception:
                continue
            if isinstance(_v, list):
                self.c41_ask[_sdk] = [dict(x) for x in _v if isinstance(x, dict)]
            elif isinstance(_v, dict) and _v:        # 老格式（单个询问）
                self.c41_ask[_sdk] = [dict(_v)]
        self.c41_copies = {int(k): [dict(x) for x in (v or [])]
                           for k, v in (f.get("c41_copies") or {}).items()}
        self.self_wind = {int(x) for x in (f.get("self_wind") or [])
                          if int(x) in range(4)}
        ws = f.get("wind_swap")
        self.wind_swap = ws if isinstance(ws, dict) and ws else None
        self.card05_hidden = {}
        for k, v in (f.get("card05_hidden") or {}).items():
            try:
                self.card05_hidden[int(k)] = [int(x) for x in (v or [])]
            except (TypeError, ValueError):
                pass
        self.card05_counter = {}
        for k, v in (f.get("card05_counter") or {}).items():
            try:
                self.card05_counter[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
        self.card05_offer = {}
        for k, v in (f.get("card05_offer") or {}).items():
            try:
                if isinstance(v, dict):
                    self.card05_offer[int(k)] = v
            except (TypeError, ValueError):
                pass
        self.card05_extra = {int(x) for x in (f.get("card05_extra") or [])
                             if int(x) in range(4)}
        self.card05_pending_hide = {}
        for k, v in (f.get("card05_pending_hide") or {}).items():
            try:
                self.card05_pending_hide[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
        self.nuki_count = {}
        self.must_tsumogiri = {int(x) for x in (f.get("must_tsumogiri") or [])
                               if int(x) in range(4)}
        for k, v in (f.get("card05_nuki") or {}).items():
            try:
                self.nuki_count[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
        self._c05_cache = {}
        self._tenac_cache = {}
        d = f.get("duel")
        self.duel = ({"by": int(d["by"]), "target": int(d["target"])}
                     if isinstance(d, dict) and "by" in d and "target" in d else None)
        self._c09_cache = {}
        self._c10_cache = {}
        self.c10_used = {str(x) for x in (f.get("c10_used") or [])}
        self.c10s2 = {}
        for k, v in (f.get("c10s2") or {}).items():
            if isinstance(v, dict):
                try:
                    self.c10s2[int(k)] = {"count": int(v.get("count", 0)),
                                          "ready": bool(v.get("ready", False)),
                                          "reveal": [str(x) for x in (v.get("reveal") or [])]}
                except (ValueError, TypeError):
                    pass
        self.c09_next = {}
        for k, v in (f.get("c09_next") or {}).items():
            try:
                if int(v) in (1, 2):
                    self.c09_next[int(k)] = int(v)
            except (ValueError, TypeError):
                pass
        self.c09_rows = {str(x) for x in (f.get("c09_rows") or [])}
        self.c09_turn = str(f.get("c09_turn", "") or "")
        self._duel_card_cache = {}
        self._load_duel_meta()                    # 标记 / 计数器（跨小局，跟着角色走）
        self.oracle = {}
        for k, v in (f.get("oracle") or {}).items():
            try:
                if isinstance(v, dict) and str(v.get("suit", "")) in ("m", "p", "s"):
                    self.oracle[int(k)] = {"suit": str(v["suit"]),
                                           "on": bool(v.get("on", True)),
                                           "dice": int(v.get("dice", 0))}
            except (ValueError, TypeError):
                pass
        b = f.get("broadcast")
        self.broadcast = b if isinstance(b, dict) and b else None
        self.broadcast_id = int(f.get("broadcast_id", 0) or 0)
        self._revealed_cache = self._load_revealed()
        self.boards = {}
        for k, v in (f.get("boards") or {}).items():
            try:
                self.boards[int(k)] = {
                    "tiles": [str(x) for x in (v.get("tiles") or [])],
                    "delivered": [str(x) for x in (v.get("delivered") or [])],
                    "pending": [{"tile": str(p.get("tile")), "seq": int(p.get("seq", 0))}
                                for p in (v.get("pending") or [])],
                }
            except (TypeError, ValueError, AttributeError):
                pass
        # 局面阶段 / 鸣牌窗口：一次请求一个进程，必须跟着落库
        if self.phase != "ended" and f.get("phase"):
            self.phase = str(f["phase"])
        if f.get("turn") is not None and self.phase != "ended":
            self.turn = int(f["turn"])
        p = f.get("pending")
        if p and self.phase == "claim":
            self.pending = {
                "discard_seq": p.get("discard_seq"), "tile": p.get("tile"),
                "from": p.get("from"),
                "options": {int(k): v for k, v in (p.get("options") or {}).items()},
                "answers": {int(k): v for k, v in (p.get("answers") or {}).items()},
            }
        else:
            self.pending = None
        # 牌山：骰子 / 配牌进度 / 牌山前面的编号 / 岭上用了几张 / 翻了几张宝牌
        d = f.get("dice")
        self.dice = tuple(int(x) for x in d) if d else None
        self.deal_i = int(f.get("deal_i", 0))
        self.next_no = int(f.get("next_no", 0))
        self.rinshan_used = int(f.get("rinshan_used", 0))
        self.dora_revealed = int(f.get("dora_revealed", 0))
        if self.phase != "ended" and f.get("round_phase"):
            self.round_phase = str(f["round_phase"])          # 配牌 / 切牌 / 结束
        # 结算结果：phase=ended 之后客户端还会来问 state（轮询 / 看破放行后的重放 /
        # 另一个窗口），不读回来的话 state.result 是 None → 结算画面永远不出现。
        _r0 = f.get("result")
        self.result = _r0 if isinstance(_r0, dict) and _r0 else None
        if self.result is None and self.phase == "ended":
            self.result = self._result_from_db()

    def _result_from_db(self) -> dict | None:
        """phase=ended 但 flags 里没有 result（这个补丁之前的局）→ 照 DB 拼一个能显示的。"""
        try:
            row = self.db._row(
                "SELECT result, winner_seat, loser_seat, han, fu, points, yaku_json "
                "FROM rounds WHERE round_id=?", (self.round_id,))
        except Exception:                                     # noqa: BLE001
            return None
        if row is None or not row["result"]:
            return None
        try:
            names = [str(x) for x in (json.loads(row["yaku_json"] or "[]") or [])]
        except Exception:                                     # noqa: BLE001
            names = []
        pts = int(row["points"] or 0)
        win = -1 if row["winner_seat"] is None else int(row["winner_seat"])
        lose = None if row["loser_seat"] is None else int(row["loser_seat"])
        return {"result": str(row["result"]), "winner": win, "loser": lose,
                "yaku": [{"name": n, "han": 0} for n in names], "yaku_names": names,
                "han": int(row["han"] or 0), "fu": int(row["fu"] or 0),
                "points": pts, "yakuman": 0, "pays": {"total": pts}, "deltas": {},
                "fu_items": [], "duel_bonus": 0,
                "scores": self.scores(), "stopped": True, "from_db": True}


    def save_flags(self) -> None:
        p = self.pending
        pending = None
        if p:
            pending = {
                "discard_seq": p.get("discard_seq"), "tile": p.get("tile"),
                "from": p.get("from"),
                "options": {str(k): v for k, v in (p.get("options") or {}).items()},
                "answers": {str(k): v for k, v in (p.get("answers") or {}).items()},
            }
        self.db.save_round_flags(self.round_id, {
            "phase": self.phase,
            "result": self.result,
            "turn": self.turn,
            "pending": pending,
            "temp_furiten": sorted(self.temp_furiten),
            "riichi_furiten": sorted(self.riichi_furiten),
            "ippatsu": sorted(self.ippatsu),
            "first_draw_done": sorted(self.first_draw_done),
            "double_riichi": sorted(self.double_riichi),
            "last_was_rinshan": self.last_was_rinshan,
            "chankan_now": self.chankan_now,
            "armed_skill": self.armed_skill,
            "win_pending": self.win_pending,
            "used_skills": sorted(self.used_skills),
            "cc_grants": sorted(self.cc_grants),
            "used_copy": sorted(self.used_copy),
            "boards": {str(k): v for k, v in self.boards.items()},
            "swaps": {str(k): v for k, v in (self.swaps or {}).items()},
            "confident": sorted(self.confident),
            "press_used": sorted(self.press_used),
            "press_win": sorted(self.press_win),
            "c11_win": self.c11_win,
            "pofa_window": self.pofa_window,
            "pofa_ask": self.pofa_ask,
            "pofa_discard_pending": self.pofa_discard_pending,
            "shenshan": sorted(self.shenshan),
            "shenshan_offer": self.shenshan_offer,
            "nongwu": self.nongwu,
            "qianlu": self.qianlu,
            "gift": {str(k): v for k, v in self.gift.items()},
            "yiding": sorted(self.yiding),
            "yiding_src": {str(k): list(v) for k, v in self.yiding_src.items()},
            "xianfu_armed": self.xianfu_armed,
            "xianfu_pending": self.xianfu_pending,
            "c24_armed": int(self.c24_armed),
            "c25_on": sorted(self.c25_on),
            "c25s2_on": sorted(self.c25s2_on),
            "c25s2_pending": int(self.c25s2_pending),
            "c25s2_offer": self.c25s2_offer,
            "future_armed": int(self.future_armed),
            "future_deadline": float(self.future_deadline),
            "c26s2_on": sorted(self.c26s2_on),
            "c26_n": {str(k): int(v) for k, v in self.c26_n.items()},
            "c26_last": {str(k): int(v) for k, v in self.c26_last.items()},
            "c26_done": {str(k): int(v) for k, v in self.c26_done.items()},
            "c26_deadline": float(self.c26_deadline),
            "c27_mark": {str(k): int(v) for k, v in self.c27_mark.items()},
            "c27_cnt": {str(k): int(v) for k, v in self.c27_cnt.items()},
            "c27_s2": sorted(self.c27_s2),
            "c28s1_on": sorted(self.c28s1_on),
            "c44s2_on": sorted(self.c44s2_on),
            "c45s1_on": sorted(self.c45s1_on),
            "c45s1_last": dict(self.c45s1_last or {}),
            "c45s2": (dict(self.c45s2) if self.c45s2 else None),
            "c45s2_wait": int(self.c45s2_wait),
            "c45s2_deadline": float(self.c45s2_deadline),
            "c39s1_on": bool(self.c39s1_on),
            "c42s1_on": bool(self.c42s1_on),
            "c40s2": (dict(self.c40s2) if self.c40s2 else None),
            "c43s2_uses": {str(k): int(v) for k, v in self.c43s2_uses.items()},
            "c43s2_imm": {str(k): sorted(v) for k, v in self.c43s2_imm.items()},
            "c43_ask": (dict(self.c43_ask) if self.c43_ask else None),
            "acts": {str(k): dict(v) for k, v in self.acts.items()},
            "act_seq": int(self.act_seq),
            "act_gated": sorted(self.act_gated),
            "c43_imm_ctx": (dict(self.c43_imm_ctx)
                             if self.c43_imm_ctx else None),
            "c43_pending": (dict(self.c43_pending)
                            if self.c43_pending else None),
            "c40s2_offer": (dict(self.c40s2_offer)
                            if self.c40s2_offer else None),
            "c40s2_deadline": float(self.c40s2_deadline),
            "c42s2_target": int(self.c42s2_target),
            "c42s2_settle": (dict(self.c42s2_settle) if self.c42s2_settle else None),
            "c42s2_asked": sorted(int(x) for x in self.c42s2_asked),
            "c29s1_offer": self.c29s1_offer,
            "c29s1_asked": sorted(self.c29s1_asked),
            "youyin_offer": self.youyin_offer,
            "gift_offer": self.gift_offer,
            "gift_used": sorted(self.gift_used),
            "gift_asked": sorted(self.gift_asked),
            "youyin_meld_armed": int(self.youyin_meld_armed),
            "youyin_meld_done": sorted(self.youyin_meld_done),
            "pending_rinshan": sorted(self.pending_rinshan),
            "youyin_meld_offer": self.youyin_meld_offer,
            "youyin_meld_deadline": float(self.youyin_meld_deadline),
            "youyin_asked": sorted(self.youyin_asked),
            "heat_kind": self.heat_kind,
            "ignite_ok": self.ignite_ok,
            "ignite_done": self.ignite_done,
            "reveal_hands": {str(k): sorted(v) for k, v in self.reveal_hands.items()},
            "kangpo_ask": self.kangpo_ask,
            "kangpo_pending": self.kangpo_pending,
            "kangpo_pass": sorted(self.kangpo_pass),
            "kangpo_once": sorted(self.kangpo_once),
            "haishin_on": bool(self.haishin_on),
            "zhalie_mark": self.zhalie_mark,
            "granted": {str(k): sorted(v) for k, v in self.granted.items()},
            "cc_copy": {str(k): dict(v) for k, v in self.cc_copy.items()},
            "poked": sorted(self.poked),
            "no_win": sorted(self.no_win),
            "yanjiu": {str(k): v for k, v in self.yanjiu.items()},
            "jiasuo": {str(k): v for k, v in self.jiasuo.items()},
            "link": {str(k): v for k, v in self.link.items()},
            "po10_pts": self.po10_pts,
            "po10_next": self.po10_next,
            "po10_init": self.po10_init,
            "po10_last": self.po10_last,
            "diaoyu_locked": self.diaoyu_locked,
            "haishin_offer": self.haishin_offer,
            "haishin_step": {str(k): v for k, v in self.haishin_step.items()},
            "haishin_gate": self.haishin_gate,
            "x_skip": {str(k): v for k, v in self.x_skip.items()},
            "deal_wait": sorted(self.deal_wait),
            "deal_used": sorted(self.deal_used),
            "deal_deadline": float(self.deal_deadline),
            "deal_queue": self.deal_queue,
            "deal_flow": self.deal_flow,
            "c31s2_used": {str(k): sorted(int(x) for x in v)
                           for k, v in self.c31s2_used.items()},
            "c31s2_stopped": dict(self.c31s2_stopped),
            "c33s1_on": sorted(int(x) for x in self.c33s1_on),
            "c33s1_last": dict(self.c33s1_last or {}),
            "c33s2_armed": int(self.c33s2_armed),
            "c34_by": int(self.c34_by),
            "c34_left": int(self.c34_left),
            "c34_charges": {str(k): int(v) for k, v in self.c34_charges.items()},
            "c34s2_on": int(self.c34s2_on),
            "c34s2_seq": int(self.c34s2_seq),
            "c34s2_tile": str(self.c34s2_tile),
            "c34s2_fired": bool(self.c34s2_fired),
            "c35_pending": int(self.c35_pending),
            "c35_mark": int(self.c35_mark),
            "c35_deadline": float(self.c35_deadline or 0.0),
            "c36_watch": {str(k): sorted(int(x) for x in v)
                          for k, v in self.c36_watch.items() if v},
            "c36s2_on": int(self.c36s2_on),
            "c37s1_ready": int(self.c37s1_ready),
            "c37s1_auto": int(self.c37s1_auto),
            "c40_cnt": {str(k): {str(a): int(b) for a, b in v.items()}
                        for k, v in self.c40_cnt.items()},
            "c40_show": {str(k): sorted(int(x) for x in v)
                         for k, v in self.c40_show.items() if v},
            "c41_ask": {str(k): [dict(x) for x in v]
                        for k, v in self.c41_ask.items() if v},
            "c41_copies": {str(k): [dict(x) for x in v]
                           for k, v in self.c41_copies.items() if v},
            "self_wind": sorted(self.self_wind),
            "wind_swap": self.wind_swap,
            "card05_hidden": {str(k): v for k, v in self.card05_hidden.items()},
            "card05_counter": {str(k): v for k, v in self.card05_counter.items()},
            "card05_offer": {str(k): v for k, v in self.card05_offer.items()},
            "card05_extra": sorted(self.card05_extra),
            "card05_pending_hide": {str(k): v for k, v in self.card05_pending_hide.items()},
            "card05_nuki": {str(k): v for k, v in self.nuki_count.items()},
            "oracle": {str(k): v for k, v in self.oracle.items()},
            "duel": self.duel,
            "c09_next": {str(k): int(v) for k, v in self.c09_next.items()},
            "c09_rows": sorted(self.c09_rows),
            "c09_turn": self.c09_turn,
            "c10_used": sorted(self.c10_used),
            "c10s2": {str(k): v for k, v in self.c10s2.items()},
            "must_tsumogiri": sorted(self.must_tsumogiri),
            "broadcast": self.broadcast,
            "broadcast_id": self.broadcast_id,
            "round_phase": self.round_phase,
            "dice": list(self.dice) if self.dice else None,
            "deal_i": self.deal_i,
            "next_no": self.next_no,
            "rinshan_used": self.rinshan_used,
            "dora_revealed": self.dora_revealed,
        })

    # ══════════════════════════════════════════════════════════════════════
    #  读牌面（都从数据库读，服务器重启也不丢）
    # ══════════════════════════════════════════════════════════════════════
    def hand(self, seat: int) -> list[str]:
        return [h["tile"] for h in self.db._rows(
            "SELECT tile FROM round_hands WHERE round_id=? AND seat=? ORDER BY is_drawn, wall_seq",
            (self.round_id, seat))]

    def hand_counts(self, seat: int) -> list[int]:
        return counts_of(self.hand(seat))

    def drawn_tile(self, seat: int) -> str | None:
        row = self.db._row("SELECT tile FROM round_hands WHERE round_id=? AND seat=? AND is_drawn=1",
                           (self.round_id, seat))
        return row["tile"] if row else None

    def melds(self, seat: int) -> list[dict]:
        # tiles  = 显示顺序（和客户端摆法一致，含被鸣的那张）
        # seqs   = 与 tiles 一一对应的「物理牌编号」wall_seq（加杠就是 4 个）
        return [{"kind": m["kind"], "meld_id": int(m["meld_id"]),
                 "tiles": json.loads(m["tiles_json"]),
                 "seqs": json.loads(m["seqs_json"] or "[]"),
                 "called_tile": m["called_tile"], "from_seat": m["from_seat"],
                 "rot_index": m["rot_index"],
                 # 友引（22S2）摊出来的面子：全部竖置、明置（像暗杠但没扣着）
                 "rot_all": str(m["kind"]) == "open_set"}
                for m in self.db._rows("SELECT * FROM round_melds WHERE round_id=? AND seat=? "
                                       "ORDER BY meld_id", (self.round_id, seat))]

    def discards(self, seat: int) -> list[str]:
        return [d["tile"] for d in self.db._rows(
            "SELECT tile FROM round_discards WHERE round_id=? AND seat=? ORDER BY seq",
            (self.round_id, seat))]

    def discards_for_furiten(self, seat: int) -> list[str]:
        """振听只看自己真正打出去的牌。


        换牌技能（Card02 Skill2）会把我的手牌**暗置**塞进别人的牌河，
        那不是他打出来的牌，不能让他因此额外振听。

        ★ 暗置牌对**任何人**都不造成振听（不管他持不持压制）。
        """
        if self.c39s1_on:
            return []                        # 【隐形】：打出的牌不造成振听
        return [d["tile"] for d in self.db._rows(
            "SELECT tile FROM round_discards WHERE round_id=? AND seat=? AND face_down=0 "
            "AND is_nuki=0 ORDER BY seq", (self.round_id, seat))]

    def sees_face_down(self, seat: int) -> bool:
        """这个座位是不是持有 Card03「压制」：暗置牌对他等于明牌。"""
        if seat not in self._sees_cache:
            # strict：必须真的在卡序里持有 Card03（没选卡数据就不算）
            self._sees_cache[seat] = skills.owns_card(
                self.db, self, seat, 3, strict=True)
        return self._sees_cache[seat]

    def turn_count(self, seat: int) -> int:
        """这一局这个座位已经打过几张牌 = 已经打完几巡（判断「第十三巡前」）。

        用「真正打出去的牌」来数：换牌技能暗置进牌河的那几张不算一巡。
        """
        return int(self.db._one(
            "SELECT COUNT(*) FROM round_actions WHERE round_id=? AND seat=? "
            "AND action='discard'", (self.round_id, seat)) or 0)

    def revealed_dora(self, kind: str = "dora") -> list[str]:
        return [d["indicator"] for d in self.db._rows(
            "SELECT indicator FROM round_dora WHERE round_id=? AND kind=? AND revealed=1 "
            "ORDER BY idx", (self.round_id, kind))]

    def scores(self) -> dict:
        return {s["seat"]: s["score"] for s in self.db._rows(
            "SELECT seat, score FROM match_seats WHERE match_id=? ORDER BY seat", (self.match_id,))}

    def is_riichi(self, seat: int) -> bool:
        return bool(self.db._row("SELECT 1 FROM round_riichi WHERE round_id=? AND seat=?",
                                 (self.round_id, seat)))

    # ── 立直后手牌锁定 ─────────────────────────────────────────────
    # 用户口径：立直之后这家的手牌谁都不能动（自己也只按立直规则换摸切）。
    # 所有「手牌归属 / 牌面变动」的入口都要先过 _assert_hand_mutable。
    def hand_locked(self, seat: int) -> bool:
        return int(seat) >= 0 and self.is_riichi(int(seat))

    def _assert_hand_mutable(self, *seats) -> None:
        for s2 in seats:
            if int(s2) >= 0 and self.hand_locked(int(s2)):
                raise RuleError("对方已经立直，手牌锁定：不能被技能改手牌")

    def live_left(self) -> int:
        return self.db._one("SELECT live_left FROM rounds WHERE round_id=?", (self.round_id,)) or 0

    def waits(self, seat: int) -> list[str]:
        """某家听什么（只能发给本人）。"""
        return agari.winning_tiles(self.hand_counts(seat), self.melds(seat))

    def hand13(self, seat: int) -> list[str]:
        """手牌去掉刚摸的那张（13 张），听牌/立直都按它算。"""
        hand = list(self.hand(seat))
        d = self.drawn_tile(seat)
        if d is not None and d in hand:
            hand.remove(d)
        return hand

    def yaku_base(self, seat: int) -> dict:
        """给听牌报告用的局面信息（亲家 / 自风 / 场风 / 立直 / 宝牌…）。"""
        return {
            "is_dealer": seat == self.dealer,
            "seat_wind": ["dong", "nan", "xi", "bei"][(seat - self.dealer) % 4],
            "round_wind": self.round_wind,
            "riichi": (self.is_riichi(seat) or self.c39s2_fake(seat)),
            "ippatsu": seat in self.ippatsu,
            "double_riichi": seat in self.double_riichi,
            "dora_indicators": self.revealed_dora("dora"),
            "ura_indicators": (self.revealed_dora("ura")
                               if (self.is_riichi(seat) or self.c39s2_fake(seat))
                               else []),
            "rules": self.rules,
        }

    def tenpai_info(self, seat: int) -> dict:
        """听牌报告：听什么、哪几张有役、无役听牌标记。"""
        return tenpai.tenpai_report(self.hand13(seat), self.melds(seat),
                                    self.tenpai_base(seat))

    def furiten(self, seat: int) -> dict:
        """振听状态：永久（自己牌河有待牌）/ 同巡（见逃）/ 立直后见逃。"""
        return tenpai.furiten_info(self.hand_counts(seat), self.melds(seat),
                                   self.discards_for_furiten(seat),
                                   temp=seat in self.temp_furiten,
                                   riichi=seat in self.riichi_furiten)

    def all_closed(self) -> bool:
        """这一局到目前为止没有任何人鸣过牌。"""
        return not self.db._one("SELECT COUNT(*) FROM round_melds WHERE round_id=?",
                                (self.round_id,))

    # ══════════════════════════════════════════════════════════════════════
    #  发给客户端的视图
    # ══════════════════════════════════════════════════════════════════════
    def start_wind(self) -> str:
        """本半庄第一局的风场（风盘用它决定显示哪张「东南X」图）。

        半庄不一定从东场开（用户口径「开局南场的玩家」），所以不能写死 dong。
        """
        if self._start_wind is None:
            try:
                row = self.db._row(
                    "SELECT wind FROM rounds WHERE match_id=? ORDER BY round_index LIMIT 1",
                    (int(self.round.get("match_id", 0) or 0),))
            except Exception:                              # noqa: BLE001
                row = None
            self._start_wind = str(row["wind"]) if row else str(self.round_wind)
        return self._start_wind

    def state_for(self, seat: int | None = None) -> dict:
        pub = self.db.public_state(self.round_id)
        st = {
            "round_id": self.round_id,
            "wind": self.round_wind, "number": self.round["number"], "honba": self.round["honba"],
            # 风盘用：本半庄从哪个风场开始（东一..南四 的「风场」= dong/nan/xi/bei）
            "start_wind": self.start_wind(),
            # 场次数据：只暴露「半庄第几场（东一..南四）」和「几本场」
            "round_name": round_name(self.round_wind, self.round["number"]),
            "round_info": {
                "name": round_name(self.round_wind, self.round["number"]),
                "honba": self.round["honba"],
            },
            "dealer": self.dealer, "turn": self.turn, "phase": self.phase,
            "live_left": self.live_left(), "dora": self.revealed_dora("dora"),
            # discards 每行都带 called：被吃/碰/杠拿走的那张标 1，
            # 客户端照着把那张牌从牌河里藏起来（牌已经进了别人的副露，别再显示一次）
            "riichi_sticks": pub["round"]["riichi_sticks"],      # 场上挂着的立直供托（根）
            "scores": pub["scores"], "discards": pub["discards"], "melds": pub["melds"],
            "hand_counts": pub["hand_counts"],
            "riichi": [s for s in range(4) if self.is_riichi(s)],
            "result": self.result,
            # ── 牌山（编号系统在服务端，客户端照着画）──
            "dice": list(self.dice) if self.dice else [],
            "first_stack": self.wall_first_stack(),
            "start_side": self.wall_start_side(),
            "round_phase": self.round_phase,
            "deal_done": self.deal_done(),
            "deal_i": self.deal_i,
            "deal_steps": len(self.deal_plan()["steps"]),
            "next_no": self.next_no,
            "rinshan_used": self.rinshan_used,
            "dora_revealed": self.dora_revealed,
            "dora_stacks": ([wallmodel.dora_stack_no(self.wall_first_stack(), i)
                             for i in range(self.dora_revealed)] if self.dice else []),
            "wall_taken": self.wall_taken(),
            "ura": (self.revealed_dora("ura")
                    if (seat is not None and (self.is_riichi(seat)
                                              or self.c39s2_fake(seat))) else []),
            # 食い替え：刚鸣完不能打哪张（给客户端拦一下，服务端自己也拦）
            "pending_kuikae": self.pending_kuikae,
            # 四家的牌河（按 seat 分开摆），客户端画桌面用
            "all_discards": [self.discards(s) for s in range(4)],
            # 四家的副露（每家每组都在），tiles 已经按摆放顺序排好
            "all_melds": [self.melds(s) for s in range(4)],
            # 四喜：用手里的东/北明置给大家看（公开信息）
            "c10s2_reveal": [{"seat": int(s), "tiles": list(v.get("reveal") or [])}
                             for s, v in sorted(self.c10s2.items())
                             if (v.get("reveal") or [])],
        }
        if seat is not None:
            ti = self.tenpai_info(seat)
            # 决斗也要看得见自己摸到的牌（用户口径：明置牌，不存在"隐藏"）
            hidden_draw = False
            # 「刚摸到那张」在 hand 数组里的下标：换牌后牌面会重复，客户端不能靠牌面找
            if hidden_draw:
                _drawn_index = -1
            else:
                _rows = self.db.my_hand(self.round_id, seat)
                _drawn_index = next((i for i, r in enumerate(_rows)
                                     if int(r["is_drawn"] or 0)), -1)
            st.update({"seat": seat,
                       "drawn_index": int(_drawn_index),
                       # 决斗里非决斗家看不到自己摸进的牌 → 只发 13 张、drawn 留空
                       "hand": (self.hand13(seat) if hidden_draw else self.hand(seat)),
                       "my_melds": self.melds(seat),
                       "waits": ti["waits"], "legal": self.legal_actions(seat),
            "drawn_count": len(self.hand(seat)),
                       "tenpai": ti, "furiten": self.furiten(seat),
                       "drawn": ("" if hidden_draw else self.drawn_tile(seat)),
                       # 本小局已经用过的一次性技能（客户端据此把图标变灰）
                       # 本小局被【看破 / 封堵】剔除的卡：客户端点图标时能说清原因
                       # （以前一律提示「不在使用时机」，玩家会以为是时机问题）
                       "poked_cards": sorted({
                           int(k.split(":")[1]) for k in self.poked
                           if k.count(":") == 1 and k.startswith("%d:" % int(seat or 0))}),
                       # 原技能那份配额用掉的（只发原技能；复制品单独发，
                       # 否则同座位同卡号时客户端没法分辨该灰哪一个图标）
                       "used_skills": [k for k in sorted(self.used_skills)
                                       if k.endswith("-%d" % int(seat or 0))],
                       "copy_used": [k for k in sorted(self.used_copy)
                                     if k.endswith("-%d" % int(seat or 0))],
                       "copy_granted": [k for k in sorted(self.cc_grants)
                                        if k.endswith("-%d" % int(seat or 0))],
                       # 自信：本小局是不是已经发动（客户端给图标套红框）
                       "confident": seat in self.confident,
                       "tenacity": self.owns_tenacity(seat),
                       # 降神：掷到的花色 + 开关（别人看不到）
                       "oracle": self.oracle_view(seat),
                       # 恶灵：降神发动过 → 本局只能门清自摸和
                       "oracle_lock": self._oracle_lock(seat),
                       # 决斗：现在跟谁打 / 我是不是被限制（只能暗置摸切）/ 能不能发动
                       "duel": self.duel_view(seat),
                       "duel_can": self.duel_can_start(seat),
                       "duel_drawn_hidden": hidden_draw,
                       # 10 号卡 S2「四喜」：能不能发动 / 数到第几张 / 已经就绪
                       "po10_pts": int(self.po10_pts),
            "shenshan_on": int(seat) in self.shenshan,
            # 思路（36S1）看的牌和「感知 / 研究」用同一条渲染链 → 并进来
            "reveal_hands": [
                {"seat": int(t), "tiles": [str(x) for x in self.hand(int(t))]}
                for t in sorted(set(self.reveal_hands.get(int(seat), set()))
                                | set(self.c36_watch.get(int(seat), set()))
                                | set(self.c40_show.get(int(seat), set()))
                                | (set(self.c44s2_on) - {int(seat)})
                                | ({int((self.c40s2 or {}).get("target", -1))}
                                   if int((self.c40s2 or {}).get("by", -1)) == int(seat)
                                   else set()))],
            "c36": {"on": sorted(int(x) for x in self.c36_watch.get(int(seat), set())),
                    "s2": int(self.c36s2_on) == int(seat)},
            # 岭上开花（37S1）：牌已经换好、等我点『自摸』
            "c37": {"ready": int(self.c37s1_ready) == int(seat)},
            # 透视（40S1）：对每一家还剩几次（初始 1）/ 现在正看着谁
            "c40": {"counts": {str(t): self.c40s1_left(int(seat), t)
                               for t in range(4) if int(t) != int(seat)},
                    "shown": sorted(int(x) for x in self.c40_show.get(int(seat), set()))},
            # 协战卡手动遮罩：{座位: 卡号}（只放**现在真的生效**的：卡换掉就自动没）
            "support_mute": {str(s2): int(skills.support_muted(self.db, self, s2))
                             for s2 in range(4)
                             if int(skills.support_muted(self.db, self, s2)) > 0},
            # 拦截树：现在等我回答的询问（可能有**多条**，各带 id）
            "asks": self.act_ask_view(int(seat)),
            # 免疫（43S2）：还剩几次 / 该我回答的那一问 / 我免疫的技能
            "c43s2": {"left": self.c43s2_left(int(seat)),
                      "ask": (dict(self.c43_ask) if (self.c43_ask
                              and int(self.c43_ask.get("owner", -1)) == int(seat))
                              else None),
                      "immune": sorted(self.c43s2_imm.get(int(seat), set()))},
            # 同盟（40S2）：能不能发动 / 我指定的那家 / 等我挑搭子
            "c40s2": {"can": self.c40s2_can(int(seat)),
                      "on": (int((self.c40s2 or {}).get("by", -1)) == int(seat)),
                      "target": (int((self.c40s2 or {}).get("target", -1))
                                 if int((self.c40s2 or {}).get("by", -1)) == int(seat)
                                 else -1),
                      "offer": (dict(self.c40s2_offer) if (self.c40s2_offer
                                and int(self.c40s2_offer.get("by", -1)) == int(seat))
                                else None)},
            # NO MISS（43S1）：能不能发动 / 牌河里可当搭子的那些 seq
            "c43": {"can": self.c43s1_can(int(seat)),
                    "rivers": (self.c43s1_river_seqs(int(seat))
                               if self.c43s1_can(int(seat)) else [])},
            # 复制（41S1）：有没有可复制的技能 / 我已经复制到的那些
            "c41": {"ask": self.c41_ask_view(int(seat)),
                    "copies": [{"card": int(x.get("card", 0)),
                                "skill": int(x.get("skill", 0)),
                                "from": int(x.get("from", -1)),
                                "name": skills.info(int(x.get("card", 0)),
                                                    int(x.get("skill", 0))).get("name", "")}
                               for x in self.c41_copies.get(int(seat), [])]},
            "kangpo_ask": (self.kangpo_ask
                           if int((self.kangpo_ask or {}).get("owner", -1)) == int(seat)
                           else None),
            # 有人正在决定是否看破 → 谁都别推进（客户端据此不开技能面板）
            "kangpo_wait": self.kangpo_pending is not None,
            "ignite_ok": bool(self.ignite_ok),
            "ignite_done": bool(self.ignite_done),
            "shenshan_can": self.shenshan_can(seat),
            "shenshan_offer": (self.shenshan_offer
                               if int((self.shenshan_offer or {}).get("seat", -1)) == int(seat)
                               else None),
            "nongwu_can": self.nongwu_can(seat),
            "nongwu_on": bool(self.nongwu and int(self.nongwu.get("by", -1)) == int(seat)),
            "qianlu_can": self.qianlu_can(seat),
            "qianlu": (self.qianlu if int((self.qianlu or {}).get("seat", -1)) == int(seat) else None),
            "gift": int(self.gift.get(int(seat), 0)),
            "gift_can": self.gift_can(seat),
            "gift_used": int(seat) in self.gift_used,   # 段2 换牌用过没有
            "yiding": int(seat) in self.yiding,
            "yiding_can": self.yiding_can(seat),
            "yiding_tiles": self.yiding_discards(seat),
            "yiding_src": self.yiding_src_of(seat),
            "guobiao_can": self.guobiao_can(seat),
            "guobiao_tiles": self.guobiao_discards(seat),
            "xianfu_can": self.xianfu_can(seat),
            "youyin_can": self.youyin_swap_can(seat),
            "youyin_meld_can": self.youyin_meld_can(seat),
            "youyin_meld_offer": (self.youyin_meld_offer
                                  if int((self.youyin_meld_offer or {}).get("seat", -1))
                                  == int(seat) else None),
            "gift_offer": (self.gift_offer
                           if int((self.gift_offer or {}).get("seat", -1)) == int(seat)
                           else None),
            "gift_swap_can": self.gift_can(seat),
            "youyin_offer": (self.youyin_offer
                             if int((self.youyin_offer or {}).get("seat", -1)) == int(seat) else None),
            "heat_kind": self.heat_kind,
            "heat_can": self.heat_can(seat),
            "cold_left": len(COLD_KINDS),
            "chuancheng_can": self.chuancheng_can(seat),
            "chuancheng_list": self.chuancheng_list(seat) if self.chuancheng_can(seat) else [],
            # 传承发动之后：16 号卡变成了谁（客户端据此换图标 + 点击路由）
            "chuancheng": {
                "used": bool(self.skill_used(seat, 16, 1)),
                "can": bool(self.chuancheng_can(seat)),
                "copy": ((lambda _c: {"card": int(_c["card"]), "skill": int(_c["skill"]),
                                      "name": skills.info(int(_c["card"]),
                                                          int(_c["skill"])).get("name", "")})(
                    self.cc_copy[seat]) if int(seat) in self.cc_copy else None),
            },
            "jiasuo_mine": int(self.jiasuo.get(int(seat), 0)),
            "jiasuo_can": self.jiasuo_can(seat),
            "kangpo_can": self.kangpo_can(seat),
            "kangpo_list": self.kangpo_list(seat) if self.kangpo_can(seat) else [],
            "no_win": int(seat) in self.no_win,
            "yanjiu_seat": int(self.yanjiu.get(int(seat), -1)),
            "yanjiu_tiles": ([str(t) for t in self.hand(int(self.yanjiu[int(seat)]))]
                             if int(seat) in self.yanjiu else []),
            "ura_peek": (self.revealed_dora("ura") if int(seat) in self.jiasuo else []),
            "link_can": self.link_can(seat),
            "link_to": int(self.link.get(int(seat), -1)),
            "zhalie_can": self.zhalie_can(seat),
            "zhalie_seqs": self.zhalie_targets(seat),
            "diaoyu_can": self.diaoyu_can(seat),
            # 立直家手牌锁定 → 直接不列出来（客户端照着这份名单画可选目标）
            "diaoyu_opts": ({str(t): self.diaoyu_options(seat, t) for t in range(4)
                             if not self.hand_locked(t)}
                            if self.diaoyu_can(seat) else {}),
            "diaoyu_locked": bool(self.diaoyu_locked),
            "shanggou": self.shanggou_active(seat),
            "pofa_can": self.pofa_can(seat),
            "pofa_seqs": self.pofa_seqs(seat),
            # 统一询问锁：客户端据此停止自动推进（别人看不到内容，只停住）
            "prompt": self.prompt_state(),
            "pofa_stage": ("discard" if self.pofa_discard_pending == int(seat)
                           else ("ask" if self.pofa_can(seat) else "")),
            "xianfu_first": int(self.first_riichi_seat(int(seat)))
                            if self.xianfu_pending else -1,
            # 先负：已经换过牌、还没立直（客户端据此收面板 + 提示「去立直」）
            "xianfu_armed": (int(self.xianfu_armed)
                             if self.xianfu_armed is not None else -1),
            # 未来（24S2）：摸牌前调接下来的 5 张
            "future_can": self.future_can(seat),
            "future_armed": int(self.future_armed) == int(seat),
            "future_tiles": self.future_view(seat),
            # 云外镜 / 天梯（26S1 / 26S2）
            "c26s1_on": self.skill_used(int(seat), 26, 1),
            "c26s2_on": int(seat) in self.c26s2_on,
            "c26_n": int(self.c26_n.get(int(seat), 0)),
            "c26_can": self.c26_can_sort(int(seat)),
            "c26_tiles": self.c26_view(int(seat)),
            # 调包 / 命中（27S1 / 27S2）
            "c27s1_can": self.c27s1_can(seat),
            "c27s1_rivers": self.c27s1_targets(seat),
            "c27s2_can": self.c27s2_can(seat),
            "c27s2_tiles": self.c27s2_discards(seat),
            "c27_mark": int(self.c27_mark.get(int(seat), -1)),
            "c27_cnt": int(self.c27_cnt.get(int(seat), 0)),
            "c27_s2_on": int(seat) in self.c27_s2,
            "c28s1_on": int(seat) in self.c28s1_on,
            "c44s2_on": int(seat) in self.c44s2_on,
            "c44s2_can": self.c44s2_can(int(seat)),
            # 神境（45S1）：摸牌前能不能发动 / 我的牌河张数 / 能挑的弃牌
            "c45": {"can": self.c45s1_can(int(seat)),
                    "on": int(seat) in self.c45s1_on,
                    "mine": self.my_discard_count(int(seat)),
                    "rivers": (self.c45s1_rivers(int(seat))
                               if self.c45s1_can(int(seat)) else [])},
            "c45s2": self.c45s2_view(int(seat)),
            # 隐形（39S1）：能不能发动 / 已经开着
            "c39": {"can": self.c39s1_can(int(seat)),
                    "on": bool(self.c39s1_on),
                    "s2": self.c39s2_fake(int(seat))},
            # 理论战 / 夺目（42S1 / 42S2）
            "c42": {"s1_can": self.c42s1_can(int(seat)),
                    "on": bool(self.c42s1_on),
                    "s2_can": self.c42s2_can(int(seat)),
                    "target": int(self.c42s2_target),
                    # 结算前的那一问（问的是「算点数时把谁当庄家」）
                    "ask": self._c42s2_ask_of(int(seat))},
            # 恶听（46S1）：能不能发动 / 哪些手牌切出去能听牌（且待牌确实还在场上）
            "c46": {"can": (self.c46s1_can(int(seat))
                            if (self.phase == "discard" and self.turn is not None
                                and int(self.turn) == int(seat))
                            else False),
                    "tiles": (self.c46s1_tiles(int(seat))
                              if (self.phase == "discard" and self.turn is not None
                                  and int(self.turn) == int(seat))
                              else [])},
            # 技能给的和牌（43S1 / 46S1）：还没结算，本人再点一次技能图标可以取消
            "win_pending": ({"seat": int(self.win_pending.get("seat", -1)),
                             "card": int(self.win_pending.get("card", 0)),
                             "tile": str(self.win_pending.get("tile", ""))}
                            if (self.win_pending
                                and int(self.win_pending.get("seat", -1)) == int(seat))
                            else None),
            "c29s1_can": self.c29s1_can(seat),
            "c29s1_ask": (dict(self.c29s1_offer) if (self.c29s1_offer
                           and int(self.c29s1_offer.get("seat", -1)) == int(seat)) else None),
            "c28s1_any": bool(self.c28s1_on),
            # 一发（24S1）
            "c24_can": self.c24_can(seat),
            "c24_tiles": (self.riichi_discards(seat) if self.c24_can(seat) else []),
            "c24_armed": int(self.c24_armed) == int(seat),
            "c24_win": self.c24_win_can(seat),
            # 宝牌运（25S1）
            "c25_on": int(seat) in self.c25_on,
            "c25_kinds": self._dora_kinds(),
            # 宝牌的集合（25S2）
            "c25s2_on": int(seat) in self.c25s2_on,
            "c25s2_can": (self.phase == "deal_skill"
                          and int(self.c25s2_pending) == int(seat)),
            "c25s2_offer": (self.c25s2_offer
                            if (self.c25s2_offer or {}).get("owner") == int(seat)
                            else None),
            "c25s2_tile": (str((self.c25s2_offer or {}).get("tile", ""))
                           if (self.c25s2_offer or {}).get("owner") == int(seat)
                           else ""),
            # 我这家的卡序（主战 → 协战 → 传承）：客户端摸牌前的几个询问按它排
            "my_cards": (self._seat_cards(int(seat)) if seat is not None else []),
            "dawa": self.owns_dawa(seat),
            "haishin_offer": (self.haishin_offer
                              if (self.haishin_offer or {}).get("owner") == int(seat) else None),
            "haishin_can": self.haishin_can(seat),
            "haishin_on": bool(self.haishin_on),
            "haishin_step": int(self.haishin_step.get(int(seat), 0)),
            "haishin_gate": (self.haishin_gate == int(seat)),
            "xn_can": self.xn_can(seat),
            "x_skip": {str(k): int(v) for k, v in self.x_skip.items()},
            "char_states": self._char_states(-1 if seat is None else int(seat)),
            "card11_can": self.card11_can(seat),
            "card11s2_can": self.card11s2_can(seat),
            "card11s2_seqs": self._c11s2_targets(seat),
            "card11_win": (self.c11_win == int(seat)),
            "card10s2_can": self._c10s2_can(seat),
                       "card10s2_count": int((self.c10s2.get(seat) or {}).get("count", 0)),
                       "card10s2_ready": bool((self.c10s2.get(seat) or {}).get("ready", False)),
                       "card10s2_reveal": list((self.c10s2.get(seat) or {}).get("reveal") or []),
                       # 10 号卡「鬼门」：能不能用 / 东和北各换过没有
                       "card10_can": self.card10_can(seat),
                       "card10_used": [k for k in ("dong", "bei")
                                       if self._c10_key(seat, k) in self.c10_used],
                       # 09 号卡：能不能用 / 下一次必须用哪个（0=随便）
                       "card09_can": self.card09_can(seat),
                       "card09_next": int(self.c09_next.get(seat, 0)),
            # 点选阶段用：这两组 seq 之外的一律点不中（换过的行/被鸣走/暗置/立直牌）
            "card09_own_seqs": self.card09_targets(seat, 1),
            "card09_other_seqs": self.card09_targets(seat, 2),
            # 染手（33S1）：用过没有 / 现在能不能发 / 可选哪些牌河位置
            "c33": {"used": int(seat) in self.c33s1_on,
                    "can": self.c33s1_can(seat),
                    "rivers": (self.c33_river_seqs(seat)
                               if self.c33s1_can(seat) else [])},
            # 记忆（33S2）：能不能发 / 整场用过没有 / 下一张要不要暗置
            # 厄运（34S1）：谁是发动者 / 我这边还剩几巡 / 我是不是在静默期
            "c34": {"by": int(self.c34_by),
                    "left": int(self.c34_left),
                    "muted": self.c34_muted(int(seat)),
                    "charges": self.c34_charges_of(int(seat)),
                    "s2": int(self.c34s2_on) == int(seat),
                    "s2_why": (self.c34s2_why
                               if int(self.c34s2_why_seat) == int(seat) else "")},
            # 流势（35S1）：轮到排牌山时给「接下来 4 张」，客户端自动弹面板
            "c35": {"can": self.c35_can(int(seat)),
                    "mark": int(self.c35_mark),
                    "k": self.c35_count(),
                    "tiles": self.c35_view(int(seat))},
            "c33s2": {"can": self.c33s2_can(seat),
                      "used": self.skill_used(int(seat), 33, 2),
                      "armed": int(self.c33s2_armed) == int(seat),
                      # 上一局我的净得失（None = 东一第一局，随便输）
                      "last": (self.c33s2_last_points(seat)
                               if (self.phase == "discard"
                                   and self.turn is not None
                                   and int(self.turn) == int(seat))
                               else None)},
                       # 决斗标记：场上有几个标记 / 我的计数器 / 我有没有标记
                       "duel_marks": len(self.duel_marks),
                       "duel_counter": int(self.duel_counter.get(seat, 0)),
                       "duel_marked": seat in self.duel_marks,
                       # 压制：一次性那段用过没有 / 暗置牌对我是不是明牌
                       "press_used": seat in self.press_used,
                       "press_can": self.press_can(seat),
                       "sees_face_down": self.sees_face_down(seat),
                       "must_tsumogiri": seat in self.must_tsumogiri,
                       # 配牌阶段技能：还有谁没决定 / 我能发动什么
                       "deal_skill": {
                           "pending": (sorted(self.deal_wait)
                                       if self.phase == "deal_skill" else []),
                           "mine": (self._deal_skill_options(seat)
                                    if (self.phase == "deal_skill"
                                        and seat in self.deal_wait
                                        and not (self.deal_flow
                                                 and int(self.deal_flow.get("seat", -1)) == seat))
                                    else []),
                       },
                       # 风神：正在跟谁换、还差几张
                       "deal_flow": self.deal_flow_view(seat),
                       # 自风：风神发动后自动生效；现在是不是在等我和别人换牌
                       "self_wind": seat in self.self_wind,
                       "wind_swap": self.wind_swap_view(),
                       # 策略：剩余次数 / 换牌机会 / 额外摸切是否已挂上 / 是否要我盖牌
                       "card05": {
                           "counter": int(self.card05_counter.get(seat, 0)),
                           "offer": self.card05_offer.get(seat),
                           "extra": seat in self.card05_extra,
                           "hide_request": seat in self.card05_pending_hide,
                           "hidden": len(self.card05_hidden.get(seat) or []),
                           "nuki": int(self.nuki_count.get(seat, 0)),
                       },
                       # 技能播报（全场共用一个 id，客户端只看 id 变没变）
                       "broadcast": self.broadcast,
                       # 已经翻明的人物卡（别人视角不再盖住）
                       "revealed": sorted(self._revealed_cache),
                       # 画板：指定的三张 + 已经给过的 + 压在卡下等我摸的明牌
                       "board": self.board_view(seat),
                       # 四家的「明牌」公开信息（谁卡下压着什么）
                       "boards_pending": {str(k): [p["tile"] for p in (v.get("pending") or [])]
                                          for k, v in self.boards.items()},
                       })
            if self.pending:
                # ★ 已经答过的座位（点过吃/碰/荣/跳过）不再下发可选项：
                #   否则客户端会继续显示「吃」按钮（还会按优先级挪到一号位），
                #   并且以为「我这边还有事要做」→ 不再推进对局 → 全桌卡死。
                _ans = self.pending.get("answers") or {}
                _opts = ([] if seat in _ans
                         else list(self.pending["options"].get(seat, [])))
                st["claim"] = {"tile": self.pending["tile"], "from": self.pending["from"],
                               "options": _opts, "answered": seat in _ans}
        st["tiles"] = self._tile_states(seat)
        return st

    def _tile_states(self, seat: int | None) -> list[dict]:
        """136 张实体状态，按视角做可见性/形式转换。

        · 自己手牌 → form='hand'（正面）；别人手牌 → form='back'（背面）
        · 副露 face_meld 公开可见；暗杠 back_meld 只有本人可见正面，别人见背
        · 牌河/宝牌公开可见；牌山/王牌隐藏
        """
        out = []
        for t in self.db.entity_states(self.round_id):
            loc, form, tseat = t["loc"], t["form"], t["seat"]
            if loc == "hand":
                if seat == tseat:
                    form = "hand"
                else:
                    form = "back"
            elif loc == "meld":
                if form == "back_meld" and seat != tseat:
                    form = "back_meld"          # 别人看暗杠 = 背
                else:
                    form = "face_meld"
            elif loc == "wall" or loc == "dead":
                form = "hidden"
            t["form"] = form
            out.append(t)
        return out

    # ══════════════════════════════════════════════════════════════════════
    #  可选动作
    # ══════════════════════════════════════════════════════════════════════
    def legal_actions(self, seat: int) -> list[dict]:
        if self.phase == "ended" or self.round_phase == "deal":
            return []                                # 配牌阶段谁也不能动
        if self.phase == "claim":
            if (self.pending and seat in self.pending["options"]
                    and seat not in self.pending["answers"]):
                return list(self.pending["options"][seat]) + [{"action": "pass"}]
            return []
        if self.phase != "discard" or seat != self.turn:
            return []
        if self._win_pending_of(seat) > 0:
            # 【换完 / 切完就能和】（43S1 NO MISS / 46S1 恶听）：只弹「自摸」，点了才结算
            return [{"action": "tsumo", "pending": True,
                     "card": self._win_pending_of(seat)}]
        if int(self.c45s2_wait) == int(seat):
            # 【替身】（用户口径 2026-10-28）：这一手彻底交给第二位 —— 连自摸都不给
            return []
        # Card34 S1【厄运】：静默期只能摸切 —— 不能和 / 杠 / 立直 / 技能自摸
        if self.c34_muted(seat):
            _d0 = self.drawn_tile(seat)
            return [{"action": "discard", "tiles": [str(_d0)] if _d0 is not None else []}]
        hand = self.hand(seat)
        melds = self.melds(seat)
        if self.duel_restricted(seat):
            # 决斗：被限制的那家只能打刚摸到的那张（手动点，不再自动打）
            _d0 = self.drawn_tile(seat)
            out = [{"action": "discard", "tiles": [str(_d0)] if _d0 is not None else []}]
        else:
            _drawn_now = self.drawn_tile(seat)
            if (self.is_riichi(seat) or int(seat) in self.c27_s2) \
                    and _drawn_now is not None:
                # 立直 / 命中之后只能摸切（_do_discard 有硬校验），列表必须一致，
                # 否则客户端把其它手牌也画成可点 → 点了被拒、看起来像卡死。
                out = [{"action": "discard", "tiles": [str(_drawn_now)]}]
            else:
                out = [{"action": "discard", "tiles": sorted(set(hand))}]
        if self.c24_win_can(seat) and self._tsumo_gate_ok(seat) \
                and self._c28s1_allows(seat, self.drawn_tile(seat) or "", True):
            # 一发：手上这张不一定和得了，但牌山/王牌里有我的胡张 → 给自摸按钮
            # ★ 必须过自摸闸门：以前这里是无条件 append，浓雾 / 恶灵都拦不住它。
            out.append({"action": "tsumo", "c24": True})
        elif self._win_ok(seat, self.drawn_tile(seat) or "", tsumo=True) \
                and self._c28s1_allows(seat, self.drawn_tile(seat) or "", True):
            out.append({"action": "tsumo"})
        if self._skill_plan(seat) and self._tsumo_gate_ok(seat):
            arm = self.armed_skill or {}
            out.append({"action": "skill_tsumo",
                        "card": int(arm.get("card", 0)),
                        "skill": int(arm.get("skill", 0))})
        for k in calls.ankan_options(hand):
            if self.ankan_allowed(seat, k):      # 立直后：必须不改变听牌
                out.append({"action": "ankan", "tile": k})
        for k in calls.kakan_options(hand, melds):
            if self.kakan_allowed(seat, k):      # 立直后不能加杠
                out.append({"action": "kakan", "tile": k})
        if self.can_riichi(seat):
            out.append({"action": "riichi",
                        "tiles": self.riichi_discards(seat)})
        if self.yiding_can(seat):
            out.append({"action": "yiding", "tiles": self.yiding_discards(seat)})
        if self.guobiao_can(seat):
            out.append({"action": "guobiao", "tiles": self.guobiao_discards(seat)})
        if (not melds and self.all_closed()
                and calls.can_kyuushu_kyuuhai(self.hand_counts(seat), melds)):
            out.append({"action": "kyuushu"})
        return out

    def _counts_without_drawn(self, seat: int) -> list[int]:
        """手牌去掉刚摸的那张（13 张），用来算立直宣言牌。"""
        return counts_of(self.hand13(seat))

    def riichi_discards(self, seat: int) -> list[str]:
        """立直可切的牌 = 切完仍然听牌的牌（**只看形状，不看振听**）。

        按「牌种」算，再映射回手上真实那张（红 5 是 0p/0s/0m，和牌种 5p/5s/5m
        不是同一个字符串，不能直接比）。

        ★ 振听不影响立直：标准规则「振聴でも立直は可能」（只是不能荣和），
          所以这里不滤振听。`can_riichi()` 也按同一口径（不再看振听）。
        """
        hand = self.hand(seat)
        melds = self.melds(seat)
        if len(hand) % 3 == 2:
            kinds = agari.losing_tiles(counts_of(hand), melds)
            pool = list(hand)
        else:
            kinds = agari.losing_tiles(self._counts_without_drawn(seat), melds)
            pool = list(self.hand13(seat))
        ks = set(kinds)
        out: list[str] = []
        seen: set[str] = set()
        for t in pool:
            # ★ 按**具体牌**去重：赤 5（0p）和普通 5（5p）是同一牌种但是两张实体，
            #   以前按 kind 去重 → 手里有 5p 时赤 5 永远进不了列表（立直不能切赤5）。
            if kind_of(t) in ks and t not in seen:
                seen.add(t)
                out.append(t)
        if out:
            return out
        # 兜底：形状算得出、手上却没有对应实体 → 用牌种名（红5 也能对上牌种）
        return list(kinds)

    def can_riichi(self, seat: int) -> bool:
        if int(seat) in self.c45s1_on:
            return False                 # 【神境】：不能立直
        if (self.is_riichi(seat) or self.phase != "discard" or seat != self.turn
                or self.live_left() < 4):
            return False
        melds = self.melds(seat)
        if not agari.is_closed(melds):
            return False
        if self.scores().get(seat, 0) < 1000:
            return False
        # ★ 振听不拦立直（振聴立直是合法牌型，只是不能荣和）：
        #   以前这里判「永久振听 / 同巡振听」→ 听牌却振听的人永远看不到立直按钮，
        #   而且先负换完牌如果是单骑待自己切的牌，就再也立不了直（先负白用）。
        return bool(self.riichi_discards(seat))

    # ══════════════════════════════════════════════════════════════════════
    #  服务器驱动
    # ══════════════════════════════════════════════════════════════════════
    def start(self) -> dict:
        if not self.dice:
            self.dice = wallmodel.roll()                      # 投骰子（服务端说了算）
            self.deal_i = 0
            self.rinshan_used = 0
            self.dora_revealed = 0
            self.next_no = wallmodel.first_stack_no(self.dice) * 2 - 1
        if self.deal_i == 0:
            self.round_phase = "deal"                         # 开局 = 配牌阶段
            self._apply_test_deal()                           # Test.txt：指定手牌 / 牌山
        self.phase = "draw" if self.round_phase == "deal" else self.phase
        self.save_flags()
        return self._event("round_start", {"dealer": self.dealer, "dice": list(self.dice),
                                          "first_stack": self.wall_first_stack(),
                                          "start_side": self.wall_start_side()})

    def _apply_test_deal(self) -> None:
        """Test.txt：把指定的起始手牌 / 牌山写进牌山（必须在配牌之前改）。

        · 只作用于「半庄第一局」（东一 0 本场），其它局照常随机
        · 文件里没写这两节 → 什么都不做，和正式完全一样
        · 手牌优先于牌山（同一张位置冲突时以手牌为准）
        """
        if not (self.round_wind == "dong" and int(self.round["number"]) == 1
                and int(self.round["honba"]) == 0):
            return
        if self.db._one("SELECT COUNT(*) FROM round_hands WHERE round_id=?", (self.round_id,)):
            return                                    # 已经发过牌了，不再动
        targets = testfile.wall_targets()
        targets.update(testfile.hand_targets(self))
        if targets:
            testfile.apply_wall(self.db, self.round_id, targets)

    # ══════════════════════════════════════════════════════════════════════
    #  牌山（编号系统只在这里；客户端照着画）
    # ══════════════════════════════════════════════════════════════════════
    def wall_first_stack(self) -> int:
        """从第几墩开始拿 = 骰子点数 + 1。"""
        return wallmodel.first_stack_no(self.dice) if self.dice else 0

    def wall_start_side(self) -> str:
        return wallmodel.start_side(self.dice) if self.dice else ""

    def deal_plan(self) -> dict:
        return (wallmodel.deal_plan(self.wall_first_stack(), self.dealer)
                if self.dice else {"steps": []})

    def deal_done(self) -> bool:
        return self.deal_i >= len(self.deal_plan()["steps"])

    def _tile_of_no(self, no: int) -> str:
        return self.db.tile_at_seq(self.round_id, wallmodel.seq_of_tile(no)) or ""

    def deal_step(self) -> dict:
        """配牌下一步：把这一步的牌发出去（庄家那一步连第 14 张一起「跳牌」）。"""
        plan = self.deal_plan()
        steps = plan["steps"]
        if not steps:
            return self._event("deal_error", {"msg": "还没投骰子"})
        if self.deal_i >= len(steps):
            ev = self._finish_deal()                          # 已经发完 → 进切牌 + 翻宝牌
            self.save_flags()
            return self._event("deal_done", {"next_no": self.next_no, "dora": ev,
                                             "phase": self.round_phase})
        st = steps[self.deal_i]
        seat = int(st["seat"])
        for no in st["tiles"]:
            self.db.draw_seq(self.round_id, seat, wallmodel.seq_of_tile(no),
                             self._tile_of_no(no), drawn=False)
        if st.get("jump"):
            self.db.draw_seq(self.round_id, seat, wallmodel.seq_of_tile(st["jump"]),
                             self._tile_of_no(st["jump"]), drawn=True)
            self.next_no = int(plan["next_no"])               # 跳牌把指针顶到下一位
        self.deal_i += 1
        self._finish_deal()
        self.save_flags()
        return self._event("deal", {"seat": seat, "tiles": st["tiles"], "jump": st.get("jump"),
                                    "round": st["round"]})

    def _finish_deal(self) -> dict | None:
        """最后一步发完 → 配牌结束（切牌阶段）+ 翻第 n-3 墩的宝牌指示牌。"""
        if self.round_phase != "deal" or self.deal_i < len(self.deal_plan()["steps"]):
            return None
        self.round_phase = "play"                             # 配牌 → 切牌
        self.turn = self.dealer                               # 轮到庄家打牌
        self.phase = "discard"
        # 有「配牌阶段发动」技能的人要先决定（发动 / 跳过），之后庄家才能切牌
        self.deal_wait = set()
        self.deal_used = set()
        self.deal_queue = []
        self._open_deal_window()
        return self.reveal_dora()

    def kan_count(self) -> int:
        """这一局开了几次杠（明杠 / 暗杠 / 加杠）。

        加杠是把原来的「碰」升级成 4 张，所以按 round_melds 的行数算就对了。
        友引（段1）摊出来的 4 张是 open_set，不是杠：不发宝牌、不补岭上，不在这里。
        """
        return int(self.db._one(
            "SELECT COUNT(*) FROM round_melds WHERE round_id=? "
            "AND kind IN ('minkan','ankan','kakan')", (self.round_id,)) or 0)

    def expected_dora(self) -> int:
        """宝牌指示牌应该翻开几张 = 开局那 1 张 + 每次杠 1 张。"""
        return 1 + self.kan_count()

    def _draw_rinshan(self, seat: int, force: bool = False) -> str | None:
        """岭上摸牌：按「第一张 → 第四张」的顺序从王牌里拿。

        ★ 只有「开过杠」才允许摸岭上（rinshan_used 不能超过杠数）。
          以前客户端可以发 op=draw&dead=true 凭空把岭上牌摸走，
          导致后面真杠补到错牌。force=True 只给测试用。
        """
        nos = wallmodel.rinshan_tile_nos(self.wall_first_stack())
        if not self.dice or self.rinshan_used >= len(nos):
            return None
        if not force and self.rinshan_used >= self.kan_count():
            return None
        no = nos[self.rinshan_used]
        self.rinshan_used += 1
        return self.db.draw_seq(self.round_id, seat, wallmodel.seq_of_tile(no),
                                self._tile_of_no(no), drawn=True, dead=True)

    def reveal_dora(self, force: bool = False) -> dict | None:
        """翻下一张宝牌指示牌：一墩两张，上面那张是表宝牌、下面那张是里宝牌。

        ★ 宝牌只能由「开局 1 张 + 每次杠 1 张」翻出来：数量对不上就拒绝。
          （历史上 op=dora 可以被客户端随便调 → 没有杠也翻出 3 张杠宝牌。）
          force=True 只给测试用。
        """
        if not self.dice or self.dora_revealed >= wallmodel.DORA_STACKS:
            return None
        if not force and self.dora_revealed >= self.expected_dora():
            return None
        n = self.wall_first_stack()
        no_d, no_u = wallmodel.dora_tile_nos(n, self.dora_revealed)
        dora, ura = self._tile_of_no(no_d), self._tile_of_no(no_u)
        self.db.add_dora(self.round_id, "dora", self.dora_revealed, dora, dora_from_indicator(dora))
        self.db.add_dora(self.round_id, "ura", self.dora_revealed, ura, dora_from_indicator(ura))
        stack = wallmodel.dora_stack_no(n, self.dora_revealed)
        self.dora_revealed += 1
        self.save_flags()
        return {"idx": self.dora_revealed - 1, "stack": stack,
                "indicator": dora, "ura": ura}

    def _draw_next_info(self, seat: int) -> dict | None:
        """普通摸牌：从牌山「前面」拿一张，跳过王牌那 6 墩；活牌摸完返回 None。"""
        if not self.dice or self.live_left() <= 0:
            return None
        no = wallmodel.next_live_no(self.next_no, self.wall_first_stack())
        if no is None:
            return None
        self.next_no = wallmodel.wrap_tile(no + 1)
        seq = wallmodel.seq_of_tile(no)
        tile = self.db.draw_seq(self.round_id, seat, seq, self._tile_of_no(no), drawn=True)
        if tile is None:
            return None
        self._c10s2_on_draw(seat)                 # 四喜：数摸牌次数
        return {"tile": tile, "seq": seq}

    def _draw_next(self, seat: int) -> str | None:
        info = self._draw_next_info(seat)
        return info["tile"] if info else None

    def wall_taken(self) -> list[int]:
        """已经拿走的牌编号（客户端拿去改牌墩显示）。"""
        return self.db.wall_taken_nos(self.round_id)

    def advance(self) -> dict:
        """帮当前该摸牌的那家摸牌；牌山摸完 → 荒牌流局。"""
        res = self._advance()
        self.save_flags()
        return res

    def _advance(self) -> dict:
        if self.phase == "ended":
            return self._event("ended", {})
        if self.round_phase == "deal":
            return self._event("dealing", {"msg": "配牌阶段，请用 deal_step"})
        if self.phase == "claim":
            return self._resolve_claims()
        if self.phase == "deal_skill" or self.deal_flow:
            return self._event("dealing", {"msg": "配牌技能还没结算完"})
        if self.phase != "draw":
            raise RuleError(f"现在是 {self.phase} 阶段，不能摸牌")
        # 友引（22S2）：四副露单骑 → 摸牌前可以先从牌河挑一张
        # 21S2 段2（馈赠换牌）：摸牌前先问一次（跳过下次继续问）
        if self.turn is not None and self.gift_offer_open(int(self.turn)):
            return self._event("gift", {"seat": int(self.turn)})
        # X神（Card12 S2）：被指定的人跳过摸切
        if self.turn is not None:
            sk = int(self.x_skip.get(int(self.turn), 0))
            if sk > 0:
                s2 = int(self.turn)
                if sk - 1 <= 0:
                    self.x_skip.pop(s2, None)
                else:
                    self.x_skip[s2] = sk - 1
                self.turn = (s2 + 1) % 4
                self.save_flags()
                return self._event("x_skip", {"seat": s2, "left": max(0, sk - 1)})
        return self._draw_common(int(self.turn))

    # ── 摸牌后的统一处理（普通摸牌 / 策略·额外摸切 共用）─────────────
    def _draw_common(self, seat: int) -> dict:
        """摸一张牌，然后把「摸牌后该做的事」全部做完：牌桌压牌、
        海神、深山、自风、振听/一发清理、首摸标记。

        普通摸牌和「策略·额外摸切」都必须走这里 —— 以前额外摸切自己摸了
        一张就完事，绕开了上面那堆钩子（海神/深山不触发、压牌桌被忽略）。
        """
        self._c34_tick(int(seat))                 # 【厄运】：这一家又过了一巡
        # ① 画板：卡下压着别人送来的明牌 → 直接拿它（这一巡不从牌山摸）
        info = self._board_take(seat)
        # ② 否则正常从牌山前面摸（跳过王牌）
        if info is None:
            info = self._draw_next_info(seat)
        if info is None:
            return self._ryuukyoku("exhaustive")
        # ③ 这张牌可能被别人抢（画板 / 深山 / 海神 / 宝牌的集合）：
        #    按「下家 → 对家 → 上家」的座位顺序，谁先能拿就归谁。
        #    画板拿走 → 我重摸（连着好几种就一直重摸）；换牌类 → 等他换完。
        moved: list[dict] = []
        for _ in range(8):
            tile0 = str(info["tile"])
            plan = self._intercept_plan(int(seat), tile0)
            if not plan:
                break
            who, kind = int(plan[0][0]), str(plan[0][1])
            if kind == "board":
                tr = self._board_transfer_to(who, int(seat), info)
                if not tr:
                    break
                moved.append(tr)
                info = self._draw_next_info(seat)
                if info is None:
                    return self._ryuukyoku("exhaustive")
                continue
            # 换牌类：先记摸牌账，再把这张牌挂给抢的人（我停在这里等他换）
            self._draw_bookkeeping(int(seat))
            self._open_intercept(int(seat), tile0, plan)   # 余下的放进 offer["plan"]
            self.save_flags()
            return self._event("draw", {"seat": int(seat), "tile": tile0, "board": moved,
                                        kind: (True if kind == "shenshan" else int(who))})
        got = info["tile"]
        self._draw_bookkeeping(int(seat))
        # 【厄运】：延迟生效的四喜若正好在这三巡里引爆 → 直接作废，不补偿
        if self.c34_muted(int(seat)) and self._c10s2_ready(int(seat)):
            self._c10s2_clear(int(seat))
            self._event("c10s2_wasted", {"seat": int(seat)})
        # Card34 S2【海底】：最后一张摸进来 → 海底自摸（厄运已在这一次摸牌结束）
        if int(self.c34s2_on) == int(seat) and int(self.live_left()) <= 0:
            _ev_last = self._c34s2_last_tsumo(int(seat), info)
            if _ev_last is not None:
                return _ev_last
        elif int(self.c34s2_on) >= 0 and int(self.live_left()) <= 0:
            # 这三巡里有人鸣牌/杠 → 摸牌顺序错开，最后一张落到了别家手里
            self.c34s2_why_seat = int(self.c34s2_on)
            self.c34s2_why = "海底：最后一张被别家摸走了（这三巡里有人鸣牌）"
            self.c34s2_on = -1
            self.save_flags()
        self.last_was_rinshan = False
        self.temp_furiten.discard(seat)          # 摸牌 → 同巡振听解除
        if seat in self.ippatsu and self._ippatsu_over(seat):
            self.ippatsu.discard(seat)           # 立直宣言牌之后又打过 → 一发结束
        owner = self._self_wind_owner(seat, got)
        if owner is not None and (self.c34_muted(int(seat)) or self.c34_muted(int(owner))):
            owner = None                       # 【厄运】：自风三巡内无效
        if owner is not None:
            self.wind_swap = {"owner": int(owner), "from": int(seat), "tile": got}
            self.phase = "wind_swap"
            return self._event("draw", {"seat": seat, "tile": got, "board": moved,
                                        "self_wind": owner})
        self.phase = "discard"
        # Card45 S2【替身】：这家摸完牌 → 由「第二位玩家」指定切哪张
        _s2 = self._c45s2_try(int(seat))
        if _s2 is not None:
            return _s2
        # Card10 S2【四喜】：第 5 张摸到的牌直接视为小四喜自摸（不用再点按钮）
        _c10ev = self._c10s2_auto_tsumo(int(seat), str(got))
        if _c10ev is not None:
            return _c10ev
        return self._event("draw", {"seat": seat, "tile": got, "board": moved})

    def _draw_bookkeeping(self, seat: int) -> None:
        """摸牌后必做的那几件事（被抢牌 / 没被抢 都要做）。"""
        self.press_used.discard(int(seat))       # 新的一巡：压制又可以换一次
        self.save_flags()                        # 标记要落库（换牌判定读的是 flags）
        self.first_draw_done.add(seat)
        self._maybe_grant_yiding(int(seat))     # 一定和牌：听牌就给权限
        # 破发窗口：别人摸牌不影响；只有「持破发卡的人自己摸牌」才过期
        # （以前这里谁摸牌都清 → 别家立直后下家一摸，询问还没发出去窗口就没了）
        if self.pofa_ask is not None and self._has_card13(int(seat)):
            a = self.pofa_ask
            w = [int(x) for x in (a.get("waiting") or [])]
            if int(seat) in w:
                w.remove(int(seat))
            if w:
                a["waiting"] = w
                a["ts"] = time.time()
                self.pofa_ask = a
            else:
                self.pofa_ask = None
                self.pofa_window = None
        # 破发的窗口不在这里关：留着给我方决定（打牌或再次立直时关）

    def _after_discard_hooks(self, seat: int, tile: str) -> None:
        # 【复制】延迟上限：到我下一次切牌就把可复制池清空
        if int(seat) in self.c41_ask:
            self.c41_ask.pop(int(seat), None)
        self._maybe_grant_yiding(int(seat))      # 打完这张听牌了 → 给一定和牌的权限
        # 切牌后，临时观看（感知等）失效；研究（17S1）整局保留
        keep = set()
        if self.skill_used(int(seat), 17, 1):
            keep = set(self.reveal_hands.get(int(seat), set()))
        if int(seat) in self.reveal_hands:
            self.reveal_hands.pop(int(seat), None)
        if keep:
            self.reveal_hands[int(seat)] = keep
        # 前路：预言比对
        ql = self.qianlu or {}
        if int(ql.get("seat", -1)) == int(seat):
            pred = list(ql.get("pred") or [])
            idx = int(ql.get("idx", 0))
            if idx < len(pred) and str(tile) == str(pred[idx]):
                ql["idx"] = idx + 1
                self.qianlu = ql
                if ql["idx"] >= 3:
                    self.yiding_grant(int(seat), 20, 1)      # 前路成功
                    self.qianlu = None
                    self._event("qianlu_done", {"seat": int(seat)})
            else:
                self.qianlu = None
                self._event("qianlu_fail", {"seat": int(seat)})
        # 浓雾：数自己打出的牌
        nw = self.nongwu or {}
        if int(nw.get("by", -1)) == int(seat):
            nw["left"] = int(nw.get("left", 0)) - 1
            self.nongwu = nw if nw["left"] > 0 else None
        # 迷途之家：手切计数
        self._gift_check(int(seat))
        self.save_flags()

    def _has_discarded(self, seat: int) -> bool:
        return bool(self.db._one("SELECT COUNT(*) FROM round_discards WHERE round_id=? AND seat=?",
                                 (self.round_id, seat)))

    def _ippatsu_over(self, seat: int) -> bool:
        """一发巡结束了吗？

        ★ 只算「立直宣言牌**之后**又打过一张」。
          以前这里用的是 `_has_discarded(seat)`（这辈子打没打过牌）——
          可立直宣言牌本身就是一张 discard → 立直玩家在**一发巡摸牌的那一刻**
          就被踢出 ippatsu，一发自摸永远不可能成立。
        """
        s = int(seat)
        row = self.db._row(
            "SELECT declared_seq FROM round_riichi WHERE round_id=? AND seat=?",
            (self.round_id, s))
        if row is None:
            return True
        last = self.db._one(
            "SELECT MAX(seq) FROM round_discards WHERE round_id=? AND seat=?",
            (self.round_id, s))
        return last is not None and int(last) > int(row["declared_seq"])

    # ══════════════════════════════════════════════════════════════════════
    #  玩家动作（统一入口）
    # ══════════════════════════════════════════════════════════════════════
    def act(self, seat: int, action: str, **kw) -> dict:
        allowed = {a["action"] for a in self.legal_actions(seat)}
        if action not in allowed:
            raise RuleError(f"{seat} 现在不能 {action}（可选：{sorted(allowed)}）")
        fn = getattr(self, "_do_" + action, None)
        if fn is None:
            raise RuleError(f"不认识的动作 {action}")
        res = fn(seat, **kw)
        self.save_flags()
        return res

    def pass_claim(self, seat: int) -> dict:
        res = self._do_pass(seat)
        self.save_flags()
        return res

    # ── 打牌 / 立直 / 九种九牌 ──
    def _do_discard(self, seat: int, tile: str | None = None,
                    riichi: bool = False, c25_ok: bool = False,
                    face_down: bool = False, forced: bool = False) -> dict:
        """forced=True：这张不是他自己选的（钓鱼强制他打出来）→
        跳过「宝牌运：确认要切宝牌吗」这一问（罚点只针对玩家自己切宝牌）。"""
        if self.win_pending and int((self.win_pending or {}).get("seat", -1)) == int(seat):
            self.win_pending = None    # 正常打牌 = 放弃技能给的那次和牌
        self.press_win.discard(seat)
        if self.c11_win is not None and int(self.c11_win) == int(seat):
            self.c11_win = None
        if self.haishin_gate is not None and int(self.haishin_gate) == int(seat):
            self.haishin_gate = None
        self.haishin_step[int(seat)] = 0
        # 破发窗口不在这里关：别家立直后要留给我决定（摸牌或破发时才清）                   # 打出牌了 → 不再是「交换后直接和牌」          # 打完牌了，「技能导致的自摸」窗口关闭
        if self.phase == "deal_skill" or self.deal_flow:
            # A0: phase 已经推进到 discard，说明配牌流程早走完了 -> 收掉残留，别再挡
            if str(self.phase) != "deal_skill":
                self.deal_flow = None
                try:
                    self.deal_wait.clear()
                except Exception:
                    pass
                try:
                    self.deal_deadline = 0.0
                except Exception:
                    pass
                self.save_flags()
            else:
                raise RuleError("配牌技能还没结算完，不能切牌")
        if self.phase != "discard" or seat != self.turn:
            raise RuleError("还没轮到你打牌")
        if self.armed_skill and int(self.armed_skill.get("seat", -1)) == seat:
            self.armed_skill = None                      # 不发动技能，正常打牌
            self._skill_cache = None
        if int(self.youyin_meld_armed) == int(seat):
            # 友引段1：在加杠/暗杠窗口点了技能，最后选择正常打牌 → 开启状态作废
            self.youyin_meld_armed = -1
        drawn = self.drawn_tile(seat)
        # Card37 S1【岭上开花】：没点自摸直接打牌 → 这次作废（不翻倍）
        if int(self.c37s1_ready) == int(seat):
            self.c37s1_ready = -1
            self.save_flags()
        # Card40 S1【透视】：打出一张牌 → 这次看到的手牌复位
        self.c40s1_clear(int(seat))
        # Card36 S1【思路】：打出一张牌 → 看到的手牌全部复位
        self.c36s1_clear(int(seat))
        # Card35 S1【流势】：没排就直接打牌 = 放弃这次调整（牌山保持原样）
        self.c35_skip(int(seat))
        # Card34 S2【海底】：落牌之前检查（切牌前；鸣牌后的打牌也算 —— 那时没有 drawn）
        self.c34s2_try(int(seat))
        # 立直之后只能摸切（打刚摸到的那张）
        if tile is not None and not riichi and self.is_riichi(seat) and drawn is not None and tile != drawn:
            raise RuleError("立直之后只能打刚摸的那张")
        # Card34 S1【厄运】：静默期只能摸切
        if self.c34_muted(seat) and drawn is not None \
                and tile is not None and tile != drawn:
            raise RuleError("【厄运】期间只能摸切（打刚摸到的那张）")
        # 换牌技能用过后：不能再手切，只能摸切
        if seat in self.must_tsumogiri and drawn is not None \
                and tile is not None and tile != drawn:
            raise RuleError("换牌之后只能摸切（打刚摸到的那张）")
        # 命中（27S2）：发动之后也不能再手切
        if int(seat) in self.c27_s2 and drawn is not None \
                and tile is not None and tile != drawn:
            raise RuleError("命中发动后只能摸切（打刚摸到的那张）")
        # 四喜：就绪了却没和（被无效 / 自己点了别的）→ 技能作废
        if self._c10s2_ready(seat):
            self._c10s2_clear(seat)
            self._event("c10s2_wasted", {"seat": int(seat)})
        # 四喜：发动期间不能打出手牌里的东/北
        if int(seat) in self.c10s2:
            if tile in ("dong", "bei"):
                raise RuleError("「四喜」期间不能打出手里的东或北")
            drawn_now = self.drawn_tile(seat)
            if drawn_now in ("dong", "bei") and tile is None:
                raise RuleError("「四喜」期间不能打出手里的东或北")
        # 决斗：非决斗家只能摸切，而且暗置打出（谁都不能鸣、不会出铳）
        duel_down = False
        if self.duel_restricted(seat):
            if tile is not None and drawn is not None and tile != drawn:
                raise RuleError("决斗中：你只能摸切（打刚摸到的那张）")
            duel_down = True
        wall_seq = None
        if tile is not None:
            if riichi:
                if tile not in self.riichi_discards(seat):
                    raise RuleError("这张打出去就不听牌了，不能立直")
            elif self.pending_kuikae and not calls.can_discard_after_call(
                    tile, self.pending_kuikae["kind"], self.pending_kuikae["called"],
                    self.pending_kuikae["used"]):
                raise RuleError("食い替え：这张不能打")
            row = self.db._row("SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? "
                               "AND tile=? ORDER BY wall_seq LIMIT 1",
                               (self.round_id, seat, tile))
            if row is None:
                raise RuleError("你手里没有这张牌")
            wall_seq = row["wall_seq"]
            if drawn is not None and tile == drawn and not riichi:
                wall_seq = None                              # 打刚摸的那张 = 摸切
        # 宝牌运（25S1）：开启状态下切宝牌要先确认；确认了才罚点（本局不能胡）。
        c25_hit = False
        if tile is not None and int(seat) in self.c25_on and self._is_dora(tile) \
                and not forced and not self.c34_muted(int(seat)):
            if not c25_ok:
                raise RuleError("宝牌运：这是宝牌，确认要切出宝牌吗？")
            c25_hit = True
            self.no_win.add(int(seat))                  # 本局无法胡牌
            with self.db.tx():
                self.db._score(self.round_id, int(seat), -9000, "宝牌运")
                for s2 in range(4):
                    if int(s2) != int(seat):
                        self.db._score(self.round_id, int(s2), 3000, "宝牌运")
            self.c25_on.discard(int(seat))               # 罚过一次就关掉
            self.save_flags()
        # Card33 S2【记忆】：发动后的**下一张**打出的牌暗置（一次性）
        if int(self.c33s2_armed) == int(seat):
            self.c33s2_armed = -1
            face_down = True
            self.save_flags()
        first_discard = not self._has_discarded(seat)
        out = self.db.discard(self.round_id, seat, wall_seq=wall_seq,
                              riichi_tile=riichi, face_down=(duel_down or face_down))
        # Card34 S1【厄运】：立直家摸到自摸牌也只能打出去 → 立刻振听
        if (self.c34_muted(seat) and self.is_riichi(seat) and drawn is not None
                and str(out.get("tile", "")) == str(drawn)
                and self._judge_win(int(seat), str(drawn), tsumo=True) is not None):
            self.riichi_furiten.add(int(seat))
            self.save_flags()
        # Card36 S2【故意】：这一张打出去，谁的手牌能和就和谁结算（下家→对家→上家）
        _c36pay = self.c36s2_resolve(int(seat), str(out.get("tile", "")))
        if _c36pay is not None:
            return _c36pay
        # ★ 命中：他这一张是手切 → 计数；恰好到 3 就立刻结算「他对我出铳」
        _c27 = self._c27_after_discard(int(seat), bool(out.get("tsumogiri")))
        if _c27 is not None:
            return _c27
        if riichi:
            if self.duel and int(self.duel.get("by", -1)) == seat:
                self.duel = None                     # 我立直 → 决斗取消
                self.save_flags()
            else:
                self.duel_retarget(seat)             # 非决斗家立直 → 目标转移
            self.ippatsu.add(seat)
            if first_discard and self.all_closed():
                self.double_riichi.add(seat)                 # 双立直：第一巡就立直
            if skills.owns_card(self.db, self, int(seat), 30, strict=True):
                self.double_riichi.add(seat)                 # W立（30-2）：立直一律算双立直
            abort = self._check_abortive()                   # 可能是四家立直
            if abort:
                return abort
        self.pending_kuikae = None
        self.card05_offer.pop(seat, None)                    # 打牌了，换牌机会作废
        self.last_was_rinshan = False                        # 牌都打出去了，岭上开花的机会就没了
        self.phase = "discard"
        dseq = self.db._one("SELECT MAX(seq) FROM round_discards WHERE round_id=?",
                            (self.round_id,))
        self._after_discard_hooks(int(seat), str(out.get("tile", "")))
        # 先负：换完牌却没立直（正常切牌）→ 这次先负白用，清掉待结算
        if self.xianfu_armed is not None and int(self.xianfu_armed) == int(seat) \
                and not riichi:
            self.xianfu_armed = None
            self.save_flags()
        if duel_down or face_down:
            # 暗置牌不能吃碰、也不能荣；唯一例外是「压制」持有者（Card03 S2）。
            # 没人荣就和普通打牌一样轮到下家（resume_back=False 才不会回到自己）。
            if not self._open_facedown_claim(dseq, str(out["tile"]), seat,
                                             resume_back=False):
                self._advance_after_discard(seat)
        else:
            # 同盟（40S2）：我打出的牌 → 被指定的那家自动副露（荣和优先）
            _c40s2ev = self._c40s2_try(int(seat), dseq, str(out["tile"]))
            if _c40s2ev is not None:
                return _c40s2ev
            # ★ 加速（29S1）：先问「无视距离吃」的持有者；没人可问才开普通鸣牌窗口
            if not self._c29s1_gate(dseq, str(out["tile"]), int(seat)):
                self._open_claim_window(dseq, out["tile"], seat)
        return self._event("discard", {"seat": seat, "tile": out["tile"], "riichi": riichi,
                                       "face_down": bool(duel_down or face_down),
                                       "c25": c25_hit})

    def _do_riichi(self, seat: int, tile: str, face_down: bool = False) -> dict:
        # 先负：必须在「打牌 + 开鸣牌窗口」之前就把待结算记下来，
        # 否则 _open_claim_window 里的结算检查永远看不到它（先负就白用了）
        if (self.xianfu_armed is not None and int(self.xianfu_armed) == int(seat)
                and not self.c34_muted(int(seat))):
            # 多个人的一发巡：视为「最先立直的那家」对我出铳（按宣言牌 seq 排序）
            self.xianfu_pending = {"seat": int(seat),
                                   "declarer": self.first_riichi_seat(int(seat))}
            self.save_flags()
        ev = self._do_discard(seat, tile=tile, riichi=True, face_down=face_down)
        if self.phase == "ended" or self.result is not None:
            return ev                       # 这一张已经把这一局打完了（命中结算）
        # 破发（Card13 S1）：别人宣布立直 → 开一个窗口，等我下次摸牌就关
        self.pofa_window = {"declarer": int(seat)}
        # 破发：所有「持 13、没立直」的人，按座位顺序逐个问
        waiting = [t for t in range(4)
                   if t != int(seat) and not self.is_riichi(t) and self._has_card13(t)]
        self.pofa_ask = ({"declarer": int(seat), "waiting": waiting, "ts": time.time()}
                         if waiting else None)
        self.save_flags()
        return ev

    def _do_kyuushu(self, seat: int) -> dict:
        self.db._log(self.round_id, seat, "kyuushu", {})
        return self._ryuukyoku("kyuushu")

    # ── 自摸 ──
    def _win_pending_of(self, seat: int) -> int:
        """这个座位有没有「技能给的和牌」等着按自摸（43S1 / 46S1）。返回卡号，没有 → -1。"""
        p = self.win_pending
        if not p or int(p.get("seat", -1)) != int(seat):
            return -1
        return int(p.get("card", -1))

    def _pending_tsumo(self, seat: int) -> dict:
        """玩家点了技能给的自摸按钮 —— 这才真正结算。

        43S1 NO MISS：换完的和牌形，按自摸判番（不计边坎吊 2 符）；
        46S1 恶听   ：走「一定和牌」（铳张在别人手里就他出铳，否则按自摸）。
        """
        pend = dict(self.win_pending or {})
        self.win_pending = None
        self.save_flags()
        s = int(seat)
        card = int(pend.get("card", 0))
        tile = str(pend.get("tile", "") or "")
        if card == 46:
            return self._yiding_settle(s, want_tile=tile)
        self.c43s1_win.add(s)
        try:
            res = self._judge_win(s, tile or (self.drawn_tile(s) or ""),
                                  tsumo=True, as_tsumo=True)
        finally:
            self.c43s1_win.discard(s)
        if res is None:
            res = self._yiding_fallback(s, True)
        self._finish(s, None, "tsumo", res)
        return self._event("tsumo", {"seat": s, "card": 43, "skill": 1,
                                     "yaku": res["yaku"], "han": res["han"],
                                     "fu": res["fu"], "points": res["pays"]})


    def _do_tsumo(self, seat: int) -> dict:
        if self._win_pending_of(seat) > 0:
            return self._pending_tsumo(int(seat))
        # 兜底：浓雾 / 恶灵 / 看破代价 / 海神 gate 一律不许自摸
        # （正常路径由 legal_actions 过滤，这里防「别的入口直接调」）
        if not self._tsumo_gate_ok(seat):
            raise RuleError("现在不能自摸（有技能拦着：浓雾 / 恶灵 / 海神 …）")
        c24_kind = ""
        res = None
        if self.c24_win_can(seat):
            # 一发：把「牌山/王牌里的胡张」当成刚摸到的那张来结算（挑打点最高的）
            got = self._c24_best_win(seat)
            if got is not None:
                c24_kind, res = got
        if res is None:
            res = self._judge_win(seat, self.drawn_tile(seat) or "", tsumo=True,
                                  as_tsumo=(self.c11_win == int(seat)))
        if not res:
            raise RuleError("这不是和牌")
        self.c24_armed = -1
        if int(self.c37s1_ready) == int(seat):
            res["c37s1"] = True                   # 得点 ×2（只在真点了自摸时生效）
            self.c37s1_ready = -1
            self.save_flags()
        self._finish(seat, None, "tsumo", res)
        return self._event("tsumo", {"seat": seat, "yaku": res["yaku"], "han": res["han"],
                                     "fu": res["fu"], "points": res["pays"],
                                     "c24": c24_kind})

    # ── 一次性技能 / 画板（Card02 Skill1）────────────────────────────
    def _cc_key(self, seat: int, card: int, skill: int) -> str:
        return f"{int(card)}-{int(skill)}-{int(seat)}"

    def copy_granted(self, seat: int, card: int, skill: int) -> bool:
        """这个座位有没有「复制 / 传承」来的这一张技能。"""
        return self._cc_key(seat, card, skill) in self.cc_grants

    def copy_used(self, seat: int, card: int, skill: int) -> bool:
        """复制品那一份配额用掉了没有（和原技能的 used_skills 分开记）。"""
        return self._cc_key(seat, card, skill) in self.used_copy

    def orig_used(self, seat: int, card: int, skill: int) -> bool:
        """原技能那一份配额用掉了没有。"""
        return self._cc_key(seat, card, skill) in self.used_skills

    def skill_used(self, seat: int, card: int, skill: int) -> bool:
        """这份技能还有没有额度：原技能一次 + 复制品一次，两本账各记各的。

        · 本次请求点的是复制品图标（req_copy_key 命中）→ 只看复制品那本
        · 其余情况 → 原技能用过 **且** 复制品那一次也用过，才算用尽
          （只有复制品、没有原卡时也成立：原技能那本永远空着，
            复制品用掉后这里才会变 True）
        """
        key = self._cc_key(seat, card, skill)
        if self.req_copy_key and self.req_copy_key == f"{int(card)}-{int(skill)}":
            return key in self.used_copy
        if key not in self.used_skills:
            return False
        if key in self.cc_grants and key not in self.used_copy:
            return False                      # 复制品那一份还留着
        return True


    def _char_states(self, viewer: int = -1) -> list[dict]:
        """主战 / 协战 的遮罩状态。open = 发动过技能（之后一直开着），
        expired = 过了「这一风场 + 下一风场」→ 永久遮住。

        viewer 开了【云外镜】(26S1) → 他看到的**其他三家**全部揭开
        （已经过期的卡照样不揭：那种卡根本不在场上显示）。
        """
        sight = (viewer is not None and int(viewer) in range(4)
                 and self.skill_used(int(viewer), 26, 1))
        used = skills._char_use(self.db)
        ri = skills._round_index(self.round_wind, self.round["number"])
        rno = skills._round_no(self.round_wind, self.round["number"])
        out = []
        for s in range(4):
            order = skills.order_of(self.db, s)
            if len(order) < 5:
                out.append({"seat": s, "main": {}, "support": {}})
                continue

            def info(card: int) -> dict:
                k = used.get(f"{int(s)}:{int(card)}")
                expired = (k is not None and rno > int(k) + 1)
                is_open = (k is not None)
                if sight and int(s) != int(viewer) and not expired:
                    is_open = True           # 云外镜：别人的卡我看得见
                return {"card": int(card), "open": is_open, "expired": expired}
            out.append({"seat": s, "main": info(order[ri]),
                        "support": info(order[4])})
        return out

    def kangpo_gate(self, seat: int, card: int, skill: int,
                    op: str = "", payload: dict | None = None) -> bool:
        """【兼容壳】老的「发动前问看破」→ 现在只是往拦截树里挂一个节点。

        返回 True = 已经挂起（有人要答），调用方先别执行。
        """
        aid = self.act_spawn(int(seat), int(card), int(skill),
                             op=str(op or ""), payload=payload or {})
        node = self.act_node(aid)
        return node.get("state") == "asking"

    def _kangpo_my_ask(self, seat: int) -> dict:
        mine = self.act_ask_view(int(seat))
        if not mine:
            raise RuleError("现在没有要你看破的技能")
        return mine[0]

    def _kangpo_void(self, pend: dict) -> dict:
        """把「被拦住的那次发动」作废掉（看破 / 封堵 共用）。"""
        tgt = int(pend.get("seat", -1))
        self.poked.add(f"{tgt}:{int(pend.get('card', 0))}")
        self.poked.add(f"{tgt}:{int(pend.get('card', 0))}:{int(pend.get('skill', 0))}")
        if tgt >= 0:
            self.no_win.add(tgt)
            # 被废的是配牌技能 → 一个能用的都不剩了才关窗口
            if (self.phase == "deal_skill" and tgt in self.deal_wait
                    and not self._deal_skill_options(tgt)):
                self.deal_wait.discard(tgt)
                self.deal_used.add(tgt)
                self._maybe_close_deal()
            # 窗口型技能被废 → 把窗口关掉（否则这个 phase 谁都动不了）
            _pop = str(pend.get("op", "") or "")
            if _pop == "wind_swap":
                self.wind_swap = None
                self.phase = "discard"
            elif _pop in ("haishin_start", "card05_hide"):
                pass
            elif _pop == "c29s1_chi":
                self._c29s1_continue()
            elif _pop == "c35s1_set":
                self.c35_skip()               # 流势被看破 → 这次不排了
        self.save_flags()
        return {"used": True, "target": tgt,
                "card": int(pend.get("card", 0)), "skill": int(pend.get("skill", 0))}

    def kangpo_answer(self, seat: int, use: bool, kind: str = "") -> dict:
        """【兼容壳】老的「回答看破」→ 直接答拦截树里我的第一条询问。"""
        s = int(seat)
        mine = self._kangpo_my_ask(s)
        kinds = list(mine.get("kinds") or [])
        k = "pass" if not use else str(kind or "")
        if k != "pass" and k not in kinds:
            if str(kind or ""):
                # 用不了的招：按「放行」收尾（别把询问留在那儿卡住桌子），然后报错
                self.act_answer(s, int(mine.get("id", -1)), "pass")
                raise RuleError("这一招在这次询问里用不了")
            k = ("sight" if "sight" in kinds
                 else ("block" if "block" in kinds else ("stop" if "stop" in kinds else "imm")))
        aid0 = int(mine.get("id", -1))
        r = self.act_answer(s, aid0, k)
        r["used"] = (k != "pass")
        r["kind"] = k
        if k != "pass":
            for m in self.acts.values():           # 我这次拦截对应的子节点：把代价带回去
                if (int(m.get("parent", -1)) == aid0
                        and int(m.get("actor", -1)) == s):
                    if "price" in m:
                        r["price"] = int(m["price"])
                    if "left" in m:
                        r["left"] = int(m["left"])
                    break
        return r

    C31_BLOCK_BASE = 2000             # 封堵价格：2000 起，每次翻倍

    def _c31_meta_key(self) -> str:
        mid = self.db._one("SELECT match_id FROM rounds WHERE round_id=?",
                           (self.round_id,))
        return "c31_block_%s" % mid

    def c31_block_used(self, seat: int) -> int:
        """这一家在**这个半庄**里已经封堵过几次。"""
        row = self.db._row("SELECT value FROM meta WHERE key=?", (self._c31_meta_key(),))
        if not row:
            return 0
        try:
            data = json.loads(row["value"]) or {}
        except Exception:
            return 0
        return int(data.get(str(int(seat)), 0) or 0)

    def _turn_token(self) -> str:
        """当前这一手的标记：谁在打 + 他打过几张。换人/换巡就变。"""
        tn = self.turn
        if tn is None:
            return "-"
        try:
            return "%d-%d" % (int(tn), int(self.turn_count(int(tn))))
        except Exception:
            return "%d-?" % int(tn)

    def c31s2_stopped_now(self, seat: int, card: int, skill: int) -> bool:
        """A7：这个「座位+技能」在本回合是不是已经被【阻止】过。"""
        key = "%d:%d:%d" % (int(seat), int(card), int(skill))
        got = self.c31s2_stopped.get(key)
        return got is not None and got == self._turn_token()

    def c31_block_price(self, seat: int) -> int:
        return int(self.C31_BLOCK_BASE) * (2 ** max(0, self.c31_block_used(int(seat))))

    def _c31_block_pay(self, seat: int, price: int) -> None:
        """扣分 + 钱进场供（1000 点 = 1 根）；次数记在 meta（整个半庄）"""
        key = self._c31_meta_key()
        row = self.db._row("SELECT value FROM meta WHERE key=?", (key,))
        try:
            data = json.loads(row["value"]) if row else {}
        except Exception:
            data = {}
        data = dict(data or {})
        data[str(int(seat))] = int(data.get(str(int(seat)), 0) or 0) + 1
        with self.db.tx():
            self.db.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)",
                (key, json.dumps(data, ensure_ascii=False)))
            self.db._score(self.round_id, int(seat), -int(price), "封堵")
            self.db.conn.execute(
                "UPDATE rounds SET riichi_sticks = IFNULL(riichi_sticks, 0) + ? "
                "WHERE round_id=?", (int(price) // 1000, self.round_id))
        self.save_flags()

    def kangpo_kinds(self, seat: int, target: int, card: int, skill: int,
                     pre: bool = True) -> list[str]:
        """这一家现在能用哪些拦截：sight(看破) / block(封堵) / stop(阻止)"""
        out: list[str] = []
        s = int(seat)
        has31 = skills.owns_card(self.db, self, s, 31, strict=True)
        if (skills.owns_card(self.db, self, s, 17, strict=True)
                and not self.skill_used(s, 17, 2)):
            out.append("sight")
        if has31:
            out.append("block")
            used = self.c31s2_used.get(s) or set()
            tmg = str(skills.timing(int(card), int(skill)))
            # 阻止必须发生在**执行前**（事后闸门没得拦），所以 pre=False 时不给 stop
            if pre and int(target) not in used and tmg in ("draw", "discard"):
                out.append("stop")     # 只挡「自己摸牌/切牌时点按钮」的主动技能
        # Card43 S2【免疫】：并进同一个面板（只在执行前、而且我是这次的目标）
        ctx = self.c43_imm_ctx or {}
        if (pre and ctx and int(ctx.get("card", 0)) == int(card)
                and int(ctx.get("skill", 0)) == int(skill)
                and s in [int(x) for x in (ctx.get("askers") or [])]
                and self.c43s2_left(s) > 0
                and not self.c43s2_immune(s, int(card), int(skill))):
            out.append("imm")
        return out

    def _kangpo_askers(self, exclude_seat: int) -> list[int]:
        """现在能回答看破的人，**按格位排（主战在前、协战在后）**。

        格位来自数据（skills.card_slot），不是一个 if/else 比较器；
        没有大厅卡序时所有人格位都是 0 → 等于原来的「按座位顺序」。
        """
        out: list[int] = []
        for s in range(4):
            if int(s) == int(exclude_seat):
                continue
            if self.c34_muted(int(s)):
                continue                     # 【厄运】：三巡内不能看破/封堵/阻止
            if self.human_seats is not None and int(s) not in self.human_seats:
                continue                     # 没人在操作（AI）：不问
            if int(s) in self.no_win:
                continue
            _h17 = (skills.owns_card(self.db, self, int(s), 17, strict=True)
                    and not self.skill_used(int(s), 17, 2))
            _h31 = skills.owns_card(self.db, self, int(s), 31, strict=True)
            if not (_h17 or _h31):
                continue
            out.append(int(s))
        out.sort(key=lambda s: (self._card_slot(s, 17), self._card_slot(s, 31)))
        return out

    def _maybe_ask_kangpo(self, seat: int, card: int, skill: int) -> None:
        """别人发动技能 → 给持有看破的人留一个待询问"""
        # 看破自己不能被看破（回答时 mark_skill_used(17,2) 会走到这里，
        # 以前会给自己挂一笔 ask 但没 pending → 之后所有人「有人正在决定是否看破」）
        if (int(card), int(skill)) == (17, 2):
            return
        # 已经有一笔在等回答 → 绝不覆盖（否则看破窗口会被后来的技能顶掉）
        if self.kangpo_ask is not None or self.kangpo_pending is not None:
            return
        key = "%d:%d:%d" % (int(seat), int(card), int(skill))
        if key in self.act_gated:
            return                          # 已经过拦截树的闸门问过了，别再补问一遍
        if (int(card), int(skill)) in ONCE_PAIRS and key in self.kangpo_once:
            return                          # 配牌技能：配牌时问过 → 之后不再问
        if key in self.kangpo_pass:        # 闸门已经问过并放行了，别重复问
            self.kangpo_pass.discard(key)
            self.save_flags()
            return
        # 拦截树：已经生效的技能也能被拦（事后记代价：poked / no_win），
        # 走同一棵树，避免两套询问系统打架
        self.act_spawn(int(seat), int(card), int(skill), op="", payload={},
                       kind="skill", post=True)

    def note_use(self, seat: int, card: int, skill: int, once: bool = True,
                 gate: bool = True) -> None:
        """一个技能**真的发动了**：统一在这里记所有账。

        once=False：这个技能可以多次发动（钓鱼 / 友引段1），只播报 + 翻卡面，
                    不记 used_skills（记了客户端图标会永久置灰）。
        gate=False：**不再问看破**（op 层的闸门已经问过；这里再问会挂第二笔 → 死锁，
                    友引摊面子就是踩的这个坑）。

        · used_skills      —— 一次性技能（客户端图标置灰）
        · char_use         —— 这张卡翻明（A 案：按卡算，遮罩只认它）
        · skill_log        —— 传承（Card16）能复制的清单
        · broadcast        —— 全场播报
        · kangpo gate      —— 看破前置询问
        """
        s, c, k = int(seat), int(card), int(skill)
        if once:
            key = f"{c}-{k}-{s}"
            if self.req_copy_key and self.req_copy_key == f"{c}-{k}":
                self.used_copy.add(key)          # 点的就是复制品 → 记复制品那本
            elif key not in self.used_skills:
                self.used_skills.add(key)        # 原技能还留着 → 记原技能那本
            elif key in self.cc_grants and key not in self.used_copy:
                self.used_copy.add(key)          # 原技能已用 → 花复制品那一份
            else:
                self.used_skills.add(key)
        # 传承：发动的是「复制来的技能」→ 起作用的是 16 号卡，卡面翻 16
        cp = self.cc_copy.get(s) or {}
        face = 16 if (int(cp.get("card", 0)) == c and int(cp.get("skill", 0)) == k) else c
        skills.set_char_use(self.db, s, face,
                            skills._round_no(self.round_wind, self.round["number"]))
        self._skill_log_add(s, c, k)
        self.duel_retarget(s)                    # 非决斗家用技能 → 决斗转移
        if gate:
            self._maybe_ask_kangpo(s, c, k)
        if s not in self._revealed_cache:        # 座位级「翻明」记录（仅供播报/头像）
            self._revealed_cache.add(s)
            with self.db.tx():
                self.db.conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES('revealed_seats', ?)",
                    (json.dumps(sorted(self._revealed_cache)),))
        name = skills.info(c, k).get("name", "")
        if int(cp.get("card", 0)) == c and int(cp.get("skill", 0)) == k:
            name = "传承·" + name
        self.broadcast_id += 1
        wind = ["dong", "nan", "xi", "bei"][(s - self.dealer) % 4]
        self.broadcast = {"id": self.broadcast_id, "seat": s,
                          "wind": wind, "card": c, "skill": k, "name": name}
        self.save_flags()

    def _note_pay_broadcast(self, seat: int, card: int, skill: int, text: str) -> None:
        """结算时「改了支付」的技能（弃子 → 0 / 电报 → 30 符 1 番）→ 播报面板补一句。

        只多发一条 broadcast：used_skills / 卡面翻明 / 看破 都在**发动那一刻**
        由 note_use 记过了，这里再记一遍会把图标重复置灰。
        """
        self.broadcast_id += 1
        wind = ["dong", "nan", "xi", "bei"][(int(seat) - int(self.dealer)) % 4]
        self.broadcast = {"id": self.broadcast_id, "seat": int(seat), "wind": wind,
                          "card": int(card), "skill": int(skill),
                          "name": skills.info(int(card), int(skill)).get("name", ""),
                          "text": str(text)}
        self.save_flags()

    def mark_skill_used(self, seat: int, card: int, skill: int) -> None:
        """历史接口：以前只记「一次性技能 + 卡面」，现在统一走 note_use。"""
        self.note_use(seat, card, skill)

    def board_view(self, seat: int) -> dict:
        b = self.boards.get(seat) or {}
        return {
            "tiles": list(b.get("tiles") or []),
            "delivered": list(b.get("delivered") or []),
            "pending": [str(p.get("tile")) for p in (b.get("pending") or [])],
        }

    def choose_board(self, seat: int, tiles: list[str]) -> dict:
        """画板：把所有手牌列出来，指定三种牌种。"""
        if self.phase != "discard" or seat != self.turn:
            raise RuleError("现在不是你的出牌回合")
        if self.drawn_tile(seat) is None:
            raise RuleError("摸牌之后才能发动")
        if self.skill_used(seat, 2, 1):
            raise RuleError("这个技能本局已经用过了")
        picks = [str(t) for t in tiles]
        if len(picks) != 3 or len(set(picks)) != 3:
            raise RuleError("要指定三种不同的牌")
        for tile in picks:
            if tile not in TILE_KINDS:
                raise RuleError(f"没有这种牌：{tile}")
        self.boards[seat] = {"tiles": picks, "delivered": [], "pending": []}
        self.mark_skill_used(seat, 2, 1)
        self.note_skill(seat, 2, 1)
        self.save_flags()
        return {"tiles": picks}

    def swap_river(self, seat: int, hand_tiles: list[str],
                   river_seqs: list[int]) -> dict:
        """Card02 Skill2：三张手牌暗置换进牌河，对应的三张牌河牌进手牌。

        · 只能在第十三巡前（自己摸牌次数 <= 12）、摸牌后、本小局一次
        · 换进来的牌河牌不算「打出去的牌」→ 不发生额外振听（见 discards_for_furiten）
        """
        if self.phase != "discard" or seat != self.turn:
            raise RuleError("现在不是你的出牌回合")
        if self.drawn_tile(seat) is None:
            raise RuleError("摸牌之后才能发动")
        self._assert_hand_mutable(seat)                  # 立直后不能换牌
        picks = [str(t) for t in hand_tiles]
        seqs = [int(s) for s in river_seqs]
        if self.skill_used(seat, 2, 2):
            # 同一个请求重发（客户端没收到回应会重试）→ 直接告诉他上次的结果
            last = (self.swaps or {}).get(seat) or {}
            if last.get("hand") == picks and last.get("river") == seqs:
                return {"hand": picks, "river": seqs, "got": list(last.get("got") or [])}
            raise RuleError("这个技能本局已经用过了")
        if self.turn_count(seat) > 11:            # 已经打完 12 巡 = 这是第 13 巡
            raise RuleError("第十三巡之后不能发动")
        if not (1 <= len(picks) <= 3):
            raise RuleError("手牌要选 1~3 张")
        if len(seqs) != len(picks):
            raise RuleError("牌河要选手牌同样张数")
        if len(set(seqs)) != len(seqs):
            raise RuleError("牌河的牌不能重复")

        # 手牌：同一种牌可以选多张，按张数扣
        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, seat))
        pool: dict[str, list[int]] = {}
        for r in rows:
            pool.setdefault(str(r["tile"]), []).append(int(r["wall_seq"]))
        hand_rows: list[tuple[str, int]] = []
        for tile in picks:
            if not pool.get(tile):
                raise RuleError(f"手里没有 {tile}")
            hand_rows.append((tile, pool[tile].pop(0)))

        # 牌河
        river: dict[int, dict] = {}
        for r in self.db._rows(
                "SELECT seq, seat, wall_seq, tile, called, is_riichi_tile, face_down "
                "FROM round_discards WHERE round_id=? ORDER BY seq", (self.round_id,)):
            river[int(r["seq"])] = r
        river_rows = []
        for s in seqs:
            row = river.get(s)
            if row is None:
                raise RuleError("这张牌不在牌河里")
            if int(row["called"] or 0):
                raise RuleError("已经被吃碰杠拿走的牌不能换")
            if int(row["is_riichi_tile"] or 0):
                raise RuleError("立直宣言牌不能换")
            if int(row["face_down"] or 0):
                raise RuleError("暗牌不能再换")
            river_rows.append(row)

        with self.db.tx():
            for (tile, hseq), row in zip(hand_rows, river_rows):
                # 手牌 → 暗置进牌河（占用被换走那张的位置）
                self.db.conn.execute(
                    "DELETE FROM round_hands WHERE round_id=? AND wall_seq=?",
                    (self.round_id, hseq))
                self.db.conn.execute(
                    "UPDATE round_discards SET wall_seq=?, tile=?, face_down=1, is_tsumogiri=0 "
                    "WHERE round_id=? AND seq=?",
                    (hseq, tile, self.round_id, int(row["seq"])))
                # 牌河那张 → 进我的手牌（不是摸进来的）
                slot = self.db._one(
                    "SELECT COALESCE(MAX(slot), -1) + 1 FROM round_hands "
                    "WHERE round_id=? AND seat=?", (self.round_id, seat)) or 0
                self.db.conn.execute(
                    "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
                    "VALUES(?,?,?,?,?,0)",
                    (self.round_id, seat, int(row["wall_seq"]), str(row["tile"]), int(slot)))
            # 换进来的牌里最后一张算「刚摸到的」：换牌之后只能摸切（must_tsumogiri）
            last = self.db._row(
                "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? "
                "ORDER BY slot DESC LIMIT 1", (self.round_id, seat))
            if last is not None:
                self.db.conn.execute(
                    "UPDATE round_hands SET is_drawn=1 WHERE round_id=? AND wall_seq=?",
                    (self.round_id, int(last["wall_seq"])))
        self.must_tsumogiri.add(int(seat))
        self.note_use(seat, 2, 2)          # 只记一笔（原来 mark + note 会播报两次）
        self.swaps = self.swaps or {}
        self.swaps[seat] = {"hand": picks, "river": seqs,
                            "got": [str(r["tile"]) for r in river_rows]}
        self.save_flags()
        # 暗置牌进河：持有 Card03「压制」的人可以荣和（一次只开一个窗口）
        claim = False
        for row, (tile, _hseq) in zip(river_rows, hand_rows):
            if self._open_facedown_claim(int(row["seq"]), tile, seat):
                claim = True
                break
        return {"hand": picks, "river": seqs,
                "got": [str(r["tile"]) for r in river_rows], "claim": claim}

    def _board_take(self, seat: int) -> dict | None:
        """轮到我摸牌：卡下压着的明牌优先拿，不再从牌山摸。"""
        b = self.boards.get(seat)
        if not b or not b.get("pending"):
            return None
        item = b["pending"].pop(0)
        tile, seq = str(item.get("tile")), int(item.get("seq", 0))
        with self.db.tx():
            self.db.conn.execute(
                "UPDATE round_hands SET is_drawn=0 WHERE round_id=? AND seat=?",
                (self.round_id, seat))
            slot = (self.db._one("SELECT COALESCE(MAX(slot), -1) + 1 FROM round_hands "
                                 "WHERE round_id=? AND seat=?", (self.round_id, seat)) or 0)
            self.db.conn.execute(
                "INSERT OR REPLACE INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
                "VALUES(?,?,?,?,?,1)", (self.round_id, seat, seq, tile, slot))
        self.save_flags()
        return {"tile": tile, "seq": seq}

    # ── 摸到的牌被谁抢：统一按「下家 → 对家 → 上家」的座位顺序 ─────────
    #   深山 / 海神 / 宝牌的集合 / 画板 都走这一套判定（别各自抢）。
    #   同一家同时满足多个时，按 _INTERCEPT_ORDER 里的先后取一个。
    _INTERCEPT_ORDER = ("board", "shenshan", "haishin", "c25s2")

    # 卡号 → 「拿走摸到的牌」的技能（遍历卡序时用它把卡翻成技能）
    _INTERCEPT_BY_CARD = {2: "board", 19: "shenshan", 12: "haishin", 25: "c25s2"}

    def _intercept_kind_ok(self, s: int, drawer: int, tile: str, kind: str) -> bool:
        """这一家的「这一个技能」现在还能拿走这张牌吗？"""
        s, drawer, tile = int(s), int(drawer), str(tile)
        if s == drawer:
            return False
        if self.hand_locked(drawer) or self.hand_locked(s):
            return False                 # 立直家摸到的牌不能被抢；立直家也不收牌
        if kind == "board":
            b = self.boards.get(s) or {}
            return (tile in (b.get("tiles") or [])
                    and tile not in (b.get("delivered") or []))
        if kind == "shenshan":
            return s in self.shenshan
        if kind == "haishin":
            return bool(self.haishin_on and self.owns_card12(s)
                        and self._is_man_or_zhong(tile))
        if kind == "c25s2":
            return bool(s in self.c25s2_on and self._is_dora(tile)
                        and self._non_dora_count(s) > 0)
        return False

    def _card_slot(self, seat: int, card: int) -> int:
        """0 = 主战 / 1 = 协战 / 2 = 其它（格位就是顺序）。"""
        if not hasattr(self, "_role_cache"):
            self._role_cache = {}
        key = (int(seat), int(card))
        if key not in self._role_cache:
            self._role_cache[key] = skills.card_slot(
                self.db, self, int(seat), int(card))
        return int(self._role_cache[key])

    def _seat_cards(self, seat: int) -> list[int]:
        """这家本局的卡，**按结算顺序**（主战 → 协战 → 传承）。"""
        return skills.cards_in_order(self.db, self, int(seat))

    def _intercept_kinds(self, s: int, drawer: int, tile: str) -> list[str]:
        """这一家能拿走这张牌的所有技能 —— **遍历卡序就得到「主战先、协战后」**。"""
        out: list[str] = []
        for card in self._seat_cards(s):
            kind = self._INTERCEPT_BY_CARD.get(int(card))
            if kind and kind not in out and self._intercept_kind_ok(s, drawer, tile, kind):
                out.append(kind)
        return out

    def _intercept_kind(self, s: int, drawer: int, tile: str) -> str:
        """兼容：这一家第一个能拿走这张牌的技能种类（"" = 不能）。"""
        ks = self._intercept_kinds(s, drawer, tile)
        return ks[0] if ks else ""

    def _intercept_plan(self, drawer: int, tile: str) -> list[list]:
        """谁能抢这张牌：下家 → 对家 → 上家；同一家里主战卡先于协战卡。

        返回 [[座位, 技能种类], ...] —— 前面那个先问，被跳过就往下问。
        """
        plan: list[list] = []
        for k in (1, 2, 3):
            s = (int(drawer) + k) % 4
            if self.c34_muted(s):
                continue                     # 【厄运】：深山 / 海神 / 宝牌集合 都不生效
            for kind in self._intercept_kinds(s, drawer, tile):
                plan.append([int(s), str(kind)])
        return plan

    def _tile_interceptor(self, drawer: int, tile: str) -> tuple[int, str] | None:
        """谁先能拿就归谁（returns 第一个）。"""
        plan = self._intercept_plan(int(drawer), tile)
        if not plan:
            return None
        return int(plan[0][0]), str(plan[0][1])

    def _open_intercept(self, drawer: int, tile: str, plan: list) -> str:
        """把 plan 里的第一个挂成询问（画板不走这里）。返回技能种类。"""
        who, kind = int(plan[0][0]), str(plan[0][1])
        rest = [[int(a), str(b)] for a, b in plan[1:]]
        if kind == "shenshan":
            self.shenshan_offer = {"seat": who, "from": int(drawer),
                                   "tile": str(tile), "plan": rest}
            self.phase = "shenshan"
        elif kind == "haishin":
            self.haishin_offer = {"owner": who, "from": int(drawer),
                                  "tile": str(tile), "plan": rest}
            self.phase = "haishin"
        else:
            self.c25s2_offer = {"owner": who, "from": int(drawer),
                                "tile": str(tile), "plan": rest}
            self.phase = "c25s2"
        return kind

    def _advance_intercept(self, offer: dict) -> dict | None:
        """这笔询问被跳过了 → 按 plan 继续问下一个（同一家的协战卡、再往后的人）。

        返回 {"event":"intercept", ...} = 又挂出了一笔询问；None = 都问完了。
        """
        drawer = int(offer.get("from", -1))
        tile = str(offer.get("tile", ""))
        plan = [[int(a), str(b)] for a, b in (offer.get("plan") or [])]
        while plan:
            who, kind = int(plan[0][0]), str(plan[0][1])
            plan = plan[1:]
            if not self._intercept_kind_ok(who, drawer, tile, kind):
                continue                 # 期间状态变了（立直 / 手里没非宝牌了…）
            got = self._open_intercept(drawer, tile, [[who, kind]] + plan)
            self.save_flags()
            return {"event": "intercept", "skill": got, "seat": who, "tile": tile}
        self.phase = "discard"
        self.save_flags()
        return None

    def _board_transfer(self, seat: int, drawn: dict) -> dict | None:
        """兼容旧接口：按统一座位顺序找「谁要这张牌」，正好是画板就交给他。"""
        hit = self._tile_interceptor(int(seat), str(drawn.get("tile")))
        if hit is None or hit[1] != "board":
            return None
        return self._board_transfer_to(hit[0], int(seat), drawn)

    def _board_transfer_to(self, owner: int, drawer: int, drawn: dict) -> dict | None:
        """画板：把这张牌交给他（压在他卡下），摸牌的人重摸。

        ★ 只处理「_tile_interceptor 已经选出来的那一家」，座位顺序由它决定。
        """
        tile = str(drawn.get("tile"))
        seq = int(drawn.get("seq", 0))
        b = self.boards.get(int(owner)) or {}
        if tile not in (b.get("tiles") or []) or tile in (b.get("delivered") or []):
            return None
        with self.db.tx():
            self.db.conn.execute(
                "DELETE FROM round_hands WHERE round_id=? AND seat=? AND wall_seq=?",
                (self.round_id, int(drawer), seq))
            self.db.conn.execute(
                "UPDATE round_hands SET is_drawn=0 WHERE round_id=? AND seat=?",
                (self.round_id, int(drawer)))
        b.setdefault("delivered", []).append(tile)
        b.setdefault("pending", []).append({"tile": tile, "seq": seq})
        self.card05_interfere(int(drawer), int(owner), "画板")   # 策略：别人害我重摸
        self.save_flags()
        return {"owner": int(owner), "tile": tile}

    # ── 技能 ──
    def _skill_plan(self, seat: int):
        """挂着的技能现在还能不能用（返回方案或 None）。同一手牌只算一次。"""
        arm = self.armed_skill
        if not arm or int(arm.get("seat", -1)) != seat:
            return None
        if self.phase != "discard" or seat != self.turn:
            return None
        if not skills.has(int(arm.get("card", 0)), int(arm.get("skill", 0))):
            return None
        key = (seat, tuple(sorted(self.hand(seat))), len(self.melds(seat)))
        cached = self._skill_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        plan = skills.card01_s1_plan(self, seat) \
            if (int(arm.get("card", 0)), int(arm.get("skill", 0))) == (1, 1) else None
        self._skill_cache = (key, plan)
        return plan

    def arm_skill(self, seat: int, card: int, skill: int) -> dict:
        """客户端点了技能图标：检查条件，成立就把技能挂上（不立刻结算）。"""
        self.armed_skill = None
        self._skill_cache = None
        # 「自信」不是「摸牌后」技能：它在配牌阶段发动，整小局常驻
        if (int(card), int(skill)) == (3, 1):
            return self._arm_confidence(seat, int(card), int(skill))
        if self.phase != "discard" or seat != self.turn:
            return {"ok": True, "armed": False, "reason": "现在不是你的出牌回合"}
        if self.drawn_tile(seat) is None:
            return {"ok": True, "armed": False, "reason": "摸完牌之后才能发动"}
        if not skills.has(card, skill):
            return {"ok": True, "armed": False, "reason": "这张人物卡没有这个技能"}
        if not skills.owns_card(self.db, self, seat, card):
            return {"ok": True, "armed": False, "reason": "这张不是你这一局的人物卡"}
        if (int(card), int(skill)) != (1, 1):
            return {"ok": True, "armed": False, "reason": "这个技能还没实现"}
        plan = skills.card01_s1_plan(self, seat)
        if not plan:
            return {"ok": True, "armed": False,
                    "reason": "没有能留下五门齐 / 花龙 / 三色三步高的听牌"}
        self.armed_skill = {"seat": seat, "card": int(card), "skill": int(skill),
                            "discard": plan["discard"], "win": plan["win"]}
        self.note_skill(seat, card, skill)
        self.save_flags()
        return {"ok": True, "armed": True, "card": int(card), "skill": int(skill),
                "skill_name": skills.info(card, skill).get("name", ""),
                "discard": plan["discard"], "win": plan["win"],
                "patterns": plan["patterns"], "han_bonus": plan["han_bonus"],
                "total": plan["total"]}

    def _arm_confidence(self, seat: int, card: int, skill: int) -> dict:
        """Card03 Skill1「自信」：配牌阶段发动，整小局有效，不能取消。

        · 和牌 → 番数双倍（役满不算番，不受影响）
        · 没和牌 → 自己付的点数双倍（放铳 / 别人自摸都算）
        """
        name = skills.info(card, skill).get("name", "自信")
        if not skills.owns_card(self.db, self, seat, card):
            return {"ok": True, "armed": False, "reason": "这张不是你这一局的人物卡"}
        if seat in self.confident:
            return {"ok": True, "armed": False, "already": True,
                    "reason": "「%s」本局已经发动过了" % name}
        if (self.phase == "ended"
                or (self.round_phase != "deal" and self.phase != "deal_skill")):
            return {"ok": True, "armed": False,
                    "reason": "「%s」只能在配牌阶段发动" % name}
        self.confident.add(seat)
        self.note_skill(seat, card, skill)          # 全场播报 + 人物卡翻明
        self.save_flags()
        return {"ok": True, "armed": True, "card": int(card), "skill": int(skill),
                "skill_name": name, "kind": "confidence", "confident": True}

    def _do_skill_tsumo(self, seat: int) -> dict:
        """按下技能给的自摸按钮：替玩家打一张、发和牌那张、按技能规则结算。"""
        if self.nongwu_blocks(seat):
            raise RuleError("「浓雾」：4 巡内不能自摸")
        if self._oracle_lock(seat) and not agari.is_closed(self.melds(seat)):
            raise RuleError("「恶灵」：发动过降神，这一局只能门清自摸和")
        plans = skills.card01_s1_plans(self, seat)
        if not plans:
            raise RuleError("这一刻没有能凑成五门齐 / 花龙 / 三色三步高的听牌")
        arm = self.armed_skill or {}
        plan = next((p for p in plans
                     if p["discard"] == arm.get("discard") and p["win"] == arm.get("win")),
                    plans[0])                   # 发动时选的那张；找不到了就随便取一张最优的
        res = skills.execute_pattern_tsumo(self.db, self, seat, plan)
        self.armed_skill = None
        self._skill_cache = None
        self._finish(seat, None, "tsumo", res)
        return self._event("skill_tsumo",
                           {"seat": seat, "card": 1, "skill": 1,
                            "discard": plan["discard"], "win": plan["win"],
                            "patterns": plan["patterns"],
                            "yaku": res["yaku"], "han": res["han"],
                            "fu": res["fu"], "points": res["pays"]})

    # ── 配牌阶段技能窗口（Card03 Skill1 等）────────────────────
    def _deal_skill_options(self, seat: int) -> list[dict]:
        """这个座位在配牌阶段能发动的技能。

        ★ 遍历「这家自己的卡序」（主战 → 协战），所以窗口里自然就是主战在前。
        """
        out = []
        for card in self._seat_cards(int(seat)):
            for skill in (1, 2):
                if not skills.has(int(card), int(skill)):
                    continue
                if skills.timing(int(card), int(skill)) != "deal":
                    continue
                # 在配牌动画里（窗口出现之前）就点过技能的人，不再让他重复决定
                if (int(card), int(skill)) == (3, 1) and seat in self.confident:
                    continue
                # 南风：只有南场才有这个技能
                if (int(card), int(skill)) == (6, 1) and str(self.round_wind) != "nan":
                    continue
                # 降神：掷过骰子就不用再列了（之后靠点图标开关）
                if (int(card), int(skill)) == (7, 1) and seat in self.oracle:
                    continue
                # 宝牌的集合（25-2）不是玩家点的：宝牌运结算完自动挂出，别列进窗口
                if (int(card), int(skill)) == (25, 2):
                    continue
                # 看破剔除的是「这一个技能」：同一张卡的另一个技能/别的卡照常可用
                if f"{int(seat)}:{int(card)}:{int(skill)}" in self.poked:
                    continue
                key = (int(seat), int(card))
                if key not in self._owns_cache:
                    self._owns_cache[key] = skills.owns_card(
                        self.db, self, int(seat), int(card), strict=True)
                if not self._owns_cache[key]:
                    continue
                out.append({"card": int(card), "skill": int(skill),
                            "name": skills.info(card, skill).get("name", ""),
                            "timing": "deal"})
        return out

    def _open_deal_window(self) -> None:
        """庄家跳完牌：把「有配牌技能的人」列出来，等他们发动或跳过。"""
        self.deal_wait = set()
        for s in range(4):
            if self._deal_skill_options(s):
                self.deal_wait.add(s)
        if self.deal_wait:
            self.phase = "deal_skill"
            self.deal_deadline = 0.0        # 配牌不限时（见 deal_skill_timeout）
            self.save_flags()

    def deal_action(self, seat: int, action: str,
                    card: int = 0, skill: int = 0) -> dict:
        """配牌窗口里某一家做出选择：发动技能（use）或跳过（skip）。"""
        if self.phase != "deal_skill":
            raise RuleError("现在不是配牌技能阶段")
        if self.deal_flow and int(self.deal_flow.get("seat", -1)) == int(seat):
            return {"ok": True, "busy": True, "pending": sorted(self.deal_wait),
                    "flow": self.deal_flow_view(seat)}      # 风神还在换牌
        if seat not in self.deal_wait:
            return {"ok": True, "done": True, "pending": sorted(self.deal_wait)}
        if action == "skip":
            self.deal_wait.discard(seat)
            self.deal_used.add(seat)
            self.save_flags()
            self._maybe_close_deal()
            return {"ok": True, "skipped": True, "pending": sorted(self.deal_wait)}
        if action != "use":
            raise RuleError("不认识的配牌动作")
        opts = self._deal_skill_options(seat)
        if not any(int(o["card"]) == int(card) and int(o["skill"]) == int(skill)
                   for o in opts):
            raise RuleError("这个技能不是配牌阶段发动的")
        # 同一张卡可能有两个配牌技能（云外镜 + 天梯）：用过的那一个不能再发一次
        # （列表里留着它是为了「风神换牌过程中窗口里还能看到」）
        if self.skill_used(int(seat), int(card), int(skill)):
            return {"ok": True, "armed": False, "already": True,
                    "reason": "本小局已经发动过了", "pending": sorted(self.deal_wait)}
        if (int(card), int(skill)) == (28, 1):
            return self._arm_c28s1(seat, int(card), int(skill))
        if (int(card), int(skill)) == (26, 1):
            return self._arm_c26s1(seat, int(card), int(skill))
        if (int(card), int(skill)) == (26, 2):
            return self._arm_c26s2(seat, int(card), int(skill))
        if (int(card), int(skill)) == (25, 1):
            return self._start_dora_luck(seat, int(card), int(skill))
        if (int(card), int(skill)) == (4, 1):
            return self._start_deal_swap(seat, int(card), int(skill))
        if (int(card), int(skill)) == (6, 1):
            return self._start_south_wind(seat, int(card), int(skill))
        if (int(card), int(skill)) == (7, 1):
            return self._start_oracle(seat, int(card), int(skill))
        if (int(card), int(skill)) == (17, 1):
            return self._start_yanjiu(seat, int(card), int(skill))
        if (int(card), int(skill)) == (14, 1):
            return self._start_ignite(seat, int(card), int(skill))
        r = self.arm_skill(seat, int(card), int(skill))
        if not r.get("armed", False):
            r["pending"] = sorted(self.deal_wait)     # 没发动成功就还等他
            return r
        # 「按发动先后顺序结算」：每个技能都是即时生效的，这里按调用顺序记账
        self.deal_queue.append({"seat": seat, "card": int(card), "skill": int(skill)})
        self.deal_wait.discard(seat)
        self.deal_used.add(seat)
        self.save_flags()
        self._maybe_close_deal()
        return {**r, "pending": sorted(self.deal_wait)}

    # ── 策略（Card05 Skill1）────────────────────────────────────
    def owns_card05(self, seat: int) -> bool:
        if int(seat) not in self._c05_cache:
            self._c05_cache[int(seat)] = skills.owns_card(
                self.db, self, int(seat), 5, strict=True)
        return self._c05_cache[int(seat)]

    def owns_tenacity(self, seat: int) -> bool:
        """Card06 Skill2「坚韧」：**东场**才有（南场无该技能），被动不发动。"""
        if str(self.round_wind) != "dong":
            return False
        s = int(seat)
        if s not in self._tenac_cache:
            self._tenac_cache[s] = skills.owns_card(
                self.db, self, s, 6, strict=True)
        return self._tenac_cache[s]

    # ── 降神（Card07 Skill1）──────────────────────────────────
    ORACLE_SUITS = {2: "m", 5: "m", 8: "m", 11: "m",
                    3: "p", 6: "p", 9: "p", 12: "p",
                    4: "s", 7: "s", 10: "s"}
    ORACLE_CN = {"m": "万", "p": "筒", "s": "条"}

    def oracle_view(self, seat: int) -> dict | None:
        o = self.oracle.get(int(seat))
        if not o:
            return None
        return {"suit": str(o.get("suit", "m")),
                "suit_cn": self.ORACLE_CN.get(str(o.get("suit", "m")), "万"),
                "on": bool(o.get("on", True)), "dice": int(o.get("dice", 0))}

    def _oracle_lock(self, seat: int) -> bool:
        """Card07 Skill2「恶灵」：发动过「降神」的这一局，只能门清自摸和。

        只看「掷过骰子没有」（关掉降神也解除不了），不看开关状态。
        """
        return int(seat) in self.oracle

    # ── 决斗（Card08 Skill1）──────────────────────────────────
    # ── 鬼门（Card10 Skill1）──────────────────────────────────
    def owns_card10(self, seat: int) -> bool:
        s = int(seat)
        if s not in self._c10_cache:
            self._c10_cache[s] = skills.owns_card(
                self.db, self, s, 10, strict=True)
        return self._c10_cache[s]

    def _c10s2_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None or self.skill_used(s, 10, 2):
            return False
        if not self.owns_card10(s):
            return False
        dong, bei = self._c10s2_counts(s)
        return dong >= 3 and bei >= 3

    def _c10s2_counts(self, seat: int) -> tuple[int, int]:
        """手牌 + 副露里各有几张东 / 北。"""
        tiles = list(self.hand(seat))
        for m in self.melds(seat):
            tiles.extend(str(x) for x in (m.get("tiles") or []))
        return tiles.count("dong"), tiles.count("bei")

    def card10s2_activate(self, seat: int) -> dict:
        """四喜：明置手里的东/北，之后第 5 张摸到的牌直接视为小四喜自摸。"""
        s = int(seat)
        if self.skill_used(s, 10, 2):
            raise RuleError("「四喜」本局已经用过了")
        if not self.owns_card10(s):
            raise RuleError("这张不是你这一局的人物卡")
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            raise RuleError("摸牌之后、打牌之前才能发动")
        if self.drawn_tile(s) is None:
            raise RuleError("摸完牌才能发动")
        if self._c10s2_counts(s)[0] < 3 or self._c10s2_counts(s)[1] < 3:
            raise RuleError("手里/副露里要有 3 张东和 3 张北")
        reveal: list[str] = []
        hand = list(self.hand(s))
        for kind in ("dong", "bei"):
            have = hand.count(kind)
            need = 3 - sum(1 for m in self.melds(s)
                           for x in (m.get("tiles") or []) if str(x) == kind)
            take = max(0, min(need, have))
            reveal.extend([kind] * take)
        self.c10s2[s] = {"count": 0, "ready": False, "reveal": reveal}
        self.mark_skill_used(s, 10, 2)
        self.note_skill(s, 10, 2)
        self.save_flags()
        return {"seat": s, "reveal": reveal, "count": 0}

    def _c10s2_on_draw(self, seat: int) -> None:
        """数摸牌次数：第 5 次摸牌就绪。"""
        st = self.c10s2.get(int(seat))
        if not st or st.get("ready"):
            return
        st["count"] = int(st.get("count", 0)) + 1
        if st["count"] >= 5:
            st["ready"] = True
        self.save_flags()

    def _c10s2_ready(self, seat: int) -> bool:
        return bool((self.c10s2.get(int(seat)) or {}).get("ready", False))

    def _c10s2_clear(self, seat: int) -> None:
        if int(seat) in self.c10s2:
            self.c10s2.pop(int(seat), None)
            self.save_flags()

    def _c10s2_auto_tsumo(self, seat: int, tile: str) -> dict | None:
        """【四喜】第 5 张摸牌 → 直接按小四喜自摸结算（2026-10-30 用户口径）。

        · 不用玩家再点「自摸」：摸到第 5 张的那一刻就结算
        · 拦截链照旧：浓雾 / 恶灵 / 决斗 / 满贯 / 看破代价 把自摸无效掉时，
          这次机会直接作废（和以前「就绪却没和」同一套处理）
        """
        s = int(seat)
        if not self._c10s2_ready(s):
            return None
        if self.c34_muted(s) or not self._tsumo_gate_ok(s):
            self._c10s2_clear(s)
            self._event("c10s2_wasted", {"seat": s})
            return None
        if not self._win_ok(s, str(tile), tsumo=True):
            return None                      # 还有别的闸门（满贯 / 看破代价…）→ 留给玩家自己判断
        ev = self._do_tsumo(s)
        self._c10s2_clear(s)                 # 结算完就把状态收掉
        return ev

    def _c10_key(self, seat: int, kind: str) -> str:
        return "%d:%s" % (int(seat), str(kind))

    def card10_can(self, seat: int) -> bool:
        if self.is_riichi(int(seat)):
            return False          # 立直后手牌锁定：不再询问会改手牌的技能

        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None:
            return False
        return self.owns_card10(s)

    def _c10_guard(self, seat: int, kind: str) -> None:
        s = int(seat)
        k = str(kind)
        if k not in ("dong", "bei"):
            raise RuleError("鬼门只能换东或北")
        if not self.owns_card10(s):
            raise RuleError("这张不是你这一局的人物卡")
        if not self.card10_can(s):
            raise RuleError("摸牌之后、打牌之前才能发动")
        if self._c10_key(s, k) in self.c10_used:
            raise RuleError("%s 这一局已经换过了" % ("东" if k == "dong" else "北"))

    def card10_swap_hand(self, seat: int, kind: str, tiles: list[str],
                         river_seqs: list[int]) -> dict:
        """鬼门·甲：3 张手牌 ↔ 牌河里 3 张东 / 北。"""
        s = int(seat)
        k = str(kind)
        self._c10_guard(s, k)
        picks = [str(x) for x in tiles]
        seqs = [int(x) for x in river_seqs]
        if len(picks) != 3 or len(seqs) != 3:
            raise RuleError("要选 3 张手牌 + 3 张牌河牌")
        rivers = []
        for sq in seqs:
            row = self.db._row(
                "SELECT seq, seat, wall_seq, tile, called, face_down FROM round_discards "
                "WHERE round_id=? AND seq=?", (self.round_id, sq))
            if row is None:
                raise RuleError("这张牌不在牌河里")
            if int(row["face_down"] or 0) or int(row["called"] or 0):
                raise RuleError("暗置 / 被鸣走的牌不能换")
            if str(row["tile"]) != k:
                raise RuleError("牌河里要选 3 张%s" % ("东" if k == "dong" else "北"))
            rivers.append(row)
        pool: list[dict] = []
        for tname in picks:
            row = self.db._row(
                "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
                "ORDER BY is_drawn, slot LIMIT 1", (self.round_id, s, tname))
            if row is None:
                raise RuleError("手里没有 %s" % tname)
            pool.append(row)
        for i in range(3):
            self.do_swap("hand_river", s, "鬼门甲",
                         hand_seq=int(pool[i]["wall_seq"]),
                         river_seq=int(seqs[i]), face_down=False)
        self.c10_used.add(self._c10_key(s, k))
        self.save_flags()
        return {"mode": "hand", "kind": k, "got": [str(r["tile"]) for r in rivers]}

    def card10_swap_meld(self, seat: int, kind: str, my_meld_id: int,
                         target: int, target_meld_id: int) -> dict:
        """鬼门·乙：我的一组副露 ↔ 别家东 / 北 的刻子或杠。"""
        s, k, tg = int(seat), str(kind), int(target)
        self._c10_guard(s, k)
        if tg == s or tg < 0 or tg > 3:
            raise RuleError("要选别家的副露")
        if self.is_riichi(tg):
            raise RuleError("对方立直了，不能换他的副露")
        mine = self.db._row("SELECT meld_id, kind, tiles_json FROM round_melds "
                            "WHERE round_id=? AND seat=? AND meld_id=?",
                            (self.round_id, s, int(my_meld_id)))
        if mine is None:
            raise RuleError("你这一组副露不存在")
        theirs = self.db._row("SELECT meld_id, kind, tiles_json FROM round_melds "
                              "WHERE round_id=? AND seat=? AND meld_id=?",
                              (self.round_id, tg, int(target_meld_id)))
        if theirs is None:
            raise RuleError("对方那一组副露不存在")
        if str(theirs["kind"]) not in ("pon", "minkan", "ankan", "kakan"):
            raise RuleError("只能换刻子或杠")
        tl = json.loads(theirs["tiles_json"] or "[]")
        if not tl or str(tl[0]) != k:
            raise RuleError("对方那组副露不是%s" % ("东" if k == "dong" else "北"))
        if str(theirs["kind"]) == "chi":
            raise RuleError("只能换刻子或杠")
        free_mine = int(self.db._one(
            "SELECT COALESCE(MAX(meld_id), -1) + 1 FROM round_melds WHERE round_id=? AND seat=?",
            (self.round_id, s)) or 0)
        free_theirs = int(self.db._one(
            "SELECT COALESCE(MAX(meld_id), -1) + 1 FROM round_melds WHERE round_id=? AND seat=?",
            (self.round_id, tg)) or 0)
        with self.db.tx():
            self.db.conn.execute(
                "UPDATE round_melds SET seat=?, meld_id=? WHERE round_id=? AND seat=? AND meld_id=?",
                (tg, free_theirs, self.round_id, s, int(my_meld_id)))
            self.db.conn.execute(
                "UPDATE round_melds SET seat=?, meld_id=? WHERE round_id=? AND seat=? AND meld_id=?",
                (s, free_mine, self.round_id, tg, int(target_meld_id)))
        self.c10_used.add(self._c10_key(s, k))
        self.save_flags()
        return {"mode": "meld", "kind": k, "target": tg,
                "mine": int(my_meld_id), "theirs": int(target_meld_id)}

    # ── 牌河交换（Card09 S1 / S2）──────────────────────────────
    def owns_card09(self, seat: int) -> bool:
        s = int(seat)
        if s not in self._c09_cache:
            self._c09_cache[s] = skills.owns_card(
                self.db, self, s, 9, strict=True)
        return self._c09_cache[s]

    def _c09_turn_key(self, seat: int) -> str:
        """「这一巡」的钥匙：座位 + 我这一局已经打出的张数。"""
        return "%d-%d" % (int(seat), self.my_discard_count(int(seat)))

    def card09_can(self, seat: int) -> bool:
        """摸牌前可以开 09 号卡（S1/S2 轮着来；每个回合只能用一次）。"""
        if self.is_riichi(int(seat)):
            return False          # 立直后手牌锁定：不再询问会改手牌的技能

        s = int(seat)
        if self.phase != "draw" or self.turn is None or int(self.turn) != s:
            return False
        if self.c09_turn == self._c09_turn_key(s):
            return False                     # 这一巡已经用过了
        return self.owns_card09(s)

    def card09_targets(self, seat: int, skill: int = 0) -> list[int]:
        """间合现在**真能换**的牌河 seq（给客户端点选阶段过滤用）。

        排除：被吃碰 / 暗置 / 立直宣言牌 / 已经换过的那一行 / 座位不符。
        skill=1 只看自己牌河，2 只看别家，0 看「这一巡轮到的那个」。
        """
        s = int(seat)
        if not self.owns_card09(s):
            return []
        if self.phase != "draw" or self.turn is None or int(self.turn) != s:
            return []
        if self.c09_turn == self._c09_turn_key(s):
            return []
        nxt = int(self.c09_next.get(s, 0))
        if skill == 0 and nxt:
            skill = nxt
        seqs_by_seat: dict[int, list[int]] = {}
        for r0 in self.db._rows(
                "SELECT seat, seq FROM round_discards WHERE round_id=? ORDER BY seq",
                (self.round_id,)):
            seqs_by_seat.setdefault(int(r0["seat"]), []).append(int(r0["seq"]))
        out: list[int] = []
        for r in self.db._rows(
                "SELECT seq, seat, called, face_down, is_riichi_tile FROM round_discards "
                "WHERE round_id=? ORDER BY seq", (self.round_id,)):
            rs = int(r["seat"])
            if skill == 1 and rs != s:
                continue
            if skill == 2 and rs == s:
                continue
            if int(r["called"] or 0) or int(r["face_down"] or 0):
                continue
            if int(r["is_riichi_tile"] or 0):
                continue
            order = seqs_by_seat.get(rs) or []
            sq = int(r["seq"])
            if sq not in order:
                continue
            row = order.index(sq) // 6
            if ("%d:%d" % (rs, row)) in self.c09_rows:
                continue                      # 这一行换过了（攻守共用）
            out.append(sq)
        return out

    def _river_row(self, river_seat: int, river_seq: int) -> int:
        """这张弃牌是这家的第几行（每 6 张一行）。"""
        seqs = [int(r["seq"]) for r in self.db._rows(
            "SELECT seq FROM round_discards WHERE round_id=? AND seat=? ORDER BY seq",
            (self.round_id, int(river_seat)))]
        if int(river_seq) not in seqs:
            return -1
        return seqs.index(int(river_seq)) // 6

    def card09_swap(self, seat: int, skill: int, hand_tile: str, river_seq: int) -> dict:
        """摸牌前：一张手牌 ↔ 牌河里的一张明牌（S1 自己的河 / S2 别家的河）。"""
        s, sk = int(seat), int(skill)
        if sk not in (1, 2):
            raise RuleError("09 号卡只有 Skill1 / Skill2")
        if not self.owns_card09(s):
            raise RuleError("这张不是你这一局的人物卡")
        if self.phase != "draw" or self.turn is None or int(self.turn) != s:
            raise RuleError("只能在摸牌之前换")
        if self.c09_turn == self._c09_turn_key(s):
            raise RuleError("间合攻/守 每个回合只能用一次")
        nxt = int(self.c09_next.get(s, 0))
        if nxt and nxt != sk:
            raise RuleError("上一次用的是 Skill%d，这一次只能用 Skill%d"
                            % (3 - int(nxt), int(nxt)))
        row = self.db._row(
            "SELECT seq, seat, wall_seq, tile, called, face_down "
            "FROM round_discards WHERE round_id=? AND seq=?", (self.round_id, int(river_seq)))
        if row is None:
            raise RuleError("这张牌不在牌河里")
        rs = int(row["seat"])
        if int(row["face_down"] or 0):
            raise RuleError("暗置的牌不能换")
        if int(row["called"] or 0):
            raise RuleError("已经被吃碰杠拿走的牌不能换")
        if sk == 1 and rs != s:
            raise RuleError("Skill1 只能换自己牌河里的牌")
        if sk == 2 and rs == s:
            raise RuleError("Skill2 只能换别家牌河里的牌")
        r = self._river_row(rs, int(river_seq))
        if r < 0:
            raise RuleError("这张牌不在牌河里")
        key = "%d:%d" % (rs, r)
        if key in self.c09_rows:
            raise RuleError("这一行牌河已经换过了")
        hrow = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY is_drawn, slot LIMIT 1", (self.round_id, s, str(hand_tile)))
        if hrow is None:
            raise RuleError("手里没有这张牌")
        hseq = int(hrow["wall_seq"])
        tseq = int(row["wall_seq"])
        river_tile = str(row["tile"])
        self.do_swap("hand_river", s, "间合%s" % ("守" if sk == 1 else "攻"),
                     hand_seq=hseq, river_seq=int(river_seq), face_down=False)
        with self.db.tx():
            self.db.conn.execute(
                "UPDATE round_discards SET is_tsumogiri=0 WHERE round_id=? AND seq=?",
                (self.round_id, int(river_seq)))
        self.c09_turn = self._c09_turn_key(s)      # 这一巡用过了
        self.c09_next[s] = 2 if sk == 1 else 1
        self.c09_rows.add(key)
        self.note_use(s, 9, sk)                    # 卡面翻明 + 播报 + 传承
        self.save_flags()
        return {"skill": sk, "hand": str(hand_tile), "got": river_tile,
                "river_seat": rs, "row": r, "next": self.c09_next[s]}

    def owns_duel_s2(self, seat: int) -> bool:
        """Card08 Skill2「决斗标记」：持 8 号卡就自动生效。"""
        s = int(seat)
        if s not in self._duel_card_cache:
            self._duel_card_cache[s] = skills.owns_card(
                self.db, self, s, 8, strict=True)
        return self._duel_card_cache[s]

    def _char_index(self) -> int:
        """现在是这个角色的第几场（东一东二=0，东三东四=1，南一南二=2，南三南四=3）。"""
        return skills._round_index(self.round_wind, int(self.round["number"]))

    def _load_duel_meta(self) -> None:
        """读决斗标记/计数器。换角色（或换半庄）就清空 —— 一个角色只活两局。"""
        ri = self._char_index()
        mid = int(self.round.get("match_id", 0) or 0)
        row = self.db._row("SELECT value FROM meta WHERE key='duel_meta'")
        data: dict = {}
        if row:
            try:
                data = json.loads(row["value"]) or {}
            except (ValueError, TypeError):
                data = {}
        if int(data.get("match", -1)) != mid or int(data.get("ri", -1)) != ri:
            self.duel_marks = set()
            self.duel_counter = {}
            self._save_duel_meta()
            return
        self.duel_marks = {int(x) for x in (data.get("marks") or [])
                           if int(x) in range(4)}
        self.duel_counter = {int(k): int(v) for k, v in (data.get("counter") or {}).items()
                             if int(k) in range(4)}

    def _save_duel_meta(self) -> None:
        body = {"match": int(self.round.get("match_id", 0) or 0),
                "ri": self._char_index(),
                "marks": sorted(int(x) for x in self.duel_marks),
                "counter": {str(k): int(v) for k, v in self.duel_counter.items()}}
        with self.db.tx():
            self.db.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('duel_meta', ?)",
                (json.dumps(body),))

    def _duel_mark(self, seat: int) -> None:
        """给这家挂上决斗标记（已经有了就还是 1 个）。"""
        s = int(seat)
        if s in self.duel_marks:
            return
        self.duel_marks.add(s)
        self._save_duel_meta()

    def duel_seats(self) -> set[int]:
        d = self.duel
        if not d:
            return set()
        return {int(d.get("by", -1)), int(d.get("target", -1))}

    def duel_restricted(self, seat: int) -> bool:
        """是不是「被决斗限制」的非决斗家（只能摸切 + 暗置打出）。"""
        if not self.duel:
            return False
        if self.c34_muted(seat):
            return False                       # 【厄运】：三巡内决斗不生效
        return int(seat) not in self.duel_seats()

    def duel_view(self, seat: int | None) -> dict | None:
        d = self.duel
        if not d:
            return None
        by, tg = int(d.get("by", -1)), int(d.get("target", -1))
        mine = seat is not None and int(seat) == by
        return {"by": by, "target": tg, "mine": mine,
                "restricted": (seat is not None and int(seat) not in (by, tg))}

    def duel_can_start(self, seat: int) -> bool:
        s = int(seat)
        if self.duel or self.phase != "discard":
            return False
        if self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None:
            return False
        if self.turn_count(s) < 6:                 # 第六巡之后
            return False
        if self.skill_used(s, 8, 1):
            return False
        return skills.owns_card(self.db, self, s, 8, strict=True)

    def duel_start(self, seat: int, target: int) -> dict:
        """第六巡后摸牌完：指定一家开决斗。"""
        s, t = int(seat), int(target)
        if self.skill_used(s, 8, 1):
            raise RuleError("「决斗」本局已经用过了")
        if not skills.owns_card(self.db, self, s, 8, strict=True):
            raise RuleError("这张不是你这一局的人物卡")
        if self.duel:
            raise RuleError("已经在决斗里了")
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            raise RuleError("只能在自己摸牌之后发动")
        if self.drawn_tile(s) is None:
            raise RuleError("摸完牌才能发动")
        if self.turn_count(s) < 6:
            raise RuleError("第六巡之后才能发动「决斗」")
        if t < 0 or t > 3 or t == s:
            raise RuleError("决斗对象不对")
        self.duel = {"by": s, "target": t}
        self._duel_mark(s)                          # 参与决斗的两家拿标记
        self._duel_mark(t)
        self.mark_skill_used(s, 8, 1)
        self.note_skill(s, 8, 1)
        for o in range(4):                          # 另外两家不能正常摸切
            if o not in (s, t):
                self.card05_interfere(o, s, "决斗")
        self.save_flags()
        return {"duel": self.duel_view(s), "target": t}

    def duel_retarget(self, seat: int) -> None:
        """非决斗家 副露 / 立直 / 用技能 → 决斗对象转移到这家（发起者不变）。"""
        d = self.duel
        if not d:
            return
        s = int(seat)
        if s in self.duel_seats():
            return
        d["target"] = s
        self._duel_mark(s)                          # 转移一次 → 新对手也拿标记
        self.card05_interfere(s, int(d.get("by", -1)), "决斗")
        self.save_flags()

    def _oracle_kinds(self, suit: str) -> list[str]:
        return ["%d%s" % (n, suit) for n in range(1, 10)]

    def _start_oracle(self, seat: int, card: int, skill: int) -> dict:
        """配牌阶段点「降神」：掷两颗骰子定花色，本局固定，默认打开。"""
        s = int(seat)
        if not skills.owns_card(self.db, self, s, card):
            raise RuleError("这张不是你这一局的人物卡")
        if s in self.oracle:
            return {"ok": True, "armed": False, "already": True,
                    "reason": "「降神」本局已经掷过骰子了",
                    "oracle": self.oracle_view(s)}
        d1 = random.randint(1, 6)
        d2 = random.randint(1, 6)
        total = d1 + d2
        suit = self.ORACLE_SUITS.get(total, "m")
        self.oracle[s] = {"suit": suit, "on": True, "dice": total}
        self.note_skill(s, card, skill)             # 播报 + 人物卡翻明
        if self.broadcast:
            self.broadcast["text"] = "【降神】：随机花色为【%s】" % self.ORACLE_CN[suit]
        self.deal_wait.discard(s)                   # 掷完就算做完决定了
        self.save_flags()
        self._maybe_close_deal()
        return {"ok": True, "armed": True, "card": int(card), "skill": int(skill),
                "skill_name": "降神", "kind": "oracle_suit", "dice": total,
                "oracle": self.oracle_view(s), "pending": sorted(self.deal_wait)}

    def oracle_toggle(self, seat: int) -> dict:
        """再点一次技能图标：打开 / 关闭。"""
        s = int(seat)
        o = self.oracle.get(s)
        if not o:
            raise RuleError("「降神」还没掷骰子")
        o["on"] = not bool(o.get("on", True))
        self.save_flags()
        return {"on": bool(o["on"]), "oracle": self.oracle_view(s)}

    def _upcoming_wall_seqs(self, k: int) -> list[int]:
        """牌山接下来要摸的 k 张（按摸牌顺序的 seq）。只看不动。"""
        out: list[int] = []
        no = self.next_no
        first = self.wall_first_stack()
        for _ in range(int(k)):
            n = wallmodel.next_live_no(no, first)
            if n is None:
                break
            out.append(int(wallmodel.seq_of_tile(n)))
            no = wallmodel.wrap_tile(n + 1)
        return out

    def oracle_pick(self, seat: int, kind: str) -> dict:
        """摸牌前指定一张牌：别家有它的，按 下家/对家/上家 换「牌山接下来第 1/2/3 张」。"""
        s = int(seat)
        o = self.oracle.get(s)
        if not o:
            raise RuleError("「降神」还没掷骰子")
        if not bool(o.get("on", True)):
            raise RuleError("「降神」现在是关着的")
        tile = str(kind)
        suit = str(o.get("suit", "m"))
        if tile not in self._oracle_kinds(suit):
            raise RuleError("这张牌不在「降神」选定的花色里")
        if self.phase != "draw" or (self.turn is None or int(self.turn) != s):
            raise RuleError("要在自己摸牌之前指定")
        upcoming = self._upcoming_wall_seqs(3)
        swaps: list[dict] = []
        for k in range(1, 4):
            if k - 1 >= len(upcoming):
                break
            opp = (s + k) % 4
            row = self.db._row(
                "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
                "ORDER BY is_drawn, slot LIMIT 1", (self.round_id, opp, tile))
            if row is None:
                continue                       # 这家没有这张牌，跳过
            hseq = int(row["wall_seq"])
            # 统一换到「我马上要摸的那一张」：这样指定哪张就一定摸到哪张
            wseq = int(upcoming[0])
            wtile = self.db._one(
                "SELECT tile FROM round_wall WHERE round_id=? AND seq=?",
                (self.round_id, wseq))
            if wtile is None:
                continue
            self.do_swap("hand_wall", s, "降神", hand_seq=hseq, wall_seq=wseq)
            swaps.append({"seat": opp, "tile": tile, "with": str(wtile),
                          "wall_seq": wseq, "order": k})
            break                              # 换到一张就够了（下一张已经是它）
        self.save_flags()
        return {"tile": tile, "suit": suit, "swaps": swaps}

    # 计数器上限（用户口径 2026-10-23）：策略只能攒 1 点，多害几次也不叠加
    CARD05_COUNTER_MAX = 1

    def card05_interfere(self, affected: int, by: int, reason: str) -> None:
        """别人的技能害我手牌变了 / 不能正常摸切：计数器 +1（上限 1），并给他一次换牌机会。"""
        if int(affected) == int(by) or not self.owns_card05(affected):
            return
        a = int(affected)
        self.card05_counter[a] = min(self.CARD05_COUNTER_MAX,
                                     int(self.card05_counter.get(a, 0)) + 1)
        self.card05_offer[a] = {"by": int(by), "reason": str(reason)}
        self.save_flags()

    def _hand_snapshot(self) -> dict[int, tuple]:
        """四家手牌快照（只比牌种，不看 slot / 摸牌标记），给技能前后比对用。"""
        out: dict[int, tuple] = {}
        for s in range(4):
            out[s] = tuple(sorted(str(r["tile"]) for r in self.db._rows(
                "SELECT tile FROM round_hands WHERE round_id=? AND seat=?",
                (self.round_id, int(s)))))
        return out

    def card05_note_changes(self, before: dict, by: int, reason: str) -> list[int]:
        """技能执行完拍第二张快照：手牌被别人的技能动过的人 → 策略计数 +1 + 换牌机会。

        只认「牌种集合真的变了」：没换到牌的对手不会被误判（南风经常有三家都没指定牌）。
        自己用自己的技能不算（by == affected 由 card05_interfere 过滤）。
        """
        after = self._hand_snapshot()
        touched: list[int] = []
        for s in range(4):
            if int(s) == int(by):
                continue
            if before.get(int(s)) == after.get(int(s)):
                continue
            self.card05_interfere(int(s), int(by), reason)
            touched.append(int(s))
        return touched

    # ══════════════════════════════════════════════════════════════════════
    #  换牌统一入口：所有技能的「换」都走这里
    #    · 三张视图表由 rules/swap.py 保证一致（round_wall / hands / discards）
    #    · 动到宝牌指示牌 → 自动重算表宝/里宝
    #    · 换到别人的手牌 → 自动给「策略」(Card05 S1) 发机会
    # ══════════════════════════════════════════════════════════════════════
    def do_swap(self, kind: str, by: int, reason: str, **kw) -> dict:
        # 立直后手牌锁定：先按 kind 查出「谁的手牌会被改」（wall_seq 是真凭据）
        _locks: list[int] = []
        if kind == "hand_hand":
            _locks = [int(kw.get("seat_a", -1)), int(kw.get("seat_b", -1))]
        elif kind == "river_hand":
            _locks = [int(kw.get("seat", -1))]
        elif kind in ("hand_river", "hand_wall"):
            _hs = int(kw.get("hand_seq", -1))
            if _hs >= 0:
                _row = self.db._row(
                    "SELECT seat FROM round_hands WHERE round_id=? AND wall_seq=?",
                    (self.round_id, _hs))
                if _row is not None:
                    _locks = [int(_row["seat"])]
        force = bool(kw.pop("force", False))     # force=True：连立直锁一起跳过（海底）
        if _locks and not force:
            self._assert_hand_mutable(*_locks)
        before = self._hand_snapshot()
        if kind == "hand_river":
            r = swap.swap_hand_river(self.db, self.round_id, **kw)
        elif kind == "hand_wall":
            r = swap.swap_hand_wall(self.db, self.round_id, **kw)
        elif kind == "wall_wall":
            r = swap.swap_wall_wall(self.db, self.round_id, **kw)
        elif kind == "hand_hand":
            r = swap.swap_hand_hand(self.db, self.round_id, **kw)
        elif kind == "river_hand":
            r = swap.move_river_to_hand(self.db, self.round_id, **kw)
        else:
            raise RuleError(f"不认识的换牌类型 {kind}")
        if r.get("seqs"):
            self._c11_sync_dora(r["seqs"])          # 动到宝牌墩就跟着重算
        self.card05_note_changes(before, int(by), str(reason))
        self.save_flags()
        return r

    # ── 换两张手牌的**唯一**实现（自风 / 南风 / 风神·宝牌运 / 向听 都走这里）──
    def _swap_hand_tiles(self, seat_a: int, seq_a: int, seat_b: int, seq_b: int,
                         reason: str, *, by: int | None = None,
                         clear_drawn: bool = False) -> dict:
        """归属对调交给 do_swap（立直锁 / 策略计数 / 宝牌同步 / save_flags 一次到位）。

        · `seq_a` 是 seat_a 自己的那张（出去），`seq_b` 是 seat_b 自己的那张（进来）
        · `clear_drawn=True`：换完把这两张的「刚摸到」标记清掉（自风/南风/风神的老口径，
          它们随后自己把该标的那张标回去）
        · 不改 slot：老实现会追加到末尾，但没有任何逻辑依赖 slot 顺序（只有几处列表用）
        """
        r = self.do_swap("hand_hand", int(seat_a if by is None else by), reason,
                         seat_a=int(seat_a), hand_seq_a=int(seq_a),
                         seat_b=int(seat_b), hand_seq_b=int(seq_b))
        if clear_drawn:
            with self.db.tx():
                self.db.conn.execute(
                    "UPDATE round_hands SET is_drawn=0 "
                    "WHERE round_id=? AND wall_seq IN (?,?)",
                    (self.round_id, int(seq_a), int(seq_b)))
            self.save_flags()
        return r

    def _set_hand_drawn(self, seq: int, on: bool) -> None:
        """把某张手牌标成 / 取消「刚摸到的」。"""
        with self.db.tx():
            self.db.conn.execute(
                "UPDATE round_hands SET is_drawn=? WHERE round_id=? AND wall_seq=?",
                (1 if on else 0, self.round_id, int(seq)))
        self.save_flags()

    def card05_extra_activate(self, seat: int) -> dict:
        """策略段3：本回合打出一张后，再摸一张再打一张。

        使用场景 = **摸牌时**（刚摸完牌、还没打，可以再摸一张再打）。
        发动条件只有：自己的出牌回合 + 刚摸完牌 + 计数器 ≥1 + 本回合没挂过。
        「不能正常摸切」不是这个技能的前置条件，而是**计数器 +1 的场景**
        （别人让你没法正常摸切 → `card05_interfere` 给你攒 1 点，目前只有【决斗】）。
        别在这儿加 duel_restricted 判断。
        """
        if self.phase != "discard" or int(seat) != int(self.turn):
            raise RuleError("现在不是你的出牌回合")
        if self.drawn_tile(seat) is None:
            raise RuleError("摸牌之后才能发动")
        if seat in self.card05_extra:
            raise RuleError("这一回合已经发动过了")
        if int(self.card05_counter.get(seat, 0)) <= 0:
            raise RuleError("计数器是 0，还不能发动")
        self.card05_counter[seat] = int(self.card05_counter.get(seat, 0)) - 1
        self.card05_extra.add(int(seat))
        self.save_flags()
        return {"extra": True, "counter": int(self.card05_counter[seat])}

    def _extra_draw(self, seat: int) -> dict:
        """策略：本回合打出一张后再摸一张。

        走 _draw_common（和普通摸牌同一套钩子），事件上多打一个 extra。
        """
        ev = self._draw_common(int(seat))
        self.save_flags()                     # _advance() 里的收尾，这里要自己补
        ev["extra"] = True
        return ev

    def _advance_after_discard(self, seat: int) -> None:
        """一张牌打完、没人鸣：如果用了「策略」的额外摸切，就自己再摸一张。"""
        if int(seat) in self.card05_extra:
            self.card05_extra.discard(int(seat))
            self.turn = int(seat)
            self.phase = "draw"
            self.save_flags()
            self._extra_draw(int(seat))
            return
        self._next_player()

    def card05_nuki(self, seat: int) -> dict:
        """拔北：把一张北放到牌河（不算振听、不鸣牌），从正常牌山补一张再打。"""
        if not self.owns_card05(seat):
            raise RuleError("这张不是你这一局的人物卡")
        if self.phase != "discard" or int(seat) != int(self.turn):
            raise RuleError("现在不是你的出牌回合")
        self._assert_hand_mutable(seat)                  # 立直后不能拔北
        row = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile='bei' "
            "ORDER BY is_drawn DESC, wall_seq DESC LIMIT 1", (self.round_id, int(seat)))
        if row is None:
            raise RuleError("手里没有北")
        if self.live_left() <= 0:
            # 牌山已经摸完：再拔北就补不到牌了（北出河、手牌净少一张 = 小相公）
            raise RuleError("牌山已经摸完，不能拔北")
        hseq = int(row["wall_seq"])
        with self.db.tx():
            self.db.conn.execute(
                "DELETE FROM round_hands WHERE round_id=? AND wall_seq=?",
                (self.round_id, hseq))
            dseq = int(self.db._one(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM round_discards WHERE round_id=?",
                (self.round_id,)) or 1)
            self.db.conn.execute(
                "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile,"
                " is_tsumogiri, is_riichi_tile, face_down, called, is_nuki)"
                " VALUES(?,?,?,?,?,0,0,0,0,1)",
                (self.round_id, dseq, int(seat), hseq, "bei"))
        self.nuki_count[int(seat)] = int(self.nuki_count.get(int(seat), 0)) + 1
        if self.armed_skill and int(self.armed_skill.get("seat", -1)) == int(seat):
            self.armed_skill = None
            self._skill_cache = None
        self.press_win.discard(seat)
        # 从正常牌山补一张（不是岭上）
        info = self._draw_next_info(seat)
        if info is None:
            self.save_flags()
            return self._event("ryuukyoku", {"reason": "exhaustive"})
        self.phase = "discard"
        self.turn = int(seat)
        owner = self._self_wind_owner(seat, info["tile"])
        if owner is not None and (self.c34_muted(int(seat)) or self.c34_muted(int(owner))):
            owner = None                       # 【厄运】：自风三巡内无效
        if owner is not None:
            self.wind_swap = {"owner": int(owner), "from": int(seat), "tile": info["tile"]}
            self.phase = "wind_swap"
        self.save_flags()
        return {"nuki": int(self.nuki_count[int(seat)]), "drawn": info["tile"],
                "discard_seq": dseq}

    def card05_swap(self, seat: int, hand_tile: str, kind: str,
                    stack: int = 0, half: str = "top", river_seq: int = -1) -> dict:
        """从王牌 / 弃牌里挑一张，和自己的一张手牌交换（明暗状态跟着位置走）。"""
        if not self.owns_card05(seat):
            raise RuleError("这张不是你这一局的人物卡")
        if seat not in self.card05_offer:
            raise RuleError("现在没有可以交换的牌")
        # 换牌机会是「别人动了我的手牌」那一刻发的，可能发在别人的回合里
        # （画板转移就发生在摸牌那一下）。只要机会还在、本局没结束，就允许换，
        # 否则玩家会被卡在选牌界面里出不来。
        if self.phase == "ended":
            raise RuleError("本局已经结束了")
        tile = str(hand_tile)
        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, seat))
        pick = next((r for r in rows if str(r["tile"]) == tile), None)
        if pick is None:
            raise RuleError(f"手里没有 {tile}")
        hseq = int(pick["wall_seq"])

        target_tile = ""
        tseq = -1
        down = False
        if kind == "dead":
            n = self.wall_first_stack()
            k = wallmodel.wrap_stack(int(stack))
            if not wallmodel.is_dead_stack(k, n):
                raise RuleError("这墩不是王牌")
            a, b = wallmodel.tile_nos_of_stack(k)
            no = a if str(half) == "top" else b
            tseq = wallmodel.seq_of_tile(no)
            row = self.db._row(
                "SELECT tile FROM round_wall WHERE round_id=? AND seq=? AND dealt_to IS NULL",
                (self.round_id, tseq))
            if row is None:
                raise RuleError("这张王牌已经摸走了")
            target_tile = str(row["tile"])
            down = True                                  # 王牌永远是暗置
        elif kind == "river":
            row = self.db._row(
                "SELECT seq, wall_seq, tile, called, is_riichi_tile, face_down "
                "FROM round_discards WHERE round_id=? AND seq=?",
                (self.round_id, int(river_seq)))
            if row is None:
                raise RuleError("这张牌不在牌河里")
            if int(row["called"] or 0):
                raise RuleError("已经被吃碰杠拿走的牌不能换")
            if int(row["is_riichi_tile"] or 0):
                raise RuleError("立直宣言牌不能换")
            tseq = int(row["wall_seq"])
            target_tile = str(row["tile"])
            down = bool(int(row["face_down"] or 0))
        else:
            raise RuleError("不认识的交换目标")

        if kind == "river":
            self.do_swap("hand_river", seat, "策略", hand_seq=hseq,
                         river_seq=int(river_seq), face_down=down)
        else:
            self.do_swap("hand_wall", seat, "策略", hand_seq=hseq, wall_seq=tseq)
        self.card05_offer.pop(seat, None)
        if kind == "dead":
            self._c11_sync_dora({tseq})    # 换到王牌上的指示牌 → 宝牌信息跟着变
        self.save_flags()
        return {"hand": tile, "got": target_tile, "kind": kind,
                "face_down": down, "stack": int(stack), "half": str(half)}

    def card05_cancel(self, seat: int) -> dict:
        self.card05_offer.pop(int(seat), None)
        self.save_flags()
        return {"cancelled": True}

    def card05_view_hand(self, viewer: int, target: int) -> dict:
        """别人要看 target 的手牌：持有策略的人先挑三张盖住，这次就看不到。"""
        if target < 0 or target > 3 or int(viewer) == int(target):
            raise RuleError("对象玩家不对")
        if self.owns_card05(target) and not self.card05_hidden.get(target) \
                and target not in self.card05_pending_hide:
            self.card05_pending_hide[int(target)] = int(viewer)
            self.save_flags()
            return {"blocked": True, "target": int(target)}
        hidden = set(int(x) for x in (self.card05_hidden.get(target) or []))
        hand = [r["tile"] for r in self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, target))
            if int(r["wall_seq"]) not in hidden]
        return {"blocked": False, "target": int(target), "hand": hand}

    def card05_hide(self, seat: int, tiles: list[str]) -> dict:
        """被看手牌时盖住最多三张。"""
        if int(seat) not in self.card05_pending_hide:
            raise RuleError("现在没有要看手牌的人")
        picks = [str(t) for t in tiles]
        if len(picks) < 1 or len(picks) > 3:
            raise RuleError("最多盖三张")
        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, seat))
        pool: dict[str, list[int]] = {}
        for r in rows:
            pool.setdefault(str(r["tile"]), []).append(int(r["wall_seq"]))
        seqs: list[int] = []
        for t in picks:
            if not pool.get(t):
                raise RuleError(f"手里没有 {t}")
            seqs.append(pool[t].pop(0))
        self.card05_hidden[int(seat)] = seqs
        self.card05_pending_hide.pop(int(seat), None)
        self.save_flags()
        return {"hidden": len(seqs)}

    # ── 取消「还在选牌」的技能（再点一次技能图标）──────────────
    def skill_cancel(self, seat: int, what: str = "") -> dict:
        """把「已经点开、但还没真正生效」的技能撤回。

        风神：一张都没换（stage=0）时算没发动过 —— 还留在配牌窗口里等，可以重新点；
              换过至少一家就不能退回手牌了，算用掉这个技能，窗口关掉。
        南风：换牌是一次调用做完的，取消时一定还没换 → 算没发动过。
        自风：等于「不换」，和超时兜底一样（摸牌的人继续打）。
        策略：换牌机会作废 / 放弃盖牌。
        返回 {cancelled, kind, used}；没有可取消的东西就抛 RuleError。
        """
        s = int(seat)
        f = self.deal_flow
        if f and int(f.get("seat", -1)) == s:
            kind = str(f.get("kind", "fengshen"))
            stage = f.get("stage")
            used = not (kind == "south_wind" or (kind == "fengshen" and int(stage or 0) == 0))
            self.deal_flow = None
            if used:
                self.deal_wait.discard(s)
                self.deal_used.add(s)
            else:
                # 「算没发动过」→ 连「本小局已用过」的标记也撤掉，否则不能重新发动
                key = "%d-%d-%d" % (int(f.get("card", 0)), int(f.get("skill", 0)), s)
                self.used_skills.discard(key)
            self.save_flags()
            self._maybe_close_deal()
            return {"cancelled": True, "kind": kind, "used": bool(used)}

        w = self.wind_swap
        if w and int(w.get("owner", -1)) == s:
            self.wind_swap_pass()                    # 内部会 save_flags + 把回合还给摸牌的人
            return {"cancelled": True, "kind": "self_wind", "used": False}

        if s in self.card05_offer:
            self.card05_cancel(s)
            return {"cancelled": True, "kind": "card05_offer", "used": False}

        if s in self.card05_pending_hide:
            self.card05_pending_hide.pop(s, None)
            self.save_flags()
            return {"cancelled": True, "kind": "card05_hide", "used": False}

        wp = self.win_pending
        if wp and int(wp.get("seat", -1)) == s:
            card = int(wp.get("card", 0))
            want = str(what or "").lower()
            aliases = {43: ("c43s1", "nomiss"), 46: ("c46s1", "evil")}
            if want in ("", "win_pending") or want in aliases.get(card, ()):
                self.win_pending = None
                self.save_flags()
                if card == 46:
                    # 恶听：牌已经切进牌河了 → 取消 = 这次不和，轮到下家
                    self._advance_after_discard(s)
                    return {"cancelled": True, "kind": "c46s1", "used": True}
                # NO MISS：换过的牌保留（和风神同口径），技能算用掉，正常打牌
                return {"cancelled": True, "kind": "c43s1", "used": True}

        raise RuleError("现在没有可以取消的技能")

    # ── 自风（Card04 Skill2）────────────────────────────────────
    def seat_wind(self, seat: int) -> str:
        """这个座位的自风（庄家=东，逆时针 南西北）。"""
        return ["dong", "nan", "xi", "bei"][(int(seat) - self.dealer) % 4]

    def _self_wind_owner(self, drawer: int, tile: str) -> int | None:
        """drawer 摸到 tile：有没有人要发动「自风」？"""
        if self.hand_locked(drawer):
            return None                  # 立直家摸到的牌不能被拿走（手牌锁定）
        t = str(tile)
        if t not in self.WINDS:
            return None
        for owner in sorted(self.self_wind):
            if int(owner) == int(drawer):
                continue
            if self.is_riichi(owner):
                continue                       # 立直后失效
            if self.seat_wind(owner) == t:
                return int(owner)
        return None

    def wind_swap_view(self) -> dict | None:
        w = self.wind_swap
        if not w:
            return None
        return {"owner": int(w["owner"]), "from": int(w["from"]),
                "tile": str(w["tile"])}

    def wind_swap_apply(self, seat: int, tile: str) -> dict:
        """自风交换：我选一张手牌，跟对方刚摸到的自风换。"""
        w = self.wind_swap
        if self.phase != "wind_swap" or not w:
            raise RuleError("现在没有要换的自风")
        if int(w.get("owner", -1)) != int(seat):
            raise RuleError("这不是你的自风交换")
        drawer = int(w["from"])
        wind = str(w["tile"])
        self._assert_hand_mutable(seat, drawer)     # 两边的手牌都动

        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, seat))
        pick = next((r for r in rows if str(r["tile"]) == str(tile)), None)
        if pick is None:
            raise RuleError(f"手里没有 {tile}")

        wrow = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? "
            "AND tile=? ORDER BY is_drawn DESC, wall_seq DESC LIMIT 1",
            (self.round_id, drawer, wind))
        if wrow is None:
            raise RuleError("摸到的那张自风已经不在对方手里了")

        before = self._hand_snapshot()          # 策略：换牌前后的手牌比对
        self._swap_hand_tiles(seat, int(pick["wall_seq"]), drawer,
                              int(wrow["wall_seq"]), "自风", clear_drawn=True)
        # 我出的那张到了他手里 = 他刚摸到的那张
        self._set_hand_drawn(int(pick["wall_seq"]), True)
        self.card05_note_changes(before, seat, "自风")    # 策略：摸牌的人手牌被换了
        self.wind_swap = None
        self.phase = "discard"
        self.turn = drawer
        self.save_flags()
        return {"tile": str(tile), "got": wind, "from": drawer}

    def wind_swap_pass(self) -> dict:
        """没人操作时兜底：不换，摸牌的人继续打。"""
        w = self.wind_swap
        if not w:
            return self._event("claim_none", {})
        drawer = int(w["from"])
        self.wind_swap = None
        self.phase = "discard"
        self.turn = drawer
        self.save_flags()
        return {"event": "wind_swap_pass", "seat": drawer, "tile": str(w["tile"])}

    # ── 风神（Card04 Skill1）────────────────────────────────────
    WINDS = ("dong", "nan", "xi", "bei")

    def _winds_of(self, seat: int) -> list[dict]:
        """某家手里的风牌（东南西北）。"""
        return [r for r in self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY slot", (self.round_id, seat))
            if str(r["tile"]) in self.WINDS]

    # ── 宝牌运（Card25 Skill1）──────────────────────────────────
    def _dora_kinds(self) -> list[str]:
        """已经翻开的宝牌是哪几种牌（从 round_dora 读，绝不缓存：杠会翻新的）。"""
        return [str(r["dora"]) for r in self.db._rows(
            "SELECT dora FROM round_dora WHERE round_id=? AND kind='dora' "
            "AND revealed=1 ORDER BY idx", (self.round_id,))
            if str(r["dora"] or "")]

    def _is_dora(self, tile: str, kinds: list[str] | None = None) -> bool:
        """这张牌是不是宝牌。赤 5 本身就算宝牌（用户口径：含赤）。"""
        t = str(tile)
        if is_red(t):
            return True
        ks = self._dora_kinds() if kinds is None else kinds
        return kind_of(t) in ks

    def _doras_of(self, seat: int) -> list[dict]:
        """某家手里的宝牌（含赤 5）。"""
        ks = self._dora_kinds()
        return [r for r in self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY slot", (self.round_id, int(seat)))
            if self._is_dora(str(r["tile"]), ks)]

    # ── Card26 S1「云外镜」/ S2「天梯」────────────────────────────
    def _deal_wait_keep(self, seat: int) -> bool:
        """这家还有**别的**配牌技能没发动吗？

        ★ 同一张卡有两个配牌技能（Card26 云外镜 + 天梯）时，发完第一个不能就把他
          踢出配牌窗口 —— 不然第二个点下去服务端会回「现在不是配牌技能阶段」。
        """
        s = int(seat)
        return any(not self.skill_used(s, int(o["card"]), int(o["skill"]))
                   for o in self._deal_skill_options(s))

    def _arm_c28s1(self, seat: int, card: int, skill: int) -> dict:
        """配牌点【满贯】(28-1)：本局**任何玩家**和牌都必须先把番数结算到满贯。

        拦截不是「点了再拒」——按钮根本不出现（见 `_c28s1_allows`）。
        """
        s = int(seat)
        self.c28s1_on.add(s)
        self.note_use(s, card, skill, gate=False)     # op 层已经问过看破
        if not self._deal_wait_keep(s):
            self.deal_wait.discard(s)
            self.deal_used.add(s)
            self._maybe_close_deal()
        self.save_flags()
        return {"ok": True, "armed": True, "card": int(card), "skill": int(skill),
                "skill_name": skills.info(card, skill).get("name", ""),
                "kind": "c28s1", "pending": sorted(self.deal_wait)}

    def _arm_c26s1(self, seat: int, card: int, skill: int) -> dict:
        """配牌点「云外镜」：本局我看得见其他三家的角色卡（过期的不揭）。"""
        s = int(seat)
        self.note_use(s, card, skill, gate=False)     # op 层已经问过看破
        if not self._deal_wait_keep(s):               # 还有天梯没发就继续等
            self.deal_wait.discard(s)
            self.deal_used.add(s)
            self._maybe_close_deal()
        self.save_flags()
        return {"ok": True, "armed": True, "card": int(card), "skill": int(skill),
                "skill_name": skills.info(card, skill).get("name", ""),
                "kind": "c26s1", "pending": sorted(self.deal_wait)}

    def _arm_c26s2(self, seat: int, card: int, skill: int) -> dict:
        """配牌点「天梯」：本局开启 —— 每次自己摸牌前先排接下来 1+n 张。"""
        s = int(seat)
        if s in self.c26s2_on:
            return {"ok": True, "armed": True, "already": True,
                    "pending": sorted(self.deal_wait)}
        self.c26s2_on.add(s)
        self.c26_n[s] = C26_N0            # n 从 1 开始（第一次排 1+n = 2 张）
        self.c26_last[s] = -1
        self.c26_done.pop(s, None)
        self.note_use(s, card, skill, gate=False)
        if not self._deal_wait_keep(s):               # 还有云外镜没发就继续等
            self.deal_wait.discard(s)
            self.deal_used.add(s)
            self._maybe_close_deal()
        self.save_flags()
        return {"ok": True, "armed": True, "card": int(card), "skill": int(skill),
                "skill_name": skills.info(card, skill).get("name", ""),
                "kind": "c26s2", "pending": sorted(self.deal_wait)}

    # ── 天梯：每次自己摸牌前，排接下来 1+n 张 ──────────────────
    def c26_count(self, seat: int) -> int:
        """这次要排几张牌 = 1 + n（活牌不够就按活牌数）。"""
        s = int(seat)
        k = int(self.c26_n.get(s, 0)) + 1
        return max(1, min(k, self.live_left()))

    def c26_can_sort(self, seat: int) -> bool:
        s = int(seat)
        if s not in self.c26s2_on:
            return False
        if self.phase != "draw" or self.turn is None or int(self.turn) != s:
            return False
        if self.round_phase == "deal" or self.phase == "ended":
            return False
        if self.live_left() < 1:
            return False
        return int(self.c26_done.get(s, -1)) != int(self.next_no)   # 这一巡还没排

    def _c26_seqs(self, k: int) -> list[int]:
        out: list[int] = []
        nxt = self.next_no
        first = self.wall_first_stack()
        for _ in range(int(k)):
            no = wallmodel.next_live_no(nxt, first)
            if no is None:
                break
            out.append(wallmodel.seq_of_tile(no))
            nxt = wallmodel.wrap_tile(no + 1)
        return out

    def _c26_tiles(self, k: int) -> list[str]:
        out: list[str] = []
        for sq in self._c26_seqs(k):
            row = self.db._row("SELECT tile FROM round_wall WHERE round_id=? AND seq=?",
                               (self.round_id, int(sq)))
            out.append(str(row["tile"]) if row else "")
        return out

    def c26_view(self, seat: int) -> list[str]:
        """只给开着天梯的人看「接下来 1+n 张」。"""
        if not self.c26_can_sort(int(seat)):
            return []
        return self._c26_tiles(self.c26_count(int(seat)))

    def c26_set(self, seat: int, order: list[int]) -> dict:
        """按玩家排的顺序改写接下来 1+n 张。order[i] = 第 i+1 张取原来第几张。"""
        s = int(seat)
        if not self.c26_can_sort(s):
            raise RuleError("天梯：现在不用排牌山")
        k = self.c26_count(s)
        seqs = self._c26_seqs(k)
        if len(seqs) != k:
            raise RuleError("天梯：牌山剩下的牌不够")
        want = [int(x) for x in (order or [])]
        if sorted(want) != list(range(k)):
            raise RuleError("天梯：要把这 %d 张都排上（每张用一次）" % k)
        tiles = self._c26_tiles(k)
        if any(t == "" for t in tiles):
            raise RuleError("天梯：读不到牌山（这一手作废）")
        with self.db.tx():
            for i, sq in enumerate(seqs):
                self.db.conn.execute(
                    "UPDATE round_wall SET tile=? WHERE round_id=? AND seq=?",
                    (tiles[want[i]], self.round_id, int(sq)))
        self.c26_done[s] = int(self.next_no)      # 这一巡排过了 → 放行摸牌
        self.c26_deadline = 0.0
        self.save_flags()
        return {"seat": s, "k": k, "tiles": [tiles[i] for i in want], "order": want}

    def c26_timeout(self) -> bool:
        if self.turn is None or not self.c26_can_sort(int(self.turn)):
            return False
        dl = float(self.c26_deadline or 0)
        return dl > 0.0 and time.time() > dl

    def c26_skip(self) -> None:
        """超时兜底：这一巡不排了，直接放行摸牌。"""
        if self.turn is not None:
            self.c26_done[int(self.turn)] = int(self.next_no)
        self.c26_deadline = 0.0
        self.save_flags()

    # ── Card35 S1【流势】：每次自己副露 → 排接下来 4 张牌山（不限次数）──
    C35_N = 4
    C35_TIMEOUT = 20.0

    # ── Card36 S1【思路】：别人宣告技能（问看破那一刻）→ 看他手牌，直到我打出一张 ──
    def c36s1_owns(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 36, strict=True)

    def c36s1_touch(self, actor: int) -> None:
        """有人要发动技能（看破 / 封堵的询问节点）→ 持有【思路】的人立刻看到他的手牌。

        · 不限次数；同一家重复发动只是 set 去重
        · 不 note_use / 不进看破闸门（用户口径：此技能不询问看破）
        · 自己打出一张牌就失效（见 `_do_discard` 里的 `c36s1_clear`）
        """
        a = int(actor)
        if not (0 <= a < 4):
            return
        hit = False
        for me in range(4):
            if me == a:
                continue
            if not self.c36s1_owns(me):
                continue
            if self.c34_muted(me):
                continue                      # 【厄运】：三巡内技能无效
            cur = self.c36_watch.setdefault(me, set())
            if a not in cur:
                cur.add(a)
                hit = True
        if hit:
            self.save_flags()

    def c36s1_clear(self, seat: int) -> None:
        """我打出一张牌 → 这次看到的手牌全部复位。"""
        if self.c36_watch.pop(int(seat), None) is not None:
            self.save_flags()

    def c36s2_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.skill_used(s, 36, 2):
            return False                      # 本小局一次
        if int(self.c36s2_on) == s:
            return False                      # 已经开着
        return self.c36s1_owns(s)

    def c36s2_arm(self, seat: int) -> dict:
        """切牌前点【故意】：开启 → 下一张打出去的牌要判「谁能和」。"""
        s = int(seat)
        if not self.c36s2_can(s):
            raise RuleError("「故意」只能在自己的切牌阶段发动（本小局一次）")
        self.c36s2_on = s
        self.note_use(s, 36, 2, gate=False)         # op 层已经问过看破
        self.save_flags()
        return {"seat": s, "on": s}

    def c36s2_resolve(self, seat: int, tile: str) -> dict | None:
        """打出一张牌：开启【故意】时，看别家能不能「这张 + 手牌」= 4 面子 + 1 雀头。

        · 只看牌型：不判役、不判振听、不看其他技能
        · 多家都成 → 按「下家 → 对家 → 上家」取第一个
        · 中奖就立刻结算：我付他 1000 点（不需要对方同意）
        """
        s = int(seat)
        if int(self.c36s2_on) != s:
            return None
        self.c36s2_on = -1
        self.save_flags()
        t0 = str(tile or "")
        if not t0:
            return None
        for k in (1, 2, 3):
            t = (s + k) % 4
            c = list(self.hand_counts(t))
            c[index_of(t0)] += 1
            if not agari.is_winning(c, self.melds(t)):
                continue
            if agari.is_chiitoitsu(c) or agari.is_kokushi(c):
                continue                      # 只认 4 面子 + 1 雀头
            return self.c36s2_pay(s, t, t0)
        return None

    def c36s2_pay(self, me: int, winner: int, tile: str) -> dict:
        """固定 1000 点：不走番数链（否则 pays 会被按 0 番重算），收付链照常。"""
        pays = {"total": 1000, "each": 0, "from_dealer": 0, "from_other": 1000,
                "ron": 1000}
        res = {"yaku": [{"name": "故意（支付 1000 点）", "han": 0}],
               "han": 0, "fu": 0, "pays": pays, "c36s2": True,
               "fu_items": [], "_tile": str(tile), "_tsumo": False}
        self._finish(int(winner), int(me), "ron", res)
        return self._event("c36_pay", {"seat": int(me), "to": int(winner),
                                       "tile": str(tile), "points": 1000})

    # ── Card37 S1【岭上开花】───────────────────────────────────────────
    def c37s1_owns(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 37, strict=True)

    def c37s1_kans(self, seat: int) -> list[tuple[str, str]]:
        """能开的杠：暗杠优先，其次加杠。"""
        s = int(seat)
        hand = self.hand(s)
        out: list[tuple[str, str]] = [("ankan", k) for k in calls.ankan_options(hand)
                                      if self.ankan_allowed(s, k)]
        out += [("kakan", k) for k in calls.kakan_options(hand, self.melds(s))
                if not self.is_riichi(s)]
        return out

    def _c37s1_claim_tiles(self, seat: int) -> list[str] | None:
        """鸣牌窗口里「这张打出来的牌我能明杠」→ 手里那 3 张；否则 None。"""
        s = int(seat)
        p = self.pending or {}
        if self.phase != "claim" or not p:
            return None
        if s not in (p.get("options") or {}) or s in (p.get("answers") or {}):
            return None
        opt = next((o for o in (p["options"][s] or [])
                    if str(o.get("action", "")) == "minkan"), None)
        if opt is None:
            return None
        ch = list(opt.get("choices") or [])
        return [str(t) for t in ch[0]] if ch else None

    def c37s1_can(self, seat: int) -> bool:
        s = int(seat)
        if self.skill_used(s, 37, 1):
            return False
        if self.c34_muted(s):
            return False
        if not self.c37s1_owns(s):
            return False
        if not bool(self._c34s2_waits(s)):          # 听牌状态
            return False
        # ① 鸣牌窗口里：这张牌正好能【明杠】也能发动
        #    （用户 2026-10-28 报的就是这一种：已经听牌、屏幕上正有杠按钮，却点不动）
        if self._c37s1_claim_tiles(s):
            return True
        # ② 自己的摸打阶段：能【暗杠 / 加杠】才能发动
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        return bool(self.c37s1_kans(s))

    def c37s1_waits(self, seat: int) -> set[str]:
        """岭上牌放到一边后，这一手（10 张 + 副露）听什么。

        ★ 不能用 `_c34s2_waits`：它把「手切别的牌」的听牌形也算进来，
          但这里换掉的一定是**刚摸的岭上那张**，算宽了会换进一张实际和不成的牌。
        """
        hand = list(self.hand(seat))
        d = self.drawn_tile(seat)
        if d is not None and d in hand:
            hand.remove(d)
        c = counts_of(hand)
        if not agari.is_tenpai(c, self.melds(seat)):
            return set()
        return set(agari.winning_tiles(c, self.melds(seat)))

    # ── Card38 S1【重整】：接下来 3 张宝牌指示牌 ⇄ 手牌 ──────────────────
    def c38s1_owns(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 38, strict=True)

    def c38s1_slots(self) -> list[int]:
        """「接下来 3 张」宝牌指示牌的物理 seq（第 2/3/4 张，第 1 张配牌已翻）。"""
        first = self.wall_first_stack()
        out: list[int] = []
        start = int(self.dora_revealed)
        for idx in range(start, min(start + 3, int(wallmodel.DORA_STACKS))):
            no_d, _no_u = wallmodel.dora_tile_nos(first, idx)
            out.append(int(wallmodel.seq_of_tile(no_d)))
        return out

    def c38s1_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.skill_used(s, 38, 1):
            return False
        if self.c34_muted(s):
            return False
        if not self.c38s1_owns(s):
            return False
        return len(self.c38s1_slots()) == 3          # 还得有 3 张没翻的

    def c38s1_view(self, seat: int) -> dict:
        s = int(seat)
        if not self.c38s1_can(s):
            return {"dora": [], "hand": [], "need": 3}
        dora = [{"i": i, "tile": str(self.db.tile_at_seq(self.round_id, sq) or "")}
                for i, sq in enumerate(self.c38s1_slots())]
        hand = [{"seq": int(r["wall_seq"]), "tile": str(r["tile"])}
                for r in self.db.my_hand(self.round_id, s)]
        return {"dora": dora, "hand": hand, "need": 3}

    def _face_of_seq(self, seq: int) -> str:
        t = self.db.tile_at_seq(self.round_id, int(seq))
        if t is not None:
            return str(t)
        row = self.db._row("SELECT tile FROM round_hands WHERE round_id=? AND wall_seq=?",
                           (self.round_id, int(seq)))
        return str(row["tile"]) if row else ""

    def _swap_faces_by(self, by: int, reason: str, sa: int, sb: int,
                       hand_seqs: set[int]) -> None:
        if int(sa) in hand_seqs:
            self.do_swap("hand_wall", int(by), reason, hand_seq=int(sa),
                         wall_seq=int(sb), force=True)
        elif int(sb) in hand_seqs:
            self.do_swap("hand_wall", int(by), reason, hand_seq=int(sb),
                         wall_seq=int(sa), force=True)
        else:
            self.do_swap("wall_wall", int(by), reason, seq_a=int(sa), seq_b=int(sb),
                         force=True)

    def c38s1_apply(self, seat: int, picks) -> dict:
        """picks = 3 项（按目标顺序）：{"kind":"dora","i":0} 或 {"kind":"hand","seq":123}。

        · 选中的 3 张依次放到第 2/3/4 张指示牌的位置
        · 被顶下来的那几张原指示牌回到手牌（手牌张数不变）
        """
        s = int(seat)
        if not self.c38s1_can(s):
            raise RuleError("「重整」只能在自己的切牌前发动（本小局一次）")
        slots = self.c38s1_slots()
        n = len(slots)
        hand_rows = {int(r["wall_seq"]): str(r["tile"])
                     for r in self.db.my_hand(self.round_id, s)}
        cur = [self._face_of_seq(sq) for sq in slots]
        want: list[str] = []
        dora_idx: set[int] = set()
        hand_pick: list[int] = []
        seen_hand: set[int] = set()
        for it in (picks or []):
            if not isinstance(it, dict):
                raise RuleError("重整：选择格式不对")
            k = str(it.get("kind", ""))
            if k == "dora":
                i = int(it.get("i", -1))
                if not (0 <= i < n) or i in dora_idx:
                    raise RuleError("重整：指示牌选重了")
                dora_idx.add(i)
                want.append(cur[i])
            elif k == "hand":
                hs = int(it.get("seq", -1))
                if hs not in hand_rows or hs in seen_hand:
                    raise RuleError("重整：这张不在你手里（或选重了）")
                seen_hand.add(hs)
                hand_pick.append(hs)
                want.append(hand_rows[hs])
            else:
                raise RuleError("重整：选择格式不对")
        if len(want) != n:
            raise RuleError("重整：要正好选 %d 张" % n)
        # 目标牌面：前 n 个给指示牌；剩下的（原来被顶下来的指示牌）按顺序回手牌
        pool = list(cur) + [hand_rows[h] for h in hand_pick]
        left = {}
        for t in pool:
            left[t] = int(left.get(t, 0)) + 1
        for t in want[:n]:
            left[t] = int(left.get(t, 0)) - 1
        rest: list[str] = []
        for t in pool:
            if int(left.get(t, 0)) > 0:
                rest.append(t)
                left[t] = int(left[t]) - 1
        seqs = list(slots) + [int(h) for h in hand_pick]
        targets = list(want[:n]) + rest[:len(hand_pick)]
        hand_set = {int(h) for h in hand_pick}
        # 按「选择排序」把牌面归位（每次交换都走 do_swap）
        cur2 = list(cur) + [hand_rows[h] for h in hand_pick]
        for i in range(len(seqs)):
            if cur2[i] == targets[i]:
                continue
            j = next((k for k in range(len(seqs))
                      if k != i and cur2[k] == targets[i]), None)
            if j is None:
                raise RuleError("重整：牌面对不上（内部错误）")
            self._swap_faces_by(s, "重整", seqs[i], seqs[j], hand_set)
            cur2[i], cur2[j] = cur2[j], cur2[i]
        self.note_use(s, 38, 1, gate=False)          # op 层已经问过看破
        self.save_flags()
        return {"dora": [str(self._face_of_seq(sq)) for sq in slots],
                "hand": [str(x) for x in rest[:len(hand_pick)]]}

    # ── Card41 S1【复制】────────────────────────────────────────────
    def c41s1_owns(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 41, strict=True)

    def c41s1_offer(self, actor: int, card: int, skill: int) -> None:
        """别人宣告技能（= 问看破那一刻）→ 给持有【复制】的人挂一个询问。

        · 配牌时机的技能不可复制（用户口径）
        · 不复制【复制】自己
        · 不阻塞对局：只是挂 8 秒的「要不要复制」
        """
        a = int(actor)
        if not (0 <= a < 4):
            return
        if (int(card), int(skill)) == (41, 1):
            return
        try:
            if skills.timing(int(card), int(skill)) == "deal":
                return
        except Exception:
            return
        hit = False
        for me in range(4):
            if me == a or not self.c41s1_owns(me) or self.c34_muted(me):
                continue
            pool = self.c41_ask.setdefault(int(me), [])
            # 同一个技能已经在池子里 → 只更新时间戳，不重复堆
            for it in pool:
                if (int(it.get("card", 0)) == int(card)
                        and int(it.get("skill", 0)) == int(skill)
                        and int(it.get("target", -1)) == int(a)):
                    it["ts"] = time.time()
                    break
            else:
                pool.append({"owner": int(me), "target": a, "card": int(card),
                             "skill": int(skill), "ts": time.time()})
            del pool[:-6]                     # 最多留 6 个
            hit = True
        if hit:
            self.save_flags()

    def c41_ask_view(self, seat: int) -> list[dict]:
        """给 state 用：我还留着哪些「可以复制的技能」（延迟复制，不过期）。"""
        s = int(seat)
        out: list[dict] = []
        for a in (self.c41_ask.get(s) or []):
            out.append({"target": int(a.get("target", -1)),
                        "card": int(a.get("card", 0)),
                        "skill": int(a.get("skill", 0)),
                        "name": skills.info(int(a.get("card", 0)),
                                            int(a.get("skill", 0))).get("name", "")})
        return out

    def c41s1_copy(self, seat: int, card: int = 0, skill: int = 0) -> dict:
        """从「可复制池」里拿一个（不指定就取最新的那个）。技能照常生效，不拦停。"""
        s = int(seat)
        pool = list(self.c41_ask.get(s) or [])
        if not pool:
            raise RuleError("现在没有可复制的技能")
        pick = None
        if int(card) > 0 and int(skill) > 0:
            for it in pool:
                if (int(it.get("card", 0)) == int(card)
                        and int(it.get("skill", 0)) == int(skill)):
                    pick = it
                    break
            if pick is None:
                raise RuleError("这个技能不在可复制列表里了")
        else:
            pick = pool[-1]
        a = {"target": int(pick.get("target", -1)),
             "card": int(pick.get("card", 0)), "skill": int(pick.get("skill", 0)),
             "name": skills.info(int(pick.get("card", 0)),
                                 int(pick.get("skill", 0))).get("name", "")}
        card, skill = int(a["card"]), int(a["skill"])
        rest = [x for x in pool if x is not pick]
        if rest:
            self.c41_ask[s] = rest
        else:
            self.c41_ask.pop(s, None)
        # 让技能的条件判定认这张卡；并清掉「已经用掉」的痕迹 → 复制来的能再用一次
        self.granted.setdefault(s, set()).add(int(card))
        self.cc_grants.add(f"{int(card)}-{int(skill)}-{s}")   # 复制品：独立配额
        self._cc_reset_skill(s, int(card), int(skill))
        lst = self.c41_copies.setdefault(s, [])
        if not any(int(x.get("card", 0)) == card and int(x.get("skill", 0)) == skill
                   for x in lst):
            lst.append({"card": card, "skill": skill, "from": int(a.get("target", -1))})
        self.note_use(s, 41, 1, once=False, gate=False)   # 无限使用
        self.save_flags()
        return {"card": card, "skill": skill, "name": str(a.get("name", "")),
                "copies": [dict(x) for x in lst]}

    def _c41s2_pay(self, winner: int, deltas: dict) -> dict:
        """局终（41S2）：复制过技能、这一局又没和牌 → 每个复制品付原作者 1000 点。

        直接并进 `deltas`（和牌 / 流局两条路都是同一份收付表），不额外写一次库。
        """
        out: dict = {}
        w = int(winner)
        for me in range(4):
            if int(me) == w:
                continue                       # 这一局我（41 持有者）和了 → 不付
            copies = self.c41_copies.get(int(me), [])
            if not copies:
                continue
            if not skills.owns_card(self.db, self, int(me), 41, strict=True):
                continue
            pay: dict = {}
            for it in copies:
                tgt = int(it.get("from", -1))
                if 0 <= tgt < 4 and tgt != int(me):
                    pay[int(tgt)] = int(pay.get(int(tgt), 0)) + 1000
            for tgt, amt in pay.items():
                deltas[int(me)] = int(deltas.get(int(me), 0)) - int(amt)
                deltas[int(tgt)] = int(deltas.get(int(tgt), 0)) + int(amt)
                out.setdefault(int(me), []).append({"to": int(tgt),
                                                    "points": int(amt)})
        return out

    # ── Card43 S1【NO MISS】─────────────────────────────────────────
    def c43s1_owns(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 43, strict=True)

    def _c43_hand_pairs(self, seat: int) -> list[list[str]]:
        """手牌里所有能成「搭子」的两张组合。"""
        hand = list(self.hand(int(seat)))
        out: list[list[str]] = []
        for i in range(len(hand)):
            for j in range(i + 1, len(hand)):
                if is_taatsu([hand[i], hand[j]]):
                    out.append([str(hand[i]), str(hand[j])])
        return out

    def c43s1_river_seqs(self, seat: int = -1) -> list[int]:
        """牌河里「能当搭子的一部分」的 seq 并集（明置、非拔北）。"""
        rows = self.db._rows(
            "SELECT seq, tile FROM round_discards WHERE round_id=? "
            "AND face_down=0 AND is_nuki=0 ORDER BY seq", (self.round_id,))
        oks: set[int] = set()
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                if is_taatsu([str(rows[i]["tile"]), str(rows[j]["tile"])]):
                    oks.add(int(rows[i]["seq"]))
                    oks.add(int(rows[j]["seq"]))
        return sorted(oks)

    def c43s1_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.skill_used(s, 43, 1):
            return False
        if self.c34_muted(s):
            return False
        if not self.c43s1_owns(s):
            return False
        if not self._c43_hand_pairs(s):
            return False
        return bool(self.c43s1_river_seqs(s))

    def c43s1_apply(self, seat: int, hand_tiles, river_seqs) -> dict:
        """手牌 2 张搭子 ⇄ 牌河 2 张搭子；换完若能成和牌形 → 直接按自摸结算。"""
        s = int(seat)
        if not self.c43s1_can(s):
            raise RuleError("「NO MISS」只能在自己的切牌前发动（本小局一次）")
        picks = [str(t) for t in (hand_tiles or [])]
        rseqs = [int(x) for x in (river_seqs or [])]
        if len(picks) != 2 or len(rseqs) != 2:
            raise RuleError("NO MISS：要选「手牌 2 张 + 牌河 2 张」")
        if not is_taatsu(picks):
            raise RuleError("NO MISS：手牌这两张不是搭子")
        rows: dict[int, dict] = {}
        for r in self.db._rows(
                "SELECT seq, tile, face_down, is_nuki FROM round_discards "
                "WHERE round_id=? AND seq IN (?,?)", (self.round_id, rseqs[0], rseqs[1])):
            rows[int(r["seq"])] = dict(r)
        if len(rows) != 2:
            raise RuleError("NO MISS：牌河里没有这两张")
        for r in rows.values():
            if int(r.get("face_down") or 0) or int(r.get("is_nuki") or 0):
                raise RuleError("NO MISS：不能选暗置牌 / 拔北")
        if not is_taatsu([rows[q]["tile"] for q in rseqs]):
            raise RuleError("NO MISS：牌河这两张不是搭子")
        # 按牌面找自己手牌的物理 seq（同牌面依次取）
        pool: dict[str, list[int]] = {}
        for r in self.db.my_hand(self.round_id, s):
            pool.setdefault(str(r["tile"]), []).append(int(r["wall_seq"]))
        hs: list[int] = []
        for t in picks:
            if not pool.get(t):
                raise RuleError("NO MISS：手牌里没有「%s」" % t)
            hs.append(int(pool[t].pop(0)))
        if len(set(hs)) != 2:
            raise RuleError("NO MISS：这两张手牌重复了")
        for i in range(2):
            self.do_swap("hand_river", s, "NO MISS",
                         hand_seq=int(hs[i]), river_seq=int(rseqs[i]))
        self.note_use(s, 43, 1, gate=False)      # op 层已经问过看破
        self.save_flags()
        # 换完就成型 → **不自动自摸**（用户口径 2026-10-28）：挂一个待办，
        # 客户端会多出「自摸」按钮，点了才结算（判定和以前一样：as_tsumo、不计边坎吊 2 符）
        if agari.is_winning(self.hand_counts(s), self.melds(s)) and not self.c34_muted(s):
            self.win_pending = {"seat": s, "card": 43, "skill": 1, "tile": str(picks[0])}
            self.save_flags()
            return {"win": True, "pending": True, "hand": picks, "river": rseqs}
        return {"win": False, "hand": picks, "river": rseqs}

    def c41s1_skip(self, seat: int) -> dict:
        """都跳过：把这一叠清空。"""
        self.c41_ask.pop(int(seat), None)
        self.save_flags()
        return {"skipped": True}

    # ── Card40 S1【透视】：三家各一个计数器（初始 1）────────────────────
    def c40s1_owns(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 40, strict=True)

    def c40s1_left(self, viewer: int, target: int) -> int:
        """对某一家还剩几次（没记录过 = 初始 1）。"""
        return int((self.c40_cnt.get(int(viewer)) or {}).get(int(target), 1))

    def c40s1_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.c34_muted(s):
            return False
        return self.c40s1_owns(s)

    def c40s1_apply(self, viewer: int, target: int) -> dict:
        """看一家手牌：**立直中免费**；非立直则消耗那一家的一次（初始 1）。"""
        s, t = int(viewer), int(target)
        if not self.c40s1_can(s):
            raise RuleError("「透视」只能在自己的切牌前发动")
        if t == s or not (0 <= t < 4):
            raise RuleError("透视：要选另外三家之一")
        free = self.is_riichi(t)
        if not free and self.c40s1_left(s, t) <= 0:
            return {"target": t, "shown": False, "free": False,
                    "why": "对这家已经没有次数了（立直中才免费）"}
        self.c40_show.setdefault(s, set()).add(t)
        if not free:
            self.c40_cnt.setdefault(s, {})[t] = 0
        self.note_use(s, 40, 1, once=False, gate=False)   # 不限次数；看破在 op 层
        self.save_flags()
        return {"target": t, "shown": True, "free": bool(free),
                "left": self.c40s1_left(s, t)}

    def c40s1_clear(self, seat: int) -> None:
        """我打出一张牌 → 这次看到的复位（计数器不回补）。"""
        if self.c40_show.pop(int(seat), None) is not None:
            self.save_flags()

    # ── Card44 S2【电报】────────────────────────────────────────────
    def c44s2_owns(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 44, strict=True)

    def c44s2_can(self, seat: int) -> bool:
        """摸牌后发动：轮到我打牌 + 手里有刚摸的那张 + 本局还没用过。"""
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None:
            return False                      # 摸牌后发动
        if self.skill_used(s, 44, 2):
            return False
        if self.c34_muted(s):
            return False
        return self.c44s2_owns(s)

    def c44s2_arm(self, seat: int) -> dict:
        """【电报】：把手牌宣言成明牌（别人视角都看得到），本局和牌按 30 符 1 番。

        · 明牌只影响显示：并进 `reveal_hands` 那条渲染链（c40_show 同款通道）。
        · 30 符 1 番在番数链里覆盖（`_settle_c44s2`），所以：
            - 满贯（28S1）预演时看到的也是 1 番 30 符 → 照样被拦；
            - 自信（番数双倍）/ 暖气（得点倍率）排在后面 → 照样吃加成；
            - 浓雾 / 看破代价这些拦截在结算之前，天然不受影响。
        """
        s = int(seat)
        if not self.c44s2_can(s):
            raise RuleError("【电报】只能在自己摸牌后、打牌前发动（本局一次）")
        self.c44s2_on.add(s)
        self.note_use(s, 44, 2, gate=False)     # op 层已经问过看破
        self.save_flags()
        return {"seat": s, "on": True,
                "public": sorted(int(x) for x in self.c44s2_on)}

    # ══════════════════════════════════════════════════════════════════
    #  拦截树（Activation）：看破 / 封堵 / 阻止 / 免疫 的统一模型
    # ══════════════════════════════════════════════════════════════════
    ACT_TIMEOUT = 18.0

    def _act_new_id(self) -> int:
        self.act_seq = int(self.act_seq) + 1
        return int(self.act_seq)

    def _act_depth(self, n: dict) -> int:
        d = 0
        cur = n
        while int(cur.get("parent", -1)) >= 0 and d < 12:
            cur = self.acts.get(str(int(cur.get("parent", -1)))) or {}
            if not cur:
                break
            d += 1
        return d

    def act_kinds(self, seat: int, node: dict) -> list[str]:
        """这个座位对「这一笔发动」能用哪几招。"""
        s = int(seat)
        if s == int(node.get("actor", -1)):
            return []                        # 自己发动的不能自己拦
        if self.c34_muted(s) or s in self.no_win:
            return []
        out: list[str] = []
        has17 = (skills.owns_card(self.db, self, s, 17, strict=True)
                 and not self.skill_used(s, 17, 2))
        kind = str(node.get("kind", "skill"))
        if kind == "skill":
            if has17:
                out.append("sight")
            if skills.owns_card(self.db, self, s, 31, strict=True):
                out.append("block")
                used = self.c31s2_used.get(s) or set()
                tmg = str(skills.timing(int(node.get("card", 0)), int(node.get("skill", 0))))
                if (int(node.get("actor", -1)) not in used
                        and tmg in ("draw", "discard")):
                    out.append("stop")
            # 免疫：我是这次的目标、次数没完、没免疫过这个技能
            card, skill = int(node.get("card", 0)), int(node.get("skill", 0))
            if (s in [int(x) for x in (node.get("targets") or [])]
                    and self.c43s2_left(s) > 0
                    and not self.c43s2_immune(s, card, skill)):
                out.append("imm")
        else:
            # 拦截本身也能被反制，但只反制一层（再深就是 看破↔封堵 无限来回问了）
            if self._act_depth(node) > 1:
                return []
            # 【看破】能看破别人的拦截；【封堵】也能拦【看破】
            # （用户 2026-10-28 口径：看破作废、原技能照常生效；钱由封堵者付；
            #   阻止 / 免疫 对拦截节点不给）
            if has17:
                out.append("sight")
            if kind == "sight" and skills.owns_card(self.db, self, s, 31, strict=True):
                out.append("block")
        return out

    def act_askers(self, node: dict) -> list[int]:
        out: list[int] = []
        for s2 in range(4):
            if int(s2) == int(node.get("actor", -1)):
                continue
            if self.c34_muted(int(s2)):
                continue
            if self.human_seats is not None and int(s2) not in self.human_seats:
                continue                     # 没人在操作（AI）：不问
            if self.act_kinds(int(s2), node):
                out.append(int(s2))
        out.sort(key=lambda x: (self._card_slot(x, 17), self._card_slot(x, 31)))
        return out

    def act_spawn(self, actor: int, card: int, skill: int, op: str = "",
                  payload: dict | None = None, kind: str = "skill",
                  parent: int = -1, post: bool = False) -> int:
        """登记一次「可被拦的发动」。返回节点 id（调用方先看 state 再决定要不要执行）。"""
        if (int(parent) < 0 and str(kind) == "skill" and not post
                and self.act_pending()):
            # 同一家、同一技能重复点 → 还是拦着（返回原来那个节点，别开新节点）
            for m in self.acts.values():
                if (m.get("state") in ("asking", "ready")
                        and int(m.get("actor", -1)) == int(actor)
                        and int(m.get("card", 0)) == int(card)
                        and int(m.get("skill", 0)) == int(skill)):
                    return int(m.get("id", -1))
            raise RuleError("有人正在决定是否看破，稍等再发动")
        nid = self._act_new_id()
        pay = dict(payload or {})
        node = {"id": int(nid), "parent": int(parent), "actor": int(actor),
                "card": int(card), "skill": int(skill), "kind": str(kind),
                "op": str(op or ""), "payload": pay,
                "targets": sorted(int(x) for x in self.c43s2_targets(str(op or ""), pay)),
                "asks": [], "state": "asking", "post": bool(post),
                "deadline": time.time() + float(self.ACT_TIMEOUT), "note": ""}
        # 这张卡已经被【看破】剔除了 → 不必再问（让 op 自己的校验去拒）
        if (("%d:%d" % (int(actor), int(card)) in self.poked)
                or ("%d:%d:%d" % (int(actor), int(card), int(skill)) in self.poked)):
            node["state"] = "voided"
            node["note"] = "poked"
        # 已经免疫这个技能的人不再受影响 → 整次作废（用户口径）
        for t in node["targets"]:
            if self.c43s2_immune(int(t), int(card), int(skill)) and int(t) != int(actor):
                node["state"] = "voided"
                node["note"] = "免疫"
        if str(kind) == "skill" and not post:
            self.act_gated.add("%d:%d:%d" % (int(actor), int(card), int(skill)))
            # 观察者：思路（36S1）看手牌 / 复制（41S1）挂可复制池（都不拦停）
            try:
                self.c36s1_touch(int(actor))
                self.c41s1_offer(int(actor), int(card), int(skill))
            except Exception:
                pass
        key0 = "%d:%d:%d" % (int(actor), int(card), int(skill))
        skip_ask = (int(card), int(skill)) in ONCE_PAIRS and key0 in self.kangpo_once
        if node["state"] == "asking" and not skip_ask:
            for s2 in self.act_askers(node):
                node["asks"].append({"seat": int(s2),
                                     "kinds": list(self.act_kinds(int(s2), node)),
                                     "answer": None})
        if node["asks"]:
            if (int(card), int(skill)) in ONCE_PAIRS:
                self.kangpo_once.add(key0)       # 配牌技能：问过就算，之后不再问
        elif node["state"] == "asking":
            node["state"] = "ready"
        self.acts[str(nid)] = node
        if not node["asks"] and node["state"] in ("applied", "voided"):
            node["_ran"] = True              # 没有询问 → 调用方当场执行/丢弃，别再被 take
        self.act_resolve()
        self._act_sync_compat()
        self.save_flags()
        return nid

    def _act_sync_compat(self) -> None:
        """老 API 兼容：把树里「最靠前的一条待答」投影成 kangpo_ask 的形状。"""
        pad = None
        for n in sorted(self.acts.values(), key=lambda x: int(x.get("id", 0))):
            if n.get("state") != "asking":
                continue
            for a in (n.get("asks") or []):
                if not a.get("answer"):
                    pad = (n, a)
                    break
            if pad:
                break
        if pad is None:
            self.kangpo_ask = None
            self.kangpo_pending = None
            return
        n, first = pad
        self.kangpo_ask = {
            "owner": int(first.get("seat", -1)),
            "target": int(n.get("actor", -1)),
            "card": int(n.get("card", 0)),
            "skill": int(n.get("skill", 0)),
            "pre": True,
            "act": int(n.get("id", -1)),
            "options": [{"seat": int(a.get("seat", -1)),
                         "kinds": list(a.get("kinds") or [])}
                        for a in (n.get("asks") or [])],
        }
        self.kangpo_pending = {"seat": int(n.get("actor", -1)),
                               "card": int(n.get("card", 0)),
                               "skill": int(n.get("skill", 0)),
                               "act": int(n.get("id", -1)),
                               "ts": time.time()}

    def act_node(self, aid) -> dict:
        return self.acts.get(str(int(aid))) or {}

    def act_ask_view(self, seat: int) -> list[dict]:
        """**我这个座位**现在要回答的询问（可能多条：拦 A 的、拦 C 封堵的…）。"""
        s = int(seat)
        out: list[dict] = []
        for n in sorted(self.acts.values(), key=lambda x: int(x.get("id", 0))):
            if n.get("state") != "asking":
                continue
            for a in (n.get("asks") or []):
                if int(a.get("seat", -1)) != s or a.get("answer"):
                    continue
                out.append({"id": int(n.get("id", -1)),
                            "parent": int(n.get("parent", -1)),
                            "kind": str(n.get("kind", "skill")),
                            "actor": int(n.get("actor", -1)),
                            "card": int(n.get("card", 0)),
                            "skill": int(n.get("skill", 0)),
                            "name": skills.info(int(n.get("card", 0)),
                                                int(n.get("skill", 0))).get("name", ""),
                            "kinds": list(a.get("kinds") or []),
                            "deadline": float(n.get("deadline", 0) or 0),
                            "post": bool(n.get("post"))})
        return out

    def act_pending(self) -> bool:
        return any(n.get("state") == "asking" for n in self.acts.values())

    def act_pending_list(self) -> list[dict]:
        return [dict(n) for n in self.acts.values() if n.get("state") == "asking"]

    def act_answer(self, seat: int, aid, kind: str) -> dict:
        """回答一条询问。kind = sight/block/stop/imm 或 pass。"""
        s = int(seat)
        k = str(kind or "pass")
        n = self.act_node(aid)
        if not n or n.get("state") != "asking":
            raise RuleError("这条询问已经结束了")
        mine = None
        for a in (n.get("asks") or []):
            if int(a.get("seat", -1)) == s and not a.get("answer"):
                mine = a
                break
        if mine is None:
            raise RuleError("现在没有要你回答的这条询问")
        if k != "pass" and k not in (mine.get("kinds") or []):
            raise RuleError("这一招在这条询问里用不了")
        mine["answer"] = {"kind": k, "ts": time.time()}
        if k != "pass":
            # 先答先落：同一个节点上别人还没答的窗口立刻作废
            for a in (n.get("asks") or []):
                if int(a.get("seat", -1)) != s and not a.get("answer"):
                    a["answer"] = {"kind": "lost", "ts": time.time()}
            # 拦截本身也是一次「发动」→ 长出一个子节点（它自己也能被看破）
            _KC = {"sight": (17, 2), "block": (31, 1), "stop": (31, 2), "imm": (43, 2)}
            _kc, _ks = _KC.get(k, (int(n.get("card", 0)), int(n.get("skill", 0))))
            self.act_spawn(s, int(_kc), int(_ks), kind=k, parent=int(n.get("id", -1)))
        self.act_resolve()
        self._act_sync_compat()
        self.save_flags()
        return {"id": int(n.get("id", -1)), "kind": k}

    def _act_pay(self, n: dict) -> None:
        """一个拦截节点真正生效时，把它的代价/记账落下去。

        ★ 身份取**父节点**（被拦的那一笔）：看破 C 的封堵 → 废的是 C 的 31 号卡，
          不是 A 的 40 号卡。
        """
        by = int(n.get("actor", -1))
        kind = str(n.get("kind", ""))
        par = self.acts.get(str(int(n.get("parent", -1)))) or {}
        tgt = int(par.get("actor", -1))          # 被拦的那一家
        card, skill = int(par.get("card", 0)), int(par.get("skill", 0))
        # 被拦的那一笔**本身就是一次拦截**（看破 / 封堵 / 阻止 / 免疫）：
        #   · 【封堵】拦它 → 只把它作废，不额外废卡 / 不禁和
        #     （用户 2026-10-28 口径：封堵拦掉看破 = 看破作废、原技能照常生效、看破者不受罚）
        #   · 【看破】拦它 → 保持老行为（废掉对方那张卡 + 禁和）
        _par_counter = str(par.get("kind", "skill")) != "skill"
        _sight_poke = kind == "block" and _par_counter
        if kind in ("sight", "block") and tgt >= 0 and not _sight_poke:
            self.poked.add("%d:%d" % (tgt, card))
            self.poked.add("%d:%d:%d" % (tgt, card, skill))
            self.no_win.add(tgt)
            # 配牌阶段被废的技能 → 他一个能用的都不剩了就关窗口
            if (self.phase == "deal_skill" and tgt in self.deal_wait
                    and not self._deal_skill_options(tgt)):
                self.deal_wait.discard(tgt)
                self.deal_used.add(tgt)
                self._maybe_close_deal()
        # 被拦的那个窗口型技能 → 把它的窗口关掉（否则这个 phase 谁都动不了）
        _pop = str(par.get("op", "") or "")
        if kind in ("sight", "block") and _pop:
            if _pop == "wind_swap":
                self.wind_swap = None
                self.phase = "discard"
            elif _pop == "c29s1_chi":
                self._c29s1_continue()
            elif _pop == "c35s1_set":
                self.c35_skip()
        if kind == "sight":
            # ★ 看破（17-2）本小局只能用一次。以前 _act_pay 只给 block/stop/imm 记账，
            #   sight 漏了 → used_skills 里没有它 → act_kinds 的 has17 永远为真，
            #   用过看破的人还会被反复询问。
            #   放行（pass）不会走到 _act_pay，所以「问了但没用」不算消耗。
            self.mark_skill_used(by, 17, 2)
        elif kind == "block":
            price = self.c31_block_price(by)
            self._c31_block_pay(by, price)
            n["price"] = int(price)
        elif kind == "stop":
            self.c31s2_used.setdefault(by, set()).add(tgt)
            # A7：本回合这个技能不许再发一次（否则花钱阻止毫无意义）
            self.c31s2_stopped["%d:%d:%d" % (int(tgt), int(card), int(skill))] = \
                self._turn_token()
        elif kind == "imm":
            left = self.c43s2_left(by)
            self.c43s2_uses[by] = max(0, left - 1)
            self.c43s2_imm.setdefault(by, set()).add("%d-%d" % (card, skill))
            n["left"] = max(0, left - 1)

    def act_resolve(self) -> None:
        """自底向上结算：asking → ready → applied/voided；拦截生效则父节点作废。"""
        for _ in range(10):
            changed = False
            # ① 所有答案都到齐 → ready
            for n in self.acts.values():
                if n.get("state") != "asking":
                    continue
                asks = n.get("asks") or []
                if all(a.get("answer") for a in asks):
                    n["state"] = "ready"
                    changed = True
            # ② 深的先判
            for n in sorted(self.acts.values(),
                            key=lambda x: self._act_depth(x), reverse=True):
                if n.get("state") != "ready":
                    continue
                kids0 = [m for m in self.acts.values()
                         if int(m.get("parent", -1)) == int(n.get("id", -1))]
                if any(m.get("state") in ("asking", "ready") for m in kids0):
                    continue                 # 子节点（对我的拦截）还没定，先别判我
                killers = [m for m in self.acts.values()
                           if int(m.get("parent", -1)) == int(n.get("id", -1))
                           and m.get("state") == "applied"
                           and str(m.get("kind")) in ("sight", "block", "stop", "imm")]
                if killers:
                    n["state"] = "voided"
                    # 后代全部作废（已经没必要再拦一个死掉的发动）
                    for m in self.acts.values():
                        if (int(m.get("parent", -1)) == int(n.get("id", -1))
                                and m.get("state") in ("asking", "ready")):
                            m["state"] = "voided"
                else:
                    n["state"] = "applied"
                    if str(n.get("kind")) in ("sight", "block", "stop", "imm") \
                            and not n.get("_paid"):
                        self._act_pay(n)
                        n["_paid"] = True
                changed = True
            if not changed:
                break

    def act_take_ready(self) -> list[dict]:
        """把「已经有结论的根节点」取出来（applied 的那些要由 api 层真正执行）。"""
        out: list[dict] = []
        for n in sorted(self.acts.values(), key=lambda x: int(x.get("id", 0))):
            if int(n.get("parent", -1)) >= 0:
                continue
            if n.get("state") not in ("applied", "voided"):
                continue
            if any(m.get("state") in ("asking", "ready") for m in self.acts.values()
                   if int(m.get("parent", -1)) == int(n.get("id", -1))):
                continue                     # 子树还没结完
            if n.get("_ran"):
                continue
            n["_ran"] = True
            out.append(dict(n))
            self._act_purge(int(n.get("id", -1)))     # 清掉这一整棵树
        if out:
            self._act_sync_compat()
            self.save_flags()
        return out

    def _act_purge(self, root_id: int) -> None:
        drop = {int(root_id)}
        for _ in range(12):
            more = {int(n.get("id", -1)) for n in self.acts.values()
                    if int(n.get("parent", -1)) in drop} - drop
            if not more:
                break
            drop |= more
        for i in drop:
            self.acts.pop(str(i), None)

    def act_timeout(self) -> bool:
        """询问超时 → 当作放行（不卡局）。返回是否动过。"""
        hit = False
        cp = self.kangpo_pending or {}
        ts0 = float(cp.get("ts", 0) or 0)
        old_compat = bool(ts0 > 0 and (time.time() - ts0) > 15.0)
        for n in self.acts.values():
            if n.get("state") != "asking":
                continue
            dl = float(n.get("deadline", 0) or 0)
            if not old_compat and (dl <= 0 or time.time() <= dl):
                continue
            for a in (n.get("asks") or []):
                if not a.get("answer"):
                    a["answer"] = {"kind": "timeout", "ts": time.time()}
            hit = True
        if hit:
            self.act_resolve()
            self._act_sync_compat()
            self.save_flags()
        return hit

    # ── Card43 S2【免疫】────────────────────────────────────────────
    C43S2_USES = 2

    def c43s2_owns(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 43, strict=True)

    def c43s2_left(self, seat: int) -> int:
        s = int(seat)
        if not self.c43s2_owns(s):
            return 0
        return int(self.c43s2_uses.get(s, int(self.C43S2_USES)))

    def c43s2_immune(self, seat: int, card: int, skill: int) -> bool:
        s = int(seat)
        if s not in self.c43s2_imm:
            return False
        return ("%d-%d" % (int(card), int(skill))) in self.c43s2_imm[s]

    # 一定波及别人、但目标算不准的 op → 按「其他三家」算（宁可多问，不漏）
    _C43_ALL_OTHERS = {
        "deal_swap", "swap", "wind_swap", "card05_swap", "card05_extra",
        "card09_swap", "card11_swap", "card11s2_swap", "haishin_swap",
        "haishin_give", "c30s1_swap", "gift_swap", "xianfu_swap",
        "youyin_take", "press", "c29s1_chi", "diaoyu_force", "c30s1_give",
        "c32s1_give", "zhalie_swap", "nongwu", "zhalie",
    }
    # op / payload 里「指向谁」的键（够覆盖目前所有指向性技能）
    # op / payload 里「指向谁」的键（够覆盖目前所有指向性技能）
    _C43_KEYS = ("target", "to", "dst", "other", "with", "seat2", "partner")
    _C43_LIST_KEYS = ("targets", "seats", "waiting", "players")

    def c43s2_targets(self, op: str, payload: dict) -> set[int]:
        """这次发动指向哪些座位（只认 payload 里明确写了座位的那些）。"""
        out: set[int] = set()
        pay = payload or {}
        for k in self._C43_KEYS:
            v = pay.get(k)
            if isinstance(v, bool):
                continue
            if isinstance(v, int) and 0 <= int(v) < 4:
                out.add(int(v))
        for k in self._C43_LIST_KEYS:
            v = pay.get(k)
            if isinstance(v, (list, tuple)):
                for x in v:
                    try:
                        if not isinstance(x, bool) and 0 <= int(x) < 4:
                            out.add(int(x))
                    except Exception:
                        pass
        # ② 牌河 seq → 这几张牌是谁打的
        seqs: list[int] = []
        for k in ("seq", "discard_seq", "called_seq"):
            v = pay.get(k)
            if isinstance(v, int) and not isinstance(v, bool):
                seqs.append(int(v))
        for k in ("seqs", "river", "river_seqs", "rivers", "discards", "tiles_seq"):
            v = pay.get(k)
            if isinstance(v, (list, tuple)):
                for x in v:
                    try:
                        if not isinstance(x, bool):
                            seqs.append(int(x))
                    except Exception:
                        pass
        if seqs:
            marks = ",".join("?" * len(seqs))
            for r in self.db._rows(
                    "SELECT seat FROM round_discards WHERE round_id=? "
                    "AND seq IN (%s)" % marks, (self.round_id, *seqs)):
                out.add(int(r["seat"]))
        # ③ 手牌实体（wall_seq）→ 这张牌在谁手里
        hs: list[int] = []
        for k in ("hand_seq", "wall_seq", "hand_wall_seq"):
            v = pay.get(k)
            if isinstance(v, int) and not isinstance(v, bool):
                hs.append(int(v))
        for k in ("hand_seqs", "wall_seqs"):
            v = pay.get(k)
            if isinstance(v, (list, tuple)):
                for x in v:
                    try:
                        if not isinstance(x, bool):
                            hs.append(int(x))
                    except Exception:
                        pass
        if hs:
            marks2 = ",".join("?" * len(hs))
            for r in self.db._rows(
                    "SELECT seat FROM round_hands WHERE round_id=? "
                    "AND wall_seq IN (%s)" % marks2, (self.round_id, *hs)):
                out.add(int(r["seat"]))
        # ④ 算不准但一定波及别人的 → 其他三家全算上
        if str(op) in self._C43_ALL_OTHERS:
            out |= {0, 1, 2, 3}
        return out

    def _kangpo_will_ask(self, actor: int, card: int, skill: int) -> bool:
        """这一笔发动会不会弹「看破/封堵/阻止」面板？"""
        try:
            if (int(card), int(skill)) == (17, 2):
                return False
            for s2 in self._kangpo_askers(int(actor)):
                if self.kangpo_kinds(int(s2), int(actor), int(card), int(skill)):
                    return True
        except Exception:
            return False
        return False

    def c43s2_gate(self, actor: int, card: int, skill: int,
                   op: str = "", payload: dict | None = None) -> str:
        """指向性技能发动前：问被指向的人要不要【免疫】。

        返回：""（放行）/ "park"（已挂起询问）/ "void"（这人免疫这个技能 → 本次作废）
        """
        pay = dict(payload or {})
        if pay.get("_imm_ok"):
            return ""                        # 已经回答过（重放）
        a = int(actor)
        tgts = {t for t in self.c43s2_targets(str(op or ""), pay) if t != a}
        if not tgts:
            return ""
        if self.c42s1_lock():
            return ""                        # 理论战期间本来就不能发动
        # 已经免疫的人在这堆目标里 → 这次发动作废
        for t in sorted(tgts):
            if self.c43s2_immune(t, int(card), int(skill)):
                return "void"
        if self.c43_ask is not None:         # 已经有一笔在等回答：不重复挂
            return ""
        askers = [t for t in sorted(tgts)
                  if self.c43s2_left(t) > 0 and self.c43s2_owns(t)
                  and not self.c34_muted(t)]
        if not askers:
            return ""
        # 这一笔本来就会去问「看破/封堵/阻止」吗？会的话就并进同一个面板（kind="imm"），
        # 不抢在前头弹自己的窗口（用户口径 2026-10-28：card31 的询问不能被打乱）
        if self._kangpo_will_ask(a, int(card), int(skill)):
            self.c43_imm_ctx = {"actor": a, "card": int(card), "skill": int(skill),
                                "targets": sorted(int(t) for t in tgts),
                                "askers": [int(t) for t in askers]}
            self.save_flags()
            return "inline"
        owner = int(askers[0])
        self.c43_ask = {"owner": owner, "actor": a, "card": int(card),
                        "skill": int(skill),
                        "name": skills.info(int(card), int(skill)).get("name", ""),
                        "targets": sorted(int(t) for t in tgts),
                        "ts": time.time()}
        self.c43_pending = {"seat": int(owner), "actor": a, "card": int(card),
                            "skill": int(skill), "op": str(op or ""),
                            "payload": pay, "ts": time.time()}
        self.save_flags()
        return "park"

    def c43s2_answer(self, seat: int, use: bool) -> dict:
        """被指向的人回答：发动免疫（这次作废 + 以后免疫）或跳过（照常发动）。"""
        s = int(seat)
        ask = self.c43_ask or {}
        if int(ask.get("owner", -1)) != s:
            raise RuleError("现在没有要你回答的【免疫】")
        pend = dict(self.c43_pending or {})
        self.c43_ask = None
        self.c43_pending = None
        self.save_flags()                    # 先落库，下面失败也别把询问留着
        key = "%d-%d" % (int(pend.get("card", 0)), int(pend.get("skill", 0)))
        if use:
            left = self.c43s2_left(s)
            if left <= 0:
                raise RuleError("【免疫】本局已经用完了")
            self.c43s2_uses[s] = left - 1
            self.c43s2_imm.setdefault(s, set()).add(key)
            self.save_flags()
            return {"used": True, "kind": "immune", "seat": s,
                    "card": int(pend.get("card", 0)), "skill": int(pend.get("skill", 0)),
                    "left": left - 1}
        return {"used": False, "kind": "skip", "pending": pend}

    def c43s2_timeout(self) -> bool:
        if self.c43_ask is None:
            return False
        ts = float((self.c43_pending or {}).get("ts", 0) or 0)
        return ts > 0 and (time.time() - ts) > 15.0

    def c43s2_auto(self) -> None:
        """超时兜底：当作跳过（照常发动），别把整局卡死。"""
        self.c43_ask = None
        self.c43_pending = None
        self.save_flags()

    # ── Card40 S2【同盟】────────────────────────────────────────────
    def c40s2_owns(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 40, strict=True)

    def c40s2_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.skill_used(s, 40, 2) or self.c40s2 is not None:
            return False
        if self.c34_muted(s) or self.c42s1_on:
            return False
        return self.c40s2_owns(s)

    def c40s2_apply(self, seat: int, target: int) -> dict:
        """【同盟】：指定一名玩家 —— 他的手牌永远显示给我，我打出的牌他能吃碰杠就自动副露。"""
        s = int(seat)
        if not self.c40s2_can(s):
            raise RuleError("【同盟】只能在自己切牌前发动（本局一次）")
        t = int(target)
        if not (0 <= t < 4) or t == s:
            raise RuleError("【同盟】：要选其他三家之一")
        self.c40s2 = {"by": s, "target": t}
        self.note_use(s, 40, 2, gate=False)
        self.save_flags()
        return {"seat": s, "target": t}

    def c40s2_view_target(self, seat: int) -> int:
        """我（作为发动者）指定的是谁；不是发动者 → -1。"""
        plan = self.c40s2 or {}
        return int(plan.get("target", -1)) if int(plan.get("by", -1)) == int(seat) else -1

    def _c40s2_try(self, by: int, discard_seq: int, tile: str) -> dict | None:
        """我打出的牌：被指定的那家如果「合法能吃 / 碰 / 杠」→ 自动副露。"""
        plan = self.c40s2 or {}
        if not plan or int(plan.get("by", -1)) != int(by):
            return None
        t = int(plan.get("target", -1))
        if t < 0 or t == int(by):
            return None
        if self.c39s1_on or self.c34_muted(t) or int(t) in self.c45s1_on:
            return None                      # 隐形 / 厄运 / 神境：不能鸣
        if self.is_riichi(t):
            return None                      # 立直之后不能吃碰（只能荣）
        # 荣和永远优先：有人能荣和就不自动副露，交给普通鸣牌窗口
        for s2 in range(4):
            if int(s2) == int(by):
                continue
            if (self._win_ok(int(s2), str(tile), tsumo=False)
                    and self._c28s1_allows(int(s2), str(tile), False)):
                return None
        acts: list[dict] = []
        hand = self.hand(t)
        if calls.can_pon(hand, tile):
            acts.append({"kind": "pon", "choices": calls.pon_options(hand, tile)})
        mine = calls.minkan_options(hand, tile)
        if mine:
            acts.append({"kind": "minkan", "choices": mine})
        if (int(t) - int(by)) % 4 == 1:      # 只有下家能吃（【加速】的远程吃不算）
            chi = calls.chi_options(hand, tile)
            if chi:
                acts.append({"kind": "chi", "choices": chi})
        if not acts:
            return None
        if len(acts) == 1 and len(acts[0]["choices"]) == 1:
            return self._c40s2_do(int(by), t, str(tile), int(discard_seq),
                                  str(acts[0]["kind"]), acts[0]["choices"][0])
        self.c40s2_offer = {"by": int(by), "target": t, "tile": str(tile),
                            "discard_seq": int(discard_seq), "acts": acts}
        self.c40s2_deadline = time.time() + 20.0
        self.phase = "c40s2"
        self.save_flags()
        return self._event("c40s2_ask", {"by": int(by), "target": t,
                                         "tile": str(tile), "acts": acts})

    def _c40s2_do(self, by: int, target: int, tile: str, discard_seq: int,
                  kind: str, tiles) -> dict:
        """真的替被指定的那家副露（他自己不做任何操作）。"""
        p = {"discard_seq": int(discard_seq), "tile": str(tile), "from": int(by),
             "options": {}, "answers": {}}
        self.c40s2_offer = None
        self.c40s2_deadline = 0.0
        ev = self._apply_claim(int(target), str(kind), list(tiles or []), p)
        self._youyin_disarm(int(target), str(kind))
        self.save_flags()
        return ev or self._event("c40s2_meld", {"by": int(by), "seat": int(target),
                                                "kind": str(kind),
                                                "tiles": list(tiles or []),
                                                "tile": str(tile)})

    def c40s2_pick(self, seat: int, kind: str, index: int) -> dict:
        """多组搭子时，由发动者挑一组（第几个 act 的第几个 choice）。"""
        off = self.c40s2_offer or {}
        if not off or int(off.get("by", -1)) != int(seat):
            raise RuleError("【同盟】：现在不是你选搭子")
        k = int(index)
        hit = None
        for a in (off.get("acts") or []):
            if str(a.get("kind")) != str(kind):
                continue
            ch = list(a.get("choices") or [])
            if 0 <= k < len(ch):
                hit = (str(a.get("kind")), ch[k])
            break
        if hit is None:
            raise RuleError("【同盟】：这组搭子不存在")
        return self._c40s2_do(int(off.get("by", -1)), int(off.get("target", -1)),
                              str(off.get("tile", "")), int(off.get("discard_seq", -1)),
                              hit[0], hit[1])

    def c40s2_timeout(self) -> bool:
        if self.phase != "c40s2" or not self.c40s2_offer:
            return False
        dl = float(self.c40s2_deadline or 0)
        return dl > 0.0 and time.time() > dl

    def c40s2_auto(self) -> dict:
        """超时兜底：按第一组搭子直接副露（不让人卡死）。"""
        off = self.c40s2_offer or {}
        acts = list(off.get("acts") or [])
        if not acts or not acts[0].get("choices"):
            self.c40s2_offer = None
            self.phase = "discard"
            self.save_flags()
            return self._event("c40s2_skip", {})
        a0 = acts[0]
        return self._c40s2_do(int(off.get("by", -1)), int(off.get("target", -1)),
                              str(off.get("tile", "")), int(off.get("discard_seq", -1)),
                              str(a0.get("kind")), a0["choices"][0])

    # ── Card42 S1【理论战】/ S2【夺目】───────────────────────────────
    def c42s1_owns(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 42, strict=True)

    def c42s1_can(self, seat: int) -> bool:
        s = int(seat)
        if self.c42s1_on:
            return False
        if self.phase != "deal_skill" or s not in self.deal_wait:
            return False
        if int(self.dealer) != s:
            return False                     # 我必须是庄家
        if self.skill_used(s, 42, 1):
            return False
        return self.c42s1_owns(s)

    def c42s1_lock(self) -> bool:
        """【理论战】生效期间：谁都不能再发动技能（看破也问不了）。"""
        return bool(self.c42s1_on)

    def _c42s1_void_deal(self) -> None:
        """已经发动过的配牌技能全部作废（清掉它们留在局上的持续状态）。"""
        for name, val in (("confident", set()), ("c25_on", set()),
                          ("c25s2_on", set()), ("c26s2_on", set()),
                          ("c28s1_on", set()), ("shenshan", set()),
                          ("oracle", {}), ("c27_s2", set()), ("gift", {}),
                          ("gift_used", set()), ("gift_asked", set()),
                          ("c40_cnt", {}), ("c40_show", {}), ("yiding", set()),
                          ("yiding_src", {}), ("c26_n", {}), ("c26_last", {}),
                          ("c26_done", {}), ("c11_win", None),
                          ("c24_armed", -1), ("future_armed", -1),
                          ("haishin_on", False), ("haishin_gate", None),
                          ("haishin_offer", None), ("haishin_step", {}),
                          ("ignite_ok", False), ("ignite_done", True),
                          ("c29s1_offer", None), ("shenshan_offer", None),
                          ("c25s2_offer", None), ("c25s2_pending", -1)):
            if hasattr(self, name):
                try:
                    setattr(self, name, val)
                except Exception:
                    pass

    def _c42s1_close_others(self, me: int) -> list[int]:
        """【理论战】生效后，其他家还没决定的配牌技能一律作废。

        bug 复现（2026-10-28 用户报）：发动后其他家还在 deal_wait 里等选技能，
        可他们的技能请求已经被理论战挡死（gate 直接回「本局谁都不能发动技能」）→
        deal_wait 永远清不掉 → `_maybe_close_deal()` 永远不关局 = 彻底卡死。
        """
        out: list[int] = []
        self.deal_flow = None                  # 风神换牌 / 宝牌运这类多步流程也没做完的
        for t in sorted(self.deal_wait):
            if int(t) == int(me):
                continue
            self.deal_wait.discard(int(t))
            self.deal_used.add(int(t))
            out.append(int(t))
        self.c25s2_pending = -1                # 「宝牌的集合」的二段询问
        self.deal_deadline = 0.0
        return out

    def c42s1_apply(self, seat: int) -> dict:
        """【理论战】：配牌时（我是庄家）发动 —— 已发动的配牌技能作废，之后谁都不能用技能。"""
        s = int(seat)
        if not self.c42s1_can(s):
            raise RuleError("【理论战】只能在配牌阶段、自己当庄家时发动")
        self._c42s1_void_deal()
        self.c42s1_on = True
        self.note_use(s, 42, 1, gate=False)
        self.deal_wait.discard(s)
        self.deal_used.add(s)
        voided = self._c42s1_close_others(s)   # 其他家还在想的配牌技能直接作废
        self._maybe_close_deal()
        self.save_flags()
        return {"seat": s, "on": True, "voided": voided,
                "pending": sorted(self.deal_wait)}

    def c42s2_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.skill_used(s, 42, 2) or int(self.c42s2_target) >= 0:
            return False
        if self.c34_muted(s):
            return False
        return self.c42s1_owns(s)

    def c42s2_arm(self, seat: int, target: int) -> dict:
        """【夺目】：指定一位玩家 —— 本局结算时把他当庄家（只影响点数）。"""
        s = int(seat)
        if not self.c42s2_can(s):
            raise RuleError("【夺目】只能在自己切牌前发动（本局一次）")
        t = int(target)
        if not (0 <= t < 4):
            raise RuleError("【夺目】：要选一个座位")
        self.c42s2_target = t
        self.note_use(s, 42, 2, gate=False)
        self.save_flags()
        return {"seat": s, "target": t}

    def _c42s2_askers(self) -> list[int]:
        """结算前要问的人：持 42、还没用过 S2、还没指定过、没被厄运静音、有人在操作。

        AI（没有窗口的座位）不问 —— 问了就等于把这一局永远挂在结算前。
        """
        if int(self.c42s2_target) >= 0:
            return []                      # 已经指定过了（手动点图标，或上一问）
        out: list[int] = []
        for s in range(4):
            if not self.c42s1_owns(int(s)):
                continue
            if self.skill_used(int(s), 42, 2) or int(s) in self.c42s2_asked:
                continue
            if self.c34_muted(int(s)):
                continue
            if self.human_seats is not None and int(s) not in self.human_seats:
                continue                   # AI：不问
            out.append(int(s))
        return out

    def _c42s2_ask_of(self, seat: int) -> dict | None:
        """这一家现在有没有「结算前指定庄家」的询问要答。"""
        pend = self.c42s2_settle or {}
        if not pend:
            return None
        waiting = [int(x) for x in (pend.get("waiting") or [])]
        if int(seat) not in waiting:
            return None
        return {"winner": int(pend.get("winner", -1)),
                "loser": (-1 if pend.get("loser") is None else int(pend.get("loser"))),
                "result": str(pend.get("result", "")),
                "dealer": int(self.dealer),
                "deadline": float(pend.get("ts", 0) or 0) + 15.0}

    def c42s2_answer(self, seat: int, target: int = -1) -> dict:
        """结算前的回答：target >= 0 → 就按他当庄家算点数；-1 = 按真庄家结算（跳过）。"""
        s = int(seat)
        pend = self.c42s2_settle or {}
        waiting = [int(x) for x in (pend.get("waiting") or [])]
        if not pend or s not in waiting:
            raise RuleError("现在没有要你指定庄家的结算")
        self.c42s2_asked.add(s)
        t = int(target)
        if t in range(4):
            self.c42s2_target = t
            # 结算这一刻来不及再问看破（用户口径：这里只决定点数怎么算）
            self.note_use(s, 42, 2, gate=False)
        rest = [x for x in waiting if x != s]
        res = dict(pend.get("res") or {})
        if rest:
            # 还有别人要问 → 继续挂着（换了名单）
            pend = dict(pend)
            pend["waiting"] = rest
            self.c42s2_settle = pend
            self.save_flags()
            return {"seat": s, "target": t if t in range(4) else -1}
        self.c42s2_settle = None
        self.phase = str(pend.get("phase") or "discard")
        self.save_flags()
        self._finish(int(pend.get("winner", 0)),
                     pend.get("loser") if pend.get("loser") is not None else None,
                     str(pend.get("result", "tsumo")), res)
        return {"seat": s, "target": t if t in range(4) else -1}

    def c42s2_timeout(self) -> bool:
        """【夺目】结算前那一问**不自动选**（用户口径 2026-10-28）。

        以前 15 秒不答就按真庄家结算，等于替玩家做了决定；现在必须玩家自己点
        （面板上有「取消」和「跳过」）。这里保留函数只为兼容调用点，永远返回 False。
        """
        return False

    def c42s2_dealer(self) -> int:
        """算点数时用的庄家：夺目指定了就用他，否则就是真庄家。"""
        t = int(self.c42s2_target)
        return t if t in range(4) else int(self.dealer)

    # ── Card39 S1【隐形】/ S2【无视】────────────────────────────────
    def c39s1_owns(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 39, strict=True)

    def c39s1_can(self, seat: int) -> bool:
        s = int(seat)
        if self.c39s1_on:
            return False
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.skill_used(s, 39, 1):
            return False
        if self.c34_muted(s):
            return False
        if self.drawn_tile(s) is None:
            return False                     # 摸牌之后、打牌之前
        if self.my_discard_count(s) < 7:
            return False                     # 自己牌河要满 7 张
        return self.c39s1_owns(s)

    def c39s1_apply(self, seat: int) -> dict:
        """【隐形】：这一局打出去的牌谁都不能吃碰杠荣，也不造成振听。"""
        s = int(seat)
        if not self.c39s1_can(s):
            raise RuleError("【隐形】只能在自己摸牌后、打牌前发动（自己牌河要满 7 张）")
        self.c39s1_on = True
        self.note_use(s, 39, 1, gate=False)
        self.save_flags()
        return {"seat": s, "on": True}

    def c39s2_fake(self, seat: int) -> bool:
        """【无视】（39S2）：门前清时**当作立直**（不改 is_riichi / 不锁手牌 / 不禁手切）。

        只有「和牌结算」和「听牌报告的里宝」认它：立直 1 番 + 里宝牌。
        """
        s = int(seat)
        if not (0 <= s < 4):
            return False
        if self.is_riichi(s):
            return False                     # 真立直走正常那条
        if self.melds(s):
            return False                     # 要门前清
        if s in self.no_win or self.c34_muted(s):
            return False
        return skills.owns_card(self.db, self, s, 39, strict=True)

    # ── Card46 S1【恶听】────────────────────────────────────────────
    def c46s1_owns(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 46, strict=True)

    def _c46_hidden_counts(self, seat: int) -> dict[str, int]:
        """「看不见的牌」每种还剩几张：他家手牌 + 牌河暗置牌 + 没摸的牌山。

        ★ 用户口径 2026-10-28：**王牌也算**（`round_wall` 里 `dealt_to IS NULL` 全算，
          不像活牌山那样再卡 `draw_no IS NOT NULL`）。
        """
        s = int(seat)
        cnt: dict[str, int] = {}

        def add(tile) -> None:
            k = kind_of(str(tile))
            cnt[k] = int(cnt.get(k, 0)) + 1

        for o in range(4):
            if int(o) == s:
                continue
            for t in self.hand(int(o)):
                add(t)
        for r in self.db._rows(
                "SELECT tile FROM round_discards WHERE round_id=? "
                "AND COALESCE(face_down,0)=1", (self.round_id,)):
            add(r["tile"])
        for r in self.db._rows(
                "SELECT tile FROM round_wall WHERE round_id=? AND dealt_to IS NULL",
                (self.round_id,)):
            add(r["tile"])
        return cnt

    def _c46_hidden_kinds(self, seat: int) -> set[str]:
        """（兼容老接口）看不见的牌有哪些牌种。"""
        return set(self._c46_hidden_counts(int(seat)).keys())



    def c46s1_waits(self, seat: int, discard: str) -> list[str]:
        """打出 discard 之后听哪些牌（牌种，去重）。"""
        s = int(seat)
        hand = [str(t) for t in self.hand(s)]
        if str(discard) not in hand:
            return []
        rest = list(hand)
        rest.remove(str(discard))
        try:
            rep = tenpai.tenpai_report(rest, self.melds(s), self.tenpai_base(s))
        except Exception:
            return []
        return [kind_of(str(w)) for w in (rep.get("waits") or [])]

    def c46s1_only(self, seat: int, discard: str) -> str:
        """打出 discard 之后，「在他家手牌 / 暗置牌 / 没摸的牌山里一共只剩 1 张」的那张待牌。

        恶听的条件就是**正好 1 张**（用户口径 2026-10-28）：那张就是铳张。
        没有 / 剩 2 张以上 → 返回 ""。
        """
        s = int(seat)
        waits = self.c46s1_waits(s, str(discard))
        if not waits:
            return ""
        pool = self._c46_hidden_counts(s)
        if sum(int(pool.get(w, 0)) for w in waits) != 1:
            return ""                          # 不是「仅剩 1 张」
        hit = [w for w in waits if int(pool.get(w, 0)) == 1]
        return str(hit[0]) if len(hit) == 1 else ""

    def c46s1_tiles(self, seat: int) -> list[str]:
        """「切出去能听牌」+ 待牌在隐藏区**一共只剩 1 张**（用户口径 2026-10-28）。"""
        s = int(seat)
        if not self.c46s1_owns(s):
            return []
        out: list[str] = []
        for d in self._tenpai_discards(s):
            if self.c46s1_only(s, d):
                out.append(str(d))
        return out



    def c46s1_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.skill_used(s, 46, 1):
            return False                     # 本小局一次
        if self.is_riichi(s) or s in self.no_win or self.c34_muted(s):
            return False
        if self.c45s2_locked(s):
            return False
        if not self.c46s1_owns(s):
            return False
        return bool(self.c46s1_tiles(s))

    def c46s1_apply(self, seat: int, tile: str) -> dict:
        """【恶听】：打出一张「切出去能听牌」的手牌 → 直接按【一定和牌】结算。

        一定和牌的规则（和 15S2/21S2/国标 同一条链 `_yiding_settle`）：
          **铳张 = 「在他家手牌 / 暗置牌 / 没摸的牌山（含王牌）里一共只剩 1 张」的那张待牌**
          （用户口径 2026-10-28：结算点数就按这张算）；
            那张在别人手里 → 他出铳；
            在牌山 / 暗置牌里 → 按自摸结算（和到的也是这张）。
        """
        s = int(seat)
        t = str(tile or "")
        if not self.c46s1_can(s):
            raise RuleError("【恶听】只能在自己切牌前发动（切出去要能听牌、待牌还得在场上）")
        if t not in self.c46s1_tiles(s):
            raise RuleError("这张切出去不听牌（或者听的那几张不是「仅剩 1 张」）")
        only = self.c46s1_only(s, t)
        if not only:
            raise RuleError("【恶听】：待牌在场上得正好剩 1 张")
        row = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY wall_seq LIMIT 1", (self.round_id, s, t))
        if row is None:
            raise RuleError(f"手里没有 {t}")
        self.pending_kuikae = None
        self.db.discard(self.round_id, s, wall_seq=int(row["wall_seq"]),
                        riichi_tile=0, face_down=False)
        self.note_use(s, 46, 1, gate=False)     # op 层已经问过看破
        self.save_flags()
        # **不要自动自摸**（用户口径 2026-10-28）：挂待办 → 客户端弹「自摸」，点了才结算。
        # 例外：这两条本来就该「直接作废」，等按钮没意义 → 立刻走作废链路。
        if self.c33s1_blocked(s, None, True) or self.nongwu_blocks(s):
            return self._yiding_settle(s, want_tile=only)
        self.win_pending = {"seat": s, "card": 46, "skill": 1, "tile": only}
        self.save_flags()
        return self._event("c46_pending", {"seat": s, "tile": only,
                                           "card": 46, "skill": 1, "pending": True})



    # ── Card45 S2【替身】────────────────────────────────────────────
    def c45s2_owns(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 45, strict=True)

    def c45s2_locked(self, seat: int) -> bool:
        """这一回合是不是「被替身接管」的那一家（技能全部不许发）。"""
        return int(self.c45s2_wait) >= 0 and int(self.c45s2_wait) == int(seat)

    def c45s2_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.skill_used(s, 45, 2):
            return False
        if self.c45s2 is not None or int(self.c45s2_wait) >= 0:
            return False                     # 已经挂着一个替身
        if self.c34_muted(s):
            return False
        return self.c45s2_owns(s)

    def c45s2_apply(self, seat: int, first: int, second: int) -> dict:
        """切牌时发动：指定 第一位（被接管切牌）/ 第二位（指定切哪张，可选自己）。"""
        s = int(seat)
        if not self.c45s2_can(s):
            raise RuleError("【替身】只能在自己的切牌前发动（本小局一次）")
        a, b = int(first), int(second)
        if not (0 <= a < 4 and 0 <= b < 4):
            raise RuleError("【替身】：要选两个座位")
        if a == b:
            raise RuleError("【替身】：两位玩家不能是同一个人")
        if a == s:
            raise RuleError("【替身】：第一位要选其他玩家（自己的切牌不用别人管）")
        self.c45s2 = {"by": s, "first": a, "second": b}
        self.note_use(s, 45, 2, gate=False)
        self.save_flags()
        return {"by": s, "first": a, "second": b}

    def _c45s2_must_tile(self, seat: int) -> str:
        """这一手是不是「只能摸切」（立直 / 命中 / 厄运 / 神境 / 换牌后）→ 返回那张牌。"""
        s = int(seat)
        d = self.drawn_tile(s)
        if d is None:
            return ""
        if (self.is_riichi(s) or int(s) in self.c27_s2 or self.c34_muted(s)
                or int(s) in self.c45s1_on or int(s) in self.must_tsumogiri):
            return str(d)
        return ""

    def _c45s2_clear(self) -> None:
        self.c45s2 = None
        self.c45s2_wait = -1
        self.c45s2_deadline = 0.0

    def _c45s2_try(self, seat: int) -> dict | None:
        """这位摸完牌了：如果他正好是「第一位」→ 把这一手交出去。"""
        s = int(seat)
        plan = self.c45s2 or {}
        if int(plan.get("first", -1)) != s:
            return None
        if self.phase != "discard":
            return None
        must = self._c45s2_must_tile(s)
        if must:
            # 只能摸切 → 不用问，直接切（信息还是给第二位看一眼）
            self._c45s2_clear()
            self.save_flags()
            return self._do_discard(s, must)
        self.c45s2_wait = s
        self.c45s2_deadline = time.time() + 20.0
        self.save_flags()
        return self._event("c45s2_wait", {"seat": s, "first": s,
                                          "second": int(plan.get("second", -1))})

    def c45s2_pick(self, seat: int, tile: str) -> dict:
        """第二位玩家点一张手牌 → 第一位自动切出这张。"""
        b = int(seat)
        a = int(self.c45s2_wait)
        plan = self.c45s2 or {}
        if a < 0 or int(plan.get("second", -1)) != b:
            raise RuleError("【替身】：现在不是你指定切牌")
        t0 = str(tile or "")
        must = self._c45s2_must_tile(a)
        if must and t0 != must:
            raise RuleError("【替身】：他这一手只能摸切「%s」" % must)
        if t0 not in [str(t) for t in self.hand(a)]:
            raise RuleError("【替身】：他手里没有这张")
        self._c45s2_clear()
        self.save_flags()
        return self._do_discard(a, t0)

    def c45s2_auto(self) -> dict:
        """兜底（超时 / 第二位是 AI）：替第一位摸切。"""
        a = int(self.c45s2_wait)
        if a < 0:
            return {}                      # 没人在等：别制造「空操作事件」让调用方空转
        d = self.drawn_tile(a)
        if d is None:
            hand = [str(t) for t in self.hand(a)]
            d = hand[-1] if hand else "1m"
        self._c45s2_clear()
        self.save_flags()
        return self._do_discard(a, str(d))

    def c45s2_timeout(self) -> bool:
        if int(self.c45s2_wait) < 0:
            return False
        dl = float(self.c45s2_deadline or 0)
        return dl > 0.0 and time.time() > dl

    def c45s2_view(self, seat: int) -> dict:
        """【替身】视图：能不能发动 / 我挂的那一份 / 现在是不是该我指定切牌。"""
        s = int(seat)
        plan = self.c45s2 or {}
        armed = None
        if plan and int(plan.get("by", -1)) == s:
            armed = {"first": int(plan.get("first", -1)),
                     "second": int(plan.get("second", -1))}
        wait = None
        if int(self.c45s2_wait) >= 0:
            a = int(self.c45s2_wait)
            b = int(plan.get("second", -1))
            mine = (b == s)
            tiles: list[str] = []
            if mine:
                must = self._c45s2_must_tile(a)
                tiles = [must] if must else sorted([str(t) for t in self.hand(a)])
            wait = {"first": a, "second": b, "by": int(plan.get("by", -1)),
                    "mine": mine, "tiles": tiles,
                    "must": bool(mine and self._c45s2_must_tile(a)),
                    "deadline": float(self.c45s2_deadline)}
        return {"can": self.c45s2_can(s), "armed": armed, "wait": wait}

    # ── Card45 S1【神境】────────────────────────────────────────────
    C45S1_CAP_DEALER = 48000              # 庄家得点上限
    C45S1_CAP_NONDEALER = 32000           # 闲家得点上限

    def c45s1_owns(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 45, strict=True)

    def c45s1_rivers(self, seat: int) -> list[int]:
        """【神境】能挑的弃牌：四家牌河里没被鸣走、不是立直宣言牌、不是拔北。"""
        out: list[int] = []
        for r in self.db._rows(
                "SELECT seq FROM round_discards WHERE round_id=? "
                "AND COALESCE(called,0)=0 AND COALESCE(is_riichi_tile,0)=0 "
                "AND COALESCE(is_nuki,0)=0 ORDER BY seq", (self.round_id,)):
            out.append(int(r["seq"]))
        return out

    def c45s1_can(self, seat: int) -> bool:
        """摸牌前：自己牌河够 12 张 + 手牌整整 13 张（门清）+ 本小局还没开。"""
        s = int(seat)
        if self.round_phase == "deal" or self.phase != "draw":
            return False
        if self.turn is None or int(self.turn) != s:
            return False
        if self.live_left() < 1:
            return False
        if s in self.c45s1_on or self.skill_used(s, 45, 1):
            return False
        if self.c34_muted(s):
            return False
        if self.melds(s):
            return False                     # 有副露 → 手牌不是 13 张，凑不出「放弃的手牌填河」
        if len(self.hand(s)) != 13:
            return False
        if self.my_discard_count(s) < 12:
            return False                     # 自己牌河不到 12 张
        if not self.c45s1_rivers(s):
            return False
        return self.c45s1_owns(s)

    def c45s1_apply(self, seat: int, hand_tiles: list[str],
                    river_seqs: list[int]) -> dict:
        """【神境】手牌 + 牌河一共挑 13 张当新手牌。

        · 没被选中的手牌（= 放弃的手牌）暗置填进被拿走的牌河位置（同【染手】33S1）
        · 换完：只能摸切 / 不能立直 / 吃碰杠荣和全关（只能自摸）/ 得点有上限
        · 正好「放弃的手牌数 = 被拿走的牌河数」，所以手牌永远是 13 张
        """
        s = int(seat)
        picks = [str(t) for t in (hand_tiles or [])]
        seqs = [int(x) for x in (river_seqs or [])]
        if self.skill_used(s, 45, 1):
            last = dict(self.c45s1_last or {})      # 看破放行后重放同一个 op
            if last.get("hand") == picks and last.get("river") == seqs:
                return last
            raise RuleError("【神境】本小局已经用过了")
        if not self.c45s1_can(s):
            raise RuleError("【神境】只能在自己摸牌前发动（自己牌河要够 12 张、手牌 13 张）")
        if len(picks) + len(seqs) != 13:
            raise RuleError("【神境】：手牌 + 牌河一共要选 13 张")
        if len(set(seqs)) != len(seqs):
            raise RuleError("【神境】：牌河的牌不能重复")
        self._assert_hand_mutable(s)

        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, s))
        pool: dict[str, list[int]] = {}
        for r in rows:
            pool.setdefault(str(r["tile"]), []).append(int(r["wall_seq"]))
        kept: list[tuple[str, int]] = []
        for tile in picks:
            if not pool.get(tile):
                raise RuleError(f"【神境】手里没有 {tile}")
            kept.append((tile, pool[tile].pop(0)))
        left: list[tuple[str, int]] = []
        for tile, wss in pool.items():
            for ws in wss:
                left.append((str(tile), int(ws)))
        left.sort(key=lambda x: x[1])            # 被放弃的手牌：按牌山顺序填位
        if len(left) != len(seqs):
            raise RuleError("【神境】：放弃的手牌要正好填满被拿走的牌河位置")

        allowed = set(self.c45s1_rivers(s))
        river: dict[int, dict] = {}
        for r in self.db._rows(
                "SELECT seq, seat, wall_seq, tile FROM round_discards WHERE round_id=?",
                (self.round_id,)):
            river[int(r["seq"])] = r
        river_rows: list[dict] = []
        for seq in seqs:
            row = river.get(int(seq))
            if row is None:
                raise RuleError("这张牌不在牌河里")
            if int(seq) not in allowed:
                raise RuleError("这张不能拿（被鸣走的 / 立直宣言牌）")
            river_rows.append(row)

        slot0 = (self.db._one(
            "SELECT COALESCE(MAX(slot), -1) + 1 FROM round_hands WHERE round_id=? AND seat=?",
            (self.round_id, s)) or 0)
        with self.db.tx():
            # ① 放弃的手牌 → 暗置填进被拿走的牌河位置
            for (tile, hseq), row in zip(left, river_rows):
                self.db.conn.execute(
                    "DELETE FROM round_hands WHERE round_id=? AND wall_seq=?",
                    (self.round_id, int(hseq)))
                self.db.conn.execute(
                    "UPDATE round_discards SET wall_seq=?, tile=?, face_down=1, "
                    "is_tsumogiri=0 WHERE round_id=? AND seq=?",
                    (int(hseq), str(tile), self.round_id, int(row["seq"])))
            # ② 牌河拿走的那些 → 新手牌
            for i, row in enumerate(river_rows):
                self.db.conn.execute(
                    "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
                    "VALUES(?,?,?,?,?,0)",
                    (self.round_id, s, int(row["wall_seq"]), str(row["tile"]),
                     int(slot0) + i))
        got = [str(r["tile"]) for r in river_rows]
        self.c45s1_on.add(s)
        self.must_tsumogiri.add(s)               # 不能手切
        self.c45s1_last = {"hand": picks, "river": seqs, "got": got}
        self.note_use(s, 45, 1, gate=False)      # op 层已经问过看破
        self.save_flags()
        return {"hand": picks, "river": seqs, "got": got}

    def _c45s1_cap(self, winner: int, deltas: dict) -> int | None:
        """【神境】得点上限：闲家 32000 / 庄家 48000。

        收付链**最后**一道：×2 ×3（逆袭 / 岭上开花）都算完再压。
        按比例缩付点（向下取到百位），赢家拿剩下的 → 保持零和。
        """
        w = int(winner)
        if w not in self.c45s1_on:
            return None
        cap = int(self.C45S1_CAP_DEALER if w == int(self.dealer)
                  else self.C45S1_CAP_NONDEALER)
        total = int(deltas.get(w, 0))
        if total <= cap:
            return None
        payers = [x for x in range(4) if x != w and int(deltas.get(x, 0)) < 0]
        if not payers:
            return None
        scale = float(cap) / float(total)
        for x in payers:
            v = -int(deltas[x])
            deltas[x] = -((int(v * scale)) // 100 * 100)
        deltas[w] = -sum(int(deltas[x]) for x in payers)
        return cap

    C38S2_LINE = 35000                    # 逆袭：自己点数低于这个数 → 得点 ×2

    def c38s2_on(self, seat: int) -> bool:
        """逆袭（38S2）：持有 38 号卡，且**结算前**自己的点数 < 35000。"""
        s = int(seat)
        if not skills.owns_card(self.db, self, s, 38, strict=True):
            return False
        return int(self.scores().get(s, 35000)) < int(self.C38S2_LINE)

    def c37s2_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None:
            return False                      # 摸牌后发动
        if self.skill_used(s, 37, 2):
            return False
        if self.c34_muted(s):
            return False
        return self.c37s1_owns(s)

    def c37s2_apply(self, seat: int, kind: str) -> dict:
        """选一种牌：下家 → 对家 → 上家 手里这种牌，按顺位与牌山第 4/8/12/16 张**对调牌面**。

        · 「所有种类牌」都能选（不看自己手牌）
        · 手牌侧顺位 = 下家全部这种牌 → 对家 → 上家（每家按手牌顺序）
        · 牌山侧 = 接下来要摸的第 4、8、12、16 张（按顺位一一配对，不是每家固定一个位）
        · 某一侧不够就以少的为准（最多 4 组）
        """
        s = int(seat)
        if not self.c37s2_can(s):
            raise RuleError("「强运」只能在自己摸完牌之后发动（本小局一次）")
        k = kind_of(str(kind or ""))
        if k not in TILE_KINDS:
            raise RuleError("不认识的牌种：%s" % str(kind))
        seqs = self._upcoming_wall_seqs(16)
        picks = [int(seqs[i]) for i in (3, 7, 11, 15) if i < len(seqs)]
        if not picks:
            raise RuleError("牌山剩下的牌不够（数不到第 4 张）")
        hand_seqs: list[tuple[int, int, str]] = []          # (seat, wall_seq, tile)
        for step in (1, 2, 3):
            t = (s + step) % 4
            for r in self.db.my_hand(self.round_id, t):
                if kind_of(str(r["tile"])) == k:
                    hand_seqs.append((int(t), int(r["wall_seq"]), str(r["tile"])))
        if not hand_seqs:
            raise RuleError("另外三家手里都没有「%s」" % str(kind))
        log: list[dict] = []
        for i, (owner, hs, _tile) in enumerate(hand_seqs[:len(picks)]):
            ws = int(picks[i])
            got = self.do_swap("hand_wall", s, "强运",
                               hand_seq=int(hs), wall_seq=ws, force=True)
            log.append({"seat": int(owner), "hand_seq": int(hs), "wall_seq": ws,
                        "got": str(got.get("got", ""))})
        self.note_use(s, 37, 2, gate=False)     # op 层已经问过看破
        self.save_flags()
        return {"kind": str(kind), "count": len(log), "log": log,
                "tiles": [x["got"] for x in log]}

    def c37s1_arm(self, seat: int) -> dict:
        """点技能 = 自动开杠 + 摸岭上 + 换成牌山里的和牌张，然后等玩家点『自摸』。

        · 岭上摸到的那张本身就让我和 → 不换牌，直接给自摸按钮
        · 牌山里没有我的和牌张 → 技能不成立（**不消耗**），杠已经开了，正常打牌
        · **鸣牌窗口里（别人打出的牌正好能明杠）也能点**：
          先照常答这一手明杠，窗口结算时真的杠出来，再由 _apply_claim 接着走下面这段
          （荣和优先由窗口结算保证；别人和了 → 这一手不成立、技能不消耗）
        """
        s = int(seat)
        if not self.c37s1_can(s):
            raise RuleError("「岭上开花」要「听牌 + 能开杠 / 加杠」才能发动")
        mtiles = self._c37s1_claim_tiles(s)
        if mtiles:
            self.c37s1_auto = s
            self._c37_auto_result = {}
            ev = self._ask(s, "minkan", mtiles)    # 记下我这一手（全员答完才真开杠）
            self.save_flags()
            res = dict(self._c37_auto_result or {})
            self._c37_auto_result = {}
            out = {"ok": True, "kind": "minkan", "armed": True,
                   "tile": str(mtiles[-1] if mtiles else ""),
                   "ev": ev if isinstance(ev, dict) else None}
            out.update(res)
            return out
        kind, tile = self.c37s1_kans(s)[0]
        ev = self._kan(s, kind, tile)              # 开杠 + 翻宝牌 + 摸岭上（phase=discard）
        if self.phase == "ended" or self.round_phase == "end":
            return {"ok": False, "kan": ev, "ready": False,
                    "why": "开杠之后本局结束了（四杠散了 / 王牌摸完）"}
        out = self._c37s1_after_kan(s)
        out["kan"] = ev
        out["kind"] = kind
        return out

    def _c37s1_after_kan(self, s: int) -> dict:
        """杠已经开出来、岭上牌也摸到手 → 判自摸 / 从牌山换一张和牌张。

        暗杠 / 加杠（c37s1_arm）和 鸣牌窗口里的明杠（_apply_claim）共用这一段。
        """
        s = int(s)
        if self.phase == "ended" or self.round_phase == "end":
            return {"ok": False, "ready": False,
                    "why": "开杠之后本局结束了（四杠散了 / 王牌摸完）"}
        drawn = self.drawn_tile(s) or ""
        if drawn and self._judge_win(s, drawn, tsumo=True) is not None:
            self.c37s1_ready = s                   # 岭上牌自己就能和
            self.note_use(s, 37, 1, gate=False)    # op 层已经问过看破
            self.save_flags()
            return {"ok": True, "ready": True, "swapped": "", "tile": drawn}
        waits = self.c37s1_waits(s)
        hit = self.wall_find(waits) if waits else None
        if hit is None:
            # 用户口径 2026-10-28：杠**照开**、杠完正常摸打；技能照样消耗
            self.note_use(s, 37, 1, gate=False)
            self.save_flags()
            return {"ok": True, "ready": False, "swapped": "",
                    "why": "牌山里没有你的和牌张：杠已经开了，正常打牌（技能已消耗）"}
        hs = self.db._one(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND is_drawn=1",
            (self.round_id, s))
        if hs is None:
            self.note_use(s, 37, 1, gate=False)
            self.save_flags()
            return {"ok": True, "ready": False, "swapped": "",
                    "why": "找不到刚摸到的岭上牌（杠已经开了，技能已消耗）"}
        # 岭上那张 ⇄ 牌山里的和牌张（立直家也可能在杠，force 跳过立直锁）
        self.do_swap("hand_wall", s, "岭上开花",
                     hand_seq=int(hs), wall_seq=int(hit[0]), force=True)
        self.c37s1_ready = s
        self.note_use(s, 37, 1, gate=False)
        self.save_flags()
        return {"ok": True, "ready": True,
                "swapped": str(hit[1]), "tile": str(hit[1])}

    def c35s1_owns(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 35, strict=True)

    def c35_start(self, seat: int, reason: str = "副露") -> bool:
        """刚副露完（吃 / 碰 / 明杠 / 加杠）→ 自动进入「流势」排序窗口。

        服务端只**挂一个待办**（`c35_pending`），真正的界面由客户端按
        `state.c35.can` 自动弹；不打牌就一直等，超时/直接打牌 = 放弃这次调整。
        """
        s = int(seat)
        if not self.c35s1_owns(s):
            return False
        if self.c34_muted(s):
            return False                      # 【厄运】：三巡内技能无效
        if int(self.live_left()) < 1:
            return False
        self.c35_pending = s
        self.c35_mark = int(self.c35_mark) + 1
        self.c35_deadline = time.time() + float(self.C35_TIMEOUT)
        self.save_flags()
        return True

    def c35_can(self, seat: int) -> bool:
        s = int(seat)
        if int(self.c35_pending) != s:
            return False
        if self.c34_muted(s):
            return False                      # 【厄运】：静默期内技能无效
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.round_phase == "deal" or self.phase == "ended":
            return False
        return int(self.live_left()) >= 1

    def c35_count(self) -> int:
        """这次要排几张 = 4（活牌不够就按剩下的）。"""
        return max(1, min(int(self.C35_N), int(self.live_left())))

    def c35_view(self, seat: int) -> list[str]:
        if not self.c35_can(int(seat)):
            return []
        return self._c26_tiles(self.c35_count())

    def c35s1_set(self, seat: int, order: list[int]) -> dict:
        """按玩家排的顺序改写接下来 4 张。order[i] = 第 i+1 张取原来第几张。"""
        s = int(seat)
        if not self.c35_can(s):
            raise RuleError("「流势」现在不用排牌山")
        k = self.c35_count()
        seqs = self._c26_seqs(k)
        if len(seqs) != k:
            raise RuleError("「流势」：牌山剩下的牌不够")
        want = [int(x) for x in (order or [])]
        if sorted(want) != list(range(k)):
            raise RuleError("「流势」：要把这 %d 张都排上（每张用一次）" % k)
        tiles = self._c26_tiles(k)
        if any(t == "" for t in tiles):
            raise RuleError("「流势」：读不到牌山（这一手作废）")
        with self.db.tx():
            for i, sq in enumerate(seqs):
                self.db.conn.execute(
                    "UPDATE round_wall SET tile=? WHERE round_id=? AND seq=?",
                    (tiles[want[i]], self.round_id, int(sq)))
        self.c35_pending = -1
        self.c35_deadline = 0.0
        # 不限次数：once=False（图标不置灰）；看破在 op 层问过 → gate=False
        self.note_use(s, 35, 1, once=False, gate=False)
        self.save_flags()
        return {"seat": s, "k": k, "tiles": [tiles[i] for i in want], "order": want}

    def c35_skip(self, seat: int = -1) -> None:
        """不排了（直接打牌 / 超时 / 被看破）→ 牌山保持原样。"""
        if seat >= 0 and int(self.c35_pending) != int(seat):
            return
        self.c35_pending = -1
        self.c35_deadline = 0.0
        self.save_flags()

    def c35_timeout(self) -> bool:
        if int(self.c35_pending) < 0:
            return False
        dl = float(self.c35_deadline or 0)
        return dl > 0.0 and time.time() > dl

    # ── Card35 S2【逆势】：**别人**和牌，且场上有人副露过 → 这一局收付减半 ──
    C44S1_LINE = 16000                     # 弃子：失点达到这个数就不付

    def _c44s1_waive(self, winner: int, deltas: dict, result: str) -> list[dict]:
        """【弃子】：持有 44 号卡的人，这一笔失点 ≥16000 或 > 自己点数 → 改成 0。

        · 只处理**失点**（deltas < 0）
        · 「无需支付」= 这笔支付不存在 → 赢家那边也减掉同样金额（保持零和）
        · 判断用**结算前**的点数（`match_seats` 当前值）
        """
        out: list[dict] = []
        scores = self.scores()
        for s in range(4):
            if int(s) == int(winner):
                continue
            v = int(deltas.get(int(s), 0))
            if v >= 0:
                continue
            if not skills.owns_card(self.db, self, int(s), 44, strict=True):
                continue
            loss = -v
            mine = int(scores.get(int(s), 0))
            if loss < int(self.C44S1_LINE) and loss <= mine:
                continue
            deltas[int(s)] = 0
            deltas[int(winner)] = int(deltas.get(int(winner), 0)) - loss
            out.append({"seat": int(s), "saved": int(loss), "points": mine})
        return out

    def c35s2_owner(self) -> int:
        for s in range(4):
            if self.c35s1_owns(s):
                return int(s)
        return -1

    @staticmethod
    def _half100(v: int) -> int:
        """一半、向上取整到 100（正向金额）。"""
        v = int(v)
        return 0 if v <= 0 else ((v + 199) // 200) * 100

    def _c35s2_half(self, winner: int, deltas: dict, pays: dict | None = None) -> bool:
        """收付结算链：把这一局所有收支减半（保持零和，取整到 100）。

        pays 也要一起减 —— 客户端结算面板读的是 `pays.total`（main.gd show_hupai），
        只改 deltas 的话玩家看到「得点没减半」，但风盘分数其实减了（用户 bug 2026-10-28）。
        """
        me = self.c35s2_owner()
        if me < 0 or int(winner) == me:
            return False                      # 只对「其他玩家和牌」生效
        n = self.db._one(
            "SELECT COUNT(*) FROM round_melds WHERE round_id=? AND kind<>'ankan'",
            (self.round_id,)) or 0
        if int(n) <= 0:
            return False                      # 场上没人副露过
        w = int(winner)
        payers = [s for s in range(4) if s != w and int(deltas.get(s, 0)) != 0]
        for s in payers:
            v = int(deltas.get(s, 0))
            if v < 0:
                deltas[s] = -self._half100(-v)             # ceil(一半) 到百位
            else:
                deltas[s] = (v // 200) * 100
        deltas[w] = -sum(int(deltas.get(s, 0)) for s in payers)
        if pays is not None:
            for k in ("each", "from_dealer", "from_other", "ron"):
                if k in pays:
                    pays[k] = self._half100(int(pays[k]))
            pays["total"] = int(deltas[w])
        return True

    def c25s2_arm(self, seat: int) -> dict:
        """宝牌运结算完 → 「宝牌的集合」紧接着发动（本局开启）。"""
        s = int(seat)
        if self.phase != "deal_skill" or int(self.c25s2_pending) != s:
            raise RuleError("现在不是「宝牌的集合」的发动时机")
        if self.skill_used(s, 25, 2):
            raise RuleError("「宝牌的集合」本局已经发动过了")
        self.c25s2_on.add(s)
        self.c25s2_pending = -1
        self.note_use(s, 25, 2, gate=False)    # op 层已经问过看破
        self.deal_wait.discard(s)
        self.deal_used.add(s)
        self.save_flags()
        self._maybe_close_deal()               # 这下才离开配牌阶段
        return {"ok": True, "card": 25, "skill": 2, "c25s2_on": True,
                "pending": sorted(self.deal_wait)}

    def c25s2_swap(self, seat: int, hand_tile: str) -> dict:
        """宝牌的集合：把别人摸到的宝牌换过来，我出一张非宝牌（不能跳过）。"""
        s = int(seat)
        off = self.c25s2_offer or {}
        if int(off.get("owner", -1)) != s:
            # 这笔询问已经结束了（兜底 / 已经换过）→ 幂等返回，别让客户端卡住
            return {"skipped": True, "already": True, "got": "", "from": -1}
        drawer = int(off.get("from", -1))
        got = str(off.get("tile", ""))
        tile = str(hand_tile)
        if tile == "":
            raise RuleError("「宝牌的集合」必须选一张手牌交换（不能跳过）")
        if self._is_dora(tile):
            raise RuleError("「宝牌的集合」不能拿宝牌去换")
        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn DESC, wall_seq DESC", (self.round_id, s))
        mine = next((r for r in rows if str(r["tile"]) == tile), None)
        if mine is None:
            raise RuleError(f"手里没有 {tile}")
        theirs = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND is_drawn=1 "
            "ORDER BY wall_seq DESC LIMIT 1", (self.round_id, drawer))
        if theirs is None:
            raise RuleError("找不到对方刚摸的那张牌")
        hseq, tseq = int(mine["wall_seq"]), int(theirs["wall_seq"])
        # ★ swap_hand_hand 的口径：hand_seq_a 必须是 seat_a 自己的那张（a→seat_b、b→seat_a）
        self.do_swap("hand_hand", s, "宝牌的集合",
                     seat_a=s, hand_seq_a=hseq, seat_b=drawer, hand_seq_b=tseq)
        self.c25s2_offer = None
        self.phase = "discard"
        self.save_flags()
        return {"got": got, "gave": tile, "from": drawer}

    def c25s2_auto_swap(self, seat: int) -> dict:
        """没人操作的座位（AI）：替他拿一张非宝牌换掉，别把整桌挂住。"""
        s = int(seat)
        ks = self._dora_kinds()
        rows = self.db._rows(
            "SELECT tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, s))
        pick = next((str(r["tile"]) for r in rows
                     if not self._is_dora(str(r["tile"]), ks)), "")
        if pick == "":
            off = self.c25s2_offer or {}
            self.c25s2_offer = None
            nxt = self._advance_intercept(off)
            self.save_flags()
            return {"skipped": True, "from": int(off.get("from", -1)), "next": nxt}
        return self.c25s2_swap(s, pick)

    def _c25s2_judge_ctx(self, seat: int, ctx: dict) -> None:
        """兼容入口：现在所有技能开关都由 `_skill_judge_flags` 统一出。"""
        ctx.update(self._skill_judge_flags(int(seat)))
    def _non_dora_count(self, seat: int) -> int:
        """某家手里「不是宝牌」的张数（宝牌运：这些才能拿出去换）。"""
        ks = self._dora_kinds()
        return sum(1 for r in self.db._rows(
            "SELECT tile FROM round_hands WHERE round_id=? AND seat=?",
            (self.round_id, int(seat)))
            if not self._is_dora(str(r["tile"]), ks))

    def _flow_target_tiles(self, f: dict, target: int) -> list[dict]:
        """配牌换牌流程里「这一家有哪些牌拿来换」：风神→风牌 / 宝牌运→宝牌。"""
        if str(f.get("kind")) == "dora_luck":
            return self._doras_of(int(target))
        return self._winds_of(int(target))

    def _start_dora_luck(self, seat: int, card: int, skill: int) -> dict:
        """点「宝牌运」：依次把下家/对家/上家手里的宝牌换过来（我出等量的非宝牌）。"""
        self.deal_flow = {
            "kind": "dora_luck",
            "seat": int(seat), "card": int(card), "skill": int(skill),
            "stage": 0, "n": 0, "target": -1,
            "targets": [(int(seat) + 1) % 4, (int(seat) + 2) % 4, (int(seat) + 3) % 4],
        }
        self.note_skill(seat, card, skill)          # 全场播报 + 人物卡翻明
        self._advance_deal_flow()                   # 三家都没宝牌 → 直接收尾
        self.save_flags()
        return {"ok": True, "armed": True, "card": int(card), "skill": int(skill),
                "skill_name": skills.info(card, skill).get("name", ""),
                "kind": "dora_luck", "flow": self.deal_flow_view(seat),
                "pending": sorted(self.deal_wait)}

    def _start_deal_swap(self, seat: int, card: int, skill: int) -> dict:
        """点「风神」：排好下家/对家/上家的顺序，选中第一个有风牌的。"""
        self.deal_flow = {
            "kind": "fengshen",
            "seat": int(seat), "card": int(card), "skill": int(skill),
            "stage": 0, "n": 0, "target": -1,
            "targets": [(int(seat) + 1) % 4, (int(seat) + 2) % 4, (int(seat) + 3) % 4],
        }
        self.self_wind.add(int(seat))               # 自风：风神发动后自动生效
        self.note_skill(seat, card, skill)          # 全场播报 + 人物卡翻明
        self._advance_deal_flow()
        self.save_flags()
        return {"ok": True, "armed": True, "card": int(card), "skill": int(skill),
                "skill_name": skills.info(card, skill).get("name", ""),
                "kind": "deal_swap", "flow": self.deal_flow_view(seat),
                "pending": sorted(self.deal_wait)}

    def _start_south_wind(self, seat: int, card: int, skill: int) -> dict:
        """南场配牌：先指定两种牌，再选两张手牌，按 下家→对家→上家 强制交换。"""
        self.deal_flow = {
            "kind": "south_wind",
            "seat": int(seat), "card": int(card), "skill": int(skill),
            "stage": "kinds", "kinds": [],
            "targets": [(int(seat) + 1) % 4, (int(seat) + 2) % 4, (int(seat) + 3) % 4],
        }
        self.note_skill(seat, card, skill)
        self.save_flags()
        return {"ok": True, "armed": True, "card": int(card), "skill": int(skill),
                "skill_name": skills.info(card, skill).get("name", ""),
                "kind": "south_wind", "flow": self.deal_flow_view(seat),
                "pending": sorted(self.deal_wait)}

    def south_wind_kinds(self, seat: int, kinds: list[str]) -> dict:
        f = self.deal_flow
        if not f or str(f.get("kind")) != "south_wind" or int(f.get("seat", -1)) != int(seat):
            raise RuleError("现在不是南风的选牌阶段")
        if str(f.get("stage")) != "kinds":
            raise RuleError("已经选过牌种了")
        picks = [str(k) for k in kinds]
        if len(picks) != 2 or len(set(picks)) != 2:
            raise RuleError("要指定两种不同的牌")
        for k in picks:
            if k not in TILE_KINDS:
                raise RuleError(f"没有这种牌：{k}")
        f["kinds"] = picks
        f["stage"] = "hand"
        self.save_flags()
        return {"kinds": picks, "flow": self.deal_flow_view(seat)}

    def south_wind_swap(self, seat: int, hand_tiles: list[str]) -> dict:
        """选两张手牌，按顺序跟下家/对家/上家换「指定的两种牌」，换满两张就结束。"""
        f = self.deal_flow
        if not f or str(f.get("kind")) != "south_wind" or int(f.get("seat", -1)) != int(seat):
            raise RuleError("现在不是南风的换牌阶段")
        if str(f.get("stage")) != "hand":
            raise RuleError("还没指定牌种")
        picks = [str(t) for t in hand_tiles]
        if len(picks) != 2:
            raise RuleError("要选两张手牌")
        rows = self.db._rows(
            "SELECT wall_seq, tile, is_drawn FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, int(seat)))
        pool: dict[str, list[dict]] = {}
        for r in rows:
            pool.setdefault(str(r["tile"]), []).append(dict(r))
        mine: list[dict] = []
        for t in picks:
            if not pool.get(t):
                raise RuleError(f"手里没有 {t}")
            mine.append(pool[t].pop(0))
        random.shuffle(mine)

        had_drawn = next((int(r["wall_seq"]) for r in rows if int(r["is_drawn"] or 0)), None)
        kinds = set(str(x) for x in (f.get("kinds") or []))
        log: list[dict] = []
        incoming: list[int] = []
        before = self._hand_snapshot()          # 策略：换牌前后的手牌比对

        with self.db.tx():
            for opp in [int(x) for x in f["targets"]]:
                if not mine:
                    break
                opp_rows = self.db._rows(
                    "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
                    "ORDER BY slot", (self.round_id, opp))
                matches = [dict(r) for r in opp_rows if str(r["tile"]) in kinds]
                if not matches:
                    continue
                random.shuffle(matches)
                while mine and matches:
                    my = mine.pop()
                    their = matches.pop()
                    # 我的手牌 ⇄ 对家的指定牌（统一入口：策略计数/立直锁都在里面）
                    self._swap_hand_tiles(int(seat), int(my["wall_seq"]), opp,
                                          int(their["wall_seq"]), "南风",
                                          clear_drawn=True)
                    incoming.append(int(their["wall_seq"]))
                    log.append({"from": opp, "gave": str(my["tile"]),
                                "got": str(their["tile"])})
            # 刚摸的那张被换走了 → 换进来的牌顶上
            if had_drawn is not None and incoming:
                still = self.db._one(
                    "SELECT COUNT(*) FROM round_hands WHERE round_id=? AND seat=? "
                    "AND wall_seq=?", (self.round_id, int(seat), int(had_drawn)))
                if not still:
                    self._set_hand_drawn(int(incoming[-1]), True)

        self.card05_note_changes(before, seat, "南风")   # 策略：对手的手牌被换了
        self.deal_flow = None
        self.deal_wait.discard(int(seat))
        self.deal_used.add(int(seat))
        self.save_flags()
        self._maybe_close_deal()
        return {"swaps": log, "count": len(log)}

    def _advance_deal_flow(self) -> None:
        """跳到下一个「手里有风牌」的对手；三家都换完就收尾。"""
        f = self.deal_flow
        if not f:
            return
        while int(f["stage"]) < len(f["targets"]):
            target = int(f["targets"][int(f["stage"])])
            n = len(self._flow_target_tiles(f, target))
            if str(f.get("kind")) == "dora_luck":
                # 我手上能拿出去换的（不能是宝牌）不够 → 只换能换的那几张
                n = min(n, self._non_dora_count(int(f["seat"])))
            if n > 0:
                f["n"] = n
                f["target"] = target
                return
            f["stage"] = int(f["stage"]) + 1
        self._finish_deal_flow()

    def _finish_deal_flow(self) -> None:
        f = self.deal_flow
        self.deal_flow = None
        if f:
            s = int(f["seat"])
            if str(f.get("kind")) == "dora_luck":
                # 宝牌运：换完（或三家都没宝牌）→ 本局【宝牌运】开启。
                # 只在正常收尾时开：deal_skip_all / 超时兜底不走这里，
                # 所以「点了技能又反悔跳过」不会误开。
                self.c25_on.add(s)
                if (skills.owns_card(self.db, self, s, 25, strict=True)
                        and not self.skill_used(s, 25, 2)):
                    # 宝牌的集合：紧接着发动（还要过一次看破）→ **先不离开配牌阶段**
                    self.c25s2_pending = s
                    self.deal_deadline = time.time() + DEAL_SKILL_TIMEOUT
                    self.save_flags()
                    return
            self.deal_wait.discard(s)
            self.deal_used.add(s)
        self.save_flags()
        self._maybe_close_deal()

    # ─── Card30 S1【向听】：选两家 → 他们各给 2~3 张 → 我挑一张换 ─────
    def _c30s1_arm(self, seat: int, targets: list[int]) -> dict:
        """配牌点【向听】：先选两家（东南西北），这里开始走流程。"""
        s = int(seat)
        if self.phase != "deal_skill":
            raise RuleError("向听只能在配牌阶段发动")
        if not skills.owns_card(self.db, self, s, 30, strict=True):
            raise RuleError("手里不是这一轮的卡")
        if self.skill_used(s, 30, 1):
            raise RuleError("向听本小局已经发动过了")
        ts = [int(t) for t in (targets or [])]
        ts = [t for t in ts if t in range(4) and t != s]
        if len(set(ts)) != 2:
            raise RuleError("要选两个不同的对手")
        # 按用户口径：下家 → 对家 → 上家 依次询问
        ts.sort(key=lambda t: (t - s) % 4)
        self.deal_flow = {"kind": "xiangting", "seat": s, "card": 30, "skill": 1,
                          "targets": ts, "stage": 0, "sub": "give",
                          "target": ts[0], "picked": []}
        self.note_use(s, 30, 1, once=False, gate=False)   # op 层已经问过看破
        self.deal_deadline = 0.0                          # 向听不做超时兜底（用户口径）
        self.save_flags()
        return {"armed": True, "card": 30, "skill": 1, "targets": ts,
                "flow": self.deal_flow_view(s)}

    def c30s1_give(self, seat: int, tiles: list[str]) -> dict:
        """**被问的那家**：从自己手里选 2~3 张交出来。"""
        f = self.deal_flow
        s = int(seat)
        if not f or str(f.get("kind")) != "xiangting":
            raise RuleError("现在不是向听的选牌阶段")
        if str(f.get("sub")) != "give" or int(f.get("target", -1)) != s:
            raise RuleError("现在不该你选牌")
        pool = [str(t) for t in (tiles or [])]
        if len(pool) not in (2, 3):
            raise RuleError("要选两张或三张牌")
        hand = list(self.hand(s))
        for t in pool:
            if t not in hand:
                raise RuleError(f"手里没有 {t}")
            hand.remove(t)
        f["picked"] = pool
        f["sub"] = "swap"
        self.save_flags()
        return {"seat": s, "tiles": pool, "flow": self.deal_flow_view(int(f["seat"]))}

    def c30s1_swap(self, seat: int, hand_tile: str, pick_tile: str) -> dict:
        """**发动者**：从对方给的那几张里挑一张，跟我一张手牌互换。"""
        f = self.deal_flow
        s = int(seat)
        if not f or str(f.get("kind")) != "xiangting" or int(f.get("seat", -1)) != s:
            raise RuleError("现在不是向听的换牌阶段")
        if str(f.get("sub")) != "swap":
            raise RuleError("对方还没选牌")
        picked = [str(t) for t in (f.get("picked") or [])]
        target = int(f.get("target", -1))
        pick = str(pick_tile)
        if pick not in picked:
            raise RuleError("只能从对方给的牌里挑一张")
        mine = str(hand_tile)
        hrow = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY slot LIMIT 1", (self.round_id, s, mine))
        if hrow is None:
            raise RuleError(f"手里没有 {mine}")
        # 对方那张：按「这张牌在 picked 里是第几次出现」定位。
        # ★ 不能用 picked.index()：picked=["3m","6m"] 挑 6m 会得到 OFFSET 1，
        #   可对方手里只有一张 6m → 找不到牌（2026-10-27 现场报「对方手里找不到这张牌」）。
        #   排序口径要和 hand() 一致（ORDER BY is_drawn, wall_seq），否则 OFFSET 对不上。
        pos = picked.index(pick)
        occ = sum(1 for t in picked[:pos] if t == pick)
        trow = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY is_drawn, wall_seq LIMIT 1 OFFSET ?",
            (self.round_id, target, pick, occ))
        if trow is None:
            raise RuleError("对方手里找不到这张牌")
        # ★ 走统一入口：策略计数(+1/换牌机会) / 立直锁 / 宝牌同步 全靠它
        self.do_swap("hand_hand", s, "向听",
                     seat_a=s, hand_seq_a=int(hrow["wall_seq"]),
                     seat_b=target, hand_seq_b=int(trow["wall_seq"]))
        f["picked"] = []
        f["stage"] = int(f.get("stage", 0)) + 1
        self._c30s1_next()
        self.save_flags()
        return {"got": pick, "gave": mine, "target": target,
                "flow": self.deal_flow_view(s)}

    # ─── Card32 S1【新手运】：依次要每家一张幺九牌，我出任意一张 ───────────
    @staticmethod
    def _c32_is_orphan(tile: str) -> bool:
        """幺九牌：一/九 或者字牌。"""
        k = kind_of(str(tile))
        if k in ("dong", "nan", "xi", "bei", "bai", "fa", "zhong"):
            return True
        return tile_number(k) in (1, 9)

    def _c32_has_orphan(self, seat: int) -> bool:
        return any(self._c32_is_orphan(t) for t in self.hand(int(seat)))

    def _c32s1_arm(self, seat: int) -> dict:
        """配牌点【新手运】：下家 → 对家 → 上家 依次要牌（不用选人）。"""
        s = int(seat)
        if self.phase != "deal_skill":
            raise RuleError("新手运只能在配牌阶段发动")
        if not skills.owns_card(self.db, self, s, 32, strict=True):
            raise RuleError("手里不是这一轮的卡")
        if self.skill_used(s, 32, 1):
            raise RuleError("新手运本小局已经发动过了")
        if self.deal_flow is not None:
            raise RuleError("配牌换牌流程正在进行 —— 等它结束再发动")
        ts = [(s + 1) % 4, (s + 2) % 4, (s + 3) % 4]
        self.deal_flow = {"kind": "c32", "seat": s, "card": 32, "skill": 1,
                          "targets": ts, "stage": 0, "sub": "give",
                          "target": ts[0], "picked": [], "min": 1, "max": 1}
        self.note_use(s, 32, 1, once=False, gate=False)   # op 层已经问过拦截
        self.deal_deadline = 0.0
        self.save_flags()
        self._c32s1_next()                                # 跳过手里没有幺九的人
        return {"armed": True, "card": 32, "skill": 1, "targets": ts,
                "flow": self.deal_flow_view(s)}

    def c32s1_give(self, seat: int, tile: str) -> dict:
        """被要牌的那家：默认方式选 1 张幺九牌交出来。"""
        s = int(seat)
        f = self.deal_flow
        if not f or str(f.get("kind")) != "c32":
            raise RuleError("现在不是新手运的选牌阶段")
        if str(f.get("sub")) != "give" or int(f.get("target", -1)) != s:
            raise RuleError("现在不该你选牌")
        t = str(tile)
        if t == "":
            raise RuleError("要选一张幺九牌")
        if not self._c32_is_orphan(t):
            raise RuleError("新手运：只能交一张幺九牌（一/九或字牌）")
        if t not in self.hand(s):
            raise RuleError(f"手里没有 {t}")
        f["picked"] = [t]
        f["sub"] = "swap"
        self.save_flags()
        return {"seat": s, "tile": t, "flow": self.deal_flow_view(int(f["seat"]))}

    def c32s1_swap(self, seat: int, hand_tile: str) -> dict:
        """发动者：选自己一张任意牌，和对方交出来的那张交换。"""
        s = int(seat)
        f = self.deal_flow
        if not f or str(f.get("kind")) != "c32" or int(f.get("seat", -1)) != s:
            raise RuleError("现在不是新手运的换牌阶段")
        if str(f.get("sub")) != "swap":
            raise RuleError("对方还没选牌")
        picked = [str(x) for x in (f.get("picked") or [])]
        if not picked:
            raise RuleError("对方还没选牌")
        mine = str(hand_tile)
        if mine == "":
            raise RuleError("要选一张自己的手牌")
        hrow = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY is_drawn, wall_seq LIMIT 1", (self.round_id, s, mine))
        if hrow is None:
            raise RuleError(f"手里没有 {mine}")
        their = picked[0]
        trow = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY is_drawn, wall_seq LIMIT 1",
            (self.round_id, int(f.get("target", -1)), their))
        if trow is None:
            raise RuleError("对方手里找不到这张牌")
        target = int(f.get("target", -1))
        # 统一入口：策略计数 / 立直锁 / 宝牌同步都在里面
        self._swap_hand_tiles(s, int(hrow["wall_seq"]), target,
                              int(trow["wall_seq"]), "新手运")
        f["picked"] = []
        f["stage"] = int(f.get("stage", 0)) + 1
        self._c32s1_next()
        self.save_flags()
        return {"got": their, "gave": mine, "target": target,
                "flow": self.deal_flow_view(s)}

    def _c32s1_next(self) -> None:
        """换完一家 → 下一家；都完了 → 收尾。手里没有幺九的那家直接跳过。"""
        f = self.deal_flow
        if not f or str(f.get("kind")) != "c32":
            return
        targets = [int(t) for t in (f.get("targets") or [])]
        while int(f.get("stage", 0)) < len(targets):
            t = targets[int(f.get("stage", 0))]
            if self._c32_has_orphan(t):
                f["target"] = t
                f["sub"] = "give"
                f["picked"] = []
                self.save_flags()
                return
            f["stage"] = int(f.get("stage", 0)) + 1      # 没有幺九牌 → 跳过
        s = int(f["seat"])
        self.deal_flow = None
        self.deal_wait.discard(s)
        self.deal_used.add(s)
        self.save_flags()
        self._maybe_close_deal()

    def c32_give_target(self) -> int:
        """新手运：现在该谁交牌（没有则 -1）。"""
        f = self.deal_flow or {}
        if str(f.get("kind")) != "c32" or str(f.get("sub")) != "give":
            return -1
        t = int(f.get("target", -1))
        return t if 0 <= t < 4 else -1

    def c32s1_auto(self, seat: int) -> dict:
        """没人在操作的座位：替他交第一张幺九牌。"""
        s = int(seat)
        f = self.deal_flow or {}
        if (str(f.get("kind")) != "c32" or str(f.get("sub")) != "give"
                or int(f.get("target", -1)) != s):
            return {"skipped": True}
        tiles = [t for t in self.hand(s) if self._c32_is_orphan(t)]
        if not tiles:
            f["stage"] = int(f.get("stage", 0)) + 1
            self._c32s1_next()
            return {"skipped": True, "no_orphan": True}
        return self.c32s1_give(s, tiles[0])

    # ─── Card33 S1【染手】：3 张手牌 ⇄ 牌河里一组面子（3 张），手牌暗置补位 ───
    @staticmethod
    def _c33_suit_ok(tiles) -> bool:
        """牌型是不是「染手」：出现的**数牌花色**至多 1 种（字牌不限）。

        用户口径：只能以混一色 / 清一色 / 字一色和牌。**按牌型判，不按役种名**——
        判番对 `绿一色` / `九莲宝灯` 只给役满名（不再叠混一色/清一色），
        按名字判会把它们误拦。
        """
        suits: set[str] = set()
        for t in tiles:
            k = kind_of(str(t))
            if is_honor(k) or k.endswith("z"):
                continue                    # 字牌（正常是 bai/fa/…，兼容 1z..7z 记法）
            if len(k) < 2:
                return False
            suits.add(k[1])
            if len(suits) > 1:
                return False
        return True

    @staticmethod
    def _c33_is_meld(tiles) -> bool:
        """3 张是不是一组面子：刻子（同牌种）或顺子（同花色连号）。"""
        ks = [kind_of(str(t)) for t in (tiles or [])]
        if len(ks) != 3:
            return False
        if ks[0] == ks[1] == ks[2]:
            return True
        if any(is_honor(k) or k.endswith("z") for k in ks):
            return False                        # 字牌不能组顺子
        if len({k[1] for k in ks}) != 1:
            return False
        nums = sorted(tile_number(k) for k in ks)
        return nums[1] == nums[0] + 1 and nums[2] == nums[1] + 1

    def _c33_win_tiles(self, seat: int, tile: str | None, tsumo: bool) -> list[str]:
        """和牌那一刻的全部牌（手牌 + 副露 + 荣和那张）。"""
        tiles = list(self.hand(int(seat)))
        for m in self.melds(int(seat)):
            tiles += [str(x) for x in (m.get("tiles") or [])]
        if not tsumo and tile:
            tiles.append(str(tile))
        return tiles

    def c33s1_blocked(self, seat: int, tile: str | None, tsumo: bool) -> bool:
        """【染手】生效时，牌型不是混一色/清一色/字一色 → True（不能和）。"""
        if int(seat) not in self.c33s1_on:
            return False
        return not self._c33_suit_ok(self._c33_win_tiles(int(seat), tile, tsumo))

    def c33s1_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None:
            return False
        if s in self.c33s1_on or self.skill_used(s, 33, 1):
            return False
        if self.hand_locked(s):
            return False
        return skills.owns_card(self.db, self, s, 33, strict=True)

    def c33_river_seqs(self, seat: int) -> list[int]:
        """【染手】可选的牌河位置：其他三家、没被鸣走、不是立直宣言牌、不是暗置牌。"""
        return [int(r["seq"]) for r in self.db._rows(
            "SELECT seq FROM round_discards WHERE round_id=? AND seat<>? "
            "AND COALESCE(called,0)=0 AND COALESCE(is_riichi_tile,0)=0 "
            "AND COALESCE(face_down,0)=0 AND COALESCE(is_nuki,0)=0 ORDER BY seq",
            (self.round_id, int(seat)))]

    def c33s1_swap(self, seat: int, hand_tiles: list[str],
                   river_seqs: list[int]) -> dict:
        """把手牌 3 张暗置换进牌河，换回牌河里一组面子（3 张）。

        · 摸牌后、自己的出牌回合、本小局一次
        · 牌河那 3 张必须是**别的座位**打出的一组面子（顺子/刻子）
        · 换完**正常切牌**（不设 must_tsumogiri，和 Card02 S2 换牌不同）
        · 我的 3 张手牌暗置填进被拿走的 3 个位置：
          手牌从左到右 → 下家 → 对家 → 上家；同一家按弃牌先后
        """
        s = int(seat)
        if self.phase != "discard" or int(self.turn) != s:
            raise RuleError("现在不是你的出牌回合")
        if self.drawn_tile(s) is None:
            raise RuleError("摸牌之后才能发动")
        self._assert_hand_mutable(s)
        picks = [str(t) for t in (hand_tiles or [])]
        seqs = [int(x) for x in (river_seqs or [])]
        if self.skill_used(s, 33, 1):
            # 看破闸门放行后会重放同一个 op —— 同参数直接回上次结果
            last = dict(self.c33s1_last or {})
            if last.get("hand") == picks and last.get("river") == seqs:
                return last
            raise RuleError("【染手】本小局已经用过了")
        if len(picks) != 3:
            raise RuleError("【染手】：手牌要选 3 张")
        if len(seqs) != 3:
            raise RuleError("【染手】：牌河要选 3 张")
        if len(set(seqs)) != 3:
            raise RuleError("【染手】：牌河的 3 张不能重复")

        # 手牌：同一种牌可以选多张，按张数扣
        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, s))
        pool: dict[str, list[int]] = {}
        for r in rows:
            pool.setdefault(str(r["tile"]), []).append(int(r["wall_seq"]))
        hand_rows: list[tuple[str, int]] = []
        for tile in picks:
            if not pool.get(tile):
                raise RuleError(f"手里没有 {tile}")
            hand_rows.append((tile, pool[tile].pop(0)))
        dr = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND is_drawn=1",
            (self.round_id, s))
        drawn_seq = int(dr["wall_seq"]) if dr is not None else None

        # 牌河：必须别的座位 + 在「现在真能拿」的列表里
        allowed = set(self.c33_river_seqs(s))
        river: dict[int, dict] = {}
        for r in self.db._rows(
                "SELECT seq, seat, wall_seq, tile, called, is_riichi_tile, face_down "
                "FROM round_discards WHERE round_id=?", (self.round_id,)):
            river[int(r["seq"])] = r
        river_rows: list[dict] = []
        for seq in seqs:
            row = river.get(int(seq))
            if row is None:
                raise RuleError("这张牌不在牌河里")
            if int(row["seat"]) == s:
                raise RuleError("【染手】：只能拿其他三家的弃牌")
            if int(seq) not in allowed:
                raise RuleError("这张不能拿（被鸣走的 / 立直宣言牌 / 暗置牌）")
            river_rows.append(row)
        if not self._c33_is_meld([str(r["tile"]) for r in river_rows]):
            raise RuleError("【染手】：牌河这 3 张不是一组面子（顺子或刻子）")

        # 填位顺序：下家 → 对家 → 上家；同一家按弃牌先后
        order = {(s + 1) % 4: 0, (s + 2) % 4: 1, (s + 3) % 4: 2}
        river_rows.sort(key=lambda r: (order.get(int(r["seat"]), 9), int(r["seq"])))

        slot0 = (self.db._one(
            "SELECT COALESCE(MAX(slot), -1) + 1 FROM round_hands WHERE round_id=? AND seat=?",
            (self.round_id, s)) or 0)
        pair: dict[int, int] = {}
        with self.db.tx():
            for i, ((tile, hseq), row) in enumerate(zip(hand_rows, river_rows)):
                self.db.conn.execute(
                    "DELETE FROM round_hands WHERE round_id=? AND wall_seq=?",
                    (self.round_id, int(hseq)))
                self.db.conn.execute(
                    "UPDATE round_discards SET wall_seq=?, tile=?, face_down=1, is_tsumogiri=0 "
                    "WHERE round_id=? AND seq=?",
                    (int(hseq), str(tile), self.round_id, int(row["seq"])))
                self.db.conn.execute(
                    "INSERT INTO round_hands(round_id, seat, wall_seq, tile, slot, is_drawn) "
                    "VALUES(?,?,?,?,?,0)",
                    (self.round_id, s, int(row["wall_seq"]), str(row["tile"]),
                     int(slot0) + i))
                pair[int(hseq)] = int(row["wall_seq"])
            # 「刚摸到的那张」被换走了 → 填进那个位置的那张算刚摸到的
            #（不能留 0 张 is_drawn=1：摸切/手切判定和客户端「有没有摸牌」都靠它）
            if drawn_seq is not None and drawn_seq in pair:
                self.db.conn.execute(
                    "UPDATE round_hands SET is_drawn=1 WHERE round_id=? AND wall_seq=?",
                    (self.round_id, int(pair[drawn_seq])))

        got = [str(r["tile"]) for r in river_rows]
        self.c33s1_on.add(s)
        self.c33s1_last = {"hand": picks, "river": seqs, "got": got}
        self.note_use(s, 33, 1, gate=False)     # op 层已过看破闸门
        self.save_flags()
        return {"hand": picks, "river": seqs, "got": got}

    # ─── Card33 S2【记忆】：输入上局结算点数 → 下一张打出暗置，**本小局**一次 ───
    def c33s2_last_points(self, seat: int) -> int | None:
        """上一局我这个座位的**净得失点数**；东一第一局（没有上一局）→ None。

        · 和牌局（tsumo / ron）：取 `score_events` 里该座位的 delta 之和
          （含罚点 / 供托），就是结算画面「我这一局 +8000 / -2000」的数字；
        · **流局（荒牌 / 九种九牌 / 四风连打 / 四家立直 / 四杠散了 / 三家和了）→ 固定 3000**
          （用户口径 2026-10-27：「流局输入 3000」）。
        """
        mid = self.db._one("SELECT match_id FROM rounds WHERE round_id=?", (self.round_id,))
        prev = self.db._row(
            "SELECT round_id, result FROM rounds WHERE match_id=? AND round_id<? "
            "AND status='ended' ORDER BY round_id DESC LIMIT 1",
            (int(mid or 0), int(self.round_id)))
        if prev is None:
            return None
        if str(prev["result"] or "") not in ("tsumo", "ron"):
            return 3000
        d = self.db._one(
            "SELECT COALESCE(SUM(delta),0) FROM score_events WHERE round_id=? AND seat=?",
            (int(prev["round_id"]), int(seat)))
        return int(d or 0)

    def c33s2_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.skill_used(s, 33, 2):
            return False
        if int(self.c33s2_armed) == s:
            return False
        return skills.owns_card(self.db, self, s, 33, strict=True)

    def c33s2_try(self, seat: int, number: int) -> dict:
        """输入数字 → 对了就武装「下一张暗置」，本小局内不能再发。"""
        s = int(seat)
        if int(self.c33s2_armed) == s:
            # 看破闸门放行后会重放同一个 op
            return {"armed": True, "last": self.c33s2_last_points(s), "number": int(number)}
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            raise RuleError("【记忆】只能在自己的切牌状态发动")
        if self.skill_used(s, 33, 2):
            raise RuleError("【记忆】本小局已经用过了")
        if not skills.owns_card(self.db, self, s, 33, strict=True):
            raise RuleError("手里没有这一轮的卡")
        want = self.c33s2_last_points(s)
        got = abs(int(number))
        if want is not None and got != abs(int(want)):
            raise RuleError("【记忆】：数字不对，再想想上一局结算了多少")
        self.c33s2_armed = s
        self.note_use(s, 33, 2, gate=False)      # op 层已过看破闸门；used_skills 记本小局
        self.save_flags()
        return {"armed": True, "last": want, "number": int(number)}

    # ─── Card34 S1【厄运】：三巡内其他三家「一切无效」 ───
    C34_TURNS = 3

    def c34_muted(self, seat: int) -> bool:
        """这个座位是不是正处在【厄运】的静默期（发动者本人永远不受影响）。"""
        if int(self.c34_by) < 0:
            return False
        if int(seat) == int(self.c34_by):
            return False
        return int(self.c34_left) > 0

    def c34_charges_of(self, seat: int) -> int:
        """本小局还剩几次【厄运】可发（默认 1；【海底】会给 +1）。"""
        return int(self.c34_charges.get(int(seat), 1))

    def c34_exempt(self, seat: int) -> bool:
        """【厄运】生效期间，**发动者自己**荣和/自摸无视拦截链（用户口径 2026-10-28）。

        注意：海底自摸那一刻厄运已经结束（`_c34_tick` 先把 left 减到 0），
        所以它**享受不到**这条豁免 —— 满贯 / 浓雾 照拦。
        """
        return int(self.c34_by) == int(seat) and int(self.c34_left) > 0

    def c34s1_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.c34_charges_of(s) <= 0:
            return False
        return skills.owns_card(self.db, self, s, 34, strict=True)

    def c34s1_arm(self, seat: int) -> dict:
        """切牌前（含鸣牌后的打牌）发动：其他三家各 3 巡「一切无效」。

        · 只能摸切 / 不能副露（含暗杠、加杠）/ 不能和 / 不能使用技能
        · 延迟生效的技能在这三巡内引爆 → 直接作废（不补偿）
        · 持续生效的技能这三巡内不生效，三巡后自动恢复
        · 决斗：三巡后重新生效，对象转移为【厄运】发动者
        · **不能被看破/封堵**（用户口径 2026-10-27）
        """
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            raise RuleError("【厄运】只能在自己的切牌阶段发动")
        if self.c34_charges_of(s) <= 0:
            raise RuleError("【厄运】本小局没有可发动次数了")
        self.c34_charges[s] = self.c34_charges_of(s) - 1
        if not skills.owns_card(self.db, self, s, 34, strict=True):
            raise RuleError("手里没有这一轮的卡")
        others = [o for o in range(4) if o != s]
        self.c34_by = s
        self.c34_left = int(self.C34_TURNS)      # 发动者自己还要摸 3 次
        self.note_use(s, 34, 1, gate=False)      # 用户口径：不能被看破
        for o in others:
            # 策略（Card05 S1）第三段计数器 +1：只对持卡人生效（上限 1）
            self.card05_interfere(int(o), s, "厄运")
        self.save_flags()
        return {"by": s, "left": int(self.c34_left), "turns": int(self.C34_TURNS)}

    def _c34_tick(self, seat: int) -> None:
        """**发动者自己**摸一次牌 → 厄运剩余 -1；摸到第 3 张那一刻结束。

        用户口径 2026-10-28：三巡 = 从「切出第 n 张」到「自己摸进第 n+3 张」。
        所以海底那张（第 3 次摸牌）摸进来的瞬间，厄运就结束了 ——
        随后的海底自摸，满贯 / 浓雾 等拦截链已经回归。
        """
        s = int(seat)
        if int(self.c34_left) <= 0 or s != int(self.c34_by):
            return
        self.c34_left = int(self.c34_left) - 1
        self.save_flags()
        if int(self.c34_left) <= 0:
            self._c34_end()

    def _c34_end(self) -> None:
        """三巡走完：一切恢复正常；决斗重新生效，对象转移为【厄运】发动者。"""
        by = int(self.c34_by)
        self.c34_by = -1
        self.c34_left = 0
        d = self.duel
        if d and by >= 0 and int(d.get("by", -1)) != by:
            d["target"] = by
            self._duel_mark(by)
        self.save_flags()

    def _c34s2_waits(self, seat: int) -> set[str]:
        """【海底】判「已经听牌」用的听牌张集合。

        ★ 2026-10-28 修：以前只看 `hand13`（去掉刚摸那张的 13 张），会漏掉
          「**刚摸进来的这张让我听牌了**」——那是最常见的一种听牌
          （摸之前不听、摸到第 14 张后打掉另一张就听），于是剩 12 张时
          `c34s2_try` 直接判「还没听牌」，海底永远不动。
        口径：14 张里只要存在一张、打出去之后听牌，就算「已经听牌」；
              听牌张取所有「打出去后能听」的并集。
              鸣牌后（没有刚摸的牌）按当前这一手直接判。
        """
        hand = list(self.hand(seat))
        melds = self.melds(seat)
        d = self.drawn_tile(seat)
        # 立直 / 命中 / 换过牌之后只能摸切 —— 手切那些形状不算数
        only_tsumogiri = (self.is_riichi(seat) or int(seat) in self.c27_s2
                          or int(seat) in self.must_tsumogiri)
        rests: list[list[str]] = []
        if d is not None and d in hand:
            r0 = list(hand)
            r0.remove(d)                       # 摸切：打掉刚摸的那张
            rests.append(r0)
            for t in (sorted(set(hand)) if not only_tsumogiri else []):
                if t == d:
                    continue
                r1 = list(hand)
                r1.remove(t)                   # 手切：打掉手里任意一张
                rests.append(r1)
        else:
            rests.append(hand)                 # 鸣牌后的打牌：这手就是最终形
        waits: set[str] = set()
        for r in rests:
            c = counts_of(r)
            if not agari.is_tenpai(c, melds):
                continue
            waits |= set(agari.winning_tiles(c, melds))
        return waits

    def c34s2_probe(self, seat: int) -> dict:
        """【海底】点技能图标时的**只读**诊断：现在为什么没发动 / 会不会发动。

        不改任何状态（不发牌、不动牌山），可以随便点。
        """
        s = int(seat)
        out: dict = {"live_left": int(self.live_left()), "need": 12,
                     "owns": skills.owns_card(self.db, self, s, 34, strict=True),
                     "fired": bool(self.c34s2_fired), "why": "",
                     "waits": [], "in_wall": "", "would_fire": False}
        if not out["owns"]:
            out["why"] = "你手里没有【海底】这张卡"
            return out
        if self.c34s2_fired:
            out["why"] = "本小局已经发动过了"
            return out
        waits = self._c34s2_waits(s)
        out["waits"] = sorted(waits)
        if not waits:
            out["why"] = "还没听牌（14 张里没有一张打出去能听）"
            return out
        hit = self.wall_find(waits)
        out["in_wall"] = str(hit[1]) if hit else ""
        if hit is None:
            out["why"] = "牌山里已经没有你听的牌：%s" % "、".join(sorted(waits))
            return out
        if int(out["live_left"]) != 12:
            out["why"] = ("现在剩 %d 张可摸（要正好剩 12 张那一刻发动）"
                          % int(out["live_left"]))
            return out
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            out["why"] = "现在不在你的切牌阶段"
            return out
        out["would_fire"] = True
        return out

    def c34s2_try(self, seat: int) -> bool:
        """切牌前自动检查【海底】：剩余 12 张 + 听牌 + 牌山（含王牌）有我的和牌张。

        满足 → 【厄运】可发动次数 +1，并**立刻自动发动**（不能被看破 / 无效化），
        同时锁定「牌山里最近的那张和牌张」，海底时用它结算。
        """
        s = int(seat)
        if self.c34s2_fired:
            return False
        if not skills.owns_card(self.db, self, s, 34, strict=True):
            return False
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        # ★ 不能要求「刚摸到牌」：吃碰之后的打牌也算切牌前（用户口径 2026-10-28），
        #   那时 drawn_tile 是 None，但手牌 10/7 张 + 副露照样能听牌。
        if int(self.live_left()) != 12:
            return False
        # ── 到这里一定是「持卡 + 剩 12 张 + 我的切牌」：开始记没触发的原因 ──
        self.c34s2_why = ""
        self.c34s2_why_seat = s
        waits = self._c34s2_waits(s)               # 14 张里任意一张打出去能听就算
        if not waits:
            self.c34s2_why = "还没听牌（14 张里没有一张打出去能听）"
            return False
        hit = self.wall_find(waits)
        if hit is None:
            self.c34s2_why = ("剩下的牌山（含王牌）里没有你听的牌：%s"
                              % "、".join(sorted(waits)))
            return False
        self.c34s2_on = s
        self.c34s2_seq, self.c34s2_tile = int(hit[0]), str(hit[1])
        self.c34s2_fired = True
        self.c34_charges[s] = self.c34_charges_of(s) + 1      # 可发动次数 +1
        self.c34s1_arm(s)                                     # 自动发动（重置 3 巡）
        self.save_flags()
        return True

    def _wall_seq_alive(self, seq: int) -> bool:
        """这张物理牌还在牌山（含王牌）里、没被摸走吗。"""
        if int(seq) < 0:
            return False
        row = self.db._row(
            "SELECT 1 FROM round_wall WHERE round_id=? AND seq=? "
            "AND dealt_to IS NULL AND draw_no IS NOT NULL",
            (self.round_id, int(seq)))
        return row is not None

    def _c34s2_last_tsumo(self, seat: int, info: dict) -> dict | None:
        """摸到最后一张（海底）：把和牌张换进手里，**等玩家点『自摸』**。

        ★ 2026-10-28 用户口径：**别自动自摸**，给按钮。
          所以这里只做「换牌 + 把刚摸那张标成和牌张」，结算走正常自摸入口
          （`legal_actions` 会出现 `tsumo`，`_do_tsumo` 再判一次）。
        · 绕过的是「能不能和」的预测：换完就是能和的手牌，振听/听牌形不影响自摸
        · **拦截链依然有效**：此刻厄运已经在「摸第 3 张」那一瞬结束，
          满贯（28S1）/ 浓雾（19S2）/ 恶灵 / 海神 / 看破代价 依然会让按钮不出现
        · 失败一律写 `c34s2_why`，客户端 `_c34_why_sync` 会 toast 出来
        """
        s = int(seat)
        # ★ 2026-10-28：`_draw_next_info` 给的键是 **seq**（不是 wall_seq）——
        #   原来只读 wall_seq，永远 -1 → 直接 return None，海底永远不自摸。
        hand_seq = info.get("wall_seq", info.get("seq", -1))
        hand_seq = -1 if hand_seq is None else int(hand_seq)
        tile, seq = str(self.c34s2_tile), int(self.c34s2_seq)
        self.c34s2_on = -1
        self.c34s2_why_seat = s
        self.c34s2_why = ""
        self.save_flags()
        if hand_seq < 0:
            self.c34s2_why = "海底：没拿到刚摸那张的牌山编号"
            return None
        # 锁定的铳张可能在这 3 巡里被别人摸走 / 被技能换掉 → 到这一刻重新确认
        if not tile or not self._wall_seq_alive(seq):
            waits = set(tile and {tile} or set()) | self._c34s2_waits(s)
            hit = self.wall_find(waits)
            if hit is None:
                self.c34s2_why = ("海底：牌山里已经没有你的和牌张了（%s）"
                                  % "、".join(sorted(waits)))
                return None
            seq, tile = int(hit[0]), str(hit[1])
        # 换牌统一走 do_swap；立直家也要能吃海底 → force=True 跳过立直锁
        self.do_swap("hand_wall", s, "海底", hand_seq=hand_seq, wall_seq=seq, force=True)
        self.c34s2_seq, self.c34s2_tile = -1, ""
        if self._judge_win(s, tile, tsumo=True) is None:
            # 换进来的牌判不出役（正常走不到）→ 原地退回，不让玩家白点
            self.c34s2_why = "海底：换进来的「%s」判不出役" % tile
            self.save_flags()
            return None
        self.temp_furiten.discard(s)
        self.last_was_rinshan = False
        self.phase = "discard"                 # 换完就是普通切牌阶段（可以点『自摸』）
        self.save_flags()
        return self._event("c34_last", {"seat": s, "tile": tile, "ready": True})

    def c30_give_target(self) -> int:
        """向听：现在该谁交牌（没有则 -1）。api_cli 用它给没人的座位代交。"""
        f = self.deal_flow or {}
        if str(f.get("kind")) != "xiangting" or str(f.get("sub")) != "give":
            return -1
        t = int(f.get("target", -1))
        return t if 0 <= t < 4 else -1

    def c30s1_auto(self, seat: int) -> dict:
        """没人在操作的座位：替他交前两张手牌（向听不做超时兜底，这里只给 AI 用）。"""
        s = int(seat)
        f = self.deal_flow or {}
        if (str(f.get("kind")) != "xiangting" or str(f.get("sub")) != "give"
                or int(f.get("target", -1)) != s):
            return {"skipped": True}
        hand = list(self.hand(s))
        if len(hand) < 2:
            return {"skipped": True}
        return self.c30s1_give(s, hand[:2])

    def _c30s1_next(self) -> None:
        """换完一家 → 问下一家；两家都完了 → 收尾（离开配牌阶段）。"""
        f = self.deal_flow
        if not f or str(f.get("kind")) != "xiangting":
            return
        targets = [int(t) for t in (f.get("targets") or [])]
        while int(f.get("stage", 0)) < len(targets):
            f["target"] = targets[int(f["stage"])]
            f["sub"] = "give"
            f["picked"] = []
            return
        s = int(f["seat"])
        self.deal_flow = None
        self.deal_wait.discard(s)
        self.deal_used.add(s)
        self.save_flags()
        self._maybe_close_deal()

    def c30_ask_for(self, seat: int) -> int:
        """这一家现在要不要「交牌」？要的话返回发动者的座位，否则 -1。"""
        f = self.deal_flow
        s = int(seat)
        if not f or str(f.get("kind")) != "xiangting":
            return -1
        if str(f.get("sub")) != "give" or int(f.get("target", -1)) != s:
            return -1
        return int(f.get("seat", -1))

    def deal_flow_view(self, seat: int) -> dict | None:
        f = self.deal_flow
        if not f:
            return None
        # 向听 / 新手运：被问的那家也要看得到（他要交牌）
        if str(f.get("kind")) in ("xiangting", "c32"):
            if (str(f.get("sub")) == "give" and int(f.get("target", -1)) == int(seat)
                    and int(f.get("seat", -1)) != int(seat)):
                return {"kind": str(f.get("kind")), "role": "give",
                        "seat": int(f["seat"]),
                        "target": int(seat), "from": int(f["seat"]),
                        "min": int(f.get("min", 2)), "max": int(f.get("max", 3)),
                        "stage": int(f.get("stage", 0))}
            if int(f.get("seat", -1)) != int(seat):
                return None
            return {"kind": str(f.get("kind")), "role": "swap", "seat": int(f["seat"]),
                    "target": int(f.get("target", -1)), "sub": str(f.get("sub")),
                    "picked": [str(x) for x in (f.get("picked") or [])],
                    "stage": int(f.get("stage", 0)),
                    "left": len(f.get("targets") or []) - int(f.get("stage", 0))}
        if int(f.get("seat", -1)) != int(seat):
            return None
        out = {"seat": int(f["seat"]), "card": int(f["card"]),
               "skill": int(f["skill"]), "kind": str(f.get("kind", "fengshen")),
               "stage": f.get("stage")}
        if "targets" in f:
            out["target"] = int(f.get("target", -1))
            out["n"] = int(f.get("n", 0))
        if "kinds" in f:
            out["kinds"] = [str(x) for x in (f.get("kinds") or [])]
        return out

    def deal_swap(self, seat: int, stage: int, tiles: list[str]) -> dict:
        """风神的一步：把选中的 n 张手牌和 target 手里所有风牌交换。"""
        f = self.deal_flow
        if not f or int(f.get("seat", -1)) != int(seat):
            raise RuleError("现在没有在交换风牌")
        if int(stage) != int(f.get("stage", -1)):
            raise RuleError("阶段对不上，请重新选牌")
        target = int(f["targets"][int(stage)])
        _dl = str(f.get("kind")) == "dora_luck"
        winds = self._flow_target_tiles(f, target)
        if _dl:
            winds = winds[:int(f.get("n", len(winds)))]   # 只换「我拿得出等量」的那几张
        picks = [str(t) for t in tiles]
        if len(picks) != len(winds):
            raise RuleError("要选 %d 张手牌" % len(winds))
        if _dl:
            for tl in picks:
                if self._is_dora(tl):
                    raise RuleError("宝牌不能拿去交换")

        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, seat))
        pool: dict[str, list[int]] = {}
        for r in rows:
            pool.setdefault(str(r["tile"]), []).append(int(r["wall_seq"]))
        picked: list[tuple[str, int]] = []
        for tile in picks:
            if not pool.get(tile):
                raise RuleError(f"手里没有 {tile}")
            picked.append((tile, pool[tile].pop(0)))

        had_drawn = self.db._one(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? "
            "AND is_drawn=1 LIMIT 1", (self.round_id, seat))

        before = self._hand_snapshot()          # 策略：换牌前后的手牌比对
        _why = "宝牌运" if _dl else "风神"
        with self.db.tx():
            pairs = list(zip(picked, winds))
            for (tile, wseq), r in pairs:            # 我的手牌 ⇄ 对家的风牌/宝牌
                self._swap_hand_tiles(int(seat), int(wseq), target,
                                      int(r["wall_seq"]), _why, clear_drawn=True)
            # 两边张数不一样时（宝牌运会有）：多出来的直接改归属，别把牌弄丢
            for tile, wseq in picked[len(pairs):]:
                self.db.conn.execute(
                    "UPDATE round_hands SET seat=?, is_drawn=0 "
                    "WHERE round_id=? AND wall_seq=?",
                    (int(target), self.round_id, int(wseq)))
            for r in winds[len(pairs):]:
                self.db.conn.execute(
                    "UPDATE round_hands SET seat=?, is_drawn=0 "
                    "WHERE round_id=? AND wall_seq=?",
                    (int(seat), self.round_id, int(r["wall_seq"])))
            # 庄家刚摸的那张如果被换走了，把换进来的那张标成「刚摸到」
            if had_drawn is not None and winds:
                still = self.db._one(
                    "SELECT COUNT(*) FROM round_hands WHERE round_id=? AND seat=? "
                    "AND wall_seq=?",
                    (self.round_id, seat, int(had_drawn)))
                if not still:
                    self._set_hand_drawn(int(winds[-1]["wall_seq"]), True)

        # 策略：对手的手牌被换了
        self.card05_note_changes(before, seat, "宝牌运" if _dl else "风神")
        got = [str(r["tile"]) for r in winds]
        f["stage"] = int(stage) + 1
        self._advance_deal_flow()
        self.save_flags()
        return {"stage": int(stage), "target": target, "count": len(winds),
                "got": got, "next": self.deal_flow_view(seat)}

    def _maybe_close_deal(self) -> None:
        if self.phase == "deal_skill" and not self.deal_wait:
            self.phase = "discard"                    # 所有人都发动完/跳过 → 庄家切牌
            self.turn = self.dealer
            self.deal_deadline = 0.0
            self.save_flags()

    def deal_skill_timeout(self) -> bool:
        """配牌技能阶段**不限时**（用户口径 2026-10-27：不要给配牌时间限时）。

        以前是 20 秒没点「发动 / 开始」就由服务端跳过。现在一律等玩家自己决定：
        真掉线的座位由客户端 `step` 的 `deal_action(..., "skip")` 兜底推进，
        不会因为「有人在想」就把整局放过去。
        """
        return False

    def deal_skip_all(self) -> None:
        """超时兜底：还在等的配牌技能全当「跳过」，把这一局放出来。"""
        if self.deal_flow is not None:                # 风神换牌没做完 → 直接放弃
            self.deal_flow = None
        for s in sorted(self.deal_wait):
            if self.phase != "deal_skill":
                break
            try:
                self.deal_action(int(s), "skip")
            except RuleError:
                self.deal_wait.discard(int(s))
                self.deal_used.add(int(s))
        self.deal_deadline = 0.0
        self.save_flags()
        self._maybe_close_deal()

    # ── 技能播报 + 人物卡翻明 ──────────────────────────────────
    def _load_revealed(self) -> set[int]:
        row = self.db._row("SELECT value FROM meta WHERE key='revealed_seats'")
        if not row:
            return set()
        try:
            return {int(x) for x in (json.loads(row["value"]) or [])
                    if int(x) in range(4)}
        except (ValueError, TypeError):
            return set()

    def note_skill(self, seat: int, card: int, skill: int) -> None:
        """历史接口：以前只播报 + 记「座位翻明」，现在统一走 note_use。"""
        self.note_use(seat, card, skill)

    def press_can(self, seat: int) -> bool:
        """压制：持 Card03、刚摸完牌、这次摸牌还没换过。"""
        s = int(seat)
        if not self.sees_face_down(s):
            return False
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None:
            return False
        return s not in self.press_used

    def suppress_swap(self, seat: int, hand_tile: str, river_seq: int) -> dict:
        """用一张手牌换一张牌河牌。换哪一类由牌河那张牌决定：

        · 自己牌河里的明牌 → mode="own"
        · 任意一家的暗置牌 → mode="down"（只有持 Card03 的人看得见）

        限次：**每次摸牌后只能换一次**（两种模式共用一个闸门 press_used，
        摸牌时清掉）。换出去的手牌也暗置进牌河；换进来的牌当成「刚摸到的」。
        """
        if self.phase != "discard" or seat != self.turn:
            raise RuleError("现在不是你的出牌回合")
        if self.drawn_tile(seat) is None:
            raise RuleError("摸牌之后才能发动")
        if not self.sees_face_down(int(seat)):
            raise RuleError("这张不是你这一局的人物卡（压制）")
        if int(seat) in self.press_used:
            raise RuleError("这次摸牌已经交换过了（每次摸牌后只能换一次）")
        self._assert_hand_mutable(seat)                  # 立直后不能压制换牌
        tile = str(hand_tile)
        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, seat))
        pick = next((r for r in rows if str(r["tile"]) == tile), None)
        if pick is None:
            raise RuleError(f"手里没有 {tile}")

        river = self.db._row(
            "SELECT seq, seat, wall_seq, tile, called, is_riichi_tile, face_down "
            "FROM round_discards WHERE round_id=? AND seq=?", (self.round_id, int(river_seq)))
        if river is None:
            raise RuleError("这张牌不在牌河里")
        if int(river["called"] or 0):
            raise RuleError("已经被吃碰杠拿走的牌不能换")
        if int(river["is_riichi_tile"] or 0):
            raise RuleError("立直宣言牌不能换")
        down = bool(int(river["face_down"] or 0))
        if down:
            mode = "down"                      # 播报用：换的是暗置牌
        elif int(river["seat"]) == seat:
            mode = "own"                       # 播报用：换的是自己牌河的明牌
        else:
            raise RuleError("只能换自己牌河里的牌，或者场上的暗置牌")

        self.do_swap("hand_river", seat, "压制", hand_seq=int(pick["wall_seq"]),
                     river_seq=int(river_seq), face_down=True)
        with self.db.tx():
            # 换进来的那张算「刚摸到的」
            self.db.conn.execute(
                "UPDATE round_hands SET is_drawn=0 WHERE round_id=? AND seat=?",
                (self.round_id, seat))
            self.db.conn.execute(
                "UPDATE round_hands SET is_drawn=1 WHERE round_id=? AND wall_seq=?",
                (self.round_id, int(pick["wall_seq"])))
        self.press_used.add(int(seat))               # 每次摸牌后只能交换一次
        self.press_win.add(int(seat))                # 换完这一手：自摸不算边张/嵌张符
        self.note_use(seat, 3, 2, once=False)        # 压制可多次发动：不记「一次性」
        self.save_flags()

        # 暗置牌进河：持有「压制」的其他人可以荣和这张（明牌对他有效）
        claim = self._open_facedown_claim(int(river["seq"]), tile, seat)
        return {"mode": mode, "hand": tile, "river": str(river["tile"]),
                "got": str(river["tile"]), "claim": bool(claim)}

    def _open_facedown_claim(self, seq: int, tile: str, from_seat: int,
                             resume_back: bool = True) -> bool:
        """一张暗置牌进牌河：只有「压制」持有者能荣和它。

        resume_back=True  → 没人荣就回到放这张牌的人继续打（压制换牌的场合）
        resume_back=False → 按普通打牌处理，轮到下家（决斗暗置打出的场合）
        """
        if self.c39s1_on:
            return False                     # 【隐形】：暗置牌也不能被荣
        opts: dict[int, list[dict]] = {}
        for s in range(4):
            if s == from_seat or not self.sees_face_down(s):
                continue
            if self._win_ok(s, tile, tsumo=False) and self._c28s1_allows(s, tile, False):
                opts[s] = [{"action": "ron"}]
        if not opts:
            return False
        p = {"discard_seq": seq, "tile": tile, "from": from_seat,
             "options": opts, "answers": {}}
        if resume_back:
            p["resume"] = from_seat
        self.pending = p
        self.phase = "claim"
        return True

    # ── 立直后的杠（标准日麻，天凤 / 雀魂同款）──────────────────────────
    # 立直 = 手牌锁死。杠是唯一还能动牌的操作，所以限制最严：
    #   · **加杠一律禁止**（碰的刻子变成杠 → 手牌少一张，牌型必定变了）；
    #   · 暗杠要同时满足：
    #       ① 杠的 4 张里必须有**刚摸到的那张**（禁「送り槓」：
    #          不能把手里原有的 4 张直接扣下去，那等于白换一次牌型）；
    #       ② 杠完**听牌一张都不能变**：杠前听什么、杠后还听什么，
    #          待牌种类完全一致（这条同时挡住「杠完不听」和「杠完改听」）。
    #
    # 例：听 3m-6m 两面，手里 111m + 摸到第 4 张 1m 起手，
    #     暗杠 1m 之后仍然只听 3m-6m → 允许；
    #     任何会让待牌集合变化的暗杠 → 连动作都不给（legal 里不出现）。
    def ankan_allowed(self, seat: int, tile: str) -> bool:
        s = int(seat)
        if not self.is_riichi(s):
            return True
        drawn = self.drawn_tile(s)
        if drawn is None:
            return False
        if kind_of(str(drawn)) != kind_of(str(tile)):
            return False                      # 手里原有的 4 张不能杠（送り槓）
        hand = self.hand(s)                   # 14 张（含刚摸那张）
        same = [t for t in hand if kind_of(str(t)) == kind_of(str(tile))]
        if len(same) < 4:
            return False
        rest = list(hand)
        for t in same[:4]:
            rest.remove(t)                    # 扛到杠上的 4 张
        melds = self.melds(s)
        before = set(agari.winning_tiles(counts_of(self.hand13(s)), melds))
        if not before:
            return False                      # 本来就没听牌（正常立直不会发生）
        kan = {"kind": "ankan", "tiles": [str(tile)] * 4}
        after = set(agari.winning_tiles(counts_of(rest), melds + [kan]))
        return before == after

    def kakan_allowed(self, seat: int, tile: str) -> bool:
        """立直后不能加杠（标准日麻）。"""
        return not self.is_riichi(int(seat))

    # ── 杠 ──
    def _do_ankan(self, seat: int, tile: str) -> dict:
        return self._kan(seat, "ankan", tile)

    def _do_kakan(self, seat: int, tile: str) -> dict:
        # 立直后不能加杠：先拦住，别让它进到「抢杠」里被别人荣和
        if not self.kakan_allowed(int(seat), str(tile)):
            raise RuleError("立直后不能加杠")
        # 抢杠：加杠的那张牌，别人正好和 → 杠不成立，直接荣和
        #（暗杠不能抢，所以只有加杠要查）
        self.chankan_now = True
        robbers = [s for s in range(4) if s != seat and self._win_ok(s, tile, tsumo=False)]
        if robbers:
            robbers.sort(key=lambda s: (s - seat) % 4)
            take = robbers if self.rules.get("multi_ron") else robbers[:1]
            for w in take:
                res = self._judge_win(w, tile, tsumo=False)
                if res:
                    self._finish(w, seat, "ron", res)
                    self.chankan_now = False
                    return self._event("chankan", {"seat": w, "from": seat, "tile": tile,
                                                   "yaku": res["yaku"], "han": res["han"],
                                                   "fu": res["fu"], "points": res["pays"]})
        self.chankan_now = False
        return self._kan(seat, "kakan", tile)

    def _kan(self, seat: int, kind: str, tile: str) -> dict:
        """杠（暗杠：手里 4 张 / 加杠：碰过的那张第 4 张）"""
        # 立直后的杠：规则见 ankan_allowed / kakan_allowed
        if kind == "ankan" and not self.ankan_allowed(int(seat), str(tile)):
            raise RuleError("立直后暗杠：必须用刚摸到的那张，且杠完听牌不能变")
        if kind == "kakan" and not self.kakan_allowed(int(seat), str(tile)):
            raise RuleError("立直后不能加杠")
        if self.c34_muted(seat):
            raise RuleError("【厄运】期间不能杠（暗杠 / 加杠 / 明杠都不行）")
        self.duel_retarget(int(seat))            # 决斗：非决斗家开杠也算「副露」
        hand = self.hand(seat)
        # 按「牌种」挑牌：kind_of 把 0m 和 5m 算同一种，字牌各算一种（dong/nan/xi/…）。
        # ★ 千万别用「花色 + 数字」去比：字牌的花色都是 ''、数字都是 0，
        #   那样东/南/西/北/白/发/中会被当成同一张牌 ——
        #   暗杠西风会把手里别的字牌一起杠进去，而西风还剩在手上。
        same = [t for t in hand if kind_of(t) == kind_of(tile)]
        if not same:
            raise RuleError("手里没有这张牌，杠不了")
        tiles = same[:4] if kind == "ankan" else [same[0]]
        if kind == "ankan" and len(same) < 4:
            raise RuleError("暗杠要手里有 4 张一样的")
        self.db.meld(self.round_id, seat, kind, tiles, called_tile=tile, from_seat=seat,
                     rot_index=-1 if kind == "ankan" else 0)
        if str(kind) == "kakan":
            self.c35_start(int(seat))              # 加杠也算副露 → 流势
        self.ippatsu.clear()
        # 友引段1：这一杠之后要摊面子 → 补岭上牌 + 翻宝牌都推迟到摊完之后
        # ★ 手里一个面子都没有就别进摊面子阶段：那是个不可取消、也没得选的死路
        if int(self.youyin_meld_armed) == int(seat):
            if self._youyin_has_mianzi(self.hand(int(seat))):
                self.pending_rinshan.add(int(seat))
                self._youyin_open_offer(int(seat))
                return self._event("youyin_meld", {"seat": int(seat),
                                                   "tiles": tiles, "kind": str(kind)})
            # 没面子 → 技能到此为止（卡面已经翻明了，本小局不再进段1）
            self.youyin_meld_armed = -1
            self.youyin_meld_done.add(int(seat))
            self.save_flags()
        self.reveal_dora()                                   # 开杠 → 立刻翻一张宝牌指示牌
        got = self._draw_rinshan(seat)                       # 岭上摸牌（从王牌里按顺序拿）
        if got is None:
            return self._ryuukyoku("exhaustive")
        self.last_was_rinshan = True
        self.phase = "discard"
        owner = self._self_wind_owner(seat, got)
        if owner is not None and (self.c34_muted(int(seat)) or self.c34_muted(int(owner))):
            owner = None                       # 【厄运】：自风三巡内无效
        if owner is not None:
            self.wind_swap = {"owner": int(owner), "from": int(seat), "tile": got}
            self.phase = "wind_swap"
        ev = self._event(kind, {"seat": seat, "tile": tile, "drawn": got,
                                "rinshan": True})
        abort = self._check_abortive()
        return abort or ev

    # ── 特殊流局（四家立直 / 四杠散了 / 四风连打）──
    def _check_abortive(self) -> dict | None:
        if self.phase == "ended":
            return None
        n_riichi = self.db._one("SELECT COUNT(*) FROM round_riichi WHERE round_id=?",
                                (self.round_id,))
        if n_riichi >= 4:
            return self._ryuukyoku("sucha_riichi")          # 四家立直
        kans = self.db._rows("SELECT seat, COUNT(*) c FROM round_melds WHERE round_id=? "
                             "AND kind IN ('ankan','minkan','kakan') GROUP BY seat",
                             (self.round_id,))
        total = sum(k["c"] for k in kans)
        if total >= 4 and len(kans) > 1:
            return self._ryuukyoku("sukan_santan")          # 四杠散了
        return None

    # ── 鸣牌 ──
    def _duel_after_call(self, seat: int) -> None:
        """鸣牌之后：非决斗家副露 → 决斗目标转移。"""
        self.duel_retarget(int(seat))

    def _do_chi(self, seat: int, tiles: list[str] | None = None) -> dict:
        return self._ask(seat, "chi", tiles)

    def _do_pon(self, seat: int, tiles: list[str] | None = None) -> dict:
        return self._ask(seat, "pon", tiles)

    def _do_minkan(self, seat: int, tiles: list[str] | None = None) -> dict:
        return self._ask(seat, "minkan", tiles)

    def _do_ron(self, seat: int) -> dict:
        p = self.pending
        if not p or seat not in p["options"] or not any(
                o["action"] == "ron" for o in p["options"][seat]):
            raise RuleError("现在没有可荣和的牌")
        p["answers"][seat] = {"action": "ron", "tiles": None}
        return self._resolve_claims()                        # 荣和立刻结算

    def _do_pass(self, seat: int) -> dict:
        p = self.pending
        if p and seat in p["options"] and seat not in p["answers"]:
            if any(o["action"] == "ron" for o in p["options"][seat]):
                self.temp_furiten.add(seat)                  # 见逃 → 同巡振听
                if self.is_riichi(seat):
                    self.riichi_furiten.add(seat)            # 立直后见逃 → 永久振听
            p["answers"][seat] = {"action": "pass", "tiles": None}
            if len(p["answers"]) >= len(p["options"]):
                return self._resolve_claims()
        return self._event("pass", {"seat": seat})

    def _ask(self, seat: int, kind: str, tiles) -> dict:
        p = self.pending
        if not p or seat not in p["options"]:
            raise RuleError("现在不能鸣这张牌")
        opt = next((o for o in p["options"][seat] if o["action"] == kind), None)
        if opt is None:
            raise RuleError(f"你不能 {kind} 这张牌")
        if tiles is None and opt.get("choices"):
            tiles = opt["choices"][0]
        p["answers"][seat] = {"action": kind, "tiles": tiles}
        self.duel_retarget(int(seat))            # 决斗：非决斗家副露 → 目标转移
        if len(p["answers"]) >= len(p["options"]):
            return self._resolve_claims()
        return self._event("waiting", {"seat": seat, "action": kind})

    # ── 鸣牌窗口 ──
    def _open_claim_window(self, discard_seq: int, tile: str, from_seat: int) -> None:
        opts: dict[int, list[dict]] = {}
        for s in range(4):
            if s == from_seat:
                continue
            if self.c34_muted(s):
                continue                     # 【厄运】：不能吃碰杠，也不能荣和
            if self.c39s1_on:
                continue                 # 【隐形】：打出的牌谁都不能吃碰杠荣
            if int(s) in self.c45s1_on:
                continue                 # 【神境】：只能自摸，吃碰杠荣和全关
            acts = []
            if self._win_ok(s, tile, tsumo=False) and self._c28s1_allows(s, tile, False):
                acts.append({"action": "ron"})
            if self.is_riichi(s):
                # 立直之后不能吃/碰/明杠（暗杠在 legal_actions 里单独给，仍然可以；荣和照旧）
                if acts:
                    opts[s] = acts
                continue
            if calls.can_pon(self.hand(s), tile):
                acts.append({"action": "pon", "choices": calls.pon_options(self.hand(s), tile)})
            mine = calls.minkan_options(self.hand(s), tile)
            if mine:
                acts.append({"action": "minkan", "choices": mine})
            if (s - from_seat) % 4 == 1:                     # 只有下家能吃
                chi = calls.chi_options(self.hand(s), tile)
                if chi:
                    acts.append({"action": "chi", "choices": chi})
            if acts:
                opts[s] = acts
        xp = self.xianfu_pending or {}
        if int(xp.get("seat", -1)) == int(from_seat) and int(xp.get("declarer", -1)) >= 0:
            if not any(any(a["action"] == "ron" for a in acts) for acts in opts.values()):
                self._xianfu_settle(int(xp["declarer"]))
                return
        if not opts:
            self._advance_after_discard(from_seat)
            return
        self.pending = {"discard_seq": discard_seq, "tile": tile, "from": from_seat,
                        "options": opts, "answers": {}}
        self.phase = "claim"

    def _resolve_claims(self) -> dict:
        p = self.pending
        self.pending = None
        # 【岭上开花】在鸣牌窗口点的那一手：结算前先收起来，
        # 只有「这一手的明杠真的归我」才放回去（荣和 / 别人先鸣 → 作废、技能不消耗）
        _c37_auto = int(self.c37s1_auto)
        self.c37s1_auto = -1
        if p is None:
            self._next_player()
            return self._event("claim_none", {})
        answers = p["answers"]

        ron_seats = sorted([s for s, a in answers.items() if a["action"] == "ron"],
                           key=lambda s: (s - p["from"]) % 4)
        if len(ron_seats) >= 3:
            return self._ryuukyoku("sanchahou")              # 三家和了
        if ron_seats:
            self.card05_extra.discard(int(p["from"]))
            take = ron_seats if self.rules.get("multi_ron") else ron_seats[:1]
            for s in take:
                magic = (self.c11_win == int(s))
                res = self._judge_win(s, p["tile"], tsumo=False, as_tsumo=magic)
                if res:
                    # 魔术：交换后直接和牌一律按自摸算（三家分摊）
                    self._youyin_disarm()
                    self._finish(s, None if magic else p["from"],
                                 "tsumo" if magic else "ron", res)
                    return self._event("ron", {"seat": s, "from": p["from"], "yaku": res["yaku"],
                                               "han": res["han"], "fu": res["fu"],
                                               "points": res["pays"]})

        best = None
        for s, a in answers.items():
            if a["action"] in ("pon", "minkan", "chi"):
                key = (CLAIM_PRIORITY[a["action"]], -((s - p["from"]) % 4))
                if best is None or key > best[0]:
                    best = (key, s, a)
        if best:
            self.card05_extra.discard(int(p["from"]))
            _, s, a = best
            if _c37_auto == int(s) and str(a.get("action", "")) == "minkan":
                self.c37s1_auto = _c37_auto      # 这一杠真的开成了 → 杠完接着走岭上
            # 钓鱼：吃到/碰上家的牌 → 本小局可以继续用
            if int(s) == int(getattr(self, "_diaoyu_me", -1)):
                up = (int(s) - int(p["from"])) % 4 == 1
                if up and a["action"] in ("chi", "pon"):
                    self.diaoyu_locked = False
                    self.save_flags()
            ev = self._apply_claim(s, a["action"], a["tiles"], p)
            self._youyin_disarm(s, a["action"])      # 没真副露就把开启状态清掉
            # _apply_claim 有事要额外说（明杠补岭上 / 杠后流局）就用它返回的事件，否则用标准事件
            return ev or self._event(a["action"], {"seat": s, "tiles": a["tiles"],
                                                   "from": p["from"],
                                                   "rot_index": self._rot_index(p["from"], s)})
        self._youyin_disarm()                        # 谁都没鸣 → 开启状态作废
        if p.get("resume") is not None:
            # 这个窗口不是「打牌」引起的（是换牌把暗置牌放进牌河）
            # → 没人荣和就回到换牌的人继续打牌，不能跳到他下家
            self.turn = int(p["resume"])
            self.phase = "discard"
            return self._event("claim_none", {})
        self._advance_after_discard(int(p["from"]))
        return self._event("claim_none", {})

    def _apply_claim(self, seat: int, kind: str, tiles, p: dict) -> dict | None:
        # 钓鱼：吃到/碰上家的牌 → 本小局还能继续用
        if self.diaoyu_locked and int(p.get("from", -1)) == (int(seat) - 1) % 4 \
                and str(kind) in ("chi", "pon"):
            self.diaoyu_locked = False
            self.save_flags()
        """把「鸣牌窗口的胜出者」真正执行掉（吃/碰/明杠）。

        返回：需要额外发给客户端的事件（明杠补岭上牌 / 杠后流局），没事就返回 None。
        """
        rot = self._rot_index(p["from"], seat)
        hand_used = list(tiles or [])
        # 副露的显示顺序：被鸣的那张摆在 rot_index 的位置（和客户端一致）
        display: list[str] = []
        rest = list(hand_used)
        for k in range(1 + len(rest)):
            if k == rot:
                display.append(p["tile"])
            elif rest:
                display.append(rest.pop(0))
        self.db.meld(self.round_id, seat, kind, display, called_tile=p["tile"],
                     from_seat=p["from"], from_discard_seq=p["discard_seq"], rot_index=rot)
        self.ippatsu.clear()
        self.temp_furiten.clear()
        self.pending_kuikae = {"kind": kind, "called": p["tile"], "used": hand_used}
        self.c35_start(int(seat))                 # 流势（35S1）：副露后自动排牌山
        # 22S2 段1：这一手是「点了友引」的副露 → 副露完先摊面子再打牌
        # （吃 / 碰 / 明杠 都算；明杠的岭上牌推迟到摊完面子之后再补）
        if int(self.youyin_meld_armed) == int(seat) and str(kind) in ("chi", "pon", "minkan"):
            if str(kind) == "minkan":
                self.pending_rinshan.add(int(seat))      # 摊完面子再补岭上 + 翻宝牌
            if self._youyin_has_mianzi(self.hand(int(seat))):
                self.pending_kuikae = None
                self._youyin_open_offer(int(seat))
                return self._event("youyin_meld", {"seat": int(seat),
                                                   "tiles": display, "kind": str(kind)})
            # 手里一个面子都没有 → 没得摊，直接收尾（补岭上/翻宝、回到打牌）。
            # 不这么走就会停在 youyin_meld：面板不可取消、服务端又拒一切组合 → 全桌卡死。
            # ★ 必须 return：下面还有一段「明杠补岭上/翻宝」，收尾时已经补过了，
            #   落下去会重复摸一张岭上牌。
            self._youyin_finish(int(seat))
            return None
        self.turn = seat
        self.phase = "discard"
        self.db.conn.execute("UPDATE rounds SET turn_seat=? WHERE round_id=?",
                             (seat, self.round_id))
        if kind == "minkan":
            # 明杠和暗杠/加杠一样，有两件事必须做，少一件就会「手上少一张牌 → 这一局再也和不了」：
            #   ① 翻一张新的宝牌指示牌（每开一次杠都翻一张）；
            #   ② 从王牌补一张「岭上牌」——这张就是明杠后的第 14 张牌。
            # （原来这里调的是 db.reveal_next_dora：它只把「已经存在的宝牌行」标成已翻开，
            #   而新宝牌那一行还没建出来 → 等于什么也没做；岭上牌则完全没补。）
            self.reveal_dora()
            got = self._draw_rinshan(seat)
            if got is None:                                  # 王牌都摸完了 → 荒牌流局
                return self._ryuukyoku("exhaustive")
            self.last_was_rinshan = True                     # 这张就是岭上牌（自摸才能算岭上开花）
            abort = self._check_abortive()                   # 可能是四杠散了
            if abort:
                return abort
            if int(self.c37s1_auto) == int(seat):
                # 【岭上开花】在鸣牌窗口里点的 → 杠已经开成，接着走「换和牌张」那一段
                self.c37s1_auto = -1
                self._c37_auto_result = self._c37s1_after_kan(int(seat))
                self.save_flags()
            return self._event("minkan", {"seat": seat, "tiles": display, "from": p["from"],
                                          "rot_index": rot, "drawn": got, "rinshan": True})
        return None

    @staticmethod
    def _rot_index(from_seat: int, seat: int) -> int:
        """横置那张摆左/中/右：上家 0 / 对家 1 / 下家 2（和客户端一致）。"""
        return {3: 0, 2: 1, 1: 2}.get((from_seat - seat) % 4, 0)

    def _next_player(self) -> None:
        if self.phase == "deal_skill" or self.deal_flow:
            return                                           # 配牌技能还没结算完
        if self._check_sufon():                              # 四风连打
            return
        self.turn = (self.turn + 1) % 4
        self.phase = "draw"
        self.db.conn.execute("UPDATE rounds SET turn_seat=? WHERE round_id=?",
                             (self.turn, self.round_id))
        self.save_flags()          # phase / turn 都在 flags 里，换人就得落库

    # ─── 魔术（Card11 Skill1）：手牌 ? 宝牌指示牌 ───────────────────────────
    def owns_card11(self, seat: int) -> bool:
        s = int(seat)
        if s not in self._c11_cache:
            self._c11_cache[s] = skills.owns_card(self.db, self, s, 11, strict=True)
        return self._c11_cache[s]

    def card11_can(self, seat: int) -> bool:
        """摸牌后、打牌前，还有没翻开的指示牌时能发动（一次性）"""
        if self.is_riichi(int(seat)):
            return False          # 立直后手牌锁定：不再询问会改手牌的技能

        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None or self.skill_used(s, 11, 1):
            return False
        if not self.owns_card11(s):
            return False
        return int(self.dora_revealed) > 0

    def _c11_dora_slots(self, idx: int) -> dict:
        """第 idx 张指示牌 → {kind: (王牌上的 wall_seq, 现在那张牌)}"""
        n = self.wall_first_stack()
        if not n or int(idx) < 0 or int(idx) >= int(self.dora_revealed):
            return {}
        no_d, no_u = wallmodel.dora_tile_nos(n, int(idx))
        out = {}
        for kind, no in (("dora", no_d), ("ura", no_u)):
            out[kind] = (int(wallmodel.seq_of_tile(no)), self._tile_of_no(int(no)))
        return out

    def _c11_sync_dora(self, seqs) -> list[dict]:
        """王牌上那几张牌被换过 → 重新读指示牌/里宝指示牌，把 round_dora 改写掉。
        宝牌信息（哪张是宝牌）永远按「当前指示牌」重算，别缓存在别处。"""
        n = self.wall_first_stack()
        if not n:
            return []
        want = {int(x) for x in seqs}
        out = []
        for i in range(int(self.dora_revealed)):
            no_d, no_u = wallmodel.dora_tile_nos(n, i)
            for kind, no in (("dora", no_d), ("ura", no_u)):
                seq = int(wallmodel.seq_of_tile(no))
                if seq not in want:
                    continue
                tile = self._tile_of_no(no)
                with self.db.tx():
                    self.db.conn.execute(
                        "UPDATE round_dora SET indicator=?, dora=? "
                        "WHERE round_id=? AND kind=? AND idx=?",
                        (tile, dora_from_indicator(tile), self.round_id, kind, i))
                out.append({"idx": i, "kind": kind, "indicator": tile,
                            "dora": dora_from_indicator(tile)})
        return out

    def card11_swap(self, seat: int, hand_tile: str, idx: int = 0) -> dict:
        """把手牌一张和「第 idx 张宝牌指示牌」交换；指示牌进手里，手牌上王牌。"""
        s = int(seat)
        if not self.owns_card11(s):
            raise RuleError("手里不是这一轮的魔术卡")
        if self.skill_used(s, 11, 1):
            raise RuleError("魔术一轮只能用一次")
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            raise RuleError("摸牌之后、打牌之前才能发动")
        if self.drawn_tile(s) is None:
            raise RuleError("还没摸牌")
        slots = self._c11_dora_slots(int(idx))
        if not slots or "dora" not in slots:
            raise RuleError("这张宝牌指示牌还没翻开")
        tile = str(hand_tile)
        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn, wall_seq", (self.round_id, s))
        pick = next((r for r in rows if str(r["tile"]) == tile), None)
        if pick is None:
            raise RuleError(f"手里没有 {tile}")
        hseq = int(pick["wall_seq"])
        dseq, dtile = slots["dora"]
        self.do_swap("hand_wall", s, "魔术", hand_seq=hseq, wall_seq=dseq)
        self.mark_skill_used(s, 11, 1)
        self.note_skill(s, 11, 1)
        self.c11_win = s                              # 这一手和牌 = 交换后直接和牌
        changed = self._c11_sync_dora({dseq})          # 宝牌/里宝信息跟着变（幂等）
        self.save_flags()
        return {"hand": tile, "got": dtile, "idx": int(idx),
                "dora": self.revealed_dora("dora"), "changed": changed}

    def card11s2_can(self, seat: int) -> bool:
        """快手：摸牌后、打牌前，别的家牌河还有第一列/第六列的牌时能发动（一次性）"""
        if self.is_riichi(int(seat)):
            return False          # 立直后手牌锁定：不再询问会改手牌的技能

        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None or self.skill_used(s, 11, 2):
            return False
        if not self.owns_card11(s):
            return False
        return bool(self._c11s2_targets(s))

    def _c11s2_targets(self, seat: int) -> list[int]:
        """可换的牌河 seq：每家牌河按顺序每 6 张一排，只要第 1 张和第 6 张；
        暗置的、被鸣走的不要。"""
        me = int(seat)
        rows = self.db._rows(
            "SELECT seq, seat, tile, called, face_down FROM round_discards "
            "WHERE round_id=? ORDER BY seat, seq", (self.round_id,))
        pos: dict[int, int] = {}
        out: list[int] = []
        for r in rows:
            sd = int(r["seat"])
            k = pos.get(sd, 0)
            pos[sd] = k + 1
            if sd == me:
                continue
            if k % 6 not in (0, 5):
                continue
            if int(r["called"] or 0) or int(r["face_down"] or 0):
                continue
            if str(r["tile"]) == "":
                continue
            out.append(int(r["seq"]))
        return out

    def _c11s2_seq_of(self, me: int, target_seat: int, slot: int) -> int:
        """某家牌河第 slot 张（按该家自己的顺序）对应的 round_discards.seq"""
        if int(target_seat) == int(me) or int(target_seat) not in range(4):
            return -1
        rows = self.db._rows(
            "SELECT seq, tile, called, face_down FROM round_discards "
            "WHERE round_id=? AND seat=? ORDER BY seq", (self.round_id, int(target_seat)))
        if int(slot) < 0 or int(slot) >= len(rows):
            return -1
        if int(slot) % 6 not in (0, 5):
            return -1
        r = rows[int(slot)]
        if int(r["called"] or 0) or int(r["face_down"] or 0) or str(r["tile"]) == "":
            return -1
        return int(r["seq"])

    def card11s2_swap(self, seat: int, river_seq: int = -1,
                      target_seat: int = -1, slot: int = -1) -> dict:
        """快手：摸到的牌暗置塞进别家牌河（第 1/6 列那张），把那张牌换进手里。"""
        s = int(seat)
        if not self.owns_card11(s):
            raise RuleError("手里不是这一轮的魔术卡")
        if self.skill_used(s, 11, 2):
            raise RuleError("快手一轮只能用一次")
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            raise RuleError("摸牌之后、打牌之前才能发动")
        drawn = self.drawn_tile(s)
        if drawn is None:
            raise RuleError("还没摸牌")
        seq = int(river_seq)
        if int(target_seat) >= 0:
            seq = self._c11s2_seq_of(s, int(target_seat), int(slot))
        if seq not in self._c11s2_targets(s):
            raise RuleError("只能换别家牌河第一列或第六列的明牌")
        row = self.db._row(
            "SELECT wall_seq, tile FROM round_discards WHERE round_id=? AND seq=?",
            (self.round_id, seq))
        if row is None:
            raise RuleError("这张牌不在牌河里")
        target = str(row["tile"])
        mine = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND is_drawn=1",
            (self.round_id, s))
        if mine is None:
            raise RuleError("找不到刚摸的那张牌")
        hseq = int(mine["wall_seq"])
        # 原来这里只改 round_hands / round_discards，round_wall 没动
        # → 客户端实体编号（牌面+序号）和真实牌面对不上。统一走 do_swap。
        self.do_swap("hand_river", s, "快手", hand_seq=hseq, river_seq=seq, face_down=True)
        with self.db.tx():
            self.db.conn.execute(
                "UPDATE round_discards SET is_riichi_tile=0 WHERE round_id=? AND seq=?",
                (self.round_id, seq))
        self.mark_skill_used(s, 11, 2)
        self.note_skill(s, 11, 2)
        self.save_flags()
        return {"seat": s, "seq": seq, "got": target, "gave": drawn}

    # ─── 海神（Card12 S1）／X神（Card12 S2）───────────────────────────────
    # ─── 深山/浓雾（19）· 前路/感知（20）· 迷途之家（21）· 先负/友引（22）· 加热（23）
    def owns_cn(self, seat: int, card: int) -> bool:
        name = {19: "_c19_cache", 20: "_c20_cache", 21: "_c21_cache",
                22: "_c22_cache", 23: "_c23_cache"}.get(int(card))
        c = getattr(self, name) if name else None
        if c is None:
            return False
        s = int(seat)
        if s not in c:
            c[s] = skills.owns_card(self.db, self, s, int(card), strict=True)
        return c[s]

    def my_discard_count(self, seat: int, hand_only: bool = False) -> int:
        sql = ("SELECT COUNT(*) FROM round_discards WHERE round_id=? AND seat=?"
               + (" AND is_tsumogiri=0" if hand_only else ""))
        return int(self.db._one(sql, (self.round_id, int(seat))) or 0)

    # 深山：第 12 张之后可开，开着就一直报牌 + 可换
    def shenshan_can(self, seat: int) -> bool:
        if self.is_riichi(int(seat)):
            return False          # 立直后手牌锁定：不再询问会改手牌的技能

        s = int(seat)
        if not self.owns_cn(s, 19):
            return False
        if s in self.shenshan:
            return True
        return self.my_discard_count(s) >= 12

    def shenshan_toggle(self, seat: int) -> dict:
        s = int(seat)
        if not self.owns_cn(s, 19):
            raise RuleError("手里不是这一轮的卡")
        if self.my_discard_count(s) < 12:
            raise RuleError("切出第 12 张牌之后才能开深山")
        if s in self.shenshan:
            self.shenshan.discard(s)
            self.shenshan_offer = None
        else:
            self.shenshan.add(s)
        self.note_use(s, 19, 1)   # 记「发动了」→ 这张卡翻明
        self.save_flags()
        return {"seat": s, "on": s in self.shenshan}

    def shenshan_offer_draw(self, drawer: int, tile: str) -> bool:
        """有人摸牌 → 给开着深山的我报一下"""
        for s in list(self.shenshan):
            if s == int(drawer):
                continue
            self.shenshan_offer = {"seat": s, "from": int(drawer), "tile": str(tile)}
            self.phase = "shenshan"
            self.save_flags()
            return True
        return False

    def shenshan_resolve(self, seat: int, hand_tile: str = "") -> dict:
        s = int(seat)
        off = self.shenshan_offer or {}
        if int(off.get("seat", -1)) != s:
            raise RuleError("现在没有要你决定的牌")
        drawer = int(off.get("from", -1))
        got = str(off.get("tile", ""))
        self.shenshan_offer = None
        if str(hand_tile) == "":
            # 这次不要 → 按「主战先、协战后」继续问下一个（可能就没有了）
            nxt = self._advance_intercept(off)
            self.save_flags()
            return {"seat": s, "skipped": True, "from": drawer, "tile": got,
                    "next": nxt}
        self.phase = "discard"
        tile = str(hand_tile)
        mine = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY wall_seq LIMIT 1", (self.round_id, s, tile))
        if mine is None:
            raise RuleError(f"手里没有 {tile}")
        theirs = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND is_drawn=1 "
            "ORDER BY wall_seq DESC LIMIT 1", (self.round_id, drawer))
        if theirs is None:
            raise RuleError("找不到对方刚摸的牌")
        hseq, tseq = int(mine["wall_seq"]), int(theirs["wall_seq"])
        self.do_swap("hand_hand", s, "深山",
                     seat_a=s, hand_seq_a=hseq, seat_b=drawer, hand_seq_b=tseq)
        self.save_flags()
        return {"seat": s, "from": drawer, "gave": tile, "got": got, "skipped": False}

    # 浓雾：4 巡内别家不能自摸
    def nongwu_can(self, seat: int) -> bool:
        s = int(seat)
        if not self.owns_cn(s, 19) or self.nongwu:
            return False
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        return self.drawn_tile(s) is not None

    def nongwu_activate(self, seat: int) -> dict:
        s = int(seat)
        if not self.owns_cn(s, 19):
            raise RuleError("手里不是这一轮的卡")
        if self.nongwu:
            raise RuleError("浓雾已经放出去了")
        self.nongwu = {"by": s, "left": 4}
        self.note_use(s, 19, 2)   # 记「发动了」→ 这张卡翻明
        self.save_flags()
        return {"seat": s, "left": 4}

    def nongwu_blocks(self, seat: int) -> bool:
        nw = self.nongwu or {}
        return bool(nw) and int(nw.get("by", -1)) != int(seat) and int(nw.get("left", 0)) > 0

    # 前路：预言接下来三张
    def qianlu_can(self, seat: int) -> bool:
        s = int(seat)
        if not self.owns_cn(s, 20) or self.qianlu:
            return False
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        return self.my_discard_count(s) >= 3

    def qianlu_set(self, seat: int, tiles: list[str]) -> dict:
        s = int(seat)
        if not self.owns_cn(s, 20):
            raise RuleError("手里不是这一轮的卡")
        if self.qianlu:
            raise RuleError("前路已经预言过了")
        if self.my_discard_count(s) < 3:
            raise RuleError("3 巡之后才能预言")
        pred = [str(t) for t in (tiles or [])][:3]
        if len(pred) != 3:
            raise RuleError("要预言三张牌")
        self.qianlu = {"seat": s, "pred": pred, "idx": 0}
        self.note_use(s, 20, 1)   # 记「发动了」→ 这张卡翻明
        self.save_flags()
        return {"seat": s, "pred": pred}

    # 感知：看所有听牌玩家的手牌
    def ganzhi_can(self, seat: int) -> bool:
        s = int(seat)
        if not self.owns_cn(s, 20):
            return False
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        return self.drawn_tile(s) is not None and not self.skill_used(s, 20, 2)

    def ganzhi_view(self, seat: int) -> list[dict]:
        s = int(seat)
        if not self.skill_used(s, 20, 2) and not self.ganzhi_can(s):
            return []
        out = []
        for t in range(4):
            if t == s:
                continue
            try:
                rep = tenpai.tenpai_report(self.hand13(t), self.melds(t),
                                           self.tenpai_base(t))
            except Exception:
                continue
            if rep.get("tenpai"):
                out.append({"seat": t, "tiles": [str(x) for x in self.hand(t)]})
        return out

    def reveal_add(self, viewer: int, targets) -> None:
        self.reveal_hands.setdefault(int(viewer), set()).update(int(t) for t in targets)
        self.save_flags()

    def reveal_clear(self, viewer: int) -> None:
        if int(viewer) in self.reveal_hands:
            self.reveal_hands.pop(int(viewer), None)
            self.save_flags()

    def ganzhi_activate(self, seat: int) -> dict:
        s = int(seat)
        if not self.owns_cn(s, 20):
            raise RuleError("手里不是这一轮的卡")
        if self.skill_used(s, 20, 2):
            raise RuleError("感知一轮只能用一次")
        self.mark_skill_used(s, 20, 2)
        view = self.ganzhi_view(s)
        self.reveal_add(s, [v["seat"] for v in view])   # 看牌期间他们手牌对我明置
        return {"seat": s, "view": view}

    # 迷途之家：手切 4/8/12 张依次拿馈赠
    def _gift_check(self, seat: int) -> int:
        s = int(seat)
        if not self.owns_cn(s, 21):
            return 0
        n = self.my_discard_count(s, hand_only=True)
        lv = 0
        if n >= 12:
            lv = 3
        elif n >= 8:
            lv = 2
        elif n >= 4:
            lv = 1
        if lv > int(self.gift.get(s, 0)):
            self.gift[s] = lv
            # 馈赠 3 不再直接给「一定和牌」：改成「听牌时获得」（见 _maybe_grant_yiding）
            self.save_flags()
            return lv
        return 0

    def gift_can(self, seat: int) -> bool:
        if self.is_riichi(int(seat)):
            return False          # 立直后手牌锁定：不再询问会改手牌的技能

        s = int(seat)
        if int(self.gift.get(s, 0)) < 2:
            return False
        if s in self.gift_used:
            return False               # 发动一次为止
        if self.phase not in ("draw", "gift"):
            return False
        if self.turn is None or int(self.turn) != s:
            return False
        return bool(self.gift_targets(s))

    def gift_offer_open(self, seat: int) -> bool:
        """摸牌前自动问一次「要不要换牌」（跳过不清标记，下次继续问）。"""
        if self.gift_offer is not None:
            return False
        if not self.gift_can(int(seat)):
            return False
        key = "%d-%d" % (int(seat), self.turn_count(int(seat)))
        if key in self.gift_asked:
            return False                   # 这一巡已经问过（跳过 → 下次摸牌前再问）
        self.gift_asked.add(key)
        self.phase = "gift"
        self.gift_offer = {"seat": int(seat)}
        self.save_flags()
        return True

    def gift_skip(self, seat: int) -> dict:
        """跳过这一次：不清 armed，下次自己摸牌前还会问。"""
        s = int(seat)
        off = self.gift_offer or {}
        if int(off.get("seat", -1)) == s:
            self.gift_offer = None
            self.phase = "draw"
            self.save_flags()
        return {"seat": s, "skipped": True}

    def gift_targets(self, seat: int) -> list[int]:
        return [int(r["seq"]) for r in self.db._rows(
            "SELECT seq FROM round_discards WHERE round_id=? AND called=0 AND face_down=0 "
            "ORDER BY seq", (self.round_id,))]

    def gift_swap(self, seat: int, hand_tile: str, river_seq: int) -> dict:
        s = int(seat)
        if not self.gift_can(s):
            raise RuleError("馈赠2 只能在自己摸牌前用")
        seq = int(river_seq)
        if seq not in self.gift_targets(s):
            raise RuleError("只能换牌河里的明牌")
        tile = str(hand_tile)
        mine = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY wall_seq LIMIT 1", (self.round_id, s, tile))
        if mine is None:
            raise RuleError(f"手里没有 {tile}")
        row = self.db._row("SELECT wall_seq, tile FROM round_discards WHERE round_id=? AND seq=?",
                           (self.round_id, seq))
        if row is None:
            raise RuleError("这张牌不在牌河里")
        target = str(row["tile"])
        hseq = int(mine["wall_seq"])
        self.do_swap("hand_river", s, "馈赠", hand_seq=hseq, river_seq=seq)
        self.gift_used.add(s)                  # 发动一次为止
        self.gift_offer = None
        self.phase = "draw"
        self.note_use(s, 21, 2)   # 记「发动了」→ 这张卡翻明
        self.save_flags()
        return {"seat": s, "got": target, "gave": tile, "seq": seq}

    # 先负：别人立直的一发巡，换牌 + 立直 → 他出铳
    def xianfu_can(self, seat: int) -> bool:
        s = int(seat)
        if not self.owns_cn(s, 22):
            return False
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None or self.is_riichi(s):
            return False
        if self.xianfu_armed is not None and int(self.xianfu_armed) == s:
            return False                     # 已经换过了，必须去立直
        others = [t for t in range(4) if t != s and self.is_riichi(t) and t in self.ippatsu]
        return bool(others) and bool(self.gift_targets(s))

    def xianfu_swap(self, seat: int, hand_tile: str, river_seq: int) -> dict:
        s = int(seat)
        if not self.xianfu_can(s):
            raise RuleError("只有别人立直的一发巡、自己打牌前才能用先负")
        r = self.gift_swap_like(s, hand_tile, river_seq)
        self.xianfu_armed = s
        self.note_use(s, 22, 1)   # 记「发动了」→ 这张卡翻明
        self.save_flags()
        return r

    def gift_swap_like(self, s: int, hand_tile: str, river_seq: int) -> dict:
        """手牌 ↔ 牌河明牌（先负/馈赠共用）"""
        seq = int(river_seq)
        if seq not in self.gift_targets(s):
            raise RuleError("只能换牌河里的明牌")
        tile = str(hand_tile)
        mine = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY wall_seq LIMIT 1", (self.round_id, s, tile))
        if mine is None:
            raise RuleError(f"手里没有 {tile}")
        row = self.db._row("SELECT wall_seq, tile FROM round_discards WHERE round_id=? AND seq=?",
                           (self.round_id, seq))
        if row is None:
            raise RuleError("这张牌不在牌河里")
        target = str(row["tile"])
        hseq = int(mine["wall_seq"])
        self.do_swap("hand_river", s, "馈赠/先负", hand_seq=hseq, river_seq=seq)
        return {"seat": s, "got": target, "gave": tile, "seq": seq}

    def first_riichi_seat(self, exclude: int = -1) -> int:
        """最先立直的那家（按立直宣言牌的牌河 seq）。只算还在「一发巡」里的。"""
        row = self.db._row(
            "SELECT seat FROM round_riichi WHERE round_id=? AND ippatsu=1 AND seat<>? "
            "ORDER BY declared_seq LIMIT 1", (self.round_id, int(exclude)))
        if row is not None:
            return int(row["seat"])
        row = self.db._row(
            "SELECT seat FROM round_riichi WHERE round_id=? AND seat<>? "
            "ORDER BY declared_seq LIMIT 1", (self.round_id, int(exclude)))
        return int(row["seat"]) if row is not None else -1

    def _xianfu_settle(self, declarer: int) -> dict:
        me = int((self.xianfu_pending or {}).get("seat", -1))
        self.xianfu_pending = None
        self.xianfu_armed = None
        self.save_flags()
        res = self._judge_best_kind(me, tsumo=False, riichi=True, ippatsu=True)
        if res is None:
            pays = score.payments(1, 30, is_dealer=(me == self.dealer), tsumo=False)
            res = {"yaku": [{"name": "先负（立直·一发）", "han": 1}], "han": 1, "fu": 30,
                   "pays": pays, "fu_items": [("先负（固定）", 30)]}
        self._finish(me, int(declarer), "ron", res)
        return self._event("xianfu", {"seat": me, "from": int(declarer),
                                      "yaku": res.get("yaku"), "han": res.get("han"),
                                      "fu": res.get("fu"), "points": res.get("pays")})

    # ─── Card24 S1「一发」──────────────────────────────────────────
    def _wall_kinds_remaining(self) -> set[str]:
        """牌山 + 王牌里**还没被拿走**的牌种（一发只认这些）。"""
        rows = self.db._rows(
            "SELECT tile FROM round_wall WHERE round_id=? AND dealt_to IS NULL",
            (self.round_id,))
        return {kind_of(str(r["tile"])) for r in rows}

    def _c24_wall_wins(self, seat: int) -> list[str]:
        """我的胡张里，有哪些现在还在牌山/王牌里（= 一发能摸到）。"""
        s = int(seat)
        base = self.hand13(s)                 # 13 张（已去掉刚摸那张）
        melds = self.melds(s)
        wall = self._wall_kinds_remaining()
        out: list[str] = []
        for kind in TILE_KINDS:
            if kind not in wall:
                continue
            if agari.is_winning(counts_of(base + [kind]), melds):
                out.append(kind)
        return out

    def c24_can(self, seat: int) -> bool:
        """一发能不能点：摸牌后 + 现在是「可立直」状态（立直判断机）。"""
        s = int(seat)
        if not self.owns_card24(s):
            return False
        if self.skill_used(s, 24, 1):         # 本小局用完一次
            return False
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None:
            return False
        if self.is_riichi(s):
            return False
        return self.can_riichi(s)

    def c24_declare(self, seat: int, tile: str) -> dict:
        """用默认方式面板选中的那张：横置打出 + 立直；再看牌山里有没有我的胡张。"""
        s = int(seat)
        if not self.c24_can(s):
            raise RuleError("一发：要刚摸完牌、而且现在是能立直的状态")
        t = str(tile)
        if t not in self.riichi_discards(s):
            raise RuleError("一发：这张打出去就不听牌了")
        ev = self._do_riichi(s, t)            # 横置打出 + 进立直（含破发窗口等）
        hit = self._c24_wall_wins(s)
        self.c24_armed = s if hit else -1
        # op 级已经问过看破了 → 这里 gate=False（否则会挂第二笔，死锁）
        self.note_use(s, 24, 1, once=True, gate=False)
        self.save_flags()
        out = {"seat": s, "tile": t, "riichi": True,
               "ippatsu_on": self.c24_armed == s, "wins": sorted(hit),
               "event": (ev or {}).get("event", "")}
        return out

    def c24_win_can(self, seat: int) -> bool:
        """轮到自己摸牌、立直 + 一发巡、而且牌山/王牌里确实还有我的胡张。"""
        s = int(seat)
        if int(self.c24_armed) != s:
            return False
        if not self.is_riichi(s) or s not in self.ippatsu:
            return False
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None:
            return False
        return bool(self._c24_wall_wins(s))

    def _c24_best_win(self, seat: int) -> tuple[str, dict] | None:
        """一发结算：在「牌山/王牌里有的胡张 + 刚摸的这张」里挑打点最高的结算。

        做法：临时把刚摸的那张换成候选牌 → 复用 `_judge_win`（宝牌/里宝/立直/一发
        全按正常口径算）→ 再换回来。
        """
        s = int(seat)
        row = self.db._row(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? AND is_drawn=1 "
            "ORDER BY wall_seq DESC LIMIT 1", (self.round_id, s))
        if row is None:
            return None
        drawn_kind = str(row["tile"])
        wall = self._wall_kinds_remaining()
        base = self.hand13(s)
        melds = self.melds(s)
        cands: list[str] = []
        for kind in TILE_KINDS:
            # 刚摸的这张本身当然也在手里，算候选；其余必须是牌山/王牌里还有的
            if kind != drawn_kind and kind not in wall:
                continue
            if agari.is_winning(counts_of(base + [kind]), melds):
                cands.append(kind)
        if not cands:
            return None
        ws = int(row["wall_seq"])
        best: tuple[int, str, dict] | None = None
        try:
            for kind in cands:
                with self.db.tx():
                    self.db.conn.execute(
                        "UPDATE round_hands SET tile=? WHERE round_id=? AND wall_seq=?",
                        (kind, self.round_id, ws))
                res = self._judge_win(s, kind, tsumo=True)
                if not res:
                    continue
                total = int((res.get("pays") or {}).get("total", 0))
                if best is None or total > best[0]:
                    best = (total, kind, res)
        finally:
            with self.db.tx():
                self.db.conn.execute(
                    "UPDATE round_hands SET tile=? WHERE round_id=? AND wall_seq=?",
                    (drawn_kind, self.round_id, ws))
        if best is None:
            return None
        return best[1], best[2]

    # ─── Card24 S2「未来」：调接下来的 5 张牌山 ──────────────────────
    def _future_seqs(self) -> list[int]:
        """接下来要摸的 5 张牌的物理 seq（按摸牌顺序）。"""
        out: list[int] = []
        nxt = self.next_no
        first = self.wall_first_stack()
        for _ in range(FUTURE_N):
            no = wallmodel.next_live_no(nxt, first)
            if no is None:
                break
            out.append(wallmodel.seq_of_tile(no))
            nxt = wallmodel.wrap_tile(no + 1)
        return out

    def _future_wall_tiles(self) -> list[str]:
        tiles: list[str] = []
        for sq in self._future_seqs():
            row = self.db._row("SELECT tile FROM round_wall WHERE round_id=? AND seq=?",
                               (self.round_id, int(sq)))
            tiles.append(str(row["tile"]) if row else "")
        return tiles

    def future_can(self, seat: int) -> bool:
        """未来能不能「发动」：轮到我摸牌之前 + 持 24 号卡 + 本小局没用过 + 牌山还够 5 张。"""
        s = int(seat)
        if int(self.future_armed) == s:
            return False                     # 已经发动了，正在排序
        if not self.owns_card24(s):
            return False
        if self.skill_used(s, 24, 2):
            return False
        if self.phase != "draw" or self.turn is None or int(self.turn) != s:
            return False
        if self.round_phase == "deal" or self.phase == "ended":
            return False
        if self.live_left() < FUTURE_N:
            return False
        return not bool(self.deal_flow)

    def future_view(self, seat: int) -> list[str]:
        """给发动者看的「接下来 5 张」——**发动之后才给**（询问阶段不亮牌）。"""
        if int(self.future_armed) != int(seat):
            return []
        return self._future_wall_tiles()

    def future_arm(self, seat: int) -> dict:
        """点技能图标 = **直接发动**（这一刻就是发动点，op 层会先问看破）→ 之后才选牌。"""
        s = int(seat)
        if int(self.future_armed) == s:
            return {"ok": True, "already": True, "armed": True,
                    "tiles": self._future_wall_tiles()}
        if not self.future_can(s):
            raise RuleError("未来：只能在轮到你摸牌之前发动（本小局一次）")
        if len(self._future_seqs()) < FUTURE_N:
            raise RuleError("未来：牌山剩下的牌不够 5 张")
        self.future_armed = s
        self.future_deadline = time.time() + FUTURE_TIMEOUT
        self.note_use(s, 24, 2, gate=False)      # 真发动了：播报 + 翻卡 + 记「本小局用过」
        self.save_flags()
        return {"ok": True, "armed": True, "tiles": self._future_wall_tiles()}

    def future_timeout(self) -> bool:
        """已经发动、却一直没排序 → 超时（客户端没反应）。"""
        if int(self.future_armed) < 0:
            return False
        dl = float(self.future_deadline or 0)
        return dl > 0.0 and time.time() > dl

    def future_abort(self) -> None:
        """超时兜底：放弃这次重排（技能已经算用掉），把摸牌放出来。"""
        self.future_armed = -1
        self.future_deadline = 0.0
        self.save_flags()

    def future_set(self, seat: int, order: list[int]) -> dict:
        """按玩家排的顺序重写这 5 张的位置。order[i] = 新的第 i+1 张取原来第几张（0 起）。"""
        s = int(seat)
        if int(self.future_armed) != s:
            raise RuleError("未来：先点技能图标发动（发动之后才能排序）")
        seqs = self._future_seqs()
        if len(seqs) != FUTURE_N:
            raise RuleError("未来：牌山剩下的牌不够 5 张")
        want = [int(x) for x in (order or [])]
        if sorted(want) != list(range(FUTURE_N)):
            raise RuleError("未来：要把 5 张都排上（每张用一次）")
        tiles = self._future_wall_tiles()
        if any(t == "" for t in tiles):
            raise RuleError("未来：读不到牌山（这一手作废）")
        with self.db.tx():
            for i, sq in enumerate(seqs):
                self.db.conn.execute(
                    "UPDATE round_wall SET tile=? WHERE round_id=? AND seq=?",
                    (tiles[want[i]], self.round_id, int(sq)))
        self.future_armed = -1                   # 排序完成
        self.future_deadline = 0.0
        self.save_flags()
        return {"seat": s, "tiles": [tiles[i] for i in want], "order": want}

    # ─── 21S2 段2：摸牌前自动问「换牌」────────────────────────────
    # （放在 _advance 里，见下面的调用；跳过不清标记，下次继续问）


    # 友引（22S2）：四副露单骑 → 牌河代摸牌
    def youyin_swap_can(self, seat: int) -> bool:
        if self.is_riichi(int(seat)):
            return False          # 立直后手牌锁定：不再询问会改手牌的技能

        s = int(seat)
        if s in self.no_win:
            return False
        if not self.owns_cn(s, 22):
            return False
        if len(self.melds(s)) != 4 or len(self.hand(s)) != 2:
            return False
        # 时机：摸完牌之后（摸牌前不算）
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        return self.drawn_tile(s) is not None

    # ─── Card29 S1【加速】：无视距离吃，且压过碰 ─────────────────────
    def _owns29s1(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 29, strict=True)

    def c29s1_can(self, seat: int, tile: str = "") -> bool:
        """这一家现在能不能被问【加速】（tile 为空 = 只问「有没有这张卡」）。"""
        s = int(seat)
        if self.is_riichi(s) or s in self.no_win:
            return False
        if f"{s}:29:1" in self.poked or f"{s}:29" in self.poked:
            return False                     # 被看破剔除
        if not self._owns29s1(s):
            return False
        if not tile:
            return True
        return bool(calls.chi_options(self.hand(s), str(tile)))

    def _c29s1_gate(self, discard_seq: int, tile: str, from_seat: int) -> bool:
        """打出一张明牌之后、开鸣牌窗口之前：先问【加速】。

        返回 True = 已经挂起询问（这次先不开普通鸣牌窗口）。
        荣和永远是最高优先级 —— 只要有任何人能荣和，加速就不问。
        """
        if self.c39s1_on:
            return False                     # 【隐形】：谁都不能吃这张
        if not tile or int(discard_seq) < 0:
            return False
        for s in range(4):
            if int(s) == int(from_seat):
                continue
            if self._win_ok(s, str(tile), tsumo=False):
                return False                 # 有人能荣和 → 让荣和先走
        cands = [s for s in range(4)
                 if int(s) != int(from_seat) and self.c29s1_can(s, str(tile))]
        cands.sort(key=lambda s: (int(s) - int(from_seat)) % 4)   # 下家 → 对家 → 上家
        cands = [s for s in cands
                 if ("%d:%d" % (int(s), int(discard_seq))) not in self.c29s1_asked]
        if not cands:
            return False
        s = int(cands[0])
        self.c29s1_asked.add("%d:%d" % (s, int(discard_seq)))
        self.c29s1_offer = {"seat": s, "tile": str(tile),
                            "discard_seq": int(discard_seq), "from": int(from_seat),
                            "choices": calls.chi_options(self.hand(s), str(tile))}
        self.phase = "c29s1"
        self.save_flags()
        return True

    def _c29s1_continue(self) -> dict:
        """这一笔结束了（跳过 / 被看破）：问下一个候选；没人了就走普通鸣牌窗口。"""
        off = self.c29s1_offer or {}
        self.c29s1_offer = None
        tile = str(off.get("tile", ""))
        dseq = int(off.get("discard_seq", -1))
        fr = int(off.get("from", -1))
        if dseq < 0 or tile == "" or fr < 0:
            self.phase = "discard"
            self.save_flags()
            return self._event("c29s1_end", {})
        if self._c29s1_gate(dseq, tile, fr):
            return self._event("c29s1_ask",
                               {"seat": int((self.c29s1_offer or {}).get("seat", -1))})
        # ★ save_flags 必须在 _open_claim_window **之后**：
        #   它会改 phase（claim / draw），而 phase 只存在 flags 里。
        #   以前先在前面存了一次 → 库里留下「phase=c29s1 + offer=null」→ 下一个进程读回来直接卡死。
        self._open_claim_window(dseq, tile, fr)
        self.save_flags()
        return self._event("c29s1_end", {})

    def c29s1_skip(self, seat: int) -> dict:
        """点「跳过」= 不发动这次加速，回到普通鸣牌窗口。"""
        off = self.c29s1_offer or {}
        if self.phase != "c29s1" or int(off.get("seat", -1)) != int(seat):
            raise RuleError("现在没有要你决定的加速")
        return self._c29s1_continue()

    def c29s1_chi(self, seat: int, tiles: list[str] | None = None) -> dict:
        """点「吃」= 发动加速（这一下就是发动时机，看破在 op 层问过了）。

        无视距离，其余和普通吃完全一样（食い替え、暗置、副露摆放都照常）。
        """
        s = int(seat)
        off = self.c29s1_offer or {}
        if self.phase != "c29s1" or int(off.get("seat", -1)) != s:
            raise RuleError("现在没有要你决定的加速")
        tile = str(off.get("tile", ""))
        dseq = int(off.get("discard_seq", -1))
        fr = int(off.get("from", -1))
        opts = calls.chi_options(self.hand(s), tile)
        if not opts:
            raise RuleError("手里没有能吃这张的搭子")
        pool = [str(t) for t in (tiles or [])]
        if pool:
            if sorted(pool) not in [sorted(o) for o in opts]:
                raise RuleError("这组搭子吃不了这张牌")
        elif len(opts) == 1:
            pool = list(opts[0])
        else:
            raise RuleError("有多组搭子，先选一组")
        self._assert_hand_mutable(s)
        self.c29s1_offer = None
        p = {"discard_seq": dseq, "tile": tile, "from": fr}
        self._apply_claim(s, "chi", pool, p)
        self._youyin_disarm(s, "chi")
        # 不限次数：不写 used_skills（只翻卡面 + 播报）
        self.note_use(s, 29, 1, once=False, gate=False)
        self.save_flags()
        return {"seat": s, "tile": tile, "tiles": pool, "from": fr}


    def youyin_meld_can(self, seat: int) -> bool:
        """友引段1 能点吗：正好出现「吃/碰/明杠」按钮，或者自己切牌时能加杠/暗杠。

        （用户口径：加杠 / 暗杠的选择窗口里也能点；杠完要摊面子，
          补岭上牌一律推迟到摊完之后。）
        """
        s = int(seat)
        if not self.owns_cn(s, 22):
            return False
        if self.is_riichi(s) or s in self.no_win:
            return False
        if self.youyin_meld_armed == s or s in self.youyin_meld_done:
            return False                     # 已经点过了 / 本小局用过了
        p = self.pending or {}
        if p and self.phase == "claim":
            if s not in (p.get("options") or {}) or s in (p.get("answers") or {}):
                return False
            acts = {str(a.get("action", "")) for a in (p["options"][s] or [])}
            return bool(acts & {"chi", "pon", "minkan"})
        # 我的切牌时：能加杠 / 暗杠 也可以点（杠完摊面子）
        if self.phase == "discard" and self.turn is not None and int(self.turn) == s:
            for a in self.legal_actions(s):
                if str(a.get("action", "")) in ("kakan", "ankan"):
                    return True
        return False

    def youyin_meld_arm(self, seat: int) -> dict:
        """在鸣牌窗口里点技能：先记「这个人副露完要把手里的面子一起摊出来」。"""
        s = int(seat)
        if not self.youyin_meld_can(s):
            raise RuleError("现在不是友引的副露时机（要正好出现吃/碰按钮）")
        self.youyin_meld_armed = s
        # 只翻卡面 + 播报：不写 used_skills（段2 还要能用），也不再问看破（会挂第二笔）
        self.note_use(s, 22, 2, once=False, gate=False)
        self.save_flags()
        return {"seat": s, "armed": True}

    def youyin_meld_sets(self, seat: int, tiles: list[str]) -> list[list[str]]:
        """**只接受正好一组面子**：3 张（刻子 / 顺子）或 4 张（同种 = 杠）。

        （用户口径：一次选一组，摊完继续判断，直到手里没有面子。）
        """
        pool = [str(t) for t in tiles]
        hand = list(self.hand(int(seat)))
        for t in pool:                        # 必须都是手里的牌
            if t not in hand:
                raise RuleError("无效副露！")
            hand.remove(t)
        if len(pool) not in (3, 4):
            raise RuleError("无效副露！")
        ks = [kind_of(t) for t in pool]
        ks = ["5" + k[1:] if k[:1] == "0" else k for k in ks]   # 红 5 当归 5
        if len(pool) == 4:
            if len(set(ks)) != 1:
                raise RuleError("无效副露！")                    # 4 张必须同种（杠）
            return [pool]
        if len(set(ks)) == 1:
            return [pool]                                        # 刻子
        suites = {k[-1:] for k in ks}
        nums = sorted(int(k[:-1]) for k in ks)
        if (len(suites) == 1 and suites.pop() in ("m", "p", "s")
                and nums[1] == nums[0] + 1 and nums[2] == nums[0] + 2):
            return [pool]                                        # 顺子
        raise RuleError("无效副露！")

    @staticmethod
    def _youyin_has_mianzi(hand) -> bool:
        """手里还有没有一组面子：3 张同种 / 3 张连续同花色 / 4 张同种。"""
        cnt: dict[str, int] = {}
        for t in hand:
            k = kind_of(t)
            if k[:1] == "0":
                k = "5" + k[1:]
            cnt[k] = cnt.get(k, 0) + 1
        if any(v >= 3 for v in cnt.values()):
            return True
        for k in cnt:
            suite = k[-1:]
            if suite not in ("m", "p", "s"):
                continue
            n = int(k[:-1])
            if n < 1 or n > 7:
                continue
            if all(("%d%s" % (n + d, suite)) in cnt for d in (0, 1, 2)):
                return True
        return False

    def _youyin_disarm(self, meld_seat: int = -1, kind: str = "") -> None:
        """鸣牌窗口结算完了：点了友引但没真的副露 → 清掉「开启状态」。

        用户口径：发动后进入开启状态，**claim 结算时清掉**。
        不清的话：本小局段1 再也点不了，而且十几巡之后随便一次吃/碰会突然摊面子。
        """
        a = int(self.youyin_meld_armed)
        if a < 0:
            return
        if a == int(meld_seat) and str(kind) in ("chi", "pon", "minkan"):
            return                                  # 他真副露了 → 交给 _apply_claim
        self.youyin_meld_armed = -1
        self.save_flags()

    def _youyin_open_offer(self, seat: int) -> None:
        """进入「选一组面子」这一步（每次进入都重置超时）。"""
        s = int(seat)
        self.phase = "youyin_meld"
        self.youyin_meld_offer = {"seat": s}
        self.turn = s
        self.youyin_meld_deadline = time.time() + YOUYIN_MELD_TIMEOUT
        self.save_flags()

    def _youyin_finish(self, seat: int) -> None:
        """摊面子收尾：清状态、补被推迟的岭上牌/宝牌、回到正常打牌。"""
        s = int(seat)
        self.youyin_meld_offer = None
        self.youyin_meld_armed = -1
        self.youyin_meld_done.add(s)
        self.youyin_meld_deadline = 0.0
        self.phase = "discard"
        self.turn = s
        # 这一手是「杠」：摊完面子才补岭上牌 + 翻宝牌（补的牌不能被技能副露出去）
        if s in self.pending_rinshan:
            self.pending_rinshan.discard(s)
            self.reveal_dora()
            got = self._draw_rinshan(s)
            if got is None:
                self.save_flags()
                self._ryuukyoku("exhaustive")
                return
            self.last_was_rinshan = True
            owner = self._self_wind_owner(s, got)
            if owner is not None and (self.c34_muted(int(s)) or self.c34_muted(int(owner))):
                owner = None                   # 【厄运】：自风三巡内无效
            if owner is not None:
                self.wind_swap = {"owner": int(owner), "from": s, "tile": got}
                self.phase = "wind_swap"
            if self._check_abortive():
                return
        with self.db.tx():
            self.db.conn.execute("UPDATE rounds SET turn_seat=? WHERE round_id=?",
                                 (s, self.round_id))
        self.save_flags()

    def _youyin_next_offer(self, seat: int) -> None:
        """摊完一组：手里还有面子就继续问，没有就结算完成（顺手补岭上牌）。"""
        s = int(seat)
        if self._youyin_has_mianzi(self.hand(s)):
            self._youyin_open_offer(s)
            return
        self._youyin_finish(s)

    def youyin_meld_timeout(self) -> bool:
        """摊面子阶段等太久了？→ 服务端自己收尾，不能让全桌永久停住。"""
        if self.phase != "youyin_meld" or self.youyin_meld_offer is None:
            return False
        dl = float(self.youyin_meld_deadline or 0.0)
        return dl > 0.0 and time.time() > dl

    def youyin_meld_skip(self) -> dict | None:
        """超时 / 没人操作 → 不再摊，直接收尾。

        用户口径：摊面子期间玩家不操作，**不要**替他自动摊第一组，所以这里是收尾。
        """
        off = self.youyin_meld_offer or {}
        s = int(off.get("seat", -1))
        if s < 0 or self.phase != "youyin_meld":
            return None
        self._youyin_finish(s)
        return self._event("youyin_meld_end", {"seat": s, "timeout": True})

    def youyin_meld_pick(self, seat: int, tiles: list[str]) -> dict:
        """副露之后：把选中的 1~3 组面子一起摊出来（全部竖置、明置）。"""
        s = int(seat)
        off = self.youyin_meld_offer or {}
        if int(off.get("seat", -1)) != s:
            raise RuleError("现在不是友引摊面子的时机")
        groups = self.youyin_meld_sets(s, tiles)
        for g in groups:
            self.db.meld(self.round_id, s, "open_set", list(g), called_tile="",
                         from_seat=-1, from_discard_seq=None, rot_index=-1)
        # ★ 这里**不能**再 note_use(22,2)：会再挂一笔看破 → 全桌卡死
        self._youyin_next_offer(s)
        return {"seat": s, "groups": groups, "n": len(groups),
                "more": self.youyin_meld_offer is not None}

    def youyin_offer_open(self, seat: int) -> bool:
        """【已废弃·别再调用】友引段2 是**主动**技能：只在点图标时进面板换牌。

        用户口径（2026-10-27）：友引两个效果都是主动技能，不需要询问。
        所以这里不再自动挂 offer（`youyin_swap_can` 直接当「图标能点」的判据），
        函数留着只是为了万一回退；目前**没有任何调用点**。
        """
        # 下面这行起是原实现（保留）
        
        if not self.youyin_swap_can(seat):
            return False
        key = "%d-%d" % (int(seat), self.turn_count(int(seat)))
        if key in self.youyin_asked:
            return False                     # 这一巡已经问过了（跳过就别再弹）
        self.youyin_asked.add(key)
        self.youyin_offer = {"seat": int(seat)}
        self.save_flags()
        return True

    def youyin_take(self, seat: int, river_seq: int = -1, hand: str = "") -> dict:
        """四副露后（摸完牌）主动发动：一张手牌 ↔ 全场牌河里的一张明牌。"""
        s = int(seat)
        if not self.youyin_swap_can(s) and int((self.youyin_offer or {}).get("seat", -1)) != s:
            raise RuleError("现在不是友引的换牌时机（要四副露、刚摸完牌）")
        self.youyin_offer = None
        if int(river_seq) < 0:
            self.save_flags()
            return {"seat": s, "skipped": True}
        row = self.db._row(
            "SELECT seq, wall_seq, tile, called, face_down FROM round_discards "
            "WHERE round_id=? AND seq=?", (self.round_id, int(river_seq)))
        if row is None or int(row["called"] or 0) or int(row["face_down"] or 0):
            raise RuleError("只能从牌河里挑一张明牌")
        tile = str(row["tile"])
        hand_tile = str(hand)
        if hand_tile == "":
            raise RuleError("要选一张手牌")
        mine = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY wall_seq LIMIT 1", (self.round_id, s, hand_tile))
        if mine is None:
            raise RuleError(f"手里没有 {hand_tile}")
        # 手牌 ↔ 牌河那张，互换（张数不变），换完照常切牌、可自摸
        self.do_swap("hand_river", s, "友引", hand_seq=int(mine["wall_seq"]),
                     river_seq=int(river_seq), face_down=False)
        self.note_use(s, 22, 2)   # 记「发动了」→ 这张卡翻明
        self.phase = "discard"
        self.turn = s
        self.save_flags()
        return {"seat": s, "got": tile, "seq": int(river_seq), "skipped": False}

    # 加热（23S1）
    def heat_can(self, seat: int) -> bool:
        s = int(seat)
        if not self.owns_cn(s, 23) or self.heat_kind:
            return False
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        return self.drawn_tile(s) is not None

    def heat_activate(self, seat: int, kind: str) -> dict:
        s = int(seat)
        if not self.owns_cn(s, 23):
            raise RuleError("手里不是这一轮的卡")
        k = str(kind)
        if k in WARM_KINDS:
            raise RuleError("加热只能选冷系牌")
        if self.heat_kind:
            raise RuleError("这一局已经加热过了")
        self.heat_kind = k
        self.mark_skill_used(s, 23, 1)
        self.save_flags()
        return {"seat": s, "kind": k}

    def _cold_count(self, seat: int) -> int:
        tiles = [str(t) for t in self.hand(int(seat))]
        for m in self.melds(int(seat)):
            tiles += [str(x) for x in (m.get("tiles") or [])]
        return sum(1 for t in tiles if t in COLD_KINDS)

    # ─── 传承（16S1）／多面（16S2）／研究（17S1）／看破（17S2）／枷锁（18S1）／连接（18S2）
    def owns_c(self, seat: int, card: int) -> bool:
        cache_name = {16: "_c16_cache", 17: "_c17_cache", 18: "_c18_cache"}.get(int(card))
        c = getattr(self, cache_name) if cache_name else None
        if c is None:
            return False
        s = int(seat)
        if s not in c:
            c[s] = skills.owns_card(self.db, self, s, int(card), strict=True)
        return c[s]

    def _skill_log_add(self, seat: int, card: int, skill: int) -> None:
        row = self.db._row("SELECT value FROM meta WHERE key='skill_log'")
        try:
            lst = json.loads(row["value"]) if row else []
        except (ValueError, TypeError):
            lst = []
        item = {"seat": int(seat), "card": int(card), "skill": int(skill),
                "wind": self.round_wind, "number": int(self.round["number"])}
        if item not in lst:                       # 去重：同一次发动被记两遍
            lst.append(item)
        lst = lst[-400:]
        with self.db.tx():
            self.db.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('skill_log', ?)",
                                (json.dumps(lst, ensure_ascii=False),))

    def chuancheng_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None or self.skill_used(s, 16, 1):
            return False
        if not self.owns_c(s, 16):
            return False
        return bool(self.chuancheng_list(s))

    def chuancheng_list(self, seat: int = 0) -> list[dict]:
        """整个半庄宣告过的技能（去重），包括已经失效的"""
        row = self.db._row("SELECT value FROM meta WHERE key='skill_log'")
        if not row:
            return []
        try:
            lst = json.loads(row["value"]) or []
        except (ValueError, TypeError):
            return []
        out, seen = [], set()
        for it in lst:
            if int(it.get("seat", -1)) != int(seat):
                continue                       # 只能复制「我」宣告过的
            key = (int(it.get("card", 0)), int(it.get("skill", 0)))
            if key in seen:
                continue
            if key == (16, 1):
                continue
            seen.add(key)
            out.append({"card": key[0], "skill": key[1],
                        "name": skills.info(key[0], key[1]).get("name",
                                                                "%d-%d" % key)})
        return out

    def chuancheng_use(self, seat: int, card: int, skill: int) -> dict:
        s = int(seat)
        if self.skill_used(s, 16, 1):
            raise RuleError("传承一轮只能用一次")
        if not self.owns_c(s, 16):
            raise RuleError("手里不是这一轮的卡")
        if (int(card), int(skill)) == (16, 1):
            raise RuleError("不能复制传承自己")
        ok = {(int(x["card"]), int(x["skill"])) for x in self.chuancheng_list(s)}
        if (int(card), int(skill)) not in ok:
            raise RuleError("这个技能这半庄还没人宣告过")
        # 16 号卡从此「就是」这个技能（用户口径）：state 下发给客户端换图标，
        # granted 让 skills.owns_card() 认这张卡，发动时走原技能的 op。
        self.cc_copy[s] = {"card": int(card), "skill": int(skill)}
        self.granted.setdefault(s, set()).add(int(card))
        self.cc_grants.add(f"{int(card)}-{int(skill)}-{s}")   # 复制品：独立配额
        # 复制来的技能要能**再用一次**：这个技能本来因为「已经用掉」才进了复制清单，
        # 不清掉 used_skills 的话，can 判定会一直是「本局已经用过了」。
        self._cc_reset_skill(s, int(card), int(skill))
        self.mark_skill_used(s, 16, 1)          # 只表示「传承这一手用掉了」
        self.save_flags()
        return {"seat": s, "card": int(card), "skill": int(skill)}

    def _cc_reset_skill(self, seat: int, card: int, skill: int) -> None:
        """传承复制过来的技能：把「已用过」的痕迹清掉，让它重新可用一次。"""
        s = int(seat)
        # 不再 discard 原技能那条记录：复制品有自己的配额（cc_grants/used_copy）
        # 各技能自己的一次性 / 每回合状态
        if (int(card), int(skill)) == (7, 1):        # 降神：可以重新掷骰
            self.oracle.pop(s, None)
        elif (int(card), int(skill)) == (15, 1):     # 钓鱼：解锁
            self.diaoyu_locked = False
        elif (int(card), int(skill)) == (17, 1):     # 研究：可以重新看
            self.yanjiu.pop(s, None)
        elif (int(card), int(skill)) == (18, 1):     # 枷锁：可以重新定
            self.jiasuo.pop(s, None)
        elif (int(card), int(skill)) == (18, 2):     # 连接：可以重新连
            self.link.pop(s, None)
        elif (int(card), int(skill)) == (21, 1):     # 迷途之家：馈赠等级重来
            self.gift.pop(s, None)
        elif (int(card), int(skill)) == (9, 1):      # 间合：轮换状态清零
            self.c09_next.pop(s, None)
        elif (int(card), int(skill)) == (23, 1):     # 加热：清掉已选牌种
            if int(getattr(self, "heat_seat", -1)) == s:
                self.heat_kind = ""
        self.save_flags()

    def _multi_face(self, seat: int, result: str) -> int:
        """和牌前那 13 张听的牌种数"""
        s = int(seat)
        base = list(self.hand(s))
        if result == "tsumo":
            d = self.drawn_tile(s)
            if d is not None and d in base:
                base.remove(d)
        n = 0
        for kind in TILE_KINDS:
            try:
                if agari.is_winning(counts_of(base + [kind]), self.melds(s)):
                    n += 1
            except Exception:
                continue
        return n

    def yanjiu_can(self, seat: int) -> bool:
        """研究：配牌阶段（和降神/风神/南风同一个窗口）"""
        s = int(seat)
        if s in self.yanjiu or self.skill_used(s, 17, 1):
            return False
        if not self.owns_cn(s, 17):
            return False
        return self.phase == "deal_skill" and s in self.deal_wait

    def _start_yanjiu(self, seat: int, card: int, skill: int) -> dict:
        """配牌阶段：摇骰子决定看谁的手牌，本局随时看"""
        s = int(seat)
        r = self.yanjiu_activate(s)
        self.deal_wait.discard(s)
        self.deal_used.add(s)
        self.save_flags()
        self._maybe_close_deal()
        r.update({"ok": True, "card": int(card), "skill": int(skill), "used": True,
                  "pending": sorted(self.deal_wait)})
        return r

    def yanjiu_activate(self, seat: int) -> dict:
        s = int(seat)
        if not self.owns_c(s, 17):
            raise RuleError("手里不是这一轮的卡")
        if self.skill_used(s, 17, 1):
            raise RuleError("研究一轮只能用一次")
        a, b = random.randint(1, 6), random.randint(1, 6)
        target = (s - 1) % 4 if (a + b) % 2 == 1 else (s + 1) % 4
        self.yanjiu[s] = int(target)
        self.mark_skill_used(s, 17, 1)
        # 「研究」是看牌者的私密信息：只给发动者自己看
        self.reveal_hands.setdefault(s, set()).add(int(target))
        self.save_flags()
        return {"dice": [a, b], "seat": s, "target": int(target),
                "tiles": [str(t) for t in self.hand(int(target))]}

    def kangpo_can(self, seat: int) -> bool:
        s = int(seat)
        if self.skill_used(s, 17, 2) or not self.owns_c(s, 17):
            return False
        return s not in self.no_win

    def kangpo_skip(self, seat: int) -> dict:
        """【兼容壳】放行我这一条询问。"""
        s0 = int(seat)
        mine = self._kangpo_my_ask(s0)
        self.act_answer(s0, int(mine.get("id", -1)), "pass")
        return {"skipped": True}

    def kangpo_list(self, seat: int) -> list[dict]:
        """这一局所有技能（含被动），供选一个剔除"""
        out = []
        for (c, k), info in sorted(skills.REGISTRY.items()):
            if (c, k) == (17, 2):
                continue
            out.append({"card": int(c), "skill": int(k),
                        "name": info.get("name", "%d-%d" % (c, k)),
                        "timing": info.get("timing", "")})
        return out

    def kangpo_poke(self, seat: int, target: int, card: int, skill: int) -> dict:
        s, t = int(seat), int(target)
        if not self.kangpo_can(s):
            raise RuleError("看破一轮只能用一次，或者本局已经不能和牌了")
        if t == s:
            raise RuleError("不能看破自己")
        self.poked.add(f"{t}:{int(card)}:{int(skill)}")
        self.poked.add(f"{t}:{int(card)}")          # 同卡技能一起剔除（简化）
        self.no_win.add(s)
        if int((self.kangpo_ask or {}).get("owner", -1)) == s:
            self.kangpo_ask = None
        self.mark_skill_used(s, 17, 2)
        self.save_flags()
        return {"seat": s, "target": t, "card": int(card), "skill": int(skill)}

    def jiasuo_can(self, seat: int) -> bool:
        s = int(seat)
        if s in self.jiasuo or not self.owns_c(s, 18):
            return False
        return self.round_phase == "deal" or self.phase == "deal_skill"

    def jiasuo_set(self, seat: int, han: int) -> dict:
        s = int(seat)
        if not self.owns_c(s, 18):
            raise RuleError("手里不是这一轮的卡")
        if s in self.jiasuo:
            raise RuleError("枷锁一局只能定一次")
        n = int(han)
        if not 1 <= n <= 13:
            raise RuleError("期待番数要在 1~13 之间")
        self.jiasuo[s] = n
        self.note_use(s, 18, 1)      # 记「发动了」→ 这张卡翻明
        self.save_flags()
        return {"seat": s, "han": n}

    def link_can(self, seat: int) -> bool:
        s = int(seat)
        if s in self.link or self.skill_used(s, 18, 2):
            return False
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None:
            return False
        return self.owns_c(s, 18)

    def link_use(self, seat: int, target: int) -> dict:
        s, t = int(seat), int(target)
        if not self.owns_c(s, 18):
            raise RuleError("手里不是这一轮的卡")
        if self.skill_used(s, 18, 2):
            raise RuleError("连接一轮只能用一次")
        if t == s or t not in range(4):
            raise RuleError("要选一位其他玩家")
        self.link[s] = t
        self.mark_skill_used(s, 18, 2)
        self.save_flags()
        return {"seat": s, "target": t}

    # ─── 点燃 / 炸裂（Card14）／钓鱼 / 上钩（Card15）──────────────────────
    def owns_card(self, seat: int, card: int, cache_name: str) -> bool:
        s = int(seat)
        c = getattr(self, cache_name, None)
        if c is None:
            c = {}
            setattr(self, cache_name, c)
        if s not in c:
            c[s] = skills.owns_card(self.db, self, s, int(card), strict=True)
        return c[s]

    def owns_card14(self, seat: int) -> bool:
        return self.owns_card(seat, 14, "_c14_cache")

    def owns_card15(self, seat: int) -> bool:
        return self.owns_card(seat, 15, "_c15_cache")

    def owns_card24(self, seat: int) -> bool:
        return self.owns_card(seat, 24, "_c24_cache")

    # 点燃：摇两颗骰子；失败时自动用最少的修正点数救成功
    # ── 点燃点数（跨小局，存 meta）────────────────────────────────────────
    def _po10_load(self) -> dict:
        row = self.db._row("SELECT value FROM meta WHERE key='po10'")
        try:
            return json.loads(row["value"]) if row else {}
        except (ValueError, TypeError):
            return {}

    def _po10_save(self) -> None:
        with self.db.tx():
            self.db.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('po10', ?)",
                (json.dumps({"now": int(self.po10_pts), "next": int(self.po10_next)}),))

    def po10_roll(self) -> dict:
        a, b = random.randint(1, 6), random.randint(1, 6)
        raw = [a, b]

        def ok(x, y):
            return (1 <= x <= 3 and 1 <= y <= 3) or (4 <= x <= 6 and 4 <= y <= 6)

        used = 0
        fix = ""
        if not ok(a, b):
            # 1 点：只改一颗
            cands = []
            for d in (0, 1):
                for sign in (-1, 1):
                    v = [a, b]
                    v[d] += sign
                    if 1 <= v[d] <= 6 and ok(v[0], v[1]):
                        cands.append((1, d, sign))
            if not cands and self.po10_pts >= 2:
                for sa in (-1, 1):
                    for sb in (-1, 1):
                        v = [a + sa, b + sb]
                        if all(1 <= x <= 6 for x in v) and ok(v[0], v[1]):
                            cands.append((2, 0, sa, sb))
            if cands and self.po10_pts >= cands[0][0]:
                c = cands[0]
                used = c[0]
                if used == 1:
                    a2, b2 = a, b
                    if c[1] == 0:
                        a2 += c[2]
                    else:
                        b2 += c[2]
                    fix = "%d→%d" % ((a, b)[c[1]], (a2, b2)[c[1]])
                    a, b = a2, b2
                else:
                    fix = "%d→%d、%d→%d" % (a, a + c[1], b, b + c[2])
                    a, b = a + c[1], b + c[2]
                self.po10_pts -= used
            self._po10_save()
        success = ok(a, b)
        if not success:
            # 真失败 → 攒 1 点，只能下一小局用
            self.po10_next += 1
            self._po10_save()
        self.po10_last = [a, b]
        self.save_flags()
        return {"dice": [a, b], "raw": raw, "success": success,
                "used": used, "fix": fix, "pts": int(self.po10_pts),
                "next": int(self.po10_next)}

    def _start_ignite(self, seat: int, card: int, skill: int) -> dict:
        """配牌阶段：摇一次骰子，决定本局「炸裂」能不能用"""
        s = int(seat)
        if self.ignite_done:
            raise RuleError("点燃本小局已经摇过了")
        r = self.po10_roll()
        self.ignite_ok = bool(r["success"])
        self.ignite_done = True               # 定生死：本小局不再摇
        # 炸裂（14,2）的发动点就在配牌这一次：之后不再问看破
        self.kangpo_once.add("%d:14:2" % s)
        self.mark_skill_used(s, 14, 1)        # 图标置灰（本小局不能再点）
        self.deal_wait.discard(s)
        self.deal_used.add(s)
        self.save_flags()
        self._maybe_close_deal()
        r.update({"ok": True, "card": int(card), "skill": int(skill), "used": True,
                  "pending": sorted(self.deal_wait)})
        return r

    def ignite_can(self, seat: int) -> bool:
        """点燃只能在配牌阶段发动，而且每小局只摇一次。"""
        s = int(seat)
        if self.ignite_done or not self.owns_card14(s):
            return False
        return self.phase == "deal_skill" and s in self.deal_wait

    def ignite_activate(self, seat: int) -> dict:
        """点燃：配牌阶段摇一次（走和 op=skill 14-1 同一条路）"""
        s = int(seat)
        if not self.owns_card14(s):
            raise RuleError("手里不是这一轮的卡")
        if self.ignite_done:
            raise RuleError("点燃本小局已经摇过了（只能在配牌阶段摇）")
        if self.phase != "deal_skill" or s not in self.deal_wait:
            raise RuleError("点燃只能在配牌阶段发动")
        return self._start_ignite(s, 14, 1)

    def pre_draw_pending(self, seat: int) -> bool:
        """这个座位在摸牌前还有没有「要先问一句」的技能可用。"""
        s = int(seat)
        if self.c34_muted(s):
            return False                       # 【厄运】：三巡内不问技能
        try:
            if self.zhalie_can(s):
                return True
            if self.card09_can(s):
                return True
            o = self.oracle.get(s) or {}
            if bool(o.get("on", False)):
                return True
            if int(self.future_armed) == s:
                return True                  # 未来：已经发动，等玩家把 5 张排好
            if self.c26_can_sort(s):
                return True                  # 天梯：摸牌前要先排牌山
            if self.c45s1_can(s):
                return True              # 神境：摸牌前先问一句
            if self.future_can(s):
                return True
        except Exception:
            return False
        return False

    def zhalie_can(self, seat: int) -> bool:
        if self.is_riichi(int(seat)):
            return False          # 立直后手牌锁定：不再询问会改手牌的技能

        s = int(seat)
        if not self.ignite_ok:
            return False                      # 点燃没成功 → 炸裂不能发动
        if not self.owns_card14(s):
            return False
        if self.phase != "draw" or self.turn is None or int(self.turn) != s:
            return False
        if self._zhalie_mark(s) == self.zhalie_mark:
            return False                      # 这一巡已经用过一次了
        return bool(self.zhalie_targets(s))

    def _zhalie_mark(self, seat: int) -> str:
        """「这一巡」的标记：按我自己打出的牌数算"""
        return "%d-%d" % (int(seat), self.my_discard_count(int(seat)))

    def zhalie_targets(self, seat: int) -> list[int]:
        """别家牌河里 6~9 的序数牌（明牌、没被鸣走）"""
        me = int(seat)
        out = []
        for r in self.db._rows(
                "SELECT seq, seat, tile, called, face_down FROM round_discards "
                "WHERE round_id=? AND called=0 ORDER BY seq", (self.round_id,)):
            if int(r["seat"]) == me or int(r["face_down"] or 0):
                continue
            t = str(r["tile"])
            if t[-1:] not in ("m", "p", "s") or t.startswith("0"):
                continue
            if 6 <= int(t[:-1]) <= 9:
                out.append(int(r["seq"]))
        return out

    def zhalie_swap(self, seat: int, hand_tile: str, river_seq: int) -> dict:
        """炸裂：先点燃判定，成功后手牌一张 ↔ 别家牌河 6~9 的牌（明牌）"""
        s = int(seat)
        if not self.owns_card14(s):
            raise RuleError("手里不是这一轮的卡")
        if self.phase != "draw" or self.turn is None or int(self.turn) != s:
            raise RuleError("摸牌前才能发动")
        if not self.ignite_ok:
            raise RuleError("本小局点燃没有成功，炸裂不能使用")
        seq = int(river_seq)
        if seq not in self.zhalie_targets(s):
            raise RuleError("只能换别家牌河里的 6~9 序数牌")
        tile = str(hand_tile)
        mine = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY wall_seq LIMIT 1", (self.round_id, s, tile))
        if mine is None:
            raise RuleError(f"手里没有 {tile}")
        row = self.db._row("SELECT wall_seq, tile FROM round_discards WHERE round_id=? AND seq=?",
                           (self.round_id, seq))
        if row is None:
            raise RuleError("这张牌不在牌河里")
        target = str(row["tile"])
        hseq = int(mine["wall_seq"])
        self.do_swap("hand_river", s, "炸裂",
                     hand_seq=hseq, river_seq=seq, face_down=None)
        self.mark_skill_used(s, 14, 2)
        self.zhalie_mark = self._zhalie_mark(s)     # 这一巡不能再炸
        self.save_flags()
        return {"ok": True, "hand": tile, "got": target, "seq": seq}

    def diaoyu_can(self, seat: int) -> bool:
        if self.is_riichi(int(seat)):
            return False          # 立直后手牌锁定：不再询问会改手牌的技能

        s = int(seat)
        if self.diaoyu_locked or not self.owns_card15(s):
            return False
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None:
            return False
        for t in range(4):
            if t != s and self.diaoyu_options(s, t):
                return True
        return False

    def _hand_kinds(self, seat: int) -> list[str]:
        return [str(t) for t in self.hand(seat)]

    def _tsumogiri_only(self, seat: int) -> bool:
        """这家现在「只能摸切」（不能手切）吗？

        立直 / 换牌技能后用过的 must_tsumogiri / 被决斗限制 —— 这三种都是
        「打出去只能是刚摸的那张」，所以任何「要求他打出手牌」的技能都要绕开他。
        """
        s = int(seat)
        if s not in range(4):
            return False
        return (self.is_riichi(s) or s in self.must_tsumogiri
                or self.duel_restricted(s))

    def diaoyu_options(self, seat: int, target: int) -> list[str]:
        """我能让 target 打出的牌种：碰/杠（有对子/刻子）、和（铳牌），
        只有上家才额外给「吃」（有搭子的牌种）"""
        s, t = int(seat), int(target)
        if t == s or t not in range(4):
            return []
        if self.hand_locked(t):
            return []                       # 立直家手牌锁定：不列出来
        if self._tsumogiri_only(t):
            return []                       # 只能摸切（换牌技能 / 决斗）：不能让他手切
        no_kinds = ("dong", "bei") if int(t) in self.c10s2 else ()
        hand = self._hand_kinds(s)
        # 刚摸的那张等会儿要交给对方 → 吃碰杠和都按「去掉它之后的 13 张」算
        drawn = self.drawn_tile(s)
        base = list(hand)
        if drawn is not None and drawn in base:
            base.remove(drawn)
        hand = list(base)
        out: list[str] = []
        for kind in TILE_KINDS:
            if kind in no_kinds:
                continue                               # 四喜：他不能打东/北
            if kind not in out and hand.count(kind) >= 2:
                out.append(kind)                       # 碰 / 杠
        for kind in TILE_KINDS:
            if kind in out:
                continue
            try:
                if agari.is_winning(counts_of(base + [kind]), self.melds(s)):
                    out.append(kind)
            except Exception:
                continue
        if (s - t) % 4 == 1:                            # t 是我的上家：只有下家能吃
            # ★ 必须用真正的「吃」判定（和鸣牌窗口同一套 chi_options），
            #   不能只看「手里有没有一张差 1~2 的牌」：
            #   手里 4p6p 可以吃 5p，但**不能**吃 3p / 7p；
            #   副露出去的牌也不在 hand 里，别指望它替你凑搭子（4p+副露的5p6p 不能吃 7p）。
            for kind in TILE_KINDS:
                if kind in out or kind in no_kinds:
                    continue
                if calls.chi_options(hand, kind):
                    out.append(kind)
        return out

    def diaoyu_force(self, seat: int, target: int, tile: str) -> dict:
        """钓鱼：强制 target 打出我指定的牌，然后照常开鸣牌/和牌窗口"""
        s, t = int(seat), int(target)
        if not self.owns_card15(s):
            raise RuleError("手里不是这一轮的卡")
        if self.diaoyu_locked:
            raise RuleError("本小局已经不能再钓鱼了")
        if self.hand_locked(t):
            # 立直家手牌锁定：这一手作废（和别的失败一样，本小局锁住）
            self.diaoyu_locked = True
            self.save_flags()
            raise RuleError("对方已经立直，手牌锁定，不能钓鱼")
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            raise RuleError("摸牌后才能发动")
        if self.drawn_tile(s) is None:
            raise RuleError("还没摸牌")
        tile = str(tile)
        if tile not in self.diaoyu_options(s, t):
            # 发动失败也算用掉：本小局不能再钓（防反复试）
            self.diaoyu_locked = True
            self.save_flags()
            raise RuleError("这张牌我不能吃/碰/杠/和")
        row = self.db._row(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY wall_seq LIMIT 1", (self.round_id, t, tile))
        if row is None:
            # 赤 5 与普通 5 在「能不能吃/碰」上是同一张：按牌种再找一次，
            # 否则目标手里只有 0m 时，选 5m 会莫名其妙地判成「他手里没有」。
            rows = self.db._rows(
                "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
                "ORDER BY wall_seq", (self.round_id, t))
            row = next((x for x in rows if kind_of(x["tile"]) == kind_of(tile)), None)
            if row is not None:
                tile = str(row["tile"])          # 后面按实际那张牌（可能是赤 5）走
        if row is None:
            # 视为「发动失败」：不消耗次数、也不锁本小局
            # 发动失败也算用掉：本小局不能再钓（防反复试）
            self.diaoyu_locked = True
            self.save_flags()
            return {"ok": False, "reason": "hand", "target": t, "tile": tile}
        my_drawn = self.db._row(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? AND is_drawn=1 "
            "ORDER BY wall_seq DESC LIMIT 1", (self.round_id, s))
        before = self._hand_snapshot()
        with self.db.tx():
            if my_drawn is not None:
                # 我刚摸的那张给他（不然他少一张）
                self.db.conn.execute(
                    "UPDATE round_hands SET seat=?, is_drawn=0, slot=IFNULL("
                    "(SELECT MAX(slot) FROM round_hands WHERE round_id=? AND seat=?), -1) + 1 "
                    "WHERE round_id=? AND wall_seq=?",
                    (t, self.round_id, t, self.round_id, int(my_drawn["wall_seq"])))
        # ★ 他这张牌 → 牌河：走 _do_discard（命中计数 / 一发 / 收钩子 / 鸣牌窗口
        #   全在它里面），不要再自己 db.discard + _open_claim_window。
        self.pending_kuikae = None
        self.turn = t
        self.phase = "discard"
        self._do_discard(t, tile=tile, forced=True)
        dseq = int(self.db._one(
            "SELECT IFNULL(MAX(seq), -1) FROM round_discards WHERE round_id=?",
            (self.round_id,)) or 0)
        # 他的手牌被我动过（多一张）→ 策略计数 +1 / 换牌机会
        self.card05_note_changes(before, s, "钓鱼")
        self.diaoyu_locked = True                    # 先锁；吃到上家再解锁
        self._diaoyu_me = s
        self.note_use(s, 15, 1, once=False)      # 钓鱼可以多次发动：不记「一次性」
        self.save_flags()
        return {"ok": True, "target": t, "tile": tile, "discard_seq": dseq,
                "from": t, "phase": self.phase}

    def shanggou_active(self, seat: int) -> bool:
        """一定和牌：上钩（三副露听牌）／前路成功／馈赠3"""
        s = int(seat)
        if s in self.yiding:
            return True
        if not self.owns_card15(s):
            return False
        melds = self.melds(s)
        if len(melds) < 3:
            return False
        try:
            rep = tenpai.tenpai_report(self.hand13(s), melds, self.tenpai_base(s))
        except Exception:
            return False
        return bool(rep.get("tenpai"))

    def _judge_shanggou(self, seat: int, tsumo: bool) -> dict | None:
        return self._judge_best_kind(seat, tsumo)

    def _judge_best_kind(self, seat: int, tsumo: bool,
                         riichi: bool = False, ippatsu: bool = False,
                         judge_opts: dict | None = None) -> dict | None:
        """一定和牌：把这张牌当成牌种，挑点数最高的那种结算（不当红 5）"""
        s = int(seat)
        hand = list(self.hand(s))
        drawn = self.drawn_tile(s) if tsumo else None
        base = list(hand)
        if tsumo and drawn is not None and drawn in base:
            base.remove(drawn)
        best = None
        for kind in TILE_KINDS:
            counts = counts_of(base + [kind])
            if not agari.is_winning(counts, self.melds(s)):
                continue
            tiles = list(base) + [kind]
            ctx = {
                "counts": counts, "tiles": tiles, "melds": self.melds(s),
                "win_index": index_of(kind), "is_dealer": s == self.dealer,
                "tsumo": tsumo, "seat_wind": ["dong", "nan", "xi", "bei"][(s - self.dealer) % 4],
                "round_wind": self.round_wind,
                "riichi": bool(riichi or self.is_riichi(s)),
                "ippatsu": bool(ippatsu or s in self.ippatsu),
                "double_riichi": s in self.double_riichi,
                "last_tile": False, "rinshan": False, "chankan": False, "tenhou": None,
                "dora_indicators": self.revealed_dora("dora"),
                "ura_indicators": ([] if self.c46s2_on(s) else
                                   (self.revealed_dora("ura")
                                    if (riichi or self.is_riichi(s)) else [])),
                "heated_kind": self.heat_kind,
                "rules": self.rules, "no_edge_fu": False, "no_wait_fu": False,
            }
            ctx.update(self._skill_judge_flags(s, with_bonus=False))
            _apply_judge_opts(ctx, judge_opts)
            res = yaku.judge(ctx)
            if not res.get("yaku"):
                # 一定和牌：无役也能和 → 记一个 1 番 30 符的兜底候选
                res = {"yaku": [{"name": "上钩（三副露听牌·无役和）", "han": 1}],
                       "han": 1, "fu": 30,
                       "pays": score.payments(1, 30, is_dealer=(s == self.dealer),
                                              tsumo=tsumo, yakuman=0,
                                              kiriage_mangan=False),
                       "fu_items": [("上钩（固定）", 30)], "dawa": True}
            total = int(res["pays"].get("total", 0))
            if best is None or total > int(best["pays"].get("total", 0)):
                best = res
                best["shanggou_tile"] = kind
                best["win_tile"] = str(kind)
        return best

    # ─── 破发（Card13 S1）／渣和（Card13 S2）────────────────────────────
    def owns_card13(self, seat: int) -> bool:
        s = int(seat)
        if s not in self._c13_cache:
            self._c13_cache[s] = skills.owns_card(self.db, self, s, 13, strict=True)
        return self._c13_cache[s]

    def owns_dawa(self, seat: int) -> bool:
        """渣和：13 号卡的第二技能（跟主/协战同一套拥有判定）"""
        return skills.owns_card(self.db, self, int(seat), 13, strict=True)

    def prompt_state(self) -> dict | None:
        """现在有没有人在等回答（统一询问锁）。

        返回 {"kind": "kangpo|haishin|shenshan|youyin|pofa", "waiting": [座位...]}；
        None = 没人在等，可以正常推进。
        破发只在「鸣牌窗口结束、回到 discard/draw」时才锁（荣和/吃碰优先级更高）。
        """
        if self.c42s2_settle is not None:
            # 夺目：结算前的询问没答完 → 谁都别动（这一局已经和了，只差点数怎么算）
            w = [int(x) for x in (self.c42s2_settle.get("waiting") or [])]
            if w:
                return {"kind": "c42s2", "waiting": w}
        if self.act_pending():
            return {"kind": "act",
                    "waiting": sorted({int(a.get("seat", -1))
                                       for n in self.act_pending_list()
                                       for a in (n.get("asks") or [])
                                       if not a.get("answer")})}
        if self.kangpo_pending is not None:
            ask = self.kangpo_ask or {}
            w = [int(ask.get("owner", -1))] if ask else []
            return {"kind": "kangpo", "waiting": [x for x in w if x >= 0]}
        if self.haishin_offer is not None:
            w = [int((self.haishin_offer or {}).get("owner", -1))]
            return {"kind": "haishin", "waiting": [x for x in w if x >= 0]}
        if self.c25s2_offer is not None:
            w = [int((self.c25s2_offer or {}).get("owner", -1))]
            return {"kind": "c25s2", "waiting": [x for x in w if x >= 0]}
        if self.shenshan_offer is not None:
            w = [int((self.shenshan_offer or {}).get("seat", -1))]
            return {"kind": "shenshan", "waiting": [x for x in w if x >= 0]}
        if self.c29s1_offer is not None and self.phase == "c29s1":
            w = [int((self.c29s1_offer or {}).get("seat", -1))]
            return {"kind": "c29s1", "waiting": [x for x in w if x >= 0]}
        if self.youyin_meld_offer is not None:
            w = [int((self.youyin_meld_offer or {}).get("seat", -1))]
            return {"kind": "youyin_meld", "waiting": [x for x in w if x >= 0]}
        if self.gift_offer is not None:
            w = [int((self.gift_offer or {}).get("seat", -1))]
            return {"kind": "gift", "waiting": [x for x in w if x >= 0]}
        if self.youyin_offer is not None:
            w = [int((self.youyin_offer or {}).get("seat", -1))]
            return {"kind": "youyin", "waiting": [x for x in w if x >= 0]}
        if self.pofa_ask is not None and self.phase in ("discard", "draw"):
            w = [int(x) for x in (self.pofa_ask.get("waiting") or [])]
            if w:
                return {"kind": "pofa", "waiting": w}
        return None

    def _has_card13(self, seat: int) -> bool:
        return skills.owns_card(self.db, self, int(seat), 13)

    def pofa_can(self, seat: int) -> bool:
        s = int(seat)
        if self.is_riichi(s):
            return False          # 立直后手牌锁定：不再询问会改手牌的技能
        if self.xianfu_pending is not None:
            return False          # 先负结算优先：破发不能改写它
        a = self.pofa_ask or {}
        waiting = [int(x) for x in (a.get("waiting") or [])]
        if not waiting or int(waiting[0]) != s:
            return False          # 逐个问：只轮到 waiting[0]
        if s == int(a.get("declarer", -1)):
            return False
        if self.pofa_discard_pending == s:
            return False          # 已经副露完，等我暗置打牌
        # 不要求主战卡：只要这一局手里有 Card13 就能用（避免「明明有卡却说不能发动」）
        return skills.owns_card(self.db, self, s, 13)

    def pofa_seqs(self, seat: int) -> list[int]:
        """可以拿来破发的牌河牌（明牌、不是自己河里的）"""
        if not self.pofa_can(seat):
            return []
        rows = self.db._rows(
            "SELECT seq, seat, called, face_down, tile FROM round_discards "
            "WHERE round_id=? AND called=0 ORDER BY seq", (self.round_id,))
        return [int(r["seq"]) for r in rows
                if int(r["seat"]) != int(seat) and not int(r["face_down"] or 0)]

    def pofa_activate(self, seat: int, river_seq: int, hand_tiles: list[str]) -> dict:
        """破发：河里一张 + 手牌 2 张（吃/碰）或 3 张（明杠）→ 副露；回合跳到我，
        然后必须暗置打出一张（见 pofa_discard）。"""
        s = int(seat)
        if not self.pofa_can(s):
            raise RuleError("只有在别人宣布立直之后才能破发")
        self._assert_hand_mutable(s)                     # 立直后不能破发
        if int(river_seq) not in self.pofa_seqs(s):
            raise RuleError("只能选别人牌河里的明牌")
        picks = [str(x) for x in (hand_tiles or [])]
        if len(picks) not in (2, 3):
            raise RuleError("无效副露！")
        row = self.db._row(
            "SELECT seq, seat, wall_seq, tile FROM round_discards "
            "WHERE round_id=? AND seq=?", (self.round_id, int(river_seq)))
        if row is None:
            raise RuleError("这张牌不在牌河里")
        called = str(row["tile"])
        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY wall_seq DESC", (self.round_id, s))
        used: list[int] = []
        if len(picks) == 3:
            if not (picks[0] == picks[1] == picks[2] == called):
                raise RuleError("无效副露！")
            got = [r for r in rows if str(r["tile"]) == called]
            if len(got) < 3:
                raise RuleError("无效副露！")
            used = [int(r["wall_seq"]) for r in got[:3]]
            kind, tiles = "minkan", [called, called, called, called]
        else:
            a, b = picks
            kind = self._pofa_kind(called, a, b)
            if kind == "":
                raise RuleError("无效副露！")
            got_a = [r for r in rows if str(r["tile"]) == a]
            got_b = [r for r in rows if str(r["tile"]) == b and r not in got_a[:1]]
            if a == b:
                got_b = [r for r in rows if str(r["tile"]) == a][1:]
            if not got_a or not got_b:
                raise RuleError("无效副露！")
            used = [int(got_a[0]["wall_seq"]), int(got_b[0]["wall_seq"])]
            tiles = [called, a, b]
        meld_id = int(self.db._one(
            "SELECT IFNULL(MAX(meld_id), -1) + 1 FROM round_melds WHERE round_id=?",
            (self.round_id,)) or 0)
        with self.db.tx():
            self.db.conn.execute(
                "UPDATE round_discards SET called=1 WHERE round_id=? AND seq=?",
                (self.round_id, int(river_seq)))
            self.db.conn.execute(
                "INSERT INTO round_melds(round_id, seat, meld_id, kind, called_tile, from_seat,"
                " tiles_json, rot_index, seqs_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (self.round_id, s, meld_id, kind, called, int(row["seat"]),
                 json.dumps(tiles), 0,
                 json.dumps([int(row["wall_seq"])] + used)))
            self.db.conn.execute(
                "DELETE FROM round_hands WHERE round_id=? AND wall_seq IN (%s)"
                % ",".join("?" * len(used)), tuple([self.round_id] + used))
        self.pofa_window = None
        self.pofa_ask = None
        self.pofa_discard_pending = s
        self.phase = "pofa_discard"
        self.turn = s
        self.mark_skill_used(s, 13, 1)
        self.save_flags()
        return {"seat": s, "kind": kind, "called": called, "tiles": tiles,
                "meld_id": meld_id, "stage": "discard"}

    def pofa_pass(self, seat: int) -> dict:
        """破发窗口：这次不副露（客户端点「开始」）→ 问下一个"""
        s = int(seat)
        a = self.pofa_ask or {}
        waiting = [int(x) for x in (a.get("waiting") or [])]
        if s in waiting:
            waiting.remove(s)
            if waiting:
                a["waiting"] = waiting
                a["ts"] = time.time()
                self.pofa_ask = a
            else:
                self.pofa_ask = None
                self.pofa_window = None
            self.save_flags()
        return {"skipped": True, "next": (self.pofa_ask or {}).get("waiting", [])}

    def pofa_discard(self, seat: int, tile: str) -> dict:
        """破发副露之后：暗置打出这一张（取代原摸牌者的回合）"""
        s = int(seat)
        if self.pofa_discard_pending != s:
            raise RuleError("现在不是破发后的打牌")
        self._assert_hand_mutable(s)                     # 立直后不能破发
        t = str(tile)
        row = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY wall_seq LIMIT 1", (self.round_id, s, t))
        if row is None:
            raise RuleError(f"手里没有 {t}")
        with self.db.tx():
            self.db.conn.execute(
                "DELETE FROM round_hands WHERE round_id=? AND wall_seq=?",
                (self.round_id, int(row["wall_seq"])))
            seq = int(self.db._one(
                "SELECT IFNULL(MAX(seq), -1) + 1 FROM round_discards WHERE round_id=?",
                (self.round_id,)) or 0)
            self.db.conn.execute(
                "INSERT INTO round_discards(round_id, seq, seat, wall_seq, tile, called,"
                " is_tsumogiri, is_riichi_tile, face_down, is_nuki)"
                " VALUES(?,?,?,?,?,0,0,0,1,0)",
                (self.round_id, seq, s, int(row["wall_seq"]), t))
        self.pofa_discard_pending = None
        self.phase = "discard"
        self.turn = s
        self.save_flags()
        return {"seat": s, "tile": t, "seq": seq, "face_down": True}

    @staticmethod
    def _pofa_kind(called: str, a: str, b: str) -> str:
        """called + a + b 能不能成面子：刻子 / 顺子"""
        if called == a == b:
            return "pon"
        suit = called[-1:]
        if suit not in ("m", "p", "s"):
            return ""
        if not all(str(t)[-1:] == suit for t in (a, b)):
            return ""
        nums = sorted([int(called[:-1]), int(a[:-1]), int(b[:-1])])
        if nums[1] == nums[0] + 1 and nums[2] == nums[1] + 1:
            return "chi"
        return ""

    def owns_card12(self, seat: int) -> bool:
        s = int(seat)
        if s not in self._c12_cache:
            self._c12_cache[s] = skills.owns_card(self.db, self, s, 12, strict=True)
        return self._c12_cache[s]

    @staticmethod
    def _is_man_or_zhong(tile: str) -> bool:
        return tile.endswith("m") or tile == "zhong"

    def _haishin_owner(self, drawer: int, tile: str) -> int | None:
        """谁的海神要借这张牌？（别人摸到万子/红中、他没立直）"""
        if not self._is_man_or_zhong(str(tile)):
            return None
        if self.hand_locked(drawer):
            return None                  # 立直家摸到的牌不能被借走（手牌锁定）
        for s in range(4):
            if s == int(drawer):
                continue
            if not self.owns_card12(s):
                continue
            if self.is_riichi(s):
                continue                          # 立直后被动失效
            return s
        return None

    def haishin_start(self, seat: int) -> dict:
        """配牌阶段点「海神」：本小局开启（之后别人摸万子/红中都会强制问你换不换）"""
        s = int(seat)
        if not self.owns_card12(s):
            raise RuleError("手里不是这一轮的海神卡")
        if self.haishin_on:
            return {"ok": True, "already": True, "haishin_on": True,
                    "pending": sorted(self.deal_wait)}
        if self.phase != "deal_skill" or s not in self.deal_wait:
            raise RuleError("海神本局已经决定过了（配牌时没开就不能再用）")
        self.haishin_on = True
        self.deal_wait.discard(s)
        self.note_use(s, 12, 1)          # 翻面 + 播报 + 传承
        self.save_flags()
        self._maybe_close_deal()
        return {"ok": True, "card": 12, "skill": 1, "haishin_on": True,
                "pending": sorted(self.deal_wait)}

    def haishin_pass(self, seat: int) -> dict:
        """兜底：没人操作/遮罩时，把这次「借牌」放掉，别把对局挂死"""
        s = int(seat)
        offer = self.haishin_offer or {}
        if int(offer.get("owner", -1)) != s:
            return {"skipped": True}
        self.haishin_offer = None
        # 这张牌他不要了（没人在操作）→ 继续问下一个；都问完就正常打牌
        # （以前这里设成 "draw" → 摸牌的人会多摸一张，手牌 15 张）
        nxt = self._advance_intercept(offer)
        self.save_flags()
        return {"skipped": True, "from": int(offer.get("from", -1)),
                "tile": str(offer.get("tile", "")), "next": nxt}

    def haishin_give(self, seat: int, hand_tile: str) -> dict:
        """被动：把摸到的牌拿过来，把手牌一张给他"""
        s = int(seat)
        offer = self.haishin_offer or {}
        if int(offer.get("owner", -1)) != s:
            # 这笔询问已经结束了（被兜底跳过 / 已经换过）→ 幂等返回，别让客户端卡住
            return {"skipped": True, "already": True, "got": "", "from": -1}
        drawer = int(offer.get("from", -1))
        got = str(offer.get("tile", ""))
        tile = str(hand_tile)
        if tile == "":
            raise RuleError("海神：必须选一张手牌交换（不能跳过）")
        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY is_drawn DESC, wall_seq DESC", (self.round_id, s))
        mine = next((r for r in rows if str(r["tile"]) == tile), None)
        if mine is None:
            raise RuleError(f"手里没有 {tile}")
        theirs = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND is_drawn=1 "
            "ORDER BY wall_seq DESC LIMIT 1", (self.round_id, drawer))
        if theirs is None:
            raise RuleError("找不到对方刚摸的那张牌")
        hseq, tseq = int(mine["wall_seq"]), int(theirs["wall_seq"])
        self.do_swap("hand_hand", s, "海神借牌",
                     seat_a=s, hand_seq_a=tseq, seat_b=drawer, hand_seq_b=hseq)
        self.haishin_offer = None
        self.phase = "discard"
        self.note_skill(s, 12, 1)
        self.save_flags()
        return {"got": got, "gave": tile, "from": drawer}

    def haishin_can(self, seat: int) -> bool:
        """主动·挪宝：自己回合、还没摸牌、手上还有万子/红中、三步没走完"""
        if self.is_riichi(int(seat)):
            return False          # 立直后手牌锁定：不再询问会改手牌的技能

        s = int(seat)
        if not self.owns_card12(s):
            return False
        if self.phase == "deal_skill":
            return s in self.deal_wait            # 配牌阶段：还能开
        return bool(self.haishin_on)              # 配牌没开 → 整小局都用不了

    def haishin_swap(self, seat: int, hand_tile: str) -> dict:
        """主动：用一张万子/红中，按 里宝 → 杠宝 → 杠里宝 的顺序换指示牌"""
        s = int(seat)
        if not self.owns_card12(s):
            raise RuleError("手里不是这一轮的海神卡")
        if self.turn is None or int(self.turn) != s:
            raise RuleError("只能在自己摸牌前发动")
        step = int(self.haishin_step.get(s, 0))
        if step >= 3:
            raise RuleError("里宝/杠宝/杠里宝都换过了")
        tile = str(hand_tile)
        if tile == "":
            return {"skipped": True, "step": step}     # 直接点开始 = 跳过
        if not self._is_man_or_zhong(tile):
            raise RuleError("只能用万子或红中去换")
        rows = self.db._rows(
            "SELECT wall_seq, tile FROM round_hands WHERE round_id=? AND seat=? "
            "ORDER BY wall_seq", (self.round_id, s))
        mine = next((r for r in rows if str(r["tile"]) == tile), None)
        if mine is None:
            raise RuleError(f"手里没有 {tile}")
        kind, idx = (("ura", 0), ("dora", 1), ("ura", 1))[step]
        n = self.wall_first_stack()
        if not n or int(self.dora_revealed) <= idx:
            raise RuleError("这一步的指示牌还没翻开")
        no_d, no_u = wallmodel.dora_tile_nos(n, idx)
        seq = int(wallmodel.seq_of_tile(no_d if kind == "dora" else no_u))
        target = self._tile_of_no(seq)
        hseq = int(mine["wall_seq"])
        self.do_swap("hand_wall", s, "海神换宝", hand_seq=hseq, wall_seq=seq)
        self._c11_sync_dora({seq})             # 宝牌信息按牌墩现状重算
        self.haishin_step[s] = step + 1
        self.haishin_gate = s                  # 没走完不许和
        if self.haishin_step[s] >= 3:
            self.haishin_gate = None
        self.mark_skill_used(s, 12, 1)
        self.save_flags()
        return {"step": step, "kind": kind, "hand": tile, "got": target,
                "next": int(self.haishin_step[s]),
                "dora": self.revealed_dora("dora")}

    def xn_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None or self.skill_used(s, 12, 2):
            return False
        return self.owns_card12(s)

    def xn_activate(self, seat: int, target: int) -> dict:
        s, t = int(seat), int(target)
        if self.skill_used(s, 12, 2):
            raise RuleError("X神一轮只能用一次")
        if not self.owns_card12(s):
            raise RuleError("手里不是这一轮的海神卡")
        if t == s or t not in range(4):
            raise RuleError("要选一位其他玩家")
        self.x_skip[t] = 2
        self.mark_skill_used(s, 12, 2)
        self.note_skill(s, 12, 2)
        self.save_flags()
        return {"seat": s, "target": t, "left": 2}

    def card11_clear(self, seat: int) -> None:
        if self.c11_win is not None and int(self.c11_win) == int(seat):
            self.c11_win = None
            self.save_flags()

    def _check_sufon(self) -> dict | None:
        """四风连打：开局四家第一张都是同一种风牌，且没人鸣过牌。"""
        if self.phase == "ended" or not self.all_closed():
            return None
        ds = self.db._rows("SELECT seat, tile FROM round_discards WHERE round_id=? ORDER BY seq",
                           (self.round_id,))
        winds = {"dong", "nan", "xi", "bei"}
        if (len(ds) == 4 and sorted(d["seat"] for d in ds) == [0, 1, 2, 3]
                and all(d["tile"] in winds for d in ds)
                and len({d["tile"] for d in ds}) == 1):
            return self._ryuukyoku("sufon_renda")
        return None

    # ══════════════════════════════════════════════════════════════════════
    #  和牌判定与结算
    # ══════════════════════════════════════════════════════════════════════
    def _win_gate(self, seat: int, tile: str | None, tsumo: bool) -> bool:
        """『允不允许和』里的**技能闸门**那一段：只看技能，不看待牌/振听/有没有役。

        `_win_ok` 和「一定和牌找放铳者」共用它 —— 后者必须允许「无役也荣和」，
        所以不能直接套 `_win_ok`（那里最后还要 `_judge_win` 有役）。
        """
        # Card34 S1【厄运】：静默期不能和（荣和 / 自摸 / 抢杠 / 海底 全走这里）
        if self.c34_muted(seat):
            return False
        # 【厄运】生效期间，发动者自己的和牌无视拦截链（满贯在 _c28s1_allows 另开一处）
        if self.c34_exempt(int(seat)):
            return True
        if tile is not None and tile == "":
            return False
        # Card19 S2「浓雾」：4 巡内别家不能自摸。
        # ★ 用户口径 2026-10-27：**什么自摸形式都无法豁免浓雾** ——
        #   以前这里留了「一定和牌握着权限就豁免」，现在没这条了。
        if tsumo and self.nongwu_blocks(seat):
            return False
        if (not tsumo) and int(seat) in self.c45s1_on:
            return False                      # 【神境】：荣和链路堵死，只能自摸
        if int(seat) in self.no_win:
            return False                          # 看破的代价：本局不能和牌
        if self.haishin_gate is not None and int(self.haishin_gate) == int(seat):
            return False                          # 海神：挪宝没做完，不许和
        if tsumo and self.duel_restricted(seat) and self.is_riichi(seat):
            return False
        # Card07 Skill2「恶灵」：降神发动过 → 荣和全封，自摸必须门清
        if self._oracle_lock(seat):
            if not tsumo:
                return False
            if not agari.is_closed(self.melds(seat)):
                return False
        return True

    @staticmethod
    def _res_clone(res: dict) -> dict:
        """深够一层的拷贝：给「预测」用，别把结算链跑在原 res 上。"""
        out = dict(res)
        out["yaku"] = []
        for y in (res.get("yaku") or []):
            d = dict(y)
            if isinstance(d.get("detail"), dict):
                d["detail"] = dict(d["detail"])
            out["yaku"].append(d)
        out["pays"] = dict(res.get("pays") or {})
        out["fu_items"] = list(res.get("fu_items") or [])
        return out

    def _c28s1_blocks(self, res: dict | None) -> bool:
        """Card28 S1【满贯】：番数结算的结果不到满贯 → 这次和牌不予结算。

        · 判据用**段位**（基本点 ≥ 2000），所以 3番70符 / 4番40符 也算满贯
        · 【渣和】特化：它无视这道缚（否则 1 番 30 符 永远过不去，渣和就废了）
        · 役满当然放行
        """
        if not self.c28s1_on or not res:
            return False
        if res.get("dawa") or res.get("yakuman"):
            return False
        _name, basic = score.tier(int(res.get("han", 0)), int(res.get("fu", 0)),
                                  yakuman=int(res.get("yakuman", 0)),
                                  kiriage_mangan=bool(self.rules.get("kiriage_mangan")))
        return int(basic) < 2000

    def _c28s1_allows(self, seat: int, tile: str, tsumo: bool) -> bool:
        """按钮用：把这次和牌按完整结算链**预演一遍**（不落账），再问【满贯】。

        ★ 必须先跑链：蜕变 / 自信 / 馈赠 / 宝牌的集合 都可能把番数抬上去。
          但「多面 / 暖气」在得点链、排在拦截之后 —— 所以它们救不了。
        """
        if not self.c28s1_on:
            return True
        if self.c34_exempt(int(seat)):
            return True                       # 厄运期间发动者自己的和牌无视满贯缚
        res = self._judge_win(int(seat), str(tile), tsumo=bool(tsumo))
        if res is None:
            return True                       # 根本和不了，交给 _win_ok 那边判
        probe = self.settle_preview(int(seat), None, "tsumo" if tsumo else "ron",
                                    self._res_clone(res), dry_run=True)
        return not self._c28s1_blocks(probe)

    def _tsumo_gate_ok(self, seat: int) -> bool:
        """自摸这条链路的**技能闸门**（不看待牌 / 牌型 / 有没有役）。

        给「不走常规 `_win_ok` 的自摸入口」用：一发（c24）的自摸按钮、
        国标（skill_tsumo）这类。浓雾 / 恶灵 / 看破代价 / 海神 gate 一律照拦。
        """
        return self._win_gate(int(seat), None, True)

    def _win_ok(self, seat: int, tile: str, tsumo: bool,
                furiten_ok: bool = False) -> bool:
        if not self._win_gate(int(seat), str(tile), bool(tsumo)):
            return False
        # Card10 S2「四喜」：数到第 5 张摸牌 → 这次自摸视为小四喜。
        # 放在所有「禁止自摸 / 限制和牌」的拦截**之后**：那些技能能把它无效掉。
        if tsumo and self._c10s2_ready(seat):
            return True
        c = list(self.hand_counts(seat))
        if not tsumo:
            c[index_of(tile)] += 1
        if not agari.is_winning(c, self.melds(seat)):
            return False
        if tsumo:
            # 自摸也要「有役」才算：和 _do_tsumo 走同一套判定，避免「按钮亮了但按下失败」
            return self._judge_win(seat, tile, tsumo=True) is not None
        if not furiten_ok:
            if seat in self.temp_furiten:
                return False
            if seat in self.riichi_furiten:
                return False
            if calls.is_permanent_furiten(self.hand_counts(seat), self.melds(seat),
                                          self.discards_for_furiten(seat)):
                return False
        return self._judge_win(seat, tile, tsumo=False) is not None

    def _skill_judge_flags(self, seat: int, with_bonus: bool = True) -> dict:
        """技能给判番加的开关（不含局面信息）。加新技能只改这一处。

        with_bonus=False：**结算路径**用。宝牌的集合那 +4n 属于「番数结算链」
        （卡 25 的钩子），不能再在判番时加一遍，否则会排在所有卡之前 ——
        那正是「宝牌的集合在协战、自信在主战」时顺序算错的原因。
        听牌机（`tenpai_base`）保持 True：它只在做「有役听牌 / 最高那手」的估算。
        """
        s = int(seat)
        out: dict = {}
        if self.c25s2_on:
            out["dora_void_kan"] = True           # 宝牌的集合：杠翻的表宝牌全场无效
        if with_bonus and s in self.c25s2_on:
            bonus = 4 * self.kan_count()
            if bonus:
                out["dora_bonus_han"] = bonus     # 每开杠一次 +4 番（算进「宝牌」）
        if self.owns_dawa(s):
            out["dawa"] = True                    # 渣和：无役也能和（听牌机也认）
        return out

    def win_ctx(self, seat: int, tiles: list[str], win_tile: str, tsumo: bool,
                as_tsumo: bool = False, no_edge_fu: bool = False,
                no_wait_fu: bool = False,
                judge_opts: dict | None = None) -> dict:
        """`yaku.judge` 的完整上下文（局面 + 技能开关 + 本次结算的临时开关）。

        ★ 判番上下文的**唯一**来源。任何「有役听牌 / 多少番」的判定都要走这里，
          否则技能开关只在结算里生效、在听牌机里不生效 —— 两套口径。
        """
        s = int(seat)
        melds = self.melds(s)
        ctx = {
            "counts": counts_of(tiles), "tiles": list(tiles), "melds": melds,
            "win_index": index_of(win_tile), "is_dealer": s == self.dealer,
            "tsumo": bool(tsumo or as_tsumo),
            "seat_wind": ["dong", "nan", "xi", "bei"][(s - self.dealer) % 4],
            "round_wind": self.round_wind,
            "riichi": (self.is_riichi(s) or self.c39s2_fake(s)),
            "ippatsu": s in self.ippatsu,
            "double_riichi": s in self.double_riichi,
            "last_tile": self.live_left() <= 0,
            "rinshan": bool(self.last_was_rinshan), "chankan": bool(self.chankan_now),
            "tenhou": ("tenhou" if s == self.dealer else "chiihou")
            if (tsumo and not melds and self.all_closed() and not self._has_discarded(s))
            else None,
            "dora_indicators": self.revealed_dora("dora"),
            # Card46 S2【赤里】：立直和牌 → 原来的里宝牌全部无效（新手牌由钩子补）
            "ura_indicators": ([] if self.c46s2_on(s) else self.revealed_dora("ura")),
            "rules": self.rules,
            "no_edge_fu": bool(no_edge_fu or s in self.c43s1_win),
            "no_wait_fu": bool(no_wait_fu or s in self.c43s1_win),
            "heated_kind": self.heat_kind,
        }
        ctx.update(self._skill_judge_flags(s, with_bonus=False))   # +4n 走卡 25 的钩子
        _apply_judge_opts(ctx, judge_opts)
        return ctx

    def tenpai_base(self, seat: int) -> dict:
        """`tenpai_report` / `is_tenpai_with_yaku` 用的 base：
        `yaku_base`（局面） + `_skill_judge_flags`（技能开关）—— 和真结算同一份。"""
        base = dict(self.yaku_base(int(seat)))
        base.update(self._skill_judge_flags(int(seat)))
        return base

    def _judge_win(self, seat: int, tile: str, tsumo: bool, quiet: bool = False,
                   as_tsumo: bool = False, judge_opts: dict | None = None) -> dict | None:
        """as_tsumo：魔术（Card11 S1）换完指示牌直接和牌 → 按自摸算、不计边坎吊 2 符"""
        # Card33 S1【染手】：用过之后，本次和牌必须是「染手牌型」
        #   （数牌花色 ≤ 1 种）→ 混一色 / 清一色 / 字一色 都满足；
        #   绿一色（判番只给役满名）/ 九莲 / 字一色 也一样放行，不看役种名。
        #   放在最前面：上钩 / 渣和 / 小四喜 这些「无役也能和」的兜底同样被挡。
        if self.c33s1_blocked(int(seat), tile, bool(tsumo)):
            return None
        if tsumo and self._c10s2_ready(seat):
            pays = score.payments(0, 0, is_dealer=(int(seat) == self.dealer), tsumo=True,
                                  yakuman=1, kiriage_mangan=False)
            return {"yaku": [{"name": "小四喜（四喜）", "han": 0}], "han": 0, "fu": 0,
                    "pays": pays, "yakuman": 1, "fu_items": [], "c10s2": True,
                    "win_tile": str(tile)}
        hand = self.hand(seat)
        melds = self.melds(seat)
        tiles = list(hand) if tsumo else list(hand) + [tile]
        # ★ 先验牌型：不是和牌形就直接不算（否则「天和/地和」会白送役满）
        if not agari.is_winning(counts_of(tiles), melds):
            return None
        # 压制换进来的牌直接自摸：不算边张 / 嵌张符
        # 魔术：换来的牌是从王牌里摸的 → 没有待ち，边张/嵌张/单钓 2 符都不算
        ctx = self.win_ctx(seat, tiles, tile, tsumo, as_tsumo=as_tsumo,
                           no_edge_fu=bool(tsumo and seat in self.press_win),
                           no_wait_fu=bool(as_tsumo), judge_opts=judge_opts)
        res = yaku.judge(ctx)
        res["win_tile"] = str(tile)       # 【赤里】要看和到的是哪张
        if res.get("yaku"):
            res["real_yaku"] = True       # 有真役（渣和的 1 番不算）
            # 精算（29S2）要「当门清重判」，得知道原来是怎么判的：
            #   _tile/_tsumo 用来重建牌型；_opts 用来把国标的 pattern_bonus 一起带过去
            res["_tile"] = str(tile)
            res["_tsumo"] = bool(tsumo)
            res["_opts"] = dict(judge_opts or {})
            return res
        if self.shanggou_active(seat):
            sg = self._judge_shanggou(seat, tsumo)
            if sg is not None:
                return sg
        if self.owns_dawa(seat):
            # 渣和＝**获得性质**：这里只给「能和牌」的占位（0 番），
            # 1 番 30 符 由结算链走到 13 号卡那一格时垫上 ——
            # 这样它在链里的位置由卡序决定（自信/馈赠 在它前面就看不到它）。
            return {"yaku": [], "han": 0, "fu": 0, "pays": {},
                    "dawa_pending": True, "real_yaku": False,
                    "win_tile": str(tile)}
        # 一定和牌不再在这里兜底：宣言时由 _yiding_settle 负责
        # （真成形的按实际番符判；判不出来才用 _yiding_fallback 的 1 番 30 符）。
        return None

    def _yiding_payer(self, seat: int, judge_opts: dict | None = None,
                          want_tile: str = "") -> tuple[int, str]:
        """一定和牌：按下家 → 对家 → 上家 找「手里有我的铳牌」的人（三次询问）。

        一个人手里可能有不止一张我的铳牌 → **取结算点数最高的那张**
        （用户口径 2026-10-25）。

        ★ 2026-10-26：候选必须先过 `_win_gate` —— 荣和链路被【恶灵】堵住时
          一个都不选，于是三家全失败 → 走自摸那条路。以前把「被堵住、点数 0」
          也当成命中，结果挑了个放铳者走 1 番 30 符兜底，恶灵被整个绕过。
          （不要求 `total > 0`：无役的待牌也要能荣和，靠 1 番 30 符兜底。）
        """
        s = int(seat)
        base = list(self.hand(s))
        drawn = self.drawn_tile(s)
        if drawn is not None and drawn in base:
            base.remove(drawn)                 # 荣和用「不含刚摸那张」的 13 张判
        best_total = -1
        best: tuple[int, str] = (-1, "")
        wt = str(want_tile or "")          # 【恶听】：只认「仅剩 1 张」那张铳牌
        for k in (1, 2, 3):
            o = (s + k) % 4
            for t in sorted(set(self.hand(o))):
                if wt and kind_of(str(t)) != wt:
                    continue
                ts = str(t)
                if not self._win_gate(s, ts, tsumo=False):
                    continue                   # 恶灵 / 看破代价 / 海神 / 决斗 …
                try:
                    if not agari.is_winning(counts_of(base + [ts]), self.melds(s)):
                        continue
                except Exception:
                    continue
                # ★ 这里不能叫 `_judge_win`：它内部用 `self.hand()` 拼牌，
                #   而此刻我手里还是 14 张（刚摸那张没打出去）→ 15 张永远不成形、
                #   一律 None，于是「取点数最高的那张」从来没生效过。
                #   直接用统一的 win_ctx 按 13 张 + 这张铳牌 判。
                try:
                    res = yaku.judge(self.win_ctx(s, base + [ts], ts, False,
                                                  judge_opts=judge_opts))
                except Exception:
                    res = None
                total = int(((res or {}).get("pays") or {}).get("total", 0)) \
                    if (res or {}).get("yaku") else 0
                if total > best_total:
                    best_total = total
                    best = (o, ts)
        return best

    def _yiding_void_apply(self, seat: int, reason: str) -> dict:
        """一定和牌作废：撤掉宣言、那张牌留在牌河、轮到下家，游戏继续。"""
        s = int(seat)
        self.yiding.discard(s)
        self.yiding_src.pop(s, None)
        self._advance_after_discard(s)          # 刚那张牌已经进牌河，轮到下家摸
        self.save_flags()
        return self._event("yiding_void", {"seat": s, "reason": str(reason)})

    def _yiding_void(self, seat: int) -> bool:
        """一定和牌**作废**的判据：自摸这条链路被堵住了。

        只在「荣和那条路已经失败」之后才问（`_yiding_settle` 里 cherry 在 payer<0 之后）：
          三家手里都没有我的铳牌 → 本来该按自摸算，
          但【浓雾】封住了自摸 → 两条路都没了 → 技能作废、游戏继续。

        ★ 只看「自摸被不被堵」：【恶灵】只封荣和、自摸照样成立（用户口径），
          所以恶灵单独出现时**不**作废，直接算自摸。
          恶灵 + 浓雾 = 荣和没人接 + 自摸被堵 → 自然落进这里。
        """
        return bool(self.nongwu_blocks(int(seat)))

    def _yiding_fallback(self, seat: int, tsumo: bool) -> dict:
        pays = score.payments(1, 30, is_dealer=(int(seat) == self.dealer),
                              tsumo=tsumo, yakuman=0, kiriage_mangan=False)
        return {"yaku": [{"name": "一定和牌", "han": 1}], "han": 1, "fu": 30,
                "pays": pays, "fu_items": [("一定和牌（固定）", 30)]}

    # ─── 一定和牌（主动宣言，立直式）────────────────────────────
    def yiding_grant(self, seat: int, card: int, skill: int) -> None:
        """被动获得「可以宣言一定和牌」的权限（记下是从哪个技能来的）。"""
        s = int(seat)
        if s in self.yiding:
            return
        self.yiding.add(s)
        self.yiding_src[s] = [int(card), int(skill)]
        self.save_flags()

    def yiding_src_of(self, seat: int) -> list:
        return list(self.yiding_src.get(int(seat)) or [])

    # ─── Card01 S1「国标」：也是一定和牌（宣言式）─────────────────
    def guobiao_can(self, seat: int) -> bool:
        s = int(seat)
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        # 用户口径：副露后（吃碰后 11 张）也算「切牌时」，不再要求刚摸的牌
        #（11 张切一张 = 10 = 3×3+1，本来就是听牌形）
        if self.skill_used(s, 1, 1):
            return False                       # 本小局一次
        if self.is_riichi(s) or s in self.no_win:
            return False
        if not skills.owns_card(self.db, self, s, 1, strict=True):
            return False
        return bool(self.guobiao_discards(s))

    def guobiao_discards(self, seat: int) -> list[str]:
        """切出后还能听牌的牌（和一定和牌同一套算法）。"""
        return self._tenpai_discards(seat)

    def guobiao_declare(self, seat: int, tile: str) -> dict:
        """宣言国标：把这张打出去（明置），然后按「一定和牌」的通用规则结算。"""
        s = int(seat)
        if not self.guobiao_can(s):
            raise RuleError("现在不能发动「国标」（刚摸牌、且切出去能听牌）")
        t = str(tile)
        if t not in self.guobiao_discards(s):
            raise RuleError("这张打出去就不听牌了")
        row = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY wall_seq LIMIT 1", (self.round_id, s, t))
        if row is None:
            raise RuleError(f"手里没有 {t}")
        self.pending_kuikae = None
        self.db.discard(self.round_id, s, wall_seq=int(row["wall_seq"]),
                        riichi_tile=0, face_down=False)
        self.note_use(s, 1, 1)                 # 卡面翻明 + 播报（只能用一次）
        self.save_flags()
        # 【国标】自己的番数效果：五门齐 / 花龙 / 三色三步高 算 门清+2 / 副露+1
        return self._yiding_settle(s, {"pattern_bonus": True})

    def _tenpai_discards(self, seat: int) -> list[str]:
        """14 张里「切出去还听牌」的牌（去重，按手里顺序）。"""
        s = int(seat)
        hand = self.hand(s)
        if len(hand) % 3 != 2:
            return []
        try:
            kinds = agari.losing_tiles(counts_of(hand), self.melds(s))
        except Exception:
            return []
        ks = set(kinds)
        out: list[str] = []
        seen: set[str] = set()
        for t in hand:
            # 同 riichi_discards：赤 5 与普通 5 是两张实体，不能按牌种去重
            if kind_of(t) in ks and t not in seen:
                seen.add(t)
                out.append(t)
        return out

    def yiding_discards(self, seat: int) -> list[str]:
        """切出后还能听牌的牌（和立直同一套：losing_tiles + 池子过滤）。"""
        if int(seat) not in self.yiding:
            return []
        return self._tenpai_discards(int(seat))

    def yiding_can(self, seat: int) -> bool:
        """切牌时（摸牌后 / 吃碰杠后都算）、手里有「切出去还听牌」的牌 → 可以宣言。"""
        s = int(seat)
        if s not in self.yiding:
            return False
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        # 副露后不再要求「刚摸的牌」（用户口径：这条链的技能在副露后也能发动）
        if self.is_riichi(s) or s in self.no_win:
            return False
        return bool(self.yiding_discards(s))

    def yiding_declare(self, seat: int, tile: str) -> dict:
        """宣言：把这张牌打出去（明置），**不进鸣牌窗口**，立刻按通用规则结算。"""
        s = int(seat)
        if not self.yiding_can(s):
            raise RuleError("现在不能宣言一定和牌（要刚摸完牌、且切出去能听牌）")
        t = str(tile)
        if t not in self.yiding_discards(s):
            raise RuleError("这张牌切出去就不听牌了")
        row = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY wall_seq LIMIT 1", (self.round_id, s, t))
        if row is None:
            raise RuleError(f"手里没有 {t}")
        src = self.yiding_src_of(s) or [21, 2]
        self.yiding.discard(s)
        self.yiding_src.pop(s, None)
        self.pending_kuikae = None
        self.db.discard(self.round_id, s, wall_seq=int(row["wall_seq"]),
                        riichi_tile=0, face_down=False)
        self.note_use(s, int(src[0]), int(src[1]))     # 卡面翻明 + 播报
        self.save_flags()
        return self._yiding_settle(s)

    def _maybe_grant_yiding(self, seat: int) -> None:
        """听牌就给权限：21S2 馈赠（听牌即得，替代原来「手切 12 张」）、15S2 上钩（三副露听牌）。"""
        s = int(seat)
        if s in self.yiding:
            return
        drawn = self.drawn_tile(s)
        hand = list(self.hand(s))
        if drawn is not None and drawn in hand:
            hand.remove(drawn)             # 听牌按 13 张算
        try:
            tenpai_now = bool(tenpai.tenpai_report(hand, self.melds(s),
                                                   self.tenpai_base(s)).get("tenpai"))
        except Exception:
            tenpai_now = False
        # 21S2 段3：**替换原来「手切 12 张 → 馈赠3」那条** —— 手切满 12 张就拿到权限，
        # 不看当时听没听（用户口径：「发动段3时不一定已经听牌」）。
        # ★ 不能「听牌就给」：那样迷途之家一次都没发动的人也会拿到，立直按钮还会被
        #   「一定和牌」顶掉、点了先去问看破。
        if self.owns_cn(s, 21) and int(self.gift.get(s, 0)) >= 3:
            self.yiding_grant(s, 21, 2)
            return
        if not tenpai_now:
            return
        if self.owns_card15(s) and len(self.melds(s)) >= 3:
            self.yiding_grant(s, 15, 2)    # 上钩（15S2，三副露听牌）

    def _yiding_settle(self, seat: int, judge_opts: dict | None = None,
                        want_tile: str = "") -> dict:
        """一定和牌的结算：有人有我的铳牌 → 他出铳；都没有 → 自摸。"""
        s = int(seat)
        # 【染手】生效：手牌+副露已经跨花色 → 怎么和都不可能是染手牌型，直接作废
        if self.c33s1_blocked(s, None, True):
            return self._yiding_void_apply(
                s, "【染手】生效：牌型不是混一色/清一色/字一色")
        payer, tile = self._yiding_payer(s, judge_opts, want_tile=want_tile)
        if payer >= 0:
            res = self._judge_win(s, tile, tsumo=False, quiet=True,
                                  judge_opts=judge_opts)
            if res is None:
                res = self._judge_best_kind(s, tsumo=False, judge_opts=judge_opts)
            if res is None:
                res = self._yiding_fallback(s, tsumo=False)
            if self._c28s1_blocks(self.settle_preview(
                    s, payer, "ron", self._res_clone(res), dry_run=True)):
                return self._yiding_void_apply(s, "【满贯】：结算番数不到满贯")
            self._finish(s, payer, "ron", res)
            return self._event("yiding", {"seat": s, "from": payer, "tile": tile,
                                          "yaku": res.get("yaku"), "han": res.get("han"),
                                          "fu": res.get("fu"), "points": res.get("pays")})
        # 荣和那条路全失败（三家手里都没有我的铳牌 → 或者被【恶灵】/【海神】堵光）
        # → 本来该按自摸算。但自摸那条链路要是也被堵住（【浓雾】封自摸），
        #   两条路都没了 → 一定和牌作废、游戏继续（用户口径 2026-10-27）。
        if self._yiding_void(s):
            return self._yiding_void_apply(
                s, "三家都没有我的铳牌，而【浓雾】封住了自摸")
        drawn = self.drawn_tile(s) or ""
        want = str(want_tile or "")
        # 荣和那条路进来的（别人打的牌触发）没有「刚摸的牌」，drawn 是空的：
        # 这时候别拿空字符串去 judge（index_of("") 会 KeyError）。
        res = None
        if want:
            # 【恶听】：铳张在牌山 / 暗置牌里（没人在手上）→ 按自摸结算，但和到的就是这张
            tiles = list(self.hand(s)) + [want]
            if not self.c33s1_blocked(s, want, True) \
                    and agari.is_winning(counts_of(tiles), self.melds(s)):
                try:
                    res = yaku.judge(self.win_ctx(s, tiles, want, True,
                                                  judge_opts=judge_opts))
                except Exception:                      # noqa: BLE001
                    res = None
                if res is not None and not res.get("yaku"):
                    res = None                         # 无役 → 走 1 番 30 符兜底
        else:
            res = (self._judge_win(s, drawn, tsumo=True, quiet=True,
                                  judge_opts=judge_opts) if drawn else None)
            if res is None:
                res = self._judge_best_kind(s, tsumo=True, judge_opts=judge_opts)
        if res is None:
            res = self._yiding_fallback(s, tsumo=True)
        if self._c28s1_blocks(self.settle_preview(
                s, None, "tsumo", self._res_clone(res), dry_run=True)):
            return self._yiding_void_apply(s, "【满贯】：结算番数不到满贯")
        self._finish(s, None, "tsumo", res)
        return self._event("yiding", {"seat": s, "from": -1, "tile": (want or drawn),
                                      "yaku": res.get("yaku"), "han": res.get("han"),
                                      "fu": res.get("fu"), "points": res.get("pays")})

    # ══════════════════════════════════════════════════════════════════
    #  结算链的钩子（`_finish` 调用）
    #    ① 番数链按卡序：`cards_in_order` = [主战, 协战, 传承…]
    #    ② 得点链固定顺序：自信 → 多面 → 暖气（与卡序无关）
    #  每个钩子自己改 res，改完统一 `_recompute` 重算 pays。
    # ══════════════════════════════════════════════════════════════════
    _FAN_HOOKS = {
        5: "_settle_nuki",         # 拔北：本局拔过几次 +几番
        13: "_settle_dawa",        # 渣和：无役也能和 → 垫 1 番 30 符
        25: "_settle_c25s2",       # 宝牌的集合：每开一次杠 +4 番
        28: "_settle_c28s2",       # 蜕变：打点进档就再升一档
        29: "_settle_c29s2",       # 精算：非门前清 → 当门清重判（并重放前面的钩子）
        30: "_settle_c30s2",       # W立
        32: "_settle_c32s2",       # 无知：对对和→四暗刻 / 索子清一色(或只带发)→绿一色，各算 1 倍役满
        8: "_settle_duel_marks",   # 决斗标记：+计数器 番
        18: "_settle_jiasuo",      # 枷锁：番数正好等于期待值 → 翻倍
        21: "_settle_gift",
        44: "_settle_c44s2",      # telegram: 30 fu 1 han fixed        # 馈赠：+1 / +3 番
        46: "_settle_c46s2",      # 赤里：和到的那张算里宝（+ 5 再多 1 番）
    }
    _POINT_HOOKS = ("_settle_confidence", "_settle_multi", "_settle_heat")

    def _recompute(self, res: dict, env: dict) -> None:
        """番数/符/役满变了之后统一重算得点（以前这里有 5 份手抄）。"""
        res["pays"] = score.payments(
            int(res.get("han", 0)), int(res.get("fu", 0)),
            is_dealer=bool(env.get("is_dealer")), tsumo=bool(env.get("tsumo")),
            yakuman=int(res.get("yakuman", 0)),
            kiriage_mangan=bool(self.rules.get("kiriage_mangan")))

    def _wall_col4_drawn(self) -> bool:
        """牌山第 4 列（从**发牌起点**那一列数 1）是不是已经开始被摸了。

        牌山是 68 墩的环；发牌起点那一墩 = `wall_first_stack()`（1..68）。
        每列 17 墩（一列 = 屏幕上的「一条边」），所以：
          · 发牌起点在第 `k` 墩（0 起）→ 前 3 列一共要摸 (17 - k) + 17 + 17 墩
          · 再摸**一张**就算进第 4 列
        因为每局掷骰子的起点不同，k 不同 → 阈值每局都不一样（按 live_left 算出来的）。
        """
        n = self.wall_first_stack()
        if not n:
            return False
        k = (int(n) - 1) % 17                 # 起点在这一列里的位置（0 起）
        need_tiles = (51 - k) * 2 + 1         # 摸完前 3 列 + 第 4 列的第 1 张
        used = 124 - int(self.live_left())    # 活牌山一共 62 墩 = 124 张
        return used >= need_tiles

    def _settle_c30s2(self, res: dict, env: dict) -> None:
        """Card30 S2【W立】：立直和牌时，若牌山第 4 列已经被摸 → 里宝牌 +4 番

        （W立直本身在**立直宣言**时处理：持 30 号卡 → `double_riichi`，
           yaku 里「双立直 2 番 elif 立直 1 番」，不会叠加成 3 番。）
        """
        w = int(env["winner"])
        if not skills.owns_card(self.db, self, w, 30, strict=True):
            return
        if not self.is_riichi(w):
            return
        if not self._wall_col4_drawn():
            return
        add = 4
        hit = False
        for y in (res.get("yaku") or []):
            if y.get("name") == "宝牌":
                y["han"] = int(y.get("han", 0)) + add
                det = y.get("detail")
                if isinstance(det, dict):
                    det["里宝牌"] = int(det.get("里宝牌", 0)) + add
                hit = True
                break
        if not hit:
            res["yaku"] = list(res.get("yaku") or []) + [
                {"name": "宝牌", "han": add, "detail": {"里宝牌": add}}]
        res["han"] = int(res.get("han", 0)) + add
        self._recompute(res, env)
        res["c30s2"] = add

    @staticmethod
    def _c32_is_green(tiles: list[str]) -> bool:
        """索子清一色（1/5/7/9 索也算）/ 索子 + 只有发财 的混一色 → 绿一色。"""
        sou = False
        for t in tiles:
            k = kind_of(str(t))
            if k == "fa":
                continue
            if k.endswith("s"):
                sou = True
                continue
            return False
        return sou

    def _c32_all_tiles(self, w: int, res: dict) -> list[str]:
        tiles = list(self.hand(int(w)))
        for m in self.melds(int(w)):
            tiles += [str(x) for x in (m.get("tiles") or [])]
        t = res.get("_tile")
        if t and len(tiles) % 3 == 1:       # 荣和：和牌张还没进手牌
            tiles.append(str(t))
        return tiles

    def _settle_c32s2(self, res: dict, env: dict) -> None:
        """无知：对对和 → 四暗刻；索子清一色 / 只有发财的索子混一色 → 绿一色。

        两个都成立 → 双倍役满（役满张数各 +1）。
        """
        w = int(env["winner"])
        if not skills.owns_card(self.db, self, w, 32, strict=True):
            return
        if int(res.get("yakuman", 0)) > 0 and any(
                "绿一色" in str(y.get("name", "")) for y in (res.get("yaku") or [])):
            pass            # 已经自己判成绿一色了，别再叠一次
        names = [str(y.get("name", "")) for y in (res.get("yaku") or [])]
        add = 0
        if (any(n.startswith("对对和") for n in names)
                and not any(n.startswith("四暗刻") for n in names)):
            res.setdefault("yaku", []).append({"name": "四暗刻（无知）", "han": 13})
            add += 1
        if (not any("绿一色" in n for n in names)
                and self._c32_is_green(self._c32_all_tiles(w, res))):
            res.setdefault("yaku", []).append({"name": "绿一色（无知）", "han": 13})
            add += 1
        if add:
            res["yakuman"] = int(res.get("yakuman", 0)) + add
            self._recompute(res, env)

    def _settle_c29s2(self, res: dict, env: dict) -> None:
        """Card29 S2【精算】：非门前清和牌 → 把副露「当没鸣过」重判一遍番符

        · 吃 / 碰：3 张收回手里（当暗刻 / 暗顺）
        · 明杠 / 加杠：**当成暗杠**（保留在 melds 里，kind 改成 ankan）—— 用户口径
        · 暗杠：原样
        重判后**替换** res，再把它前面已经跑过的番数钩子按原顺序重放一遍
        （否则「主战馈赠 +3、协战精算」会把 +3 抹掉）。
        """
        w = int(env["winner"])
        if not skills.owns_card(self.db, self, w, 29, strict=True):
            return
        melds = self.melds(w)
        if not melds or agari.is_closed(melds):
            return                            # 本来就门清 → 不动
        win_tile = str(res.get("_tile", ""))
        tsumo = bool(res.get("_tsumo"))
        tiles = list(self.hand(w))
        if not tsumo and win_tile:
            tiles.append(win_tile)
        melds_new: list[dict] = []
        for m in melds:
            kind = str(m.get("kind", ""))
            if kind in ("minkan", "kakan"):
                m2 = dict(m)
                m2["kind"] = "ankan"          # 当成暗杠
                melds_new.append(m2)
            else:
                tiles.extend(str(t) for t in (m.get("tiles") or []))
        opts = res.get("_opts") or None
        ctx = self.win_ctx(w, tiles, win_tile, tsumo, judge_opts=opts)
        ctx["melds"] = melds_new
        # 精算**不能**把副露手「重判成四暗刻」（用户口径）→ 役满段跳过四暗刻，
        # 自然退化成 三暗刻 + 对对和 这类普通役
        ctx["no_suuankou"] = True
        new = yaku.judge(ctx)
        if not new.get("yaku"):
            return                            # 按口径不可能无役；保险起见不动
        keep = {"_opts": res.get("_opts"), "_tile": win_tile, "_tsumo": tsumo}
        res.clear()
        res.update(new)
        res.update(keep)
        res["real_yaku"] = True
        res["c29s2"] = True
        for card in list(env.get("_done") or []):
            hook = self._FAN_HOOKS.get(int(card))
            if hook and hook != "_settle_c29s2":
                getattr(self, hook)(res, env)

    def _settle_c28s2(self, res: dict, env: dict) -> None:
        """Card28 S2【蜕变】：打点每进一个档位就再升一档（按该档位的**最小番**计入）

        > 30符2番 且 <满贯 → 满贯(5) ／ 满贯 → 跳满(6) ／ 跳满 → 倍满(8)
        ／ 倍满 → 三倍满(11) ／ 三倍满 → 役满 ／ 役满不升
        「渣和」的 1 番 30 符够不着阈值，所以**不用特判**就被排除在外。
        """
        w = int(env["winner"])
        if res.get("yakuman"):
            return
        if not skills.owns_card(self.db, self, w, 28, strict=True):
            return
        nt = score.next_tier(int(res.get("han", 0)), int(res.get("fu", 0)),
                             kiriage_mangan=bool(self.rules.get("kiriage_mangan")))
        if nt is None:
            return
        new_han, _basic, name = nt
        old_han = int(res.get("han", 0))
        if name == "役满":
            res["yakuman"] = 1
            res["han"] = max(new_han, old_han)
            add = {"name": "蜕变（→ 役满）", "han": 0}
        else:
            res["han"] = new_han
            add = {"name": "蜕变（→ %s）" % name, "han": max(0, new_han - old_han)}
        res["yaku"] = list(res.get("yaku") or []) + [add]
        self._recompute(res, env)
        res["c28s2"] = name

    def _settle_dawa(self, res: dict, env: dict) -> None:
        """Card13 S2【渣和】：无役也能和 → 垫 1 番 30 符（固定，不叠手牌宝牌）

        它**不短路**链：后面的番数加成照常叠（馈赠 / 拔北 / 枷锁 / 蜕变…）。
        只有【满贯】对它特化放行（见 `_c28s1_blocks`）。
        """
        if res.get("real_yaku") or res.get("dawa") or not res.get("dawa_pending"):
            return
        res["dawa"] = True
        res["fu"] = 30
        res["fu_items"] = [("渣和（固定）", 30)]
        res["han"] = int(res.get("han", 0)) + 1
        res["yaku"] = list(res.get("yaku") or []) + [
            {"name": "渣和（无役和牌）", "han": 1}]
        self._recompute(res, env)

    def _settle_c44s2(self, res: dict, env: dict) -> None:
        """Card44 S2【电报】：宣言过明牌 → 这次和牌一律按 30 符 1 番算。

        ★ 只改 han / fu（番数链），得点链（自信 / 暖气）排在后面照常加成；
          不动 dawa 标记 → 【满贯】的 1 番 30 符 豁免**不适用**，照样被拦。
        ★ 役满不压（役满没有被压成 1 番的道理）。
        """
        w = int(env["winner"])
        if w not in self.c44s2_on:
            return
        if res.get("yakuman"):
            # 用户口径 2026-10-28：役满也压成 30 符 1 番
            res["yakuman_was"] = int(res.get("yakuman", 0))
            res["yakuman"] = 0
        old_han = int(res.get("han", 0))
        old_total = int((res.get("pays") or {}).get("total", 0) or 0)   # 压番之前的得点
        res["han"] = 1
        res["fu"] = 30
        res["fu_items"] = [("电报（明牌，固定 30 符）", 30)]
        res["yaku"] = [{"name": "电报（明牌，按 30 符 1 番计）", "han": 1}]
        self._recompute(res, env)
        res["c44s2"] = {"old_han": old_han,
                       "old_total": old_total,
                       "new_total": int((res.get("pays") or {}).get("total", 0) or 0),
                       "yakuman": int(res.get("yakuman_was", 0) or 0)}

    def c46s2_on(self, seat: int) -> bool:
        """【赤里】（46S2）：持卡 + 和牌这一刻处于立直状态（被动，不发动）。"""
        s = int(seat)
        if not self.is_riichi(s):
            return False
        return skills.owns_card(self.db, self, s, 46, strict=True)

    def _settle_c46s2(self, res: dict, env: dict) -> None:
        """Card46 S2【赤里】：立直和牌 → 里宝牌换成「和到的那张」，原来那几张作废。

        · 和到的那张牌在「手牌 + 副露」里有几张（荣和再把铳张算上）→ 几番里宝；
        · 和到的是 5m / 5p / 5s（含赤 5）→ 再多 1 番，播报写【赤里】1 番；
        · 役满不掺（役满本来就按役满算）。
        """
        w = int(env["winner"])
        if not self.c46s2_on(w):
            return
        if res.get("yakuman"):
            return
        t = str(res.get("win_tile") or "")
        if not t:
            return
        k = kind_of(t)
        tiles = [str(x) for x in self.hand(w)]
        for m in self.melds(w):
            tiles += [str(x) for x in (m.get("tiles") or [])]
        if str(env.get("result", "")) == "ron":
            tiles.append(t)                      # 荣和那张不在手里
        n = sum(1 for x in tiles if kind_of(x) == k)
        if n < 1:
            n = 1
        five = k in ("5m", "5p", "5s")
        res["han"] = int(res.get("han", 0)) + int(n) + (1 if five else 0)
        res["yaku"] = list(res.get("yaku") or []) + [
            {"name": "赤里（和到的「%s」算里宝）" % t, "han": int(n)}]
        if five:
            res["yaku"] = list(res.get("yaku") or []) + [{"name": "赤里", "han": 1}]
        self._recompute(res, env)
        res["c46s2"] = int(n) + (1 if five else 0)

    def _settle_c25s2(self, res: dict, env: dict) -> None:
        """Card25 S2【宝牌的集合】：本局每开一次杠 +4 番（算进「宝牌」条目）

        以前这段写在 `win_ctx` 里（判番时就加），等于永远排在所有卡之前；
        现在按卡序在 25 号卡这一格加。
        """
        w = int(env["winner"])
        if w not in self.c25s2_on or res.get("yakuman"):
            return
        n = 4 * self.kan_count()
        if n <= 0:
            return
        hit = False
        for y in (res.get("yaku") or []):
            if y.get("name") == "宝牌":
                y["han"] = int(y.get("han", 0)) + n
                det = y.get("detail")
                if isinstance(det, dict):
                    det["宝牌的集合"] = int(det.get("宝牌的集合", 0)) + n
                hit = True
                break
        if not hit:
            res["yaku"] = list(res.get("yaku") or []) + [
                {"name": "宝牌", "han": n, "detail": {"宝牌的集合": n}}]
        res["han"] = int(res.get("han", 0)) + n
        self._recompute(res, env)
        res["c25s2"] = n

    # ── ① 番数链 ──────────────────────────────────────────────
    def _settle_nuki(self, res: dict, env: dict) -> None:
        """Card05 S2「拔北」：本局拔过几次就 +几番"""
        if res.get("yakuman"):
            return
        n = int(self.nuki_count.get(int(env["winner"]), 0))
        if n <= 0:
            return
        res["yaku"] = list(res.get("yaku") or []) + [{"name": "拔北", "han": n}]
        res["han"] = int(res["han"]) + n
        self._recompute(res, env)
        res["nuki"] = n

    def _duel_counter_tick(self, winner: int) -> None:
        """Card08 S2「决斗标记」的**全场**副作用：别人和牌 → 持卡者的计数器涨。

        ★ 这不是「和牌者自己的番数效果」，跟卡序无关，所以在 `_finish` 里
          无条件先跑一次（不能挂在赢家的 `cards_in_order` 上 —— 赢家手上
          没有 8 号卡时那个钩子根本不会触发）。
        """
        w = int(winner)
        n_marks = len(self.duel_marks)
        if not n_marks:
            return
        gained = False
        for s in range(4):
            if s == w or not self.owns_duel_s2(s):
                continue
            self.duel_counter[s] = int(self.duel_counter.get(s, 0)) + n_marks
            gained = True
        if gained:
            self._save_duel_meta()

    def _settle_duel_marks(self, res: dict, env: dict) -> None:
        """Card08 S2「决斗标记」：我胡牌 → 额外 +计数器 番"""
        w = int(env["winner"])
        bonus = int(self.duel_counter.get(w, 0))
        if bonus <= 0 or not self.owns_duel_s2(w):
            return
        if res.get("yakuman"):
            return
        res["han"] = int(res["han"]) + bonus
        res["yaku"] = list(res.get("yaku") or []) + [
            {"name": "决斗标记（+%d 番）" % bonus, "han": bonus}]
        self._recompute(res, env)
        res["duel_bonus"] = bonus

    def _settle_jiasuo(self, res: dict, env: dict) -> None:
        """枷锁（Card18 S1）：番数正好等于期待值 → 番数翻倍"""
        w = int(env["winner"])
        want = int(self.jiasuo.get(w, 0))
        if want <= 0 or int(res.get("han", 0)) != want:
            return
        res["han"] = int(res["han"]) * 2
        res["yaku"] = list(res.get("yaku") or []) + [
            {"name": "枷锁（%d 番成真，翻倍）" % want, "han": int(res["han"])}]
        self._recompute(res, env)
        res["jiasuo"] = want

    def _settle_gift(self, res: dict, env: dict) -> None:
        """馈赠（Card21 S2）：番数加成（1→+1，2/3→+3）"""
        gv = int(self.gift.get(int(env["winner"]), 0))
        if not gv or res.get("yakuman"):
            return
        add = 1 if gv == 1 else 3
        res["han"] = int(res["han"]) + add
        res["yaku"] = list(res.get("yaku") or []) + [
            {"name": "馈赠（+%d 番）" % add, "han": add}]
        self._recompute(res, env)
        res["gift"] = gv

    # ── ② 得点链（固定顺序）────────────────────────────────────
    def _settle_confidence(self, res: dict, env: dict) -> None:
        """Card03 S1「自信」：和牌者番数双倍（役满没有番数，不受影响）"""
        w = int(env["winner"])
        if w not in self.confident or res.get("yakuman"):
            return
        base_han = int(res.get("han", 0))
        res["han"] = base_han * 2
        # 播报里把奖励番单独列出来（和 Card01 的奖励番一个写法）
        res["yaku"] = list(res.get("yaku") or []) + [
            {"name": "自信（番数双倍）", "han": base_han}]
        self._recompute(res, env)
        res["confidence"] = True

    def _settle_multi(self, res: dict, env: dict) -> None:
        """多面：按听的牌种数放大得点（得点性质，永远在番数之后）"""
        w = int(env["winner"])
        if not self.owns_c(w, 16) or res.get("yakuman"):
            return
        n = self._multi_face(w, str(env["result"]))
        if n < 3:
            return
        mult = n - 1
        p = dict(res["pays"])
        for k in ("total", "each", "from_dealer", "from_other", "basic"):
            if k in p and p[k]:
                p[k] = int(math.ceil(int(p[k]) * mult / 100.0) * 100)
        res["pays"] = p
        res["multi"] = mult
        res["multi_n"] = n
        res["yaku"] = list(res.get("yaku") or []) + [
            {"name": "多面（%d 面，得点 ×%d）" % (n, mult), "han": 0}]

    def _settle_heat(self, res: dict, env: dict) -> None:
        """暖气（Card23 S1）：冷系牌 0 张 ×3、≤3 张 ×2（得点性质）"""
        w = int(env["winner"])
        if not self.owns_cn(w, 23):
            return
        cold = self._cold_count(w)
        cm = 3 if cold == 0 else (2 if cold <= 3 else 1)
        if cm <= 1:
            return
        p2 = dict(res["pays"])
        for k in ("total", "each", "from_dealer", "from_other", "basic"):
            if k in p2 and p2[k]:
                p2[k] = int(math.ceil(int(p2[k]) * cm / 100.0) * 100)
        res["pays"] = p2
        res["nuanqi"] = cm
        res["yaku"] = list(res.get("yaku") or []) + [
            {"name": "暖气（冷系 %d 张，得点 ×%d）" % (cold, cm), "han": 0}]

    def settle_preview(self, winner: int, loser: int | None, result: str,
                       res: dict, dry_run: bool = False) -> dict:
        """跑一遍结算链（番数链 → 得点链），**不落账**。

        dry_run=True：连「决斗标记计数器增长」这种全场副作用都不做 ——
        给 28S1【满贯】的预测（每次 `legal_actions` 都会跑）用。
        """
        env = {"winner": int(winner), "loser": loser, "result": result,
               "tsumo": result == "tsumo",
               # 【夺目】(42S2)：只改「算点数时谁是庄家」，不动 self.dealer
               "is_dealer": int(winner) == int(self.c42s2_dealer())}
        res.setdefault("han", 0)
        res.setdefault("fu", 0)
        if not dry_run:
            self._duel_counter_tick(int(winner))   # 全场副作用，先结（不看卡序）
        done: list[int] = []
        for _card in skills.cards_in_order(self.db, self, int(winner)):
            _hook = self._FAN_HOOKS.get(int(_card))
            if _hook:
                env["_done"] = done        # 精算要靠它把「前面跑过的钩子」重放一遍
                getattr(self, _hook)(res, env)
                done.append(int(_card))
        env["_done"] = done
        # 【夺目】(42S2)：算点数用的庄家可能被改过 → 按 env 重算一次基础 pays
        #（幂等：han/fu 没变时结果一样；必须排在得点链之前）
        self._recompute(res, env)
        for _hook in self._POINT_HOOKS:
            getattr(self, _hook)(res, env)
        return res

    def _finish(self, winner: int, loser: int | None, result: str, res: dict) -> None:
        # 【夺目】(42S2) **结算那一刻问一次**（用户口径 2026-10-28）：
        #   以前只能自己在切牌前点图标，很容易错过（#98）。这里先把这次结算挂起，
        #   等 c42s2_answer（或 15 秒超时）回来再真正跑下去。
        if self.c42s2_settle is not None:
            return                        # 已经挂起了：别用第二笔结算盖掉它
        _ask42 = self._c42s2_askers()
        if _ask42:
            self.c42s2_settle = {"winner": int(winner),
                                 "loser": None if loser is None else int(loser),
                                 "result": str(result),
                                 "res": dict(res),
                                 "phase": str(self.phase),
                                 "waiting": _ask42, "ts": time.time()}
            # phase 换成「等夺目」：不这么写的话 _drive_others 会以为还在打牌，
            # 替赢家再打一张 → 这一局的和牌就丢了。
            self.phase = "c42s2_ask"
            self.save_flags()
            return
        # ══ 结算链 ═══════════════════════════════════════════════════
        #  ① 番数链：**按卡序**（主战 → 协战 → 传承），只改 han / fu
        #  ② 得点链：**固定顺序**（自信 → 多面 → 暖气），只改 pays
        #  两条链的顺序规则见交接文档 §50；加新技能时只往这两张表里塞。
        # 故意（36S2）：固定支付 1000 点 —— 不能跑番数链（`_recompute` 会按 han/fu
        # 把 pays 重算成 0），所以直接用它自己带的那份 pays。
        if not res.get("c36s2"):
            res = self.settle_preview(winner, loser, result, res)
        han, fu, pays = res["han"], res["fu"], res["pays"]
        total = pays.get("total", 0)
        # 结算里「改了支付」的技能 → 播报面板补一句（用户口径 2026-10-28）
        _pay_notes: list[str] = []
        _c44b = res.get("c44s2") or {}
        _c44b_old = int(_c44b.get("old_total", 0) or 0)
        if _c44b_old > 0 and _c44b_old != int(total):
            _pay_notes.append("得点 %d → %d（电报）" % (_c44b_old, int(total)))
        deltas = {winner: total}
        # 立直供托（每根 1000）归和牌的人 —— 挪到结算最后再加（供托不该被减半）
        sticks = int(self.db._one("SELECT riichi_sticks FROM rounds WHERE round_id=?",
                                  (self.round_id,)) or 0)
        # 连接：被连接者的这次得失点，与我平分（互铳不生效）
        for s0, t0 in list(self.link.items()):
            if s0 != winner and t0 != winner:
                continue
            partner = t0 if s0 == winner else s0
            if result == "ron" and loser is not None and loser in (s0, t0):
                continue                                   # 互铳
            d = int(deltas.get(winner, 0))
            half = int(round(d / 2.0 / 100.0) * 100)
            deltas[winner] = d - half
            deltas[partner] = int(deltas.get(partner, 0)) + half
            if result == "ron" and loser is not None:
                d2 = int(deltas.get(loser, 0))
                half2 = int(round(d2 / 2.0 / 100.0) * 100)
                deltas[loser] = d2 - half2
                deltas[partner] = int(deltas.get(partner, 0)) + half2
            res["link"] = {"with": partner, "seat": s0}
        if result == "ron" and loser is not None:
            deltas[loser] = -total
        else:
            for s in range(4):
                if s == winner:
                    continue
                deltas[s] = -(pays["each"] if winner == self.c42s2_dealer() else
                              (pays["from_dealer"] if s == self.c42s2_dealer()
                               else pays["from_other"]))
        # ── Card44 S1「弃子」：失点 ≥ 16000 或 > 我的点数 → 这一笔不用付 ──
        #   收付链**最前**（后面的自信 / 坚韧 / 逆势 / 岭上 / 逆袭 都在剩下的数上做）
        _c44 = self._c44s1_waive(winner, deltas, result)
        if _c44:
            res["c44s1"] = _c44
            _waive_who = "、".join("%d 号位" % int(x.get("seat", -1)) for x in _c44)
            _waive_amt = sum(int(x.get("saved", 0) or 0) for x in _c44)
            _pay_notes.append("%s 失点 %d → 0（弃子）" % (_waive_who, _waive_amt))
        # ── 自信：没和牌的人，失点双倍（放铳 / 其他家自摸都算）──
        # 和牌的人已经按「番数双倍」算过了，这里不再重复翻倍。
        if winner not in self.confident:
            extra = 0
            doubled = []
            for s in sorted(self.confident):
                v = deltas.get(s, 0)
                if v < 0:
                    deltas[s] = v * 2
                    extra += -v
                    doubled.append(s)
            if extra:
                deltas[winner] = deltas.get(winner, 0) + extra
                total += extra
                res["confidence_payers"] = doubled
        # ── Card06 Skill2「坚韧」：东场 → 我自己付的那一份减半（向上取整到百位）──
        # 「和牌的人得点不变」：少付的那份不回补给赢家，只让我少掉血（这一局总分会少一点）。
        halved: list[int] = []
        for s in range(4):
            if s == winner:
                continue
            v = int(deltas.get(s, 0))
            if v >= 0 or not self.owns_tenacity(s):
                continue
            deltas[s] = -((-v + 199) // 200 * 100)      # ceil(一半) 取到 100 的整数倍
            halved.append(int(s))
        if halved:
            res["tenacity_payers"] = halved
            res["yaku"] = list(res.get("yaku") or []) + [
                {"name": "坚韧（失点减半）", "han": 0}]
        # ── Card35 S2【逆势】：别人和牌 + 场上有人副露过 → 这一局收付减半 ──
        if self._c35s2_half(winner, deltas, pays):
            total = int(deltas.get(winner, 0))
            res["c35s2"] = True
            res["yaku"] = list(res.get("yaku") or []) + [
                {"name": "逆势（得点减半）", "han": 0}]
        # ── Card37 S1【岭上开花】：这一手得点 ×2（收付链最后一道）──
        if res.get("c37s1"):
            for _k in list(deltas.keys()):
                deltas[_k] = int(deltas[_k]) * 2
            total = int(total) * 2
            for _k in ("total", "each", "from_dealer", "from_other", "ron"):
                if _k in pays:
                    pays[_k] = int(pays[_k]) * 2
            res["yaku"] = list(res.get("yaku") or []) + [
                {"name": "岭上开花（得点×2）", "han": 0}]
        # ── Card38 S2「逆袭」：自己点数 < 35000 → 本次和牌得点 ×2 ──
        #   位置就在收付链最后一段：番数链、拦截链都已经跑完（用户口径）。
        if not res.get("c38s2") and self.c38s2_on(int(winner)):
            for _k in list(deltas.keys()):
                deltas[_k] = int(deltas[_k]) * 2
            total = int(total) * 2
            for _k in ("total", "each", "from_dealer", "from_other", "ron"):
                if _k in pays:
                    pays[_k] = int(pays[_k]) * 2
            res["c38s2"] = True
            res["yaku"] = list(res.get("yaku") or []) + [
                {"name": "逆袭（得点×2）", "han": 0}]
        # ── Card36 S2「故意」× 天梯（26S2）特判 ──
        #   这 1000 点：天梯还没记过 → 记成他的第一次成绩；记过 → 直接打断，天梯从 0 开始。
        # ── Card45 S1【神境】：得点上限（闲家 32000 / 庄家 48000）──
        #   收付链最后一道：×2 ×3（岭上开花 / 逆袭）都算完，再压上限。
        _c45cap = self._c45s1_cap(int(winner), deltas)
        if _c45cap:
            total = int(deltas.get(int(winner), 0))
            pays["total"] = int(total)
            res["c45s1"] = int(_c45cap)
            res["yaku"] = list(res.get("yaku") or []) + [
                {"name": "神境（得点上限 %d）" % int(_c45cap), "han": 0}]
        _skip_c26 = False
        if res.get("c36s2"):
            self._c36s2_c26(int(winner))
            _skip_c26 = True                  # 这一手不走天梯的「比上次高」判定
        # ── Card26 S2「天梯」：得点没比上次高 300 → 这一手白干 + 罚点 + 本局流局 ──
        if not _skip_c26 and self._c26_check(winner, total):
            self._c26_fail(winner, total, res)
            return
        if not _skip_c26:
            self._c26_commit(winner, total)
        # ── Card41 S2「局终」：复制过技能又没和牌 → 每个复制品付原作者 1000 ──
        _c41pay = self._c41s2_pay(int(winner), deltas)
        if _c41pay:
            res["c41s2"] = _c41pay
        if sticks:
            deltas[winner] = int(deltas.get(winner, 0)) + 1000 * sticks
            with self.db.tx():
                self.db.conn.execute("UPDATE rounds SET riichi_sticks = 0 WHERE round_id=?",
                                     (self.round_id,))
        # A12：收付表必须守恒（供托已经单独加进 winner 了）。
        #   不守恒就是某个钩子写死了数值（历史上出现过 {2:+10000, 1:-2000}）。
        _dsum = sum(int(v) for v in deltas.values())
        if _dsum != 0:
            print("[SCORE] 收付不守恒！round=%s result=%s han=%s fu=%s points=%s "
                  "deltas=%s sum=%d"
                  % (self.round_id, result, han, fu, total, deltas, _dsum), flush=True)
            res["deltas_sum"] = _dsum
        # 宝牌明细也一起落库（以前 dora={}，出了"少算一张"根本查不出来）
        _dora_detail = {}
        for _y in (res.get("yaku") or []):
            if str(_y.get("name", "")).startswith("宝牌"):
                _dora_detail = dict(_y.get("detail") or {})
                _dora_detail["han"] = int(_y.get("han", 0))
                break
        self.db.finish_round(self.round_id, result, winner_seat=winner, loser_seat=loser,
                             han=han, fu=fu, points=total,
                             yaku=[{"name": y["name"], "han": int(y.get("han", 0)),
                                    "detail": y.get("detail")} for y in res["yaku"]],
                             dora=_dora_detail, deltas=deltas)
        self.phase = "ended"                 # ← 停止游戏：legal_actions 变空、advance 不再发牌
        self.round_phase = "end"
        _wt = str(res.get("win_tile") or res.get("_tile") or "")
        if not _wt:
            _d = self.drawn_tile(int(winner))
            _wt = str(_d) if _d else ""
        if not _wt and loser is not None:
            _dl = self.discards(int(loser))
            _wt = str(_dl[-1]) if _dl else ""
        self.result = {"result": result, "winner": winner, "loser": loser,
                       "yaku": res["yaku"], "yaku_names": [y["name"] for y in res["yaku"]],
                       "han": han, "fu": fu, "points": total, "yakuman": res.get("yakuman", 0),
                       "pays": pays, "deltas": deltas, "fu_items": res.get("fu_items", []),
                       "c41s2": res.get("c41s2"),
                       "c44s1": res.get("c44s1"),
                       "c44s2": res.get("c44s2"),
                       "c45s1": res.get("c45s1"),
                       "c46s2": res.get("c46s2"),
                       "duel_bonus": int(res.get("duel_bonus", 0)),
                       # 结算播报要贴「和牌家的手牌」：暗手(13/10/7) + 副露 + 和牌那张
                       # 技能强制和牌时，win_tile 就是「被算作铳」的那一张
                       "hand": self.hand13(int(winner)),
                       "melds": self.melds(int(winner)),
                       "win_tile": _wt,
                       "scores": self.scores(), "stopped": True}
        if _pay_notes:
            self._note_pay_broadcast(int(winner), 44, 1, "；".join(_pay_notes))
        self._print_result()
        self.save_flags()                 # 结果也要落库（别的进程要读得到）

    # ── Card27 S1「调包」：手牌 ⇄ 别人牌河的明牌 + 标记那一家 ────────
    def c27s1_targets(self, seat: int) -> list[int]:
        """能换的牌河 seq：**别人的、明置的、没被鸣走的**。
        （立直宣言牌可以换 —— 和【间合】不同；暗置牌不能换）"""
        s = int(seat)
        out: list[int] = []
        for r in self.db._rows(
                "SELECT seq, seat, called, face_down FROM round_discards "
                "WHERE round_id=? ORDER BY seq", (self.round_id,)):
            if int(r["seat"]) == s:
                continue
            if int(r["called"] or 0) or int(r["face_down"] or 0):
                continue
            out.append(int(r["seq"]))
        return out

    def c27s1_can(self, seat: int) -> bool:
        s = int(seat)
        if self.skill_used(s, 27, 1):
            return False                     # 本小局一次
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None:
            return False
        if self.is_riichi(s):
            return False
        if not skills.owns_card(self.db, self, s, 27, strict=True):
            return False
        return bool(self.c27s1_targets(s))

    def c27s1_swap(self, seat: int, hand_tile: str, river_seq: int) -> dict:
        """换牌面（和间合同一套 swap_hand_river）：换的谁的牌就进谁的牌河，换进来的进我手里。"""
        s = int(seat)
        if not self.c27s1_can(s):
            raise RuleError("调包：要刚摸完牌、而且本小局还没用过")
        if int(river_seq) not in self.c27s1_targets(s):
            raise RuleError("调包：只能换别人牌河里的明牌")
        self._assert_hand_mutable(s)
        row = self.db._row(
            "SELECT seat, wall_seq, tile FROM round_discards WHERE round_id=? AND seq=?",
            (self.round_id, int(river_seq)))
        if row is None:
            raise RuleError("这张牌不在牌河里")
        tgt = int(row["seat"])
        hrow = self.db._row(
            "SELECT wall_seq FROM round_hands WHERE round_id=? AND seat=? AND tile=? "
            "ORDER BY is_drawn, slot LIMIT 1", (self.round_id, s, str(hand_tile)))
        if hrow is None:
            raise RuleError(f"手里没有 {hand_tile}")
        hseq = int(hrow["wall_seq"])
        got = str(row["tile"])
        self.do_swap("hand_river", s, "调包", hand_seq=hseq,
                     river_seq=int(river_seq), face_down=None)
        with self.db.tx():
            # 换进来的那张算「刚摸到的」
            self.db.conn.execute(
                "UPDATE round_hands SET is_drawn=0 WHERE round_id=? AND seat=?",
                (self.round_id, s))
            self.db.conn.execute(
                "UPDATE round_hands SET is_drawn=1 WHERE round_id=? AND wall_seq=?",
                (self.round_id, hseq))
        self.c27_mark[s] = tgt                  # ★ 标记那一家（S1/S2 共用一个槽）
        self.c27_cnt[s] = 0
        self.note_use(s, 27, 1)                 # 一次性
        self.save_flags()
        return {"hand": str(hand_tile), "got": got, "river_seat": tgt,
                "mark": tgt, "cnt": 0}

    # ── Card27 S2「命中」：有役听牌 → 暗置（可能立直）打出 + 标记 + 手切计数 ──
    def c27s2_discards(self, seat: int) -> list[str]:
        """切出去之后**仍然是「有役听牌 或 门清」**的牌。

        门清就够了：门清自摸和本身就是役（用户口径「门清状态这个闸门肯定能过」）。
        有【渣和】的话，无役听牌也算。
        """
        s = int(seat)
        hand = list(self.hand(s))
        if len(hand) % 3 != 2:
            return []
        melds = self.melds(s)
        try:
            kinds = set(agari.losing_tiles(counts_of(hand), melds))
        except Exception:
            return []
        base = self.tenpai_base(s)             # 局面 + 技能开关（渣和 / 宝牌的集合…）
        out: list[str] = []
        seen: set[str] = set()
        for t in hand:
            k = kind_of(t)
            if k not in kinds or k in seen:
                continue
            seen.add(k)
            after = list(hand)
            after.remove(t)
            # 渣和由 tenpai_base 的 dawa 开关负责 → 这里不再特判
            try:
                ok = tenpai.is_tenpai_with_yaku(after, melds, base, tsumo_ok=True)
            except Exception:
                ok = False
            if ok:
                out.append(str(t))
        return out

    def c27s2_can(self, seat: int) -> bool:
        s = int(seat)
        if self.skill_used(s, 27, 2):
            return False                     # 本小局一次
        if self.phase != "discard" or self.turn is None or int(self.turn) != s:
            return False
        if self.drawn_tile(s) is None:
            return False
        if self.is_riichi(s) or s in self.no_win:
            return False
        if not skills.owns_card(self.db, self, s, 27, strict=True):
            return False
        return bool(self.c27s2_discards(s))

    def c27s2_declare(self, seat: int, tile: str) -> dict:
        """选一张「切出后仍有役听牌/门清」的牌 → 暗置打出（门清就连立直一起）。"""
        s = int(seat)
        if not self.c27s2_can(s):
            raise RuleError("命中：要刚摸完牌、而且本小局还没用过")
        t = str(tile)
        if t not in self.c27s2_discards(s):
            raise RuleError("命中：这张切出去就没有役听牌了")
        self._assert_hand_mutable(s)
        closed = agari.is_closed(self.melds(s))
        do_riichi = bool(closed and t in self.riichi_discards(s))
        self.note_use(s, 27, 2)              # 一次性（失败也不退）
        # 标记：字牌不标；147 → 下家 / 258 → 对家 / 369 → 上家
        tgt = -1
        if not is_honor(t):
            r = tile_number(t) % 3           # 1 → 下家, 2 → 对家, 0 → 上家
            tgt = (s + (1 if r == 1 else (2 if r == 2 else 3))) % 4
            self.c27_mark[s] = tgt
            self.c27_cnt[s] = 0
        self.save_flags()
        # ★ 顺序很重要：**先把宣言牌打出去**，打完才进入「只能摸切」。
        #   以前先 `c27_s2.add(s)` 再打 → `_do_discard` 里「命中后只能摸切」那条
        #   硬校验把自己这张宣言牌拦下（tile != 刚摸的那张就拒），于是
        #   技能已经记成发动过、牌却没打出去，这一巡只剩摸切 → 听牌白废。
        ev = self._do_discard(s, t, riichi=do_riichi, face_down=True)
        if self.phase != "ended" and self.result is None:
            self.c27_s2.add(s)               # 从**下一巡**开始：只能摸切
            self.save_flags()
        return {"seat": s, "tile": t, "riichi": do_riichi, "mark": tgt,
                "cnt": int(self.c27_cnt.get(s, 0)), "event": ev}

    # ── 27S2 的计数与「他对我出铳」 ────────────────────────────
    def _c27_tick(self, loser: int, tsumogiri: bool) -> list[int]:
        """loser 打了一张：被我标记的、且我开着命中 → 计数 +1。返回计数到 3 的我。"""
        if tsumogiri:
            return []                        # 摸切不算
        out: list[int] = []
        for owner in sorted(self.c27_s2):
            if self.c34_muted(int(owner)):
                continue                     # 【厄运】：三巡内不累计（等于不引爆）
            if int(self.c27_mark.get(int(owner), -1)) != int(loser):
                continue
            c = int(self.c27_cnt.get(int(owner), 0)) + 1
            self.c27_cnt[int(owner)] = c
            if c == 3:
                out.append(int(owner))
        if out:
            self._act_sync_compat()
            self.save_flags()
        return out

    def wall_find(self, wants, include_dead: bool = True) -> tuple[int, str] | None:
        """按**摸牌顺序**找第一张「属于 wants 的牌」，返回 (wall_seq, tile)。

        · 先扫剩余活牌（`next_no` 往后，跳过王牌），再扫**王牌区**（`zone='dead'`）
        · wants 是**牌种**集合（"1p" / "5m"…），赤 5 按 5 算
        · 找不到返回 None

        用户口径 2026-10-28：所有「牌山里有没有这张牌」的判断统一走这个函数
        （命中 Card27S2 / 海底 Card34S2 都用它）。
        """
        want = {str(k) for k in (wants or [])}
        if not want:
            return None
        first = self.wall_first_stack()
        # ★ 2026-10-28：按 `_upcoming_wall_seqs` 扫（它就是「接下来要摸的牌」的
        #   唯一权威顺序，跳过王牌、跳过已摸走的）。以前自己按编号算，
        #   碰到配牌/杠之后会指到**已经摸走**的牌上 —— 海底就会锁到一张不在牌山里的牌。
        for seq in self._upcoming_wall_seqs(max(int(self.live_left()), 0)):
            row = self.db._row("SELECT tile FROM round_wall WHERE round_id=? AND seq=?",
                               (self.round_id, int(seq)))
            t = str(row["tile"]) if row else ""
            if t and kind_of(t) in want:
                return int(seq), t
        if not include_dead:
            return None
        # ★ 王牌不在 zone='dead' 里（库里 136 张全是 'live'）——按**牌号**算：
        #   dead_stack_nos = 最后的 7 墩（岭上 2 + 宝牌/里宝 4 + 保障 1）= 14 张
        for k in wallmodel.dead_stack_nos(first):
            for t_no in wallmodel.tile_nos_of_stack(k):
                seq = int(wallmodel.seq_of_tile(t_no))
                row = self.db._row(
                    "SELECT tile FROM round_wall WHERE round_id=? AND seq=? "
                    "AND dealt_to IS NULL", (self.round_id, seq))
                t = str(row["tile"]) if row else ""
                if t and kind_of(t) in want:
                    return seq, t
        return None

    def _c27_wall_win(self, seat: int, waits: set[str]) -> str:
        """按顺序读剩下的牌山（含王牌），找到第一张「我的铳牌」。"""
        # 命中只认「还能摸到的活牌」：王牌摸不到，不算（和海底不同）
        hit = self.wall_find(waits, include_dead=False)
        return hit[1] if hit else ""

    def c27s2_fail(self, me: int) -> None:
        """命中失败（牌山没有铳牌 / 荣和链路被堵）→ 技能作废，游戏继续。"""
        s = int(me)
        self.c27_s2.discard(s)
        self.c27_mark.pop(s, None)
        self.c27_cnt.pop(s, None)
        self.save_flags()

    def _c27_try_ron(self, me: int, loser: int) -> dict | None:
        """计数器到 3：按牌山第一张铳牌结算「他对我出铳」。失败返回 None。"""
        s, l = int(me), int(loser)
        waits = set(self.waits(s))
        if not waits:
            return None
        tile = self._c27_wall_win(s, waits)
        if tile == "":
            return None
        if not self._win_ok(s, tile, tsumo=False, furiten_ok=True):
            return None                      # 恶灵 / 看破代价 / 海神 … 堵住荣和
        res = self._judge_win(s, tile, tsumo=False)
        if res is None:
            return None
        if self._c28s1_blocks(self.settle_preview(
                s, l, "ron", self._res_clone(res), dry_run=True)):
            return None                      # 不足满贯 → 作废（调用方会 c27s2_fail）
        self.c27_s2.discard(s)
        self.c27_mark.pop(s, None)
        self.c27_cnt.pop(s, None)
        self._finish(s, l, "ron", res)
        return self._event("c27_ron", {"seat": s, "from": l, "tile": tile,
                                       "yaku": res.get("yaku"), "han": res.get("han"),
                                       "fu": res.get("fu"), "points": res.get("pays")})

    def _c27_after_discard(self, loser: int, tsumogiri: bool) -> dict | None:
        """打牌之后：计数；到 3 就立刻结算（在鸣牌窗口之前）。"""
        hits = self._c27_tick(int(loser), bool(tsumogiri))
        if not hits:
            return None
        for me in hits:
            ev = self._c27_try_ron(int(me), int(loser))
            if ev is not None:
                return ev
            self.c27s2_fail(int(me))         # 失败 = 技能作废
        return None

    # ── Card26 S2「天梯」结算 ──────────────────────────────────
    def _c26_check(self, winner: int, total: int) -> bool:
        """得点够不够？True = 不合格（要罚）。发动之后的第一次没有大小要求。"""
        s = int(winner)
        if s not in self.c26s2_on:
            return False
        last = int(self.c26_last.get(s, -1))
        if last < 0:
            return False                      # 第一次：随便多少都行
        return int(total) <= last + 300

    def _c26_commit(self, winner: int, total: int) -> None:
        """这一手算数：记下得点、天梯次数 +1。"""
        s = int(winner)
        if s not in self.c26s2_on:
            return
        self.c26_last[s] = int(total)
        self.c26_n[s] = int(self.c26_n.get(s, 0)) + 1

    def _c26_fail(self, winner: int, total: int, res: dict) -> None:
        """天梯失败：拿不到和牌得点，付每家 3000；本局按「无人听牌的荒牌流局」记。"""
        s = int(winner)
        self.c26_n[s] = C26_N0                # 断连：回到初始值
        self.c26_last[s] = -1
        with self.db.tx():
            self.db._score(self.round_id, s, -9000, "天梯失败")
            for o in range(4):
                if int(o) != s:
                    self.db._score(self.round_id, o, 3000, "天梯失败")
        self._ryuukyoku("exhaustive", force_no_tenpai=True)
        if isinstance(self.result, dict):
            self.result["c26_fail"] = {"seat": s, "total": int(total),
                                       "yaku": [y["name"] for y in (res.get("yaku") or [])]}
            self.save_flags()                 # 失败原因也要落库（别的进程读得到）

    def _c36s2_c26(self, winner: int) -> None:
        """【故意】付给天梯持有者时的特判（用户口径 2026-10-28）。

        · 天梯还没记录过点数 → 1000 记成他的第一次成绩（n 也 +1）
        · 已经记录过 → 直接打断天梯：n 回到初始值、last 清空（下次重新算第一次）
        """
        s = int(winner)
        if s not in self.c26s2_on:
            return
        if int(self.c26_last.get(s, -1)) < 0:
            self.c26_last[s] = 1000
            self.c26_n[s] = int(self.c26_n.get(s, 0)) + 1
        else:
            self.c26_n[s] = C26_N0
            self.c26_last[s] = -1
        self.save_flags()

    # 和牌后把「番 / 符 / 得点」打印出来（服务端控制台）
    def _print_result(self) -> None:
        r = self.result or {}
        if r.get("result") == "ryuukyoku":
            return
        win = r.get("winner")
        seat_wind = ["东", "南", "西", "北"][(win - self.dealer) % 4]
        dealer_txt = ", 亲家" if win == self.dealer else ""
        how = "自摸" if r.get("result") == "tsumo" else f"荣和 (放铳 {r.get('loser')} 号位)"
        print("======== 和了 ========")
        print(f"{win} 号位 ({seat_wind}家{dealer_txt}) {how}")
        print("役种: " + ", ".join(r.get("yaku_names", [])))
        if r.get("yakuman"):
            print(f"役满 x{r['yakuman']}")
        else:
            print(f"番符: {r.get('han')} 番 {r.get('fu')} 符")
        pay = r.get("pays", {})
        if r.get("result") == "tsumo":
            detail = (f"其余三家每家 {pay.get('each', 0)}" if win == self.dealer
                      else f"亲家 {pay.get('from_dealer', 0)} / 子家 {pay.get('from_other', 0)}")
        else:
            detail = "放铳者全额"
        print(f"得点: {r.get('points')} ({detail})")
        print(f"收付: {r.get('deltas')}")
        print(f"总分: {r.get('scores')}")
        print("======== 本局结束，游戏停止 ========")

    def _ryuukyoku(self, reason: str, force_no_tenpai: bool = False) -> dict:
        """流局。

        · 荒牌流局（exhaustive）：听牌的人分 3000（没听的人每人出 1000）
        · 途中流局（九种九牌 / 四风连打 / 四家立直 / 四杠散了 / 三家和了）：
          这一局作废，没有听牌罚符；已经挂出来的立直供托**原样退还**给立直的人
        · 荒牌流局时供托留在桌上，下一局继续挂（由 op="next" 带过去）
        · 本场/亲家怎么走不在这里管：存进 rounds.result 由 op="next" 决定
        """
        tenpai = [] if force_no_tenpai else [s for s in range(4)
                  if agari.is_tenpai(self.hand_counts(s), self.melds(s))]
        deltas: dict = {}
        if reason == "exhaustive" and tenpai and len(tenpai) < 4:
            pay = 3000 // len(tenpai)
            for s in range(4):
                deltas[s] = pay if s in tenpai else -(3000 // (4 - len(tenpai)))
            deltas = {s: v for s, v in deltas.items() if v}
        if reason != "exhaustive":
            # 途中流局：立直供托退回本人（立直的人每人拿回 1000）
            sticks = int(self.db._one("SELECT riichi_sticks FROM rounds WHERE round_id=?",
                                      (self.round_id,)) or 0)
            for r in self.db._rows("SELECT seat FROM round_riichi WHERE round_id=?",
                                   (self.round_id,)):
                deltas[r["seat"]] = deltas.get(r["seat"], 0) + 1000
                sticks = max(sticks - 1, 0)
            with self.db.tx():
                self.db.conn.execute("UPDATE rounds SET riichi_sticks = ? WHERE round_id=?",
                                     (sticks, self.round_id))
            deltas = {s: v for s, v in deltas.items() if v}
        # Card41 S2「局终」：流局也算「本局没有和牌」→ 照付
        _c41pay_d = self._c41s2_pay(-1, deltas)
        self.db.finish_round(self.round_id, _draw_result_name(reason), deltas=deltas)
        self.phase = "ended"
        self.round_phase = "end"
        self.result = {"result": "ryuukyoku", "reason": reason, "tenpai": tenpai,
                       "c41s2": _c41pay_d or None,
                       "deltas": deltas,
                       "stopped": True, "scores": self.scores()}
        names = {"exhaustive": "荒牌流局", "kyuushu": "九种九牌", "sufon_renda": "四风连打",
                 "sucha_riichi": "四家立直", "sukan_santan": "四杠散了", "sanchahou": "三家和了"}
        print("======== 流局 ========")
        print(f"理由: {names.get(reason, reason)}   听牌: {tenpai}")
        print("======== 本局结束，游戏停止 ========")
        self.save_flags()                 # 流局结果也要落库（带上 reason / tenpai）
        return self._event("ryuukyoku", {"reason": reason, "tenpai": tenpai})

    def _event(self, name: str, data: dict) -> dict:
        return {"event": name, **data}
