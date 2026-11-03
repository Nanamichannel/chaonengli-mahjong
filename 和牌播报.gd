extends Node2D

# ─────────────────────────────────────────────────────────────────────────────
# 和牌播报（场景 res://和牌播报.tscn）
#
# ① 点击和牌那一刻的全屏截图 → 背景
# ② 按赢家方位播「长条从屏幕滑过」的进场动画（上家 / 对家，下家·自己走镜像）
# ③ 长条正中贴一张人物卡（卡的宽 = 长条宽，长边贴长条长边）
# ④ 播完 → 等 1s → 全屏蒙版 +「谁铳了谁」横幅 淡入（抛物线 1.2s）
# ⑤ 停 0.2s → 番种底座从右往左逐个「从上往下」擦开（每个 0.3s，间隔 1s）
# ⑥ 全部露完 → 等 1s → 四个分数小面板 + 确认按钮 淡入（抛物线 1.2s）→ 按钮可点
#
# 调参：调试模式下鼠标拖动（横幅 / 小面板 / 手牌 / 番种条）
#       F9 打印当前数值、F12 存 user://announce_tune.cfg、F8 重新读取
# ─────────────────────────────────────────────────────────────────────────────

const ANNOUNCE_SCRIPT := preload("res://win_announce.gd")
const CARD_DIR := "res://Cailiao/skill/cards/card_%02d.png"
const MASK_PATH := "res://Cailiao/UI/睡2.png"
const BASE_TEX_PATH := "res://Cailiao/UI/结算播报底座.png"
const PLATE_TEX := "res://Cailiao/UI/底座底座.png"   # 番种条底下那块大盘子
const FONT_PATH := "res://Cailiao/fonts/xingkai.ttf"
const TUNE_CFG := "user://announce_tune.cfg"
const BAR_W := 487.0
const STEP_WAIT := 1.0

@export var intro_speed := 1.0

# ── 可调布局（调试模式下拖动会实时改这些值）──
@export var head_offset := Vector2.ZERO      # 「谁铳了谁」横幅
@export var head_scale := 1.0
@export var seats_offset := Vector2.ZERO     # 四个分数小面板整体
@export var seats_scale := 0.85
@export var seats_center_y := 0.55
@export var hand_offset := Vector2.ZERO      # 页眉手牌区
@export var hand_scale := 1.0
@export var strip_scale := 0.62
@export var strip_gap := 10.0                # 底座之间间距
@export var strip_top := 370.0
@export var fade_time := 1.2                 # 淡入时长
@export var fade_time_seats := 0.75         # 最后「小面板 + 确认按钮」的淡入时长
@export var plate_offset := Vector2.ZERO    # 「底座底座」整体偏移
@export var plate_scale := 1.0
@export var plate_wait := 0.3               # 底座底座开扫前的休息
@export var plate_wipe := 0.5               # 底座底座横向扫开的时间（从右往左）
@export var fade_pow := 2.0                  # 淡入曲线：alpha = t^pow（2 = 抛物线）

var bg: TextureRect = null
var head: Control = null                     # 蒙版 + 横幅（旧名字 announce 也指它）
var announce: Control = null
var seats_panel: Control = null              # 四个分数小面板
var strips_root: Node2D = null               # 番种底座
var plate_root: Node2D = null                # 「底座底座」那一层（在番种条下面）
var plate_clip: Control = null               # 做横向擦开用的裁剪容器
var _plate_inner: TextureRect = null
var _plate_rect := Vector2.ZERO
var _plate_full := Vector2.ZERO
var hand_root: Node2D = null                 # 和牌家手牌
var card_root: Node2D = null                 # 长条上的人物卡

var busy := false
var _gen := 0
var _card_cache := {}
var _mask_tex: Texture2D = null
var _base_tex: Texture2D = null
var _xingkai: Font = null
var _face: Sprite2D = null
var _mask_spr: Sprite2D = null
var _follow: Sprite2D = null
var _card_rot := 0.0                    # 长条朝向（贴卡时算一次）

var tune_mode := false
var _tune_sel := ""
var _tune_last := Vector2.ZERO
var _dragging := false

