extends Node2D

# ── 初始菜单 = 四个客户端的大厅 ─────────────────────────────────────
# 四个 Godot 实例 = 四个客户端，各自向服务端认领一个座位（server/lobby.py）。
#
#   waiting  点「开始」= 准备，按钮外出现偏粗黄色框；四家都准备 → 随机 20 张
#   draft    传递选卡：随机 20 张、一家 5 张；每人留 1 张，
#            剩下 4 张整手传给下家（0→1→2→3→0），一共转 5 轮
#   order    把自己的 5 张排成 1..5（1-4 主战、5 协战），点「开始」提交
#            （提交后同样出黄色框，表示这一家准备好了）
#   play     四家都提交 → 一起进 node_2d
#
# 状态/校验全在服务端，客户端只负责显示和把点击发上去。

const CARD_COUNT := 46
const POLL_SEC := 0.35

const CARD_SCALE := 0.70        # 手里的牌（传递选卡 / 调序）
const PICK_SCALE := 0.22        # 已经留到自己名下的牌（左下角）
const ROW_CENTER_Y := 500.0
const SCREEN_W := 1920.0
const SCREEN_H := 1080.0

# 抽卡时的「滑进来 / 滑出去」动效（和之前一样）
var slide_time := 0.45         # 滑入 / 滑出各用时；要观察动画可临时调大
const EDGE_MARGIN := 220.0

const ORDERS_PATH := "user://player_orders.json"
const ORDER_PATH := "user://player_order.json"   # 本家自己那 5 张（身份卡兜底用）
const MENU_FLAG := "user://from_initial_menu.flag"

const SEAT_NAMES := ["我", "下家", "对家", "上家"]

var srv: ServerBridge
var start_btn: BaseButton
var row: Node2D
var picked_row: Node2D
var bank: Node2D
var card_buttons := {}

var cs: Node = null
var my_seat := -1
var lobby: Dictionary = {}
var phase := "waiting"
var selected_no := -1
var order: Array = []
var order_inited := false
var my_ready := false
var entered := false

var draft_round := -1
var pick_animating := false

var row_tween: Tween = null
var row_animating := false
var row_width := 0.0

var title: Label
var hint: Label
var seat_box: ColorRect
var seat_labels: Array = []
var ready_label: Label
var ready_frame: ReferenceRect


# ══════════════════════════════════════════════════════════════════════════
#  【测试用】跳过选角色阶段，直接指定四家的出战人物
#    · 用 txt 改：项目根目录放 test_seats.cfg（格式见 _test_seats_orders）
#    · 或用脚本改：把 TEST_SEATS_OVERRIDE 填成 4x5 的卡号数组（优先）
#  一行格式： seat0 = 7,17,18,19,12   （前 4 张 = 主战，第 5 张 = 协战）
# ══════════════════════════════════════════════════════════════════════════
const TEST_SEATS_CFG := "res://test_seats.cfg"

# 想直接写死在脚本里就用这个（非空即生效）：4 家 x 5 张
const TEST_SEATS_OVERRIDE: Array = []


func _test_seats_orders() -> Array:
	if TEST_SEATS_OVERRIDE.size() == 4:
		return TEST_SEATS_OVERRIDE
	if not FileAccess.file_exists(TEST_SEATS_CFG):
		return []
	var f := FileAccess.open(TEST_SEATS_CFG, FileAccess.READ)
	if f == null:
		return []
	var lines := f.get_as_text().split("\n")
	f.close()
	var out: Array = [[], [], [], []]
	var enabled := true
	for line in lines:
		var t := String(line).strip_edges()
		if t == "" or t.begins_with("#"):
			continue
		var eq := t.find("=")
		if eq <= 0:
			continue
		if t.substr(0, eq).strip_edges().to_lower() == "enabled":
			enabled = int(t.substr(eq + 1).strip_edges()) != 0
			continue
		var key := t.substr(0, eq).strip_edges().to_lower()
		var seat := -1
		if key.begins_with("seat"):
			seat = int(key.substr(4).strip_edges())
		elif key.begins_with("窗口"):
			seat = int(key.substr(2).strip_edges()) - 1        # 窗口1..4 → 座位0..3
		if seat < 0 or seat > 3:
			continue
		var arr: Array = []
		for piece in t.substr(eq + 1).split(","):
			var v := String(piece).strip_edges()
			if v != "":
				arr.append(int(v))
		if arr.size() == 5:
			out[seat] = arr
	if not enabled:
		print("[TEST_SEATS] enabled=0 → 走正常的选角色流程")
		return []
	for s2 in range(4):
		if (out[s2] as Array).is_empty():
			print("[TEST_SEATS] 缺少 seat%d，放弃跳过", s2)
			return []
	return out


