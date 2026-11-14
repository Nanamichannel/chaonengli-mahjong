extends CanvasItem
##
## mask_apply.gd —— 把 mask_rig 的遮罩纹理接到自己身上
##
## 挂在要被裁的图层上（通常是"上一屏"的 Sprite2D）：
##   1. material 设成 mask_tex.gdshader 的 ShaderMaterial
##   2. mask_viewport 指向 mask_rig 所在的 SubViewport
##

@export var mask_viewport: NodePath
@export var invert := false

var _vp: SubViewport


func _ready() -> void:
	if mask_viewport.is_empty():
		return
	_vp = get_node_or_null(mask_viewport) as SubViewport
	if _vp == null:
		push_warning("mask_apply: 找不到 SubViewport " + String(mask_viewport))
		return
	_bind()


func _bind() -> void:
	var mat := material as ShaderMaterial
	if mat == null:
		push_warning("mask_apply: 本节点的 material 不是 ShaderMaterial")
		return
	mat.set_shader_parameter("mask_tex", _vp.get_texture())
	mat.set_shader_parameter("invert", invert)
