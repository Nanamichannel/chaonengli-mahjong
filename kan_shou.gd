extends Node2D
## 鉴赏界面：点卡放大（AnimationPlayer 关键帧，先快后慢）／右键逆动画退回
## 中键拖动由 Camera2D（kan_shou_camera.gd）自己处理，这里只给它注边界。

const SKIP_TEX := "res://Cailiao/UI/tiaoguo.png"      # 右上角「跳过」
const ANIM_ZOOM := "放大"
const START_SCENE := "res://真初始场景.tscn"
const Wipe := preload("res://transition_wipe.gd")
const ANIM_SHRINK := "缩小"
## ease-out cubic 采样（与 AnimationPlayer 里 "放大" 的 6 个关键帧一一对应：1-(1-x)^3）
const EASE_OUT := [0.0, 0.488, 0.784, 0.936, 0.992, 1.0]

@onready var _cam: Camera2D = $摄像机
@onready var _dim: ColorRect = $遮罩层/黑幕
@onready var _big: TextureRect = $遮罩层/放大卡
@onready var _ap: AnimationPlayer = $动画

var _open := false
var _skip_ui: CanvasLayer = null       # 固定层（不跟相机走）
var _skip_btn: TextureButton = null
var _card: TextureButton = null
var _leaving := false
var _start_ps: PackedScene = null
var _start_req := false


func _ready() -> void:
	_big.visible = false
	_dim.color.a = 0.0
	for c in get_children():
		if c is TextureButton and c.name != "背景板":
			(c as TextureButton).pressed.connect(_on_card_pressed.bind(c))
	_ap.animation_finished.connect(_on_anim_finished)
	_inject_camera_limit()
	_make_skip_ui()
	# 倒放转场要实例化一级菜单，提前预加载，按 ESC 时不卡
	_start_req = (ResourceLoader.load_threaded_request(START_SCENE, "PackedScene") == OK)


## 边界 = 所有卡片的包围盒再各边留 120px（背景板不算，它在 AE 里位置不同）
func _inject_camera_limit() -> void:
	var r := Rect2()
	var first := true
	for c in get_children():
		if c is TextureButton and c.name != "背景板":
			var rr: Rect2 = (c as TextureButton).get_global_rect()
			if first:
				r = rr
				first = false
			else:
				r = r.merge(rr)
	if first:
		return
	_cam.set("limit_rect", r.grow(120.0))
	# 滚轮放大上限：背景板视觉宽度铺满屏幕
	var bg = get_node_or_null("背景板")
	if bg != null and bg is Control:
		var bgr := _visual_rect(bg as Control)
		if bgr.size.x > 1.0:
			_cam.set("backdrop_width", bgr.size.x)


## 卡片在「屏幕空间」的中心（CanvasLayer 坐标；含相机 zoom）
func _card_screen_center(card: Control) -> Vector2:
	var r: Rect2 = card.get_global_rect()
	var vp := get_viewport_rect().size
	return (r.position + r.size * 0.5 - _cam.get_screen_center_position()) * _cam.zoom + vp * 0.5


## 卡片在屏幕上的尺寸（含相机 zoom）
func _card_screen_size(card: Control) -> Vector2:
	return card.get_global_rect().size * _cam.zoom


## 放大卡的 position：pivot 在中心，所以视觉中心恒为 position + size*0.5（与 scale 无关）
func _big_pos_for_center(c: Vector2) -> Vector2:
	return c - _big.size * 0.5


## Control 经过 rotation/scale 后在世界里的 AABB（get_global_rect 不含旋转）
func _visual_rect(c: Control) -> Rect2:
	var xf := c.get_global_transform()
	var sz := c.size
	var pts := [Vector2.ZERO, Vector2(sz.x, 0), Vector2(0, sz.y), sz]
	var r := Rect2(xf * pts[0], Vector2.ZERO)
	for i in range(1, 4):
		r = r.expand(xf * pts[i])
	return r


## 右上角「跳过」：固定屏幕位置（放 CanvasLayer，别跟着相机平移/缩放）
##   网格态显示 → 点击回真初始场景；放大态隐藏（放大态点空白就缩回）
func _make_skip_ui() -> void:
	_skip_ui = CanvasLayer.new()
	_skip_ui.name = "SkipLayer"
	_skip_ui.layer = 5
	add_child(_skip_ui)
	var host := Control.new()
	host.name = "SkipRoot"
	host.set_anchors_preset(Control.PRESET_FULL_RECT)
	host.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_skip_ui.add_child(host)
	var tex := load(SKIP_TEX) as Texture2D
	_skip_btn = TextureButton.new()
	_skip_btn.name = "Skip"
	_skip_btn.texture_normal = tex
	_skip_btn.ignore_texture_size = true
	_skip_btn.stretch_mode = TextureButton.STRETCH_KEEP_ASPECT_CENTERED
	_skip_btn.focus_mode = Control.FOCUS_NONE
	var sz := Vector2(84, 92)                     # 和房间左上角那枚同尺寸
	_skip_btn.size = sz
	var vp := get_viewport_rect().size
	_skip_btn.position = Vector2(vp.x - sz.x - 22.0, 16.0)
	_skip_btn.pressed.connect(_go_back)
	host.add_child(_skip_btn)


