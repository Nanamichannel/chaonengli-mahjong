extends RefCounted

# ── 通用「技能选牌面板」────────────────────────────────────────────
# 目的：把每个技能都要手写一遍的东西集中到一处 ——
#   · 「开始」按钮的创建 / 显隐 / 每帧跟随未副露手牌的右边（以前忘了加进
#     _sync_prompt_btns 就会「按钮严重偏移」）
#   · 手牌选中/取消（统一走 hand_pick：亮度只归它管）
#   · 牌河点击 + 彩框（可选，按 river_ok 过滤）
#   · 被看破拦下 / 服务端拒绝 / 回合被推进 → close()（以前只 return 就卡死）
#   · 不可取消的面板（cancel=false 时点技能图标也不会关）
#
# 用法（main.gd，一个面板一个实例）：
#   panel.begin({
#       "name": "换牌",
#       "want": 3, "min": 1,          # 手牌最多/最少几张
#       "river": true,                # 还要选牌河
#       "river_match": true,          # 牌河张数必须等于手牌张数
#       "cancel": true,               # 能不能取消
#       "close_on_confirm": true,     # 点开始后先关面板再回调（友引循环用 false）
#       "river_ok": func(seq, seat, down): return ...,
#       "on_confirm": func(picks, rivers): ...,
#   })
#   panel.handle_hand(i) / panel.handle_river(seq) / panel.tick()（每帧）

const START_TEX := "res://Cailiao/UI/tiaoguo.png"

var host: Node = null            # Main
var bank = null                  # TileBank
var picker = null                # HandPick 实例

var active := false
var label := "技能"
var want := 1
var min_pick := 1
var river_on := false
var river_match := true
var total := 0                   # >0：手牌 + 牌河**合计**要正好这么多张（神境）
var close_on_confirm := true
var allow_cancel := true
var river_ok := Callable()       # func(seq:int, seat:int, down:bool) -> bool
var on_confirm := Callable()     # func(picks:Array[int], rivers:Array[int])

var picks: Array[int] = []       # 手牌下标（display_tiles 顺序）
var rivers: Array[int] = []      # 牌河 seq
var ui: Control = null
var btn: TextureButton = null


func setup(p_host: Node, p_bank, p_picker) -> void:
	host = p_host
	bank = p_bank
	picker = p_picker


func begin(spec: Dictionary) -> void:
	active = true
	label = String(spec.get("name", "技能"))
	want = maxi(1, int(spec.get("want", 1)))
	min_pick = clampi(int(spec.get("min", want)), 0, want)
	river_on = bool(spec.get("river", false))
	river_match = bool(spec.get("river_match", true))
	total = maxi(0, int(spec.get("total", 0)))
	close_on_confirm = bool(spec.get("close_on_confirm", true))
	allow_cancel = bool(spec.get("cancel", true))
	river_ok = spec.get("river_ok", Callable())
	on_confirm = spec.get("on_confirm", Callable())
	picks.clear()
	rivers.clear()
	_make_ui()
	picker.begin(picks, want, {"min": min_pick, "on_change": refresh})
	refresh()


# 手牌点一下：选中/取消；手牌减少时把多出来的牌河选择丢掉
func handle_hand(index: int) -> void:
	if not active:
		return
	var before := picks.size()
	picker.toggle(index)
	if picks.size() != before:
		var keep := ((total - picks.size()) if total > 0 else picks.size())
		while rivers.size() > maxi(keep, 0):
			rivers.pop_back()
	refresh()


func handle_river(seq: int) -> void:
	if not active or not river_on:
		return
	var cap := ((total - picks.size()) if total > 0 else maxi(1, picks.size()))
	if rivers.has(seq):
		rivers.erase(seq)
	elif rivers.size() < cap:
		rivers.append(seq)
	else:
		if total > 0:
			_note("%s：手牌 + 牌河一共选 %d 张（还能选 %d 张牌河）"
				% [label, total, maxi(cap - rivers.size(), 0)])
		else:
			_note("%s：先选手牌（最多 %d 张）" % [label, maxi(1, picks.size())])
		return
	refresh()


func can_confirm() -> bool:
	if not active:
		return false
	var n := picks.size()
	if n < min_pick or n > want:
		return false
	if total > 0:
		return river_on and (picks.size() + rivers.size() == total)
	if not river_on:
		return true
	if river_match:
		return n >= 1 and rivers.size() == n
	return rivers.size() >= 1


# 按钮显隐 + 牌河可点/彩框（手牌亮度由 hand_pick 负责）
func refresh() -> void:
	if btn != null and is_instance_valid(btn):
		btn.visible = can_confirm()
	refresh_rivers()


# 只刷牌河（_apply_entity_states 重画之后要再调一次）
func refresh_rivers() -> void:
	if bank == null or not active:
		return
	for q in bank.all_pieces():
		var tp := q as TilePiece
		if tp == null or not tp.visible:
			continue
		if tp.form == "river" or tp.form == "back":
			tp.set_river_clickable(_river_allowed(tp))
			tp.set_selected_frame(rivers.has(tp.discard_seq))


func _river_allowed(tp) -> bool:
	if not river_on:
		return false
	if river_ok.is_valid():
		return bool(river_ok.call(int(tp.discard_seq), int(tp.river_seat), bool(tp.face_down)))
	return not tp.face_down


func confirm() -> void:
	if not can_confirm():
		_note("%s：还没选好" % label)
		return
	var p := picks.duplicate()
	var r := rivers.duplicate()
	if close_on_confirm:
		close()
	if on_confirm.is_valid():
		on_confirm.call(p, r)


func close() -> void:
	if not active and ui == null:
		return
	active = false
	picks.clear()
	rivers.clear()
	if picker != null:
		picker.end()
	if btn != null and is_instance_valid(btn):
		btn.visible = false
	if ui != null and is_instance_valid(ui):
		ui.queue_free()
	ui = null
	btn = null


# 每帧：把「开始」按钮贴到未副露手牌的右边（和别的面板同一套摆位）
func tick() -> void:
	if btn == null or not is_instance_valid(btn) or not btn.visible:
		return
	if host == null:
		return
	var aspect := 70.0 / 220.0
	if btn.texture_normal != null and btn.texture_normal.get_width() > 0:
		aspect = float(btn.texture_normal.get_height()) / float(btn.texture_normal.get_width())
	var r: Rect2 = host.call("prompt_btn_rect", aspect)
	if btn.size.distance_to(r.size) > 0.5:
		btn.size = r.size
	if btn.global_position.distance_to(r.position) > 0.5:
		btn.global_position = r.position


func _note(msg: String) -> void:
	if host != null and host.has_method("_toast"):
		host.call("_toast", msg)


func _make_ui() -> void:
	if ui != null or host == null:
		return
	var holder: Node = host.get_parent()
	if holder == null:
		holder = host
	ui = Control.new()
	ui.name = "SkillPanel_%s" % label
	ui.z_index = 262
	holder.add_child(ui)
	ui.position = Vector2.ZERO
	var tex := load(START_TEX) as Texture2D
	var bw := 220.0
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = bw * float(tex.get_height()) / float(tex.get_width())
	btn = TextureButton.new()
	btn.name = "Start"
	btn.texture_normal = tex
	btn.ignore_texture_size = true
	btn.stretch_mode = TextureButton.STRETCH_SCALE
	btn.focus_mode = Control.FOCUS_NONE
	btn.size = Vector2(bw, bh)
	btn.global_position = host.call("prompt_btn_pos", bw, bh)
	btn.visible = false
	btn.pressed.connect(confirm)
	ui.add_child(btn)
