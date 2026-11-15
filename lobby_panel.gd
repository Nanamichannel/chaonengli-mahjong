extends "res://lobby_cards.gd"
const UiSfx := preload("res://ui_sfx.gd")
##
## lobby_panel.gd —— 把「初始菜单」的大厅 / 选卡 / 调序 搬进真初始场景之后的面板。
##
## 和旧 initial_menu.gd 的区别：
##   · 没有背景图 / 标题 / 座位框 / 房间号输入框 / 昵称框 / 语音包下拉框
##   · 座位状态 = 输入框下方 4 行纯文字（用户名 + 已进入/加人机），无边框、无底座
##   · 房间号由二级的「搜索框」输入框传进来（begin()）
##
## 仍然复用 lobby_cards.gd 里那套：CardBank / Row / 选卡动画 / 调序 / 提交 / 进牌桌。

signal phase_changed(p: String)

# 一行一个玩家：左边（左护法正下方）是 id，右边（右护法正下方）是「已进入 / 加电脑」
# ★ 位置不再写死成「框」的坐标：以前 NAME_X/STATUS_X/LIST_TOP 是照 3D 框量出来的，
#   结果整块字落在「框下方」而不是「护法下方」（2026-11-13 用户反馈「字有点偏移」）。
#   现在两列的**列中心**和**首行 y** 全部从「左右护法」贴图实测推出来（见 _layout_from_hufa）。
const LIST_ROW_H := 36.0
const NAME_W := 190.0
const STATUS_W := 130.0
const LIST_FONT := 24
const MSG_W := 900.0
# 左右护法贴图（res://Cailiao/UI/搜索框/左右护法.png）的设计尺寸与内部排版：
#   773x172 里 左护法占 x 0..150（中心 75）、右护法占 x 620..773（中心 696），
#   脚下云朵底边在 y≈168。
const HUFA_TEX := Vector2(773.0, 172.0)
const HUFA_LEFT_CX := 75.0
const HUFA_RIGHT_CX := 696.0
const HUFA_CLOUD_BOTTOM := 168.0
const LIST_GAP_UNDER_HUFA := 2.0      # 第一行离云朵底边（px）
# 兜底（万一找不到护法节点）：等于上面那套算出来的值
const NAME_CX_FALLBACK := 662.0
const STATUS_CX_FALLBACK := 1284.0
const LIST_TOP_FALLBACK := 760.0
const COL_GREEN := Color(0.13, 0.58, 0.20)      # 已进入（暗背景上略提亮）
const COL_BLACK := Color(0.06, 0.05, 0.04)      # 加人机
const COL_MSG := Color(1.0, 0.92, 0.80)         # 提示（在面板外，浅色）

var _list_root: Control = null
var _row_name: Array = []
var _row_btn: Array = []
var _msg: Label = null
var _font: SystemFont = null
var _nick_sent := false
var _auto_fill := false        # 房间名 cardXX → 进房自动补 3 个电脑
var _auto_done := false
var _clear_bots := false      # 普通房间：把上次残留的人机清掉
var _skip_btn: TextureButton = null

# 列表布局（_layout_from_hufa 每进一次房刷新一次：护法的 position 会被 intro 改）
var _name_cx := NAME_CX_FALLBACK
var _status_cx := STATUS_CX_FALLBACK
var _list_top := LIST_TOP_FALLBACK
var _hufa: Sprite2D = null
# 正在飞的 bg 请求类型（"join" = 认领座位，要单独收）
var _bg_kind := ""


func _ready() -> void:
	visible = false                       # 由 real_start 在点【进入】后打开
	cs = get_node_or_null("/root/ClientState")
	srv = ServerBridge.new()
	start_btn = get_node_or_null("开始按钮") as BaseButton
	row = get_node_or_null("Row") as Node2D
	if row == null:
		row = Node2D.new()
		row.name = "Row"
		add_child(row)
	picked_row = Node2D.new()
	picked_row.name = "PickedRow"
	add_child(picked_row)
	bank = get_node_or_null("CardBank") as Node2D
	_prepare_cards()
	_build_ui()
	if start_btn != null:
		start_btn.visible = false
		if not start_btn.pressed.is_connected(_on_start_pressed):
			start_btn.pressed.connect(_on_start_pressed)
	if bank != null:
		bank.visible = false
	var t := Timer.new()
	t.name = "LobbyPoll"
	t.wait_time = POLL_SEC
	t.autostart = true
	t.timeout.connect(_poll)
	add_child(t)
	UiSfx.hook_buttons(self)     # 房间里的 开始 / 卡片 / 机器人行 / 跳过


