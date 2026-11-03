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
const C_UP := Color(0.494, 1.0, 0.639, 1.0)      # 分数涨：绿
const C_DOWN := Color(1.0, 0.427, 0.427, 1.0)    # 分数跌：红

var title := "和了"
var method := "自摸"
var yaku_text := ""
var score_text := ""
var sub_text := ""
var is_draw := false
var seats: Array = []          # 四个方位的分数小面板数据
var draw_mode := "head"                # "head" = 蒙版+横幅 / "seats" = 四个小分数面板
var banner_pos := Vector2(960.0, 200.0)   # 横幅中心（屏内坐标）
var banner_size := Vector2(820.0, 76.0)   # 横幅底座大小
var banner_scale := 1.0
var seats_offset := Vector2.ZERO          # 四个小面板整体偏移
var seats_scale := 1.0
var left_panel_offset := Vector2.ZERO    # 左边那个小面板单独偏移（调试可拖）
var right_panel_offset := Vector2.ZERO   # 右边那个小面板单独偏移（调试可拖）
var _font: Font = null
var center_y := 0.53            # 结算面板中心在屏高上的比例（越小越靠上；由和牌播报.gd 传进来）


func set_content(data: Dictionary) -> void:
	title = String(data.get("title", title))
	method = String(data.get("method", method))
	yaku_text = String(data.get("yaku", yaku_text))
	score_text = String(data.get("score", score_text))
	sub_text = String(data.get("sub", sub_text))
	is_draw = bool(data.get("is_draw", false))
	var _seats = data.get("seats", [])
	seats = _seats if typeof(_seats) == TYPE_ARRAY else []
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
	
	# ── 四个分数小面板（单独一层，后面才淡入）──
	if draw_mode == "seats":
		var rect := Rect2(Vector2.ZERO, Vector2(980.0, 620.0) * seats_scale)
		rect.position = Vector2(w * 0.5, h * clampf(center_y, 0.15, 0.92)) - rect.size * 0.5 + seats_offset
		_draw_seat_scores(f, rect, w, h)
		return
	
	# ── 全屏蒙版（和牌后压暗桌面，就是「现在的蒙版」）──
	draw_rect(Rect2(Vector2.ZERO, size), Color(0.016, 0.063, 0.067, 0.74))
	
	# ── 「谁铳了谁」横幅：六边形底座 + 两端小花 + 文案 ──
	var bs := banner_size * clampf(banner_scale, 0.2, 3.0)
	var bc := banner_pos
	var brect := Rect2(bc - bs * 0.5, bs)
	_plate(brect)
	_flower(Vector2(brect.position.x + bs.y * 0.62, bc.y), bs.y * 0.19)
	_flower(Vector2(brect.end.x - bs.y * 0.62, bc.y), bs.y * 0.19)
	var fs := bs.y * 0.44
	_text(f, bc.x, bc.y - fs * 0.5, method, fs, C_GOLD, bs.x * 0.70)


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



# ── 四个方位的分数小面板 ────────────────────────────────────────────
#   seats = [{pos:"bottom"/"right"/"top"/"left", nick:"昵称",
#             before:35000, after:43000}, ...]
#   第一行昵称；第二行「原分 → 结算后分」，涨 = 箭头+新分绿色，跌 = 红色。
func _draw_seat_scores(f: Font, rect: Rect2, w: float, h: float) -> void:
	if seats.is_empty():
		return
	var sw := clampf(rect.size.x * 0.34, 220.0, 340.0)
	var sh := clampf(rect.size.y * 0.145, 60.0, 82.0)
	var gap := 16.0
	var c := rect.get_center()
	for it in seats:
		if typeof(it) != TYPE_DICTIONARY:
			continue
		var d: Dictionary = it
		var pos := String(d.get("pos", ""))
		var r := Rect2()
		match pos:
			"top":
				r = Rect2(c.x - sw * 0.5, rect.position.y - gap - sh, sw, sh)
			"bottom":
				r = Rect2(c.x - sw * 0.5, rect.end.y + gap, sw, sh)
			"left":
				r = Rect2(rect.position.x - gap - sw, c.y - sh * 0.5, sw, sh)
			"right":
				r = Rect2(rect.end.x + gap, c.y - sh * 0.5, sw, sh)
			_:
				continue
		# 别被屏幕边缘切掉
		if pos == "left":
			r.position += left_panel_offset
		elif pos == "right":
			r.position += right_panel_offset
		r.position.x = clampf(r.position.x, 10.0, maxf(10.0, w - sw - 10.0))
		r.position.y = clampf(r.position.y, 10.0, maxf(10.0, h - sh - 10.0))
		var b := int(d.get("before", 0))
		var a := int(d.get("after", 0))
		var col := C_UP if a > b else (C_DOWN if a < b else C_WHITE)
		var nick := String(d.get("nick", ""))
		_text_black(f, r.get_center().x, r.position.y + sh * 0.14, nick,
			sh * 0.30, r.size.x * 0.86)
		# 第二行：原分（白）→ 箭头（涨绿/跌红）→ 新分（同色）
		var s1 := str(b)
		var s2 := "→"
		var s3 := str(a)
		var fs := int(maxf(10.0, sh * 0.34))
		while fs > 10 and _sw(f, s1, fs) + _sw(f, s2, fs) + _sw(f, s3, fs) + 16.0 > r.size.x * 0.86:
			fs -= 1
		var pad := 8.0
		var tx := r.get_center().x - (_sw(f, s1, fs) + _sw(f, s2, fs) + _sw(f, s3, fs) + pad * 2.0) * 0.5
		var ty := r.position.y + sh * 0.80
		draw_string(f, Vector2(tx, ty), s1, HORIZONTAL_ALIGNMENT_LEFT, -1, fs, C_WHITE)
		tx += _sw(f, s1, fs) + pad
		draw_string(f, Vector2(tx, ty), s2, HORIZONTAL_ALIGNMENT_LEFT, -1, fs, col)
		tx += _sw(f, s2, fs) + pad
		draw_string(f, Vector2(tx, ty), s3, HORIZONTAL_ALIGNMENT_LEFT, -1, fs, col)


func _sw(f: Font, txt: String, fs: int) -> float:
	return f.get_string_size(txt, HORIZONTAL_ALIGNMENT_LEFT, -1, fs).x



# ID 用黑色字；不垫底板，所以补一圈淡描边，深色背景上也看得见
func _text_black(f: Font, cx: float, y: float, txt: String, fs: float, width: float) -> void:
	if txt == "":
		return
	var sz := maxi(10, int(fs))
	var guard := 0
	while sz > 10 and guard < 40:
		if f.get_string_size(txt, HORIZONTAL_ALIGNMENT_LEFT, -1, sz).x <= width:
			break
		sz -= 1
		guard += 1
	var p := Vector2(cx - width * 0.5, y + float(sz) * 0.36)
	draw_string_outline(f, p, txt, HORIZONTAL_ALIGNMENT_CENTER, width, sz, 6,
		Color(0.965, 1.0, 0.988, 1.0))
	draw_string(f, p, txt, HORIZONTAL_ALIGNMENT_CENTER, width, sz, Color(0.02, 0.05, 0.05, 1.0))