func _test_seats_maybe() -> void:
	var orders := _test_seats_orders()
	if orders.is_empty():
		return
	print("[TEST_SEATS] 跳过选角色：", JSON.stringify(orders))
	# ① 先把四家的 5 张卡告诉服务端（技能归属以服务端为准）
	var r: Dictionary = srv.request({"op": "test_seats", "orders": orders,
		"seat": int(my_seat) if int(my_seat) >= 0 else 0})
	if not bool(r.get("ok", false)):
		print("[TEST_SEATS] 服务端拒绝：", String(r.get("error", "")))
		return
	# ② 本地记录也写好（身份卡的兜底数据 + 之后 reload_orders 用）
	var pick: Array = orders[0]
	if int(my_seat) >= 0 and int(my_seat) < 4:
		pick = orders[int(my_seat)]
	if cs != null:
		cs.orders = orders.duplicate(true)
		cs.picks = pick.duplicate()
	var wf := FileAccess.open(ORDER_PATH, FileAccess.WRITE)
	if wf != null:
		wf.store_string(JSON.stringify(pick))
		wf.close()
	var wf2 := FileAccess.open(ORDERS_PATH, FileAccess.WRITE)
	if wf2 != null:
		wf2.store_string(JSON.stringify(orders))
		wf2.close()
	# ③ 直接进牌桌
	var flag := FileAccess.open(MENU_FLAG, FileAccess.WRITE)
	if flag != null:
		flag.store_string("1")
		flag.close()
	get_tree().change_scene_to_file("res://node_2d.tscn")


const SkinPatch := preload("res://skin.gd")   # 外部皮肤（exe 同目录 skin\）


func _ready() -> void:
	call_deferred("_test_seats_maybe")      # 测试用：有 test_seats.cfg 就直接进牌桌
	get_tree().auto_accept_quit = false     # 关窗口要先清记录再退
	cs = get_node_or_null("/root/ClientState")
	srv = ServerBridge.new()
	start_btn = get_node_or_null("开始按钮") as BaseButton
	if start_btn == null:
		start_btn = get_node_or_null("StartButton") as BaseButton
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
	_build_room_ui()
	if start_btn != null and not start_btn.pressed.is_connected(_on_start_pressed):
		start_btn.pressed.connect(_on_start_pressed)
	_wipe_if_fresh()                    # 上一次记录没清干净 → 这里补一刀，从「准备」重新开始
	_join_lobby()
	var t := Timer.new()
	t.name = "LobbyPoll"
	t.wait_time = POLL_SEC
	t.autostart = true
	t.timeout.connect(_poll)
	add_child(t)

	# ── 外部皮肤（exe 同目录 skin\ 或 user://skin）：没有图就什么都不做 ──
	SkinPatch.setup()
	var _skin_scene := get_tree().current_scene
	if _skin_scene != null:
		SkinPatch.apply_tree(_skin_scene)
	SkinPatch.hook(get_tree())


# ── 每次运行都从「准备」开始 ───────────────────────────────────────
# 编辑器停止 / 强杀进程时不一定来得及清，所以启动时也查一次：
# 没有别的窗口在（没有活着的座位租约）= 这是一次全新的运行 → 服务端记录全部清空。
const LOCAL_RECORD_FILES := ["user://player_orders.json", "user://player_order.json",
	"user://player_cards.json", "user://from_initial_menu.flag",
	"user://hanchan_owner.json"]


func _wipe_if_fresh() -> void:
	if srv == null:
		return
	var r: Dictionary = srv.request({"op": "wipe"})
	if not bool(r.get("wiped", false)):
		return
	_clear_local_records()
	if cs != null:
		cs.orders = []
		cs.picks = []
		cs.lobby = {}


func _clear_local_records() -> void:
	for p in LOCAL_RECORD_FILES:
		if FileAccess.file_exists(String(p)):
			DirAccess.remove_absolute(ProjectSettings.globalize_path(String(p)))
	# 顺手清掉历史运行留下的请求/响应临时文件（只在「没有别的窗口」时才会走到这里）
	var dir := DirAccess.open("user://")
	if dir != null:
		dir.list_dir_begin()
		var f := dir.get_next()
		while f != "":
			if f.begins_with("srv_req_") or f.begins_with("srv_res_"):
				dir.remove(f)
			f = dir.get_next()
		dir.list_dir_end()


# 关窗口：如果自己是最后一个窗口，服务端会把整局记录清掉，下次启动不继承进度
func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST:
		_on_window_closing()