# ── 外部入口：房间号（来自二级「搜索框」输入框）────────────────────
func begin(room: String) -> void:
	visible = true
	if srv == null or srv.net == null:
		_set_hint("单机模式：没有房间")
		return
	var want := room.strip_edges()
	if want == "":
		want = "default"
	if want != String(srv.net.room):
		if not srv.net.set_room(want):
			_set_hint("房间号不合法")
			return
	# 换房间 = 换一张桌：本地状态清干净
	my_seat = -1
	lobby = {}
	phase = "waiting"
	entered = false
	order.clear()
	selected_no = -1
	order_inited = false
	my_ready = false
	draft_round = -1
	if cs != null:
		cs.seat = -1
		cs.lobby = {}
		cs.orders = []
		cs.picks = []
	_set_hint("")
	_auto_fill = want.to_lower().begins_with("card")
	_auto_done = false
	_clear_bots = not _auto_fill
	var _pt := get_node_or_null("LobbyPoll")
	if _pt != null:
		_pt.start()
	joined = true
	_nick_sent = false
	_bg_wait = false
	_bg_kind = ""
	_layout_from_hufa()          # 护法位置被 intro 挪过 → 每次进房重算两列坐标
	_apply_layout()
	_refresh_seats()
	_join_lobby()                # 非阻塞：发出去立刻返回，结果下一帧收（见 _poll）


# ── UI：4 行纯文字（用户名 + 已进入/加人机）────────────────────────
func _build_ui() -> void:
	_font = SystemFont.new()
	_font.font_names = PackedStringArray(["Microsoft YaHei", "Microsoft YaHei UI", "SimHei", "sans-serif"])

	_list_root = Control.new()
	_list_root.name = "PlayerList"
	_list_root.set_anchors_preset(Control.PRESET_FULL_RECT)
	_list_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_list_root)

	for i in range(4):
		var y := _list_top + float(i) * LIST_ROW_H
		var nl := Label.new()
		nl.name = "RowName%d" % i
		nl.position = Vector2(_name_cx - NAME_W * 0.5, y)
		nl.size = Vector2(NAME_W, LIST_ROW_H)
		nl.mouse_filter = Control.MOUSE_FILTER_IGNORE
		nl.add_theme_font_override("font", _font)
		nl.add_theme_font_size_override("font_size", LIST_FONT)
		nl.add_theme_color_override("font_color", COL_BLACK)
		nl.add_theme_color_override("font_outline_color", Color(1.0, 0.97, 0.86, 0.9))
		nl.add_theme_constant_override("outline_size", 6)
		nl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER   # 居中对齐到护法中心
		nl.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		_list_root.add_child(nl)
		_row_name.append(nl)

		var bb := Button.new()
		bb.name = "RowStatus%d" % i
		bb.flat = true
		bb.focus_mode = Control.FOCUS_NONE
		bb.position = Vector2(_status_cx - STATUS_W * 0.5, y)
		bb.size = Vector2(STATUS_W, LIST_ROW_H)
		bb.alignment = HORIZONTAL_ALIGNMENT_CENTER
		bb.add_theme_font_override("font", _font)
		bb.add_theme_font_size_override("font_size", LIST_FONT)
		bb.add_theme_color_override("font_color", COL_BLACK)
		bb.add_theme_color_override("font_hover_color", COL_BLACK)
		bb.add_theme_color_override("font_pressed_color", COL_BLACK)
		bb.add_theme_color_override("font_disabled_color", COL_GREEN)
		bb.add_theme_color_override("font_outline_color", Color(1.0, 0.97, 0.86, 0.9))
		bb.add_theme_constant_override("outline_size", 6)
		var empty := StyleBoxEmpty.new()
		for st in ["normal", "hover", "pressed", "focus", "disabled"]:
			bb.add_theme_stylebox_override(st, empty)
		bb.pressed.connect(_on_row_bot_pressed.bind(i))
		_list_root.add_child(bb)
		_row_btn.append(bb)

	_msg = Label.new()
	_msg.name = "LobbyMsg"
	_msg.position = Vector2(960.0 - MSG_W * 0.5, _list_top + 4.0 * LIST_ROW_H + 6.0)
	_msg.size = Vector2(MSG_W, LIST_ROW_H)
	_msg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_msg.add_theme_font_override("font", _font)
	_msg.add_theme_font_size_override("font_size", LIST_FONT)
	_msg.add_theme_color_override("font_color", COL_MSG)
	_msg.add_theme_color_override("font_outline_color", Color(0.05, 0.04, 0.06))
	_msg.add_theme_constant_override("outline_size", 4)
	_msg.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER     # 提示行在框正下方居中
	_msg.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	_list_root.add_child(_msg)

	# 左上角：跳过（退出房间）
	_skip_btn = TextureButton.new()
	_skip_btn.name = "SkipRoom"
	_skip_btn.texture_normal = load("res://Cailiao/UI/tiaoguo.png")
	_skip_btn.ignore_texture_size = true
	_skip_btn.stretch_mode = TextureButton.STRETCH_KEEP_ASPECT_CENTERED
	_skip_btn.position = Vector2(22, 16)
	_skip_btn.size = Vector2(84, 92)
	_skip_btn.mouse_filter = Control.MOUSE_FILTER_STOP
	_skip_btn.pressed.connect(quit_room)
	add_child(_skip_btn)


