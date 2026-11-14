@tool
extends RefCounted
##
## ae_builder.gd —— 把 ae-motion/1 JSON 建成场景 + AnimationPlayer。
## 不依赖编辑器，也不依赖任何工程的路径，全部由参数传入。
##
## 图层两种形态：
##   - 普通层：一张 PNG（Sprite2D）
##   - 序列帧层：json 里带 frames 字段（AnimatedSprite2D），像素烘好，
##     位置/层级/时间窗仍然吃 json 的轨道
##

var _by_index := {}
var _nodes := {}
var _layer_list := []
var _root: Node
var _root2d: Node2D
var _root2d_back: Node2D
var _parented2d := {}
var _merge_mode := false
var _autoplay := true
var _world: Node3D
var _cam_node: Camera3D
var _use3d := false
var _white_tex: Texture2D
var _mid_3d_z := 0
var _missing := []
var _missing_frames := []
var _blend_skipped := []
var _mask_skipped := []
var _mask_applied := []
var _mask_drivers := []
var _blend_applied := []
var _heavy_frames := []
var _frames_size_mismatch := []
var _tex_fixed := []
var _lines: PackedStringArray = []
var _art_dir := ""
var _frames_root := ""
var _out_scene := ""
var _fps := 60.0
var _frame_ms := 16.666667
var _comp_size := Vector2(1920, 1080)
var _comp_space_layers := {}


func build(json_path: String, art_dir: String, out_scene: String, frames_dir: String = "", segments_spec: String = "", merge_target: Node = null, autoplay: bool = true) -> Dictionary:
	_by_index.clear()
	_nodes.clear()
	_missing.clear()
	_missing_frames.clear()
	_blend_skipped.clear()
	_mask_skipped.clear()
	_mask_applied.clear()
	_mask_drivers.clear()
	_blend_applied.clear()
	_heavy_frames.clear()
	_frames_size_mismatch.clear()
	_tex_fixed.clear()
	_lines = PackedStringArray()
	_art_dir = art_dir
	_out_scene = out_scene
	_frames_root = frames_dir if frames_dir != "" else art_dir.path_join("Frames")

	if json_path == "" or not FileAccess.file_exists(json_path):
		return _fail("找不到 JSON：" + json_path)
	if art_dir == "" or not DirAccess.dir_exists_absolute(art_dir):
		return _fail("找不到素材目录：" + art_dir)
	if out_scene == "":
		return _fail("还没选输出场景")

	var f := FileAccess.open(json_path, FileAccess.READ)
	var text := f.get_as_text()
	f.close()

	var data = JSON.parse_string(text)
	if typeof(data) != TYPE_DICTIONARY:
		return _fail("JSON 解析失败：" + json_path)

	_layer_list = data.get("layers", [])
	for L in _layer_list:
		_by_index[int(L["index"])] = L
	if _layer_list.is_empty():
		return _fail("JSON 里没有 layers")

	_merge_mode = (merge_target != null)
	_autoplay = true   # 一律自动播放，导入后直接能看到效果
	var clip: Dictionary = data["clip"]
	_fps = float(clip.get("sampleFps", clip.get("fps", 60.0)))
	var segments := _parse_segments(segments_spec, float(clip.get("length", 0.0)))
	for seg in segments:
		if bool(seg["loop"]):
			_lines.append("段 %s：第 %d–%d 帧（%.2fs – %.2fs，循环）" % [seg["name"], int(round(float(seg["start"]) * _fps)), int(round(float(seg["end"]) * _fps)), seg["start"], seg["end"]])
		else:
			_lines.append("段 %s：第 %d–%d 帧（%.2fs – %.2fs，一次性）" % [seg["name"], int(round(float(seg["start"]) * _fps)), int(round(float(seg["end"]) * _fps)), seg["start"], seg["end"]])
	var comp: Dictionary = clip.get("comp", {})
	_comp_size = Vector2(float(comp.get("width", 1920)), float(comp.get("height", 1080)))
	_comp_space_layers.clear()

	_use3d = bool(clip.get("hasCamera", false))
	var zs: Array = []
	for L0 in _layer_list:
		if bool(L0.get("threeD", false)) and int(L0["z"]) > 1:
			zs.append(int(L0["z"]))
	if not zs.is_empty():
		zs.sort()
		_mid_3d_z = int(zs[zs.size() / 2])
	if _use3d:
		# 3D 渲进 SubViewport，再当一张图贴回 2D 画布，
		# 否则 2D 画布永远盖在 3D 上面（Godot 的绘制顺序）
		_root = Node2D.new()
		var screen_layer := CanvasLayer.new()
		screen_layer.name = "3D画面"
		screen_layer.layer = 1
		_root.add_child(screen_layer)
		var holder := SubViewportContainer.new()
		holder.name = "3D容器"
		holder.size = Vector2(_comp_size.x, _comp_size.y)
		holder.stretch = true
		screen_layer.add_child(holder)
		var vp := SubViewport.new()
		vp.name = "3D视口"
		# 遮罩视口用半分辨率：边缘略软，开销降到 1/4
		vp.size = Vector2i(int(_comp_size.x * 0.5), int(_comp_size.y * 0.5))
		vp.transparent_bg = true
		vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
		holder.add_child(vp)
		_world = Node3D.new()
		_world.name = "3D世界"
		vp.add_child(_world)

		var back := CanvasLayer.new()
		back.name = "2D后层"
		back.layer = -1
		_root.add_child(back)
		_parented2d.clear()
		_root2d_back = Node2D.new()
		_root2d_back.name = "Sprites2D后"
		back.add_child(_root2d_back)

		var canvas := CanvasLayer.new()
		canvas.name = "2D层"
		canvas.layer = 2
		_root.add_child(canvas)
		_root2d = Node2D.new()
		_root2d.name = "Sprites2D"
		canvas.add_child(_root2d)
	else:
		_root = Node2D.new()
	_root.name = _base_name(String(clip["name"]))

	var sorted: Array = _layer_list.duplicate()
	sorted.sort_custom(func(a, b): return int(a["z"]) > int(b["z"]))
	for L in sorted:
		_node_for(int(L["index"]))

	_build_mask_drivers()

	var stats: Array
	if _use3d:
		_make_camera3(data)
		stats = _build_animation_3d(data, segments)
	else:
		stats = _build_animation(data, segments)
	var err := OK
	if merge_target != null:
		# 重名就替换掉旧的那份，避免越导越多
		var base_name := String(_root.name)
		var existing := merge_target.get_node_or_null(NodePath(base_name))
		if existing != null:
			merge_target.remove_child(existing)
			existing.queue_free()
			_lines.append("替换了已存在的同名节点：" + base_name)
			_root.name = base_name
		else:
			_root.name = _unique_name(merge_target, _root.name, _root)
		merge_target.add_child(_root)
		var scene_root: Node = merge_target
		while scene_root.owner != null:
			scene_root = scene_root.owner
		_root.owner = scene_root
		_set_owner(_root, scene_root)
	else:
		err = _save()

	_lines.append("========== 完成 ==========")
	_lines.append("合成：%s  %sx%s  %.2fs" % [
		String(clip["name"]),
		str(clip.get("comp", {}).get("width", "?")),
		str(clip.get("comp", {}).get("height", "?")),
		float(clip.get("length", 0.0))
	])
	_lines.append("图层 %d 个｜动画层 %d 个｜轨道 %d 条｜关键帧 %d 个" % [
		_layer_list.size(), stats[0], stats[1], stats[2]
	])
	if merge_target != null:
		_lines.append("已合并进当前场景：" + String(merge_target.get_path()))
	else:
		_lines.append("输出：" + _out_scene)

	if not _blend_skipped.is_empty():
		_lines.append("⚠ 混合模式未实现 %d 层：%s（现在是普通叠加）" % [
			_blend_skipped.size(), ", ".join(PackedStringArray(_blend_skipped))
		])
	if _missing.is_empty():
		_lines.append("贴图：全部找到")
	else:
		_lines.append("缺贴图 %d 张：%s" % [_missing.size(), ", ".join(PackedStringArray(_missing))])
	if not _frames_size_mismatch.is_empty():
		_lines.append("⚠ 序列帧和图层边界不一致，位置会偏：" + ", ".join(PackedStringArray(_frames_size_mismatch)))
	if not _heavy_frames.is_empty():
		_lines.append("⚠ 序列帧太重：%s —— 建议裁切/缩尺寸/降帧率，否则会爆显存" % [
			", ".join(PackedStringArray(_heavy_frames))
		])
	if not _tex_fixed.is_empty():
		_lines.append("贴图导入设置已修正 %d 张（无损 + 无 mipmap）：%s" % [
			_tex_fixed.size(), ", ".join(PackedStringArray(_tex_fixed))
		])
	if not _missing_frames.is_empty():
		_lines.append("缺序列帧目录 %d 个：%s（在 %s 下找）" % [
			_missing_frames.size(), ", ".join(PackedStringArray(_missing_frames)), _frames_root
		])

	if err != OK:
		return _fail("保存场景失败：%d" % err)

	return {
		"ok": true,
		"lines": _lines,
		"scene": _out_scene,
		"missing": _missing,
		"missing_frames": _missing_frames
	}


