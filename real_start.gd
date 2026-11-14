# 真初始场景 —— 交互总控（一级菜单 / 二级「进入房间」）
#
# 一级（刚打开）：人物12/3/4/5 悬停切标题 + 黄框，点人物12 进二级。
# 二级（合成 1）：播 intro→idle（循环），idle 后搜索框可输入数字；点【进入】播 outro 后停；
#                 任何时候按右键 → 倒放 intro 回一级。
#
# 动画全部由你做好并挂在两个 AnimationPlayer 上：
#   背景 2/AnimationPlayer ： intro(14.35s) → idle(15s loop)   ← AutoSequence 自动串，不动
#   合成 1/AnimationPlayer ： intro(0.667s) → idle(3.33s loop) → outro(0.15s)
# 这里只负责「什么时候 play 哪一段」，不写任何轨道的值。
extends Node2D

const GALLERY_SCENE := "res://鉴赏.tscn"
const TRANS_MASK_PATH := "只差遮罩/Masks/鉴赏蒙版"
const TRANS_SEQ_PATH := "只差遮罩/转场_[00000-00025]"
const Wipe := preload("res://transition_wipe.gd")
# 2026-11-11：效果根节点在编辑器里被改名（背景 2 → 背景和人物，合成 1 → 搜索框），
# 这里用候选名单 + 特征兜底找，避免再改名就整套播放/交互失效。
const STAGE_CANDIDATES := ["背景和人物", "背景 2"]     # 一级动画场景实例
const STAGE2_CANDIDATES := ["搜索框", "合成 1"]        # 二级动画（3D 星光 + 左右护法 + Sprites2D后）
const SETTINGS_CANDIDATES := ["设置", "设置2", "设置3"]                   # 【设置】面板（一个 30s 的 play，关键帧 60fps）

# 【设置】面板的帧口径（用户 2026-11-11：0→35 弹出定格 / 67→229 登入）
const SETTINGS_FPS := 60.0
const SETTINGS_T_FULL := 35.0 / 60.0      # 0.5833s：弹出完成，输入框出现
const SETTINGS_T_INTRO := 40.0 / 60.0     # 0.6667s：intro 段长度（= 导入器切的 intro）
const SETTINGS_T_LOOP := 1.6666667        # idle 段长度（AE 40→140 帧，只驱动左右护法 rotation）
const SETTINGS_T_LOGIN := 3.05            # login 段（AE 67→250 帧）：登入成功进来又出去
# 输入框（35 帧定格那一帧量出来的位置，1920x1080 设计空间）
const SETTINGS_INPUT_RECT := Rect2(790.0, 577.0, 277.0, 37.0)
const ROOM_INPUT_RECT := Rect2(777.0, 571.0, 319.0, 47.0)   # 二级「搜索框」白条内区（3D 投影实测）

const HOVER := {
	"人物12": "开始游戏",
	"人物3": "设置",
	"人物4": "鉴赏",
	"人物5": "鸣谢",
}


# 黄框：自绘「较粗」方框（金黄、6px）
class FrameDraw:
	extends Node2D
	var frame := Rect2()
	var shown := false
	var color := Color(1.0, 0.83, 0.48, 1.0)
	var width := 6.0

	func set_rect(r: Rect2) -> void:
		frame = r
		shown = true
		queue_redraw()

	func clear_rect() -> void:
		if not shown:
			return
		shown = false
		queue_redraw()

	func _draw() -> void:
		if shown:
			draw_rect(frame.grow(width * 0.5), color, false, width)


var _frame: Node2D = null
var _chars: Dictionary = {}
var _titles: Dictionary = {}
var _hover := ""

var _stage2: Node = null
var _stage2_layers: Array = []
var _ap2: AnimationPlayer = null
var _cam3d: Camera3D = null
var _enter3d: Sprite3D = null
var _arrow3d: Sprite3D = null
var _search: LineEdit = null

# 1 = 一级菜单　2 = 二级（已进入）　3 = 正在退出二级（倒放 intro）
var _state := 1
var _search_ready := false
var _rewind_t := 0.0          # 倒放位置（秒）
var _rewind_speed := 1.0      # 倒放倍速（按 intro 长度算，让人感觉是原速倒退）

