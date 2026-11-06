extends Node2D

# ── 身份卡（Main/Identity）────────────────────────────────────────────
# Card01..Card08 是桌面上已经摆好的 8 个位置：
#   1 / 3 / 5 / 7 = 本家 / 下家 / 对家 / 上家 的主战位
#   2 / 4 / 6 / 8 = 本家 / 下家 / 对家 / 上家 的协战位
# 主战位按「半庄第几场」放该玩家的第 1~4 号人物卡：
#   东一、东二 → 1 号；东三、东四 → 2 号；南一、南二 → 3 号；南三、南四 → 4 号
# 协战位始终放该玩家的第 5 号（协战）卡，z 序压在主战卡下面。
# Card09..Card46 是人物卡库，不参与桌面摆放，统一隐藏。

# 某一家的人物卡技能被按下：seat 是座位号，card_no 是人物编号，index 是 0/1
signal skill_pressed(seat: int, card_no: int, index: int)
# Skill2 下的东南西北被选中（wind：0=东 1=南 2=西 3=北）
signal wind_picked(seat: int, card_no: int, wind: int)
# 技能图标展开 / 收起
signal skills_toggled(seat: int, card_no: int, open: bool)
# 长按人物卡（≥0.7 秒）：main 用它开「协战卡遮罩」的东南西北选择器
signal card_long_pressed(seat: int, card_no: int)

const CARD_DIR := "res://Cailiao/skill/cards/card_%02d.png"
const CARD_COUNT := 46
const ORDER_COUNT := 5

const ORDER_PATH := "user://player_order.json"      # 本家最终编号（1..5 号人物）
const ORDERS_PATH := "user://player_orders.json"    # 四家各自的 5 张（seat 0..3）

const MAIN_SLOTS := [1, 3, 5, 7]
const SUPPORT_SLOTS := [2, 4, 6, 8]
# 遮罩贴图：**不写死文件路径**，取场景里 Main/UI/CardCover 节点的贴图（睡2.png）。
#   在编辑器里换 CardCover 的图就全局生效，不用改代码。
const COVER_NODE_PATH := "../UI/CardCover"
# ★ 遮罩样式可自定义：
#   1) 换图：把 card_cover.png 放到 <exe 同目录>\skin\ 或 user://skin\（优先于 CardCover 节点）
#   2) 颜色/透明度：identity_card.COVER_TINT（或运行时 identity_card.set_cover_tint()）
#   3) 技能图标上那层半透明白：identity_card.SKILL_MUTE_COLOR
const COVER_SKIN_FILES := ["card_cover.png", "card_cover.jpg", "card_cover.webp"]

var _slots := {}                 # 位置号 1..8 → TextureButton
var _orders: Array = []          # 4 家，每家 5 个卡号
var _main_node: Node = null
var _last_key := ""
var _cover_tex: Texture2D = null    # 遮罩贴图（hidden_card.png），整局只 load 一次
var _revealed := {}             # 已解除隐藏的座位（绝对座位号 0..3）
var _char_states := {}        # seat -> {main:{...}, support:{...}}
var _slot_card := {}          # 位子 1..8 -> 现在摆的卡号
var _cur_ri := 0
var _debug_cards := false        # test_seats.cfg 里 debug_cards=1 → 打印摆卡情况
var _char_sig := ""
var _support_mute := {}          # seat -> 被遮罩的协战卡卡号（服务端说的，只放生效的）
var _sup_mute_sig := ""
var _force_mask := {}              # 当前角色索引（0..3）
var _view_seat := 0             # 本窗口坐哪一家（决定桌面上谁是「本家」）

