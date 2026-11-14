@tool
extends VBoxContainer
##
## 面板：选 JSON / 选素材目录 / 选输出场景 → 点"生成"
##

var _json_edit: LineEdit
var _art_edit: LineEdit
var _frames_edit: LineEdit
var _segments: LineEdit
var _merge_check: CheckBox
var _merge_parent: LineEdit
var _out_edit: LineEdit
var _log: TextEdit
var _open_after: CheckBox
var _dlg: EditorFileDialog
var _target := ""
var _busy := false


func _ready() -> void:
	custom_minimum_size = Vector2(360, 220)
	add_theme_constant_override("separation", 6)
	_build_ui()


func _build_ui() -> void:
	var title := Label.new()
	title.text = "AE Motion → 场景"
	add_child(title)

	_json_edit = _row("AE 导出的 json", _browse_json)
	_art_edit = _row("素材目录（项目内）", _browse_art)
	_frames_edit = _row("序列帧目录（可选）", _browse_frames)

	var seg_box := VBoxContainer.new()
	var seg_label := Label.new()
	seg_label.text = "分段（名称:起帧-止帧，带 * 为循环）"
	seg_box.add_child(seg_label)
	_segments = LineEdit.new()
	_segments.placeholder_text = "留空=整段一条；填帧号，例 intro:0-24; idle:24-240*"
	seg_box.add_child(_segments)
	add_child(seg_box)
	_out_edit = _row("输出场景（项目内）", _browse_out)

	var opts := HBoxContainer.new()
	_open_after = CheckBox.new()
	_open_after.text = "生成后打开"
	_open_after.button_pressed = true
	opts.add_child(_open_after)
	add_child(opts)

	var merge_box := VBoxContainer.new()
	_merge_check = CheckBox.new()
	_merge_check.text = "合并进当前打开的场景（不新建文件）"
	merge_box.add_child(_merge_check)
	_merge_parent = LineEdit.new()
	_merge_parent.placeholder_text = "父节点路径，留空=挂到场景根"
	merge_box.add_child(_merge_parent)
	add_child(merge_box)

	var run := Button.new()
	run.text = "生成场景"
	run.pressed.connect(_run)
	add_child(run)

	_log = TextEdit.new()
	_log.editable = false
	_log.custom_minimum_size = Vector2(0, 160)
	_log.wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY
	add_child(_log)

	_dlg = EditorFileDialog.new()
	_dlg.access = EditorFileDialog.ACCESS_FILESYSTEM
	_dlg.file_mode = EditorFileDialog.FILE_MODE_OPEN_FILE
	add_child(_dlg)
	_dlg.file_selected.connect(_on_file_selected)
	_dlg.dir_selected.connect(_on_dir_selected)


func _row(label_text: String, cb: Callable) -> LineEdit:
	var box := VBoxContainer.new()
	var l := Label.new()
	l.text = label_text
	box.add_child(l)
	var h := HBoxContainer.new()
	var edit := LineEdit.new()
	edit.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	edit.placeholder_text = "点右边按钮选择"
	h.add_child(edit)
	var b := Button.new()
	b.text = "…"
	b.pressed.connect(cb)
	h.add_child(b)
	box.add_child(h)
	add_child(box)
	return edit


func _browse_json() -> void:
	_target = "json"
	_dlg.access = EditorFileDialog.ACCESS_FILESYSTEM
	_dlg.file_mode = EditorFileDialog.FILE_MODE_OPEN_FILE
	_dlg.clear_filters()
	_dlg.add_filter("*.json", "AE Motion JSON")
	var cur := _json_edit.text.strip_edges()
	if cur != "":
		_dlg.current_dir = cur.get_base_dir()
	_dlg.popup_centered_ratio(0.5)


func _browse_art() -> void:
	_target = "art"
	_dlg.access = EditorFileDialog.ACCESS_RESOURCES
	_dlg.file_mode = EditorFileDialog.FILE_MODE_OPEN_DIR
	_dlg.clear_filters()
	if _art_edit.text.strip_edges() != "":
		_dlg.current_dir = _art_edit.text.strip_edges()
	_dlg.popup_centered_ratio(0.5)


func _browse_frames() -> void:
	_target = "frames"
	_dlg.access = EditorFileDialog.ACCESS_RESOURCES
	_dlg.file_mode = EditorFileDialog.FILE_MODE_OPEN_DIR
	_dlg.clear_filters()
	if _frames_edit.text.strip_edges() != "":
		_dlg.current_dir = _frames_edit.text.strip_edges()
	elif _art_edit.text.strip_edges() != "":
		_dlg.current_dir = _art_edit.text.strip_edges()
	_dlg.popup_centered_ratio(0.5)


func _browse_out() -> void:
	_target = "out"
	_dlg.access = EditorFileDialog.ACCESS_RESOURCES
	_dlg.file_mode = EditorFileDialog.FILE_MODE_SAVE_FILE
	_dlg.clear_filters()
	_dlg.add_filter("*.tscn", "Godot 场景")
	if _out_edit.text.strip_edges() == "":
		_dlg.current_dir = "res://generated"
	_dlg.popup_centered_ratio(0.5)


func _on_file_selected(path: String) -> void:
	match _target:
		"json":
			_json_edit.text = path
			if _out_edit.text.strip_edges() == "":
				var base := path.get_file().get_basename()
				_out_edit.text = "res://generated/%s.tscn" % _safe(base)
		"out":
			_out_edit.text = path


func _on_dir_selected(path: String) -> void:
	if _target == "art":
		_art_edit.text = path
		if _frames_edit.text.strip_edges() == "":
			_frames_edit.text = path.path_join("Frames")
	elif _target == "frames":
		_frames_edit.text = path




func _run() -> void:
	if _busy:
		return
	var j := _json_edit.text.strip_edges()
	var a := _art_edit.text.strip_edges()
	var o := _out_edit.text.strip_edges()
	if j == "" or a == "" or o == "":
		_log.text = "三项都选好才会生成。"
		return

	_busy = true
	_log.text = "生成中…"
	# 先扫一遍，让新放进去的 PNG 有机会被导入
	EditorInterface.get_resource_filesystem().scan()
	var b = load("res://addons/ae_motion/ae_builder.gd").new()
	var fdir := _frames_edit.text.strip_edges()
	var segs := _segments.text.strip_edges()
	var target: Node = null
	if _merge_check.button_pressed:
		var scene := EditorInterface.get_edited_scene_root()
		if scene == null:
			_log.text = "没有打开的场景，先把主场景打开再勾选合并。"
			_busy = false
			return
		target = scene
		var parent_path := _merge_parent.text.strip_edges()
		if parent_path != "":
			target = scene.get_node_or_null(NodePath(parent_path))
			if target == null:
				_log.text = "找不到父节点：" + parent_path
				_busy = false
				return

	var res: Dictionary = b.build(j, a, o, fdir, segs, target)
	if target != null and res.get("ok", false):
		EditorInterface.mark_scene_as_unsaved()
	var text := ""
	for line in res.get("lines", []):
		text += String(line) + "\n"
	_log.text = text
	_busy = false

	if res.get("ok", false) and target == null:
		EditorInterface.get_resource_filesystem().scan()
		if _open_after.button_pressed:
			EditorInterface.open_scene_from_path(o)


func _safe(s: String) -> String:
	var out := s
	for ch in [".", ":", "@", "/", "\\", "\"", "%"]:
		out = out.replace(ch, "_")
	return out
