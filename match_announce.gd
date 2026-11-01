extends Control

# ─────────────────────────────────────────────────────────────────────────────
# 半庄终局播报：和「和牌播报」(win_announce.gd) 同一套青玉金视觉。
#   标题「半庄终了」+ 四行名次（1/2/3/4，分数从高到低）+ 底部「确认」。
#   四家都确认后由调用方负责回大厅。
# 数据全部来自服务端：{"rank": [{seat, score, rank}, ...], "my_seat": 0,
#                       "confirmed": [1], "humans": [0, 1]}
# ─────────────────────────────────────────────────────────────────────────────

signal confirmed

const C_INK := Color(0.043, 0.106, 0.114, 0.97)
const C_JADE := Color(0.106, 0.259, 0.271, 0.98)
const C_MINT := Color(0.443, 0.871, 0.796, 1.0)
const C_EDGE := Color(0.784, 0.941, 0.914, 1.0)
const C_GOLD := Color(1.0, 0.831, 0.478, 1.0)
const C_WHITE := Color(0.965, 0.996, 0.988, 1.0)
const C_MUTED := Color(0.749, 0.898, 0.875, 1.0)

var rank_rows: Array = []          # [{seat, score, rank}]
var my_seat := 0
var confirmed_seats: Array = []
var humans: Array = []
var busy := false                  # 已经点过确认，等别人
var all_done := false

var _btn: Button = null
var _font: Font = null


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_STOP
	_btn = Button.new()
	_btn.name = "Confirm"
	_btn.text = "确认"
	_btn.focus_mode = Control.FOCUS_NONE
	_btn.add_theme_font_size_override("font_size", 28)
	_btn.add_theme_color_override("font_color", Color(0.05, 0.10, 0.12))
	_btn.pressed.connect(_on_btn)
	add_child(_btn)
	_layout_btn()


func _notification(what: int) -> void:
	if what == NOTIFICATION_RESIZED:
		_layout_btn()
		queue_redraw()


func _layout_btn() -> void:
	if _btn == null:
		return
	var vp := size
	if vp.x < 100.0:
		vp = get_viewport_rect().size
	var bw := clampf(vp.x * 0.20, 220.0, 360.0)
	var bh := bw * 0.30
	_btn.size = Vector2(bw, bh)
	_btn.position = Vector2((vp.x - bw) * 0.5, vp.y * 0.5 + vp.y * 0.235)
	_btn.visible = not all_done


func set_content(data: Dictionary) -> void:
	rank_rows = data.get("rank", []) if typeof(data.get("rank")) == TYPE_ARRAY else []
	my_seat = int(data.get("my_seat", 0))
	confirmed_seats = data.get("confirmed", []) if typeof(data.get("confirmed")) == TYPE_ARRAY else []
	humans = data.get("humans", []) if typeof(data.get("humans")) == TYPE_ARRAY else []
	busy = false
	all_done = false
	if _btn != null:
		_btn.text = "确认"
		_btn.disabled = false
	_layout_btn()
	queue_redraw()


func set_state(confirmed_now: Array, done: bool, wait_text := "") -> void:
	confirmed_seats = confirmed_now
	all_done = done
	busy = true
	if _btn != null:
		if done:
			_btn.visible = false
		else:
			_btn.visible = true
			_btn.disabled = true
			_btn.text = wait_text if wait_text != "" else "等待其他家…"
	queue_redraw()


func _on_btn() -> void:
	if busy or all_done:
		return
	busy = true
	if _btn != null:
		_btn.disabled = true
		_btn.text = "等待其他家…"
	confirmed.emit()


func _f() -> Font:
	if _font == null:
		_font = get_theme_default_font()
		if _font == null:
			_font = ThemeDB.fallback_font
	return _font


