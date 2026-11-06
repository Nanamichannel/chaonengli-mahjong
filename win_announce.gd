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
var draw_banner := true                # false = 只画全屏蒙版（「谁铳了谁」横幅已删掉）
var banner_pos := Vector2(960.0, 200.0)   # 横幅中心（屏内坐标）
var banner_size := Vector2(820.0, 76.0)   # 横幅底座大小
var banner_scale := 1.0
var seats_offset := Vector2.ZERO          # 四个小面板整体偏移
var seats_scale := 1.0
var left_panel_offset := Vector2.ZERO    # 左边那个小面板单独偏移（调试可拖）
var right_panel_offset := Vector2.ZERO   # 右边那个小面板单独偏移（调试可拖）
var _font: Font = null
var center_y := 0.53            # 结算面板中心在屏高上的比例（越小越靠上；由和牌播报.gd 传进来）

# ── 分数面板动画（用户口径 2026-11-04）────────────────────────────────
#   ① 只有「原始分数」淡入（0.3s），位置不动
#   ② 0.3s 后「本次变化」从下方升到与原分等高（0.3s）+ 淡入；涨绿 / 跌红
#   ③ 停 0.5s
#   ④ 再按同样距离上移并淡出（0.3s，位移与 ② 对称）
#   ⑤ ④ 开始那一刻，原分计数器从 before 涨到 after（1000 点/秒）
#   ⑥ 涨完再停 0.5s → 发 seats_anim_done（外层据此出「確認」按钮）
signal seats_anim_done

const T_BASE := 0.3          # ① 原分淡入
const T_DELTA := 0.3         # ②④ 变化值上移（两段等距，方向相反）
const T_HOLD := 0.5          # ③ 中间休息
const T_TAIL := 0.5          # ⑥ 涨完再休息多久才出确认按钮
# ⑤ 计数器时长：按「这次变化多少点」动态给（点数越大给的时间越长，但对数增长 + 封顶）
#   时长 = COUNT_A + COUNT_B * log2(1 + |Δ| / COUNT_REF)，再夹在 [COUNT_MIN, COUNT_MAX]
#   实测：400→0.77s  1000→1.17s  4000→2.03s  8000→2.55s  12000→2.85s  32000→封顶
const COUNT_A := 0.30        # 基础时长（秒）
const COUNT_B := 0.30        # 点数每翻一倍，多给多久（用户 2026-11-04 从 0.55 调到 0.30）
const COUNT_REF := 500.0     # 参考点数
const COUNT_MIN := 0.30      # 再小的变化也至少给这么久（不然看不清在跳）
const COUNT_MAX := 3.20      # 封顶（役满 +48000 也只是 3.2 秒，不会拖太久）

var anim_delay := 0.0        # 面板整体淡入的时长：这段时间先不启动分数动画
var _anim_running := false
var _anim_finished := false
var _anim_elapsed := 0.0
var _anim_len := 0.0


func set_content(data: Dictionary) -> void:
	title = String(data.get("title", title))
	method = String(data.get("method", method))
	yaku_text = String(data.get("yaku", yaku_text))
	score_text = String(data.get("score", score_text))
	sub_text = String(data.get("sub", sub_text))
	is_draw = bool(data.get("is_draw", false))
	var _seats = data.get("seats", [])
	seats = _seats if typeof(_seats) == TYPE_ARRAY else []
	start_seats_anim()
	queue_redraw()


func _ready() -> void:
	set_process(false)


## 开始播一次分数动画（set_content 里调用；重播时从头走）
func start_seats_anim() -> void:
	_anim_elapsed = 0.0
	_anim_len = _anim_total()
	_anim_finished = false
	_anim_running = not seats.is_empty()
	set_process(_anim_running)
	queue_redraw()


func _count_dur(delta: int) -> float:
	"""计数器走完这一段要多久（秒）：按点数动态，对数增长 + 上下限。"""
	var d := absf(float(delta))
	var t := COUNT_A + COUNT_B * log(1.0 + d / COUNT_REF) / log(2.0)
	return clampf(t, COUNT_MIN, COUNT_MAX)


func _anim_total() -> float:
	var mx := 0.0
	for it in seats:
		if typeof(it) != TYPE_DICTIONARY:
			continue
		var d: Dictionary = it
		mx = maxf(mx, _count_dur(int(d.get("after", 0)) - int(d.get("before", 0))))
	return T_BASE + T_DELTA + T_HOLD + T_DELTA + mx + T_TAIL


func _process(dt: float) -> void:
	if not _anim_running:
		set_process(false)
		return
	_anim_elapsed += dt
	if _anim_elapsed - anim_delay >= _anim_len:
		_anim_running = false
		_anim_finished = true
		set_process(false)
		queue_redraw()
		seats_anim_done.emit()
		return
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

	if not draw_banner:
		return
	
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
# 四块小面板的矩形：屏幕最底下一行，从左往右 上家 / 我 / 対家 / 下家
func _seat_rects(w: float, h: float) -> Array:
	var sw := clampf(980.0 * seats_scale * 0.34, 220.0, 340.0)
	var sh := clampf(620.0 * seats_scale * 0.145, 60.0, 82.0)
	var gap := sw * 0.30
	# 右下角还压着「確認」按钮（300x92，margin 28），整行宽度压到 1240 以内，别被它盖住
	if 4.0 * sw + 3.0 * gap > 1240.0:
		sw = 1240.0 / 4.9
		gap = sw * 0.30
	var total := 4.0 * sw + 3.0 * gap
	var x0 := w * 0.5 - total * 0.5 + seats_offset.x
	var y0 := h - sh - 36.0 + seats_offset.y
	var out: Array = []
	for i in range(4):
		var r := Rect2(x0 + float(i) * (sw + gap), y0, sw, sh)
		if i == 0:
			r.position += left_panel_offset
		elif i == 3:
			r.position += right_panel_offset
		out.append(r)
	return out