func _ready() -> void:
	_main_node = get_parent()
	for i in range(1, 9):
		var b := get_node_or_null("Card%02d" % i) as TextureButton
		if b == null:
			continue
		_slots[i] = b
		b.focus_mode = Control.FOCUS_NONE
		if b.has_signal("skill_pressed") and not b.is_connected("skill_pressed", _on_slot_skill.bind(i)):
			b.connect("skill_pressed", _on_slot_skill.bind(i))
		if b.has_signal("wind_picked") and not b.is_connected("wind_picked", _on_slot_wind.bind(i)):
			b.connect("wind_picked", _on_slot_wind.bind(i))
		if b.has_signal("skills_toggled") and not b.is_connected("skills_toggled", _on_slot_toggled.bind(i)):
			b.connect("skills_toggled", _on_slot_toggled.bind(i))
		if b.has_signal("long_pressed") and not b.is_connected("long_pressed", _on_slot_long.bind(i)):
			b.connect("long_pressed", _on_slot_long.bind(i))
		if b.has_signal("touched") and not b.is_connected("touched", _on_slot_touched.bind(i)):
			b.connect("touched", _on_slot_touched.bind(i))
	# 主战卡盖在协战卡上方
	# 注意：两层**都必须 ≥ 1**。桌面上的牌背 / 牌墩 / 背景这些 sprite 的 z 比 Identity 高，
	# 协战卡原来是 z=0 → 整张被盖住（看着像「协战卡没有牌」，主战卡因为 z=1 才露出来）。
	# 现在两张都是 z=1，靠下面的 move_child 让主战卡排在协战卡后面 = 画在上层。
	for s in MAIN_SLOTS:
		var b := _slots.get(s, null) as TextureButton
		if b != null:
			b.z_index = 1
	for s in SUPPORT_SLOTS:
		var b := _slots.get(s, null) as TextureButton
		if b != null:
			b.z_index = 1
	# 两张卡重叠的部分，让主战卡优先吃鼠标：
	# Control 的点击判定按同级顺序，不按 z_index，所以把主战卡排到协战卡后面。
	for seat in range(4):
		var m := _slots.get(MAIN_SLOTS[seat], null) as Control
		var sp := _slots.get(SUPPORT_SLOTS[seat], null) as Control
		if m != null and sp != null:
			move_child(m, sp.get_index() + 1)
	# 卡库里的其余人物卡不参与桌面显示
	for i in range(9, CARD_COUNT + 1):
		var c := get_node_or_null("Card%02d" % i)
		if c != null:
			c.visible = false
			if c is Control:
				(c as Control).mouse_filter = Control.MOUSE_FILTER_IGNORE
	_cover_tex = _load_cover_tex()
	_load_orders()
	_apply_round("dong", 1)
	_refresh_hidden()

func _cover_external_path() -> String:
	var dirs := [OS.get_executable_path().get_base_dir().path_join("skin"),
		ProjectSettings.globalize_path("user://skin")]
	for d in dirs:
		for n in COVER_SKIN_FILES:
			var p := String(d).path_join(String(n))
			if FileAccess.file_exists(p):
				return p
	return ""


func _load_cover_tex() -> Texture2D:
	var ext := _cover_external_path()
	if ext != "":
		var img := Image.load_from_file(ext)
		if img != null and not img.is_empty():
			print("identity_cards: 遮罩 = %s（外部）" % ext)
			return ImageTexture.create_from_image(img)
	var node := get_node_or_null(COVER_NODE_PATH)
	if node != null and node is TextureRect:
		var t := (node as TextureRect).texture
		if t != null:
			return t
	push_warning("identity_cards: 场景里找不到 UI/CardCover（人物卡遮罩贴图缺失）")
	return null


# 运行时改完 skin/card_cover.png（或 COVER_TINT）后调一下，立刻重刷
func refresh_cover_style() -> void:
	_cover_tex = _load_cover_tex()
	_refresh_hidden()


# 本家当前 5 张（直接 F5 时给 CardPhase 用，保证桌面和选牌界面一致）
func current_order() -> Array:
	return _orders[0].duplicate() if _orders.size() > 0 else []


# 卡组文件变了（新一局抽卡 / 直接 F5 重开）→ 重新读取并按当前场次重摆
func reload_orders() -> void:
	_load_orders()
	var st = _main_node.get("srv_state") if _main_node != null else null
	if typeof(st) == TYPE_DICTIONARY and not (st as Dictionary).is_empty():
		var d: Dictionary = st
		_apply_round(String(d.get("wind", "dong")), int(d.get("number", 1)))
	else:
		_apply_round("dong", 1)