func _draw() -> void:
	var w := size.x
	var h := size.y
	if w < 100.0 or h < 100.0:
		return
	var f := _f()
	draw_rect(Rect2(Vector2.ZERO, size), Color(0.016, 0.063, 0.067, 0.80))
	var c := Vector2(w * 0.5, h * 0.48)
	for i in range(14):
		var t := float(i) / 14.0
		draw_circle(c, minf(w, h) * (0.44 - t * 0.26), Color(0.30, 0.72, 0.66, 0.016))

	var pw := minf(w * 0.56, 820.0)
	var ph := minf(h * 0.68, 660.0)
	var rect := Rect2(c - Vector2(pw, ph) * 0.5, Vector2(pw, ph))
	_panel(rect, 42.0, C_INK, C_EDGE, 5.0)
	_panel(rect.grow(-14.0), 33.0, C_JADE, Color(0.380, 0.682, 0.651, 0.95), 2.0)

	# 顶部牌子 + 标题
	var band := Rect2(rect.position + Vector2(pw * 0.22, ph * 0.045),
		Vector2(pw * 0.56, ph * 0.10))
	_plate(band)
	_text(f, c.x, rect.position.y + ph * 0.105, "半庄终了", ph * 0.068, C_GOLD, pw * 0.50)

	# 四行名次
	var rows := rank_rows
	if rows.is_empty():
		_text(f, c.x, rect.position.y + ph * 0.40, "（没有终局数据）", ph * 0.06, C_MUTED, pw * 0.8)
	else:
		var y0 := rect.position.y + ph * 0.20
		var rh := ph * 0.135
		for i in range(rows.size()):
			if i >= 4:
				break
			var r: Dictionary = rows[i]
			var seat := int(r.get("seat", -1))
			var score := int(r.get("score", 0))
			var rk := int(r.get("rank", i + 1))
			var mine := (seat == my_seat)
			var row_rect := Rect2(rect.position.x + pw * 0.09, y0 + rh * i,
				pw * 0.82, rh * 0.86)
			draw_rect(row_rect, Color(0.443, 0.871, 0.796, 0.10 if mine else 0.045))
			if mine:
				draw_rect(row_rect, C_MINT, false, 2.0)

			var cy := y0 + rh * i + rh * 0.43
			# 名次
			var rk_col: Color = [C_GOLD, C_WHITE, C_MUTED, C_MUTED][clampi(rk - 1, 0, 3)]
			_text_at(f, row_rect.position.x + pw * 0.06, cy, "%d位" % rk,
				rh * 0.52, rk_col)
			# 座位
			var name := "%d 号位" % seat
			if mine:
				name += "（我）"
			_text_at(f, row_rect.position.x + pw * 0.20, cy, name, rh * 0.46,
				C_MINT if mine else C_WHITE)
			# 分数
			_text_right(f, row_rect.end.x - pw * 0.05, cy, "%d" % score,
				rh * 0.52, C_GOLD if not mine else C_WHITE)

			# 已确认打勾
			if confirmed_seats.has(seat) or confirmed_seats.has(float(seat)):
				_text_right(f, row_rect.end.x - pw * 0.22, cy, "✓", rh * 0.46, C_MINT)

	# 四角铆钉
	for sx in [-1.0, 1.0]:
		for sy in [-1.0, 1.0]:
			var p := c + Vector2(sx * pw * 0.43, sy * ph * 0.40)
			draw_circle(p, 5.0, C_GOLD)
			draw_circle(p, 2.0, Color(1, 0.95, 0.72))


func _panel(r: Rect2, cut: float, fill: Color, edge: Color, ew: float) -> void:
	var p := PackedVector2Array([
		r.position + Vector2(cut, 0), r.position + Vector2(r.size.x - cut, 0),
		r.position + Vector2(r.size.x, cut), r.end - Vector2(0, cut),
		r.end - Vector2(cut, 0), r.position + Vector2(cut, r.size.y),
		r.position + Vector2(0, r.size.y - cut), r.position + Vector2(0, cut)])
	draw_colored_polygon(p, fill)
	p.append(p[0])
	draw_polyline(p, edge, ew, true)


func _plate(r: Rect2) -> void:
	var cut := r.size.y * 0.46
	var p := PackedVector2Array([
		Vector2(r.position.x, r.get_center().y), r.position + Vector2(cut, 0),
		Vector2(r.end.x - cut, r.position.y), Vector2(r.end.x, r.get_center().y),
		Vector2(r.end.x - cut, r.end.y), Vector2(r.position.x + cut, r.end.y)])
	draw_colored_polygon(p, Color(0.059, 0.169, 0.180, 1.0))
	p.append(p[0])
	draw_polyline(p, C_EDGE, 3.0, true)


func _text(f: Font, cx: float, y: float, txt: String, fs: float, col: Color, width: float) -> void:
	if txt == "":
		return
	var sz := maxi(10, int(fs))
	while sz > 10 and f.get_string_size(txt, HORIZONTAL_ALIGNMENT_LEFT, -1, sz).x > width:
		sz -= 1
	draw_string(f, Vector2(cx - width * 0.5, y + float(sz) * 0.36), txt,
		HORIZONTAL_ALIGNMENT_CENTER, width, sz, col)


func _text_at(f: Font, x: float, cy: float, txt: String, fs: float, col: Color) -> void:
	var sz := maxi(10, int(fs))
	draw_string(f, Vector2(x, cy + float(sz) * 0.36), txt,
		HORIZONTAL_ALIGNMENT_LEFT, -1, sz, col)


func _text_right(f: Font, x_right: float, cy: float, txt: String, fs: float, col: Color) -> void:
	var sz := maxi(10, int(fs))
	var tw := f.get_string_size(txt, HORIZONTAL_ALIGNMENT_LEFT, -1, sz).x
	draw_string(f, Vector2(x_right - tw, cy + float(sz) * 0.36), txt,
		HORIZONTAL_ALIGNMENT_LEFT, -1, sz, col)