func _fail(msg: String) -> Dictionary:
	_lines.append("失败：" + msg)
	return {"ok": false, "lines": _lines, "scene": "", "missing": _missing}


func _node_for(idx: int) -> Node:
	if _use3d:
		if bool(_by_index[idx].get("threeD", false)):
			return _node_for3(idx)
		return _node_for2d(idx)
	if _nodes.has(idx):
		return _nodes[idx]

	var L: Dictionary = _by_index[idx]
	var frames_name := String(L.get("frames", ""))
	# AE 的图片序列素材：层名形如 "转场_[00000-00025].png"
	if frames_name == "":
		var seq_prefix := _sequence_prefix(String(L["name"]))
		if seq_prefix != "":
			frames_name = seq_prefix
	var n: Node2D

	if String(L.get("type", "image")) == "null":
		n = Node2D.new()
		n.z_index = -int(L["z"])

	elif frames_name != "":
		var asp := AnimatedSprite2D.new()
		asp.sprite_frames = _build_sprite_frames(frames_name, bool(L.get("framesLoop", true)))
		# 图片序列：层名里的 [00000-00025] 是帧范围，超出部分裁掉；
		# 播放速度按图层时长铺满，和 AE 里一致
		var seq_count := _sequence_frame_count(String(L["name"]))
		if seq_count > 0 and asp.sprite_frames.get_frame_count("default") > seq_count:
			while asp.sprite_frames.get_frame_count("default") > seq_count:
				asp.sprite_frames.remove_frame("default", asp.sprite_frames.get_frame_count("default") - 1)
		var layer_dur := float(L.get("outPoint", 0.0)) - float(L.get("inPoint", 0.0))
		var fc := asp.sprite_frames.get_frame_count("default")
		if fc > 0 and layer_dur > 0.01:
			asp.sprite_frames.set_animation_speed("default", float(fc) / layer_dur)
		asp.animation = "default"
		asp.autoplay = "default"
		asp.centered = false
		asp.z_index = -int(L["z"])

		var fa: Dictionary = L["asset"]
		var fanchor: Array = fa["anchor"]
		_check_frames_size(asp.sprite_frames, fa, String(L["name"]))
		if _is_comp_sized(asp.sprite_frames):
			# 整帧序列：像素已经是合成空间的了，位置改成"相对首帧的位移"
			asp.offset = Vector2.ZERO
			_comp_space_layers[idx] = true
		else:
			# 只含这一层内容的序列：按锚点摆
			asp.offset = -Vector2(float(fanchor[0]), float(fanchor[1]))
		n = asp

	else:
		var sp := Sprite2D.new()
		sp.centered = false
		sp.z_index = -int(L["z"])

		var asset: Dictionary = L["asset"]
		var anchor: Array = asset["anchor"]
		var wj := float(asset["width"])
		var hj := float(asset["height"])
		var scol2 = _solid_color(L)
		if scol2 != null:
			sp.texture = _white_texture()
			sp.self_modulate = scol2
			sp.offset = Vector2(-float(anchor[0]) / maxf(wj, 1.0), -float(anchor[1]) / maxf(hj, 1.0))
			sp.scale = Vector2(maxf(wj, 1.0), maxf(hj, 1.0))
		else:
			sp.texture = _texture_for(L)
			var tex_size := Vector2(wj, hj)
			if sp.texture != null:
				tex_size = sp.texture.get_size()
			sp.offset = -(Vector2(float(anchor[0]), float(anchor[1])) - (Vector2(wj, hj) - tex_size))
		n = sp

	# AE 的层序是全局的：必须关掉相对父级累加，否则子层会被父级的 z 拖到底下
	n.z_as_relative = false

	# 静态值（动画层的轨道会覆盖）
	if bool(_comp_space_layers.get(idx, false)):
		# 整帧序列：像素已经含位置，姿态归零，位移只由轨道给（相对首帧）
		n.position = Vector2.ZERO
		n.rotation = 0.0
		n.scale = Vector2.ONE
	else:
		var p0: Array = L["tracks"]["position"][0]
		n.position = Vector2(float(p0[1]), float(p0[2]))
		var r0: Array = L["tracks"]["rotation"][0]
		n.rotation = deg_to_rad(float(r0[1]))
		var s0: Array = L["tracks"]["scale"][0]
		var szn := _solid_size(L)
		n.scale = Vector2(float(s0[1]) * szn.x, float(s0[2]) * szn.y)
	var a0: Array = L["tracks"]["alpha"][0]
	var scn = _solid_color(L)
	var basec2 := Color(1.0, 1.0, 1.0) if scn == null else (scn as Color)
	n.self_modulate = Color(basec2.r, basec2.g, basec2.b, float(a0[1]))

	_apply_blend2d(n, L)

	n.name = _base_name(String(L["name"]))

	# 蒙版：用 Polygon2D 包一层，clip_children 裁掉外面的部分
	var wrap := _apply_masks2d(n, L)
	if wrap != null:
		n = wrap

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


func _apply_masks2d(child: Node, L: Dictionary) -> Node:
	var masks: Array = L.get("masks", [])
	if masks.is_empty() or not (child is CanvasItem):
		return null
	# 动蒙版：生成一个驱动节点，由它每帧把多边形写进目标材质
	for m in masks:
		if bool(m.get("animated", false)):
			_mask_drivers.append({"layer": String(L["name"]), "mask": m})
			_mask_applied.append("%s(%s,动蒙版→MaskDriver)" % [String(L["name"]), String(m.get("name", "?"))])
			return null
		if String(m.get("mode", "ADD")) != "ADD" or bool(m.get("inverted", false)):
			_mask_skipped.append("%s(%s,%s%s)" % [String(L["name"]), String(m.get("name", "?")),
				String(m.get("mode", "ADD")), " 反转" if bool(m.get("inverted", false)) else ""])
			return null

	# 只有一个普通 ADD 蒙版才处理
	var pts: Array = masks[0].get("points", [])
	if pts.size() < 3:
		return null

	var anchor: Array = L["asset"]["anchor"]
	# 用 discard 着色器做裁剪（clip_children 对没有贴图的节点无效）
	var sh: Shader = load("res://addons/ae_motion/mask_poly.gdshader")
	if sh == null:
		_mask_skipped.append("%s(缺 mask_poly.gdshader)" % String(L["name"]))
		return null
	var ci0 := child as CanvasItem
	if ci0.material != null:
		_mask_skipped.append("%s(同时有混合模式,暂不支持组合)" % String(L["name"]))
		return null
	var sm := ShaderMaterial.new()
	sm.shader = sh
	var arr := PackedVector2Array()
	for p2 in pts:
		if arr.size() >= 128:
			break
		arr.append(Vector2(float(p2[0]), float(p2[1])))
	sm.set_shader_parameter("points", arr)
	sm.set_shader_parameter("count", arr.size())
	sm.set_shader_parameter("layer_size", Vector2(float(L["asset"]["width"]), float(L["asset"]["height"])))
	sm.set_shader_parameter("layer_anchor", Vector2(float(anchor[0]), float(anchor[1])))
	ci0.material = sm
	_mask_applied.append("%s(%d 点)" % [String(L["name"]), arr.size()])
	return null