# ── 【设置】面板 ──
var _settings: Node = null
var _settings_layers: Array = []
var _ap_s: AnimationPlayer = null
var _cam_s: Camera3D = null
var _vp2: SubViewport = null          # 二级「搜索框」的 3D 视口
var _vp_s: SubViewport = null          # 设置面板的 3D 视口
var _login3d: Sprite3D = null
var _settings_search: LineEdit = null
var _settings_ready := false          # 定格完成 → 【登入】可点
var _settings_phase := 0              # 0 空闲 / 1 弹出中 / 2 定格 / 3 登入中 / 4 倒放退出
var _settings_rewind_t := 0.0

var _gallery_ps: PackedScene = null
var _gallery_req := false
var _lobby: Node = null
var _lobby_layer: CanvasLayer = null
var _lobby_on := false
var _going := false


func _ready() -> void:
	_setup_level1()
	_setup_level2()
	_setup_settings()
	_setup_lobby()
	# 鉴赏：46 张卡，提前预加载，点【人物4】时几乎瞬间可切（转场动画不卡）
	_gallery_req = (ResourceLoader.load_threaded_request(GALLERY_SCENE, "PackedScene") == OK)
	print("[真初始场景] 一级人物 %d / 标题 %d　二级=%s　设置=%s　预加载=%s" % [
		_chars.size(), _titles.size(), str(_ap2 != null), str(_ap_s != null), str(_lobby != null)])


# 效果根节点解析：先按候选名找，再按「有 AnimationPlayer 且含特征子节点」兜底
func _find_stage(candidates: Array, must_have: String) -> Node:
	for nm in candidates:
		var n := get_node_or_null(String(nm))
		if n != null and n != self:
			return n
	if must_have != "":
		for c in get_children():
			if c == self or c.get_node_or_null("AnimationPlayer") == null:
				continue
			if c.find_child(must_have, true, false) != null:
				return c
	return null


func _setup_level1() -> void:
	var stage := _find_stage(STAGE_CANDIDATES, "人物12")
	if stage == null:
		push_warning("真初始场景：找不到一级动画根节点 %s" % str(STAGE_CANDIDATES))
		stage = self
	for nm in HOVER.keys():
		var sp := stage.find_child(String(nm), true, false) as Sprite2D
		if sp != null:
			_chars[nm] = sp
		var ti := stage.find_child(String(HOVER[nm]), true, false) as CanvasItem
		if ti != null:
			_titles[String(HOVER[nm])] = ti
			ti.visible = false
	_frame = FrameDraw.new()
	_frame.name = "HoverFrame"
	_frame.z_index = 100
	add_child(_frame)


func _setup_level2() -> void:
	_stage2 = _find_stage(STAGE2_CANDIDATES, "进入")
	if _stage2 == null:
		push_warning("真初始场景：找不到二级动画根节点 %s" % str(STAGE2_CANDIDATES))
		return
	# CanvasLayer 不受父 Node2D 的 visible 影响 → 逐个隐藏
	for c in _stage2.get_children():
		if c is CanvasLayer:
			(c as CanvasLayer).visible = false
			_stage2_layers.append(c)
	_ap2 = _stage2.get_node_or_null("AnimationPlayer") as AnimationPlayer
	if _ap2 != null:
		# 断开 AutoSequence（它会在 _ready 自动 play 并自动串段）→ 改由这里控制
		for conn in _ap2.animation_finished.get_connections():
			_ap2.animation_finished.disconnect(conn.callable)
		_ap2.animation_finished.connect(_on_ap2_finished)
		# 停在第 0 帧，别让二级内容提前出现在画面上
		_ap2.play("intro")
		_ap2.seek(0.0, true)
		_ap2.pause()
	_vp2 = _stage2.get_node_or_null("3D画面/3D容器/3D视口") as SubViewport
	if _vp2 != null:
		_vp2.render_target_update_mode = SubViewport.UPDATE_DISABLED
	_cam3d = _stage2.find_child("Camera3D", true, false) as Camera3D
	_enter3d = _stage2.find_child("进入", true, false) as Sprite3D
	_arrow3d = _stage2.find_child("小箭头", true, false) as Sprite3D
	_make_search_box()