# ── 布局：一切以「左右护法」贴图实测为准（不再照 3D 框的坐标写死）──────
#   · 两列的列中心 = 左/右护法在贴图里的中心（75 / 696）
#   · 首行 y = 护法云朵底边（贴图 y≈168）往下 2px
#   护法节点的 position 会被 intro 改（708.8 → 676.9），所以每次进房都重算。
func _find_hufa() -> Sprite2D:
	var host := get_parent()
	if host != null:
		host = host.get_parent()
	if host == null:
		return null
	var stage := host.get_node_or_null("搜索框")
	if stage == null:
		stage = host.get_node_or_null("合成 1")
	if stage == null:
		return null
	return stage.find_child("左右护法", true, false) as Sprite2D


func _layout_from_hufa() -> void:
	_hufa = _find_hufa()
	if _hufa == null or _hufa.texture == null:
		return
	var sz := Vector2(_hufa.texture.get_size())
	var sx := _hufa.scale.x if not is_zero_approx(_hufa.scale.x) else 1.0
	var sy := _hufa.scale.y if not is_zero_approx(_hufa.scale.y) else 1.0
	var kx := sz.x / HUFA_TEX.x                 # 实际贴图 / 设计尺寸
	var ky := sz.y / HUFA_TEX.y
	var top_left := _hufa.position + _hufa.offset * _hufa.scale
	_name_cx = top_left.x + HUFA_LEFT_CX * kx * sx
	_status_cx = top_left.x + HUFA_RIGHT_CX * kx * sx
	_list_top = top_left.y + (HUFA_CLOUD_BOTTOM * ky + LIST_GAP_UNDER_HUFA) * sy


func _apply_layout() -> void:
	for i in range(4):
		var y := _list_top + float(i) * LIST_ROW_H
		(_row_name[i] as Control).position = Vector2(_name_cx - NAME_W * 0.5, y)
		(_row_btn[i] as Control).position = Vector2(_status_cx - STATUS_W * 0.5, y)
	if _msg != null:
		_msg.position = Vector2(960.0 - MSG_W * 0.5, _list_top + 4.0 * LIST_ROW_H + 6.0)
		_msg.size = Vector2(MSG_W, LIST_ROW_H)