func _on_window_closing() -> void:
	get_tree().auto_accept_quit = false
	if srv != null:
		srv.request({"op": "wipe", "seat": my_seat if my_seat >= 0 else -1})
	_clear_local_records()
	get_tree().quit()


# ── 场景里现成的 46 张卡 ───────────────────────────────────────────
func _prepare_cards() -> void:
	if bank == null:
		return
	for i in range(1, CARD_COUNT + 1):
		var b = bank.get_node_or_null("Card%02d" % i)
		if b == null:
			continue
		b.set("card_no", i)
		b.scale = Vector2.ONE
		b.visible = false
		if not b.card_clicked.is_connected(_on_card_clicked):
			b.card_clicked.connect(_on_card_clicked)
		card_buttons[i] = b


# ── 大厅 UI（座位状态 / 提示 / 准备黄框）────────────────────────────
func _build_ui() -> void:
	var ui := Control.new()
	ui.name = "LobbyUI"
	ui.set_anchors_preset(Control.PRESET_FULL_RECT)
	ui.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(ui)

	# 左上角的标题 / 提示文字已按要求移除（title / hint 保持为 null，
	# _set_hint() 与 _refresh_seats() 里都有 null 判断，不会报错）。

	# 右下角：四家状态
	seat_box = ColorRect.new()
	seat_box.name = "SeatBox"
	seat_box.color = Color(0.02, 0.03, 0.08, 0.72)
	seat_box.position = Vector2(1430, 786)
	seat_box.size = Vector2(460, 270)
	seat_box.mouse_filter = Control.MOUSE_FILTER_IGNORE
	ui.add_child(seat_box)

	for g in range(4):
		var lb := Label.new()
		lb.name = "Seat%d" % g
		lb.position = Vector2(1444, 796 + g * 44)
		lb.size = Vector2(440, 40)
		lb.mouse_filter = Control.MOUSE_FILTER_IGNORE
		lb.add_theme_font_size_override("font_size", 21)
		lb.add_theme_color_override("font_outline_color", Color(0.04, 0.04, 0.08))
		lb.add_theme_constant_override("outline_size", 4)
		ui.add_child(lb)
		seat_labels.append(lb)

	ready_label = Label.new()
	ready_label.name = "ReadyCount"
	ready_label.position = Vector2(1444, 796 + 4 * 44)
	ready_label.size = Vector2(440, 36)
	ready_label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	ready_label.add_theme_font_size_override("font_size", 22)
	ready_label.add_theme_color_override("font_color", Color(1, 0.85, 0.35))
	ready_label.add_theme_color_override("font_outline_color", Color(0.1, 0.06, 0.0))
	ready_label.add_theme_constant_override("outline_size", 4)
	ui.add_child(ready_label)

	# 「开始」按钮外面那圈偏粗的黄框
	ready_frame = ReferenceRect.new()
	ready_frame.name = "ReadyFrame"
	ready_frame.editor_only = false
	ready_frame.border_color = Color(1.0, 0.82, 0.16, 1.0)
	ready_frame.border_width = 12.0
	ready_frame.mouse_filter = Control.MOUSE_FILTER_IGNORE
	ready_frame.visible = false
	ready_frame.z_index = 20
	ui.add_child(ready_frame)


# ── 房间号（只在联机模式出现）：改完点「進入」立刻换桌，本机会记住 ──────
var room_edit: LineEdit = null
var room_btn: Button = null
var _room_flash := 0


var net_badge: Label = null


# 连不上服务端时的一行提示（放左上角，平时隐藏）
func _make_net_badge() -> void:
	net_badge = Label.new()
	net_badge.name = "NetBadge"
	net_badge.position = Vector2(24, 22)
	net_badge.size = Vector2(1560, 34)
	net_badge.mouse_filter = Control.MOUSE_FILTER_IGNORE
	net_badge.add_theme_font_size_override("font_size", 20)
	net_badge.add_theme_color_override("font_color", Color(1.0, 0.72, 0.42))
	net_badge.add_theme_color_override("font_outline_color", Color(0.06, 0.03, 0.02))
	net_badge.add_theme_constant_override("outline_size", 4)
	net_badge.visible = false
	add_child(net_badge)


func _net_badge_show(text: String) -> void:
	if net_badge == null or not is_instance_valid(net_badge):
		return
	net_badge.text = text
	net_badge.visible = text != ""


