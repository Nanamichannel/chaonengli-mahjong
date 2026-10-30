extends Control
# 座位选择面板（东南西北）—— 独立面板，不属于任何人物卡。
#
# 为什么要有它：以前「东南西北」是 Skill2 的子节点，
#   · 位置永远在 S2 上方；
#   · S2 用掉后 set_skill_disabled(1,true) 把 Skill2 的 modulate 变灰，子节点一起灰；
#   · 同一张卡的 S1/S2 还会抢同一套按钮。
# 现在统一成这个面板：位置固定、不跟任何技能状态挂钩、单例复用。
#
# 外观（用户口径 2026-10-28）：**只要东南西北四个按钮** —— 不要全屏半透明遮罩、
# 不要大底板、不要取消按钮（Esc 取消）；标题是一行小字；「跳过」只有需要时才出现。
#
# 微调接口（用户自己调）：
#   Main.seat_pick_tune(scale, Vector2(0.5, 0.80))   # 缩放 + 位置（视口比例，以按钮行为中心）
#   Main.seat_pick_reset()                          # 回到默认
#   Main.seat_pick_info()                           # 看当前值
# 也可以直接改 DEFAULT_SCALE / DEFAULT_POS / BTN / GAP 常量。

signal picked(seat: int)
signal cancelled()
signal skipped()

const TEX_DIR := "res://Cailiao/skill/ui/winds/"
const TEX_FILES := ["dong", "nan", "xi", "bei"]
const CFG_PATH := "user://seat_pick.cfg"

const BTN := 96.0               # 方位按钮边长（未缩放）—— 用户说现在这个大小正好
const GAP := 18.0               # 按钮间距
const TITLE_H := 26.0           # 标题（一行小字）高度
const TITLE_SIZE := 18
const ROW_GAP := 8.0            # 标题 / 按钮 / 跳过 之间
const SKIP_H := 32.0            # 「跳过」小按钮高度
const SKIP_W := 104.0
const DEFAULT_SCALE := 1.0
const DEFAULT_POS := Vector2(0.5, 0.80)   # 视口比例（按钮行的中心点）

var _box: Control = null
var _title: Label = null
var _btns: Array = []            # 4 个 TextureButton
var _frames: Array = []          # 4 个红框（选中）
var _skip: Button = null

var _seat_of_wind: Array = []    # 方位 index → 绝对座位号
var _enabled: Array = []         # 方位 index → 能不能点
var _allow_skip := false
var _picked := -1

var _scale_v := DEFAULT_SCALE
var _pos_v := DEFAULT_POS


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE      # 空着的地方不挡点击（没有遮罩层）
	z_index = 320
	z_as_relative = false
	visible = false
	_load_cfg()
	if not FileAccess.file_exists(CFG_PATH):
		_save_cfg()          # 第一次进游戏就把默认值写出来，方便直接改文件
	_build()


func _build() -> void:
	if _box != null:
		return                       # 已经建过（_ready 跑过了）
	_box = Control.new()
	_box.name = "Box"
	_box.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_box)

	_title = Label.new()
	_title.name = "Title"
	_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_title.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	_title.add_theme_font_size_override("font_size", TITLE_SIZE)
	_title.add_theme_color_override("font_color", Color(1, 0.94, 0.7))
	_title.add_theme_color_override("font_outline_color", Color(0, 0, 0))
	_title.add_theme_constant_override("outline_size", 5)
	_title.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_box.add_child(_title)

	for i in range(4):
		var b := TextureButton.new()
		b.name = "Wind%d" % i
		var tex := load(TEX_DIR + String(TEX_FILES[i]) + ".png") as Texture2D
		if tex != null:
			b.texture_normal = tex
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		b.pressed.connect(_on_wind.bind(i))
		_box.add_child(b)
		_btns.append(b)
		var f := ReferenceRect.new()
		f.name = "Frame"
		f.editor_only = false
		f.border_color = Color(1.0, 0.16, 0.16, 1.0)
		f.border_width = 4.0
		f.mouse_filter = Control.MOUSE_FILTER_IGNORE
		f.visible = false
		b.add_child(f)
		_frames.append(f)

	_skip = Button.new()
	_skip.name = "Skip"
	_skip.text = "跳过"
	_skip.focus_mode = Control.FOCUS_NONE
	_skip.pressed.connect(_on_skip)
	_box.add_child(_skip)


# ── 打开 / 关闭 ─────────────────────────────────────────────────────
func open(title: String, seat_of_wind: Array, enabled: Array = [],
		allow_skip: bool = false) -> void:
	if _box == null:
		_build()                     # 保险：万一 _ready 还没跑
	if _title == null:
		return
	_title.text = String(title)
	_seat_of_wind = []
	for i in range(4):
		_seat_of_wind.append(int(seat_of_wind[i]) if i < seat_of_wind.size() else i)
	_enabled = []
	for i in range(4):
		_enabled.append(bool(enabled[i]) if i < enabled.size() else true)
	_allow_skip = bool(allow_skip)
	_picked = -1
	for f in _frames:
		(f as ReferenceRect).visible = false
	visible = true
	_relayout()