# 搜索框（房间号）：位置/大小用 3D 投影实测值（ROOM_INPUT_RECT），不再用 Label 的 rect
func _make_search_box() -> void:
	# 位置/尺寸 = 3D 投影出来的白条内区（2296×1292 截图实测，设计空间 1920×1080）。
	# 以前拿 Label 的 rect（338×48）：比白条宽 19、高 3，而且 font 0.78 会把最小高撑到 59，
	# size 设不进去 → 文字又大又偏下。
	var r := ROOM_INPUT_RECT
	var cl := CanvasLayer.new()
	cl.name = "SearchLayer"
	cl.layer = 10
	add_child(cl)
	_search = LineEdit.new()
	_search.name = "RoomSearch"
	_search.position = r.position
	_search.size = r.size
	_search.visible = false
	_search.editable = false
	_search.max_length = 8
	# 用户口径 2026-11-11：从左往右输入 / 不要黄框 / 不要闪动光标
	_search.alignment = HORIZONTAL_ALIGNMENT_LEFT
	_search.add_theme_font_size_override("font_size", int(maxf(r.size.y * 0.55, 14.0)))
	_search.add_theme_color_override("font_color", Color(0.16, 0.10, 0.04, 1.0))
	_search.add_theme_color_override("caret_color", Color(0, 0, 0, 0))   # 光标全透明
	if "caret_blink" in _search:
		_search.set("caret_blink", false)
	# 底 / 边框都清空（连获得焦点时也不画）
	var sb := StyleBoxEmpty.new()
	sb.content_margin_left = 8.0
	sb.content_margin_right = 6.0
	_search.add_theme_stylebox_override("normal", sb)
	_search.add_theme_stylebox_override("focus", sb)
	_search.text_changed.connect(_on_search_typed)
	cl.add_child(_search)


func _on_search_typed(t: String) -> void:
	# 用户口径 2026-11-13：房间号可以是字母 + 数字
	var d := ""
	for i in t.length():
		var c := t.unicode_at(i)
		var ok := (c >= 48 and c <= 57) or (c >= 65 and c <= 90) or (c >= 97 and c <= 122)
		if ok:
			d += t[i]
	if d != t:
		_search.set_text(d)
		_search.caret_column = d.length()


# ── 一级菜单 ────────────────────────────────────────────────
# ── 【设置】面板（generated/设置.tscn 的 3D 登录界面）────────
func _setup_settings() -> void:
	var st := _find_stage(SETTINGS_CANDIDATES, "登入")
	if st == null:
		push_warning("真初始场景：找不到设置面板 %s" % str(SETTINGS_CANDIDATES))
		return
	_settings = st
	# CanvasLayer 不受父 Node2D 的 visible 影响 → 逐个隐藏
	for c in st.get_children():
		if c is CanvasLayer:
			(c as CanvasLayer).visible = false
			_settings_layers.append(c)
	_ap_s = st.get_node_or_null("AnimationPlayer") as AnimationPlayer
	if _ap_s != null:
		_ap_s.play("intro")
		_ap_s.seek(0.0, true)
		_ap_s.pause()
	_vp_s = st.get_node_or_null("3D画面/3D容器/3D视口") as SubViewport
	if _vp_s != null:
		_vp_s.render_target_update_mode = SubViewport.UPDATE_DISABLED
	_cam_s = st.find_child("Camera3D", true, false) as Camera3D
	_login3d = st.find_child("登入", true, false) as Sprite3D
	_make_settings_box()