func _draw_seat_scores(f: Font, _rect: Rect2, w: float, h: float) -> void:
	if seats.is_empty():
		return
	var rects := _seat_rects(w, h)
	# 时间轴：running → 按秒数走；播完/从没播 → 直接显示结算后分数（t = -1）
	var t := -1.0
	if _anim_running:
		t = maxf(_anim_elapsed - anim_delay, 0.0)
	for i in range(seats.size()):
		if i >= rects.size():
			continue
		var it = seats[i]
		if typeof(it) != TYPE_DICTIONARY:
			continue
		var d: Dictionary = it
		var r: Rect2 = rects[i]
		var sw := r.size.x
		var sh := r.size.y
		# 不许出屏幕边缘
		r.position.x = clampf(r.position.x, 10.0, maxf(10.0, w - sw - 10.0))
		r.position.y = clampf(r.position.y, 10.0, maxf(10.0, h - sh - 10.0))
		var b := int(d.get("before", 0))
		var a := int(d.get("after", 0))
		var delta := a - b
		var col := C_UP if delta > 0 else (C_DOWN if delta < 0 else C_WHITE)
		var nick := String(d.get("nick", ""))
		_text_black(f, r.get_center().x, r.position.y + sh * 0.14, nick,
			sh * 0.30, r.size.x * 0.86)

		var base_a := 1.0          # 原始分数的透明度
		var d_a := 0.0             # 变化值的透明度（动画播完 = 不显示，只剩最终分数）
		var d_off := 0.0           # 变化值相对基线的纵向偏移（正 = 下方）
		var shown := float(a)      # 原始分数现在的数值（计数器）
		if t >= 0.0:
			var dy := sh * 0.36                                  # 一行的高度
			var p_in := clampf((t - T_BASE) / T_DELTA, 0.0, 1.0)
			var c_start := T_BASE + T_DELTA + T_HOLD
			var p_out := clampf((t - c_start) / T_DELTA, 0.0, 1.0)
			base_a = clampf(t / T_BASE, 0.0, 1.0)                # ① 只有原分在淡入
			d_a = p_in * (1.0 - p_out)                           # ② 淡入 → ④ 淡出
			d_off = (1.0 - p_in) * dy - p_out * dy               # ②④ 等距、方向相反
			# ⑤ 第二段上移开始那一刻起，原分按 1000 点/秒涨到 after
			var span := _count_dur(delta)
			if span <= 0.0 or t >= c_start + span:
				shown = float(a)
			elif t > c_start:
				shown = float(b) + float(delta) * ((t - c_start) / span)
			else:
				shown = float(b)

		var s1 := str(int(round(shown)))
		var dtxt := ""
		if delta > 0:
			dtxt = "+%d" % delta
		elif delta < 0:
			dtxt = "%d" % delta
		var fs := int(maxf(10.0, sh * 0.34))
		var gap := 14.0
		# 原分居中、变化值挂右边：宽度预算按「原分半宽 + 间距 + 变化值」算
		while fs > 10 and (_sw(f, s1, fs) * 0.5 + gap + _sw(f, dtxt, fs)) > r.size.x * 0.46:
			fs -= 1
		var w1 := _sw(f, s1, fs)
		# ★ 原分永远在昵称正下方（同一个中心）；变化值挂在原分右边，
		#   不参与居中 —— 否则变化值一进场，原分就被推到左边（用户报的对不齐）。
		var tx := r.get_center().x - w1 * 0.5
		var ty := r.position.y + sh * 0.80
		draw_string(f, Vector2(tx, ty), s1, HORIZONTAL_ALIGNMENT_LEFT, -1, fs,
			Color(C_WHITE, base_a))
		if dtxt != "":
			# 字号和前面的分数完全一样；只有 +/- 符号单独小一号 ——
			# 字体里「+」的字形比数字显大，同号字会让整串看着比原分粗（用户报的）。
			var fs_sign := maxi(8, int(round(float(fs) * 0.82)))
			var sign_ch := dtxt.substr(0, 1)
			var num_txt := dtxt.substr(1)
			var x2 := tx + w1 + gap
			draw_string(f, Vector2(x2, ty + d_off + float(fs - fs_sign) * 0.34), sign_ch,
				HORIZONTAL_ALIGNMENT_LEFT, -1, fs_sign, Color(col, d_a))
			draw_string(f, Vector2(x2 + _sw(f, sign_ch, fs_sign) + 2.0, ty + d_off), num_txt,
				HORIZONTAL_ALIGNMENT_LEFT, -1, fs, Color(col, d_a))



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