func close() -> void:
	visible = false
	_picked = -1


func is_open() -> bool:
	return visible


# ── 微调接口 ────────────────────────────────────────────────────────
func tune(scale_value: float, pos_ratio: Vector2) -> void:
	if scale_value > 0.05:
		_scale_v = float(scale_value)
	_pos_v = Vector2(float(pos_ratio.x), float(pos_ratio.y))
	_save_cfg()
	_relayout()


func tune_reset() -> void:
	_scale_v = DEFAULT_SCALE
	_pos_v = DEFAULT_POS
	_save_cfg()
	_relayout()


func tune_info() -> Dictionary:
	return {"scale": _scale_v, "pos": [_pos_v.x, _pos_v.y],
			"btn": BTN, "gap": GAP, "skip": _allow_skip,
			"cfg": ProjectSettings.globalize_path(CFG_PATH)}


func _load_cfg() -> void:
	if not FileAccess.file_exists(CFG_PATH):
		return
	var f := FileAccess.open(CFG_PATH, FileAccess.READ)
	if f == null:
		return
	var raw := f.get_as_text()
	f.close()
	var d = JSON.parse_string(raw)
	if typeof(d) != TYPE_DICTIONARY:
		return
	var s := float((d as Dictionary).get("scale", DEFAULT_SCALE))
	var p = (d as Dictionary).get("pos", null)
	if s > 0.05:
		_scale_v = s
	if typeof(p) == TYPE_ARRAY and (p as Array).size() == 2:
		_pos_v = Vector2(float(p[0]), float(p[1]))


func _save_cfg() -> void:
	var f := FileAccess.open(CFG_PATH, FileAccess.WRITE)
	if f == null:
		return
	f.store_string(JSON.stringify({"scale": _scale_v, "pos": [_pos_v.x, _pos_v.y]}))
	f.close()


# ── 布局：只有「小字标题 + 四个按钮（+ 跳过）」 ────────────────────
func _relayout() -> void:
	if _box == null:
		return
	var vp := get_viewport_rect().size
	position = Vector2.ZERO
	size = vp                             # 只为算坐标；mouse_filter=IGNORE 不会挡点击
	var row_w := BTN * 4.0 + GAP * 3.0
	var title_w := row_w
	if _title != null:
		var fnt := _title.get_theme_font("font")
		if fnt != null:
			title_w = fnt.get_string_size(_title.text, HORIZONTAL_ALIGNMENT_LEFT, -1,
				TITLE_SIZE).x
	var box_w := maxf(row_w, title_w)
	var box_h := TITLE_H + ROW_GAP + BTN + (ROW_GAP + SKIP_H if _allow_skip else 0.0)
	_box.size = Vector2(box_w, box_h)
	_box.pivot_offset = _box.size * 0.5
	_box.scale = Vector2(_scale_v, _scale_v)
	_box.position = _pos_v * vp - _box.size * _scale_v * 0.5
	# 标题：小字一行，居中在按钮行上方（宽一点没关系，没有底板）
	_title.position = Vector2((box_w - title_w) * 0.5, 0.0)
	_title.size = Vector2(title_w, TITLE_H)
	var y := TITLE_H + ROW_GAP
	var left := (box_w - row_w) * 0.5
	for i in range(_btns.size()):
		var b := _btns[i] as TextureButton
		b.position = Vector2(left + float(i) * (BTN + GAP), y)
		b.size = Vector2(BTN, BTN)
		b.pivot_offset = b.size * 0.5
		b.modulate = Color(1, 1, 1, 1) if bool(_enabled[i]) else Color(1, 1, 1, 0.32)
		var f := _frames[i] as ReferenceRect
		f.position = Vector2.ZERO
		f.size = b.size
	if _skip != null:
		_skip.visible = _allow_skip
		_skip.position = Vector2((box_w - SKIP_W) * 0.5, y + BTN + ROW_GAP)
		_skip.size = Vector2(SKIP_W, SKIP_H)


# ── 交互 ────────────────────────────────────────────────────────────
func _on_wind(i: int) -> void:
	if i >= _enabled.size() or not bool(_enabled[i]):
		return
	if i >= _seat_of_wind.size():
		return
	_picked = int(_seat_of_wind[i])
	for k in range(_frames.size()):
		(_frames[k] as ReferenceRect).visible = (k == i)
	picked.emit(int(_seat_of_wind[i]))


func _on_skip() -> void:
	close()
	skipped.emit()


func _on_cancel() -> void:
	close()
	cancelled.emit()


func _input(event: InputEvent) -> void:
	if not visible:
		return
	if event is InputEventKey:
		var k := event as InputEventKey
		if k.pressed and not k.echo and k.keycode == KEY_ESCAPE:
			_on_cancel()
			get_viewport().set_input_as_handled()