func _build_sprite_frames(folder: String, loop_anim: bool = true) -> SpriteFrames:
	var sf := SpriteFrames.new()
	sf.set_animation_speed("default", _fps)
	sf.set_animation_loop("default", loop_anim)

	var path := _frames_root.path_join(folder)
	var dir := DirAccess.open(path)
	if dir == null:
		# 不是 Frames/<名字> 这种序列目录，就当作"图片序列素材"按前缀去找
		var seq := _find_sequence(folder)
		if seq.is_empty():
			_missing_frames.append(folder)
			return sf
		var ok := 0
		for sp in seq:
			var tex = load(sp)
			if tex is Texture2D:
				sf.add_frame("default", tex as Texture2D)
				ok += 1
		if ok == 0:
			_missing_frames.append(folder + "（序列 PNG 未导入完成）")
		return sf

	var files: Array = []
	dir.list_dir_begin()
	var f := dir.get_next()
	while f != "":
		if not dir.current_is_dir() and f.get_extension().to_lower() == "png":
			files.append(f)
		f = dir.get_next()
	dir.list_dir_end()

	files.sort()
	var loaded := 0
	var failed := 0
	var bytes := 0
	for name in files:
		# 序列帧也要走无损规则，否则被 3D 引用时会自动转 VRAM(BPTC)
		_ensure_lossless(path.path_join(String(name)))
		var t = load(path.path_join(String(name)))
		if t is Texture2D:
			sf.add_frame("default", t as Texture2D)
			var ts: Vector2 = (t as Texture2D).get_size()
			bytes += int(ts.x * ts.y * 4.0)
			loaded += 1
		else:
			failed += 1
			# PNG 还没被 Godot 导入时，每张 load 都会失败并触发一次导入尝试。
			# 连续失败就立刻收手，别把编辑器卡死。
			if loaded == 0 and failed >= 3:
				_missing_frames.append(folder + "（PNG 未导入完成）")
				return sf

	if files.is_empty():
		_missing_frames.append(folder)
	elif bytes > 268435456:
		_heavy_frames.append("%s（%d 帧，约 %d MB 显存）" % [folder, loaded, bytes / 1048576])
	return sf


func _texture_for(L: Dictionary) -> Texture2D:
	var want := _norm(_base_name(String(L["name"])))
	var want_src := _norm(_base_name(String(L["asset"].get("source", ""))))

	var dir := DirAccess.open(_art_dir)
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
					var path := _art_dir.path_join(f)
					_ensure_lossless(path)
					var t = load(path)
					if t is Texture2D:
						dir.list_dir_end()
						return t as Texture2D
			f = dir.get_next()
		dir.list_dir_end()

	if bool(L.get("enabled", true)) and _solid_color(L) == null:
		_missing.append(_base_name(String(L["name"])))
	return null


func _build_animation(data: Dictionary, segments: Array) -> Array:
	var ap := AnimationPlayer.new()
	ap.name = "AnimationPlayer"
	_root.add_child(ap)

	var lib := AnimationLibrary.new()
	var animated := 0
	var tracks := 0
	var keys := 0
	var first_name := ""

	for L in _layer_list:
		if not bool(L.get("enabled", true)):
			continue
		if not bool(L.get("isStatic", true)):
			animated += 1

	for seg in segments:
		var s := float(seg["start"])
		var e := float(seg["end"])
		var loop := bool(seg["loop"])
		var reps := int(seg.get("repeat", 0))
		var copies := reps if reps > 1 else 1

		var anim := Animation.new()
		anim.length = maxf((e - s) * copies, 0.001)
		if loop and copies == 1:
			anim.loop_mode = Animation.LOOP_LINEAR

		var seg_name := String(seg["name"])
		if first_name == "":
			first_name = seg_name

		for L in _layer_list:
			if not bool(L.get("enabled", true)):
				continue
			if bool(L.get("isStatic", true)):
				continue
			if not bool(L.get("threeD", false)):
				continue
			var n = _nodes.get(int(L["index"]))
			if n == null:
				continue
			var rel := String(_root.get_path_to(n))
			var tk: Dictionary = L["tracks"]
			var comp_space := bool(_comp_space_layers.get(int(L["index"]), false))

			var kp := _slice(tk["position"], s, e, loop)
			if copies > 1:
				kp = _repeat_rows(kp, copies, e - s)
			if _varies(kp, 3):
				var t1 := anim.add_track(Animation.TYPE_VALUE)
				anim.track_set_path(t1, NodePath(rel + ":position"))
				anim.track_set_interpolation_type(t1, Animation.INTERPOLATION_LINEAR)
				var base_p := Vector2(float(kp[0][1]), float(kp[0][2]))
				for row in kp:
					var v := Vector2(float(row[1]), float(row[2]))
					if comp_space:
						v -= base_p
					anim.track_insert_key(t1, float(row[0]) / 1000.0, v)
					keys += 1
				tracks += 1

			var kr := _slice(tk["rotation"], s, e, loop)
			if copies > 1:
				kr = _repeat_rows(kr, copies, e - s)
			if _varies(kr, 2):
				var t2 := anim.add_track(Animation.TYPE_VALUE)
				anim.track_set_path(t2, NodePath(rel + ":rotation"))
				anim.track_set_interpolation_type(t2, Animation.INTERPOLATION_LINEAR)
				var base_r := float(kr[0][1])
				for row in kr:
					var rv := float(row[1])
					if comp_space:
						rv -= base_r
					anim.track_insert_key(t2, float(row[0]) / 1000.0, deg_to_rad(rv))
					keys += 1
				tracks += 1

			var ks := _slice(tk["scale"], s, e, loop)
			if copies > 1:
				ks = _repeat_rows(ks, copies, e - s)
			# 3D 层在正交投影下（AE 无相机时）表现为各方向压缩：
			# X 轴旋转压 Y，Y 轴旋转压 X。这样不用建 Node3D 也是精确的。
			var k3 := _slice(tk.get("rot3d", []), s, e, false)
			if k3.size() > 1 and _varies(k3, 3):
				if ks.size() == 1:
					var grown: Array = []
					for r3 in k3:
						grown.append([r3[0], ks[0][1], ks[0][2]])
					ks = grown
				for idx in range(ks.size()):
					var r3r := _row_at(k3, float(ks[idx][0]))
					if r3r.is_empty():
						continue
					var rx := deg_to_rad(float(r3r[1]))
					var ry := deg_to_rad(float(r3r[2]))
					ks[idx][1] = float(ks[idx][1]) * cos(ry)
					ks[idx][2] = float(ks[idx][2]) * cos(rx)
			if _varies(ks, 3):
				var t3 := anim.add_track(Animation.TYPE_VALUE)
				anim.track_set_path(t3, NodePath(rel + ":scale"))
				anim.track_set_interpolation_type(t3, Animation.INTERPOLATION_LINEAR)
				var base_sx := maxf(float(ks[0][1]), 0.0001)
				var base_sy := maxf(float(ks[0][2]), 0.0001)
				var smul := _solid_size(L)
				for row in ks:
					var sv := Vector2(float(row[1]), float(row[2]))
					if comp_space:
						sv = Vector2(sv.x / base_sx, sv.y / base_sy)
					sv = Vector2(sv.x * smul.x, sv.y * smul.y)
					anim.track_insert_key(t3, float(row[0]) / 1000.0, sv)
					keys += 1
				tracks += 1

			var ka := _slice(tk["alpha"], s, e, loop)
			if copies > 1:
				ka = _repeat_rows(ka, copies, e - s)
			if _varies(ka, 2):
				var t4 := anim.add_track(Animation.TYPE_VALUE)
				anim.track_set_path(t4, NodePath(rel + ":self_modulate:a"))
				anim.track_set_interpolation_type(t4, Animation.INTERPOLATION_LINEAR)
				for row in ka:
					anim.track_insert_key(t4, float(row[0]) / 1000.0, float(row[1]))
					keys += 1
				tracks += 1

		# 2D 层：屏幕空间坐标 = 自身 + 父级链位置
		for L in _layer_list:
			if bool(L.get("threeD", false)) or bool(L.get("isStatic", true)):
				continue
			var n2 = _nodes.get(int(L["index"]))
			if n2 == null or not (n2 is Sprite2D):
				continue
			var rel2 := String(_root.get_path_to(n2))
			var afx := Transform2D.IDENTITY if _parented2d.has(int(L["index"])) else _ancestor_xform(L)
			var t2k: Dictionary = L["tracks"]

			var kp2 := _slice(t2k["position"], s, e, false)
			if _varies(kp2, 3):
				var tp := anim.add_track(Animation.TYPE_VALUE)
				anim.track_set_path(tp, NodePath(rel2 + ":position"))
				anim.track_set_interpolation_type(tp, Animation.INTERPOLATION_LINEAR)
				var pshift := _parent_anchor(L) if _parented2d.has(int(L["index"])) else Vector2.ZERO
				for row in kp2:
					anim.track_insert_key(tp, float(row[0]) / 1000.0,
						afx * (Vector2(float(row[1]), float(row[2])) - pshift))
					keys += 1
				tracks += 1

			var kr2 := _slice(t2k["rotation"], s, e, false)
			if _varies(kr2, 2):
				var tr := anim.add_track(Animation.TYPE_VALUE)
				anim.track_set_path(tr, NodePath(rel2 + ":rotation"))
				anim.track_set_interpolation_type(tr, Animation.INTERPOLATION_LINEAR)
				for row in kr2:
					anim.track_insert_key(tr, float(row[0]) / 1000.0, deg_to_rad(float(row[1])))
					keys += 1
				tracks += 1

			var ka2 := _slice(t2k["alpha"], s, e, false)
			if _varies(ka2, 2):
				var ta := anim.add_track(Animation.TYPE_VALUE)
				anim.track_set_path(ta, NodePath(rel2 + ":self_modulate:a"))
				anim.track_set_interpolation_type(ta, Animation.INTERPOLATION_LINEAR)
				for row in ka2:
					anim.track_insert_key(ta, float(row[0]) / 1000.0, float(row[1]))
					keys += 1
				tracks += 1

		# 循环段：首末值不一致 = 每圈都会跳，直接报出来
		if bool(seg["loop"]) and copies == 1:
			var worst := ""
			var worst_d := 0.0
			for i in range(anim.get_track_count()):
				var nk := anim.track_get_key_count(i)
				if nk < 2:
					continue
				var v0 = anim.track_get_key_value(i, 0)
				var v1 = anim.track_get_key_value(i, nk - 1)
				var d := 0.0
				if v0 is Vector3:
					d = (v0 as Vector3).distance_to(v1)
				elif v0 is Vector2:
					d = (v0 as Vector2).distance_to(v1)
				else:
					d = absf(float(v0) - float(v1))
				if d > worst_d:
					worst_d = d
					worst = String(anim.track_get_path(i))
			if worst_d > 0.02:
				_lines.append("⚠ 循环段 %s 首末不一致：%s 差 %.2f（每圈都会跳）" % [seg_name, worst, worst_d])

			# 相机关键帧：位置 / 朝向（由目标点算出欧拉角）/ 焦距
		if _cam_node != null:
			var ct: Dictionary = {}
			for L2 in _layer_list:
				if String(L2.get("type", "")) == "camera" and L2.has("cameraTracks"):
					ct = L2["cameraTracks"]
					break
			if not ct.is_empty():
				var ck: Array = _slice(ct.get("position", []), s, e, false)
				if ck.size() > 1:
					var relc := String(_root.get_path_to(_cam_node))
					var tp := anim.add_track(Animation.TYPE_VALUE)
					anim.track_set_path(tp, NodePath(relc + ":position"))
					anim.track_set_interpolation_type(tp, Animation.INTERPOLATION_LINEAR)
					var tr := anim.add_track(Animation.TYPE_VALUE)
					anim.track_set_path(tr, NodePath(relc + ":rotation"))
					anim.track_set_interpolation_type(tr, Animation.INTERPOLATION_LINEAR)
					var tf := anim.add_track(Animation.TYPE_VALUE)
					anim.track_set_path(tf, NodePath(relc + ":fov"))
					anim.track_set_interpolation_type(tf, Animation.INTERPOLATION_LINEAR)

					for row in ck:
						var ms2 := float(row[0])
						var pos := Vector3(float(row[1]) - _comp_size.x * 0.5,
							-(float(row[2]) - _comp_size.y * 0.5),
							-float(row[3]))
						var ir := _row_at(ct.get("interest", []), ms2)
						var tgt := Vector3(0.0, 0.0, 0.0)
						if ir.size() >= 4:
							tgt = Vector3(float(ir[1]) - _comp_size.x * 0.5,
								-(float(ir[2]) - _comp_size.y * 0.5),
								-float(ir[3]))
						var euler := Vector3(0.0, 0.0, 0.0)
						var dir := tgt - pos
						if dir.length() > 0.0001:
							euler = Basis.looking_at(dir.normalized(), Vector3.UP).get_euler()
						var zr2 := _row_at(ct.get("zoom", []), ms2)
						var zoom := float(zr2[1]) if zr2.size() >= 2 else 0.0
						var fov := 75.0
						if zoom > 0.0:
							fov = rad_to_deg(2.0 * atan((_comp_size.y * 0.5) / zoom))
						anim.track_insert_key(tp, ms2 / 1000.0, pos)
						anim.track_insert_key(tr, ms2 / 1000.0, euler)
						anim.track_insert_key(tf, ms2 / 1000.0, fov)
						keys += 3

		lib.add_animation(seg_name, anim)

	ap.add_animation_library("", lib)
	ap.root_node = NodePath("..")

	if segments.size() > 1:
		# 多段：自动挂一个串接节点，按段表顺序播，不用手写代码
		var seq := Node.new()
		seq.name = "AutoSequence"
		seq.set_script(load("res://addons/ae_motion/auto_sequence.gd"))
		var names := PackedStringArray()
		for seg2 in segments:
			names.append(String(seg2["name"]))
		seq.set("player_path", NodePath("../AnimationPlayer"))
		seq.set("sequence", names)
		seq.set("autoplay", _autoplay)
		_root.add_child(seq)
		ap.autoplay = ""
	elif first_name != "" and _autoplay:
		ap.autoplay = first_name

	return [animated, tracks, keys]