@onready var intro: Control = $和牌进场
@onready var bar_left: Sprite2D = $和牌进场/左
@onready var bar_top: Sprite2D = $和牌进场/对
@onready var ap_left: AnimationPlayer = $和牌进场/上家动画
@onready var ap_top: AnimationPlayer = $和牌进场/对家动画


func _ready() -> void:
	var vp := get_viewport_rect().size

	# 场景里用户摆的那个「播报底座」Sprite2D 只是模板：藏着，用它的贴图复制
	# 场景里用户摆的「播报底座」只是模板：把它所在的 Control 藏起来（贴图用文件路径加载）
	for _n in get_children():
		if _n is CanvasItem and String(_n.name) == "背景":
			(_n as CanvasItem).visible = false      # 用户拿来对位置的绿色/背景图，播报不用
			continue
		if _n is Control and String(_n.name).contains("播报"):
			(_n as CanvasItem).visible = false      # 底座模板
	_load_tune()

	# 背景：点击和牌那一刻的截图
	bg = TextureRect.new()
	bg.name = "Shot"
	bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	bg.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	bg.stretch_mode = TextureRect.STRETCH_SCALE
	bg.position = Vector2.ZERO
	bg.size = vp
	bg.z_index = -100
	add_child(bg)

	# 长条上的人物卡（单独一层）
	card_root = Node2D.new()
	card_root.name = "CardOnBar"
	card_root.z_index = 5
	card_root.visible = false
	add_child(card_root)
	_face = Sprite2D.new()
	_face.name = "CardFace"
	_face.centered = true
	card_root.add_child(_face)
	_mask_spr = Sprite2D.new()
	_mask_spr.name = "CardMask"
	_mask_spr.centered = true
	_mask_spr.z_index = 1
	card_root.add_child(_mask_spr)

	# 蒙版 + 横幅
	head = ANNOUNCE_SCRIPT.new()
	head.name = "WinAnnounce"
	head.mouse_filter = Control.MOUSE_FILTER_STOP
	head.position = Vector2.ZERO
	head.size = vp
	head.visible = false
	head.z_index = 20
	add_child(head)
	announce = head

	# 四个分数小面板（单独淡入，确认按钮也挂在这一层）
	seats_panel = ANNOUNCE_SCRIPT.new()
	seats_panel.name = "SeatsPanel"
	seats_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	seats_panel.position = Vector2.ZERO
	seats_panel.size = vp
	seats_panel.visible = false
	seats_panel.z_index = 21
	add_child(seats_panel)

	# 番种底座
	strips_root = Node2D.new()
	strips_root.name = "YakuStrips"
	strips_root.z_index = 22

	plate_root = Node2D.new()
	plate_root.name = "PlateRoot"
	plate_root.z_index = 21          # 在番种条(22)下面、蒙版(20)上面
	add_child(plate_root)
	add_child(strips_root)

	# 和牌家手牌（压在最上面）
	hand_root = Node2D.new()
	hand_root.name = "WinnerHand"
	hand_root.z_index = 30
	add_child(hand_root)

	_apply_layout()

	intro.visible = false
	set_process_priority(100)
	set_process(false)


# 卡的长边（贴图 Y 轴）要贴住长条的长边（贴图 X 轴）→ 两者差 90°；
# 再规整到 (−90°, 90°]，保证卡看起来是「正置」的。
func _bar_rot(bar: Sprite2D) -> float:
	var a := bar.global_transform.x.angle() - PI * 0.5
	while a > PI * 0.5:
		a -= PI
	while a <= -PI * 0.5:
		a += PI
	return a


func _process(_dt: float) -> void:
	if _follow != null and is_instance_valid(_follow) and card_root.visible:
		var xf := _follow.global_transform
		card_root.global_position = xf.origin
		card_root.rotation = _card_rot          # 长条朝向贴卡时算一次就够了


func _card_tex(card_no: int) -> Texture2D:
	var c := int(card_no)
	if c <= 0:
		return null
	if _card_cache.has(c):
		return _card_cache[c]
	var tex := load(CARD_DIR % c) as Texture2D
	_card_cache[c] = tex
	return tex


