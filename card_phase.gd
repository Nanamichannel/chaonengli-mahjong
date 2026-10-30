extends CanvasLayer

# ── node_2d 开局的「5 张角色卡编号」阶段 ──────────────────────────
# 抽卡链已在初始菜单完成（本地玩家 5 张，其余 3 位电脑随机）。
# 这里把抽到的 5 张卡带进画面，点击编号：
#   1-4 = 主战卡，5 = 协战卡
#   再点已编号的卡 = 取消，后面的编号自动往前补
#   点场景里自带的「开始按钮」= 记录最终编号并进入游戏

const CARD_COUNT := 46
const CARD_SCALE := 0.76
const SPACING_RATIO := 0.96
const ROW_CENTER_Y := 537.0
const SCREEN_W := 1920.0
const ENTER_MAX_SPEED := 2600.0
const ENTER_ACCEL := 4200.0
const EDGE_MARGIN := 220.0

const PICK_PATH := "user://player_cards.json"
const ORDER_PATH := "user://player_order.json"
const ORDERS_PATH := "user://player_orders.json"
const ORDER_COUNT := 5

var ui: Control
var row: Node2D
var bank: Node2D
var start_btn: BaseButton
var card_buttons := {}
var cards: Array = []
var order: Array = []
var finished := false

var moving := false
var move_target_x := 0.0
var move_vel := 0.0
var move_max_speed := 0.0
var move_accel := 0.0

func _ready() -> void:
	# 选卡和调序已经在初始菜单（服务端大厅）里做完 → 这里直接不出现。
	var cs := get_node_or_null("/root/ClientState")
	if cs != null and typeof(cs.orders) == TYPE_ARRAY and (cs.orders as Array).size() == 4:
		visible = false
		set_process(false)
		return
	layer = 20
	_build_ui()
	# 使用场景里自带的「开始按钮」节点（不自己新建）
	var sb := get_node_or_null("开始按钮") as BaseButton
	if sb != null:
		sb.reparent(ui, true)
		start_btn = sb
		if not start_btn.pressed.is_connected(_on_start_pressed):
			start_btn.pressed.connect(_on_start_pressed)
	cards = _load_cards()
	_show_cards()

func _build_ui() -> void:
	ui = Control.new()
	ui.name = "UI"
	ui.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(ui)

	var dim := ColorRect.new()
	dim.name = "Dim"
	dim.color = Color(0.02, 0.03, 0.06, 0.72)
	dim.set_anchors_preset(Control.PRESET_FULL_RECT)
	dim.mouse_filter = Control.MOUSE_FILTER_STOP
	ui.add_child(dim)

	row = Node2D.new()
	row.name = "Row"
	ui.add_child(row)

	bank = Node2D.new()
	bank.name = "CardBank"
	bank.visible = false
	ui.add_child(bank)
	for i in range(1, CARD_COUNT + 1):
		var b := TextureButton.new()
		b.name = "Card%02d" % i
		var tex = load("res://Cailiao/skill/cards/card_%02d.png" % i)
		b.texture_normal = tex
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		if tex != null:
			b.size = tex.get_size()
			b.custom_minimum_size = tex.get_size()
		b.visible = false
		b.set_script(load("res://card_button.gd"))
		b.set("card_no", i)
		bank.add_child(b)
		card_buttons[i] = b
		b.card_clicked.connect(_on_card_clicked)

func _load_cards() -> Array:
	var arr: Array = []
	if FileAccess.file_exists(PICK_PATH):
		var rf := FileAccess.open(PICK_PATH, FileAccess.READ)
		if rf != null:
			var data = JSON.parse_string(rf.get_as_text())
			if typeof(data) == TYPE_ARRAY:
				arr = data
	var out: Array = []
	for v in arr:
		var n := int(v)
		if n >= 1 and n <= CARD_COUNT and not out.has(n):
			out.append(n)
	if out.size() > ORDER_COUNT:
		out = out.slice(out.size() - ORDER_COUNT)
	while out.size() < ORDER_COUNT:
		var n := randi_range(1, CARD_COUNT)
		if not out.has(n):
			out.append(n)
	return out

