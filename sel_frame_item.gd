extends Node2D
# ─────────────────────────────────────────────────────────────────────────────
# 彩虹描边选中框（自绘，不依赖任何贴图）。由 sel_frame.gd 的 attach() 创建，别直接 new。
#
# 动画：选中（visible=true）时，一条彩色线条沿边框跑一圈（DRAW_TIME 秒），
#       跑完变成整圈彩虹常亮，并做很轻的呼吸（不再逐帧重绘，省性能）。
#
# 想调外观改这里：
#   line_width / corner_radius / inset / offset / breath
# 想调全局默认值：见 sel_frame.gd 顶部的常量。
# ─────────────────────────────────────────────────────────────────────────────

const DRAW_TIME := 0.40          # 勾边一圈用时（秒）；0 附近会变成瞬间亮起
const STEP := 7.0                # 边框采样间距（像素）：越小越顺滑，越大越省
const HUE_SPAN := 1.0            # 一圈跨多少色相（1.0 = 完整彩虹）
const SAT := 0.72                # 饱和度（0.6 左右比较「霓虹」不刺眼）
const VAL := 1.0
const BREATH_MIN := 0.84         # 常亮时呼吸到的最低不透明度

var frame_size := Vector2(120.0, 160.0)
var line_width := 3.0
var corner_radius := 9.0
var inset := 0.0                 # 正数 = 边线往里缩（像素）
var offset := Vector2.ZERO       # 整体偏移（像素，正数 = 右/下）
var breath := true

var _prog := 0.0
var _pts := PackedVector2Array()
var _cols := PackedColorArray()
var _dirty := true
var _tw: Tween = null


func _ready() -> void:
	visibility_changed.connect(_on_visibility_changed)
	var p := get_parent()
	if p is Control:
		var c := p as Control
		if not c.resized.is_connected(_on_parent_resized):
			c.resized.connect(_on_parent_resized)
		if c.size.x > 1.0 and c.size.y > 1.0:
			_apply_parent_size(c.size)
	_on_visibility_changed()


# 外部改完 frame_size / line_width 等之后调一下
func refresh() -> void:
	_dirty = true
	queue_redraw()


func _apply_parent_size(sz: Vector2) -> void:
	if sz.x < 1.0 or sz.y < 1.0:
		return
	frame_size = sz
	position = sz * 0.5
	refresh()


func _on_parent_resized() -> void:
	var p := get_parent()
	if p is Control:
		_apply_parent_size((p as Control).size)


func _on_visibility_changed() -> void:
	if _tw != null and _tw.is_valid():
		_tw.kill()
	_tw = null
	self_modulate = Color(1, 1, 1, 1)
	if not visible:
		set_process(false)
		return
	# 每次「被选中」都重新跑一遍勾边动画
	_prog = 0.0
	set_process(true)
	queue_redraw()


func _process(delta: float) -> void:
	if _prog >= 1.0:
		set_process(false)
		return
	_prog = minf(1.0, _prog + delta / maxf(DRAW_TIME, 0.01))
	queue_redraw()
	if _prog >= 1.0:
		set_process(false)
		_start_breath()


# 常亮后只让 self_modulate 呼吸：不重绘、不占 CPU
func _start_breath() -> void:
	if not breath or not is_inside_tree():
		return
	_tw = create_tween().set_loops()
	_tw.tween_property(self, "self_modulate:a", BREATH_MIN, 0.95) \
			.set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_IN_OUT)
	_tw.tween_property(self, "self_modulate:a", 1.0, 0.95) \
			.set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_IN_OUT)


func _draw() -> void:
	if _dirty:
		_rebuild()
	var n := _pts.size()
	if n < 2:
		return
	if _prog >= 1.0:
		_draw_span(0, n - 1)
		return
	var last := int(ceil(float(n - 1) * _prog))
	last = clampi(last, 1, n - 1)
	_draw_span(0, last)
	# 笔头：白热光点
	var head := _pts[last]
	draw_circle(head, line_width * 2.0, Color(1, 1, 1, 0.85))
	draw_circle(head, line_width * 5.5, Color(1, 1, 1, 0.10))


