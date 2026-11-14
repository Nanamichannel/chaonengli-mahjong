extends Node
##
## 「只差遮罩」通用转场 —— 正向 / 倒放都能用，两个场景共用一份实现。
##
##   TransitionWipe.run(self, packed_scene, false)   # 正向：蒙版擦掉旧画面，露出新场景
##   TransitionWipe.run(self, packed_scene, true)    # 倒放：时间倒走 + 擦除方向反过来
##                                                  #       （蒙版和角色序列帧都逆着播）
##
## 结构（全部塞进一个 CanvasLayer，layer=80，避免被场景里的 Camera2D 影响）：
##   最下层 = 目标场景的预览实例（结束时直接「转正」成 current_scene，零画面跳变）
##   中间   = 旧画面截图 + 蒙版擦除着色器
##   最上层 = 转场角色序列帧（51 帧 / 800ms，与蒙版同一条时间轴）
##
## 蒙版数据不在这里写死：从「预览实例」或「当前场景」里的
## `只差遮罩/Masks/鉴赏蒙版`（mask_rig.gd）+ `只差遮罩/转场_[00000-00025]`（SpriteFrames）现取，
## 所以以后重导素材不需要动这个脚本。

const MASK_PATH := "只差遮罩/Masks/鉴赏蒙版"
const SEQ_PATH := "只差遮罩/转场_[00000-00025]"
const LAYER_INDEX := 80

## 擦除着色器：m = 蒙版纹理的 alpha（1 = 蒙版已经扫过这里）
##   invert=0（正向）→ 擦掉多边形内部，露出下面的新场景
##   invert=1（倒放）→ 保留多边形内部、擦掉外部，新场景从上一遍的终点边界退回
const WIPE_SHADER := """
shader_type canvas_item;
uniform sampler2D mask_tex : filter_linear, repeat_disable;
uniform float invert = 0.0;
void fragment() {
	vec4 c = texture(TEXTURE, UV);
	float m = texture(mask_tex, UV).a;
	float keep = mix(1.0 - m, m, invert);
	COLOR = vec4(c.rgb, c.a * keep);
}
"""

static var _busy := false

var reverse := false

var _layer: CanvasLayer = null
var _shot: Sprite2D = null
var _seq: AnimatedSprite2D = null
var _rig: Node = null
var _wrap: Node = null
var _preview: Node = null
var _old: Node = null
var _total := 0.0
var _nframes := 1
var _t := 0.0
var _done := false
var _wrap_was_visible := true


## 唯一入口。caller 用任意「当前场景里」的节点即可；next_ps = 要去的场景。
static func run(caller: Node, next_ps: PackedScene, rev: bool) -> void:
	if caller == null or not caller.is_inside_tree():
		return
	if _busy:
		return
	if next_ps == null:
		return
	_busy = true
	var w: Node = (load("res://transition_wipe.gd") as GDScript).new()
	w.set("reverse", rev)
	caller.get_tree().root.add_child(w)
	w.call("start", next_ps)


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	set_process(false)


func start(next_ps: PackedScene) -> void:
	_old = get_tree().current_scene

	# ① 先截旧画面（此刻目标场景还没进树）
	var img: Image = get_viewport().get_texture().get_image()
	var design: Vector2 = get_viewport().get_visible_rect().size
	var ipx := Vector2(float(img.get_width()), float(img.get_height()))

	# ② 实例化目标场景（先不进树，只为拿它的蒙版 / 序列帧数据）
	_preview = next_ps.instantiate()
	var packed := _pick_data(_preview)
	if packed[1] == null:
		packed = _pick_data(_old)
	var rig: Node = packed[1]
	var seq_src: Node = packed[2]
	if rig == null or seq_src == null or seq_src.sprite_frames == null:
		_finish()                          # 没有转场素材 → 直接转正，等价于瞬时切场景
		return
	_rig = rig
	_wrap = packed[0]
	var frames: Array = rig.get("frames")
	if frames == null or frames.is_empty():
		_finish()
		return
	_total = float(frames[frames.size() - 1][0])
	var seq_frames: SpriteFrames = seq_src.sprite_frames
	_nframes = maxi(seq_frames.get_frame_count("default"), 1)

	# ③ 转场层
	_layer = CanvasLayer.new()
	_layer.name = "TransitionLayer"
	_layer.layer = LAYER_INDEX
	add_child(_layer)

	_layer.add_child(_preview)

	# ④ 旧画面截图 + 蒙版擦除（截图是窗口像素，画布是设计分辨率 → 按比例铺满）
	_shot = Sprite2D.new()
	_shot.centered = false
	_shot.texture = ImageTexture.create_from_image(img)
	if ipx.x > 1.0 and ipx.y > 1.0:
		_shot.scale = Vector2(design.x / ipx.x, design.y / ipx.y)
	_shot.z_index = 1
	if _wrap != null:
		_wrap_was_visible = _wrap.visible
		_wrap.visible = true                  # SubViewport 要被渲染，蒙版纹理才是最新的
	var sh := Shader.new()
	sh.code = WIPE_SHADER
	var mat := ShaderMaterial.new()
	mat.shader = sh
	mat.set_shader_parameter("mask_tex", rig.get_texture())
	mat.set_shader_parameter("invert", 1.0 if reverse else 0.0)
	_shot.material = mat
	_layer.add_child(_shot)

	# ⑤ 最上层：角色序列帧（帧号自己按进度写，不用 play）
	_seq = AnimatedSprite2D.new()
	_seq.centered = false
	_seq.sprite_frames = seq_frames
	_seq.z_index = 2
	_layer.add_child(_seq)
	_seq.frame = (_nframes - 1) if reverse else 0

	_rig.set_time(_total if reverse else 0.0)
	_t = 0.0
	_done = false
	set_process(true)


func _pick_data(n: Node) -> Array:
	if n == null:
		return [null, null, null]
	var wrap := n.get_node_or_null(NodePath("只差遮罩"))
	if wrap == null:
		return [null, null, null]
	var rig := n.get_node_or_null(NodePath(MASK_PATH))
	var seq_src := n.get_node_or_null(NodePath(SEQ_PATH))
	if rig == null or seq_src == null:
		return [wrap, rig, seq_src]
	return [wrap, rig, seq_src]


func _process(delta: float) -> void:
	if _done or _rig == null or not is_instance_valid(_rig):
		return
	_t += delta * 1000.0
	var p := 1.0
	if _total > 0.0:
		p = clampf(_t / _total, 0.0, 1.0)
	var q := (1.0 - p) if reverse else p
	_rig.set_time(_total * q)
	if _seq != null and is_instance_valid(_seq):
		_seq.frame = clampi(int(round(q * float(_nframes - 1))), 0, _nframes - 1)
	if p >= 1.0:
		_finish()


## 收尾：把预览实例转正成 current_scene，释放旧场景 / 转场层 / 本节点
func _finish() -> void:
	if _done:
		return
	_done = true
	set_process(false)
	_busy = false
	if _rig != null and is_instance_valid(_rig):
		_rig.set_time(0.0 if reverse else _total)
	if _wrap != null and is_instance_valid(_wrap) and not _wrap_was_visible:
		_wrap.visible = false
	if _preview != null and is_instance_valid(_preview):
		if _layer != null and is_instance_valid(_layer):
			_layer.remove_child(_preview)
		get_tree().root.add_child(_preview)
		get_tree().current_scene = _preview
	if _old != null and is_instance_valid(_old) and _old != _preview:
		_old.queue_free()
	if _layer != null and is_instance_valid(_layer):
		_layer.queue_free()
		_layer = null
	queue_free()
