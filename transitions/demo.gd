extends Control
##
## demo.gd —— 独立演示：真初始场景 → 鉴赏，用我自己抠的 alpha 做揭开
##
## 不注册 autoload、不碰任何已有场景；只在演示场景里跑。
##

const SRC_SCENE := "res://真初始场景.tscn"
const DST_SCENE := "res://鉴赏.tscn"
const MASK_DIR := "res://transitions/masks"
const CLIP_DIR := "res://transitions/clip"
const DURATION := 1.25

var _mask_tex: Array[Texture2D] = []
var _clip_tex: Array[Texture2D] = []
var _layer: CanvasLayer
var _snap: TextureRect
var _clip: TextureRect
var _mat: ShaderMaterial
var _busy := false
var _t := 0.0
var _phase := 0
var _shot := 0


func _ready() -> void:
	_load_tex()
	var ps := load(SRC_SCENE) as PackedScene
	if ps:
		add_child(ps.instantiate())
	print("[demo] 素材 蒙版=%d 片段=%d" % [_mask_tex.size(), _clip_tex.size()])


func _load_tex() -> void:
	# 导出包里目录枚举不可靠，直接按编号加载
	var arr_m: Array[Texture2D] = []
	var arr_c: Array[Texture2D] = []
	for i in range(30):
		var m := load("res://transitions/masks/mask_%03d.png" % i)
		if m is Texture2D:
			arr_m.append(m)
		var c := load("res://transitions/clip/clip_%03d.png" % i)
		if c is Texture2D:
			arr_c.append(c)
	_mask_tex = arr_m
	_clip_tex = arr_c


func _input(event: InputEvent) -> void:
	if _busy:
		return
	if event is InputEventMouseButton and event.pressed:
		_play()
	elif event is InputEventKey and event.pressed and not event.echo:
		_play()


func _play() -> void:
	_busy = true
	var img := get_viewport().get_texture().get_image()
	var snap := ImageTexture.create_from_image(img)

	_layer = CanvasLayer.new()
	_layer.layer = 128
	get_tree().root.add_child(_layer)

	_snap = TextureRect.new()
	_snap.texture = snap
	_snap.set_anchors_preset(Control.PRESET_FULL_RECT)
	_snap.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_mat = ShaderMaterial.new()
	_mat.shader = load("res://transitions/wipe.gdshader")
	_snap.material = _mat
	_layer.add_child(_snap)

	# 动漫片段本身作为过渡画面，叠在快照之上、新场景之下
	_clip = TextureRect.new()
	_clip.set_anchors_preset(Control.PRESET_FULL_RECT)
	_clip.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_clip.modulate.a = 0.0
	_layer.add_child(_clip)
	_layer.move_child(_clip, 0)

	get_tree().change_scene_to_file(DST_SCENE)
	await get_tree().process_frame
	await get_tree().process_frame

	var n := _mask_tex.size()
	var c := _clip_tex.size()
	var t := 0.0
	while t < DURATION:
		t += get_process_delta_time()
		var p := clampf(t / DURATION, 0.0, 1.0)
		if n > 0:
			_mat.set_shader_parameter("mask_tex", _mask_tex[mini(int(p * (n - 1)), n - 1)])
		if c > 0:
			_clip.texture = _clip_tex[mini(int(p * (c - 1)), c - 1)]
			# 片段淡入淡出：0→0.35 淡入，0.6 之后快速淡出
			_clip.modulate.a = clampf(minf(p / 0.15, (0.72 - p) / 0.12), 0.0, 1.0)
		await get_tree().process_frame

	if _layer and is_instance_valid(_layer):
		_layer.queue_free()
	_layer = null
	_busy = false