func _slice(track: Array, s: float, e: float, loop: bool) -> Array:
	var out: Array = []
	if track.is_empty():
		return out
	# 全程用毫秒整数比较：秒级浮点会让"最后一帧"落在区间外 1/3 毫秒处被切掉
	var s_ms := int(round(s * 1000.0))
	var e_ms := int(round(e * 1000.0))
	for row in track:
		var ms := int(round(float(row[0])))
		if ms >= s_ms and ms <= e_ms:
			var nr: Array = row.duplicate()
			nr[0] = ms - s_ms
			out.append(nr)

	if out.is_empty():
		var only: Array = track[0].duplicate()
		only[0] = 0
		out.append(only)

	out[0][0] = 0

	return out


func _parse_segments(spec: String, total: float) -> Array:
	var segs: Array = []
	var txt := spec.strip_edges().replace("；", ";").replace("，", ";").replace(",", ";")
	if txt != "":
		for chunk in txt.split(";", false):
			var part := chunk.strip_edges()
			if part == "":
				continue
			var loop := false
			var repeat := 0
			var star := part.find("*")
			if star >= 0:
				var tail := part.substr(star + 1).strip_edges()
				part = part.substr(0, star).strip_edges()
				if tail == "":
					loop = true
					repeat = 0
				else:
					var n := int(tail)
					if n > 0:
						loop = true
						repeat = n
			var nm := "seg"
			var range_txt := part
			var colon := part.find(":")
			if colon >= 0:
				nm = part.substr(0, colon).strip_edges()
				range_txt = part.substr(colon + 1).strip_edges()
			var dash := range_txt.find("-")
			if dash < 0:
				continue
			# 填的是帧号，换算成秒
			var a := float(range_txt.substr(0, dash).strip_edges()) / _fps
			var b := float(range_txt.substr(dash + 1).strip_edges()) / _fps
			if b <= a:
				continue
			var used := {}
			for s0 in segs:
				used[String(s0["name"])] = true
			var unique := nm
			var idx := 2
			while used.has(unique):
				unique = "%s_%d" % [nm, idx]
				idx += 1
			segs.append({"name": unique, "start": a, "end": b, "loop": loop, "repeat": repeat})

	if segs.is_empty():
		segs.append({"name": "play", "start": 0.0, "end": total, "loop": false})
	return segs

