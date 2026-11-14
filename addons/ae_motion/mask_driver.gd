extends Node
##
## mask_driver.gd —— 把 AE 导出的逐帧蒙版多边形写进着色器
##
## AnimationPlayer 没法驱动着色器 uniform，所以用这个小节点每帧写一次。
## 由导入器自动创建，也可以手动挂到任意节点上。
##
## 用法：
##   1. 把要裁的图层（比如"上一屏"的 Sprite2D）的 material 设成
##      mask_screen.gdshader 的 ShaderMaterial
##   2. 本节点的 target_path 指向那个 Sprite2D
##   3. 本节点的 frames 由导入器写好，或者手动填
##      [[毫秒, [x1,y1,x2,y2,...]], ...]
##
## 多个蒙版时用 paths 数组，每个元素是一组同结构的数据，会依次写入 target 上的
## 多个材质（target_paths）。
##

@export var target_path: NodePath
@export var frames: Array = []          # 合成坐标的点（来自 json 的 compFrames）
@export var comp_size := Vector2(1920.0, 1080.0)
@export var loop := false

var _t := 0.0
var _target: CanvasItem


func _ready() -> void:
	_target = get_node_or_null(target_path) as CanvasItem
	if _target == null:
		# 没指定就退回到父节点
		_target = get_parent() as CanvasItem
	_apply(0.0)


func _process(delta: float) -> void:
	if frames.is_empty():
		return
	_t += delta * 1000.0
	var total := float(frames[frames.size() - 1][0])
	if _t > total:
		if loop:
			_t = fmod(_t, maxf(total, 1.0))
		else:
			_t = total
	_apply(_t)


func _apply(ms: float) -> void:
	if _target == null or frames.is_empty():
		return
	var mat := _target.material as ShaderMaterial
	if mat == null:
		return

	# 找当前帧（取最近的一条）
	var current: Array = frames[0]
	for f in frames:
		if float(f[0]) <= ms:
			current = f
		else:
			break

	var pts_arr: Array = current[1]
	var packed := PackedVector2Array()
	var max_pts := 512
	for i in range(pts_arr.size()):
		if packed.size() >= max_pts:
			break
		packed.append(Vector2(float(pts_arr[i][0]), float(pts_arr[i][1])))
	mat.set_shader_parameter("points", packed)
	mat.set_shader_parameter("count", packed.size())
	mat.set_shader_parameter("comp_size", comp_size)