func _draw_span(a: int, b: int) -> void:
	var pts := PackedVector2Array()
	var cols := PackedColorArray()
	for i in range(a, b + 1):
		pts.append(_pts[i])
		cols.append(_cols[i])
	if pts.size() < 2:
		return
	var shadow := PackedColorArray()
	var halo := PackedColorArray()
	for c in cols:
		shadow.append(Color(0.02, 0.03, 0.06, 0.30))
		halo.append(Color(c.r, c.g, c.b, 0.24))
	# 深色垫底（在浅色牌面上也看得清）→ 外发光 → 彩色主线
	draw_polyline_colors(pts, shadow, line_width + 2.2, true)
	draw_polyline_colors(pts, halo, line_width + 4.5, true)
	draw_polyline_colors(pts, cols, line_width, true)


func _rebuild() -> void:
	_dirty = false
	_pts = PackedVector2Array()
	_cols = PackedColorArray()
	if frame_size.x < 4.0 or frame_size.y < 4.0:
		return
	var rect := Rect2(-frame_size * 0.5, frame_size)
	rect.position += Vector2(inset, inset) + offset
	rect.size -= Vector2(inset, inset) * 2.0
	if rect.size.x < 3.0 or rect.size.y < 3.0:
		return
	var r: float = clampf(corner_radius, 0.0, minf(rect.size.x, rect.size.y) * 0.5)
	_pts = _rounded_rect(rect, r)
	var n := _pts.size()
	if n < 2:
		return
	var total := 0.0
	for i in range(1, n):
		total += _pts[i - 1].distance_to(_pts[i])
	total = maxf(total, 0.001)
	var acc := 0.0
	for i in range(n):
		if i > 0:
			acc += _pts[i - 1].distance_to(_pts[i])
		var h := fmod(HUE_SPAN * (acc / total) + 0.52, 1.0)
		_cols.append(Color.from_hsv(h, SAT, VAL, 1.0))


# 顺时针一圈：左上角开始
func _rounded_rect(rect: Rect2, r: float) -> PackedVector2Array:
	var pts := PackedVector2Array()
	var x0 := rect.position.x
	var y0 := rect.position.y
	var x1 := rect.end.x
	var y1 := rect.end.y
	var cx := [x0 + r, x1 - r, x1 - r, x0 + r]
	var cy := [y0 + r, y0 + r, y1 - r, y1 - r]
	var a0 := [PI, -PI * 0.5, 0.0, PI * 0.5]
	var a1 := [PI * 1.5, 0.0, PI * 0.5, PI]
	for k in range(4):
		var arc: float = absf(a1[k] - a0[k]) * r
		var na: int = maxi(2, int(ceil(arc / STEP)))
		for i in range(na + 1):
			var a: float = lerpf(a0[k], a1[k], float(i) / float(na))
			pts = _push(pts, Vector2(cx[k] + cos(a) * r, cy[k] + sin(a) * r))
		var nx := (k + 1) % 4
		var p_from := Vector2(cx[k] + cos(a1[k]) * r, cy[k] + sin(a1[k]) * r)
		var p_to := Vector2(cx[nx] + cos(a0[nx]) * r, cy[nx] + sin(a0[nx]) * r)
		var seg: float = p_from.distance_to(p_to)
		var ns: int = maxi(1, int(ceil(seg / STEP)))
		for i in range(1, ns):
			pts = _push(pts, p_from.lerp(p_to, float(i) / float(ns)))
	if pts.size() > 1:
		pts = _push(pts, pts[0])          # 闭合成一圈
	return pts


func _push(pts: PackedVector2Array, p: Vector2) -> PackedVector2Array:
	if pts.size() == 0 or pts[pts.size() - 1].distance_to(p) > 0.01:
		pts.append(p)
	return pts