func _build_room_ui() -> void:
	if srv == null or srv.net == null or not bool(srv.net.enabled):
		return                                  # 单机：没有房间概念
	_make_net_badge()

	var tag := Label.new()
	tag.name = "RoomTag"
	tag.text = "房間"
	tag.position = Vector2(1418, 34)
	tag.size = Vector2(74, 34)
	tag.mouse_filter = Control.MOUSE_FILTER_IGNORE
	tag.add_theme_font_size_override("font_size", 22)
	tag.add_theme_color_override("font_color", Color(1, 0.93, 0.8))
	tag.add_theme_color_override("font_outline_color", Color(0.05, 0.05, 0.1))
	tag.add_theme_constant_override("outline_size", 5)
	add_child(tag)

	room_edit = LineEdit.new()
	room_edit.name = "RoomEdit"
	room_edit.text = String(srv.net.room)
	room_edit.placeholder_text = "房間號"
	room_edit.max_length = 24
	room_edit.position = Vector2(1496, 28)
	room_edit.size = Vector2(228, 44)
	room_edit.add_theme_font_size_override("font_size", 22)
	# 跟初始菜单同一套粉金配色（默认 LineEdit 是灰底，太出戏）
	var sb := StyleBoxFlat.new()
	sb.bg_color = Color(0.16, 0.06, 0.12, 0.80)
	sb.border_color = Color(0.965, 0.616, 0.749, 0.85)
	sb.set_border_width_all(2)
	sb.set_corner_radius_all(9)
	sb.content_margin_left = 10.0
	sb.content_margin_right = 10.0
	room_edit.add_theme_stylebox_override("normal", sb)
	room_edit.add_theme_stylebox_override("read_only", sb)
	var sbf := sb.duplicate() as StyleBoxFlat
	sbf.border_color = Color(1.0, 0.79, 0.86, 1.0)
	sbf.set_border_width_all(2)
	room_edit.add_theme_stylebox_override("focus", sbf)
	room_edit.add_theme_color_override("font_color", Color(1.0, 0.96, 0.98))
	room_edit.add_theme_color_override("font_placeholder_color", Color(1.0, 0.85, 0.90, 0.55))
	room_edit.add_theme_color_override("caret_color", Color(1.0, 0.79, 0.86))
	room_edit.add_theme_color_override("selection_color", Color(0.965, 0.616, 0.749, 0.45))
	room_edit.text_submitted.connect(_on_room_submitted)
	add_child(room_edit)

	room_btn = Button.new()
	room_btn.name = "RoomBtn"
	room_btn.text = "進入"
	room_btn.position = Vector2(1734, 28)
	room_btn.size = Vector2(140, 44)
	room_btn.add_theme_font_size_override("font_size", 22)
	var bsb := StyleBoxFlat.new()
	bsb.bg_color = Color(0.965, 0.616, 0.749, 0.92)
	bsb.set_corner_radius_all(9)
	room_btn.add_theme_stylebox_override("normal", bsb)
	var bsbh := bsb.duplicate() as StyleBoxFlat
	bsbh.bg_color = Color(1.0, 0.72, 0.83, 1.0)
	room_btn.add_theme_stylebox_override("hover", bsbh)
	var bsbd := bsb.duplicate() as StyleBoxFlat
	bsbd.bg_color = Color(0.85, 0.50, 0.62, 1.0)
	room_btn.add_theme_stylebox_override("pressed", bsbd)
	room_btn.add_theme_stylebox_override("focus", bsb)
	room_btn.add_theme_color_override("font_color", Color(0.24, 0.05, 0.13))
	room_btn.add_theme_color_override("font_hover_color", Color(0.24, 0.05, 0.13))
	room_btn.add_theme_color_override("font_pressed_color", Color(0.24, 0.05, 0.13))
	room_btn.pressed.connect(_on_room_apply)
	add_child(room_btn)


func _on_room_submitted(_t: String) -> void:
	_on_room_apply()
	if room_edit != null:
		room_edit.release_focus()


func _on_room_apply() -> void:
	if srv == null or srv.net == null or room_edit == null:
		return
	var want := room_edit.text.strip_edges()
	if want == "":
		want = "default"
	if want == String(srv.net.room):
		_flash_room_btn("已在此房間")
		return
	if not srv.net.set_room(want):
		_flash_room_btn("房間號不合法")
		return
	# 换房间 = 换一张四人桌：本地座位/大厅/选卡状态全部清掉，再重新入座
	my_seat = -1
	lobby = {}
	phase = "waiting"
	entered = false
	order.clear()
	selected_no = -1
	order_inited = false
	my_ready = false
	room_edit.text = String(srv.net.room)
	if cs != null:
		cs.seat = -1
		cs.lobby = {}
		cs.orders = []
		cs.picks = []
	_set_hint("正在進入房間「%s」…" % String(srv.net.room))
	_flash_room_btn("進入中…")
	_join_lobby()
	_refresh_seats()


