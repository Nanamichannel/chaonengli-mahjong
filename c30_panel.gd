extends RefCounted

# ── Card30 S1【向听】的界面 ──────────────────────────────────────────
# 三段：
#   ① arm  ：配牌点技能图标 → 点两个「东南西北」→ 点中间的「确认」
#   ② give ：被问的那家（对手座位的窗口）从自己手里选 2~3 张交出来 →「确认」
#   ③ swap ：发动者看到对方给的 2~3 张（彩框点选 1 张）+ 选自己 1 张 →「确认」互换
#
# 服务端 op：c30s1_arm{targets:[a,b]} / c30s1_give{tiles} / c30s1_swap{hand,tile}
# 手牌亮度统一交给 hand_pick（其它面板同一套约定）。
#
# ★ 坑（2026-10-27）：GDScript 的 `or` 是**逻辑或**，不是 Python 的 `x or 默认值`。
#   `dict.get("picked") or []` 在 picked 缺失时得到的是 **bool**，接着 `"、".join(false)`
#   抛脚本错误；而这段是在 srv_apply_state 里跑的 → 后面的 srv_busy 收不回来 → 整桌卡死。
#   所以下面一律写 `typeof(x) == TYPE_ARRAY` 判断。

const START_TEX := "res://Cailiao/UI/tiaoguo.png"
const SelFrame := preload("res://sel_frame.gd")
const TILE_DIR := "res://Cailiao/mahjong_graphic/PNG 位图/默认风格 default style/竖 vertical/"
const WIND_DIR := "res://Cailiao/skill/ui/winds/"
const WIND_FILES := ["dong", "nan", "xi", "bei"]
const WIND_CN := ["东", "南", "西", "北"]
const HONOR := {"dong": "1z", "nan": "2z", "xi": "3z", "bei": "4z",
	"bai": "5z", "fa": "6z", "zhong": "7z"}

var host: Node = null            # Main
var bank = null                  # TileBank
var picker = null                # HandPick

var active := false
var mode := ""                   # "arm" / "give" / "swap"

var targets: Array = []          # arm：已选的两家（座位号）
var picks: Array = []            # give / swap：手牌下标（display_tiles 顺序）
var given: Array = []            # swap：对方交出来的牌
var gsel := -1                   # swap：彩框选中的那张（given 下标）
var from_seat := -1              # 对方是谁
var min_pick := 2
var max_pick := 3

var layer: CanvasLayer = null
var ui: Control = null
var start_btn: TextureButton = null   # 唯一的「确认」= 和其他面板一样的开始按钮
var seat_btns: Array = []        # arm：三个风牌按钮
var seat_frames: Array = []
var seat_labels: Array = []
var tile_rows: Array = []        # swap：牌 + 彩框
var tex_cache := {}
var _vp := Vector2.ZERO
# 这个面板被两张卡共用：向听（c30）与新手运（c32）
#   op_prefix   → 发出去的 op 前缀（"c30" / "c32"）
#   only_orphan → 交给对方的牌只能选幺九（新手运）
#   need_arm    → 要不要先选两家（只有向听要；新手运是固定 下家→对家→上家）
var op_prefix := "c30"
var flow_name := "向听"          # 提示文案里的名字（新手运 = "新手运"）
var only_orphan := false
var need_arm := true


func setup(p_host: Node, p_bank, p_picker) -> void:
	host = p_host
	bank = p_bank
	picker = p_picker


# ── ① 选两家 ──────────────────────────────────────────────────────
func arm_begin() -> void:
	close()
	active = true
	mode = "arm"
	targets.clear()
	_make_ui()
	_build_seat_btns()
	_hide_deal_skip(true)
	_refresh()
	_note(flow_name + "：点两个对手的风牌，再点「确认」")


# ── ② 对方交牌 ────────────────────────────────────────────────────
func give_begin(from: int, mn: int, mx: int) -> void:
	close()
	active = true
	mode = "give"
	from_seat = int(from)
	min_pick = clampi(int(mn), 1, 4)
	max_pick = clampi(int(mx), min_pick, 4)
	_make_ui()
	_hide_deal_skip(true)
	picker.begin(picks, max_pick, {"min": min_pick, "on_change": _refresh})
	_refresh()
	_note(flow_name + "：%s 的牌 —— 选 %d~%d 张手牌交给他"
		% [_rel(from), min_pick, max_pick])