func _process(_delta: float) -> void:
	if _main_node == null:
		return
	var st = _main_node.get("srv_state")
	if typeof(st) != TYPE_DICTIONARY:
		return
	var d: Dictionary = st
	if d.is_empty():
		return
	var wind := String(d.get("wind", "dong"))
	var number := int(d.get("number", 1))
	var honba := int(d.get("honba", 0))
	var key := "%s:%d:%d" % [wind, number, honba]
	if key == _last_key:
		return
	_last_key = key
	_apply_round(wind, number)

# 半庄的第几场 → 该用第几号主战卡（0..3）
# 东一/东二 = 0，东三/东四 = 1，南一/南二 = 2，南三/南四 = 3
func _round_index(wind: String, number: int) -> int:
	var base := 0
	match wind:
		"nan":
			base = 4
		"xi":
			base = 8
		"bei":
			base = 12
	var idx := base + clampi(number, 1, 4) - 1
	return clampi(idx >> 1, 0, 3)

func _apply_round(wind: String, number: int) -> void:
	if _orders.size() < 4:
		return
	var ri := _round_index(wind, number)
	_cur_ri = ri
	_apply_char_cards()          # 主战/协战（含协战覆盖时隐藏协战位）
	_refresh_hidden()

# 只有自己的卡能用技能（别的座位点了不算）
func _on_slot_skill(card_no: int, index: int, slot: int) -> void:
	var seat := _seat_of_group((slot - 1) >> 1)
	if seat != _view_seat:
		return
	skill_pressed.emit(seat, card_no, index)


# Skill2 的东南西北：只在「这张人物卡」上打开 / 收起
func open_wind_picker(card_no: int = 1) -> void:
	for i in range(1, 9):
		var b := _slots.get(i, null) as TextureButton
		if b == null or not b.has_method("open_wind_picker"):
			continue
		if int(b.get("_card_no")) == int(card_no):
			b.call("open_wind_picker")


func close_wind_picker(card_no: int = 1) -> void:
	for i in range(1, 9):
		var b := _slots.get(i, null) as TextureButton
		if b == null or not b.has_method("close_wind_picker"):
			continue
		if int(b.get("_card_no")) == int(card_no):
			b.call("close_wind_picker")


# 本小局用过的一次性技能：图标变灰、点不动
func set_skill_disabled(card_no: int, index: int, disabled: bool) -> void:
	for i in range(1, 9):
		var b := _slots.get(i, null) as TextureButton
		if b == null or not b.has_method("set_skill_disabled"):
			continue
		if int(b.get("_card_no")) == int(card_no):
			b.call("set_skill_disabled", index, disabled)


func reset_skill_states() -> void:
	for i in range(1, 9):
		var b := _slots.get(i, null) as TextureButton
		if b == null or not b.has_method("set_skill_disabled"):
			continue
		b.call("set_skill_disabled", 0, false)
		b.call("set_skill_disabled", 1, false)


# 技能图标的框（Card03「自信」红色，整小局常驻）
func set_skill_frame(card_no: int, index: int, on: bool) -> void:
	for i in range(1, 9):
		var b := _slots.get(i, null) as TextureButton
		if b == null or not b.has_method("set_skill_frame"):
			continue
		if int(b.get("_card_no")) == int(card_no):
			b.call("set_skill_frame", index, on)


func reset_skill_frames() -> void:
	for i in range(1, 9):
		var b := _slots.get(i, null) as TextureButton
		if b == null or not b.has_method("reset_skill_frames"):
			continue
		b.call("reset_skill_frames")


# 技能发动成功 → 把这张人物卡上的技能图标收起来
func collapse_skills(card_no: int) -> void:
	for i in range(1, 9):
		var b := _slots.get(i, null) as TextureButton
		if b == null or not b.has_method("collapse_skills"):
			continue
		if int(b.get("_card_no")) == int(card_no):
			b.call("collapse_skills")


