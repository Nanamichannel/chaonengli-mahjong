extends Node
##
## transition.gd —— 全局转场（autoload）
##
## 用法（不需要改任何已有场景）：
##   1. 别的脚本里： SceneTransition.start("res://鉴赏.tscn")
##   2. 或者什么都不做：它会在运行时自动找到名字里带「鉴赏」的节点，
##      点它就触发转场
##
## 原理：
##   抓当前画面 → 叠一层全屏快照 → 切场景 → 用遮罩序列把快照擦掉
##

const MASK_DIR := "res://transitions/masks"
const GALLERY_SCENE := "res://鉴赏.tscn"
const DURATION := 1.25
const AUTO_HOOK_NAME := "鉴赏"
## 自动接管默认关闭，避免和你已有的按钮逻辑打架；要用就改成 true
const AUTO_HOOK := true

var _layer: CanvasLayer
var _rect: TextureRect
var _mat: ShaderMaterial
var _masks: Array[Texture2D] = []
var _busy := false
var _hooked := false


func _ready() -> void:
	_load_masks()
	set_process(true)


func _load_masks() -> void:
	_masks.clear()
	var dir := DirAccess.open(MASK_DIR)
	if dir == null:
		push_warning("SceneTransition: 找不到遮罩目录 " + MASK_DIR)
		return
	dir.list_dir_begin()
	var f := dir.get_next()
	var names: Array[String] = []
	while f != "":
		if not dir.current_is_dir() and f.get_extension().to_lower() == "png":
			names.append(f)
		f = dir.get_next()
	dir.list_dir_end()
	names.sort()
	for n in names:
		var tex := load(MASK_DIR.path_join(n))
		if tex is Texture2D:
			_masks.append(tex)


## 外部调用：切到某个场景并播放擦除
func start(target: String = GALLERY_SCENE, duration: float = DURATION) -> void:
	if _busy:
		return
	_busy = true

	var snap := get_viewport().get_texture().get_image()
	var snap_tex := ImageTexture.create_from_image(snap)

	_layer = CanvasLayer.new()
	_layer.layer = 128
	get_tree().root.add_child(_layer)

	_rect = TextureRect.new()
	_rect.texture = snap_tex
	_rect.set_anchors_preset(Control.PRESET_FULL_RECT)
	_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE

	var sh := load("res://transitions/wipe.gdshader") as Shader
	_mat = ShaderMaterial.new()
	_mat.shader = sh
	_rect.material = _mat
	_layer.add_child(_rect)

	get_tree().change_scene_to_file(target)
	await get_tree().process_frame
	await get_tree().process_frame

	# 按遮罩序列推进
	var n := _masks.size()
	if n == 0:
		_cleanup()
		return
	var t := 0.0
	while t < duration:
		t += get_process_delta_time()
		var p := clampf(t / duration, 0.0, 1.0)
		var idx := mini(int(p * float(n - 1)), n - 1)
		_mat.set_shader_parameter("mask_tex", _masks[idx])
		await get_tree().process_frame

	_cleanup()


func _cleanup() -> void:
	if _layer != null and is_instance_valid(_layer):
		_layer.queue_free()
	_layer = null
	_rect = null
	_mat = null
	_busy = false


# ---------------------------------------------------------------- 自动接管
# 找到名字里带「鉴赏」的节点，点它就跑转场。不改原场景，也不接管原本的点击。

func _input(event: InputEvent) -> void:
	# 调试用：按 F9 直接播转场，不用点按钮
	if event is InputEventKey and event.pressed and not event.echo:
		if (event as InputEventKey).keycode == KEY_F9:
			start()
			return
	if not AUTO_HOOK or _busy:
		return
	if not (event is InputEventMouseButton):
		return
	var mb := event as InputEventMouseButton
	if not mb.pressed or mb.button_index != MOUSE_BUTTON_LEFT:
		return
	if _hit_gallery(mb.position):
		start()


func _hit_gallery(pos: Vector2) -> bool:
	var scene := get_tree().current_scene
	if scene == null:
		return false
	for n in scene.find_children("*", "Node2D", true, false):
		if String(n.name).find(AUTO_HOOK_NAME) < 0:
			continue
		if n is Sprite2D:
			var s := n as Sprite2D
			if s.texture == null:
				continue
			var size := s.texture.get_size() * s.global_scale
			var rect := Rect2(s.global_position - size * 0.5, size)
			if rect.has_point(pos):
				return true
	return false