func _flash_room_btn(t: String) -> void:
	if room_btn == null or not is_instance_valid(room_btn):
		return
	room_btn.text = t
	_room_flash += 1
	var tok := _room_flash
	await get_tree().create_timer(1.4).timeout
	if is_instance_valid(room_btn) and tok == _room_flash:
		room_btn.text = "進入"


# ── 和服务端说话 ───────────────────────────────────────────────────
var _last_join_err := ""


# 连不上时到底为什么：把「哪个地址 + 什么原因」显示出来，朋友截图就能定位
func _net_why(r: Dictionary) -> String:
	var mode := "单机"
	var addr := ""
	if srv != null and srv.net != null:
		if not bool(srv.net.enabled):
			return "当前是单机模式（没有服务器地址）—— 请换最新版 exe"
		mode = "联机"
		addr = String(srv.net.status_text())
	var why := String(r.get("error", "")).strip_edges()
	if why == "" and srv != null and srv.net != null:
		why = String(srv.net.last_error).strip_edges()
	if why == "":
		why = "服务端没有回应"
	return "%s 连不上：%s（%s）" % [mode, why, addr]


func _join_lobby() -> void:
	var r: Dictionary = srv.request({"op": "lobby_join", "seat": -1})
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
	_apply_lobby(r.get("lobby", {}))


func _poll() -> void:
	if entered:
		return
	if my_seat < 0:
		_join_lobby()               # 还没认领到座位（上次服务端忙）→ 一直重试到成功
		return
	var r: Dictionary = srv.request({"op": "lobby_state", "seat": my_seat})
	if bool(r.get("ok", false)):
		_apply_lobby(r.get("lobby", {}))
	elif srv.net != null and bool(srv.net.enabled) and bool(srv.net.offline()):
		_net_badge_show(_net_why(r))
	else:
		_net_badge_show("")


func _apply_lobby(l) -> void:
	if typeof(l) != TYPE_DICTIONARY or (l as Dictionary).is_empty():
		return
	var prev := phase
	lobby = l
	if cs != null:
		cs.lobby = l
	phase = String(l.get("phase", "waiting"))

	var seats: Array = l.get("seats", [])
	my_ready = false
	if my_seat >= 0 and my_seat < seats.size() and typeof(seats[my_seat]) == TYPE_DICTIONARY:
		my_ready = bool((seats[my_seat] as Dictionary).get("ready", false))

	if phase == "order":
		# 不替玩家预排：进到调序界面时 5 张全是「没编号」的，
		# 玩家自己按 1→5 的顺序点
		if phase != prev:
			order_inited = false
			order.clear()
		if not order_inited:
			order_inited = true
			order.clear()
	elif phase != "order":
		order_inited = false
		order.clear()

	_refresh_seats()
	_refresh_hint()
	_refresh_ready_frame()

	if phase == "play" and not entered:
		entered = true
		_enter_game()
		return

	if phase == "draft":
		_update_draft(prev)
	else:
		draft_round = -1
		pick_animating = false
		_refresh_cards()


# 传递选卡：只在「轮次变化 / 手牌变化」时重排，选中和动画不打架
func _update_draft(prev_phase: String) -> void:
	var r := int(lobby.get("round", 0))
	var pending := _am_pending()
	if prev_phase != "draft":
		selected_no = -1
	if pick_animating or row_animating:
		return
	if pending:
		if draft_round != r or prev_phase != "draft":
			draft_round = r
			_show_waiting()
		return
	if r != draft_round:
		draft_round = r
		selected_no = -1
		_layout_hand(true)
	else:
		_refresh_cards()


func _enter_game() -> void:
	var seats: Array = lobby.get("seats", [])
	var orders: Array = []
	for s in range(4):
		var st: Dictionary = seats[s] if s < seats.size() and typeof(seats[s]) == TYPE_DICTIONARY else {}
		var o: Array = st.get("order", [])
		orders.append(o.duplicate())
	if cs != null:
		cs.orders = orders
		cs.picks = _my_picks()
	var wf := FileAccess.open(ORDERS_PATH, FileAccess.WRITE)
	if wf != null:
		wf.store_string(JSON.stringify(orders))
		wf.close()
	var flag := FileAccess.open(MENU_FLAG, FileAccess.WRITE)
	if flag != null:
		flag.store_string("1")
		flag.close()
	_set_hint("四家都准备好了，进入牌桌…")
	await get_tree().create_timer(0.35).timeout
	get_tree().change_scene_to_file("res://node_2d.tscn")


