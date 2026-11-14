@tool
extends EditorScript
##
## ae_importer.gd —— 读 ae-motion/1 JSON，生成骨架场景 + AnimationPlayer。
##
## 用法：
##   1. 改下面三行常量
##   2. 打开本脚本，按 Ctrl+Shift+X（或脚本编辑器右上角 ▶）
##   3. 打开输出面板看汇总
##
## 生成物不要手改，重跑会整个覆盖。交互脚本请写在包装场景里。
##

# ---------------- 改这三行 ----------------
const JSON_DIR := "N:/媒体/AfterEffects/AE-Motion-Export"
const JSON_PATH := ""   # 留空 = 自动用 JSON_DIR 里最新的那个 json
const ART_DIR := "res://Cailiao/UI/开始界面"
const OUT_SCENE := "res://generated/真初始场景.tscn"
# ------------------------------------------

const ANIM_NAME := "play"

var _by_index := {}      # int -> Dictionary
var _nodes := {}         # int -> Node2D
var _layer_list := []
var _root: Node2D
var _missing := []


func _run() -> void:
	var json_path: String = JSON_PATH
	if json_path == "":
		json_path = _latest_json(JSON_DIR)
		if json_path == "":
			push_error("" + JSON_DIR + " 里没有 json")
			return
		print("读取：" + json_path)

	if not FileAccess.file_exists(json_path):
		push_error("找不到 JSON：" + json_path)
		return

	var f := FileAccess.open(json_path, FileAccess.READ)
	var text := f.get_as_text()
	f.close()

	var data = JSON.parse_string(text)
	if typeof(data) != TYPE_DICTIONARY:
		push_error("JSON 解析失败：" + json_path)
		return

	_by_index.clear()
	_nodes.clear()
	_missing.clear()
	_layer_list = data.get("layers", [])

	for L in _layer_list:
		_by_index[int(L["index"])] = L

	var comp: Dictionary = data.get("comp", data["clip"].get("comp", {}))
	_root = Node2D.new()
	_root.name = _base_name(String(data["clip"]["name"]))

	# 从最底层往上建，父子关系沿途递归补建
	var sorted: Array = _layer_list.duplicate()
	sorted.sort_custom(func(a, b): return int(a["z"]) > int(b["z"]))
	for L in sorted:
		_node_for(int(L["index"]))

	var stats := _build_animation(data)

	print("========== ae-motion 导入完成 ==========")
	print("合成：%s  %sx%s  %.2fs" % [
		String(data["clip"]["name"]),
		str(comp.get("width", "?")), str(comp.get("height", "?")),
		float(data["clip"].get("length", 0.0))
	])
	print("图层：%d 个，动画层 %d 个，轨道 %d 条，关键帧 %d 个" % [
		_layer_list.size(), stats[0], stats[1], stats[2]
	])
	print("输出：" + OUT_SCENE)
	if _missing.size() > 0:
		print("缺贴图（%d 张）：%s" % [_missing.size(), ", ".join(PackedStringArray(_missing))])
		push_warning("有贴图没找到，对应图层会是空白。检查 ART_DIR 和文件名。")
	else:
		print("贴图：全部找到")
	print("逐层：")
	for L in _layer_list:
		var n = _nodes.get(int(L["index"]))
		var path: String = "-" if n == null else String(_root.get_path_to(n))
		var mark: String = "缺"
		if String(L.get("type", "")) == "null":
			mark = "空对象"
		elif n is Sprite2D and (n as Sprite2D).texture != null:
			mark = "有图"
		print("  z=" + str(int(L["z"])) + "  " + String(L["name"]) + "  -> " + path + "  [" + mark + "]")
	print("=======================================")
	_save(data)