func _mask() -> Texture2D:
	if _mask_tex == null:
		_mask_tex = load(MASK_PATH) as Texture2D
	return _mask_tex


func _base_texture() -> Texture2D:
	if _base_tex == null:
		_base_tex = load(BASE_TEX_PATH) as Texture2D
	return _base_tex


func _font_xingkai() -> Font:
	if _xingkai == null:
		_xingkai = load(FONT_PATH) as Font
	return _xingkai


# 贴卡：卡「宽」（短边）= 长条「宽」（短边）；长边沿长条长度方向居中
func _set_card(bar: Sprite2D, card_no: int, need_mask: bool) -> void:
	var tex := _card_tex(card_no)
	if tex == null:
		card_root.visible = false
		_follow = null
		return
	var cw := float(maxi(tex.get_width(), 1))
	var ch := float(maxi(tex.get_height(), 1))
	var bar_scale := absf(bar.global_scale.y)
	_card_rot = _bar_rot(bar)
	var s := BAR_W * bar_scale / cw
	_follow = bar
	card_root.visible = true
	var bxf := bar.global_transform
	card_root.global_position = bxf.origin
	card_root.rotation = _card_rot
	set_process(true)

	_face.texture = tex
	_face.scale = Vector2(s, s)
	_face.visible = true

	if need_mask:
		var mt := _mask()
		if mt != null:
			_mask_spr.texture = mt
			_mask_spr.scale = Vector2(cw * s / float(maxi(mt.get_width(), 1)),
				ch * s / float(maxi(mt.get_height(), 1)))
			_mask_spr.visible = true
		else:
			_mask_spr.visible = false
	else:
		_mask_spr.visible = false


# ── 把 @export 里的布局值推给各个节点 ────────────────────────────────────────
func _apply_layout() -> void:
	var vp := get_viewport_rect().size
	if head != null:
		head.draw_mode = "head"
		head.banner_size = Vector2(820.0, 72.0)
		head.banner_scale = head_scale
		head.banner_pos = Vector2(vp.x * 0.5, 176.0) + head_offset
		head.queue_redraw()
	if seats_panel != null:
		seats_panel.draw_mode = "seats"
		seats_panel.center_y = seats_center_y
		seats_panel.seats_offset = seats_offset
		seats_panel.seats_scale = seats_scale
		seats_panel.queue_redraw()
	if hand_root != null:
		hand_root.position = hand_offset
		hand_root.scale = Vector2(hand_scale, hand_scale)
	if strips_root != null:
		for st in strips_root.get_children():
			if st is Control:
				(st as Control).position.y = strip_top


# ── 番种底座：竖排文字（行楷、黑字带淡描边）────────────────────────────────
func _vertical_text(txt: String) -> String:
	var s := txt.strip_edges()
	if s.length() <= 1:
		return s
	var out := ""
	for i in range(s.length()):
		if i > 0:
			out += "\n"
		out += s.substr(i, 1)
	return out


func _vlabel(font: Font, txt: String, want_fs: float, area: Vector2) -> Label:
	var lb := Label.new()
	lb.mouse_filter = Control.MOUSE_FILTER_IGNORE
	lb.text = _vertical_text(txt)
	lb.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	lb.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	lb.autowrap_mode = TextServer.AUTOWRAP_OFF
	lb.clip_text = true
	lb.size = area
	lb.position = Vector2.ZERO
	if font != null:
		lb.add_theme_font_override("font", font)
	var n := maxi(lb.text.count("\n") + 1, 1)
	var fs := minf(want_fs, area.y / float(n) / 1.16)   # 1.16 ≈ 行高系数，不然顶出底座
	fs = maxf(fs, 10.0)
	lb.add_theme_font_size_override("font_size", int(fs))
	lb.add_theme_color_override("font_color", Color(0.02, 0.05, 0.05, 1.0))
	lb.add_theme_color_override("font_outline_color", Color(0.965, 1.0, 0.988, 0.95))
	lb.add_theme_constant_override("outline_size", maxi(int(fs * 0.10), 3))
	lb.add_theme_constant_override("line_spacing", -int(fs * 0.18))
	return lb