func _on_slot_wind(card_no: int, wind: int, slot: int) -> void:
	var seat := _seat_of_group((slot - 1) >> 1)
	if seat != _view_seat:
		return
	wind_picked.emit(seat, card_no, wind)


# 点谁谁在上：把这张卡移到同级最后 → 绘制在上层 + 优先吃鼠标
func _bring_slot_front(slot: int) -> void:
	var b := _slots.get(int(slot), null) as Control
	if b == null or b.get_parent() != self:
		return
	move_child(b, get_child_count() - 1)


func _on_slot_touched(card_no: int, slot: int) -> void:
	_bring_slot_front(int(slot))
	_collapse_covered(int(slot))


# 点谁就把「被它盖住」的那些卡的技能图标收起来：
#   人物卡是「主战 + 协战」两两叠着摆的，两张重叠时下层卡的技能按钮会被上层卡盖住，
#   但按钮本身还是可点的（会误触到别人的技能）→ 收起来最干净。
func _collapse_covered(slot: int) -> void:
	var me_b := _slots.get(int(slot), null) as Control
	if me_b == null:
		return
	var r := me_b.get_global_rect()
	for i in range(1, 9):
		if i == int(slot):
			continue
		var b := _slots.get(i, null) as TextureButton
		if b == null or not b.is_visible_in_tree():
			continue
		if not b.has_method("collapse_skills"):
			continue
		if not r.intersects(b.get_global_rect()):
			continue
		b.call("collapse_skills")


func _on_slot_long(card_no: int, slot: int) -> void:
	var seat := _seat_of_group((slot - 1) >> 1)
	if seat != _view_seat:
		return                       # 只有自己那一家能开遮罩选择器
	card_long_pressed.emit(seat, card_no)


func _on_slot_toggled(card_no: int, open: bool, slot: int) -> void:
	var seat := _seat_of_group((slot - 1) >> 1)
	if seat != _view_seat:
		return
	if open:
		_collapse_covered(int(slot))          # 展开技能时，先把被压住的卡收起来
	skills_toggled.emit(seat, card_no, open)


func _set_card(slot: int, card_no: int) -> void:
	_slot_card[slot] = int(card_no)
	var b := _slots.get(slot, null) as TextureButton
	if b == null:
		return
	var path := CARD_DIR % card_no
	var tex := load(path) as Texture2D
	if tex != null:
		b.texture_normal = tex
	b.visible = true
	if b.has_method("set_character"):
		b.call("set_character", card_no)

# 传承（Card16 S1）：把这张卡的某个技能图标换成「复制来的那个技能」
#   ★ 只换技能图标（按钮 + 气泡），**卡面不动**
func set_skill_icon(card_no: int, index: int, from_card: int, from_skill: int = 1) -> void:
	for i in range(1, 9):
		var b := _slots.get(i, null) as TextureButton
		if b == null or not b.has_method("set_skill_icon"):
			continue
		if int(b.get("_card_no")) == int(card_no):
			b.call("set_skill_icon", int(index), int(from_card), int(from_skill))


# ── 四家的 5 张卡 ─────────────────────────────────────────────────────
func _load_orders() -> void:
	_orders = [[], [], [], []]

	var own = _read_array(ORDER_PATH)
	if _valid_order(own):
		_orders[0] = own.slice(0, ORDER_COUNT)

	var all = _read_array(ORDERS_PATH)
	if typeof(all) == TYPE_ARRAY and all.size() >= 4:
		for i in range(4):
			if _valid_order(all[i]):
				_orders[i] = (all[i] as Array).slice(0, ORDER_COUNT)

	# ★ 以前这里会给「缺失的座位」随机编 5 张卡并存盘 —— 那是联机版的元凶：
	#   每台机器编的都不一样 → 别人看到你面前是另一张卡；而且随机卡和服务端
	#   char_states 对不上 → 遮罩全部失效（所有人都亮着）。
	#   现在：**只认文件里真实存在的卡序**，缺的就留空，由服务端 char_states 决定。
	_debug_cards = _read_debug_flag()

