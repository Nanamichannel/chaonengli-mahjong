extends RefCounted

# ══════════════════════════════════════════════════════════════════════
#  外部皮肤：不用重导 exe 就能换图
#
#  找图顺序：
#    ① <游戏 exe 同目录>\skin\<名字>
#    ② %APPDATA%\Godot\app_userdata\Tianma\skin\<名字>   （编辑器调试用 user://skin）
#  两个地方都没有 → 用 pck 里的原图（和以前一模一样）。
#
#  想加别的图：在下面的 MAP 里加一行「文件名 → 原图 res 路径」就行，
#  代码不用动第二遍（但每加一行要重导一次 exe；之后换图就不用再导了）。
#
#  关于尺寸：全屏背景按「cover」等比裁切（不变形，边角会被切掉）；
#           其他按钮一律缩放到原图尺寸（布局绝对不会跑位）。
# ══════════════════════════════════════════════════════════════════════

const MAP := {
	# 牌桌背景不在这里管：main.gd 的 _load_background() 会读 skin/bg.png
	"menu.png":  "res://Cailiao/UI/初始界面.png",             # 初始菜单背景
	"start.png": "res://Cailiao/UI/tiaoguo.png",             # 「开始 / 跳过」按钮
	"chi.png":   "res://Cailiao/UI/chi.png",                 # 吃
	"peng.png":  "res://Cailiao/UI/peng.png",                # 碰
	"gang.png":  "res://Cailiao/UI/gang.png",                # 杠
	"rong.png":  "res://Cailiao/UI/rong.png",                # 荣和
	"zimo.png":  "res://Cailiao/UI/zimo.png",                # 自摸
	"lizhi.png": "res://Cailiao/UI/lizhi.png",               # 立直
}

# 这两张是全屏背景 → 用 cover 裁切；其余按原尺寸拉伸
const COVER_NAMES := ["bg.png", "menu.png"]

# 贴图所在的属性名（TextureRect / TextureButton / Sprite2D 各不一样）
const TEX_PROPS := ["texture", "texture_normal", "texture_hover",
	"texture_pressed", "texture_disabled", "texture_focused"]

static var _ov := {}             # 原图 res 路径 → 外部贴图
static var _setup_done := false


# 启动时调一次：扫文件、准备替换表（没有外部图时什么都不做，零开销）
static func setup() -> void:
	if _setup_done:
		return
	_setup_done = true
	var dirs := [
		OS.get_executable_path().get_base_dir().path_join("skin"),
		ProjectSettings.globalize_path("user://skin"),
	]
	for out_name in MAP:
		var res_path := String(MAP[out_name])
		var src := _find(dirs, String(out_name))
		if src == "":
			continue
		var t := _load_tex(src, res_path, COVER_NAMES.has(String(out_name)))
		if t != null:
			_ov[res_path] = t
			print("[skin] %s ← %s" % [out_name, src])
	if not _ov.is_empty():
		print("[skin] 外部皮肤生效：%d 张（同目录 skin\\ 或 user://skin）" % _ov.size())


static func has_override() -> bool:
	return not _ov.is_empty()


static func _find(dirs: Array, name: String) -> String:
	for d in dirs:
		var p := String(d).path_join(name)
		if FileAccess.file_exists(p):
			return p
	return ""


static func _load_tex(path: String, res_path: String, cover: bool) -> Texture2D:
	var img := Image.load_from_file(path)
	if img == null or img.is_empty():
		push_warning("[skin] 读不了这张图：" + path)
		return null
	var orig := load(res_path) as Texture2D
	if orig == null:
		push_warning("[skin] 找不到原图：" + res_path)
		return null
	var want := Vector2i(orig.get_width(), orig.get_height())
	if want.x <= 0 or want.y <= 0:
		return ImageTexture.create_from_image(img)
	if cover:
		# 等比裁切到原图比例（不变形，只切边）
		var dst_ratio := float(want.x) / float(want.y)
		var src_ratio := float(img.get_width()) / float(img.get_height())
		if src_ratio > dst_ratio:
			var w := int(round(float(img.get_height()) * dst_ratio))
			if w > 0 and w < img.get_width():
				img = img.get_region(Rect2i((img.get_width() - w) / 2, 0, w, img.get_height()))
		elif src_ratio < dst_ratio:
			var h := int(round(float(img.get_width()) / dst_ratio))
			if h > 0 and h < img.get_height():
				img = img.get_region(Rect2i(0, (img.get_height() - h) / 2, img.get_width(), h))
	img.resize(want.x, want.y, Image.INTERPOLATE_LANCZOS)
	return ImageTexture.create_from_image(img)


# 把这棵子树里所有「用原图」的节点换成外部图（场景里已有的节点）
static func apply_tree(n: Node) -> void:
	if _ov.is_empty() or n == null:
		return
	_apply(n)
	for c in n.get_children():
		apply_tree(c)


static func _apply(n: Node) -> void:
	if not (n is CanvasItem):
		return
	for prop in TEX_PROPS:
		var t = n.get(prop)
		if t is Texture2D and _ov.has((t as Texture2D).resource_path):
			n.set(prop, _ov[(t as Texture2D).resource_path])


# 运行时新建的节点（各种面板/按钮都是代码现场建的）也要覆盖
static func hook(tree: SceneTree) -> void:
	if _ov.is_empty() or tree == null:
		return
	if not tree.node_added.is_connected(_on_node_added):
		tree.node_added.connect(_on_node_added)


static func _on_node_added(n: Node) -> void:
	if not (n is CanvasItem):
		return
	_apply(n)
	# 代码可能先 add_child 再赋贴图 → 等这一帧过完再查一次
	_apply_later(n)


static func _apply_later(n: Node) -> void:
	await Engine.get_main_loop().process_frame
	if is_instance_valid(n):
		_apply(n)