# ── 「底座底座」：番种条之前先横向扫开的那块大盘子 ─────────────────────
func _clear_plate() -> void:
	if plate_root != null:
		for c in plate_root.get_children():
			plate_root.remove_child(c)
			c.queue_free()
	plate_clip = null
	_plate_inner = null


func _build_plate() -> void:
	_clear_plate()
	if plate_root == null:
		return
	var vp := get_viewport_rect().size
	var tex: Texture2D = null
	var center := vp * 0.5
	var extra := Vector2.ONE
	var src := get_node_or_null("底座底座")   # 用户摆好的节点（有就用它的位置/缩放）
	if src is Sprite2D and (src as Sprite2D).texture != null:
		tex = (src as Sprite2D).texture
		center = (src as Sprite2D).global_position
		extra = (src as Sprite2D).global_scale
		(src as CanvasItem).visible = false
	else:
		tex = load(PLATE_TEX) as Texture2D
	if tex == null:
		return
	extra *= plate_scale
	var size := Vector2(tex.get_width(), tex.get_height()) * extra
	_plate_full = size
	_plate_rect = center - size * 0.5 + plate_offset
	plate_clip = Control.new()
	plate_clip.name = "PlateClip"
	plate_clip.clip_contents = true
	plate_clip.mouse_filter = Control.MOUSE_FILTER_IGNORE
	plate_clip.position = _plate_rect
	plate_clip.size = Vector2(0.01, size.y)
	plate_clip.visible = false
	plate_root.add_child(plate_clip)
	_plate_inner = TextureRect.new()
	_plate_inner.texture = tex
	_plate_inner.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_plate_inner.stretch_mode = TextureRect.STRETCH_SCALE
	_plate_inner.size = size
	_plate_inner.position = Vector2.ZERO
	_plate_inner.mouse_filter = Control.MOUSE_FILTER_IGNORE
	plate_clip.add_child(_plate_inner)


# 横向扫开：从右往左（裁剪框右边缘不动，左边缘往左长；内容反向补偿）
func _reveal_plate(gen: int) -> void:
	if plate_clip == null:
		return
	plate_clip.visible = true
	var w := _plate_full.x
	plate_clip.size = Vector2(0.01, _plate_full.y)
	plate_clip.position.x = _plate_rect.x + w
	_plate_inner.position.x = -w
	var tw := create_tween()
	tw.tween_method(func(p: float) -> void:
		if plate_clip == null or _plate_inner == null:
			return
		plate_clip.size = Vector2(maxf(w * p, 0.01), _plate_full.y)
		plate_clip.position.x = _plate_rect.x + w * (1.0 - p)
		_plate_inner.position.x = -w * (1.0 - p)
	, 0.0, 1.0, maxf(plate_wipe, 0.05)).set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_OUT)
	await tw.finished


func _clear_strips() -> void:
	if strips_root == null:
		return
	for c in strips_root.get_children():
		strips_root.remove_child(c)
		c.queue_free()


func _build_strips(rows: Array) -> void:
	_clear_strips()
	var tex := _base_texture()
	if tex == null or rows.is_empty():
		return
	var vp := get_viewport_rect().size
	var w := float(tex.get_width()) * strip_scale
	var h := float(tex.get_height()) * strip_scale
	var n := rows.size()
	var total := float(n) * w + float(maxi(n - 1, 0)) * strip_gap
	var x0 := maxf((vp.x - total) * 0.5, 8.0)
	var font := _font_xingkai()
	for i in range(n):
		var row: Dictionary = rows[i]
		var strip := Control.new()
		strip.name = "Yaku%d" % i
		strip.clip_contents = true                  # ★ 靠它做「从上往下擦开」
		strip.mouse_filter = Control.MOUSE_FILTER_IGNORE
		strip.position = Vector2(x0 + float(n - 1 - i) * (w + strip_gap), strip_top)   # 从右往左排
		strip.size = Vector2(w, h)
		strip.modulate.a = 1.0
		strips_root.add_child(strip)

		var tr := TextureRect.new()
		tr.texture = tex
		tr.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		tr.stretch_mode = TextureRect.STRETCH_SCALE
		tr.mouse_filter = Control.MOUSE_FILTER_IGNORE
		tr.size = Vector2(w, h)
		tr.position = Vector2.ZERO
		strip.add_child(tr)

		var name_area := Vector2(w, h * 0.50)
		var nm := _vlabel(font, String(row.get("name", "")), w * 0.66, name_area)
		nm.position = Vector2(0.0, h * 0.06)      # 往下挪一点，别顶出笔触上沿
		strip.add_child(nm)

		var han_area := Vector2(w, h * 0.40)
		var hl := _vlabel(font, String(row.get("han_text", "")), w * 0.52, han_area)
		hl.position = Vector2(0.0, h * 0.56)
		strip.add_child(hl)

		# 先藏着（高度几乎为 0 + clip），入场时再拉开
		strip.set_meta("full_h", h)
		strip.size = Vector2(w, 0.5)
		strip.visible = false