# ── 点击 ───────────────────────────────────────────────────────────
func _on_start_pressed() -> void:
	if entered or my_seat < 0:
		return
	match phase:
		"waiting":
			var want := not my_ready
			var r: Dictionary = srv.request({"op": "lobby_ready", "seat": my_seat, "value": want})
			if not bool(r.get("ok", false)):
				_set_hint(String(r.get("error", "服务端没有回应")))
				return
			_apply_lobby(r.get("lobby", {}))
		"draft":
			if pick_animating:
				return
			if selected_no < 0:
				if _am_pending():
					_set_hint("这一轮你已经留好牌了，等其他人")
				else:
					_set_hint("先点一张要留下的卡牌，再点「开始」")
				return
			var r2: Dictionary = srv.request({"op": "lobby_pick", "seat": my_seat, "card": selected_no})
			if not bool(r2.get("ok", false)):
				_set_hint(String(r2.get("error", "这张牌不能留")))
				selected_no = -1
				_poll()
				return
			selected_no = -1
			_play_pick_out(r2.get("lobby", {}))
		"order":
			if order.size() < 5:
				_set_hint("先把 5 张卡按顺序点好（1..5）")
				return
			var r3: Dictionary = srv.request({"op": "lobby_order", "seat": my_seat, "order": order})
			if not bool(r3.get("ok", false)):
				_set_hint(String(r3.get("error", "提交失败")))
				return
			_apply_lobby(r3.get("lobby", {}))


func _on_card_clicked(card_no: int) -> void:
	if entered or my_seat < 0:
		return
	if phase == "draft":
		if pick_animating:
			return
		if not _hand_has(card_no):
			return
		selected_no = -1 if selected_no == card_no else card_no
		_refresh_cards()
		_refresh_hint()
	elif phase == "order":
		if order.has(card_no):
			order.erase(card_no)
		else:
			if order.size() >= 5:
				_set_hint("已经排满 5 张了，先点一张取消编号")
				return
			order.append(card_no)
		_refresh_cards()
		_refresh_hint()


# ── 选卡动效 ───────────────────────────────────────────────────────
# 手牌一行、固定高度：从右侧滑进来（右→左）；四家都选完后整行继续往左滑出屏幕。
# 两段对称：用时相同、同一条三次曲线，进场减速停住，出场加速离开。
func _play_pick_out(new_lobby) -> void:
	pick_animating = true
	if typeof(new_lobby) == TYPE_DICTIONARY and not (new_lobby as Dictionary).is_empty():
		lobby = new_lobby
		if cs != null:
			cs.lobby = new_lobby
	_layout_picked()                      # 留下的这张立刻缩到左下角（同时从行里挪走）
	var rw := _row_width_now()
	_slide_row_out(-(rw + EDGE_MARGIN), _after_pick_out.bind(new_lobby))


func _row_width_now() -> float:
	var right := 0.0
	for c in row.get_children():
		if not (c as CanvasItem).visible:
			continue
		right = maxf(right, (c as Control).position.x + 512.0 * CARD_SCALE)
	return right



func _after_pick_out(new_lobby) -> void:
	pick_animating = false
	if typeof(new_lobby) == TYPE_DICTIONARY and not (new_lobby as Dictionary).is_empty():
		lobby = new_lobby
		if cs != null:
			cs.lobby = new_lobby
	if _am_pending():
		_show_waiting()                     # 滑出屏幕后再收牌，显示「等待其他玩家」
	else:
		draft_round = -1                  # 下一轮（可能已经推进）重新滑进来
		_apply_lobby(lobby)
	_poll()

func _kill_row_tween() -> void:
	if row_tween != null and row_tween.is_valid():
		row_tween.kill()
	row_tween = null
	row_animating = false


func _slide_row_in(target_x: float) -> void:
	_kill_row_tween()
	row.position.x = SCREEN_W + EDGE_MARGIN
	row_animating = true
	row_tween = create_tween()
	row_tween.set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
	row_tween.tween_property(row, "position:x", target_x, slide_time)
	row_tween.finished.connect(_on_row_slide_done)


func _slide_row_out(target_x: float, on_done := Callable()) -> void:
	_kill_row_tween()
	row_animating = true
	row_tween = create_tween()
	row_tween.set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_IN)
	row_tween.tween_property(row, "position:x", target_x, slide_time)
	row_tween.finished.connect(func():
		row_animating = false
		row_tween = null
		if on_done.is_valid():
			on_done.call())


func _on_row_slide_done() -> void:
	row_animating = false
	row_tween = null