func _read_debug_flag() -> bool:
	if not FileAccess.file_exists("res://test_seats.cfg"):
		return false
	var f := FileAccess.open("res://test_seats.cfg", FileAccess.READ)
	if f == null:
		return false
	var txt := f.get_as_text()
	f.close()
	for line in txt.split("\n"):
		var t := String(line).strip_edges().to_lower()
		if t.begins_with("debug_cards="):
			return int(t.substr(12).strip_edges()) != 0
	return false

func _valid_order(arr) -> bool:
	if typeof(arr) != TYPE_ARRAY or arr.size() < ORDER_COUNT:
		return false
	var seen := {}
	for v in arr.slice(0, ORDER_COUNT):
		var n := int(v)
		if n < 1 or n > CARD_COUNT or seen.has(n):
			return false
		seen[n] = true
	return true

func _read_array(path: String):
	if not FileAccess.file_exists(path):
		return null
	var rf := FileAccess.open(path, FileAccess.READ)
	if rf == null:
		return null
	return JSON.parse_string(rf.get_as_text())

func _save_orders() -> void:
	var wf := FileAccess.open(ORDERS_PATH, FileAccess.WRITE)
	if wf != null:
		wf.store_string(JSON.stringify(_orders))


# ── 隐藏 / 解除隐藏 ─────────────────────────────────────────────────
# 初始只有本家（屏幕下方/右下）的两张卡可见；其他三家盖着 hidden。
# 当某位其他玩家使用角色技能时调用 reveal_seat(1/2/3) 即可解除。
func reveal_seat(seat: int) -> void:
	if seat < 0 or seat > 3 or seat == _view_seat:
		return
	_revealed[seat] = true
	_refresh_hidden()


func reset_reveals() -> void:
	_revealed.clear()
	_refresh_hidden()


func is_seat_revealed(seat: int) -> bool:
	return seat == _view_seat or _revealed.has(seat)


# 本窗口坐哪一家：屏幕上「本家」那一组显示自己的卡，其余按逆时针（下→对→上）转
func set_view_seat(seat: int) -> void:
	_view_seat = clampi(seat, 0, 3)
	_last_key = ""
	reload_orders()


func _seat_of_group(g: int) -> int:
	return (_view_seat + g) % 4


# 我这一家的「主战位 / 协战位」位置号（1..8）。拿不到就返回空数组。
# 用途：技能图标遮罩只盖自己的卡（muted_skills 只按卡号记，不分座位）。
func my_skill_slots() -> Array:
	for g in range(4):
		if _seat_of_group(g) == _view_seat:
			return [int(MAIN_SLOTS[g]), int(SUPPORT_SLOTS[g])]
	return []


# 服务端下发的遮罩状态：[{seat, main:{card,open,expired}, support:{...}}]
var _painted := false                   # 遮罩有没有画过至少一次

func set_char_states(data) -> void:
	var sig := JSON.stringify(data)
	var sig_changed := sig != _char_sig
	if sig_changed:
		_char_sig = sig
		_char_states.clear()
		if typeof(data) == TYPE_ARRAY:
			for it in (data as Array):
				if typeof(it) == TYPE_DICTIONARY:
					_char_states[int((it as Dictionary).get("seat", -1))] = it
	# ★ 每次 state 都给「摆卡」一次机会：位子上的卡可能被 reload_orders()/_apply_round()
	#   改过；但只在「状态变了 / 卡变了 / 还没画过」时才重刷遮罩 ——
	#   set_hidden() 会打断卡面动画，每 0.35 秒刷一遍会很吵。
	var cards_changed := false
	if _orders.size() >= 4:
		cards_changed = bool(_apply_char_cards())
	if sig_changed or cards_changed or not _painted:
		_painted = true
		_refresh_hidden()


