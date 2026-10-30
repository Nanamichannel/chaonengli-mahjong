extends RefCounted

# ─────────────────────────────────────────────────────────────────────────────
# 统一「选中框」：不再用黄框贴图，改成自绘的彩虹描边（res://sel_frame_item.gd）。
#
#   attach()  → 在 parent 上挂一个框，返回 Node2D（旧代码里的 Sprite2D 用法已同步改掉）
#   fit()     → 目标尺寸变了（换形态 / 缩放）时重新贴合
#
# 选中时：彩色线条沿边框跑一圈 → 常亮 + 轻微呼吸。常亮状态不逐帧重绘。
#
# ★ 位置/外观调整接口（全局默认值，改这里即可）：
#     INSET         边线往里缩（像素，正数=缩）
#     OFFSET        整体平移（像素，正数=右/下）
#     LINE_WIDTH    线宽
#     CORNER_RADIUS 圆角
#     BREATH        常亮后要不要呼吸
# 单个框想单独调：attach() 之后直接改 node 的 inset / offset / line_width 再 refresh()。
# ─────────────────────────────────────────────────────────────────────────────

const TEX_YELLOW := "res://Cailiao/skill/ui/frame_yellow.png"   # 旧贴图，仅为兼容旧调用保留
const FRAME_SCRIPT := preload("res://sel_frame_item.gd")

const INSET := 0.0
const OFFSET := Vector2.ZERO
const LINE_WIDTH := 3.0
const CORNER_RADIUS := 9.0
const BREATH := true


# 在 parent 上挂一个选中框；size = 要框住的显示尺寸。
# parent 是 Node2D（牌）时以原点为中心，是 Control（按钮）时按左上角 + size 自行居中。
static func attach(parent: Node, size: Vector2, tex_path := TEX_YELLOW,
		tint := Color(1, 1, 1, 1), shown := false, z := 5) -> Node2D:
	if parent == null:
		return null
	var s := Node2D.new()
	s.name = "SelFrame"
	s.set_script(FRAME_SCRIPT)
	s.z_index = z
	s.modulate = tint
	s.set("frame_size", size)
	s.set("inset", INSET)
	s.set("offset", OFFSET)
	s.set("line_width", LINE_WIDTH)
	s.set("corner_radius", CORNER_RADIUS)
	s.set("breath", BREATH)
	s.position = size * 0.5 if parent is Control else Vector2.ZERO
	parent.add_child(s)
	fit(s, size)
	s.visible = shown
	return s


# 框的尺寸贴合：换牌形态 / 动画缩放后调用
static func fit(s: Node2D, size: Vector2) -> void:
	if s == null or not is_instance_valid(s):
		return
	if size.x <= 0.0 or size.y <= 0.0:
		return
	s.set("frame_size", size)
	if s.get_parent() is Control:
		s.position = size * 0.5
	if s.has_method("refresh"):
		s.call("refresh")