# ── 刷新显示 ───────────────────────────────────────────────────────
func _refresh_hint() -> void:
	var seats: Array = lobby.get("seats", [])
	match phase:
		"waiting":
			var n := 0
			for s in seats:
				if typeof(s) == TYPE_DICTIONARY and bool((s as Dictionary).get("ready", false)):
					n += 1
			_set_hint("点击「开始」准备（%d/4 已准备）；四家都准备好后开始选卡" % n)
		"draft":
			var r := int(lobby.get("round", 0)) + 1
			if _am_pending():
				_set_hint("第 %d 轮已留牌，等待其他玩家…（每人 5 轮）" % r)
			elif selected_no >= 0:
				_set_hint("第 %d 轮：已选中 Card%02d —— 点「开始」留下它" % [r, selected_no])
			else:
				_set_hint("第 %d 轮：从手里选一张留下，剩下 4 张传给下家" % r)
		"order":
			if my_ready:
				_set_hint("顺序已提交，等待其他玩家…")
			elif order.size() < 5:
				_set_hint("按顺序点卡牌编号（1-4 主战、5 协战），点满 5 张后点「开始」提交（%d/5）" % order.size())
			else:
				_set_hint("顺序已排好 —— 点「开始」提交")
		"play":
			_set_hint("四家都准备好了，进入牌桌…")


func _refresh_seats() -> void:
	var seats: Array = lobby.get("seats", [])
	var ready_n := 0
	var pending: Array = lobby.get("pending", [])
	for g in range(4):
		var s := (my_seat + g) % 4 if my_seat >= 0 else g
		var st: Dictionary = seats[s] if s < seats.size() and typeof(seats[s]) == TYPE_DICTIONARY else {}
		var is_ready := bool(st.get("ready", false))
		if is_ready:
			ready_n += 1
		var picks: Array = st.get("picks", [])
		var state_text := "等待中"
		if phase == "draft":
			var done := bool(pending[s]) if s < pending.size() else false
			state_text = "已留 %d/5" % picks.size()
			if done and picks.size() < 5:
				state_text += " 等传牌"
		elif phase == "order":
			state_text = "已提交" if is_ready else "调序中 %d/5" % picks.size()
		elif phase == "play":
			state_text = "已就绪"
		elif is_ready:
			state_text = "已准备"
		var lb: Label = seat_labels[g] if g < seat_labels.size() else null
		if lb != null:
			lb.text = " %s·%d号   %s" % [SEAT_NAMES[g], s, state_text]
			var col := Color(0.86, 0.9, 1.0)
			if is_ready:
				col = Color(0.55, 1.0, 0.6)
			if s == my_seat:
				col = Color(1.0, 0.86, 0.3) if not is_ready else Color(1.0, 0.95, 0.45)
			lb.add_theme_color_override("font_color", col)

	if ready_label != null:
		if phase == "waiting":
			ready_label.text = "  %d/4 家已准备" % ready_n
		elif phase == "draft":
			var mine := _my_picks().size()
			ready_label.text = "  本窗口已留 %d/5 张" % mine
		elif phase == "order":
			ready_label.text = "  %d/4 家已提交顺序" % ready_n
		else:
			ready_label.text = "  4/4 家已就绪"

	if title != null:
		var phase_cn := {"waiting": "等待准备", "draft": "传递选卡", "order": "调整顺序", "play": "即将开始"}
		title.text = "天马 · %s —— 本窗口 %s" % [
			String(phase_cn.get(phase, phase)), _seat_display_name(my_seat)]


func _refresh_ready_frame() -> void:
	if ready_frame == null:
		return
	ready_frame.visible = my_ready and phase != "play"
	if ready_frame.visible and start_btn != null:
		ready_frame.position = start_btn.global_position - Vector2(7, 7)
		ready_frame.size = start_btn.size * start_btn.scale + Vector2(14, 14)


func _refresh_cards() -> void:
	for no in card_buttons.keys():
		var b = card_buttons[no]
		if b != null:
			b.visible = false
	_clear(picked_row)
	if phase == "draft":
		_layout_hand(false)
		_layout_picked()
	elif phase == "order":
		_layout_order()


# 手里的牌：一行居中；animate_in = true 时从右侧滑进来
func _layout_hand(animate_in: bool) -> void:
	var hand := _my_hand()
	var n := hand.size()
	var keep := {}
	for h in hand:
		keep["Card%02d" % int(h)] = true
	for c in row.get_children():
		if not keep.has(c.name) and (c as CanvasItem).visible:
			c.visible = false
	if n == 0:
		_clear(row)
		_set_hint("等待其他玩家留牌…")
		return
	var cw := 512.0 * CARD_SCALE
	var ch := 746.0 * CARD_SCALE
	var spacing := cw * 0.96
	var row_w := spacing * (n - 1) + cw
	for i in range(n):
		_place_card(row, int(hand[i]), Vector2(i * spacing, 0), CARD_SCALE, int(hand[i]) == selected_no)
	row.position.y = ROW_CENTER_Y - ch * 0.5
	row_width = row_w
	var target_x := (SCREEN_W - row_w) * 0.5
	if animate_in:
		_slide_row_in(target_x)
	elif row_animating:
		pass                            # 滑入还没结束，别把 x 拉回终点
	else:
		row.position.x = target_x