func _make_settings_box() -> void:
	var cl := CanvasLayer.new()
	cl.name = "SettingsLayer"
	cl.layer = 20
	add_child(cl)
	_settings_search = LineEdit.new()
	_settings_search.name = "AccountInput"
	_settings_search.position = SETTINGS_INPUT_RECT.position
	_settings_search.size = SETTINGS_INPUT_RECT.size
	_settings_search.visible = false
	_settings_search.editable = false
	_settings_search.max_length = 24
	# 用户口径 2026-11-11（与房间号输入框一致）：左对齐 / 不要黄框 / 不要闪动光标
	_settings_search.alignment = HORIZONTAL_ALIGNMENT_LEFT
	_settings_search.add_theme_font_size_override("font_size", int(maxf(SETTINGS_INPUT_RECT.size.y * 0.55, 14.0)))
	_settings_search.add_theme_color_override("font_color", Color(0.16, 0.10, 0.04, 1.0))
	_settings_search.add_theme_color_override("caret_color", Color(0, 0, 0, 0))
	if "caret_blink" in _settings_search:
		_settings_search.set("caret_blink", false)
	var sb := StyleBoxEmpty.new()
	sb.content_margin_left = 8.0
	sb.content_margin_right = 6.0
	_settings_search.add_theme_stylebox_override("normal", sb)
	_settings_search.add_theme_stylebox_override("focus", sb)
	_settings_search.text_changed.connect(_on_settings_typed)
	_settings_search.text_submitted.connect(_on_settings_submitted)
	cl.add_child(_settings_search)


func _on_settings_typed(t: String) -> void:
	# 用户口径 2026-11-13：账号可以是汉字 + 字母 + 数字
	var d := ""
	for i in t.length():
		var c := t.unicode_at(i)
		var ok := (c >= 48 and c <= 57) or (c >= 65 and c <= 90) or (c >= 97 and c <= 122) \
			or (c >= 0x4E00 and c <= 0x9FFF) or (c >= 0x3400 and c <= 0x4DBF) or (c >= 0xF900 and c <= 0xFAFF)
		if ok:
			d += t[i]
	if d != t:
		_settings_search.set_text(d)
		_settings_search.caret_column = d.length()


func _on_settings_submitted(_t: String) -> void:
	# 回车 = 点【登入】（跟搜索框的点【进入】同一个出口）
	_play_settings_login()


func _set_settings_search(on: bool) -> void:
	if _settings_search == null:
		return
	_settings_search.visible = on
	_settings_search.editable = on
	if on:
		_settings_search.grab_focus()
	else:
		# ★ 同步 release_focus() 会立刻关掉 Windows 输入法窗口（点【登入】那次卡顿多半是它），
		#   延到下一帧关，点击这一帧就不卡了。
		_settings_search.call_deferred("release_focus")


# 点【设置】：0 → 35 帧弹出，定格进二级
func _enter_settings() -> void:
	if _state != 1 or _ap_s == null:
		return
	_state = 4
	_settings_phase = 1
	_settings_ready = false
	_apply_hover("")
	_hide_settings_leaving(false)
	var _b2 := _settings.find_child("登入成功", true, false) as Sprite2D
	if _b2 != null:
		_b2.position.y = -598.0
	for l in _settings_layers:
		(l as CanvasLayer).visible = true
	_set_settings_search(false)
	_ap_s.speed_scale = 1.0
	if _vp_s != null:
		_vp_s.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	_ap_s.play("intro")
	_ap_s.seek(0.0, true)


func _tick_settings(dt: float) -> void:
	if _ap_s == null:
		return
	# ① 逆 intro 退场（右键）：按真实时间从 0.667s 倒回 0
	if _settings_phase == 4:
		_settings_rewind_t -= dt
		if _settings_rewind_t <= 0.0:
			_ap_s.seek(0.0, true)
			_ap_s.pause()
			_finish_settings()
			return
		_ap_s.seek(_settings_rewind_t, true)
		return
	# ② 登入段播完：AE 末帧窗口已转走、黑幕已退干净 —— 直接回一级，不再补一次退场
	if _settings_phase == 3:
		if _ap_s.current_animation != "login" or _ap_s.current_animation_position >= SETTINGS_T_LOGIN - 0.001:
			_finish_settings()
		return
	var t := _ap_s.current_animation_position
	var cur := _ap_s.current_animation
	if _settings_phase == 1 and t >= SETTINGS_T_FULL:
		# 0→35 帧：输入框出现（intro 继续播到 40 帧）
		_settings_phase = 2
		_settings_ready = true
		_set_settings_search(true)
	elif _settings_phase == 2:
		# intro 播完（结束时 current_animation 会被清空，所以用 position 判）
		# → 接 idle：左右护法一直摇摆（1.6667s loop，只驱动 rotation）
		if cur != "idle" and t >= SETTINGS_T_INTRO - 0.0005:
			_ap_s.play("idle")