func _node_for3(idx: int) -> Node:
	if _nodes.has(idx):
		return _nodes[idx]

	var L: Dictionary = _by_index[idx]
	var anchor: Array = L["asset"]["anchor"]
	var n: Node

	var t3 := String(L.get("type", "image"))
	if t3 == "null" or t3 == "camera" or t3 == "light":
		n = Node3D.new()
	else:
		var sp := Sprite3D.new()
		var scol = _solid_color(L)
		sp.pixel_size = 1.0
		sp.centered = false
		sp.billboard = BaseMaterial3D.BILLBOARD_DISABLED
		if scol != null:
			# 纯色层：1×1 白图染色，尺寸靠 scale 撑开
			sp.texture = _white_texture()
			sp.modulate = scol
			var sw := maxf(float(L["asset"]["width"]), 1.0)
			var sh := maxf(float(L["asset"]["height"]), 1.0)
			sp.offset = Vector2(-float(anchor[0]) / sw, -float(anchor[1]) / sh)
			sp.scale = Vector3(sw, sh, 1.0)
		else:
			sp.texture = _texture_for(L)
			sp.offset = Vector2(-float(anchor[0]), -float(anchor[1]))
		sp.billboard = BaseMaterial3D.BILLBOARD_DISABLED
		# 同深度的透明精灵按这个排序：AE 里图层号越小越靠前
		sp.render_priority = 100 - int(L["z"])
		var bl3: Dictionary = L.get("blend", {})
		if String(bl3.get("role", "normal")) != "normal":
			_blend_skipped.append("%s(%s,3D)" % [String(L["name"]), String(bl3.get("mode", "?"))])
		n = sp

	var p0: Array = L["tracks"]["position"][0]
	var z0 := 0.0
	var pz: Array = L["tracks"].get("posZ", [])
	if not pz.is_empty():
		z0 = float(pz[0][1])

	var node3 := n as Node3D
	var pid0 = L.get("parent")
	var is_root_level := (pid0 == null or int(pid0) <= 0)
	if is_root_level:
		node3.position = Vector3(
			float(p0[1]) - _comp_size.x * 0.5,
			-(float(p0[2]) - _comp_size.y * 0.5),
			-z0)
	else:
		# 子节点：父级已经是局部空间，这里只做 Y/Z 轴翻转
		node3.position = Vector3(float(p0[1]), -float(p0[2]), -z0)

	var s0: Array = L["tracks"]["scale"][0]
	var sz0 := _solid_size(L)
	node3.scale = Vector3(float(s0[1]) * sz0.x, float(s0[2]) * sz0.y, 1.0)

	var rx0 := 0.0
	var ry0 := 0.0
	var r3: Array = L["tracks"].get("rot3d", [])
	if not r3.is_empty():
		rx0 = float(r3[0][1])
		ry0 = float(r3[0][2])
	var rz0 := 0.0
	var r2: Array = L["tracks"]["rotation"]
	if not r2.is_empty():
		rz0 = float(r2[0][1])
	node3.rotation = Vector3(deg_to_rad(-rx0), deg_to_rad(-ry0), deg_to_rad(-rz0))

	if n is Sprite3D:
		var a0: Array = L["tracks"]["alpha"][0]
		var sc0 = _solid_color(L)
		var base0 := Color(1.0, 1.0, 1.0) if sc0 == null else (sc0 as Color)
		(n as Sprite3D).modulate = Color(base0.r, base0.g, base0.b, float(a0[1]))

	n.name = _base_name(String(L["name"]))
	_nodes[idx] = n

	var pid = L.get("parent")
	if pid != null and int(pid) > 0:
		var p := _node_for3(int(pid))
		p.add_child(n)
		n.name = _unique_name(p, String(n.name), n)
	else:
		_world.add_child(n)
		n.name = _unique_name(_world, String(n.name), n)

	return n


func _make_camera3(data: Dictionary) -> void:
	var cam_data: Dictionary = {}
	for L in _layer_list:
		if String(L.get("type", "")) == "camera" and L.has("camera"):
			cam_data = L["camera"]
			break
	var cam := Camera3D.new()
	cam.name = "Camera3D"
	var zoom := float(cam_data.get("zoom", 0.0))
	var cp: Array = cam_data.get("position", [0, 0, 0])
	var ip: Array = cam_data.get("interest", [0, 0])

	cam.position = Vector3(
		float(cp[0]) - _comp_size.x * 0.5,
		-(float(cp[1]) - _comp_size.y * 0.5),
		-float(cp[2]))

	if zoom > 0.0:
		cam.fov = rad_to_deg(2.0 * atan((_comp_size.y * 0.5) / zoom))
		cam.keep_aspect = Camera3D.KEEP_HEIGHT
	cam.current = true
	_world.add_child(cam)
	cam.make_current()
	_cam_node = cam
	cam.look_at_from_position(cam.position, Vector3(
		float(ip[0]) - _comp_size.x * 0.5,
		-(float(ip[1]) - _comp_size.y * 0.5),
		0.0), Vector3.UP)