# 从右往左逐个擦开：每个 0.3s，露完等 1s 再下一个
func _reveal_strips(gen: int) -> void:
	var kids := strips_root.get_children()
	for idx in range(kids.size()):                 # 子节点 0 = 最右 → 从右往左露
		if gen != _gen:
			return
		var st := kids[idx] as Control
		if st == null:
			continue
		var full := float(st.get_meta("full_h", st.size.y))
		st.visible = true
		st.size = Vector2(st.size.x, 0.5)
		var tw := st.create_tween()
		tw.tween_property(st, "size:y", full, 0.3).set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_OUT)
		await tw.finished
		if gen != _gen:
			return
		if idx < kids.size() - 1:
			await get_tree().create_timer(1.0).timeout


# 抛物线淡入：Tween 的 QUAD/EASE_IN 就是 t²，交给引擎跑，不用每帧过脚本
func _fade_group(nodes: Array, dur: float, target: float = 1.0) -> void:
	var live: Array = []
	for n in nodes:
		if n != null and is_instance_valid(n):
			(n as CanvasItem).modulate.a = 0.0
			live.append(n)
	if live.is_empty():
		return
	var tw := create_tween()
	tw.set_parallel(true)
	for n in live:
		tw.tween_property(n, "modulate:a", target, maxf(dur, 0.05)) \
			.set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_IN)
	await tw.finished


func _enable_confirm() -> void:
	if seats_panel == null:
		return
	for c in seats_panel.get_children():
		if c is Control and String(c.name).begins_with("Confirm"):
			(c as Control).visible = true
			(c as Control).mouse_filter = Control.MOUSE_FILTER_STOP


func _hide_confirm() -> void:
	if seats_panel == null:
		return
	for c in seats_panel.get_children():
		if c is Control and String(c.name).begins_with("Confirm"):
			(c as Control).visible = false
			(c as Control).mouse_filter = Control.MOUSE_FILTER_IGNORE


func _reset_visual() -> void:
	intro.visible = false
	intro.scale = Vector2.ONE
	intro.position = Vector2.ZERO
	bar_left.visible = false
	bar_top.visible = false
	_follow = null
	set_process(false)
	if card_root != null:
		card_root.visible = false
		card_root.rotation = 0.0
	if _face != null:
		_face.visible = false
	if _mask_spr != null:
		_mask_spr.visible = false
	_clear_plate()
	_clear_strips()
	if head != null:
		head.visible = false
		head.modulate.a = 1.0
	if seats_panel != null:
		seats_panel.visible = false
		seats_panel.modulate.a = 1.0
	_hide_confirm()


func reset() -> void:
	clear_hand()
	busy = false
	_gen += 1
	_reset_visual()
	if bg != null:
		bg.texture = null


# 流局：不播进场动画，直接贴「蒙版+横幅」→ 小面板
func show_panel(data: Dictionary) -> void:
	clear_hand()
	_apply_layout()
	busy = true
	_gen += 1
	var gen := _gen
	_reset_visual()
	if bg != null:
		bg.texture = null
	if head != null:
		head.call("set_content", data)
		head.visible = true
		await _fade_group([head], fade_time)
	if gen != _gen:
		busy = false
		return
	await get_tree().create_timer(0.2).timeout
	if seats_panel != null:
		seats_panel.call("set_content", data)
		seats_panel.visible = true
		await _fade_group([seats_panel], fade_time_seats)
	if gen != _gen:
		busy = false
		return
	_enable_confirm()
	busy = false