func _show_cards() -> void:
	for c in row.get_children():
		row.remove_child(c)
		bank.add_child(c)
		c.visible = false
		c.scale = Vector2.ONE
		c.position = Vector2.ZERO
	var n := cards.size()
	var cw := 512.0 * CARD_SCALE
	var ch := 746.0 * CARD_SCALE
	var spacing := cw * SPACING_RATIO
	var row_w := spacing * (n - 1) + cw
	for i in range(n):
		var no: int = cards[i]
		var b = card_buttons.get(no, null)
		if b == null:
			continue
		bank.remove_child(b)
		row.add_child(b)
		b.visible = true
		b.scale = Vector2(CARD_SCALE, CARD_SCALE)
		b.set_selected(false)
		b.position = Vector2(i * spacing, 0)
		_update_number_label(no, -1)
	row.position.y = ROW_CENTER_Y - ch * 0.5
	row.position.x = SCREEN_W + EDGE_MARGIN
	_start_move((SCREEN_W - row_w) * 0.5, ENTER_MAX_SPEED, ENTER_ACCEL)

func _on_card_clicked(card_no: int) -> void:
	if finished:
		return
	var idx := order.find(card_no)
	if idx >= 0:
		order.remove_at(idx)
	elif order.size() < ORDER_COUNT:
		order.append(card_no)
	_refresh_numbers()

func _refresh_numbers() -> void:
	for no in card_buttons.keys():
		var b = card_buttons[no]
		var pos := order.find(no)
		if b.visible:
			b.set_selected(pos >= 0)
		_update_number_label(no, pos + 1 if pos >= 0 else -1)

func _update_number_label(card_no: int, n: int) -> void:
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
		lbl.add_theme_font_size_override("font_size", 72)
		lbl.add_theme_color_override("font_color", Color(1.0, 0.86, 0.1))
		lbl.add_theme_color_override("font_outline_color", Color(0.1, 0.05, 0.0))
		lbl.add_theme_constant_override("outline_size", 8)
		lbl.mouse_filter = Control.MOUSE_FILTER_IGNORE
		b.add_child(lbl)
	lbl.text = str(n)
	lbl.visible = true
	lbl.position = Vector2(b.size.x * 0.5 - 60, -96)
	lbl.size = Vector2(120, 96)

func _on_start_pressed() -> void:
	if finished:
		return
	if order.size() < ORDER_COUNT:
		return
	finished = true
	_save_order()
	# 编号确认后立刻刷新桌面上的主战/协战卡
	var root := get_parent()
	var idn := root.get_node_or_null("Main/Identity") if root != null else null
	if idn != null and idn.has_method("reload_orders"):
		idn.call("reload_orders")
	var tw := create_tween()
	tw.tween_property(ui, "modulate:a", 0.0, 0.35)
	tw.tween_callback(_hide_phase)

func _hide_phase() -> void:
	visible = false

func _save_order() -> void:
	var wf := FileAccess.open(ORDER_PATH, FileAccess.WRITE)
	if wf != null:
		wf.store_string(JSON.stringify(order))
	# 四家共用的记录：本家（0 号位）用刚刚确认的最终编号；
	# 其余三家沿用初始菜单里记录下来的选卡顺序。
	var all: Array = []
	if FileAccess.file_exists(ORDERS_PATH):
		var rf := FileAccess.open(ORDERS_PATH, FileAccess.READ)
		if rf != null:
			var data = JSON.parse_string(rf.get_as_text())
			if typeof(data) == TYPE_ARRAY:
				all = data
	while all.size() < 4:
		all.append([])
	all[0] = order.duplicate()
	var wf2 := FileAccess.open(ORDERS_PATH, FileAccess.WRITE)
	if wf2 != null:
		wf2.store_string(JSON.stringify(all))

# ── 与菜单相同的「匀加速 → 匀速 → 匀减速」平移 ──
func _start_move(target_x: float, max_speed: float, accel: float) -> void:
	move_target_x = target_x
	move_max_speed = maxf(max_speed, 1.0)
	move_accel = maxf(accel, 1.0)
	move_vel = 0.0
	moving = true

func _process(delta: float) -> void:
	if not moving or row == null:
		return
	var x: float = row.position.x
	var dx: float = move_target_x - x
	var dir: float = signf(dx)
	var stop_dist: float = (move_vel * move_vel) / (2.0 * move_accel)
	if absf(dx) <= stop_dist or absf(dx) < 1.0:
		move_vel = move_toward(move_vel, 0.0, move_accel * delta)
	else:
		move_vel = move_toward(move_vel, move_max_speed * dir, move_accel * delta)
	x += move_vel * delta
	if (dir > 0.0 and x > move_target_x) or (dir < 0.0 and x < move_target_x):
		x = move_target_x
		move_vel = 0.0
	row.position.x = x
	if absf(move_target_x - x) <= 0.5 and absf(move_vel) <= 1.0:
		row.position.x = move_target_x
		moving = false