# ── ③ 我挑一张换 ──────────────────────────────────────────────────
func swap_begin(from: int, picked_value) -> void:
	close()
	active = true
	mode = "swap"
	from_seat = int(from)
	given.clear()
	if typeof(picked_value) == TYPE_ARRAY:
		for t in picked_value:
			given.append(String(t))
	gsel = 0 if given.size() == 1 else -1
	_make_ui()
	_hide_deal_skip(true)
	_build_tile_row()
	picker.begin(picks, 1, {"min": 1, "on_change": _refresh})
	_refresh()
	_note(flow_name + "：%s 给了 %d 张 —— 点彩框选 1 张，再选自己 1 张手牌"
		% [_rel(from), given.size()])


# 手牌点击（give / swap 阶段）
func handle_hand(index: int) -> void:
	if not active or mode == "arm":
		return
	if mode == "give" and only_orphan:
		var all := _my_tiles()
		if index >= 0 and index < all.size() and not _is_orphan(String(all[index])):
			_note("只能交一张幺九牌（一/九或字牌）")
			return
	picker.toggle(index)


func refresh() -> void:
	_refresh()


func can_confirm() -> bool:
	if not active:
		return false
	if mode == "arm":
		return targets.size() == 2
	if mode == "give":
		return picks.size() >= min_pick and picks.size() <= max_pick
	return gsel >= 0 and picks.size() == 1


func _refresh() -> void:
	# 「开始按钮」= 项目统一那套（tiaoguo.png，贴在未副露手牌右边，main 每帧贴位）
	if start_btn != null and is_instance_valid(start_btn):
		start_btn.visible = active and can_confirm()
	for i in range(tile_rows.size()):
		var row: Dictionary = tile_rows[i]
		var fr := row.get("frame") as Node2D
		if fr != null and is_instance_valid(fr):
			fr.visible = i == gsel
	for i in range(seat_btns.size()):
		var b := seat_btns[i] as TextureButton
		var f := seat_frames[i] as ReferenceRect
		if b == null or not is_instance_valid(b):
			continue
		var picked := targets.has(int(b.get_meta("seat", -1)))
		if f != null and is_instance_valid(f):
			f.visible = picked
		b.modulate = Color(1.0, 0.95, 0.55, 1.0) if picked else Color(1, 1, 1, 1)


func _confirm() -> void:
	if not active:
		return
	if mode == "arm":
		var r := _req({"op": "%ss1_arm" % op_prefix, "seat": int(host.get("my_seat")),
			"targets": [int(targets[0]), int(targets[1])]})
		if r.is_empty():
			return
		var ar: Dictionary = {}
		if typeof(r.get("c30")) == TYPE_DICTIONARY:
			ar = r.get("c30")
		var names: Array = []
		var tl = ar.get("targets")
		if typeof(tl) == TYPE_ARRAY:
			for t in tl:
				names.append(_rel(int(t)))
		close()
		host.call("srv_apply_state", r.get("state"), r.get("events"))
		_kick()
		if not names.is_empty():
			_note(flow_name + "：开始询问 %s" % "、".join(names))
		return
	if mode == "give":
		var tiles := _my_tiles()
		var out: Array = []
		for i in picks:
			if int(i) >= 0 and int(i) < tiles.size():
				out.append(String(tiles[int(i)]))
		if out.size() < min_pick:
			return
		var r2 := _req({"op": "%ss1_give" % op_prefix, "seat": int(host.get("my_seat")),
			"tiles": out})
		if r2.is_empty():
			return
		close()
		host.call("srv_apply_state", r2.get("state"), r2.get("events"))
		_kick()
		_note(flow_name + "：交出了 %s" % "、".join(out))
		return
	# swap
	if not can_confirm():
		return
	var tiles2 := _my_tiles()
	if picks.is_empty() or int(picks[0]) >= tiles2.size():
		return
	var mine := String(tiles2[int(picks[0])])
	var pick := String(given[gsel])
	var r3 := _req({"op": "%ss1_swap" % op_prefix, "seat": int(host.get("my_seat")),
		"hand": mine, "tile": pick})
	if r3.is_empty():
		return
	var got := pick
	if typeof(r3.get("c30")) == TYPE_DICTIONARY:
		var sw: Dictionary = r3.get("c30")
		if String(sw.get("got", "")) != "":
			got = String(sw.get("got"))
	close()
	host.call("srv_apply_state", r3.get("state"), r3.get("events"))
	_kick()
	_note(flow_name + "：用 %s 换到 %s" % [mine, got])


# 发请求 + 统一错误处理（看破拦截 / 服务端拒绝 / 没回应）
func _req(req: Dictionary) -> Dictionary:
	var r: Dictionary = host.call("srv_request", req)
	if r.is_empty():
		_note(_srv_err(flow_name + "：服务端没有回应"))
		_pull()
		return {}
	if bool(host.call("srv_kangpo_blocked", r)):
		close()
		return {}
	if not bool(r.get("ok", false)):
		_note(_srv_err(flow_name + "：%s" % String(r.get("error", "发动失败"))))
		_pull()
		return {}
	return r


