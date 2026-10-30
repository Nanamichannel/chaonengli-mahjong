extends Control

signal confirmed

const C_GOLD := Color(1.0, 0.831, 0.478, 1.0)
const C_MINT := Color(0.443, 0.871, 0.796, 1.0)
const C_JADE := Color(0.063, 0.157, 0.169, 0.98)
const C_EDGE := Color(0.784, 0.941, 0.914, 1.0)
const C_WHITE := Color(0.965, 0.996, 0.988, 1.0)

var text := "確　認"
var progress := "0 / 4"
var disabled := false
var hovered := false
var pressed := false
var _font: Font = null


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_STOP
	mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	mouse_entered.connect(func(): hovered = true; queue_redraw())
	mouse_exited.connect(func(): hovered = false; pressed = false; queue_redraw())
	gui_input.connect(_on_input)


func set_state(done: bool, confirmed_count: int, total: int) -> void:
	disabled = done
	text = "已　確　認" if done else "確　認"
	progress = "%d / %d" % [confirmed_count, total]
	mouse_default_cursor_shape = Control.CURSOR_ARROW if done else Control.CURSOR_POINTING_HAND
	queue_redraw()


func _on_input(ev: InputEvent) -> void:
	if disabled:
		return
	if ev is InputEventMouseButton and ev.button_index == MOUSE_BUTTON_LEFT:
		pressed = ev.pressed
		queue_redraw()
		if not ev.pressed:
			confirmed.emit()
			accept_event()


func _f() -> Font:
	if _font == null:
		_font = get_theme_default_font()
		if _font == null:
			_font = ThemeDB.fallback_font
	return _font


func _draw() -> void:
	var r := Rect2(Vector2.ZERO, size)
	var col := C_JADE.lightened(0.08 if hovered and not disabled else 0.0)
	if pressed:
		col = col.darkened(0.08)
	if disabled:
		col = Color(0.086, 0.180, 0.192, 0.90)
	var cut := size.y * 0.34
	var pts := PackedVector2Array([
		Vector2(cut, 0), Vector2(size.x - cut, 0), Vector2(size.x, size.y * 0.5),
		Vector2(size.x - cut, size.y), Vector2(cut, size.y), Vector2(0, size.y * 0.5)])
	draw_colored_polygon(pts, col)
	pts.append(pts[0])
	draw_polyline(pts, C_MINT if disabled else C_EDGE, 3.0, true)
	var f := _f()
	draw_string(f, Vector2(0, size.y * 0.45), text, HORIZONTAL_ALIGNMENT_CENTER,
		size.x, int(size.y * 0.34), C_MINT if disabled else C_GOLD)
	draw_string(f, Vector2(0, size.y * 0.82), progress, HORIZONTAL_ALIGNMENT_CENTER,
		size.x, int(size.y * 0.18), C_WHITE)