# 入口：who = "me"/"D"/"C"/"B"；data = 结算内容
func play(who: String, card_no: int, need_mask: bool, shot: Texture2D,
		data: Dictionary) -> void:
	_apply_layout()
	busy = true
	var gen := _gen
	_reset_visual()
	if bg != null:
		pass    # 播报不要背景图：只靠全屏蒙版压暗桌面

	# 上家 / 下家 → 「左」那条；对家 / 自己 → 「对」那条
	var use_left := who == "B" or who == "D"
	var mirror := who == "D" or who == "me"
	var bar := bar_left if use_left else bar_top
	var ap := ap_left if use_left else ap_top
	var anim := "new_animation" if use_left else "new_animation_2"

	var vp := get_viewport_rect().size
	intro.scale = Vector2(-1.0, 1.0) if mirror else Vector2.ONE
	intro.position = Vector2(vp.x, 0.0) if mirror else Vector2.ZERO

	intro.visible = true
	bar.visible = true
	_set_card(bar, card_no, need_mask)

	ap.speed_scale = maxf(float(intro_speed), 0.05)
	ap.play(anim)
	await ap.animation_finished
	ap.speed_scale = 1.0
	if gen != _gen:
		busy = false
		return

	# 进场动画播完：隐藏长条 + 卡，背景留着
	intro.visible = false
	intro.scale = Vector2.ONE
	intro.position = Vector2.ZERO
	card_root.visible = false
	_follow = null
	set_process(false)

	await get_tree().create_timer(STEP_WAIT).timeout
	if gen != _gen:
		busy = false
		return

	# ④ 全屏蒙版 +「谁铳了谁」横幅（+ 页眉手牌）淡入
	if head != null:
		head.call("set_content", data)
		head.visible = true
	if hand_root != null and hand_root.get_child_count() > 0:
		hand_root.visible = true
		await _fade_group([head, hand_root], fade_time)
	else:
		await _fade_group([head], fade_time)
	if gen != _gen:
		busy = false
		return

	# ⑤ 停 0.2s → 番种底座从右往左擦开
	await get_tree().create_timer(0.2).timeout
	if gen != _gen:
		busy = false
		return
	# 底座底座：先休息 0.3s，再横向从右往左扫开 0.5s（扫完立刻露第一条番种）
	_build_plate()
	await get_tree().create_timer(maxf(plate_wait, 0.0)).timeout
	if gen != _gen:
		busy = false
		return
	await _reveal_plate(gen)
	if gen != _gen:
		busy = false
		return
	var rows = data.get("yaku_rows", [])
	_build_strips(rows if typeof(rows) == TYPE_ARRAY else [])
	await _reveal_strips(gen)
	if gen != _gen:
		busy = false
		return

	# ⑥ 等 1s → 四个小面板 + 确认按钮 淡入
	await get_tree().create_timer(1.0).timeout
	if gen != _gen:
		busy = false
		return
	if seats_panel != null:
		seats_panel.call("set_content", data)
		seats_panel.visible = true
	await _fade_group([seats_panel], fade_time_seats)
	if gen != _gen:
		busy = false
		return
	_enable_confirm()
	busy = false


# 和牌家的手牌：由 main.gd 造好整块 Node2D 传进来
func set_hand(node: Node2D) -> void:
	clear_hand()
	if node == null or hand_root == null:
		return
	hand_root.add_child(node)
	hand_root.visible = false
	hand_root.modulate.a = 1.0


func clear_hand() -> void:
	if hand_root == null:
		return
	for c in hand_root.get_children():
		hand_root.remove_child(c)
		c.queue_free()


# main.gd 用：确认按钮挂到这一层（和小面板一起淡入）
func seats_node() -> Control:
	return seats_panel


# ── 调试：拖动调参 ───────────────────────────────────────────────────────────
func set_tune_mode(on: bool) -> void:
	tune_mode = on
	if on:
		_report_tune()