func _latest_json(dir_path: String) -> String:
	var best := ""
	var best_time := -1
	var d := DirAccess.open(dir_path)
	if d == null:
		return ""
	d.list_dir_begin()
	var f := d.get_next()
	while f != "":
		if not d.current_is_dir() and f.get_extension().to_lower() == "json":
			var ft := FileAccess.get_modified_time(dir_path.path_join(f))
			if ft > best_time:
				best_time = ft
				best = dir_path.path_join(f)
		f = d.get_next()
	d.list_dir_end()
	return best


func _node_for(idx: int) -> Node2D:
	if _nodes.has(idx):
		return _nodes[idx]

	var L: Dictionary = _by_index[idx]
	var n: Node2D

	if String(L.get("type", "image")) == "null":
		n = Node2D.new()
		n.z_index = -int(L["z"])
	else:
		var sp := Sprite2D.new()
		sp.centered = false
		sp.texture = _texture_for(L)
		sp.z_index = -int(L["z"])

		var asset: Dictionary = L["asset"]
		var anchor: Array = asset["anchor"]
		var wj := float(asset["width"])
		var hj := float(asset["height"])
		var tex_size := Vector2(wj, hj)
		if sp.texture != null:
			tex_size = sp.texture.get_size()
		# left/top 通常为 0；PNG 被裁小时自动修正
		sp.offset = -(Vector2(float(anchor[0]), float(anchor[1])) - (Vector2(wj, hj) - tex_size))
		n = sp

	# 静态值：位置/旋转/缩放/透明度（动画层的轨道会覆盖它们）
	var p0: Array = L["tracks"]["position"][0]
	n.position = Vector2(float(p0[1]), float(p0[2]))
	var r0: Array = L["tracks"]["rotation"][0]
	n.rotation = deg_to_rad(float(r0[1]))
	var s0: Array = L["tracks"]["scale"][0]
	n.scale = Vector2(float(s0[1]), float(s0[2]))
	if n is Sprite2D:
		var a0: Array = L["tracks"]["alpha"][0]
		(n as Sprite2D).self_modulate = Color(1.0, 1.0, 1.0, float(a0[1]))

	n.name = _base_name(String(L["name"]))
	_nodes[idx] = n

	var pid = L.get("parent")
	if pid != null and int(pid) > 0:
		var p := _node_for(int(pid))
		p.add_child(n)
		n.name = _unique_name(p, String(n.name), n)
	else:
		_root.add_child(n)
		n.name = _unique_name(_root, String(n.name), n)

	return n


func _texture_for(L: Dictionary) -> Texture2D:
	var want := _norm(_base_name(String(L["name"])))
	var want_src := _norm(_base_name(String(L["asset"].get("source", ""))))

	var dir := DirAccess.open(ART_DIR)
	if dir != null:
		dir.list_dir_begin()
		var f := dir.get_next()
		while f != "":
			if not dir.current_is_dir() and f.get_extension().to_lower() == "png":
				var base := f.get_basename()
				var tail := base.get_slice("_", base.get_slice_count("_") - 1)
				var k1 := _norm(tail)
				var k2 := _norm(base)
				if k1 == want or k2 == want or (want_src != "" and (k1 == want_src or k2 == want_src)):
					var path := ART_DIR.path_join(f)
					var t = load(path)
					if t is Texture2D:
						dir.list_dir_end()
						return t as Texture2D
			f = dir.get_next()
		dir.list_dir_end()

	_missing.append(_base_name(String(L["name"])))
	return null


func _norm(s: String) -> String:
	var out := s.to_lower()
	for ch in [" ", "-", "_", ".", "(", ")", "（", "）"]:
		out = out.replace(ch, "")
	return out



func _base_name(raw: String) -> String:
	var nm := raw.get_slice("/", 0)
	nm = nm.get_basename()
	for ch in [".", ":", "@", "\"", "%", "\n", "\r", "\t"]:
		nm = nm.replace(ch, "_")
	nm = nm.strip_edges()
	if nm == "":
		nm = "layer"
	return nm


