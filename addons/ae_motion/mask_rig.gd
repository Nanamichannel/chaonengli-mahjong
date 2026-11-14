extends SubViewport
##
## mask_rig.gd —— 按 AE 蒙版数据逐帧生成遮罩纹理
##
## 由导入器按「蒙版所在图层的名字」创建，放在 `Masks/` 下。
## 默认**不自动播放**，由你在需要的时候指定时间，然后取纹理：
##
##   var m := $Masks/转场遮罩
##   m.set_time(1200)                       # 取第 1.2 秒的蒙版形状
##   mat.set_shader_parameter("mask_tex", m.get_mask_texture())
##
## 需要它自己随时间走的场合，把 autoplay 勾上即可。
##

@export var frames: Array = []          # [[毫秒, [x1,y1,x2,y2,...]], ...] 合成坐标
@export var comp_size := Vector2(1920.0, 1080.0)
@export var autoplay := false
@export var loop := false

var _t := 0.0
var _poly: Polygon2D


func _ready() -> void:
	render_target_update_mode = SubViewport.UPDATE_ALWAYS
	transparent_bg = true
	_ensure_poly()
	set_time(0.0)


func _ensure_poly() -> void:
	if _poly != null and is_instance_valid(_poly):
		return
	_poly = null
	for c in get_children():
		if c is Polygon2D:
			_poly = c
			break
	if _poly == null:
		_poly = Polygon2D.new()
		_poly.name = "MaskPoly"
		add_child(_poly)
	_poly.color = Color(1, 1, 1, 1)


## 把蒙版定位到指定毫秒
func set_time(ms: float) -> void:
	_ensure_poly()
	if frames.is_empty():
		return
	var current: Array = frames[0]
	for f in frames:
		if float(f[0]) <= ms:
			current = f
		else:
			break
	var src: Array = current[1]
	var k := Vector2(float(size.x), float(size.y)) / comp_size
	var pts := PackedVector2Array()
	for i in range(src.size()):
		pts.append(Vector2(float(src[i][0]), float(src[i][1])) * k)
	_poly.polygon = pts


## 拿到遮罩纹理（ViewportTexture），直接喂给 mask_tex 着色器
func get_mask_texture() -> Texture2D:
	return get_texture()


## 蒙版总时长（毫秒）
func duration_ms() -> float:
	if frames.is_empty():
		return 0.0
	return float(frames[frames.size() - 1][0])


func _process(delta: float) -> void:
	if not autoplay or frames.is_empty():
		return
	_t += delta * 1000.0
	var total := duration_ms()
	if total > 0.0 and _t > total:
		_t = fmod(_t, total) if loop else total
	set_time(_t)