func _srv_err(base: String) -> String:
	var note := String(host.get("srv_note"))
	if note == "":
		return base
	return "%s（%s）" % [base, note]


# 位置不在这里算：确认按钮就是项目统一的「开始按钮」，
# 由 main.gd 的 _sync_prompt_btns() 每帧贴到未副露手牌右边（和别的面板完全一致）。
func tick() -> void:
	if not active or mode != "arm":
		return
	var rc: Rect2 = host.call("get_viewport_rect")
	if rc.size.distance_to(_vp) > 0.5:
		_layout_arm()                     # 窗口大小变了 → 风牌重新摆


func close() -> void:
	if not active and ui == null:
		return
	active = false
	mode = ""
	targets.clear()
	given.clear()
	gsel = -1
	from_seat = -1
	tile_rows.clear()
	seat_btns.clear()
	seat_frames.clear()
	seat_labels.clear()
	if picker != null:
		picker.end()
	if start_btn != null and is_instance_valid(start_btn):
		start_btn.visible = false
	if layer != null and is_instance_valid(layer):
		layer.queue_free()
	layer = null
	ui = null
	start_btn = null
	_hide_deal_skip(false)


# ── 内部 ──────────────────────────────────────────────────────────
# 发完 op 之后自己接上推进链 / 失败时拉一次 state。
# ★ 用 has_method 兜一层：host.call 调不存在的方法会抛脚本错误，
#   而这个面板是在 srv_apply_state 的调用栈里跑的 —— 抛出去会连带卡死。
func _kick() -> void:
	if host != null and host.has_method("_srv_kick"):
		host.call("_srv_kick")


func _pull() -> void:
	if host != null and host.has_method("_pull_state"):
		host.call("_pull_state")


func _my_tiles() -> Array:
	var t = host.call("display_tiles")
	if typeof(t) == TYPE_ARRAY:
		return t
	return []


# 幺九牌：一/九 或字牌（和服务器 _c32_is_orphan 同一口径）
func _is_orphan(kind: String) -> bool:
	if HONOR.has(kind):
		return true
	var n := kind.substr(0, 1)
	return n == "1" or n == "9"


func _rel(seat: int) -> String:
	return String(host.call("_rel_seat_name", int(seat)))


func _note(msg: String) -> void:
	if host != null and host.has_method("_toast"):
		host.call("_toast", msg)


# 面板开着的时候把配牌窗口那个「开始（= 跳过）」藏起来：
#   · 它和这里的「确认」位置相近，玩家很容易点错（点错就是把配牌技能跳过）
func _hide_deal_skip(v: bool) -> void:
	if host != null and host.has_method("_set_deal_skip_visible"):
		host.call("_set_deal_skip_visible", not v)


func _tile_tex(kind: String) -> Texture2D:
	if tex_cache.has(kind):
		return tex_cache[kind] as Texture2D
	var f := String(HONOR.get(kind, kind))
	var t := load(TILE_DIR + f + ".png") as Texture2D
	tex_cache[kind] = t
	return t


func _wind_tex(wind: int) -> Texture2D:
	var key := "wind%d" % int(wind)
	if tex_cache.has(key):
		return tex_cache[key] as Texture2D
	var t := load(WIND_DIR + String(WIND_FILES[int(wind)]) + ".png") as Texture2D
	tex_cache[key] = t
	return t


func _make_ui() -> void:
	if ui != null:
		return
	var holder: Node = host.get_parent()
	if holder == null:
		holder = host
	layer = CanvasLayer.new()
	layer.name = "C30Layer"
	layer.layer = 30                       # 人物卡在 layer=20，必须再上一层
	holder.add_child(layer)
	ui = Control.new()
	ui.name = "C30UI"
	ui.position = Vector2.ZERO
	layer.add_child(ui)
	# 确认 = 项目统一的「开始按钮」（tiaoguo.png，手牌右边，_sync_prompt_btns 贴位）
	var tex := load(START_TEX) as Texture2D
	start_btn = TextureButton.new()
	start_btn.name = "C30Start"
	start_btn.texture_normal = tex
	start_btn.ignore_texture_size = true
	start_btn.stretch_mode = TextureButton.STRETCH_SCALE
	start_btn.focus_mode = Control.FOCUS_NONE
	start_btn.visible = false
	start_btn.pressed.connect(_confirm)
	ui.add_child(start_btn)