## 面板复位（进场时把 self_modulate 恢复；3D 窗口不隐藏，交给逆 intro 转走）
func _hide_settings_leaving(on: bool) -> void:
	if _settings == null or on:
		return
	var panel := _settings.get_node_or_null("2D层/Sprites2D/软萌星空登录界面 null") as Sprite2D
	if panel == null:
		return
	panel.position.y = 540.0
	panel.self_modulate.a = 1.0


func _play_settings_login() -> void:
	if _state != 4 or _ap_s == null or not _settings_ready:
		return
	if _settings_phase == 3 or _settings_phase == 4:
		return
	_settings_ready = false
	_set_settings_search(false)
	# 登入段 = AE 67→250 帧（3.05s）：3D 窗口转走 / 黑幕退掉 / 登入成功 从顶部滑进来
	if not _ap_s.has_animation("login"):
		push_warning("设置：AnimationPlayer 里没有 login，直接回一级")
		_finish_settings()
		return
	_ap_s.speed_scale = 1.0
	_ap_s.play("login")
	_settings_phase = 3


func _exit_settings() -> void:
	if _state != 4 or _ap_s == null:
		return
	_settings_ready = false
	_settings_phase = 4
	_set_settings_search(false)
	# 没有 outro：退回一级就是 intro 的逆动画。
	# 停在 idle 定格态时先切回 intro 末帧（40 帧）再倒放，接缝只有 20 帧的姿态差。
	if _ap_s.current_animation != "intro":
		_ap_s.play("intro")
		_ap_s.seek(SETTINGS_T_INTRO, true)
	_settings_rewind_t = _ap_s.current_animation_position
	_ap_s.pause()


func _finish_settings() -> void:
	var _b := _settings.find_child("登入成功", true, false) as Sprite2D
	if _b != null:
		_b.position.y = -598.0
	_set_settings_search(false)
	if _settings_search != null:
		_settings_search.set_text("")
	if _ap_s != null:
		_ap_s.play("intro")
		_ap_s.seek(0.0, true)
		_ap_s.pause()
	for l in _settings_layers:
		(l as CanvasLayer).visible = false
	if _vp_s != null:
		_vp_s.render_target_update_mode = SubViewport.UPDATE_DISABLED
	_settings_ready = false
	_settings_phase = 0
	_state = 1


# 点【登入】：按 3D 投影算屏幕矩形（跟搜索框的 _hit_enter3d 同一套换算）
func _hit_settings_login(mp: Vector2) -> bool:
	if _login3d == null or _cam_s == null or _login3d.texture == null:
		return false
	var sz := Vector2(_login3d.texture.get_size()) * _login3d.pixel_size
	var tl := _login3d.offset
	var xf := _login3d.global_transform
	var pts: Array = []
	for p in [tl, tl + Vector2(sz.x, 0.0), tl + Vector2(0.0, sz.y), tl + sz]:
		var w: Vector3 = xf * Vector3(p.x, -p.y, 0.0)
		pts.append(_cam_s.unproject_position(w))
	if pts.is_empty():
		return false
	var r := Rect2(pts[0], Vector2.ZERO)
	for i in range(1, pts.size()):
		r = r.expand(pts[i])
	var vs := _cam_s.get_viewport().get_visible_rect().size
	if vs.x > 1.0 and vs.y > 1.0:
		var sc := get_viewport_rect().size / vs
		r = Rect2(r.position * sc, r.size * sc)
	return r.has_point(mp)


func _process(_dt: float) -> void:
	if _going:
		return                              # 转场中：冻结一级交互
	if _state == 3:
		_tick_rewind(_dt)
		return
	if _state == 4:
		_tick_settings(_dt)
		if _hover != "":
			_apply_hover("")
		return
	if _state != 1:
		if _hover != "":
			_apply_hover("")
		return
	var mp := get_global_mouse_position()
	var hit := ""
	for nm in _chars.keys():
		if _world_rect(_chars[nm]).has_point(mp):
			hit = String(nm)
			break
	if hit != _hover:
		_apply_hover(hit)
	if _hover != "" and _frame != null:
		_frame.call("set_rect", _world_rect(_chars[_hover]))