# 只重排「哪个位子摆哪张卡」（协战覆盖主战的逻辑在这里）
func _apply_char_cards() -> bool:
	var changed := false
	for g in range(4):
		var seat := _seat_of_group(g)
		if seat >= _orders.size():
			continue
		var order: Array = _orders[seat]
		var st: Dictionary = _char_states.get(seat, {})
		var main_info: Dictionary = st.get("main", {}) if typeof(st.get("main")) == TYPE_DICTIONARY else {}
		var sup: Dictionary = st.get("support", {}) if typeof(st.get("support")) == TYPE_DICTIONARY else {}
		# 卡号以服务端为准（服务端读的是大厅里四家各自的 order）；
		# 本地 player_orders.json 只在自己那一家可信，2/3 号窗口那几家可能是猜的/空的。
		var srv_main := int(main_info.get("card", 0))
		var srv_sup := int(sup.get("card", 0))
		var ms0 := int(MAIN_SLOTS[g])
		var ss0 := int(SUPPORT_SLOTS[g])
		if srv_main <= 0 and srv_sup <= 0:
			# 服务端还没给这一家的卡：**不拿本地卡序顶替**（会显示错的人 + 遮罩对不上），
			# 直接把这家的两个位子强制盖住，等 char_states 到了再翻回来。
			_force_mask[ms0] = true
			_force_mask[ss0] = true
			continue
		_force_mask.erase(ms0)
		_force_mask.erase(ss0)
		# A 案：两个位子各摆各的卡、各遮各的（不再「协战发动后搬到主战位」——
		# 那样主战卡会凭空消失，看起来就像协战卡跑到了主战位上）
		var main_card := srv_main
		# 只有真的变了才重设 —— _set_card 会把技能图标按钮收起来，
		# 每次 state 都重设的话图标会一闪就没、根本点不到。
		var ms := int(MAIN_SLOTS[g])
		var ss := int(SUPPORT_SLOTS[g])
		var mb := _slots.get(ms, null) as TextureButton
		if main_card <= 0:
			# 服务端没给卡号 = 这一家没发动过 → 保持遮罩，别去 load card_00.png
			_force_mask[ms] = true
		elif int(_slot_card.get(ms, -1)) != main_card \
				or (mb != null and mb.texture_normal == null):
			_force_mask.erase(ms)
			_set_card(ms, main_card)
			changed = true
		var sb2 := _slots.get(ss, null) as TextureButton
		if srv_sup > 0 and (int(_slot_card.get(ss, -1)) != srv_sup \
				or (sb2 != null and sb2.texture_normal == null)):
			_set_card(ss, srv_sup)
			changed = true
		# 拿不到协战卡号就什么都不做（别把位子藏起来 —— 会露出桌布，
		# 而且别人那一家能看到遮罩图层、看起来像「有卡」，更难判断）
		# 协战覆盖期间：协战位整张藏起来（卡已经在主战位上了，不能显示两张）
		if sb2 != null and srv_sup > 0:
			sb2.visible = true
		if _debug_cards and seat == _view_seat:
			print("[CARDS] 我 seat=%d  主战=%d 协战=%d  位子→卡 %s"
				% [seat, main_card, srv_sup, str(_slot_card)])
	return changed


# 这个位子（1..8）要不要因为「没发动过 / 已过期」而遮住
# 这个位子是不是「被玩家手动遮罩的协战卡」
func _manual_muted_slot(slot: int) -> bool:
	var seat := _seat_of_group((slot - 1) >> 1)
	# ★ 只对自己那一家生效（用户口径 2026-11-06）：
	#   以前不分座位，服务端又把全桌的遮罩表发下来 → 别人遮罩过自己的协战卡，
	#   我们这边就会把他的卡 `set_hidden(false)` → 能点开看技能（身份泄露）。
	if seat != _view_seat:
		return false
	var shown := int(_slot_card.get(slot, -1))
	return shown > 0 and int(_support_mute.get(seat, 0)) == shown