func _tune_hit(pos: Vector2) -> String:
	var vp := get_viewport_rect().size
	if head != null:
		var bs: Vector2 = head.banner_size * head_scale
		var r := Rect2(head.banner_pos - bs * 0.5, bs).grow(24.0)
		if r.has_point(pos):
			return "head"
	if pos.y < 170.0:
		return "hand"
	if pos.y >= strip_top - 24.0 and strips_root != null and strips_root.get_child_count() > 0:
		return "strips"
	if seats_panel != null:
		var rect := Rect2(Vector2(vp.x * 0.5, vp.y * seats_center_y) - Vector2(490.0, 310.0) * seats_scale,
			Vector2(980.0, 620.0) * seats_scale)
		rect.position += seats_offset
		if rect.grow(40.0).has_point(pos):
			return "seats"
	return ""


func _input(event: InputEvent) -> void:
	if not tune_mode:
		return
	var k := event as InputEventKey
	if k != null and k.pressed and not k.echo:
		if k.keycode == KEY_F9:
			_report_tune()
			get_viewport().set_input_as_handled()
		elif k.keycode == KEY_F12:
			_save_tune()
			get_viewport().set_input_as_handled()
		elif k.keycode == KEY_F8:
			_load_tune()
			_apply_layout()
			_report_tune()
			get_viewport().set_input_as_handled()
		return
	var mb := event as InputEventMouseButton
	if mb != null and mb.button_index == MOUSE_BUTTON_LEFT:
		if mb.pressed:
			_tune_sel = _tune_hit(mb.position)
			_dragging = _tune_sel != ""
			_tune_last = mb.position
			if _dragging:
				print("[announce tune] 抓取：", _tune_sel)
				get_viewport().set_input_as_handled()
		else:
			if _dragging:
				_save_tune()
			_dragging = false
			_tune_sel = ""
		return
	var mm := event as InputEventMouseMotion
	if _dragging and mm != null:
		var d: Vector2 = mm.position - _tune_last
		_tune_last = mm.position
		match _tune_sel:
			"head":
				head_offset += d
			"seats":
				seats_offset += d
			"hand":
				hand_offset += d
			"strips":
				strip_top += d.y
		_apply_layout()
		get_viewport().set_input_as_handled()


func _report_tune() -> void:
	print("[announce tune] head_offset=%s head_scale=%.3f | seats_offset=%s seats_scale=%.3f center_y=%.3f" % [
		str(head_offset), head_scale, str(seats_offset), seats_scale, seats_center_y])
	print("[announce tune] hand_offset=%s hand_scale=%.3f | strip_top=%.1f strip_scale=%.3f strip_gap=%.1f" % [
		str(hand_offset), hand_scale, strip_top, strip_scale, strip_gap])


func _save_tune() -> void:
	var cf := ConfigFile.new()
	cf.set_value("head", "offset", head_offset)
	cf.set_value("head", "scale", head_scale)
	cf.set_value("seats", "offset", seats_offset)
	cf.set_value("seats", "scale", seats_scale)
	cf.set_value("seats", "center_y", seats_center_y)
	cf.set_value("hand", "offset", hand_offset)
	cf.set_value("hand", "scale", hand_scale)
	cf.set_value("strips", "top", strip_top)
	cf.set_value("strips", "scale", strip_scale)
	cf.set_value("strips", "gap", strip_gap)
	cf.save(TUNE_CFG)
	print("[announce tune] 已保存 ", TUNE_CFG)
	_report_tune()


func _load_tune() -> void:
	var cf := ConfigFile.new()
	if cf.load(TUNE_CFG) != OK:
		return
	head_offset = cf.get_value("head", "offset", head_offset)
	head_scale = float(cf.get_value("head", "scale", head_scale))
	seats_offset = cf.get_value("seats", "offset", seats_offset)
	seats_scale = float(cf.get_value("seats", "scale", seats_scale))
	seats_center_y = float(cf.get_value("seats", "center_y", seats_center_y))
	hand_offset = cf.get_value("hand", "offset", hand_offset)
	hand_scale = float(cf.get_value("hand", "scale", hand_scale))
	strip_top = float(cf.get_value("strips", "top", strip_top))
	strip_scale = float(cf.get_value("strips", "scale", strip_scale))
	strip_gap = float(cf.get_value("strips", "gap", strip_gap))