# 预热：进房那一帧才第一次画中文（24px + 6px 描边）要现栅格化字形，
# 会有一下明显掉帧（用户 2026-11-13「加载出 ID 和已进入时卡顿」）。
# 场景刚加载时用「几乎全透明」先把这些字画两帧，把字形缓存提前做掉。
func prewarm() -> void:
	if _list_root == null or _row_name.is_empty():
		return
	var keep := visible
	modulate = Color(1, 1, 1, 0.004)      # 不用 0：要保证真的走一遍绘制
	visible = true
	_list_root.visible = true
	for i in range(4):
		(_row_name[i] as Label).text = "玩家%d" % (i + 1)
		(_row_name[i] as Label).visible = true
		(_row_btn[i] as Button).text = "已进入"
		(_row_btn[i] as Button).visible = true
	if _msg != null:
		_msg.text = "正在加入房间…"
	await get_tree().process_frame
	await get_tree().process_frame
	for i in range(4):
		(_row_name[i] as Label).visible = false
		(_row_name[i] as Label).text = ""
		(_row_btn[i] as Button).visible = false
		(_row_btn[i] as Button).text = ""
	if _msg != null:
		_msg.text = ""
	_list_root.visible = false
	modulate = Color(1, 1, 1, 1)
	visible = keep


# 旧菜单里的这些 UI 这里不要
func _build_room_ui() -> void:
	pass


func _make_voice_picker() -> void:
	pass


func _refresh_my_wind() -> void:
	pass


func _refresh_hint() -> void:
	pass


func _show_enter_hint() -> void:
	pass


func _set_hint(t: String) -> void:
	if _msg != null:
		_msg.text = t


# ── 座位列表：用户名 + 已进入（绿）/ 加人机（黑）────────────────────
# 点左上角「跳过」：退出房间 → 回一级（real_start 收到 phase_changed("quit") 收尾）
func quit_room() -> void:
	if my_seat >= 0:
		_request_noblock({"op": "lobby_leave", "seat": my_seat})
	_bg_wait = false
	_bg_kind = ""
	var t := get_node_or_null("LobbyPoll")
	if t != null:
		t.stop()
	my_seat = -1
	joined = false
	lobby = {}
	phase = "waiting"
	entered = false
	order.clear()
	selected_no = -1
	order_inited = false
	my_ready = false
	draft_round = -1
	_nick_sent = false
	_auto_fill = false
	_auto_done = false
	_clear_bots = false
	if cs != null:
		cs.lobby = {}
		cs.orders = []
		cs.picks = []
	if bank != null:
		bank.visible = false
	if start_btn != null:
		start_btn.visible = false
	for no in card_buttons.keys():
		card_buttons[no].visible = false
	_clear(row)
	_clear(picked_row)
	if _list_root != null:
		_list_root.visible = false
	if _msg != null:
		_msg.text = ""
	visible = false
	phase_changed.emit("quit")


# 发一个请求但不阻塞主线程：联机交给 bg 通道（结果由下一轮 _poll 带回来）
func _request_noblock(req: Dictionary) -> void:
	if srv == null:
		return
	if srv.has_method("bg_send") and bool(srv.bg_ok()) and bool(srv.bg_send(req)):
		_bg_wait = true
		_bg_kind = "req"
		return
	# bg 正忙（有请求在飞）→ 这条是「必须送达」的动作（加电脑/退出房间），
	# 不能像轮询那样直接丢掉；退化成一次同步请求（~100ms）也能接受。
	var r: Dictionary = srv.request(req)
	if bool(r.get("ok", false)) and r.has("lobby"):
		_apply_lobby(r.get("lobby", {}))


# ── 进房（认领座位）：一律非阻塞 ─────────────────────────────────────
# ★ 以前这里是同步 srv.request()，点【进入】那一帧要等一整个往返
#   （本机 ~30ms、云端 100~300ms）→ 就是「加载出 ID 和已进入时明显卡一下」。
#   现在发出去立刻返回，座位由下一帧的 _poll 收（进房瞬间的 _process 会连收）。
func _join_lobby() -> void:
	if srv == null:
		return
	if srv.has_method("bg_send") and bool(srv.bg_ok()):
		if bool(srv.bg_busy()):
			return                              # 有请求在飞：下一帧再试
		if bool(srv.bg_send({"op": "lobby_join", "seat": -1})):
			_bg_wait = true
			_bg_kind = "join"
		return
	var _t0 := Time.get_ticks_msec()
	var r: Dictionary = srv.request({"op": "lobby_join", "seat": -1})
	last_req_ms = Time.get_ticks_msec() - _t0
	_handle_join(r)