# 这个位子上摆的那张卡「寿命到头」了吗？（服务端 char_states 里的 expired）
func _slot_expired(slot: int) -> bool:
	var seat := _seat_of_group((slot - 1) >> 1)
	var st: Dictionary = _char_states.get(seat, {})
	var shown := int(_slot_card.get(slot, -1))
	if st.is_empty() or shown <= 0:
		return false
	for kind2 in ["main", "support"]:
		var cand: Dictionary = st.get(kind2, {}) if typeof(st.get(kind2)) == TYPE_DICTIONARY else {}
		if int(cand.get("card", -1)) == shown:
			return bool(cand.get("expired", false))
	return false


func _char_masked(slot: int) -> bool:
	var seat := _seat_of_group((slot - 1) >> 1)
	if seat == _view_seat:
		# 自己的卡：手动遮罩的协战卡 + 寿命到头的卡（到期 = 永久盖，不能取消）
		return _manual_muted_slot(slot) or _slot_expired(slot)
	# 别人的卡：没发动过 / 两风场过期 → 盖。
	# ★ 【云外镜】(26S1)：我持有它时，服务端会给别人所有**没过期**的卡 open=True
	#   → 下面 `not open` 为假 → **无视遮罩**（这条不能被手动遮罩逻辑挡掉，
	#   所以手动遮罩只在上面的「自己那家」分支里判）。
	var st: Dictionary = _char_states.get(seat, {})
	if st.is_empty():
		return true                     # 还没有这一家的状态 → 先盖住（宁可看不见，别显示错的人）
	# 按「位子上实际摆的那张卡」去 char_states 里找它的状态（A 案：按卡算）
	var shown := int(_slot_card.get(slot, -1))
	if shown <= 0:
		# 位子上没有卡号（服务端对"别人没发动过"的卡不再下发真实卡号）
		# → 一律盖住，别把桌布露出来（用户口径 2026-11-06）
		return true
	var d := {}
	for kind2 in ["main", "support"]:
		var cand: Dictionary = st.get(kind2, {}) if typeof(st.get(kind2)) == TYPE_DICTIONARY else {}
		if int(cand.get("card", -1)) == shown:
			d = cand
			break
	if d.is_empty():
		return true                     # 状态里找不到这张卡（卡序没同步 / 已过期）→ 盖住
	if bool(d.get("expired", false)):
		return true                     # 两风场过了 → 永久遮罩
	return not bool(d.get("open", false))   # 没发动过 → 默认遮罩


# ── 协战卡「遮罩」：服务端下发的 support_mute = {座位: 卡号} ──────────
# 遮罩就是每张人物卡自己的 `Cover` 子节点（贴图 = hidden_card.png，和「没发动 / 过期」
# 同一张图）—— 画在卡身上，天然贴合、也不会糊到重叠的另一张卡。
# 要不要盖由 _char_masked() 决定。
func set_support_muted(data) -> void:
	var sig := JSON.stringify(data)
	if sig == _sup_mute_sig:
		return
	_sup_mute_sig = sig
	_support_mute.clear()
	if typeof(data) == TYPE_DICTIONARY:
		for k in (data as Dictionary).keys():
			var c := int((data as Dictionary)[k])
			if c > 0:
				_support_mute[int(k)] = c
	_refresh_hidden()


func _refresh_hidden() -> void:
	for i in range(1, 9):
		# A 案：遮罩**只看这张卡自己**（发动过 → 揭开；没发动过 → 盖着；两风场后永久盖）
		var hidden := _char_masked(i)
		if _force_mask.has(i):
			hidden = true
		var manual := _manual_muted_slot(i)
		var b := _slots.get(i, null) as TextureButton
		if b == null:
			continue
		# 遮罩画在卡自己身上（子节点）→ 天然贴合，也不会糊到重叠的另一张卡上
		if b.has_method("set_covered"):
			b.call("set_covered", _cover_tex, hidden)
		if b.has_method("set_hidden"):
			# 手动遮罩只盖图、卡保持可点（不然长按就取消不了了）
			b.call("set_hidden", hidden and not manual)