func _world_rect(sp: Sprite2D) -> Rect2:
	if sp == null or not is_instance_valid(sp) or sp.texture == null:
		return Rect2()
	var sz := sp.texture.get_size()
	var xf := sp.global_transform
	var a := sp.offset
	if sp.centered:
		a -= sz * 0.5
	var p0 := xf * a
	var p1 := xf * (a + Vector2(sz.x, 0.0))
	var p2 := xf * (a + Vector2(0.0, sz.y))
	var p3 := xf * (a + sz)
	return Rect2(p0, Vector2.ZERO).expand(p1).expand(p2).expand(p3)


func _apply_hover(nm: String) -> void:
	_hover = nm
	var want := String(HOVER.get(nm, ""))
	for k in _titles.keys():
		var ti: CanvasItem = _titles[k]
		if ti != null and is_instance_valid(ti):
			ti.visible = (String(k) == want)
	if _frame == null:
		return
	if nm == "":
		_frame.call("clear_rect")
	else:
		var sp: Sprite2D = _chars.get(nm)
		if sp != null:
			_frame.call("set_rect", _world_rect(sp))


# ── 二级菜单 ────────────────────────────────────────────────
func _enter_level2() -> void:
	if _state != 1 or _ap2 == null:
		return
	_state = 2
	_search_ready = false
	_apply_hover("")
	for l in _stage2_layers:
		(l as CanvasLayer).visible = true
	_ap2.speed_scale = 1.0
	if _vp2 != null:
		_vp2.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	_ap2.play("intro")


func _on_ap2_finished(nm: String) -> void:
	if _state == 3:
		return                                # 正在倒放退出，由 _exit_level2 收尾
	if nm == "intro" and _state == 2:
		_ap2.play("idle")                     # 循环
		_set_search(true)
	elif nm == "outro":
		# ★ 停在最后一帧：不能 stop()（它会把属性重置回动画开头 → 看起来「播完又退回」）
		_ap2.pause()
		_ap2.seek(_ap2.get_animation("outro").length, true)
		_set_search(false)
		_begin_lobby()


func _set_search(on: bool) -> void:
	_search_ready = on
	if _search == null:
		return
	_search.visible = on
	_search.editable = on
	if on:
		_search.grab_focus()
	else:
		_search.release_focus()


# 右键：把二级「退回去」= 逆向播 intro。
# ★ 不用 AnimationPlayer 的反向播放：seek 到末尾后 speed=-1，它会在下一次 tick
#   立刻判 finished 并停住（实机表现就是「动画没倒放、框直接消失」）。
#   改成 pause + 每帧手动 seek：位置从 intro 末尾退到 0，属性值就真的往回走。
func _exit_level2() -> void:
	if _state != 2 or _ap2 == null:
		return
	_state = 3
	_set_search(false)
	_apply_hover("")
	_rewind_len = _ap2.get_animation("intro").length if _ap2.has_animation("intro") else 0.0
	_rewind_t = _rewind_len
	_rewind_speed = 1.0
	_ap2.speed_scale = 1.0
	_ap2.play("intro")
	_ap2.seek(_rewind_len, true)
	_ap2.pause()                              # 位置改由 _tick_rewind 驱动
	if _rewind_len <= 0.001:
		_finish_exit()


var _rewind_len := 0.0


func _tick_rewind(dt: float) -> void:
	_rewind_t -= dt * maxf(_rewind_speed, 0.05)
	if _rewind_t <= 0.0:
		_ap2.seek(0.0, true)
		_finish_exit()
		return
	_ap2.seek(_rewind_t, true)


func _finish_exit() -> void:
	if _ap2 != null:
		_set_hufa_idle(false)          # 先停护法循环，再 seek(0) 把姿态还原
		_ap2.pause()
		_ap2.seek(0.0, true)
		_ap2.speed_scale = 1.0
	for l in _stage2_layers:
		(l as CanvasLayer).visible = false
	if _vp2 != null:
		_vp2.render_target_update_mode = SubViewport.UPDATE_DISABLED
	_state = 1


