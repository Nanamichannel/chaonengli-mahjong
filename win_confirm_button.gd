extends Control

# 结算播报的「確認」按钮：直接用一直以来的那张确认图（元气脸），
# 不写任何文字 / 数字；点过之后外面套一圈细黄框。
signal confirmed

const TEX_PATH := "res://Cailiao/UI/queren.png"
const C_FRAME := Color(1.0, 0.855, 0.35, 1.0)   # 细黄框
const FRAME_W := 3.0

var disabled := false
var hovered := false
var pressed := false
var show_frame := false
var _tex: Texture2D = null


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_STOP
	mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	mouse_entered.connect(func(): hovered = true; queue_redraw())
	mouse_exited.connect(func(): hovered = false; pressed = false; queue_redraw())
	gui_input.connect(_on_input)
	_tex = load(TEX_PATH) as Texture2D


# 保住老接口：done = 已经点过（按钮压暗 + 套黄框）；人数提示不要了
func set_state(done: bool, _confirmed_count: int = 0, _total: int = 0) -> void:
	disabled = done
	show_frame = done
	mouse_default_cursor_shape = Control.CURSOR_ARROW if done else Control.CURSOR_POINTING_HAND
	queue_redraw()


func _on_input(ev: InputEvent) -> void:
	if disabled:
		return
	if ev is InputEventMouseButton and ev.button_index == MOUSE_BUTTON_LEFT:
		pressed = ev.pressed
		queue_redraw()
		if not ev.pressed:
			# 点下去立刻给反馈：压暗 + 黄框（服务器要是拒绝，set_state 会把状态纠正回来）
			disabled = true
			show_frame = true
			queue_redraw()
			confirmed.emit()
			accept_event()


func _draw() -> void:
	if _tex == null:
		return
	var r := Rect2(Vector2.ZERO, size)
	var col := Color(1, 1, 1, 1)
	if disabled:
		col = Color(0.72, 0.75, 0.75, 0.85)     # 点过了：压暗
	elif pressed:
		col = Color(0.88, 0.90, 0.90, 1.0)
	draw_texture_rect(_tex, r, false, col)
	if show_frame:
		draw_rect(Rect2(Vector2(FRAME_W, FRAME_W), size - Vector2(FRAME_W, FRAME_W) * 2.0),
			C_FRAME, false, FRAME_W)