func _build_animation_3d(data: Dictionary, segments: Array) -> Array:
	var ap := AnimationPlayer.new()
	ap.name = "AnimationPlayer"
	_root.add_child(ap)

	var lib := AnimationLibrary.new()
	var animated := 0
	var tracks := 0
	var keys := 0
	var first_name := ""

	for L in _layer_list:
		if not bool(L.get("enabled", true)):
			continue
		if not bool(L.get("isStatic", true)):
			animated += 1

	for seg in segments:
		var s := float(seg["start"])
		var e := float(seg["end"])
		var reps := int(seg.get("repeat", 0))
		var copies := reps if reps > 1 else 1
		var anim := Animation.new()
		anim.length = maxf(e - s, 0.001) * copies
		if bool(seg["loop"]) and copies == 1:
			anim.loop_mode = Animation.LOOP_LINEAR
		var seg_name := String(seg["name"])
		if first_name == "":
			first_name = seg_name

		for L in _layer_list:
			if not bool(L.get("enabled", true)):
				continue
			if bool(L.get("isStatic", true)):
				continue
			if not bool(L.get("threeD", false)):
				continue
			var n = _nodes.get(int(L["index"]))
			if n == null:
				continue
			var rel := String(_root.get_path_to(n))
			var tk: Dictionary = L["tracks"]
			var kp := _slice(tk["position"], s, e, false)
			var kz := _slice(tk.get("posZ", []), s, e, false)
			var kr := _slice(tk["rotation"], s, e, false)
			var k3 := _slice(tk.get("rot3d", []), s, e, false)
			var ks := _slice(tk["scale"], s, e, false)

			# 判断"这一段里有没有变化"要用整条轨道：整条动过、但这段时间是常量时，
			# 也必须建一条单帧轨道，否则播放别的段以后这里会停在旧姿态
			var has_pos := _varies(tk["position"], 3) or _varies(tk.get("posZ", []), 2)
			var has_rot := _varies(tk["rotation"], 2) or _varies(tk.get("rot3d", []), 3)
			var has_scl := _varies(tk["scale"], 3)
			if not (has_pos or has_rot or has_scl):
				continue

			# 关键帧时间网格取这一层最密的通道，不能跟着 position 走
			var grid: Array = kp
			for cand in [kz, k3, kr, ks]:
				if (cand as Array).size() > grid.size():
					grid = cand

			var t_pos := -1
			if has_pos:
				t_pos = anim.add_track(Animation.TYPE_VALUE)
				anim.track_set_path(t_pos, NodePath(rel + ":position"))
				anim.track_set_interpolation_type(t_pos, Animation.INTERPOLATION_LINEAR)
				tracks += 1
			var t_rot := -1
			if has_rot:
				t_rot = anim.add_track(Animation.TYPE_VALUE)
				anim.track_set_path(t_rot, NodePath(rel + ":rotation"))
				anim.track_set_interpolation_type(t_rot, Animation.INTERPOLATION_LINEAR)
				tracks += 1
			var t_scl := -1
			if has_scl:
				t_scl = anim.add_track(Animation.TYPE_VALUE)
				anim.track_set_path(t_scl, NodePath(rel + ":scale"))
				anim.track_set_interpolation_type(t_scl, Animation.INTERPOLATION_LINEAR)
				tracks += 1

			for row in grid:
				var ms := float(row[0])
				var pr := _row_at(kp, ms)
				var x := float(pr[1]) if not pr.is_empty() else 0.0
				var y := float(pr[2]) if not pr.is_empty() else 0.0
				var z := 0.0
				var zr := _row_at(kz, ms)
				if not zr.is_empty():
					z = float(zr[1])

				if t_pos >= 0:
					var v3: Vector3
					if bool(L.get("parent") == null or int(L.get("parent", 0)) <= 0):
						v3 = Vector3(x - _comp_size.x * 0.5, -(y - _comp_size.y * 0.5), -z)
					else:
						v3 = Vector3(x, -y, -z)
					anim.track_insert_key(t_pos, ms / 1000.0, v3)
					keys += 1

				if t_rot >= 0:
					var rx := 0.0
					var ry := 0.0
					var r3r := _row_at(k3, ms)
					if not r3r.is_empty():
						rx = float(r3r[1])
						ry = float(r3r[2])
					var rz := 0.0
					var rrr := _row_at(kr, ms)
					if not rrr.is_empty():
						rz = float(rrr[1])
					anim.track_insert_key(t_rot, ms / 1000.0, Vector3(
						deg_to_rad(-rx), deg_to_rad(-ry), deg_to_rad(-rz)))
					keys += 1

				if t_scl >= 0:
					var sr := _row_at(ks, ms)
					if not sr.is_empty():
						var m3 := _solid_size(L)
						anim.track_insert_key(t_scl, ms / 1000.0, Vector3(
							float(sr[1]) * m3.x, float(sr[2]) * m3.y, 1.0))
						keys += 1

			# 透明度：Sprite3D 走 modulate:a（之前 3D 路径完全没建这条轨道）
			if _varies(tk["alpha"], 2):
				var ka3 := _slice(tk["alpha"], s, e, false)
				var ta := anim.add_track(Animation.TYPE_VALUE)
				anim.track_set_path(ta, NodePath(rel + ":modulate:a"))
				anim.track_set_interpolation_type(ta, Animation.INTERPOLATION_LINEAR)
				for row in ka3:
					anim.track_insert_key(ta, float(row[0]) / 1000.0, float(row[1]))
					keys += 1
				tracks += 1

		# 2D 层：屏幕空间坐标 = 自身 + 父级链位置
		for L in _layer_list:
			if bool(L.get("threeD", false)) or bool(L.get("isStatic", true)):
				continue
			var n2 = _nodes.get(int(L["index"]))
			if n2 == null or not (n2 is Sprite2D):
				continue
			var rel2 := String(_root.get_path_to(n2))
			var afx := Transform2D.IDENTITY if _parented2d.has(int(L["index"])) else _ancestor_xform(L)
			var t2k: Dictionary = L["tracks"]

			var kp2 := _slice(t2k["position"], s, e, false)
			if _varies(kp2, 3):
				var tp := anim.add_track(Animation.TYPE_VALUE)
				anim.track_set_path(tp, NodePath(rel2 + ":position"))
				anim.track_set_interpolation_type(tp, Animation.INTERPOLATION_LINEAR)
				var pshift := _parent_anchor(L) if _parented2d.has(int(L["index"])) else Vector2.ZERO
				for row in kp2:
					anim.track_insert_key(tp, float(row[0]) / 1000.0,
						afx * (Vector2(float(row[1]), float(row[2])) - pshift))
					keys += 1
				tracks += 1

			var kr2 := _slice(t2k["rotation"], s, e, false)
			if _varies(kr2, 2):
				var tr := anim.add_track(Animation.TYPE_VALUE)
				anim.track_set_path(tr, NodePath(rel2 + ":rotation"))
				anim.track_set_interpolation_type(tr, Animation.INTERPOLATION_LINEAR)
				for row in kr2:
					anim.track_insert_key(tr, float(row[0]) / 1000.0, deg_to_rad(float(row[1])))
					keys += 1
				tracks += 1

			var ka2 := _slice(t2k["alpha"], s, e, false)
			if _varies(ka2, 2):
				var ta := anim.add_track(Animation.TYPE_VALUE)
				anim.track_set_path(ta, NodePath(rel2 + ":self_modulate:a"))
				anim.track_set_interpolation_type(ta, Animation.INTERPOLATION_LINEAR)
				for row in ka2:
					anim.track_insert_key(ta, float(row[0]) / 1000.0, float(row[1]))
					keys += 1
				tracks += 1

		# 循环段：首末值不一致 = 每圈都会跳，直接报出来
		if bool(seg["loop"]) and copies == 1:
			var worst := ""
			var worst_d := 0.0
			for i in range(anim.get_track_count()):
				var nk := anim.track_get_key_count(i)
				if nk < 2:
					continue
				var v0 = anim.track_get_key_value(i, 0)
				var v1 = anim.track_get_key_value(i, nk - 1)
				var d := 0.0
				if v0 is Vector3:
					d = (v0 as Vector3).distance_to(v1)
				elif v0 is Vector2:
					d = (v0 as Vector2).distance_to(v1)
				else:
					d = absf(float(v0) - float(v1))
				if d > worst_d:
					worst_d = d
					worst = String(anim.track_get_path(i))
			if worst_d > 0.02:
				_lines.append("⚠ 循环段 %s 首末不一致：%s 差 %.2f（每圈都会跳）" % [seg_name, worst, worst_d])


		# 相机关键帧：位置 / 朝向（由目标点算出欧拉角）/ 焦距
		if _cam_node != null:
			var ct: Dictionary = {}
			for L2 in _layer_list:
				if String(L2.get("type", "")) == "camera" and L2.has("cameraTracks"):
					ct = L2["cameraTracks"]
					break
			if not ct.is_empty():
				var ck: Array = _slice(ct.get("position", []), s, e, false)
				if ck.size() > 1:
					var relc := String(_root.get_path_to(_cam_node))
					var tp := anim.add_track(Animation.TYPE_VALUE)
					anim.track_set_path(tp, NodePath(relc + ":position"))
					anim.track_set_interpolation_type(tp, Animation.INTERPOLATION_LINEAR)
					var tr := anim.add_track(Animation.TYPE_VALUE)
					anim.track_set_path(tr, NodePath(relc + ":rotation"))
					anim.track_set_interpolation_type(tr, Animation.INTERPOLATION_LINEAR)
					var tf := anim.add_track(Animation.TYPE_VALUE)
					anim.track_set_path(tf, NodePath(relc + ":fov"))
					anim.track_set_interpolation_type(tf, Animation.INTERPOLATION_LINEAR)

					for row in ck:
						var ms2 := float(row[0])
						var pos := Vector3(float(row[1]) - _comp_size.x * 0.5,
							-(float(row[2]) - _comp_size.y * 0.5),
							-float(row[3]))
						var ir := _row_at(ct.get("interest", []), ms2)
						var tgt := Vector3(0.0, 0.0, 0.0)
						if ir.size() >= 4:
							tgt = Vector3(float(ir[1]) - _comp_size.x * 0.5,
								-(float(ir[2]) - _comp_size.y * 0.5),
								-float(ir[3]))
						var euler := Vector3(0.0, 0.0, 0.0)
						var dir := tgt - pos
						if dir.length() > 0.0001:
							euler = Basis.looking_at(dir.normalized(), Vector3.UP).get_euler()
						var zr2 := _row_at(ct.get("zoom", []), ms2)
						var zoom := float(zr2[1]) if zr2.size() >= 2 else 0.0
						var fov := 75.0
						if zoom > 0.0:
							fov = rad_to_deg(2.0 * atan((_comp_size.y * 0.5) / zoom))
						anim.track_insert_key(tp, ms2 / 1000.0, pos)
						anim.track_insert_key(tr, ms2 / 1000.0, euler)
						anim.track_insert_key(tf, ms2 / 1000.0, fov)
						keys += 3

		lib.add_animation(seg_name, anim)

	ap.add_animation_library("", lib)
	ap.root_node = NodePath("..")

	if segments.size() > 1:
		var seq := Node.new()
		seq.name = "AutoSequence"
		seq.set_script(load("res://addons/ae_motion/auto_sequence.gd"))
		var names := PackedStringArray()
		for seg2 in segments:
			names.append(String(seg2["name"]))
		seq.set("player_path", NodePath("../AnimationPlayer"))
		seq.set("sequence", names)
		seq.set("autoplay", _autoplay)
		_root.add_child(seq)
		ap.autoplay = ""
	elif first_name != "" and _autoplay:
		ap.autoplay = first_name

	return [animated, tracks, keys]


func _save() -> int:
	_set_owner(_root, _root)
	var ps := PackedScene.new()
	var err := ps.pack(_root)
	if err != OK:
		return err

	var dir := _out_scene.get_base_dir()
	if not DirAccess.dir_exists_absolute(dir):
		DirAccess.make_dir_recursive_absolute(dir)

	var err2 := ResourceSaver.save(ps, _out_scene)
	_root.free()
	return err2


func _set_owner(n: Node, owner_root: Node) -> void:
	for c in n.get_children():
		c.owner = owner_root
		_set_owner(c, owner_root)


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


func _base_name(raw: String) -> String:
	var nm := raw.get_slice("/", 0)
	nm = nm.get_basename()
	for ch in [".", ":", "@", "#", "\"", "%", "\n", "\r", "\t"]:
		nm = nm.replace(ch, "_")
	nm = nm.strip_edges()
	if nm == "":
		nm = "layer"
	return nm


func _norm(s: String) -> String:
	var out := s.to_lower()
	for ch in [" ", "-", "_", ".", "(", ")", "（", "）"]:
		out = out.replace(ch, "")
	return out


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


func _is_comp_sized(sf: SpriteFrames) -> bool:
	if sf.get_frame_count("default") == 0:
		return false
	var tex := sf.get_frame_texture("default", 0)
	if tex == null:
		return false
	var ts := tex.get_size()
	return absf(ts.x - _comp_size.x) <= 2.0 and absf(ts.y - _comp_size.y) <= 2.0


func _check_frames_size(sf: SpriteFrames, asset: Dictionary, layer_name: String) -> void:
	if sf.get_frame_count("default") == 0:
		return
	var tex := sf.get_frame_texture("default", 0)
	if tex == null:
		return
	var ts := tex.get_size()
	var w := float(asset.get("width", 0))
	var h := float(asset.get("height", 0))
	if w <= 0.0 or h <= 0.0:
		return
	if _is_comp_sized(sf):
		return
	if absf(ts.x - w) > 2.0 or absf(ts.y - h) > 2.0:
		_frames_size_mismatch.append("%s：序列帧 %dx%d，图层边界 %dx%d" % [
			layer_name, int(ts.x), int(ts.y), int(w), int(h)
		])