# 刚拖过（平移镜头）→ 这一下不算点按，别顺手放大一张卡
func _tap_blocked() -> bool:
	if _cam == null:
		return false
	var t = _cam.get("tap_blocked_until")
	return t != null and Time.get_ticks_msec() < int(t)


func _on_card_pressed(card: TextureButton) -> void:
	if _open or card.texture_normal == null:
		return
	if _tap_blocked():
		return
	_open = true
	if _skip_btn != null and is_instance_valid(_skip_btn):
		_skip_btn.visible = false                 # 放大态：藏起来，别挡「点空白退出」
	_card = card

	# 放大卡：像素尺寸对齐原图，pivot 放中心
	_big.texture = card.texture_normal
	_big.size = card.texture_normal.get_size()
	_big.pivot_offset = _big.size * 0.5
	_big.visible = true

	# 起点 = 卡片此刻在屏幕上的位置/尺寸；终点 = 屏幕正中、1:1
	var vp := get_viewport_rect().size
	var start_scale := _card_screen_size(card) / _big.size
	var start_pos := _big_pos_for_center(_card_screen_center(card))
	var end_pos := _big_pos_for_center(vp * 0.5)

	# 把整条曲线写进关键帧：position / scale 共用同一条 ease-out 采样，
	# 否则位移会瞬间到终点（key1..5 都是终点值），跟缩放割裂。
	var a := _ap.get_animation(ANIM_ZOOM)
	var n := a.track_get_key_count(0)
	for i in range(n):
		var p := 1.0
		if i < EASE_OUT.size():
			p = float(EASE_OUT[i])
		a.track_set_key_value(0, i, start_pos.lerp(end_pos, p))          # 放大卡:position
		a.track_set_key_value(1, i, start_scale.lerp(Vector2.ONE, p))     # 放大卡:scale
	_ap.speed_scale = 1.0
	_ap.play(ANIM_ZOOM)


func _input(e: InputEvent) -> void:
	if e is InputEventKey and (e as InputEventKey).pressed and (e as InputEventKey).keycode == KEY_ESCAPE:
		if not _open:                      # 没在放大 → ESC 倒放转场回一级
			_go_back()
		get_viewport().set_input_as_handled()
		return
	if e is InputEventMouseButton and (e as InputEventMouseButton).pressed \
			and (e as InputEventMouseButton).button_index == MOUSE_BUTTON_RIGHT:
		_close()
		get_viewport().set_input_as_handled()
		return
	# 左键 / 触屏 tap（用户口径 2026-11-15）：**放大态点放大卡以外 = 缩回**；
	# 网格态点空白什么都不做（返回靠右上角「跳过」/ ESC / 安卓返回键）。
	# ★ 放大态点空白缩回：改在**抬手**时判定（按下就关的话，想拖动会先被关掉）
	if e is InputEventMouseButton and not (e as InputEventMouseButton).pressed \
			and (e as InputEventMouseButton).button_index == MOUSE_BUTTON_LEFT:
		if _open and not _tap_blocked():
			var mp := (e as InputEventMouseButton).position
			if not _big.get_global_rect().has_point(mp):
				_close()
				get_viewport().set_input_as_handled()



## ESC：用转场动画的「倒放」退回一级菜单（蒙版 + 角色序列帧都逆着播）
func _go_back() -> void:
	if _leaving:
		return
	_leaving = true
	if _start_ps == null and _start_req:
		var st := ResourceLoader.load_threaded_get_status(START_SCENE)
		while st == ResourceLoader.THREAD_LOAD_IN_PROGRESS:
			await get_tree().process_frame
			st = ResourceLoader.load_threaded_get_status(START_SCENE)
		if st == ResourceLoader.THREAD_LOAD_LOADED:
			_start_ps = ResourceLoader.load_threaded_get(START_SCENE) as PackedScene
	if _start_ps == null:
		_start_ps = load(START_SCENE) as PackedScene
	if _start_ps == null:                  # 实在拿不到就直切
		get_tree().change_scene_to_file.call_deferred(START_SCENE)
		return
	Wipe.run(self, _start_ps, true)


## 右键：播「缩小」（同样是 ease-out 先快后慢，不是把放大倒放 —— 倒放会变成先慢后快）
func _close() -> void:
	if not _open or _card == null:
		return
	var vp := get_viewport_rect().size
	var end_scale := _card_screen_size(_card) / _big.size
	var end_pos := _big_pos_for_center(_card_screen_center(_card))
	var center_pos := _big_pos_for_center(vp * 0.5)
	var a := _ap.get_animation(ANIM_SHRINK)
	var n := a.track_get_key_count(0)
	for i in range(n):
		var p := 1.0
		if i < EASE_OUT.size():
			p = float(EASE_OUT[i])
		a.track_set_key_value(0, i, center_pos.lerp(end_pos, p))        # position: 中心 → 原位
		a.track_set_key_value(1, i, Vector2.ONE.lerp(end_scale, p))     # scale: 1:1 → 卡缩放
	_ap.speed_scale = 1.0
	_ap.play(ANIM_SHRINK)


func _on_anim_finished(nm: String) -> void:
	if nm == ANIM_SHRINK:
		_big.visible = false
		_dim.color.a = 0.0
		_card = null
		_open = false
		if _skip_btn != null and is_instance_valid(_skip_btn):
			_skip_btn.visible = true          # 缩回网格 → 「跳过」按钮回来
	# 放大播完 → 保持放大状态（不做任何收尾）