func _unhandled_input(ev: InputEvent) -> void:
	if ev is InputEventMouseButton:
		var mb := ev as InputEventMouseButton
		if mb.button_index == MOUSE_BUTTON_RIGHT and mb.pressed:
			if _state == 2:
				# 已经在房间里 → 不许右键退回二级面板（要退出请点左上角「跳过」）
				if not _lobby_on:
					_exit_level2()
			elif _state == 4:
				_exit_settings()
			return
		if mb.button_index != MOUSE_BUTTON_LEFT or not mb.pressed:
			return
		if _state == 1:
			if _hover == "人物12":
				_enter_level2()
			elif _hover == "人物3":
				_enter_settings()
			elif _hover == "人物4":
				_go_gallery()
			return
		if _state == 2 and _search_ready and _hit_enter3d(get_viewport().get_mouse_position()):
			_play_outro()
		elif _state == 4 and _settings_ready and _hit_settings_login(get_viewport().get_mouse_position()):
			_play_settings_login()


# 点【进入】：按 3D 投影算屏幕矩形（3D 位置一改，这里自动跟随）
func _hit_enter3d(mp: Vector2) -> bool:
	if _enter3d == null or _cam3d == null:
		return false
	if _enter3d.texture == null:
		return false
	var sz := Vector2(_enter3d.texture.get_size()) * _enter3d.pixel_size
	var tl := _enter3d.offset
	var xf := _enter3d.global_transform
	var pts: Array = []
	for p in [tl, tl + Vector2(sz.x, 0.0), tl + Vector2(0.0, sz.y), tl + sz]:
		var w: Vector3 = xf * Vector3(p.x, -p.y, 0.0)
		pts.append(_cam3d.unproject_position(w))
	if pts.is_empty():
		return false
	var r := Rect2(pts[0], Vector2.ZERO)
	for i in range(1, pts.size()):
		r = r.expand(pts[i])
	# SubViewport 坐标 → 屏幕坐标（3D容器 1920x1080 stretch 铺满）
	var vs := _cam3d.get_viewport().get_visible_rect().size
	if vs.x > 1.0 and vs.y > 1.0:
		var sc := get_viewport_rect().size / vs
		r = Rect2(r.position * sc, r.size * sc)
	return r.has_point(mp)


# 点【进入】：只播 outro（小箭头 + 进入），播完停住。
# ★ 用户 2026-11-11：先不要进对局 —— 场景切换留着，等要接的时候把 _go_menu() 放开。
func _play_outro() -> void:
	if _state != 2 or _ap2 == null:
		return
	_set_search(false)
	_ap2.speed_scale = 1.0
	_ap2.play("outro")


# ── 切到【初始菜单】（暂时不调用）────────────────────────────
func _go_gallery() -> void:
	if _going:
		return
	_going = true
	# 预加载（_ready 里就 load_threaded_request 了，这里通常已就绪）
	if _gallery_ps == null and _gallery_req:
		var st := ResourceLoader.load_threaded_get_status(GALLERY_SCENE)
		while st == ResourceLoader.THREAD_LOAD_IN_PROGRESS:
			await get_tree().process_frame
			st = ResourceLoader.load_threaded_get_status(GALLERY_SCENE)
		if st == ResourceLoader.THREAD_LOAD_LOADED:
			_gallery_ps = ResourceLoader.load_threaded_get(GALLERY_SCENE) as PackedScene

	# 转场 + 转正（预览实例直接变成 current_scene，零画面跳变）都交给 TransitionWipe
	if _gallery_ps == null:
		_going = false
		return
	Wipe.run(self, _gallery_ps, false)


# ── 大厅（原「初始菜单」的选卡/调序，已搬进本场景）────────────────
func _setup_lobby() -> void:
	_lobby_layer = get_node_or_null("LobbyLayer") as CanvasLayer
	_lobby = get_node_or_null("LobbyLayer/Lobby")
	if _lobby == null:
		push_warning("真初始场景：找不到 LobbyLayer/Lobby（选卡界面不会出现）")
		return
	if _lobby_layer != null:
		_lobby_layer.visible = true       # 预热需要一个「可见」的父层才能真画（见 _prewarm_lobby）
	if _lobby.has_signal("phase_changed"):
		_lobby.connect("phase_changed", Callable(self, "_on_lobby_phase"))
	_prewarm_lobby()