# join 的回包：认领座位 + 应用大厅状态（失败提示和原来一致）
func _handle_join(r: Dictionary) -> void:
	if not bool(r.get("ok", false)):
		var why := String(r.get("error", "未知错误"))
		if why.find("已满") >= 0:
			_set_hint("房间已满（4/4）—— 有人退出后会自动加入")
		else:
			var why2 := _net_why(r)
			_set_hint(why2)
			_net_badge_show(why2)
		if why != _last_join_err:
			_last_join_err = why
			print("initial_menu: 加入大厅失败，稍后自动重试：", why)
		return
	_last_join_err = ""
	_set_hint("")
	_net_badge_show("")
	my_seat = clampi(int(r.get("seat", 0)), 0, 3)
	if cs != null:
		cs.seat = my_seat
	var _lb: Dictionary = r.get("lobby", {})
	_need_manual_enter = String(_lb.get("phase", "")) == "play"
	_apply_lobby(_lb)


# join 在飞时每帧顺手收一下（不用等 0.35s 的轮询节拍，名字立刻出来）
func _process(delta: float) -> void:
	super._process(delta)
	if srv == null:
		return
	if _bg_wait:
		_poll()
	elif srv.has_method("bg_busy") and bool(srv.bg_busy()):
		# 有请求在飞但没人认领（换房间时把上一个 join 丢了就是这样）：
		# 不推它走完的话 bg 会永远 busy → 之后再也发不出 join，进房一直等不到座位。
		srv.bg_poll()


func _poll() -> void:
	if _bg_wait and _bg_kind == "join" and srv != null:
		var rb: Dictionary = srv.bg_poll() if srv.has_method("bg_poll") else {}
		if srv.has_method("bg_busy") and not bool(srv.call("bg_busy")):
			_bg_wait = false                  # 请求已经不在了（超时/断开）
		if rb.is_empty():
			return
		_bg_wait = false
		_bg_kind = ""
		_handle_join(rb)
		return
	super._poll()


# 服务端回来的 bots 是 [1.0, 3.0]（JSON 数字）；Array.has(1) 对 1.0 会返回 false，
# 所以统一转成 int 集合再判断。
func _bot_set() -> Dictionary:
	var out := {}
	for v in (lobby.get("bots", []) as Array):
		out[int(v)] = true
	return out


func _refresh_seats() -> void:
	if _list_root == null:
		return
	var seats: Array = lobby.get("seats", [])
	var bots: Dictionary = _bot_set()
	var jd: Array = lobby.get("joined", [])

	var here: Array = []
	for s in range(4):
		var st: Dictionary = seats[s] if s < seats.size() and typeof(seats[s]) == TYPE_DICTIONARY else {}
		var nick := String(st.get("nick", "")).strip_edges()
		var is_bot := bots.has(s)
		var joined_h := (s < jd.size() and bool(jd[s])) or s == my_seat
		if nick == "" and not is_bot and not joined_h:
			continue
		here.append(s)

	var rows: Array = []
	for s in here:
		var st2: Dictionary = seats[s] if s < seats.size() and typeof(seats[s]) == TYPE_DICTIONARY else {}
		var nm := String(st2.get("nick", "")).strip_edges()
		if bots.has(s):
			nm = "电脑%d" % (s + 1)
		elif nm == "":
			nm = "玩家%d" % (s + 1)
		rows.append({"name": nm, "add": false})

	if phase == "waiting" and here.size() < 4 and my_seat >= 0:
		rows.append({"name": "", "add": true})

	for i in range(4):
		var nl: Label = _row_name[i]
		var bb: Button = _row_btn[i]
		if i >= rows.size():
			nl.visible = false
			bb.visible = false
			continue
		var r: Dictionary = rows[i]
		if bool(r.add):
			nl.text = ""
			nl.visible = false
			bb.text = "加电脑"
			bb.add_theme_color_override("font_color", COL_BLACK)
			bb.add_theme_color_override("font_hover_color", Color(0.35, 0.22, 0.10))
			bb.disabled = false
		else:
			nl.text = String(r.name)
			nl.visible = true
			bb.text = "已进入"
			bb.disabled = true
		bb.visible = true

	# 4 人齐 → 把 cardbank + 开始按钮 弹出来
	var full := here.size() >= 4
	var in_draft := phase == "draft" or phase == "order"
	if bank != null:
		bank.visible = full or in_draft
	if start_btn != null:
		# play 阶段：中途加入的人要靠「开始」进牌桌（base 的 _need_manual_enter）
		start_btn.visible = full or in_draft or phase == "play"


