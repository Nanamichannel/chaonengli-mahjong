extends Control

# ─────────────────────────────────────────────────────────────────────────────
# 胡牌 / 流局播报：和新风盘同一套青玉金视觉
# 数据完全来自服务端结算结果，客户端只排版，不参与算分。
# ─────────────────────────────────────────────────────────────────────────────

const C_INK := Color(0.043, 0.106, 0.114, 0.97)    # 最外层：墨青
const C_JADE := Color(0.106, 0.259, 0.271, 0.98)  # 卡面：深青玉
const C_MINT := Color(0.443, 0.871, 0.796, 1.0)   # 主强调：青绿（薄荷）
const C_EDGE := Color(0.784, 0.941, 0.914, 1.0)   # 描边浅青
const C_GOLD := Color(1.0, 0.831, 0.478, 1.0)     # 点缀金（偏暖，压青玉不刺眼）
const C_WHITE := Color(0.965, 0.996, 0.988, 1.0)
const C_MUTED := Color(0.749, 0.898, 0.875, 1.0)  # 次要文字：浅青

var title := "和了"
var method := "自摸"
var yaku_text := ""
var score_text := ""
var sub_text := ""
var is_draw := false
var _font: Font = null


func set_content(data: Dictionary) -> void:
	title = String(data.get("title", title))
	method = String(data.get("method", method))
	yaku_text = String(data.get("yaku", yaku_text))
	score_text = String(data.get("score", score_text))
	sub_text = String(data.get("sub", sub_text))
	is_draw = bool(data.get("is_draw", false))
	queue_redraw()


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
	# 全屏墨青遮罩 + 中心柔光
	draw_rect(Rect2(Vector2.ZERO, size), Color(0.016, 0.063, 0.067, 0.74))
	var c := Vector2(w * 0.5, h * 0.49)
	for i in range(14):
		var t := float(i) / 14.0
		draw_circle(c, minf(w, h) * (0.42 - t * 0.25), Color(0.30, 0.72, 0.66, 0.016))

	# 中央切角卡
	var pw := minf(w * 0.68, 980.0)
	var ph := minf(h * 0.62, 620.0)
	var rect := Rect2(c - Vector2(pw, ph) * 0.5, Vector2(pw, ph))
	_panel(rect, 42.0, C_INK, C_EDGE, 5.0)
	_panel(rect.grow(-14.0), 33.0, C_JADE, Color(0.380, 0.682, 0.651, 0.95), 2.0)

	# 顶部金色条 + 两端青花
	var band := Rect2(rect.position + Vector2(pw * 0.14, ph * 0.07), Vector2(pw * 0.72, ph * 0.12))
	_plate(band)
	_flower(Vector2(band.position.x + band.size.y * 0.62, band.get_center().y), band.size.y * 0.19)
	_flower(Vector2(band.end.x - band.size.y * 0.62, band.get_center().y), band.size.y * 0.19)

	# 小标签：TSUMO/RON/DRAW（中文为主）
	var method_col := C_MUTED if is_draw else C_GOLD
	_text(f, c.x, rect.position.y + ph * 0.13, method, ph * 0.062, method_col, pw * 0.76)

	# 主标题：和 了 / 流 局
	var title_fs := ph * 0.176
	_text(f, c.x, rect.position.y + ph * 0.305, title, title_fs, C_WHITE, pw * 0.72)
	# 主标题金青双下划线
	draw_line(Vector2(c.x - pw * 0.25, rect.position.y + ph * 0.445),
		Vector2(c.x + pw * 0.25, rect.position.y + ph * 0.445), C_GOLD, 4.0, true)
	draw_line(Vector2(c.x - pw * 0.18, rect.position.y + ph * 0.462),
		Vector2(c.x + pw * 0.18, rect.position.y + ph * 0.462), C_MINT, 2.0, true)

	# 役种（过长自动缩小）
	var yf := ph * 0.064
	if yaku_text.length() > 22:
		yf *= 0.80
	if yaku_text.length() > 38:
		yf *= 0.78
	_text(f, c.x, rect.position.y + ph * 0.595, yaku_text, yf, C_MUTED, pw * 0.82)

	# 点数大字；流局时显示说明
	var sf := ph * (0.13 if not is_draw else 0.085)
	_text(f, c.x, rect.position.y + ph * 0.730, score_text, sf,
		C_GOLD if not is_draw else C_WHITE, pw * 0.78)

	# 番符 / 听牌等副信息
	_text(f, c.x, rect.position.y + ph * 0.875, sub_text, ph * 0.050, C_MUTED, pw * 0.80)

	# 四角装饰铆钉
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
	# 自动缩字：役种/流局原因再长也不会被宽度裁掉
	var size := maxi(10, int(fs))
	var guard := 0
	while size > 10 and guard < 40:
		var measured: float = f.get_string_size(txt, HORIZONTAL_ALIGNMENT_LEFT, -1, size).x
		if measured <= width:
			break
		size -= 1
		guard += 1
	draw_string(f, Vector2(cx - width * 0.5, y + float(size) * 0.36), txt,
		HORIZONTAL_ALIGNMENT_CENTER, width, size, col)


func _flower(c: Vector2, r: float) -> void:
	for i in range(5):
		var a := TAU * float(i) / 5.0 - PI * 0.5
		draw_circle(c + Vector2(cos(a), sin(a)) * r, r * 0.60, Color(0.443, 0.839, 0.769))
	draw_circle(c, r * 0.28, Color(0.902, 0.988, 0.965))