func _apply_loop(data: Dictionary, s: float, e: float) -> void:
	var dur := e - s
	var end_ms := int(round(dur * 1000.0))
	for L in data.get("layers", []):
		var tracks: Dictionary = L.get("tracks", {})
		for ch in ["position", "rotation", "scale", "alpha"]:
			var arr: Array = tracks.get(ch, [])
			if arr.is_empty():
				continue

			var out: Array = []
			for row in arr:
				var t := float(row[0]) / 1000.0
				if t + 0.0001 >= s and t - 0.0001 <= e:
					var nr: Array = row.duplicate()
					nr[0] = int(round((t - s) * 1000.0))
					out.append(nr)

			if out.is_empty():
				var only: Array = arr[0].duplicate()
				only[0] = 0
				out.append(only)

			var first: Array = out[0]
			first[0] = 0

			var last: Array = out[out.size() - 1]
			if int(last[0]) >= end_ms - 1:
				# 区间正好有末帧：把它的值换成首帧的值
				last[0] = end_ms
				for i in range(1, last.size()):
					last[i] = first[i]
			else:
				# 区间里没有末帧：补一个和首帧一样的
				var extra: Array = first.duplicate()
				extra[0] = end_ms
				out.append(extra)

			tracks[ch] = out

	data["clip"]["length"] = dur


func _repeat_rows(rows: Array, reps: int, dur: float) -> Array:
	if reps <= 1:
		return rows
	var out: Array = []
	for r in range(reps):
		var off := int(round(r * dur * 1000.0))
		for row in rows:
			var nr: Array = row.duplicate()
			nr[0] = int(nr[0]) + off
			out.append(nr)
	return out


func _row_at(rows: Array, ms: float) -> Array:
	if rows.is_empty():
		return []
	var best: Array = rows[0]
	var bd := absf(float(rows[0][0]) - ms)
	for row in rows:
		var d := absf(float(row[0]) - ms)
		if d < bd:
			bd = d
			best = row
	return best

## 父级链的 2D 复合变换（自上而下）：T(pos − anchor) 再叠加 scale / rotation。
## 只累加 position 会漏掉父级 scale —— 父级 scale=1.03 时 y 会偏 40px。
func _ancestor_xform(L: Dictionary) -> Transform2D:
	var chain: Array = []
	var pid = L.get("parent")
	var guard := 0
	while pid != null and int(pid) > 0 and guard < 32:
		chain.push_front(int(pid))
		var P: Dictionary = _by_index[int(pid)]
		pid = P.get("parent")
		guard += 1

	var xf := Transform2D.IDENTITY
	for id in chain:
		var P: Dictionary = _by_index[id]
		var pp: Array = P["tracks"]["position"][0]
		var ps: Array = P["tracks"]["scale"][0]
		var pr: Array = P["tracks"]["rotation"][0]
		var pa: Array = P.get("asset", {}).get("anchor", [0, 0])
		# 先建“旋转+缩放”的线性部分（origin 为 0，scaled 不会挪动原点），再设平移
		var t := Transform2D(deg_to_rad(float(pr[1])), Vector2.ZERO)
		t = t.scaled(Vector2(float(ps[1]), float(ps[2])))
		t.origin = Vector2(float(pp[1]) - float(pa[0]), float(pp[2]) - float(pa[1]))
		xf = xf * t
	return xf


func _ancestor_offset(L: Dictionary) -> Vector2:
	return _ancestor_xform(L).origin


func _node_for2d(idx: int) -> Node:
	if _nodes.has(idx):
		return _nodes[idx]

	var L: Dictionary = _by_index[idx]
	var t2 := String(L.get("type", "image"))
	if t2 == "camera" or t2 == "light":
		var stub := Node2D.new()
		stub.name = _base_name(String(L["name"]))
		_nodes[idx] = stub
		_root2d.add_child(stub)
		return stub

	var sp := Sprite2D.new()
	sp.centered = false
	var host: Node2D = _root2d
	if int(L["z"]) > int(_mid_3d_z):
		host = _root2d_back

	var a: Array = L["asset"]["anchor"]
	var wj := float(L["asset"]["width"])
	var hj := float(L["asset"]["height"])
	var sc2 = _solid_color(L)
	if sc2 != null:
		sp.texture = _white_texture()
		sp.self_modulate = sc2
		sp.offset = Vector2(-float(a[0]) / maxf(wj, 1.0), -float(a[1]) / maxf(hj, 1.0))
		sp.scale = Vector2(maxf(wj, 1.0), maxf(hj, 1.0))
	else:
		sp.texture = _texture_for(L)
		var ts := Vector2(wj, hj)
		if sp.texture != null:
			ts = sp.texture.get_size()
		sp.offset = -(Vector2(float(a[0]), float(a[1])) - (Vector2(wj, hj) - ts))

	# 父级也是 2D 层时，保留层级（父级动，子层跟着动）；否则按合成坐标摆放
	var p0: Array = L["tracks"]["position"][0]
	var pid2 = L.get("parent")
	var parent2d: Node = null
	if pid2 != null and int(pid2) > 0:
		_node_for(int(pid2))   # 先确保父级节点已创建
		var pn = _nodes.get(int(pid2))
		if pn != null and pn is CanvasItem and not (pn is Node3D):
			parent2d = pn
	if parent2d != null:
		sp.position = Vector2(float(p0[1]), float(p0[2])) - _parent_anchor(L)
	else:
		sp.position = _ancestor_xform(L) * Vector2(float(p0[1]), float(p0[2]))
	sp.z_index = 100 - int(L["z"])

	var s0: Array = L["tracks"]["scale"][0]
	var sz2 := _solid_size(L)
	sp.scale = Vector2(float(s0[1]) * sz2.x, float(s0[2]) * sz2.y)
	var r0: Array = L["tracks"]["rotation"][0]
	sp.rotation = deg_to_rad(float(r0[1]))
	var al: Array = L["tracks"]["alpha"][0]
	var basec := Color(1.0, 1.0, 1.0) if sc2 == null else (sc2 as Color)
	sp.self_modulate = Color(basec.r, basec.g, basec.b, float(al[1]))

	_apply_blend2d(sp, L)
	sp.name = _base_name(String(L["name"]))
	_nodes[idx] = sp
	if parent2d != null:
		parent2d.add_child(sp)
		_parented2d[idx] = true
		sp.name = _unique_name(parent2d, String(sp.name), sp)
	else:
		host.add_child(sp)
		sp.name = _unique_name(host, String(sp.name), sp)
	return sp

func _solid_color(L: Dictionary) -> Variant:
	# 只有 type=solid 的图层才是"色块"；null 也可能是纯色源，但它是空物体
	if String(L.get("type", "")) != "solid":
		return null
	var a: Dictionary = L.get("asset", {})
	if a.has("color"):
		var c: Array = a["color"]
		return Color(float(c[0]), float(c[1]), float(c[2]), 1.0)
	return null


func _white_texture() -> Texture2D:
	if _white_tex == null:
		var img := Image.create(1, 1, false, Image.FORMAT_RGBA8)
		img.fill(Color.WHITE)
		_white_tex = ImageTexture.create_from_image(img)
	return _white_tex

func _solid_size(L: Dictionary) -> Vector2:
	if _solid_color(L) == null:
		return Vector2.ONE
	return Vector2(maxf(float(L["asset"]["width"]), 1.0), maxf(float(L["asset"]["height"]), 1.0))

func _blend_mode_for(mode: String) -> int:
	match mode.to_upper():
		"ADD", "LINEAR_DODGE", "LINEAR_LIGHT", "COLOR_DODGE":
			return CanvasItemMaterial.BLEND_MODE_ADD
		"MULTIPLY", "COLOR_BURN", "CLASSIC_COLOR_BURN":
			return CanvasItemMaterial.BLEND_MODE_MUL
		"SUBTRACT", "DIFFERENCE":
			return CanvasItemMaterial.BLEND_MODE_SUB
		_:
			return -1


const BLEND_SHADER_PATH := "res://addons/ae_motion/blend_screen.gdshader"