# 点「加人机」：占第一个空座位（人机名 = 电脑(座位号+1)）
func _on_row_bot_pressed(_row: int) -> void:
	if my_seat < 0 or phase != "waiting":
		return
	var seats: Array = lobby.get("seats", [])
	var bots: Dictionary = _bot_set()
	var jd: Array = lobby.get("joined", [])
	var target := -1
	for s in range(4):
		var st: Dictionary = seats[s] if s < seats.size() and typeof(seats[s]) == TYPE_DICTIONARY else {}
		var nick := String(st.get("nick", "")).strip_edges()
		var joined_h := (s < jd.size() and bool(jd[s])) or s == my_seat
		if not joined_h and nick == "" and not bots.has(s):
			target = s
			break
	if target < 0:
		return
	# 非阻塞：结果由下一轮 _poll 带回来（同步请求在公网上会把界面卡 200~300ms）
	_set_hint("")
	_request_noblock({"op": "lobby_add_bot", "seat": my_seat, "bot_seat": target})


# ── 阶段变化：进 draft/order 就把「人名 + 已进入」这层关掉 ──────────
func _apply_lobby(l) -> void:
	var prev := phase
	super._apply_lobby(l)
	if phase != prev:
		phase_changed.emit(phase)
	if _list_root != null:
		_list_root.visible = (phase == "waiting")
	# 普通房间：上次残留的人机清掉（每个 poll 清一个）
	if _clear_bots and my_seat >= 0 and phase == "waiting":
		var bset0 := _bot_set()
		if bset0.is_empty():
			_clear_bots = false
		elif not srv.has_method("bg_busy") or not bool(srv.bg_busy()):
			var tgt0 := int(bset0.keys()[0])
			_request_noblock({"op": "lobby_remove_bot", "seat": my_seat, "bot_seat": tgt0})

	# cardXX 房间：进来默认就带 3 个电脑（每次 poll 补一个，不卡主线程）
	if _auto_fill and not _auto_done and my_seat >= 0 and phase == "waiting":
		var bset := _bot_set()
		if bset.size() >= 3:
			_auto_done = true
		elif not srv.has_method("bg_busy") or not bool(srv.bg_busy()):
			var seats2: Array = lobby.get("seats", [])
			var jd2: Array = lobby.get("joined", [])
			var tgt := -1
			for ss in range(4):
				var st: Dictionary = seats2[ss] if ss < seats2.size() and typeof(seats2[ss]) == TYPE_DICTIONARY else {}
				var jh := (ss < jd2.size() and bool(jd2[ss])) or ss == my_seat
				if not jh and String(st.get("nick", "")).strip_edges() == "" and not bset.has(ss):
					tgt = ss
					break
			if tgt >= 0:
				_request_noblock({"op": "lobby_add_bot", "seat": my_seat, "bot_seat": tgt})

	if my_seat >= 0 and not _nick_sent and phase == "waiting":
		var st := _seat_data(my_seat)
		if String(st.get("nick", "")).strip_edges() == "":
			_nick_sent = true
			srv.request({"op": "rename", "seat": my_seat, "nick": "玩家%d" % (my_seat + 1)})