func _show_waiting() -> void:
	_kill_row_tween()
	_clear(row)
	_layout_picked()
	_set_hint("等待其他玩家留牌…")


func _layout_picked() -> void:
	var mine := _my_picks()
	var pw := 512.0 * PICK_SCALE
	var ph := 746.0 * PICK_SCALE
	for i in range(mine.size()):
		_place_card(picked_row, int(mine[i]), Vector2(56 + i * (pw * 1.1), SCREEN_H - ph - 40), PICK_SCALE, false)


func _layout_order() -> void:
	var mine := _my_picks()
	var n := mine.size()
	if n == 0:
		return
	var cw := 512.0 * CARD_SCALE
	var ch := 746.0 * CARD_SCALE
	var spacing := cw * 0.96
	var row_w := spacing * (n - 1) + cw
	for i in range(n):
		var no := int(mine[i])
		_place_card(row, no, Vector2(i * spacing, 0), CARD_SCALE, order.has(no))
		_set_number(no, order.find(no) + 1 if order.has(no) else -1)
	row.position.y = ROW_CENTER_Y - ch * 0.5
	row.position.x = (SCREEN_W - row_w) * 0.5
	_kill_row_tween()


func _place_card(parent: Node2D, card_no: int, pos: Vector2, sc: float, sel: bool) -> void:
	var b = card_buttons.get(card_no, null)
	if b == null:
		return
	if b.get_parent() != parent:
		var p: Node = b.get_parent()
		if p != null:
			p.remove_child(b)
		parent.add_child(b)
	b.visible = true
	b.scale = Vector2(sc, sc)
	b.position = pos
	if b.has_method("set_selected"):
		b.call("set_selected", sel)


func _clear(node: Node2D) -> void:
	if node == null:
		return
	for c in node.get_children():
		c.visible = false
		if bank != null and c.get_parent() != bank:
			node.remove_child(c)
			bank.add_child(c)
			c.scale = Vector2.ONE
			c.position = Vector2.ZERO


func _set_number(card_no: int, n: int) -> void:
	var b = card_buttons.get(card_no, null)
	if b == null:
		return
	var lbl := b.get_node_or_null("NumLabel") as Label
	if n <= 0:
		if lbl != null:
			lbl.text = ""
			lbl.visible = false
		return
	if lbl == null:
		lbl = Label.new()
		lbl.name = "NumLabel"
		lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		lbl.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		lbl.add_theme_font_size_override("font_size", 110)
		lbl.add_theme_color_override("font_color", Color(1.0, 0.86, 0.1))
		lbl.add_theme_color_override("font_outline_color", Color(0.1, 0.05, 0.0))
		lbl.add_theme_constant_override("outline_size", 10)
		lbl.mouse_filter = Control.MOUSE_FILTER_IGNORE
		b.add_child(lbl)
	lbl.text = str(n)
	lbl.visible = true
	lbl.position = Vector2(b.size.x * 0.5 - 90, -140)
	lbl.size = Vector2(180, 130)


# ── 小工具 ─────────────────────────────────────────────────────────
func _seat_data(seat: int) -> Dictionary:
	var seats: Array = lobby.get("seats", [])
	if seat < 0 or seat >= seats.size() or typeof(seats[seat]) != TYPE_DICTIONARY:
		return {}
	return seats[seat]


func _my_hand() -> Array:
	var out: Array = []
	for v in (_seat_data(my_seat).get("hand", []) as Array):
		out.append(int(v))
	return out


func _my_picks() -> Array:
	var out: Array = []
	for v in (_seat_data(my_seat).get("picks", []) as Array):
		out.append(int(v))
	return out


func _am_pending() -> bool:
	var pending: Array = lobby.get("pending", [])
	if my_seat < 0 or my_seat >= pending.size():
		return false
	return bool(pending[my_seat])


func _hand_has(card_no: int) -> bool:
	for v in _my_hand():
		if int(v) == card_no:
			return true
	return false


func _seat_display_name(seat: int) -> String:
	if seat < 0 or my_seat < 0:
		return "?"
	var g := (seat - my_seat + 4) % 4
	return "%s（%d 号位）" % [SEAT_NAMES[g], seat]


func _set_hint(t: String) -> void:
	if hint != null:
		hint.text = t