func _unique_name(parent: Node, base: String, self_node: Node) -> String:
	var nm := base
	var i := 2
	while true:
		var existing := parent.get_node_or_null(NodePath(nm))
		if existing == null or existing == self_node:
			return nm
		nm = "%s_%d" % [base, i]
		i += 1
	return nm


func _varies(track: Array, dims: int) -> bool:
	if track.size() <= 1:
		return false
	var first: Array = track[0]
	for i in range(1, track.size()):
		var row: Array = track[i]
		for d in range(1, dims):
			if absf(float(row[d]) - float(first[d])) > 0.0005:
				return true
	return false


func _build_animation(data: Dictionary) -> Array:
	var ap := AnimationPlayer.new()
	ap.name = "AnimationPlayer"
	_root.add_child(ap)

	var anim := Animation.new()
	anim.length = float(data["clip"].get("length", 0.0))
	var lib := AnimationLibrary.new()
	lib.add_animation(ANIM_NAME, anim)
	ap.add_animation_library("", lib)
	ap.root_node = NodePath("..")
	ap.autoplay = ANIM_NAME

	var animated := 0
	var tracks := 0
	var keys := 0

	for L in _layer_list:
		if bool(L.get("isStatic", true)):
			continue
		var n = _nodes.get(int(L["index"]))
		if n == null:
			continue
		animated += 1
		var rel := String(_root.get_path_to(n))
		var tk: Dictionary = L["tracks"]

		if _varies(tk["position"], 3):
			var t1 := anim.add_track(Animation.TYPE_VALUE)
			anim.track_set_path(t1, NodePath(rel + ":position"))
			anim.track_set_interpolation_type(t1, Animation.INTERPOLATION_LINEAR)
			for s in tk["position"]:
				anim.track_insert_key(t1, float(s[0]) / 1000.0, Vector2(float(s[1]), float(s[2])))
				keys += 1
			tracks += 1

		if _varies(tk["rotation"], 2):
			var t2 := anim.add_track(Animation.TYPE_VALUE)
			anim.track_set_path(t2, NodePath(rel + ":rotation"))
			anim.track_set_interpolation_type(t2, Animation.INTERPOLATION_LINEAR)
			for s in tk["rotation"]:
				anim.track_insert_key(t2, float(s[0]) / 1000.0, deg_to_rad(float(s[1])))
				keys += 1
			tracks += 1

		if _varies(tk["scale"], 3):
			var t3 := anim.add_track(Animation.TYPE_VALUE)
			anim.track_set_path(t3, NodePath(rel + ":scale"))
			anim.track_set_interpolation_type(t3, Animation.INTERPOLATION_LINEAR)
			for s in tk["scale"]:
				anim.track_insert_key(t3, float(s[0]) / 1000.0, Vector2(float(s[1]), float(s[2])))
				keys += 1
			tracks += 1

		if _varies(tk["alpha"], 2):
			var t4 := anim.add_track(Animation.TYPE_VALUE)
			anim.track_set_path(t4, NodePath(rel + ":self_modulate:a"))
			anim.track_set_interpolation_type(t4, Animation.INTERPOLATION_LINEAR)
			for s in tk["alpha"]:
				anim.track_insert_key(t4, float(s[0]) / 1000.0, float(s[1]))
				keys += 1
			tracks += 1

	return [animated, tracks, keys]


func _save(data: Dictionary) -> void:
	_set_owner(_root, _root)
	var ps := PackedScene.new()
	var err := ps.pack(_root)
	if err != OK:
		push_error("打包场景失败：%d" % err)
		return

	var dir := OUT_SCENE.get_base_dir()
	if not DirAccess.dir_exists_absolute(dir):
		DirAccess.make_dir_recursive_absolute(dir)

	var err2 := ResourceSaver.save(ps, OUT_SCENE)
	if err2 != OK:
		push_error("保存场景失败：%d" % err2)
		return

	_root.free()


func _set_owner(n: Node, owner_root: Node) -> void:
	for c in n.get_children():
		c.owner = owner_root
		_set_owner(c, owner_root)
