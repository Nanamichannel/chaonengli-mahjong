# ════════════════════════════════════════════════════════════════════════════
#  天才麻将少女 · 客户端主脚本 main.gd
# ----------------------------------------------------------------------------
#  这个文件只干三件事：
#    ① 画画面：手牌 / 牌河 / 牌墩 / 副露 / 按钮 / 和牌面板
#    ② 把玩家的点击变成一条 JSON 请求发出去（server_bridge.gd → python）
#    ③ 把服务端回来的 state 画到画面上（srv_apply_state 是总入口）
#  ★ 规则（能不能吃、能不能和、几番几符几点）全在服务端 server/ 里，这里不算；
#     本文件只剩「离线兜底」的老函数（use_server_rules=false 才用得上）。
#
#  想改东西时从哪儿进：
#    · 调显示大小 / 位置  → 「布局接口」那几节（都带 @export，编辑器里能直接调）
#    · 调按钮样式        → 「操作按钮」那节（贴图/位置/缩放取自场景 UI 下的模板节点）
#    · 调宝牌指示牌翻转  → 「宝牌指示牌覆盖图」那节
#    · 调规则            → 别改这里，去 server/（server/README.md 有说明）
#
#  分区地图（行号 = 该节第一行）：
#    55    排布参数（参考图：手牌贴紧、摸到的牌与手牌留一个空隙）
#    68    打出的牌（风盘下方的牌河）
#    77    日麻 听牌/和牌 判定 + 立直
#    92    三家（B/C/D）的回合
#    159   布局接口（改完立刻重排，方便自己微调）
#    161   风盘（桌面中央的蓝框）
#    177   我的手牌
#    200   其他三家手牌
#    231   规则全部问服务端（客户端不再自己定规则）
#    369   牌墩 / 牌山（四面，每面 17 墩）
#    440   手牌排序
#    473   牌桌逻辑
#    475   牌墩 / 牌山（四面：左右两列 + 上下两排，每面 17 墩）
#    489   牌山接口：两组，各自都有「大小 + 位置」（都在「牌墩」节点自己的坐标系里，改完立刻重摆）
#    530   配牌阶段（骰子 → 牌山编号 → 发牌）
#    566   数据都在服务端，客户端只渲染
#    812   宝牌指示牌覆盖图（按主视角的四个方向；改这里就能微调）
#    996   对局由服务端驱动：客户端只发动作 + 按服务端状态渲染
#    1048  「过」按钮：服务端开出鸣牌窗口时，不鸣就点它（不然会一直等你）
#    1080  操作按钮（图片样式；位置/大小/贴图都取自场景里 UI 下对应的节点）
#    1538  显示
#    1656  打出的牌（风盘下方牌河）
#    1783  日麻 听牌 / 和牌 判定
#    1916  立直 / 和牌 流程
#    2052  快捷键
#    2078  三家的回合（B/C/D）
#    2282  吃（吃上家 B 打出的牌）
#    2298  副露牌大小接口
#    2303  上下家（B/D）手牌列的间距
#    2310  暗杠素材
#    2572  碰（碰三家打出的牌）
#    2662  其他家的副露（吃）显示
#    2948  暗杠（显示 + 玩法）
# ════════════════════════════════════════════════════════════════════════════

extends Control

const SelFrame := preload("res://sel_frame.gd")   # 统一彩框（图片）
const HandShow := preload("res://hand_show.gd")  # 通用「手牌展示」面板
const WinAnnounce := preload("res://win_announce.gd")  # 胡牌/流局播报
const MatchAnnounce := preload("res://match_announce.gd")  # 半庄终局排行播报
const WinConfirmButton := preload("res://win_confirm_button.gd")
const HandPick := preload("res://hand_pick.gd")   # 统一「选手牌」界面
const SkillPanel := preload("res://skill_panel.gd")  # 统一「技能选牌面板」
const C30Panel := preload("res://c30_panel.gd")      # Card30 S1「向听」专用面板

var hand_pick := HandPick.new()

# ── 排布参数（参考图：手牌贴紧、摸到的牌与手牌留一个空隙） ──
const HAND_LEFT_RATIO := 0.130     # 手牌区左端位置（占屏宽比例）
const HAND_BOTTOM_MARGIN := 17.0   # 牌底距离屏幕底部 
const DRAWN_GAP_RATIO := 0.55      # 摸到的牌与手牌之间的空隙（占牌宽比例）
const HOVER_RAISE := 25.0          # 悬停时抬起的高度
# 副露（吃牌后右下角面子）的显示尺寸
const MELD_TILE_SIZE := Vector2(52.0, 74.0)  # 可自行调整
# 摸到的牌始终摆在最右端，与手牌之间留一个空隙（打出摸到的牌或手牌后，剩下的牌都当手牌重新排序）
const DRAWN_INSERT_SORTED := false

# 赤宝牌：0m/0p/0s 各自替换掉一张普通的 5
const RED_FIVES := {"0m": "5m", "0p": "5p", "0s": "5s"}

# ── 打出的牌（风盘下方的牌河） ──
const FPAI_NODE := "fPai"                  # 打出牌的形象库（Main 的子节点）
const FENGPAN_NODE := "UI/风盘"             # 风盘 Sprite2D
const DISCARDS_PER_ROW := 6                # 每排 6 张
const DISCARD_GAP := 1.02                 # 牌河：牌与牌之间的间距倍数（1.0 = 紧贴）
const DISCARD_SPAN_RATIO := 1.03           # 5 张牌宽 + 1 张牌长 = 风盘宽度 × 此比例（略长于风盘；1.0 = 正好相等）
# 风盘图（1920×1080）里「盘面本体」的有效区域（奶白外框实测 bbox 510~1467 / 106~946，外沿 +12）
const FENGPAN_TEX_SIZE := Vector2(1920, 1080)
const FENGPAN_TEX_RECT := Rect2(498, 96, 981, 862)

# ── 风盘：8 张图（场风 + 自家风）────────────────────────────────────────────
#   节点名 = 场风字 + 自家风字，例：东东 = 东场 + 我(东家)、南北 = 南场 + 我(北家)
#   图里已经画好了「我的自风在右下角、其他三家的字朝向各自玩家」，所以运行时不旋转、只换图。
const FENGPAN_IMG_PRE := ["东", "南"]                  # 场风（西入/北入没有专属图，沿用南）
const FENGPAN_IMG_SUF := ["东", "南", "西", "北"]       # 自家风
const FENGPAN_LEAF_PREFIX := "Huaban"                  # 本场叶子（5 片）
const FENGPAN_TURNS_TO_DEG: Array[int] = [0, -90, 180, 90]

# ── 日麻 听牌/和牌 判定 + 立直 ──
# ★ 立直按钮只有一套：场景里的 UI/Btn/BtnLizhi，由 srv_layout_buttons() 按服务端
#   legal 摆（服务端允不允许是唯一标准）。原来还有一个代码自建的 riichi_button，
#   「只出现一次（RIICHI_OFFER_ONCE）」且用「听不听」判断（不看振听）→ 会和服务端
#   状态打架：闪一下就消失、之后再也回不来。那一套已经删掉。
const HUPAI_TEXT := "胡牌"
const RESULT_AUTO_NEXT_SEC := 2.5       # 结算画面停留多久后自动进下一局
const FROM_MENU_FLAG := "user://from_initial_menu.flag"
const HANCHAN_OWNER := "user://hanchan_owner.json"
const HUPAI_FONT_SIZE := 120
# 34 种牌（听牌判定用；赤宝牌 0m/0s/0p 按普通 5 处理）
const TILE_KINDS: Array[String] = [
	"1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
	"1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p",
	"1s", "2s", "3s", "4s", "5s", "6s", "7s", "8s", "9s",
	"dong", "nan", "xi", "bei", "bai", "fa", "zhong"
]
const ORPHAN_KINDS := [0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33]  # 国士无双的幺九牌

# ── 三家（B/C/D）的回合 ──
const TAPAI_NODE := "UI/Tapai"                      # 三家手牌挂在 Tapai 下
const OPP_ORDER: Array[String] = ["D", "C", "B"]    # 逆时针：我 → 下家(右D) → 对家(上C) → 上家(左B)
const OPP_HAND_COUNT := 13                          # 每家手牌张数
const OPP_DRAW_DELAY := 0.1                         # 他家摸牌后自动打出的延迟（秒）
const OPP_DRAWN_GAP_RATIO := 0.55                   # 他家摸到的牌与手牌的间隔（占一步间距的比例）
# 三家的牌河 = 我的牌河绕风盘中心顺时针旋转；新摸的牌挂哪一端（B/D 从第 1 张那端起）
const OPP_DISCARD_ROTATION := {"B": 90.0, "C": 180.0, "D": 270.0}
const OPP_DRAWN_ANCHOR := {"B": ["01", -1.0], "C": ["13", 1.0], "D": ["01", -1.0]}

# 牌 ID —— 与 Main/Pai 下的模板节点名一一对应：
#   1m~9m 万 / 1s~9s 索 / 1p~9p 筒 / dong 东 / nan 南 / xi 西 / bei 北 / bai 白 / fa 发 / zhong 中
#   0m 0s 0p 为赤宝牌（默认不进牌山，需要时把它们加进 TILE_IDS 即可）
const TILE_IDS: Array[String] = [
	"1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
	"1s", "2s", "3s", "4s", "5s", "6s", "7s", "8s", "9s",
	"1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p",
	"dong", "nan", "xi", "bei", "bai", "fa", "zhong"
]

# 手牌从左到右的排列顺序（0 赤宝牌排在 4 和 5 之间；万 → 筒 → 索 → 字牌）
const SORT_ORDER: Array[String] = [
	"1m", "2m", "3m", "4m", "0m", "5m", "6m", "7m", "8m", "9m",
	"1p", "2p", "3p", "4p", "0p", "5p", "6p", "7p", "8p", "9p",
	"1s", "2s", "3s", "4s", "0s", "5s", "6s", "7s", "8s", "9s",
	"dong", "nan", "xi", "bei", "bai", "fa", "zhong"
]

var hand_tiles: Array[String] = []     # 手里的牌（已排序，不含刚摸到的那张）
var drawn_tile := ""                   # 刚摸到、还没打出的那张牌（"" = 没有）
var wall_tiles: Array[String] = []
var tile_wrappers: Array[Button] = []
var hovered_index := -1
var sort_rank := {}                    # 牌 ID -> 排序权重

var pai: Node2D                # 牌模板库：Pai 下每个子节点就是一种牌
var hand_container: Control
var sizee := 0.8
var tile_size := Vector2(68.00, 97.00)   # 由模板牌自动量出 
var tile_bank: TileBank = null       # 136 张牌实体库（TilePiece 节点都挂在它下面）
var drawn_gap := 0.0                   # 摸到的牌与手牌之间的空隙
var fpai: Node2D                       # 打出牌的形象库
var fengpan: Node2D                     # 风盘（本体是 Node2D，图在子 Sprite2D 上）
var discard_container: Node2D          # 牌河容器（挂在风盘同级）
var discard_pile: Array[String] = []   # 已打出的牌，按顺序
var discard_rotated: Array[bool] = []  # 与牌河一一对应：true = 横置（立直宣言牌）
var kind_index := {}                   # 牌 ID -> 0..33（听牌判定用）

var riichi_declared := false           # 已立直
var riichi_selecting := false          # 点了立直、正在选宣言牌
var yiding_selecting := false          # 点了「一定和牌」、正在选宣言牌
var guobiao_selecting := false         # 点了「国标」、正在选宣言牌
var gb_picks: Array[int] = []          # 国标选中的手牌（display_tiles 下标）
var gb_ui: Control = null
var gb_btn: TextureButton = null
var yd_picks: Array[int] = []          # 一定和牌选中的手牌
var yd_ui: Control = null
var yd_btn: TextureButton = null
var game_over := false                 # 已和牌：停止一切行为
var auto_next_scheduled := false       # 结算后已经排了「自动下一局」
var hupai_label: Label                 # "胡牌"（旧节点，保留兼容）
var win_announce: Control = null        # 新胡牌/流局播报
var match_announce: Control = null      # 半庄终局：四家名次播报
var match_active := false               # 终局播报正在显示
var _match_waiting := false             # 我已经点过确认，等别人
var _match_returned := false            # 已经回大厅（防重复）
var _match_acc := 0.0
var win_confirm_btn: Control = null      # 四家结算确认
var result_confirmed := false
var result_confirm_sig := ""

var tapai: Node2D                      # 三家手牌（UI/Tapai）
var opp_hands := {}                    # "B"/"C"/"D" -> Array[String]，各家 13 张（不可见）
var opp_drawn := {}                    # 同上 -> 刚摸到的那张牌（"" = 没有）
var opp_discards := {}                 # 同上 -> 各家已打出的牌（暂不显示）
var opp_drawn_nodes := {}              # 同上 -> 各家「摸到的那张」的形象节点
var opp_step := {}                     # 同上 -> 各家排列方向与间距（Vector2）
var opp_discard_containers := {}       # 同上 -> 各家牌河的容器（带旋转）
var turn_index := 0                    # 0 = 我；1/2/3 = OPP_ORDER 里的第几家
var opp_pending := false               # 某家已摸牌、正在等自动打出


# ────────────────────────── 布局接口（改完立刻重排，方便自己微调）──────────────────────────

# ── 风盘（桌面中央的蓝框）──
# ① 风盘大小：相对场景里那个大小（牌河会跟着一起缩放、重排）
@export var fengpan_scale_ratio := 0.85:
	set(v):
		fengpan_scale_ratio = maxf(v, 0.01)
		_apply_fengpan()
# ② 风盘位置：在场景里那个位置的基础上再挪多少
@export var fengpan_offset := Vector2.ZERO:
	set(v):
		fengpan_offset = v
		_apply_fengpan()
# ③ 风盘朝向：图上的「東」永远指向庄家那一面（庄家换人时整张图转 90° 的整数倍）
@export var fengpan_center_on_ring := true   # 盘面中心对齐「牌河环中心」（图里盘面不在画布正中，不对齐会整体偏右）
@export var fengpan_face_dealer := true:
	set(v):
		fengpan_face_dealer = v
		_apply_fengpan()

var fengpan_base_scale := Vector2.ONE
var fengpan_base_pos := Vector2.ZERO
var fengpan_ready := false

# ── 我的手牌 ──
# ① 手牌大小（副露、吃法预览会一起缩放）
@export var hand_scale_ratio := 0.8:
	set(v):
		hand_scale_ratio = maxf(v, 0.05)
		_measure_tile_size()
		_layout_hand_area()
		refresh_hand()
		redraw_melds()
# ② 手牌区左端位置（占屏宽比例，就是原来的 HAND_LEFT_RATIO）
@export var hand_left_ratio := 0.130:
	set(v):
		hand_left_ratio = v
		_layout_hand_area()
# ③ 手牌整体额外位移（x 正 = 往右，y 正 = 往下；副露会跟着一起挪）
@export var hand_offset := Vector2.ZERO:
	set(v):
		hand_offset = v
		_layout_hand_area()
		redraw_melds()

var base_tile_size := Vector2(68.00, 97.00)   # 模板牌量出来的原始尺寸；tile_size = 它 × hand_scale_ratio

# ── 其他三家手牌 ──
# ① 三家手牌各自的大小（相对场景里那个大小；上下家的列间距会跟着一起缩放）
@export var opp_hand_scale_b := 0.75:      # 上家 B
	set(v):
		opp_hand_scale_b = maxf(v, 0.05)
		_layout_opp_hands()
@export var opp_hand_scale_c := 0.65:      # 对家 C
	set(v):
		opp_hand_scale_c = maxf(v, 0.05)
		_layout_opp_hands()
@export var opp_hand_scale_d := 0.75:      # 下家 D
	set(v):
		opp_hand_scale_d = maxf(v, 0.05)
		_layout_opp_hands()
# ② 三家手牌各自的额外位移（B = 上家 / C = 对家 / D = 下家）
@export var opp_offset_b := Vector2.ZERO:
	set(v):
		opp_offset_b = v
		_layout_opp_hands()
@export var opp_offset_c := Vector2(-60.0, 0.0):
	set(v):
		opp_offset_c = v
		_layout_opp_hands()
@export var opp_offset_d := Vector2.ZERO:
	set(v):
		opp_offset_d = v
		_layout_opp_hands()

var opp_hand_base := {}      # 三家手牌在场景里的基准（中心 + 每张的位置/缩放），接口都相对它算


# ────────────────────────── 规则全部问服务端（客户端不再自己定规则）──────────────────────────

# 规则只在服务端 server/rules/*.py 有一份。这里只负责：把「我的手牌 + 副露」拼成请求，
# 发上去，拿服务端的判定回来用。连不上服务端才会退回下面的本地兜底函数。
const SRV_FROM_SEAT := {"B": 3, "C": 2, "D": 1}      # 上家/对家/下家 → 服务端座位号

@export var use_server_rules := true                 # 关掉 = 纯离线兜底（调试用）

# 牌「飞」的速度（打牌飞进牌河 / 摸牌飞进手牌 / 鸣牌飞过去）。只影响牌位动画，
# 不影响和牌播报的长条、也不影响立直棒淡入等其它动画。
#   1.0 = 原速；2.0 = 快一倍；0.5 = 慢一半；0 = 关掉（牌直接瞬移到位）
@export_category("牌飞行（打牌 / 摸牌 / 鸣牌的牌位动画）")
@export_range(0.0, 4.0, 0.05) var tile_fly_speed := 1.0

@export_category("和牌播报")
# 播报期间的帧率上限：0 = 自动跟随显示器刷新率（固定数字容易和 240Hz/200Hz 屏错拍，动画看着一顿一顿）
@export var announce_max_fps := 0
var srv                                          # ServerBridge
var srv_up := false                              # 上一次请求服务端是否正常回答
var srv_note := ""                              # 上一次失败原因

# ── 本窗口是几号位（多窗口测试：每个窗口认领一个座位）──
#   没被任何窗口认领的座位，仍然由服务端代打（AI）。
#   按 1/2/3/4 切换本窗口的座位；按 F2 开新的一局。
var my_seat := 0                                # 0..3
var waiting_for_others := false                 # 现在是不是在等别人出牌（等的时候要轮询）
var poll_accum := 0.0
var _poll_fast_until := 0                     # 刚发过动作：这之前用快速轮询
# ★ 上云后调慢：没推送（反代没转发 WebSocket / 掉线）时全靠这个间隔拉状态。
#   0.35 → 0.5 秒，服务端出网流量省 ~30%，人手感觉不出差别；
#   有长连接推送时这值根本不生效（下面会被抬到 2 秒）。
const POLL_SEC := 0.5                           # 等别人时的轮询间隔（秒）
												# 配合 https 长连接复用（每次请求 2~3ms），
												# 从 0.6 压到 0.35：别人出牌后肉眼几乎同步
const POLL_IDLE_SEC := 1.0                      # 轮到我 / 结算后也慢一点问一次（别人可能开了新局）
const SEAT_LABEL_POS := Vector2(18.0, 8.0)      # 「本窗口 = 几号位」显示位置
var seat_label: Label


# 从我的座位看出去：下家 = 我+1、对家 = 我+2、上家 = 我+3（逆时针）
func who_of_seat(seat: int) -> String:
	if seat == my_seat:
		return "me"
	match (seat - my_seat + 4) % 4:
		1:
			return "D"
		2:
			return "C"
		3:
			return "B"
	return ""


func seat_of_who(who: String) -> int:
	match who:
		"me":
			return my_seat
		"D":
			return (my_seat + 1) % 4
		"C":
			return (my_seat + 2) % 4
		"B":
			return (my_seat + 3) % 4
	return my_seat

# 最近一次点的技能图标按钮的屏幕矩形（枷锁的数字按钮贴在它上方）
var _skill_btn_rect := Rect2()


func _remember_skill_btn(card_no: int, index: int) -> void:
	var idn := get_node_or_null("Identity")
	if idn == null:
		return
	var cn := idn.get_node_or_null("Card%02d" % int(card_no))
	if cn == null:
		return
	var sb := cn.get_node_or_null("Skill%d" % (int(index) + 1)) as Control
	if sb != null and is_instance_valid(sb):
		_skill_btn_rect = sb.get_global_rect()


# 点了「复制品 / 传承品」的图标之后，下一次真正发动的请求要带 copy=true，
# 服务端据此把这一下记到「复制品」那本账上（原技能与复制品各有一份配额）。
# 值 = "card-skill"；空 = 普通（原技能）发动。
var copy_hint := ""
var _state_ver := ""      # 上一次 state 的版本号（服务端给的）


# ── 调试 HUD（F3）：卡的时候让对方截图，一眼看出卡在哪一环 ──
#   FPS / 帧时间（>16ms 就是在掉帧） / 最近一次请求耗时（大 = 网络等太久）
#   推送频率（正常 1~3/s，飙高说明状态在被反复重建） / 状态应用频率
var _hud: Label = null
var _hud_show := false
var _hud_acc := 0.0

# ── 右上角「东几局 几本场」白色小字（用户口径 2026-11-01）──────────────
var _round_hud: Label = null
var _round_info_on := true               # 右上角四行信息开着没有
var _round_info_btn: BaseButton = null   # 右上角小开关（Main/UI/按钮）
var _round_info_icon: Sprite2D = null   # 按钮图标是个 Sprite2D（不是 Button）
var _round_info_probe := 0.0            # 右上角开关探测计时
@export var round_hud_margin := Vector2(28.0, 62.0)   # 距离屏幕右 / 上边（上边让出按钮的位置）
const ROUND_HUD_W := 420.0

# ── 询问 / 出牌计时器（用户口径 2026-11-01）─────────────────────────────
#   三个**独立**计时器，各 20 秒、各自重置、各自显示（纯黄，不变色）：
#     discard = 该我打牌        → 到点强制摸切
#     claim   = 该我吃碰杠荣    → 到点自动「过」
#     ask     = 技能询问        → 到点按当前亮着的「跳过 / 开始」按钮（没选牌 = 跳过）
#   ★ 用「指纹」重置，不是「每来一份 state 就重置」——
#     0.35s 轮询 + 推送会不停送 state，那样永远到不了 20 秒。
const TM_SEC := 35.0
var _tm_mode := ""
var _tm_fp := ""
var _tm_left := 0.0
var _tm_sent := false
var _tm_fire_ms := 0
var _tm_retry := 0
var _tm_label: Label = null
var last_req_ms := 0
var _push_n := 0
var _apply_n := 0


# ── 性能探针（开发用，不影响对局）──────────────────────────────────
# 每个项目都测两次：**清掉缓存**（= 优化前的行为）与**走缓存**（= 现在）。
# 用法：控制台 / MCP 调 perf_bench_ms()（默认每种 30 轮，单位毫秒）。
func perf_bench_ms(rounds: int = 30) -> Dictionary:
	var out := {}
	var r := maxi(1, rounds)
	var t0 := Time.get_ticks_usec()
	for i in range(r):
		_hand_view_sig = ""
		refresh_hand()
	out["1_手牌重画_优化前"] = float(Time.get_ticks_usec() - t0) / 1000.0 / float(r)
	t0 = Time.get_ticks_usec()
	for i in range(r):
		refresh_hand()
	out["1_手牌重画_现在"] = float(Time.get_ticks_usec() - t0) / 1000.0 / float(r)

	t0 = Time.get_ticks_usec()
	for i in range(r):
		_entity_sig = ""
		_apply_entity_states(srv_state)
	out["2_136张实体_优化前"] = float(Time.get_ticks_usec() - t0) / 1000.0 / float(r)
	t0 = Time.get_ticks_usec()
	for i in range(r):
		_apply_entity_states(srv_state)
	out["2_136张实体_现在"] = float(Time.get_ticks_usec() - t0) / 1000.0 / float(r)

	t0 = Time.get_ticks_usec()
	for i in range(r):
		_pbr_frame = -1
		_pbr_memo.clear()
		_sync_prompt_btns()
	out["3_开始按钮摆位_优化前"] = float(Time.get_ticks_usec() - t0) / 1000.0 / float(r)
	t0 = Time.get_ticks_usec()
	for i in range(r):
		_pbr_frame = -1
		_sync_prompt_btns()
	out["3_开始按钮摆位_现在"] = float(Time.get_ticks_usec() - t0) / 1000.0 / float(r)

	t0 = Time.get_ticks_usec()
	for i in range(r):
		_btn_ok.clear()
		_refresh_start_btn_kinds()
	out["4_确认跳过切图_优化前"] = float(Time.get_ticks_usec() - t0) / 1000.0 / float(r)
	t0 = Time.get_ticks_usec()
	for i in range(r):
		_refresh_start_btn_kinds()
	out["4_确认跳过切图_现在"] = float(Time.get_ticks_usec() - t0) / 1000.0 / float(r)

	t0 = Time.get_ticks_usec()
	for i in range(r * 10):
		_hand_slots_n = -1
		_hand_slots()
	out["5_手牌格子查表_优化前"] = float(Time.get_ticks_usec() - t0) / 1000.0 / float(r * 10)
	t0 = Time.get_ticks_usec()
	for i in range(r * 10):
		_hand_slots()
	out["5_手牌格子查表_现在"] = float(Time.get_ticks_usec() - t0) / 1000.0 / float(r * 10)

	# 6) 整份 state 应用（这个才是用户真正能感觉到的「一顿」）
	#    我的回合会有自动摸牌等推进副作用 → 只有不是我的回合时才测
	if not srv_state.is_empty() and int(srv_state.get("turn", -1)) != my_seat:
		t0 = Time.get_ticks_usec()
		for i in range(maxi(1, r / 3)):
			_last_state_hash = 0
			srv_apply_state(srv_state, [])
		out["6_整份state_优化前"] = float(Time.get_ticks_usec() - t0) / 1000.0 / float(maxi(1, r / 3))
		t0 = Time.get_ticks_usec()
		for i in range(r * 3):
			srv_apply_state(srv_state, [])
		out["6_整份state_现在"] = float(Time.get_ticks_usec() - t0) / 1000.0 / float(r * 3)

	for k in out.keys():
		out[k] = snappedf(out[k], 0.001)
	return out


# 每帧固定开销（_process 里那串 tick）：量「一帧不干正事也要花多少毫秒」
func perf_bench_process_ms(rounds: int = 200) -> float:
	var r := maxi(1, rounds)
	var t0 := Time.get_ticks_usec()
	for i in range(r):
		_skill_panel_stale_close()
		_sync_c05_dead_buttons()
		_refresh_start_btn_kinds()
		_sync_prompt_btns()
		swap_panel.tick()
		ym_panel.tick()
		press_panel.tick()
		c25b_panel.tick()
		c27_panel.tick()
		c30_panel.tick()
		c32_panel.tick()
		c33_panel.tick()
		c43_panel.tick()
		c45_panel.tick()
		c46_panel.tick()
		c24_panel.tick()
		_sync_chow_choices()
	return float(Time.get_ticks_usec() - t0) / 1000.0 / float(r)


func _round_hud_sync(st: Dictionary) -> void:
	_round_hud_ensure()
	_round_hud.visible = _round_info_on
	var w := _wind_cn(String(st.get("round_wind", st.get("wind", "dong"))))
	var n := int(st.get("number", 1))
	var h := int(st.get("honba", 0))
	var up := srv_nick_of((my_seat + 3) % 4)
	var opp := srv_nick_of((my_seat + 2) % 4)
	var low := srv_nick_of((my_seat + 1) % 4)
	var txt := "上家：%s\n对家：%s\n下家：%s\n%s%s局　%d 本场" % [
		up, opp, low, w, _num_cn(n), h]
	if _round_hud.text != txt:
		_round_hud.text = txt


func _round_hud_ensure() -> void:
	if _round_hud != null and is_instance_valid(_round_hud):
		return
	_round_hud = Label.new()
	_round_hud.name = "RoundHud"
	_round_hud.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_round_hud.z_index = 400                 # 压在所有面板（250~320）上面
	_round_hud.add_theme_font_size_override("font_size", 22)
	_round_hud.add_theme_color_override("font_color", Color(1, 1, 1, 0.92))
	_round_hud.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.75))
	_round_hud.add_theme_constant_override("outline_size", 4)
	_round_hud.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	_round_hud.size = Vector2(ROUND_HUD_W, 30.0 * 4.0)   # 四行
	_round_hud.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_round_hud)


# 右上角「四行信息」的开关按钮：节点由用户在场景里放好（Main/UI/按钮）
func _round_info_button_get() -> BaseButton:
	if _round_info_btn != null and is_instance_valid(_round_info_btn):
		return _round_info_btn
	# ① 先按名字找（用户口径：Main/UI/按钮）
	for p in ["UI/按钮", "UI/按钮2", "按钮"]:
		var nd := get_node_or_null(p)
		if nd is BaseButton:
			_bind_info_btn(nd as BaseButton)
			return _round_info_btn
	# ② 名字改了也认：UI 下第一个 Button / TextureButton 就是它
	var ui := get_node_or_null("UI")
	if ui != null:
		for ch in ui.get_children():
			if ch is BaseButton:
				_bind_info_btn(ch as BaseButton)
				break
	return _round_info_btn


func _bind_info_btn(b: BaseButton) -> void:
	_round_info_btn = b
	_round_info_btn.mouse_filter = Control.MOUSE_FILTER_STOP
	if not _round_info_btn.pressed.is_connected(_round_info_toggle):
		_round_info_btn.pressed.connect(_round_info_toggle)


# 按钮图标（用户在 Main/UI/按钮 放的是一个 Sprite2D，不是 Button）
func _round_info_icon_get() -> Sprite2D:
	if _round_info_icon != null and is_instance_valid(_round_info_icon):
		return _round_info_icon
	var nd := get_node_or_null("UI/按钮")
	if nd is Sprite2D:
		_round_info_icon = nd as Sprite2D
	return _round_info_icon


func _round_info_icon_rect() -> Rect2:
	var sp := _round_info_icon_get()
	if sp == null or sp.texture == null:
		return Rect2()
	var sz := sp.texture.get_size() * Vector2(absf(sp.global_scale.x), absf(sp.global_scale.y))
	return Rect2(sp.global_position - sz * 0.5, sz)


# 图标整块在屏幕外（用户摆的 y = -33，看不见也点不到）→ 拉回右上角
func _round_info_icon_place() -> void:
	var sp := _round_info_icon_get()
	if sp == null or sp.texture == null:
		return
	if bool(sp.get_meta("placed", false)):
		return
	sp.set_meta("placed", true)
	var vp := get_viewport_rect().size
	var r := _round_info_icon_rect()
	if r.size == Vector2.ZERO:
		return
	if r.position.y < 2.0 or r.end.y > vp.y - 2.0 or r.position.x < 2.0 or r.end.x > vp.x - 2.0:
		# 用全局坐标摆（Main/UI 自己有偏移，改 position 会摆歪）
		sp.global_position = Vector2(vp.x - r.size.x * 0.5 - 16.0, 10.0 + r.size.y * 0.5)


# 点在图标上？（Sprite2D 没有信号，只能自己算矩形）
func _round_info_hit(pos: Vector2) -> bool:
	if _round_info_btn != null and is_instance_valid(_round_info_btn):
		return false                 # 有真按钮的话走它自己的 pressed
	var r := _round_info_icon_rect()
	return r.size != Vector2.ZERO and r.has_point(pos)


func _round_info_toggle() -> void:
	_round_info_on = not _round_info_on
	if _round_hud != null and is_instance_valid(_round_hud):
		_round_hud.visible = _round_info_on


func _round_hud_tick() -> void:
	_round_info_probe += get_process_delta_time()
	if _round_info_probe >= 1.0:            # 每帧查字符串太浪费，1 秒探一次就够
		_round_info_probe = 0.0
		if _round_info_btn == null:
			_round_info_button_get()
		_round_info_icon_place()
	if _round_hud != null and is_instance_valid(_round_hud):
		_round_hud.visible = _round_info_on
	if _round_hud == null or not is_instance_valid(_round_hud):
		return
	var vp := get_viewport_rect().size
	var want := Vector2(vp.x - ROUND_HUD_W - round_hud_margin.x, round_hud_margin.y)
	if _round_hud.global_position.distance_to(want) > 0.5:
		_round_hud.global_position = want   # 全局坐标：Main 自己有偏移，用 position 会顶出屏幕右边


func _hud_tick(delta: float) -> void:
	_hud_acc += delta
	if _hud == null and _hud_show:
		_hud = Label.new()
		_hud.name = "PerfHud"
		_hud.position = Vector2(20, 56)
		_hud.mouse_filter = Control.MOUSE_FILTER_IGNORE
		_hud.z_index = 400                 # 压在牌山/风盘/面板（250~320）上面，不能再被遮挡
		_hud.add_theme_font_size_override("font_size", 20)
		_hud.add_theme_color_override("font_color", Color(0.55, 1.0, 0.65))
		_hud.add_theme_color_override("font_outline_color", Color(0, 0, 0))
		_hud.add_theme_constant_override("outline_size", 5)
		add_child(_hud)
	if _hud != null:
		_hud.visible = _hud_show
	if not _hud_show:
		_push_n = 0
		_apply_n = 0
		return
	if _hud_acc < 0.5:
		return
	var fps := Engine.get_frames_per_second()
	var win := get_viewport().get_visible_rect().size
	_hud.text = "FPS %d | 帧 %.1fms | 最近请求 %dms | 推送 %.1f/s | 应用状态 %.1f/s | 视口 %dx%d" % [
		fps, 1000.0 / maxf(float(fps), 1.0), last_req_ms,
		float(_push_n) / _hud_acc, float(_apply_n) / _hud_acc, int(win.x), int(win.y)]
	# ▼ 调试行（F1 第二行）：牌山 / 按钮 / legal —— 排查「牌山没了 / 副露按钮没了」
	var _vis_st := 0
	for _s in wall_stacks:
		var _nd = _s.get("vis", null)
		if _nd != null and is_instance_valid(_nd) and (_nd as CanvasItem).visible:
			_vis_st += 1
	var _btn_on: Array = []
	for _k in btn_nodes:
		var _b = btn_nodes[_k]
		if _b != null and is_instance_valid(_b) and (_b as CanvasItem).visible:
			_btn_on.append(String(_k))
	var _ops := srv_opts_of(srv_state)
	var _side_n := {}
	for _s2 in wall_stacks:
		var _sd := String(_s2.get("side", "?"))
		var _nd2 = _s2.get("vis", null)
		if _nd2 != null and is_instance_valid(_nd2) and (_nd2 as CanvasItem).visible:
			_side_n[_sd] = int(_side_n.get(_sd, 0)) + 1
	var _bdetail: Array = []
	for _k2 in _btn_on:
		var _bb = btn_nodes.get(_k2, null)
		if _bb == null or not is_instance_valid(_bb):
			continue
		var _tb := _bb as TextureButton
		var _tex_ok := _tb != null and _tb.texture_normal != null
		_bdetail.append("%s@(%.0f,%.0f) sz(%.0f,%.0f) sc(%.2f) a=%.2f tex=%s intree=%s" % [
			String(_k2), (_bb as CanvasItem).global_position.x, (_bb as CanvasItem).global_position.y,
			(_bb as Control).size.x, (_bb as Control).size.y, (_bb as CanvasItem).scale.x,
			float((_bb as CanvasItem).modulate.a), "1" if _tex_ok else "0",
			"1" if (_bb as CanvasItem).is_visible_in_tree() else "0"])
	var _pv := "?"
	var _bv := "?"
	var _pn := get_node_or_null("UI/Pile")
	var _bn := get_node_or_null("UI/Btn")
	if _pn != null:
		_pv = "1" if (_pn as CanvasItem).visible else "0"
	if _bn != null:
		_bv = "1" if (_bn as CanvasItem).visible else "0"
	_hud.text += "\n墙=%s Pile.vis=%s Btn.vis=%s ｜ %s" % [str(_side_n), _pv, _bv, str(_bdetail)]
	_hud.text += "\n牌山 %d/%d 墩(可见/总)  wall_taken=%d | 按钮 %d/%d 显示%s | legal=%s | phase=%s turn=%s my=%d | my_seat=%d" % [
		_vis_st, wall_stacks.size(), srv_taken.size(),
		_btn_on.size(), btn_nodes.size(), str(_btn_on), str(_ops),
		String(srv_state.get("phase", "")), int(srv_state.get("turn", -1)), my_seat, my_seat]
	_push_n = 0
	_apply_n = 0
	_hud_acc = 0.0


func srv_request(req: Dictionary) -> Dictionary:
	if not use_server_rules:
		return {}
	if srv == null:
		srv = ServerBridge.new()
		if not srv.available:
			push_warning("main.gd: 找不到 python，规则退回本地兜底")
			srv_note = "找不到 python"
			return {}
	# 真动作（不是轮询）→ 开 1.5 秒快轮询，别让结算等下一次慢轮询
	var _op := String(req.get("op", ""))
	if _op != "" and _op != "state" and _op != "poll":
		_poll_fast_until = Time.get_ticks_msec() + 1500
	var _t0 := Time.get_ticks_msec()
	var r: Dictionary = srv.request(_srv_shape(req))
	last_req_ms = Time.get_ticks_msec() - _t0
	return _srv_handle(r)


# 请求整形：只有「带座位、会落到某个技能上」的请求才带 copy 标记（状态轮询不带）；
# state 一律换成「版本号轮询」——服务端没变化只回 {"same": true}（几十字节）。
func _srv_shape(req: Dictionary) -> Dictionary:
	if String(req.get("op", "")) == "state" and _state_ver != "":
		req = req.duplicate()
		req["op"] = "poll"
		req["ver"] = _state_ver
	if copy_hint != "" and not req.has("copy"):
		req = req.duplicate()
		req["copy"] = true
		if String(req.get("op", "")) != "state":
			copy_hint = ""
	return req


# 服务端回的这份怎么记账（同步 / 非阻塞两条路共用）
func _srv_handle(r: Dictionary) -> Dictionary:
	if r.is_empty():
		return r
	if String(r.get("ver", "")) != "":
		_state_ver = String(r.get("ver"))
	if bool(r.get("same", false)):
		# 服务端说没变化 → 直接用本地那份（行为完全不变，但省掉 21KB + 解析）
		srv_up = true
		srv_note = ""
		var out_same := {"ok": true, "state": srv_state, "events": [], "result": null,
			"same": true}
		# ★ humans 必须带回去：「谁在线」不在 state 里，只在响应顶层。
		#   以前这个分支把它丢了 → 客户端 srv_humans 永远是空 → 「配牌推进者」
		#   判断退化成「只认 0 号位」→ 1 个人坐 1 号位时没人发牌，界面卡死。
		if typeof(r.get("humans")) == TYPE_ARRAY:
			out_same["humans"] = r.get("humans")
		# ★ 半庄结束的信息也必须带回去：状态没变化时（同一个 ver）这个分支直接返回，
		#   以前把 match_finished 吞掉了 → 终局分数播报永远不弹，只看到最后那一局的流局。
		if bool(r.get("match_finished", false)):
			out_same["match_finished"] = true
			out_same["final_rank"] = r.get("final_rank", [])
			out_same["confirmed"] = r.get("confirmed", [])
		return out_same
	srv_up = bool(r.get("ok", false))
	srv_note = "" if srv_up else String(r.get("error", ""))
	if not srv_up:
		push_warning("main.gd: 服务端判定失败 → " + srv_note)
		# ★ 拒绝时服务端通常会带回最新 state（例如「有人正在等回答」）。
		#   不刷新的话客户端会一直停在旧画面（技能面板关了却还在等 → 看起来卡死）。
		var st_fail = r.get("state")
		if typeof(st_fail) == TYPE_DICTIONARY and not (st_fail as Dictionary).is_empty():
			srv_apply_state(st_fail, r.get("events"))
		return {}
	return r


# 我的手牌 + 副露，写成服务端认识的形状（手牌给 13 张，不含刚摸的那张）
# 服务端拒绝的真实原因只在 srv_note 里（srv_request 把失败吞成 {}）
# 看破闸门拦下了这次发动（服务端回 need_kangpo=True）：
# 提示「等对方决定」、别当成成功、别继续往下走。所有技能确认都要先问一句它。
func srv_kangpo_blocked(r: Dictionary) -> bool:
	if not bool(r.get("need_kangpo", false)):
		return false
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("已确认，等对方决定是否拦截…")
	return true


func _srv_err(fallback: String) -> String:
	var n := srv_note.strip_edges()
	return n if n != "" else fallback

func srv_hand_payload() -> Dictionary:
	var melds := []
	for m in meld_list:
		melds.append({
			"kind": String(m.get("kind", "pon")),
			"tiles": (m["tiles"] as Array).duplicate(),
			"from_seat": seat_of_who(String(m.get("from", ""))),
			"rot_index": int(m.get("rot_index", 0)),
		})
	return {
		"seat": 0,
		"hand": hand_tiles.duplicate(),
		"melds": melds,
		# 局面信息（客户端目前是单人，亲家/东一局/自己立直）+ 已经翻出来的宝牌
		"base": {
			"is_dealer": true, "seat_wind": "dong", "round_wind": "dong",
			"riichi": riichi_declared,
			"dora_indicators": dora_indicators.duplicate(),
			"ura_indicators": ura_indicators.duplicate() if riichi_declared else [],
		},
	}


# 这一张和下来多少番符点（服务端算的）
func srv_judge_win(tile: String, tsumo: bool) -> Dictionary:
	var req := srv_hand_payload()
	req["op"] = "judge"
	req["tile"] = tile
	req["tsumo"] = tsumo
	var r := srv_request(req)
	if r.is_empty():
		return {}
	var j = r.get("judge")
	return j if typeof(j) == TYPE_DICTIONARY else {}


# 听牌 / 有役无役 / 振听（服务端算的）
func srv_tenpai() -> Dictionary:
	var req := srv_hand_payload()
	req["op"] = "tenpai"
	var r := srv_request(req)
	if r.is_empty():
		return {}
	var t = r.get("tenpai")
	return t if typeof(t) == TYPE_DICTIONARY else {}


# ────────────────────────── 背景（用户可更换）──────────────────────────
# 把任意图片放进 res://Cailiao/background/ 即可换背景；默认取按文件名排序的第一张。
# 不同分辨率按「覆盖整屏」等比缩放（多余部分裁掉），窗口大小变化会自动重算。
const BG_DIR := "res://Cailiao/background/"
const BG_EXTS := ["png", "jpg", "jpeg", "webp", "bmp", "tga", "avif"]
# 风盘同款蓝色背景：有就用它（想换回别的，把这个文件改名/删掉即可）
const BG_PREFER := "board_teal.png"
var beijing: Sprite2D = null
var _bg_tex: Texture2D = null


func _setup_background() -> void:
	beijing = get_node_or_null("UI/beijing") as Sprite2D
	if beijing == null:
		push_warning("main.gd: 找不到 UI/beijing 背景节点")
		return
	get_viewport().size_changed.connect(_fit_background)
	_load_background()


func _bg_files() -> Array:
	var out: Array = []
	var dir := DirAccess.open(BG_DIR)
	if dir == null:
		return out
	dir.list_dir_begin()
	var f := dir.get_next()
	while f != "":
		if not dir.current_is_dir() and not f.begins_with("."):
			var ext := f.get_extension().to_lower()
			if ext in BG_EXTS:
				out.append(f)
		f = dir.get_next()
	dir.list_dir_end()
	out.sort()
	return out


# 外部背景（不用重导 exe）：
#   ① <exe 同目录>\skin\bg.png      ← 和别的皮肤放一起，最省事
#   ② user://skin/bg.png            ← 编辑器调试
#   ③ <exe 同目录>\background\ 里按名字排序的第一张
#   ④ user://background\ 同上
func _bg_external_files() -> Array:
	var out: Array = []
	var skin_dirs := [OS.get_executable_path().get_base_dir().path_join("skin"),
		ProjectSettings.globalize_path("user://skin")]
	for d in skin_dirs:
		var p := String(d).path_join("bg.png")
		if FileAccess.file_exists(p):
			out.append(p)
			return out
	var bg_dirs := [OS.get_executable_path().get_base_dir().path_join("background"),
		ProjectSettings.globalize_path("user://background")]
	for d in bg_dirs:
		var dn := DirAccess.open(String(d))
		if dn == null:
			continue
		var names: Array = []
		dn.list_dir_begin()
		var f := dn.get_next()
		while f != "":
			if not dn.current_is_dir() and not f.begins_with("."):
				if String(f).get_extension().to_lower() in BG_EXTS:
					names.append(String(f))
			f = dn.get_next()
		dn.list_dir_end()
		if names.is_empty():
			continue
		names.sort()
		for n in names:
			out.append(String(d).path_join(String(n)))
		return out
	return out


func _load_background() -> void:
	if beijing == null:
		return
	# ① 先试外部图（exe 同目录 skin\bg.png / background\ …）——有就用，不用重导
	var ext := _bg_external_files()
	if not ext.is_empty():
		var ep := String(ext[0])
		var eimg := Image.load_from_file(ep)
		if eimg != null and not eimg.is_empty():
			_bg_tex = ImageTexture.create_from_image(eimg)
			beijing.texture = _bg_tex
			_fit_background()
			print("main.gd: 背景 = %s（外部）" % ep)
			return
		push_warning("main.gd: 外部背景读不了，改用包里的：" + ep)
	# ② 包里的 board_teal.png：**直接 load**
	#    ★ 导出成 exe 后 DirAccess 枚举 res:// 目录会拿不到（pck 里的文件列表为空），
	#      以前就是这里失败 → 保留场景默认那张动漫背景（联机玩家看到的「桌布不对」）。
	#      资源系统 load() 在导出版一定可用，所以优先走它。
	var prefer_path := BG_DIR + BG_PREFER
	if ResourceLoader.exists(prefer_path):
		var pt := load(prefer_path) as Texture2D
		if pt != null:
			_bg_tex = pt
			beijing.texture = _bg_tex
			_fit_background()
			print("main.gd: 背景 = %s（OK）" % BG_PREFER)
			return
	# ③ 兜底：目录扫描（编辑器里能用，导出版可能为空）
	var files := _bg_files()
	if files.has(BG_PREFER):
		files.erase(BG_PREFER)
		files.push_front(BG_PREFER)
	if files.is_empty():
		_fit_background()          # 文件夹为空 → 保留场景里原来的背景，但仍按屏幕缩放
		return
	var path: String = BG_DIR + String(files[0])
	var img: Image = Image.load_from_file(path)   # 直接读文件：不依赖 Godot 先导入
	if img != null and not img.is_empty():
		_bg_tex = ImageTexture.create_from_image(img)
	else:
		var t = load(path)         # 回退：走资源系统（需要已导入）
		if t is Texture2D:
			_bg_tex = t
	if _bg_tex != null:
		beijing.texture = _bg_tex
	_fit_background()
	print("main.gd: 背景 = %s（%s）" % [String(files[0]), "OK" if _bg_tex != null else "加载失败"])


func _fit_background() -> void:
	if beijing == null or beijing.texture == null:
		return
	var vp := get_viewport_rect().size
	var ts := beijing.texture.get_size()
	if ts.x <= 0.0 or ts.y <= 0.0:
		return
	# 覆盖整屏：等比缩放到刚好盖满，多余部分裁掉（不会变形、不会留黑边）
	var sc := maxf(vp.x / ts.x, vp.y / ts.y)
	beijing.centered = true
	beijing.scale = Vector2(sc, sc)
	beijing.global_position = vp * 0.5

const SkinPatch := preload("res://skin.gd")   # 外部皮肤（exe 同目录 skin\）


func _ready() -> void:
	Engine.max_fps = int(ProjectSettings.get_setting("application/run/max_fps", 90))   # 跟着 项目设置→运行→最大FPS（现在 90）
	TilePiece.anim_scale = maxf(tile_fly_speed, 0.0)   # 牌飞行速度倍率（0 = 瞬移）
	randomize()
	_btn_tune_load()          # 按钮微调（user://btn_tune.cfg，没有就用 @export 的值）
	call_deferred("_dev_autoplay_maybe")	# 开发用：有 autoplay.cfg 才自动打
	call_deferred("_round_info_icon_place")   # 右上角开关图标：摆进屏幕（用户摆的 y=-33 在屏幕外）
	# 播报场景在这里先实例化一次（贴图/字体预热的开销挪到开局），避免第一次和牌卡一下
	call_deferred("_win_scene_get")
	get_tree().auto_accept_quit = false     # 关窗口要先清记录再退
	_setup_background()
	_lizhi_stick_hide_all()   # 立直棒：开局先把四根收起来（等 riichi 列表再淡入）

	for i in SORT_ORDER.size():
		sort_rank[SORT_ORDER[i]] = i
	for i in TILE_KINDS.size():
		kind_index[TILE_KINDS[i]] = i

	pai = get_node_or_null("Pai")
	if pai == null:
		push_error("main.gd: 找不到 Pai 节点（牌模板库），手牌无法显示")
		return
	pai.visible = false          # 模板库只在运行时被复制，不直接显示
	_measure_tile_size()

	# 136 张牌实体库：开局前一次性建好并编号（1m01..zhong04），之后只改状态
	tile_bank = TileBank.new()
	tile_bank.name = "TileBank"
	add_child(tile_bank)
	# 牌直接用屏幕坐标摆放，忽略 Main 的偏移，把坐标空间对齐到 (0,0)
	tile_bank.top_level = true
	tile_bank.global_position = Vector2.ZERO
	tile_bank.build(tile_size)
	# 手牌点击由单张牌的脚本发出，这里只把它接到「打哪张」
	tile_bank.hand_clicked.connect(discard_tile)
	hand_pick.setup(self, tile_bank)                 # 统一的「选手牌」界面
	swap_panel.setup(self, tile_bank, hand_pick)     # 通用的「技能选牌面板」
	c33_panel.setup(self, tile_bank, hand_pick)      # 染手（33S1）
	c43_panel.setup(self, tile_bank, hand_pick)      # NO MISS（43S1）
	c45_panel.setup(self, tile_bank, hand_pick)      # 神境（45S1）
	c46_panel.setup(self, tile_bank, hand_pick)      # 恶听（46S1）
	ym_panel.setup(self, tile_bank, hand_pick)
	press_panel.setup(self, tile_bank, hand_pick)
	c27_panel.setup(self, tile_bank, hand_pick)
	c24_panel.setup(self, tile_bank, hand_pick)      # 一发（24S1）
	c25b_panel.setup(self, tile_bank, hand_pick)     # 宝牌的集合（25S2）
	c30_panel.setup(self, tile_bank, hand_pick)      # 向听（30S1）
	c32_panel.op_prefix = "c32"                     # 新手运（32S1）：只能交幺九、不用选人
	c32_panel.flow_name = "新手运"
	c32_panel.only_orphan = true
	c32_panel.need_arm = false
	c32_panel.setup(self, tile_bank, hand_pick)
	tile_bank.river_clicked.connect(_on_river_clicked)      # 换牌技能：点牌河

	fpai = get_node_or_null(FPAI_NODE)
	if fpai != null:
		fpai.visible = false     # 打出牌的模板库，同样只在运行时被复制
	fengpan = get_node_or_null(FENGPAN_NODE) as Node2D
	if fengpan != null:
		fengpan_base_scale = fengpan.scale
		fengpan_base_pos = fengpan.position
		fengpan_ready = true
		_apply_fengpan()          # 大小 / 位置 / 朝向一次到位（牌河跟着重排）
	# 牌河：场景里预置了 UI/Pile/{我,D,C,B}（每家 24 个格子「格01…格24」）
	#   · 认领成功 → 直接用，代码不再新建节点（每个格子都能挂动效）
	#   · 找不到 → 退回老办法（现场新建一个空容器，格子临时生成）
	discard_container = get_node_or_null("UI/Pile/我") as Node2D
	if discard_container == null:
		discard_container = Node2D.new()
		discard_container.name = "DiscardPile"
		if fengpan != null:
			fengpan.get_parent().add_child(discard_container)
		else:
			add_child(discard_container)

	create_wall()
	# 开局每家 0 张 —— 手牌由「配牌阶段」一张一张发（见 start_deal）
	hand_tiles.clear()
	drawn_tile = ""
	sort_hand()

	_setup_opponents()
	_setup_action_buttons()               # 三家各 0 张 + 准备「摸到的那张」的形象
	_load_muted()                         # ★ 遮罩状态存盘（F5 之后还在）
	_setup_identity_skills()              # 人物卡上的技能图标 → 发技能请求

	_skill_mute_apply()

	# 手牌区：场景里预置了 UI/Hand（14 个格子「格01…格14」，每格下面有 Anim 层）
	#   · 认领成功 → 直接用这些格子（位置/动画归你）；找不到 → 退回现场新建
	hand_container = get_node_or_null("UI/Hand") as Control
	if hand_container == null:
		hand_container = Control.new()
		hand_container.mouse_filter = Control.MOUSE_FILTER_IGNORE
		add_child(hand_container)
	_setup_hand_slots()
	_layout_hand_area()


	refresh_hand()
	_refresh_wall_stacks()   # 牌山：认领场景里预置的 68 个牌墩（墩01…墩68）
	_update_seat_label()     # 左上角显示「本窗口 = 几号位」（按 1/2/3/4 换）
	# ── 外部皮肤（exe 同目录 skin\ 或 user://skin）：没有图就什么都不做 ──
	SkinPatch.setup()
	var _skin_scene := get_tree().current_scene
	if _skin_scene != null:
		SkinPatch.apply_tree(_skin_scene)
	SkinPatch.hook(get_tree())

	start_deal()             # 认领座位 + 配牌（第一个窗口开新局，其余接上）


# ── 关窗口：最后一个窗口关掉时把整局记录清空（下次启动从「准备」重新开始）──
func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST:
		_on_window_closing()


func _on_window_closing() -> void:
	get_tree().auto_accept_quit = false
	var seat := my_seat if my_seat >= 0 else -1
	if srv != null:
		srv.request({"op": "wipe", "seat": seat})
	for p in ["user://player_orders.json", "user://player_order.json",
			"user://player_cards.json", "user://from_initial_menu.flag",
			"user://hanchan_owner.json"]:
		if FileAccess.file_exists(String(p)):
			DirAccess.remove_absolute(ProjectSettings.globalize_path(String(p)))
	get_tree().quit()


# ────────────────────────── 牌墩 / 牌山（四面，每面 17 墩）──────────────────────────

# 摆牌山：左右两列用 b_04（先摆远的一端、后摆近的一端，后摆的盖住先摆的正面边缘）；
# 上下两排用 b_05（竖版方块，紧密相连、互不覆盖）
func _build_wall_stacks() -> void:
	if wall_node == null:
		if not is_inside_tree():
			return          # 场景还没挂好（加载时 setter 会先跑一次），等 _ready
		wall_node = get_node_or_null(WALL_NODE)
	if wall_node == null:
		push_warning("main.gd: 找不到 " + WALL_NODE + " 节点")
		return
	# ★ 牌墩现在是场景里预置的 68 个节点（墩01…墩68，按编号顺序）—— 优先「认领」它们：
	#   · 认领成功：按 wall_* 参数重排一次（所以调那些导出参数 = 「按参数再排一遍」）
	#   · 平时位置归你：在编辑器里手拖、挂动画，都不用回来改代码
	#   · 节点被删了 / 数量对不上 → 退回老办法（下面那段现场新建）
	if _adopt_wall_stacks():
		_layout_wall_nodes()
		return
	if art_sprite("牌背", "b_04") == null:
		push_warning("main.gd: 找不到 牌背/b_04 节点（牌山摆不出来）")
		return
	# 老办法：按参数现场新建（只在「预置节点不可用」时跑）
	# 先把上一次摆的收掉（改接口数值时会重摆）
	for vis in wall_sprites:
		if is_instance_valid(vis):
			if vis.get_parent() != null:
				vis.get_parent().remove_child(vis)
			vis.queue_free()
	wall_sprites.clear()
	wall_stacks.clear()
	# 把你示范用的那三墩藏起来，免得和新牌墩叠在一起
	for c in wall_node.get_children():
		var cs := c as Sprite2D
		if cs != null and cs.texture != null and cs.texture.resource_path.ends_with("b_04.png"):
			cs.visible = false
	var cc := wall_col_center
	var cw: float = wall_col_width                              # 左右两列一墩的显示宽度
	var cpitch: float = cw * WALL_COL_PITCH_RATIO                # 左右两列相邻两墩的间距
	var chalf: float = float(wall_stacks_per_side - 1) * 0.5 * cpitch
	# 左右两列：竖着排，越往下越靠前（z 越大）→ 下压上
	_wall_side("牌背", "b_04", cw, cpitch, Vector2(cc.x - wall_col_span * 0.5, cc.y - chalf), Vector2(0.0, 1.0), 0.0, "left")
	_wall_side("牌背", "b_04", cw, cpitch, Vector2(cc.x + wall_col_span * 0.5, cc.y - chalf), Vector2(0.0, 1.0), 0.0, "right")
	# 上下两排：横着排，间距 = 一墩宽度（紧挨着，不叠压）
	var rtex := _wall_row_texture()
	if rtex != null:
		var rc := wall_row_center
		var rw: float = wall_row_width                          # 上下两排一墩的显示宽度
		var rhalf: float = float(wall_stacks_per_side - 1) * 0.5 * rw
		_wall_side("牌背", "b_05", rw, rw, Vector2(rc.x - rhalf, rc.y - wall_row_span * 0.5), Vector2(1.0, 0.0), wall_row_rotation, "top")
		_wall_side("牌背", "b_05", rw, rw, Vector2(rc.x - rhalf, rc.y + wall_row_span * 0.5), Vector2(1.0, 0.0), wall_row_rotation, "bottom")

# 上下两排用的 b_05：节点里已经挂好「裁出中间那块」的图（AtlasTexture），直接用
func _wall_row_texture() -> Texture2D:
	if wall_row_atlas == null:
		var t := art_back_tex("b_05")
		if t == null:
			t = _load_tex(WALL_ROW_STACK_TEX)
		if t == null:
			return null
		if t is AtlasTexture:
			wall_row_atlas = t                       # 节点上就是裁好的
		else:
			var at := AtlasTexture.new()
			at.atlas = t
			at.region = WALL_ROW_INK_RECT
			wall_row_atlas = at
	return wall_row_atlas

# 摆一面牌山：origin = 第一墩的位置，dir = 排列方向（单位向量）
# 图从 Art 节点复制（group/key）：左右两列用 牌背/b_04，上下两排用 牌背/b_05
func _wall_side(group: String, key: String, w: float, pitch: float, origin: Vector2,
		dir: Vector2, rot_deg: float, side: String) -> void:
	for i in range(wall_stacks_per_side):
		var vis := _make_art_visual(group, key, w)
		if vis == null:
			return
		vis.position = origin + dir * (float(i) * pitch)
		vis.rotation_degrees = rot_deg
		vis.z_index = i                      # 后摆的盖住先摆的
		wall_node.add_child(vis)
		wall_sprites.append(vis)
		wall_stacks.append({"side": side, "idx": i, "vis": vis, "count": 2, "no": 0, "tiles": []})


# ── 牌墩：编号 ↔ 场景节点 ────────────────────────────────────────────────────
# 场景的「牌墩」下面预置了 4×N 个节点：墩01 … 墩68（顺序 = 绕牌山一圈的编号顺序：
#   下排从右往左 → 左列从下往上 → 上排从左往右 → 右列从上往下）。
#   · wall_stacks 数组 = 按同一顺序「认领」这些节点；墩号（1..4N）仍由 assign_wall_numbers() 分
#   · 认领时不动 position / rotation —— 位置归你，手拖、挂动画都不用回来改代码
#   · 只有改 wall_* 那组导出参数时，才会调 _layout_wall_nodes() 按参数重排一次
const WALL_STACK_FMT := "墩%02d"


# 预置节点（按 ring 顺序）；数量对不上就返回空 = 让上层走老办法
func _wall_stack_nodes() -> Array:
	var out: Array = []
	if wall_node == null:
		return out
	for i in range(1, 4 * int(wall_stacks_per_side) + 1):
		var n := wall_node.get_node_or_null(WALL_STACK_FMT % i) as Node2D
		if n == null:
			return []
		out.append(n)
	return out


# ring 顺序（下→左→上→右；下/左按 idx 倒着数）对应的 side / idx
func _wall_ring_meta() -> Array:
	var out: Array = []
	var n := int(wall_stacks_per_side)
	for side in WALL_RING:
		for i in range(n):
			out.append({"side": side,
				"idx": (n - 1 - i) if (side == "bottom" or side == "left") else i})
	return out


# 一墩的位置 / 显示宽度（只由 wall_* 参数决定）→ [Vector2 位置, float 宽度]
func _wall_slot_rect(side: String, idx: int) -> Array:
	var n := int(wall_stacks_per_side)
	if side == "left" or side == "right":
		var cw: float = wall_col_width
		var cpitch: float = cw * WALL_COL_PITCH_RATIO
		var chalf: float = float(n - 1) * 0.5 * cpitch
		var x: float = wall_col_center.x
		x += wall_col_span * 0.5 if side == "right" else -wall_col_span * 0.5
		return [Vector2(x, wall_col_center.y - chalf + float(idx) * cpitch), cw]
	var rw: float = wall_row_width
	var rhalf: float = float(n - 1) * 0.5 * rw
	var y: float = wall_row_center.y
	y += wall_row_span * 0.5 if side == "bottom" else -wall_row_span * 0.5
	return [Vector2(wall_row_center.x - rhalf + float(idx) * rw, y), rw]


# 按 wall_* 参数把预置的牌墩重排一遍（改参数时才走这里）
# 「从牌山飞进来」的起飞点：所有牌墩节点的平均位置（≈牌山环中心）。
# 配牌 / 摸牌时新出现的牌从这里飞出来，比「凭空出现在手上」好认得多。
func _wall_fly_anchor() -> Vector2:
	var c := Vector2.ZERO
	var n := 0
	for nd in wall_sprites:
		var sp := nd as Node2D
		if sp == null or not is_instance_valid(sp) or not sp.visible:
			continue
		c += sp.global_position
		n += 1
	if n > 0:
		return c / float(n)
	var r := fengpan_effective_rect()
	if r.size.x > 0.0:
		return global_position + r.position + r.size * 0.5
	return get_viewport_rect().size * 0.5


func _layout_wall_nodes() -> void:
	var _pile := get_node_or_null("UI/Pile")
	if _pile != null:
		_force_visible_chain(_pile)
	var nodes := _wall_stack_nodes()
	var meta := _wall_ring_meta()
	if nodes.is_empty() or nodes.size() != meta.size():
		return
	for i in range(nodes.size()):
		var info := _wall_slot_rect(String(meta[i]["side"]), int(meta[i]["idx"]))
		var nd: Node2D = nodes[i]
		nd.position = info[0]
		nd.rotation_degrees = 0.0
		nd.z_index = int(meta[i]["idx"])              # 后摆的盖住先摆的
		nd.call("setup", String(meta[i]["side"]), (wall_row_width if WALL_VERT_SIDES.has(String(meta[i]["side"])) else wall_col_width))
		nd.visible = true


# 「认领」预置的牌墩：重建 wall_stacks / wall_sprites，不动位置
func _adopt_wall_stacks() -> bool:
	var nodes := _wall_stack_nodes()
	var meta := _wall_ring_meta()
	if nodes.is_empty() or nodes.size() != meta.size():
		return false
	wall_stacks.clear()
	wall_sprites.clear()
	for i in range(nodes.size()):
		var nd: Node2D = nodes[i]
		var side := String(meta[i]["side"])
		nd.call("setup", side, (wall_row_width if WALL_VERT_SIDES.has(side) else wall_col_width))
		wall_stacks.append({"side": side, "idx": int(meta[i]["idx"]), "vis": nd,
			"count": 2, "no": 0, "tiles": []})
		wall_sprites.append(nd)
	return true


# 开一局 / 换局时用：只认领，不重排（位置归你）
func _refresh_wall_stacks() -> void:
	if not _adopt_wall_stacks():
		_build_wall_stacks()


# 一墩长什么样：完整的两张（b_04 / b_05）还是只剩一张（b_01 / b_02）。
# ★ 只换图、缩放、翻转，不新建节点 —— 节点是场景里的那个，动画都挂在它身上。
func _set_stack_face(nd: Node2D, side: String, count: int) -> void:
	if nd == null:
		return
	var vert: bool = WALL_VERT_SIDES.has(side)        # 主视角的上/下 = 竖着的墩
	var sp := nd.get_node_or_null("Sprite2D") as Sprite2D
	if sp == null:
		return
	var key := ("b_05" if vert else "b_04") if count >= 2 else ("b_02" if vert else "b_01")
	var tex := art_back_tex(key)
	if tex == null:
		return
	var w: float = wall_row_width if vert else wall_col_width
	var two_h := 0.0
	if count < 2:      # 只剩一张：往下挪半张，底边和原来那墩对齐
		var two := art_back_tex("b_05" if vert else "b_04")
		if two != null:
			two_h = two.get_size().y * (w / maxf(two.get_size().x, 1.0))
	sp.texture = tex
	sp.centered = true
	sp.scale = Vector2.ONE * (w / maxf(tex.get_size().x, 1.0))
	sp.rotation_degrees = 180.0 if count < 2 else 0.0
	var h: float = tex.get_size().y * sp.scale.y
	sp.position = Vector2(0.0, (two_h - h) * 0.5) if count < 2 else Vector2.ZERO
	sp.visible = count > 0
	nd.visible = count > 0


# ────────────────────────── 手牌排序 ──────────────────────────

func sort_hand() -> void:
	hand_tiles.sort_custom(_comes_first)


func _comes_first(a: String, b: String) -> bool:
	return sort_rank.get(a, 999) < sort_rank.get(b, 999)


# 摸到的牌在整行里的下标（-1 = 没有摸牌）
func drawn_slot() -> int:
	if drawn_tile == "":
		return -1
	if not DRAWN_INSERT_SORTED:
		return hand_tiles.size()
	var r: int = sort_rank.get(drawn_tile, 999)
	var i := 0
	while i < hand_tiles.size() and sort_rank.get(hand_tiles[i], 999) <= r:
		i += 1
	return i


# 实际显示的一行牌（手牌 + 插到排序位置的摸牌）
func display_tiles() -> Array[String]:
	var out: Array[String] = []
	out.assign(hand_tiles)
	var slot := drawn_slot()
	if slot >= 0:
		out.insert(slot, drawn_tile)
	return out


# ────────────────────────── 牌桌逻辑 ──────────────────────────

# ── 牌墩 / 牌山（四面：左右两列 + 上下两排，每面 17 墩）──
const WALL_NODE := "../牌墩"      # 相对 Main：牌墩挂在场景根节点下
const WALL_STACK_TEX := "res://Cailiao/mahjong_graphic/PNG 位图/默认风格 default style/背面 back/b_04.png"
const WALL_ROW_STACK_TEX := "res://Cailiao/mahjong_graphic/PNG 位图/默认风格 default style/背面 back/b_05.png"
const WALL_ROW_INK_RECT := Rect2(413, 284, 352, 531)   # b_05 画布很大、牌只占中间一块，先裁出来用

# ────────────────────────── 图从「节点」取（不再按路径现读）──────────────────────────
# 所有图和以前不一样了：它们是场景里的节点 —— Main/Art 下面分成
#   牌背 / 杠面 / 宝牌指示牌{竖翻,横翻}
# （建这些节点的是 art_library.gd；名字就是文件名，例如 牌背/b_04、宝牌指示牌/竖翻/1m）
# 好处：以后要给图加动效/换图，直接在场景里改节点，不用回来改代码。
# 说明：节点找不到时**回退**成老办法（按路径读文件），所以永远不会变白板。
const ART_NODE := "Art"                      # Main/Art（见 art_library.gd）
var _art_cache: Node = null                  # 缓存的 Art 节点


func _art() -> Node:
	if _art_cache == null or not is_instance_valid(_art_cache):
		_art_cache = get_node_or_null(ART_NODE)
	return _art_cache


# 取「组 / 名字」对应的那个图节点（拿它做动画/复制就用这个）
func art_sprite(group: String, key: String) -> Sprite2D:
	var a := _art()
	if a == null or not a.has_method("sprite"):
		return null
	return a.call("sprite", group, key) as Sprite2D


func _art_tex(group: String, key: String) -> Texture2D:
	var s := art_sprite(group, key)
	return s.texture if s != null else null


# 牌背：b_01 / b_02 / b_04 / b_05 …
func art_back_tex(key: String) -> Texture2D:
	var t := _art_tex("牌背", key)
	if t == null:
		t = _load_tex(BACK_DIR + key + ".png")              # 回退：老办法
	return t


# 宝牌指示牌：view = "h"(横) / "hf"(横翻) / "vf"(竖翻)；key = 文件名（1m / h1z / 0p …）
func art_dora_tex(view: String, key: String) -> Texture2D:
	var group := "宝牌指示牌/竖翻" if view == "vf" else "宝牌指示牌/横翻"
	var t := _art_tex(group, key)
	if t == null:
		t = _load_tex((DORA_DIR_VF if view == "vf" else DORA_DIR_HF) + key + ".png")
	return t


# 杠面（暗杠那张「两张牌叠着画」的图）
func art_kan_tex(key: String) -> Texture2D:
	var t := _art_tex("杠面", key)
	if t == null:
		t = _load_tex(KAN_FACE_DIR + key + ".png")          # 回退：老办法
	return t
# 你示范的 B04/05/06 量出来的参数（都相对「牌墩」节点）
const WALL_DEMO_PITCH := 57.06        # 示范里两墩的间距（墩心到墩心）
const WALL_DEMO_WIDTH := 75.748       # 示范里一墩的显示宽度
const WALL_DEMO_TOP_Y := 162.053      # 示范推出来的最上面那墩（801.125 − 16 × 57.06）
const WALL_DEMO_BOTTOM_Y := 801.125   # 示范里最下面那墩的位置
const WALL_DEMO_LEFT_X := 307.0       # 示范那一列的 x
const WALL_DEMO_RIGHT_X := 1461.89    # 右列（左边那列关于屏幕中线镜像）
const WALL_COL_PITCH_RATIO := WALL_DEMO_PITCH / WALL_DEMO_WIDTH   # 左右两列：间距 = 一墩宽度 × 0.75329

# ── 牌山接口：两组，各自都有「大小 + 位置」（都在「牌墩」节点自己的坐标系里，改完立刻重摆）──
# ① 左右两列（左列 + 右列，永远关于中心左右对称）
@export var wall_col_width := 55.00:                    # 大小：一墩的显示宽度（像素）；间距按示范比例跟着缩放
	set(v):
		wall_col_width = maxf(v, 1.0)
		_build_wall_stacks()
@export var wall_col_center := Vector2(834.445, 381.589):   # 位置：这两列的中心（x 左右挪、y 上下挪）
	set(v):
		wall_col_center = v
		_build_wall_stacks()
@export var wall_col_span := 771.67:                    # 位置：左右两列的间距（两列一起朝中间 / 朝两侧挪）
	set(v):
		wall_col_span = v
		_build_wall_stacks()
# ② 上下两排（上排 + 下排，紧密相连、互不叠压）
@export var wall_row_width := 42.00:                    # 大小：一墩的显示宽度（像素）；间距 = 宽度（紧挨着）
	set(v):
		wall_row_width = maxf(v, 1.0)
		_build_wall_stacks()
@export var wall_row_center := Vector2(834.445, 381.589):   # 位置：这两排的中心
	set(v):
		wall_row_center = v
		_build_wall_stacks()
@export var wall_row_span := 762.75:                    # 位置：上下两排的间距（两排一起朝中间 / 朝两侧挪）
	set(v):
		wall_row_span = v
		_build_wall_stacks()
# ③ 两组共用
@export var wall_stacks_per_side := 17:                 # 每一面几墩
	set(v):
		wall_stacks_per_side = maxi(v, 1)
		_build_wall_stacks()
@export var wall_row_rotation := 0.0:                   # 上下两排的朝向（b_05 本身就是竖着的，不旋转）
	set(v):
		wall_row_rotation = v
		_build_wall_stacks()

var wall_node: Node2D
var wall_sprites: Array[Node2D] = []
var wall_row_atlas: Texture2D = null

# ────────────────────────── 配牌阶段（骰子 → 牌山编号 → 发牌）──────────────────────────
#
# 牌山：每面 17 墩，一墩 = 两张牌（上面那张奇数号、下面那张偶数号）。
# 编号从骰子指到的那一面开始，沿牌山绕一圈：下排(东)从右往左 → 左列(西)从下往上
# → 上排(北)从左往右 → 右列(南)从上往下。编号 1..136 和服务器牌山序列 seq 0..135 一一对应，
# 其中前 14 张是王牌，发牌从第 15 张开始。
# ★ 「哪一面算东」不是写死的：东面 = 庄家那一面（服务端就是这么数的），所以庄家换人、
#   或者我换了座位视角时，都要 assign_wall_numbers() 重排一次（见 wall_dealer_ring_slot）。
# 整个一局分三个阶段：配牌 → 切牌 → 结算（看 game_phase）

const PHASE_DEAL := "配牌"
const PHASE_PLAY := "切牌"
const PHASE_END := "结算"
const DEAL_ROUNDS := 3                       # 一共 3 圈
const DEAL_TILES_PER_TURN := 4               # 每次 4 张（2 墩）
const DEAL_FIRST_WAIT := 1.0                 # 第一次等 1 秒
const DEAL_STEP_WAIT := 0.2                  # 之后每次 0.2 秒
# 老渲染（UI/Hand 格子、UI/Pile 格子、Melds 现场建节点）已经被 TileBank 实体取代。
# false = 只让实体画（动画不会重影）；true = 回到以前的多套画法。
const LEGACY_TILE_RENDER := false
const DEAL_FIRST_TILE := 15                  # 1..14 是王牌，发牌从 15 开始
const WALL_FIRST_SIDE: Array[String] = ["东", "南", "西", "北"]   # 风名顺序（服务端 SIDE_ORDER 同一套；现在只当参考）
const WALL_RING: Array[String] = ["bottom", "left", "top", "right"]   # 编号沿牌山绕的方向
# 沿着牌山绕一圈的时候，四个「风名」的先后 —— 和风盘图上的画法一致（下东 → 左西 → 上北 → 右南）
const WALL_RING_WINDS: Array[String] = ["东", "西", "北", "南"]
# 「庄家坐 0 号位时哪一面叫什么风」，只是备忘（真正用的是 wall_dealer_ring_slot()，跟着庄家走）
const WALL_SIDE_NAME := {"bottom": "东", "right": "南", "top": "北", "left": "西"}
# 牌墩只剩一张时的图（方向都是对主视角而言）：
#   主视角的上/下（竖着摆的墩）→ b_02 转 180°；主视角的左/右（横着摆的墩）→ b_01 转 180°
const WALL_SINGLE_VERT := "res://Cailiao/mahjong_graphic/PNG 位图/默认风格 default style/背面 back/b_02.png"
const WALL_SINGLE_HORZ := "res://Cailiao/mahjong_graphic/PNG 位图/默认风格 default style/背面 back/b_01.png"
const WALL_VERT_SIDES: Array[String] = ["top", "bottom"]

var game_phase := PHASE_DEAL                 # 配牌 / 切牌 / 结算
var dice := [0, 0]                           # 静默投的两个骰子（不显示在画面上）
var wall_start_side := ""                    # 骰子指到的牌山面
var wall_stacks: Array = []                  # 每墩：{side, idx, vis, count, no, tiles:[上,下]}
var wall_tile_order: Array = []              # 编号 1..136 → 牌 id（跟服务端牌山序列一一对应）
var deal_round := 0
var deal_seat := 0
var dealing := false
var deal_final_done := false                 # 配牌最后一步（庄家多摸那张）是否做完
var jump_tile_no := 0                        # 庄家跳牌多拿那张的编号（0 = 还没跳）

# ── 数据都在服务端，客户端只渲染 ──
var srv_state: Dictionary = {}      # 最近一次服务端状态（庄家/骰子/牌山/牌河/副露…）
var srv_taken := {}                 # 已根据服务端拿走的牌编号（幂等，不重复扣）
var srv_dora_n := -1                # 已经渲染了几张宝牌指示牌
var srv_round_id := -1              # 最近一次服务端状态的 round_id（变了 = 换了一局，整块重画）
var srv_dealer_side := -1           # 庄家在我屏幕的哪一面（0 下 / 1 右 / 2 上 / 3 左；变了 = 风盘要转、牌山要重编号）
var srv_humans: Array = []          # 服务端说「哪些座位有窗口在操作」（配牌由最小座位号那个窗口推进）


# 认领座位：服务端把「没人认领的座位」继续当代打 AI；
# 还没有牌局就顺手开一局（created = true），已经有局就接上（created = false）。
func srv_join_seat(seat: int, quiet := false, render := true,
		force := false, keep := false) -> Dictionary:
	# seat < 0 = 不指定，让服务端自动挑一个没人坐的位子
	# ★ force 只有「按 1/2/3/4 手动切座位」才用。
	#   启动时绝不能 force：F5 时上一个窗口可能还活着，force 会把 0 号位抢过来
	#   → 两个窗口都显示「本窗口 = 0 号位」。
	var r := srv_request({"op": "join", "seat": seat,
		"force": bool(force) and int(seat) >= 0,
		# keep = 「大厅刚把我分到这个位子，进牌桌还坐这儿」→ 服务端别把我挤走
		"keep": bool(keep) and int(seat) >= 0})
	if r.is_empty():
		return {}
	# 座位号只信服务端给的，而且一定夹在 0..3（响应异常时别把界面带到「4 号位」这种不存在的地方）
	var got_seat := clampi(int(r.get("seat", maxi(seat, 0))), 0, 3)
	if not quiet and int(seat) >= 0 and got_seat != int(seat):
		print("main.gd: %d 号位已经有别的窗口在操作 → 本窗口改坐 %d 号位"
			% [int(seat), got_seat])
	my_seat = got_seat
	# 换座位（大厅分座 / 按 1-4 切视角）时，桌面身份卡也要跟着转：
	# 自己那两张永远摆在「本家」的右下角，其余三家按 下→对→上 逆时针排
	var idn_view := get_node_or_null("Identity")
	if idn_view != null and idn_view.has_method("set_view_seat"):
		idn_view.call("set_view_seat", my_seat)
	if typeof(r.get("humans")) == TYPE_ARRAY:
		srv_humans = r.get("humans")
	_update_seat_label()
	if not quiet:
		print("main.gd: 本窗口 = %s（有窗口的座位 %s）" % [_seat_text(), _humans_text()])
	if render and typeof(r.get("state")) == TYPE_DICTIONARY:
		# 换了视角：牌面有关的缓存全部清掉，整块按新座位重画
		_reset_view_for_new_round()
		_apply_round_start(r)
		game_phase = PHASE_PLAY
		dealing = false
		srv_apply_state(r.get("state"), [])
		draw_tile()
	return r


func srv_new_round() -> void:
	# F2（调试）：把当前局当作「无人听牌的荒牌流局」直接结束，进入下一场。
	# 例：东二 2 本场 → 东三 2 本场（本场不 +1，亲家下移）。
	var r := srv_request({"op": "next", "seat": my_seat, "f2": true})
	if r.is_empty():
		return
	print("main.gd: 下一局（本窗口 = %d 号位）" % my_seat)
	_reset_view_for_new_round()
	dealing = true
	game_phase = PHASE_DEAL
	_apply_round_start(r)
	get_tree().create_timer(DEAL_FIRST_WAIT).timeout.connect(_deal_step)


# 换座位 / 开新局之后：牌面有关的缓存全部清掉，牌山重建，整块按新视角重画
# 这次启动是不是「新的半庄」？
#   · 没有 owner、owner 进程已经关了 → 我是新进程 → 重置东一
#   · owner 还活着且不是本进程 → 另一个窗口在开这场 → 直接接上
#   · owner 就是本进程 → 本进程已经开过，重进场景不再重置
# 是不是联机模式（net.cfg 存在 → 走 server/net_server.py）。
# ★ 联机时不要用本机的 hanchan_owner.json 去决定「谁重置半庄」：
#   那是一个**本地文件**，四台机器各有一份 → 四个人都会以为自己是主人，
#   于是每人发一次 new_hanchan，开局被重置 4 次。联机的新半庄交给
#   大厅（四家都准备好时服务端自己重置）。
func _net_mode() -> bool:
	if srv == null:
		srv = ServerBridge.new()
	return srv.net != null and bool(srv.net.enabled)


func _claim_hanchan_owner() -> bool:
	var my_pid := OS.get_process_id()
	var owner_pid := -1
	if FileAccess.file_exists(HANCHAN_OWNER):
		var rf := FileAccess.open(HANCHAN_OWNER, FileAccess.READ)
		if rf != null:
			var data = JSON.parse_string(rf.get_as_text())
			if typeof(data) == TYPE_DICTIONARY:
				owner_pid = int((data as Dictionary).get("pid", -1))
	if owner_pid == my_pid:
		return false
	if owner_pid > 0 and OS.is_process_running(owner_pid):
		return false
	var wf := FileAccess.open(HANCHAN_OWNER, FileAccess.WRITE)
	if wf == null:
		return false
	wf.store_string(JSON.stringify({"pid": my_pid, "time": Time.get_unix_time_from_system()}))
	wf.close()
	# 写完回读一次：两个窗口同时启动时，只有一个能读到自己的 pid
	var chk := -1
	if FileAccess.file_exists(HANCHAN_OWNER):
		var rf2 := FileAccess.open(HANCHAN_OWNER, FileAccess.READ)
		if rf2 != null:
			var d2 = JSON.parse_string(rf2.get_as_text())
			if typeof(d2) == TYPE_DICTIONARY:
				chk = int((d2 as Dictionary).get("pid", -1))
	if chk != my_pid:
		return false
	return true


func _clear_card_files() -> void:
	for p in ["user://player_cards.json", "user://player_order.json",
			"user://player_orders.json"]:
		if FileAccess.file_exists(p):
			DirAccess.remove_absolute(ProjectSettings.globalize_path(p))


func _reset_view_for_new_round() -> void:
	game_over = false
	_skill2_close(false)
	_board_close()
	_press_close()
	_swap_close()
	if ym_panel.active:
		ym_panel.close()
	if c24_panel.active:
		c24_panel.close()
	if c25b_panel.active:
		c25b_panel.close()
	if c27_panel.active:
		c27_panel.close()
	if c30_panel.active:
		c30_panel.close()
	c30_key = ""
	if c32_panel.active:
		c32_panel.close()
	c32_key = ""
	if c26_active:
		_c26_close()
	_future_close()
	_deal_hide()
	_flow_close()
	_c25_confirm_show(false)
	_wind_close()
	_c05_close(false)
	_c05_hide_close()
	_sw_close()
	_last_broadcast_id = 0
	var idn0 := get_node_or_null("Identity")
	if idn0 != null and idn0.has_method("reset_skill_states"):
		idn0.call("reset_skill_states")
	if idn0 != null and idn0.has_method("reset_skill_frames"):
		idn0.call("reset_skill_frames")
	if board_tile_node != null and is_instance_valid(board_tile_node):
		board_tile_node.visible = false
	riichi_declared = false
	riichi_selecting = false
	if guobiao_selecting:
		_gb_close(false)
	if yiding_selecting:
		_yd_close(false)
	srv_meld_sig = MELD_SIG_RESET          # 哨兵值：保证下一次一定重画（空副露的指纹也是 ""）
	srv_taken.clear()
	srv_dora_n = -1
	dora_revealed = 0
	rinshan_used = 0
	dora_indicators.clear()
	ura_indicators.clear()
	meld_list.clear()
	hand_tiles.clear()
	drawn_tile = ""
	discard_pile.clear()
	discard_rotated.clear()
	# 副露的图直接清掉（不等下一次状态同步）——不然上一局的副露会留在桌面上
	if meld_container != null:
		for c in meld_container.get_children():
			meld_container.remove_child(c)
			c.queue_free()
	if opp_meld_container != null:
		for c in opp_meld_container.get_children():
			opp_meld_container.remove_child(c)
			c.queue_free()
	meld_left = -1.0
	meld_count = 0
	menzen = true
	# 各种按钮也收起来
	hide_chow_panel()
	srv_layout_buttons([])
	for who in OPP_ORDER:
		opp_hands[who] = []
		opp_drawn[who] = ""
		opp_discards[who] = []
		opp_meld_counts[who] = 0
	var rp := get_node_or_null("UI/ResultPanel")
	if rp != null:
		rp.visible = false
		rp.scale = Vector2.ONE
		rp.modulate.a = 1.0
	_win_intro_running = false
	if win_scene != null and is_instance_valid(win_scene):
		win_scene.call("reset")             # 截图背景 / 进场动画 / 结算面板一起清掉
	if win_announce != null and is_instance_valid(win_announce):
		win_announce.visible = false
		win_announce.scale = Vector2.ONE
		win_announce.modulate = Color(1, 1, 1, 1)
	if win_confirm_btn != null and is_instance_valid(win_confirm_btn):
		win_confirm_btn.visible = false
	result_confirmed = false
	result_confirm_sig = ""
	_refresh_wall_stacks()      # 牌山：把上一局拿走的牌全部放回去（认领预置节点，不动位置）
	assign_wall_numbers()       # 重新给每墩编号（编号 ↔ 墩的对应关系跟着重排）
	lizhi_stick_ready = false
	_lizhi_stick_hide_all()     # 立直棒：新一局四根一起收起


# 把「开一局」返回的东西（骰子/牌山/牌山面）画到牌山上
func _apply_round_start(r: Dictionary) -> void:
	var st = r.get("state")
	if typeof(st) != TYPE_DICTIONARY:
		push_error("main.gd: 服务端没给状态，配牌停止。")
		dealing = false
		return
	srv_state = st
	var w = r.get("wall")
	if typeof(w) == TYPE_ARRAY and (w as Array).size() >= 136:
		wall_tile_order = w            # 编号 1..136 → 牌 id（服务端牌山，一一对应）
	elif wall_tile_order.size() < 136:
		wall_tile_order = wall_tiles.duplicate()
	dice = st.get("dice", [])
	first_stack = int(st.get("first_stack", 0))
	wall_start_side = String(st.get("start_side", ""))
	_apply_fengpan()                   # 先把风盘的「東」转到新庄家那一面
	assign_wall_numbers()              # 再把「编号」对到「哪一墩」（编号的起点 = 庄家那一面）


func _seat_text() -> String:
	# 屏幕上的位置是定的（0 号位永远在下方、1 号位在右…）；本窗口坐的是几号位就是哪一家
	match my_seat:
		0:
			return "0 号位（屏幕下方 · 自己）"
		1:
			return "1 号位（屏幕右侧 · 下家）"
		2:
			return "2 号位（屏幕上方 · 对家）"
		3:
			return "3 号位（屏幕左侧 · 上家）"
	return "%d 号位" % my_seat


func _humans_text() -> String:
	# 服务端告诉你「现在哪些座位有窗口」（JSON 回来是浮点，转成整数好看）
	var out := []
	for h in srv_humans:
		out.append(str(int(h)))
	return "[" + ",".join(out) + "]"


func _update_seat_label() -> void:
	# 左上角那行「本窗口 = X 号位 … 第 N 局 东一 0 本场 轮到谁 我 N 张 有窗口的座位 […]」
	# 按需求删掉了。函数保留：_ready / 开新局 / srv_apply_state 都还在调它。
	return


func _num_cn(n: int) -> String:
	return ["一", "二", "三", "四"][clampi(n, 1, 4) - 1]


# 场风 id → 中文（dong → 东）
func _wind_cn(w: String) -> String:
	match w:
		"dong":
			return "东"
		"nan":
			return "南"
		"xi":
			return "西"
		"bei":
			return "北"
	return "东"


# 配牌：全在服务端
#   服务端开新一局：投骰子、洗牌山、算拿牌起点、定牌山面；
#   客户端只拿这些数据来摆牌，自己不算骰子、不算「从第几墩开始拿」。
func start_deal() -> void:
	game_phase = PHASE_DEAL
	dealing = true
	# 是不是从初始菜单（完成抽卡）进来的？直接启动 node_2d = 按 F5 处理
	var from_menu := FileAccess.file_exists(FROM_MENU_FLAG)
	if from_menu:
		DirAccess.remove_absolute(ProjectSettings.globalize_path(FROM_MENU_FLAG))
	# 四个窗口同时进牌桌时，flag 只会被第一个窗口消费掉；
	# 但「大厅已经发过卡」这件事每个窗口自己都记着（ClientState.orders），
	# 所以用内存里的这份兜底，别让后进来的窗口把卡序文件清掉。
	var cst0 := get_node_or_null("/root/ClientState")
	if cst0 != null and typeof(cst0.orders) == TYPE_ARRAY and (cst0.orders as Array).size() == 4:
		from_menu = true
	# 每次 F5 = 新半庄：由「第一个游戏进程」把服务端重置到东一 0 本场。
	# 同时开多个窗口时，后面的窗口看到 owner 进程还活着 → 直接接上，不重置。
	# 从大厅（初始菜单）进来的：半庄已经在「四家全部准备好」时由服务端重置，
	# 这里不能再认领一次，否则第二个窗口会把第一个窗口刚开的那局又结束掉。
	var new_hanchan := false
	if not from_menu and not _net_mode():
		new_hanchan = _claim_hanchan_owner()
	# 认领座位（第一个窗口会顺手开一局；后面的窗口接上同一局）
	# 新半庄的第一个进程固定坐 0 号位；其他窗口自动找空位。
	# 大厅里已经认领过座位（四个窗口各坐一家）→ 进牌桌就坐同一个位子
	var want_seat := -1
	var cst := get_node_or_null("/root/ClientState")
	if cst != null and int(cst.seat) >= 0:
		want_seat = int(cst.seat)
	# 新半庄的「第一个进程」希望坐 0 号位，但**不强占**：0 号位要是还有窗口活着，
	# 服务端会自动给下一个空位（否则会出现两个「0 号位」窗口）。
	var r := srv_join_seat(want_seat if want_seat >= 0 else (0 if new_hanchan else -1),
		true, false, false, from_menu)
	# 大厅里四家调好的顺序：所有窗口写的是同一份，谁写都不会互相踩
	if cst != null and typeof(cst.orders) == TYPE_ARRAY and (cst.orders as Array).size() == 4:
		var owf := FileAccess.open("user://player_orders.json", FileAccess.WRITE)
		if owf != null:
			owf.store_string(JSON.stringify(cst.orders))
			owf.close()
	if new_hanchan:
		var nr := srv_request({"op": "new_hanchan", "seat": my_seat})
		if not nr.is_empty() and typeof(nr.get("state")) == TYPE_DICTIONARY:
			r = nr
			if typeof(nr.get("humans")) == TYPE_ARRAY:
				srv_humans = nr.get("humans")
			# 直接启动 node_2d（没经过初始菜单）→ 清掉上一大局的卡，
			# 让 CardPhase 重新随机 5 张，避免主战/协战还是上一局角色。
			if not from_menu:
				_clear_card_files()
				var idn := get_node_or_null("Identity")
				if idn != null and idn.has_method("reload_orders"):
					idn.call("reload_orders")
					# CardPhase 随后会读这个文件；写入同一组，保证桌面卡和选牌界面一致
					var own = idn.call("current_order")
					if typeof(own) == TYPE_ARRAY and (own as Array).size() >= 5:
						var wf := FileAccess.open("user://player_cards.json", FileAccess.WRITE)
						if wf != null:
							wf.store_string(JSON.stringify(own))
	var st = r.get("state")
	if typeof(st) != TYPE_DICTIONARY:
		push_error("main.gd: 连不上服务端、开不了桌，配牌停止。")
		dealing = false
		return
	_reset_view_for_new_round()
	_apply_round_start(r)
	print("main.gd: 本窗口 = %s（%s；有窗口的座位 %s）"
		% [_seat_text(), "开了新的一局" if bool(r.get("created", false)) else "接上现有的一局",
			_humans_text()])
	if not bool(r.get("created", false)):
		# 已经有局了：不用再发一次牌，直接按服务端状态画出来
		dealing = false
		game_phase = PHASE_PLAY
		srv_apply_state(st, [])
		if not bool(st.get("deal_done", true)):
			# 上一局还没配完牌就断线了 → 该我接手就接着配
			if _is_deal_driver():
				dealing = true
				game_phase = PHASE_DEAL
				_deal_step()
				return
		draw_tile()
		return
	srv_state = st
	var w = r.get("wall")
	if typeof(w) == TYPE_ARRAY and (w as Array).size() >= 136:
		wall_tile_order = w            # 编号 1..136 → 牌 id（服务端牌山，一一对应）
	elif wall_tile_order.size() < 136:
		wall_tile_order = wall_tiles.duplicate()
	# 骰子、拿牌起点、牌山面，全由服务端给（客户端不再自己投骰子、自己算起点）
	dice = st.get("dice", [])
	first_stack = int(st.get("first_stack", 0))
	wall_start_side = String(st.get("start_side", ""))

	print("[配牌] 骰子 %s ＝ 第 %d 墩 → %s 面开始编号，从第 %d 墩开始拿"
		% [str(dice), first_stack, wall_start_side, first_stack])
	# 每家 0 张
	hand_tiles.clear()
	drawn_tile = ""
	sort_hand()
	refresh_hand()
	for who in OPP_ORDER:
		var empty: Array[String] = []
		opp_hands[who] = empty
		opp_drawn[who] = ""
		_refresh_opp_hand(who)
	deal_round = 0
	deal_seat = 0
	deal_final_done = false
	jump_tile_no = 0
	get_tree().create_timer(DEAL_FIRST_WAIT).timeout.connect(_deal_step)


# 把服务端数据画到牌山上：
#   ① 已被拿走的牌（state.wall_taken）→ 逐张渲染（墩 2 张 → 1 张，1 张 → 移除）
#   ② 已翻开的宝牌指示牌（state.dora_stacks + state.dora）→ 逐张渲染覆盖图
func srv_sync_wall(st: Dictionary) -> void:
	if st.is_empty():
		return
	for no in (st.get("wall_taken", []) as Array):
		var n := int(no)
		if not srv_taken.has(n):
			srv_taken[n] = true
			take_wall_tile(n)
	var stacks: Array = st.get("dora_stacks", [])
	var dora: Array = st.get("dora", [])
	for i in range(stacks.size()):
		if i <= srv_dora_n:
			continue
		var tile_id := String(dora[i]) if i < dora.size() else ""
		var s := _stack_at_no(int(stacks[i]))
		if s.is_empty() or tile_id == "":
			continue
		srv_dora_n = i
		dora_revealed = i + 1
		dora_indicators.append(tile_id)
		var vis = s.get("vis", null)
		if vis != null and is_instance_valid(vis):
			(vis as Node).call("show_dora", tile_id)
	# ★ 自愈：一圈牌墩全都不可见、但服务端说牌山还有牌 → 重建一次（编号 + 拿走）
	if int(st.get("live_left", 0)) > 8:
		var _vis_n := 0
		for _st in wall_stacks:
			var _nd = _st.get("vis", null)
			if _nd != null and is_instance_valid(_nd) and (_nd as CanvasItem).visible:
				_vis_n += 1
		if _vis_n == 0 and not wall_stacks.is_empty():
			print("[WALL] 牌山整圈不可见 → 按 state 重建")
			_refresh_wall_stacks()
			_wall_retake(st)
	# 指示牌被换过（Card11「魔术」/ Card05「策略」换王牌的牌）→ 王牌上那张也要换
	for i in range(mini(dora_indicators.size(), dora.size())):
		var now := String(dora[i])
		if now == "" or dora_indicators[i] == now or i >= stacks.size():
			continue
		dora_indicators[i] = now
		var s2 := _stack_at_no(int(stacks[i]))
		if s2.is_empty():
			continue
		var vis2 = s2.get("vis", null)
		if vis2 != null and is_instance_valid(vis2):
			(vis2 as Node).call("show_dora", now)


# 一墩一墩排出的「编号顺序」：从骰子那一面起，沿牌山绕一圈
# 牌山重建后按当前 state 重新扣一遍（自愈用）
func _wall_retake(st: Dictionary) -> void:
	srv_taken.clear()
	srv_dora_n = -1
	for no in (st.get("wall_taken", []) as Array):
		var n2 := int(no)
		if srv_taken.has(n2):
			continue
		srv_taken[n2] = true
		take_wall_tile(n2)


func wall_ring() -> Array:
	var out: Array = []
	var n: int = wall_stacks_per_side
	for side in WALL_RING:
		for i in range(n):
			var idx: int = (n - 1 - i) if (side == "bottom" or side == "left") else i
			var st := _stack_at(side, idx)
			if not st.is_empty():
				out.append(st)
	return out


func _stack_at(side: String, idx: int) -> Dictionary:
	for st in wall_stacks:
		if String(st["side"]) == side and int(st["idx"]) == idx:
			return st
	return {}


# 「东面」是庄家那一面；返回值是那一面在牌山 ring 里的第几节：
#   0 下方 / 3 右侧 / 2 上方 / 1 左侧（ring 是顺时针绕的：下 → 左 → 上 → 右）
func wall_dealer_ring_slot() -> int:
	return [0, 3, 2, 1][_dealer_side()]


# 给每墩编号：一墩两张牌，上面奇数号、下面偶数号。
# 「编号 1 从哪一墩开始」有两件事决定：
#   ① 骰子指到的那一面（wall_start_side，服务端算好给我们的）
#   ② 「东面」是哪一面 —— 东面 = 庄家那一面（服务端就是这么数的：骰子从东家数起），
#      所以庄家换了、或者我换了座位视角，「编号 ↔ 墩」的对应关系就要重排一次。
func assign_wall_numbers() -> void:
	var ring := wall_ring()
	var wi: int = WALL_RING_WINDS.find(wall_start_side)
	if wi < 0:
		wi = 0                                  # 服务端状态还没到 → 先当东面
	var start: int = ((wall_dealer_ring_slot() + wi) % 4) * int(wall_stacks_per_side)
	var no := 1
	var stack_idx := 1
	for k in range(ring.size()):
		var st: Dictionary = ring[(start + k) % ring.size()]
		st["no"] = stack_idx                 # 墩号（1..68）
		st["tiles"] = [no, no + 1]           # 这墩两张牌的编号（上面那张奇数、下面那张偶数）
		st["face"] = [false, false]          # 每张牌的状态：false = 暗置，true = 明牌
		no += 2
		stack_idx += 1


# ★ 这里原来有 draw_from_wall()：客户端发 op=draw 让服务端「从牌山摸一张」。
#   它没有任何前置校验，谁调都能凭空多摸一张（现场出现过庄家手牌 28 张）。
#   服务端已经删掉 op=draw，摸牌一律走 op=step / op=advance（服务端自己按阶段摸）。


# 第 no 号牌被拿走
func take_wall_tile(no: int) -> void:
	for st in wall_stacks:
		if int(st.get("count", 2)) > 0 and (st.get("tiles", []) as Array).has(no):
			var left: int = int(st["count"]) - 1
			st["count"] = left
			var vis = st.get("vis", null)
			if vis != null and is_instance_valid(vis):
				(vis as Node).call("set_count", left)
			return


# 一墩只剩一张牌时的样子：宽度不变、底边和原来那墩对齐（牌躺在墩的下半部分）
# ★ 现在直接在「那一墩自己的节点」上换图，不再新建/替换节点（节点是场景里的，动画都挂在它身上）
func _swap_wall_stack_single(st: Dictionary) -> void:
	var nd = st.get("vis", null)
	if nd == null or not is_instance_valid(nd):
		return
	_set_stack_face(nd as Node2D, String(st.get("side", "")), 1)


# 编号 no 对应哪张牌（跟服务端牌山序列一一对应）
func wall_tile_id(no: int) -> String:
	if no >= 1 and no <= wall_tile_order.size():
		return String(wall_tile_order[no - 1])
	return ""



var first_stack := 0                     # 从第几墩开始拿（= 骰子点数）
var dora_revealed := 0                   # 已经翻了几张宝牌指示牌
var rinshan_used := 0                    # 已经摸了几张岭上牌
var dora_indicators: Array[String] = []  # 已经翻出来的宝牌指示牌
var ura_indicators: Array[String] = []   # 对应的里宝牌指示牌


# 第 k 墩是哪一墩（按编号找）
func _stack_at_no(k: int) -> Dictionary:
	for st in wall_stacks:
		if int(st.get("no", 0)) == k:
			return st
	return {}


# 一墩的显示尺寸（直接量它自己的 sprite，你换图/换尺寸都不会错）
func _stack_box(st: Dictionary) -> Vector2:
	var vis = st.get("vis", null)
	if vis == null or not is_instance_valid(vis):
		return Vector2.ZERO
	var spr := (vis as Node2D).get_node_or_null("Sprite2D") as Sprite2D
	if spr == null or spr.texture == null:
		return Vector2.ZERO
	return spr.texture.get_size() * spr.scale


# 手牌图（Pai 下 1m/2m… 竖版）
func _pai_tex(tile_id: String) -> Texture2D:
	if pai == null or tile_id == "":
		return null
	var n := pai.get_node_or_null(tile_id) as Node2D
	if n == null:
		return null
	var spr := n.get_node_or_null("Sprite2D") as Sprite2D
	return spr.texture if spr != null else null


# 横版牌图（fPai 下的 h1m 等，来自「横 horizontal」目录）
func _h_tex(tile_id: String) -> Texture2D:
	if fpai == null or tile_id == "":
		return null
	var n := fpai.get_node_or_null(hpai_node_name(tile_id)) as Node2D
	if n == null:
		return null
	var spr := n.get_node_or_null("Sprite2D") as Sprite2D
	return spr.texture if spr != null else null


# ★ 这里原来有 reveal_dora()：客户端发 op=dora 让服务端翻一张宝牌。
#   现场事故：一局里没有任何杠，却翻出了 3 张杠宝牌（宝牌指示牌被提前用光）。
#   现在宝牌只由服务端在「开局 / 每次杠」时翻，客户端只照 state 画。
#   （宝牌指示牌的摆位见下面的 dora indicator 那一段。）


# ── 宝牌指示牌覆盖图（按主视角的四个方向；改这里就能微调）──
#   左右两列（b_04 的墩）用「横 horizontal」的图；上下两排（b_05 的墩）用「竖 翻转」的图。
#   注意：素材库里「横 翻转 / 竖 翻转」目前只是正向图的副本（还没真的翻转），
#         所以这里再补一次运行时翻转；等你把素材真的翻转好了，把 DORA_FLIP_FOLDERS 改成 false。
const DORA_FLIP_FOLDERS := true
const DORA_DIR_HF := "res://Cailiao/mahjong_graphic/PNG 位图/默认风格 default style/横 翻转/"
const DORA_DIR_VF := "res://Cailiao/mahjong_graphic/PNG 位图/默认风格 default style/竖 翻转/"
# 每个方向：dir = h(横 horizontal) / hf(横 翻转) / vf(竖 翻转)；rot = 旋转角度；flip_v = 再上下翻一次
const DORA_VIEW := {
	"left": {"dir": "h", "rot": 180.0, "flip_v": false},     # 左列：横图转 180°
	"right": {"dir": "hf", "rot": 0.0, "flip_v": true},      # 右列：横图上下翻转
	"bottom": {"dir": "vf", "rot": 0.0, "flip_v": true},     # 下排：竖图上下翻转
	"top": {"dir": "vf", "rot": 180.0, "flip_v": true},      # 上排：与下排差 180°
}


func _dora_tex(tile_id: String, dir: String) -> Texture2D:
	if dir == "h":
		return _h_tex(tile_id)
	var nm := dora_file_base(tile_id)        # 数牌 = 1m/0p…；字牌 = 1z…7z
	if dir == "hf":
		var t := art_dora_tex("hf", "h" + nm)       # 节点：宝牌指示牌/横翻/h1m…
		return t if t != null else _h_tex(tile_id)
	if dir == "vf":
		var t2 := art_dora_tex("vf", nm)            # 节点：宝牌指示牌/竖翻/1m…
		return t2 if t2 != null else _pai_tex(tile_id)
	return _pai_tex(tile_id)


# 牌的文件名（不含目录/后缀）：数牌就是自身（1m / 0p / 5s），字牌是 1z…7z（东=1z … 中=7z）
func dora_file_base(tile_id: String) -> String:
	var h := hpai_node_name(tile_id)         # dong→h1z、1m→h1m、0m→h0m
	return h.substr(1) if h.begins_with("h") else tile_id


func _show_indicator(st: Dictionary, tile_id: String) -> void:
	var old = st.get("vis", null)
	if old == null or not is_instance_valid(old) or tile_id == "":
		return
	var side := String(st.get("side", ""))
	var spec: Dictionary = DORA_VIEW.get(side, {"dir": "h", "rot": 180.0, "flip_v": false})
	var view := String(spec.get("dir", "h"))
	var dora_flip: bool = bool(spec.get("flip_v", false)) and DORA_FLIP_FOLDERS
	var rot: float = float(spec.get("rot", 180.0))
	# 优先：复制 Art 节点（你在节点上做的动效会一起带过来）
	var vis := _dup_art(_dora_group(view), _dora_key(tile_id, view))
	var spr := vis.get_node_or_null("Sprite2D") as Sprite2D if vis != null else null
	if spr == null:
		# 回退：老办法（拿贴图现场建一个）
		var tex: Texture2D = _dora_tex(tile_id, view)
		if tex == null:
			push_warning("main.gd: 找不到 %s 的指示牌图" % tile_id)
			return
		vis = Node2D.new()
		spr = Sprite2D.new()
		spr.name = "Sprite2D"
		spr.texture = tex
		spr.centered = true
		vis.add_child(spr)
	var box := _stack_box(st)
	if box.x <= 0.0:
		return
	vis.name = "DoraIndicator"
	var tex_size := spr.texture.get_size()
	# 旋转角度（都按主视角数）：上/下、左列 = 180°；右列不旋转，改用垂直翻转的横牌图

	# 转 90/270 才交换长宽；0/180 是拿原图的「宽」当宽度
	var swaps: bool = is_equal_approx(rot, 90.0) or is_equal_approx(rot, 270.0)
	var base: float = tex_size.y if swaps else tex_size.x
	var s: float = box.x / maxf(base, 1.0)
	var h_new: float = (tex_size.x if swaps else tex_size.y) * s
	spr.scale = Vector2.ONE * s
	spr.flip_v = dora_flip                       # 右列：横牌图“垂直翻转”
	vis.rotation_degrees = rot
	vis.position = (old as Node2D).position + Vector2(0.0, (h_new - box.y) * 0.5)   # 上部对齐
	vis.z_index = (old as Node2D).z_index
	wall_node.add_child(vis)
	wall_sprites.append(vis)


# ★ 这里原来有 draw_rinshan()：客户端发 op=draw&dead=true 自己摸岭上牌。
#   它不看有没有开杠，现场因此白摸走 2 张岭上牌（后面真杠补到错牌）。


# 配牌：一步一步问服务端（发牌顺序、庄家跳牌、什么时候翻宝牌，都在服务端）
#   第一次等 1s，之后每 0.5s 一步；客户端只把服务端发的牌摆上手牌。
func _deal_step() -> void:
	if not dealing or game_phase != PHASE_DEAL:
		return
	var r := srv_request({"op": "deal_step", "seat": my_seat})
	var st = r.get("state")
	if typeof(st) != TYPE_DICTIONARY:
		push_error("main.gd: 配牌失败（服务端不在？），停止配牌。")
		dealing = false
		return
	srv_state = st
	var jumped := false
	var evs = r.get("events", [])
	if typeof(evs) == TYPE_ARRAY:
		for ev in (evs as Array):
			if typeof(ev) != TYPE_DICTIONARY:
				continue
			var who := _deal_who(int(ev.get("seat", 0)))
			var ids: Array = []
			for no in (ev.get("tiles", []) as Array):
				ids.append(wall_tile_id(int(no)))
			_give_tiles(who, ids)
			var jn = ev.get("jump")
			var extra := ""
			if jn != null:
				_give_drawn(who, wall_tile_id(int(jn)))
				jumped = true
				extra = " + 跳牌 %d = %s" % [int(jn), wall_tile_id(int(jn))]
			print("[配牌] %s 拿到 %s%s" % [who, str(ev.get("tiles", [])), extra])
	if jumped:
		sort_hand()                    # 跳牌后立刻理牌
		refresh_hand()
		print("[配牌] 跳牌后理牌 → %s" % str(hand_tiles))
	srv_sync_wall(st)
	# 每一步都按服务端状态重画一次：这样多窗口时，谁推进的配牌都看得到一样的结果
	srv_apply_state(st, evs)
	if bool(st.get("deal_done", false)):
		dealing = false
		game_phase = PHASE_PLAY
		draw_tile()                    # 摸牌按钮取消：配牌一结束就自动开始摸打
		print("[配牌] 配牌结束，我手上 %d 张（台上 %d 张）"
			% [display_tiles().size(), opp_hands.get("B", []).size()])
		return
	get_tree().create_timer(DEAL_STEP_WAIT).timeout.connect(_deal_step)


# 摸到的那张：单独摆在手牌右边（和手牌隔一个空隙）
func _give_drawn(who: String, tile: String) -> void:
	if tile == "":
		return
	if who == "me":
		drawn_tile = tile
		refresh_hand()
		return
	var hand: Array = opp_hands.get(who, [])
	hand.append(tile)
	opp_hands[who] = hand
	opp_drawn[who] = tile
	_show_opp_drawn(who, true)
	_refresh_opp_hand(who)


# 座位号 → 「谁」（按本窗口的座位算：me / D 下家 / C 对家 / B 上家）
func _deal_who(seat: int) -> String:
	return who_of_seat(seat)


# 给某一家添牌（按现在调好的大小/位置，从左边开始往右排）
func _give_tiles(who: String, tiles: Array) -> void:
	if tiles.is_empty():
		return
	if who == "me":
		for t in tiles:
			hand_tiles.append(String(t))
		refresh_hand()
		return
	var hand: Array = opp_hands.get(who, [])
	for t in tiles:
		hand.append(String(t))
	opp_hands[who] = hand
	_refresh_opp_hand(who)

func create_wall() -> void:
	wall_tiles.clear()
	for tile_id in TILE_IDS:
		for i in range(4):
			wall_tiles.append(tile_id)
	# 赤宝牌：每种 5 各把一张换成 0m / 0p / 0s（总数仍是 136 张）
	for red in RED_FIVES:
		var normal: String = RED_FIVES[red]
		var idx := wall_tiles.find(normal)
		if idx >= 0:
			wall_tiles[idx] = red
	wall_tiles.shuffle()


# ══════════════ 对局由服务端驱动：客户端只发动作 + 按服务端状态渲染 ══════════════
#   服务端 op="step"：走一步（该谁摸就摸、该谁打就打），轮到我要做决定时停下
#   服务端 op="act" ：我做一个动作（打牌 / 立直 / 自摸 / 荣和）
var srv_meld_sig := ""               # 副露指纹（组数/种类/张数/牌面；变了才按服务端重画副露）
const MELD_SIG_RESET := "#reset"     # 「强制重画」的哨兵（空副露的指纹是空串，不能拿空串当哨兵）
var srv_busy := false                # 正在一步步推进（防止重复触发）


# 让服务端走一步；有人动过就继续走（带节奏），轮到我了就停下
# 摸牌前的几个询问：**按我这家的卡序遍历**（主战卡先、协战卡后），
# 不再写死「降神→炸裂→海神→间合→未来」这个顺序。
const PRE_DRAW_GATES := {
	7: "_oracle_gate_before_draw",       # Card07 S1 降神
	9: "_card09_gate_before_draw",       # Card09 间合（守 / 攻 同一张卡）
	12: "_hs_gate_before_draw",          # Card12 S1 海神（借牌面板还开着就先别摸）
	14: "_zl_gate_before_draw",          # Card14 S2 炸裂
	24: "_future_gate_before_draw",      # Card24 S2 未来
	26: "_c26_gate_before_draw",         # Card26 S2 天梯（排牌山）
	45: "_c45_gate_before_draw",         # Card45 S1 神境（手牌+牌河挑 13 张）
}


func srv_my_cards() -> Array:
	var cs = srv_state.get("my_cards")
	return cs if typeof(cs) == TYPE_ARRAY else []


func _pre_draw_gate() -> bool:
	var cards := srv_my_cards()
	if cards.is_empty():
		# 还没收到 state（或者没走大厅）→ 退回老顺序，别把技能漏掉
		cards = [7, 14, 12, 9, 24]
	for c in cards:
		var m := String(PRE_DRAW_GATES.get(int(c), ""))
		if m == "":
			continue
		if bool(call(m)):
			return true
	return false


func draw_tile() -> void:
	if game_over or game_phase == PHASE_DEAL or srv_busy:
		return
	if _prompt_blocked():
		return                                   # 有人在等回答：先别推进
	if _pre_draw_gate():
		return                                   # 摸牌前的技能询问（按卡序：主战先）
	srv_busy = true
	_srv_step_once(true)                         # 技能都问完了 → 允许服务端替我摸牌


func _srv_step_once(pre_ok := false) -> void:
	if game_over:
		srv_busy = false
		return
	# pre_ok=true 才允许服务端「替我摸牌」。没问过摸牌前技能就传 false，
	# 服务端会停在那里（wait_pre），不会先摸牌再让我发动技能。
	var r := srv_request({"op": "step", "seat": my_seat, "pre_ok": pre_ok})
	if r.is_empty():
		srv_busy = false
		return
	if bool(r.get("waiting_kangpo", false)):
		_toast("有人正在决定是否看破…")
		srv_busy = false
		return
	var evs = r.get("events", [])
	# 先放锁：srv_apply_state 里万一抛脚本错误（曾经真的发生过），
	# 后面那句 srv_busy = false 就跑不到 → 每帧都 return → 界面永久卡死。
	srv_busy = false
	srv_apply_state(r.get("state"), evs)
	if game_over:
		srv_busy = false
		return
	# 服务端说「先别摸，还有摸牌前技能要问」→ 交给 draw_tile 的闸门（问完会带 pre_ok 回来）
	if typeof(evs) == TYPE_ARRAY:
		for e in (evs as Array):
			if typeof(e) == TYPE_DICTIONARY \
					and String((e as Dictionary).get("event", "")) == "wait_pre":
				srv_busy = false
				draw_tile()
				return
	if typeof(evs) == TYPE_ARRAY and not (evs as Array).is_empty():
		srv_busy = true
		get_tree().create_timer(OPP_DRAW_DELAY).timeout.connect(_srv_step_once)
	else:
		srv_busy = false
		srv_yield_to_me()


# 技能面板发完 op 之后自己把推进链接上（不依赖 srv_act 的尾巴）
func _srv_kick() -> void:
	if game_over or srv_busy:
		return
	if not is_inside_tree():
		return
	srv_busy = true
	get_tree().create_timer(OPP_DRAW_DELAY).timeout.connect(_srv_step_once)


# 我做一个动作，然后把服务端状态画出来，接着继续推进
func srv_act(action: String, extra: Dictionary = {}) -> Dictionary:
	srv_layout_buttons([])               # 先收起按钮，动作做完再按新状态摆
	var req := {"op": "act", "seat": my_seat, "action": action}
	for k in extra:
		req[k] = extra[k]
	var r := srv_request(req)
	if r.is_empty():
		return {}
	if not bool(r.get("ok", false)) and String(r.get("error", "")) != "":
		_toast(String(r.get("error")))            # 服务端拒绝（比如立直后想打手牌）要说一声
	srv_apply_state(r.get("state"), r.get("events"))
	_ensure_result()                     # 服务端说 ended 但没带 result → 重拉一次
	if not game_over and not srv_busy:
		srv_busy = true
		get_tree().create_timer(OPP_DRAW_DELAY).timeout.connect(_srv_step_once)
	return r


# 轮到我了：服务端说能和就和；其余按钮按服务端给的选项显示
# ── 「过」按钮：服务端开出鸣牌窗口时，不鸣就点它（不然会一直等你）──
const PASS_BUTTON_POS := Vector2(680, 20)


# 【死代码·别再改这里】真正被点到的「跳过」按钮是场景里的 UI/Btn/BtnTiaoguo，
# 它接的是 _on_action_button("pass")。下面这个 pass_button 是早期现场 new 的「过」按钮，
# show_pass_button() 已经没有任何调用点 —— 之前修加速时改错地方就是踩了这个。




func _on_pass_pressed() -> void:
	hide_chow_panel()
	# 加速询问里的「跳过」= 不发动这个技能（不是普通鸣牌的跳过）
	if not srv_c29s1_ask().is_empty():
		_c29s1_op("c29s1_skip")
		return
	srv_act("pass")


# ────────── 操作按钮（图片样式；位置/大小/贴图都取自场景里 UI 下对应的节点）──────────
#   种类 -> 场景里那个节点名（只认名字，大小写不敏感）：
#     自摸 Zimo / 荣和 Rong / 立直 Lizhi / 跳过 Tiaoguo / 碰 Peng2(Peng) / 吃 Chi / 杠 Gang
#   ★ 这些节点只当「模板」：一律隐藏（不隐藏它们就会一直当静态图挂在屏幕上）
#   ★ 按钮大小 = 模板贴图尺寸 × 模板节点的缩放（你在场景里怎么缩的就怎么显示）
#   槽位（1..5 号位）：一号位 Gang、二号位 Zimo、三号位 Rong、四号位 Lizhi、五号位 Peng2
#   出现优先级（高→低）：自摸/荣和 > 立直 > 跳过 > 碰 > 吃 > 杠
const BTN_PRIORITY := ["tsumo", "ron", "riichi", "pass", "pon", "chi", "kan"]
# 每个动作对应场景里的一个按钮节点（Main/UI/Btn/BtnXXX），一个节点搞定显示 + 交互 + 动画
const BTN_KIND_TO_NODE := {
	"tsumo": "BtnZimo",
	"ron": "BtnRong",
	"riichi": "BtnLizhi",
	"pass": "BtnTiaoguo",
	"pon": "BtnPeng",
	"chi": "BtnChi",
	"kan": "BtnGang",
}
# 5 个槽位：按钮按优先级从高到低依次落到 1..5 号位（中心点，取自旧参考节点 Gang/Zimo/Rong/Lizhi/Peng2）
const BTN_SLOT_CENTERS: Array[Vector2] = [
	Vector2(1325.0, 811.0),   # 1 号位
	Vector2(1069.0, 807.0),   # 2 号位
	Vector2(818.0, 808.0),    # 3 号位
	Vector2(1318.0, 625.0),   # 4 号位
	Vector2(1066.0, 627.0),   # 5 号位
]

var btn_nodes := {}        # kind -> TextureButton（场景里直接用的节点，不再复制）


func _setup_action_buttons() -> void:
	# Control 的点击命中按「树的先后顺序」判定（不按 z_index）：
	# 人物卡挂在 Main/Identity，是最靠后的分枝，会抢走按钮的点击。
	# 把整个 UI 分枝挪到最后 → 按钮画在卡上面，点重叠区域也归按钮。
	var ui_root := get_node_or_null("UI")
	if ui_root != null and ui_root.get_index() != get_child_count() - 1:
		move_child(ui_root, get_child_count() - 1)
	var _bn0 := get_node_or_null("UI/Btn") as Node2D
	if _bn0 != null:
		_bn0.z_index = 120                 # 按钮那一枝整体压在最上面（人物卡在 CanvasLayer=20，挡不住）
	btn_nodes.clear()
	for kind in BTN_KIND_TO_NODE:
		var b := get_node_or_null("UI/Btn/" + String(BTN_KIND_TO_NODE[kind])) as TextureButton
		if b == null:
			push_warning("main.gd: 找不到按钮节点 UI/Btn/" + String(BTN_KIND_TO_NODE[kind]))
			continue
		b.z_index = 30
		b.visible = false
		if kind == "riichi":
			b.set("vanish_on_press", false)   # 立直按钮按下后留在原地，方便再点一次取消
		b.pressed.connect(_on_action_button.bind(kind))
		btn_nodes[kind] = b


func _on_action_button(kind: String) -> void:
	if game_over:
		return
	if kind == "riichi":
		_toggle_riichi_selecting()
		return
	if kind == "tsumo" and has_action("skill_tsumo") and not has_action("tsumo"):
		srv_act("skill_tsumo")                       # 技能发的自摸
		return
	if kind == "kan":                                # 明杠 / 加杠 / 暗杠，交给服务端根据 legal 选择
		for a in ["minkan", "kakan", "ankan"]:
			if a == "ankan" or a == "kakan":
				# 暗杠 / 加杠，服务端需要知道是哪一张牌，从 legal 里取第一张
				var t := srv_legal_tile(srv_state, a)
				if t != "":
					srv_act(a, {"tile": t})
					return
			elif has_action(a):
				srv_act(a)
				return
		return
	if kind == "chi":
		_chow_choose()                               # 吃：有几种搭子就让玩家挑
		return
	# 加速（29S1）询问里的「跳过」= 技能 op（不是普通鸣牌的 pass）
	if kind == "pass" and not srv_c29s1_ask().is_empty():
		_c29s1_op("c29s1_skip")
		return
	srv_act(kind)                                    # tsumo / ron / pon / minkan / pass


# ── 人物卡技能 ────────────────────────────────────────────────────────
# 单击人物卡 → 技能图标出现（identity_card.gd）；单击技能图标 → 这里发请求。
# 服务端只回「能不能发动、要打哪张、发哪张、凑成什么番」，
# 真正的结算在「自摸」按钮被按下时走 skill_tsumo。
# ── 分数显示：直接用场景里的 4 个 Label（用户自己摆好位置/字号）──────────
#   对应关系（按风盘四条深蓝框的方位）：
#     0 下（我）  → 风盘/Label
#     1 右（下家）→ 风盘/Label2
#     2 上（对家）→ 风盘/Label3
#     3 左（上家）→ 风盘/Label4
#   ★ 这四个 Label 是「风盘」节点的子节点（场景 Main/UI/风盘/Label…）：
#     位置 / 旋转 / 缩放 / 字号 / 颜色全部来自场景，代码只写数字，一个像素都不动。
#     所以编辑器里摆成什么样，F5 进游戏就是什么样（fengpan_scale_ratio 只会整体等比缩放）。
const SCORE_LABELS := ["UI/风盘/Label", "UI/风盘/Label2",
					   "UI/风盘/Label3", "UI/风盘/Label4"]
const SCORE_START_POINTS := 25000
# 场景里 Label 的模板文本（保留前导空格，这样数字在框里的横向位置和编辑器里完全一致）
const SCORE_TEXT_TPL := "       35000"
# 想再微调某个方向的数字：运行时调 Main.score_label_tune(i, Vector2(dx, dy))，单位是风盘局部像素
var score_nudge: Array = [Vector2.ZERO, Vector2.ZERO, Vector2.ZERO, Vector2.ZERO]
var _score_last: Array = [-1, -1, -1, -1]
var _score_base_pos: Array = [null, null, null, null]


# 风盘「本体（浅蓝盘面）」在世界坐标里的矩形 —— 按可见那张 sprite 的实际绘制矩形算，
# 所以风盘换图 / 改 fengpan_scale_ratio / 缩放窗口都跟着走。
func _fengpan_wind_sprite() -> Sprite2D:
	if fengpan == null:
		return null
	for c in fengpan.get_children():
		if not (c is Sprite2D):
			continue
		var sp := c as Sprite2D
		if sp.texture == null:
			continue
		if _fengpan_is_wind_img(String(sp.name)):
			return sp
	return null


func _fengpan_is_wind_img(nm: String) -> bool:
	if nm.length() != 2:
		return false
	return FENGPAN_IMG_PRE.has(nm.substr(0, 1)) and FENGPAN_IMG_SUF.has(nm.substr(1, 1))


func _fengpan_body_rect() -> Rect2:
	if fengpan == null:
		return Rect2()
	var sp := _fengpan_wind_sprite()
	if sp == null:
		return Rect2()
	var r := sp.get_rect()                    # 整张图在本节点里的矩形（已含 offset / 居中）
	var xf := sp.get_global_transform()
	var inv := get_global_transform().affine_inverse()     # Main 是 Control，没有 to_local()
	var a: Vector2 = inv * (xf * (r.position + FENGPAN_TEX_RECT.position))
	var b: Vector2 = inv * (xf * (r.position + FENGPAN_TEX_RECT.position
			+ FENGPAN_TEX_RECT.size))
	return Rect2(a, b - a)


# 数字文本：保留模板里的前导空格（scene 里摆好的横向位置），只换数字
func _score_fmt(val: int) -> String:
	var tpl := SCORE_TEXT_TPL
	var i := 0
	while i < tpl.length() and tpl.unicode_at(i) == 32:
		i += 1
	return tpl.substr(0, i) + str(val)


# 位置微调（单位：风盘局部像素）。不调 = 完全等于编辑器里的位置。
func _score_label_place(i: int, lb: Label) -> void:
	if _score_base_pos[i] == null:
		return
	var nudge: Vector2 = score_nudge[i] as Vector2
	lb.position = (_score_base_pos[i] as Vector2) + nudge


# 把四家的点数写进那四个 Label（找不到节点就跳过，不报错）
func _score_label_sync(st: Dictionary) -> void:
	var sc = st.get("scores")
	var by_seat := {}
	if typeof(sc) == TYPE_ARRAY:
		for it in (sc as Array):
			if typeof(it) != TYPE_DICTIONARY:
				continue
			var d := it as Dictionary
			by_seat[int(d.get("seat", -1))] = int(d.get("score", 0))
	elif typeof(sc) == TYPE_DICTIONARY:
		for k in (sc as Dictionary).keys():
			by_seat[int(k)] = int((sc as Dictionary)[k])
	else:
		return                              # 还没有分数（刚进游戏）→ 保持原样
	_update_fengpan_image()               # 换风盘图（场风 + 自家风）
	_fengpan_leaf_sync(int(st.get("honba", 0)))
	for i in range(4):
		var lb := get_node_or_null(String(SCORE_LABELS[i])) as Label
		if lb == null:
			continue
		var val := int(by_seat.get((my_seat + i) % 4, 0))
		if _score_base_pos[i] == null:
			_score_base_pos[i] = lb.position
		if lb.position != (_score_base_pos[i] as Vector2) + (score_nudge[i] as Vector2):
			_score_label_place(i, lb)
		lb.text = _score_fmt(val)
		if _score_last[i] >= 0 and _score_last[i] != val:
			_score_label_flash(lb)
		_score_last[i] = val


# 点数变化时轻轻闪一下，不闪瞎眼
func _score_label_flash(lb: Label) -> void:
	var old = lb.get_meta("flash_tw", null)
	if old is Tween and (old as Tween).is_valid():
		(old as Tween).kill()
	lb.modulate = Color(1.45, 1.30, 0.92, 1.0)
	var tw := lb.create_tween()
	tw.tween_property(lb, "modulate", Color(1, 1, 1, 1), 0.45) \
			.set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_OUT)
	lb.set_meta("flash_tw", tw)


# ── 位置调整接口 ──────────────────────────────────────────────────────────
# 方向 i：0=下（自己）1=右 2=上 3=左。nudge 单位是风盘局部像素（正数=右/下），
# 是在场景位置上的**追加偏移**，默认 0 = 和编辑器里一模一样。
#   Main.score_label_tune(0, Vector2(0, -6))
func score_label_tune(i: int, nudge: Vector2) -> void:
	if i < 0 or i > 3:
		return
	score_nudge[i] = nudge
	var lb := get_node_or_null(String(SCORE_LABELS[i])) as Label
	if lb == null:
		return
	if _score_base_pos[i] == null:
		_score_base_pos[i] = lb.position
	_score_label_place(i, lb)


# 校准用：打印四个分数框的实际屏幕矩形（Main.score_label_where()）
func score_label_where() -> String:
	var out: Array = []
	for i in range(4):
		var lb := get_node_or_null(String(SCORE_LABELS[i])) as Label
		if lb == null:
			out.append("%d: 无" % i)
			continue
		var r := lb.get_global_rect()
		out.append("%d: x=%.0f y=%.0f w=%.0f h=%.0f rot=%.0f" % [
			i, r.position.x, r.position.y, r.size.x, r.size.y,
			rad_to_deg(lb.rotation)])
	var s := " | ".join(out)
	print("分数框 ", s)
	return s


func _setup_identity_skills() -> void:
	var idn := get_node_or_null("Identity")
	if idn == null or not idn.has_signal("skill_pressed"):
		return
	if not idn.is_connected("skill_pressed", _on_identity_skill):
		idn.connect("skill_pressed", _on_identity_skill)
	if idn.has_signal("wind_picked") and not idn.is_connected("wind_picked", _on_identity_wind):
		idn.connect("wind_picked", _on_identity_wind)
	if idn.has_signal("skills_toggled") and not idn.is_connected("skills_toggled", _on_identity_skills_toggled):
		idn.connect("skills_toggled", _on_identity_skills_toggled)
	if idn.has_signal("card_long_pressed") \
			and not idn.is_connected("card_long_pressed", _on_identity_long_press):
		idn.connect("card_long_pressed", _on_identity_long_press)


# ── 技能「反悔」：还在选牌时再点一次同一个技能图标 = 取消这次发动 ──────
#   画板 / 换牌 / 压制 / 避开：服务端没有中间状态，把界面收掉就行
#   风神 / 南风 / 自风 / 策略：要叫服务端把中间状态也撤掉（op=skill_cancel）
# 现在有没有「技能给的和牌」等着按自摸（43S1 NO MISS / 46S1 恶听）→ 返回卡号，没有 = 0
func _win_pending_card() -> int:
	var wp = srv_state.get("win_pending")
	if typeof(wp) != TYPE_DICTIONARY:
		return 0
	return int((wp as Dictionary).get("card", 0))



func _skill_cancel_if_busy(card_no: int, index: int) -> bool:
	var c := int(card_no)
	var i := int(index)
	if c == 1 and i == 1 and skill2_card != 0:
		_skill2_close(true)
		_toast("已取消「避开」")
		return true
	if c == 2 and i == 0 and board_ui != null:
		_board_close()
		_toast("已取消「画板」")
		return true
	if c == 2 and i == 1 and swap_panel.active:
		_swap_close()
		_toast("已取消「换牌」")
		return true
	if c == 3 and i == 1 and press_panel.active:
		_press_close()
		_toast("已取消「压制」")
		return true
	if c == 24 and i == 0 and c24_panel.active:
		c24_panel.close()
		_toast("已取消「一发」")
		return true
	if c == 24 and i == 1 and future_active:
		_toast("未来：已经发动了，不能跳过 —— 把 5 张排好点「确认」")
		return true
	if c == 4 and i == 0 and flow_active:
		_flow_cancel()
		return true
	if c == 4 and i == 1 and wind_active:
		_wind_cancel()
		return true
	if c == 5 and i == 0:
		if c05_hide_active:
			_c05_hide_cancel()
			return true
		if c05_active:
			_c05_close(true)                    # 里面会发 op=card05_cancel
			_toast("已取消「策略」换牌")
			return true
	if c == 6 and i == 0 and sw_stage != "":
		_sw_cancel()
		return true
	if c == 11 and i == 1 and c11s2_active:
		_card11s2_close()
		_toast("已取消「快手」")
		return true
	if c == 11 and i == 0 and c11_active:
		_card11_close()
		_toast("已取消「魔术」（还没有和服务端确认，不用回滚）")
		return true
	if c == 30 and i == 0 and c30_panel.active and c30_panel.mode == "arm":
		c30_panel.close()
		c30_key = ""
		_toast("向听：已收起（还没发动，不用回滚）")
		return true
	if c == 22 and i == 1 and sf_active and sf_mode == "youyin":
		_sf_close()                        # 友引段2 是主动技能：再点一次 = 收起
		_toast("已收起「友引」换牌")
		return true
	# NO MISS / 恶听：面板还开着 → 收起；已经换完/切完、等着按自摸 → 叫服务端撤销
	if c == 43 and i == 0 and c43_panel.active:
		c43_panel.close()
		_toast("已取消「NO MISS」（还没和服务端确认，牌没动）")
		return true
	if c == 46 and i == 0 and c46_panel.active:
		c46_panel.close()
		_toast("已取消「恶听」（还没切牌）")
		return true
	if c == 43 and i == 0 and _win_pending_card() == 43:
		if _srv_skill_cancel("c43s1"):
			_toast("已取消「NO MISS」：这次不和（换过的牌保留，接着打牌）")
		return true
	if c == 46 and i == 0 and _win_pending_card() == 46:
		if _srv_skill_cancel("c46s1"):
			_toast("已取消「恶听」：这次不和，轮到下家")
		return true

	return false


# 叫服务端撤掉正在进行的技能状态；失败只提示，界面不硬关（还能继续选）
func _srv_skill_cancel(what: String) -> bool:
	var r := srv_request({"op": "skill_cancel", "seat": my_seat, "what": what})
	if r.is_empty():
		_toast(_srv_err("取消技能失败：服务端没有回应"))
		return false
	srv_apply_state(r.get("state"), r.get("events"))
	return true


func _flow_cancel() -> void:
	if not _srv_skill_cancel("fengshen"):
		return
	_flow_close()
	_toast("已取消「风神」：已经换出去/换进来的牌不会退回去")


func _wind_cancel() -> void:
	if not _srv_skill_cancel("self_wind"):
		return
	_wind_close()
	_toast("已取消「自风」交换")


func _sw_cancel() -> void:
	if not _srv_skill_cancel("south_wind"):
		return
	_sw_close()
	_toast("已取消「南风」")


func _c05_hide_cancel() -> void:
	if not _srv_skill_cancel("card05_hide"):
		return
	_c05_hide_close()
	_toast("已取消盖牌（这次手牌会被看到）")


# ── Card07 Skill1「降神」──────────────────────────────────────────────
#   配牌时发动：掷一次骰子定花色（2/5/8/11=万，3/6/9/12=筒，4/7/10=条），本局固定，
#   发动后默认「打开」（技能图标套红框）。打开时每次自己摸牌前弹 9 张同花色的牌：
#   选一张 → 别家有这张的，按下家→对家→上家 跟「牌山接下来第 1/2/3 张」交换。
#   再点一次技能图标 = 关掉 / 重新打开。
var oracle_ui: Control = null
var oracle_pick := ""
var oracle_start_btn: TextureButton = null
var hand_show := HandShow.new()           # 通用手牌展示（翻面 / 贴明牌）
var oracle_frames := {}                  # kind -> 彩框 Sprite2D
var oracle_skip_next := false            # 选完/跳过之后放行这一次摸牌


func _oracle_on_clicked() -> void:
	if typeof(srv_state.get("oracle")) == TYPE_DICTIONARY:
		_oracle_toggle()                     # 已经掷过 → 开 / 关
		return
	if String(srv_state.get("phase", "")) != "deal_skill":
		_toast("「降神」只能在配牌阶段发动（掷一次骰子定花色）")
		return
	_oracle_activate()


func _oracle_activate() -> void:
	if not is_inside_tree():
		return
	var r := srv_request({"op": "deal_skill", "seat": my_seat,
		"action": "use", "card": 7, "skill": 1})
	if r.is_empty():
		_toast(_srv_err("「降神」发动失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return
	var dr: Dictionary = r.get("deal_skill", {})
	if not bool(dr.get("armed", false)):
		_toast(String(dr.get("reason", "现在不能发动「降神」")))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	var idn := get_node_or_null("Identity")
	if idn != null and idn.has_method("collapse_skills"):
		idn.call("collapse_skills", 7)
	var o: Dictionary = dr.get("oracle", {})
	_toast("「降神」：掷出 %d 点 → 本局花色【%s】"
		% [int(dr.get("dice", 0)), String(o.get("suit_cn", ""))])


# Card07 Skill2「恶灵」：被动。发动过「降神」之后，本局只能门清自摸和。
func _evil_tip() -> void:
	if bool(srv_state.get("oracle_lock", false)):
		_toast("「恶灵」正在生效：发动过降神 → 这一局只能门清自摸和（不能荣和、不能有副露）")
	else:
		_toast("「恶灵」不用发动：一旦发动过「降神」，这一局就只能门清自摸和")


func _oracle_toggle() -> void:
	var r := srv_request({"op": "oracle_toggle", "seat": my_seat})
	if r.is_empty():
		_toast(_srv_err("「降神」开关失败：服务端没有回应"))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	var d: Dictionary = r.get("oracle", {})
	var o: Dictionary = d.get("oracle", {})
	if bool(o.get("on", false)):
		_toast("「降神」已打开：每次摸牌前可以指定一张【%s】" % String(o.get("suit_cn", "")))
	else:
		_toast("「降神」已关闭（再点一次可以重新打开）")


# 摸牌前拦一道：降神开着就先弹选牌界面。返回 true = 这次别摸牌。
func _srv_kangpo_wait() -> bool:
	return bool(srv_state.get("kangpo_wait", false))


# 统一询问锁：只要有人在等回答（看破/海神/深山/友引/破发），谁都不能摸/打/推进。
# 其他人「什么都看不到」，就是停住。
func _prompt_blocked() -> bool:
	var pr = srv_state.get("prompt")
	return typeof(pr) == TYPE_DICTIONARY and not (pr as Dictionary).is_empty()


# 立直后手牌锁定：会改手牌的技能一律不再询问（降神只换牌山顺序，不算）。
# 宣言牌还没打出去的「立直选择中」也算锁定。
func _hand_locked() -> bool:
	return riichi_declared or riichi_selecting


func _oracle_gate_before_draw() -> bool:
	if oracle_skip_next:
		oracle_skip_next = false
		return false
	if _srv_kangpo_wait():
		return false                    # 有人正在决定是否看破：先别开面板
	if oracle_ui != null:
		return true                         # 已经弹出来了，别重复弹
	var st := srv_state
	var o = st.get("oracle")
	if typeof(o) != TYPE_DICTIONARY:
		return false
	if not bool((o as Dictionary).get("on", false)):
		return false
	if String(st.get("phase", "")) != "draw" or int(st.get("turn", -1)) != my_seat:
		return false
	_oracle_open(String((o as Dictionary).get("suit", "m")))
	return true


func _oracle_open(suit: String) -> void:
	if oracle_ui != null:
		return
	oracle_pick = ""
	oracle_frames.clear()
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	oracle_ui = Control.new()
	oracle_ui.name = "OracleUI"
	oracle_ui.z_index = 262
	host.add_child(oracle_ui)
	oracle_ui.position = Vector2.ZERO

	var bg := ColorRect.new()
	bg.color = Color(0.02, 0.03, 0.06, 0.8)
	bg.size = vp
	bg.mouse_filter = Control.MOUSE_FILTER_STOP
	oracle_ui.add_child(bg)

	var cn := String({"m": "万", "p": "筒", "s": "条"}.get(suit, "万"))
	var title := Label.new()
	title.text = "降神：摸牌前指定一张【%s】（单击选中 / 再点取消）" % cn
	title.add_theme_font_size_override("font_size", 30)
	title.add_theme_color_override("font_color", Color(1.0, 0.96, 0.8))
	title.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	title.add_theme_constant_override("outline_size", 6)
	title.position = Vector2(0, vp.y * 0.5 - SW_TILE_H * 0.5 - 90.0)
	title.size = Vector2(vp.x, 40)
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	oracle_ui.add_child(title)

	var gap := 10.0
	var total := 9.0 * SW_TILE_W + 8.0 * gap
	var x0 := (vp.x - total) * 0.5
	var y0 := vp.y * 0.5 - SW_TILE_H * 0.5
	for i in range(9):
		var kind := "%d%s" % [i + 1, suit]
		var b := TextureButton.new()
		b.name = "K%d" % i
		b.texture_normal = load(TileBank.VERT_DIR + TileBank.face_file(kind) + ".png")
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		b.position = Vector2(x0 + float(i) * (SW_TILE_W + gap), y0)
		b.size = Vector2(SW_TILE_W, SW_TILE_H)
		b.pressed.connect(_oracle_pick_kind.bind(kind))
		oracle_ui.add_child(b)
		oracle_frames[kind] = SelFrame.attach(b, b.size)     # 选中：彩框图

	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	oracle_start_btn = TextureButton.new()
	oracle_start_btn.name = "OracleStart"
	oracle_start_btn.texture_normal = tex
	oracle_start_btn.ignore_texture_size = true
	oracle_start_btn.stretch_mode = TextureButton.STRETCH_SCALE
	oracle_start_btn.focus_mode = Control.FOCUS_NONE
	oracle_start_btn.size = Vector2(bw, bh)
	oracle_start_btn.position = prompt_btn_pos(bw, bh)
	oracle_start_btn.visible = true            # 常驻：没选牌时按它就是「跳过这次」
	oracle_start_btn.pressed.connect(_oracle_start)
	oracle_ui.add_child(oracle_start_btn)




func _oracle_pick_kind(kind: String) -> void:
	oracle_pick = "" if oracle_pick == kind else kind
	for k in oracle_frames:
		var f := oracle_frames[k] as Node2D
		if f != null and is_instance_valid(f):
			f.visible = String(k) == oracle_pick
	# ★ 样板：没选牌 = 跳过（tiaoguo），选了牌 = 确认（queren）
	if oracle_start_btn != null and is_instance_valid(oracle_start_btn):
		set_start_btn_kind(oracle_start_btn, oracle_pick != "")
		oracle_start_btn.visible = true


# 「开始」按钮：选了牌 = 确认交换；没选牌 = 跳过这次（看破询问也是它）
func _oracle_start() -> void:
	if oracle_pick == "":
		_oracle_skip()
		return
	_oracle_confirm()


func _oracle_confirm() -> void:
	if oracle_pick == "":
		return
	var tile := oracle_pick
	_oracle_close()
	oracle_skip_next = true            # 这次已经选过了：别再弹（draw_tile 会消耗掉）
	srv_busy = true                    # 挡住 srv_apply_state 里的自动摸牌，下面自己摸
	var r := srv_request({"op": "oracle_pick", "seat": my_seat, "tile": tile})
	if r.is_empty():
		_toast(_srv_err("「降神」指定失败：服务端没有回应"))
	elif bool(r.get("need_kangpo", false)):
		# 看破：对方还没决定 → 这次交换先不结算，也别摸牌（放行后服务端会照原样执行）
		_toast("「降神」已确认：等对方决定是否看破…")
		srv_busy = false
		return
	else:
		srv_apply_state(r.get("state"), r.get("events"))
		var d: Dictionary = r.get("oracle", {})
		var sw: Array = d.get("swaps", [])
		if (sw as Array).is_empty():
			_toast("「降神」：没有别人拿着 %s" % tile)
		else:
			var who := []
			for s in sw:
				if typeof(s) == TYPE_DICTIONARY:
					who.append("%s→%s" % [
						_rel_seat_name(int((s as Dictionary).get("seat", -1))),
						String((s as Dictionary).get("with", ""))])
			_toast("「降神」：%s" % "、".join(who))
	srv_busy = false
	draw_tile()


func _oracle_skip() -> void:
	_oracle_close()
	oracle_skip_next = true
	draw_tile()


func _oracle_close() -> void:
	oracle_pick = ""
	oracle_frames.clear()
	if oracle_start_btn != null and is_instance_valid(oracle_start_btn):
		oracle_start_btn.visible = false
	if oracle_ui != null and is_instance_valid(oracle_ui):
		oracle_ui.queue_free()
	oracle_ui = null
	oracle_start_btn = null


# ── Card08 Skill1「决斗」──────────────────────────────────────────────
#   第六巡后摸牌完发动：点技能 → 东南西北选一家 → 跟他决斗。
#   之后只有「我 + 对手」能正常摸切；另外两家只能摸切、暗置打出（谁都不能鸣/荣），
#   而且看不到自己摸进的牌。非决斗家 副露/立直/用技能 → 对手换成他那家；我立直 → 决斗取消。
var duel_selecting := false              # 正在选东南西北


# Card08 Skill2「决斗标记」：被动。参与过决斗的人拿标记（不清除）；
# 别人和牌 → 我计数器 +标记数；我和牌 → 额外 +计数器 番。
func _duel_mark_tip() -> void:
	var n := int(srv_state.get("duel_counter", 0))
	var m := int(srv_state.get("duel_marks", 0))
	var mine := "（我也有标记）" if bool(srv_state.get("duel_marked", false)) else ""
	_toast("「决斗标记」：场上 %d 个标记%s，计数器 %d —— 别人和牌 +%d，我和牌 +%d 番"
		% [m, mine, n, m, n])


func _duel_on_clicked() -> void:
	var d = srv_state.get("duel")
	if typeof(d) == TYPE_DICTIONARY:
		var tg := int((d as Dictionary).get("target", -1))
		if bool((d as Dictionary).get("mine", false)):
			_toast("决斗中：对手是%s" % _rel_seat_name(tg))
		else:
			_toast("你被卷进了决斗：只能摸切（暗置打出），也看不到自己摸的牌")
		return
	if not bool(srv_state.get("deal_done", false)):
		return
	if not bool(srv_state.get("duel_can", false)):
		_toast("「决斗」要第六巡之后、自己摸完牌才能发动")
		return
	duel_selecting = true
	_seat_pick_begin("duel", "决斗：选一个对手")


func _duel_start(target: int) -> void:
	duel_selecting = false
	_seat_pick_end()
	if int(target) == my_seat:
		_toast("不能跟自己决斗")
		return
	var r := srv_request({"op": "duel_start", "seat": my_seat, "target": int(target)})
	if r.is_empty():
		_toast(_srv_err("「决斗」发动失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return

	srv_apply_state(r.get("state"), r.get("events"))
	var idn := get_node_or_null("Identity")
	if idn != null and idn.has_method("collapse_skills"):
		idn.call("collapse_skills", 8)
	_toast("「决斗」开始：对手是%s —— 另外两家只能摸切（暗置）" % _rel_seat_name(int(target)))


# 被决斗限制的那家：摸完牌自动打出去（他看不到自己摸的牌，也没得选）
# 决斗：**不自动打牌**（用户口径）——玩家自己点刚摸到的那张；
# 技能 / 副露 / 立直照常可以发动。


# ── Card09 S1 / S2：摸牌前用一张手牌换一张牌河明牌 ────────────────────
#   S1 换自己牌河、S2 换别家牌河（都只能挑明置的牌，每 6 张一行、每行只能换一次）。
#   不限次数，但用过 S1 下一次只能 S2、反之亦然；换完照常摸牌。
var c09_active := false
var c09_skill := 1
var c09_seq := -1
var c09_picks: Array[int] = []
var c09_ui: Control = null
var c09_btn: TextureButton = null
var c09_hint_key := ""                   # 摸牌前那句提示，每巡只弹一次


# 这张牌河牌能不能点：Skill1 只有自己的河，Skill2 只有别家的河，暗置的不行
func _card09_ok(river_seat: int, down: bool, seq: int = -1) -> bool:
	if not c09_active or down:
		return false
	if seq >= 0:
		# 服务端算好的「现在真能换」的牌河：换过的行 / 被鸣走 / 暗置 / 立直牌都不在里面
		var own := int_set(srv_state.get("card09_own_seqs", []))
		var oth := int_set(srv_state.get("card09_other_seqs", []))
		if int(c09_skill) == 1:
			return own.has(int(seq))
		if int(c09_skill) == 2:
			return oth.has(int(seq))
		return own.has(int(seq)) or oth.has(int(seq))
	if int(c09_skill) == 0:
		return true                      # 还没定用哪个技能：两边牌河都能点
	return (int(river_seat) == my_seat) == (int(c09_skill) == 1)


# 摸牌前停一下：持 09 号卡的人先决定「换牌河」还是「直接摸」
func _zl_gate_before_draw() -> bool:
	if zl_active:
		return true                      # 面板开着：先别摸牌，等玩家点「开始」
	if _hand_locked():
		return false                     # 立直后手牌锁定：炸裂会换手牌，不问
	if _srv_kangpo_wait():
		return false
	if is_skill_muted(14, 2) or not bool(srv_state.get("zhalie_can", false)):
		return false
	var key := "%d-%d" % [int(srv_state.get("live_left", 0)), int(srv_state.get("turn", 0))]
	if key == zl_ask_key:
		return false
	zl_ask_key = key
	_zl_open_now()
	return true


func _hs_gate_before_draw() -> bool:
	# 海神已经改成「配牌开启 + 别人摸万/红中时被动询问」，不再在摸牌前弹
	if hs_active:
		return true                      # 借牌面板开着：先别摸牌
	return false


func _card09_gate_before_draw() -> bool:
	if c09_active:
		return true                          # 界面开着：先点「开始」
	if _hand_locked():
		return false                         # 立直后手牌锁定：间合会换手牌，不问
	if _srv_kangpo_wait():
		return false                         # 有人正在决定是否看破：先别问
	if is_skill_muted(9, 1) and is_skill_muted(9, 2):
		return false                         # 两个都屏蔽了 → 不再问
	if not bool(srv_state.get("card09_can", false)):
		return false
	# 摸牌前问一次（一巡只问一次）：直接开面板，点「开始」= 跳过这次、照常摸牌
	var key := "%d-%d" % [int(srv_state.get("live_left", 0)),
		int(srv_state.get("turn", 0))]
	if key == c09_hint_key:
		return false
	c09_hint_key = key
	var nxt := int(srv_state.get("card09_next", 0))
	_card09_on_clicked(0 if nxt == 0 else nxt)     # 0 = 两个都没用过：自己挑牌河
	return true


func _card09_on_clicked(skill: int) -> void:
	if _srv_kangpo_wait():
		_toast("有人正在决定是否看破，稍等…")
		return
	if _hand_locked():
		_toast("已经立直了：手牌锁定，不能用间合")
		return
	if c09_active:
		_card09_close()                      # 再点一次 = 取消
		_toast("已取消 09 号卡的换牌")
		return
	if not bool(srv_state.get("card09_can", false)):
		_toast("09 号卡只能在摸牌之前用")
		return
	var nxt := int(srv_state.get("card09_next", 0))
	if int(skill) != 0 and nxt != 0 and nxt != int(skill):
		_toast("上一次用的是 Skill%d，这一次只能用 Skill%d" % [3 - nxt, nxt])
		return
	c09_active = true
	c09_skill = int(skill)
	c09_seq = -1
	_make_c09_ui()
	hand_pick.begin(c09_picks, 1, {"on_change": _refresh_c09_btn})
	_apply_entity_states(srv_state)
	if int(skill) == 0:
		_toast("09：选 1 张手牌 → 点自己牌河（间合守）或别家牌河（间合攻）→ 开始")
	else:
		_toast("09：选 1 张手牌 → 再点%s牌河里的明牌 → 开始"
			% ("自己" if int(skill) == 1 else "别家"))


func _make_c09_ui() -> void:
	if c09_ui != null:
		return
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	c09_ui = Control.new()
	c09_ui.name = "Card09UI"
	c09_ui.z_index = 250
	host.add_child(c09_ui)
	c09_ui.position = Vector2.ZERO
	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	c09_btn = TextureButton.new()
	c09_btn.name = "Card09Start"
	c09_btn.texture_normal = tex
	c09_btn.ignore_texture_size = true
	c09_btn.stretch_mode = TextureButton.STRETCH_SCALE
	c09_btn.focus_mode = Control.FOCUS_NONE
	c09_btn.size = Vector2(bw, bh)
	c09_btn.position = prompt_btn_pos(bw, bh)
	c09_btn.visible = false
	c09_btn.pressed.connect(_card09_confirm)
	c09_ui.add_child(c09_btn)


func _refresh_c09_btn() -> void:
	# 常驻：选了牌+牌河 = 确认交换；什么都没选就点它 = 跳过这次（直接摸牌）
	if c09_btn != null and is_instance_valid(c09_btn):
		c09_btn.visible = c09_active


func _card09_confirm() -> void:
	if not c09_active:
		return
	if not bool(srv_state.get("card09_can", false)):
		_toast("这一手已经过了（间合只能在自己摸牌前发动）")
		_card09_close()
		return
	if c09_picks.is_empty() or c09_seq < 0:
		_card09_close()                      # 没选牌 = 跳过这次
		draw_tile()
		return
	var tiles := display_tiles()
	var idx := int(c09_picks[0])
	if idx < 0 or idx >= tiles.size():
		return
	var hand := String(tiles[idx])
	var sk := c09_skill
	var seq := c09_seq
	_card09_close()
	var r := srv_request({"op": "card09_swap", "seat": my_seat,
		"skill": sk, "hand": hand, "river": seq})
	if r.is_empty():
		# 服务端拒绝：真实原因在 srv_note。别把这一次机会吞掉，让玩家重选。
		_toast(_srv_err("09 换牌失败"))
		c09_hint_key = ""
		draw_tile()
		return
	elif bool(r.get("need_kangpo", false)):
		# 看破：对方还没决定 → 这次先不结算，也别摸牌（放行后服务端照原样执行）
		srv_apply_state(r.get("state"), r.get("events"))
		_toast("间合：已确认，等对方决定是否看破…")
		c09_hint_key = ""            # 万一被看破，这一巡还能再问一次
		return
	else:
		srv_apply_state(r.get("state"), r.get("events"))
		var d: Dictionary = r.get("card09", {})
		_toast("09 换牌：用 %s 换到 %s（下一次只能用 Skill%d）"
			% [hand, String(d.get("got", "")), int(d.get("next", 1))])
	draw_tile()                              # 技能结算完，照常摸牌


func _card09_close() -> void:
	c09_active = false
	c09_seq = -1
	hand_pick.end()
	if c09_btn != null and is_instance_valid(c09_btn):
		c09_btn.visible = false
	if c09_ui != null and is_instance_valid(c09_ui):
		c09_ui.queue_free()
	c09_ui = null
	c09_btn = null
	_apply_entity_states(srv_state)


# ── Card10 Skill1「鬼门」──────────────────────────────────────────────
#   全场彩框选牌，两种形状：
#     6 张 = 3 张手牌 + 牌河 3 张东/北（甲：换进手里）
#     7/8 张 = 我的一组副露（含杠）+ 别家东/北的刻子/杠（乙：整组交换）
#   东、北各能换一次。副露直接在牌桌上点（整组选中），不再弹黑色按钮。
var c10_active := false
var c10_picks: Array[int] = []           # 选中的手牌（display_tiles 下标）
var c10_rivers := {}                     # 选中的牌河 seq 集合
var c10_ui: Control = null
var c10_btn: TextureButton = null
var c10_groups := {}                     # "seat:group" -> {seat, group, meld_id, kind, head, ids}
var c10_sel: Array = []                  # 选中的副露组 key（最多 2 组）
var river_kind_by_seq := {}              # 牌河 seq -> 牌种（鬼门要知道选的是东还是北）
var river_seat_by_seq := {}              # 牌河 seq -> 座位（间合：判断自家 / 别家）


# 把服务端下发的数字数组（JSON 里是 float）变成 int 字典，方便 O(1) 判断。
# 注意：GDScript 里 `200 in [200.0]` 是 false（Array.has 严格比较），不能直接用 in。
func int_set(arr) -> Dictionary:
	var d := {}
	if typeof(arr) == TYPE_ARRAY:
		for v in (arr as Array):
			d[int(v)] = true
	return d


func _c10_on_clicked() -> void:
	if c10_active:
		_c10_close()
		_toast("已取消「鬼门」")
		return
	if not bool(srv_state.get("card10_can", false)):
		_toast("「鬼门」要摸牌之后、打牌之前才能发动")
		return
	var used: Array = srv_state.get("card10_used", [])
	if (used as Array).has("dong") and (used as Array).has("bei"):
		_toast("「鬼门」这一局东、北都换过了")
		return
	_c10_open()


func _c10_make_ui() -> void:
	if c10_ui != null:
		return
	var host: Node = get_parent()
	if host == null:
		host = self
	c10_ui = Control.new()
	c10_ui.name = "Card10UI"
	c10_ui.z_index = 255
	host.add_child(c10_ui)
	c10_ui.position = Vector2.ZERO


func _c10_make_start_btn(y: float) -> void:
	if c10_btn != null:
		return
	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	c10_btn = TextureButton.new()
	c10_btn.texture_normal = tex
	c10_btn.ignore_texture_size = true
	c10_btn.stretch_mode = TextureButton.STRETCH_SCALE
	c10_btn.focus_mode = Control.FOCUS_NONE
	c10_btn.size = Vector2(bw, bh)
	c10_btn.position = prompt_btn_pos(bw, bh)
	c10_btn.visible = false
	c10_btn.pressed.connect(_c10_confirm)
	c10_ui.add_child(c10_btn)


# 开场：不弹选择框，直接进场选牌（手牌 / 牌河 / 副露 都能点）
func _c10_open() -> void:
	_c10_close()
	c10_active = true
	_c10_build_groups()
	_c10_make_ui()
	_c10_make_start_btn(get_viewport_rect().size.y - 330.0)
	var vp := get_viewport_rect().size
	var tip := Label.new()
	tip.text = "鬼门：彩框选 6 张（3 手牌 + 牌河 3 张东/北）
或选 7/8 张（我的一组副露 + 别家东/北的刻子/杠）→ 开始"
	tip.add_theme_font_size_override("font_size", 24)
	tip.add_theme_color_override("font_color", Color(1.0, 0.96, 0.8))
	tip.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	tip.add_theme_constant_override("outline_size", 6)
	tip.position = Vector2(0, 26)
	tip.size = Vector2(vp.x, 76)
	tip.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	tip.mouse_filter = Control.MOUSE_FILTER_IGNORE
	c10_ui.add_child(tip)
	hand_pick.begin(c10_picks, 3, {"min": 0, "on_change": _refresh_c10_btn})
	_apply_entity_states(srv_state)
	_c10_refresh_frames()
	_refresh_c10_btn()
	_toast("鬼门：点手牌 / 牌河 / 副露 选或取消（彩框）；再点技能图标取消")


# 把牌桌上的副露整理成「可整组选」的字典
func _c10_build_groups() -> void:
	c10_groups.clear()
	var tiles: Array = srv_state.get("tiles", [])
	for t in tiles:
		if typeof(t) != TYPE_DICTIONARY:
			continue
		var td := t as Dictionary
		if String(td.get("loc", "")) != "meld":
			continue
		var seat := int(td.get("seat", -1))
		var g := int(td.get("group", -1))
		if seat < 0 or g < 0:
			continue
		var key := _c10_group_key(seat, g)
		if not c10_groups.has(key):
			c10_groups[key] = {"seat": seat, "group": g, "meld_id": g,
				"kind": "", "head": "", "ids": []}
		((c10_groups[key] as Dictionary)["ids"] as Array).append(String(td.get("id", "")))
	var all: Array = srv_state.get("all_melds", [])
	for seat2 in range(all.size()):
		for m in (all[seat2] as Array):
			if typeof(m) != TYPE_DICTIONARY:
				continue
			var md := m as Dictionary
			var key2 := _c10_group_key(int(seat2), int(md.get("meld_id", -1)))
			if not c10_groups.has(key2):
				continue
			var rec: Dictionary = c10_groups[key2]
			rec["meld_id"] = int(md.get("meld_id", -1))
			rec["kind"] = String(md.get("kind", ""))
			var tl: Array = md.get("tiles", [])
			if not tl.is_empty():
				rec["head"] = String(tl[0])


func _c10_group_key(seat: int, group: int) -> String:
	return "%d:%d" % [int(seat), int(group)]


# 点任意一张副露牌 = 整组选中/取消
func _c10_toggle_meld(seat: int, group: int) -> void:
	if not c10_active or int(group) < 0:
		return
	var key := _c10_group_key(seat, group)
	if not c10_groups.has(key):
		_c10_build_groups()              # 状态变了（新副露）→ 重扫一遍
	if c10_sel.has(key):
		c10_sel.erase(key)
	else:
		var rec = c10_groups.get(key)
		if typeof(rec) == TYPE_DICTIONARY:
			var kind := String((rec as Dictionary).get("kind", ""))
			var head := String((rec as Dictionary).get("head", ""))
			if int(seat) != my_seat \
					and (kind not in ["pon", "minkan", "ankan", "kakan"]
						or (head != "dong" and head != "bei")):
				_toast("别家只能选东/北的刻子或杠")
				return
		if c10_sel.size() >= 2:
			_toast("鬼门：副露最多选 2 组（再点一次可取消）")
			return
		# 一组自己的 + 一组别家的，各只能一个（否则点「开始」也换不了）
		for k in c10_sel:
			var r0 = c10_groups.get(k)
			if typeof(r0) != TYPE_DICTIONARY:
				continue
			if (int((r0 as Dictionary).get("seat", -1)) == my_seat) \
					== (int(seat) == my_seat):
				_toast("鬼门：要一组自己的 + 一组别家的")
				return
		if not c10_picks.is_empty() or not c10_rivers.is_empty():
			c10_picks.clear()
			c10_rivers.clear()
			hand_pick.sync()             # 甲/乙 不混着选：选了副露就清掉手牌+牌河
		c10_sel.append(key)
	_c10_refresh_frames()
	_refresh_c10_btn()


func _c10_refresh_frames() -> void:
	for key in c10_groups:
		var rec: Dictionary = c10_groups[key]
		var on: bool = c10_sel.has(key)
		for eid in (rec.get("ids", []) as Array):
			var p := tile_bank.piece(String(eid))
			if p != null:
				p.set_selected_frame(on)


# 每次 _apply_entity_states 之后：把副露牌设成「可点 + 按选中态上彩框」
func _c10_apply_meld_hit(meld_entities: Dictionary) -> void:
	for seat in meld_entities:
		var groups: Dictionary = meld_entities[seat]
		for g in groups:
			var on: bool = c10_sel.has(_c10_group_key(int(seat), int(g)))
			for td in (groups[g] as Array):
				var p := tile_bank.piece(String((td as Dictionary).get("id", "")))
				if p == null:
					continue
				p.set_meta("meld_seat", int(seat))
				p.set_meta("meld_group", int(g))
				if not p.meld_clicked.is_connected(_c10_toggle_meld):
					p.meld_clicked.connect(_c10_toggle_meld)
				p.set_meld_clickable(true)
				p.set_selected_frame(on)


func _c10_clear_meld_hit() -> void:
	if tile_bank == null:
		return
	for q in tile_bank.all_pieces():
		var p := q as TilePiece
		if p == null:
			continue
		if int(p.get_meta("meld_group", -1)) < 0:
			continue
		p.set_meld_clickable(false)
		p.set_selected_frame(false)
		p.set_meta("meld_group", -1)


func _c10_river_ok(down: bool, kind: String) -> bool:
	if not c10_active or down or not c10_sel.is_empty():
		return false
	return String(kind) == "dong" or String(kind) == "bei"


func _c10_toggle_river(seq: int) -> void:
	var s := int(seq)
	if c10_rivers.has(s):
		c10_rivers.erase(s)
	elif c10_rivers.size() < 3:
		c10_rivers[s] = true
	else:
		_toast("最多选 3 张牌河牌")
		return
	if not c10_sel.is_empty():
		c10_sel.clear()
		_c10_refresh_frames()
	_refresh_c10_btn()
	_apply_entity_states(srv_state)


func _c10_toggle_hand(index: int) -> void:
	if not c10_sel.is_empty():
		c10_sel.clear()
		_c10_refresh_frames()
	hand_pick.toggle(index)
	_apply_entity_states(srv_state)


func _refresh_c10_btn() -> void:
	if c10_btn == null or not is_instance_valid(c10_btn):
		return
	var hn := c10_picks.size()
	var rn := c10_rivers.size()
	var mn := c10_sel.size()
	c10_btn.visible = c10_active and (
		(mn == 2 and hn == 0 and rn == 0)
		or (mn == 0 and hn == 3 and rn == 3))


func _c10_confirm() -> void:
	if c10_sel.size() == 2:
		_c10_confirm_meld()
		return
	_c10_confirm_hand()


func _c10_confirm_hand() -> void:
	if c10_picks.size() != 3 or c10_rivers.size() != 3:
		_toast("鬼门：甲要 3 张手牌 + 牌河 3 张东/北")
		return
	var tiles := display_tiles()
	var picks: Array = []
	for i in c10_picks:
		if int(i) < 0 or int(i) >= tiles.size():
			return
		picks.append(String(tiles[int(i)]))
	var seqs: Array = []
	for s in c10_rivers.keys():
		seqs.append(int(s))
	var kind := ""
	for s in seqs:
		var kk := String(river_kind_by_seq.get(int(s), ""))
		if kind == "":
			kind = kk
		elif kk != kind:
			_toast("3 张牌河牌要全是东或全是北")
			return
	if kind != "dong" and kind != "bei":
		_toast("牌河里要选 3 张东/北")
		return
	_c10_close()
	var r := srv_request({"op": "card10_hand", "seat": my_seat,
		"kind": kind, "tiles": picks, "rivers": seqs})
	if r.is_empty():
		_toast(_srv_err("「鬼门」换牌失败：服务端没有回应"))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("鬼门：用 %s 换到牌河里的东/北" % "、".join(picks))


func _c10_confirm_meld() -> void:
	var mine := ""
	var theirs := ""
	for k in c10_sel:
		var rec = c10_groups.get(k)
		if typeof(rec) != TYPE_DICTIONARY:
			continue
		if int((rec as Dictionary).get("seat", -1)) == my_seat:
			mine = String(k)
		else:
			theirs = String(k)
	if mine == "" or theirs == "":
		_toast("鬼门：副露要一组自己的 + 一组别家的")
		return
	var mr: Dictionary = c10_groups[mine]
	var tr: Dictionary = c10_groups[theirs]
	var kind := String(tr.get("head", ""))
	if kind != "dong" and kind != "bei":
		_toast("别家只能选东/北的刻子或杠")
		return
	var my_id := int(mr.get("meld_id", -1))
	var tg := int(tr.get("seat", -1))
	var tg_id := int(tr.get("meld_id", -1))
	_c10_close()
	var r := srv_request({"op": "card10_meld", "seat": my_seat, "kind": kind,
		"my_meld": my_id, "target": tg, "their_meld": tg_id})
	if r.is_empty():
		_toast(_srv_err("「鬼门」换副露失败：服务端没有回应"))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("鬼门：换了一组副露（对方可能因此无役）")


func _c10_close() -> void:
	c10_active = false
	c10_picks.clear()
	c10_rivers.clear()
	c10_sel.clear()
	c10_groups.clear()
	hand_pick.end()
	_c10_clear_meld_hit()
	if c10_btn != null and is_instance_valid(c10_btn):
		c10_btn.visible = false
	if c10_ui != null and is_instance_valid(c10_ui):
		c10_ui.queue_free()
	c10_ui = null
	c10_btn = null
	_apply_entity_states(srv_state)


# ── Card10 Skill2「四喜」──────────────────────────────────────────────
#   摸牌后发动：手里/副露有 3 张东 + 3 张北；手里的那几张明置给别人看。
#   之后「第 5 张摸牌」（不含发动这次）视为小四喜自摸；期间不能打东/北。
var c10s2_kinds: Array[String] = []       # 被明置的牌种（用来拦「不能打东/北」）
var c11s2_active := false              # 「快手」界面开着
var c11s2_seq := -1                    # 选中的牌河 seq
var c11s2_sel := {}                    # {"seat":x,"slot":i} 选中的位置
var c11s2_by_seq := {}                 # 牌河 seq -> {"seat","slot"}（渲染时记）
var c11s2_ui: Control = null
var c11s2_btn: TextureButton = null
# 通用换牌面板：深山 / 先负 / 馈赠2 / 友引
var kp_active := false
var kp_ui: Control = null
var kp_key := ""
var rv_nodes: Array = []
var hs_ask_key := ""
var zl_ask_key := ""
var cg_copied := {}
var sf_active := false
var sf_mode := ""                      # shenshan / xianfu / gift / youyin
var sf_seq := -1
var sf_by_seq := {}
var sf_picks := []
var sf_ui: Control = null
var sf_btn: TextureButton = null
var sf_allow_skip := false
var sf_waiting := false                # 已经发出去、在等看破回答：这段时间别再发同一笔
var ql_picks: Array = []               # 前路：已选的三张
var cg_active := false                 # 传承 / 看破 / 枷锁 的列表面板
var cg_ui: Control = null
var cg_kind := ""                      # inherit / sight / shackle / kanpo_target
var cg_target := -1
var zl_active := false                 # 炸裂界面
var zl_seq := -1
var zl_picks := []
var zl_by_seq := {}
var zl_ui: Control = null
var zl_btn: TextureButton = null
var dy_active := false                 # 钓鱼：选牌种面板
var dy_target := -1
var dy_kind := ""
var dy_ui: Control = null
var dy_btn: TextureButton = null
var dy_frames := []
var pofa_ask_key := ""                 # 同一个立直窗口只自动问一次
var pofa_disc_stage := false           # 副露完，等我暗置打出一张
var pofa_active := false               # 破发界面开着
var pofa_seq := -1
var pofa_picks := []
var pofa_ui: Control = null
var pofa_btn: TextureButton = null
var hs_active := false                 # 海神界面开着
var hs_mode := ""                      # give（被动还牌）/ swap（主动挪宝）
var hs_picks := []
var hs_ui: Control = null
var hs_btn: TextureButton = null
var xn_selecting := false              # X神：正在选东南西北
var c11_active := false                  # 「魔术」界面开着
var c11_picks := []                      # 选中的手牌（hand_pick 用）
var c11_ind := -1                        # 选中的宝牌指示牌下标
var c11_ui: Control = null
var c11_btn: TextureButton = null
var c11_frames: Array = []               # 指示牌上的彩框


func _card10s2_on_clicked() -> void:
	var cnt := int(srv_state.get("card10s2_count", 0))
	if bool(srv_state.get("card10s2_ready", false)):
		_toast("「四喜」已经就绪：这一次自摸就是小四喜")
		return
	if cnt > 0 or not (srv_state.get("card10s2_reveal", []) as Array).is_empty():
		_toast("「四喜」已发动：还差 %d 张摸牌" % maxi(0, 5 - cnt))
		return
	if not bool(srv_state.get("card10s2_can", false)):
		_toast("「四喜」要摸牌后发动，而且手里/副露里要有 3 张东 + 3 张北")
		return
	var r := srv_request({"op": "card10s2_activate", "seat": my_seat})
	if r.is_empty():
		_toast(_srv_err("「四喜」发动失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return

	srv_apply_state(r.get("state"), r.get("events"))
	_toast("「四喜」发动：第 5 张摸到的牌直接按小四喜自摸结算（期间不能打东/北）")
# 这张卡是不是被【看破 / 封堵】本小局剔除了
func _skill_voided(card: int) -> bool:
	for c in (srv_state.get("poked_cards", []) as Array):
		if int(c) == int(card):
			return true
	return false


# 这个 (卡, 技能) 本小局是不是已经用过了（一次性）
func _skill_used_once(card: int, skill: int) -> bool:
	return (srv_state.get("used_skills", []) as Array).has(
		"%d-%d-%d" % [int(card), int(skill), my_seat])


func _card11_on_clicked() -> void:
	if c11_active:
		_card11_close()
		_toast("已取消「魔术」")
		return
	if c11s2_active:
		_card11s2_close()          # 同一张卡的另一个技能先收掉（否则两个「开始」按钮重叠）
	if not bool(srv_state.get("card11_can", false)):
		if _skill_used_once(11, 1):
			_toast("「魔术」本小局已经用过了")
		elif _skill_voided(11):
			_toast("「魔术」本小局被【看破/封堵】剔除了（换了别人来拦也一样）")
		else:
			_toast("「魔术」要摸牌之后、打牌之前发动")
		return
	if (dora_indicators as Array).is_empty():
		_toast("场上还没有翻开的宝牌指示牌")
		return
	c11_active = true
	c11_ind = -1
	_make_c11_ui()
	hand_pick.begin(c11_picks, 1, {"on_change": _refresh_c11_btn})
	_apply_entity_states(srv_state)
	_toast("魔术：选 1 张手牌 + 1 张宝牌指示牌 → 开始")


func _make_c11_ui() -> void:
	if c11_ui != null:
		return
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	c11_ui = Control.new()
	c11_ui.name = "Card11UI"
	c11_ui.z_index = 250
	host.add_child(c11_ui)
	c11_ui.position = Vector2.ZERO
	var n: int = (dora_indicators as Array).size()
	var tw := 76.0
	var th := 104.0
	var gap := 12.0
	var total: float = float(n) * tw + float(maxi(0, n - 1)) * gap
	var x0: float = (vp.x - total) * 0.5
	var y0: float = vp.y - 500.0
	c11_frames.clear()
	for i in range(n):
		var b := TextureButton.new()
		b.name = "C11Ind%d" % i
		b.texture_normal = load(TileBank.VERT_DIR
			+ TileBank.face_file(String(dora_indicators[i])) + ".png") as Texture2D
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		b.position = Vector2(x0 + float(i) * (tw + gap), y0)
		b.size = Vector2(tw, th)
		b.pressed.connect(_c11_pick_ind.bind(i))
		c11_ui.add_child(b)
		var f := SelFrame.attach(b, b.size)      # 彩框
		f.visible = false
		c11_frames.append(f)
	var hint := Label.new()
	hint.text = "点一张宝牌指示牌（彩框）"
	hint.add_theme_font_size_override("font_size", 22)
	hint.add_theme_color_override("font_color", Color(1, 1, 1))
	hint.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	hint.add_theme_constant_override("outline_size", 5)
	hint.position = Vector2(x0, y0 - 34.0)
	hint.mouse_filter = Control.MOUSE_FILTER_IGNORE
	c11_ui.add_child(hint)
	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	c11_btn = TextureButton.new()
	c11_btn.name = "Card11Start"
	c11_btn.texture_normal = tex
	c11_btn.ignore_texture_size = true
	c11_btn.stretch_mode = TextureButton.STRETCH_SCALE
	c11_btn.focus_mode = Control.FOCUS_NONE
	c11_btn.size = Vector2(bw, bh)
	c11_btn.position = prompt_btn_pos(bw, bh)
	c11_btn.visible = false
	c11_btn.pressed.connect(_card11_confirm)
	c11_ui.add_child(c11_btn)


func _c11_pick_ind(i: int) -> void:
	if not c11_active:
		return
	c11_ind = -1 if c11_ind == int(i) else int(i)
	for k in range(c11_frames.size()):
		var f = c11_frames[k]
		if f != null and is_instance_valid(f):
			f.visible = (k == c11_ind)
	_refresh_c11_btn()


func _refresh_c11_btn() -> void:
	if c11_btn != null and is_instance_valid(c11_btn):
		c11_btn.visible = c11_active and hand_pick.ready() and c11_ind >= 0


func _card11_confirm() -> void:
	if not c11_active or c11_picks.is_empty() or c11_ind < 0:
		return
	var tiles := display_tiles()
	var idx := int(c11_picks[0])
	if idx < 0 or idx >= tiles.size():
		return
	var hand := String(tiles[idx])
	var ind := c11_ind
	_card11_close()
	var r := srv_request({"op": "card11_swap", "seat": my_seat, "hand": hand, "idx": ind})
	if r.is_empty():
		_toast(_srv_err("「魔术」发动失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return

	srv_apply_state(r.get("state"), r.get("events"))
	var d: Dictionary = r.get("card11", {})
	var dl: Array = d.get("dora", [])
	var ds := ""
	for k in dl:
		ds += String(k) + " "
	_toast("魔术：用【%s】换了指示牌【%s】→ 宝牌指示牌现在是：%s"
		% [hand, String(d.get("got", "")), ds])
	refresh_hand()


func _card11_close() -> void:
	c11_active = false
	c11_ind = -1
	c11_frames.clear()
	hand_pick.end()
	if c11_btn != null and is_instance_valid(c11_btn):
		c11_btn.visible = false
	if c11_ui != null and is_instance_valid(c11_ui):
		c11_ui.queue_free()
	c11_ui = null
	c11_btn = null
	_apply_entity_states(srv_state)


# ─── 快手（Card11 Skill2）：摸的牌暗置换进别家牌河第 1 / 6 列 ─────────
func _card11s2_on_clicked() -> void:
	if c11s2_active:
		_card11s2_close()
		_toast("已取消「快手」")
		return
	if c11_active:
		_card11_close()            # 同一张卡的另一个技能先收掉
	if not bool(srv_state.get("card11s2_can", false)):
		if _skill_used_once(11, 2):
			_toast("「快手」本小局已经用过了")
		elif _skill_voided(11):
			_toast("「快手」本小局被【看破/封堵】剔除了")
		else:
			_toast("「快手」要摸牌后、打牌前发动；别家牌河要还有空位")
		return
	c11s2_active = true
	c11s2_seq = -1
	c11s2_sel = {}
	c11s2_by_seq = {}
	_make_c11s2_ui()
	_apply_entity_states(srv_state)
	_toast("快手：点一张别家牌河第 1 / 6 列的明牌（彩框） → 开始")


func _c11s2_ok(seq: int) -> bool:
	if not c11s2_active:
		return false
	return c11s2_by_seq.has(int(seq))


# 牌河渲染时调用：记下「这个 seq 是哪家的第几张」，并判断能不能点
func _c11s2_note(seq: int, seat: int, slot: int, down: bool) -> bool:
	if int(seq) < 0:
		return false
	c11s2_by_seq[int(seq)] = {"seat": int(seat), "slot": int(slot)}
	if not c11s2_active:
		return false
	if int(seat) == my_seat or down:
		return false
	return int(slot) % 6 == 0 or int(slot) % 6 == 5


func _on_c11s2_river_clicked(seq: int) -> void:
	if not _c11s2_ok(seq):
		_toast("只能选别家牌河第一列或第六列的明牌")
		return
	if c11s2_seq == int(seq):
		c11s2_seq = -1
		c11s2_sel = {}
	else:
		c11s2_seq = int(seq)
		c11s2_sel = (c11s2_by_seq.get(int(seq), {}) as Dictionary).duplicate()
	_refresh_c11s2_btn()
	_apply_entity_states(srv_state)


func _make_c11s2_ui() -> void:
	if c11s2_ui != null:
		return
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	c11s2_ui = Control.new()
	c11s2_ui.name = "Card11S2UI"
	c11s2_ui.z_index = 250
	host.add_child(c11s2_ui)
	c11s2_ui.position = Vector2.ZERO
	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	c11s2_btn = TextureButton.new()
	c11s2_btn.name = "Card11S2Start"
	c11s2_btn.texture_normal = tex
	c11s2_btn.ignore_texture_size = true
	c11s2_btn.stretch_mode = TextureButton.STRETCH_SCALE
	c11s2_btn.focus_mode = Control.FOCUS_NONE
	c11s2_btn.size = Vector2(bw, bh)
	c11s2_btn.position = prompt_btn_pos(bw, bh)
	c11s2_btn.visible = false
	c11s2_btn.pressed.connect(_card11s2_confirm)
	c11s2_ui.add_child(c11s2_btn)


func _refresh_c11s2_btn() -> void:
	if c11s2_btn != null and is_instance_valid(c11s2_btn):
		c11s2_btn.visible = c11s2_active and c11s2_seq >= 0


func _card11s2_confirm() -> void:
	if not c11s2_active or c11s2_seq < 0:
		return
	var seq := c11s2_seq
	var ts := int(c11s2_sel.get("seat", -1))
	var sl := int(c11s2_sel.get("slot", -1))
	_card11s2_close()
	var r := srv_request({"op": "card11s2_swap", "seat": my_seat, "river": seq,
		"ts": ts, "slot": sl})
	if r.is_empty():
		_toast(_srv_err("「快手」发动失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return

	srv_apply_state(r.get("state"), r.get("events"))
	var d: Dictionary = r.get("card11s2", {})
	_toast("快手：摸到的【%s】暗置进了牌河，换回【%s】"
		% [String(d.get("gave", "")), String(d.get("got", ""))])
	refresh_hand()


func _card11s2_close() -> void:
	c11s2_active = false
	c11s2_seq = -1
	c11s2_sel = {}
	c11s2_by_seq = {}
	hand_pick.end()                # 快手不用手牌，但别的面板可能借着 hand_pick → 统一收掉
	if c11s2_btn != null and is_instance_valid(c11s2_btn):
		c11s2_btn.visible = false
	if c11s2_ui != null and is_instance_valid(c11s2_ui):
		c11s2_ui.queue_free()
	c11s2_ui = null
	c11s2_btn = null
	_apply_entity_states(srv_state)


# ─── 海神 / X神（Card12）────────────────────────────────────────────
# ─── 破发（Card13 S1）───────────────────────────────────────────────
# ─── 炸裂（Card14 S2）／钓鱼（Card15 S1）────────────────────────────
# ─── 传承 / 研究 / 看破 / 枷锁 / 连接（Card16~18）──────────────────
# ─── 深山 / 浓雾 / 前路 / 感知 / 馈赠 / 先负 / 友引 / 加热 ──────────
func _cold_kinds() -> Array:
	var warm := ["0m", "0p", "0s", "zhong", "5s", "7s", "9s"]
	for n in range(1, 10):
		warm.append("%dm" % n)
	var out: Array = []
	for k in TileBank.TILE_KINDS:
		if not warm.has(k):
			out.append(k)
	return out


func _sf_shenshan_toggle() -> void:
	if not bool(srv_state.get("shenshan_can", false)):
		_toast("深山：切出第 12 张牌之后才能开")
		return
	var r := srv_request({"op": "shenshan_toggle", "seat": my_seat})
	if r.is_empty():
		_toast(_srv_err("深山开关失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("深山：%s" % ("开（别人摸牌都会报给你）"
		if bool(r.get("state", {}).get("shenshan_on", false)) else "关"))


func _sf_ignite() -> void:
	# 点燃是配牌技能：走和降神/风神/研究同一套 deal_skill 窗口
	if not is_inside_tree():
		return
	var r := srv_request({"op": "deal_skill", "seat": my_seat, "action": "use",
		"card": 14, "skill": 1})
	if typeof(r) != TYPE_DICTIONARY or (r as Dictionary).is_empty():
		_toast(_srv_err("点燃发动失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return
	srv_apply_state(r.get("state"), r.get("events"))
	var d: Dictionary = r.get("deal_skill", {})
	var dc: Array = d.get("dice", [])
	var a := "?"
	var b := "?"
	if dc.size() > 0:
		a = str(int(dc[0]))
	if dc.size() > 1:
		b = str(int(dc[1]))
	if bool(d.get("success", false)):
		_toast("点燃：骰子【%s】【%s】→ 成功，本局可以先点炸裂了" % [a, b])
	else:
		_toast("点燃：骰子【%s】【%s】→ 失败，本局炸裂不能发动" % [a, b])


func _sf_ignite_again() -> void:
	var r := srv_request({"op": "ignite", "seat": my_seat})
	if typeof(r) != TYPE_DICTIONARY or (r as Dictionary).is_empty():
		_toast(_srv_err("点燃发动失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return
	srv_apply_state(r.get("state"), r.get("events"))
	var d: Dictionary = r.get("ignite", {})
	_toast("点燃：骰子 %s → %s" % [str(d.get("dice", [])),
		"成功，本局炸裂随便用" if bool(d.get("success", false)) else "失败，下次再多 1 点修正"])


func _sf_nongwu() -> void:
	if not bool(srv_state.get("nongwu_can", false)):
		_toast("浓雾：摸牌后发动，一场只能放一次")
		return
	var r := srv_request({"op": "nongwu", "seat": my_seat})
	if r.is_empty():
		_toast(_srv_err("浓雾失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return

	srv_apply_state(r.get("state"), r.get("events"))
	_toast("浓雾：接下来 4 巡别家不能自摸")


func _sf_qianlu() -> void:
	if not bool(srv_state.get("qianlu_can", false)):
		_toast("前路：打出 3 张牌之后才能预言")
		return
	ql_picks.clear()
	_sf_pick_kind_next()


func _sf_pick_kind_next() -> void:
	var n := ql_picks.size()
	if n >= 3:
		var r := srv_request({"op": "qianlu", "seat": my_seat, "tiles": ql_picks.duplicate()})
		if r.is_empty():
			_toast(_srv_err("前路失败：服务端没有回应"))
			return
		if srv_kangpo_blocked(r):
			return
		if not bool(r.get("ok", true)):
			var why := String(r.get("error", ""))
			_toast(why if why != "" else "前路：发动失败了")
			_pull_state()
			return
		srv_apply_state(r.get("state"), r.get("events"))
		_toast("前路：预言了【%s】【%s】【%s】" % [String(ql_picks[0]),
			String(ql_picks[1]), String(ql_picks[2])])
		ql_picks.clear()
		_cg_close()			# 网格必须关掉，否则 cg_kind 挂着 → _skill_input_busy() 恒 true = 卡死
		return
	cg_kind = "qianlu"
	cg_pick_cb = Callable()
	cg_ok_cb = Callable()
	_cg_show_kind_grid("前路：预言接下来打出的第 %d 张（已选 %d 张）" % [n + 1, n])


func _sf_pick_kind_add(k: String) -> void:
	if cg_ui == null or not is_instance_valid(cg_ui):
		return
	var idx := ql_picks.find(k)
	if idx >= 0:
		ql_picks.remove_at(idx)            # 再点一次 = 取消
	else:
		if ql_picks.size() >= 3:
			_toast("最多选三张")
			return
		ql_picks.append(k)
	_cg_refresh_grid()
	var head := cg_ui.get_node_or_null("Head") as Label
	if head != null:
		head.text = "前路：预言接下来打出的牌（已选 %d / 3）" % ql_picks.size()


func _sf_ganzhi() -> void:
	var r := srv_request({"op": "ganzhi", "seat": my_seat})
	if r.is_empty():
		_toast(_srv_err("感知失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return

	srv_apply_state(r.get("state"), r.get("events"))
	var v: Array = r.get("ganzhi", {}).get("view", [])
	if (v as Array).is_empty():
		_toast("感知：现在没有人听牌")
		return
	var txt := ""
	for it in v:
		txt += "%s：%s　" % [srv_name_of(int(it.get("seat", 0))),
			" ".join(PackedStringArray(it.get("tiles", [])))]
	_toast("感知：" + txt)


func _sf_gift() -> void:
	if bool(srv_state.get("gift_used", false)):
		_toast("馈赠2：换牌这一局已经用过了（一定和牌看另一条链路）")
		return
	if not bool(srv_state.get("gift_swap_can", false)):
		_toast("馈赠2：手切满 8 张、摸牌前才能换牌")
		return
	_sf_open("gift")


func _sf_xianfu() -> void:
	if not bool(srv_state.get("xianfu_can", false)):
		_toast("先负：别人立直的一发巡、自己打牌前才能用")
		return
	_sf_open("xianfu")


func _sf_heat() -> void:
	if not bool(srv_state.get("heat_can", false)):
		_toast("加热：摸牌后发动，一局一次")
		return
	_cg_heat_grid()


# 加热：冷系牌种做成**牌面按钮**，点一张直接发动；右边一个「跳过」= 不加热
func _cg_heat_grid() -> void:
	_cg_close()
	var host: Node = get_parent()
	if host == null:
		host = self
	cg_ui = Control.new()
	cg_ui.name = "HeatGridUI"
	cg_ui.z_index = 300                       # 牌墩 15/16、技能按钮 20 → 不遮挡
	host.add_child(cg_ui)
	cg_ui.position = Vector2.ZERO
	cg_active = true
	var head := Label.new()
	head.text = "加热：点一张冷系牌（四张全变赤宝）"
	head.add_theme_font_size_override("font_size", 22)
	head.add_theme_color_override("font_color", Color(1, 1, 0.85))
	head.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	head.add_theme_constant_override("outline_size", 6)
	head.position = Vector2(40, 40)
	cg_ui.add_child(head)
	var kinds: Array = _cold_kinds()
	var tw := 62.0
	var th := 86.0
	var gap := 6.0
	var per := 13
	for i in range((kinds as Array).size()):
		var kind := String(kinds[i])
		var b := TextureButton.new()
		b.name = "H%s" % kind
		b.texture_normal = load(TileBank.VERT_DIR + TileBank.face_file(kind) + ".png") as Texture2D
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		b.position = Vector2(40.0 + float(i % per) * (tw + gap),
			100.0 + float(int(i / per)) * (th + 20.0))
		b.size = Vector2(tw, th)
		b.pressed.connect(_cg_heat_pick.bind(kind))
		cg_ui.add_child(b)
	var cols := mini(per, (kinds as Array).size())
	var sk := ui_btn("pass", 170.0)           # 跳过：不加热
	sk.position = Vector2(40.0 + float(cols) * (tw + gap) + 24.0, 100.0)
	sk.pressed.connect(_cg_close)
	cg_ui.add_child(sk)


func _cg_heat_pick(kind: String) -> void:
	_cg_close()
	_sf_heat_use(kind)


func _sf_heat_use(k: String) -> void:
	var r := srv_request({"op": "heat", "seat": my_seat, "kind": k})
	if r.is_empty():
		_toast(_srv_err("加热失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return

	srv_apply_state(r.get("state"), r.get("events"))
	_toast("加热：%s 的四张全部变赤宝" % k)


# 友引（22S2）：
#   段1 = 鸣牌窗口里先点技能（arm），副露完再把手里 1~3 组面子一起摊出来
#   段2 = 四副露后、摸完牌：一张手牌 ↔ 全场牌河一张
func _sf_youyin() -> void:
	if bool(srv_state.get("youyin_meld_can", false)):
		var r := srv_request({"op": "youyin_meld_arm", "seat": my_seat})
		if srv_kangpo_blocked(r):
			return
		if r.is_empty() or not bool(r.get("ok", false)):
			_toast(_srv_err(String(r.get("error", "友引：现在不能发动"))))
			return
		srv_apply_state(r.get("state"), r.get("events"))
		_toast("友引：准备好了 —— 现在点吃/碰，副露完再把手里的面子一起摊出来")
		return
	if bool(srv_state.get("youyin_can", false)):
		_sf_open("youyin")
		return
	_toast("友引：要正好出现吃/碰按钮；或者四副露之后刚摸完牌")


# ─── 22S2 段1：摊面子（选 3/6/9 张，必须都是完整面子）─────────────
# 22S2 段1「友引摊面子」：通用面板（一次一组、不可取消、循环由服务端 offer 控制）
var ym_panel := SkillPanel.new()


func _ym_open() -> void:
	ym_panel.begin({
		"name": "友引",
		"want": 4, "min": 3,          # 一次正好一组：3 张（刻/顺）或 4 张（杠）
		"cancel": false,              # 不可取消
		"close_on_confirm": false,    # 可能还要继续摊，先不关
		"on_confirm": _ym_confirm,
	})
	_toast("友引：选 1 组面子（3 张 或 4 张杠）→ 开始（不能跳过）")


func _ym_confirm(picks: Array, rivers: Array) -> void:
	var tiles := display_tiles()
	var picked: Array = []
	for i in picks:
		if int(i) >= 0 and int(i) < tiles.size():
			picked.append(String(tiles[int(i)]))
	var r := srv_request({"op": "youyin_meld_pick", "seat": my_seat, "tiles": picked})
	if srv_kangpo_blocked(r):
		ym_panel.close()
		return
	if r.is_empty():
		_toast(_srv_err("友引：服务端没有回应"))
		ym_panel.close()
		return
	if not bool(r.get("ok", false)):
		# 无效副露：面板不关，清空重选
		_toast(String(r.get("error", "无效副露！")))
		_ym_open()
		return
	var d: Dictionary = r.get("youyin_meld", {})
	srv_apply_state(r.get("state"), r.get("events"))
	refresh_hand()
	if bool(d.get("more", false)):
		_ym_open()                    # 手里还有面子 → 清空继续摊
		_toast("友引：还有面子，继续摊（全部明置）")
		return
	ym_panel.close()
	_toast("友引：摊完了，正常打牌")


func _ym_sync(st: Dictionary) -> void:
	if typeof(st.get("youyin_meld_offer")) == TYPE_DICTIONARY:
		if not ym_panel.active:
			_ym_open()
		return
	if ym_panel.active:
		ym_panel.close()
func _sf_open(mode: String) -> void:
	riichi_selecting = false              # 技能面板优先，先退出立直选牌
	_update_riichi_button_dim()
	sf_active = true
	sf_mode = mode
	sf_seq = -1
	sf_waiting = false
	sf_picks.clear()
	sf_by_seq.clear()
	sf_allow_skip = (mode == "shenshan" or mode == "youyin" or mode == "gift")
	_make_sf_ui()
	hand_pick.begin(sf_picks, 1, {"on_change": _refresh_sf_btn})
	_refresh_sf_btn()
	_apply_entity_states(srv_state)
	match mode:
		"shenshan":
			_toast("深山：选一张手牌 + 开始 = 换他摸的牌；不选直接开始 = 跳过")
		"xianfu":
			_toast("先负：选一张手牌 + 牌河一张 → 开始（换完必须立直）")
		"gift":
			_toast("馈赠2：选一张手牌 + 彩框选牌河一张 → 开始（不选直接开始 = 跳过）")
		"youyin":
			_toast("友引：选一张手牌 + 彩框选牌河一张 → 开始（互换）")


func _make_sf_ui() -> void:
	if sf_ui != null:
		return
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	sf_ui = Control.new()
	sf_ui.name = "SwapFlowUI"
	sf_ui.z_index = 260
	host.add_child(sf_ui)
	sf_ui.position = Vector2.ZERO
	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	sf_btn = TextureButton.new()
	sf_btn.name = "SwapStart"
	sf_btn.texture_normal = tex
	sf_btn.ignore_texture_size = true
	sf_btn.stretch_mode = TextureButton.STRETCH_SCALE
	sf_btn.focus_mode = Control.FOCUS_NONE
	sf_btn.size = Vector2(bw, bh)
	sf_btn.position = prompt_btn_pos(bw, bh)
	sf_btn.visible = false
	sf_btn.pressed.connect(_sf_confirm)
	sf_ui.add_child(sf_btn)


func _refresh_sf_btn() -> void:
	if sf_btn == null or not is_instance_valid(sf_btn):
		return
	if sf_waiting:
		sf_btn.visible = false            # 等对方决定是否看破：别让人重复点
		return
	if sf_allow_skip:
		sf_btn.visible = sf_active
	else:
		sf_btn.visible = sf_active and hand_pick.ready() and sf_seq >= 0


func _on_sf_river_clicked(seq: int) -> void:
	if sf_mode == "shenshan":
		return
	var info := {}
	for td in (srv_state.get("tiles", []) as Array):
		if int(td.get("discard_seq", -1)) == int(seq):
			info = td
			break
	if bool((info as Dictionary).get("face_down", false)):
		_toast("暗置的牌不能选")
		return
	sf_seq = -1 if sf_seq == int(seq) else int(seq)
	_refresh_sf_btn()
	_apply_entity_states(srv_state)


func _sf_confirm() -> void:
	if not sf_active:
		return
	var tiles := display_tiles()
	var hand := ""
	if not sf_picks.is_empty():
		var idx := int(sf_picks[0])
		if idx >= 0 and idx < tiles.size():
			hand = String(tiles[idx])
	var mode := sf_mode
	var seq := sf_seq
	var op := ""
	var payload := {"seat": my_seat}
	match mode:
		"shenshan":
			op = "shenshan_resolve"
			payload["hand"] = hand
		"xianfu":
			op = "xianfu_swap"
			payload["hand"] = hand
			payload["river"] = seq
		"gift":
			op = "gift_skip" if seq < 0 else "gift_swap"
			payload["hand"] = hand
			payload["river"] = seq
		"youyin":
			op = "youyin_take"
			payload["hand"] = hand
			payload["river"] = seq
	var r := srv_request(payload.merged({"op": op}))
	if r.is_empty():
		_toast(_srv_err("发动失败：服务端没有回应"))
		_sf_close()
		return
	if srv_kangpo_blocked(r):
		# ★ 别关、更别重开：重开会把刚选的牌清空，而服务端已经把这一笔挂起来，
		#   对方回答「不看破」时会用**刚才的 payload** 自己重放。
		#   这里只把「开始」藏起来，等 state 里看破结束再放出来。
		sf_waiting = true
		_refresh_sf_btn()
		return
	_sf_close()
	srv_apply_state(r.get("state"), r.get("events"))
	refresh_hand()
	match mode:
		"shenshan":
			var d: Dictionary = r.get("shenshan", {})
			if bool(d.get("skipped", false)):
				_toast("深山：跳过这次")
			else:
				_toast("深山：用【%s】换了 %s 的【%s】"
					% [String(d.get("gave", "")), srv_name_of(int(d.get("from", 0))),
					   String(d.get("got", ""))])
		"xianfu":
			# 手牌变了：立直按钮由 state 里的 legal 决定，这里只提示
			_toast("先负：换好了，现在去立直（不能振听）")
		"gift":
			_toast("馈赠2：换好了")
		"youyin":
			var d2: Dictionary = r.get("youyin", {})
			_toast("友引：%s" % ("跳过" if bool(d2.get("skipped", false))
				else "把【%s】纳入手牌" % String(d2.get("got", ""))))


func _sf_close() -> void:
	sf_active = false
	sf_mode = ""
	sf_waiting = false
	sf_seq = -1
	sf_picks.clear()
	sf_by_seq.clear()
	hand_pick.end()
	if sf_btn != null and is_instance_valid(sf_btn):
		sf_btn.visible = false
	if sf_ui != null and is_instance_valid(sf_ui):
		sf_ui.queue_free()
	sf_ui = null
	sf_btn = null
	_apply_entity_states(srv_state)


# 深山报牌 / 友引：state 里出现 offer 就自动弹面板
func _sf_sync(st: Dictionary) -> void:
	if _hand_locked():
		return                               # 立直后手牌锁定：这些都会换手牌，一律不问
	# 「等看破」结束了（不管对方看没看破）→ 允许重新点开始
	if sf_waiting:
		var pr0 = st.get("prompt")
		var still := typeof(pr0) == TYPE_DICTIONARY \
			and String((pr0 as Dictionary).get("kind", "")) == "kangpo"
		if not still:
			sf_waiting = false
			_refresh_sf_btn()
	# 先负：换牌成功 → 提示去立直；窗口没了 → 收面板
	#   （客户端自己的成功响应可能是**服务端重放**回来的，本地 match 分支拿不到，
	#     所以必须靠 state 收敛，否则面板会一直挂着、手牌点不动）
	if sf_active and sf_mode == "xianfu":
		if int(st.get("xianfu_armed", -1)) == my_seat:
			_sf_close()
			_toast("先负：换好了，现在去立直（不能振听）")
			return
		if not bool(st.get("xianfu_can", false)):
			_sf_close()
			return
	var so = st.get("shenshan_offer")
	var go = st.get("gift_offer")
	if typeof(so) == TYPE_DICTIONARY and not sf_active:
		if is_skill_muted(19, 1):
			return                       # 深山图标盖着遮罩 → 不再自动询问
		_sf_open("shenshan")
		_toast("深山：%s 摸到【%s】" % [srv_name_of(int(so.get("from", 0))),
			String(so.get("tile", ""))])
		return
	if typeof(go) == TYPE_DICTIONARY and not sf_active:
		if is_skill_muted(21, 2):
			return                       # 馈赠图标盖着遮罩 → 不再自动询问
		_sf_open("gift")
		_toast("馈赠2：要换牌吗？（选一张手牌 + 牌河一张；不选直接开始 = 跳过）")
		return
	# 【友引】两个效果都是**主动**技能（点图标才发动），没有 offer，也没有自动询问：
	#   段1 = 吃/碰按钮出现时点图标 → arm；段2 = 四副露摸完牌点图标 → 换牌面板。
	#   ★ 以前这里会自动开关面板：段2 的 offer 早就不发了，于是「点图标 → 面板刚开
	#     就被这里 close 掉」，看起来像点一下立刻退出。
	if typeof(so) != TYPE_DICTIONARY and typeof(go) != TYPE_DICTIONARY \
			and sf_active \
			and (sf_mode == "shenshan" or sf_mode == "gift"):
		_sf_close()


# ─── 看破询问（Card17 S2）────────────────────────────────────────
# 遮罩 ≠ 静音：服务端还挂着「等你看破」，必须自动放行，否则对局永久停住。
var _auto_skip_sig := ""
var _auto_note_sig := ""


func key0_note(ask) -> String:
	if typeof(ask) != TYPE_DICTIONARY:
		return ""
	var d := ask as Dictionary
	return "%d-%d-%d" % [int(d.get("target", -1)), int(d.get("card", 0)),
		int(d.get("skill", 0))]
var _masked_pass_queued := false


func _masked_auto_pass(st: Dictionary) -> void:
	var arr = st.get("asks")
	if typeof(arr) != TYPE_ARRAY or (arr as Array).is_empty():
		_auto_skip_sig = ""                  # 这一笔问完了 → 清记号（下一笔要重新放行）
		return
	for it in (arr as Array):
		if typeof(it) != TYPE_DICTIONARY:
			continue
		var d := it as Dictionary
		if not _kp_all_muted(d):
			continue                         # 还有没被遮罩的招 → 照常问我
		var aid := int(d.get("id", -1))
		if aid < 0:
			continue
		var key := str(aid)
		if key == _auto_skip_sig:
			return
		_auto_skip_sig = key
		if key != _auto_note_sig:             # 只在第一次提示，别每帧刷
			_auto_note_sig = key
			_toast("这个技能的所有拦截方式都被你屏蔽了 → 自动放行（再点图标可恢复询问）")
		if not _masked_pass_queued:
			_masked_pass_queued = true
			# 不能在 srv_apply_state 的调用栈里再跑一次 srv_apply_state（会重入）→ 挪到帧末
			call_deferred("_masked_do_pass", aid)
		return                               # 一次只放行一条，剩下的下一帧接着来


# 遮罩状态下替玩家放行这一条询问
func _masked_do_pass(aid: int) -> void:
	_masked_pass_queued = false
	if game_over:
		return
	var r := srv_request({"op": "act_answer", "seat": my_seat, "aid": int(aid), "kind": "pass"})
	if r.is_empty():
		_auto_skip_sig = ""                  # 没回话 → 下次轮询再试一次
		return
	kp_sig = ""
	srv_apply_state(r.get("state"), r.get("events"))


# ── 询问栈：看破 / 封堵 / 阻止 / 免疫（同一个座位**可能同时有多条**）────────
#   每条 = 树上的一个节点；点哪条的按钮就答哪条（先答先落由服务端保证）。
var kp_sig := ""

const ACT_KIND_CN := {"sight": "看破", "block": "封堵", "stop": "阻止", "imm": "免疫"}


func _kp_sync(st: Dictionary) -> void:
	var arr = st.get("asks")
	if typeof(arr) != TYPE_ARRAY:
		arr = []
	var sig := JSON.stringify(arr)
	if sig == kp_sig:
		return
	kp_sig = sig
	_asks_show(arr as Array)


# ── 询问按钮（看破 / 封堵 / 阻止 / 免疫 / 开始=跳过）的大小：右上角 − ＋ ⟲ 实时调 ──
const ASK_CFG := "user://ask_ui.cfg"
const ASK_SCALE_DEFAULT := 2.3          # 230%：用户 2026-10-28 拍的
const ASK_TUNE_UI := false              # 调节条已经收起来了（想再调就把这里改成 true）
var ask_btn_scale := ASK_SCALE_DEFAULT
var _ask_cfg_ok := false
var _asks_last: Array = []


# 一条询问 = 一行：标题 + 能用哪几招（技能图标按钮）+「开始」图当跳过
# 这张卡是不是某一家的「主战」卡（决定询问行的上下顺序）
func _ask_card_is_main(actor: int, card: int) -> bool:
	var arr = srv_state.get("char_states", [])
	if typeof(arr) != TYPE_ARRAY:
		return false
	for it in (arr as Array):
		if typeof(it) != TYPE_DICTIONARY:
			continue
		if int((it as Dictionary).get("seat", -1)) != int(actor):
			continue
		var m = (it as Dictionary).get("main", {})
		if typeof(m) == TYPE_DICTIONARY and int((m as Dictionary).get("card", 0)) == int(card):
			return true
	return false


func _asks_show(arr: Array) -> void:
	_asks_last = (arr as Array).duplicate(true)
	_ask_scale_load()
	_kp_close()
	if arr.is_empty():
		return
	kp_active = true
	if cg_active:
		_cg_close()                      # 残留的选单（比如【复制】列表）先收掉，别叠着
	var host: Node = get_parent()
	if host == null:
		host = self
	kp_ui = Control.new()
	kp_ui.name = "ActAskUI"
	kp_ui.z_index = 320
	kp_ui.mouse_filter = Control.MOUSE_FILTER_IGNORE   # 不铺遮罩：点桌面照常
	host.add_child(kp_ui)
	kp_ui.position = Vector2.ZERO
	var vp := get_viewport_rect().size
	var col_x := 48.0
	var y := 96.0
	# 摊平成「行」：一行 = 一个（询问 × 可用招式）= 一个人物卡 + 一个跳过
	#   主战卡发动的排在前面（用户口径：谁在主战位谁在上面）
	var rows: Array = []
	for it in arr:
		if typeof(it) != TYPE_DICTIONARY:
			continue
		var d0 := it as Dictionary
		var a_actor := int(d0.get("actor", -1))
		var a_card := int(d0.get("card", 0))
		var kl0 = d0.get("kinds")
		var ks0: Array = kl0 if typeof(kl0) == TYPE_ARRAY else []
		if ks0.is_empty():
			# 兜底：服务端没给可用招式（异常/版本不一致）→ 至少留一个「跳过」，
			# 否则这条询问没有按钮可点，kp_active 永远为真，整个对局卡死。
			rows.append({"d": d0, "kind": "pass",
				"main": _ask_card_is_main(a_actor, a_card)})
		for k0 in ks0:
			rows.append({"d": d0, "kind": String(k0),
				"main": _ask_card_is_main(a_actor, a_card)})
	rows.sort_custom(func(a, b) -> bool:
		return bool(a.get("main", false)) and not bool(b.get("main", false)))
	y = 96.0
	for row in rows:
		var d: Dictionary = row.get("d", {})
		var ks := String(row.get("kind", ""))
		var aid := int(d.get("id", -1))
		var actor := int(d.get("actor", -1))
		var nm := String(d.get("name", ""))
		var card := int(d.get("card", 0))
		var is_counter := String(d.get("kind", "skill")) != "skill"
		var txt := "%s 发动了【%s】—— 要拦下来吗？" % [srv_name_of(actor), nm]
		if is_counter:
			txt = "%s 的【%s】正在拦别人的技能 —— 要反制吗？" % [srv_name_of(actor), nm]
		var lb := Label.new()
		lb.text = txt
		lb.add_theme_font_size_override("font_size", 22)
		lb.add_theme_color_override("font_color", Color(1, 1, 0.85))
		lb.add_theme_color_override("font_outline_color", Color(0, 0, 0))
		lb.add_theme_constant_override("outline_size", 6)
		lb.position = Vector2(col_x, y)
		kp_ui.add_child(lb)
		# 跳过按钮（尺寸基准）
		var stex := btn_tex("pass")
		var sb := TextureButton.new()
		sb.texture_normal = stex
		sb.ignore_texture_size = true
		sb.stretch_mode = TextureButton.STRETCH_SCALE
		sb.focus_mode = Control.FOCUS_NONE
		var sw := 84.0 * ask_btn_scale
		var sh := sw * 0.32
		if stex != null and stex.get_width() > 0:
			sh = sw * float(stex.get_height()) / float(stex.get_width())
		sb.size = Vector2(sw, sh)
		# 被看破的那张人物卡：等比缩放到和跳过按钮同高（不变形、不叠字）
		var ctex := load("res://Cailiao/skill/cards/card_%02d.png" % card) as Texture2D
		var cb2 := TextureButton.new()
		cb2.texture_normal = ctex
		cb2.ignore_texture_size = true
		cb2.stretch_mode = TextureButton.STRETCH_SCALE
		cb2.focus_mode = Control.FOCUS_NONE
		var cw := sh * 0.72
		var ch := sh
		if ctex != null and ctex.get_width() > 0:
			cw = sh * float(ctex.get_width()) / float(ctex.get_height())
		cb2.size = Vector2(cw, ch)
		cb2.tooltip_text = "%s 的【%s】→ 点这张卡用「%s」拦下来" % [
			srv_name_of(actor), nm, String(ACT_KIND_CN.get(ks, ks))]
		cb2.position = Vector2(col_x, y + 30.0)
		cb2.pressed.connect(_kp_answer.bind(aid, ks))
		kp_ui.add_child(cb2)
		sb.position = Vector2(col_x + cw + 18.0, y + 30.0)
		sb.pressed.connect(_kp_answer.bind(aid, "pass"))
		kp_ui.add_child(sb)
		y += ch + 70.0
		if y > vp.y - 150.0:             # 兜底：排不下就另起一列，别跑出屏幕
			y = 96.0
			col_x += 620.0
	if ASK_TUNE_UI:
		_ask_tune_show(vp)


func _ask_tune_show(vp: Vector2) -> void:
	if kp_ui == null or not is_instance_valid(kp_ui):
		return
	var tx := vp.x - 316.0
	var ty := 24.0
	var bg := ColorRect.new()
	bg.color = Color(0.0, 0.0, 0.0, 0.42)
	bg.position = Vector2(tx - 8.0, ty - 6.0)
	bg.size = Vector2(300.0, 52.0)
	bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	kp_ui.add_child(bg)
	var lb := Label.new()
	lb.text = "询问按钮 %d%%" % int(round(ask_btn_scale * 100.0))
	lb.add_theme_font_size_override("font_size", 18)
	lb.add_theme_color_override("font_color", Color(1, 1, 0.9))
	lb.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	lb.add_theme_constant_override("outline_size", 5)
	lb.position = Vector2(tx, ty + 8.0)
	lb.mouse_filter = Control.MOUSE_FILTER_IGNORE
	kp_ui.add_child(lb)
	_ask_tune_btn("-", Vector2(tx + 132.0, ty), _ask_scale_by.bind(-0.1))
	_ask_tune_btn("+", Vector2(tx + 180.0, ty), _ask_scale_by.bind(0.1))
	_ask_tune_btn("重置", Vector2(tx + 228.0, ty), _ask_scale_reset)


func _ask_tune_btn(txt: String, pos: Vector2, cb: Callable) -> void:
	var b := Button.new()
	b.text = txt
	b.focus_mode = Control.FOCUS_NONE
	b.position = pos
	b.size = Vector2(60.0, 42.0) if txt == "重置" else Vector2(44.0, 42.0)
	b.add_theme_font_size_override("font_size", 20)
	b.pressed.connect(cb)
	kp_ui.add_child(b)


func _ask_scale_load() -> void:
	if _ask_cfg_ok:
		return
	_ask_cfg_ok = true
	var cf := ConfigFile.new()
	if cf.load(ASK_CFG) == OK:
		ask_btn_scale = clampf(float(cf.get_value("ask", "scale", ask_btn_scale)), 0.5, 2.5)


func _ask_scale_by(d: float) -> void:
	ask_btn_scale = clampf(snappedf(ask_btn_scale + d, 0.01), 0.5, 2.5)
	_ask_scale_apply()


func _ask_scale_reset() -> void:
	ask_btn_scale = ASK_SCALE_DEFAULT
	_ask_scale_apply()


func _ask_scale_apply() -> void:
	var cf := ConfigFile.new()
	cf.set_value("ask", "scale", ask_btn_scale)
	cf.save(ASK_CFG)
	if not _asks_last.is_empty():
		_asks_show(_asks_last)               # 立刻按新尺寸重排


func _kp_answer(aid: int, kind: String) -> void:
	var r := srv_request({"op": "act_answer", "seat": my_seat, "aid": int(aid),
		"kind": String(kind)})
	if r.is_empty():
		_toast(_srv_err("拦截：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "拦截：失败")))
		_pull_state()
		return
	kp_sig = ""
	srv_apply_state(r.get("state"), r.get("events"))
	if String(kind) == "pass":
		_toast("放行")
	else:
		_toast("已发动【%s】" % String(ACT_KIND_CN.get(String(kind), kind)))



func _kp_my_kinds(ask) -> Array:
	var out: Array = []
	if typeof(ask) != TYPE_DICTIONARY:
		return out
	var d := ask as Dictionary
	# 拦截树格式：这条 ask 就是「我」的那一条，直接带着我能用的招
	var kk = d.get("kinds")
	if typeof(kk) == TYPE_ARRAY:
		for k in (kk as Array):
			out.append(String(k))
		return out
	# 老 kangpo_ask 外形（带 options），向后兼容
	var opts = d.get("options")
	if typeof(opts) != TYPE_ARRAY:
		if int(d.get("owner", -1)) == my_seat:
			out.append("sight")
		return out
	for o in opts:
		if typeof(o) != TYPE_DICTIONARY:
			continue
		if int((o as Dictionary).get("seat", -1)) != my_seat:
			continue
		var kinds = (o as Dictionary).get("kinds")
		if typeof(kinds) != TYPE_ARRAY:
			continue
		for k in kinds:
			var ks := String(k)
			if not out.has(ks):
				out.append(ks)
	return out


func _kp_kind_muted(k: String) -> bool:
	match String(k):
		"sight":
			return is_skill_muted(17, 2)
		"block":
			return is_skill_muted(31, 1)
		"stop":
			return is_skill_muted(31, 2)
		"imm":
			return false                  # 免疫没有「屏蔽」这一说
	return true


# 我能用的拦截方式**全部**被遮罩盖住 → 这一笔就不再问我（自动放行）
func _kp_all_muted(ask) -> bool:
	var mine := _kp_my_kinds(ask)
	if mine.is_empty():
		return false
	for k in mine:
		if not _kp_kind_muted(String(k)):
			return false
	return true


# 点自己卡上的【封堵】(31-1) / 【阻止】(31-2)
#   · 正在问我、而且这一招能用 → 立刻用它
#   · 否则 → 盖遮罩 / 取消遮罩（和看破、加速同一套语义）
func _c31_on_clicked(skill: int) -> void:
	var kind := "block" if int(skill) == 1 else "stop"
	var arr = srv_state.get("asks")
	if typeof(arr) == TYPE_ARRAY:
		for it in arr:
			if typeof(it) != TYPE_DICTIONARY:
				continue
			var ks = (it as Dictionary).get("kinds")
			if typeof(ks) == TYPE_ARRAY and (ks as Array).has(kind):
				_kp_answer(int((it as Dictionary).get("id", -1)), kind)
				return
	# 没有能用的询问 → 老语义：盖遮罩 / 取消遮罩
	var key := _skill_key(31, int(skill))
	if muted_skills.has(key):
		muted_skills.erase(key)
		_save_muted()
		_skill_mute_apply()
		_toast("%s：恢复自动询问" % ("封堵" if int(skill) == 1 else "阻止"))
		return
	muted_skills[key] = true
	_save_muted()
	_skill_mute_apply()
	_toast("%s：已屏蔽自动询问（再点一次恢复）" % ("封堵" if int(skill) == 1 else "阻止"))



func _kp_skip() -> void:
	_kp_close()
	var r := srv_request({"op": "kangpo_answer", "seat": my_seat, "use": false})
	if r.is_empty():
		_toast(_srv_err("放行失败：服务端没有回应"))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	if not bool(r.get("ok", true)):
		_toast(String(r.get("error", "放行之后那次发动没成功")))
		return
	# ★ 放行 = 那次发动**继续执行**（服务端会原地重放）：
	#   一定要说出来，否则玩家以为「什么都没发生」，可一次性技能其实已经用掉了。
	var got := ""
	if typeof(r.get("card11")) == TYPE_DICTIONARY:
		got = String((r.get("card11") as Dictionary).get("got", ""))
	var pend := false
	if typeof(r.get("kangpo")) == TYPE_DICTIONARY:
		pend = typeof((r.get("kangpo") as Dictionary).get("pending")) == TYPE_DICTIONARY
	if got != "":
		_toast("已放行：那次发动继续执行（换到 %s）" % got)
	elif pend:
		_toast("已放行：那次发动继续执行")


func _kp_close() -> void:
	c41_key = ""                          # 询问栈收起来了 → 复制列表下次重新弹
	kp_active = false
	if kp_ui != null and is_instance_valid(kp_ui):
		kp_ui.queue_free()
	kp_ui = null


# ─── 观看手牌：别家手牌在我视角变明牌（我切牌后服务端会清掉）─────────
# ─── 观看手牌：别家手牌在我视角变明牌（我切牌后服务端会清掉）─────────
#   「翻哪几张 / 怎么摆」全在 res://hand_show.gd（通用手牌展示面板），
#   这里只比对状态、决定什么时候重翻。
# ─── 别家手牌展示：全部走同一条链（c40s1 透视 / 感知 / 思路 / 四喜）──────
#   数据来源：state.reveal_hands（整手）+ c10s2_reveal（只公开 3 张）
#   摆法：就翻在**这家自己的手牌行**里（不另画一层）→ 多家各在各家位，不会挤。
#   具体翻哪几张 / 怎么转，都在 res://hand_show.gd。
var _reveal_sig := ""


func _reveal_hands_sync(st: Dictionary) -> void:
	var arr = st.get("reveal_hands")
	var rv = st.get("c10s2_reveal")
	var sig := JSON.stringify(arr) if typeof(arr) == TYPE_ARRAY else ""
	var sig2 := JSON.stringify(rv) if typeof(rv) == TYPE_ARRAY else ""
	var hsig := ""
	for w in OPP_ORDER:
		hsig += "%s%d," % [w, (opp_hands.get(w, []) as Array).size()]
	var key := sig + "|" + sig2 + "|" + hsig
	if key == _reveal_sig:
		return                                   # 内容没变 → 不重翻（避免闪烁）
	_reveal_sig = key
	hand_show.restore_reveal()
	c10s2_kinds.clear()
	var shown := {}
	# ① 整手观看（透视 / 感知 / 思路 / 同盟）
	if typeof(arr) == TYPE_ARRAY:
		for it in (arr as Array):
			if typeof(it) != TYPE_DICTIONARY:
				continue
			var seat := int((it as Dictionary).get("seat", -1))
			var tiles: Array = (it as Dictionary).get("tiles", [])
			if seat < 0 or seat == my_seat or (tiles as Array).is_empty():
				continue
			shown[seat] = true
			hand_show.reveal(seat, tiles)
	# ② 四喜：只公开 3 张 → 同样翻在他自己手牌行里（和透视一模一样的观感）
	if typeof(rv) == TYPE_ARRAY:
		for it2 in (rv as Array):
			if typeof(it2) != TYPE_DICTIONARY:
				continue
			var seat2 := int((it2 as Dictionary).get("seat", -1))
			var t2: Array = (it2 as Dictionary).get("tiles", [])
			if (t2 as Array).is_empty():
				continue
			if seat2 == my_seat:
				for k in t2:
					c10s2_kinds.append(String(k))
				continue
			if shown.has(seat2):
				continue                         # 整手已经翻开了，不用再翻一遍
			hand_show.reveal(seat2, t2)


# 这一家的牌面朝向（B=90 / C=180 / D=270），和「其他家副露」同一套
func opp_hand_rot(who: String) -> float:
	var geo: Array = OPP_MELD_GEO.get(who, [Vector2.ZERO, Vector2.ZERO, 180.0])
	return float(geo[2])


func _cg_close() -> void:
	cg_active = false
	cg_kind = ""
	cg_target = -1
	cg_pick_cb = Callable()
	cg_ok_cb = Callable()
	if cg_ui != null and is_instance_valid(cg_ui):
		cg_ui.queue_free()
	cg_ui = null


# 把「确认 + 跳过」两个按钮当成**一个整体**水平居中：
#   cx/cy = 整体中心点（cy 是这一行的高度中点，两个按钮各自垂直居中）
func _place_btn_pair(left: Control, right: Control, cx: float, cy: float,
		gap := 26.0) -> void:
	if left == null or right == null:
		return
	var w := left.size.x + gap + right.size.x
	var h := maxf(left.size.y, right.size.y)
	var x0 := cx - w * 0.5
	left.position = Vector2(x0, cy - left.size.y * 0.5)
	right.position = Vector2(x0 + left.size.x + gap, cy - right.size.y * 0.5)


# 二选一询问：标题 + 「确认」「跳过」两张贴图（不叠字）
func _cg_answer_pair(title: String, cb_yes: Callable, cb_no: Callable) -> void:
	_cg_close()
	var host: Node = get_parent()
	if host == null:
		host = self
	cg_ui = Control.new()
	cg_ui.name = "CgPairUI"
	cg_ui.z_index = 300
	host.add_child(cg_ui)
	cg_ui.position = Vector2.ZERO
	cg_active = true
	var vp := get_viewport_rect().size
	var head := Label.new()
	head.text = title
	head.add_theme_font_size_override("font_size", 24)
	head.add_theme_color_override("font_color", Color(1, 1, 0.85))
	head.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	head.add_theme_constant_override("outline_size", 6)
	head.position = Vector2(vp.x * 0.5 - 320.0, vp.y * 0.5 - 90.0)
	cg_ui.add_child(head)
	var ok := ui_btn("ok", 150.0)
	ok.pressed.connect(func():
		_cg_close()
		cb_yes.call())
	cg_ui.add_child(ok)
	var no := ui_btn("pass", 150.0)
	no.pressed.connect(func():
		_cg_close()
		cb_no.call())
	cg_ui.add_child(no)
	_place_btn_pair(ok, no, vp.x * 0.5, vp.y * 0.5 + 60.0)


# 竖向列表选择器：items = [{"label": String, "cb": Callable}]
# 用「技能卡图」做按钮的列表：lst = [{card, skill, name}]，点一张就回调
func _cg_show_cards(title: String, lst: Array, cb: Callable) -> void:
	_cg_close()
	cg_active = true
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	cg_ui = Control.new()
	cg_ui.name = "ChoiceCardsUI"
	cg_ui.z_index = 300
	host.add_child(cg_ui)
	cg_ui.position = Vector2.ZERO
	var head := Label.new()
	head.text = title
	head.add_theme_font_size_override("font_size", 22)
	head.add_theme_color_override("font_color", Color(1, 1, 0.85))
	head.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	head.add_theme_constant_override("outline_size", 6)
	head.position = Vector2(40, 40)
	cg_ui.add_child(head)
	var i := 0
	for it in (lst as Array):
		var d: Dictionary = it
		var card := int(d.get("card", 0))
		var sk := int(d.get("skill", 0))
		var nm := String(d.get("name", ""))
		var tex := load("res://Cailiao/skill/cards/card_%02d.png" % card) as Texture2D
		var b := TextureButton.new()
		b.name = "Card%d" % card
		b.texture_normal = tex
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		var col := i % 6
		var row := i / 6
		b.position = Vector2(40.0 + float(col) * 150.0, 90.0 + float(row) * 215.0)
		b.size = Vector2(140.0, 200.0)
		b.pressed.connect(func(): _cg_fire(cb.bind(card, sk, nm)))
		cg_ui.add_child(b)
		var lbl := Label.new()
		lbl.text = nm
		lbl.add_theme_font_size_override("font_size", 18)
		lbl.position = Vector2(0, 202)
		lbl.size = Vector2(140, 24)
		lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		lbl.mouse_filter = Control.MOUSE_FILTER_IGNORE
		b.add_child(lbl)
		i += 1
	# 跳过 / 关闭：用牌桌统一的「跳过」贴图（场景节点 BtnTiaoguo），不要黑色文字按钮
	var cl := TextureButton.new()
	cl.name = "CgSkip"
	cl.texture_normal = btn_tex("pass")
	cl.ignore_texture_size = true
	cl.stretch_mode = TextureButton.STRETCH_SCALE
	cl.focus_mode = Control.FOCUS_NONE
	var sk_w := 116.0
	var sk_h := 64.0
	var sk_tex := cl.texture_normal
	if sk_tex != null and sk_tex.get_width() > 0:
		sk_h = sk_w * float(sk_tex.get_height()) / float(sk_tex.get_width())
	cl.size = Vector2(sk_w, sk_h)
	cl.position = Vector2(40, 90.0 + float((i + 5) / 6) * 215.0 + 10.0)
	cl.tooltip_text = "跳过（不传承）"
	cl.pressed.connect(_cg_close)
	cg_ui.add_child(cl)


# 34 张牌种网格：多选，选中的加彩框 + 黄色序号（前路用）
var cg_pick_cb: Callable = Callable()      # 点牌种时干什么（空 = 前路）
var cg_ok_cb: Callable = Callable()        # 点「开始」时干什么（空 = 前路）


func _cg_pick_kind(kind: String) -> void:
	if cg_pick_cb.is_valid():
		cg_pick_cb.call(kind)
	else:
		_sf_pick_kind_add(kind)


func _cg_ok_pressed() -> void:
	if cg_ok_cb.is_valid():
		cg_ok_cb.call()
	else:
		_sf_pick_kind_next()


func _cg_show_kind_grid(title: String, on_pick: Callable = Callable(), on_ok: Callable = Callable()) -> void:
	_cg_close()
	cg_pick_cb = on_pick                    # 必须在 _cg_close() 之后再赋：
	cg_ok_cb = on_ok                        # _cg_close() 会把这两个 Callable 清掉
	cg_active = true
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	cg_ui = Control.new()
	cg_ui.name = "KindGridUI"
	cg_ui.z_index = 300
	host.add_child(cg_ui)
	cg_ui.position = Vector2.ZERO
	var head := Label.new()
	head.text = title
	head.name = "Head"
	head.add_theme_font_size_override("font_size", 22)
	head.add_theme_color_override("font_color", Color(1, 1, 0.85))
	head.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	head.add_theme_constant_override("outline_size", 6)
	head.position = Vector2(40, 40)
	cg_ui.add_child(head)
	var tw := 62.0
	var th := 86.0
	var gap := 6.0
	var kinds: Array = TileBank.TILE_KINDS
	for i in range((kinds as Array).size()):
		var kind := String(kinds[i])
		var col := i % 17
		var row := i / 17
		var b := TextureButton.new()
		b.name = "K%s" % kind
		b.texture_normal = load(TileBank.VERT_DIR + TileBank.face_file(kind) + ".png") as Texture2D
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		b.position = Vector2(40.0 + float(col) * (tw + gap), 100.0 + float(row) * (th + 30.0))
		b.size = Vector2(tw, th)
		b.pressed.connect(_cg_pick_kind.bind(kind))
		cg_ui.add_child(b)
		var f := SelFrame.attach(b, b.size)
		f.visible = false
		b.set_meta("frame", f)
		var num := Label.new()
		num.name = "Num"
		num.add_theme_font_size_override("font_size", 34)
		num.add_theme_color_override("font_color", Color(1, 0.9, 0.2))
		num.add_theme_color_override("font_outline_color", Color(0, 0, 0))
		num.add_theme_constant_override("outline_size", 6)
		num.position = Vector2(4, 2)
		num.mouse_filter = Control.MOUSE_FILTER_IGNORE
		b.add_child(num)
	var ok := ui_btn("ok", 150.0)              # 并排：两个同尺寸
	ok.name = "OK"
	ok.pressed.connect(_cg_ok_pressed)
	cg_ui.add_child(ok)
	var cl := ui_btn("pass", 150.0)
	cl.pressed.connect(_cg_kind_close)
	cg_ui.add_child(cl)
	# 两个按钮作为整体居中（这一行在牌种网格下方）
	_place_btn_pair(ok, cl, vp.x * 0.5, 100.0 + 2.0 * (th + 30.0) + 6.0 + 62.0)


# 关掉牌种网格（顺手把前路 / 强运的临时选择清掉）
func _cg_kind_close() -> void:
	ql_picks.clear()
	c37_kind = ""
	_cg_close()


# 刷新网格上的彩框/序号
func _cg_refresh_grid() -> void:
	if cg_ui == null or not is_instance_valid(cg_ui):
		return
	for i in range((TileBank.TILE_KINDS as Array).size()):
		var kind := String(TileBank.TILE_KINDS[i])
		var b := cg_ui.get_node_or_null("K%s" % kind) as TextureButton
		if b == null:
			continue
		var f = b.get_meta("frame", null)
		var idx := ql_picks.find(kind)
		if f != null and is_instance_valid(f):
			f.visible = idx >= 0
		var num := b.get_node_or_null("Num") as Label
		if num != null:
			num.text = str(idx + 1) if idx >= 0 else ""


func _cg_fire(cb: Callable) -> void:
	_cg_close()
	cb.call()


func _cg_inherit() -> void:
	var lst: Array = srv_state.get("chuancheng_list", [])
	if not bool(srv_state.get("chuancheng_can", false)) or lst.is_empty():
		_toast("传承：摸牌后发动；要这半庄有人宣告过技能")
		return
	_cg_show_cards("传承：选一个我宣告过的技能", lst, func(card, sk, nm):
		_cg_inherit_use(card, sk, nm))


func _cg_inherit_use(card: int, sk: int, nm: String) -> void:
	var r := srv_request({"op": "chuancheng", "seat": my_seat,
		"card": card, "skill": sk})
	if r.is_empty():
		_toast(_srv_err("传承失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return

	srv_apply_state(r.get("state"), r.get("events"))
	cg_copied = {"card": int(card), "skill": int(sk), "name": nm}
	_toast("传承：本小局把【%s】当成我的技能（再点这个图标就是发动它）" % nm)


func _cg_research() -> void:
	if int(srv_state.get("yanjiu_seat", -1)) >= 0:
		# 已经有了查看权：把看到的手牌念出来
		var ts: Array = srv_state.get("yanjiu_tiles", [])
		_toast("研究：%s 的手牌 %s" % [srv_name_of(int(srv_state.get("yanjiu_seat", 0))),
			" ".join(PackedStringArray(ts))])
		return
	# 配牌阶段：走和降神/风神同一套 deal_skill 窗口
	if not is_inside_tree():
		return
	var r := srv_request({"op": "deal_skill", "seat": my_seat, "action": "use",
		"card": 17, "skill": 1})
	if typeof(r) != TYPE_DICTIONARY or (r as Dictionary).is_empty():
		_toast(_srv_err("研究失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return
	srv_apply_state(r.get("state"), r.get("events"))
	var d: Dictionary = r.get("yanjiu", {})
	var dc: Array = d.get("dice", [])
	var ts2: Array = d.get("tiles", [])
	_toast("研究：骰子【%s】【%s】 → 本局可以查看 %s 的手牌：%s"
		% [String(dc[0]) if dc.size() > 0 else "?",
		   String(dc[1]) if dc.size() > 1 else "?",
		   srv_name_of(int(d.get("target", 0))),
		   " ".join(PackedStringArray(ts2))])


# 看破：选一个要剔除的技能 —— 用**技能图标按钮**（card_XX_Y_r0），旁边一个「跳过」
func _cg_show_skills(kind: String, target: int) -> void:
	var lst: Array = srv_state.get("kangpo_list", [])
	if (lst as Array).is_empty():
		_toast("看破：%s 现在没有可以剔除的技能" % srv_name_of(target))
		return
	_cg_close()
	var host: Node = get_parent()
	if host == null:
		host = self
	var cell := Vector2(150.0, 84.0)          # 技能图标按钮（446x250 等比）
	var gap := 12.0
	var per := 5
	var cnt := (lst as Array).size()
	var cols := mini(per, cnt)
	var w := float(cols) * cell.x + float(maxi(0, cols - 1)) * gap
	var rows := int((cnt + per - 1) / per)
	var vp := get_viewport_rect().size
	var x := (vp.x - w) * 0.5
	var yaw := float(rows) * cell.y + float(maxi(0, rows - 1)) * gap
	var y := vp.y * 0.5 - yaw * 0.5
	cg_ui = Control.new()
	cg_ui.name = "CgSightUI"
	cg_ui.z_index = 300                       # 牌墩 15/16、技能按钮 20 → 不会被盖
	host.add_child(cg_ui)
	cg_ui.position = Vector2.ZERO
	cg_active = true
	cg_kind = kind
	var head := Label.new()
	head.text = "看破：剔除 %s 的哪个技能？" % srv_name_of(target)
	head.add_theme_font_size_override("font_size", 24)
	head.add_theme_color_override("font_color", Color(1, 1, 0.85))
	head.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	head.add_theme_constant_override("outline_size", 6)
	head.position = Vector2(x, y - 40.0)
	cg_ui.add_child(head)
	for i in range(cnt):
		var d: Dictionary = (lst as Array)[i]
		var card := int(d.get("card", 0))
		var sk := int(d.get("skill", 0))
		var nm := String(d.get("name", ""))
		var b := TextureButton.new()
		b.name = "Sight%d" % i
		b.texture_normal = load("res://Cailiao/skill/ui/buttons/card_%02d_%d_r0.png"
			% [card, sk]) as Texture2D
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		b.size = cell
		b.position = Vector2(x + float(i % per) * (cell.x + gap),
			y + float(int(i / per)) * (cell.y + gap))
		b.tooltip_text = nm
		b.pressed.connect(_cg_sight_pick.bind(target, card, sk, nm))
		cg_ui.add_child(b)
	var sk2 := ui_btn("pass", 170.0)           # 跳过（放弃这次看破）
	sk2.position = Vector2(x + w - sk2.size.x, y + yaw + 12.0)
	sk2.pressed.connect(_cg_close)
	cg_ui.add_child(sk2)


func _cg_sight_pick(target: int, card: int, sk: int, nm: String) -> void:
	_cg_close()
	_cg_sight_use(target, card, sk, nm)


func _cg_sight_use(target: int, card: int, sk: int, nm: String) -> void:
	var r := srv_request({"op": "kangpo", "seat": my_seat, "target": target,
		"card": card, "skill": sk})
	if r.is_empty():
		_toast(_srv_err("看破失败：服务端没有回应"))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("看破：%s 的【%s】本小局剔除（代价：本局我不能和牌）"
		% [srv_name_of(target), nm])


func _cg_shackle() -> void:
	if not bool(srv_state.get("jiasuo_can", false)):
		_toast("枷锁：配牌时才能定，一局只能定一次")
		return
	_cg_shackle_grid()


# 枷锁：1~13 的数字按钮，4 / 5 / 4 三行，贴在「枷锁」技能图标按钮的正上方
#   · 单击数字 = 直接发动（不叠字、不用确认）
#   · z_index 300：牌墩 15/16、技能按钮 20 → 既不压住技能图标，也不会被牌山盖住
func _cg_shackle_grid() -> void:
	_cg_close()
	var host: Node = get_parent()
	if host == null:
		host = self
	var cell := Vector2(110.0, 62.0)
	var t0 := load("res://Cailiao/UI/数字/1.png") as Texture2D
	if t0 != null and t0.get_width() > 0:
		cell.y = cell.x * float(t0.get_height()) / float(t0.get_width())
	if _skill_btn_rect.size.x > 1.0:              # 和技能图标按钮一样大
		cell = _skill_btn_rect.size
	var gap := 10.0
	var rows := [4, 5, 4]
	var w := 5.0 * cell.x + 4.0 * gap
	var hh := 3.0 * cell.y + 2.0 * gap
	var vp := get_viewport_rect().size
	var x := (vp.x - w) * 0.5
	var y := 120.0
	if _skill_btn_rect.size.x > 1.0:
		x = _skill_btn_rect.get_center().x - w * 0.5
		y = _skill_btn_rect.position.y - hh - 12.0
	x = clampf(x, 8.0, maxf(8.0, vp.x - w - 8.0))
	y = clampf(y, 8.0, maxf(8.0, vp.y - hh - 8.0))
	cg_ui = Control.new()
	cg_ui.name = "CgShackleUI"
	cg_ui.z_index = 300
	host.add_child(cg_ui)
	cg_ui.position = Vector2.ZERO
	cg_active = true
	var n := 1
	for ri in range(rows.size()):
		var cnt := int(rows[ri])
		var row_w := float(cnt) * cell.x + float(maxi(0, cnt - 1)) * gap
		var rx := x + (w - row_w) * 0.5
		for ci in range(cnt):
			var b := TextureButton.new()
			b.name = "Han%d" % n
			b.texture_normal = load("res://Cailiao/UI/数字/%d.png" % n) as Texture2D
			b.ignore_texture_size = true
			b.stretch_mode = TextureButton.STRETCH_SCALE
			b.focus_mode = Control.FOCUS_NONE
			b.size = cell
			b.position = Vector2(rx + float(ci) * (cell.x + gap),
				y + float(ri) * (cell.y + gap))
			b.pressed.connect(_cg_shackle_pick.bind(n))
			cg_ui.add_child(b)
			n += 1
	var sk := ui_btn("pass", cell.x)               # 跳过（不定番）
	sk.position = Vector2(x + w + gap, y + 2.0 * (cell.y + gap))
	sk.pressed.connect(_cg_close)
	cg_ui.add_child(sk)


func _cg_shackle_pick(n: int) -> void:
	_cg_close()
	_cg_shackle_set(n)


func _cg_shackle_set(n: int) -> void:
	var r := srv_request({"op": "jiasuo", "seat": my_seat, "han": int(n)})
	if r.is_empty():
		_toast(_srv_err("枷锁失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return

	srv_apply_state(r.get("state"), r.get("events"))
	_toast("枷锁：本局期待 %d 番（正好和到就翻倍）" % int(n))


func _cg_link_pick() -> void:
	if not bool(srv_state.get("link_can", false)):
		_toast("连接：摸牌后发动，一局一次")
		return
	cg_kind = "link_target"
	_seat_pick_begin("link", "连接：选一位玩家，得点与他平分（互铳不算）")


func _cg_link_use(target: int) -> void:
	# ★ 用户口径（2026-11-01）：用完【连接】手牌点不动、只能打摸的那张。
	#   根因是 cg_kind 停在 "link_target" 没人清 → _skill_input_busy() 永远 true。
	_cg_close()
	if target == my_seat:
		_toast("不能连自己")
		return
	var r := srv_request({"op": "link", "seat": my_seat, "target": int(target)})
	if r.is_empty():
		_toast(_srv_err("连接失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return

	srv_apply_state(r.get("state"), r.get("events"))
	_toast("连接：与 %s 连接，得点平分" % srv_name_of(int(target)))


func _zl_on_clicked() -> void:
	if _hand_locked():
		_toast("已经立直了：手牌锁定，不能用炸裂")
		return
	if zl_active:
		_zl_close()
		_toast("已取消「炸裂」")
		return
	if not bool(srv_state.get("zhalie_can", false)):
		_toast("炸裂：摸牌前发动；别家牌河要有 6~9 的明牌")
		return
	_zl_open_now()


func _zl_open_now() -> void:
	if is_skill_muted(14, 2) and not zl_active:
		return                                   # 炸裂图标盖着遮罩 → 不再自动询问
	zl_active = true
	zl_seq = -1
	zl_picks.clear()
	zl_by_seq = {}
	_make_zl_ui()
	hand_pick.begin(zl_picks, 1, {"on_change": _refresh_zl_btn})
	_apply_entity_states(srv_state)
	_toast("炸裂：选一张手牌 + 别家牌河 6~9 的一张（彩框）→ 开始（会先摇点燃的骰子）")


func _make_zl_ui() -> void:
	if zl_ui != null:
		return
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	zl_ui = Control.new()
	zl_ui.name = "ZhalieUI"
	zl_ui.z_index = 250
	host.add_child(zl_ui)
	zl_ui.position = Vector2.ZERO
	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	zl_btn = TextureButton.new()
	zl_btn.name = "ZhalieStart"
	zl_btn.texture_normal = tex
	zl_btn.ignore_texture_size = true
	zl_btn.stretch_mode = TextureButton.STRETCH_SCALE
	zl_btn.focus_mode = Control.FOCUS_NONE
	zl_btn.size = Vector2(bw, bh)
	zl_btn.position = prompt_btn_pos(bw, bh)
	zl_btn.visible = false
	zl_btn.pressed.connect(_zl_confirm)
	zl_ui.add_child(zl_btn)


func _refresh_zl_btn() -> void:
	if zl_btn != null and is_instance_valid(zl_btn):
		zl_btn.visible = zl_active            # 不选牌点开始 = 跳过


func _on_zl_river_clicked(seq: int) -> void:
	var ok := int_set(srv_state.get("zhalie_seqs", [])).has(int(seq))
	if not ok:
		_toast("只能换别家牌河里的 6~9 序数牌")
		return
	zl_seq = -1 if zl_seq == int(seq) else int(seq)
	_refresh_zl_btn()
	_apply_entity_states(srv_state)


func _zl_confirm() -> void:
	if not zl_active:
		return
	if not bool(srv_state.get("zhalie_can", false)):
		_toast("这一手已经过了（炸裂只能在自己摸牌前发动）")
		_zl_close()
		return
	if zl_seq < 0 or zl_picks.is_empty():
		_zl_close()                          # 直接点开始 = 跳过
		draw_tile()
		return
	var tiles := display_tiles()
	var idx := int(zl_picks[0])
	if idx < 0 or idx >= tiles.size():
		return
	var hand := String(tiles[idx])
	var seq := zl_seq
	_zl_close()
	var r := srv_request({"op": "zhalie_swap", "seat": my_seat,
		"hand": hand, "river": seq})
	if r.is_empty():
		_toast(_srv_err("炸裂失败"))
		zl_ask_key = ""              # 这一巡还能再来一次
		draw_tile()
		return
	# 点燃改版后：本小局能不能炸在配牌阶段就定了，这里不再摇骰子。
	if bool(r.get("need_kangpo", false)):
		srv_apply_state(r.get("state"), r.get("events"))
		_toast("炸裂：已确认，等对方决定是否看破…")
		zl_ask_key = ""
		return
	srv_apply_state(r.get("state"), r.get("events"))
	var z: Dictionary = r.get("zhalie", {})
	if not bool(z.get("ok", false)):
		_toast("炸裂：这张换不了")
		zl_ask_key = ""
		draw_tile()
		return
	_toast("炸裂：用【%s】换了【%s】" % [hand, String(z.get("got", ""))])
	draw_tile()


func _zl_close() -> void:
	zl_active = false
	zl_seq = -1
	zl_picks.clear()
	zl_by_seq = {}
	hand_pick.end()
	if zl_btn != null and is_instance_valid(zl_btn):
		zl_btn.visible = false
	if zl_ui != null and is_instance_valid(zl_ui):
		zl_ui.queue_free()
	zl_ui = null
	zl_btn = null
	_apply_entity_states(srv_state)


# 钓鱼：点技能 → 选一家 → 列出「我能吃碰杠和」的牌种 → 点一张 → 开始
func _dy_on_clicked() -> void:
	if dy_active:
		_dy_close()
		_toast("已取消「钓鱼」")
		return
	if not bool(srv_state.get("diaoyu_can", false)):
		if bool(srv_state.get("diaoyu_locked", false)):
			_toast("钓鱼：本小局已经锁住了（吃到/碰上家的牌才会解锁）")
		else:
			_toast("钓鱼：要刚摸完牌，而且有一家手里有我能吃/碰/杠/和的牌")
		return
	if int(srv_state.get("diao_target", -1)) >= 0:
		_dy_open_panel(int(srv_state.get("diao_target")))
		return
	dy_active = true
	dy_target = -1
	_seat_pick_begin("dy", "钓鱼：先选一家，再选让他打出的牌")


func _dy_open_panel(target: int) -> void:
	dy_active = true
	dy_target = int(target)
	dy_kind = ""
	var opts: Dictionary = srv_state.get("diaoyu_opts", {})
	var list: Array = opts.get(str(target), [])
	if (list as Array).is_empty():
		_toast("这一家没有我能吃/碰/杠/和的牌")
		_dy_close()
		return
	_make_dy_ui(list)


func _make_dy_ui(kinds: Array) -> void:
	if dy_ui != null and is_instance_valid(dy_ui):
		dy_ui.queue_free()
	dy_ui = null
	dy_frames.clear()
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	dy_ui = Control.new()
	dy_ui.name = "DiaoyuUI"
	dy_ui.z_index = 250
	host.add_child(dy_ui)
	dy_ui.position = Vector2.ZERO
	var tw := 64.0
	var th := 88.0
	var gap := 8.0
	var per := mini(13, (kinds as Array).size())
	var total := float(per) * tw + float(maxi(0, per - 1)) * gap
	var x0 := (vp.x - total) * 0.5
	var y0 := vp.y - 470.0
	for i in range((kinds as Array).size()):
		var kind := String(kinds[i])
		var col := i % 13
		var row := i / 13
		var b := TextureButton.new()
		b.name = "DY%d" % i
		b.texture_normal = load(TileBank.VERT_DIR + TileBank.face_file(kind) + ".png") as Texture2D
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		b.position = Vector2(x0 + float(col) * (tw + gap), y0 + float(row) * (th + 10.0))
		b.size = Vector2(tw, th)
		b.pressed.connect(_dy_pick.bind(kind, i))
		dy_ui.add_child(b)
		var f := SelFrame.attach(b, b.size)
		f.visible = false
		dy_frames.append(f)
	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	dy_btn = TextureButton.new()
	dy_btn.name = "DiaoyuStart"
	dy_btn.texture_normal = tex
	dy_btn.ignore_texture_size = true
	dy_btn.stretch_mode = TextureButton.STRETCH_SCALE
	dy_btn.focus_mode = Control.FOCUS_NONE
	dy_btn.size = Vector2(bw, bh)
	dy_btn.position = prompt_btn_pos(bw, bh)
	dy_btn.visible = false
	dy_btn.pressed.connect(_dy_confirm)
	dy_ui.add_child(dy_btn)


func _dy_pick(kind: String, i: int) -> void:
	dy_kind = "" if dy_kind == kind else kind
	for k in range(dy_frames.size()):
		var f = dy_frames[k]
		if f != null and is_instance_valid(f):
			f.visible = (k == i and dy_kind != "")
	if dy_btn != null and is_instance_valid(dy_btn):
		dy_btn.visible = dy_kind != ""


func _dy_confirm() -> void:
	if not dy_active or dy_target < 0 or dy_kind == "":
		return
	var t := dy_target
	var kind := dy_kind
	_dy_close()
	var r := srv_request({"op": "diaoyu_force", "seat": my_seat,
		"target": t, "tile": kind})
	if r.is_empty():
		_toast(_srv_err("钓鱼失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return

	srv_apply_state(r.get("state"), r.get("events"))
	var d: Dictionary = r.get("diaoyu", {})
	if not bool(d.get("ok", true)):
		_toast("钓鱼：%s 手里没有【%s】→ 发动失败（本小局锁住）"
			% [srv_name_of(t), kind])
		return
	_toast("钓鱼：强制 %s 打出【%s" + "】" % [srv_name_of(t), kind])


func _dy_close() -> void:
	dy_active = false
	dy_target = -1
	dy_kind = ""
	dy_frames.clear()
	if dy_btn != null and is_instance_valid(dy_btn):
		dy_btn.visible = false
	if dy_ui != null and is_instance_valid(dy_ui):
		dy_ui.queue_free()
	dy_ui = null
	dy_btn = null
	_apply_entity_states(srv_state)


func _pofa_sync(st: Dictionary) -> void:
	var stage := String(st.get("pofa_stage", ""))
	if stage == "discard":
		if not pofa_active or not pofa_disc_stage:
			_pofa_close()
			pofa_active = true
			pofa_disc_stage = true
			pofa_seq = -1
			pofa_picks.clear()
			_make_pofa_ui()
			hand_pick.begin(pofa_picks, 1, {"on_change": _refresh_pofa_btn})
			_toast("破发：副露完成——暗置打出一张手牌")
		_refresh_pofa_btn()
		return
	if stage == "ask":
		var key := "%d-%d" % [int(st.get("live_left", 0)), int(st.get("turn", -1))]
		if key == pofa_ask_key:
			return
		pofa_ask_key = key
		if not pofa_active:
			_pofa_on_clicked()               # 别家立直 → 立刻问我
		return
	if pofa_active:
		_pofa_close()


func _pofa_on_clicked() -> void:
	if _hand_locked():
		_toast("已经立直了：手牌锁定，不能用破发")
		return
	if pofa_active:
		_pofa_close()
		_toast("已取消「破发」")
		return
	if not bool(srv_state.get("pofa_can", false)):
		_toast("破发：要在别人宣布立直之后发动")
		return
	pofa_active = true
	pofa_seq = -1
	pofa_picks.clear()
	_make_pofa_ui()
	hand_pick.begin(pofa_picks, 3, {"on_change": _refresh_pofa_btn})  # 选 2 张（吃碰）或 3 张（杠）
	_apply_entity_states(srv_state)
	_toast("破发：点河里一张明牌（彩框）+ 选 3 张手牌（前 2 张当搭子，第 3 张暗置放回牌河）")


func _make_pofa_ui() -> void:
	if pofa_ui != null:
		return
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	pofa_ui = Control.new()
	pofa_ui.name = "PofaUI"
	pofa_ui.z_index = 250
	host.add_child(pofa_ui)
	pofa_ui.position = Vector2.ZERO
	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	pofa_btn = TextureButton.new()
	pofa_btn.name = "PofaStart"
	pofa_btn.texture_normal = tex
	pofa_btn.ignore_texture_size = true
	pofa_btn.stretch_mode = TextureButton.STRETCH_SCALE
	pofa_btn.focus_mode = Control.FOCUS_NONE
	pofa_btn.size = Vector2(bw, bh)
	pofa_btn.position = prompt_btn_pos(bw, bh)
	pofa_btn.visible = false
	pofa_btn.pressed.connect(_pofa_confirm)
	pofa_ui.add_child(pofa_btn)


func _refresh_pofa_btn() -> void:
	if pofa_btn == null or not is_instance_valid(pofa_btn):
		return
	# 常驻：选好了 = 副露/暗置打出；什么都没选就点它 = 跳过这次破发
	pofa_btn.visible = pofa_active


func _on_pofa_river_clicked(seq: int) -> void:
	var ok := int_set(srv_state.get("pofa_seqs", [])).has(int(seq))
	if not ok:
		_toast("只能选别人牌河里的明牌")
		return
	pofa_seq = -1 if pofa_seq == int(seq) else int(seq)
	_refresh_pofa_btn()
	_apply_entity_states(srv_state)


func _pofa_confirm() -> void:
	if not pofa_active:
		return
	var tiles := display_tiles()
	if pofa_disc_stage:
		# 副露之后：暗置打出一张（回合已经跳到我）
		if pofa_picks.is_empty():
			return
		var di := int(pofa_picks[0])
		if di < 0 or di >= tiles.size():
			return
		var dt := String(tiles[di])
		pofa_disc_stage = false
		_pofa_close()
		var rd := srv_request({"op": "pofa_discard", "seat": my_seat, "tile": dt})
		if rd.is_empty():
			_toast(_srv_err("破发：暗置打出失败"))
			return
		srv_apply_state(rd.get("state"), rd.get("events"))
		_toast("破发：暗置打出【%s】（不造成振听）" % dt)
		refresh_hand()
		return
	if pofa_seq < 0 or pofa_picks.size() < 2:
		# 没选牌点「开始」= 跳过这次破发（问下一个 / 解锁对局）
		_pofa_close()
		var rp := srv_request({"op": "pofa_pass", "seat": my_seat})
		if not rp.is_empty():
			srv_apply_state(rp.get("state"), rp.get("events"))
		return
	var got: Array = []
	for k in pofa_picks:
		var i := int(k)
		if i < 0 or i >= tiles.size():
			return
		got.append(String(tiles[i]))
	var seq := pofa_seq
	_pofa_close()
	var r := srv_request({"op": "pofa_activate", "seat": my_seat, "river": seq,
		"tiles": got})
	if r.is_empty():
		_toast(_srv_err("破发失败"))
		return
	if srv_kangpo_blocked(r):
		return
	srv_apply_state(r.get("state"), r.get("events"))
	var d: Dictionary = r.get("pofa", {})
	_toast("破发：用【%s】+ 手牌 %d 张副露——现在暗置打出一张"
		% [String(d.get("called", "")), got.size()])
	refresh_hand()


func _pofa_close() -> void:
	pofa_active = false
	pofa_disc_stage = false
	pofa_seq = -1
	pofa_picks.clear()
	hand_pick.end()
	if pofa_btn != null and is_instance_valid(pofa_btn):
		pofa_btn.visible = false
	if pofa_ui != null and is_instance_valid(pofa_ui):
		pofa_ui.queue_free()
	pofa_ui = null
	pofa_btn = null
	_apply_entity_states(srv_state)


func _hs_on_clicked() -> void:
	if _srv_kangpo_wait():
		_toast("有人正在决定是否看破，稍等…（就在这个配牌窗口里）")
		return
	if hs_active:
		_toast("海神：必须选一张手牌交换（不能取消）")
		return
	var ph := String(srv_state.get("phase", ""))
	if ph == "deal_skill":
		var r := srv_request({"op": "haishin_start", "seat": my_seat})
		if bool(r.get("need_kangpo", false)):
			srv_apply_state(r.get("state"), r.get("events"))
			_toast("海神：已提出开启，等对方决定是否看破…（开成功会再提示一次）")
			return
		if r.is_empty():
			_toast(_srv_err("海神：配牌开启失败"))
			return
		srv_apply_state(r.get("state"), r.get("events"))
		_toast("海神：本小局开启——之后别人摸到万子/红中都会强制换牌")
		return
	var offer = srv_state.get("haishin_offer")
	if typeof(offer) == TYPE_DICTIONARY:
		_hs_open("give")
		return
	if bool(srv_state.get("haishin_on", false)):
		_toast("海神：本小局已开启；等别人摸到万子/红中时才会问")
		return
	_toast("海神：这是配牌技能——配牌时没开就不能用了")


func _hs_open(mode: String) -> void:
	riichi_selecting = false
	_update_riichi_button_dim()
	hs_active = true
	hs_mode = mode
	hs_picks.clear()
	_make_hs_ui()
	hand_pick.begin(hs_picks, 1, {"on_change": _refresh_hs_btn})
	_apply_entity_states(srv_state)
	if mode == "give":
		_toast("海神：选一张手牌还给他（换走他摸到的牌）")
	else:
		var step := int(srv_state.get("haishin_step", 0))
		var nm0: String = ["里宝", "杠宝", "杠里宝"][clampi(step, 0, 2)]
		_toast("海神：选一张万子/红中，换【%s】指示牌" % nm0)


func _make_hs_ui() -> void:
	if hs_ui != null:
		return
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	hs_ui = Control.new()
	hs_ui.name = "HaishinUI"
	hs_ui.z_index = 250
	host.add_child(hs_ui)
	hs_ui.position = Vector2.ZERO
	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	hs_btn = TextureButton.new()
	hs_btn.name = "HaishinStart"
	hs_btn.texture_normal = tex
	hs_btn.ignore_texture_size = true
	hs_btn.stretch_mode = TextureButton.STRETCH_SCALE
	hs_btn.focus_mode = Control.FOCUS_NONE
	hs_btn.size = Vector2(bw, bh)
	hs_btn.position = prompt_btn_pos(bw, bh)
	hs_btn.visible = false
	hs_btn.pressed.connect(_hs_confirm)
	hs_ui.add_child(hs_btn)


func _refresh_hs_btn() -> void:
	if hs_btn != null and is_instance_valid(hs_btn):
		hs_btn.visible = hs_active            # 不选牌直接点 = 跳过


func _hs_confirm() -> void:
	if not hs_active:
		return
	var tiles := display_tiles()
	var hand := ""
	if not hs_picks.is_empty():
		var idx := int(hs_picks[0])
		if idx >= 0 and idx < tiles.size():
			hand = String(tiles[idx])
	var mode := hs_mode
	hs_picks.clear()
	if mode == "give" and hand == "":
		_toast("海神：必须选一张手牌交换（不能跳过）")
		hand_pick.begin(hs_picks, 1, {"on_change": _refresh_hs_btn})
		return
	if mode == "swap" and hand == "":
		_hs_close()
		draw_tile()                              # 跳过 → 正常摸牌
		return
	if mode == "give":
		# ★ 先发请求，成功了才关面板。失败时要保留面板（否则 offer 还在、面板没了，
		#   服务端又锁着对局 → 看起来就是「彻底卡住」）
		var r := srv_request({"op": "haishin_give", "seat": my_seat, "hand": hand})
		if r.is_empty():
			_toast(_srv_err("海神借牌失败"))
			# 自愈：这笔询问可能已经结束了 → 拉一次最新状态，offer 没了就把面板收掉
			var st0 := srv_request({"op": "state", "seat": my_seat})
			if not st0.is_empty():
				srv_apply_state(st0.get("state"), [])
			if srv_state.get("haishin_offer") == null:
				_hs_close()
				return
			hs_picks.clear()
			hand_pick.begin(hs_picks, 1, {"on_change": _refresh_hs_btn})
			return
		if srv_kangpo_blocked(r):
			return
		var d: Dictionary = r.get("haishin", {})
		if bool(d.get("already", false)):
			_hs_close()                     # 这笔询问已经结束了：关面板、对局继续
			return
		if String(d.get("got", "")) == "":
			_toast("海神：这次没换成（再选一张试试）")
			hs_picks.clear()
			hand_pick.begin(hs_picks, 1, {"on_change": _refresh_hs_btn})
			return
		_hs_close()
		srv_apply_state(r.get("state"), r.get("events"))
		_toast("海神：借到【%s】，给出【%s】" % [String(d.get("got", "")), hand])
		refresh_hand()
		return
	# 挪宝：一次换一张，最多 3 次
	var r2 := srv_request({"op": "haishin_swap", "seat": my_seat, "hand": hand})
	if r2.is_empty():
		_hs_close()
		_toast(_srv_err("海神挪宝失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r2):
		return

	srv_apply_state(r2.get("state"), r2.get("events"))
	var d2: Dictionary = r2.get("haishin", {})
	var nxt := int(d2.get("next", 3))
	refresh_hand()
	if nxt >= 3:
		_hs_close()
		_toast("海神：里宝/杠宝/杠里宝都换完了，可以正常和牌")
		return
	var nm2: String = ["里宝", "杠宝", "杠里宝"][clampi(nxt, 0, 2)]
	hand_pick.begin(hs_picks, 1, {"on_change": _refresh_hs_btn})
	_refresh_hs_btn()
	_toast("海神：换到【%s】；下一步换【%s】（不换了就再点技能取消）"
		% [String(d2.get("got", "")), nm2])


func _hs_close() -> void:
	hs_active = false
	hs_mode = ""
	hs_picks.clear()
	hand_pick.end()
	if hs_btn != null and is_instance_valid(hs_btn):
		hs_btn.visible = false
	if hs_ui != null and is_instance_valid(hs_ui):
		hs_ui.queue_free()
	hs_ui = null
	hs_btn = null
	_apply_entity_states(srv_state)


# 别家摸到万子/红中 → 自动弹出「还牌」
func _hs_sync(st: Dictionary) -> void:
	var offer = st.get("haishin_offer")
	if typeof(offer) == TYPE_DICTIONARY:
		var key := "%d-%d-%s" % [int(offer.get("from", -1)), int(st.get("live_left", 0)),
			String(offer.get("tile", ""))]
		if key != hs_ask_key:
			hs_ask_key = key
			_hs_open("give")                     # 一次 offer 只弹一次（不再闪烁）
	elif hs_active and hs_mode == "give":
		_hs_close()


func _xn_on_clicked() -> void:
	if xn_selecting:
		xn_selecting = false
		_toast("已取消「X神」")
		return
	if not bool(srv_state.get("xn_can", false)):
		_toast("X神要摸牌之后、打牌之前发动")
		return
	xn_selecting = true
	_seat_pick_begin("xn", "X神：选一位其他玩家，让他跳过 2 次摸切")


func _xn_start(target: int) -> void:
	xn_selecting = false
	if int(target) == my_seat:
		_toast("不能选自己")
		return
	var r := srv_request({"op": "xn_activate", "seat": my_seat, "target": int(target)})
	if r.is_empty():
		_toast(_srv_err("X神发动失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return

	srv_apply_state(r.get("state"), r.get("events"))
	_toast("X神：%s 接下来 2 次摸切被跳过" % srv_name_of(int(target)))


# ── 技能图标遮罩：点一下盖住（不再自动询问），再点一下取消 ──────────────
# 判断「现在能不能发动」用的是服务端下发的各个 *_can 标志
var muted_skills := {}                     # "卡号:技能号" -> true（存盘的，F5 之后还在）
const MUTE_FILE := "user://muted_skills.json"


func _load_muted() -> void:
	muted_skills.clear()
	if not FileAccess.file_exists(MUTE_FILE):
		return
	var rf := FileAccess.open(MUTE_FILE, FileAccess.READ)
	if rf == null:
		return
	var data = JSON.parse_string(rf.get_as_text())
	if typeof(data) == TYPE_DICTIONARY:
		for k in (data as Dictionary):
			if bool((data as Dictionary)[k]):
				muted_skills[String(k)] = true


func _save_muted() -> void:
	var wf := FileAccess.open(MUTE_FILE, FileAccess.WRITE)
	if wf == null:
		return
	wf.store_string(JSON.stringify(muted_skills))
	wf.close()

const _MUTE_CAN := {
	# 只有「会自己弹出来问」的技能才需要遮罩：
	#   · 摸牌前 / 配牌前发动的
	# （看破这类**即时响应**技能不在这张表里，图标点击 = 遮罩开关，见 _on_identity_skill）
	# 摸牌之后才发动的技能不遮（它们不会被自动询问）
	Vector2i(7, 1): "oracle_timing",   # 降神：配牌阶段
	Vector2i(9, 1): "card09_can",      # 间合守：摸牌前
	Vector2i(9, 2): "card09_can",      # 间合攻：摸牌前
	# 海神不可遮罩（配牌开启后每次都必须换，见 _hs_sync）
	Vector2i(14, 2): "zhalie_can",     # 炸裂：摸牌前
	Vector2i(21, 2): "gift_swap_can",  # 馈赠：每巡摸牌前会自己弹询问
	Vector2i(19, 1): "shenshan_can",   # 深山：会自己弹报牌
	# 【看破】(17-2) 故意不在这张表里：它是**即时响应**技能，没有「不在时机」
	# 这种状态（`kangpo_can` 整局几乎恒为 true）。它的图标点击 = 遮罩开关，
	# 在 _on_identity_skill 里特判。
	Vector2i(24, 2): "future_can",     # 未来：每巡摸牌前会自己弹询问
}


func _skill_key(card: int, skill: int) -> String:
	return "%d:%d" % [int(card), int(skill)]


func is_skill_muted(card: int, skill: int) -> bool:
	return muted_skills.has(_skill_key(card, skill))


# 现在这个技能「不能发动」吗？（用来决定点击时是否盖遮罩）
func _skill_out_of_window(card: int, skill: int) -> bool:
	if int(card) == 21 and int(skill) == 2:
		# 馈赠：换牌 或 一定和牌，任一可用就不算「不在时机」
		return not (bool(srv_state.get("gift_swap_can", false))
			or bool(srv_state.get("yiding_can", false)))
	var flag := String(_MUTE_CAN.get(Vector2i(int(card), int(skill)), ""))
	if flag == "":
		return false
	if flag == "oracle_timing":
		# 降神：配牌阶段能发动；已经掷过骰子就靠图标开关
		return String(srv_state.get("phase", "")) != "deal_skill" \
			and typeof(srv_state.get("oracle")) != TYPE_DICTIONARY
	return not bool(srv_state.get(flag, false))


# 把遮罩状态同步到人物卡的图标上（只影响自己那一家）
func _skill_mute_apply() -> void:
	var idn := get_node_or_null("Identity")
	if idn == null:
		return
	# 只盖自己那两格：muted_skills 的键是「卡号:技能号」，没有座位，
	# 桌上要是碰巧有别人摆着同一张卡，不筛就会把他的图标也盖掉。
	# 拿不到座位映射（Identity 还没初始化好）→ only 为空 → 退回旧行为。
	var only: Array = []
	if idn.has_method("my_skill_slots"):
		only = idn.call("my_skill_slots")
	for c in idn.get_children():
		if not c.has_method("set_skill_muted"):
			continue
		var raw = c.get("_card_no")
		var cn := int(raw) if raw != null else 0
		if cn <= 0:
			continue
		if not only.is_empty():
			var mine := false
			for s in only:
				if String(c.name) == "Card%02d" % int(s):
					mine = true
					break
			if not mine:
				continue
		for i in range(2):
			c.call("set_skill_muted", i, muted_skills.has(_skill_key(cn, i + 1)))


func _on_identity_skill(seat: int, card_no: int, index: int,
		is_copy := false) -> void:
	if game_over or seat != my_seat:
		return
	_remember_skill_btn(card_no, index)
	# 这次点的是「复制来的那一份」→ 让服务端记到复制品那本账上
	copy_hint = ("%d-%d" % [card_no, index + 1]) if is_copy else ""
	# 协战卡被遮罩 → 这张卡的技能一律不发动（服务端也会拒，这里先给个说明）
	if _card_is_support_muted(int(card_no)):
		_toast("这张协战卡已经遮罩（长按人物卡可以取消）")
		return
	# 【厄运】静默期：其他三家不能使用任何技能（含看破/封堵/阻止）
	var _c34 = srv_state.get("c34")
	if typeof(_c34) == TYPE_DICTIONARY and bool((_c34 as Dictionary).get("muted", false)):
		_toast("【厄运】期间不能使用技能")
		return
	# 【海底】(34-2) 是**自动**技能，没有「手动发动」这一步 ——
	# 点图标 = 问服务端「现在为什么没发动」（只读诊断，不改状态）。
	# ★ 必须放在「不在发动时机 → 盖遮罩」之前，否则点了只会得到一句
	#   「现在不是发动时机」，看不出真正原因（用户 2026-10-28 报的就是这个）。
	if int(card_no) == 34 and int(index) == 1:
		_c34s2_probe()
		return
	# 染手面板开着时点别的技能图标 = 先关染手（两个面板会抢同一个 hand_pick）
	if c33_panel.active and not (int(card_no) == 33 and int(index) == 0):
		c33_panel.close()
		_apply_entity_states(srv_state)
	# 已经盖着遮罩 → 再点一下取消（恢复自动询问）
	var key := _skill_key(card_no, index + 1)
	if muted_skills.has(key):
		muted_skills.erase(key)
		_save_muted()
		_skill_mute_apply()
		_toast("这个技能恢复自动询问")
		return
	# 【看破】是即时响应技能：没有「发动时机」，所以图标就是遮罩的开关 ——
	# 点一下 = 别人的技能发动时不再弹询问（服务端那边由 _masked_auto_pass 自动放行），
	# 再点一下 = 恢复询问。★ 必须特判：通用那条「不在时机才盖遮罩」对它永远不成立
	# （`kangpo_can` 是「这张卡还能不能用」，整局都是 true），
	# 以前就是卡在这里 —— 点图标只会走到 _cg_sight_pick() 弹一句提示。
	if int(card_no) == 17 and int(index) == 1:
		muted_skills[key] = true
		_save_muted()
		_skill_mute_apply()
		_toast("看破：已屏蔽自动询问（再点一次恢复）")
		return
	# 【加速】也是「服务端会主动问我」的技能：图标 = 遮罩开关
	if int(card_no) == 29 and int(index) == 0:
		muted_skills[key] = true
		_save_muted()
		_skill_mute_apply()
		_c29s1_masked_skip(srv_state)
		_toast("加速：已屏蔽自动询问（再点一次恢复）")
		return
	# 不在发动时机点它 → 盖上 50% 白遮罩，并且以后不再自动询问它
	if _skill_out_of_window(card_no, index + 1):
		muted_skills[key] = true
		_save_muted()
		_skill_mute_apply()
		_toast("现在不是发动时机：已屏蔽这个技能的自动询问（再点一次取消）")
		return
	# 这个技能已经在选牌了（图标亮着、手牌变暗）→ 再点一次 = 取消这次发动
	if _skill_cancel_if_busy(card_no, index):
		return
	if int(card_no) == 1 and int(index) == 0:
		_cg_guobiao()                      # Card01 Skill1「国标」：挂牌子 → 点自摸结算
		return
	if int(card_no) == 1 and int(index) == 1:
		_skill2_on_clicked()               # Card01 Skill2「避开」：先选人、再选两张牌
		return
	if int(card_no) == 2 and int(index) == 0:
		_board_open()                      # Card02 Skill1「画板」：选三种手牌
		return
	if int(card_no) == 2 and int(index) == 1:
		_swap_start()                      # Card02 Skill2「换牌」：3 手牌 ↔ 3 牌河牌
		return
	if int(card_no) == 3 and int(index) == 0:
		_confidence_activate()             # Card03 Skill1「自信」：配牌阶段发动
		return
	if int(card_no) == 3 and int(index) == 1:
		_press_start()                     # Card03 Skill2「压制」：手牌 ↔ 牌河牌
		return
	if int(card_no) == 4 and int(index) == 0:
		_deal_swap_activate()              # Card04 Skill1「风神」：依次换三家的风牌
		return
	if int(card_no) == 25 and int(index) == 0:
		_dora_luck_activate()               # Card25 Skill1「宝牌运」：依次换三家的宝牌
		return
	if int(card_no) == 25 and int(index) == 1:
		if srv_c25s2_can():
			_c25s2_auto_arm()               # 万一自动那一次没发出去，点图标补一次
		elif srv_c25s2_on():
			_toast("宝牌的集合：本小局已开启（别人摸到宝牌会来问）")
		else:
			_toast("宝牌的集合：宝牌运发动之后才会紧接开启")
		return
	if int(card_no) == 4 and int(index) == 1:
		_self_wind_tip()                   # Card04 Skill2「自风」：自动技能，只提示
		return
	if int(card_no) == 6 and int(index) == 1:
		_tenacity_tip()                    # Card06 Skill2「坚韧」：被动技能，只提示
		return
	if int(card_no) == 7 and int(index) == 0:
		_oracle_on_clicked()               # Card07 Skill1「降神」：配牌发动 / 开关
		return
	if int(card_no) == 7 and int(index) == 1:
		_evil_tip()                        # Card07 Skill2「恶灵」：被动，只提示
		return
	if int(card_no) == 8 and int(index) == 0:
		_duel_on_clicked()                 # Card08 Skill1「决斗」：东南西北选对手
		return
	if int(card_no) == 8 and int(index) == 1:
		_duel_mark_tip()                   # Card08 Skill2「决斗标记」：被动，只提示
		return
	if int(card_no) == 9 and int(index) == 0:
		_card09_on_clicked(1)              # Card09 S1：换自己牌河
		return
	if int(card_no) == 9 and int(index) == 1:
		_card09_on_clicked(2)              # Card09 S2：换别家牌河
		return
	if int(card_no) == 10 and int(index) == 0:
		_c10_on_clicked()                  # Card10 S1「鬼门」
		return
	if int(card_no) == 10 and int(index) == 1:
		_card10s2_on_clicked()             # Card10 S2「四喜」
		return
	if int(card_no) == 19 and int(index) == 0:
		_sf_shenshan_toggle()              # Card19 S1「深山」
		return
	if int(card_no) == 19 and int(index) == 1:
		_sf_nongwu()                       # Card19 S2「浓雾」
		return
	if int(card_no) == 20 and int(index) == 0:
		if bool(srv_state.get("yiding_can", false)):
			_yiding_on_clicked()           # 前路成功 → 一定和牌
			return
		_sf_qianlu()                       # Card20 S1「前路」
		return
	if int(card_no) == 20 and int(index) == 1:
		_sf_ganzhi()                       # Card20 S2「感知」
		return
	if int(card_no) == 21 and int(index) == 0:
		_toast("迷途之家：被动技能 —— 手切 4 / 8 / 12 张自动累积馈赠")
		return
	if int(card_no) == 21 and int(index) == 1:
		if bool(srv_state.get("yiding_can", false)):
			_yiding_on_clicked()           # 段3：一定和牌（优先）
			return
		_sf_gift()                         # 段2：换牌
		return
	if int(card_no) == 22 and int(index) == 0:
		_sf_xianfu()                       # Card22 S1「先负」
		return
	if int(card_no) == 22 and int(index) == 1:
		_sf_youyin()                       # Card22 S2「友引」
		return
	if int(card_no) == 23 and int(index) == 0:
		_sf_heat()                         # Card23 S1「加热」
		return
	if int(card_no) == 24 and int(index) == 0:
		_c24_on_clicked()                  # Card24 S1「一发」
		return
	if int(card_no) == 24 and int(index) == 1:
		_future_on_clicked()               # Card24 S2「未来」
		return
	if int(card_no) == 16 and int(index) == 0:
		# 传承发动过 → 这张卡「就是」复制来的那个技能，直接转发
		var cp := _cc_copy(srv_state)
		if not cp.is_empty():
			_on_identity_skill(seat, int(cp.get("card", 0)), int(cp.get("skill", 0)))
			return
		_cg_inherit()                      # Card16 S1「传承」
		return
	if int(card_no) == 17 and int(index) == 0:
		_cg_research()                     # Card17 S1「研究」
		return
	if int(card_no) == 18 and int(index) == 0:
		_cg_shackle()                      # Card18 S1「枷锁」
		return
	if int(card_no) == 18 and int(index) == 1:
		_cg_link_pick()                    # Card18 S2「连接」
		return
	if int(card_no) == 14 and int(index) == 0:
		if String(srv_state.get("phase", "")) == "deal_skill":
			_sf_ignite()                   # 点燃：配牌阶段摇一次
		elif bool(srv_state.get("ignite_done", false)):
			_toast("点燃本小局已经摇过了（只在配牌阶段摇一次）")
		else:
			_toast("点燃只能在配牌阶段发动")
		return
	if int(card_no) == 14 and int(index) == 1:
		_zl_on_clicked()                   # Card14 S2「炸裂」
		return
	if int(card_no) == 15 and int(index) == 1:
		_yiding_on_clicked()               # Card15 S2「上钩」= 一定和牌
		return
	if int(card_no) == 15 and int(index) == 0:
		_dy_on_clicked()                   # Card15 S1「钓鱼」
		return
	if int(card_no) == 13 and int(index) == 0:
		_pofa_on_clicked()                 # Card13 S1「破发」
		return
	if int(card_no) == 12 and int(index) == 0:
		_hs_on_clicked()                   # Card12 S1「海神」
		return
	if int(card_no) == 12 and int(index) == 1:
		_xn_on_clicked()                   # Card12 S2「X神」
		return
	if int(card_no) == 11 and int(index) == 0:
		_card11_on_clicked()               # Card11 S1「魔术」
		return
	if int(card_no) == 11 and int(index) == 1:
		_card11s2_on_clicked()             # Card11 S2「快手」
		return
	if int(card_no) == 5 and int(index) == 0:
		_c05_skill()                       # Card05 Skill1「策略」
		return
	if int(card_no) == 5 and int(index) == 1:
		_c05_nuki()                        # Card05 Skill2「拔北」
		return
	if int(card_no) == 6 and int(index) == 0:
		_sw_activate()                     # Card06 Skill1「南风」
		return
	if int(card_no) == 26 and int(index) == 0:
		_c26s1_activate()                  # Card26 S1「云外镜」
		return
	if int(card_no) == 26 and int(index) == 1:
		_c26s2_activate()                  # Card26 S2「天梯」
		return
	# 走到这里 = 这个 (卡号, 技能号) 没有专门的界面/接口。
	# 以前一律发 op=skill → 服务端先问看破、再回「这个技能还没实现」，
	# 玩家看到的就是「点了技能先问看破、放行后又什么也没发生」。现在直接说清楚。
	if int(card_no) == 28 and int(index) == 0:
		_c28s1_activate()                  # Card28 S1「满贯」：配牌发动
		return
	if int(card_no) == 27 and int(index) == 0:
		_c27s1_open()                      # Card27 S1「调包」
		return
	if int(card_no) == 27 and int(index) == 1:
		_c27s2_open()                      # Card27 S2「命中」
		return
	if int(card_no) == 32 and int(index) == 0:
		_c32s1_activate()                  # Card32 S1「新手运」：配牌要每家一张幺九
		return
	if int(card_no) == 32 and int(index) == 1:
		_toast("无知：和牌时对对被算成四暗刻、索子清一色/只有发字牌的混一色被算成绿一色（可叠成双倍役满）")
		return
	if int(card_no) == 33 and int(index) == 0:
		_c33_start()                       # 染手：3 张手牌 ⇄ 牌河一组面子
		return
	if int(card_no) == 33 and int(index) == 1:
		_c33s2_open()                      # 记忆：输入上局结算点数 → 下一张暗置
		return
	if int(card_no) == 34 and int(index) == 0:
		_c34_arm()                         # 厄运：三巡内其他三家一切无效
		return
	if int(card_no) == 40 and int(index) == 1:
		_c40s2_open()                      # 同盟：指定一名玩家
		return
	if int(card_no) == 42 and int(index) == 0:
		_c42s1_apply()                     # 理论战：封死全场技能
		return
	if int(card_no) == 42 and int(index) == 1:
		_c42s2_open()                      # 夺目：指定结算用的庄家
		return
	if int(card_no) == 39 and int(index) == 0:
		_c39s1_apply()                     # 隐形：打出的牌谁都不能鸣/被荣
		return
	if int(card_no) == 46 and int(index) == 0:
		_c46_start()                       # 恶听：切一张能听牌的手牌 → 一定和牌
		return
	if int(card_no) == 45 and int(index) == 1:
		_c45s2_start()                     # 替身：指定两位玩家
		return
	if int(card_no) == 45 and int(index) == 0:
		_c45s1_start()                     # 神境：手牌 + 牌河挑 13 张
		return
	if int(card_no) == 44 and int(index) == 1:
		_c44s2_arm()                       # 电报：宣言明牌 → 和牌按 30 符 1 番
		return
	if int(card_no) == 43 and int(index) == 1:
		_toast("免疫：被动 —— 别人发动「指向你」的技能时会问你要不要免疫（本局 2 次）")
		return
	if int(card_no) == 43 and int(index) == 0:
		_c43_start()                       # NO MISS：手牌搭子 ⇄ 牌河搭子
		return
	if int(card_no) == 41 and int(index) == 0:
		if not c41_pool.is_empty():
			c41_auto_done = true
			_c41_pick_open(c41_pool)          # 有可复制的 → 点图标 = 开面板
			return
		muted_skills[key] = true              # 没有 → 点图标 = 盖遮罩（以后不再自动问）
		_save_muted()
		_skill_mute_apply()
		_c41_hint(false)
		_toast("复制：已屏蔽自动询问（再点一次恢复）")
		return
	if int(card_no) == 40 and int(index) == 0:
		_c40s1_open()                      # 透视：选一家看手牌
		return
	if int(card_no) == 38 and int(index) == 0:
		_c38s1_open()                      # 重整：3 张指示牌 ⇄ 手牌
		return
	if int(card_no) == 37 and int(index) == 1:
		_c37s2_open()                      # 强运：选一种牌 ⇄ 牌山第 4/8/12/16 张
		return
	if int(card_no) == 37 and int(index) == 0:
		_c37s1_arm()                       # 岭上开花：自动杠开 + 换铳张 + 得点×2
		return
	if int(card_no) == 36 and int(index) == 0:
		_toast("思路：被动 —— 别人宣告技能时自动看他的手牌，我打出一张牌后失效")
		return
	if int(card_no) == 36 and int(index) == 1:
		_c36s2_arm()                       # 故意：开启 → 下一张打出去自动结算
		return
	if int(card_no) == 31 and (int(index) == 0 or int(index) == 1):
		_c31_on_clicked(int(index) + 1)    # Card31：封堵 / 阻止（询问时点 = 发动，否则 = 遮罩）
		return
	if int(card_no) == 30 and int(index) == 0:
		_c30s1_activate()                  # Card30 S1「向听」：选两家 → 交牌 → 挑一张换
		return
	if int(card_no) == 30 and int(index) == 1:
		_w30s2_tip()                       # Card30 S2「W立」：被动，只提示
		return
	_toast("这个技能还没有专属的发动界面（%d-%d），先不用点它" % [card_no, index + 1])


# ── Card03 Skill1「自信」──────────────────────────────────────────────
#   配牌阶段发动，整小局有效、不能取消：
#   和牌 → 番数双倍；没和牌 → 自己付的点数双倍（放铳 / 别人自摸都算）。
#   发动后技能图标套红框（服务端 state.confident 决定，重进/换局都不会丢）。
func _confidence_activate() -> void:
	if bool(srv_state.get("confident", false)):
		_toast("「自信」本局已经发动过了")
		return
	# 配牌窗口里：通过 deal_skill 结算（这样服务端才知道我做完决定了）
	if String(srv_state.get("phase", "")) == "deal_skill":
		var r2 := srv_request({"op": "deal_skill", "seat": my_seat,
			"action": "use", "card": 3, "skill": 1})
		if r2.is_empty():
			_toast(_srv_err("「自信」发动失败：服务端没有回应"))
			return
		if srv_kangpo_blocked(r2):
			return
		var dr: Dictionary = r2.get("deal_skill", {})
		if not bool(dr.get("armed", false)):
			_toast(String(dr.get("reason", "现在不能发动「自信」")))
			return
		srv_apply_state(r2.get("state"), r2.get("events"))
		var idn2 := get_node_or_null("Identity")
		if idn2 != null and idn2.has_method("collapse_skills"):
			idn2.call("collapse_skills", 3)
		_toast("发动「自信」：本局和牌番数双倍；没和牌则失点双倍")
		return
	var r := srv_request({"op": "skill", "seat": my_seat, "card": 3, "skill": 1})
	if r.is_empty():
		_toast(_srv_err("「自信」发动失败：服务端没有回应"))
		return
	if not bool(r.get("armed", false)):
		_toast(String(r.get("reason", "只能在配牌阶段发动")))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	var idn := get_node_or_null("Identity")
	if idn != null and idn.has_method("collapse_skills"):
		idn.call("collapse_skills", 3)
	_toast("发动「自信」：本局和牌番数双倍；没和牌则失点双倍")


# ── Card28 S1「满贯」────────────────────────────────────────────────
#   配牌点图标发动：本局**任何玩家**和牌，番数结算不到满贯就不结算
#   （服务端直接不给和牌按钮）。特例：渣和无视满贯缚。
func _c28s1_activate() -> void:
	if bool(srv_state.get("c28s1_on", false)):
		_toast("满贯：本小局已经发动过了（整局常开）")
		return
	if String(srv_state.get("phase", "")) != "deal_skill":
		_toast("满贯：只能在配牌阶段发动")
		return
	var r := srv_request({"op": "deal_skill", "seat": my_seat,
		"action": "use", "card": 28, "skill": 1})
	if r.is_empty():
		_toast(_srv_err("「满贯」发动失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return
	var dr: Dictionary = r.get("deal_skill", {})
	if not bool(dr.get("armed", false)):
		_toast(String(dr.get("reason", "现在不能发动「满贯」")))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	var idn := get_node_or_null("Identity")
	if idn != null and idn.has_method("collapse_skills"):
		idn.call("collapse_skills", 28)
	_toast("发动【满贯】：本局任何人和牌，番数不到满贯都不予结算（渣和除外）")


func _apply_skill_frames(st: Dictionary) -> void:
	var idn := get_node_or_null("Identity")
	if idn == null or not idn.has_method("set_skill_frame"):
		return
	idn.call("reset_skill_frames")
	if bool(st.get("confident", false)):
		idn.call("set_skill_frame", 3, 0, true)     # Card03 Skill1 自信 → 红色框
	if bool(st.get("self_wind", false)):
		idn.call("set_skill_frame", 4, 1, true)     # Card04 Skill2 自风 → 红色框
	if bool(st.get("c25s2_on", false)):
		idn.call("set_skill_frame", 25, 1, true)    # Card25 Skill2 宝牌的集合（开启中）→ 红框
	if bool(st.get("c26s2_on", false)):
		idn.call("set_skill_frame", 26, 1, true)    # Card26 Skill2 天梯（开启中）→ 红框
	if bool(st.get("c44s2_on", false)):
		idn.call("set_skill_frame", 44, 1, true)    # Card44 Skill2 电报（明牌中）→ 红框
	if bool(st.get("c28s1_on", false)):
		idn.call("set_skill_frame", 28, 0, true)    # Card28 Skill1 满贯（本局常开）→ 红框
	if bool(st.get("tenacity", false)):
		idn.call("set_skill_frame", 6, 1, true)     # Card06 Skill2 坚韧（东场）→ 红色框
	var oc = st.get("oracle")
	if typeof(oc) == TYPE_DICTIONARY and bool((oc as Dictionary).get("on", false)):
		idn.call("set_skill_frame", 7, 0, true)     # Card07 S1 降神（打开中）→ 红色框


# ── Card06 Skill1「南风」──────────────────────────────────────────────
#   南场配牌时发动：先指定两种牌（34 种里选 2），再选两张手牌，
#   按 下家→对家→上家 的顺序，把他家手里「指定的牌」强制换过来（换满两张就结束）。
var sw_stage := ""                 # "" / "kinds" / "hand"
var sw_kinds: Array[String] = []
var sw_ui: Control = null          # 34 种牌的选择界面
var sw_start_btn: TextureButton = null
var sw_frames := {}                # kind -> [ReferenceRect]
var sw_hand_picks: Array[int] = []
var sw_hand_ui: Control = null
var sw_hand_btn: TextureButton = null

const SW_TILE_W := 92.0
const SW_TILE_H := 134.0


func _sw_activate() -> void:
	if String(srv_state.get("phase", "")) != "deal_skill":
		_toast("「南风」要在南场的配牌阶段发动")
		return
	var mine: Array = srv_state.get("deal_skill", {}).get("mine", [])
	var ok := false
	for o in mine:
		if typeof(o) == TYPE_DICTIONARY and int((o as Dictionary).get("card", 0)) == 6:
			ok = true
	if not ok:
		_toast("「南风」只在南场可用")
		return
	if not is_inside_tree():
		return
	var r := srv_request({"op": "deal_skill", "seat": my_seat,
		"action": "use", "card": 6, "skill": 1})
	if r.is_empty():
		_toast(_srv_err("「南风」发动失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return
	var dr: Dictionary = r.get("deal_skill", {})
	if not bool(dr.get("armed", false)):
		_toast(String(dr.get("reason", "现在不能发动「南风」")))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	var idn := get_node_or_null("Identity")
	if idn != null and idn.has_method("collapse_skills"):
		idn.call("collapse_skills", 6)


func _sw_sync(st: Dictionary) -> void:
	var f = st.get("deal_flow")
	var kind := ""
	if typeof(f) == TYPE_DICTIONARY:
		kind = String((f as Dictionary).get("kind", ""))
	if kind != "south_wind" or int((f as Dictionary).get("seat", -1)) != my_seat:
		if sw_stage != "":
			_sw_close()
		return
	var stage := String((f as Dictionary).get("stage", ""))
	_set_deal_skip_visible(false)   # 南风选牌期间别让「开始（跳过）」抢点击
	if stage == "kinds":
		if sw_stage != "kinds":
			sw_stage = "kinds"
			sw_hand_picks.clear()
			_sw_open_picker()
			_toast("南风：先在全部牌里指定两种牌")
	elif stage == "hand":
		if sw_stage != "hand":
			sw_stage = "hand"
			_sw_close_picker()
			hand_pick.begin(sw_hand_picks, 2, {"on_change": _refresh_sw_hand_btn})
			_make_sw_hand_ui()
			_update_sw_view()
			_refresh_sw_hand_btn()
			_toast("南风：再选两张手牌，按 下家→对家→上家 的顺序换牌")


func _sw_open_picker() -> void:
	if sw_ui != null:
		return
	sw_kinds.clear()
	sw_frames.clear()
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	sw_ui = Control.new()
	sw_ui.name = "SouthWindUI"
	sw_ui.z_index = 262
	host.add_child(sw_ui)
	sw_ui.position = Vector2.ZERO

	var bg := ColorRect.new()
	bg.color = Color(0.02, 0.03, 0.06, 0.84)
	bg.size = vp
	bg.mouse_filter = Control.MOUSE_FILTER_STOP
	sw_ui.add_child(bg)

	var title := Label.new()
	title.text = "南风：指定两种牌（单击选中 / 再点取消），选好后点「开始」"
	title.add_theme_font_size_override("font_size", 30)
	title.add_theme_color_override("font_color", Color(1.0, 0.96, 0.8))
	title.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	title.add_theme_constant_override("outline_size", 6)
	title.position = Vector2(0, 120)
	title.size = Vector2(vp.x, 40)
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	sw_ui.add_child(title)

	var kinds := TileBank.TILE_KINDS
	var n := kinds.size()
	var per_row := 9
	var rows := int(ceil(float(n) / float(per_row)))
	var gap := 10.0
	var y0 := 210.0
	for i in range(n):
		var kind := String(kinds[i])
		var row := i / per_row
		var col := i % per_row
		var in_row := mini(per_row, n - row * per_row)
		var this_w := float(in_row) * SW_TILE_W + float(in_row - 1) * gap
		var bx := (vp.x - this_w) * 0.5 + float(col) * (SW_TILE_W + gap)
		var by := y0 + float(row) * (SW_TILE_H + gap)
		var b := TextureButton.new()
		b.name = "K%d" % i
		b.texture_normal = load(TileBank.VERT_DIR + TileBank.face_file(kind) + ".png")
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		b.position = Vector2(bx, by)
		b.size = Vector2(SW_TILE_W, SW_TILE_H)
		b.pressed.connect(_sw_toggle_kind.bind(kind))
		sw_ui.add_child(b)
		var f := SelFrame.attach(b, b.size)          # 选中：彩框图
		if not sw_frames.has(kind):
			sw_frames[kind] = []
		(sw_frames[kind] as Array).append(f)

	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	sw_start_btn = TextureButton.new()
	sw_start_btn.name = "SWStart"
	sw_start_btn.texture_normal = tex
	sw_start_btn.ignore_texture_size = true
	sw_start_btn.stretch_mode = TextureButton.STRETCH_SCALE
	sw_start_btn.focus_mode = Control.FOCUS_NONE
	sw_start_btn.size = Vector2(bw, bh)
	sw_start_btn.position = prompt_btn_pos(bw, bh)
	sw_start_btn.visible = false
	sw_start_btn.pressed.connect(_sw_confirm_kinds)
	sw_ui.add_child(sw_start_btn)


func _sw_toggle_kind(kind: String) -> void:
	if sw_stage != "kinds":
		return
	if sw_kinds.has(kind):
		sw_kinds.erase(kind)
	elif sw_kinds.size() < 2:
		sw_kinds.append(kind)
	else:
		_toast("已经选够两种了")
		return
	_sw_refresh_frames()
	if sw_start_btn != null:
		sw_start_btn.visible = sw_kinds.size() == 2


func _sw_refresh_frames() -> void:
	for kind in sw_frames.keys():
		var on := sw_kinds.has(String(kind))
		for f in (sw_frames[kind] as Array):
			if f != null and is_instance_valid(f):
				(f as Node2D).visible = on


func _sw_confirm_kinds() -> void:
	if sw_kinds.size() != 2:
		return
	var r := srv_request({"op": "south_wind_kinds", "seat": my_seat,
		"kinds": sw_kinds.duplicate()})
	if r.is_empty():
		_toast(_srv_err("南风选牌失败：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "南风选牌失败")))
		return
	srv_apply_state(r.get("state"), r.get("events"))


func _sw_close_picker() -> void:
	sw_kinds.clear()
	sw_frames.clear()
	if sw_start_btn != null and is_instance_valid(sw_start_btn):
		sw_start_btn.visible = false
	if sw_ui != null and is_instance_valid(sw_ui):
		sw_ui.queue_free()
	sw_ui = null
	sw_start_btn = null


func _make_sw_hand_ui() -> void:
	if sw_hand_ui != null:
		return
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	sw_hand_ui = Control.new()
	sw_hand_ui.name = "SouthWindHandUI"
	sw_hand_ui.z_index = 250
	host.add_child(sw_hand_ui)
	sw_hand_ui.position = Vector2.ZERO
	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	sw_hand_btn = TextureButton.new()
	sw_hand_btn.name = "SWHandStart"
	sw_hand_btn.texture_normal = tex
	sw_hand_btn.ignore_texture_size = true
	sw_hand_btn.stretch_mode = TextureButton.STRETCH_SCALE
	sw_hand_btn.focus_mode = Control.FOCUS_NONE
	sw_hand_btn.size = Vector2(bw, bh)
	sw_hand_btn.position = prompt_btn_pos(bw, bh)
	sw_hand_btn.visible = false
	sw_hand_btn.pressed.connect(_sw_confirm_hand)
	sw_hand_ui.add_child(sw_hand_btn)


func _update_sw_view() -> void:
	hand_pick.sync()                     # 手牌变暗统一由 hand_pick 负责


func _toggle_sw_hand(index: int) -> void:
	if sw_stage != "hand":
		return
	hand_pick.toggle(index)              # 选牌视觉/张数上限都由 hand_pick 管


func _refresh_sw_hand_btn() -> void:
	if sw_hand_btn == null or not is_instance_valid(sw_hand_btn):
		return
	sw_hand_btn.visible = sw_stage == "hand" and hand_pick.ready()


func _sw_confirm_hand() -> void:
	if sw_stage != "hand" or sw_hand_picks.size() != 2:
		return
	var tiles := display_tiles()
	var picked: Array = []
	for i in sw_hand_picks:
		if i >= 0 and i < tiles.size():
			picked.append(String(tiles[i]))
	if picked.size() != 2:
		return
	var r := srv_request({"op": "south_wind_swap", "seat": my_seat, "tiles": picked})
	if r.is_empty():
		_toast(_srv_err("南风换牌失败：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "南风换牌失败")))
		return
	var sw: Dictionary = r.get("south_wind", {})
	var log: Array = sw.get("swaps", [])
	var infos: Array = []
	for s in log:
		if typeof(s) == TYPE_DICTIONARY:
			infos.append("%s→%s" % [String((s as Dictionary).get("gave", "")),
				String((s as Dictionary).get("got", ""))])
	srv_apply_state(r.get("state"), r.get("events"))
	_sw_close()
	if infos.is_empty():
		_toast("南风：三家都没有指定的牌，技能结束")
	else:
		_toast("南风：换牌 %s" % "、".join(infos))


func _sw_close() -> void:
	if sw_stage == "" and sw_ui == null and sw_hand_ui == null:
		return
	sw_stage = ""
	sw_hand_picks.clear()
	hand_pick.end()
	_sw_close_picker()
	if sw_hand_btn != null and is_instance_valid(sw_hand_btn):
		sw_hand_btn.visible = false
	if sw_hand_ui != null and is_instance_valid(sw_hand_ui):
		sw_hand_ui.queue_free()
	sw_hand_ui = null
	sw_hand_btn = null
	_set_deal_skip_visible(true)
	_update_sw_view()


# ── Card05 Skill1「策略」──────────────────────────────────────────────
#   ① 被人看手牌：先盖住最多 3 张（服务端 view_hand 触发）
#   ② 别人技能动了我的手牌：可以从王牌 / 弃牌里换一张（明暗跟着位置走）
#   ③ 别人害我不能正常摸切 → 计数 +1；花 1 点，切牌后再摸一张再切一张
var c05_counter_label: Label = null

var c05_active := false
var c05_picks: Array[int] = []
var c05_target: Dictionary = {}
var c05_ui: Control = null
var c05_start_btn: TextureButton = null
var c05_dead_layer: Control = null
var c05_dead_map := {}           # 墩号 -> Button（位置每帧跟牌墩走，见 _sync_c05_dead_buttons）
var c05_choice: Control = null

var c05_hide_active := false
var c05_hide_picks: Array[int] = []
var c05_hide_ui: Control = null
var c05_hide_btn: TextureButton = null


# 拔北：手里有北（或刚摸到北）→ 把北放到牌河，正常牌山补一张再切
func _c05_nuki() -> void:
	if String(srv_state.get("phase", "")) != "discard" \
			or int(srv_state.get("turn", -1)) != my_seat:
		_toast("「拔北」要在自己的出牌回合发动")
		return
	if not display_tiles().has("bei"):
		_toast("手里没有北")
		return
	var r := srv_request({"op": "card05_nuki", "seat": my_seat})
	if r.is_empty():
		_toast(_srv_err("拔北失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "拔北失败")))
		return
	var nk: Dictionary = r.get("nuki", {})
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("拔北：补到 %s，继续切牌（本局拔北 %d 次，和牌 +%d 番）"
		% [String(nk.get("drawn", "")), int(nk.get("nuki", 0)), int(nk.get("nuki", 0))])


func _c05_state() -> Dictionary:
	var c = srv_state.get("card05")
	return c if typeof(c) == TYPE_DICTIONARY else {}


# 「策略」还有一次换牌机会吗（客户端判断用，不走服务端）
func _c05_has_offer() -> bool:
	var c = _c05_state()
	return typeof(c.get("offer")) == TYPE_DICTIONARY


func _c05_skill() -> void:
	if c05_hide_active or c05_active:
		return
	var c := _c05_state()
	if String(srv_state.get("phase", "")) != "discard" or int(srv_state.get("turn", -1)) != my_seat:
		_toast("「策略」要在自己的出牌回合发动")
		return
	if drawn_tile == "":
		_toast("摸牌之后才能发动「策略」")
		return
	if bool(c.get("extra", false)):
		_toast("「策略」这一回合已经发动过了")
		return
	if int(c.get("counter", 0)) <= 0:
		_toast("「策略」计数是 0：要等别人用技能害你不能正常摸切")
		return
	var r := srv_request({"op": "card05_extra", "seat": my_seat})
	if srv_kangpo_blocked(r):
		return
	if r.is_empty():
		_toast(_srv_err("「策略」发动失败：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "「策略」发动失败")))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	var left: Dictionary = r.get("card05", {})
	_toast("策略：本回合切牌后会再摸一张（剩 %d 次）" % int(left.get("counter", 0)))


# ── ③ 计数器显示 ─────────────────────────────────────────────
func _c05_counter_sync(st: Dictionary) -> void:
	var c = st.get("card05")
	var n := int((c as Dictionary).get("counter", 0)) if typeof(c) == TYPE_DICTIONARY else 0
	if n <= 0:
		if c05_counter_label != null and is_instance_valid(c05_counter_label):
			c05_counter_label.visible = false
		return
	if c05_counter_label == null or not is_instance_valid(c05_counter_label):
		var host: Node = get_parent()
		if host == null:
			host = self
		c05_counter_label = Label.new()
		c05_counter_label.name = "Card05Counter"
		c05_counter_label.z_index = 240
		c05_counter_label.add_theme_font_size_override("font_size", 26)
		c05_counter_label.add_theme_color_override("font_color", Color(1.0, 0.92, 0.45))
		c05_counter_label.add_theme_color_override("font_outline_color", Color(0, 0, 0))
		c05_counter_label.add_theme_constant_override("outline_size", 5)
		host.add_child(c05_counter_label)
		c05_counter_label.position = Vector2(28, get_viewport_rect().size.y - 300)
		c05_counter_label.size = Vector2(220, 40)
	c05_counter_label.visible = true
	c05_counter_label.text = "策略 ×%d" % n


# ── ② 换牌：王牌 / 弃牌 ──────────────────────────────────────
func _make_c05_ui() -> void:
	if c05_ui != null:
		return
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	c05_ui = Control.new()
	c05_ui.name = "Card05UI"
	c05_ui.z_index = 250
	host.add_child(c05_ui)
	c05_ui.position = Vector2.ZERO

	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	c05_start_btn = TextureButton.new()
	c05_start_btn.name = "C05Start"
	c05_start_btn.texture_normal = tex
	c05_start_btn.ignore_texture_size = true
	c05_start_btn.stretch_mode = TextureButton.STRETCH_SCALE
	c05_start_btn.focus_mode = Control.FOCUS_NONE
	c05_start_btn.size = Vector2(bw, bh)
	c05_start_btn.position = prompt_btn_pos(bw, bh)
	c05_start_btn.visible = false
	c05_start_btn.pressed.connect(_c05_confirm)
	c05_ui.add_child(c05_start_btn)

	var cancel := ui_btn("pass", 200.0)         # 取消换牌：贴图，不叠字
	cancel.name = "C05Cancel"
	cancel.position = Vector2(vp.x - 230.0, 150.0)
	cancel.pressed.connect(func(): _c05_close(true))
	c05_ui.add_child(cancel)


	# 六个王牌牌墩的点击区
	c05_dead_layer = Control.new()
	c05_dead_layer.name = "DeadStacks"
	c05_dead_layer.z_index = 251
	c05_ui.add_child(c05_dead_layer)
	_build_c05_dead_buttons()


# 王牌 6 墩的点击区。牌山可能还没摆好 → 同步时再补一次（只在还没有按钮时补）。
func _build_c05_dead_buttons() -> void:
	if c05_dead_layer == null or not is_instance_valid(c05_dead_layer):
		return
	if c05_dead_layer.get_child_count() > 0:
		return
	var first := int(srv_state.get("first_stack", 0))
	if first > 0:
		for i in range(1, 7):
			var k := ((first - i - 1) % 68 + 68) % 68 + 1
			var st := {}
			for s in wall_stacks:
				if int(s.get("no", 0)) == k:
					st = s
					break
			if st.is_empty():
				continue
			var vis = st.get("vis", null)
			if vis == null or not is_instance_valid(vis):
				continue
			var b := Button.new()
			b.name = "Dead%d" % k
			b.flat = true
			b.focus_mode = Control.FOCUS_NONE
			b.modulate = Color(1, 1, 1, 0.18)
			b.size = _dead_btn_size(vis)
			b.tooltip_text = "王牌（第 %d 墩）" % k
			b.pressed.connect(_c05_choose_dead.bind(k))
			c05_dead_layer.add_child(b)
			b.global_position = (vis as Node2D).global_position - b.size * 0.5
			c05_dead_map[k] = b
			# 看得见的彩框：不然玩家根本不知道王牌哪一墩能点
			SelFrame.attach(b, b.size, SelFrame.TEX_YELLOW,
				Color(1, 1, 1, 1), true)


# 王牌点击区的大小：取牌墩里那张 Sprite 的实际显示尺寸（原来是写死 76x100，
# 和真实牌面差一截，点上去就感觉「框和牌不重合」）
func _dead_btn_size(vis) -> Vector2:
	var node := vis as Node2D
	if node != null:
		var sp := node.get_node_or_null("Sprite2D") as Sprite2D
		if sp != null and sp.texture != null:
			var sz: Vector2 = sp.texture.get_size() * sp.global_scale
			if sz.x > 4.0 and sz.y > 4.0:
				return sz
	return Vector2(76.0, 107.0)


# 位置每帧跟牌墩走。牌山会重建（_refresh_wall_stacks），只在创建时取一次的话，
# 重建后按钮就停在旧位置 —— 这就是「牌墩和识别位置严重偏移」的原因。
func _sync_c05_dead_buttons() -> void:
	if c05_dead_map.is_empty():
		return
	var live := {}
	for st in wall_stacks:
		live[int(st.get("no", 0))] = st.get("vis", null)
	for k in c05_dead_map.keys():
		var b := c05_dead_map[k] as Button
		if b == null or not is_instance_valid(b):
			continue
		var v := live.get(int(k), null) as Node2D
		if v == null or not is_instance_valid(v):
			b.visible = false
			continue
		b.visible = true
		var want := v.global_position - b.size * 0.5
		if b.global_position.distance_to(want) > 0.5:
			b.global_position = want


func _c05_choose_dead(stack: int) -> void:
	# 位置现场取（牌山可能已经重建过），不要用创建时的旧坐标
	var pos := Vector2.ZERO
	for s in wall_stacks:
		if int(s.get("no", 0)) == stack:
			var v := s.get("vis", null) as Node2D
			if v != null and is_instance_valid(v):
				pos = v.global_position
			break
	_c05_choice_close()
	var vp := get_viewport_rect().size
	c05_choice = Control.new()
	c05_choice.name = "DeadChoice"
	c05_choice.z_index = 255
	c05_ui.add_child(c05_choice)

	var shade := ColorRect.new()               # 空白处：取消（半透明，点得到）
	shade.color = Color(0, 0, 0, 0.35)
	shade.size = vp
	shade.mouse_filter = Control.MOUSE_FILTER_STOP
	shade.gui_input.connect(_c05_shade_input)
	c05_choice.add_child(shade)

	var hint := Label.new()
	hint.text = "选上面 / 下面那张；点空白处取消"
	hint.add_theme_font_size_override("font_size", 26)
	hint.add_theme_color_override("font_color", Color(1, 1, 1, 0.9))
	hint.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	hint.add_theme_constant_override("outline_size", 6)
	hint.position = Vector2(0, pos.y + 110.0)
	hint.size = Vector2(vp.x, 40)
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	hint.mouse_filter = Control.MOUSE_FILTER_IGNORE
	c05_choice.add_child(hint)

	var back := load(TileBank.BACK_DIR + TileBank.BACK_KEY + ".png") as Texture2D
	var cw := 120.0
	var ch := 170.0
	# 两张示意牌优先摆在牌墩上方；上面放不下（上排的墩）就摆到下面
	var cy := pos.y - ch - 24.0
	if cy < 40.0:
		cy = pos.y + 40.0
	if cy + ch > vp.y - 20.0:
		cy = vp.y - 20.0 - ch
	var cx0 := pos.x - cw - 18.0
	var cx1 := pos.x + 18.0
	if cx0 < 12.0:
		cx0 = 12.0
	if cx1 + cw > vp.x - 12.0:
		cx1 = vp.x - 12.0 - cw
	for i in range(2):
		var b := TextureButton.new()
		b.name = "Pick%d" % i
		b.texture_normal = back
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		b.size = Vector2(cw, ch)
		b.position = Vector2(cx0 if i == 0 else cx1, cy)
		b.pressed.connect(_c05_pick_dead.bind(stack, "top" if i == 0 else "bottom"))
		c05_choice.add_child(b)
		var tag := Label.new()
		tag.text = "上" if i == 0 else "下"
		tag.add_theme_font_size_override("font_size", 30)
		tag.add_theme_color_override("font_color", Color(1, 1, 1))
		tag.add_theme_color_override("font_outline_color", Color(0, 0, 0))
		tag.add_theme_constant_override("outline_size", 6)
		tag.position = Vector2(cw * 0.5 - 18, ch + 6)
		tag.size = Vector2(40, 40)
		tag.mouse_filter = Control.MOUSE_FILTER_IGNORE
		b.add_child(tag)


func _c05_shade_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		if mb.pressed and mb.button_index == MOUSE_BUTTON_LEFT:
			_c05_choice_close()


func _c05_choice_close() -> void:
	if c05_choice != null and is_instance_valid(c05_choice):
		c05_choice.queue_free()
	c05_choice = null


func _c05_pick_dead(stack: int, half: String) -> void:
	c05_target = {"kind": "dead", "stack": stack, "half": half}
	_c05_choice_close()
	_update_c05_view()
	_refresh_c05_button()


func _update_c05_view() -> void:
	if tile_bank == null:
		return
	var river_sel := -1
	if String(c05_target.get("kind", "")) == "river":
		river_sel = int(c05_target.get("seq", -1))
	hand_pick.sync()
	for q in tile_bank.all_pieces():
		var tp := q as TilePiece
		if tp == null or not tp.visible:
			continue
		if tp.form == "river" or tp.form == "back":
			if c05_active:
				tp.set_river_clickable(true)
				tp.set_selected_frame(tp.discard_seq == river_sel)
			elif not press_panel.active and not swap_panel.active:
				tp.set_river_clickable(false)
				tp.set_selected_frame(false)


func _refresh_c05_button() -> void:
	if c05_start_btn == null or not is_instance_valid(c05_start_btn):
		return
	c05_start_btn.visible = c05_active and hand_pick.ready() and not c05_target.is_empty()


func _toggle_c05_hand(index: int) -> void:
	if not c05_active:
		return
	hand_pick.toggle(index)


func _c05_pick_river(seq: int) -> void:
	if not c05_active:
		return
	if String(c05_target.get("kind", "")) == "river" and int(c05_target.get("seq", -1)) == seq:
		c05_target = {}
	else:
		c05_target = {"kind": "river", "seq": seq}
	_c05_choice_close()
	_update_c05_view()
	_refresh_c05_button()


func _c05_confirm() -> void:
	if not c05_active or c05_picks.is_empty() or c05_target.is_empty():
		return
	var tiles := display_tiles()
	if int(c05_picks[0]) >= tiles.size():
		return
	var hand := String(tiles[int(c05_picks[0])])
	var r := srv_request({"op": "card05_swap", "seat": my_seat, "hand": hand,
		"kind": String(c05_target.get("kind", "")),
		"stack": int(c05_target.get("stack", 0)),
		"half": String(c05_target.get("half", "top")),
		"river": int(c05_target.get("seq", -1))})
	if r.is_empty() or not bool(r.get("ok", false)):
		_toast(_srv_err(String(r.get("error", "策略换牌失败：服务端没有回应"))))
		# 不管失败原因，先把最新状态拉回来：换牌其实已经生效、或者机会已经作废，
		# 界面都必须跟着关掉，不能把整个客户端卡在选牌界面里。
		var st := srv_request({"op": "state", "seat": my_seat})
		if not st.is_empty():
			srv_apply_state(st.get("state"), [])
		if c05_active and not _c05_has_offer():
			_c05_close(false)
		return
	var sw: Dictionary = r.get("card05_swap", {})
	var got := String(sw.get("got", ""))
	srv_apply_state(r.get("state"), r.get("events"))
	_c05_close(false)
	_toast("策略：用 %s 换到 %s" % [hand, got])


func _c05_close(cancel: bool) -> void:
	if not cancel and not c05_active and c05_ui == null:
		return                                    # 已经收起来了
	if cancel:
		var r := srv_request({"op": "card05_cancel", "seat": my_seat})
		if not r.is_empty():
			srv_apply_state(r.get("state"), r.get("events"))
	c05_active = false
	c05_picks.clear()
	hand_pick.end()
	c05_target = {}
	_c05_choice_close()
	if c05_start_btn != null and is_instance_valid(c05_start_btn):
		c05_start_btn.visible = false
	if c05_ui != null and is_instance_valid(c05_ui):
		c05_ui.queue_free()
	c05_ui = null
	c05_start_btn = null
	c05_dead_layer = null
	c05_dead_map.clear()
	_update_c05_view()


func _c05_sync(st: Dictionary) -> void:
	var c = st.get("card05")
	var offer = (c as Dictionary).get("offer") if typeof(c) == TYPE_DICTIONARY else null
	if typeof(offer) != TYPE_DICTIONARY:
		if c05_active:
			_c05_close(false)
		return
	if c05_active:
		_build_c05_dead_buttons()               # 牌山晚一点才摆好时补上点击区
		return                                  # 已经在选了：轮询别动我的选牌
	c05_active = true
	c05_target = {}
	hand_pick.begin(c05_picks, 1, {"on_change": _refresh_c05_button})
	_make_c05_ui()
	_update_c05_view()
	_refresh_c05_button()
	var by := int((offer as Dictionary).get("by", -1))
	_toast("%s 的技能动了你的手牌：选 1 张手牌，再选王牌 / 弃牌换一张"
		% _rel_seat_name(by))


# ── ① 被看手牌：盖住最多三张 ─────────────────────────────────
func _make_c05_hide_ui() -> void:
	if c05_hide_ui != null:
		return
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	c05_hide_ui = Control.new()
	c05_hide_ui.name = "Card05HideUI"
	c05_hide_ui.z_index = 250
	host.add_child(c05_hide_ui)
	c05_hide_ui.position = Vector2.ZERO
	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	c05_hide_btn = TextureButton.new()
	c05_hide_btn.name = "HideStart"
	c05_hide_btn.texture_normal = tex
	c05_hide_btn.ignore_texture_size = true
	c05_hide_btn.stretch_mode = TextureButton.STRETCH_SCALE
	c05_hide_btn.focus_mode = Control.FOCUS_NONE
	c05_hide_btn.size = Vector2(bw, bh)
	c05_hide_btn.position = prompt_btn_pos(bw, bh)
	c05_hide_btn.visible = false
	c05_hide_btn.pressed.connect(_c05_hide_confirm)
	c05_hide_ui.add_child(c05_hide_btn)


func _toggle_c05_hide_hand(index: int) -> void:
	if not c05_hide_active:
		return
	hand_pick.toggle(index)


func _refresh_c05_hide_button() -> void:
	if c05_hide_btn == null or not is_instance_valid(c05_hide_btn):
		return
	c05_hide_btn.visible = c05_hide_active and c05_hide_picks.size() >= mini(3, display_tiles().size())


func _c05_hide_confirm() -> void:
	if not c05_hide_active:
		return
	var tiles := display_tiles()
	var picked: Array = []
	for i in c05_hide_picks:
		if i >= 0 and i < tiles.size():
			picked.append(String(tiles[i]))
	if picked.is_empty():
		return
	var r := srv_request({"op": "card05_hide", "seat": my_seat, "tiles": picked})
	if r.is_empty():
		_toast(_srv_err("盖牌失败：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "盖牌失败")))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	_c05_hide_close()
	_toast("策略：已盖住 %d 张手牌" % picked.size())


func _c05_hide_close() -> void:
	if not c05_hide_active and c05_hide_ui == null:
		return                                    # 已经收起来了
	c05_hide_active = false
	c05_hide_picks.clear()
	hand_pick.end()
	if c05_hide_btn != null and is_instance_valid(c05_hide_btn):
		c05_hide_btn.visible = false
	if c05_hide_ui != null and is_instance_valid(c05_hide_ui):
		c05_hide_ui.queue_free()
	c05_hide_ui = null
	c05_hide_btn = null
	_update_c05_view()


func _c05_hide_sync(st: Dictionary) -> void:
	var c = st.get("card05")
	var need := bool((c as Dictionary).get("hide_request", false)) if typeof(c) == TYPE_DICTIONARY else false
	if not need:
		if c05_hide_active:
			_c05_hide_close()
		return
	if c05_hide_active:
		return
	c05_hide_active = true
	hand_pick.begin(c05_hide_picks, 3, {"min": 1, "on_change": _refresh_c05_hide_button})
	_make_c05_hide_ui()
	_update_c05_view()
	_refresh_c05_hide_button()
	_toast("有人要看你的手牌：选最多 3 张盖住不给他看")


# ── Card04 Skill2「自风」──────────────────────────────────────────────
#   发动过「风神」后自动生效（图标红框、不能取消）：
#   其他家摸到我的自风时，他不能切牌，我选 1 张手牌跟他刚摸到的自风交换。
const WIND_TILE_CN := {"dong": "东", "nan": "南", "xi": "西", "bei": "北"}
var wind_active := false
var wind_picks: Array[int] = []
var wind_from := -1
var wind_tile := ""
var wind_ui: Control = null
var wind_start_btn: TextureButton = null


func _self_wind_tip() -> void:
	if bool(srv_state.get("self_wind", false)):
		_toast("「自风」已自动发动：别人摸到你的自风时会和你换一张手牌")
	else:
		_toast("「自风」要发动过「风神」之后才会自动生效")


# Card06 Skill2「坚韧」：被动，不用点。东场里自己付的钱减半（向上取整到百位）。
func _tenacity_tip() -> void:
	if bool(srv_state.get("tenacity", false)):
		_toast("「坚韧」正在生效：东场里你被自摸 / 放铳的失点减半")
	else:
		_toast("「坚韧」只在东场生效（南场没有这个技能）")


func _make_wind_ui() -> void:
	if wind_ui != null:
		return
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	wind_ui = Control.new()
	wind_ui.name = "SelfWindUI"
	wind_ui.z_index = 250
	host.add_child(wind_ui)
	wind_ui.position = Vector2.ZERO

	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	wind_start_btn = TextureButton.new()
	wind_start_btn.name = "WindStart"
	wind_start_btn.texture_normal = tex
	wind_start_btn.ignore_texture_size = true
	wind_start_btn.stretch_mode = TextureButton.STRETCH_SCALE
	wind_start_btn.focus_mode = Control.FOCUS_NONE
	wind_start_btn.size = Vector2(bw, bh)
	wind_start_btn.position = prompt_btn_pos(bw, bh)
	wind_start_btn.visible = false
	wind_start_btn.pressed.connect(_wind_confirm)
	wind_ui.add_child(wind_start_btn)



func _update_wind_view() -> void:
	hand_pick.sync()                     # 手牌变暗统一由 hand_pick 负责


func _toggle_wind_hand(index: int) -> void:
	if not wind_active:
		return
	hand_pick.toggle(index)


func _refresh_wind_button() -> void:
	if wind_start_btn == null or not is_instance_valid(wind_start_btn):
		return
	wind_start_btn.visible = wind_active and hand_pick.ready()


func _wind_sync(st: Dictionary) -> void:
	var w = st.get("wind_swap")
	if typeof(w) != TYPE_DICTIONARY or int((w as Dictionary).get("owner", -1)) != my_seat:
		_wind_close()
		return
	var frm := int((w as Dictionary).get("from", -1))
	var tile := String((w as Dictionary).get("tile", ""))
	if wind_active and frm == wind_from and tile == wind_tile:
		return
	wind_active = true
	wind_from = frm
	wind_tile = tile
	hand_pick.begin(wind_picks, 1, {"on_change": _refresh_wind_button})
	_make_wind_ui()
	_update_wind_view()
	_refresh_wind_button()
	_toast("%s 摸到了你的自风【%s】—— 选 1 张手牌交换"
		% [_rel_seat_name(frm), String(WIND_TILE_CN.get(tile, tile))])


func _wind_confirm() -> void:
	if not wind_active or wind_picks.is_empty():
		return
	var tiles := display_tiles()
	if int(wind_picks[0]) >= tiles.size():
		return
	var tile := String(tiles[int(wind_picks[0])])
	var r := srv_request({"op": "wind_swap", "seat": my_seat, "tile": tile})
	if r.is_empty():
		_toast(_srv_err("自风交换失败：服务端没有回应"))
		_wind_close()
		return
	var got := String((r.get("wind_swap", {}) as Dictionary).get("got", ""))
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("自风：用 %s 换到【%s】" % [tile, String(WIND_TILE_CN.get(got, got))])


func _wind_close() -> void:
	if not wind_active and wind_ui == null:
		return                                    # 已经收起来了，别每帧扫一遍牌
	wind_active = false
	wind_picks.clear()
	hand_pick.end()
	wind_from = -1
	wind_tile = ""
	if wind_start_btn != null and is_instance_valid(wind_start_btn):
		wind_start_btn.visible = false
	if wind_ui != null and is_instance_valid(wind_ui):
		wind_ui.queue_free()
	wind_ui = null
	wind_start_btn = null
	_update_wind_view()


# ── Card04 Skill1「风神」──────────────────────────────────────────────
#   配牌时发动：先和下家、再和对家、最后和上家交换「对方所有风牌」。
#   每一家先读出对方手里风牌数 n → 自己选 n 张手牌 → 开始按钮确认 → 交换。
#   三家都换完这次配牌技能才算做完（庄家才能切牌）。
var flow_active := false
var flow_picks: Array[int] = []
var flow_n := 0
var flow_stage := -1
var flow_target := -1
var flow_ui: Control = null
var flow_start_btn: TextureButton = null
var flow_kind := "fengshen"                  # 这套流程是哪个技能（风神 / 宝牌运）

# ── Card25 Skill1「宝牌运」：切宝牌二次确认 ──
var c25_confirm_tile := ""
var c25_ui: Control = null
var c25_layer: CanvasLayer = null            # 人物卡挂在 CanvasLayer(20)，必须再上一层
var c25_btn: TextureButton = null


func _rel_seat_name(seat: int) -> String:
	match (seat - my_seat + 4) % 4:
		1:
			return "下家"
		2:
			return "对家"
		3:
			return "上家"
	return "自己"


# ── Card25 Skill1「宝牌运」────────────────────────────────────────
#   配牌时发动：依次把下家/对家/上家的宝牌换过来（我出等量的非宝牌）。
#   之后本局开启：切宝牌要先确认一次，确认了 -9000 / 三家各 +3000、本局不能胡牌。
func srv_c25_on() -> bool:
	return bool(srv_state.get("c25_on", false))


func srv_c25_kinds() -> Array:
	var ks = srv_state.get("c25_kinds")
	return ks if typeof(ks) == TYPE_ARRAY else []


# 这张牌是不是宝牌（赤 5 本身就算宝牌，跟服务端口径一致）
func srv_is_dora(tile_id: String) -> bool:
	var t := String(tile_id)
	if t.begins_with("0"):
		return true
	for k in srv_c25_kinds():
		if String(k) == t:
			return true
	return false


func _dora_luck_activate() -> void:
	if String(srv_state.get("phase", "")) != "deal_skill":
		_toast("「宝牌运」只能在配牌阶段发动")
		return
	if srv_state.get("deal_flow") != null:
		return
	if not is_inside_tree():
		return
	var r := srv_request({"op": "deal_skill", "seat": my_seat,
		"action": "use", "card": 25, "skill": 1})
	if r.is_empty():
		_toast(_srv_err("「宝牌运」发动失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return
	var dr: Dictionary = r.get("deal_skill", {})
	if not bool(dr.get("armed", false)):
		_toast(String(dr.get("reason", "现在不能发动「宝牌运」")))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	var idn := get_node_or_null("Identity")
	if idn != null and idn.has_method("collapse_skills"):
		idn.call("collapse_skills", 25)


# 「开始」按钮 = 取消这次切宝牌（用户口径：点它可以重新切牌）
func _c25_confirm_make() -> void:
	if c25_ui != null and is_instance_valid(c25_ui):
		return
	var host: Node = get_parent()
	if host == null:
		host = self
	c25_layer = CanvasLayer.new()
	c25_layer.name = "C25ConfirmLayer"
	c25_layer.layer = 30                     # 人物卡在 layer=20，同 canvas 怎么调 z_index 都压不过
	host.add_child(c25_layer)
	c25_ui = Control.new()
	c25_ui.name = "C25ConfirmUI"
	c25_ui.z_index = 1600                    # 牌面按 y 当 z_index（能到 1000+），必须压过它们
	c25_ui.position = Vector2.ZERO
	c25_layer.add_child(c25_ui)
	var tex := btn_tex("pass")
	var aspect := 1.0
	if tex != null and tex.get_width() > 0:
		aspect = float(tex.get_width()) / float(tex.get_height())
	var rc := prompt_btn_rect(aspect)
	c25_btn = TextureButton.new()
	c25_btn.name = "C25Cancel"
	c25_btn.texture_normal = tex
	c25_btn.ignore_texture_size = true
	c25_btn.stretch_mode = TextureButton.STRETCH_SCALE
	c25_btn.focus_mode = Control.FOCUS_NONE
	c25_btn.position = rc.position
	c25_btn.size = rc.size
	c25_btn.visible = false
	c25_btn.pressed.connect(_c25_confirm_cancel)
	c25_ui.add_child(c25_btn)


func _c25_confirm_show(v: bool) -> void:
	if v:
		_c25_confirm_make()
	if c25_btn != null and is_instance_valid(c25_btn):
		c25_btn.visible = v
	if not v:
		c25_confirm_tile = ""


func _c25_confirm_cancel() -> void:
	_c25_confirm_show(false)
	_toast("宝牌运：已取消，重新选一张要切的牌")


func _deal_swap_activate() -> void:
	if String(srv_state.get("phase", "")) != "deal_skill":
		_toast("「风神」只能在配牌阶段发动")
		return
	if srv_state.get("deal_flow") != null:
		return
	if not is_inside_tree():
		return
	var r := srv_request({"op": "deal_skill", "seat": my_seat,
		"action": "use", "card": 4, "skill": 1})
	if r.is_empty():
		_toast(_srv_err("「风神」发动失败：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return
	var dr: Dictionary = r.get("deal_skill", {})
	if not bool(dr.get("armed", false)):
		_toast(String(dr.get("reason", "现在不能发动「风神」")))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	var idn := get_node_or_null("Identity")
	if idn != null and idn.has_method("collapse_skills"):
		idn.call("collapse_skills", 4)



# ── Card30 S1【向听】──────────────────────────────────────────────
#   配牌点图标 → 选两家（东南西北）→ 按 下家/对家/上家 顺序逐家交 2~3 张
#   → 我彩框挑一张 + 选自己一张 → 互换 → 下一家。服务端不做超时兜底。
func _w30s2_tip() -> void:
	_toast("W立：立直一律算双立直（2 番）；立直和牌时若第 4 列已被摸过，里宝牌 +4 番")


func _c30s1_activate() -> void:
	if game_over:
		return
	if String(srv_state.get("phase", "")) != "deal_skill":
		_toast("「向听」只能在配牌阶段发动")
		return
	var df = srv_state.get("deal_flow")
	if typeof(df) == TYPE_DICTIONARY:
		_toast("配牌换牌已经在进行了 —— 等这一次做完")
		return
	if _skill_panel_open() and not c30_panel.active:
		_toast("先把现在的选牌面板处理掉")
		return
	c30_panel.arm_begin()


# 服务端下发 deal_flow（kind=xiangting）→ 开对应的界面
func _c30_sync(st: Dictionary) -> void:
	var f = st.get("deal_flow")
	var is_x := typeof(f) == TYPE_DICTIONARY and String((f as Dictionary).get("kind", "")) == "xiangting"
	if not is_x:
		c30_key = ""
		if c30_panel.active and String(c30_panel.mode) != "arm":
			c30_panel.close()               # 服务端已经收尾 → 面板跟着收（arm 是本地选择）
		return
	var d := f as Dictionary
	var role := String(d.get("role", ""))
	var sub := String(d.get("sub", ""))
	# ★ 别写 `d.get("picked") or []`：GDScript 的 or 是**逻辑或**，
	#   picked 缺失时得到的是 bool，后面 join 会抛脚本错误，
	#   而这段跑在 srv_apply_state 里 → srv_busy 收不回来 → 整桌卡死。
	var picked: Array = []
	var raw_picked = d.get("picked")
	if typeof(raw_picked) == TYPE_ARRAY:
		picked = raw_picked
	var picked_txt: Array = []
	for t in picked:
		picked_txt.append(String(t))
	var key := "%s-%d-%d-%s" % [role, int(d.get("stage", 0)),
		int(d.get("target", -1)), "、".join(picked_txt)]
	if role == "give":
		if c30_key == key and String(c30_panel.mode) == "give":
			return
		c30_key = key
		c30_panel.give_begin(int(d.get("from", -1)),
			int(d.get("min", 2)), int(d.get("max", 3)))
		return
	if role != "swap" or sub != "swap":
		return                              # 我这边在等对方交牌
	if c30_key == key and String(c30_panel.mode) == "swap":
		return
	c30_key = key
	c30_panel.swap_begin(int(d.get("target", -1)), picked)


# ── Card32 S1【新手运】────────────────────────────────────────────
#   配牌点图标 → 下家、对家、上家 依次交 1 张幺九牌，我出 1 张任意牌互换。
#   对方还有配牌技能没发动 → 先「暂离」，等他选完再回来（不抢他的窗口）。
func _c32s1_activate() -> void:
	if game_over:
		return
	if String(srv_state.get("phase", "")) != "deal_skill":
		_toast("「新手运」只能在配牌阶段发动")
		return
	if typeof(srv_state.get("deal_flow")) == TYPE_DICTIONARY:
		_toast("配牌换牌已经在进行了 —— 等这一次做完")
		return
	var r := srv_request({"op": "c32s1_arm", "seat": my_seat})
	if r.is_empty():
		_toast(_srv_err("新手运：服务端没有回应"))
		return
	if srv_kangpo_blocked(r):
		return
	if not bool(r.get("ok", false)):
		_toast(_srv_err("新手运：%s" % String(r.get("error", "发动失败"))))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	_srv_kick()
	var ar: Dictionary = {}
	if typeof(r.get("c32")) == TYPE_DICTIONARY:
		ar = r.get("c32")
	if bool(ar.get("armed", false)):
		_toast("新手运：开始向他们各要一张幺九牌")


func _c32_sync(st: Dictionary) -> void:
	var f = st.get("deal_flow")
	var is_c := typeof(f) == TYPE_DICTIONARY \
		and String((f as Dictionary).get("kind", "")) == "c32"
	if not is_c:
		c32_key = ""
		if c32_panel.active:
			c32_panel.close()
		return
	var d := f as Dictionary
	var role := String(d.get("role", ""))
	var picked: Array = []
	var raw_p = d.get("picked")
	if typeof(raw_p) == TYPE_ARRAY:
		picked = raw_p
	if role == "give":
		# 暂离：他还有配牌技能没发动 → 先把面板收起来，让他玩自己的
		var mine: Array = []
		var ds = st.get("deal_skill")
		if typeof(ds) == TYPE_DICTIONARY:
			var mm = (ds as Dictionary).get("mine")
			if typeof(mm) == TYPE_ARRAY:
				mine = mm
		if not mine.is_empty():
			if c32_panel.active:
				c32_panel.close()
			c32_key = ""
			return
		var key := "give-%d-%d" % [int(d.get("stage", 0)), int(d.get("from", -1))]
		if c32_key == key and String(c32_panel.mode) == "give":
			return
		c32_key = key
		c32_panel.give_begin(int(d.get("from", -1)),
			int(d.get("min", 1)), int(d.get("max", 1)))
		return
	if role != "swap" or String(d.get("sub", "")) != "swap":
		return
	var parts: Array = []
	for t in picked:
		parts.append(String(t))
	var key2 := "swap-%d-%s" % [int(d.get("stage", 0)), "、".join(parts)]
	if c32_key == key2 and String(c32_panel.mode) == "swap":
		return
	c32_key = key2
	c32_panel.swap_begin(int(d.get("target", -1)), picked)


# ── Card33 S1【染手】─────────────────────────────────────────────────
#   摸牌后发动：默认方式选 3 张手牌 + 彩框选牌河里一组面子（3 张）→ 开始
#   换完：3 张河牌进手牌，我的 3 张手牌暗置填回那 3 个位置 → 正常切牌
func _c33_start() -> void:
	if game_over:
		return
	if swap_panel.active or press_panel.active or ym_panel.active or c24_panel.active \
			or c27_panel.active or c25b_panel.active or c30_panel.active or c32_panel.active:
		_toast("别的技能面板还开着 —— 先关掉它")
		return
	if (srv_state.get("used_skills", []) as Array).has("33-1-%d" % my_seat):
		_toast("「染手」本小局已经用过了")
		return
	if String(srv_state.get("phase", "")) != "discard" \
			or int(srv_state.get("turn", -1)) != my_seat or drawn_tile == "":
		_toast("摸牌之后才能发动「染手」")
		return
	c33_panel.begin({
		"name": "染手",
		"want": 3, "min": 3,                 # 手牌恰好 3 张
		"river": true, "river_match": true,  # 牌河也恰好 3 张（要是一组面子）
		"cancel": true,
		"river_ok": _c33_river_ok,
		"on_confirm": _c33_confirm,
	})
	_toast("染手：选 3 张手牌 + 牌河里一组面子（3 张）→ 点「开始」")


func _c33_river_ok(seq: int, seat: int, down: bool) -> bool:
	if down or int(seat) == my_seat:
		return false
	var c33 = srv_state.get("c33")
	if typeof(c33) != TYPE_DICTIONARY:
		return false
	var rs = (c33 as Dictionary).get("rivers")
	if typeof(rs) != TYPE_ARRAY:
		return false
	# ★ 服务端 state 走 JSON，数字进来是 float；Array.has(1) 对 [1.0] 是 false
	#   → 必须先转 int 再查（int_set 已成项目惯例）
	return int_set(rs).has(int(seq))


func _c33_confirm(picks: Array, rivers: Array) -> void:
	var tiles := display_tiles()
	var picked: Array = []
	# ★「手牌从左到右」：按显示下标排序，不按点击顺序
	#   （服务端按这个顺序把手牌填进 下家→对家→上家 的空位）
	var idxs: Array = picks.duplicate()
	idxs.sort()
	for i in idxs:
		if int(i) >= 0 and int(i) < tiles.size():
			picked.append(String(tiles[int(i)]))
	if picked.size() != 3 or rivers.size() != 3:
		_toast("染手：手牌 3 张 + 牌河 3 张")
		return
	var r := srv_request({"op": "c33s1_swap", "seat": my_seat,
		"hand_tiles": picked, "river": rivers.duplicate()})
	if srv_kangpo_blocked(r):
		return                               # 等对方决定是否看破；面板在 confirm 时已关
	if r.is_empty():
		_toast(_srv_err("染手：服务端没有回应"))
		_pull_state()
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "染手：发动失败")))
		_pull_state()
		return
	var got: Array = []
	if typeof(r.get("c33")) == TYPE_DICTIONARY:
		var d: Dictionary = r.get("c33")
		if typeof(d.get("got")) == TYPE_ARRAY:
			got = d.get("got")
	srv_apply_state(r.get("state"), r.get("events"))
	refresh_hand()
	_toast("染手：%s → %s（本次和牌只能混一色/清一色/字一色）"
		% ["、".join(picked), "、".join(got)])


# ── Card33 S2【记忆】─────────────────────────────────────────────────
#   切牌状态点图标 → 弹输入框 → 输入上局的结算点数（东一第一局随便输）
#   对了：接下来打出的**一张**牌暗置；然后【记忆】整场永久关闭。
func _c33s2_open() -> void:
	if game_over:
		return
	if c33s2_layer != null and is_instance_valid(c33s2_layer):
		return
	var st = srv_state.get("c33s2")
	if typeof(st) != TYPE_DICTIONARY:
		_toast("记忆：服务端还没准备好")
		return
	var d: Dictionary = st
	if bool(d.get("used", false)):
		_toast("【记忆】本小局已经用过了")
		return
	if not bool(d.get("can", false)):
		_toast("【记忆】只能在自己的切牌状态发动")
		return
	var last = d.get("last", null)
	var tip_txt := "输入上一局的结算点数"
	if last == null:
		tip_txt = "东一第一局：随便输一个数字就行"
	_toast("记忆：" + tip_txt)

	var host: Node = get_parent()
	if host == null:
		host = self
	var vp := get_viewport_rect().size
	var cl := CanvasLayer.new()
	cl.name = "C33MemoryLayer"
	cl.layer = 100                          # 压在 CardPhase(20) 和主牌桌之上
	host.add_child(cl)
	c33s2_layer = cl
	var ui := Control.new()
	ui.name = "C33MemoryUI"
	ui.z_index = 0
	ui.mouse_filter = Control.MOUSE_FILTER_STOP
	cl.add_child(ui)
	ui.position = Vector2.ZERO
	ui.size = vp
	c33s2_ui = ui

	var mask := ColorRect.new()
	mask.color = Color(0.0, 0.0, 0.0, 0.55)
	mask.size = vp
	mask.mouse_filter = Control.MOUSE_FILTER_STOP
	ui.add_child(mask)

	var center := CenterContainer.new()
	center.size = vp
	center.mouse_filter = Control.MOUSE_FILTER_IGNORE
	ui.add_child(center)

	var panel := PanelContainer.new()
	var sb := StyleBoxFlat.new()
	sb.bg_color = Color(0.06, 0.09, 0.08, 0.98)
	sb.border_color = Color(0.88, 0.74, 0.38, 1.0)
	sb.set_border_width_all(3)
	sb.set_corner_radius_all(16)
	sb.content_margin_left = 34.0
	sb.content_margin_right = 34.0
	sb.content_margin_top = 26.0
	sb.content_margin_bottom = 26.0
	panel.add_theme_stylebox_override("panel", sb)
	panel.custom_minimum_size = Vector2(620, 0)
	center.add_child(panel)

	var vb := VBoxContainer.new()
	vb.add_theme_constant_override("separation", 18)
	panel.add_child(vb)

	var title := Label.new()
	title.text = "记  忆"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 42)
	title.add_theme_color_override("font_color", Color(0.95, 0.84, 0.45))
	title.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	title.add_theme_constant_override("outline_size", 6)
	vb.add_child(title)

	var tip := Label.new()
	tip.text = tip_txt
	tip.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	tip.add_theme_font_size_override("font_size", 22)
	tip.add_theme_color_override("font_color", Color(0.82, 0.85, 0.80))
	vb.add_child(tip)

	var edit := LineEdit.new()
	edit.placeholder_text = "例如 8000"
	edit.alignment = HORIZONTAL_ALIGNMENT_CENTER
	edit.max_length = 9
	edit.custom_minimum_size = Vector2(0, 70)
	edit.add_theme_font_size_override("font_size", 38)
	edit.add_theme_color_override("font_color", Color(1, 1, 1))
	edit.add_theme_color_override("font_placeholder_color", Color(0.55, 0.58, 0.55))
	var eb := StyleBoxFlat.new()
	eb.bg_color = Color(0.13, 0.16, 0.15, 1.0)
	eb.border_color = Color(0.42, 0.47, 0.42, 1.0)
	eb.set_border_width_all(2)
	eb.set_corner_radius_all(8)
	eb.content_margin_left = 16.0
	eb.content_margin_right = 16.0
	edit.add_theme_stylebox_override("normal", eb)
	var ebf := eb.duplicate() as StyleBoxFlat
	ebf.border_color = Color(0.95, 0.84, 0.45, 1.0)
	ebf.set_border_width_all(3)
	edit.add_theme_stylebox_override("focus", ebf)
	edit.text_submitted.connect(func(_t: String): _c33s2_submit())
	vb.add_child(edit)
	c33s2_edit = edit

	var row := HBoxContainer.new()
	row.alignment = BoxContainer.ALIGNMENT_CENTER
	row.add_theme_constant_override("separation", 30)
	vb.add_child(row)

	var ok := _c33s2_btn("ok")
	ok.pressed.connect(_c33s2_submit)
	row.add_child(ok)

	var cancel := _c33s2_btn("pass")
	cancel.pressed.connect(_c33s2_close)
	row.add_child(cancel)

	edit.caret_column = edit.text.length()
	edit.call_deferred("grab_focus")


# kind = "ok"（确认）/ "pass"（取消）：贴图按钮，不叠字
func _c33s2_btn(kind: String) -> TextureButton:
	var b := ui_btn(kind, 220.0)
	b.custom_minimum_size = b.size
	return b


func _c33s2_submit() -> void:
	if c33s2_edit == null or not is_instance_valid(c33s2_edit):
		return
	var txt := String(c33s2_edit.text).strip_edges()
	if txt == "":
		_toast("记忆：先输入一个数字")
		return
	if not txt.is_valid_int():
		_toast("记忆：只能输入数字")
		return
	var num := int(txt)
	var r := srv_request({"op": "c33s2_try", "seat": my_seat, "number": num})
	if srv_kangpo_blocked(r):
		_c33s2_close()                     # 等对方决定是否看破
		return
	if r.is_empty():
		_toast(_srv_err("记忆：服务端没有回应"))
		_pull_state()
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "记忆：数字不对")))
		if c33s2_edit != null and is_instance_valid(c33s2_edit):
			c33s2_edit.select_all()        # 留在面板里，改一个再试
		return
	_c33s2_close()
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("记忆：发动了 —— 下一张打出的牌会暗置")


func _c33s2_close() -> void:
	if c33s2_layer != null and is_instance_valid(c33s2_layer):
		c33s2_layer.queue_free()            # ui 是它的子节点，一起走
	elif c33s2_ui != null and is_instance_valid(c33s2_ui):
		c33s2_ui.queue_free()
	c33s2_ui = null
	c33s2_edit = null
	c33s2_layer = null


# ── Card34 S1【厄运】─────────────────────────────────────────────────
#   切牌前点图标直接发动（不用选牌）：其他三家 3 巡内
#   只能摸切 / 不能副露（含暗杠加杠）/ 不能和 / 不能使用技能。
func _c34_arm() -> void:
	if game_over:
		return
	if (srv_state.get("used_skills", []) as Array).has("34-1-%d" % my_seat):
		_toast("「厄运」本小局已经用过了")
		return
	if String(srv_state.get("phase", "")) != "discard" \
			or int(srv_state.get("turn", -1)) != my_seat:
		_toast("【厄运】只能在自己的切牌阶段发动")
		return
	var r := srv_request({"op": "c34s1_arm", "seat": my_seat})
	if srv_kangpo_blocked(r):
		return                               # 厄运不能被看破，理论上走不到
	if r.is_empty():
		_toast(_srv_err("厄运：服务端没有回应"))
		_pull_state()
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "厄运：发动失败")))
		_pull_state()
		return
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("厄运：三巡内其他三家只能摸切、不能副露 / 和牌 / 使用技能")


# ── Card43 S2【免疫】───────────────────────────────────────────────
#   别人发动「指向我」的技能（换我的牌 / 看我牌 / 决斗 / 上标记…）时问我一句：
#   发动 → 这次作废，而且以后我免疫这个技能；跳过 → 照常发动。本局 2 次。
var c43i_key := ""


func _c43s2_sync(st: Dictionary) -> void:
	var d = st.get("c43s2")
	if typeof(d) != TYPE_DICTIONARY:
		c43i_key = ""
		return
	var ask = (d as Dictionary).get("ask")
	if typeof(ask) != TYPE_DICTIONARY:
		c43i_key = ""
		return
	if kp_active or _skill_panel_open() or c45b_ui != null:
		return                            # 正在回答看破 / 别的面板开着 → 先别叠窗口
	var a := ask as Dictionary
	var key := "%d-%d-%d" % [int(a.get("actor", -1)), int(a.get("card", 0)),
		int(a.get("skill", 0))]
	if key == c43i_key:
		return
	c43i_key = key
	var who := srv_name_of(int(a.get("actor", -1)))
	var nm := String(a.get("name", ""))
	var left := int((d as Dictionary).get("left", 0))
	# 免疫 = 「确认(queren)」/「跳过(tiaoguo)」两张贴图，标题说明还剩几次
	_cg_answer_pair("%s 对你发动了「%s」—— 要免疫吗？（还剩 %d 次）" % [who, nm, left],
		Callable(self, "_c43s2_answer").bind(true),
		Callable(self, "_c43s2_answer").bind(false))


func _c43s2_answer(use: bool) -> void:
	var r := srv_request({"op": "c43s2_answer", "seat": my_seat, "use": bool(use)})
	if r.is_empty():
		_toast(_srv_err("免疫：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "免疫：回答失败")))
		_pull_state()
		return
	c43i_key = ""
	srv_apply_state(r.get("state"), r.get("events"))
	if bool(use):
		_toast("免疫：这次发动作废，我以后免疫这个技能")
	else:
		_toast("免疫：跳过了，这次照常发动")


# ── Card40 S2【同盟】───────────────────────────────────────────────
#   切牌前指定一名玩家：他的手牌永远显示在我视角里；我打出的牌他能合法吃/碰/杠
#   就自动副露（他自己不做任何操作）。多组搭子时弹给我挑。
var c40b_key := ""


func _c40s2_open() -> void:
	if game_over:
		return
	if _skill_used_once(40, 2):
		_toast("「同盟」本小局已经发动过了")
		return
	if String(srv_state.get("phase", "")) != "discard" \
			or int(srv_state.get("turn", -1)) != my_seat:
		_toast("【同盟】只能在自己的切牌前发动")
		return
	var st = srv_state.get("c40s2")
	if typeof(st) != TYPE_DICTIONARY or not bool((st as Dictionary).get("can", false)):
		_toast("【同盟】现在不能发动（本局一次）")
		return
	_seat_pick_begin("c40s2", "同盟：指定一名玩家（他的手牌会一直显示给你）")


func _c40s2_pick(t: int) -> void:
	var r := srv_request({"op": "c40s2_apply", "seat": my_seat, "target": int(t)})
	if srv_kangpo_blocked(r):
		return
	if r.is_empty():
		_toast(_srv_err("同盟：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "同盟：发动失败")))
		_pull_state()
		return
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("同盟：已和 %s 结盟 —— 他的手牌一直显示，你打出的牌他能吃碰杠就自动副露"
		% srv_name_of(int(t)))



func _c40s2_sync(st: Dictionary) -> void:
	var d = st.get("c40s2")
	if typeof(d) != TYPE_DICTIONARY:
		c40b_key = ""
		return
	var off = (d as Dictionary).get("offer")
	if typeof(off) != TYPE_DICTIONARY:
		c40b_key = ""
		return
	var o := off as Dictionary
	var acts0 = o.get("acts")
	var n_acts := 0
	if typeof(acts0) == TYPE_ARRAY:
		n_acts = (acts0 as Array).size()
	var key := "%d-%s-%d" % [int(o.get("discard_seq", -1)),
		String(o.get("tile", "")), n_acts]
	# 已经在问，而且面板真的还在 → 不重复弹
	# （面板被别的清理逻辑干掉时（tile_pick_clear 会把 c40b_key 复位）要能重弹）
	if key == c40b_key and tile_pick_tag == "c40b" and tile_pick_container != null:
		return
	c40b_key = key
	# 多组打法：用「吃」那套 UI —— 手牌上方摆牌面候选，点哪组就选哪组
	var groups: Array = []
	var acts: Array = o.get("acts", [])
	for ai in range(acts.size()):
		var a: Dictionary = acts[ai]
		var kind := String(a.get("kind", ""))
		var chs: Array = a.get("choices", [])
		for ci in range(chs.size()):
			var tiles: Array = chs[ci]
			groups.append({"tiles": tiles.duplicate(),
				"data": {"kind": kind, "index": int(ci)}})
	if groups.is_empty():
		return
	_tile_pick_show(groups, Callable(self, "_c40b_do_pick"),
		func() -> bool: return String(c40b_key) != "",
		"c40b", Callable(self, "_c40b_anchor"))


# 面板摆在「被同盟者的手牌」下面（他的手牌是 reveal_hands 翻开的那一排）
# 找不到那排牌时返回 Vector2.INF → 退回「自己手牌上方」
func _c40b_anchor() -> Vector2:
	var st = srv_state.get("c40s2")
	if typeof(st) != TYPE_DICTIONARY:
		return Vector2.INF
	var off = (st as Dictionary).get("offer")
	if typeof(off) != TYPE_DICTIONARY:
		return Vector2.INF
	var t := int((off as Dictionary).get("target", -1))
	if t < 0 or tapai == null:
		return Vector2.INF
	var who := who_of_seat(int(t))
	if who == "" or who == "me":
		return Vector2.INF
	var min_x := INF
	var max_y := -INF
	var found := false
	for j in range(1, OPP_HAND_COUNT + 1):
		var node := tapai.get_node_or_null("%s%02d" % [who, j]) as Node2D
		if node == null or not node.visible:
			continue
		var gp := node.global_position
		min_x = minf(min_x, gp.x - tile_size.x * 0.5)
		max_y = maxf(max_y, gp.y + tile_size.y * 0.5)
		found = true
	if not found:
		return Vector2.INF
	return Vector2(min_x, max_y + 12.0)


# 面板点选回调：data = {"kind": "pon"/"chi"/"minkan", "index": 第几组}
func _c40b_do_pick(data) -> void:
	if typeof(data) != TYPE_DICTIONARY:
		return
	_c40b_do(String((data as Dictionary).get("kind", "")),
		int((data as Dictionary).get("index", -1)))


func _c40b_do(kind: String, index: int) -> void:
	var r := srv_request({"op": "c40s2_pick", "seat": my_seat,
		"kind": String(kind), "index": int(index)})
	if r.is_empty():
		_toast(_srv_err("同盟：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "同盟：副露失败")))
		_pull_state()
		return
	c40b_key = ""
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("同盟：副露完成（他自己不用操作）")


# ── Card42 S1【理论战】/ S2【夺目】───────────────────────────────────
#   S1：配牌阶段（我当庄家）发动 → 已发动的配牌技能作废，之后谁都不能用技能（连看破都不问）。
#   S2：切牌前指定一位玩家 → 本局结算时把他当庄家（只影响点数，真庄家不变）。
func _c42s1_apply() -> void:
	if game_over:
		return
	var st = srv_state.get("c42")
	if typeof(st) != TYPE_DICTIONARY or not bool((st as Dictionary).get("s1_can", false)):
		_toast("【理论战】只能在配牌阶段、自己当庄家时发动")
		return
	var r := srv_request({"op": "c42s1_apply", "seat": my_seat})
	if srv_kangpo_blocked(r):
		return
	if r.is_empty():
		_toast(_srv_err("理论战：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "理论战：发动失败")))
		_pull_state()
		return
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("理论战：已经发动过的配牌技能全部作废，之后谁都不能再用技能")


func _c42s2_open() -> void:
	if game_over:
		return
	var st = srv_state.get("c42")
	if typeof(st) != TYPE_DICTIONARY or not bool((st as Dictionary).get("s2_can", false)):
		_toast("【夺目】只能在自己切牌前发动（本局一次）")
		return
	_seat_pick_begin("c42s2", "夺目：结算时把谁当庄家？（只影响点数）")


func _c42s2_pick(t: int) -> void:
	var r := srv_request({"op": "c42s2_arm", "seat": my_seat, "target": int(t)})
	if srv_kangpo_blocked(r):
		return
	if r.is_empty():
		_toast(_srv_err("夺目：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "夺目：发动失败")))
		_pull_state()
		return
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("夺目：本局结算时把 %s 当庄家（只影响点数）" % srv_name_of(int(t)))


# 【夺目】(42S2) 的**结算前询问**（用户口径 2026-10-28）：
# 以前只能自己在切牌前点图标，很容易错过 → 现在服务端在真正结算之前挂一问，
# 让你决定「这次和牌按谁的庄家算点数」。答完（或 15 秒超时）才真正结算。
var _c42s2_ask_sig := ""


func _c42s2_sync(st: Dictionary) -> void:
	var c = st.get("c42")
	var ask = (c as Dictionary).get("ask") if typeof(c) == TYPE_DICTIONARY else null
	if typeof(ask) != TYPE_DICTIONARY:
		_c42s2_ask_sig = ""
		return
	var d := ask as Dictionary
	var sig := "%d|%s|%d" % [int(d.get("winner", -1)), String(d.get("result", "")),
		int(d.get("dealer", -1))]
	if sig == _c42s2_ask_sig:
		return
	_c42s2_ask_sig = sig
	# 播报：让【夺目】的主人也知道这次是谁和了（谁铳的 / 谁自摸）
	var who := srv_name_of(int(d.get("winner", -1)))
	var loser := _int_of(d, "loser", -1)
	var ev := "%s 自摸" % who
	if String(d.get("result", "")) != "tsumo" and loser >= 0:
		ev = "%s 铳给 %s" % [srv_name_of(loser), who]
	_seat_pick_begin("c42s2_ask", "夺目：%s —— 这次按谁的庄家算点数？" % ev)


func _c42s2_answer(t: int) -> void:
	var r := srv_request({"op": "c42s2_answer", "seat": my_seat, "target": int(t)})
	_c42s2_ask_sig = ""
	if r.is_empty():
		_toast(_srv_err("夺目：服务端没有回应"))
		_pull_state()
		return
	srv_apply_state(r.get("state"), r.get("events"))
	if int(t) >= 0:
		_toast("夺目：这次结算把 %s 当庄家（只影响点数）" % srv_name_of(int(t)))
	else:
		_toast("夺目：这次按真庄家结算")


# ── Card39 S1【隐形】───────────────────────────────────────────────
#   切牌前、自己牌河超过 7 张时发动：这一局打出去的牌谁都不能吃碰杠荣，
#   也不造成振听（【加速】【钓鱼】也吃不到）。S2【无视】是被动，没有入口。
func _c39s1_apply() -> void:
	if game_over:
		return
	if bool(srv_state.get("c39s1_on", false)) \
			or bool(((srv_state.get("c39", {}) as Dictionary)
				if typeof(srv_state.get("c39")) == TYPE_DICTIONARY else {}).get("on", false)):
		_toast("【隐形】本局已经开着了")
		return
	if String(srv_state.get("phase", "")) != "discard" \
			or int(srv_state.get("turn", -1)) != my_seat:
		_toast("【隐形】只能在自己摸牌后、打牌前发动")
		return
	var st = srv_state.get("c39")
	if typeof(st) != TYPE_DICTIONARY or not bool((st as Dictionary).get("can", false)):
		_toast("【隐形】自己牌河要满 7 张（摸牌后、打牌前）")
		return
	var r := srv_request({"op": "c39s1_apply", "seat": my_seat})
	if srv_kangpo_blocked(r):
		return
	if r.is_empty():
		_toast(_srv_err("隐形：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "隐形：发动失败")))
		_pull_state()
		return
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("隐形：这一局打出去的牌谁都不能吃碰杠荣，也不造成振听")


# ── Card46 S1【恶听】───────────────────────────────────────────────
#   切牌前：手里有「打出去就听牌」的牌，而且听的牌确实还在场上
#   （他家手牌 / 牌河暗置牌 / 没摸的牌山）→ 点一张切出去，直接按【一定和牌】结算：
#   下家→对家→上家 依次问，谁手里有我的铳牌就他出铳，都没有就算自摸。
func _c46_start() -> void:
	if game_over:
		return
	if _skill_used_once(46, 1):
		_toast("「恶听」本小局已经发动过了")
		return
	if String(srv_state.get("phase", "")) != "discard" \
			or int(srv_state.get("turn", -1)) != my_seat:
		_toast("【恶听】只能在自己的切牌前发动")
		return
	var st = srv_state.get("c46")
	if typeof(st) != TYPE_DICTIONARY or not bool((st as Dictionary).get("can", false)):
		_toast("【恶听】现在不能发动（要有一张打出去就听牌、且待牌在场上只剩 1 张的手牌）")
		return
	if c46_panel.active:
		c46_panel.close()
		return
	c46_panel.begin({
		"name": "恶听",
		"want": 1, "min": 1,
		"river": false,
		"cancel": true,
		"on_confirm": _c46_confirm,
	})
	_toast("恶听：选 1 张「切出去就听牌、待牌只剩 1 张」的手牌 → 点「开始」（随后一定和牌）")


func _c46_confirm(picks: Array, _rivers: Array) -> void:
	if picks.is_empty():
		_toast("恶听：先选 1 张手牌")
		return
	var all := display_tiles()
	var idx := int(picks[0])
	if idx < 0 or idx >= all.size():
		_toast("恶听：这张选不了")
		return
	var tile := String(all[idx])
	var st = srv_state.get("c46")
	var ok := false
	if typeof(st) == TYPE_DICTIONARY:
		var ts = (st as Dictionary).get("tiles")
		if typeof(ts) == TYPE_ARRAY:
			ok = int_set(ts).size() > 0 and (tile in (ts as Array))
	if not ok:
		_toast("恶听：这张切出去不听牌（听的那几张可能都已经不在场上了）")
		return
	var r := srv_request({"op": "c46s1_apply", "seat": my_seat, "tile": tile})
	if srv_kangpo_blocked(r):
		return
	if r.is_empty():
		_toast(_srv_err("恶听：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "恶听：发动失败")))
		_pull_state()
		return
	c46_panel.close()
	srv_apply_state(r.get("state"), r.get("events"))
	# ★ 别写 `r.get("c46") or {}`：GDScript 的 or 返回 **bool**（不是 Python 那种「取真值」），
	#   赋给 Dictionary 会抛 Trying to assign value of type 'bool' to a variable of type 'Dictionary'
	var d := {}
	var raw_c46 = r.get("c46")
	if typeof(raw_c46) == TYPE_DICTIONARY:
		d = raw_c46 as Dictionary
	var _ev := String(d.get("event", ""))
	if _ev == "c46_pending":
		_toast("恶听：铳张「%s」→ 点「自摸」" % String(d.get("tile", "")))
	elif _ev == "yiding":
		var frm := int(d.get("from", -1))
		if frm >= 0:
			_toast("恶听：%s 手里有你的铳张「%s」→ 他出铳"
				% [srv_name_of(frm), String(d.get("tile", ""))])
		else:
			_toast("恶听：铳张「%s」不在任何人手里 → 按自摸结算" % String(d.get("tile", "")))
	else:
		_toast("恶听：%s" % String(d.get("reason", "结算完成")))


# ── Card45 S2【替身】───────────────────────────────────────────────
#   切牌时发动：指定 第一位（他摸牌后由别人决定切哪张）+ 第二位（可自己）。
#   第一位摸牌后 → 第二位在面板里点一张手牌 → 第一位自动切出这张；
#   第一位这一回合不能发动任何技能（服务端集中闸门拦掉）。
var c45b_layer: CanvasLayer = null
var c45b_ui: Control = null
var c45b_sig := ""
var c45b_asked := ""


func _c45s2_start() -> void:
	if game_over:
		return
	if _skill_used_once(45, 2):
		_toast("「替身」本小局已经发动过了")
		return
	if String(srv_state.get("phase", "")) != "discard" \
			or int(srv_state.get("turn", -1)) != my_seat:
		_toast("【替身】只能在自己的切牌前发动")
		return
	var st = srv_state.get("c45s2")
	if typeof(st) != TYPE_DICTIONARY or not bool((st as Dictionary).get("can", false)):
		_toast("【替身】现在不能发动")
		return
	seat_pick_first = -1
	_seat_pick_begin("c45s2a", "替身：先选第一位（被接管切牌的人）")


func _c45s2_first(a: int) -> void:
	seat_pick_first = int(a)
	_seat_pick_begin("c45s2b", "替身：再选第二位（可以选你自己）")


func _c45s2_second(a: int, b: int) -> void:
	var r := srv_request({"op": "c45s2_apply", "seat": my_seat,
		"first": int(a), "second": int(b)})
	if srv_kangpo_blocked(r):
		return
	if r.is_empty():
		_toast(_srv_err("替身：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "替身：发动失败")))
		_pull_state()
		return
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("替身：已指定 %s 的切牌由 %s 决定"
		% [srv_name_of(int(a)), srv_name_of(int(b))])


# 第二位玩家的面板：把第一位的手牌摆成一排，点一张就切
func _c45s2_sync(st: Dictionary) -> void:
	var d = st.get("c45s2")
	var w = null
	if typeof(d) == TYPE_DICTIONARY:
		w = (d as Dictionary).get("wait")
	if typeof(w) != TYPE_DICTIONARY:
		if c45b_ui != null:
			_c45b_close()
		c45b_sig = ""
		return
	var w2 := w as Dictionary
	var first := int(w2.get("first", -1))
	if not bool(w2.get("mine", false)):
		if c45b_ui != null:
			_c45b_close()
			c45b_sig = ""
		# 我是被接管的那一位 → 提示一次
		if first == my_seat:
			var k2 := "%d-%d" % [first, int(w2.get("second", -1))]
			if k2 != c45b_asked:
				c45b_asked = k2
				_toast("替身：本回合由 %s 指定你切哪张"
					% srv_name_of(int(w2.get("second", -1))))
		return
	var tiles: Array = w2.get("tiles", [])
	var sig := str(first)
	for t in tiles:
		sig += "|" + String(t)
	if sig == c45b_sig and c45b_ui != null:
		return
	c45b_sig = sig
	if c45b_ui != null:
		_c45b_close()
	_c45b_make(first, tiles)


func _c45b_make(first: int, tiles: Array) -> void:
	var host: Node = get_parent()
	if host == null:
		host = self
	c45b_layer = CanvasLayer.new()
	c45b_layer.name = "C45bLayer"
	c45b_layer.layer = 100
	host.add_child(c45b_layer)
	c45b_ui = Control.new()
	c45b_ui.name = "C45bUI"
	c45b_ui.z_index = 300
	c45b_ui.position = Vector2.ZERO
	c45b_layer.add_child(c45b_ui)
	var vp := get_viewport_rect().size
	var bg := ColorRect.new()
	bg.color = Color(0, 0, 0, 0.6)
	bg.size = vp
	bg.mouse_filter = Control.MOUSE_FILTER_STOP
	c45b_ui.add_child(bg)
	var head := Label.new()
	head.text = "替身：请指定 %s 切哪张（点一张即可）" % srv_name_of(int(first))
	head.add_theme_font_size_override("font_size", 22)
	head.add_theme_color_override("font_color", Color(1, 1, 0.85))
	head.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	head.add_theme_constant_override("outline_size", 6)
	head.position = Vector2(40, 60)
	c45b_ui.add_child(head)
	var n: int = (tiles as Array).size()
	var tw := 64.0
	var th := 92.0
	var gap := 8.0
	var total := float(n) * tw + float(maxi(n - 1, 0)) * gap
	var x0 := (vp.x - total) * 0.5
	if x0 < 20.0:
		x0 = 20.0
	for j in range(n):
		var b := TextureButton.new()
		b.texture_normal = load(TileBank.VERT_DIR
			+ TileBank.face_file(String((tiles as Array)[j])) + ".png") as Texture2D
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		b.size = Vector2(tw, th)
		b.position = Vector2(x0 + float(j) * (tw + gap), vp.y * 0.42)
		b.pressed.connect(_c45b_pick.bind(String((tiles as Array)[j])))
		c45b_ui.add_child(b)


func _c45b_pick(tile: String) -> void:
	var r := srv_request({"op": "c45s2_pick", "seat": my_seat, "tile": String(tile)})
	if r.is_empty():
		_toast(_srv_err("替身：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "替身：指定失败")))
		_pull_state()
		return
	_c45b_close()
	c45b_sig = ""
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("替身：已指定「%s」" % String(tile))


func _c45b_close() -> void:
	if c45b_ui != null and is_instance_valid(c45b_ui):
		c45b_ui.queue_free()
	c45b_ui = null
	if c45b_layer != null and is_instance_valid(c45b_layer):
		c45b_layer.queue_free()
	c45b_layer = null


# ── Card45 S1【神境】───────────────────────────────────────────────
#   摸牌前询问：自己牌河满 12 张 → 手牌 + 牌河**合计**挑 13 张当新手牌
#   （放弃的手牌暗置补回被拿走的牌河位置）。之后：只能摸切 / 不能立直 /
#   吃碰杠荣和全关（只能自摸）/ 得点上限（闲 32000・庄 48000）。
func _c45_gate_before_draw() -> bool:
	if c45_panel.active:
		return true                      # 面板开着：先别摸牌
	if _srv_kangpo_wait():
		return false
	var c45st = srv_state.get("c45")
	if typeof(c45st) != TYPE_DICTIONARY:
		return false
	if not bool((c45st as Dictionary).get("can", false)):
		return false
	var key := "%d-%d" % [int(srv_state.get("live_left", 0)),
		int(srv_state.get("turn", 0))]
	if key == c45_key:
		return false                     # 这一巡已经问过（点了跳过）
	c45_key = key
	_c45s1_start()
	return true


func _c45s1_start() -> void:
	if game_over:
		return
	if c45_panel.active:
		c45_panel.close()                # 再点一次 = 跳过这一巡
		_toast("神境：跳过了（下次摸牌前还会问）")
		return
	var st = srv_state.get("c45")
	if typeof(st) != TYPE_DICTIONARY or not bool((st as Dictionary).get("can", false)):
		_toast("【神境】只能在自己摸牌前发动（自己牌河要够 12 张、手牌 13 张）")
		return
	c45_panel.begin({
		"name": "神境",
		"want": 13, "min": 0,
		"total": 13,                     # 手牌 + 牌河合计 13 张
		"river": true, "river_match": false,
		"cancel": true,
		"river_ok": _c45_river_ok,
		"on_confirm": _c45_confirm,
	})
	_toast("神境：手牌 + 牌河一共选 13 张（可以 13 张全选牌河）→ 点「开始」")


func _c45_river_ok(seq: int, _seat: int, _down: bool) -> bool:
	var st = srv_state.get("c45")
	if typeof(st) != TYPE_DICTIONARY:
		return false
	var rv = (st as Dictionary).get("rivers")
	if typeof(rv) != TYPE_ARRAY:
		return false
	return int_set(rv).has(int(seq))


func _c45_confirm(picks: Array, rivers: Array) -> void:
	var all := display_tiles()
	var picked: Array = []
	var idxs: Array = picks.duplicate()
	idxs.sort()
	for i in idxs:
		if int(i) >= 0 and int(i) < all.size():
			picked.append(String(all[int(i)]))
	var rs: Array = []
	for seq in rivers:
		rs.append(int(seq))
	if picked.size() + rs.size() != 13:
		_toast("神境：手牌 + 牌河一共要选 13 张")
		return
	var r := srv_request({"op": "c45s1_apply", "seat": my_seat,
		"hand_tiles": picked, "river": rs})
	if srv_kangpo_blocked(r):
		return
	if r.is_empty():
		_toast(_srv_err("神境：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "神境：发动失败")))
		_pull_state()
		return
	c45_panel.close()
	srv_apply_state(r.get("state"), r.get("events"))
	c45_key = "%d-%d" % [int(srv_state.get("live_left", 0)),
		int(srv_state.get("turn", 0))]
	_toast("神境：13 张已换好 —— 之后只能摸切，和牌只能自摸（得点有上限）")
	draw_tile()


# ── Card43 S1【NO MISS】─────────────────────────────────────────────
#   切牌前：手牌选 2 张（要成搭子）+ 彩框选牌河 2 张（也要成搭子）→「开始」
#   换完若能直接成和牌形 → 服务端按自摸结算（有平和计平和，不计边坎吊 2 符）。
func _c43_start() -> void:
	if game_over:
		return
	if (srv_state.get("used_skills", []) as Array).has("43-1-%d" % my_seat):
		_toast("「NO MISS」本小局已经用过了")
		return
	if String(srv_state.get("phase", "")) != "discard" \
			or int(srv_state.get("turn", -1)) != my_seat:
		_toast("【NO MISS】只能在自己的切牌前发动")
		return
	var st = srv_state.get("c43")
	if typeof(st) != TYPE_DICTIONARY or not bool((st as Dictionary).get("can", false)):
		_toast("NO MISS：手牌里得有一组搭子，牌河里也得有一个搭子")
		return
	if c33_panel.active:
		c33_panel.close()
	c43_panel.begin({
		"name": "NO MISS",
		"want": 2, "min": 2,
		"river": true, "river_match": true,
		"cancel": true,
		"river_ok": _c43_river_ok,
		"on_confirm": _c43_confirm,
	})
	_toast("NO MISS：选 2 张手牌 + 牌河 2 张（都要是搭子）→ 点「开始」")


func _c43_river_ok(seq: int, _seat: int, down: bool) -> bool:
	if down:
		return false
	var st = srv_state.get("c43")
	if typeof(st) != TYPE_DICTIONARY:
		return false
	var rv = (st as Dictionary).get("rivers")
	if typeof(rv) != TYPE_ARRAY:
		return false
	return int_set(rv).has(int(seq))


func _c43_confirm(picks: Array, rivers: Array) -> void:
	var all := display_tiles()
	var picked: Array = []
	var idxs: Array = picks.duplicate()
	idxs.sort()
	for i in idxs:
		if int(i) >= 0 and int(i) < all.size():
			picked.append(String(all[int(i)]))
	if picked.size() != 2:
		_toast("NO MISS：要选 2 张手牌")
		return
	var rs: Array = []
	for seq in rivers:
		rs.append(int(seq))
	if rs.size() != 2:
		_toast("NO MISS：要选 2 张牌河")
		return
	var r := srv_request({"op": "c43s1_apply", "seat": my_seat,
		"hand_tiles": picked, "river": rs})
	if srv_kangpo_blocked(r):
		return
	if r.is_empty():
		_toast(_srv_err("NO MISS：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "NO MISS：发动失败")))
		_pull_state()
		return
	var d: Dictionary = r.get("c43", {})
	c43_panel.close()
	srv_apply_state(r.get("state"), r.get("events"))
	if bool(d.get("win", false)):
		_toast("NO MISS：换成了和牌形 → 点「自摸」")
	else:
		_toast("NO MISS：换完了，接着打牌")


# ── 左侧「复制品图标条」：复制（Card41，可多个）+ 传承（Card16，一个）──────────
#   都画成技能图标按钮（skill/ui/buttons/card_XX_Y_r0.png），点一下 = 发动那个技能。
#   复制品贴在 Card41 上方，传承品贴在 Card16 上方；数据没变就不重建（避免闪烁）。
func _copied_icons_refresh(st: Dictionary) -> void:
	var items: Array = []
	var c41 = st.get("c41")
	if typeof(c41) == TYPE_DICTIONARY:
		var copies = (c41 as Dictionary).get("copies")
		if typeof(copies) != TYPE_ARRAY:
			copies = []
		for x in copies:
			if typeof(x) != TYPE_DICTIONARY:
				continue
			items.append({"card": int((x as Dictionary).get("card", 0)),
				"skill": int((x as Dictionary).get("skill", 1)), "host": 41})
	var cp := _cc_copy(st)
	if not cp.is_empty():
		items.append({"card": int(cp.get("card", 0)),
			"skill": int(cp.get("skill", 1)), "host": 16})
	var cu: Array = st.get("copy_used", [])
	var key := JSON.stringify(items) + "|" + JSON.stringify(cu)
	if key == c41_icons_key:
		return
	c41_icons_key = key

	for b in c41_btns:
		if b != null and is_instance_valid(b):
			(b as Node).queue_free()
	c41_btns.clear()
	if items.is_empty():
		return
	if c41_layer == null or not is_instance_valid(c41_layer):
		var host: Node = get_parent()
		if host == null:
			host = self
		c41_layer = CanvasLayer.new()
		c41_layer.name = "C41Layer"
		c41_layer.layer = 60
		host.add_child(c41_layer)

	const ICON := Vector2(96.0, 54.0)          # 横版技能按钮（446x250 等比缩小）
	var idn := get_node_or_null("Identity")
	var stack_by_host := {}                    # 同一张卡上方可以摞多个
	for i in range(items.size()):
		var it: Dictionary = items[i]
		var card_no := int(it.get("card", 0))
		var sk := int(it.get("skill", 1))
		var host_card := int(it.get("host", 41))
		var base := Vector2(30, 360)
		if idn != null:
			var cn := idn.get_node_or_null("Card%d" % host_card)
			if cn != null and cn is Node2D:
				base = (cn as Node2D).global_position + Vector2(0, -52)
		var idx := int(stack_by_host.get(host_card, 0))
		stack_by_host[host_card] = idx + 1

		var b := TextureButton.new()
		b.name = "CopyIcon%d" % i
		var t := load("res://Cailiao/skill/ui/buttons/card_%02d_%d_r0.png" % [card_no, sk]) as Texture2D
		b.texture_normal = t
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		b.size = ICON
		b.position = base + Vector2(0, -float(idx) * (ICON.y + 6.0))
		b.tooltip_text = "%s来的技能：Card%02d-%d（点一下就用）" % [
			"传承" if host_card == 16 else "复制", card_no, sk]
		# 复制品自己那一份配额用掉了 → 这一格单独变灰（原技能那份不受影响）
		if cu.has("%d-%d-%d" % [card_no, sk, my_seat]):
			b.disabled = true
			b.modulate = Color(0.42, 0.42, 0.42, 1.0)
			b.tooltip_text += "（这一份已经用过了）"
		b.pressed.connect(func(): _on_identity_skill(my_seat, card_no, sk - 1, true))
		c41_layer.add_child(b)
		c41_btns.append(b)


# ── Card41 S1【复制】───────────────────────────────────────────────
#   别人宣告技能的一瞬间问我要不要复制；复制到的技能在【复制】图标**上方**堆按钮，
#   点按钮 = 走那个技能原来的入口（服务端 granted 已经把我当持有者）。
var c41_key := ""
var c41_btns: Array = []
var c41_layer: CanvasLayer = null
var c41_pool: Array = []              # 当前可复制的技能池（非空时点技能图标 = 复制）
var c41_pick_layer: CanvasLayer = null
var c41_pick_btn: Control = null
var c41_icons_key := ""        # 左侧「复制品图标条」的缓存 key（避免每帧重建）
var c41_auto_done := false     # 本局已经自动弹过「复制」面板了？（再问就只闪图标）


# 「复制」有没有待挑的（闪 41 号卡的技能图标 = 点我开面板）
func _c41_hint(on: bool) -> void:
	var idn := get_node_or_null("Identity")
	if idn != null and idn.has_method("set_skill_frame"):
		idn.call("set_skill_frame", 41, 0, on)


func _c41_sync(st: Dictionary) -> void:
	_copied_icons_refresh(st)          # 先刷：只有传承（16 号卡）没有 41 卡时也要显示
	var d = st.get("c41")
	if typeof(d) != TYPE_DICTIONARY:
		return
	var dd := d as Dictionary
	if kp_active:
		return                            # 正在答拦截询问（模态）→ 复制列表等它关了再弹
	# 延迟复制：别人刚发动的技能会攒在池子里，我随时来挑（不拦停对局）
	var ask = dd.get("ask")
	var pool: Array = ask if typeof(ask) == TYPE_ARRAY else []
	if pool.is_empty():
		c41_key = ""
		# 只在「之前确实开着」时收一次（别每帧都 reset 图标缩放）
		if not c41_pool.is_empty() or c41_pick_layer != null:
			c41_pool = []
			_c41_pick_close()
			_c41_hint(false)
	else:
		var key := JSON.stringify(pool)
		if key != c41_key:
			c41_key = key
			var items: Array = []
			for it in pool:
				if typeof(it) != TYPE_DICTIONARY:
					continue
				var nm := String((it as Dictionary).get("name", ""))
				var tgt := int((it as Dictionary).get("target", -1))
				var cd := int((it as Dictionary).get("card", 0))
				var sk := int((it as Dictionary).get("skill", 0))
				items.append({"label": "复制【%s】（%s 发动）" % [nm, srv_name_of(tgt)],
					"cb": Callable(self, "_c41_do_copy2").bind(cd, sk)})
			c41_pool = pool
			# ★ 用户口径 2026-11-01：只在本局第一次自动弹；用过之后只闪图标，
			#   点 41 号卡的技能图标才开面板（以前每复制一次池子变一次 → 又弹一次）
			if not c41_auto_done and not is_skill_muted(41, 1):
				c41_auto_done = true
				_c41_pick_open(pool)
				_toast("复制：点技能图标复制（共 %d 个），点「跳过」全部取消" % pool.size())
			else:
				_c41_hint(true)


func _c41_do_copy2(card: int, skill: int) -> void:
	var r := srv_request({"op": "c41_copy", "seat": my_seat,
		"card": int(card), "skill": int(skill)})
	if r.is_empty():
		_toast(_srv_err("复制：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "复制：失败")))
		_pull_state()
		return
	var d: Dictionary = r.get("c41", {})
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("复制：拿到了【%s】—— 在【复制】图标上方点它就能用" % String(d.get("name", "")))


func _c41_do_copy() -> void:
	var r := srv_request({"op": "c41_copy", "seat": my_seat})
	if r.is_empty():
		_toast(_srv_err("复制：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "复制：失败")))
		_pull_state()
		return
	var d: Dictionary = r.get("c41", {})
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("复制：拿到了【%s】—— 在【复制】图标上方点它就能用" % String(d.get("name", "")))


# ── 复制「待选」界面：不弹黑色文字列表 ────────────────────────────────
#   提示一行 + 一个「跳过」按钮（贴图取场景里的 BtnTiaoguo），
#   同时把人物卡上的技能图标等比放大 → 点哪个图标就复制哪个技能。
const C41_SKILL_SCALE := 1.35


# ── 复制「待选」面板（左上角）──────────────────────────────────────
#   一排「可复制技能」的图标按钮（技能卡图）+ 一个跳过按钮。
#   点图标 = 复制那个技能；点跳过 = 剩下的都取消。
#   面板放在 layer 62，压在人物卡、牌、其他 UI 上面（不会被抢点击）。
const C41_ICON := Vector2(112.0, 156.0)      # 技能图标按钮（等比）
const C41_GAP := 10.0
const C41_BOX_POS := Vector2(24.0, 84.0)     # 左上角


func _c41_pick_open(pool: Array, names: Array = []) -> void:
	_c41_pick_close()
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	var layer := CanvasLayer.new()
	layer.name = "C41Pick"
	layer.layer = 62                          # ★ 最上层：不会被牌 / 人物卡挡住
	host.add_child(layer)
	c41_pick_layer = layer

	var tex_skip := btn_tex("pass")
	var skip_w := 104.0
	var skip_h := 116.0
	if tex_skip != null and tex_skip.get_width() > 0:
		skip_h = skip_w * float(tex_skip.get_height()) / float(tex_skip.get_width())

	var n := (pool as Array).size()
	var row_w := n * (C41_ICON.x + C41_GAP)
	var box := Control.new()
	box.name = "C41Box"
	box.position = C41_BOX_POS
	box.size = Vector2(row_w + skip_w + C41_GAP, 34.0 + maxf(C41_ICON.y, skip_h))
	box.mouse_filter = Control.MOUSE_FILTER_IGNORE
	layer.add_child(box)

	var tip := Label.new()
	tip.text = "复制（点图标 = 复制，%d 个可选）" % n
	tip.add_theme_font_size_override("font_size", 24)
	tip.add_theme_color_override("font_color", Color(1.0, 0.96, 0.85))
	tip.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	tip.add_theme_constant_override("outline_size", 6)
	tip.position = Vector2(0, 0)
	tip.size = Vector2(box.size.x, 30)
	tip.mouse_filter = Control.MOUSE_FILTER_IGNORE
	box.add_child(tip)

	for i in range(n):
		var it = (pool as Array)[i]
		if typeof(it) != TYPE_DICTIONARY:
			continue
		var d := it as Dictionary
		var cd := int(d.get("card", 0))
		var sk := int(d.get("skill", 1))
		var b := TextureButton.new()
		b.name = "C41Icon%d" % i
		var t := load("res://Cailiao/skill/cards/card_%02d.png" % cd) as Texture2D
		b.texture_normal = t
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		b.size = C41_ICON
		b.position = Vector2(i * (C41_ICON.x + C41_GAP), 34.0)
		b.tooltip_text = "复制：%s（%s 发动）" % [String(d.get("name", "")),
			srv_name_of(int(d.get("target", -1)))]
		b.pressed.connect(_c41_do_copy2.bind(cd, sk))
		b.pressed.connect(_c41_pick_close)
		box.add_child(b)
		# 技能名已经在贴图里了（card_XX_Y_r0.png 自带），不再叠 Label

	var sbtn := TextureButton.new()
	sbtn.name = "C41Skip"
	sbtn.texture_normal = tex_skip
	sbtn.ignore_texture_size = true
	sbtn.stretch_mode = TextureButton.STRETCH_SCALE
	sbtn.focus_mode = Control.FOCUS_NONE
	sbtn.size = Vector2(skip_w, skip_h)
	sbtn.position = Vector2(row_w, 34.0)
	sbtn.tooltip_text = "都跳过（清空这一叠）"
	sbtn.pressed.connect(_c41_do_skip)
	sbtn.pressed.connect(_c41_pick_close)
	box.add_child(sbtn)
	c41_pick_btn = sbtn


func _c41_pick_close() -> void:
	if c41_pick_layer != null and is_instance_valid(c41_pick_layer):
		c41_pick_layer.queue_free()
	c41_pick_layer = null
	c41_pick_btn = null


func _c41_do_skip() -> void:
	var r := srv_request({"op": "c41_skip", "seat": my_seat})
	if not r.is_empty():
		srv_apply_state(r.get("state"), r.get("events"))


# ── Card40 S1【透视】───────────────────────────────────────────────
#   切牌前点图标 → 选一家：立直中的免费看；否则消耗那一家的一次（每家初始 1）。
#   看到的手牌走 reveal 那条链（和「感知 / 思路」同一套，多家各在自己家位，不重叠）。
func _c40s1_open() -> void:
	if game_over:
		return
	if String(srv_state.get("phase", "")) != "discard" \
			or int(srv_state.get("turn", -1)) != my_seat:
		_toast("【透视】只能在自己的切牌前发动")
		return
	_seat_pick_begin("c40s1", "透视：选一家看手牌（立直中免费）")


func _c40s1_pick(t: int) -> void:
	var r := srv_request({"op": "c40s1_apply", "seat": my_seat, "target": int(t)})
	if srv_kangpo_blocked(r):
		return
	if r.is_empty():
		_toast(_srv_err("透视：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "透视：发动失败")))
		_pull_state()
		return
	var d: Dictionary = r.get("c40", {})
	srv_apply_state(r.get("state"), r.get("events"))
	if bool(d.get("shown", false)):
		_toast("透视：看到 %s 的手牌%s" % [srv_name_of(int(t)),
			"（立直中，不消耗次数）" if bool(d.get("free", false)) else ""])
	else:
		_toast("透视：%s" % String(d.get("why", "看不到")))


# ── Card38 S1【重整】───────────────────────────────────────────────
#   点图标 → 把「接下来会翻的 3 张宝牌指示牌」摆到屏幕中央，和我的手牌一起
#   依次选 3 张（点击顺序 = 放入顺序）→ 确认后按顺序放进第 2/3/4 张指示牌的位置，
#   被顶下来的那几张回手牌。
var c38_active := false
var c38_layer: CanvasLayer = null
var c38_ui: Control = null
var c38_dora: Array = []
var c38_hand: Array = []
var c38_picks: Array = []            # [{"kind":"dora","i":0} / {"kind":"hand","seq":n}]
var c38_nodes := {}                  # key -> TextureButton
var c38_ok: TextureButton = null


func _c38s1_open() -> void:
	if game_over:
		return
	if _skill_used_once(38, 1):
		_toast("「重整」本小局已经发动过了")
		return
	if String(srv_state.get("phase", "")) != "discard" \
			or int(srv_state.get("turn", -1)) != my_seat:
		_toast("【重整】只能在自己的切牌前发动")
		return
	var r := srv_request({"op": "c38s1_view", "seat": my_seat})
	if r.is_empty():
		_toast(_srv_err("重整：服务端没有回应"))
		return
	var v: Dictionary = r.get("c38", {})
	c38_dora = v.get("dora", [])
	c38_hand = v.get("hand", [])
	if (c38_dora as Array).size() != 3:
		_toast("重整：现在没有 3 张可翻的宝牌指示牌")
		return
	c38_picks.clear()
	c38_active = true
	_c38s1_make_ui()
	_c38s1_refresh()


func _c38_tile_btn(tile_id: String, sz: Vector2) -> TextureButton:
	var b := TextureButton.new()
	b.texture_normal = load(TileBank.VERT_DIR + TileBank.face_file(tile_id) + ".png") as Texture2D
	b.ignore_texture_size = true
	b.stretch_mode = TextureButton.STRETCH_SCALE
	b.focus_mode = Control.FOCUS_NONE
	b.size = sz
	var f := SelFrame.attach(b, sz)
	f.visible = false
	b.set_meta("frame", f)
	var num := Label.new()
	num.name = "Num"
	num.add_theme_font_size_override("font_size", 26)
	num.add_theme_color_override("font_color", Color(1, 0.9, 0.2))
	num.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	num.add_theme_constant_override("outline_size", 6)
	num.position = Vector2(3, 1)
	num.mouse_filter = Control.MOUSE_FILTER_IGNORE
	b.add_child(num)
	return b


func _c38s1_make_ui() -> void:
	if c38_ui != null:
		return
	var host: Node = get_parent()
	if host == null:
		host = self
	c38_layer = CanvasLayer.new()
	c38_layer.name = "C38Layer"
	c38_layer.layer = 100
	host.add_child(c38_layer)
	c38_ui = Control.new()
	c38_ui.name = "C38UI"
	c38_ui.z_index = 300
	c38_ui.position = Vector2.ZERO
	c38_layer.add_child(c38_ui)
	var vp := get_viewport_rect().size
	var bg := ColorRect.new()
	bg.color = Color(0, 0, 0, 0.6)
	bg.size = vp
	bg.mouse_filter = Control.MOUSE_FILTER_STOP
	c38_ui.add_child(bg)
	var head := Label.new()
	head.name = "Head"
	head.text = "重整：选 3 张（指示牌或我的手牌），点击顺序 = 放入顺序"
	head.add_theme_font_size_override("font_size", 22)
	head.add_theme_color_override("font_color", Color(1, 1, 0.85))
	head.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	head.add_theme_constant_override("outline_size", 6)
	head.position = Vector2(40, 34)
	c38_ui.add_child(head)
	# ── 指示牌 3 张（屏幕中央）──
	var tw := 76.0
	var th := 106.0
	var gap := 26.0
	var total := 3.0 * tw + 2.0 * gap
	var x0 := (vp.x - total) * 0.5
	var cap0 := Label.new()
	cap0.text = "接下来会翻的宝牌指示牌"
	cap0.add_theme_font_size_override("font_size", 18)
	cap0.add_theme_color_override("font_color", Color(0.9, 0.9, 0.9))
	cap0.position = Vector2(x0, 84)
	c38_ui.add_child(cap0)
	for i in range(3):
		var it: Dictionary = c38_dora[i]
		var b := _c38_tile_btn(String(it.get("tile", "")), Vector2(tw, th))
		b.position = Vector2(x0 + float(i) * (tw + gap), 112.0)
		b.pressed.connect(_c38_pick_dora.bind(i))
		c38_ui.add_child(b)
		c38_nodes["d%d" % i] = b
		var cap := Label.new()
		cap.text = "第%d张" % (i + 2)
		cap.add_theme_font_size_override("font_size", 16)
		cap.add_theme_color_override("font_color", Color(0.85, 0.85, 0.85))
		cap.position = Vector2(b.position.x + 6, 112.0 + th + 4.0)
		c38_ui.add_child(cap)
	# ── 我的手牌 ──
	var hw := 50.0
	var hh := 70.0
	var hgap := 6.0
	var hn := (c38_hand as Array).size()
	var total2 := float(hn) * hw + float(maxi(hn - 1, 0)) * hgap
	var x1 := (vp.x - total2) * 0.5
	var cap1 := Label.new()
	cap1.text = "我的手牌（不含副露）"
	cap1.add_theme_font_size_override("font_size", 18)
	cap1.add_theme_color_override("font_color", Color(0.9, 0.9, 0.9))
	cap1.position = Vector2(x1, 300)
	c38_ui.add_child(cap1)
	for j in range(hn):
		var it: Dictionary = c38_hand[j]
		var b := _c38_tile_btn(String(it.get("tile", "")), Vector2(hw, hh))
		b.position = Vector2(x1 + float(j) * (hw + hgap), 328.0)
		b.pressed.connect(_c38_pick_hand.bind(j))
		c38_ui.add_child(b)
		c38_nodes["h%d" % j] = b
	# ── 确认 / 取消（贴图，不叠字）──
	c38_ok = ui_btn("ok", 150.0)               # 并排：两个同尺寸
	c38_ok.pressed.connect(_c38s1_confirm)
	c38_ui.add_child(c38_ok)
	var cancel := ui_btn("pass", 150.0)
	cancel.pressed.connect(_c38s1_close)
	c38_ui.add_child(cancel)
	_place_btn_pair(c38_ok, cancel, vp.x * 0.5, 470.0)


func _c38s1_refresh() -> void:
	var order := {}
	for i in range(c38_picks.size()):
		var p: Dictionary = c38_picks[i]
		var key := "d%d" % int(p.get("i", -1)) if String(p.get("kind", "")) == "dora" \
				else "h%d" % int(p.get("j", -1))
		order[key] = i + 1
	for key in c38_nodes:
		var b: TextureButton = c38_nodes[key]
		if b == null or not is_instance_valid(b):
			continue
		var f = b.get_meta("frame", null)
		var num := b.get_node_or_null("Num") as Label
		if order.has(key):
			if f != null:
				(f as Node).visible = true
			if num != null:
				num.text = str(int(order[key]))
		else:
			if f != null:
				(f as Node).visible = false
			if num != null:
				num.text = ""
	if c38_ok != null and is_instance_valid(c38_ok):
		c38_ok.disabled = c38_picks.size() != 3


func _c38_toggle(pick: Dictionary) -> void:
	for i in range(c38_picks.size()):
		var q: Dictionary = c38_picks[i]
		if String(q.get("kind", "")) == String(pick.get("kind", "")) \
				and int(q.get("i", -1)) == int(pick.get("i", -1)) \
				and int(q.get("j", -1)) == int(pick.get("j", -1)):
			c38_picks.remove_at(i)
			_c38s1_refresh()
			return
	if c38_picks.size() >= 3:
		_toast("重整：已经选满 3 张（再点一次那张可以取消）")
		return
	c38_picks.append(pick)
	_c38s1_refresh()


func _c38_pick_dora(i: int) -> void:
	_c38_toggle({"kind": "dora", "i": i})


func _c38_pick_hand(j: int) -> void:
	var it: Dictionary = c38_hand[j]
	_c38_toggle({"kind": "hand", "j": j, "seq": int(it.get("seq", -1))})


func _c38s1_confirm() -> void:
	if c38_picks.size() != 3:
		_toast("重整：要选 3 张")
		return
	var arr: Array = []
	for i in range(c38_picks.size()):
		var p: Dictionary = c38_picks[i]
		if String(p.get("kind", "")) == "dora":
			arr.append({"kind": "dora", "i": int(p.get("i", -1))})
		else:
			arr.append({"kind": "hand", "seq": int(p.get("seq", -1))})
	var r := srv_request({"op": "c38s1_apply", "seat": my_seat, "picks": arr})
	if srv_kangpo_blocked(r):
		return
	if r.is_empty():
		_toast(_srv_err("重整：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "重整：发动失败")))
		_pull_state()
		return
	var d: Dictionary = r.get("c38", {})
	_c38s1_close()
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("重整：指示牌 → %s" % "、".join(d.get("dora", [])))


func _c38s1_close() -> void:
	c38_active = false
	c38_picks.clear()
	c38_nodes.clear()
	c38_ok = null
	if c38_ui != null and is_instance_valid(c38_ui):
		c38_ui.queue_free()
	c38_ui = null
	if c38_layer != null and is_instance_valid(c38_layer):
		c38_layer.queue_free()
	c38_layer = null


# ── Card37 S2【强运】───────────────────────────────────────────────
#   摸牌后点图标 → 牌种网格（34 种都能选）→ 彩框选中 → 「开始」确认：
#   下家/对家/上家手里这种牌，按顺位与牌山接下来第 4、8、12、16 张对调牌面。
var c37_kind := ""


func _c37s2_open() -> void:
	if game_over:
		return
	if _skill_used_once(37, 2):
		_toast("「强运」本小局已经发动过了")
		return
	if String(srv_state.get("phase", "")) != "discard" \
			or int(srv_state.get("turn", -1)) != my_seat \
			or String(srv_state.get("drawn", "")) == "":
		_toast("【强运】只能在自己摸完牌之后（打牌前）发动")
		return
	ql_picks.clear()
	c37_kind = ""
	var on_pick: Callable = func(k: String):
		ql_picks.clear()
		ql_picks.append(k)
		c37_kind = k
		_cg_refresh_grid()
		var head := cg_ui.get_node_or_null("Head") as Label if cg_ui != null else null
		if head != null:
			head.text = "强运：已选中【%s】—— 点「开始」确认" % k
	var on_ok: Callable = func(): _c37s2_confirm()
	_cg_show_kind_grid("强运：选一种牌（所有种类都能选）", on_pick, on_ok)


func _c37s2_confirm() -> void:
	if c37_kind == "":
		_toast("强运：先选一张牌")
		return
	var k := c37_kind
	var r := srv_request({"op": "c37s2_apply", "seat": my_seat, "kind": k})
	if srv_kangpo_blocked(r):
		# 已经交出去了：牌种网格必须收掉。
		# 留着的话 cg_active 恒 true → 点手牌/技能全没反应，而「开始」还能再点一次
		# → 又发一遍 op → 又回 need_kangpo，玩家看到的就是「等对方拦截」永远不停。
		_cg_kind_close()
		return
	if r.is_empty():
		_toast(_srv_err("强运：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "强运：发动失败")))
		_pull_state()
		return
	var d: Dictionary = r.get("c37s2", {})
	_cg_close()
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("强运：【%s】换了 %d 张 → %s"
		% [k, int(d.get("count", 0)), "、".join(d.get("tiles", []))])


# 【强运】的牌种网格跟着服务端状态收：技能已经在服务端生效
# （看破放行后重放 / 询问超时后重放）→ 把网格关掉。
# 不关的话 cg_active 恒 true：点手牌、点技能全没反应，看起来就是「发动了界面却不取消」。
func _c37s2_sync(_st: Dictionary) -> void:
	if cg_ui == null or not is_instance_valid(cg_ui):
		return
	if c37_kind == "":                 # 不是强运的网格（牌种网格和【前路】共用）
		return
	if _skill_used_once(37, 2):
		_cg_kind_close()


# ── Card37 S1【岭上开花】─────────────────────────────────────────────
#   听牌 + 能开杠/加杠时点图标：自动杠开 → 摸岭上 → 换成牌山里的和牌张，
#   然后由服务端给『自摸』按钮；点了才结算（得点 ×2，役种里带「岭上开花」）。
#   ★ 鸣牌窗口里（别人打出的牌正好能明杠）也点得动 —— 只粗筛时机，
#     能不能发由服务端判（用户 2026-10-28：屏幕上明明有杠按钮却点不动）。
func _c37s1_arm() -> void:
	if game_over:
		return
	var ph := String(srv_state.get("phase", ""))
	if ph != "claim" and not (ph == "discard" and int(srv_state.get("turn", -1)) == my_seat):
		_toast("【岭上开花】要「听牌 + 能开杠 / 加杠」时才能发动（摸打阶段，或出现杠按钮时）")
		return
	var r := srv_request({"op": "c37s1_arm", "seat": my_seat})
	if srv_kangpo_blocked(r):
		return
	if r.is_empty():
		_toast(_srv_err("岭上开花：服务端没有回应"))
		_pull_state()
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "岭上开花：发动失败")))
		_pull_state()
		return
	var d: Dictionary = r.get("c37", {})
	if bool(d.get("ready", false)):
		_c37s1_was_ready = true      # 这一发的提示由下面那条带牌名的话负责
	srv_apply_state(r.get("state"), r.get("events"))
	if bool(d.get("armed", false)):
		_toast("岭上开花：已记下这一杠 —— 等这张牌的鸣牌窗口结算")
		return
	if bool(d.get("ready", false)):
		var got := String(d.get("swapped", ""))
		if got == "":
			got = String(d.get("tile", ""))
		_toast("岭上开花：杠开成功，换进「%s」—— 点【自摸】结算（得点 ×2）" % got)
	else:
		_toast("岭上开花：%s" % String(d.get("why", "这次没成（杠已开、技能已消耗，正常打牌）")))


var _c37s1_was_ready := false


# 【岭上开花】服务端把「岭上牌 ⇄ 牌山里的和牌张」换好了 → 提示一次。
# 鸣牌窗口里点的那一杠，要等窗口结算才真的开出来（甚至可能是别人一次请求触发的），
# 所以结果只能从状态里看（state.c37.ready），不能在 _c37s1_arm 的回包里等。
func _c37s1_sync(st: Dictionary) -> void:
	var c = st.get("c37")
	var now := typeof(c) == TYPE_DICTIONARY and bool((c as Dictionary).get("ready", false))
	if now and not _c37s1_was_ready:
		_toast("岭上开花：岭上牌已换好 —— 点【自摸】结算（得点 ×2）")
	_c37s1_was_ready = now


# ── Card36 S2【故意】─────────────────────────────────────────────────
#   切牌前点图标开启；打出这一张时，若它能让某家手牌成「4 面子 + 1 雀头」
#   （不判役 / 不判振听 / 不看其他技能）→ 立刻结算，我付他 1000 点。
# ── Card44 S2【电报】─────────────────────────────────────────────────
#   摸牌后点图标：手牌宣言成明牌（别人视角都看得到），本局和牌按 30 符 1 番。
#   明牌只是「reveal_hands」那条渲染链多了一行（服务端下发），客户端不用额外画。
#   仍会被【浓雾】【满贯】拦下；【自信】【暖气】照样加成。
func _c44s2_arm() -> void:
	if game_over:
		return
	if _skill_used_once(44, 2):
		_toast("「电报」本小局已经发动过了")
		return
	if String(srv_state.get("phase", "")) != "discard" \
			or int(srv_state.get("turn", -1)) != my_seat:
		_toast("【电报】只能在自己摸牌后、打牌前发动")
		return
	if bool(srv_state.get("c44s2_on", false)):
		_toast("【电报】已经开着：本局和牌按 30 符 1 番")
		return
	var r := srv_request({"op": "c44s2_arm", "seat": my_seat})
	if srv_kangpo_blocked(r):
		return
	if r.is_empty():
		_toast(_srv_err("电报：服务端没有回应"))
		_pull_state()
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "电报：发动失败")))
		_pull_state()
		return
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("电报：手牌已明置 —— 本局和牌按 30 符 1 番结算")


func _c36s2_arm() -> void:
	if game_over:
		return
	if _skill_used_once(36, 2):
		_toast("「故意」本小局已经发动过了")
		return
	if String(srv_state.get("phase", "")) != "discard" \
			or int(srv_state.get("turn", -1)) != my_seat:
		_toast("【故意】只能在自己的切牌阶段发动")
		return
	if bool(((srv_state.get("c36", {}) as Dictionary) if typeof(srv_state.get("c36")) == TYPE_DICTIONARY else {}).get("s2", false)):
		_toast("【故意】已经开着：打出一张牌就会判定")
		return
	var r := srv_request({"op": "c36s2_arm", "seat": my_seat})
	if srv_kangpo_blocked(r):
		return
	if r.is_empty():
		_toast(_srv_err("故意：服务端没有回应"))
		_pull_state()
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "故意：发动失败")))
		_pull_state()
		return
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("故意：已开启 —— 打出这一张，谁的手牌能和就立刻结算（我付 1000 点）")


# 【海底】（34S2）：点图标 = 问服务端要一句「现在为什么没发动」
#   服务端 c34s2_probe 只读：不改牌山、不发牌，随便点。
#   `would_fire` = 打出现在这张牌就会自动发动（厄运 +1 并静默三家）。
func _c34s2_probe() -> void:
	if game_over:
		return
	var r := srv_request({"op": "c34s2_probe", "seat": my_seat})
	if r.is_empty():
		_toast("【海底】服务端没有回应")
		return
	var d = r.get("c34s2")
	if typeof(d) != TYPE_DICTIONARY:
		_toast("【海底】服务端没有回应")
		return
	var dd := d as Dictionary
	var ll := int(dd.get("live_left", 0))
	if bool(dd.get("would_fire", false)):
		_toast("【海底】条件是满足的：打出这张牌就自动发动【厄运】，海底锁定「%s」（剩 %d 张）"
				% [String(dd.get("in_wall", "")), ll])
		return
	var why := String(dd.get("why", ""))
	if why == "":
		why = "条件还不满足"
	_toast("【海底】现在不能发动：%s（还剩 %d 张可摸，要正好 12 张）" % [why, ll])


# 【海底】（34S2）：剩 12 张没触发时，服务端会给一句原因 —— 只提示一次
# 【流势】(35S1)：每次副露后服务端挂一个待办 → 自动弹「排接下来 4 张」
#   和天梯同一块面板；区别是这里排完不摸牌（接着打牌），而且是**每次副露**都来。
# 【思路】(36S1)：别人宣告技能 → 服务端把我该看的手牌塞进 reveal_hands（已渲染），
#   这里只负责「多了一张新面孔」时提示一句。打出一张牌后会自动复位。
var c36_seen: Array = []


func _c36_sync(st: Dictionary) -> void:
	var d = st.get("c36")
	if typeof(d) != TYPE_DICTIONARY:
		return
	var on: Array = (d as Dictionary).get("on", [])
	var cur := int_set(on)
	# 掉出去的座位清掉记录 → 下次同一个再发动还能再提示
	for s in c36_seen.duplicate():
		if not cur.has(int(s)):
			c36_seen.erase(int(s))
	var fresh: Array = []
	for s in on:
		if not int_set(c36_seen).has(int(s)):
			fresh.append(int(s))
			c36_seen.append(int(s))
	if fresh.is_empty():
		return
	var names: Array = []
	for s in fresh:
		names.append(srv_name_of(int(s)))
	_toast("思路：看到 %s 的手牌（打出一张牌后失效）" % "、".join(names))


func _c35_sync(st: Dictionary) -> void:
	var d = st.get("c35")
	if typeof(d) != TYPE_DICTIONARY:
		return
	var dd := d as Dictionary
	var mark := int(dd.get("mark", -1))
	if not bool(dd.get("can", false)):
		if c26_active and c26_op == "c35s1_set":
			_c26_close()
		return
	var tiles: Array = dd.get("tiles", [])
	if (tiles as Array).is_empty():
		return
	if c26_active and c26_op == "c35s1_set":
		return
	if mark == c35_mark:
		return                           # 这一次已经弹过
	if _skill_panel_open() and not c26_active:
		return                           # 别的选牌/发动面板还开着 → 等它关了再弹（下一帧重试）
	c35_mark = mark
	c26_op = "c35s1_set"
	c26_res_key = "c35"
	c26_title = "流势"
	c26_after_draw = false
	_c26_open_tiles(tiles)


func _c34_why_sync(st: Dictionary) -> void:
	var d = st.get("c34")
	if typeof(d) != TYPE_DICTIONARY:
		return
	var why := String((d as Dictionary).get("s2_why", ""))
	if why == "":
		c34_why_key = ""
		return
	var key := "%s-%d-%d" % [why, int(st.get("live_left", 0)), int(st.get("round_id", 0))]
	if key == c34_why_key:
		return
	c34_why_key = key
	_toast("【海底】没触发：" + why)


func _make_flow_ui() -> void:
	if flow_ui != null:
		return
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	flow_ui = Control.new()
	flow_ui.name = "DealSwapUI"
	flow_ui.z_index = 250
	host.add_child(flow_ui)
	flow_ui.position = Vector2.ZERO

	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	flow_start_btn = TextureButton.new()
	flow_start_btn.name = "FlowStart"
	flow_start_btn.texture_normal = tex
	flow_start_btn.ignore_texture_size = true
	flow_start_btn.stretch_mode = TextureButton.STRETCH_SCALE
	flow_start_btn.focus_mode = Control.FOCUS_NONE
	flow_start_btn.size = Vector2(bw, bh)
	flow_start_btn.position = prompt_btn_pos(bw, bh)
	flow_start_btn.visible = false
	flow_start_btn.pressed.connect(_flow_confirm)
	flow_ui.add_child(flow_start_btn)



func _update_flow_view() -> void:
	hand_pick.sync()                     # 手牌变暗统一由 hand_pick 负责


func _toggle_flow_hand(index: int) -> void:
	if not flow_active:
		return
	if flow_kind == "dora_luck":
		var all := display_tiles()
		if index >= 0 and index < all.size() and srv_is_dora(String(all[index])):
			_toast("宝牌运：宝牌不能拿去交换")
			return
	hand_pick.toggle(index)


func _refresh_flow_button() -> void:
	if flow_start_btn == null or not is_instance_valid(flow_start_btn):
		return
	flow_start_btn.visible = flow_active and hand_pick.ready()


func _flow_sync(st: Dictionary) -> void:
	var f = st.get("deal_flow")
	if typeof(f) != TYPE_DICTIONARY:
		_flow_close()
		return
	var fk := String((f as Dictionary).get("kind", "fengshen"))
	if fk != "fengshen" and fk != "dora_luck":
		return
	if int((f as Dictionary).get("seat", -1)) != my_seat:
		return
	var stage := int((f as Dictionary).get("stage", -1))
	if flow_active and stage == flow_stage:
		return
	flow_active = true
	flow_kind = fk
	flow_stage = stage
	flow_target = int((f as Dictionary).get("target", -1))
	flow_n = int((f as Dictionary).get("n", 0))
	hand_pick.begin(flow_picks, flow_n, {"on_change": _refresh_flow_button})
	_set_deal_skip_visible(false)
	_make_flow_ui()
	_update_flow_view()
	_refresh_flow_button()
	if fk == "dora_luck":
		_toast("宝牌运：%s有 %d 张宝牌 —— 请选 %d 张非宝牌手牌去换"
			% [_rel_seat_name(flow_target), flow_n, flow_n])
	else:
		_toast("风神：与%s交换 %d 张风牌 —— 请选 %d 张手牌"
			% [_rel_seat_name(flow_target), flow_n, flow_n])


func _flow_confirm() -> void:
	if not flow_active:
		return
	var tiles := display_tiles()
	var picked: Array = []
	for i in flow_picks:
		if i >= 0 and i < tiles.size():
			picked.append(String(tiles[i]))
	if picked.size() != flow_n:
		return
	var r := srv_request({"op": "deal_swap", "seat": my_seat,
		"stage": flow_stage, "tiles": picked})
	if r.is_empty():
		_toast(_srv_err("风神换牌失败：服务端没有回应"))
		_flow_close()
		return
	var ds: Dictionary = r.get("deal_swap", {})
	var got_csv := "、".join(picked)
	var cnt := int(ds.get("count", 0))
	var was_dl := flow_kind == "dora_luck"
	srv_apply_state(r.get("state"), r.get("events"))
	if was_dl:
		_toast("宝牌运：用 %s 换到 %d 张宝牌" % [got_csv, cnt])
	else:
		_toast("风神：用 %s 换到 %d 张风牌" % [got_csv, cnt])


func _flow_close() -> void:
	if not flow_active and flow_ui == null:
		return                                    # 已经收起来了，别每帧扫一遍牌
	flow_active = false
	flow_picks.clear()
	hand_pick.end()
	flow_n = 0
	flow_stage = -1
	flow_target = -1
	flow_kind = "fengshen"
	if flow_start_btn != null and is_instance_valid(flow_start_btn):
		flow_start_btn.visible = false
	if flow_ui != null and is_instance_valid(flow_ui):
		flow_ui.queue_free()
	flow_ui = null
	flow_start_btn = null
	_set_deal_skip_visible(true)
	_update_flow_view()


# ── 配牌技能窗口（庄家跳完牌之后）────────────────────────────────────
#   有配牌技能的人：可以点技能图标发动，或点「开始」跳过。
#   所有人都发动完 / 跳过后，庄家才能切牌。
var deal_ui: Control = null
var deal_skip_btn: TextureButton = null
var deal_shown := false


func _make_deal_ui() -> void:
	if deal_ui != null:
		return
	var vp := get_viewport_rect().size
	var host: Node = get_parent()
	if host == null:
		host = self
	deal_ui = Control.new()
	deal_ui.name = "DealSkillUI"
	deal_ui.z_index = 250
	host.add_child(deal_ui)
	deal_ui.position = Vector2.ZERO

	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	deal_skip_btn = TextureButton.new()
	deal_skip_btn.name = "DealSkip"
	deal_skip_btn.texture_normal = tex
	deal_skip_btn.ignore_texture_size = true
	deal_skip_btn.stretch_mode = TextureButton.STRETCH_SCALE
	deal_skip_btn.focus_mode = Control.FOCUS_NONE
	deal_skip_btn.size = Vector2(bw, bh)
	deal_skip_btn.position = prompt_btn_pos(bw, bh)
	deal_skip_btn.pressed.connect(_deal_skip)
	deal_ui.add_child(deal_skip_btn)



func _deal_skip() -> void:
	if not is_inside_tree():
		return
	var r := srv_request({"op": "deal_skill", "seat": my_seat, "action": "skip"})
	if r.is_empty():
		_toast(_srv_err("跳过失败：服务端没有回应"))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("跳过配牌技能，进入切牌阶段")


func _deal_hide() -> void:
	deal_shown = false
	if deal_ui != null and is_instance_valid(deal_ui):
		deal_ui.queue_free()
	deal_ui = null
	deal_skip_btn = null


# 配牌窗口的「开始（= 跳过）」按钮：技能自己的选牌界面开着时先藏起来，
# 否则两个「开始」按钮叠在同一个位置，玩家点确认时可能误触发跳过。
func _set_deal_skip_visible(v: bool) -> void:
	if deal_skip_btn != null and is_instance_valid(deal_skip_btn):
		deal_skip_btn.visible = v


func _update_deal_window(st: Dictionary) -> void:
	var ds = st.get("deal_skill")
	var mine: Array = []
	if typeof(ds) == TYPE_DICTIONARY:
		mine = (ds as Dictionary).get("mine", [])
	if mine.is_empty():
		_deal_hide()
		return
	if deal_ui == null:
		_make_deal_ui()
	# 配牌换牌流程（风神 / 宝牌运 / 向听）进行中：先别给「开始（跳过）」，
	# 它会把这个流程掐掉，而且和技能自己的确认按钮挤在同一个位置。
	# 向听在「选两家」阶段还没有 deal_flow，所以面板开着也一起藏。
	var hide_skip := typeof(st.get("deal_flow")) == TYPE_DICTIONARY or c30_panel.active
	_set_deal_skip_visible(not hide_skip)
	if not deal_shown:
		deal_shown = true
		var nm := "技能"
		if not mine.is_empty() and typeof(mine[0]) == TYPE_DICTIONARY:
			nm = String((mine[0] as Dictionary).get("name", "技能"))
		_toast("配牌阶段：可发动「%s」，或点「开始」跳过" % nm)


# ── 技能播报（画面中上部，行楷，黑字）────────────────────────────────
const BROADCAST_FONT := "res://Cailiao/fonts/xingkai.ttf"
var broadcast_label: Label = null
var broadcast_tween: Tween = null
var _last_broadcast_id := 0


func _show_broadcast(text: String) -> void:
	if broadcast_label == null or not is_instance_valid(broadcast_label):
		var host: Node = get_parent()
		if host == null:
			host = self
		broadcast_label = Label.new()
		broadcast_label.name = "SkillBroadcast"
		broadcast_label.z_index = 300
		broadcast_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		broadcast_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		broadcast_label.add_theme_font_size_override("font_size", 52)
		broadcast_label.add_theme_color_override("font_color", Color(0, 0, 0, 1))
		broadcast_label.add_theme_color_override("font_outline_color", Color(1, 1, 1, 0.9))
		broadcast_label.add_theme_constant_override("outline_size", 6)
		var f := load(BROADCAST_FONT) as Font
		if f != null:
			broadcast_label.add_theme_font_override("font", f)
		host.add_child(broadcast_label)
		broadcast_label.size = Vector2(get_viewport_rect().size.x, 90)
		broadcast_label.position = Vector2(0, 175)
	broadcast_label.text = text
	broadcast_label.modulate.a = 1.0
	broadcast_label.visible = true
	if broadcast_tween != null and broadcast_tween.is_valid():
		broadcast_tween.kill()
	broadcast_tween = create_tween()
	broadcast_tween.tween_interval(2.0)          # 先完整显示 2 秒
	broadcast_tween.tween_property(broadcast_label, "modulate:a", 0.0, 1.0)
	broadcast_tween.tween_callback(_hide_broadcast)


func _hide_broadcast() -> void:
	if broadcast_label != null and is_instance_valid(broadcast_label):
		broadcast_label.visible = false


func _apply_broadcast(st: Dictionary) -> void:
	var b = st.get("broadcast")
	if typeof(b) != TYPE_DICTIONARY:
		return
	var bid := int((b as Dictionary).get("id", 0))
	if bid <= _last_broadcast_id:
		return
	_last_broadcast_id = bid
	var txt := String((b as Dictionary).get("text", ""))
	if txt != "":
		_show_broadcast(txt)                      # 服务端给了整句就用它（比如降神的骰子播报）
		return
	var wind_cn := {"dong": "东", "nan": "南", "xi": "西", "bei": "北"}
	var wind := String(wind_cn.get(String((b as Dictionary).get("wind", "")), ""))
	var nm := String((b as Dictionary).get("name", "技能"))
	_show_broadcast("【%s】玩家发动了【%s】！" % [wind, nm])


# 协战卡遮罩：{座位: 卡号} → Identity 在那张协战卡上盖一层「遮罩」
func _support_mute_apply(st: Dictionary) -> void:
	var idn := get_node_or_null("Identity")
	if idn == null or not idn.has_method("set_support_muted"):
		return
	var sm = st.get("support_mute")
	idn.call("set_support_muted", sm if typeof(sm) == TYPE_DICTIONARY else {})


# ── 别人视角里暗置的人物卡：第一次发动技能后永久翻明 ────────────────
func _apply_revealed(st: Dictionary) -> void:
	var idn := get_node_or_null("Identity")
	if idn == null:
		return
	# 主战 / 协战遮罩：默认遮住，发动过技能就一直开着，两风场过后永久遮住
	if idn.has_method("set_char_states") and typeof(st.get("char_states")) == TYPE_ARRAY:
		idn.call("set_char_states", st.get("char_states"))
	# 传承：只换 16 号卡的**技能图标**（卡面不动）；没有复制就换回来
	if idn.has_method("set_skill_icon"):
		var _cp0 := _cc_copy(st)
		if _cp0.is_empty():
			idn.call("set_skill_icon", 16, 0, 0, 1)
		else:
			idn.call("set_skill_icon", 16, 0,
				int(_cp0.get("card", 0)), int(_cp0.get("skill", 1)))
	if not idn.has_method("reveal_seat"):
		return
	for s in (st.get("revealed", []) as Array):
		idn.call("reveal_seat", int(s))


# ── Card03 Skill2「压制」──────────────────────────────────────────────
#   摸牌后、打牌前发动，两段共用一个选牌界面：
#     · 选「自己牌河的明牌」 → 一次性那段（每局一次）
#     · 选「任意一家的暗置牌」→ 不限次数那段
#   手牌全部变暗 50%，选 1 张手牌（再点取消）→ 选 1 张牌河牌（彩框）
#   → 正下方「开始按钮」→ 交换：牌河那张进手牌，手牌暗置进牌河。
#   持有这张卡的人看牌河的暗置牌永远是明牌，也可以荣和暗置牌。
# Card03 S2「压制」：通用面板（手牌 1 张 + 牌河 1 张；暗置牌任意家、明牌只自己牌河）
var press_panel := SkillPanel.new()


func _press_start() -> void:
	if press_panel.active or swap_panel.active or ym_panel.active or c24_panel.active \
			or game_over:
		return                                  # 三个面板共用同一个 hand_pick，不能同时开
	if not bool(srv_state.get("press_can", false)):
		_toast("压制：要持这张卡、刚摸完牌，而且这次摸牌还没交换过")
		return
	press_panel.begin({
		"name": "压制",
		"want": 1, "min": 1,
		"river": true, "river_match": true,
		"cancel": true,
		"river_ok": _press_river_ok_seq,
		"on_confirm": _press_confirm,
	})
	_toast("压制：选一张手牌，再选一张牌河牌")


# 牌河可点规则（面板的 river_ok 是 func(seq, seat, down)）
func _press_river_ok_seq(_seq: int, seat: int, down: bool) -> bool:
	return _press_river_ok(seat, down)


func _press_river_ok(seat: int, down: bool) -> bool:
	if down:
		return true                       # 暗置牌：任意一家的都能换
	return seat == my_seat                # 明牌：只能换自己牌河里的


func _press_confirm(picks: Array, rivers: Array) -> void:
	var tiles := display_tiles()
	if picks.is_empty() or rivers.is_empty():
		return
	if int(picks[0]) >= tiles.size():
		return
	var hand := String(tiles[int(picks[0])])
	var r := srv_request({"op": "press", "seat": my_seat,
		"hand": hand, "river": int(rivers[0])})
	if srv_kangpo_blocked(r):
		return                            # 面板已在 confirm 时关掉
	if r.is_empty():
		_toast(_srv_err("压制换牌失败：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "压制换牌失败")))
		return
	var pr: Dictionary = r.get("press", {})
	srv_apply_state(r.get("state"), r.get("events"))
	var how := "暗置牌" if String(pr.get("mode", "")) == "down" else "自己牌河"
	_toast("压制（%s）：%s ⇄ %s" % [how, hand, String(pr.get("river", ""))])


func _press_close() -> void:
	press_panel.close()
	_apply_entity_states(srv_state)



func _maybe_close_press(st: Dictionary) -> void:
	if not press_panel.active:
		return
	if String(st.get("phase", "")) != "discard" or int(st.get("turn", -1)) != my_seat:
		_press_close()


# ── Card02 Skill2「换牌」──────────────────────────────────────────────
#   摸牌后、第十三巡前，本小局一次：
#   手牌全部变暗 50% → 选三张手牌（再点取消）→ 选三张全场牌河的牌（彩框）
#   → 三张手牌暗置进牌河替换它们，那三张牌河牌进我的手牌。
#   换进来的牌河牌不算「打出去的牌」，别人不会因此额外振听。
# Card02 S2「换牌」：通用面板（按钮/手牌亮度/牌河点击/取消/卡死兜底都由 skill_panel 管）
var swap_panel := SkillPanel.new()
var c43_panel := SkillPanel.new()      # Card43 S1「NO MISS」：手牌 2 张 ⇄ 牌河 2 张
var c45_panel := SkillPanel.new()      # Card45 S1「神境」：手牌 + 牌河合计 13 张
var c45_key := ""                     # 神境：这一巡问过的标记（跳过不重复问）
var c46_panel := SkillPanel.new()      # Card46 S1「恶听」：选 1 张切出去听牌的手牌
var c33_panel := SkillPanel.new()      # Card33 S1「染手」：3 张手牌 + 牌河一组面子
var c33s2_ui: Control = null          # Card33 S2「记忆」的输入框
var c33s2_layer: CanvasLayer = null    # 它单独一层（Node2D 的 z_index 会盖住 Control）
var c33s2_edit: LineEdit = null
var c34_why_key := ""                 # 【海底】没触发的原因只 toast 一次
# ── Card24 S1「一发」─────────────────────────────────────────────────
#   摸牌后、处于「可立直」状态 → 点图标 → 默认方式选一张「打出去能立直」的牌
#   → 开始 → 服务端横置打出、进立直；牌山/王牌里有我的胡张就把「一发」开启
var c24_panel := SkillPanel.new()


func _c24_on_clicked() -> void:
	if c24_panel.active:
		c24_panel.close()
		_toast("一发：取消")
		return
	if game_over:
		return
	if not bool(srv_state.get("c24_can", false)):
		_toast("一发：要刚摸完牌、而且现在是能立直的状态")
		return
	if swap_panel.active or press_panel.active or ym_panel.active:
		_toast("先把现在的选牌面板处理掉")
		return
	c24_panel.begin({
		"name": "一发",
		"want": 1, "min": 1,              # 只选一张（打出去能立直的那张）
		"cancel": true,
		"on_confirm": _c24_confirm,
	})
	_toast("一发：选一张打出去能立直的牌 → 开始")


# ── Card27 S1「调包」/ S2「命中」──────────────────────────────────────
#   S1：摸牌后点图标 → 选 1 张手牌 + 1 张**别人牌河的明牌** → 开始 → 互换
#       （换的谁的牌就进谁的牌河，换进来的那张进我手里），并标记那一家；本小局一次。
#       立直宣言牌能换，暗置牌不能换。
#   S2：摸牌后点图标 → 选一张「切出后仍然有役听牌 / 门清」的牌 → 开始 →
#       暗置打出（门清同时立直 → 暗置 + 横置）；按序数 147 下家 / 258 对家 /
#       369 上家标记，字牌不标记；之后只能摸切；本小局一次（失败也不退）。
var c27_panel := SkillPanel.new()
var c27_mode := ""


func srv_c27_list(key: String) -> Array:
	var a = srv_state.get(key)
	return a if typeof(a) == TYPE_ARRAY else []


func srv_c27_has(key: String, v: int) -> bool:
	for x in srv_c27_list(key):
		if int(x) == int(v):
			return true
	return false


func srv_c27s1_can() -> bool:
	return bool(srv_state.get("c27s1_can", false))


func srv_c27s2_can() -> bool:
	return bool(srv_state.get("c27s2_can", false))


# 这张手牌「切出去还听牌」吗（服务端算好的候选）
func srv_c27s2_ok(tile_id: String) -> bool:
	for x in srv_c27_list("c27s2_tiles"):
		if String(x) == String(tile_id):
			return true
	return false


func srv_c27_mark() -> int:
	return int(srv_state.get("c27_mark", -1))


func srv_c27_cnt() -> int:
	return int(srv_state.get("c27_cnt", 0))


func _c27s1_open() -> void:
	if c27_panel.active:
		c27_panel.close()
		_toast("调包：取消")
		return
	if game_over:
		return
	if not srv_c27s1_can():
		_toast("调包：要刚摸完牌、而且本小局还没用过")
		return
	if _skill_panel_open():
		_toast("先把现在的选牌面板处理掉")
		return
	c27_mode = "s1"
	c27_panel.begin({
		"name": "调包",
		"want": 1, "min": 1,
		"river": true, "river_match": true,
		"cancel": true,
		"river_ok": _c27_river_ok,
		"on_confirm": _c27s1_confirm,
	})
	_toast("调包：选一张手牌，再点别人牌河里的一张明牌 → 开始")


# 牌河可点：只认服务端列的「别人牌河的明牌」（立直宣言牌可以，暗置牌不行）
func _c27_river_ok(seq: int, _seat: int, down: bool) -> bool:
	if down:
		return false
	return srv_c27_has("c27s1_rivers", seq)


func _c27s1_confirm(picks: Array, rivers: Array) -> void:
	var tiles := display_tiles()
	if picks.is_empty() or rivers.is_empty():
		return
	if int(picks[0]) >= tiles.size():
		return
	var hand := String(tiles[int(picks[0])])
	var r := srv_request({"op": "c27s1_swap", "seat": my_seat,
		"hand": hand, "river": int(rivers[0])})
	if srv_kangpo_blocked(r):
		return                            # 面板已在 confirm 时关掉
	if r.is_empty():
		_toast(_srv_err("调包失败：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "调包失败")))
		return
	var sw: Dictionary = {}
	if typeof(r.get("c27s1")) == TYPE_DICTIONARY:
		sw = r.get("c27s1")
	srv_apply_state(r.get("state"), r.get("events"))
	if not sw.is_empty():
		_toast("调包：%s ⇄ %s（标记 %d 号位）"
			% [hand, String(sw.get("got", "")), int(sw.get("mark", -1))])


func _c27s2_open() -> void:
	if c27_panel.active:
		c27_panel.close()
		_toast("命中：取消")
		return
	if game_over:
		return
	if not srv_c27s2_can():
		_toast("命中：要刚摸完牌、切出后仍听牌（门清一定行），而且本小局还没用过")
		return
	if _skill_panel_open():
		_toast("先把现在的选牌面板处理掉")
		return
	c27_mode = "s2"
	c27_panel.begin({
		"name": "命中",
		"want": 1, "min": 1,
		"cancel": true,
		"on_confirm": _c27s2_confirm,
	})
	_toast("命中：选一张「打出去仍然听牌」的牌 → 开始（暗置打出，门清连立直）")


func _c27s2_confirm(picks: Array, _rivers: Array) -> void:
	var tiles := display_tiles()
	if picks.is_empty() or int(picks[0]) >= tiles.size():
		return
	var t := String(tiles[int(picks[0])])
	if not srv_c27s2_ok(t):
		_toast("命中：这张打出去就不听牌了")
		return
	var r := srv_request({"op": "c27s2_declare", "seat": my_seat, "tile": t})
	if srv_kangpo_blocked(r):
		return
	if r.is_empty():
		_toast(_srv_err("命中失败：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "命中发动失败")))
		return
	var d: Dictionary = {}
	if typeof(r.get("c27s2")) == TYPE_DICTIONARY:
		d = r.get("c27s2")
	srv_apply_state(r.get("state"), r.get("events"))
	var mk := int(d.get("mark", -1))
	var riichi_txt := "、同时立直" if bool(d.get("riichi", false)) else ""
	if mk >= 0:
		_toast("命中：%s 暗置打出%s；标记 %d 号位（他手切 3 张就出铳）"
			% [t, riichi_txt, mk])
	else:
		_toast("命中：%s 暗置打出%s（字牌不标记）" % [t, riichi_txt])


func _c27_close() -> void:
	c27_panel.close()
	c27_mode = ""
	_apply_entity_states(srv_state)


# ── Card25 S2「宝牌的集合」────────────────────────────────────────────
#   配牌：【宝牌运】结算完自动紧接发动（要再过一次看破），开着之后：
#   别人摸到宝牌 → 我拿一张非宝牌换过来（不能跳过、不能拿宝牌换）。
#   杠翻出来的表宝牌全场无效；我胡牌时每杠 +4 番（服务端算进宝牌里）。
var c25b_panel := SkillPanel.new()
var c25b_key := ""
var c30_panel := C30Panel.new()      # Card30 S1「向听」：选两家 / 交牌 / 挑牌互换
var c30_key := ""                    # 去重：同一笔询问只开一次面板
var c32_panel := C30Panel.new()      # Card32 S1「新手运」：同一个面板类，op 前缀不同
var c32_key := ""
var c25s2_arm_t := 0.0


func srv_c25s2_can() -> bool:
	return bool(srv_state.get("c25s2_can", false))


func srv_c25s2_on() -> bool:
	return bool(srv_state.get("c25s2_on", false))


# 配牌阶段：宝牌运结算完 → 自动替玩家发一次「宝牌的集合」发动（要过看破）
func _c25s2_auto_arm() -> void:
	if game_over or srv_busy or _srv_kangpo_wait():
		return
	if not srv_c25s2_can():
		c25s2_arm_t = 0.0
		return
	var now := Time.get_ticks_msec() / 1000.0
	if c25s2_arm_t > 0.0 and now - c25s2_arm_t < 1.5:
		return                       # 上一次还在被看破拦着，等一会儿再试
	c25s2_arm_t = now
	var r := srv_request({"op": "c25s2_arm", "seat": my_seat})
	if r.is_empty():
		return
	if srv_kangpo_blocked(r):
		_toast("宝牌的集合：等对方决定是否看破…")
		return
	var dr: Dictionary = r.get("c25s2", {})
	if bool(dr.get("c25s2_on", false)):
		_toast("宝牌的集合：本小局开启 —— 杠翻出来的表宝牌无效，别人摸到宝牌我会去换")
	srv_apply_state(r.get("state"), r.get("events"))


func _c25b_sync(st: Dictionary) -> void:
	var off = st.get("c25s2_offer")
	if typeof(off) == TYPE_DICTIONARY and not (off as Dictionary).is_empty():
		var o := off as Dictionary
		if not c25b_panel.active:
			c25b_key = "%d-%d-%s" % [int(o.get("from", -1)),
				int(st.get("live_left", 0)), String(o.get("tile", ""))]
			_c25b_open(String(o.get("tile", "")), int(o.get("from", -1)))
	elif c25b_panel.active:
		c25b_panel.close()


func _c25b_open(tile: String, from_seat: int) -> void:
	c25b_panel.begin({
		"name": "宝牌的集合",
		"want": 1, "min": 1,
		"cancel": false,                     # 不能跳过
		"close_on_confirm": true,
		"on_confirm": _c25b_confirm,
	})
	_toast("宝牌的集合：%s摸到宝牌 %s —— 选一张非宝牌跟他换（不能跳过）"
		% [_rel_seat_name(from_seat), tile])


func _c25b_confirm(picks: Array, _rivers: Array) -> void:
	var tiles := display_tiles()
	var hand := ""
	if not picks.is_empty():
		var idx := int(picks[0])
		if idx >= 0 and idx < tiles.size():
			hand = String(tiles[idx])
	if hand == "":
		_toast("宝牌的集合：必须选一张手牌（不能跳过）")
		return
	var r := srv_request({"op": "c25s2_swap", "seat": my_seat, "hand": hand})
	if r.is_empty():
		_toast(_srv_err("宝牌的集合：服务端没有回应"))
		return
	var sw: Dictionary = r.get("c25s2_swap", {})
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("宝牌的集合：用 %s 换到宝牌 %s" % [hand, String(sw.get("got", ""))])


# ── Card24 S2「未来」：摸牌前把接下来 5 张牌山重新排序 ────────────────
#   交互照「开局选人物卡出战顺序」那套：按你要的顺序点牌，牌上出现 1~5 的编号；
#   「开始」= 跳过；5 张都排好后出现「确认」。
const FUTURE_N := 5
const FUTURE_TILE_W := 112.0
const FUTURE_TILE_H := 156.0
const FUTURE_GAP := 26.0
var future_active := false
var future_ui: Control = null
var future_layer: CanvasLayer = null      # 人物卡在 CardPhase(layer=20) 里，要压过它
var future_tiles: Array = []              # 5 张牌面（服务端只发给发动者）
var future_order: Array = []              # 玩家点选的顺序（存下标）
var future_slots: Array = []              # [{btn, num}]
var future_ask_ui: Control = null          # 询问阶段：只有「跳过」一个按钮
var future_ask_btn: TextureButton = null
var future_btn_ok: TextureButton = null
var future_ask_key := ""                  # 同一次摸牌只自动问一次


# 摸牌前：能发动就问一句 —— **只出「跳过」按钮，不亮牌**
# （点技能图标 = 直接发动，那才是发动点、可被看破；之后才亮牌给玩家排序）
func _future_gate_before_draw() -> bool:
	if future_active:
		return true                       # 面板开着：先别摸牌
	if future_ask_ui != null and is_instance_valid(future_ask_ui):
		return true                       # 询问按钮还摆着：先别摸牌
	if _srv_kangpo_wait():
		return false
	if is_skill_muted(24, 2):
		return false                      # 图标盖了遮罩 → 不再自动询问
	if not bool(srv_state.get("future_can", false)):
		return false
	var key := "%d-%d" % [int(srv_state.get("live_left", 0)), int(srv_state.get("turn", 0))]
	if key == future_ask_key:
		return false                      # 这一次摸牌问过了（跳过就别再弹）
	future_ask_key = key
	_future_ask_show()
	return true


func _future_ask_show() -> void:
	if future_ask_ui != null and is_instance_valid(future_ask_ui):
		return
	var host: Node = get_parent()
	if host == null:
		host = self
	future_ask_ui = Control.new()
	future_ask_ui.name = "FutureAskUI"
	future_ask_ui.z_index = 262
	future_ask_ui.position = Vector2.ZERO
	host.add_child(future_ask_ui)
	var tex := btn_tex("pass")
	var aspect := 70.0 / 220.0
	if tex != null and tex.get_width() > 0:
		aspect = float(tex.get_height()) / float(tex.get_width())
	var rc := prompt_btn_rect(aspect)
	future_ask_btn = TextureButton.new()
	future_ask_btn.name = "FutureSkip"
	future_ask_btn.texture_normal = tex
	future_ask_btn.ignore_texture_size = true
	future_ask_btn.stretch_mode = TextureButton.STRETCH_SCALE
	future_ask_btn.focus_mode = Control.FOCUS_NONE
	future_ask_btn.position = rc.position
	future_ask_btn.size = rc.size
	future_ask_btn.pressed.connect(_future_ask_skip)
	future_ask_ui.add_child(future_ask_btn)
	_toast("未来：想发动就点技能图标（会被看破）；点「开始」跳过")


func _future_ask_skip() -> void:
	if future_ask_ui != null and is_instance_valid(future_ask_ui):
		future_ask_ui.queue_free()
	future_ask_ui = null
	future_ask_btn = null
	_toast("未来：跳过")
	draw_tile()


func _future_ask_hide() -> void:
	if future_ask_ui != null and is_instance_valid(future_ask_ui):
		future_ask_ui.queue_free()
	future_ask_ui = null
	future_ask_btn = null


# 点技能图标 = **直接发动**（这一刻算发动点，服务端先问看破）→ 成功后才有选牌界面
func _future_on_clicked() -> void:
	if future_active:
		_toast("未来：已经发动了，把 5 张排好再点「确认」（这一手不能跳过）")
		return
	if not bool(srv_state.get("future_can", false)):
		if bool(srv_state.get("future_armed", false)):
			_toast("未来：已经发动了，把 5 张排好再点「确认」")
		else:
			_toast("未来：只能在轮到你摸牌之前发动（本小局一次）")
		return
	if game_over or srv_busy or _srv_kangpo_wait():
		return
	var r := srv_request({"op": "future_arm", "seat": my_seat})
	if srv_kangpo_blocked(r):
		_toast("未来：已发动，等对方决定是否看破…")
		return
	if r.is_empty():
		_toast(_srv_err("未来：服务端没有回应"))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "未来：发动失败")))
		return
	_future_ask_hide()
	srv_apply_state(r.get("state"), r.get("events"))
	_future_open()
	_toast("未来：已发动 —— 按你想要的顺序点这 5 张（1~5），排好后点「确认」")


# 发动之后（state.future_armed）→ 亮牌给玩家排序
func _future_sync(st: Dictionary) -> void:
	if bool(st.get("future_armed", false)):
		if not future_active:
			_future_open()
		return
	if future_active:
		_future_close()


func _future_open() -> void:
	var arr: Array = srv_state.get("future_tiles", [])
	if (arr as Array).size() < FUTURE_N:
		return
	future_tiles.clear()
	for t in arr:
		future_tiles.append(String(t))
	future_order.clear()
	future_active = true
	_future_make_ui()
	_future_refresh()
	_toast("未来：按你想要的顺序点这 5 张（1~5）；点「开始」= 跳过")


func _future_make_ui() -> void:
	if future_ui != null:
		return
	var host: Node = get_parent()
	if host == null:
		host = self
	# ★ 人物卡挂在 CardPhase（CanvasLayer, layer=20）里 —— 画在同一 canvas 上的东西
	#   全都会被它们盖住，所以面板要放进一个更高的 CanvasLayer。
	future_layer = CanvasLayer.new()
	future_layer.name = "FutureLayer"
	future_layer.layer = 30
	host.add_child(future_layer)
	future_ui = Control.new()
	future_ui.name = "FutureUI"
	future_ui.z_index = 262
	future_ui.mouse_filter = Control.MOUSE_FILTER_IGNORE
	future_layer.add_child(future_ui)
	future_ui.position = Vector2.ZERO
	var vp := get_viewport_rect().size
	var total := float(FUTURE_N) * FUTURE_TILE_W + float(FUTURE_N - 1) * FUTURE_GAP
	var x0 := (vp.x - total) * 0.5
	var y0 := vp.y * 0.5 - FUTURE_TILE_H * 0.5 - 40.0
	future_slots.clear()
	for i in range(FUTURE_N):
		var b := TextureButton.new()
		b.name = "Fut%d" % i
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		var tx := TileBank.VERT_DIR + TileBank.face_file(String(future_tiles[i])) + ".png"
		b.texture_normal = load(tx) as Texture2D
		b.size = Vector2(FUTURE_TILE_W, FUTURE_TILE_H)
		b.position = Vector2(x0 + float(i) * (FUTURE_TILE_W + FUTURE_GAP), y0)
		b.pressed.connect(_future_pick.bind(i))
		future_ui.add_child(b)
		var num := Label.new()
		num.name = "Num"
		num.text = ""
		num.add_theme_font_size_override("font_size", 36)
		num.add_theme_color_override("font_color", Color(1.0, 0.86, 0.25, 1.0))
		num.add_theme_color_override("font_outline_color", Color(0, 0, 0, 1))
		num.add_theme_constant_override("outline_size", 6)
		num.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		num.size = Vector2(FUTURE_TILE_W, 46)
		num.position = Vector2(0, -2)
		num.mouse_filter = Control.MOUSE_FILTER_IGNORE
		b.add_child(num)
		future_slots.append({"btn": b, "num": num})
	var tex := btn_tex("pass")
	var aspect := 70.0 / 220.0
	if tex != null and tex.get_width() > 0:
		aspect = float(tex.get_height()) / float(tex.get_width())
	var r := prompt_btn_rect(aspect)          # 尺寸 = 手牌高度那套（和别的面板一致）
	# 发动之后**不能跳过**：这里没有「开始」按钮，只有排好 5 张才出现的「确认」
	future_btn_ok = _future_make_btn(btn_tex("ok"), "", r.position, r.size)
	future_btn_ok.pressed.connect(_future_confirm)
	future_btn_ok.visible = false


func _future_make_btn(tex: Texture2D, _txt: String, pos: Vector2,
		sz: Vector2) -> TextureButton:
	var b := TextureButton.new()
	b.texture_normal = tex
	b.ignore_texture_size = true
	b.stretch_mode = TextureButton.STRETCH_SCALE
	b.focus_mode = Control.FOCUS_NONE
	b.size = sz
	b.position = pos
	future_ui.add_child(b)
	return b


func _future_pick(i: int) -> void:
	if not future_active:
		return
	if future_order.has(i):
		future_order.erase(i)
	elif future_order.size() < FUTURE_N:
		future_order.append(i)
	_future_refresh()


func _future_refresh() -> void:
	for i in range(future_slots.size()):
		var slot: Dictionary = future_slots[i]
		var at := future_order.find(i)
		var num := slot["num"] as Label
		if num != null:
			num.text = "" if at < 0 else str(at + 1)
		var b := slot["btn"] as TextureButton
		if b != null:
			b.modulate = Color(1, 1, 1, 1) if at >= 0 else Color(0.62, 0.62, 0.62, 1.0)
	if future_btn_ok != null and is_instance_valid(future_btn_ok):
		future_btn_ok.visible = future_order.size() == FUTURE_N


func _future_confirm() -> void:
	if future_order.size() != FUTURE_N:
		return
	var order: Array = []
	for i in range(FUTURE_N):
		order.append(int(future_order[i]))
	var r := srv_request({"op": "future_set", "seat": my_seat, "order": order})
	if srv_kangpo_blocked(r):
		_future_close()
		_toast("未来：等对方决定是否看破…")
		return
	if r.is_empty():
		_future_close()
		_toast(_srv_err("未来：服务端没有回应"))
		_pull_state()
		return
	if not bool(r.get("ok", false)):
		_future_close()
		_toast(String(r.get("error", "未来：发动失败")))
		_pull_state()
		return
	var d: Dictionary = r.get("future", {})
	_future_close()
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("未来：牌山顺序 → %s" % "、".join(d.get("tiles", [])))
	draw_tile()                           # 技能完了 → 接着摸牌（摸新顺序的第一张）


func _future_close() -> void:
	future_active = false
	future_order.clear()
	future_slots.clear()
	future_btn_ok = null
	_future_ask_hide()
	if future_ui != null and is_instance_valid(future_ui):
		future_ui.queue_free()
	future_ui = null
	if future_layer != null and is_instance_valid(future_layer):
		future_layer.queue_free()
	future_layer = null


# ── Card26 S1「云外镜」/ S2「天梯」：都是配牌阶段发动（问一次看破）─────
func _c26s1_activate() -> void:
	if String(srv_state.get("phase", "")) != "deal_skill":
		_toast("「云外镜」只能在配牌阶段发动")
		return
	if bool(srv_state.get("c26s1_on", false)):
		_toast("「云外镜」本局已经开启了")
		return
	_c26_use_deal(26, 1, "云外镜", "云外镜：本局我能看见其他三家的角色卡")


func _c26s2_activate() -> void:
	if String(srv_state.get("phase", "")) != "deal_skill":
		_toast("「天梯」只能在配牌阶段发动")
		return
	if bool(srv_state.get("c26s2_on", false)):
		_toast("「天梯」本局已经开启了（每次自己摸牌前都要排牌山）")
		return
	_c26_use_deal(26, 2, "天梯", "天梯：本局开启 —— 每次自己摸牌前排接下来 1+n 张")


func _c26_use_deal(card: int, skill: int, nm: String, ok_msg: String) -> void:
	if game_over or srv_busy or _srv_kangpo_wait():
		return
	var r := srv_request({"op": "deal_skill", "seat": my_seat,
		"action": "use", "card": int(card), "skill": int(skill)})
	if srv_kangpo_blocked(r):
		_toast("%s：已发动，等对方决定是否看破…" % nm)
		return
	if r.is_empty():
		_toast(_srv_err("%s：服务端没有回应" % nm))
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "%s：发动失败" % nm)))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	var idn := get_node_or_null("Identity")
	if idn != null and idn.has_method("collapse_skills"):
		idn.call("collapse_skills", int(card))
	_toast(ok_msg)


# ── Card26 S2「天梯」──────────────────────────────────────────────────
#   配牌发动 → 本局开启（红框锁住、不可关闭）；
#   之后**每次自己摸牌前**自动弹出：把接下来 1+n 张重新排序，**不可跳过**。
#   n = 连续和牌次数（服务端算，state.c26_n）。
var c26_active := false
var c26_layer: CanvasLayer = null
var c26_ui: Control = null
var c26_tiles: Array = []
var c26_order: Array = []
var c26_slots: Array = []
var c26_btn: TextureButton = null
var c26_key := ""
# 这块面板被三个技能复用：天梯(26S2) / 未来(24S2 自己的) / 流势(35S1)
var c26_op := "c26_set"          # 确认时发哪个 op
var c26_res_key := "c26"         # 回包里取结果的键
var c26_title := "天梯"           # toast 用
var c26_after_draw := true       # 确认完是否接着摸牌（流势=false：接着打牌）
var c35_mark := -1               # 流势：已经弹过的 mark


func _c26_gate_before_draw() -> bool:
	if c26_active:
		return true                      # 面板开着：先别摸牌
	if _srv_kangpo_wait():
		return false
	if not bool(srv_state.get("c26_can", false)):
		return false
	var key := "%d-%d" % [int(srv_state.get("live_left", 0)),
		int(srv_state.get("turn", 0))]
	if key == c26_key:
		return false                     # 这一巡已经排过 / 问过
	c26_key = key
	_c26_open()
	return true


func _c26_open() -> void:
	c26_op = "c26_set"
	c26_res_key = "c26"
	c26_title = "天梯"
	c26_after_draw = true
	_c26_open_tiles(srv_state.get("c26_tiles", []))


# 真正开面板（数据来源和界面分开，方便单独验证）
func _c26_open_tiles(arr: Array) -> void:
	if (arr as Array).is_empty():
		return
	c26_tiles.clear()
	for t in arr:
		c26_tiles.append(String(t))
	c26_order.clear()
	c26_active = true
	_c26_make_ui()
	_c26_refresh()
	_toast("%s：排好接下来 %d 张" % [c26_title, c26_tiles.size()])


func _c26_make_ui() -> void:
	if c26_ui != null:
		return
	var host: Node = get_parent()
	if host == null:
		host = self
	c26_layer = CanvasLayer.new()
	c26_layer.name = "C26Layer"
	c26_layer.layer = 30                 # 人物卡在 layer=20
	host.add_child(c26_layer)
	c26_ui = Control.new()
	c26_ui.name = "C26UI"
	c26_ui.z_index = 262
	c26_ui.mouse_filter = Control.MOUSE_FILTER_IGNORE
	c26_ui.position = Vector2.ZERO
	c26_layer.add_child(c26_ui)
	var vp := get_viewport_rect().size
	var n := maxi(c26_tiles.size(), 1)
	var gap := 18.0
	var max_w := (vp.x - 160.0 - gap * float(maxi(n - 1, 0))) / float(n)
	var tw := clampf(max_w, 46.0, 112.0)
	var th := tw * 1.3928
	var total := float(n) * tw + float(n - 1) * gap
	var x0 := (vp.x - total) * 0.5
	var y0 := vp.y * 0.5 - th * 0.5 - 40.0
	c26_slots.clear()
	for i in range(c26_tiles.size()):
		var b := TextureButton.new()
		b.name = "C26T%d" % i
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		var tx := TileBank.VERT_DIR + TileBank.face_file(String(c26_tiles[i])) + ".png"
		b.texture_normal = load(tx) as Texture2D
		b.size = Vector2(tw, th)
		b.position = Vector2(x0 + float(i) * (tw + gap), y0)
		b.pressed.connect(_c26_pick.bind(i))
		c26_ui.add_child(b)
		var num := Label.new()
		num.name = "Num"
		num.text = ""
		num.add_theme_font_size_override("font_size", int(clampf(tw * 0.42, 18.0, 36.0)))
		num.add_theme_color_override("font_color", Color(1.0, 0.86, 0.25, 1.0))
		num.add_theme_color_override("font_outline_color", Color(0, 0, 0, 1))
		num.add_theme_constant_override("outline_size", 6)
		num.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		num.size = Vector2(tw, 46)
		num.position = Vector2(0, -2)
		num.mouse_filter = Control.MOUSE_FILTER_IGNORE
		b.add_child(num)
		c26_slots.append({"btn": b, "num": num})
	var tex := btn_tex("pass")
	var aspect := 70.0 / 220.0
	if tex != null and tex.get_width() > 0:
		aspect = float(tex.get_height()) / float(tex.get_width())
	var rc := prompt_btn_rect(aspect)
	c26_btn = TextureButton.new()
	c26_btn.texture_normal = btn_tex("ok")
	c26_btn.ignore_texture_size = true
	c26_btn.stretch_mode = TextureButton.STRETCH_SCALE
	c26_btn.focus_mode = Control.FOCUS_NONE
	c26_btn.size = rc.size
	c26_btn.position = rc.position
	c26_btn.visible = false
	c26_btn.pressed.connect(_c26_confirm)
	c26_ui.add_child(c26_btn)
	


func _c26_pick(i: int) -> void:
	if not c26_active:
		return
	if c26_order.has(i):
		c26_order.erase(i)
	elif c26_order.size() < c26_tiles.size():
		c26_order.append(i)
	_c26_refresh()


func _c26_refresh() -> void:
	for i in range(c26_slots.size()):
		var slot: Dictionary = c26_slots[i]
		var at := c26_order.find(i)
		var num := slot.get("num") as Label
		var btn := slot.get("btn") as TextureButton
		if num != null:
			num.text = str(at + 1) if at >= 0 else ""
		if btn != null:
			btn.modulate = Color(1, 1, 1, 1) if at >= 0 else Color(0.62, 0.62, 0.62, 1)
	if c26_btn != null and is_instance_valid(c26_btn):
		c26_btn.visible = c26_order.size() == c26_tiles.size()


func _c26_confirm() -> void:
	if c26_order.size() != c26_tiles.size():
		return
	var order: Array = []
	for i in range(c26_order.size()):
		order.append(int(c26_order[i]))
	var r := srv_request({"op": c26_op, "seat": my_seat, "order": order})
	if r.is_empty():
		_toast(_srv_err("%s：服务端没有回应" % c26_title))
		_c26_close()
		return
	# 有人要决定「看破 / 封堵」：先收面板，放行之后服务端会替我把这次排好
	if bool(r.get("need_kangpo", false)):
		_c26_close()
		_toast("%s：有人在决定是否看破，放行后自动生效" % c26_title)
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "%s：排序失败" % c26_title)))
		_c26_close()
		_pull_state()
		return
	var d: Dictionary = r.get(c26_res_key, {})
	_c26_close()
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("%s：接下来 %d 张 → %s"
		% [c26_title, int(d.get("k", 0)), "、".join(d.get("tiles", []))])
	if c26_after_draw:
		draw_tile()                       # 天梯：排完了 → 接着摸牌
	# 流势：排完了直接接着打牌，不用摸


func _c26_close() -> void:
	c26_active = false
	c26_order.clear()
	c26_slots.clear()
	c26_btn = null
	if c26_ui != null and is_instance_valid(c26_ui):
		c26_ui.queue_free()
	c26_ui = null
	if c26_layer != null and is_instance_valid(c26_layer):
		c26_layer.queue_free()
	c26_layer = null


func srv_can_c24_with(tile_id: String) -> bool:
	for t in (srv_state.get("c24_tiles", []) as Array):
		if String(t) == tile_id:
			return true
	return false


func _c24_confirm(picks: Array, rivers: Array) -> void:
	var tiles := display_tiles()
	if picks.is_empty():
		return
	var idx := int(picks[0])
	if idx < 0 or idx >= tiles.size():
		return
	var tile := String(tiles[idx])
	var r := srv_request({"op": "c24_declare", "seat": my_seat, "tile": tile})
	if srv_kangpo_blocked(r):
		# 等对方决定是否看破：放行后服务端会自己重放这条 op
		_apply_entity_states(srv_state)
		return
	if r.is_empty():
		_toast(_srv_err("一发：服务端没有回应"))
		_pull_state()
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "一发：发动失败")))
		_pull_state()
		return
	var d: Dictionary = r.get("c24", {})
	srv_apply_state(r.get("state"), r.get("events"))
	refresh_hand()
	if bool(d.get("ippatsu_on", false)):
		_toast("一发：牌山里有你的胡张（%s）→ 一发自摸窗口开启"
			% "、".join(d.get("wins", [])))
	else:
		_toast("一发：牌山/王牌里没有你的胡张 —— 立直了，但没有一发")


func _swap_start() -> void:
	if swap_panel.active or press_panel.active or ym_panel.active or c24_panel.active \
			or game_over:
		return                                  # 三个面板共用同一个 hand_pick，不能同时开
	if (srv_state.get("used_skills", []) as Array).has("2-2-%d" % my_seat):
		_toast("「换牌」本局已经用过了")
		return
	if (String(srv_state.get("phase", "")) != "discard"
			or int(srv_state.get("turn", -1)) != my_seat or drawn_tile == ""):
		_toast("摸牌之后才能发动「换牌」")
		return
	swap_panel.begin({
		"name": "换牌",
		"want": 3, "min": 1,                 # 手牌 1~3 张
		"river": true, "river_match": true,  # 牌河张数必须和手牌一样
		"cancel": true,
		"on_confirm": _swap_confirm,
	})
	_toast("换牌：选 1~3 张手牌 + 同样张数的牌河牌 → 点「开始」")


func _on_card09_river_clicked(seq: int) -> void:
	if not _card09_ok(int(river_seat_by_seq.get(int(seq), -1)), false, int(seq)):
		_toast("这张不能换（这一行换过了 / 被鸣走 / 暗置）")
		return
	if c09_seq == seq:
		c09_seq = -1
		_refresh_c09_btn()
		_apply_entity_states(srv_state)
		return
	c09_seq = seq
	if int(c09_skill) == 0:
		# 第一次发动：点自己牌河 = 间合守(1)，点别家牌河 = 间合攻(2)
		var rs := int(river_seat_by_seq.get(int(seq), -1))
		c09_skill = 1 if rs == my_seat else 2
		_toast("间合%s：已选%s牌河那张；再选一张手牌 → 开始"
			% ["守" if int(c09_skill) == 1 else "攻",
			   "自己" if int(c09_skill) == 1 else "别家"])
	_refresh_c09_btn()
	_apply_entity_states(srv_state)


func _on_river_clicked(seq: int) -> void:
	if sf_active:
		_on_sf_river_clicked(seq)
		return
	if zl_active:
		_on_zl_river_clicked(seq)
		return
	if pofa_active:
		_on_pofa_river_clicked(seq)
		return
	if c11s2_active:
		_on_c11s2_river_clicked(seq)
		return
	if c10_active:
		_c10_toggle_river(seq)
		return
	if c09_active:
		_on_card09_river_clicked(seq)
		return
	if c05_active:
		_c05_pick_river(seq)
		return
	if c27_panel.active:
		c27_panel.handle_river(seq)
		return
	if press_panel.active:
		press_panel.handle_river(seq)
		return
	if c33_panel.active:
		c33_panel.handle_river(seq)
		return
	if c43_panel.active:
		c43_panel.handle_river(seq)
		return
	if c45_panel.active:
		c45_panel.handle_river(seq)
		return
	if swap_panel.active:
		swap_panel.handle_river(seq)


func _swap_confirm(picks: Array, rivers: Array) -> void:
	var tiles := display_tiles()
	var picked: Array = []
	for i in picks:
		if int(i) >= 0 and int(i) < tiles.size():
			picked.append(String(tiles[int(i)]))
	if picked.is_empty() or picked.size() != rivers.size():
		_toast("手牌和牌河的张数要一样（1~3 张）")
		return
	var r := srv_request({"op": "swap", "seat": my_seat,
		"hand_tiles": picked, "river": rivers.duplicate()})
	if srv_kangpo_blocked(r):
		return                               # 面板在 confirm 时已经关掉了
	if not r.is_empty() and not bool(r.get("ok", false)):
		_toast(String(r.get("error", "换牌失败")))
		return
	if r.is_empty():
		_toast(_srv_err("换牌失败：服务端没有回应"))
		return
	var sw: Dictionary = r.get("swap", {})
	var got: Array = sw.get("got", [])
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("换牌：%s → %s" % ["、".join(picked), "、".join(got)])


func _swap_close() -> void:
	swap_panel.close()
	_apply_entity_states(srv_state)
	refresh_hand()





# ── Card02 Skill1「画板」──────────────────────────────────────────────
#   摸牌后发动：弹出全部手牌，选三种（黄色框，再点取消）
#   选满三张 → 下方出现「开始」→ 点了才生效，UI 消失
#   之后别人摸到这三种牌中的任意一种 → 交给我，压在我人物卡下方当明牌，
#   我下一次摸牌直接拿它（不摸牌山）；每种牌只转移一次。本小局只能用一次。
var board_ui: Control = null
var board_picks: Array[String] = []
var board_frames := {}                 # 牌种 -> [ReferenceRect…]
var board_start_btn: TextureButton = null
var board_tile_node: Sprite2D = null   # 压在我人物卡下方的明牌

const BOARD_TILE_W := 92.0
const BOARD_TILE_H := 134.0
const BOARD_START_TEX := "res://Cailiao/UI/tiaoguo.png"

# ── 「开始/确认」按钮的贴图：统一取自场景节点，不直接 load 文件 ──────────────
#   kind = "pass" → Main/UI/Btn/BtnTiaoguo（跳过）
#   kind = "ok"   → Main/UI/Btn/BtnQueren （确认）
# 在编辑器里换这两张图，所有技能面板的按钮一起变。
const START_BTN_NODE := {"pass": "BtnTiaoguo", "ok": "BtnQueren"}

# ══════════════════════════════════════════════════════════════════════════
#  【手牌右侧 开始/确认按钮】位置微调接口
#   ① 检视面板：选中 **Main** 节点（挂 main.gd 的那个，不是根 Node2D2）→「开始按钮微调」
#      改完 Ctrl+S 存场景，值就写进 node_2d.tscn
#   ② 运行时热键（面板开着就能调，立刻看到效果）
#        F10                    进入/退出「微调模式」（进去后方向键直接挪，不用按 Ctrl）
#        方向键                  平移确认态 1px（按住 Shift = 10px）
#        Alt + 方向键            在 confirm_btn_offset 上再叠一层（同样是确认态）
#        ★ 跳过态（未选牌时的 BtnTiaoguo）固定用「一开始的位置」，调不动也不会动
#        [ / ]                  确认态放大倍数 ∓/± 0.05
#        Ctrl + 0               全部恢复默认
#        F12                    重新读 user://btn_tune.cfg（手改那个文件后按一下）
#        F9                     把当前数值 + 实际矩形打到输出面板
#      （Ctrl+方向键 / Ctrl+Alt+方向键 / Ctrl+[ ] 在微调模式外也能用，效果一样）
#   ③ 自动记忆：调完写 user://btn_tune.cfg，下次启动自动带上
#      （想回到 @export 的值：删掉那个文件，或按 Ctrl+0）
#   ④ ★ 以上热键 / 记忆**只在编辑器里生效**（OS.has_feature("template") 为假）。
#      导出的 exe 用 @export 的默认值，玩家碰不到这套调试开关。
# ══════════════════════════════════════════════════════════════════════════
@export_group("开始按钮微调")
@export var prompt_btn_gap := 12.0            # 按钮和手牌最右边的空隙（px）
@export var prompt_btn_offset := Vector2.ZERO  # 整体平移（确认 / 跳过 一起动，右/下为正）

const BTN_TUNE_CFG := "user://btn_tune.cfg"
const BTN_TUNE_DEFAULT := {"gap": 12.0, "ox": 0.0, "oy": 0.0}

var _btn_ok := {}                   # 按钮 -> 是否「确认态」（_sync_prompt_btns 据此放大）
var _btn_tune_mode := false         # F10：微调模式（方向键不用按 Ctrl）


# 微调接口只在编辑器里可用；导出的 exe 一律用 @export 的默认值
func _btn_tune_dev() -> bool:
	return not OS.has_feature("template")


func _btn_tune_load() -> void:
	if not _btn_tune_dev():
		return
	if not FileAccess.file_exists(BTN_TUNE_CFG):
		return
	var f := FileAccess.open(BTN_TUNE_CFG, FileAccess.READ)
	if f == null:
		return
	var raw := f.get_as_text()
	f.close()
	var d = JSON.parse_string(raw)
	if typeof(d) != TYPE_DICTIONARY:
		push_warning("main.gd: btn_tune.cfg 不是合法 JSON，忽略")
		return
	var dd := d as Dictionary
	prompt_btn_gap = float(dd.get("gap", prompt_btn_gap))
	prompt_btn_offset = Vector2(float(dd.get("ox", 0.0)), float(dd.get("oy", 0.0)))
	print("[PROMPT_BTN] 已载入微调：gap=%.1f offset=%s" % [
		prompt_btn_gap, prompt_btn_offset])


func _btn_tune_save() -> void:
	var f := FileAccess.open(BTN_TUNE_CFG, FileAccess.WRITE)
	if f == null:
		push_warning("main.gd: 写不了 " + BTN_TUNE_CFG)
		return
	f.store_string(JSON.stringify({
		"gap": prompt_btn_gap, "ox": prompt_btn_offset.x, "oy": prompt_btn_offset.y}, "\t"))
	f.close()


func _btn_tune_reset() -> void:
	prompt_btn_gap = float(BTN_TUNE_DEFAULT["gap"])
	prompt_btn_offset = Vector2(0, 0)
	if FileAccess.file_exists(BTN_TUNE_CFG):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(BTN_TUNE_CFG))


# F9：当前值 + 实际矩形（照这个数字去调 @export 或直接按方向键）
func _btn_tune_report() -> void:
	var aspect := 70.0 / 220.0
	var t0 := btn_tex("pass")
	if t0 != null and t0.get_width() > 0:
		aspect = float(t0.get_height()) / float(t0.get_width())
	var r := prompt_btn_rect(aspect)
	var s2 := r.size
	var cp := r.position + prompt_btn_offset
	var line := "gap=%.1f  offset=%s" % [prompt_btn_gap, prompt_btn_offset]
	print("[PROMPT_BTN] ", line)
	print("[PROMPT_BTN] 跳过态=", r, "  确认态=", Rect2(cp, s2))
	_toast("按钮微调 · " + line)


var _btn_tex_cache := {}                   # kind -> Texture2D（贴图在场景里固定，缓存一次就够）

func btn_tex(kind: String) -> Texture2D:
	# ★ 性能：_process 每帧要问二十多次（_refresh_start_btn_kinds / 各面板 tick），
	#   每次都 get_node + 取贴图纯属白干。只缓存取到的那份（null 不缓存，
	#   否则 _ready 之前问过一次就会永久变白板）。
	if _btn_tex_cache.has(kind):
		return _btn_tex_cache[kind] as Texture2D
	var nm: String = START_BTN_NODE.get(kind, "BtnTiaoguo")
	var n := get_node_or_null("UI/Btn/" + nm)
	if n == null or not (n is TextureButton):
		return null
	var t := (n as TextureButton).texture_normal
	if t != null:
		_btn_tex_cache[kind] = t
		return t
	return null


# 统一「确认 / 跳过」贴图按钮（不叠任何文字，贴图本身就是语义）
#   kind = "ok"（BtnQueren）/ "pass"（BtnTiaoguo）
#   width = 按钮宽度；高度按贴图比例算，永远不变形
func ui_btn(kind: String, width: float) -> TextureButton:
	var b := TextureButton.new()
	b.texture_normal = btn_tex(kind)
	b.ignore_texture_size = true
	b.stretch_mode = TextureButton.STRETCH_SCALE
	b.focus_mode = Control.FOCUS_NONE
	var bw := maxf(40.0, width)
	var bh := bw * (70.0 / 220.0)
	var t := b.texture_normal
	if t != null and t.get_width() > 0:
		bh = bw * float(t.get_height()) / float(t.get_width())
	b.size = Vector2(bw, bh)
	return b


# 给已经 new 出来的「开始按钮」换图：picked=false → 跳过，true → 确认
func set_start_btn_kind(btn: TextureButton, picked: bool) -> void:
	if btn == null or not is_instance_valid(btn):
		return
	# ★ 性能：本函数被 _process 每帧调二十多次。记录态没变 → 直接走人，
	#   否则每帧都要比贴图、写字典（几十个按钮 × 60 帧/秒全是白工）。
	if _btn_ok.has(btn) and bool(_btn_ok[btn]) == picked and is_equal_approx(btn.scale.x, 1.0):
		var _t0 := btn_tex("ok" if picked else "pass")
		if _t0 == null or btn.texture_normal == _t0:
			return
	var t := btn_tex("ok" if picked else "pass")
	if t != null and btn.texture_normal != t:
		btn.texture_normal = t
	# 只记状态：真正的「放大 1.5 倍 + 底部对齐」在 _sync_prompt_btns() 里按 size 算。
	# ★ 不用 scale/pivot 的原因：action_button 的 resized 信号会把 pivot 写回中心，
	#   而 _sync_prompt_btns 每帧改 size 就触发一次 → 放大后底部总会往下探一截。
	_btn_ok[btn] = picked
	if not is_equal_approx(btn.scale.x, 1.0):
		btn.scale = Vector2.ONE


# ── 统一刷新：每个技能面板的「开始按钮」按「有没有选东西」切图 ──────────────
#   没选 → tiaoguo（跳过）；选了 → queren（确认）。
#   放在 _process 里当兜底：不管哪个回调改了选择状态，下一帧自动跟上，
#   不用去 24 个回调里各插一句。
#   注：只在「选满才出现」的按钮（c26 / future）出现时必然是已选 → 直接给确认图。
func _refresh_start_btn_kinds() -> void:
	set_start_btn_kind(oracle_start_btn, oracle_pick != "")
	set_start_btn_kind(c09_btn, not c09_picks.is_empty())
	set_start_btn_kind(c10_btn, not c10_picks.is_empty() or not c10_sel.is_empty())
	set_start_btn_kind(c11_btn, not c11_picks.is_empty())
	set_start_btn_kind(c11s2_btn, not c11s2_sel.is_empty())
	set_start_btn_kind(sf_btn, not sf_picks.is_empty())
	set_start_btn_kind(zl_btn, not zl_picks.is_empty())
	set_start_btn_kind(pofa_btn, pofa_picks.size() >= 2)
	set_start_btn_kind(hs_btn, not hs_picks.is_empty())
	# ↓ 下面这些按钮**只在「选够了」之后才 visible**，跳过态根本不该出现 → 恒确认图
	#   （用户口径：恒确认的那些确保是确认按钮；双图只留给「选牌前就露出」的 9 个）
	set_start_btn_kind(dy_btn, true)              # 钓鱼：选完牌种才出现
	set_start_btn_kind(sw_start_btn, true)        # 南风·种类
	set_start_btn_kind(sw_hand_btn, true)         # 南风·换牌
	set_start_btn_kind(c05_start_btn, true)       # 策略·换牌
	set_start_btn_kind(c05_hide_btn, true)        # 策略·盖牌
	set_start_btn_kind(wind_start_btn, true)      # 自风
	set_start_btn_kind(flow_start_btn, true)      # 风神
	set_start_btn_kind(gb_btn, true)              # 国标
	set_start_btn_kind(yd_btn, true)              # 一定
	set_start_btn_kind(board_start_btn, true)     # 画板
	set_start_btn_kind(c25_btn, false)          # C25Cancel：取消/跳过
	set_start_btn_kind(c26_btn, true)          # 出现时必然已排好
	set_start_btn_kind(future_btn_ok, true)    # 同上
	set_start_btn_kind(deal_skip_btn, false)   # 发牌阶段的「跳过」
	# 外部面板（按钮在各自脚本里 new 的）：语义都是「选好之后确认」
	set_start_btn_kind(c30_panel.start_btn, true)     # 向听
	set_start_btn_kind(c32_panel.start_btn, true)     # 新手运
	if hand_pick != null:
		set_start_btn_kind(hand_pick.start_btn, true)  # 手牌选择



func _board_open() -> void:
	if board_ui != null or game_over:
		return
	if (srv_state.get("used_skills", []) as Array).has("2-1-%d" % my_seat):
		_toast("「画板」本局已经用过了")
		return
	if (String(srv_state.get("phase", "")) != "discard"
			or int(srv_state.get("turn", -1)) != my_seat or drawn_tile == ""):
		_toast("摸牌之后才能发动「画板」")
		return
	# 画板列的是「所有牌种」（1m..9m / 1p..9p / 1s..9s / 东南西北白发中），
	# 不局限于自己的手牌：指定的是牌种，别人摸到就送过来
	var tiles: Array = []
	for k in TileBank.TILE_KINDS:
		tiles.append(String(k))
	print("画板：全部牌种 ", tiles)
	board_picks.clear()
	board_frames.clear()
	var vp := get_viewport_rect().size
	board_ui = Control.new()
	board_ui.name = "BoardUI"
	board_ui.z_index = 260
	# 挂到场景根节点上：Main 自己带偏移，挂 Main 下面遮罩会被挪走、盖不满屏幕
	var host: Node = get_parent()
	if host == null:
		host = self
	host.add_child(board_ui)
	board_ui.position = Vector2.ZERO

	var bg := ColorRect.new()
	bg.name = "Bg"
	bg.color = Color(0.02, 0.03, 0.06, 0.84)
	bg.position = Vector2.ZERO
	bg.size = vp
	bg.mouse_filter = Control.MOUSE_FILTER_STOP
	board_ui.add_child(bg)

	var title := Label.new()
	title.text = "画板：选三种牌（任意牌种，再点一下取消）；选满三张后点「开始」"
	title.add_theme_font_size_override("font_size", 30)
	title.add_theme_color_override("font_color", Color(1.0, 0.96, 0.8))
	title.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	title.add_theme_constant_override("outline_size", 6)
	title.position = Vector2(0, 120)
	title.size = Vector2(vp.x, 40)
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	board_ui.add_child(title)

	var n := tiles.size()
	var per_row := 9
	var rows := int(ceil(float(n) / float(per_row)))
	var gap := 10.0
	var y0 := 210.0
	for i in range(n):
		var kind := String(tiles[i])
		var row := i / per_row
		var col := i % per_row
		var in_row := mini(per_row, n - row * per_row)
		var this_w := float(in_row) * BOARD_TILE_W + float(in_row - 1) * gap
		var bx := (vp.x - this_w) * 0.5 + float(col) * (BOARD_TILE_W + gap)
		var by := y0 + float(row) * (BOARD_TILE_H + gap)
		var b := TextureButton.new()
		b.name = "T%d" % i
		var tex := load(TileBank.VERT_DIR + TileBank.face_file(kind) + ".png") as Texture2D
		b.texture_normal = tex
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		b.position = Vector2(bx, by)
		b.size = Vector2(BOARD_TILE_W, BOARD_TILE_H)
		b.pressed.connect(_on_board_tile.bind(kind))
		board_ui.add_child(b)
		var f := SelFrame.attach(b, b.size)              # 选中：彩框图
		if not board_frames.has(kind):
			board_frames[kind] = []
		(board_frames[kind] as Array).append(f)

	var start_tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if start_tex != null and start_tex.get_width() > 0:
		bh = bw * float(start_tex.get_height()) / float(start_tex.get_width())
	board_start_btn = TextureButton.new()
	board_start_btn.name = "BoardStart"
	board_start_btn.texture_normal = start_tex
	board_start_btn.ignore_texture_size = true
	board_start_btn.stretch_mode = TextureButton.STRETCH_SCALE
	board_start_btn.focus_mode = Control.FOCUS_NONE
	board_start_btn.size = Vector2(bw, bh)
	board_start_btn.position = prompt_btn_pos(bw, bh)
	board_start_btn.visible = false
	board_start_btn.pressed.connect(_board_confirm)
	board_ui.add_child(board_start_btn)



func _on_board_tile(kind: String) -> void:
	if board_ui == null:
		return
	if board_picks.has(kind):
		board_picks.erase(kind)
	elif board_picks.size() < 3:
		board_picks.append(kind)
	else:
		_toast("最多指定三种手牌")
		return
	for k in board_frames:
		for f in (board_frames[k] as Array):
			if f != null:
				(f as Node2D).visible = board_picks.has(String(k))
	if board_start_btn != null:
		board_start_btn.visible = board_picks.size() == 3


func _board_confirm() -> void:
	if board_ui == null or board_picks.size() != 3:
		return
	var picked := board_picks.duplicate()
	var r := srv_request({"op": "board", "seat": my_seat, "tiles": picked})
	if r.is_empty():
		_toast("服务端没有回应")
		return
	if srv_kangpo_blocked(r):
		return

	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "发动失败")))
		return
	_board_close()
	srv_apply_state(r.get("state"), r.get("events"))
	_toast("画板：已指定 %s" % "、".join(picked))


func _board_close() -> void:
	if board_ui != null and is_instance_valid(board_ui):
		board_ui.queue_free()
	board_ui = null
	board_start_btn = null
	board_frames.clear()
	board_picks.clear()


# 传承（Card16 S1）：这张卡现在「是」哪个技能（没有就返回空）
func _cc_copy(st) -> Dictionary:
	if typeof(st) != TYPE_DICTIONARY:
		return {}
	var cc = (st as Dictionary).get("chuancheng")
	if typeof(cc) != TYPE_DICTIONARY:
		return {}
	var cp = (cc as Dictionary).get("copy")
	if typeof(cp) != TYPE_DICTIONARY:
		return {}
	return cp


# 本小局用过的一次性技能 → 图标变灰、点不动
func _apply_used_skills(st: Dictionary) -> void:
	var idn := get_node_or_null("Identity")
	if idn == null or not idn.has_method("set_skill_disabled"):
		return
	idn.call("reset_skill_states")
	for u in (st.get("used_skills", []) as Array):
		var parts := String(u).split("-")
		if parts.size() != 3 or int(parts[2]) != my_seat:
			continue
		# 馈赠（21S2）：换牌用掉了，但「一定和牌」那条链路还在 → 不能锁死
		if int(parts[0]) == 21 and int(parts[1]) == 2:
			continue
		# 钓鱼（15S1）/ 压制（3S2）：可以多次发动，图标不能因为用了一次就永久灰
		if (int(parts[0]) == 15 and int(parts[1]) == 1) \
				or (int(parts[0]) == 3 and int(parts[1]) == 2):
			continue
		# 友引（22S2）：段1 摊完面子后，段2（四副露换牌河那张）还要能用
		if int(parts[0]) == 22 and int(parts[1]) == 2:
			continue
		idn.call("set_skill_disabled", int(parts[0]), int(parts[1]) - 1, true)
	# 钓鱼（15S1）：本小局被锁住时图标要变灰（它能多次发动，不在 used_skills 里）
	if bool(st.get("diaoyu_locked", false)):
		idn.call("set_skill_disabled", 15, 0, true)


# 画板明牌：压在我人物卡下方（拿到之后服务端就不再给了，这里随之隐藏）
func _update_board_tile(st: Dictionary) -> void:
	var pending: Array = []
	var b = st.get("board")
	if typeof(b) == TYPE_DICTIONARY:
		pending = (b as Dictionary).get("pending", [])
	if pending.is_empty():
		if board_tile_node != null and is_instance_valid(board_tile_node):
			board_tile_node.visible = false
		return
	var kind := String(pending[0])
	var tex := load(TileBank.VERT_DIR + TileBank.face_file(kind) + ".png") as Texture2D
	if tex == null:
		return
	if board_tile_node == null or not is_instance_valid(board_tile_node):
		board_tile_node = Sprite2D.new()
		board_tile_node.name = "BoardFaceUp"
		board_tile_node.centered = false
		board_tile_node.z_index = 40
		if tile_bank != null:
			tile_bank.add_child(board_tile_node)
		else:
			add_child(board_tile_node)
	board_tile_node.texture = tex
	board_tile_node.visible = true
	var vp := get_viewport_rect().size
	var tw := float(maxi(tex.get_width(), 1))
	var th := float(maxi(tex.get_height(), 1))
	var w := 110.0
	var pos := Vector2(vp.x * 0.5 - w * 0.5, vp.y - 220.0)
	var card := get_node_or_null("Identity/Card01") as Control
	if card != null:
		var rect := card.get_global_rect()
		w = maxf(rect.size.x * 0.55, 64.0)
		pos = Vector2(rect.position.x + (rect.size.x - w) * 0.5,
			rect.position.y + rect.size.y + 8.0)
	var h := w * th / tw
	if pos.y + h > vp.y - 4.0:
		pos.y = vp.y - h - 4.0
	board_tile_node.position = pos
	board_tile_node.scale = Vector2(w / tw, h / th)


# ── Card01 Skill2「避开」──────────────────────────────────────────────
#   第一次点 Skill2：Skill2 下面伸出「东南西北」四个小按钮
#   点一个字：选中那一家的座位风 → 所有手牌变暗 50%
#   点手牌：选中变亮，再点取消；最多两张
#   选满两张再点 Skill2：问服务端这两张里有没有他的铳张，有就在那张牌上闪两次红光
#   确认之后 Skill2 / 东南西北一起消失
var skill2_card := 0                  # 正在用哪张卡的 Skill2（0 = 没在用）
var skill2_target := -1               # 选中的对象座位
var skill2_picks: Array[int] = []     # 选中的手牌下标（display_tiles 顺序）

const WIND_CN := ["东", "南", "西", "北"]


func _on_identity_wind(seat: int, card_no: int, wind: int) -> void:
	if seat != my_seat:
		return
	# 兼容：旧的「东南西北挂在人物卡上」那套保留着但不再调用；
	# 万一还有遗留入口，就按「东=庄家」换算成座位走统一分发。
	_on_seat_picked(_wind_to_seat(int(wind)))
	if dy_active and int(card_no) == 15:
		var dl3 := int(srv_state.get("dealer", my_seat))
		var tgt := (dl3 + int(wind)) % 4
		if tgt == my_seat:
			_toast("不能选自己")
			return
		_dy_open_panel(tgt)
		return
	if cg_kind == "sight_target" and int(card_no) == 17:
		var dl4 := int(srv_state.get("dealer", my_seat))
		_cg_show_skills("sight", (dl4 + int(wind)) % 4)
		return
	if cg_kind == "link_target" and int(card_no) == 18:
		var dl5 := int(srv_state.get("dealer", my_seat))
		_cg_link_use((dl5 + int(wind)) % 4)
		return
	if xn_selecting and int(card_no) == 12:            # X神：选谁被跳过
		var dl2 := int(srv_state.get("dealer", my_seat))
		_xn_start((dl2 + int(wind)) % 4)
		return
	if duel_selecting and int(card_no) == 8:          # 决斗：选对手
		var dl := int(srv_state.get("dealer", my_seat))
		_duel_start((dl + int(wind)) % 4)
		return
	if skill2_card == 0 or int(card_no) != skill2_card:
		return
	var dealer := int(srv_state.get("dealer", my_seat))
	var target := (dealer + int(wind)) % 4
	if target == my_seat:
		_toast("不能选自己")
		return
	skill2_target = target
	hand_pick.begin(skill2_picks, 2)
	_update_skill2_dim()
	_toast("对象：%s（%s风）— 请点两张手牌" % [srv_name_of(target), WIND_CN[clampi(wind, 0, 3)]])


# ── 座位选择面板（东南西北）· 统一入口 ──────────────────────────────
# 独立面板（seat_picker.gd），**不再挂在人物卡的 Skill2 上**：
#   · 位置固定、不随卡牌旋转缩放；S2 用掉变灰也不会把方位按钮带灰；
#   · 单例复用，同一时刻只有一个；调用方只给「模式 + 标题」；
#   · 面板上有「取消」，需要时还有「跳过」（夺目结算前）。
# 用户自己微调（存 user://seat_pick.cfg，重启也记得）：
#   seat_pick_tune(1.2, Vector2(0.5, 0.78))   # 缩放 / 位置（视口比例，中心对齐）
#   seat_pick_reset()                         # 回默认
#   seat_pick_info()                          # 看当前值
var seat_pick: Control = null
var seat_pick_mode := ""        # "" | c40s1 | c40s2 | c42s2 | c42s2_ask | c45s2a | c45s2b | dy | sight | link | xn | duel | skill2
var seat_pick_first := -1

const SEAT_PICK_SCRIPT := "res://seat_picker.gd"
const SEAT_PICK_NO_SELF := ["c40s1", "c40s2", "c45s2a", "dy", "sight", "link", "xn", "duel", "skill2"]


# 自愈：cg_kind 还挂着，但选单 UI 已经没了（也没在选人）→ 收掉。
# 不这么做的话，一次失败/被拦截的技能流程就能让手牌永远点不动。
func _cg_stale_close() -> void:
	if cg_kind == "" or cg_active:
		return
	if cg_ui != null and is_instance_valid(cg_ui):
		return
	if seat_pick_mode != "" or dy_active or duel_selecting or xn_selecting:
		return
	if skill2_card != 0 or sf_active or future_active:
		return
	_cg_close()


func _seat_pick_node() -> Control:
	if seat_pick != null and is_instance_valid(seat_pick):
		return seat_pick
	var scr := load(SEAT_PICK_SCRIPT)
	if scr == null:
		return null
	seat_pick = scr.new() as Control
	if seat_pick == null:
		return null
	seat_pick.name = "SeatPicker"
	add_child(seat_pick)
	seat_pick.connect("picked", _on_seat_picked)
	seat_pick.connect("cancelled", _on_seat_cancelled)
	seat_pick.connect("skipped", _on_seat_skipped)
	return seat_pick


func seat_pick_tune(scale_value: float, pos_ratio: Vector2) -> void:
	var n := _seat_pick_node()
	if n != null and n.has_method("tune"):
		n.call("tune", float(scale_value), Vector2(pos_ratio))


func seat_pick_reset() -> void:
	var n := _seat_pick_node()
	if n != null and n.has_method("tune_reset"):
		n.call("tune_reset")


func seat_pick_info() -> Dictionary:
	var n := _seat_pick_node()
	if n != null and n.has_method("tune_info"):
		return n.call("tune_info")
	return {}


# 打开 user:// 目录（seat_pick.cfg 就在里面），省得手找
func seat_pick_open_cfg() -> void:
	var dir := ProjectSettings.globalize_path("user://")
	OS.shell_open(dir)
	_toast("配置文件目录：%s" % dir)


# 东南西北 → 座位：和决斗 / 避开 / 看破选目标同一条换算（东=庄家，南=下家…）
func _wind_to_seat(wind: int) -> int:
	return (int(srv_state.get("dealer", my_seat)) + int(wind)) % 4


func _seat_pick_begin(mode: String, title: String) -> void:
	var n := _seat_pick_node()
	if n == null:
		_toast("座位选择面板没加载出来（seat_picker.gd）")
		return
	seat_pick_mode = String(mode)
	var dealer := int(srv_state.get("dealer", my_seat))
	var order: Array = []
	var allowed: Array = []
	for i in range(4):
		var s := (dealer + i) % 4
		order.append(s)
		var ok := true
		if SEAT_PICK_NO_SELF.has(mode) and s == my_seat:
			ok = false                      # 这些只能选别人
		if String(mode) == "c45s2b" and s == int(seat_pick_first):
			ok = false                      # 替身：第二位不能等于第一位
		allowed.append(ok)
	n.call("open", String(title), order, allowed, String(mode) == "c42s2_ask")


func _seat_pick_end() -> void:
	seat_pick_mode = ""
	var n := _seat_pick_node()
	if n != null and n.has_method("close"):
		n.call("close")


func _on_seat_cancelled() -> void:
	seat_pick_mode = ""
	seat_pick_first = -1


func _on_seat_skipped() -> void:
	var mode := seat_pick_mode
	seat_pick_mode = ""
	seat_pick_first = -1
	if mode == "c42s2_ask":
		_c42s2_answer(-1)               # 跳过 = 这次就按真庄家结算


func _on_seat_picked(seat: int) -> void:
	var mode := seat_pick_mode
	seat_pick_mode = ""
	var n := _seat_pick_node()
	if n != null and n.has_method("close"):
		n.call("close")
	match mode:
		"c40s1":
			_c40s1_pick(int(seat))
		"c40s2":
			_c40s2_pick(int(seat))
		"c42s2":
			_c42s2_pick(int(seat))
		"c42s2_ask":
			_c42s2_answer(int(seat))
		"c45s2a":
			_c45s2_first(int(seat))
		"c45s2b":
			var a := int(seat_pick_first)
			seat_pick_first = -1
			_c45s2_second(a, int(seat))
		"dy":
			_dy_open_panel(int(seat))
		"sight":
			_cg_show_skills("sight", int(seat))
		"link":
			_cg_link_use(int(seat))
		"xn":
			_xn_start(int(seat))
		"duel":
			_duel_start(int(seat))
		"skill2":
			skill2_target = int(seat)
			hand_pick.begin(skill2_picks, 2)
			_update_skill2_dim()
			_toast("对象：%s — 请点两张手牌" % srv_name_of(int(seat)))


# ── 协战人物卡遮罩（长按人物卡 ≥0.7 秒）──────────────────────────────
#   协战卡只活两个风场，出场时机很关键 → 玩家可以把它整体遮罩掉：
#   遮罩期间这张卡的**一切技能判定都不成立**（服务端 skills.owns_card / cards_in_order 剔掉）。
#   选玩家走独立的「东南西北」面板（seat_picker.gd），不另做左上角列表。
func _my_support_expired() -> bool:
	var cs = srv_state.get("char_states")
	if typeof(cs) != TYPE_ARRAY:
		return false
	for it in (cs as Array):
		if typeof(it) != TYPE_DICTIONARY:
			continue
		if int((it as Dictionary).get("seat", -1)) != my_seat:
			continue
		var sup = (it as Dictionary).get("support")
		if typeof(sup) == TYPE_DICTIONARY:
			return bool((sup as Dictionary).get("expired", false))
	return false


func _on_identity_long_press(seat: int, card_no: int) -> void:
	if game_over or seat != my_seat:
		return
	# 协战卡寿命到头 → 永久遮罩，长按不能取消（用户口径 2026-11-01）
	if _my_support_expired():
		_toast("这张协战卡已经到期：永久遮罩，不能取消")
		return
	_support_mute_toggle()          # 长按 = 直接开关「自己协战卡」的遮罩


# 开关自己协战卡的遮罩：遮罩期间这张卡的技能不自动发动、也不自动来问我
func _support_mute_toggle() -> void:
	if _my_support_expired():
		_toast("这张协战卡已经到期：永久遮罩，不能取消")
		return
	var sm = srv_state.get("support_mute")
	var was_on := (typeof(sm) == TYPE_DICTIONARY
		and int((sm as Dictionary).get(str(my_seat), 0)) > 0)
	var r := srv_request({"op": "support_mute", "seat": my_seat,
		"target": my_seat, "on": (not was_on)})
	if r.is_empty():
		_toast(_srv_err("协战卡遮罩：服务端没有回应"))
		return
	srv_apply_state(r.get("state"), r.get("events"))
	if was_on:
		_toast("协战卡遮罩：已关闭（协战卡的技能恢复判定）")
	else:
		_toast("协战卡遮罩：已打开（这张卡的技能不再自动发动、也不再问我）")


# 这张卡现在是不是被遮罩的协战卡（点它的技能图标 → 直接拦下）
func _card_is_support_muted(card_no: int) -> bool:
	var sm = srv_state.get("support_mute")
	if typeof(sm) != TYPE_DICTIONARY:
		return false
	for k in (sm as Dictionary).keys():
		if int((sm as Dictionary)[k]) == int(card_no):
			return true
	return false


func _on_identity_skills_toggled(seat: int, card_no: int, open: bool) -> void:
	# 玩家手动把技能图标收起来了 → 技能 2 的选牌状态也一起清掉
	if seat == my_seat and not open and skill2_card != 0:
		_skill2_close(false)
	# 收起图标 = 放弃这次「东南西北选玩家」
	if seat == my_seat and not open and seat_pick_mode != "":
		_seat_pick_end()
		seat_pick_first = -1


func _skill2_on_clicked() -> void:
	if (srv_state.get("used_skills", []) as Array).has("1-2-%d" % my_seat):
		_toast("「避开」本局已经用过了")
		return
	if skill2_card == 0:
		skill2_card = 1
		skill2_target = -1
		skill2_picks.clear()
		_seat_pick_begin("skill2", "避开：选一名玩家")
		return
	if skill2_target < 0:
		_toast("先点东南西北选一名玩家")
		return
	if skill2_picks.size() < 2:
		_toast("先选两张手牌（点一下选中，再点一下取消）")
		return
	_skill2_confirm()


func _skill2_confirm() -> void:
	var tiles := display_tiles()
	var picked: Array = []
	for i in skill2_picks:
		if i >= 0 and i < tiles.size():
			picked.append(String(tiles[i]))
	var r := srv_request({"op": "skill2", "seat": my_seat,
		"target": skill2_target, "tiles": picked})
	var hits: Array = []
	if bool(r.get("ok", false)):
		hits = r.get("hits", [])
		if hits.is_empty():
			_toast("这两张里没有他的铳张")
		else:
			# 只闪「命中的那张」，位置按 display_tiles 的下标找
			for h in hits:
				var k := int(h)
				if k >= 0 and k < skill2_picks.size():
					_blink_red_tile(skill2_picks[k])
			_toast("有 %d 张是他的铳张" % hits.size())
	else:
		_toast(String(r.get("error", "技能发动失败")))
	_skill2_close(true)


func _skill2_close(collapse: bool) -> void:
	skill2_card = 0
	skill2_target = -1
	skill2_picks.clear()
	hand_pick.end()
	_update_skill2_dim()
	var idn := get_node_or_null("Identity")
	if idn == null:
		return
	_seat_pick_end()
	if collapse and idn.has_method("collapse_skills"):
		idn.call("collapse_skills", 1)          # Skill2 和东南西北一起消失


func _toggle_skill2_pick(index: int) -> void:
	if index < 0:
		return
	if skill2_picks.has(index):
		skill2_picks.erase(index)
	elif skill2_picks.size() < 2:
		skill2_picks.append(index)
	else:
		_toast("最多选两张")
		return
	_update_skill2_dim()
	if skill2_picks.size() == 2:
		_toast("已选两张 — 再点一次 Skill2 确认")


# 手牌亮度：选了对象之后全部 50%，选中的恢复原样
func _update_skill2_dim() -> void:
	hand_pick.sync()                     # 手牌变暗统一由 hand_pick 负责


# 铳张提示：纯红 30% 不透明度、和手牌一样大，快速显示/消失两次
func _blink_red_tile(index: int) -> String:
	if tile_bank == null:
		return ""
	var target: TilePiece = null
	for q in tile_bank.all_pieces():
		var tp := q as TilePiece
		if tp != null and tp.visible and tp.form == "hand" and tp.slot_index == index:
			target = tp
			break
	if target == null:
		return ""
	var rect := ColorRect.new()
	rect.name = "Skill2Hit"
	rect.color = Color(1.0, 0.0, 0.0, 0.3)
	rect.size = tile_size
	rect.position = -tile_size * 0.5
	rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	rect.z_index = 10
	target.add_child(rect)
	var show_rect := func() -> void:
		if is_instance_valid(rect):
			rect.visible = true
	var hide_rect := func() -> void:
		if is_instance_valid(rect):
			rect.visible = false
	var kill_rect := func() -> void:
		if is_instance_valid(rect):
			rect.queue_free()
	var tw := create_tween()
	for i in range(2):
		tw.tween_callback(show_rect)
		tw.tween_interval(0.10)
		tw.tween_callback(hide_rect)
		tw.tween_interval(0.08)
	tw.tween_callback(kill_rect)
	return String(target.get_path()) + "/Skill2Hit"


var toast_label: Label


func _toast(text: String) -> void:
	if toast_label == null or not is_instance_valid(toast_label):
		toast_label = Label.new()
		toast_label.name = "SkillToast"
		toast_label.z_index = 200
		toast_label.add_theme_font_size_override("font_size", 26)
		toast_label.add_theme_color_override("font_color", Color(1.0, 0.95, 0.7))
		toast_label.add_theme_color_override("font_outline_color", Color(0, 0, 0))
		toast_label.add_theme_constant_override("outline_size", 6)
		toast_label.position = Vector2(520, 60)
		toast_label.custom_minimum_size = Vector2(880, 40)
		toast_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		add_child(toast_label)
	toast_label.text = text
	toast_label.visible = true
	await get_tree().create_timer(2.6).timeout
	if is_instance_valid(toast_label):
		toast_label.visible = false


func has_action(action: String) -> bool:
	for a in (srv_state.get("legal", []) as Array):
		if typeof(a) == TYPE_DICTIONARY and String((a as Dictionary).get("action", "")) == action:
			return true
	var c = srv_state.get("claim")
	if typeof(c) == TYPE_DICTIONARY:
		for o in ((c as Dictionary).get("options", []) as Array):
			if typeof(o) == TYPE_DICTIONARY and String((o as Dictionary).get("action", "")) == action:
				return true
	return false


# 按优先级把「当前可选动作」映射成要显示的按钮；opts = 服务端给的合法动作集合
# 节点是被「看得见的父节点」决定的：以前出现过 UI/Btn、UI/Pile 自己 visible=true
# 但父链被隐藏 → visible 属性真、屏幕上什么都没有。这里一律拉回来。
func _force_visible_chain(n: Node) -> void:
	var c := n
	var guard := 0
	while c != null and c != self and guard < 12:
		guard += 1
		if c is CanvasItem and not (c as CanvasItem).visible:
			(c as CanvasItem).visible = true
		c = c.get_parent()


func srv_layout_buttons(opts: Array) -> void:
	var want: Array = []
	for k in BTN_PRIORITY:
		if k == "kan":
			if opts.has("minkan") or opts.has("kakan") or opts.has("ankan"):
				want.append("kan")
		elif opts.has(k):
			want.append(k)
	if want.has("ron"):
		want.erase("tsumo")                          # 荣和优先，就不再显示自摸
	# 目标按钮 -> 槽位（顺便把不在目标里的按钮藏起来）
	var slot_of := {}
	for i in range(want.size()):
		if i >= BTN_SLOT_CENTERS.size():
			break
		slot_of[want[i]] = i
	for kind in btn_nodes:
		if slot_of.has(kind):
			continue
		var hide_b := btn_nodes[kind] as TextureButton
		if hide_b.visible:
			hide_b.visible = false
			# 顺手把入场/消散的半透明状态复位：否则下次显示时可能停在 alpha<1
			if hide_b.has_method("reset_anim"):
				hide_b.call("reset_anim")
	for kind in slot_of:
		var b: TextureButton = btn_nodes.get(kind, null)
		if b == null:
			continue
		var i2: int = int(slot_of[kind])
		var target := BTN_SLOT_CENTERS[i2] - b.size * 0.5
		# 位置没变就别重复赋值，避免任何可能触发的鼠标进出判定
		if b.position != target:
			b.position = target
		# ★ 只有「隐藏 → 显示」才改 visible / 播入场；保持可见时绝不隐藏再显示，
		#   否则鼠标停在上方时会反复触发 mouse_exited / mouse_entered（变大又缩回）
		if not b.visible:
			b.visible = true
			b.call("play_appear")
		elif b.has_method("ensure_shown") and float(b.modulate.a) < 0.999:
			# 正在淡出（上一次按下的消失动画还没走完）→ 拉回来，别让按钮凭空消失
			b.call("ensure_shown")
		_force_visible_chain(b)


# 加速（29S1）：吃 / 跳过都是**技能 op**（op=c29s1_chi / c29s1_skip），
# ★ 不能用 srv_act()：那个发的是 op=act（普通动作），服务端会当成非法动作拒掉，
#   然后 phase 卡在 c29s1，全桌谁都动不了。
func _c29s1_op(op: String, extra: Dictionary = {}) -> void:
	_c29s1_skip_queued = false
	var req := {"op": op, "seat": my_seat}
	for k in extra:
		req[k] = extra[k]
	srv_layout_buttons([])
	hide_chow_panel()
	var r := srv_request(req)
	if r.is_empty():
		_toast(_srv_err("加速：服务端没有回应"))
		_pull_state()
		return
	if srv_kangpo_blocked(r):
		return                       # 等对方决定是否看破；放行后服务端自己重放这条 op
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "加速失败")))
		_pull_state()                # 别留一个「本地以为点了、服务端没动」的界面
		return
	srv_apply_state(r.get("state"), r.get("events"))


# 加速（29S1）：别人打出我能无视距离吃的牌 → 服务端只问我一个人
func srv_c29s1_ask() -> Dictionary:
	var a = srv_state.get("c29s1_ask")
	return a if typeof(a) == TYPE_DICTIONARY else {}


# 遮罩盖着 + 正在问我 → 直接替玩家跳过（遮罩 = 别再问我）
var _c29s1_skip_queued := false


func _c29s1_masked_skip(st: Dictionary) -> void:
	if not is_skill_muted(29, 1):
		return
	if typeof(st.get("c29s1_ask")) != TYPE_DICTIONARY:
		_c29s1_skip_queued = false           # 这一笔没了 → 下次可以再自动跳
		return
	# ★ 这个函数是在 srv_apply_state 里面被调的：直接发请求 + 再 apply 会重入，
	#   所以挪到帧末；用标记防止每次轮询都发一遍。
	if not _c29s1_skip_queued:
		_c29s1_skip_queued = true
		call_deferred("_c29s1_op", "c29s1_skip")


# 从服务端状态里收集当前所有合法动作（含 claim 选项）
func srv_opts_of(st: Dictionary) -> Array:
	var opts: Array = []
	if typeof(st.get("c29s1_ask")) == TYPE_DICTIONARY:
		# 加速询问：只有 吃 / 跳过（走的是技能那条路，不是普通鸣牌）
		return ["chi", "pass"]
	for a in (st.get("legal", []) as Array):
		if typeof(a) == TYPE_DICTIONARY:
			opts.append(String((a as Dictionary).get("action", "")))
	var claim = st.get("claim")
	if typeof(claim) == TYPE_DICTIONARY:
		for o in ((claim as Dictionary).get("options", []) as Array):
			if typeof(o) == TYPE_DICTIONARY:
				opts.append(String((o as Dictionary).get("action", "")))
	if opts.has("skill_tsumo"):
		opts.append("tsumo")          # 技能给的自摸：复用「自摸」按钮
	if opts.has("yiding"):
		opts.erase("yiding")          # 一定和牌走技能图标那条链路，不占用立直按钮
	return opts


func srv_yield_to_me() -> void:
	hide_chow_panel()
	var st := srv_state
	if st.is_empty():
		srv_layout_buttons([])
		return
	var opts: Array = srv_opts_of(st)
	# 立直出牌后进入听牌，只显示立直按钮，再按一次可取消
	if riichi_selecting:
		srv_layout_buttons(["riichi"])
		return
	srv_layout_buttons(opts)


# 这张牌现在能不能打？（服务端 legal 里 discard.tiles 说了算；没给就是不限）
func srv_can_discard_with(tile_id: String) -> bool:
	for a in (srv_state.get("legal", []) as Array):
		if typeof(a) != TYPE_DICTIONARY or String(a.get("action", "")) != "discard":
			continue
		var ts: Array = (a as Dictionary).get("tiles", [])
		if ts.is_empty():
			return true
		for t in ts:
			if String(t) == tile_id:
				return true
		return false
	return true                     # 现在不是我的打牌回合 → 不拦


func srv_can_yiding_with(tile_id: String) -> bool:
	for t in (srv_state.get("yiding_tiles", []) as Array):
		if String(t) == tile_id:
			return true
	return false


func srv_can_riichi_with(tile_id: String) -> bool:
	for a in (srv_state.get("legal", []) as Array):
		if typeof(a) == TYPE_DICTIONARY and String((a as Dictionary).get("action", "")) == "riichi":
			for t in ((a as Dictionary).get("tiles", []) as Array):
				if String(t) == tile_id:
					return true
			return false
	return true                          # 服务端没给这个信息就不拦（由服务端最终判定）


func srv_legal_tile(st: Dictionary, action: String) -> String:
	for a in (st.get("legal", []) as Array):
		if typeof(a) == TYPE_DICTIONARY and String((a as Dictionary).get("action", "")) == action:
			return String((a as Dictionary).get("tile", ""))
	return ""


# 把服务端状态画到界面上（我的手牌 / 牌河 / 其他家张数 / 轮到谁）
# ── 实体渲染：按服务端 state.tiles 把 136 张牌摆到位 ─────────────────────────
# 新版显示架构总入口：每张牌是一个 TilePiece 实体，这里只改它的形式/位置/旋转/显隐。
# 选牌状态指纹：只影响牌河上的「选中彩框」，不改变任何牌的实体状态。
func _selection_sig() -> String:
	# ★ 新增「选牌 / 面板」状态必须登记到这里，否则 _apply_entity_states 会跳过重绘，
	#   表现就是「面板打开了但牌河没有彩框、点不动」（2026-11-02 魔术/快手）。
	return "%d%d%d%d%d%d%d%d%d%d%d|%d|%s|%s|%d|%d|%d|%d|%s|%s|%s|%s|%s|%s" % [
		int(c09_active), int(c10_active), int(c11_active), int(c11s2_active),
		int(c05_active), int(sf_active), int(zl_active), int(pofa_active),
		int(hs_active), int(dy_active), int(swap_panel.active),
		int(c09_seq), str(c05_target), str(c10_rivers),
		int(c11s2_seq), int(sf_seq), int(zl_seq), int(pofa_seq),
		str(press_panel.rivers), str(swap_panel.rivers), str(c43_panel.rivers),
		str(c45_panel.rivers), str(c33_panel.rivers), str(c27_panel.rivers)]


func _apply_entity_states(st2: Dictionary) -> void:
	if tile_bank == null:
		return
	tile_bank.begin_frame()
	river_kind_by_seq.clear()
	river_seat_by_seq.clear()
	var tiles: Array = st2.get("tiles", [])
	if typeof(tiles) != TYPE_ARRAY or tiles.is_empty():
		return
	# ★ 性能：136 张实体逐张 apply_state / 改亮度是这里最贵的一步。
	#   牌位没变（tiles 深 hash 一致）+ 选牌/立直/窗口没变 → 一张都不用重摆。
	# ★ 选牌类技能（间合 / 策略 / 鬼门 / 深山 / 炸裂 / 破发 / 魔术 / 压制 / 各种面板）
	#   点牌河只会改「选中了哪张」，牌的实体状态一点没变。这些状态必须进签名，
	#   否则签名不变 → 这里直接 return → 牌河彩框不重画，非得再点一下手牌才刷出来
	#   （用户报的【间合守/攻】bug，2026-11-02；所有选牌技能都受影响）。
	var _esig := "%d|%s|%d|%s|%d|%d|%s" % [tiles.hash(), str(get_viewport_rect().size),
		int(hand_pick.active) if hand_pick != null else 0,
		str(hand_pick.picks.hash()) if hand_pick != null else "-",
		int(riichi_selecting), int(hand_offset.x * 100.0), _selection_sig()]
	if _esig == _entity_sig:
		return
	_entity_sig = _esig
	var vp := get_viewport_rect().size
	var rect := fengpan_effective_rect()
	# fengpan_effective_rect() 是 Main 的局部坐标，TileBank 用屏幕坐标 → 补上 Main 的全局偏移
	if rect.size.x > 0.0:
		rect = Rect2(rect.position + global_position, rect.size)
	var slot := discard_slot_size(rect.size.x, rect.size.y) if rect.size.x > 0.0 else Vector2(48.0, 36.0)

	# 按 loc 分组
	var hand_entities := {}    # seat -> Array[Dictionary]
	var river_entities := {}   # seat -> Array[Dictionary]
	var meld_entities := {}    # seat -> Dictionary(group -> Array)
	var dora_entities: Array = []
	for t in tiles:
		if typeof(t) != TYPE_DICTIONARY:
			continue
		var td: Dictionary = t
		var eid := String(td.get("id", ""))
		var loc := String(td.get("loc", "wall"))
		var seat := int(td.get("seat", -1))
		if eid == "":
			continue
		if loc == "hand":
			if not hand_entities.has(seat):
				hand_entities[seat] = []
			(hand_entities[seat] as Array).append(td)
		elif loc == "river":
			if not river_entities.has(seat):
				river_entities[seat] = []
			(river_entities[seat] as Array).append(td)
		elif loc == "meld":
			if not meld_entities.has(seat):
				meld_entities[seat] = {}
			var g := int(td.get("group", 0))
			if not (meld_entities[seat] as Dictionary).has(g):
				(meld_entities[seat] as Dictionary)[g] = []
			((meld_entities[seat] as Dictionary)[g] as Array).append(td)
		elif loc == "dora":
			dora_entities.append(td)

	# 1) 我的手牌（正面）：按牌种排序，摸到的牌放最后并留一个空隙
	if hand_entities.has(my_seat):
		var arr: Array = hand_entities[my_seat]
		arr.sort_custom(func(a, b):
			var ka := TileBank.kind_of_entity(String(a.get("id", "")))
			var kb := TileBank.kind_of_entity(String(b.get("id", "")))
			if ka.begins_with("0"):
				ka = "5" + ka.substr(1)
			if kb.begins_with("0"):
				kb = "5" + kb.substr(1)
			var ra := int(kind_index.get(ka, 99))
			var rb := int(kind_index.get(kb, 99))
			if ra != rb:
				return ra < rb
			return String(a.get("id", "")) < String(b.get("id", ""))
		)
		# 摸到的牌挪到最右（服务端 slot 会有空洞，不能直接拿来当横坐标）
		var drawn_i := -1
		for i in range(arr.size()):
			if bool((arr[i] as Dictionary).get("drawn", false)):
				drawn_i = i
				break
		if drawn_i >= 0 and drawn_i != arr.size() - 1:
			var dtan: Dictionary = arr[drawn_i]
			arr.remove_at(drawn_i)
			arr.append(dtan)
		var hpos := hand_container.global_position if hand_container != null else Vector2.ZERO
		var fly_anchor := Vector2.INF     # 牌山出口（第一次真的要用时才去算）
		for i in range(arr.size()):
			var td: Dictionary = arr[i]
			var x := float(i) * tile_size.x
			if bool(td.get("drawn", false)):
				x += drawn_gap
			var pos := hpos + Vector2(x + tile_size.x * 0.5, tile_size.y * 0.5 + HOVER_RAISE)
			var p := tile_bank.piece(String(td.get("id", "")))
			if p != null:
				# 新出现的手牌（配牌 / 摸牌）：从牌山方向飞进来
				if not p.visible:
					if fly_anchor == Vector2.INF:
						fly_anchor = _wall_fly_anchor()
					p.fly_from(fly_anchor)
				p.slot_index = i
				p.apply_state("hand", pos)
				# 这张牌可能是被换进手里来的（原先在牌河里）：
				# 清掉残留的彩框 / 牌河信息，否则会「锁到别家的那张牌」上
				p.set_selected_frame(false)
				p.set_river_info(-1, false, -1)
				# 手牌亮度统一由 hand_pick 管：选牌时全变 50%、选中的恢复；
				# 没在选牌时退回「立直」那套（不能保持听牌的牌暗一半）
				if hand_pick.active:
					p.set_dimmed(not hand_pick.has(i))
				else:
					p.set_dimmed(riichi_selecting and not srv_can_riichi_with(p.kind))

	# 2) 牌河（我 + 三家；三家按 OPP_DISCARD_ROTATION 旋转）
	var river_used := {"me": {}, "B": {}, "C": {}, "D": {}}
	for seat in river_entities:
		var who := "me" if seat == my_seat else who_of_seat(seat)
		if who == "":
			continue
		var arr: Array = river_entities[seat]
		arr.sort_custom(func(a, b): return int(a.get("slot", 0)) < int(b.get("slot", 0)))
		var used: Dictionary = river_used[who]
		for td in arr:
			var i := int(td.get("slot", 0))
			var rot := bool(td.get("rotated", false))
			var col := i % DISCARDS_PER_ROW
			var row := floori(float(i) / float(DISCARDS_PER_ROW))
			var w := slot.y if rot else slot.x
			var u := float(used.get(row, 0.0))
			var info := discard_slot(who, rect, slot, col, row, u, w)
			used[row] = u + w
			var p := tile_bank.piece(String(td.get("id", "")))
			if p != null:
				var psc := (w / maxf(tile_size.x, 1.0)) if not rot else (w / maxf(tile_size.y, 1.0))
				var down := bool(td.get("face_down", false))
				# 持有 Card03「压制」：暗置牌对自己永远是明牌 → 照正面画
				var sees := bool(st2.get("sees_face_down", false))
				var hide := down and not sees
				var form := "rot" if rot else "river"
				if hide:
					form = "back_rot" if rot else "back"   # 暗置：竖置画背面；横置（立直宣言牌 / 命中）画横向背面
				p.apply_state(form, Vector2(info.x, info.y), info.z, Vector2.ONE * psc)
				# 压制（Card03）：暗置牌在自己视角是明牌，但亮度压到 65%
				p.set_alpha(0.65 if (down and sees) else 1.0)
				p.set_river_info(int(td.get("discard_seq", -1)), down,
					int(td.get("seat", -1)))
				river_kind_by_seq[int(td.get("discard_seq", -1))] = String(p.kind)
				river_seat_by_seq[int(td.get("discard_seq", -1))] = int(td.get("seat", -1))
				if c05_active:
					p.set_river_clickable(true)
					p.set_selected_frame(String(c05_target.get("kind", "")) == "river"
						and int(c05_target.get("seq", -1)) == int(td.get("discard_seq", -1)))
				elif c10_active:
					p.set_river_clickable(_c10_river_ok(down, p.kind))
					p.set_selected_frame(c10_rivers.has(int(td.get("discard_seq", -1))))
				elif sf_active:
					p.set_river_clickable(sf_mode != "shenshan" and not down)
					p.set_selected_frame(sf_seq == int(td.get("discard_seq", -1)))
				elif zl_active:
					var zok := int_set(srv_state.get("zhalie_seqs", [])).has(int(td.get("discard_seq", -1)))
					p.set_river_clickable(zok)
					p.set_selected_frame(zl_seq == int(td.get("discard_seq", -1)))
				elif pofa_active:
					var pok := int_set(srv_state.get("pofa_seqs", [])).has(int(td.get("discard_seq", -1)))
					p.set_river_clickable(pok)
					p.set_selected_frame(pofa_seq == int(td.get("discard_seq", -1)))
				elif c11s2_active:
					var cok := _c11s2_note(int(td.get("discard_seq", -1)),
						int(td.get("seat", -1)), i, down)
					p.set_river_clickable(cok)
					p.set_selected_frame(c11s2_seq == int(td.get("discard_seq", -1)))
				elif c09_active:
					p.set_river_clickable(_card09_ok(int(td.get("seat", -1)), down,
						int(td.get("discard_seq", -1))))
					p.set_selected_frame(int(td.get("discard_seq", -1)) == c09_seq)
				elif press_panel.active:
					p.set_river_clickable(_press_river_ok(int(td.get("seat", -1)), down))
					p.set_selected_frame(press_panel.rivers.has(int(td.get("discard_seq", -1))))
				elif c43_panel.active:
					var c43seq := int(td.get("discard_seq", -1))
					p.set_river_clickable(_c43_river_ok(c43seq, int(td.get("seat", -1)), down))
					p.set_selected_frame(c43_panel.rivers.has(c43seq))
				elif c45_panel.active:
					var c45seq := int(td.get("discard_seq", -1))
					p.set_river_clickable(_c45_river_ok(c45seq, int(td.get("seat", -1)), down))
					p.set_selected_frame(c45_panel.rivers.has(c45seq))
				elif c33_panel.active:
					var c33seq := int(td.get("discard_seq", -1))
					var c33ok := false
					if not down:
						var c33st = srv_state.get("c33")
						if typeof(c33st) == TYPE_DICTIONARY:
							var c33rv = (c33st as Dictionary).get("rivers")
							if typeof(c33rv) == TYPE_ARRAY:
								c33ok = int_set(c33rv).has(c33seq)
					p.set_river_clickable(c33ok)
					p.set_selected_frame(c33_panel.rivers.has(c33seq))
				elif c27_panel.active:
					var c27seq := int(td.get("discard_seq", -1))
					p.set_river_clickable(not down and srv_c27_has("c27s1_rivers", c27seq))
					p.set_selected_frame(c27_panel.rivers.has(c27seq))
				else:
					if swap_panel.active and not down:
						p.set_river_clickable(true)
					p.set_selected_frame(
						not down and swap_panel.rivers.has(int(td.get("discard_seq", -1))))

	# 3) 副露（我的 + 三家；含暗杠）
	var my_right := vp.x + hand_offset.x
	var ms := meld_scale
	var mw := tile_size.x * ms
	var mh := tile_size.y * ms
	var mrw := tile_size.y * ms
	var mrh := mrw * (302.0 / 360.0)   # 横置牌的实际高度（横图 360x302）
	if meld_entities.has(my_seat):
		var groups: Dictionary = meld_entities[my_seat]
		var keys := groups.keys()
		keys.sort()
		for g in keys:
			var arr: Array = groups[g]
			arr.sort_custom(func(a, b): return int(a.get("slot", 0)) < int(b.get("slot", 0)))
			var kind := String((arr[0] as Dictionary).get("meld_kind", ""))
			var is_ankan: bool = kind == "ankan"
			var n: int = arr.size()
			var group_w := 0.0
			for td in arr:
				group_w += mrw if bool(td.get("rotated", false)) else mw
			var x := my_right - group_w
			if is_ankan:
				# 暗杠：两侧暗牌 + 中间两张明牌，等宽 4 张
				var x0 := my_right - 4.0 * mw
				for k in range(arr.size()):
					var td: Dictionary = arr[k]
					var p := tile_bank.piece(String(td.get("id", "")))
					if p != null:
						var form := "back_meld" if (k == 0 or k == 3) else "face_meld"
						p.apply_state(form, Vector2(x0 + mw * 0.5 + k * mw, vp.y + hand_offset.y - mh * 0.5), 0.0, Vector2.ONE * ms)
			else:
				for td in arr:
					var k := int(td.get("slot", 0))
					var rot := bool(td.get("rotated", false))
					var sw := mrw if rot else mw
					var p := tile_bank.piece(String(td.get("id", "")))
					if p != null:
						if rot:
							p.apply_state("rot", Vector2(x + sw * 0.5, vp.y + hand_offset.y - mrh * 0.5), 0.0, Vector2.ONE * ms)
						else:
							p.apply_state("face_meld", Vector2(x + sw * 0.5, vp.y + hand_offset.y - mh * 0.5), 0.0, Vector2.ONE * ms)
					x += sw
			my_right -= group_w
	# 其他家副露锚点 = 屏幕四个角（与旧版 add_opp_meld / add_opp_ankan 一致）
	# 注意：不要加 _opp_offset（那是给手牌用的，C 的 -60 会把副露/暗杠推出屏幕）
	var opp_anchor := {
		"B": Vector2(0.0, vp.y),
		"C": Vector2.ZERO,
		"D": Vector2(vp.x, 0.0),
	}
	for seat in meld_entities:
		if seat == my_seat:
			continue
		var who := who_of_seat(seat)
		if who == "":
			continue
		var geo: Array = OPP_MELD_GEO.get(who, [])
		if geo.is_empty():
			continue
		var to_far: Vector2 = geo[0]
		var out_dir: Vector2 = geo[1]
		var rot_deg: float = geo[2]
		var sz := opp_meld_tile_size(who)
		var ow := sz.x
		var ol := sz.y
		var groups: Dictionary = meld_entities[seat]
		var keys2 := groups.keys()
		keys2.sort()
		var anc: Vector2 = opp_anchor[who]
		for g in keys2:
			var arr: Array = groups[g]
			arr.sort_custom(func(a, b): return int(a.get("slot", 0)) < int(b.get("slot", 0)))
			var kind2 := String((arr[0] as Dictionary).get("meld_kind", ""))
			var is_ankan2: bool = kind2 == "ankan"
			var group_w2 := 0.0
			for td in arr:
				group_w2 += ol if bool(td.get("rotated", false)) else ow
			var c := 0.0
			for k in range(arr.size()):
				var td: Dictionary = arr[k]
				var rot := bool(td.get("rotated", false))
				var sw2 := ol if rot else ow
				var depth := ol if not rot else (ol * (301.0 / 359.0))
				var pos := anc + to_far * (group_w2 - c - sw2 * 0.5) + out_dir * (depth * 0.5)
				var form := "rot" if rot else "face_meld"
				if is_ankan2:
					# 暗杠：左右两张暗置、中间两张亮牌（所有视角一致）
					form = "back_meld" if (k == 0 or k == arr.size() - 1) else "face_meld"
				var p := tile_bank.piece(String(td.get("id", "")))
				if p != null:
					p.apply_state(form, pos, rot_deg, Vector2.ONE * (sz.x / maxf(tile_size.x, 1.0)))
				c += sw2
			anc = anc + to_far * group_w2
		opp_anchor[who] = anc

	if c10_active:
		_c10_apply_meld_hit(meld_entities)

	# 4) 宝牌指示（牌墩上叠加的明牌）
	for td in dora_entities:
		var p := tile_bank.piece(String(td.get("id", "")))
		if p != null:
			p.apply_state("dora", Vector2(vp.x * 0.5, vp.y * 0.5))

	# 5) 清掉旧模板渲染的残留（按钮留着接点击，视觉交给实体）
	if hand_container != null:
		for sl in _hand_slots():
			var anim := (sl as Control).get_node_or_null("Anim")
			if anim != null and anim.get_child_count() > 0:     # 平时是空的 → 直接跳过
				for c in anim.get_children():
					anim.remove_child(c)
					c.queue_free()
	if discard_container != null and not _piles_hidden_done:
		for sl in _pile_slots(discard_container):
			(sl as Node2D).visible = false
		_piles_hidden_done = true
	for who in OPP_ORDER:
		var cont = opp_discard_containers.get(who, null)
		if cont != null:
			for sl in _pile_slots(cont):
				(sl as Node2D).visible = false
	if meld_container != null:
		for c in meld_container.get_children():
			meld_container.remove_child(c)
			c.queue_free()
	if opp_meld_container != null:
		for c in opp_meld_container.get_children():
			opp_meld_container.remove_child(c)
			c.queue_free()

	# 只隐藏「这一帧没有再出现」的牌；仍在手牌/牌河/副露里的牌不隐藏，
	# 避免每帧 visible/mouse_filter 抖动导致鼠标悬停状态丢失（手牌自己落下/抽搐）
	tile_bank.end_frame()


# ── 性能：状态 / 渲染去重用的记号（见各函数里的 ★ 性能 注释）─────────────
var _last_state_hash := 0                          # 上一份 state 的内容 hash
var _last_state_size := -1                         # 上一份 state 的字段数（防 hash 碰撞）
var _entity_sig := ""                              # 上一次牌实体摆放的指纹
var _push_seat_sent := -999                        # 已告知长连接的座位号
var _piles_hidden_done := false                     # 老画法的牌河格子已隐藏过（只需要一次）

func srv_apply_state(st, events = null) -> void:
	if typeof(st) != TYPE_DICTIONARY:
		return
	var st2: Dictionary = st
	# 服务端给的 state 是「哪个座位看到的」。和本窗口的座位对不上就直接丢掉 ——
	# 多窗口时曾经出过「读到别家的响应」，结果把别家的手牌画到自己这里。
	# （正常路径下 state.seat 一定等于 my_seat，这只是个保险丝）
	var got_seat := int(st2.get("seat", my_seat))
	if got_seat != my_seat:
		push_warning("main.gd: 收到 %d 号位的状态，本窗口是 %d 号位 —— 丢掉这次同步"
			% [got_seat, my_seat])
		return
	# ★ 性能（掉帧主因）：0.35s 轮询 + 长连接推送经常把**一模一样**的 state 送过来，
	#   以前每来一次就把手牌节点、牌河、136 张实体全部重画一遍。
	#   内容没变（hash + 字段数一致）且没有事件要重放 → 整个渲染流程直接跳过。
	#   （同一份 state 的重放是幂等的，跳过不影响任何逻辑；有事件时必定重放。）
	if typeof(events) == TYPE_ARRAY and not (events as Array).is_empty():
		_last_state_hash = 0
	else:
		var _sh: int = st2.hash()
		if _sh != 0 and _sh == _last_state_hash and st2.size() == _last_state_size:
			return
		_last_state_hash = _sh
		_last_state_size = st2.size()
	# 换了一局？（F2 开新局、或别的窗口开了新局）→ 牌山/手牌/牌河全部重来
	# 庄家换人、或我换了座位视角 → 风盘的「東」要转过去，牌山的「东面」也要跟着换
	srv_state = st2
	var rid := int(st2.get("round_id", -1))
	_update_fengpan_image()
	_round_hud_sync(st2)
	if rid != srv_round_id or _dealer_side() != srv_dealer_side:
		srv_round_id = rid
		srv_dealer_side = _dealer_side()
		_reset_view_for_new_round()
		c41_auto_done = false
		c41_key = ""      # 牌山重建（会顺手编号一次，但那时还不知道新庄家）
		assign_wall_numbers()            # 用新庄家再排一次：编号 1 从「庄家那一面」开始
		_apply_fengpan()                 # 风盘的「東」转到庄家那一面
		_update_seat_label()             # 左上角那行字也跟着报「第几局」
	if typeof(st2.get("humans")) == TYPE_ARRAY:
		srv_humans = st2.get("humans")
	# 现在是不是「在等别人」：等的时候要定时问服务端（多窗口时才能看到别人的动作）
	var my_opts := srv_opts_of(st2)
	waiting_for_others = (int(st2.get("turn", my_seat)) != my_seat) and my_opts.is_empty()
	# 我的手牌：服务端权威（hand 含刚摸那张，用 drawn 区分出「摸牌」）
	var hand: Array = st2.get("hand", [])
	var dr := "" if st2.get("drawn") == null else String(st2.get("drawn"))
	hand_tiles.clear()
	var skip_i := -1
	var di := int(st2.get("drawn_index", -1))
	if di >= 0 and di < (hand as Array).size():
		skip_i = di                      # 服务端按「物理牌」给的下标（换牌后也准）
	elif dr != "":
		for i in range((hand as Array).size() - 1, -1, -1):
			if String((hand as Array)[i]) == dr:
				skip_i = i
				break
	for i in range((hand as Array).size()):
		if i == skip_i:
			continue
		hand_tiles.append(String((hand as Array)[i]))
	drawn_tile = dr if skip_i >= 0 else ""
	sort_hand()
	refresh_hand()
	# 牌河：服务端按座位给（顺序也由服务端定）
	discard_pile.clear()
	discard_rotated.clear()
	for who in OPP_ORDER:
		opp_discards[who] = []
	for row in (st2.get("discards", []) as Array):
		if typeof(row) != TYPE_DICTIONARY:
			continue
		var rd := row as Dictionary
		# 被吃/碰/杠拿走的那张牌：牌河里就不该再看到它了
		# （服务端把 called 标成 1；不跳过去的话，同一张牌会「牌河 1 张 + 副露 4 张」看起来 5 张）
		if int(rd.get("called", 0)) != 0:
			continue
		var s := int(rd.get("seat", 0))
		var t2 := String(rd.get("tile", ""))
		if s == my_seat:
			discard_pile.append(t2)
			discard_rotated.append(bool(rd.get("is_riichi_tile", false)))
		elif who_of_seat(s) != "":
			(opp_discards[who_of_seat(s)] as Array).append(t2)
	refresh_discards()
	# 其他家手牌张数（只显示张数，不看内容）
	var hc: Array = st2.get("hand_counts", [])
	for row in hc:
		if typeof(row) != TYPE_DICTIONARY:
			continue
		var hw := who_of_seat(int((row as Dictionary).get("seat", my_seat)))
		if hw == "" or hw == "me":
			continue
		var n := int((row as Dictionary).get("tiles", 13))
		var arr: Array = []
		for k in range(n):
			arr.append("")
		opp_hands[hw] = arr
		_refresh_opp_hand(hw)
	# 轮次：0 = 我，1/2/3 = OPP_ORDER（下家/对家/上家）
	var tseat := int(st2.get("turn", my_seat))
	var twho := who_of_seat(tseat)
	turn_index = 0 if tseat == my_seat else (OPP_ORDER.find(twho) + 1)
	riichi_declared = false
	for s in (st2.get("riichi", []) as Array):
		# 服务端给的是**绝对座位号**，必须和 my_seat 比。
		# 以前这里写死 0：0 号位一立直，所有窗口都以为自己立直了 → 全都只能摸切。
		if int(s) == my_seat:
			riichi_declared = true
	if riichi_declared:
		# 已经立直了：选牌态收掉（按钮由 srv_layout_buttons 按 legal 关）
		riichi_selecting = false
	# 食い替え（吃/碰/杠之后不能打的那几张）：服务端说了算
	# 字段名是 pending_kuikae（以前这里写成 kuikae，一直读不到 → 客户端这边从来没拦过）
	var kq = st2.get("pending_kuikae")
	if typeof(kq) == TYPE_DICTIONARY:
		var kkw := String((kq as Dictionary).get("kind", ""))
		var kused: Array = (kq as Dictionary).get("used", [])
		after_chi_discard = (kkw == "chi")
		after_pon_discard = (kkw == "pon" or kkw == "minkan" or kkw == "kakan")
		if after_chi_discard and kused.size() >= 2:
			chi_used_tiles = [kused[0], kused[1]]
		if after_pon_discard and kused.size() >= 2:
			pon_groups = [kused[0], kused[1]]
	else:
		after_chi_discard = false
		after_pon_discard = false
	srv_apply_melds(st2)
	_apply_used_skills(st2)             # 一次性技能：本小局用过的图标变灰
	_c37s2_sync(st2)                    # 强运：已经生效就把牌种网格收掉（否则卡死）
	_c37s1_sync(st2)                    # 岭上开花：牌换好了（鸣牌窗口里那一杠）→ 提示点自摸
	_c42s2_sync(st2)                    # 夺目：结算前问一次「按谁的庄家算点数」
	_skill_mute_apply()                 # 技能图标遮罩（屏蔽自动询问）跟着状态走
	_maybe_close_press(st2)             # 压制：不是我的出牌回合就收起选牌界面
	_support_mute_apply(st2)            # 协战卡遮罩：在协战卡上画「遮罩」
	_apply_revealed(st2)                # 别人发动过技能 → 人物卡翻明
	_apply_broadcast(st2)               # 全场技能播报
	_kp_sync(st2)                      # 看破：别人发动技能时问我
	_masked_auto_pass(st2)             # 遮罩（屏蔽自动询问）→ 替玩家放行
	_c29s1_masked_skip(st2)            # 加速：遮罩盖着就别问我（自动跳过）
	_pofa_sync(st2)                    # 破发：别家立直后自动问我
	_reveal_hands_sync(st2)            # 观看手牌：别家手牌变明牌
	_sf_sync(st2)                      # 深山 / 友引：自动弹窗
	_ym_sync(st2)                      # 友引段1：副露完摊面子
	_c25b_sync(st2)                    # 宝牌的集合：别人摸到宝牌 → 强制换
	_future_sync(st2)                  # 未来：发动之后才亮牌排序
	_c25s2_auto_arm()                  # 宝牌的集合：配牌阶段自动发动（要过看破）
	_hs_sync(st2)                      # 海神：别人摸到万子/红中 → 弹还牌
	_update_deal_window(st2)            # 配牌阶段技能窗口（开始按钮）
	_flow_sync(st2)                     # 风神：换风牌的分步界面
	_c30_sync(st2)                      # 向听：交牌 / 挑牌互换
	_c32_sync(st2)                      # 新手运：要幺九牌 / 换牌（对方有配牌技能就先让路）
	_c34_why_sync(st2)                  # 厄运/海底：剩 12 张没触发时给一句原因
	_c35_sync(st2)                      # 流势：副露后自动弹「排接下来 4 张」
	_c36_sync(st2)                      # 思路：别人宣告技能 → 看到他的手牌
	_c41_sync(st2)                      # 复制：别人宣告技能 → 问我要不要复制
	_c45s2_sync(st2)                    # 替身：第二位点一张手牌 = 第一位切这张
	_c40s2_sync(st2)                    # 同盟：我打出的牌他能吃碰杠 → 我挑一组搭子
	_c43s2_sync(st2)                    # 免疫：别人指向我的技能 → 问我要不要免疫
	_wind_sync(st2)                     # 自风：别人摸到我的自风 → 换牌界面
	_c05_sync(st2)                      # 策略：换牌机会
	_c05_hide_sync(st2)                 # 策略：被人看手牌 → 盖牌
	_c05_counter_sync(st2)              # 策略：计数器
	_sw_sync(st2)                       # 南风：选牌种 / 选两张手牌
	_apply_skill_frames(st2)            # 自信 / 自风：发动过的图标套红框（整小局）
	_update_board_tile(st2)             # 画板：压在人物卡下方的明牌
	srv_sync_wall(st2)                  # 牌山（拿走哪些 / 翻了哪些宝牌）也跟着服务端走
	_score_label_sync(st2)              # 风盘四边 Label：下/右/上/左 的点数
	# 宝牌运（25S1）：切出宝牌被罚 → 说一声（自己的事件不在下面那个「别人摸牌」循环里）
	if typeof(events) == TYPE_ARRAY:
		for ev in (events as Array):
			if typeof(ev) != TYPE_DICTIONARY:
				continue
			if bool((ev as Dictionary).get("c25", false)):
				_toast("宝牌运：切出宝牌，支付三家各 3000 点，本局不能胡牌")
			elif String((ev as Dictionary).get("event", "")) == "c34_last":
				_toast("海底：把「%s」换进手里了 —— 点【自摸】结算"
					% String((ev as Dictionary).get("tile", "")))
	# 其他家摸到的牌：显示成一个牌背，打完就收起
	if typeof(events) == TYPE_ARRAY:
		for ev in (events as Array):
			if typeof(ev) != TYPE_DICTIONARY:
				continue
			var e := String((ev as Dictionary).get("event", ""))
			var s2 := int((ev as Dictionary).get("seat", my_seat))
			var w2 := who_of_seat(s2)
			if w2 == "" or w2 == "me":
				continue
			if e == "draw":
				opp_drawn[w2] = String((ev as Dictionary).get("tile", ""))
				_show_opp_drawn(w2, true)
			elif e == "discard":
				opp_drawn[w2] = ""
				_show_opp_drawn(w2, false)
	# 已经和了 / 流局了
	var res = st2.get("result")
	if typeof(res) == TYPE_DICTIONARY and not (res as Dictionary).is_empty():
		srv_show_result(res)
	# 按钮永远跟服务端状态一致：每次同步都重摆一次，残留在屏幕上的会立刻消失
	if riichi_selecting:
		srv_layout_buttons(["riichi"])
	else:
		srv_layout_buttons(srv_opts_of(st2))
	_apply_entity_states(st2)
	_lizhi_stick_sync(st2)              # 立直棒：谁立直谁门前那根 2 秒淡入
	# ★ 必须在 _apply_entity_states 之后：牌河那张的 discard_seq / river_seat
	#   是这一步才写进 TilePiece 的，放前面会锁到「上一张」（用户报的 off-by-one）
	_claim_frames_sync(st2)
	_legal_guard(st2)
	# 最后：如果服务端说「轮到我摸牌了」，我自己把摸牌推下去（见下面的注释）
	_auto_draw_if_my_turn()


# 轮到我摸牌 → 立刻自动推一步（客户端没有「摸牌」按钮，全靠这个）。
# 为什么必须放在这里：多窗口时「轮到我」这件事是**轮询**发现的（别人打完了我才知道），
# 如果不主动开推，这个窗口就会一直停在「该我摸牌」不动 —— 表现就是「下一家不自动摸牌」。
# 单人玩时不会暴露，因为那是我自己动作之后 srv_act 接着推的。
func _auto_draw_if_my_turn() -> void:
	if game_over or dealing or srv_busy:
		return                                   # 正在推 / 正在配牌 / 已结束 → 不重复开推
	if not bool(srv_state.get("deal_done", false)):
		return
	if int(srv_state.get("turn", -1)) != my_seat:
		return
	if String(srv_state.get("phase", "")) != "draw":
		return                                   # 只有「该我摸牌」才自动推；打牌/鸣牌等我按按钮
	if _card09_gate_before_draw():
		return                                   # 持 09 号卡：先让他决定要不要换牌河
	draw_tile()


# 副露指纹：我的 + 其他三家的「组数 / 种类 / 张数 / 牌面」全都算进来
# ★ 加杠是「碰的 3 张 → 杠的 4 张」，组数没变 —— 只数组数的话这里会以为「没变化」，
#   副露区就不会重画，杠里永远只显示 3 张。
func _meld_fingerprint(st: Dictionary) -> String:
	var sig := ""
	for m in (st.get("my_melds", []) as Array):
		if typeof(m) != TYPE_DICTIONARY:
			continue
		var d: Dictionary = m
		sig += "M:" + String(d.get("kind", "")) + ":"
		for t in (d.get("tiles", []) as Array):
			sig += String(t) + ","
		sig += "|"
	var am: Array = st.get("all_melds", [])
	for i in range(1, mini(am.size(), 4)):
		if typeof(am[i]) != TYPE_ARRAY:
			continue
		for m in (am[i] as Array):
			if typeof(m) != TYPE_DICTIONARY:
				continue
			var d2: Dictionary = m
			sig += "O%d:" % i + String(d2.get("kind", "")) + ":"
			for t in (d2.get("tiles", []) as Array):
				sig += String(t) + ","
			sig += "|"
	return sig


# 和了 / 流局的显示（番符点用服务端算好的）
# 副露：服务端是唯一权威；只要有变化就整块按服务端重画（我的 + 其他三家的）
func srv_apply_melds(st: Dictionary) -> void:
	var mine: Array = st.get("my_melds", [])
	var am: Array = st.get("all_melds", [])
	var sig := _meld_fingerprint(st)
	if sig == srv_meld_sig:
		return
	srv_meld_sig = sig
	# 我的副露
	if meld_container != null:
		for c in meld_container.get_children():
			meld_container.remove_child(c)
			c.queue_free()
	meld_list.clear()
	meld_left = -1.0
	meld_count = 0
	menzen = true
	for m in mine:
		var d: Dictionary = m
		var kind := String(d.get("kind", ""))
		var rot := int(d.get("rot_index", 0))
		if kind == "minkan":                 # 明杠：横置那张按「谁打的」摆（杠下家 = 第 3 张）
			rot = kan_rot_index(srv_name_of(int(d.get("from_seat", 0))))
		# 加杠：沿用原来那副「碰」的横置位置（横置那张不动，第 4 张竖着加到一端）
		add_meld(d.get("tiles", []), -1.0, rot, false, kind)
		meld_count += 1
		if kind != "ankan":
			menzen = false               # 吃/碰/明杠/加杠 破门清，暗杠不破
	# 其他三家的副露
	if opp_meld_container != null:
		for c in opp_meld_container.get_children():
			opp_meld_container.remove_child(c)
			c.queue_free()
	var vp := get_viewport_rect().size
	for i in range(1, mini(am.size(), 4)):
		var who: String = OPP_ORDER[i - 1]
		opp_meld_counts[who] = 0
		opp_meld_anchor[who] = {
			"B": Vector2(0.0, vp.y), "C": Vector2.ZERO, "D": Vector2(vp.x, 0.0)
		}.get(who, Vector2.ZERO)
		for m in (am[i] as Array):
			var dd: Dictionary = m
			var k2 := String(dd.get("kind", ""))
			var r2 := int(dd.get("rot_index", 0))
			if k2 == "minkan":
				r2 = kan_rot_index(srv_name_of(int(dd.get("from_seat", 0))))
			# 加杠：横置位置沿用原来的「碰」
			add_opp_meld(who, dd.get("tiles", []), r2, false, k2)
			opp_meld_counts[who] = int(opp_meld_counts.get(who, 0)) + 1


# 占位昵称（离线本地 4 个账号就叫 我/下家/对家/上家）不算 ID，统一换成 P1~P4
const NICK_PLACEHOLDERS := ["我", "下家", "对家", "上家", "me", "B", "C", "D"]


func _nick_is_placeholder(n: String) -> bool:
	return NICK_PLACEHOLDERS.has(n)


func srv_nick_of(seat: int) -> String:
	"""座位 → 本局昵称（服务端 state.scores 里带的）；拿不到 / 是占位名就回 ID「P1~P4」。"""
	var s := int(seat)
	if s < 0 or s > 3:
		return ""
	var arr = srv_state.get("scores")
	if typeof(arr) == TYPE_ARRAY:
		for it in (arr as Array):
			if typeof(it) != TYPE_DICTIONARY:
				continue
			if int((it as Dictionary).get("seat", -1)) != s:
				continue
			var n := String((it as Dictionary).get("nickname", "")).strip_edges()
			if n != "" and not _nick_is_placeholder(n):
				return n
			break
	return "P%d" % (s + 1)


func srv_name_of(seat: int) -> String:
	# 座位号 → 显示用的「谁」（me / B 上家 / C 对家 / D 下家），按本窗口的座位算。
	return who_of_seat(seat)


func srv_show_result(res: Dictionary) -> void:
	var w: Dictionary = res
	if typeof(res.get("win")) == TYPE_DICTIONARY:
		w = res["win"]
	if typeof(w.get("pays")) != TYPE_DICTIONARY and typeof(w.get("points")) == TYPE_DICTIONARY:
		w = w.duplicate()
		w["pays"] = w["points"]
	# ★ 以前第一行是 `if game_over: return`：而摸牌后的「预告版播报」(_after_draw → show_hupai)
	#   已经把 game_over 置成 true → 点【自摸】后真正的结算被丢掉，界面什么都不弹（荣和不受影响）。
	#   现在：面板还开着就用真结算刷新它；没开着就正常弹。
	var _panel_on := (win_announce != null and is_instance_valid(win_announce)
		and (win_announce as CanvasItem).visible)
	if _panel_on:
		var _was := game_over
		game_over = false
		show_hupai(w)
		game_over = _was
		return
	show_hupai(w)
	# 不再计时自动进下一局：四家都点「确认」后由服务端放行。


# 结算画面停一会儿，再按服务端规则进下一局（连庄 / 本场 / 场次推进都由服务端算）。
# ── 结算确认：四个人都点后，服务端才放行下一局 ─────────────────────────
# ── 半庄终局播报（四家名次 → 确认 → 一起回大厅）─────────────────────
func _match_announce_get() -> Control:
	if match_announce != null and is_instance_valid(match_announce):
		return match_announce
	var host: Node = get_parent()
	if host == null:
		host = self
	var layer := host.get_node_or_null("MatchAnnounceLayer") as CanvasLayer
	if layer == null:
		layer = CanvasLayer.new()
		layer.name = "MatchAnnounceLayer"
		# ★ 必须比 WinAnnounceLayer(31) 高：南四那一局的「流局/和牌播报」还开着，
		#   层级低就会被整块盖住（2026-11-01 现场：只看到流局，看不到分数）。
		layer.layer = 32
		host.add_child(layer)
	match_announce = MatchAnnounce.new()
	match_announce.name = "MatchAnnounce"
	match_announce.visible = false
	layer.add_child(match_announce)
	match_announce.position = Vector2.ZERO
	match_announce.size = get_viewport_rect().size
	return match_announce


func _show_match_final(rank, confirmed) -> void:
	if match_active:
		return
	match_active = true
	_match_waiting = false
	_match_acc = 0.0
	# 把「和牌/流局播报」收掉：它是上一小局的结算，分数播报才是终局
	if win_announce != null and is_instance_valid(win_announce):
		win_announce.visible = false
	if win_announce != null and is_instance_valid(win_announce):
		win_announce.scale = Vector2.ONE
		win_announce.modulate = Color(1, 1, 1, 1)
	var a := _match_announce_get()
	a.set_content({
		"rank": rank if typeof(rank) == TYPE_ARRAY else [],
		"my_seat": my_seat,
		"confirmed": confirmed if typeof(confirmed) == TYPE_ARRAY else [],
		"humans": srv_humans,
	})
	a.position = Vector2.ZERO
	a.size = get_viewport_rect().size
	a.visible = true
	if not a.confirmed.is_connected(_match_confirm_press):
		a.confirmed.connect(_match_confirm_press)
	print("[终局] 半庄结束，名次：", rank)


func _match_confirm_press() -> void:
	_match_waiting = true
	var r := srv_request({"op": "match_confirm", "seat": my_seat})
	if r.is_empty():
		_toast(_srv_err("终局确认：服务端没有回应"))
		return
	_match_apply(r)


func _match_apply(r: Dictionary) -> void:
	var done := bool(r.get("all_done", false))
	var conf = r.get("confirmed", [])
	if match_announce != null and is_instance_valid(match_announce):
		var rk = r.get("final_rank", [])
		if typeof(rk) == TYPE_ARRAY and not (rk as Array).is_empty() 				and (match_announce.rank_rows as Array).is_empty():
			match_announce.rank_rows = rk
			match_announce.queue_redraw()
		match_announce.set_state(conf if typeof(conf) == TYPE_ARRAY else [], done)
	if done:
		match_active = false
		_back_to_lobby()


func _backend_lobby_ready() -> bool:
	return true


func _back_to_lobby() -> void:
	if _match_returned:
		return
	_match_returned = true
	print("[终局] 四家都已确认 → 回大厅")
	await get_tree().create_timer(0.9).timeout
	get_tree().change_scene_to_file("res://初始菜单.tscn")


# 点过确认后每 1.5 秒问一次「别人点了没」，全齐就回大厅
func _match_tick(delta: float) -> void:
	if not match_active or _match_returned or not _match_waiting:
		return
	_match_acc += delta
	if _match_acc < 1.5:
		return
	_match_acc = 0.0
	var r := srv_request({"op": "match_confirm", "seat": my_seat})
	if r.is_empty():
		return
	_match_apply(r)


# 结算「确认」按钮：右下角（用户口径 2026-11-02：原来放屏幕下方正中，会压住自己的分数面板）
func _result_confirm_place(b: Control) -> void:
	if b == null:
		return
	var vp := get_viewport_rect().size
	var m := 28.0
	b.position = Vector2(maxf(vp.x - b.size.x - m, 0.0), maxf(vp.y - b.size.y - m, 0.0))


func _result_confirm_button_get() -> Control:
	if win_confirm_btn != null and is_instance_valid(win_confirm_btn):
		return win_confirm_btn
	var host := _win_seats_node()
	if host == null:
		host = _win_announce_get()
	if host == null:
		return null
	win_confirm_btn = WinConfirmButton.new()
	win_confirm_btn.name = "Confirm"
	win_confirm_btn.size = Vector2(300, 92)
	_result_confirm_place(win_confirm_btn)
	win_confirm_btn.confirmed.connect(_result_confirm_press)
	win_confirm_btn.visible = false      # 场景里到最后一步才点亮
	host.add_child(win_confirm_btn)
	return win_confirm_btn


func _result_confirm_press() -> void:
	if not game_over or result_confirmed:
		return
	var r := srv_request({"op": "result_confirm", "seat": my_seat})
	if r.is_empty():
		_toast(_srv_err("結算確認失敗"))
		return
	result_confirmed = true
	_result_confirm_apply(r.get("result_confirm", {}))
	# 这次刚好凑齐四家 → 由最后确认的人发 next；其他窗口轮询会接到新 round_id。
	var rc = r.get("result_confirm")
	if typeof(rc) == TYPE_DICTIONARY and bool((rc as Dictionary).get("ready", false)):
		_auto_next_round()


func _result_confirm_apply(raw) -> void:
	if typeof(raw) != TYPE_DICTIONARY:
		return
	var d := raw as Dictionary
	var confirmed: Array = d.get("confirmed", [])
	var required: Array = d.get("required", [])
	result_confirmed = confirmed.has(my_seat) or confirmed.has(float(my_seat))
	var count := 0
	for s2 in required:
		if confirmed.has(int(s2)) or confirmed.has(float(s2)):
			count += 1
	var b := _result_confirm_button_get()
	if b != null:
		pass    # 显隐由和牌播报场景控制
		_result_confirm_place(b)
		b.call("set_state", result_confirmed, count, maxi(required.size(), 1))
	var sig := "%s/%s" % [str(confirmed), str(required)]
	if sig != result_confirm_sig:
		result_confirm_sig = sig
		if result_confirmed and not bool(d.get("ready", false)):
			_toast("已確認，等待其他玩家（%d/%d）" % [count, maxi(required.size(), 1)])


func _result_confirm_poll() -> void:
	if not game_over:
		return
	var r := srv_request({"op": "state", "seat": my_seat})
	if r.is_empty():
		return
	var st = r.get("state")
	if typeof(st) == TYPE_DICTIONARY:
		var old_rid := int(srv_state.get("round_id", -1))
		var new_rid := int((st as Dictionary).get("round_id", old_rid))
		if new_rid != old_rid:
			# 最后确认的另一个窗口已经开了下一局：本窗口直接接上。
			_reset_view_for_new_round()
			dealing = true
			game_phase = PHASE_DEAL
			_apply_round_start(r)
			get_tree().create_timer(DEAL_FIRST_WAIT).timeout.connect(_deal_step)
			return
	var rc = r.get("result_confirm")
	if typeof(rc) == TYPE_DICTIONARY:
		_result_confirm_apply(rc)


func _auto_next_round() -> void:
	if not game_over:
		return
	var r := srv_request({"op": "next", "seat": my_seat})
	if r.is_empty():
		return
	if bool(r.get("waiting_confirm", false)):
		_result_confirm_apply(r.get("result_confirm", {}))
		return
	if bool(r.get("match_finished", false)):
		# 半庄打完 → 弹「半庄终了」四家名次播报，四家确认后一起回大厅
		_show_match_final(r.get("final_rank", []), r.get("confirmed", []))
		return
	var st = r.get("state")
	if typeof(st) != TYPE_DICTIONARY:
		return
	_reset_view_for_new_round()
	dealing = true
	game_phase = PHASE_DEAL
	_apply_round_start(r)
	get_tree().create_timer(DEAL_FIRST_WAIT).timeout.connect(_deal_step)


func discard_tile(index: int) -> void:
	if game_over:
		return
	# 国标 / 一定和牌：点手牌 = 只选中（亮度/张数都交给 hand_pick），点「开始」才宣言
	if guobiao_selecting:
		_gb_pick(index)
		return
	if yiding_selecting:
		_yd_pick(index)
		return
	# ※ 技能选牌界面优先：这些界面上点手牌 = 选中/取消，不是打牌。
	#    配牌技能（风神 Card04 S1 / 南风 Card06 S1）选牌时服务端 phase 还是
	#    "deal_skill"，所以阶段判断必须放到这堆分支的**后面**，否则永远选不了牌。
	if skill2_card != 0 and skill2_target >= 0:
		_toggle_skill2_pick(index)          # 技能 2 选牌阶段：点手牌 = 选中/取消
		return
	if sw_stage == "hand":
		_toggle_sw_hand(index)                  # 南风：选两张手牌
		return
	if c10_active:
		_c10_toggle_hand(index)                  # 鬼门：手牌/牌河/副露 统一彩框
		return
	if c09_active:
		hand_pick.toggle(index)                 # 09：选手牌（统一界面）
		_apply_entity_states(srv_state)
		return
	if c05_hide_active:
		_toggle_c05_hide_hand(index)            # 策略：盖牌
		return
	if c05_active:
		_toggle_c05_hand(index)                 # 策略：换牌用的手牌
		return
	if wind_active:
		_toggle_wind_hand(index)                # 自风：点手牌 = 选中/取消
		return
	if flow_active:
		_toggle_flow_hand(index)                # 风神：点手牌 = 选中/取消
		return
	if c30_panel.active:
		c30_panel.handle_hand(index)            # 向听：点手牌 = 选中/取消
		return
	if c32_panel.active:
		c32_panel.handle_hand(index)            # 新手运：点手牌 = 选中/取消（只能交幺九）
		return
	if c33_panel.active:
		c33_panel.handle_hand(index)            # 染手：点手牌 = 选中/取消
		return
	if c43_panel.active:
		c43_panel.handle_hand(index)            # NO MISS：点手牌 = 选中/取消
		return
	if c45_panel.active:
		c45_panel.handle_hand(index)            # 神境：点手牌 = 选中/取消
		return
	if c46_panel.active:
		c46_panel.handle_hand(index)            # 恶听：点手牌 = 选中/取消
		return
	if c27_panel.active:
		var all27 := display_tiles()
		if c27_mode == "s2" and index >= 0 and index < all27.size() \
				and not srv_c27s2_ok(String(all27[index])):
			_toast("命中：这张打出去就不听牌了")
			return
		c27_panel.handle_hand(index)            # 调包 / 命中：点手牌 = 选中/取消
		return
	if c24_panel.active:
		var c24_tiles := display_tiles()
		if index >= 0 and index < c24_tiles.size() \
				and not srv_can_c24_with(String(c24_tiles[index])):
			_toast("一发：这张打出去就不听牌了")
			return
		c24_panel.handle_hand(index)            # 一发：点手牌 = 选中/取消
		return
	if press_panel.active:
		press_panel.handle_hand(index)          # 压制：点手牌 = 选中/取消
		return
	if c25b_panel.active:
		var all25 := display_tiles()
		if index >= 0 and index < all25.size() and srv_is_dora(String(all25[index])):
			_toast("宝牌的集合：不能拿宝牌去换")
			return
		c25b_panel.handle_hand(index)          # 宝牌的集合：点手牌 = 选中/取消
		return
	if swap_panel.active:
		swap_panel.handle_hand(index)           # 换牌：点手牌 = 选中/取消
		return
	# ※ 以上都不是选牌界面 → 下面是真正的切牌，先拦配牌阶段
	if c11_active:
		hand_pick.toggle(index)          # 「魔术」选牌中：点手牌只是选中
		return
	if hs_active and hs_ui != null:
		hand_pick.toggle(index)          # 海神选牌中：只是选中
		return
	if pofa_active and pofa_ui != null:
		hand_pick.toggle(index)          # 破发选牌中：只是选中
		return
	if zl_active and zl_ui != null:
		hand_pick.toggle(index)          # 炸裂选牌中：只是选中
		return
	if ym_panel.active:
		ym_panel.handle_hand(index)             # 友引摊面子：选牌
		return
	if sf_active and sf_ui != null:
		hand_pick.toggle(index)          # 深山/先负/馈赠/友引：选牌只是选中
		return
	if dy_active and dy_ui != null:
		return                           # 钓鱼只选牌种，不用手牌
	if c11s2_active:
		return                           # 「快手」不需要手牌
	# ★ 统一闸门：还有技能在等我「选人 / 选牌」→ 点手牌一律不算打牌。
	#   这些状态以前不在上面的 if 链里，点手牌会直接把牌打出去
	#   （友引段2、决斗/X神/避开/连接/钓鱼的选人、前路/传承的选单…）。
	if _skill_input_busy():
		return
	if game_phase == PHASE_DEAL:
		return
	if String(srv_state.get("phase", "")) == "deal_skill":
		_toast("配牌阶段：等其他玩家发动技能或跳过")
		return
	if bool(srv_state.get("must_tsumogiri", false)) and drawn_tile != "" \
			and index != drawn_slot():
		_toast("换牌之后只能摸切（打刚摸到的那张）")
		return
	var _all := display_tiles()
	if index >= 0 and index < _all.size() and not srv_can_discard_with(String(_all[index])):
		_toast("现在只能打刚摸到的那张")
		return
	if drawn_tile == "" and not after_chi_discard and not after_pon_discard and String(srv_state.get("phase", "")) != "discard":
		return                       # 没摸牌就不能打（吃之后允许直接打一张）
	var tiles := display_tiles()
	if index < 0 or index >= tiles.size():
		return
	if c10s2_kinds.has(String(tiles[index])):
		_toast("「四喜」期间不能打出手里的东或北")
		return

	# Card25 S1「宝牌运」：开启状态下切宝牌要先确认一次
	var c25_t := String(tiles[index])
	if srv_c25_on() and srv_is_dora(c25_t):
		if c25_confirm_tile != c25_t:
			c25_confirm_tile = c25_t
			_c25_confirm_show(true)
			_toast("确认要切出宝牌吗？（再点一次这张牌才打出；点「开始」取消）")
			return
	elif c25_confirm_tile != "" and c25_confirm_tile != c25_t:
		_c25_confirm_show(false)             # 点了别的牌 → 取消上次的确认

	# 吃完必须切一张，且这张不能和吃用的那两张凑成面子（否则切不出去）
	if after_chi_discard and not can_discard_after_chi(tiles[index]):
		return
	# 碰完必须切一张，且不能切出与碰来的那张相同的牌
	if after_pon_discard and not can_discard_after_pon(tiles[index]):
		return

	# ① 已点立直：只能切出「切完仍听牌」的那张，切出后横置进牌河
	if riichi_selecting:
		if not srv_can_riichi_with(String(tiles[index])):
			return                       # 这张切了就断听，不允许
		_discard_at(index, true)
		riichi_selecting = false
		_update_riichi_button_dim()
		return

	# ② 立直后：不允许再从手牌打出，只能摸切
	if riichi_declared and index != drawn_slot():
		_toast("立直后只能打刚摸到的那张（摸切）")
		return

	_discard_at(index, false)


# 一定和牌：宣言 → 把选好的那张打出去 → 服务端立刻结算（不进鸣牌窗口）
# 选牌面板由 _yd_confirm 先关掉（亮度交回 hand_pick / 立直规则）
func _declare_yiding(tile: String) -> void:
	hovered_index = -1
	var r := srv_request({"op": "yiding", "seat": my_seat, "tile": tile})
	if srv_kangpo_blocked(r):
		# 等对方决定是否看破：放行后服务端自己重放这条 op
		_apply_entity_states(srv_state)
		return
	if r.is_empty():
		_toast(_srv_err("一定和牌：服务端没有回应"))
		_pull_state()
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "一定和牌：发动失败")))
		_pull_state()
		return
	var yd_ev: Dictionary = {}
	if typeof(r.get("event")) == TYPE_DICTIONARY:
		yd_ev = r.get("event")
	if String(yd_ev.get("event", "")) == "yiding_void":
		# 恶灵堵荣和 + 浓雾封自摸 → 一定和牌作废，这一局接着打
		_toast("一定和牌作废：%s（游戏继续）"
			% String(yd_ev.get("reason", "两条路都被堵住")))
	else:
		_toast("一定和牌：宣言！")
	srv_apply_state(r.get("state"), r.get("events"))
	_ensure_result()


func _discard_at(index: int, rotated: bool) -> void:
	var tiles := display_tiles()
	if index < 0 or index >= tiles.size():
		return
	var t := String(tiles[index])
	var confirmed := c25_confirm_tile != "" and c25_confirm_tile == t
	if c25_confirm_tile != "":
		_c25_confirm_show(false)             # 确认态用完就清（打出去了 / 立直也算）
	hovered_index = -1
	after_chi_discard = false
	after_pon_discard = false
	var req := {"tile": t}
	if confirmed:
		req["c25_ok"] = true                 # 已经确认过要切宝牌
	srv_act("riichi" if rotated else "discard", req)


# 打出手牌后，刚摸的那张正式进手牌并重新排序
func _merge_drawn() -> void:
	if drawn_tile != "":
		hand_tiles.append(drawn_tile)
		drawn_tile = ""
		sort_hand()


# ────────────────────────── 显示 ──────────────────────────

# 量出模板牌的真实显示尺寸，让手牌排布刚好贴合牌面（再乘上「手牌大小」接口）
func _measure_tile_size() -> void:
	if pai == null:
		return
	var sample := pai.get_node_or_null(TILE_IDS[0]) as Node2D
	if sample == null:
		return
	var spr := sample.get_node_or_null("Sprite2D") as Sprite2D
	if spr == null or spr.texture == null:
		return
	base_tile_size = spr.texture.get_size() * sample.scale * spr.scale
	tile_size = base_tile_size * hand_scale_ratio
	drawn_gap = tile_size.x * DRAWN_GAP_RATIO * sizee


# 手牌区整体贴到屏幕底部（按钮高度含悬停抬起空间）
func _layout_hand_area() -> void:
	if hand_container == null:
		return
	var vp := get_viewport_rect().size
	var wrapper_size := Vector2(tile_size.x, tile_size.y + HOVER_RAISE)
	hand_container.size = Vector2(vp.x, wrapper_size.y)
	hand_container.global_position = Vector2(
		vp.x * hand_left_ratio,
		vp.y - HAND_BOTTOM_MARGIN - wrapper_size.y
	) + hand_offset
	_layout_hand_slots()      # 14 个格子的位置/大小（改手牌参数时跟着重排）


# ── 询问窗口的「开始按钮」统一摆位 ────────────────────────────────────
# 用户口径：贴在「未副露手牌」的最右边，大小不变；副露变多 / 摸牌进出手牌时
# 跟着最右边那张走，不要压在牌上。
# （所有询问技能都是摸牌前或即时发动，所以不用给「刚摸到的那张」让位。）
# 空隙 / 平移 / 放大倍数都是可调参数，见上面「开始按钮微调」@export 组

# 「开始按钮」的矩形（**全局坐标**）：
#   高 = 手牌那张牌的高度（和手牌等高）、宽 = 高 ÷ 贴图宽高比（等比）
#   贴在未副露手牌最右边，上边缘和牌的上边缘对齐。
#   ★ 位置一律用 global_position 赋值：Main 这个 Control 带了 offset(39,-15)，
#     用局部 position 会把按钮带歪（以前「严重偏下」就是这么来的）。
var _pbr_frame := -1
var _pbr_memo := {}

func prompt_btn_rect(aspect: float) -> Rect2:
	# ★ 性能：每帧被「所有技能面板的开始按钮」各问一次（20+ 次），
	#   同一帧、同一宽高比的结果必然一样 → 一帧只真算一次。
	var _fr := Engine.get_process_frames()
	if _fr != _pbr_frame:
		_pbr_frame = _fr
		_pbr_memo.clear()
	elif _pbr_memo.has(aspect):
		return _pbr_memo[aspect]
	var vp := get_viewport_rect().size
	var slots := _hand_slots()
	var h := tile_size.y
	var row_left := 0.0
	var row_top := 0.0
	if not slots.is_empty() and (slots[0] as Control).is_inside_tree():
		var b0 := slots[0] as Control
		row_left = b0.global_position.x
		row_top = b0.global_position.y + HOVER_RAISE          # 牌的上边缘
		h = maxf(1.0, b0.size.y - HOVER_RAISE)                # 牌的实际高度
	elif hand_container != null and is_instance_valid(hand_container):
		row_left = hand_container.global_position.x
		row_top = hand_container.global_position.y + HOVER_RAISE
	var sz := Vector2(h / maxf(aspect, 0.05), h)
	# 手牌张数不该每次重排一遍 display_tiles()（14 张牌的数组复制 + 插入）
	var n := hand_tiles.size() + (1 if drawn_tile != "" else 0)
	var right := row_left + tile_size.x
	if n > 0:
		right = row_left + tile_x(n - 1) + tile_size.x         # 未副露手牌的最右边
	var x := right + prompt_btn_gap
	# 横着放不下 → 整体等比缩一点（窗口很窄时才会用到）
	var room_x := vp.x - x - 8.0
	if sz.x > room_x and sz.x > 0.0:
		sz = sz * clampf(room_x / sz.x, 0.2, 1.0)
	if x + sz.x > vp.x - 8.0:
		x = maxf(8.0, vp.x - sz.x - 8.0)
	var y := clampf(row_top, 8.0, maxf(8.0, vp.y - sz.y - 8.0))
	# ★ 这里只给「一开始的位置」：跳过态就用它，不再叠加任何偏移。
	#   确认态的偏移在 _sync_prompt_btns 里加（用户口径：跳过按钮保持原位）
	var _r := Rect2(Vector2(x, y), sz)
	_pbr_memo[aspect] = _r
	return _r


func prompt_btn_pos(bw: float, bh: float) -> Vector2:
	return prompt_btn_rect(bh / maxf(bw, 1.0)).position


# 手牌会变（摸牌 / 打牌 / 副露）：每帧把还开着的「开始按钮」尺寸和位置都贴回去
func _sync_prompt_btns() -> void:
	var btns := [oracle_start_btn, sw_start_btn, sw_hand_btn, c05_start_btn,
		c05_hide_btn, wind_start_btn, flow_start_btn,
		board_start_btn, c09_btn, c10_btn, c11_btn, c11s2_btn, sf_btn,
		zl_btn, dy_btn, pofa_btn, hs_btn, deal_skip_btn, gb_btn, yd_btn,
		c25_btn, future_ask_btn,
		]
	btns.append(c30_panel.start_btn)      # 向听：和其他面板同一个「开始按钮」
	btns.append(c32_panel.start_btn)      # 新手运（32-1）：交牌 / 换牌的确认按钮
	for b in btns:
		var btn := b as Control
		if btn == null or not is_instance_valid(btn) or not btn.visible:
			continue
		var tb := btn as TextureButton
		var aspect := 70.0 / 220.0                       # 贴图默认比例（220×70）
		if tb != null and tb.texture_normal != null and tb.texture_normal.get_width() > 0:
			aspect = float(tb.texture_normal.get_height()) / float(tb.texture_normal.get_width())
		# ★ 确认 / 跳过**同一位置、同一大小**（2026-10-31 换图后的口径：
		#   两张图都是 894x974，只换贴图、不缩放）；微调偏移对两种状态一起生效。
		var r := prompt_btn_rect(aspect)
		r.position += prompt_btn_offset
		if btn.size.distance_to(r.size) > 0.5:
			btn.size = r.size
		if btn.global_position.distance_to(r.position) > 0.5:
			btn.global_position = r.position


# 复制一张模板牌的形象（Node2D + Sprite2D）
func _make_tile_visual(tile_id: String, scale: float = 1.0) -> Node2D:
	if pai == null:
		return null
	var template := pai.get_node_or_null(tile_id) as Node2D
	if template == null:
		push_warning("main.gd: Pai 下找不到模板牌 " + tile_id)
		return null
	var vis: Node2D = template.duplicate()
	vis.visible = true
	var s := scale * hand_scale_ratio            # 手牌大小接口
	if s != 1.0:
		vis.scale = vis.scale * s
	# 牌面相对按钮居中：按钮高度 = 牌高 + 抬起高度，平时贴在下方
	vis.position = Vector2(tile_size.x * 0.5 * scale, tile_size.y * 0.5 * scale + HOVER_RAISE)
	return vis


# 手牌之间不留空隙；摸到的那张牌（及其右边的牌）整体让出一个空隙
func tile_x(index: int) -> float:
	var x := index * tile_size.x
	var slot := drawn_slot()
	if slot >= 0 and index >= slot:
		x += drawn_gap
	return x


# 手牌：14 个格子是场景节点（UI/Hand/格01…格14），每格下面有一个 Anim 层。
#   代码只做：给格子换牌的形象、显示/隐藏、把「摸到的那张」那一格留出空隙。
#   动效挂 Anim 层（代码永远不碰它）→ 换牌也不会把动画弄丢。
var _hand_slots_cache: Array = []     # 14 个格子（场景里固定）→ 缓存，别每帧重排
var _hand_slots_n := -1

func _hand_slots() -> Array:
	# ★ 性能：这函数每帧会被「悬停抬起 / 开始按钮摆位 / 手牌重画 / 吃碰面板」叫十几遍，
	#   每次都遍历子节点 + 字符串排序太浪费。只在子节点数量变了时才重建。
	var kids := hand_container.get_child_count() if hand_container != null else 0
	if kids == _hand_slots_n and not _hand_slots_cache.is_empty():
		return _hand_slots_cache
	_hand_slots_n = kids
	_hand_slots_cache = []
	if hand_container == null:
		return _hand_slots_cache
	var out: Array = []
	for c in hand_container.get_children():
		if String(c.name).begins_with("格"):
			out.append(c)
	if out.size() >= 2:
		out.sort_custom(func(a, b): return String(a.name) < String(b.name))
		_hand_slots_cache = out
	return _hand_slots_cache


# 认领格子：样式 + 信号只接一次（格子固定，不用每次重画都重接）
func _setup_hand_slots() -> void:
	var slots := _hand_slots()
	for i in range(slots.size()):
		var b := slots[i] as Button
		if b == null:
			continue
		b.flat = true
		b.focus_mode = Control.FOCUS_NONE
		b.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
		b.mouse_filter = Control.MOUSE_FILTER_IGNORE   # 交互动效由 TilePiece 自己处理
		for state in ["normal", "hover", "pressed", "focus", "disabled"]:
			b.add_theme_stylebox_override(state, StyleBoxEmpty.new())
		if not b.mouse_entered.is_connected(_on_tile_entered):
			b.mouse_entered.connect(_on_tile_entered.bind(i))
			b.mouse_exited.connect(_on_tile_exited.bind(i))
			b.pressed.connect(discard_tile.bind(i))


# 一格里的牌的形象（挂在 Anim 层下面）
func _hand_visual(index: int) -> Node2D:
	var slots := _hand_slots()
	if index < 0 or index >= slots.size():
		return null
	var anim := (slots[index] as Control).get_node_or_null("Anim")
	if anim == null:
		return null
	var kids := anim.get_children()
	return (kids[0] as Node2D) if kids.size() > 0 else null


# 把格子按当前参数排好（只在改手牌参数时走这里；平时位置归你）
# 最后一格永远留着「摸到的那张」的空隙（它空着时看不见，不碍事）
# 手牌/摸牌/窗口大小都没变 → 一个节点都不重建。
# ★ 以前每次 state 应用（0.35s 轮询、每次推送）都重排一遍手牌，
#   鼠标在牌上划、反复点人物卡时还会叠加重建 → 掉帧累积。
var _hand_layout_sig := ""

func _layout_hand_slots() -> void:
	var _vp := get_viewport().get_visible_rect().size if get_viewport() != null else Vector2.ZERO
	var _sig := "%s|%s|%d|%dx%d" % [str(hand_tiles), String(drawn_tile), int(my_seat),
		int(_vp.x), int(_vp.y)]
	if _sig == _hand_layout_sig:
		return
	_hand_layout_sig = _sig

	var slots := _hand_slots()
	if slots.is_empty():
		return
	var wrapper_size := Vector2(tile_size.x, tile_size.y + HOVER_RAISE)
	for i in range(slots.size()):
		var b := slots[i] as Control
		if b == null:
			continue
		b.custom_minimum_size = wrapper_size
		b.size = wrapper_size
		b.position = Vector2(tile_x(i), 0.0)


var _hand_view_sig := ""

func refresh_hand() -> void:
	# ★ 性能：每次 state 应用都会走这里，而它会把 14 个格子的 Anim 子节点全删了重造
	#   （duplicate 模板 + queue_free）。手牌内容、摸的那张、亮度依据、窗口尺寸都没变
	#   → 一个节点都不重建。（state 级去重之后，这里再兜一层「state 变了但手牌没变」。）
	var _picks: Array = hand_pick.picks if hand_pick != null else []
	var _legal = srv_state.get("legal", [])
	var _vk := get_viewport_rect().size if is_inside_tree() else Vector2.ZERO
	var _sig := "%s|%s|%d|%s|%d|%s|%dx%d" % [str(hand_tiles), String(drawn_tile),
		int(hand_pick.active) if hand_pick != null else 0, str(_picks.hash()),
		int(riichi_selecting),
		str((_legal as Array).hash()) if typeof(_legal) == TYPE_ARRAY else "-",
		int(_vk.x), int(_vk.y)]
	if _sig == _hand_view_sig and hand_container != null:
		return
	_hand_view_sig = _sig
	hovered_index = -1
	_layout_hand_area()
	var slots := _hand_slots()
	if slots.is_empty():
		_build_hand_legacy()          # 没有预置格子 → 老办法
		return
	var tiles := display_tiles()
	# ★ 性能（关键）：现在视觉由 TileBank 实体画，`_apply_entity_states` 末尾还会把这里
	#   的残留再删一遍。所以 LEGACY=false 时**不再**给每格 duplicate 模板牌 ——
	#   以前每份 state 都要造 14 个节点、紧接着又被删掉，纯白干 + queue_free 抖动。
	#   格子只保留「接点击 / 显隐 / 排位」这三件事。
	var _ent = srv_state.get("tiles", [])
	var _ent_ok := tile_bank != null and typeof(_ent) == TYPE_ARRAY and not (_ent as Array).is_empty()
	if not LEGACY_TILE_RENDER and _ent_ok:
		for i in range(slots.size()):
			var slot := slots[i] as Button
			if slot == null:
				continue
			var anim0 := slot.get_node_or_null("Anim")
			if anim0 != null and anim0.get_child_count() > 0:
				for c in anim0.get_children():      # 万一有老残留，清一次
					anim0.remove_child(c)
					c.queue_free()
			slot.visible = i < tiles.size()
		update_tile_positions()
		return
	for i in range(slots.size()):
		var b := slots[i] as Button
		if b == null:
			continue
		var anim := b.get_node_or_null("Anim")
		if anim == null:
			continue
		for c in anim.get_children():           # 先把旧的形象清掉
			anim.remove_child(c)
			c.queue_free()
		if i >= tiles.size():
			b.visible = false
			continue
		b.visible = true
		var vis := _make_tile_visual(tiles[i])
		if vis != null:
			# 亮度只归 hand_pick 管：选牌时全暗、选中的亮；没在选牌就按立直规则
			if hand_pick.active:
				if not hand_pick.has(i):
					vis.modulate = Color(0.5, 0.5, 0.5, 1.0)
			elif riichi_selecting and not srv_can_riichi_with(String(tiles[i])):
				vis.modulate = Color(0.5, 0.5, 0.5, 1.0)
			elif not srv_can_discard_with(String(tiles[i])):
				vis.modulate = Color(0.5, 0.5, 0.5, 1.0)     # 决斗/立直不许打的牌变暗
			anim.add_child(vis)
	update_tile_positions()


# 老办法：现场新建 Button 当格子（只在没有预置格子时用）
func _build_hand_legacy() -> void:
	if hand_container == null:
		return
	for child in hand_container.get_children():
		hand_container.remove_child(child)
		child.queue_free()
	tile_wrappers.clear()
	var tiles := display_tiles()
	var wrapper_size := Vector2(tile_size.x, tile_size.y + HOVER_RAISE)
	for i in range(tiles.size()):
		var wrapper := Button.new()
		wrapper.flat = true
		wrapper.focus_mode = Control.FOCUS_NONE
		wrapper.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
		wrapper.custom_minimum_size = wrapper_size
		wrapper.size = wrapper_size
		wrapper.position = Vector2(tile_x(i), 0)
		var empty := StyleBoxEmpty.new()
		for state in ["normal", "hover", "pressed", "focus", "disabled"]:
			wrapper.add_theme_stylebox_override(state, empty)
		var vis := _make_tile_visual(tiles[i])
		if vis != null:
			# 亮度只归 hand_pick 管：选牌时全暗、选中的亮；没在选牌就按立直规则
			if hand_pick.active:
				if not hand_pick.has(i):
					vis.modulate = Color(0.5, 0.5, 0.5, 1.0)
			elif riichi_selecting and not srv_can_riichi_with(String(tiles[i])):
				vis.modulate = Color(0.5, 0.5, 0.5, 1.0)
			elif not srv_can_discard_with(String(tiles[i])):
				vis.modulate = Color(0.5, 0.5, 0.5, 1.0)     # 决斗/立直不许打的牌变暗
			wrapper.add_child(vis)
		wrapper.mouse_entered.connect(_on_tile_entered.bind(i))
		wrapper.mouse_exited.connect(_on_tile_exited.bind(i))
		wrapper.pressed.connect(discard_tile.bind(i))
		hand_container.add_child(wrapper)
		tile_wrappers.append(wrapper)
	update_tile_positions()



func _on_tile_entered(index: int) -> void:
	hovered_index = index
	update_tile_positions()


func _on_tile_exited(index: int) -> void:
	if hovered_index == index:
		hovered_index = -1
	update_tile_positions()


# 悬停时只抬起牌的形象，按钮本身不动 —— 避免鼠标划出按钮导致抖动
func update_tile_positions() -> void:
	var slots := _hand_slots()
	if slots.is_empty():                       # 老办法（现场新建的格子）
		for i in range(tile_wrappers.size()):
			var vis0 := tile_wrappers[i].get_child(0) as Node2D
			if vis0 != null:
				var lift0 := 0.0 if i == hovered_index else HOVER_RAISE
				vis0.position = Vector2(tile_size.x * 0.5, tile_size.y * 0.5 + lift0)
			tile_wrappers[i].z_index = 1 if i == hovered_index else 0
		return
	for i in range(slots.size()):
		var vis := _hand_visual(i)
		if vis != null:
			var lift := 0.0 if i == hovered_index else HOVER_RAISE
			vis.position = Vector2(tile_size.x * 0.5, tile_size.y * 0.5 + lift)
		(slots[i] as Control).z_index = 1 if i == hovered_index else 0


# ────────────────────────── 打出的牌（风盘下方牌河） ──────────────────────────

# 风盘的「大小 / 位置 / 朝向」接口：在场景里的基准上乘缩放、加位移、按庄家转朝向，然后重排牌河
func _apply_fengpan() -> void:
	if not fengpan_ready or fengpan == null:
		return
	# 8 张风盘图都是「整块 1920×1080、盘面就画在图里的固定位置」，
	# 所以这里只做整体缩放 / 平移，不动任何子节点（Label / 叶子跟着一起走，比例天然一致）。
	fengpan.scale = fengpan_base_scale * fengpan_scale_ratio
	fengpan.position = fengpan_base_pos + fengpan_offset
	fengpan.rotation_degrees = 0.0
	if fengpan_center_on_ring:
		_fengpan_align_to_ring()
	_fengpan_img_cur = ""             # 风盘刚被重排/重建过 → 强制下一帧重贴一次图
	_update_fengpan_image()
	refresh_discards()


# 牌河四家「格01」的平均点 = 牌河环的中心（四家对称，平均就是中心）。
func _fengpan_ring_center() -> Vector2:
	var acc := Vector2.ZERO
	var n := 0
	for who in ["我", "D", "C", "B"]:
		var cell := get_node_or_null("UI/Pile/%s/格01" % who) as Node2D
		if cell == null:
			continue
		acc += cell.global_position
		n += 1
	if n == 0:
		return Vector2.ZERO
	return acc / float(n)


# 盘面中心的世界坐标（按可见风盘图的实际变换算）
func _fengpan_body_center_global() -> Vector2:
	var sp := _fengpan_wind_sprite()
	if sp == null:
		return Vector2.ZERO
	var rec := sp.get_rect()
	var c: Vector2 = rec.position + FENGPAN_TEX_RECT.position + FENGPAN_TEX_RECT.size * 0.5
	return sp.get_global_transform() * c


# 把「盘面中心」挪到牌河环中心。
# ★ 为什么需要：风盘图里盘面不是画在 1920×1080 的正中（偏右 ~28、偏上 ~13），
#   直接按图片中心摆，进游戏看就整体偏右一大截（2026-10-30 报）。
func _fengpan_align_to_ring() -> void:
	if fengpan == null or not fengpan_ready:
		return
	var target := _fengpan_ring_center()
	if target == Vector2.ZERO:
		return
	var body_c := _fengpan_body_center_global()
	if body_c == Vector2.ZERO:
		return
	var dlt := target - body_c
	var par := fengpan.get_parent() as Node2D
	if par != null:
		dlt = par.global_transform.basis_xform_inv(dlt)   # 转成父节点（UI）的局部方向
	fengpan.position += dlt


# 该显示哪张风盘图：场风（东/南）+ 自家风（东/南/西/北）
func _fengpan_img_name() -> String:
	var rw := int(WIND_IDX.get(String(srv_state.get("wind", "dong")), 0))
	var dealer := int(srv_state.get("dealer", 0))
	var mw := (my_seat - dealer + 4) % 4
	var pre: String = FENGPAN_IMG_PRE[0] if rw <= 0 else FENGPAN_IMG_PRE[1]
	return pre + String(FENGPAN_IMG_SUF[clampi(mw, 0, 3)])


var _fengpan_img_cur := ""

# 风盘蓝框在图里是 981×862（不是正方形）→ 牌河纵向会挤。
# 这里把 8 张风盘图的 Y 拉成正方形（Sprite2D 居中缩放），再贴回环心，位置不变。
const FENGPAN_SQUARE_K := 1.0             # 用户口径 2026-11-02：不拉伸风盘（1.0 = 保持原图）
const FENGPAN_TEX_MID_Y := 540.0            # 风盘图 1920x1080 的一半高（Sprite2D 原点在图心）


# 盘面（FENGPAN_TEX_RECT）在 sprite 空间里的中心 y（现在约 -13）
func _fengpan_art_center_y() -> float:
	return (FENGPAN_TEX_RECT.position.y + FENGPAN_TEX_RECT.size.y * 0.5) - FENGPAN_TEX_MID_Y


# 拉伸之后，画在盘面上的东西要按同一比例跟着走，否则相对盘面会跑偏：
#   · 本场计数器（Huaban 叶子）  · 四家点数 Label
#   y' = cy + (y - cy) * k     —— cy = 盘面中心，k = 拉伸倍数
# 盘面上下沿在拉伸后的位移（风盘本地单位）：[上沿(负), 下沿(正)]
func _fengpan_edge_shift(k: float) -> Array:
	var cy := _fengpan_art_center_y()
	var half := FENGPAN_TEX_RECT.size.y * 0.5
	return [(cy - half) * (k - 1.0), (cy + half) * (k - 1.0)]


func _fengpan_follow_hud(k: float) -> void:
	if fengpan == null or not is_instance_valid(fengpan):
		return
	var cy := _fengpan_art_center_y()
	var sh := _fengpan_edge_shift(k)
	var d_top := float(sh[0])
	var d_bot := float(sh[1])
	for c in fengpan.get_children():
		var n := c as Node2D
		if n == null:
			continue
		if n is Sprite2D and _fengpan_is_wind_img(String((n as Sprite2D).name)):
			continue                       # 风盘图自己已经缩过了
		if bool(n.get_meta("fengpan_hud_done", false)):
			continue
		var ny := cy + (n.position.y - cy) * k        # 默认：跟盘面同比例
		if c is Control:
			# 四家点数：**贴着上下沿**的那两个必须跟着沿走。
			# （按比例缩放只走 42px，实际沿走了 58px → 差 16px，看着就是「歪」）
			var ctrl := c as Control
			var rr := fmod(absf(ctrl.rotation), PI)
			var sideways := absf(rr - PI * 0.5) < 0.2  # 左右两家 ±90°，不贴上下沿
			if not sideways:
				ny = n.position.y + (d_bot if n.position.y >= cy else d_top)
		n.position = Vector2(n.position.x, ny)
		n.set_meta("fengpan_hud_done", true)


func _fengpan_make_square() -> void:
	if fengpan == null or not is_instance_valid(fengpan):
		return
	var changed := false
	for c in fengpan.get_children():
		if not (c is Sprite2D):
			continue
		var sp := c as Sprite2D
		if not _fengpan_is_wind_img(String(sp.name)):
			continue
		if bool(sp.get_meta("fengpan_sq", false)):
			continue
		sp.scale = Vector2(sp.scale.x, sp.scale.y * FENGPAN_SQUARE_K)
		sp.set_meta("fengpan_sq", true)
		changed = true
	if changed:
		_fengpan_follow_hud(FENGPAN_SQUARE_K)   # 计数器 / 点数跟着盘面一起走
		_fengpan_align_to_ring()                # 缩放后仍以牌山环心为准


func _update_fengpan_image() -> void:
	if fengpan == null:
		return
	var want := _fengpan_img_name()
	if want == _fengpan_img_cur and is_instance_valid(fengpan):
		return              # 已经显示这张 → 不用每次 state 都把 8 个子 Sprite 摸一遍
	_fengpan_img_cur = want
	for c in fengpan.get_children():
		if not (c is Sprite2D):
			continue
		var sp := c as Sprite2D
		if _fengpan_is_wind_img(String(sp.name)):
			sp.visible = String(sp.name) == want
	_fengpan_make_square()


# 本场叶子（5 片，从左到右排好序）
func _fengpan_leaves() -> Array:
	var out: Array = []
	if fengpan == null:
		return out
	for c in fengpan.get_children():
		if c is Sprite2D and String(c.name).begins_with(FENGPAN_LEAF_PREFIX):
			out.append(c)
	out.sort_custom(func(a, b): return (a as Node2D).position.x < (b as Node2D).position.x)
	return out


# 本场数 → 亮几片叶子：
#   1~5 本场：从左往右依次点亮；第 6 本场只亮最右一片，之后从右往左，满了再从左边来，往复。
func _fengpan_leaf_sync(honba: int) -> void:
	var leaves := _fengpan_leaves()
	var n := leaves.size()
	if n == 0:
		return
	for i in range(n):
		(leaves[i] as Sprite2D).visible = false
	var h := maxi(honba, 0)
	if h <= 0:
		return
	var phase := (h - 1) % (2 * n)          # 0..2n-1
	var from_right := phase >= n
	var cnt := (phase - n + 1) if from_right else (phase + 1)
	for i in range(mini(cnt, n)):
		var idx := (n - 1 - i) if from_right else i
		(leaves[idx] as Sprite2D).visible = true

const WIND_CN4 := ["東", "南", "西", "北"]
const WIND_IDX := {"dong": 0, "nan": 1, "xi": 2, "bei": 3}


func _fengpan_tex_size() -> Vector2:
	if fengpan != null:
		for c in fengpan.get_children():
			if c is Sprite2D and (c as Sprite2D).texture != null:
				return (c as Sprite2D).texture.get_size()
	return FENGPAN_TEX_SIZE


# 整张图中心 → 牌盘本体中心 的偏移（子 Sprite2D 的 offset 用它）
func _fengpan_body_offset() -> Vector2:
	var body := fengpan_body_size_in_tex()
	var center := FENGPAN_TEX_RECT.position * _fengpan_tex_k() + body * 0.5
	return _fengpan_tex_size() * 0.5 - center


func _fengpan_tex_k() -> float:
	return _fengpan_tex_size().x / FENGPAN_TEX_SIZE.x


# 牌盘本体（那块蓝框）在图里的尺寸
func fengpan_body_size_in_tex() -> Vector2:
	return FENGPAN_TEX_RECT.size * _fengpan_tex_k()


# 庄家摆在我屏幕的哪一面：0 下方 / 1 右侧 / 2 上方 / 3 左侧
# （屏幕位置是固定的：0 号位在下方、1 号位在右侧…… 我坐几号位只影响「谁在我哪一面」）
func _dealer_side() -> int:
	return (int(srv_state.get("dealer", 0)) - my_seat + 4) % 4


# 牌盘本体在屏幕上的矩形（牌河围着它摆）。
# ★ sprite 的基准点已经被挪到本体中心（见 _apply_fengpan），所以正中心就是 fengpan.position；
#   而且这里故意用「没转过」的本体尺寸 —— 风盘转 90° 的时候牌河不会跟着跳。
func fengpan_effective_rect() -> Rect2:
	return _fengpan_body_rect()


# 牌 ID -> fPai 下的模板节点名（扁平风格命名：f1m / f0mn / f1z …）
func fpai_node_name(tile_id: String) -> String:
	var h = ["dong", "nan", "xi", "bei", "bai", "fa", "zhong"].find(tile_id)
	if h >= 0:
		return "f%dz" % (h + 1)
	if tile_id.begins_with("0"):
		return "f0" + tile_id.substr(1) + "n"
	return "f" + tile_id


# 牌河：从风盘下端最左端开始铺，每排 6 张；5 张牌宽 + 1 张牌长 = 风盘宽 × DISCARD_SPAN_RATIO
func refresh_discards() -> void:
	if not LEGACY_TILE_RENDER:
		return                     # 牌河现在由 TileBank 实体画（能挂动画）
	if fpai == null:
		return
	var rect := fengpan_effective_rect()
	if rect.size.x <= 0.0:
		return
	# 我的牌河：贴着风盘下边缘、向左对齐、往下成排
	_render_discard_pile(discard_container, discard_pile, discard_rotated, "me")
	# 三家的牌河：与风盘蓝框边缘对齐（B 左 / C 上 / D 右），牌面分别转 90/180/270°
	for who in OPP_ORDER:
		var cont = opp_discard_containers.get(who, null)
		if cont == null:
			continue
		_render_discard_pile(cont, opp_discards.get(who, []), [], who)


# 一张牌在牌河里的位置与旋转：side = "me" / "B" / "C" / "D"
func discard_slot(side: String, rect: Rect2, slot: Vector2, col: int, row: int, used: float, w: float) -> Vector3:
	# ★ 间距一律按**牌的尺寸**算（以前 B/D 用 rect.size.y/6）：
	#   风盘蓝框是 981×862 不是正方形 → rect.h/6=143.7 < 牌短边 159.7 → 每张重叠 16px。
	var pitch_x := slot.x * DISCARD_GAP          # 牌短边 + 2% 缝
	var pitch_y := slot.y * DISCARD_GAP          # 牌长边 + 2% 缝（换排时才用）
	# 一排 6 张牌的总宽（盘面下/上边比它长 → 居中摆，不再贴左/右）
	var row_len := float(DISCARDS_PER_ROW) * pitch_x
	var row_x0 := rect.position.x + rect.size.x * 0.5 - row_len * 0.5
	match side:
		"B":    # 贴风盘左缘，牌向下排，再一排往左挪
			return Vector3(rect.position.x - (row + 0.5) * pitch_y, rect.position.y + (col + 0.5) * pitch_x, OPP_DISCARD_ROTATION["B"])
		"C":    # 贴风盘上缘，180°（居中）
			return Vector3(row_x0 + row_len - (col + 0.5) * pitch_x, rect.position.y - (row + 0.5) * pitch_y, OPP_DISCARD_ROTATION["C"])
		"D":    # 贴风盘右缘，牌向上排，再一排往右挪
			return Vector3(rect.position.x + rect.size.x + (row + 0.5) * pitch_y, rect.position.y + rect.size.y - (col + 0.5) * pitch_x, OPP_DISCARD_ROTATION["D"])
	# 我：贴风盘下缘，牌向右排（居中）
	return Vector3(row_x0 + used * DISCARD_GAP + w * 0.5, rect.position.y + rect.size.y + (row + 0.5) * pitch_y, 0.0)


# 画一个牌河。两种走法：
#   ① 场景里预置了格子（UI/Pile/<谁>/格01…）→ 用那些节点（★ 每个格子都能挂动效）
#   ② 没有（节点被删了）→ 退回老办法：临场复制 fPai 模板、用完就删
# 每条牌河上一次画的内容指纹（内容+风盘矩形+朝向）→ 没变就一个节点都不碰
var _pile_sig := {}

func _render_discard_pile(container: Node2D, pile: Array, rotated_flags: Array, side: String) -> void:
	if container == null or fpai == null:
		return
	var _r0 := fengpan_effective_rect()
	var _sig := "%s|%s|%.1f,%.1f,%.1f,%.1f|%s" % [side, str(pile), _r0.position.x,
		_r0.position.y, _r0.size.x, _r0.size.y, str(rotated_flags)]
	if String(_pile_sig.get(side, "")) == _sig:
		return                                   # 这条牌河没变化 → 不重画（不重建节点）
	_pile_sig[side] = _sig
	var rect := fengpan_effective_rect()
	if rect.size.x <= 0.0:
		return
	var slot := discard_slot_size(rect.size.x, rect.size.y)
	var slots := _pile_slots(container)
	if slots.is_empty():
		_legacy_render_discard_pile(container, pile, rotated_flags, side, rect, slot)
		return
	# 先把这一家的格子全藏起来，再按牌数逐个摆出来
	for s in slots:
		(s as Node2D).visible = false
	var row_x := {}                          # 我的牌河里每排已占用的宽度（横置牌会撑宽那排）
	for i in range(pile.size()):
		if i >= slots.size():
			break
		var rotated: bool = side == "me" and i < rotated_flags.size() and rotated_flags[i]
		var node_name := hpai_node_name(pile[i]) if rotated else fpai_node_name(pile[i])
		var tpl := fpai.get_node_or_null(node_name) as Node2D
		if tpl == null:
			push_warning("main.gd: fPai 下找不到 " + node_name)
			continue
		var tpl_spr := tpl.get_node_or_null("Sprite2D") as Sprite2D
		if tpl_spr == null or tpl_spr.texture == null:
			continue
		var vis: Node2D = slots[i]
		var spr := vis.get_node_or_null("Anim/Sprite2D") as Sprite2D
		if spr == null:
			spr = vis.get_node_or_null("Sprite2D") as Sprite2D     # 兼容没有 Anim 层的旧结构
		if spr == null:
			continue
		spr.texture = tpl_spr.texture
		spr.centered = true
		spr.position = Vector2.ZERO
		var tex := tpl_spr.texture.get_size()
		var col := i % DISCARDS_PER_ROW
		var row := floori(i / float(DISCARDS_PER_ROW))
		# 横置牌用横版图：占位 = 自己的长边；普通牌 = 格子宽度
		var w := slot.y if rotated else slot.x
		spr.scale = Vector2.ONE * (w / maxf(tex.x, 1.0))
		var used: float = row_x.get(row, 0.0)
		var info := discard_slot(side, rect, slot, col, row, used, w)
		spr.rotation_degrees = info.z
		vis.position = Vector2(info.x, info.y)
		vis.visible = true
		row_x[row] = used + w


# 牌河里预置的格子（按名字排序：格01…格24）；少于 2 个就当作「没有」
var _pile_slots_cache := {}          # container -> Array（格子在场景里固定，缓存住）

func _pile_slots(container: Node2D) -> Array:
	# ★ 性能：每份 state 都要为「我 + 三家」各调一次，里面遍历子节点再排序太浪费。
	if container == null:
		return []
	var kids := container.get_child_count()
	var key := container.get_instance_id()
	var hit = _pile_slots_cache.get(key, null)
	if hit is Dictionary and int((hit as Dictionary).get("n", -1)) == kids:
		return (hit as Dictionary).get("arr", [])
	var out: Array = []
	for c in container.get_children():
		if String(c.name).begins_with("格"):
			out.append(c)
	if out.size() >= 2:
		out.sort_custom(func(a, b): return String(a.name) < String(b.name))
	else:
		out = []
	_pile_slots_cache[key] = {"n": kids, "arr": out}
	return out


# 老办法：临场复制 fPai 模板画出牌河（预置格子不可用时才走这里）
func _legacy_render_discard_pile(container: Node2D, pile: Array, rotated_flags: Array,
		side: String, rect: Rect2, slot: Vector2) -> void:
	for c in container.get_children():
		container.remove_child(c)
		c.queue_free()
	var row_x := {}
	for i in range(pile.size()):
		var rotated: bool = side == "me" and i < rotated_flags.size() and rotated_flags[i]
		var node_name := hpai_node_name(pile[i]) if rotated else fpai_node_name(pile[i])
		var tpl := fpai.get_node_or_null(node_name) as Node2D
		if tpl == null:
			push_warning("main.gd: fPai 下找不到 " + node_name)
			continue
		var vis: Node2D = tpl.duplicate()
		vis.visible = true
		var spr := vis.get_node_or_null("Sprite2D") as Sprite2D
		if spr == null or spr.texture == null:
			continue
		var tex := spr.texture.get_size()
		var col := i % DISCARDS_PER_ROW
		var row := floori(i / float(DISCARDS_PER_ROW))
		var w := slot.y if rotated else slot.x
		spr.scale = Vector2.ONE * (w / (tex.x * vis.scale.x))
		var used: float = row_x.get(row, 0.0)
		var info := discard_slot(side, rect, slot, col, row, used, w)
		spr.rotation_degrees = info.z
		vis.position = Vector2(info.x, info.y)
		row_x[row] = used + w
		container.add_child(vis)


# 牌河格子的尺寸：牌宽 = 风盘宽 × DISCARD_SPAN_RATIO ÷ (5 + 长宽比)，长宽比取扁平牌面
func discard_slot_size(board_w: float, board_h: float = 0.0) -> Vector2:
	# 用户口径 2026-11-02：牌的大小以风盘的**短边**（竖着那两条，较短）为基准 ——
	#   一排 6 张正好落在短边长度内（含 2% 缝），四个方向都不会重叠。
	var aspect := 360.0 / 271.0
	if fpai != null:
		var ref := fpai.get_node_or_null("f1m/Sprite2D") as Sprite2D
		if ref != null and ref.texture != null:
			aspect = ref.texture.get_size().y / ref.texture.get_size().x
	var base := board_w
	if board_h > 1.0:
		base = minf(board_w, board_h)          # 短边
	var w := base / float(DISCARDS_PER_ROW) / DISCARD_GAP
	return Vector2(w, w * aspect)


# 牌 ID -> 横版模板节点名（横 horizontal 命名：h1m / h0m / h1z …）
func hpai_node_name(tile_id: String) -> String:
	var h = ["dong", "nan", "xi", "bei", "bai", "fa", "zhong"].find(tile_id)
	if h >= 0:
		return "h%dz" % (h + 1)
	return "h" + tile_id


# ────────────────────────── 日麻 听牌 / 和牌 判定 ──────────────────────────

# 牌 ID -> 0..33（赤宝牌 0m/0s/0p 按普通 5 算）
func kind_of(tile_id: String) -> int:
	if tile_id.begins_with("0"):
		tile_id = "5" + tile_id.substr(1)
	return kind_index.get(tile_id, -1)


# 手牌 -> 每种牌的张数（34 个）
func tiles_to_counts(ids: Array) -> Array[int]:
	var counts: Array[int] = []
	counts.resize(34)
	counts.fill(0)
	for id in ids:
		var k := kind_of(id)
		if k >= 0:
			counts[k] += 1
	return counts


# 是否和牌：暗牌 ids + 已有 melds 组副露（每组算 1 个面子）
func is_winning_hand(ids: Array, melds: int = 0) -> bool:
	return is_winning_counts(tiles_to_counts(ids), melds)


func is_winning_counts(counts: Array[int], melds: int = 0) -> bool:
	var total := 0
	for n in counts:
		total += n
	if total + 3 * melds != 14:
		return false
	if melds == 0:                                   # 七对子 / 国士必须门清
		if is_kokushi(counts):
			return true
		if is_chiitoitsu(counts):
			return true
	for i in range(34):
		if counts[i] >= 2:
			counts[i] -= 2                       # 拆出雀头
			var ok := can_form_melds(counts)
			counts[i] += 2
			if ok:
				return true
	return false


# 剩下的牌能否刚好拆成若干个面子（刻子 / 顺子）
func can_form_melds(counts: Array[int]) -> bool:
	var i := 0
	while i < 34 and counts[i] == 0:
		i += 1
	if i == 34:
		return true
	if counts[i] >= 3:                           # 刻子
		counts[i] -= 3
		var trip := can_form_melds(counts)
		counts[i] += 3
		if trip:
			return true
	if i < 27 and (i % 9) <= 6 and counts[i + 1] > 0 and counts[i + 2] > 0:   # 顺子（同花色内）
		counts[i] -= 1
		counts[i + 1] -= 1
		counts[i + 2] -= 1
		var run := can_form_melds(counts)
		counts[i] += 1
		counts[i + 1] += 1
		counts[i + 2] += 1
		if run:
			return true
	return false


# 七对子（7 个不同的对子）
func is_chiitoitsu(counts: Array[int]) -> bool:
	var pairs := 0
	for i in range(34):
		if counts[i] == 0:
			continue
		if counts[i] != 2:
			return false
		pairs += 1
	return pairs == 7


# 国士无双（13 种幺九牌各一 + 其中一种再来一张）
func is_kokushi(counts: Array[int]) -> bool:
	var pairs := 0
	for i in range(34):
		if ORPHAN_KINDS.has(i):
			if counts[i] == 0 or counts[i] > 2:
				return false
			if counts[i] == 2:
				pairs += 1
		elif counts[i] > 0:
			return false
	return pairs == 1


# 13 张是否听牌（34 种牌里随便来一张都能和）
func is_tenpai(ids: Array, melds: int = 0) -> bool:
	var counts := tiles_to_counts(ids)
	var total := 0
	for n in counts:
		total += n
	if total + 3 * melds != 13:
		return false
	for k in range(34):
		if counts[k] >= 4:
			continue                             # 4 张都在自己手上，不可能再摸到
		counts[k] += 1
		var ok := is_winning_counts(counts, melds)
		counts[k] -= 1
		if ok:
			return true
	return false


# 把 14 张里的第 index 张切出后，剩下的 13 张是否仍听牌
func keeps_tenpai(ids: Array, index: int, melds: int = 0) -> bool:
	var rest := ids.duplicate()
	rest.remove_at(index)
	return is_tenpai(rest, melds)


# 有没有「切出后仍听牌」的牌（= 可以立直）
func can_declare_riichi(ids: Array, melds: int = 0) -> bool:
	for i in range(ids.size()):
		if keeps_tenpai(ids, i, melds):
			return true
	return false


# ────────────────────────── 立直 / 和牌 流程 ──────────────────────────

# ────────────────────────── 立直棒（图片 · 2 秒淡入）──────────────────────────
# 四根立直棒 = 风盘四条边中点上摆好的 4 个 Sprite2D（用户 2026-11-02 摆的）：
#   下 = 自己 / 右 = 下家(D) / 上 = 对家(C) / 左 = 上家(B)
# 谁立直，谁门前那根就在 **2 秒**内从全透明淡到不透明。
#
# ★ 位置/缩放/旋转一律照抄那 4 个节点（取它们的 global_transform），一个像素都不改。
# ★ 但主牌桌在 CanvasLayer 0、人物卡在 CanvasLayer 20 —— 直接把风盘下那几个节点点亮
#   会被人物卡整块盖住（2026-11-02 实测：截图里什么都看不到）。
#   所以在 layer=21 上放一个「镜像 Sprite2D」来显示：贴图和全局变换每次都从原节点抄，
#   视觉位置和风盘的关系完全一致，只是画在人物卡上面。
const LIZHI_STICK_FADE := 2.0            # 立直后淡入用时（秒）
const LIZHI_STICK_SPREAD := false        # true = 按 1/风盘缩放把四根摊开（位置会偏，默认关）
const LIZHI_STICK_NODES := {
	"me": "UI/风盘/Huaban5659731464",    # 屏幕下方 = 自己
	"D": "UI/风盘/Huaban5659731463",     # 屏幕右侧 = 下家
	"C": "UI/风盘/Huaban5659731462",     # 屏幕上方 = 对家
	"B": "UI/风盘/Huaban5659731461",     # 屏幕左侧 = 上家
}
var lizhi_stick_on := {}                 # who -> 现在该不该显示
var lizhi_stick_tw := {}                 # who -> Tween（淡入中）
var lizhi_stick_ready := false           # 第一次同步时先把四根全部收起来
var lizhi_stick_layer: CanvasLayer = null
var lizhi_stick_mirrors := {}            # who -> Sprite2D（真正显示的那个）


func _lizhi_stick_anchor(who: String) -> Sprite2D:
	return get_node_or_null(String(LIZHI_STICK_NODES.get(who, ""))) as Sprite2D


func _lizhi_stick_layer_get() -> CanvasLayer:
	if lizhi_stick_layer != null and is_instance_valid(lizhi_stick_layer):
		return lizhi_stick_layer
	lizhi_stick_layer = CanvasLayer.new()
	lizhi_stick_layer.name = "LizhiStickLayer"
	lizhi_stick_layer.layer = 21      # 人物卡在 20；别压过 30 / 31 / 32 的播报与结算
	add_child(lizhi_stick_layer)
	return lizhi_stick_layer


# 显示用的镜像节点：贴图 + 全局变换都跟场景里那 4 个节点走
func _lizhi_stick_node(who: String) -> Sprite2D:
	var anchor := _lizhi_stick_anchor(who)
	if anchor == null:
		return null
	var m = lizhi_stick_mirrors.get(who, null)
	if m != null and is_instance_valid(m):
		_lizhi_stick_apply(m, anchor)
		return m
	var mir := Sprite2D.new()
	mir.name = "LizhiStick_" + who
	mir.texture = anchor.texture
	mir.centered = anchor.centered
	mir.offset = anchor.offset
	mir.flip_h = anchor.flip_h
	mir.flip_v = anchor.flip_v
	mir.visible = false
	lizhi_stick_mirrors[who] = mir
	_lizhi_stick_layer_get().add_child(mir)
	_lizhi_stick_apply(mir, anchor)
	anchor.visible = false                 # 原节点只当位置标尺，不再直接显示
	return mir


# 贴图 / 朝向 / 大小照抄锚点；位置按「相对风盘中心的偏移」反补偿风盘缩放。
# 风盘 scale=0.3388 时，锚点 position(±260) 在屏幕上只有 ±88px —— 四根会叠在一起。
func _lizhi_stick_apply(mir: Sprite2D, anchor: Sprite2D) -> void:
	mir.texture = anchor.texture
	mir.centered = anchor.centered
	mir.offset = anchor.offset
	mir.flip_h = anchor.flip_h
	mir.flip_v = anchor.flip_v
	var gxf := anchor.get_global_transform()
	if LIZHI_STICK_SPREAD and fengpan != null and is_instance_valid(fengpan):
		var fsc := maxf(fengpan.global_scale.x, 0.01)
		var center: Vector2 = fengpan.global_position
		var origin: Vector2 = center + (gxf.origin - center) / fsc
		mir.global_transform = Transform2D(gxf.get_rotation(), gxf.get_scale(), 0.0, origin)
	else:
		mir.global_transform = gxf


func _lizhi_stick_show(who: String) -> void:
	var n := _lizhi_stick_node(who)
	if n == null:
		return
	n.visible = true
	n.modulate.a = 0.0
	var tw := create_tween()
	tw.tween_property(n, "modulate:a", 1.0, LIZHI_STICK_FADE) \
		.set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_OUT)
	lizhi_stick_tw[who] = tw


func _lizhi_stick_hide(who: String) -> void:
	var tw = lizhi_stick_tw.get(who, null)
	if tw != null and tw.is_valid():
		tw.kill()
	lizhi_stick_tw.erase(who)
	var n := _lizhi_stick_node(who)
	if n != null:
		n.visible = false
		n.modulate.a = 1.0               # 复位：下次淡入再从 0 开始


func _lizhi_stick_hide_all() -> void:
	for w in LIZHI_STICK_NODES.keys():
		lizhi_stick_on[w] = false
		_lizhi_stick_hide(String(w))


# 跟着服务端状态走：riichi 列表里有谁，谁门前那根就淡入；没有就收起。
func _lizhi_stick_sync(st: Dictionary) -> void:
	var want := {}
	var rr = st.get("riichi")
	if typeof(rr) == TYPE_ARRAY:
		for s in (rr as Array):
			var w := who_of_seat(int(s))
			if w != "":
				want[w] = true
	for w in LIZHI_STICK_NODES.keys():
		var on := want.has(w)
		if lizhi_stick_ready and bool(lizhi_stick_on.get(w, false)) == on:
			# 状态没变，但风盘可能被缩放/挪动过（窗口尺寸变化）→ 顺手重新对齐位置
			if on:
				_lizhi_stick_node(String(w))
			continue
		lizhi_stick_on[w] = on
		if on:
			_lizhi_stick_show(String(w))
		else:
			_lizhi_stick_hide(String(w))
	lizhi_stick_ready = true


# 每次摸牌后判定：先看是否和牌，再按立直状态处理
func _after_draw() -> void:
	if game_over or game_phase == PHASE_DEAL:
		return
	var tiles := display_tiles()
	# ① 摸到的这张能不能和 —— 问服务端（连不上才用本地兜底）
	var report := srv_tenpai()
	if not report.is_empty():
		var detail: Dictionary = report.get("detail", {})
		var one = detail.get(drawn_tile, null)
		var w = one.get("tsumo", null) if typeof(one) == TYPE_DICTIONARY else null
		if typeof(w) == TYPE_DICTIONARY:
			show_hupai(w)
			return
	elif is_winning_hand(tiles, meld_count):          # 服务端连不上 → 本地兜底
		show_hupai({})
		return
	riichi_selecting = false
	# ② 立直按钮不在这里弹：交给 srv_layout_buttons() 按服务端 legal 摆。
	#   以前用「听不听」判断（不看振听）→ 会弹出一个服务端其实不允许的立直按钮。


# ── 国标（Card01 S1）= 一定和牌：默认方式选牌 + 「开始」确认 ────────────
# 手牌全变暗（亮度只归 hand_pick 管）→ 只能点能听的牌 → 选满 1 张出「开始」
# → 点「开始」才发 op=guobiao（打出去后服务端立刻结算）。
# 再点一次技能图标 = 取消；服务端拒绝 / 被看破拦下 → 自动回正常态。
func _cg_guobiao() -> void:
	if guobiao_selecting:
		_gb_close()
		_toast("国标：取消")
		return
	if not bool(srv_state.get("guobiao_can", false)):
		_toast("国标：要刚摸完牌、且切出一张还能听牌（本小局一次）")
		return
	if yiding_selecting:
		_yd_close()
	guobiao_selecting = true
	yiding_selecting = false
	riichi_selecting = false
	_make_gb_ui()
	hand_pick.begin(gb_picks, 1, {"on_change": _refresh_gb_btn})
	_apply_entity_states(srv_state)
	_refresh_gb_btn()
	_toast("国标：选一张能听牌的牌 → 点「开始」")


func _make_gb_ui() -> void:
	if gb_ui != null:
		return
	var host: Node = get_parent()
	if host == null:
		host = self
	gb_ui = Control.new()
	gb_ui.name = "GuobiaoUI"
	gb_ui.z_index = 250
	host.add_child(gb_ui)
	gb_ui.position = Vector2.ZERO
	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	gb_btn = TextureButton.new()
	gb_btn.name = "GuobiaoStart"
	gb_btn.texture_normal = tex
	gb_btn.ignore_texture_size = true
	gb_btn.stretch_mode = TextureButton.STRETCH_SCALE
	gb_btn.focus_mode = Control.FOCUS_NONE
	gb_btn.size = Vector2(bw, bh)
	gb_btn.position = prompt_btn_pos(bw, bh)
	gb_btn.visible = false
	gb_btn.pressed.connect(_gb_confirm)
	gb_ui.add_child(gb_btn)


func _refresh_gb_btn() -> void:
	if gb_btn != null and is_instance_valid(gb_btn):
		gb_btn.visible = guobiao_selecting and hand_pick.ready()


# 点手牌 = 只选中（打不出去、也不会发请求）；不能听的牌点了不选中
func _gb_pick(index: int) -> void:
	var tiles := display_tiles()
	if index < 0 or index >= tiles.size():
		return
	if not srv_can_guobiao_with(String(tiles[index])):
		_toast("国标：这张打出去就不听牌了")
		return
	hand_pick.toggle(index)
	_apply_entity_states(srv_state)         # 选中的恢复亮度


func _gb_confirm() -> void:
	if not guobiao_selecting:
		return
	var tiles := display_tiles()
	var idx := -1
	if not gb_picks.is_empty():
		idx = int(gb_picks[0])
	if idx < 0 or idx >= tiles.size():
		_toast("国标：先选一张能听牌的牌")
		return
	var tile := String(tiles[idx])
	_gb_close()
	_declare_guobiao(tile)


func _gb_close(render := true) -> void:
	guobiao_selecting = false
	gb_picks.clear()
	hand_pick.end()
	if gb_btn != null and is_instance_valid(gb_btn):
		gb_btn.visible = false
	if gb_ui != null and is_instance_valid(gb_ui):
		gb_ui.queue_free()
	gb_ui = null
	gb_btn = null
	if render:
		_apply_entity_states(srv_state)


func srv_can_guobiao_with(tile_id: String) -> bool:
	for t in (srv_state.get("guobiao_tiles", []) as Array):
		if String(t) == tile_id:
			return true
	return false


# 宣言：把选好的那张打出去 → 服务端立刻结算
# 按 下家 → 对家 → 上家 找手里有我铳张的人（有就他放铳，多张取最高点数），都没有就自摸
func _declare_guobiao(tile: String) -> void:
	hovered_index = -1
	var r := srv_request({"op": "guobiao", "seat": my_seat, "tile": tile})
	if srv_kangpo_blocked(r):
		# 等对方决定是否看破：放行后服务端会自己重放这条 op，不用再点
		_apply_entity_states(srv_state)
		return
	if r.is_empty():
		_toast(_srv_err("国标：服务端没有回应"))
		_pull_state()
		return
	if not bool(r.get("ok", false)):
		_toast(String(r.get("error", "国标：发动失败")))
		_pull_state()
		return
	_toast("国标：宣言！")
	srv_apply_state(r.get("state"), r.get("events"))
	_ensure_result()


# 服务端拒绝后重新拉一次 state（真实原因在 srv_note，界面回到正常态）
# 这张牌现在能不能打？——B2：一张都不能打 = 本地 state 过期，强制重拉一次。
var _legal_fix_ms := 0


func _legal_guard(st: Dictionary) -> void:
	if game_over or dealing or srv_busy:
		return
	if String(st.get("phase", "")) != "discard" or int(st.get("turn", -1)) != my_seat:
		return
	var tiles := display_tiles()
	if (tiles as Array).is_empty():
		return
	for x in tiles:
		if srv_can_discard_with(String(x)):
			return
	var now := Time.get_ticks_msec()
	if now - _legal_fix_ms < 2000:
		return
	_legal_fix_ms = now
	_dev_log("[LEGAL] 本地 legal 不可用（%d 张都不许打）→ 强制重拉 state" % (tiles as Array).size())
	_pull_state()


func _pull_state() -> void:
	var st := srv_request({"op": "state", "seat": my_seat})
	if not st.is_empty():
		srv_apply_state(st.get("state"), [])


# 服务端说「这局结束了」却没给 result（老数据 / 响应缺字段）→ 再问一次 state 兜底，
# 否则结算画面永远不出现，界面看起来就是卡死。
func _ensure_result() -> void:
	if String(srv_state.get("phase", "")) != "ended":
		return
	var rs = srv_state.get("result")
	if typeof(rs) == TYPE_DICTIONARY and not (rs as Dictionary).is_empty():
		return
	_pull_state()


# ── 一定和牌（21S2 馈赠 / 15S2 上钩 / 20S1 前路）：同一套选牌界面 ──────
func _yiding_on_clicked() -> void:
	if yiding_selecting:
		_yd_close()
		_toast("一定和牌：取消")
		return
	if not bool(srv_state.get("yiding_can", false)):
		_toast("一定和牌：要刚摸完牌、且切出一张还能听牌")
		return
	if guobiao_selecting:
		_gb_close()
	guobiao_selecting = false
	yiding_selecting = true
	riichi_selecting = false
	_make_yd_ui()
	hand_pick.begin(yd_picks, 1, {"on_change": _refresh_yd_btn})
	_apply_entity_states(srv_state)
	_refresh_yd_btn()
	_toast("一定和牌：选一张能听牌的牌 → 点「开始」")


func _make_yd_ui() -> void:
	if yd_ui != null:
		return
	var host: Node = get_parent()
	if host == null:
		host = self
	yd_ui = Control.new()
	yd_ui.name = "YidingUI"
	yd_ui.z_index = 250
	host.add_child(yd_ui)
	yd_ui.position = Vector2.ZERO
	var tex := btn_tex("pass")
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	yd_btn = TextureButton.new()
	yd_btn.name = "YidingStart"
	yd_btn.texture_normal = tex
	yd_btn.ignore_texture_size = true
	yd_btn.stretch_mode = TextureButton.STRETCH_SCALE
	yd_btn.focus_mode = Control.FOCUS_NONE
	yd_btn.size = Vector2(bw, bh)
	yd_btn.position = prompt_btn_pos(bw, bh)
	yd_btn.visible = false
	yd_btn.pressed.connect(_yd_confirm)
	yd_ui.add_child(yd_btn)


func _refresh_yd_btn() -> void:
	if yd_btn != null and is_instance_valid(yd_btn):
		yd_btn.visible = yiding_selecting and hand_pick.ready()


func _yd_pick(index: int) -> void:
	var tiles := display_tiles()
	if index < 0 or index >= tiles.size():
		return
	if not srv_can_yiding_with(String(tiles[index])):
		_toast("一定和牌：这张打出去就不听牌")
		return
	hand_pick.toggle(index)
	_apply_entity_states(srv_state)


func _yd_confirm() -> void:
	if not yiding_selecting:
		return
	var tiles := display_tiles()
	var idx := -1
	if not yd_picks.is_empty():
		idx = int(yd_picks[0])
	if idx < 0 or idx >= tiles.size():
		_toast("一定和牌：先选一张能听牌的牌")
		return
	var tile := String(tiles[idx])
	_yd_close()
	_declare_yiding(tile)


func _yd_close(render := true) -> void:
	yiding_selecting = false
	yd_picks.clear()
	hand_pick.end()
	if yd_btn != null and is_instance_valid(yd_btn):
		yd_btn.visible = false
	if yd_ui != null and is_instance_valid(yd_ui):
		yd_ui.queue_free()
	yd_ui = null
	yd_btn = null
	if render:
		_apply_entity_states(srv_state)


# 立直按钮：再点一次取消。开了国标/一定和牌选牌就先收起它们
func _toggle_riichi_selecting() -> void:
	if game_over or riichi_declared:
		return
	if guobiao_selecting:
		_gb_close()
	if yiding_selecting:
		_yd_close()
	riichi_selecting = not riichi_selecting
	_update_hand_dim()
	_update_riichi_button_dim()
	refresh_hand()
	srv_yield_to_me()


# 选牌状态下：打出去就不能保持听牌的牌，亮度降到 50%
func _update_hand_dim() -> void:
	hand_pick.sync()                     # 立直 / 选牌 的暗化都由 hand_pick 统一算


# 立直按钮自己也要在选牌状态下变暗 50%（仍然可点，再点一次取消）
func _update_riichi_button_dim() -> void:
	var c := Color(0.5, 0.5, 0.5, 1.0) if riichi_selecting else Color(1.0, 1.0, 1.0, 1.0)
	var bl := get_node_or_null("UI/Btn/BtnLizhi")
	if bl is CanvasItem:
		(bl as CanvasItem).modulate = c


# 和牌：停止一切行为并显示「胡牌」（番 / 符 / 得点由服务端算好传过来）
# 宝牌明细（服务端 yaku 里的 detail：宝牌 / 赤宝牌 / 里宝牌；里宝牌只有立直和牌时才 > 0）
# 服务端 result 里有些字段是「自摸时为 null、荣和时为数字」的（典型：loser）。
# GDScript 的 int(null) 会抛 "Invalid call. Nonexistent 'int' constructor"，
# 整个 show_hupai 就在这里中止 → 表现就是「荣和有结算框，自摸没有」（2026-11-02）。
# 所有 result 字段一律走这个函数读。
func _int_of(d, key: String, def: int = 0) -> int:
	if typeof(d) != TYPE_DICTIONARY:
		return def
	var v = (d as Dictionary).get(key, def)
	if v == null:
		return def
	if typeof(v) == TYPE_BOOL:
		return 1 if bool(v) else 0
	if typeof(v) == TYPE_STRING or typeof(v) == TYPE_STRING_NAME:
		var s := String(v).strip_edges()
		return int(s) if s.is_valid_int() else def
	return int(v)


func srv_dora_detail(yaku_list: Array) -> String:
	var parts := []
	for y in yaku_list:
		if typeof(y) != TYPE_DICTIONARY:
			continue
		var det = (y as Dictionary).get("detail", {})
		if typeof(det) != TYPE_DICTIONARY:
			continue
		for key in ["宝牌", "赤宝牌", "里宝牌"]:
			var n := _int_of(det, key, 0)
			if n > 0:
				parts.append("%s %d" % [key, n])
	if parts.is_empty():
		return ""
	return "（%s）" % "、".join(parts)


const WIN_SCENE_PATH := "res://和牌播报.tscn"
var win_scene: Node2D = null            # 和牌播报场景（截图背景 + 进场动画 + 结算面板）
var _win_intro_running := false         # 进场动画正在播
var _win_intro_ms := 0                  # 上次播报开始时刻（ms）：flag 自愈用


# 和牌播报场景（只实例化一次，之后复用）
func _win_scene_get() -> Node2D:
	if win_scene != null and is_instance_valid(win_scene):
		return win_scene
	var ps := load(WIN_SCENE_PATH) as PackedScene
	if ps == null:
		push_warning("main.gd: 找不到 " + WIN_SCENE_PATH)
		return null
	# ★ 必须挂在高层 CanvasLayer 上：Control 的鼠标命中只看「层号 → 树序」，不看 z_index。
	#   塞进 UI（layer 0）时，牌自带的 Hit 控制在树里更靠后 → 悬浮/点击被麻将牌抢走，
	#   播报上的确认按钮点不到（2026-10-30 报）。
	#   layer 必须在 CardPhase(=20) 之上；实测 90 这一层整个不绘制，31 正常。
	var host: Node = get_parent() if get_parent() != null else self
	var layer := host.get_node_or_null("WinAnnounceLayer") as CanvasLayer
	if layer == null:
		layer = CanvasLayer.new()
		layer.name = "WinAnnounceLayer"
		layer.layer = 31
		host.add_child(layer)
	win_scene = ps.instantiate() as Node2D
	win_scene.name = "WinAnnounce"
	layer.add_child(win_scene)
	return win_scene


# 和牌播报里「四个小面板」那一层（确认按钮挂这层，一起淡入）
func _win_seats_node() -> Control:
	var sc := _win_scene_get()
	if sc == null or not sc.has_method("seats_node"):
		return null
	return sc.call("seats_node") as Control


func _win_announce_get() -> Control:
	if win_announce != null and is_instance_valid(win_announce):
		return win_announce
	var sc := _win_scene_get()
	win_announce = sc.announce if sc != null else null
	return win_announce


func _win_panel_visible() -> bool:
	return win_announce != null and is_instance_valid(win_announce) \
		and (win_announce as CanvasItem).visible


# 和牌播报：① 截「点击和牌那一刻」的全屏图当背景 ② 按赢家方位播长条进场
#           ③ 播完隐藏 ④ 等 1 秒弹结算面板
# ── 结算：把和牌家的手牌贴到屏幕上方 ────────────────────────────────
#   顺序：暗手（理牌）→ 副露（该横置的横置）→ 隔开一段 → 和牌那张
#   hand / melds / win_tile 由服务端结算时给（技能强制和牌 → 被算作铳的那张）
func _win_hand_show(seat: int, win: Dictionary) -> void:
	var sc := _win_scene_get()
	if sc == null:
		return
	var hand: Array = []
	var hs = win.get("hand")
	if typeof(hs) == TYPE_ARRAY:
		for t in (hs as Array):
			hand.append(String(t))
	if not hand.is_empty():
		hand.sort_custom(_comes_first)
	var wts := String(win.get("win_tile", ""))
	var melds: Array = []
	var ms = win.get("melds")
	if typeof(ms) == TYPE_ARRAY:
		melds = ms

	# 竖牌尺寸（按 Pai 模板的贴图比例算；横置就是把竖牌转 90°）
	var uw := 60.0
	var uh := 86.0
	var tpl: Node2D = null
	if pai != null:
		tpl = pai.get_node_or_null("1m") as Node2D
	if tpl != null:
		var tspr := tpl.get_node_or_null("Sprite2D") as Sprite2D
		if tspr != null and tspr.texture != null:
			var ts := tspr.texture.get_size()
			if ts.x > 1.0:
				uh = uw * (ts.y / ts.x)

	# 副露分组（rot_index / rot_all 决定哪张横置；杠是 4 张）
	var groups: Array = []
	for m in melds:
		if typeof(m) != TYPE_DICTIONARY:
			continue
		var md: Dictionary = m
		var mt = md.get("tiles")
		if typeof(mt) != TYPE_ARRAY or (mt as Array).is_empty():
			continue
		var rot_i := int(md.get("rot_index", 0))
		var rot_all := bool(md.get("rot_all", false))
		var gw := 0.0
		for k in range((mt as Array).size()):
			gw += uh if (rot_all or k == rot_i) else uw
		groups.append({"tiles": mt, "rot": rot_i, "rot_all": rot_all})

	# 总宽 → 水平居中；底边距屏幕顶部留一点
	var gap_hand := 2.0
	var gap_meld := 12.0
	var gap_win := 34.0
	var total := 0.0
	for k in range(hand.size()):
		total += uw + (gap_hand if k > 0 else 0.0)
	for g in groups:
		var gd0: Dictionary = g
		total += gap_meld
		var t0: Array = gd0["tiles"]
		var r0 := int(gd0.get("rot", 0))
		var ra0 := bool(gd0.get("rot_all", false))
		for k in range(t0.size()):
			total += uh if (ra0 or k == r0) else uw
	if wts != "":
		total += gap_win + uw

	var vp := get_viewport_rect().size
	var base := 52.0 + uh                 # 牌的下边缘 y
	var x := maxf((vp.x - total) * 0.5, 12.0)
	var root := Node2D.new()
	root.name = "HandRack"

	# 1) 暗手
	for k in range(hand.size()):
		if k > 0:
			x += gap_hand
		var hv := _make_face_visual(String(hand[k]), uw)
		if hv != null:
			hv.position = Vector2(x + uw * 0.5, base - uh * 0.5)
			root.add_child(hv)
		x += uw

	# 2) 副露
	for g in groups:
		var gd: Dictionary = g
		x += gap_meld
		var tt: Array = gd["tiles"]
		var rot_i2 := int(gd.get("rot", 0))
		var rot_all2 := bool(gd.get("rot_all", false))
		for k in range(tt.size()):
			var horiz: bool = rot_all2 or k == rot_i2
			var vis := _make_face_visual(String(tt[k]), uw)
			if vis != null:
				if horiz:
					# 横置：把竖牌转 90°，占位宽度 = 竖牌的高
					vis.rotation_degrees = -90.0
					vis.position = Vector2(x + uh * 0.5, base - uw * 0.5)
				else:
					vis.position = Vector2(x + uw * 0.5, base - uh * 0.5)
				root.add_child(vis)
			x += uh if horiz else uw

	# 3) 和牌那张（和暗手/副露隔开一段）
	if wts != "":
		x += gap_win
		var wv := _make_face_visual(wts, uw)
		if wv != null:
			wv.position = Vector2(x + uw * 0.5, base - uh * 0.5)
			root.add_child(wv)

	sc.call("set_hand", root)


# 流局等场合：不放长条进场动画，直接把结算面板贴出来（服务端给了 scores/deltas，面板一样有分数条）
func _win_panel_show(content: Dictionary) -> void:
	var sc := _win_scene_get()
	if sc == null:
		return
	sc.call("show_panel", content)
	var cb := _result_confirm_button_get()
	if cb != null:
		cb.visible = true
		cb.call("set_state", false, 0, 4)


func _win_intro_start(win: Dictionary, content: Dictionary) -> void:
	if _win_intro_running:
		# 防御：上一次播报如果中途抛错，flag 会永远留在 true → 之后再也不会播报
		if Time.get_ticks_msec() - _win_intro_ms < 20000:
			return
	_win_intro_running = true
	_win_intro_ms = Time.get_ticks_msec()
	var sc := _win_scene_get()
	if sc == null:
		_win_intro_running = false
		return
	srv_layout_buttons([])                     # 截图上不要出现荣/自摸按钮
	sc.call("reset")
	await get_tree().process_frame             # 让按钮收起、场景隐藏生效
	var shot: Texture2D = null      # 播报不要背景图（只用全屏蒙版），不再截图
	# 流局（result 里没有 winner 键）不贴卡：以前会兜底成 my_seat，把「自己的主战卡」贴上去
	var has_winner := win.has("winner") and win.get("winner") != null
	var wseat := _int_of(win, "winner", my_seat)
	var who := who_of_seat(wseat)
	var pick: Array = _win_card_pick(wseat) if has_winner else [0, false]
	if not has_winner:
		who = who_of_seat(my_seat)
	# 页眉手牌先摆好（隐藏状态）；play 里到「蒙版+横幅淡入」那一步才亮
	if has_winner:
		_win_hand_show(wseat, win)
	var _fps0 := Engine.max_fps
	var _vs0 := DisplayServer.window_get_vsync_mode()
	if announce_max_fps > 0:
		Engine.max_fps = maxi(int(_fps0), int(announce_max_fps))
	else:
		# 0 = 跟着屏幕走：开垂直同步 + 解除帧率上限，帧节奏和刷新对齐，慢速平移才不抖
		DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_ENABLED)
		Engine.max_fps = 0
	var _lose := -1
	if win.get("loser") != null:
		_lose = _int_of(win, "loser", -1)
	content["winner_id"] = srv_nick_of(wseat)
	content["loser_id"] = srv_nick_of(_lose) if _lose >= 0 else ""
	content["level"] = _result_level(win)      # 满贯 / 跳满 / 倍满 / 三倍满 / 役满（对应场景里的图）
	# 表宝牌 / 里宝牌指示牌（result 里有就用，没有就退回自己的 state）
	var _di = win.get("dora_indicators")
	var _ui = win.get("ura_indicators")
	if typeof(_di) != TYPE_ARRAY:
		_di = srv_state.get("dora", [])
	if typeof(_ui) != TYPE_ARRAY:
		_ui = srv_state.get("ura", [])
	content["dora_ind"] = _di if typeof(_di) == TYPE_ARRAY else []
	content["ura_ind"] = _ui if typeof(_ui) == TYPE_ARRAY else []
	await sc.call("play", who, int(pick[0]), bool(pick[1]), shot, content)
	Engine.max_fps = int(_fps0)
	if announce_max_fps <= 0:
		DisplayServer.window_set_vsync_mode(_vs0)
	# 确认按钮的显隐 / 可点时机由场景控制（跟小面板一起淡入）
	var cb := _result_confirm_button_get()
	if cb != null:
		cb.call("set_state", false, 0, 4)
	_win_intro_running = false
# 播报上贴谁的人物卡：主战已暴露 → 主战；否则协战（没暴露就连遮罩一起）；只剩主战没暴露 → 主战+遮罩
func _win_card_pick(seat: int) -> Array:
	var cs := {}
	for it in (srv_state.get("char_states", []) as Array):
		if typeof(it) == TYPE_DICTIONARY and int((it as Dictionary).get("seat", -1)) == int(seat):
			cs = it
			break
	var main_i: Dictionary = cs.get("main", {}) if typeof(cs.get("main")) == TYPE_DICTIONARY else {}
	var sup_i: Dictionary = cs.get("support", {}) if typeof(cs.get("support")) == TYPE_DICTIONARY else {}
	var mc := int(main_i.get("card", 0))
	var sc2 := int(sup_i.get("card", 0))
	var main_open := bool(main_i.get("open", false))
	var sup_open := bool(sup_i.get("open", false))
	var main_exp := bool(main_i.get("expired", false))
	var sup_exp := bool(sup_i.get("expired", false))
	# 一律按「公开信息」贴卡（自己赢也一样 —— 用户口径 2026-11-02）：
	#   发动过 = 已公开；没发动过 / 已到期 / 自己手动遮罩 → 连遮罩一起复制
	var main_ok := mc > 0 and main_open and not main_exp
	var sup_ok := sc2 > 0 and sup_open and not sup_exp and not _card_is_support_muted(sc2)
	if main_ok:
		return [mc, false]                  # 主战已暴露：直接复制
	if sup_ok:
		return [sc2, false]                 # 协战已暴露：正常复制
	if sc2 > 0:
		return [sc2, true]                  # 协战没暴露：连遮罩一起复制
	if mc > 0:
		return [mc, true]                   # 只剩主战且没暴露：主战 + 遮罩
	return [0, false]


# 结算播报：四个方位的小面板（自己=下 / 下家=右 / 对家=上 / 上家=左）
#   win.scores = {座位: 结算后分数}，win.deltas = {座位: 本局增减}（JSON 的 key 是字符串）
# 结算播报的番种条：每个役一条（名字 + 番数）；宝牌一张都没中就不写；役满写役满
# 番种播报的先后：0 = 局况/立直相关 → 1 = 决定符的基础门清役 → 2 = 手牌构成的手役 → 3 = 宝牌
func _yaku_rank(nm: String) -> int:
	if nm.contains("宝牌") or nm.contains("ドラ") or nm.contains("宝牌"):
		return 30
	for k in ["立直", "双立直", "一发", "门前清自摸和", "岭上开花", "抢杠",
			"海底", "河底", "天和", "地和", "人和"]:
		if nm.contains(k):
			return 0
	for k in ["平和", "一杯口", "七对子", "断幺九"]:
		if nm.contains(k):
			return 10
	return 20


func _result_yaku_rows(win: Dictionary) -> Array:
	var out: Array = []
	var ym := _int_of(win, "yakuman", 0)
	var ord := 0
	for y in win.get("yaku", []):
		if typeof(y) != TYPE_DICTIONARY:
			continue
		var nm := String((y as Dictionary).get("name", ""))
		var hn := int((y as Dictionary).get("han", 0))
		if nm == "":
			continue
		var dt = (y as Dictionary).get("detail")
		var dcount := 0
		if typeof(dt) == TYPE_DICTIONARY:
			for k in (dt as Dictionary).keys():
				dcount = maxi(dcount, int((dt as Dictionary)[k]))
		var is_dora := nm.contains("宝牌") or nm.contains("ドラ")
		if is_dora and dcount <= 0:
			continue                    # 没宝牌就不写宝牌
		if hn <= 0 and ym <= 0:
			continue
		var ht := ""
		if ym > 0:
			ht = "役满" if ym < 2 else "双倍役满"
		else:
			ht = "%d番" % hn
		if ym > 0 and (is_dora or hn < 13):
			continue                    # 役满优先：宝牌不算役、普通役简略掉
		# 宝牌拆开播：表宝牌 / 赤宝牌 / 里宝牌（+ 技能加成）各占一条，别再糊成一条「宝牌 N 番」
		if is_dora and ym <= 0 and typeof(dt) == TYPE_DICTIONARY:
			var _any := false
			for _k in ["宝牌", "赤宝牌", "里宝牌"]:
				var _n2 := int((dt as Dictionary).get(_k, 0))
				if _n2 <= 0:
					continue
				_any = true
				out.append({"name": _k, "han_text": "%d番" % _n2,
					"rank": _yaku_rank(_k), "ord": ord})
				ord += 1
			for _k in (dt as Dictionary).keys():
				var _ks := String(_k)
				if _ks in ["宝牌", "赤宝牌", "里宝牌", "han"]:
					continue
				var _n3 := int((dt as Dictionary)[_k])
				if _n3 <= 0:
					continue
				_any = true
				out.append({"name": _ks, "han_text": "%d番" % _n3,
					"rank": _yaku_rank(_ks), "ord": ord})
				ord += 1
			if _any:
				continue
		out.append({
			"name": nm, "han_text": ht,
			"rank": 0 if ym > 0 else _yaku_rank(nm),
			"ord": ord,
		})
		ord += 1
	# 同一档内保持服务端给的顺序：先比档位，再比原始序号
	out.sort_custom(func(a, b):
		if int(a["rank"]) != int(b["rank"]):
			return int(a["rank"]) < int(b["rank"])
		return int(a["ord"]) < int(b["ord"]))
	return out


# 调试入口（autoplay.cfg 里写 announce=1）：直接进和牌播报调界面
func _debug_announce() -> void:
	await get_tree().create_timer(0.8).timeout      # 等牌桌画出来再截图当背景
	game_over = false
	var sc := _win_scene_get()
	if sc != null and sc.has_method("set_tune_mode"):
		sc.call("set_tune_mode", true)
	var ws := my_seat
	var win := {
		"result": "tsumo", "tsumo": true, "winner": ws, "loser": null,
		"han": 6, "fu": 30, "points": 12000, "yakuman": 0,
		"pays": {"total": 12000},
		"yaku": [{"name": "立直", "han": 1}, {"name": "门前清自摸和", "han": 1},
			{"name": "平和", "han": 1}, {"name": "断幺九", "han": 1},
			{"name": "一气通贯", "han": 2}, {"name": "宝牌", "han": 4, "detail": {"宝牌": 2, "赤宝牌": 1, "里宝牌": 1}}],
		"hand": ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "1s", "2s", "3s", "9m", "9m"],
		"melds": [{"kind": "chi", "tiles": ["4m", "5m", "6m"], "rot_index": 0, "rot_all": false}],
		"win_tile": "3p",
	"dora_indicators": ["bai", "1s"],
	"ura_indicators": ["4m"],
		"scores": {str(ws): 47000, str((ws + 1) % 4): 31000, str((ws + 2) % 4): 31000, str((ws + 3) % 4): 31000},
		"deltas": {str(ws): 12000, str((ws + 1) % 4): -4000, str((ws + 2) % 4): -4000, str((ws + 3) % 4): -4000},
	}
	var content := {
		"title": "和　了", "method": "%s　自摸" % srv_nick_of(ws),
		"yaku": "立直・门前清自摸和・平和・断幺九・一气通贯・宝牌2",
		"score": "12000 點", "sub": "6 番　30 符", "is_draw": false,
		"yaku_rows": _result_yaku_rows(win),
		"seats": _result_seats(win),
	}
	_win_intro_start(win, content)


func _result_level(win: Dictionary) -> String:
	# 对应 和牌播报.tscn 里 和牌播报面板 下的 AnimatedSprite2D 名字
	if _int_of(win, "yakuman", 0) > 0:
		return "役满"
	var han := _int_of(win, "han", 0)
	var fu := _int_of(win, "fu", 0)
	if han >= 13:
		return "役满"
	if han >= 11:
		return "三倍满"
	if han >= 8:
		return "倍满"
	if han >= 6:
		return "跳满"
	if han >= 5:
		return "满贯"
	if han >= 3 and float(fu) * pow(2.0, float(han) + 2.0) >= 2000.0:
		return "满贯"      # 3番70符 / 4番40符 以上也算满贯
	return ""


func _result_seats(win: Dictionary) -> Array:
	# 屏幕最底下一行，从左往右：上家 / 我 / 対家 / 下家
	var out: Array = []
	var sc = win.get("scores")
	var dl = win.get("deltas")
	var order := [3, 0, 2, 1]        # 相对自己的座位偏移：+3=上家 · 0=我 · +2=対家 · +1=下家
	for k in range(4):
		var sid := (my_seat + int(order[k])) % 4
		var after := -1
		if typeof(sc) == TYPE_DICTIONARY:
			if (sc as Dictionary).has(str(sid)):
				after = int((sc as Dictionary)[str(sid)])
			elif (sc as Dictionary).has(sid):
				after = int((sc as Dictionary)[sid])
		if after < 0:
			after = _score_now(sid)
		var delta := 0
		if typeof(dl) == TYPE_DICTIONARY:
			if (dl as Dictionary).has(str(sid)):
				delta = int((dl as Dictionary)[str(sid)])
			elif (dl as Dictionary).has(sid):
				delta = int((dl as Dictionary)[sid])
		out.append({
			"slot": k,
			"nick": srv_nick_of(sid),
			"before": maxi(after - delta, 0) if after >= 0 else 0,
			"after": maxi(after, 0),
		})
	return out


func _score_now(seat: int) -> int:
	var arr = srv_state.get("scores")
	if typeof(arr) == TYPE_ARRAY:
		for it in (arr as Array):
			if typeof(it) != TYPE_DICTIONARY:
				continue
			if int((it as Dictionary).get("seat", -1)) == int(seat):
				return int((it as Dictionary).get("score", -1))
	return -1


func show_hupai(win: Dictionary = {}) -> void:
	if game_over:
		return
	game_over = true
	riichi_selecting = false
	srv_layout_buttons([])

	var is_draw := String(win.get("result", "")) == "ryuukyoku" \
		or (win.has("reason") and not win.has("winner"))
	var title := "流　局" if is_draw else "和　了"
	var method := "DRAW" if is_draw else "WIN"
	var yaku_text := ""
	var score_text := ""
	var sub_text := ""
	var detail := "流局" if is_draw else "和了"      # 旧 ResultPanel 兜底
	if not win.is_empty():
		if is_draw:
			var draw_names := {"exhaustive": "荒牌流局", "kyuushu": "九种九牌",
				"sufon_renda": "四风连打", "sucha_riichi": "四家立直",
				"sukan_santan": "四杠散了", "sanchahou": "三家和了"}
			detail = String(draw_names.get(String(win.get("reason", "")), "流局"))
			method = "流局"
			score_text = detail
			var tp = win.get("tenpai", [])
			if typeof(tp) == TYPE_ARRAY and not (tp as Array).is_empty():
				var who := []
				for sid in tp:
					who.append("%d 号位" % int(sid))
				detail += "\n听牌：%s" % "、".join(who)
				sub_text = "聽牌　%s" % "・".join(who)
		else:
			var names := []
			for y in win.get("yaku", []):
				names.append(String(y.get("name", "?")) if typeof(y) == TYPE_DICTIONARY else String(y))
			# 宝牌明细由服务端算好（包括立直后的里宝牌），客户端只负责显示
			var dora_txt := srv_dora_detail(win.get("yaku", []))
			var han := _int_of(win, "han", 0)
			var fu := _int_of(win, "fu", 0)
			var pays: Dictionary = {}
			if typeof(win.get("pays")) == TYPE_DICTIONARY:
				pays = win.get("pays")
			var pts := _int_of(pays, "total", 0)
			var head := "自摸" if (bool(win.get("tsumo", false)) \
				or String(win.get("result", "")) == "tsumo") else "榮和"
			method = head
			# 用户口径 2026-11-02：顶部写昵称（荣和 = 昵称一 ← 昵称二）
			var _wn := _int_of(win, "winner", my_seat)
			var _ls := _int_of(win, "loser", -1)   # 自摸时服务端给 null
			if bool(win.get("tsumo", false)) \
					or String(win.get("result", "")) == "tsumo":
				method = "%s　自摸" % srv_nick_of(_wn)
			elif _ls >= 0:
				method = "%s ← %s　荣和" % [srv_nick_of(_wn), srv_nick_of(_ls)]
			yaku_text = "・".join(names) + dora_txt
			detail = "%s　%s%s" % [head, "、".join(names), dora_txt]
			var _ym := _int_of(win, "yakuman", 0)
			if _ym > 0:
				var ym := _ym
				score_text = "%d 點" % pts
				sub_text = "役滿" + (" ×%d" % ym if ym > 1 else "")
				detail += "\n役满 ×%d　%d 点" % [ym, pts]
			else:
				score_text = "%d 點" % pts
				sub_text = "%d 番　%d 符" % [han, fu]
				detail += "\n%d 番 %d 符　%d 点" % [han, fu, pts]

	var _content := {
		"title": title, "method": method, "yaku": yaku_text,
	"score": score_text, "sub": sub_text, "is_draw": is_draw,
	"seats": _result_seats(win),
	"yaku_rows": _result_yaku_rows(win),
	}
	# 结算面板已经开着（真结算迟到 / 刷新）→ 只更新文字，不重播进场动画
	if _win_panel_visible():
		var ann := _win_announce_get()
		if ann != null:
			ann.call("set_content", _content)
	elif not _win_intro_running:
		result_confirmed = false
		result_confirm_sig = ""
		if is_draw:
			_win_panel_show(_content)      # 流局：不放进场动画，直接把播报贴出来
		else:
			_win_intro_start(win, _content)
	# 旧 ResultPanel 仍填内容作为兼容，但不再显示
	var panel := get_node_or_null("UI/ResultPanel") as Control
	if panel == null:
		return
	var tl := panel.get_node_or_null("ResultTitle") as Label
	var dl := panel.get_node_or_null("ResultDetail") as Label
	if tl != null:
		tl.text = title
	if dl != null:
		dl.text = detail
	panel.visible = false

# ────────────────────────── 快捷键 ──────────────────────────

# 配牌该由谁推进：座位号最小的那个窗口（它中途关了，服务端 12 秒后把座位交回 AI，
# 于是别的窗口就成了最小号，自动接手把配牌推完）
func _is_deal_driver() -> bool:
	if srv_humans.is_empty():
		# ★ 不知道谁在线 → 谁都可以推。deal_step 在服务端是「按 deal_i 顺计划走」，
		#   多个人同时推不会重复发牌（事务串行 + 进度指针），顶多多几个请求。
		#   以前这里写「只认 0 号位」，一旦人是 1/2/3 号位就永久卡死（2026-11-01 现场）。
		return true
	var mn := 3
	for h in srv_humans:
		mn = mini(mn, int(h))
	return my_seat == mn


# 定时问服务端（只看不动手）。两种节奏：
#   · 在等别人出牌  → POLL_SEC（0.6 秒，要尽快看到别人的动作）
#   · 轮到我 / 已结算 → POLL_IDLE_SEC（1.5 秒）—— 别家的窗口可能开了新局、
#     或者替我动了牌，不问的话这个窗口会一直停在旧局（四个窗口「不同步」就是这么来的）
#   · 这局只有我一个窗口（没有别的窗口）→ 轮到我时干脆不问，省掉每次 60ms 的卡顿
# 技能面板开着时玩家会想很久：定时问一次 state 续租，
# 否则 seat_lease 过期后，别的窗口一 step 就把我当 AI 代打（摸了牌 → 技能报「摸牌前才能发动」）。
var _lease_ping := 0.0
# 有没有技能正等着我「选人 / 选牌」？（这些界面上点手牌不能算打牌）
func _skill_input_busy() -> bool:
	if skill2_card != 0:                          # 避开：选人 / 选两张手牌
		return true
	if duel_selecting or xn_selecting:            # 决斗 / X神：风盘选人
		return true
	if dy_active:                                 # 钓鱼：选人 / 选牌种
		return true
	if cg_active or cg_kind != "":                # 研究/传承/前路/连接/看破：选单
		return true
	if seat_pick_mode != "":                      # 正在用东南西北选玩家
		return true
	if c32_panel.active:                          # 新手运：交牌 / 换牌
		return true
	if sf_active:                                 # 深山 / 先负 / 馈赠 / 友引
		return true
	if future_active or future_ask_ui != null:    # 未来：排牌山
		return true
	if oracle_ui != null:                         # 降神：选花色
		return true
	if c45b_ui != null:                           # 替身：我点别人的手牌
		return true
	if c45_panel.active:                          # 神境：挑 13 张
		return true
	if c26_active:                                # 天梯：排牌山
		return true
	return false


func _skill_panel_open() -> bool:
	return c09_active or zl_active or hs_active or c05_active or pofa_active \
		or press_panel.active or ym_panel.active or c10_active or c11s2_active \
		or sf_active or swap_panel.active or c24_panel.active or future_active \
		or c25b_panel.active or c27_panel.active or c30_panel.active \
		or c32_panel.active or c43_panel.active or c45_panel.active \
		or c46_panel.active \
		or future_ask_ui != null or c26_active or c38_active \
		or oracle_ui != null or guobiao_selecting or yiding_selecting


var _result_confirm_accum := 0.0


func _result_confirm_tick(delta: float) -> void:
	_result_confirm_accum += delta
	if _result_confirm_accum < 0.8:
		return
	_result_confirm_accum = 0.0
	_result_confirm_poll()


func _lease_tick(delta: float) -> void:
	if not _skill_panel_open():
		_lease_ping = 0.0
		return
	_lease_ping += delta
	if _lease_ping < 2.0:
		return
	_lease_ping = 0.0
	if srv != null and not game_over:
		srv_request({"op": "state", "seat": my_seat})


# 面板还开着、但服务端已经不允许发动了（刚换完 / 已经摸牌 / 被别的窗口推进）
# → 自动收起来，别留一个点不动的空面板。
func _skill_panel_stale_close() -> void:
	if zl_active and not bool(srv_state.get("zhalie_can", false)):
		_zl_close()
	if hs_active and not bool(srv_state.get("haishin_can", false)):
		_hs_close()
	if c09_active and not bool(srv_state.get("card09_can", false)):
		_card09_close()
	# 魔术 / 快手：服务端已经不允许了（打完了 / 被别的窗口推进）→ 必须收起来，
	# 否则 c11_active / c11s2_active 会一直吞掉手牌和牌河的点击（2026-11-02 卡死）。
	if c11_active and not bool(srv_state.get("card11_can", false)):
		_card11_close()
	if c11s2_active and not bool(srv_state.get("card11s2_can", false)):
		_card11s2_close()
	if pofa_active and not pofa_disc_stage and String(srv_state.get("pofa_stage", "")) == "":
		_pofa_close()
	# 国标 / 一定和牌：服务端已经不允许了（被别的窗口推进 / 已经打过了）就收起面板
	if guobiao_selecting and not bool(srv_state.get("guobiao_can", false)):
		_gb_close()
	if yiding_selecting and not bool(srv_state.get("yiding_can", false)):
		_yd_close()
	# 换牌面板：不是我的出牌回合了（被别的窗口推进 / 已经打完）就收起
	if swap_panel.active and (String(srv_state.get("phase", "")) != "discard"
			or int(srv_state.get("turn", -1)) != my_seat):
		_swap_close()
	# 一发：已经打过了 / 不满足条件了 → 收起
	if c24_panel.active and not bool(srv_state.get("c24_can", false)):
		c24_panel.close()
	# 宝牌的集合：这笔询问已经结束了就收起
	if c25b_panel.active and typeof(srv_state.get("c25s2_offer")) != TYPE_DICTIONARY:
		c25b_panel.close()
	# 向听：离开配牌阶段 → 收起（arm 阶段本地取消由点图标处理）
	if c30_panel.active and String(srv_state.get("phase", "")) != "deal_skill":
		c30_panel.close()
		c30_key = ""
	if c32_panel.active and String(srv_state.get("phase", "")) != "deal_skill":
		c32_panel.close()
		c32_key = ""
	if c43_panel.active and (String(srv_state.get("phase", "")) != "discard"
			or int(srv_state.get("turn", -1)) != my_seat):
		c43_panel.close()
	if c46_panel.active and (String(srv_state.get("phase", "")) != "discard"
			or int(srv_state.get("turn", -1)) != my_seat):
		c46_panel.close()
	if c45_panel.active and (String(srv_state.get("phase", "")) != "draw"
			or int(srv_state.get("turn", -1)) != my_seat):
		c45_panel.close()                        # 已经摸到牌 / 被别的窗口推进 → 收起
	if c33_panel.active and (String(srv_state.get("phase", "")) != "discard"
			or int(srv_state.get("turn", -1)) != my_seat):
		c33_panel.close()
	if c33s2_ui != null and is_instance_valid(c33s2_ui) \
			and (String(srv_state.get("phase", "")) != "discard"
				 or int(srv_state.get("turn", -1)) != my_seat):
		_c33s2_close()
	# 调包 / 命中：服务端已经不允许发动了（被别的窗口推进 / 已经打过）就收起
	if c27_panel.active:
		if c27_mode == "s1" and not srv_c27s1_can():
			_c27_close()
		elif c27_mode == "s2" and not srv_c27s2_can():
			_c27_close()
	# 宝牌运：确认态只在「轮到我切牌 + 技能还开着」时保留
	if c25_confirm_tile != "" and (not srv_c25_on()
			or String(srv_state.get("phase", "")) != "discard"
			or int(srv_state.get("turn", -1)) != my_seat):
		_c25_confirm_show(false)


# ── 计时器：显示 ────────────────────────────────────────────────────
func _tm_label_ensure() -> void:
	if _tm_label != null and is_instance_valid(_tm_label):
		return
	_tm_label = Label.new()
	_tm_label.name = "TurnTimer"
	_tm_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_tm_label.z_index = 400
	_tm_label.size = Vector2(150, 58)
	_tm_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	_tm_label.add_theme_font_size_override("font_size", 46)
	_tm_label.add_theme_color_override("font_color", Color(1.0, 0.85, 0.2, 1.0))
	_tm_label.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.9))
	_tm_label.add_theme_constant_override("outline_size", 6)
	add_child(_tm_label)


func _tm_visible(v: bool) -> void:
	if _tm_label == null or not is_instance_valid(_tm_label):
		return
	if _tm_label.visible != v:
		_tm_label.visible = v


# 贴在「手牌最右边那列按钮」的正上方（跟着手牌/副露走）
func _tm_label_pos() -> void:
	if _tm_label == null or not is_instance_valid(_tm_label):
		return
	var r := prompt_btn_rect(70.0 / 220.0)
	var want := Vector2(r.position.x + r.size.x - _tm_label.size.x, r.position.y - _tm_label.size.y - 4.0)
	if _tm_label.global_position.distance_to(want) > 0.5:
		_tm_label.global_position = want


# ── 计时器：判定「现在该给谁计时」 ──────────────────────────────────
func _tm_probe() -> Dictionary:
	if game_over or dealing or srv_busy:
		return {}
	if srv_state.is_empty() or not bool(srv_state.get("deal_done", false)):
		return {}
	var ph := String(srv_state.get("phase", ""))
	var rid := int(srv_state.get("round_id", -1))
	# ① 鸣牌询问：吃 / 碰 / 杠 / 荣
	if ph == "claim":
		var opts := srv_opts_of(srv_state)
		if not opts.is_empty():
			var claim = srv_state.get("claim")
			var key := "c29s1"
			if typeof(claim) == TYPE_DICTIONARY:
				key = "%s@%d" % [String((claim as Dictionary).get("tile", "")),
					int((claim as Dictionary).get("from", -1))]
			return {"mode": "claim", "fp": "%d|claim|%s|%s" % [rid, key, str(opts)]}
	# ② 技能询问：有现成的「跳过 / 开始」按钮亮着就算
	var b := _tm_skip_btn()
	if b != null:
		return {"mode": "ask", "fp": "%d|ask|%s|%d|%d" % [rid, String(b.name),
			int(srv_state.get("turn", -1)), int(srv_state.get("live_left", 0))], "btn": b}
	# ③ 该我打牌
	if ph == "discard" and int(srv_state.get("turn", -1)) == my_seat:
		return {"mode": "discard",
			"fp": "%d|discard|%d|%d" % [rid, int(srv_state.get("turn", -1)), display_tiles().size()]}
	return {}


# 现成的「跳过 / 开始」按钮（和 _sync_prompt_btns 同一批；没选牌时点它 = 跳过）
func _tm_skip_btn() -> TextureButton:
	var cand: Array = [deal_skip_btn, future_ask_btn, pofa_btn, hs_btn, sf_btn, zl_btn,
		dy_btn, c25_btn, board_start_btn, c09_btn, c10_btn, c11_btn, c11s2_btn,
		gb_btn, yd_btn, oracle_start_btn, wind_start_btn, flow_start_btn,
		sw_start_btn, sw_hand_btn, c05_start_btn, c05_hide_btn, c41_pick_btn,
		c30_panel.start_btn, c32_panel.start_btn]
	for x in cand:
		var b := x as TextureButton
		if b != null and is_instance_valid(b) and b.visible and b.is_visible_in_tree():
			return b
	return null


# 玩家已经在选牌了？（这种时候绝不替他确认/跳过，只把时间续上）
func _tm_any_picks() -> bool:
	if hand_pick != null and int(hand_pick.count()) > 0:
		return true
	var panels: Array = [swap_panel, press_panel, ym_panel, c24_panel, c25b_panel, c27_panel,
		c30_panel, c32_panel, c33_panel, c43_panel, c45_panel, c46_panel]
	for p in panels:
		if p == null or not is_instance_valid(p):
			continue
		var pk = p.get("picks")
		if typeof(pk) == TYPE_ARRAY and (pk as Array).size() > 0:
			return true
	return false


# ── 计时器：到点 ────────────────────────────────────────────────────
func _tm_fire(mode: String, cur: Dictionary) -> void:
	if _tm_any_picks():
		_tm_left = TM_SEC                 # 正在选牌 → 再给 35 秒，不替他确认
		return
	_tm_sent = true
	_tm_fire_ms = Time.get_ticks_msec()
	_tm_visible(false)
	if mode == "claim":
		_dev_log("[TIMER] 鸣牌询问超时 → 自动过")
		_toast("35 秒到：自动过")
		_on_action_button("pass")
		return
	if mode == "ask":
		var b = cur.get("btn")
		if b is TextureButton and is_instance_valid(b) and (b as TextureButton).visible:
			_dev_log("[TIMER] 技能询问超时 → 按 %s" % String((b as TextureButton).name))
			_toast("35 秒到：自动跳过这次询问")
			(b as TextureButton).emit_signal("pressed")
		return
	_tm_auto_discard()


# 到点强制摸切
func _tm_auto_discard() -> void:
	var t := ""
	var dr = srv_state.get("drawn")
	if dr != null and String(dr) != "":
		t = String(dr)
	if t == "":
		var h: Array = srv_state.get("hand", [])
		if not h.is_empty():
			t = String(h[h.size() - 1])
	if t == "" or not srv_can_discard_with(t):
		t = srv_legal_tile(srv_state, "discard")
	if t == "":
		return
	_dev_log("[TIMER] 出牌超时 → 摸切 %s" % t)
	_toast("35 秒到：自动摸切")
	srv_act("discard", {"tile": t})


# ── 计时器：每帧 ────────────────────────────────────────────────────
func _tm_tick(delta: float) -> void:
	var cur := _tm_probe()
	var mode := String(cur.get("mode", ""))
	if mode == "":
		if _tm_mode != "":
			_tm_mode = ""
			_tm_fp = ""
			_tm_left = 0.0
			_tm_sent = false
		_tm_visible(false)
		return
	var fp := String(cur.get("fp", ""))
	if fp != _tm_fp:
		_tm_fp = fp
		_tm_mode = mode
		_tm_left = TM_SEC
		_tm_sent = false
		_tm_retry = 0
	if _tm_sent:
		_tm_visible(false)                # 已经发过 → 等 state 回来再重置
		# 服务端 4 秒还没动（请求丢了 / 被拒）→ 最多再补 2 次，免得这个回合永久卡住
		if _tm_retry < 2 and Time.get_ticks_msec() - _tm_fire_ms > 4000:
			_tm_retry += 1
			_tm_sent = false
			_tm_left = 3.0
		return
	_tm_left = maxf(0.0, _tm_left - delta)
	_tm_label_ensure()
	_tm_visible(true)
	_tm_label.text = str(int(ceil(_tm_left)))
	_tm_label_pos()
	if _tm_left <= 0.0:
		_tm_fire(mode, cur)


func _process(delta: float) -> void:
	# 播报期间牌桌是静态的：只留租约/结算确认，其余 tick/sync/轮询全跳过（不然每帧一堆活抢帧）
	if _win_intro_running or _win_panel_visible():
		_lease_tick(delta)
		if game_over:
			_result_confirm_tick(delta)
		return
	_lease_tick(delta)
	if game_over:
		_result_confirm_tick(delta)
	_match_tick(delta)
	_skill_panel_stale_close()
	_cg_stale_close()
	_sync_c05_dead_buttons()     # Card05 王牌点击区：位置跟牌墩走
	_refresh_start_btn_kinds()  # 先定「跳过/确认」状态（决定贴图 + 是否放大）
	_sync_prompt_btns()          # 再排版：贴着手牌右边，确认态放大 1.5 倍且底部对齐
	swap_panel.tick()            # 通用面板自己贴位置
	_sync_chow_choices()         # 「吃」的选搭子面板跟着手牌走
	ym_panel.tick()
	press_panel.tick()
	c25b_panel.tick()            # 宝牌的集合
	c27_panel.tick()             # 调包 / 命中
	c30_panel.tick()             # 向听
	c32_panel.tick()             # 新手运
	c33_panel.tick()             # 染手
	c43_panel.tick()             # NO MISS
	c45_panel.tick()             # 神境
	c46_panel.tick()             # 恶听
	c24_panel.tick()             # 一发
	_hud_tick(delta)
	_round_hud_tick()
	_tm_tick(delta)
	# ★ 先收上一次「非阻塞轮询」的结果（公网往返 100~300ms 也不冻画面）
	if srv != null and srv.has_method("bg_poll") and bool(srv.call("bg_busy")):
		var rb: Dictionary = srv.call("bg_poll")
		if not rb.is_empty():
			var rr := _srv_handle(rb)
			if not rr.is_empty():
				if typeof(rr.get("humans")) == TYPE_ARRAY:
					srv_humans = rr.get("humans")
				if not bool(rr.get("same", false)):
					srv_apply_state(rr.get("state"), rr.get("events"))
				# 半庄打完了 → 弹终局名次播报（不管是谁点下的最后一下确认）
				if bool(rr.get("match_finished", false)) and not match_active:
					_show_match_final(rr.get("final_rank", []), rr.get("confirmed", []))
	# ★ 长连接推送：服务端状态一变就发新的 ver 过来 → 立刻拉一次，不用等轮询周期
	if srv != null and srv.has_method("push_tick"):
		if _push_seat_sent != my_seat:          # ★ 每帧重发纯属浪费，座位变了才发
			_push_seat_sent = my_seat
			srv.call("push_set_seat", my_seat)
		var pr: Dictionary = srv.call("push_tick")
		if not pr.is_empty():
			var pv := String(pr.get("ver", ""))
			var pst = pr.get("state")
			if typeof(pst) == TYPE_DICTIONARY and not (pst as Dictionary).is_empty():
				# 推送里直接带了「按我这个座位裁好」的整份 state → 不用再拉
				if pv != "":
					_state_ver = pv
				_push_n += 1
				_apply_n += 1
				srv_apply_state(pst, [])
			elif pv != "" and pv != _state_ver:
				poll_accum = 99999.0        # 只推了版本号 → 被叫醒，自己拉一次
	if game_over or srv_busy:
		return
	if _prompt_blocked():
		# 有人在等回答：不推进对局，但必须继续问 state ——
		# 否则「询问结束」这一刻永远看不到，界面就永久停在旧状态（看起来像卡死）。
		poll_accum += delta
		if poll_accum >= POLL_SEC:
			poll_accum = 0.0
			if not (srv != null and srv.has_method("bg_send")
					and bool(srv.call("bg_send", _srv_shape({"op": "state", "seat": my_seat})))):
				var rq := srv_request({"op": "state", "seat": my_seat})
				if not rq.is_empty():
					srv_apply_state(rq.get("state"), [])
		return
	# 还卡在配牌（比如推进的那个窗口被关了）→ 该我接手就接着推
	if not dealing and not srv_state.is_empty() and not bool(srv_state.get("deal_done", true)):
		if _is_deal_driver():
			dealing = true
			game_phase = PHASE_DEAL
			_deal_step()
			return
		# ★ 不是推进者也要照常轮询：配牌的每一步都是推进者发给服务端的，
		#   不问就看不到自己发到的牌（以前这里直接 return，结果别的窗口一直停在配牌前那一帧）
	if dealing:
		return                                        # 我是推进者，正在一步步发牌，不用轮询
	var others_here := srv_humans.size() > 1          # 这局还有别的窗口在操作
	var deal_running := not bool(srv_state.get("deal_done", true))
	var period := POLL_SEC if (waiting_for_others or deal_running or others_here) else POLL_IDLE_SEC
	# 推送长连接活着 → 轮询退化成「保险丝」，放慢到 2 秒（公网流量/手机电量都省）
	if srv != null and srv.has_method("push_ok") and bool(srv.call("push_ok")):
		period = maxf(period, 2.0)
	if Time.get_ticks_msec() < _poll_fast_until:
		period = 0.10                     # 刚点完动作：0.1s 一次，结算一到就播
	poll_accum += delta
	if poll_accum < period:
		return
	poll_accum = 0.0
	# 配牌技能窗口 / 鸣牌窗口（我这边已经没有可选项）= 用 op=step 轮询：
	# 服务端会顺手把「没人在操作」的座位跳过。
	#   只问 op=state 的话，这个窗口永远结算不了（别人都不动）→ 界面卡死。
	var phase_now := String(srv_state.get("phase", ""))
	var i_owe_nothing := phase_now == "claim" and srv_opts_of(srv_state).is_empty()
	if phase_now == "deal_skill" or i_owe_nothing:
		if not srv_busy:
			srv_busy = true
			_srv_step_once()
		return
	# 轮询用非阻塞：发出去立刻返回，下一帧再收（否则每 0.35s 按住一整个 RTT）
	if srv != null and srv.has_method("bg_send") \
			and bool(srv.call("bg_send", _srv_shape({"op": "state", "seat": my_seat}))):
		return
	var r := srv_request({"op": "state", "seat": my_seat})
	if r.is_empty():
		return
	if typeof(r.get("humans")) == TYPE_ARRAY:
		srv_humans = r.get("humans")
	srv_apply_state(r.get("state"), [])


# 空格 = 摸牌；摸到之后点右键 = 把刚摸的那张直接切出去（摸切）
# 用 _input 而不是 _unhandled_input：这样鼠标停在手牌/按钮上时右键也一样有效
func _input(event: InputEvent) -> void:
	# 输入框（例如猜番数）有焦点时，所有调试热键都不响应 ——
	# 否则 _input 比输入框先跑，1~4 会被「切座位」吃掉，数字根本打不进去。
	var _focus := get_viewport().gui_get_focus_owner() if get_viewport() != null else null
	if _focus is LineEdit or _focus is TextEdit:
		return
	# 右上角「四行信息」开关（图标是 Sprite2D，自己算点击）
	var _mb := (event as InputEventMouseButton)
	if _mb != null and _mb.pressed and _mb.button_index == MOUSE_BUTTON_LEFT:
		if _round_info_hit(_mb.position):
			_round_info_toggle()
			get_viewport().set_input_as_handled()
			return
	var _k := (event as InputEventKey)
	if _k != null and _k.pressed and not _k.echo:
		if _k.keycode == KEY_F3:
			_hud_show = not _hud_show
			get_viewport().set_input_as_handled()
			return
		if _k.keycode == KEY_F11:
			var _m := DisplayServer.window_get_mode()
			DisplayServer.window_set_mode(
				DisplayServer.WINDOW_MODE_WINDOWED
				if _m == DisplayServer.WINDOW_MODE_FULLSCREEN
				else DisplayServer.WINDOW_MODE_FULLSCREEN)
			get_viewport().set_input_as_handled()
			return
	if event is InputEventKey:
		var k0 := event as InputEventKey
		if k0.pressed and not k0.echo:
			# 1/2/3/4：本窗口认领几号位；F2：开新的一局
			if k0.keycode >= KEY_1 and k0.keycode <= KEY_4:
				# 手动切座位：这里才强占（调试用：想坐哪家就坐哪家）
				srv_join_seat(int(k0.keycode - KEY_1), false, true, true)
				get_viewport().get_viewport().set_input_as_handled()
				return
			if k0.keycode == KEY_F2:
				srv_new_round()
				get_viewport().get_viewport().set_input_as_handled()
				return
			# ── 手牌右侧按钮微调（**只在编辑器里**；导出的 exe 没有这套热键）──
			if _btn_tune_dev() and k0.keycode == KEY_F9:
				_btn_tune_report()
				get_viewport().get_viewport().set_input_as_handled()
				return
			if _btn_tune_dev() and k0.keycode == KEY_F10:
				_btn_tune_mode = not _btn_tune_mode
				_toast("按钮微调模式：%s（方向键挪，F9 看数值）"
					% ("开" if _btn_tune_mode else "关"))
				get_viewport().get_viewport().set_input_as_handled()
				return
			if _btn_tune_dev() and k0.keycode == KEY_F12:
				_btn_tune_load()
				_btn_tune_report()
				get_viewport().get_viewport().set_input_as_handled()
				return
			if _btn_tune_dev() and (k0.ctrl_pressed or _btn_tune_mode):
				var step := 10.0 if k0.shift_pressed else 1.0
				var d := Vector2.ZERO
				match k0.keycode:
					KEY_LEFT: d = Vector2(-step, 0)
					KEY_RIGHT: d = Vector2(step, 0)
					KEY_UP: d = Vector2(0, -step)
					KEY_DOWN: d = Vector2(0, step)
				if d != Vector2.ZERO:
					prompt_btn_offset += d               # 确认 / 跳过 一起动
					_btn_tune_save()
					_btn_tune_report()
					get_viewport().get_viewport().set_input_as_handled()
					return
				if k0.keycode == KEY_0:
					_btn_tune_reset()
					_btn_tune_report()
					get_viewport().get_viewport().set_input_as_handled()
					return
	if game_over:
		return
	if event is InputEventKey:
		var key := event as InputEventKey
		if key.pressed and not key.echo and key.keycode == KEY_SPACE:
			draw_tile()
			get_viewport().get_viewport().set_input_as_handled()
	elif event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		if mb.pressed and mb.button_index == MOUSE_BUTTON_RIGHT:
			if board_ui != null:
				_board_close()                  # 画板开着：右键 = 取消
			elif sw_stage != "":
				pass                            # 南风流程中：右键不做任何事
			elif c05_active:
				_c05_close(true)                # 策略：右键 = 放弃这次换牌
			elif c05_hide_active:
				pass                            # 盖牌必须选完
			elif wind_active:
				pass                            # 自风换牌中：右键不做任何事
			elif String(srv_state.get("phase", "")) == "wind_swap":
				pass                            # 等别人把自风换走
			elif flow_active:
				pass                            # 风神换牌中：右键不做任何事
			elif press_panel.active:
				if press_panel.allow_cancel:
					_press_close()              # 压制进行中：右键 = 取消
			elif swap_panel.active:
				if swap_panel.allow_cancel:
					_swap_close()               # 换牌进行中：右键 = 取消
			else:
				quick_discard_drawn()
			get_viewport().get_viewport().set_input_as_handled()


# 切出刚摸到的那张牌（还没摸牌时什么都不做）
func quick_discard_drawn() -> void:
	if game_over or drawn_tile == "":
		return
	discard_tile(drawn_slot())


# ────────────────────────── 三家的回合（B/C/D） ──────────────────────────

# 初始化三家：各发 13 张、量出各家排列方向与间距、建牌河容器、准备好「摸到的那张」的形象
func _setup_opponents() -> void:
	tapai = get_node_or_null(TAPAI_NODE)
	if tapai == null:
		push_warning("main.gd: 找不到 " + TAPAI_NODE + "（三家手牌）")
		return
	hand_show.setup(self, tapai)
	var pile_parent: Node = fengpan.get_parent() if fengpan != null else self
	var vp := get_viewport_rect().size
	_layout_opp_hands()                                  # 先按间距接口把手牌列排好
	for who in OPP_ORDER:
		var hand: Array[String] = []          # 开局 0 张，由配牌阶段发
		opp_hands[who] = hand
		opp_drawn[who] = ""
		opp_discards[who] = []
		opp_meld_counts[who] = 0
		# 各家副露从「自己最靠外、且在自己右手边」的那个角开始摆
		opp_meld_anchor[who] = {
			"B": Vector2(0.0, vp.y), "C": Vector2.ZERO, "D": Vector2(vp.x, 0.0)
		}.get(who, Vector2.ZERO)
		# 牌河容器：场景里的 UI/Pile/<谁>（里面预置了 24 个格子）；没有就现场新建一个
		var cont := pile_parent.get_node_or_null("Pile/" + who) as Node2D
		if cont == null:
			cont = Node2D.new()
			cont.name = who + "_discard"
			pile_parent.add_child(cont)
		opp_discard_containers[who] = cont
		# 排列方向 = 从第 12 张指向第 13 张（直接从节点量出来，跟着你的摆位走）
		var a := tapai.get_node_or_null(who + "12") as Node2D
		var b := tapai.get_node_or_null(who + "13") as Node2D
		if a == null or b == null:
			continue
		opp_step[who] = b.position - a.position
		# 「摸到的那张」：B 放手牌下侧、C 放右侧、D 放上侧（复制那一端的牌，样式与手牌一致）
		var anchor_info: Array = OPP_DRAWN_ANCHOR.get(who, ["13", 1.0])
		var anchor := tapai.get_node_or_null(who + str(anchor_info[0])) as Node2D
		if anchor == null:
			continue
		opp_drawn_sign[who] = float(anchor_info[1])
		var vis: Node2D = anchor.duplicate()
		vis.name = who + "_drawn"
		vis.position = anchor.position + opp_step[who] * float(anchor_info[1]) * (1.0 + OPP_DRAWN_GAP_RATIO)
		vis.visible = false
		tapai.add_child(vis)
		opp_drawn_nodes[who] = vis
	refresh_discards()


# ★ 这里原来有 opp_draw()：旧本地对局里「替别家从牌山摸一张」。
#   服务端接管后已经没有调用点，而且它会发 op=draw（已删除），一并去掉。


# 那家摸完 OPP_DRAW_DELAY 秒后自动打出 → 手牌回到 13 张
func _opp_auto_discard(who: String) -> void:
	# ★ 同上：自己的座位不许走「对手自动打牌」这条
	if who == who_of_seat(my_seat):
		return
	if game_over:
		return
	if not opp_pending or opp_drawn.get(who, "") == "":
		return
	opp_pending = false
	# 测试用：把这张换成「下家能吃」的牌，好把「其他家吃」的显示跑出来
	if OPP_CHOW_TEST:
		var feed_to := next_player_name(who)
		if feed_to != "me" and opp_meld_counts.get(feed_to, 0) < OPP_CHOW_TEST_MAX:
			var feed := find_feed_tile(opp_hands.get(feed_to, []))
			if feed != "":
				opp_drawn[who] = feed
	opp_discards[who].append(opp_drawn[who])
	opp_drawn[who] = ""
	_show_opp_drawn(who, false)
	_after_opp_discard(who)


# 三家手牌按接口重排：
#   · 大小 = 场景里的基准 × 该家的大小接口（opp_hand_scale_b / _c / _d）
#   · 位置 = 场景里的基准中心 + 各自的位移接口；上下家再按 opp_hand_pitch 等距排开（整列居中）
# 基准只在第一次量一次，所以反复调用不会越挪越远。
func _layout_opp_hands() -> void:
	if tapai == null:
		return
	for who in ["B", "C", "D"]:
		var nodes: Array[Node2D] = []
		for i in range(1, OPP_HAND_COUNT + 1):
			var n := tapai.get_node_or_null("%s%02d" % [who, i]) as Node2D
			if n != null:
				nodes.append(n)
		if nodes.size() < 2:
			continue
		if not opp_hand_base.has(who):
			var items: Array = []
			var c := Vector2.ZERO
			for n in nodes:
				items.append({"pos": n.position, "scale": n.scale})
				c += n.position
			c /= float(nodes.size())
			opp_hand_base[who] = {"center": c, "items": items}
		var info: Dictionary = opp_hand_base[who]
		var base_center: Vector2 = info["center"]
		var items: Array = info["items"]
		var one_size: float = _opp_scale(who)
		var center: Vector2 = base_center + _opp_offset(who)
		for i in range(nodes.size()):
			var it: Dictionary = items[i]
			if it["scale"] is Vector2:
				nodes[i].scale = (it["scale"] as Vector2) * one_size
				nodes[i].position = center + ((it["pos"] as Vector2) - base_center) * one_size
		# 上下家：按间距接口等距排开（保持整列居中）；对家 C 保持场景里的排法
		if who != "C":
			var dir := Vector2(0.0, -1.0) if who == "B" else Vector2(0.0, 1.0)
			var mid := (nodes.size() - 1) * 0.5
			var pitch: float = opp_hand_pitch * one_size
			for i in range(nodes.size()):
				nodes[i].position = center + dir * ((float(i) - mid) * pitch)
		# 排列方向也跟着重算（「摸到的那张」靠它定位）
		var a := tapai.get_node_or_null(who + "12") as Node2D
		var b := tapai.get_node_or_null(who + "13") as Node2D
		if a != null and b != null:
			opp_step[who] = b.position - a.position
		# 「摸到的那张」跟着一起缩放 / 挪位
		var dn = opp_drawn_nodes.get(who, null)
		if dn != null and not opp_hands.get(who, []).is_empty() and items.size() > 0:
			var anchor_info: Array = OPP_DRAWN_ANCHOR.get(who, ["13", 1.0])
			var ai: int = clampi(int(str(anchor_info[0])) - 1, 0, items.size() - 1)
			var it2: Dictionary = items[ai]
			if it2["scale"] is Vector2:
				dn.scale = (it2["scale"] as Vector2) * one_size
			_refresh_opp_hand(who)


# 三家的大小接口
func _opp_scale(who: String) -> float:
	match who:
		"B":
			return opp_hand_scale_b
		"C":
			return opp_hand_scale_c
		"D":
			return opp_hand_scale_d
	return 1.0


# 三家的位移接口
func _opp_offset(who: String) -> Vector2:
	match who:
		"B":
			return opp_offset_b
		"C":
			return opp_offset_c
		"D":
			return opp_offset_d
	return Vector2.ZERO


# 某家打完一张之后：刷新牌河 → 轮转 → 亮吃/碰按钮 → 其他家的吃
func _after_opp_discard(who: String) -> void:
	refresh_discards()                   # 打出的牌进他家牌河
	_next_turn()
	hide_chow_panel()
	# 其他家的吃（OPP_CHOW_TEST 打开时才自动喂牌 + 吃下）
	if OPP_CHOW_TEST:
		var nxt := next_player_name(who)
		if nxt != "me" and opp_meld_counts.get(nxt, 0) < OPP_CHOW_TEST_MAX:
			if do_opp_chow(nxt, who, last_opp_discard(who)):
				hide_chow_panel()       # 这张已经被别人吃了，我的吃/碰按钮作废
				_schedule_opp_chow_discard(nxt)


func _show_opp_drawn(who: String, on: bool) -> void:
	var node = opp_drawn_nodes.get(who, null)
	if node != null:
		node.visible = on


# 逆时针轮转：我 → D → C → B → 我
func _next_turn() -> void:
	turn_index = (turn_index + 1) % (OPP_ORDER.size() + 1)


# 按钮上显示现在轮到谁摸（方便看出「单击按钮让下一家摸牌」）


# ────────────────────────── 吃（吃上家 B 打出的牌） ──────────────────────────

const CHOW_GROUP_GAP := 30.0                 # 两组吃法之间的间隔
const CHOW_ABOVE_MARGIN := 20.0              # 吃法组离手牌上方的距离

var chi_groups := []                         # 当前可选的吃法：每组 = 两张牌的 id（按手牌顺序）
var chi_selecting := false                   # 已点吃、正在选组
var chi_select_container: Control            # 选组容器
var meld_container: Node2D                   # 已吃下的副露容器
var meld_count := 0                          # 已吃组数
var meld_left := -1.0                        # 上一组副露的左边界（下一组挨着它左边放）
var after_chi_discard := false               # 吃之后必须立刻切一张
var chi_used_tiles := []                     # 这次吃用的两张牌（切牌特判用）

# ── 加杠的第 4 张摆在哪一端 ──
#   我的主视角：加杠那 4 张里，第 4 张「竖直」摆在刻子的最左 / 最右
#   true = 最左（默认）   false = 最右
const KAKAN_TILE_AT_LEFT := true

#   其他三家：true = 摆到「离锚点远」的那端（锚点：B 左下 / C 左上 / D 右上）
#     B：远端在上 → 取 false，第 4 张落到下面（紧贴下侧）
#     C：远端在右 → 取 true （紧贴右侧）
#     D：远端在下 → 取 true （紧贴下侧）
const KAKAN_OPP_AT_FAR := {"B": false, "C": true, "D": true}


# ── 副露牌大小接口 ──
# 在「Main 节点的检查器」里直接改这个值即可；代码里也可以 main.meld_scale = 0.5
# 其他家的副露同样用这个值（想单独指定就调用 add_meld(tiles, 缩放比例)）
@export var meld_scale := 0.84

# ── 上下家（B/D）手牌列的间距 ──
# 在「Main 节点的检查器」里改这个值，运行时会立刻按新间距重新排列（手牌列保持居中）
@export var opp_hand_pitch := 62.0:
	set(v):
		opp_hand_pitch = maxf(v, 1.0)
		_layout_opp_hands()

# ── 暗杠素材 ──
# 正面图放在 槓 kan 文件夹：数字重复两遍 + 花色（3s 的杠 = 33s.png）；
# 5m/5s/5p 用 05X 那张（赤 5 版本），不用 55X。
const KAN_FACE_DIR := "res://Cailiao/mahjong_graphic/PNG 位图/默认风格 default style/槓 kan/"
const BACK_DIR := "res://Cailiao/mahjong_graphic/PNG 位图/默认风格 default style/背面 back/"
const KAN_BUTTON_POS := Vector2(350, 20)
const MINKAN_BUTTON_POS := Vector2(460, 20)
const KAKAN_BUTTON_POS := Vector2(570, 20)
var ankan_tile := ""
var minkan_who := ""
var minkan_tiles := []
var kakan_tile := ""
var meld_list := []          # 已完成的副露（喂给 redraw_melds 重画用）
var menzen := true           # 门前清：吃/碰/明杠/加杠会破，暗杠不破


# 取牌的数字（0m/0s/0p 按 5 算；字牌返回 0）
func tile_number(tile_id: String) -> int:
	var c := tile_id.substr(0, 1)
	if c >= "0" and c <= "9":
		var n := int(c)
		return 5 if n == 0 else n
	return 0


# 取牌的花色（数牌 "m"/"s"/"p"；字牌 ""）
func tile_suit(tile_id: String) -> String:
	if tile_id.length() == 2 and tile_id.substr(1, 1) in ["m", "s", "p"]:
		return tile_id.substr(1, 1)
	return ""


# 手牌里「某花色 + 某数值」的下标
func hand_indexes_with_value(suit: String, num: int) -> Array:
	var out := []
	for i in range(hand_tiles.size()):
		if tile_suit(hand_tiles[i]) == suit and tile_number(hand_tiles[i]) == num:
			out.append(i)
	return out


# 找出所有吃法：返回 [[id_a, id_b], ...]。
# 按 id 去重 → 两张一样的 5s 只算一种；而 0s 与 5s 是不同 id，会各成一组（按你说的一样分两组）
func find_chow_groups(discard_id: String) -> Array:
	var out := []
	var suit := tile_suit(discard_id)
	if suit == "":
		return out
	var n := tile_number(discard_id)
	for pat in [[n - 2, n - 1], [n - 1, n + 1], [n + 1, n + 2]]:
		var a: int = pat[0]
		var b: int = pat[1]
		if a < 1 or b > 9:
			continue
		for x in hand_indexes_with_value(suit, a):
			for y in hand_indexes_with_value(suit, b):
				if x == y:
					continue
				var pair := [hand_tiles[x], hand_tiles[y]]
				pair.sort()
				if not out.has(pair):
					out.append(pair)
	return out


func last_opp_discard(who: String) -> String:
	var pile: Array = opp_discards.get(who, [])
	if pile.is_empty():
		return ""
	return pile[pile.size() - 1]


# 收起「吃的选搭子面板」（吃到 / 窗口关闭 / 新一局 / 点过 都走这里）
# ※ 以前这里还有一套「自己建吃按钮 + 本地 find_chow_groups」的流程，服务端接管后
#   已经不可达（_after_opp_discard 只服务旧的本地对局），已整块删掉。
func hide_chow_panel() -> void:
	chi_selecting = false
	if tile_pick_tag == "c40b":
		return                      # 同盟的面板别被「吃」的清理逻辑误杀
	clear_chow_choices()


# 「吃」：多于一种搭子 → 两两摆到手牌上方让玩家挑；只有一种就直接吃
# ── 鸣牌提示：能被吃 / 碰 / 杠的牌也挂上现成的彩框（用户口径 2026-11-01）──
#   候选牌**不问服务端**：claim.options 里已经带好 choices（chi=两张、pon=两张、minkan=三张）
var _claim_frame_on := {}          # entity_id -> true（当前被我们挂了框的牌）


func _claim_norm_kind(t: String) -> String:
	var s := t.strip_edges()
	if s.length() == 2 and s[0] == "0":
		return "5" + s[1]                  # 赤五：0m / 0p / 0s 归一成 5m / 5p / 5s
	return s


func _claim_kinds_of(st: Dictionary) -> Array:
	var out: Array = []
	var claim = st.get("claim")
	if typeof(claim) != TYPE_DICTIONARY:
		return out
	if bool((claim as Dictionary).get("answered", false)):
		return out
	for o in ((claim as Dictionary).get("options", []) as Array):
		if typeof(o) != TYPE_DICTIONARY:
			continue
		var act := String((o as Dictionary).get("action", ""))
		if act != "chi" and act != "pon" and act != "minkan":
			continue
		for ch in ((o as Dictionary).get("choices", []) as Array):
			if typeof(ch) != TYPE_ARRAY:
				continue
			for x in (ch as Array):
				var k := _claim_norm_kind(String(x))
				if k != "" and not out.has(k):
					out.append(k)
	return out


func _claim_is_river_form(f: String) -> bool:
	return f == "river" or f == "rot" or f == "back" or f == "back_rot"


func _claim_frames_clear() -> void:
	if tile_bank == null or _claim_frame_on.is_empty():
		return
	for q in tile_bank.all_pieces():
		var tp := q as TilePiece
		if tp != null and _claim_frame_on.has(tp.entity_id):
			tp.set_claim_frame(false)
	_claim_frame_on.clear()


func _claim_frames_sync(st: Dictionary) -> void:
	var want := _claim_kinds_of(st)
	# 选牌面板开着 / 已经结束 → 一律不挂（免得两种框混在一起）
	if want.is_empty() or tile_bank == null or game_over 			or (hand_pick != null and bool(hand_pick.active)):
		_claim_frames_clear()
		return
	var claim = st.get("claim")
	var from_seat := -1
	if typeof(claim) == TYPE_DICTIONARY:
		from_seat = int((claim as Dictionary).get("from", -1))
	var keep := {}
	var river_pick: TilePiece = null
	var river_best := -1
	for q in tile_bank.all_pieces():
		var tp := q as TilePiece
		if tp == null or not tp.visible:
			continue
		if tp.form == "hand" and want.has(_claim_norm_kind(tp.kind)):
			keep[tp.entity_id] = true
		elif _claim_is_river_form(tp.form) and from_seat >= 0 and tp.river_seat == from_seat:
			# 牌河里「刚打出来的那张」= 这一家牌河里 seq 最大的
			if tp.discard_seq > river_best:
				river_best = tp.discard_seq
				river_pick = tp
	if river_pick == null and from_seat >= 0 and typeof(claim) == TYPE_DICTIONARY:
		# 兜底：牌河里 seq 没写进来（旧渲染路径）→ 按「牌种相同」找这一家最靠后的一张
		var want_kind := _claim_norm_kind(String((claim as Dictionary).get("tile", "")))
		var best2 := -1
		for q3 in tile_bank.all_pieces():
			var tp3 := q3 as TilePiece
			if tp3 == null or not tp3.visible or tp3.river_seat != from_seat:
				continue
			if not _claim_is_river_form(tp3.form):
				continue
			if _claim_norm_kind(tp3.kind) != want_kind:
				continue
			if tp3.discard_seq > best2:
				best2 = tp3.discard_seq
				river_pick = tp3
	if river_pick != null:
		keep[river_pick.entity_id] = true
	# 只动有变化的牌（设成同值会立刻 return，不会每份 state 重建描边）
	for q2 in tile_bank.all_pieces():
		var tp2 := q2 as TilePiece
		if tp2 == null:
			continue
		var on := keep.has(tp2.entity_id)
		if on or _claim_frame_on.has(tp2.entity_id):
			tp2.set_claim_frame(on)
	_claim_frame_on = keep


func _chow_choose() -> void:
	if game_over:
		return
	var groups := _chow_groups_from_state()
	if groups.is_empty():
		return                            # 鸣牌窗口已经关了（chi_groups 是旧缓存，绝不能用）
	if groups.size() == 1:
		if not srv_c29s1_ask().is_empty():
			_c29s1_op("c29s1_chi")            # 只有一种吃法 → 服务端取 choices[0]
			return
		# ★ 只有「服务端确实开了鸣牌窗口」才自动吃（避免状态串了时莫名吃一张）
		if typeof(srv_state.get("claim")) != TYPE_DICTIONARY:
			return
		if (groups[0] as Array).size() != 2:
			return
		srv_act("chi")
		return
	chi_groups = groups
	chi_selecting = true
	show_chow_choices()
	_sync_chow_choices()
	_toast("吃：选一组搭子")


# 服务端下发的吃法：state.claim.options 里 action="chi" 的 choices
func _chow_groups_from_state() -> Array:
	var out: Array = []
	var ask := srv_c29s1_ask()
	if not ask.is_empty():
		for ch in ((ask as Dictionary).get("choices", []) as Array):
			var g: Array = []
			for t in (ch as Array):
				g.append(String(t))
			if g.size() == 2:
				out.append(g)
		return out
	var claim = srv_state.get("claim")
	if typeof(claim) != TYPE_DICTIONARY:
		return out
	for o in ((claim as Dictionary).get("options", []) as Array):
		if typeof(o) != TYPE_DICTIONARY or String(o.get("action", "")) != "chi":
			continue
		for ch in ((o as Dictionary).get("choices", []) as Array):
			var g: Array = []
			for t in (ch as Array):
				g.append(String(t))
			if g.size() == 2:
				out.append(g)
	return out


# ── 通用「从几种搭子里挑一组」面板 ──────────────────────────────────
# 就是「吃」那一套：**手牌上方一排牌面候选**，点哪组就选哪组。
# 吃（chi）和【同盟】(40S2 多组打法) 共用这一套 —— 不再自己做左上角列表。
#   groups: [{"tiles": ["5p","5p"], "data": <任意>}, ...]
var tile_pick_container: Control = null
var tile_pick_groups: Array = []
var tile_pick_cb: Callable = Callable()
var tile_pick_alive: Callable = Callable()
var tile_pick_tag := ""            # "chi" / "c40b" —— 清理时要分清楚是谁的
var tile_pick_anchor: Callable = Callable()   # 可选：返回左上角（全局坐标）；空 = 摆在自己手牌上方


func _tile_pick_show(groups: Array, cb: Callable, alive: Callable,
		tag: String = "chi", anchor: Callable = Callable()) -> void:
	_tile_pick_clear()
	if groups.is_empty():
		return
	tile_pick_groups = groups.duplicate(true)
	tile_pick_cb = cb
	tile_pick_alive = alive
	tile_pick_tag = String(tag)
	tile_pick_anchor = anchor
	tile_pick_container = Control.new()
	tile_pick_container.name = "TilePick"
	tile_pick_container.mouse_filter = Control.MOUSE_FILTER_IGNORE
	# 副露/对面手牌这些 Node2D 用的是「z_index = 自己的 y」（见 _render_opp_*），
	# 屏幕下半部分的 y 有八九百 → z_index 就是八九百，会把选搭子面板整个盖住。
	# 面板必须压在它们上面，否则玩家只看得到露出的一两张牌。
	tile_pick_container.z_index = 1200
	add_child(tile_pick_container)
	tile_pick_container.global_position = Vector2.ZERO
	var w := tile_size.x
	var h := tile_size.y
	for gi in range(tile_pick_groups.size()):
		var tiles: Array = (tile_pick_groups[gi] as Dictionary).get("tiles", [])
		var n := maxi(tiles.size(), 1)
		var btn := Button.new()
		btn.flat = true
		btn.focus_mode = Control.FOCUS_NONE
		btn.mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
		btn.custom_minimum_size = Vector2(float(n) * w, h)
		btn.size = Vector2(float(n) * w, h)
		btn.z_index = 15
		var empty := StyleBoxEmpty.new()
		for st in ["normal", "hover", "pressed", "focus", "disabled"]:
			btn.add_theme_stylebox_override(st, empty)
		for k in range(tiles.size()):
			var vis := _make_tile_visual(String(tiles[k]))
			if vis != null:
				vis.position = Vector2((k + 0.5) * w, h * 0.5)
				btn.add_child(vis)
		btn.pressed.connect(_tile_pick_do.bind(gi))
		tile_pick_container.add_child(btn)
	_tile_pick_sync()


# 每帧跟着手牌走（手牌位置/缩放变了也不会飘）；来源没了就自动收起
func _tile_pick_sync() -> void:
	if tile_pick_container == null or not is_instance_valid(tile_pick_container):
		return
	if tile_pick_alive.is_valid() and not bool(tile_pick_alive.call()):
		_tile_pick_clear()
		return
	var w := tile_size.x
	var h := tile_size.y
	var x0 := hand_container.global_position.x
	var y := hand_container.global_position.y - CHOW_ABOVE_MARGIN - h
	if tile_pick_anchor.is_valid():
		var ap = tile_pick_anchor.call()
		if typeof(ap) == TYPE_VECTOR2 and (ap as Vector2) != Vector2.INF:
			x0 = (ap as Vector2).x
			y = (ap as Vector2).y
	# 别把面板摆到屏幕外（竖排手牌是「一列」，锚点在列底时会顶到边）
	var vp := get_viewport_rect().size
	x0 = clampf(x0, 8.0, maxf(8.0, vp.x - 8.0))
	y = clampf(y, 8.0, maxf(8.0, vp.y - h - 8.0))
	var x := x0
	for i in range(tile_pick_container.get_child_count()):
		var b := tile_pick_container.get_child(i) as Control
		if b == null or not is_instance_valid(b):
			continue
		var tiles: Array = (tile_pick_groups[i] as Dictionary).get("tiles", []) \
			if i < tile_pick_groups.size() else []
		var n := maxi(tiles.size(), 1)
		b.size = Vector2(float(n) * w, h)
		b.global_position = Vector2(x, y)
		x += float(n) * w + CHOW_GROUP_GAP


func _tile_pick_clear() -> void:
	if tile_pick_tag == "c40b":
		c40b_key = ""              # 自愈：面板被清掉了 → 下一次 state 同步要重新弹
	tile_pick_tag = ""
	tile_pick_anchor = Callable()
	tile_pick_groups = []
	tile_pick_cb = Callable()
	tile_pick_alive = Callable()
	chi_select_container = null
	if tile_pick_container == null:
		return
	if is_instance_valid(tile_pick_container):
		for c in tile_pick_container.get_children():
			tile_pick_container.remove_child(c)
			c.queue_free()
		tile_pick_container.queue_free()
	tile_pick_container = null


func _tile_pick_do(gi: int) -> void:
	if gi < 0 or gi >= tile_pick_groups.size():
		return
	var data = (tile_pick_groups[gi] as Dictionary).get("data", null)
	var cb := tile_pick_cb
	_tile_pick_clear()
	if cb.is_valid():
		cb.call(data)


# 让玩家在几种吃法里挑一种（服务端接管后由服务端挑，这里保留备用）
func show_chow_choices() -> void:
	var groups: Array = []
	for g in chi_groups:
		groups.append({"tiles": (g as Array).duplicate(), "data": (g as Array).duplicate()})
	_tile_pick_show(groups, Callable(self, "do_chow"),
		func() -> bool: return has_action("chi"))


# 选搭子面板每帧跟着手牌走（手牌位置/缩放变了也不会飘）
func _sync_chow_choices() -> void:
	_tile_pick_sync()


func clear_chow_choices() -> void:
	_tile_pick_clear()


# 吃下：手牌去掉这两张 → 上家那张从牌河消失 → 三张摆到右下角
func do_chow(group: Array) -> void:
	if game_over:
		return
	hide_chow_panel()
	var extra := {}
	if not group.is_empty():
		extra["tiles"] = group           # 把选中的搭子告诉服务端
	# 加速（29S1）走自己的 op：那一下就是技能发动点（会被问看破）
	if not srv_c29s1_ask().is_empty():
		_c29s1_op("c29s1_chi", extra)
		return
	srv_act("chi", extra)


# 一组副露：三张左右紧贴；第 rot_index 张「横置」且底边紧靠画面下沿，其余竖直。
# 第一组紧靠右下角，之后每组紧挨上一组的左侧。
# scale <= 0 时用 meld_scale（副露大小接口）；其他家的副露也可以传自己的比例
# 副露贴的那个「右下角」：跟着手牌位移接口一起挪（动了手牌，副露还挤在手牌旁边）
func meld_anchor_bottom_right() -> Vector2:
	var vp := get_viewport_rect().size
	return Vector2(vp.x, vp.y) + hand_offset


func add_meld(tiles: Array, scale: float = -1.0, rot_index: int = 0, rot_all: bool = false, kind: String = "") -> void:
	# 副露容器：场景里的 Main/Melds；没有才现场新建。
	# ★ 副露的坐标是按「全屏」算的（meld_anchor_bottom_right 用的是视口尺寸），
	#   所以容器必须待在画布原点 —— 整体想挪就用 hand_offset 那个导出参数。
	if meld_container == null or not is_instance_valid(meld_container):
		meld_container = get_node_or_null("Melds") as Node2D
	if meld_container == null:
		meld_container = Node2D.new()
		meld_container.name = "Melds"
		add_child(meld_container)
	meld_container.global_position = Vector2.ZERO
	if not LEGACY_TILE_RENDER:
		meld_container.modulate = Color(1.0, 1.0, 1.0, 0.0)   # 老画法的副露节点一律透明
	var s := meld_scale if scale <= 0.0 else scale
	var br := meld_anchor_bottom_right()   # 副露贴的右下角（跟着「手牌位移」接口走）
	var w := tile_size.x * s
	var h := tile_size.y * s
	var rot_w := tile_size.y * s          # 横置那张的长边 = 手牌高度 × 比例
	# 加杠：原来那副「碰」的 3 张保持原样，第 4 张「竖直」摆在它们的一端
	#   服务端给的 tiles = [碰的 3 张…, 第 4 张]，所以把第 4 张挪到最前/最后再加上去的槽位
	#   KAKAN_TILE_AT_LEFT 决定摆最左还是最右（横置那张的下标跟着 +1）
	var seq_tiles: Array = tiles
	var seq_rot := rot_index
	if kind == "kakan" and tiles.size() == 4:
		if KAKAN_TILE_AT_LEFT:
			seq_tiles = [tiles[3], tiles[0], tiles[1], tiles[2]]
			seq_rot = rot_index + 1
		else:
			seq_tiles = [tiles[0], tiles[1], tiles[2], tiles[3]]
			seq_rot = rot_index
	var group_w := 0.0
	for k in range(seq_tiles.size()):     # 每组 N 张（吃碰 3 张、明杠加杠 4 张）
		group_w += (rot_w if (rot_all or k == seq_rot) else w)
	meld_list.append({"tiles": tiles.duplicate(), "rot_index": rot_index,
		"rot_all": rot_all, "kind": kind, "from": ""})
	var right := br.x
	if meld_left >= 0.0:
		right = meld_left                 # 挨着上一组的左边
	if kind == "ankan":
		_add_my_ankan(tiles, right, w)
		meld_left = right - 4.0 * w
		return
	var cy := br.y - h * 0.5              # 竖直牌：底边贴画面下沿
	var x := right - group_w
	# 从左往右依次加入 → 同一容器里「后放的压住先放的」
	# （所以左边那张在下面、右边那张在上面；加杠的第 4 张摆最左时就在最下面）
	for k in range(seq_tiles.size()):
		var horizontal: bool = rot_all or k == seq_rot
		var slot_w: float = rot_w if horizontal else w
		if horizontal:
			var rot := _make_rotated_visual(seq_tiles[k], s)
			if rot != null:
				var rs := rot.get_node_or_null("Sprite2D") as Sprite2D
				var rot_h := h
				if rs != null and rs.texture != null:
					rot_h = rs.texture.get_size().y * rot.scale.x * rs.scale.y
				rot.position = Vector2(x + slot_w * 0.5, br.y - rot_h * 0.5)   # 横置那张紧靠下方
				rot.name = "Meld%d_%s" % [k, String(seq_tiles[k])]   # 每张牌记着自己的编号
				meld_container.add_child(rot)
		else:
			var vis := _make_tile_visual(seq_tiles[k], s)
			if vis != null:
				vis.position = Vector2(x + slot_w * 0.5, cy)
				vis.name = "Meld%d_%s" % [k, String(seq_tiles[k])]   # 每张牌记着自己的编号
				meld_container.add_child(vis)
		x += slot_w
	meld_left = right - group_w


# 复制一张横版模板（fPai 下的 h*，与手牌同属「默认风格」），长边 = 手牌高度 × scale
func _make_rotated_visual(tile_id: String, scale: float = 1.0) -> Node2D:
	if tile_id == "":
		return null
	var tpl := fpai.get_node_or_null(hpai_node_name(tile_id)) as Node2D
	if tpl == null:
		return null
	var vis: Node2D = tpl.duplicate()
	vis.visible = true
	var spr := vis.get_node_or_null("Sprite2D") as Sprite2D
	if spr != null and spr.texture != null:
		spr.scale = Vector2.ONE * (tile_size.y / (spr.texture.get_size().x * vis.scale.x))
	if scale != 1.0:
		vis.scale = vis.scale * scale
	return vis


# 吃之后这张牌能不能切：不能和吃用的那两张凑成面子（否则切不出去）
func can_discard_after_chi(tile_id: String) -> bool:
	if not after_chi_discard or chi_used_tiles.size() < 2:
		return true
	return not is_meld_of_three([chi_used_tiles[0], chi_used_tiles[1], tile_id])


# 三张牌是不是面子（三张相同 = 刻子；同花色且数字连续 = 顺子）
func is_meld_of_three(ids: Array) -> bool:
	if ids.size() != 3:
		return false
	if ids[0] == ids[1] and ids[1] == ids[2]:
		return true
	var suit := tile_suit(ids[0])
	if suit == "":
		return false
	var nums := []
	for id in ids:
		if tile_suit(id) != suit:
			return false
		nums.append(tile_number(id))
	nums.sort()
	return nums[1] == nums[0] + 1 and nums[2] == nums[1] + 1


# ────────────────────────── 碰（碰三家打出的牌） ──────────────────────────

const PON_BUTTON_POS := Vector2(240, 20)          # 碰按钮位置（样式待定）
# 碰的是哪家的牌 → 横置的那张摆在「左 / 中 / 右」（B 上家 / C 对家 / D 下家）
const PON_ROT_INDEX := {"B": 0, "C": 1, "D": 2}

var pon_groups := []                              # 当前能用来碰的两张手牌
var pon_who := ""                                 # 碰的是哪家打出的牌
var after_pon_discard := false                    # 碰之后必须立刻切一张
var pon_used_tile := ""                           # 碰来的那张牌（切牌特判用）


# 手牌里能用来碰「这张弃牌」的两张（碰不上返回空；优先用两张完全一样的）
func find_pon_group(discard_id: String) -> Array:
	var k := kind_of(discard_id)
	if k < 0:
		return []
	var same_kind := []
	for i in range(hand_tiles.size()):
		if kind_of(hand_tiles[i]) == k:
			same_kind.append(i)
	if same_kind.size() < 2:
		return []
	var by_id := {}
	for i in same_kind:
		var id: String = hand_tiles[i]
		if not by_id.has(id):
			by_id[id] = []
		by_id[id].append(i)
	for id in by_id:
		var idxs: Array = by_id[id]
		if idxs.size() >= 2:
			return [hand_tiles[int(idxs[0])], hand_tiles[int(idxs[1])]]
	return [hand_tiles[int(same_kind[0])], hand_tiles[int(same_kind[1])]]


# 某家打出后调用：能碰就亮「碰」按钮








# 碰下：手牌去掉两张 → 那家牌河里那张消失 → 三张摆到右下角（摆放逻辑与吃相同）


# 碰之后这张牌能不能切：不能切出与碰来的那张相同的牌


# ────────────────────────── 其他家的副露（吃）显示 ──────────────────────────

# 副露大小基准：true = 以「该家自己的手牌」为基准；false = 以「我的手牌」为基准
const OPP_MELD_BASIS_OWN_HAND := true
@export var opp_meld_scale := 0.96             # 其他家副露牌 = 基准尺寸 × 此比例
# 测试用：让其他家主动喂牌并吃下（关掉就不会自动吃）
const OPP_CHOW_TEST := false
const OPP_CHOW_TEST_MAX := 2                  # 每家最多吃几次（防止测试时吃个没完）

# 逆时针座次：我 → 下家D → 对家C → 上家B
const TURN_ORDER: Array[String] = ["me", "D", "C", "B"]
# 各家副露的几何：[0] 锚点→「第 1 张」的方向  [1] 基线→牌面（往外）的方向  [2] 牌面旋转角
# 锚点 = 该家自己一侧「最靠外、且在自己右手边」的那个屏幕角（_setup_opponents 里按分辨率算）
const OPP_MELD_GEO := {
	"B": [Vector2(0.0, -1.0), Vector2(1.0, 0.0), 90.0],
	"C": [Vector2(1.0, 0.0), Vector2(0.0, 1.0), 180.0],
	"D": [Vector2(0.0, 1.0), Vector2(-1.0, 0.0), 270.0]
}

var opp_meld_container: Node2D                # 其他家副露的容器
var opp_meld_counts := {}                     # 各家已吃组数
var opp_meld_anchor := {}                     # 各家下一组副露的锚点
var opp_drawn_sign := {}                      # 各家「摸到的牌」在锚点的哪一侧（+1/-1）


# 下一个玩家（逆时针）
# 碰之后不能打碰来的那张（食い替え）；服务端也会拦一道
func can_discard_after_pon(tile_id: String) -> bool:
	if not after_pon_discard or pon_groups.size() < 2:
		return true
	return not is_meld_of_three([pon_groups[0], pon_groups[1], tile_id])
func next_player_name(who: String) -> String:
	var i := TURN_ORDER.find(who)
	if i < 0:
		return "me"
	return TURN_ORDER[(i + 1) % TURN_ORDER.size()]


# 其他家手牌在屏幕上的「牌宽（短边）」——直接量那张手牌图像画出来的尺寸
func opp_hand_tile_width(who: String) -> float:
	if tapai == null:
		return tile_size.x
	var n := tapai.get_node_or_null(who + "03")
	if n == null:
		return tile_size.x
	var spr: Sprite2D = n if n is Sprite2D else n.get_node_or_null("Sprite2D")
	if spr == null or spr.texture == null:
		return tile_size.x
	var d: Vector2 = spr.texture.get_size() * spr.global_scale
	return minf(d.x, d.y)


# 其他家一张副露牌的尺寸：x = 牌宽，y = 牌长
func opp_meld_tile_size(who: String) -> Vector2:
	if pai == null:
		return tile_size
	var base_w := tile_size.x
	if OPP_MELD_BASIS_OWN_HAND:
		base_w = opp_hand_tile_width(who)
	var w := base_w * opp_meld_scale
	var aspect := 389.0 / 271.0
	var tpl := pai.get_node_or_null(TILE_IDS[0] + "/Sprite2D") as Sprite2D
	if tpl != null and tpl.texture != null:
		aspect = tpl.texture.get_size().y / tpl.texture.get_size().x
	return Vector2(w, w * aspect)


# 复制一张手牌风格的牌面（竖版），显示宽度 = width，牌长按原图比例
func _make_face_visual(tile_id: String, width: float) -> Node2D:
	if pai == null:
		return null
	var tpl := pai.get_node_or_null(tile_id) as Node2D
	if tpl == null:
		push_warning("main.gd: Pai 下找不到模板牌 " + tile_id)
		return null
	var tspr := tpl.get_node_or_null("Sprite2D") as Sprite2D
	if tspr == null or tspr.texture == null:
		return null
	var vis := Node2D.new()
	var spr := Sprite2D.new()
	spr.name = "Sprite2D"
	spr.texture = tspr.texture
	spr.centered = true
	spr.scale = Vector2.ONE * (width / tspr.texture.get_size().x)
	vis.add_child(spr)
	return vis


# 复制一张横版牌面（横 horizontal），长边 = width（用于副露里横置的那张）
func _make_face_h_visual(tile_id: String, width: float) -> Node2D:
	if tile_id == "" or fpai == null:
		return null
	var tpl := fpai.get_node_or_null(hpai_node_name(tile_id)) as Node2D
	if tpl == null:
		push_warning("main.gd: fPai 下找不到横版牌 " + hpai_node_name(tile_id))
		return null
	var tspr := tpl.get_node_or_null("Sprite2D") as Sprite2D
	if tspr == null or tspr.texture == null:
		return null
	var vis := Node2D.new()
	var spr := Sprite2D.new()
	spr.texture = tspr.texture
	spr.centered = true
	spr.scale = Vector2.ONE * (width / tspr.texture.get_size().x)
	vis.add_child(spr)
	return vis


# 一组其他家的副露：摆放逻辑与我的一致（哪张横置、紧靠基线、三张紧贴，
# 第一组贴自己那一侧的角，之后的组继续往「第 1 张」的方向排），
# 只是整组按该家所在的一侧摆放、牌面按该家的视角旋转。
func add_opp_meld(who: String, tiles: Array, rot_index: int = 0, rot_all: bool = false, kind: String = "") -> void:
	var geo: Array = OPP_MELD_GEO.get(who, [])
	if geo.is_empty() or tiles.is_empty():
		return
	if kind == "ankan":
		add_opp_ankan(who, tiles)
		return
	# 三家副露容器：场景里的 Main/OppMelds；没有才现场新建（同样要待在画布原点）
	if opp_meld_container == null or not is_instance_valid(opp_meld_container):
		opp_meld_container = get_node_or_null("OppMelds") as Node2D
	if opp_meld_container == null:
		opp_meld_container = Node2D.new()
		opp_meld_container.name = "OppMelds"
		add_child(opp_meld_container)
	opp_meld_container.global_position = Vector2.ZERO
	if not LEGACY_TILE_RENDER:
		opp_meld_container.modulate = Color(1.0, 1.0, 1.0, 0.0)   # 老画法的副露节点一律透明
	var to_far: Vector2 = geo[0]
	var out_dir: Vector2 = geo[1]
	var rot_deg: float = geo[2]
	var sz := opp_meld_tile_size(who)
	var w := sz.x
	var l := sz.y
	var rot_w := l                          # 横置那张的长边
	var h_aspect := 301.0 / 359.0
	var h_tpl := fpai.get_node_or_null("h1m/Sprite2D") as Sprite2D if fpai != null else null
	if h_tpl != null and h_tpl.texture != null:
		h_aspect = h_tpl.texture.get_size().y / h_tpl.texture.get_size().x
	var rot_h := rot_w * h_aspect           # 横置那张的宽度（往外的厚度）
	# 加杠：原来那副「碰」的 3 张不动，第 4 张按这一家的方向摆到组的另一端
	#   KAKAN_OPP_AT_FAR[who] = true → 摆到「离锚点远」的那端
	#   锚点：上家 B 在左下角 / 对家 C 在左上角 / 下家 D 在右上角
	#   → 上家 B：远端是上、近端是下 → 第 4 张放近端（紧贴下侧）
	#     对家 C：远端是右 → 第 4 张放远端（紧贴右侧）
	#     下家 D：远端是下 → 第 4 张放远端（紧贴下侧）
	var seq_tiles: Array = tiles
	var seq_rot := rot_index
	if kind == "kakan" and tiles.size() == 4:
		if bool(KAKAN_OPP_AT_FAR.get(who, true)):
			seq_tiles = [tiles[3], tiles[0], tiles[1], tiles[2]]
			seq_rot = rot_index + 1
		else:
			seq_tiles = [tiles[0], tiles[1], tiles[2], tiles[3]]
			seq_rot = rot_index
	# 组宽按「张数」算（吃碰 3 张、明杠/加杠 4 张都要对；原来写死 3 张）
	var group_w := 0.0
	for k in range(seq_tiles.size()):
		group_w += rot_w if (rot_all or k == seq_rot) else w
	var anchor: Vector2 = opp_meld_anchor.get(who, Vector2.ZERO)
	var c := 0.0
	for k in range(seq_tiles.size()):
		# 加杠的第 4 张不是横置的（rot_index 只有 0..2）→ 它和这组里其它竖牌一样摆
		var horizontal: bool = rot_all or k == seq_rot
		var slot_w: float = rot_w if horizontal else w
		var depth: float = rot_h if horizontal else l
		var vis: Node2D = _make_face_h_visual(seq_tiles[k], rot_w) if horizontal else _make_face_visual(seq_tiles[k], w)
		if vis != null:
			# 从锚点沿 to_far 走满一组到「第 1 张」那端，再一格一格往回摆
			vis.position = anchor + to_far * (group_w - c - slot_w * 0.5) + out_dir * (depth * 0.5)
			vis.rotation_degrees = rot_deg
			vis.z_index = int(vis.position.y)          # 覆盖关系：下方的牌压住上方
			vis.name = "%s_Meld%d_%s" % [who, k, String(seq_tiles[k])]   # 每张牌记着自己的编号
			opp_meld_container.add_child(vis)
		c += slot_w
	opp_meld_anchor[who] = anchor + to_far * group_w


# 某家手牌「摸牌那一端」的牌：摸到的新牌就挂在这一张旁边
#（上家 B 的摸牌端在下方 B01 那端；下家 D 在上方 D01 那端；对家 C 在右侧 C13 那端）
func _opp_near_node_name(who: String) -> String:
	var n: int = opp_hands.get(who, []).size()
	if who == "C":
		return "%s%02d" % [who, OPP_HAND_COUNT]
	return "%s%02d" % [who, mini(OPP_HAND_COUNT, OPP_HAND_COUNT - n + 1)]


# 其他家手牌图像：副露（吃）之后手牌变少 —— 减掉「他自己右手边」的两张：
#   上家 B = 视觉最下面两张（B01/B02）；下家 D = 视觉最上面两张（D01/D02）；
#   对家 C = 视觉最左边两张（C01/C02，因为他的右边就是我的左边）。
# 同时让「摸到的那张」紧跟着剩下手牌的摸牌端，间距始终不变。
var _opp_hand_sig := {}

func _refresh_opp_hand(who: String) -> void:
	if tapai == null:
		return
	var n: int = opp_hands.get(who, []).size()
	# ★ 性能：每次 state 都会对四家各调一次，每次摸 13 个节点改 visible。
	#   张数 + 锚点位置都没变 → 一个节点都不碰。
	var _near0 := tapai.get_node_or_null(_opp_near_node_name(who)) as Node2D
	var _sig := "%d|%s" % [n, str(_near0.position) if _near0 != null else ""]
	if String(_opp_hand_sig.get(who, "")) == _sig:
		return
	_opp_hand_sig[who] = _sig
	for i in range(OPP_HAND_COUNT):
		var node := tapai.get_node_or_null("%s%02d" % [who, i + 1])
		if node == null:
			continue
		node.visible = (i + 1) > (OPP_HAND_COUNT - n)     # 留序号大的那 n 张
	var dn = opp_drawn_nodes.get(who, null)
	var near := tapai.get_node_or_null(_opp_near_node_name(who)) as Node2D
	if dn != null and near != null and opp_step.has(who):
		dn.position = near.position + opp_step[who] * float(opp_drawn_sign.get(who, -1.0)) * (1.0 + OPP_DRAWN_GAP_RATIO)


# 在给定手牌里找吃法（与 find_chow_groups 同一套规则，手牌由外部传入）
func find_chow_groups_in(hand: Array, discard_id: String) -> Array:
	var out := []
	var suit := tile_suit(discard_id)
	if suit == "":
		return out
	var n := tile_number(discard_id)
	for pat in [[n - 2, n - 1], [n - 1, n + 1], [n + 1, n + 2]]:
		var a: int = pat[0]
		var b: int = pat[1]
		if a < 1 or b > 9:
			continue
		for x in range(hand.size()):
			if tile_suit(hand[x]) != suit or tile_number(hand[x]) != a:
				continue
			for y in range(hand.size()):
				if x == y:
					continue
				if tile_suit(hand[y]) != suit or tile_number(hand[y]) != b:
					continue
				var pair := [hand[x], hand[y]]
				pair.sort()
				if not out.has(pair):
					out.append(pair)
	return out


# 测试用：找一张「喂给这手牌就能吃」的牌（手里两张不同数字的牌 + 缺的那张）
func find_feed_tile(hand: Array) -> String:
	for i in range(hand.size()):
		for j in range(hand.size()):
			if i == j:
				continue
			var a: String = hand[i]
			var b: String = hand[j]
			var suit := tile_suit(a)
			if suit == "" or suit != tile_suit(b):
				continue
			var na := tile_number(a)
			var nb := tile_number(b)
			if na == nb:
				continue
			var diff := absi(na - nb)
			if diff == 1:
				var lo := mini(na, nb)
				if lo - 1 >= 1:
					return str(lo - 1) + suit
				if lo + 2 <= 9:
					return str(lo + 2) + suit
			elif diff == 2:
				return str(mini(na, nb) + 1) + suit
	return ""


# 其他家吃下（上家 = discarder 打出的 tile_id）
func do_opp_chow(who: String, discarder: String, tile_id: String) -> bool:
	if game_over or tile_id == "" or who == discarder:
		return false
	# ★ 自己那一家只由服务端 state 驱动；这里绝不能给自己「演」一手自动吃
	if who == who_of_seat(my_seat):
		return false
	var hand: Array = opp_hands.get(who, [])
	var groups := find_chow_groups_in(hand, tile_id)
	if groups.is_empty():
		return false
	var pile: Array = opp_discards.get(discarder, [])
	if pile.is_empty() or pile[pile.size() - 1] != tile_id:
		return false
	var g: Array = groups[0]
	var idx := []
	for id in g:
		var hit := hand.find(id)
		if hit < 0:
			return false
		idx.append(hit)
	idx.sort()
	hand.remove_at(int(idx[1]))
	hand.remove_at(int(idx[0]))
	_refresh_opp_hand(who)
	pile.remove_at(pile.size() - 1)         # 上家牌河那张消失
	refresh_discards()
	add_opp_meld(who, [tile_id, g[0], g[1]], 0, false)
	opp_meld_counts[who] = opp_meld_counts.get(who, 0) + 1
	return true


func _schedule_opp_chow_discard(who: String) -> void:
	get_tree().create_timer(OPP_DRAW_DELAY).timeout.connect(_opp_chow_discard.bind(who))


# 其他家吃完之后必须打一张（手牌 13 → 吃 2 张 → 再打 1 张）
func _opp_chow_discard(who: String) -> void:
	if game_over:
		return
	var hand: Array = opp_hands.get(who, [])
	if hand.is_empty():
		return
	var idx := randi() % hand.size()
	# 测试用：优先打出一张「下家能吃」的牌，好把连锁的吃显示也跑出来
	if OPP_CHOW_TEST:
		var nxt := next_player_name(who)
		if nxt != "me" and opp_meld_counts.get(nxt, 0) < OPP_CHOW_TEST_MAX:
			var feed := find_feed_tile(hand)
			if feed != "":
				var hit := hand.find(feed)
				if hit >= 0:
					idx = hit
	opp_discards[who].append(hand[idx])
	hand.remove_at(idx)
	_refresh_opp_hand(who)
	_after_opp_discard(who)


# ────────────────────────── 暗杠（显示 + 玩法） ──────────────────────────

# 读一张图（不存在就返回 null，不会崩）
func _load_tex(path: String) -> Texture2D:
	if ResourceLoader.exists(path):
		return load(path) as Texture2D
	push_warning("main.gd: 找不到图 " + path)
	return null


# 暗杠正面图的名字：数字重复两遍 + 花色；5m/5s/5p 用 05X 那张
func kan_face_name(tile_id: String) -> String:
	var honors := ["dong", "nan", "xi", "bei", "bai", "fa", "zhong"]
	var h := honors.find(tile_id)
	if h >= 0:
		return "%d%dz" % [h + 1, h + 1]
	var s := tile_suit(tile_id)
	if tile_id.begins_with("0") or tile_number(tile_id) == 5:
		return "05" + s                              # 5m/5s/5p 的杠一律用 05X 那张
	var n := tile_number(tile_id)
	return "%d%d%s" % [n, n, s]


# 一张「指定显示宽度」的图（暗杠的正面 / 背面都用它）
# by_height = true 时按「高度」定宽（横版图用在竖着排的副露里，比如上下家的 b_01）

# ── 从 Art 节点「复制」出一个牌面（而不是新建 Sprite2D 再塞贴图）────────────────
# 为什么要复制节点：你在场景里给 Art/… 那张图挂的 AnimationPlayer / 子节点 / 脚本，
# 复制出来的这一份会一起带过来 —— 以后加动效就不用再回代码里改了。
# 复制出来的外形和以前完全一样：Node2D 包着名字叫 "Sprite2D" 的子节点（老代码都按这个名字找尺寸/翻转）。
func _dup_art(group: String, key: String) -> Node2D:
	var src := art_sprite(group, key)
	if src == null or src.texture == null:
		return null
	var copy := src.duplicate() as Node2D
	if copy == null:
		return null
	copy.name = "Sprite2D"
	copy.visible = true                      # 模板自己是隐藏的，复制出来要看得见
	copy.position = Vector2.ZERO
	copy.rotation_degrees = 0.0
	var wrap := Node2D.new()
	wrap.name = "PlainTile"
	wrap.add_child(copy)
	return wrap


# 造一张「指定显示宽度」的图：优先用 Art 节点复制，节点缺了才退回老办法（贴图现场建）
func _make_art_visual(group: String, key: String, width: float, by_height := false) -> Node2D:
	var vis := _dup_art(group, key)
	if vis == null:
		if group == "牌背":
			vis = _make_plain_visual(art_back_tex(key), width, by_height)
	if vis == null:
		return null
	var spr := vis.get_node_or_null("Sprite2D") as Sprite2D
	if spr == null or spr.texture == null:
		return null
	var base := spr.texture.get_size().y if by_height else spr.texture.get_size().x
	# ★ 乘上「模板节点自己的缩放」：你在场景里把 Art/牌背/b_04 放大一点，桌上所有牌墩跟着变
	var src := art_sprite(group, key)
	var k := src.scale if src != null else Vector2.ONE
	spr.scale = k * (width / maxf(base, 1.0))
	return vis


# 宝牌指示牌用哪个组：view = h(横) / hf(横翻) → 横翻；vf(竖翻) → 竖翻
func _dora_group(view: String) -> String:
	return "宝牌指示牌/竖翻" if view == "vf" else "宝牌指示牌/横翻"


# 宝牌指示牌：key = 文件名（1m / h1z / 0p …）
func _dora_key(tile_id: String, view: String) -> String:
	var nm := dora_file_base(tile_id)
	return ("h" + nm) if view == "hf" else nm


func _make_plain_visual(tex: Texture2D, width: float, by_height: bool = false) -> Node2D:
	if tex == null:
		return null
	var vis := Node2D.new()
	vis.name = "PlainTile"
	var spr := Sprite2D.new()
	spr.name = "Sprite2D"
	spr.texture = tex
	spr.centered = true
	var base := tex.get_size().y if by_height else tex.get_size().x
	spr.scale = Vector2.ONE * (width / maxf(base, 1.0))
	vis.add_child(spr)
	return vis


# 这张牌画出来「往外占多厚」——要按它转过的角度算（转 90° 时长宽互换）
# 注意：sprite 的 scale 可能不是等比的（暗杠亮牌要压成和暗牌一样大），所以 x/y 分开算
func _plain_depth(vis: Node2D, out_dir: Vector2) -> float:
	var spr := vis.get_node_or_null("Sprite2D") as Sprite2D
	if spr == null or spr.texture == null:
		return 0.0
	var tex := spr.texture.get_size()
	var sideways := absf(fmod(vis.rotation_degrees, 180.0)) > 1.0
	var wx := tex.x * spr.scale.x
	var wy := tex.y * spr.scale.y
	var ex := wy if sideways else wx
	var ey := wx if sideways else wy
	return absf(out_dir.x) * ex + absf(out_dir.y) * ey


# 暗杠的正面：kan 文件夹里的一张图里就有「两张牌」（上下叠着画的）。
# 转 rot_deg 让这两张牌顺着副露方向铺开；并且把单张牌的大小压成和暗牌一模一样：
#   depth_w = 单张牌「往外的厚度」，axis_h = 单张牌「沿副露方向的宽度」
# （图画得比暗牌扁，所以这里 x/y 分开缩放，保证和暗牌同尺寸、不显大）
func _make_kan_pair(tile_id: String, rot_deg: float, depth_w: float, axis_h: float) -> Node2D:
	var vis := _dup_art("杠面", kan_face_name(tile_id))     # 节点：杠面/19anke…
	if vis == null:
		return null
	var spr := vis.get_node_or_null("Sprite2D") as Sprite2D
	if spr == null or spr.texture == null:
		return null
	var tex := spr.texture.get_size()
	spr.scale = Vector2(depth_w / maxf(tex.x, 1.0), 2.0 * axis_h / maxf(tex.y, 1.0))
	vis.rotation_degrees = rot_deg
	return vis


# 暗牌的「单张牌厚度」：上下家用 b_01(横)、对家和自己用 b_02(竖)
func _back_depth(w: float, updown: bool) -> float:
	if updown:
		return w * (359.0 / 301.0)
	return w * (389.0 / 271.0)


# 我的暗杠：1 张正面图（里面两张牌）+ 左右各 1 张暗牌，四张紧密相连、底边贴画面下沿
func _add_my_ankan(tiles: Array, right: float, w: float) -> void:
	# 副露容器：场景里的 Main/Melds；没有才现场新建。
	# ★ 副露的坐标是按「全屏」算的（meld_anchor_bottom_right 用的是视口尺寸），
	#   所以容器必须待在画布原点 —— 整体想挪就用 hand_offset 那个导出参数。
	if meld_container == null or not is_instance_valid(meld_container):
		meld_container = get_node_or_null("Melds") as Node2D
	if meld_container == null:
		meld_container = Node2D.new()
		meld_container.name = "Melds"
		add_child(meld_container)
	meld_container.global_position = Vector2.ZERO
	if not LEGACY_TILE_RENDER:
		meld_container.modulate = Color(1.0, 1.0, 1.0, 0.0)   # 老画法的副露节点一律透明
	var bottom := meld_anchor_bottom_right().y
	var x0 := right - 4.0 * w
	# 三块：暗牌(1张) / 正面(2张) / 暗牌(1张)；正面单张压成和暗牌一样大
	var parts := [
		{"vis": _make_art_visual("牌背", "b_02", w), "slot": w},
		{"vis": _make_face_visual(tiles[0], w), "slot": w},
		{"vis": _make_face_visual(tiles[1], w), "slot": w},
		{"vis": _make_art_visual("牌背", "b_02", w), "slot": w},
	]
	var x := x0
	for p in parts:
		var vis: Node2D = p["vis"]
		if vis != null:
			var depth := _plain_depth(vis, Vector2(0.0, -1.0))
			vis.position = Vector2(x + float(p["slot"]) * 0.5, bottom - depth * 0.5)
			meld_container.add_child(vis)
		x += float(p["slot"])


# 其他家的暗杠：1 张正面图（里面两张牌，按各家的方向旋转）+ 两侧各 1 张暗牌。
# 摆放规则同普通副露：贴自己那一侧的基线，同组里下方的牌压住上方。
#   kan 图的旋转：上家 B = 0°（横躺，跟着竖排的副露）、对家 C = 270°、下家 D = 180°
func add_opp_ankan(who: String, tiles: Array) -> void:
	var geo: Array = OPP_MELD_GEO.get(who, [])
	if geo.is_empty() or tiles.size() < 4:
		return
	# 三家副露容器：场景里的 Main/OppMelds；没有才现场新建（同样要待在画布原点）
	if opp_meld_container == null or not is_instance_valid(opp_meld_container):
		opp_meld_container = get_node_or_null("OppMelds") as Node2D
	if opp_meld_container == null:
		opp_meld_container = Node2D.new()
		opp_meld_container.name = "OppMelds"
		add_child(opp_meld_container)
	opp_meld_container.global_position = Vector2.ZERO
	if not LEGACY_TILE_RENDER:
		opp_meld_container.modulate = Color(1.0, 1.0, 1.0, 0.0)   # 老画法的副露节点一律透明
	var to_far: Vector2 = geo[0]
	var out_dir: Vector2 = geo[1]
	var w := opp_meld_tile_size(who).x
	var updown := who == "B" or who == "D"          # 上下家：牌是横躺的
	var back_key := "b_01" if updown else "b_02"
	var back_rot := 180.0
	var rot_deg: float = geo[2]
	var parts := [
		{"vis": _make_art_visual("牌背", back_key, w, updown), "rot": back_rot, "slot": w, "face": false},
		{"vis": _make_face_visual(tiles[0], w), "rot": rot_deg, "slot": w, "face": false},
		{"vis": _make_face_visual(tiles[1], w), "rot": rot_deg, "slot": w, "face": false},
		{"vis": _make_art_visual("牌背", back_key, w, updown), "rot": back_rot, "slot": w, "face": false},
	]
	var group_w := 4.0 * w
	var anchor: Vector2 = opp_meld_anchor.get(who, Vector2.ZERO)
	var c := 0.0
	for p in parts:
		var vis: Node2D = p["vis"]
		if vis != null:
			if float(p["rot"]) != 0.0:
				vis.rotation_degrees = float(p["rot"])
			if who == "B" and bool(p.get("face", false)):
				# 上家暗杠「中间那张亮牌图」要垂直镜像（两侧暗牌不动）
				var mspr := vis.get_node_or_null("Sprite2D") as Sprite2D
				if mspr != null:
					mspr.flip_v = true
			var depth := _plain_depth(vis, out_dir)
			vis.position = anchor + to_far * (group_w - c - float(p["slot"]) * 0.5) + out_dir * (depth * 0.5)
			vis.z_index = int(vis.position.y)          # 下方的牌压住上方
			opp_meld_container.add_child(vis)
		c += float(p["slot"])
	opp_meld_anchor[who] = anchor + to_far * group_w


# 手牌里凑够 4 张一样的（含刚摸的那张）就亮「暗杠」按钮
# 注意：不能拿「花色 + 数值」当种类 —— 字牌的花色是 ""、数值是 0，会把不同字牌算成同一种。
# 一律用 kind_of()（0m/0p/0s 按 5 处理，字牌各有各的编号）。


# 暗杠：手牌去掉 4 张 → 摆出副露 → 补一张岭上牌（客户端没有王牌，就从牌山继续摸）


# 明杠 / 加杠 时，横置的那张摆在从左往右第几张（从 0 数）
# 杠上家 / 对家 → 第 2 张(1)；杠下家 → 第 3 张(2)
func redraw_melds() -> void:
	if meld_container != null:
		for c in meld_container.get_children():
			meld_container.remove_child(c)
			c.queue_free()
	meld_left = -1.0
	var saved: Array = meld_list.duplicate(true)
	meld_list = []
	for m in saved:
		add_meld(m["tiles"], -1.0, int(m.get("rot_index", 0)), bool(m.get("rot_all", false)),
			String(m.get("kind", "")))
		meld_list[meld_list.size() - 1]["from"] = m.get("from", "")


func kan_rot_index(who: String) -> int:
	return 2 if who == "D" else 1


# 手里有没有 3 张和这张一样的（能明杠）。同样用 kind_of 判种类，字牌才分得清。
func find_minkan_tiles(tile_id: String) -> Array:
	var out := []
	var k := kind_of(tile_id)
	for t in hand_tiles:
		if kind_of(t) == k:
			out.append(t)
	return out if out.size() >= 3 else []








# 明杠：手里三张 + 别家打出那张 = 4 张；横置的那张按来源摆第 2 / 第 3 张


# 碰过的牌又摸到第 4 张 → 亮「加杠」




# 加杠：手里第 4 张塞进那副碰里，横置位置跟明杠一样；然后补一张岭上牌


# ══════════════════════════════════════════════════════════════════════════
#  开发用：窗口级「自动打牌」（正式包没有 autoplay.cfg 就完全不会启动）
#  用法：在项目根目录放 autoplay.cfg，内容一行  hands=2
#        然后正常开窗口 → 会自动从东一打到第 N 小局结束，日志带 [AUTOPLAY] 前缀
#  它只做四件事：摸牌 / 摸切 / 和牌 / 过，遇到技能选牌面板就停手并报出来
# ══════════════════════════════════════════════════════════════════════════
const AUTOPLAY_CFG := "res://autoplay.cfg"

var _dev_auto_on := false
var _dev_auto_target := 2
var _dev_auto_done := 0
var _dev_auto_was_over := false
var _dev_auto_idle := 0
var _dev_auto_beats := 0


const AUTOPLAY_LOG := "N:/apps/_tmp/autoplay_log.txt"


func _dev_log(msg: String) -> void:
	print(msg)
	for path in ["user://autoplay_log.txt", AUTOPLAY_LOG]:
		var f := FileAccess.open(path, FileAccess.READ_WRITE)
		if f == null:
			f = FileAccess.open(path, FileAccess.WRITE)
		if f == null:
			print("[AUTOPLAY] 日志写不了: ", path, " err=", FileAccess.get_open_error())
			continue
		f.seek_end()
		f.store_line(msg)
		f.close()


func _dev_autoplay_maybe() -> void:
	# ① 环境变量最省事：TIANMA_AUTOPLAY=2 就自动打 2 小局
	var env := OS.get_environment("TIANMA_AUTOPLAY").strip_edges()
	var cfg_file := FileAccess.open(AUTOPLAY_CFG, FileAccess.READ)
	var has_cfg := cfg_file != null
	if has_cfg:
		cfg_file.close()
	if env != "":
		_dev_log("[AUTOPLAY] 启动（env）：目标 %s 小局" % env)
		_dev_autoplay(maxi(1, int(env)))
		return
	if not has_cfg:
		return
	var f := FileAccess.open(AUTOPLAY_CFG, FileAccess.READ)
	if f == null:
		return
	var txt := f.get_as_text()
	f.close()
	# announce=1 → F5 直接进和牌播报调界面（跳过选卡/打牌）
	if txt.contains("announce="):
		for line2 in txt.split("\n"):
			var kv2 := String(line2).strip_edges()
			if kv2.begins_with("announce=") and int(kv2.substr(9)) != 0:
				call_deferred("_debug_announce")
				return
	var hands := 2
	for line in txt.split("\n"):
		var kv := String(line).strip_edges()
		if kv.begins_with("hands="):
			hands = maxi(1, int(kv.substr(6)))
	_dev_log("[AUTOPLAY] 启动：目标 %d 小局" % hands)
	_dev_autoplay(hands)


func _dev_autoplay(hands: int) -> void:
	_dev_auto_target = hands
	_dev_auto_done = 0
	_dev_auto_on = true
	_dev_auto_was_over = false
	while _dev_auto_on:
		await get_tree().create_timer(0.3).timeout
		if not is_inside_tree():
			return
		_dev_auto_tick()
	_dev_log("[AUTOPLAY] 结束：一共打了 %d 小局" % _dev_auto_done)


func _dev_auto_tick() -> void:
	_dev_auto_beats += 1
	if _dev_autostart():
		return
	if _dev_auto_beats % 20 == 0:
		_dev_log("[AUTOPLAY·心跳] phase=%s turn=%s 我=%d dealing=%s busy=%s done=%s 手=%d"
			% [String(srv_state.get("phase", "")), str(srv_state.get("turn", -1)), my_seat,
			   str(dealing), str(srv_busy), str(srv_state.get("deal_done", false)),
			   display_tiles().size()])
		if srv_note != "":
			_dev_log("[AUTOPLAY·心跳·拒绝] %s" % srv_note)
	if game_over:
		if not _dev_auto_was_over:
			_dev_auto_was_over = true
			_dev_auto_done += 1
			_dev_log("[AUTOPLAY] 第 %d 小局结束（目标 %d）" % [_dev_auto_done, _dev_auto_target])
			if _dev_auto_done >= _dev_auto_target:
				_dev_auto_on = false
		return
	_dev_auto_was_over = false
	if dealing or srv_busy or not bool(srv_state.get("deal_done", false)):
		return
	var blocking := _dev_auto_blocking_ui()
	if blocking != "":
		_dev_auto_idle += 1
		if _dev_auto_idle <= 3:
			_dev_log("[AUTOPLAY] 停在技能界面：%s（phase=%s）" % [blocking,
				String(srv_state.get("phase", ""))])
		return
	_dev_auto_idle = 0
	# 看破询问：直接跳过
	var ka: Variant = srv_state.get("kangpo_ask")
	if typeof(ka) == TYPE_DICTIONARY and not (ka as Dictionary).is_empty():
		_kp_skip()
		return
	var ph := String(srv_state.get("phase", ""))
	var turn := int(srv_state.get("turn", -1))
	var rname := String(srv_state.get("round_name", ""))
	var opts := srv_opts_of(srv_state)
	# 鸣牌窗口跟 turn 无关：别人打出来的牌也可能轮到我吃碰杠和 → 先处理我自己的选项
	if ph == "claim" and not opts.is_empty():
		if "ron" in opts:
			_dev_log("[AUTOPLAY] %s 荣和" % rname)
			srv_act("ron")
		elif "tsumo" in opts:
			_dev_log("[AUTOPLAY] %s 自摸和牌" % rname)
			srv_act("tsumo")
		else:
			_dev_log("[AUTOPLAY] %s 过（鸣牌窗口：%s）" % [rname, str(opts)])
			_on_pass_pressed()
		return
	if turn != my_seat:
		srv_busy = true
		_srv_step_once()
		return
	match ph:
		"draw":
			_dev_log("[AUTOPLAY] %s 我摸牌（现 %d 张，预期 +1）" % [rname, display_tiles().size()])
			draw_tile()
		"discard":
			if "tsumo" in opts:
				_dev_log("[AUTOPLAY] %s 自摸和牌" % rname)
				srv_act("tsumo")
				return
			var n := display_tiles().size()
			var idx := n - 1
			if drawn_tile != "":
				idx = drawn_slot()
			_dev_log("[AUTOPLAY] %s 我打第 %d 张（%d → 预期 %d）" % [rname, idx, n, n - 1])
			discard_tile(idx)
			if srv_note != "":
				_dev_log("[AUTOPLAY·拒绝] %s" % srv_note)
		"claim":
			if "ron" in opts:
				_dev_log("[AUTOPLAY] %s 荣和" % rname)
				srv_act("ron")
			else:
				_on_pass_pressed()
		_:
			srv_busy = true
			_srv_step_once()


# 自动过开局：大厅选卡 → 开始 → 编号确认。成功过了一步就返回 true（本拍不干别的）
func _dev_autostart() -> bool:
	var root := get_parent()
	if root == null:
		return false
	# ① 大厅选卡阶段
	var menu := root.get_node_or_null("InitialMenu")
	if menu != null and menu.visible and menu.has_method("_on_start_pressed"):
		var hand: Array = []
		if menu.has_method("_my_hand"):
			hand = menu.call("_my_hand")
		var picked: Array = []
		if menu.has_method("_my_picks"):
			picked = menu.call("_my_picks")
		if picked.size() < 5 and not hand.is_empty():
			for i in range(mini(5, hand.size())):
				menu.call("_on_card_clicked", int(hand[i]))
			_dev_log("[AUTOPLAY] 大厅：选好 5 张卡")
			return true
		if picked.size() >= 5:
			menu.call("_on_start_pressed")
			_dev_log("[AUTOPLAY] 大厅：点了开始（等进牌桌）")
			return true
		return true
	# ② 编号确认阶段
	var cp := root.get_node_or_null("CardPhase")
	if cp != null and cp.visible and cp.has_method("_on_start_pressed"):
		var ord: Array = cp.get("order") if cp.get("order") != null else []
		if ord.size() < 5:
			cp.set("order", [14, 17, 18, 19, 12])
		cp.call("_on_start_pressed")
		_dev_log("[AUTOPLAY] 编号确认：已点开始")
		return true
	return false


# 任何技能选牌 / 换牌面板开着 → 自动打牌不硬闯，报出来让人看
func _dev_auto_blocking_ui() -> String:
	if guobiao_selecting:
		return "国标选牌"
	if yiding_selecting:
		return "一定和牌选牌"
	if riichi_selecting:
		return "立直选牌"
	if c11_active:
		return "11S1 魔术"
	if hs_active and hs_ui != null:
		return "12S1 海神"
	if pofa_active and pofa_ui != null:
		return "13S1 破发"
	if zl_active and zl_ui != null:
		return "14S2 炸裂"
	if sf_active and sf_ui != null:
		return "深山/先负/馈赠面板"
	if dy_active and dy_ui != null:
		return "15S1 钓鱼"
	if c11s2_active:
		return "11S2 快手"
	if c09_active:
		return "09 间合"
	if c10_active:
		return "10S1 鬼门"
	if skill2_card != 0 and skill2_target >= 0:
		return "技能2 选牌"
	if sw_stage == "hand":
		return "05S1 降神"
	if wind_active or flow_active or press_panel.active or swap_panel.active:
		return "换牌/压制面板"
	if ym_panel.active:
		return "22S2 友引摊面子"
	if c24_panel.active:
		return "24S1 一发选牌"
	if c25b_panel.active:
		return "25S2 宝牌的集合换牌"
	if c30_panel.active:
		return "30S1 向听（%s）" % String(c30_panel.mode)
	if c32_panel.active:
		return "32S1 新手运（%s）" % String(c32_panel.mode)
	if c27_panel.active:
		return "27 调包/命中选牌"
	if future_active:
		return "24S2 未来排序"
	if future_ask_ui != null:
		return "24S2 未来询问"
	if c26_active:
		return "26S2 天梯排牌山"
	return ""