# 需要屏幕纹理的模式 → 着色器里的常量
const BLEND_SHADER_MODES := {
	"SCREEN": 1, "CLASSIC_SCREEN": 1, "OVERLAY": 2, "SOFT_LIGHT": 3, "HARD_LIGHT": 4,
	"COLOR_DODGE": 5, "COLOR_BURN": 6, "DIFFERENCE": 7, "EXCLUSION": 8,
	"DARKEN": 9, "DARKER_COLOR": 9, "LIGHTEN": 10, "LIGHTER_COLOR": 10, "VIVID_LIGHT": 11, "LINEAR_LIGHT": 12,
	"PIN_LIGHT": 13, "HARD_MIX": 14, "DIVIDE": 15, "LINEAR_BURN": 16,
}


func _apply_blend2d(n: Node, L: Dictionary) -> void:
	var blend: Dictionary = L.get("blend", {})
	var mode := String(blend.get("mode", "NORMAL")).to_upper()
	var role := String(blend.get("role", "normal"))

	# 第一档：Godot 内置混合，零开销
	var bm := _blend_mode_for(mode)
	if bm >= 0 and n is CanvasItem:
		var mat := CanvasItemMaterial.new()
		mat.blend_mode = bm
		(n as CanvasItem).material = mat
		_blend_applied.append("%s(%s)" % [String(L["name"]), mode])
		return

	# 第二档：需要底图的模式，走屏幕纹理着色器
	if BLEND_SHADER_MODES.has(mode) and n is CanvasItem:
		var sh: Shader = load(BLEND_SHADER_PATH)
		if sh == null:
			_blend_skipped.append("%s(%s,缺着色器)" % [String(L["name"]), mode])
			return
		var sm := ShaderMaterial.new()
		sm.shader = sh
		sm.set_shader_parameter("mode", int(BLEND_SHADER_MODES[mode]))
		(n as CanvasItem).material = sm

		# 该层之前必须有一次 BackBufferCopy，否则拿不到底图
		var parent := n.get_parent()
		if parent != null:
			var bb := BackBufferCopy.new()
			bb.name = "BBCopy_" + String(n.name)
			bb.copy_mode = BackBufferCopy.COPY_MODE_VIEWPORT
			parent.add_child(bb)
			parent.move_child(bb, n.get_index())
		_blend_applied.append("%s(%s,着色器)" % [String(L["name"]), mode])
		return

	if role != "normal":
		_blend_skipped.append("%s(%s)" % [String(L["name"]), mode])


func _blend_mode_for3(mode: String) -> int:
	match mode.to_upper():
		"ADD", "LINEAR_DODGE", "LINEAR_LIGHT", "COLOR_DODGE":
			return BaseMaterial3D.BLEND_MODE_ADD
		"MULTIPLY", "COLOR_BURN", "CLASSIC_COLOR_BURN":
			return BaseMaterial3D.BLEND_MODE_MUL
		"SUBTRACT", "DIFFERENCE":
			return BaseMaterial3D.BLEND_MODE_SUB
		_:
			return -1


func _apply_blend3(sp: Sprite3D, L: Dictionary) -> void:
	var blend: Dictionary = L.get("blend", {})
	var mode := String(blend.get("mode", "NORMAL"))
	var bm := _blend_mode_for3(mode)
	if bm < 0:
		if String(blend.get("role", "normal")) != "normal":
			_blend_skipped.append("%s(%s)" % [String(L["name"]), mode])
		return
	var mat := StandardMaterial3D.new()
	mat.albedo_texture = sp.texture
	mat.albedo_color = sp.modulate
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	mat.blend_mode = bm
	sp.material_override = mat
	_blend_applied.append("%s(%s)" % [String(L["name"]), mode])

func _parent_anchor(L: Dictionary) -> Vector2:
	var pid = L.get("parent")
	if pid == null or int(pid) <= 0:
		return Vector2.ZERO
	var P: Dictionary = _by_index.get(int(pid), {})
	if P.is_empty():
		return Vector2.ZERO
	var pa: Array = P.get("asset", {}).get("anchor", [0, 0])
	return Vector2(float(pa[0]), float(pa[1]))

func _build_mask_drivers() -> void:
	if _mask_drivers.is_empty():
		return
	# 用 SubViewport + Polygon2D 把蒙版画成纹理：着色器只采一次，成本与点数无关
	var holder := Node2D.new()
	holder.name = "Masks"
	_root.add_child(holder)
	for d in _mask_drivers:
		var m: Dictionary = d["mask"]
		var frames: Array = m.get("compFrames", m.get("frames", []))
		if frames.is_empty():
			continue
		var vp := SubViewport.new()
		vp.name = _unique_name(holder, _base_name(String(d["layer"])), null)
		# 遮罩视口用半分辨率：边缘略软，开销降到 1/4
		vp.size = Vector2i(int(_comp_size.x * 0.5), int(_comp_size.y * 0.5))
		vp.transparent_bg = true
		vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
		vp.set_script(load("res://addons/ae_motion/mask_rig.gd"))
		vp.set("frames", frames)
		vp.set("comp_size", _comp_size)
		var poly := Polygon2D.new()
		poly.name = "MaskPoly"
		poly.color = Color(1, 1, 1, 1)
		vp.add_child(poly)
		holder.add_child(vp)
		_mask_applied.append("%s → %s" % [String(d["layer"]), vp.name])

## 从 "转场_[00000-00025].png" 里取出 "转场_"，不是序列就返回空串
func _sequence_prefix(layer_name: String) -> String:
	var bracket := layer_name.find("[")
	if bracket <= 0:
		return ""
	var close := layer_name.find("]", bracket)
	if close < 0:
		return ""
	var inner := layer_name.substr(bracket + 1, close - bracket - 1)
	if inner.find("-") < 0:
		return ""
	var prefix := layer_name.substr(0, bracket)
	if prefix.strip_edges() == "":
		return ""
	return prefix


## 在素材目录里递归找 <prefix><数字>.png，按数字排序后返回路径数组
func _find_sequence(prefix: String) -> Array:
	var found: Array = []
	_scan_sequence_dir(_art_dir, prefix, found)
	found.sort_custom(func(a, b): return str(a).naturalnocasecmp_to(str(b)) < 0)
	return found


func _scan_sequence_dir(dir_path: String, prefix: String, out: Array) -> void:
	var dir := DirAccess.open(dir_path)
	if dir == null:
		return
	dir.list_dir_begin()
	var f := dir.get_next()
	while f != "":
		if dir.current_is_dir():
			if not f.begins_with("."):
				_scan_sequence_dir(dir_path.path_join(f), prefix, out)
		else:
			var lower := f.to_lower()
			if lower.ends_with(".png") and f.begins_with(prefix):
				out.append(dir_path.path_join(f))
		f = dir.get_next()
	dir.list_dir_end()

## "转场_[00000-00025].png" → 26；解析不出来返回 0
func _sequence_frame_count(layer_name: String) -> int:
	var bracket := layer_name.find("[")
	if bracket < 0:
		return 0
	var close := layer_name.find("]", bracket)
	if close < 0:
		return 0
	var inner := layer_name.substr(bracket + 1, close - bracket - 1)
	var dash := inner.find("-")
	if dash < 0:
		return 0
	var a := int(inner.substr(0, dash))
	var b := int(inner.substr(dash + 1))
	if b < a:
		return 0
	return b - a + 1

## UI 贴图在「导入」阶段就规范成 无损 + 无 mipmap + 不做 3D 自动压缩。
## 原因：VRAM 压缩是 BPTC（4×4 块），半透明边缘和不透明色块会在同一个块里被平均，
## 在 Sprite3D 被相机缩放采样时表现为「接壤处多出一层块状色带」。
## 这里直接改写 .import（一次性、可重复），而不是导完再去改场景/贴图。
func _ensure_lossless(tex_path: String) -> void:
	var imp := tex_path + ".import"
	if not FileAccess.file_exists(imp):
		return
	var rf := FileAccess.open(imp, FileAccess.READ)
	if rf == null:
		return
	var txt := rf.get_as_text()
	rf.close()
	var out := txt
	out = out.replace("compress/mode=2", "compress/mode=0")   # VRAM(BPTC) -> 无损
	out = out.replace("compress/mode=4", "compress/mode=0")   # Basis Universal -> 无损
	out = out.replace("mipmaps/generate=true", "mipmaps/generate=false")
	out = out.replace("detect_3d/compress_to=1", "detect_3d/compress_to=0")
	if out == txt:
		return
	var wf := FileAccess.open(imp, FileAccess.WRITE)
	if wf == null:
		return
	wf.store_string(out)
	wf.close()
	_tex_fixed.append(tex_path.get_file())
	if Engine.is_editor_hint():
		var efs := EditorInterface.get_resource_filesystem()
		if efs != null:
			efs.update_file(tex_path)