# 大厅文字预热 + 收尾（协程）：进场先把「玩家1 / 已进入」画两帧（几乎全透明），
# 把 24px + 6px 描边的中文字形缓存提前做掉，进房那一帧就不会卡。
func _prewarm_lobby() -> void:
	if _lobby != null and _lobby.has_method("prewarm"):
		_lobby.call("prewarm")
	await get_tree().process_frame
	await get_tree().process_frame
	await get_tree().process_frame
	if _lobby_layer != null and not _lobby_on:
		_lobby_layer.visible = false


func _begin_lobby() -> void:
	if _lobby == null or _lobby_on:
		return
	_lobby_on = true
	if _lobby_layer != null:
		_lobby_layer.visible = true
	var room := ""
	if _search != null:
		room = String(_search.text).strip_edges()
	_lobby.call("begin", room)
	_set_hufa_idle(true)               # 进房后左右护法继续摇摆（只驱动 rotation）


# ── 进房后：左右护法继续摇摆 ─────────────────────────────────────
# outro 播完我们把 _ap2 pause 在末帧（3D 框/√/小箭头都不许再动），
# 但 idle 里那条「左右护法:rotation」轨道也就跟着冻住了 —— 用户 2026-11-13：
# 进房后护法也要继续动。做法：从 idle 里抠出那条轨道，单独做一个 AnimationPlayer 循环播。
var _hufa_ap: AnimationPlayer = null


func _set_hufa_idle(on: bool) -> void:
	if on:
		if _hufa_ap == null:
			_make_hufa_idle()
		if _hufa_ap != null and not _hufa_ap.is_playing():
			_hufa_ap.play(&"loop")
	elif _hufa_ap != null:
		_hufa_ap.stop()


func _make_hufa_idle() -> void:
	if _ap2 == null or _stage2 == null or not _ap2.has_animation("idle"):
		return
	var src := _ap2.get_animation("idle")
	var idx := -1
	for i in range(src.get_track_count()):
		if String(src.track_get_path(i)).ends_with("左右护法:rotation"):
			idx = i
			break
	if idx < 0:
		return
	var anim := Animation.new()
	anim.length = src.length
	anim.step = src.step
	anim.loop_mode = Animation.LOOP_LINEAR
	anim.add_track(Animation.TYPE_VALUE)
	anim.track_set_path(0, src.track_get_path(idx))
	anim.track_set_interpolation_type(0, src.track_get_interpolation_type(idx))
	anim.track_set_interpolation_loop_wrap(0, true)
	var n := src.track_get_key_count(idx)
	for k in range(n):
		anim.track_insert_key(0, src.track_get_key_time(idx, k),
			src.track_get_key_value(idx, k), src.track_get_key_transition(idx, k))
	var lib := AnimationLibrary.new()
	lib.add_animation(&"loop", anim)
	_hufa_ap = AnimationPlayer.new()
	_hufa_ap.name = "HufaIdle"
	_hufa_ap.add_animation_library(&"", lib)
	_stage2.add_child(_hufa_ap)       # 挂在 搜索框 下：轨道路径 2D层/Sprites2D/左右护法 才能解析


# 开始选卡/调序 → 把二级的 3D 房间面板收起来（人名列表由 lobby 自己收）
func _on_lobby_phase(p: String) -> void:
	if p == "quit":
		_lobby_on = false
		if _lobby_layer != null:
			_lobby_layer.visible = false
		_finish_exit()                     # 收起二级 + 回到一级
		return
	if p == "draft" or p == "order":
		for l in _stage2_layers:
			(l as CanvasLayer).visible = false
		_set_hufa_idle(false)
		if _ap2 != null:
			_ap2.pause()
		_set_search(false)
		_search_ready = false
		_state = 9                     # 选卡阶段不再响应一级/二级的点击与右键