# arm：三个风牌按钮（下家 / 对家 / 上家，按各自的自风出图）+ 标签，下面一个「确认」
func _build_seat_btns() -> void:
	seat_btns.clear()
	seat_frames.clear()
	seat_labels.clear()
	if ui == null:
		return
	var state: Dictionary = {}
	var raw = host.get("srv_state")
	if typeof(raw) == TYPE_DICTIONARY:
		state = raw
	var dealer := int(state.get("dealer", 0))
	var me := int(host.get("my_seat"))
	var order := [1, 2, 3]                  # 下家 → 对家 → 上家
	for i in range(order.size()):
		var seat := (me + int(order[i])) % 4
		var wind := (seat - dealer + 16) % 4
		var b := TextureButton.new()
		b.name = "C30Seat%d" % seat
		b.texture_normal = _wind_tex(wind)
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_KEEP_ASPECT
		b.focus_mode = Control.FOCUS_NONE
		b.set_meta("seat", seat)
		b.pressed.connect(_seat_clicked.bind(seat))
		ui.add_child(b)
		var f := ReferenceRect.new()
		f.name = "Frame"
		f.editor_only = false
		f.border_color = Color(1.0, 0.16, 0.16, 1.0)
		f.border_width = 4.0
		f.mouse_filter = Control.MOUSE_FILTER_IGNORE
		f.visible = false
		ui.add_child(f)
		var lb := Label.new()
		lb.name = "SeatLabel%d" % seat
		lb.text = "%s（%s）" % [String(host.call("_rel_seat_name", seat)),
			String(WIND_CN[wind])]
		lb.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		lb.add_theme_font_size_override("font_size", 26)
		lb.add_theme_color_override("font_color", Color(1, 1, 1, 1))
		lb.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.85))
		lb.add_theme_constant_override("outline_size", 6)
		ui.add_child(lb)
		seat_btns.append(b)
		seat_frames.append(f)
		seat_labels.append(lb)
	_layout_arm()


func _layout_arm() -> void:
	var rc: Rect2 = host.call("get_viewport_rect")
	_vp = rc.size
	var n := seat_btns.size()
	if n == 0:
		return
	var side := clampf(_vp.x * 0.075, 84.0, 140.0)
	var gap := side * 0.9
	var total := float(n) * side + float(n - 1) * gap
	var x0 := (_vp.x - total) * 0.5
	var y0 := _vp.y * 0.34
	for i in range(n):
		var b := seat_btns[i] as TextureButton
		var f := seat_frames[i] as ReferenceRect
		var lb := seat_labels[i] as Label
		if b == null:
			continue
		b.position = Vector2(x0 + float(i) * (side + gap), y0)
		b.size = Vector2(side, side)
		if f != null:
			f.position = b.position
			f.size = b.size
		if lb != null:
			lb.position = Vector2(b.position.x - 40.0, y0 + side + 6.0)
			lb.size = Vector2(side + 80.0, 34.0)



func _seat_clicked(seat: int) -> void:
	if not active or mode != "arm":
		return
	var s := int(seat)
	if targets.has(s):
		targets.erase(s)
	elif targets.size() < 2:
		targets.append(s)
	else:
		_note(flow_name + "：最多选两家（先点掉一个再选）")
		return
	_refresh()


# swap：对方给的那几张，横着摆在屏幕中部，彩框 = 选中
func _build_tile_row() -> void:
	tile_rows.clear()
	if ui == null:
		return
	var rc: Rect2 = host.call("get_viewport_rect")
	var vp := rc.size
	var n := maxi(1, given.size())
	var tw := clampf(vp.x * 0.055, 44.0, 96.0)
	var th := tw * 1.35
	var gap := tw * 0.16
	var total := float(n) * tw + float(maxi(0, n - 1)) * gap
	var x0 := (vp.x - total) * 0.5
	var y0 := vp.y * 0.40
	for i in range(given.size()):
		var box := Control.new()
		box.name = "C30Given%d" % i
		box.position = Vector2(x0 + float(i) * (tw + gap), y0)
		box.size = Vector2(tw, th)
		ui.add_child(box)
		var tb := TextureButton.new()
		tb.texture_normal = _tile_tex(String(given[i]))
		tb.ignore_texture_size = true
		tb.stretch_mode = TextureButton.STRETCH_KEEP_ASPECT
		tb.size = Vector2(tw, th)
		tb.focus_mode = Control.FOCUS_NONE
		tb.pressed.connect(_given_clicked.bind(i))
		box.add_child(tb)
		var frame := SelFrame.attach(box, Vector2(tw, th), SelFrame.TEX_YELLOW,
			Color(1, 1, 1, 1), i == gsel)
		tile_rows.append({"frame": frame, "kind": String(given[i])})


func _given_clicked(i: int) -> void:
	if not active or mode != "swap":
		return
	gsel = int(i)
	_refresh()
