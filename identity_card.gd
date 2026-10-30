extends TextureButton

# ── 桌面身份卡（Card01..Card08）──────────────────────────────────────
# · 鼠标悬停：轻微放大；按下：先缩小再回弹（弹性很弱）
# · 左键按下：在卡牌正上方展开两个技能按钮（左右对称）
# · 悬停技能按钮：按钮正上方显示技能气泡
# · 隐藏状态：整张卡不响应鼠标，技能按钮/气泡全部收起
#
# 技能按钮/气泡的图片都是离线生成好的 PNG（Cailiao/skill/ui/），
# 运行时只按角色卡编号 load，不在现场拼接文字和底板。

# 技能按钮被按下（card_no = 这张卡的人物编号，index = 0/1 对应 Skill1/Skill2）
signal skill_pressed(card_no: int, index: int)
# Skill2 下的「东南西北」被选中（wind：0=东 1=南 2=西 3=北）
signal wind_picked(card_no: int, wind: int)
# 技能图标被展开 / 收起（点人物卡切换）
signal skills_toggled(card_no: int, open: bool)
# 长按人物卡（≥0.7 秒）：用来开关「协战卡遮罩」
signal long_pressed(card_no: int)
# 这张卡被按下（单击 / 长按都算）：用来「点谁谁在上」（主战 ⇄ 协战 层级）
signal touched(card_no: int)

const WIND_TEX := [
	"res://Cailiao/skill/ui/winds/dong.png",
	"res://Cailiao/skill/ui/winds/nan.png",
	"res://Cailiao/skill/ui/winds/xi.png",
	"res://Cailiao/skill/ui/winds/bei.png",
]

const DATA_PATH := "res://Cailiao/skill/ui/skills.json"
const BTN_DIR := "res://Cailiao/skill/ui/buttons/"
const BUB_DIR := "res://Cailiao/skill/ui/bubbles/"

const HOVER_SCALE := 1.05
const LONG_PRESS_SEC := 0.5        # 长按多久算「长按」（协战卡遮罩用）
const SKILL_WIDTH_RATIO := 0.4       # 技能按钮长度 = 卡牌宽度 × 2/5
const SKILL_ASPECT := 446.0 / 250.0  # skillbutton.png 原始比例
const BUBBLE_WIDTH_RATIO := 2.4
# ── 遮罩样式（可改）──────────────────────────────────────────────
# 卡面遮罩的颜色/透明度（贴图本身用 identity_cards.HIDDEN_CARD_TEX / 外部 skin/card_cover.png）
static var COVER_TINT := Color(1, 1, 1, 1)
# 技能图标上「已屏蔽」的半透明遮罩
static var SKILL_MUTE_COLOR := Color(1, 1, 1, 0.5)

static var _skill_data: Dictionary = {}

var _base_scale := Vector2.ONE
var _base_position := Vector2.ZERO
var _card_no := 0
var _hidden := false
var _skills_visible := false
var _hover_gen := 0          # 悬停代次：技能按钮算卡牌延伸，见 _on_unhover
var _skill_disabled := [false, false]   # 本小局用过的一次性技能（灰掉、不能点）
var _wind_buttons: Array = []   # Skill2 下的四个小按钮（东南西北）
var _wind_frames: Array = []    # 每个按钮的红框
var _wind_picker := false
var _wind_picked := -1
var _scale_tween: Tween
var _skill_buttons: Array = []
var _skill_frames: Array = [null, null]   # 技能图标外面的框（Card03「自信」用红色）
var _bubbles: Array = []
var _cover: TextureRect = null  # 卡面遮罩（子节点 → 自动跟随位置/旋转/缩放/悬停放大）
var _press_gen := 0             # 长按计时代次：松手 / 再按下都会作废上一次

func _ready() -> void:
	_base_scale = scale
	_base_position = position
	# 缩放锚点放到卡牌中心：悬停/按下时绕中心放大缩小。
	# Control 的 pivot 会随 scale 改变视觉位置，这里把 position 反补回去，
	# 保证初始视觉位置不变；旋转过的卡牌要按 rotation 旋转补偿向量。
	pivot_offset = size * 0.5
	position = _base_position - pivot_offset + (pivot_offset * _base_scale).rotated(rotation)
	focus_mode = Control.FOCUS_NONE
	mouse_filter = Control.MOUSE_FILTER_STOP
	_skill_buttons = [get_node_or_null("Skill1"), get_node_or_null("Skill2")]
	_bubbles = [get_node_or_null("Bubble1"), get_node_or_null("Bubble2")]
	for i in range(2):
		var sb := _skill_buttons[i] as TextureButton
		if sb != null:
			sb.visible = false
			sb.focus_mode = Control.FOCUS_NONE
			sb.mouse_filter = Control.MOUSE_FILTER_STOP
			sb.pivot_offset = sb.size * 0.5
			sb.z_index = 0            # ★ 必须是 0：抬 z 会让子节点跨卡覆盖（见文件头注释）
			if not sb.mouse_entered.is_connected(_on_skill_enter):
				sb.mouse_entered.connect(_on_skill_enter.bind(i))
			if not sb.mouse_exited.is_connected(_on_skill_exit):
				sb.mouse_exited.connect(_on_skill_exit.bind(i))
			if not sb.pressed.is_connected(_on_skill_pressed.bind(i)):
				sb.pressed.connect(_on_skill_pressed.bind(i))
		var bub := _bubbles[i] as TextureRect
		if bub != null:
			bub.visible = false
			bub.mouse_filter = Control.MOUSE_FILTER_IGNORE
			bub.stretch_mode = TextureRect.STRETCH_SCALE
			# ★ 气泡（悬停技能图标时的文字图）要永远压在别的牌/面板上面：
		#   牌河/副露的牌按 y 当 z（能到 1000+），面板 250~1600，所以给 2000。
		#   技能按钮本身仍然是 0（抬 z 会跨卡覆盖，见文件头）。
		bub.z_index = 2000
	# 卡面遮罩：作为**卡的子节点**，这样位置/旋转/缩放（含悬停放大）天然贴合；
	# z 高于卡面、Skill1/2（z=2）、气泡（z=3）→ 盖住整张卡
	_cover = TextureRect.new()
	_cover.name = "Cover"
	_cover.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_cover.stretch_mode = TextureRect.STRETCH_SCALE
	# ★ z 必须是 0：遮罩要和「这张卡」同层级（靠树顺序盖住卡内图标/气泡），
	#   不能抬 z —— 抬了就变成「协战的遮罩盖住主战卡」。它是最后一个子节点 → 最上。
	_cover.z_index = 0
	_cover.visible = false
	add_child(_cover)
	_layout_cover()
	_build_wind_picker()
	if not mouse_entered.is_connected(_on_hover):
		mouse_entered.connect(_on_hover)
	if not mouse_exited.is_connected(_on_unhover):
		mouse_exited.connect(_on_unhover)
	if not button_down.is_connected(_on_button_down):
		button_down.connect(_on_button_down)
	if not button_up.is_connected(_on_button_up):
		button_up.connect(_on_button_up)
	if not resized.is_connected(_layout_skill_ui):
		resized.connect(_layout_skill_ui)
	if _card_no <= 0:
		var nm := String(name)
		if nm.begins_with("Card"):
			var n := int(nm.substr(4))
			if n > 0:
				set_character(n)
	_layout_skill_ui()

# 当前这张卡显示的是第几号人物（1..46）→ 换对应的技能按钮和气泡
func set_character(card_no: int) -> void:
	_card_no = card_no
	_skills_visible = false
	reset_skill_frames()
	_ensure_data()
	var entry: Dictionary = _skill_data.get(str(card_no), {})
	var arr: Array = entry.get("skills", []) if typeof(entry) == TYPE_DICTIONARY else []
	for i in range(2):
		var sb := _skill_buttons[i] as TextureButton
		var bub := _bubbles[i] as TextureRect
		if sb != null:
			if i < arr.size() and typeof(arr[i]) == TYPE_DICTIONARY:
				var s: Dictionary = arr[i]
				var suf := _variant_tag()
				sb.texture_normal = load((BTN_DIR + "card_%02d_%d_%s.png") % [card_no, i + 1, suf])
				sb.tooltip_text = String(s.get("name", ""))
			else:
				sb.texture_normal = null
		if bub != null:
			if i < arr.size() and typeof(arr[i]) == TYPE_DICTIONARY:
				bub.texture = load((BUB_DIR + "card_%02d_%d_%s.png") % [card_no, i + 1, _variant_tag()])
			else:
				bub.texture = null
	_layout_skill_ui()
	_apply_skills()
	_apply_icon_override()      # 传承换的图标要保住（set_character 会重设贴图）

# 传承（Card16 S1）：把某个技能图标换成「复制来的那个技能」（**只换图标，不换卡面**）
var _icon_override := {}        # index(0/1) -> [card_no, skill_no(1 起)]


func set_skill_icon(index: int, from_card: int, from_skill: int = 1) -> void:
	var i := int(index)
	if int(from_card) <= 0:
		_icon_override.erase(i)
	else:
		_icon_override[i] = [int(from_card), int(from_skill)]
	_apply_icon_override()


func _apply_icon_override() -> void:
	if _icon_override.is_empty():
		return
	var tag := _variant_tag()
	for i in [0, 1]:
		if not _icon_override.has(i):
			continue
		var v: Array = _icon_override[i]
		var c := int(v[0])
		var k := int(v[1])
		var sb := _skill_buttons[i] as TextureButton
		if sb != null:
			sb.texture_normal = load((BTN_DIR + "card_%02d_%d_%s.png") % [c, k, tag])
		var bub := _bubbles[i] as TextureRect
		if bub != null:
			bub.texture = load((BUB_DIR + "card_%02d_%d_%s.png") % [c, k, tag])


# 隐藏 / 解除隐藏（其他玩家用技能时由 identity_cards.gd 调用）
func set_hidden(v: bool) -> void:
	_hidden = v
	if v:
		_skills_visible = false
		close_wind_picker()
		_kill_scale_tween()
		scale = _base_scale
	mouse_filter = Control.MOUSE_FILTER_IGNORE if v else Control.MOUSE_FILTER_STOP
	_apply_skills()

func _variant_tag() -> String:
	var r := int(round(rotation_degrees))
	r = ((r % 360) + 360) % 360
	if r == 90:
		return "r90"
	if r == 180:
		return "r180"
	if r == 270:
		return "rm90"
	return "r0"


func _ensure_data() -> void:
	if not _skill_data.is_empty():
		return
	if not FileAccess.file_exists(DATA_PATH):
		return
	var rf := FileAccess.open(DATA_PATH, FileAccess.READ)
	if rf == null:
		return
	var d = JSON.parse_string(rf.get_as_text())
	if typeof(d) == TYPE_DICTIONARY:
		_skill_data = d

# 卡牌是否横躺（旋转 90 / 270）：此时保持正置的技能气泡，
# 它的「宽」会落在卡牌的竖直轴上，算偏移时要用宽而不是高。
func _is_sideways() -> bool:
	var r := int(round(rotation_degrees)) % 360
	if r < 0:
		r += 360
	return r == 90 or r == 270

func _layout_cover() -> void:
	if _cover == null or not is_instance_valid(_cover):
		return
	_cover.position = Vector2.ZERO
	_cover.size = size
	_cover.stretch_mode = TextureRect.STRETCH_SCALE


# 卡面遮罩：on=true 盖住（贴图 = 现成的 hidden_card.png），on=false 揭开
func set_covered(tex: Texture2D, on: bool) -> void:
	if _cover == null or not is_instance_valid(_cover):
		return
	if tex != null:
		_cover.texture = tex
	_cover.modulate = COVER_TINT
	_cover.visible = bool(on) and _cover.texture != null
	if _cover.visible:
		for b in _bubbles:                     # 盖住状态下气泡也别飘出来
			var br := b as TextureRect
			if br != null:
				br.visible = false
	_layout_cover()


func is_covered() -> bool:
	return _cover != null and is_instance_valid(_cover) and _cover.visible


func _layout_skill_ui() -> void:
	_layout_cover()
	var target_len := size.x * SKILL_WIDTH_RATIO
	var short_len := target_len * (250.0 / 446.0)
	var gap := size.x * 0.02
	var top_center_y := -gap - short_len * 0.5
	var local_rot := -rotation_degrees
	for i in range(2):
		var sb := _skill_buttons[i] as TextureButton
		if sb == null:
			continue
		var dir_sign := -1.0 if i == 0 else 1.0
		var cx := size.x * 0.5 + dir_sign * (target_len + gap) * 0.5
		var k := target_len / 446.0
		var stex := sb.texture_normal
		var sw := 446.0
		var sh := 250.0
		if stex != null:
			sw = float(stex.get_width())
			sh = float(stex.get_height())
		sb.size = Vector2(sw, sh) * k
		sb.pivot_offset = sb.size * 0.5
		sb.position = Vector2(cx - sb.size.x * 0.5, top_center_y - sb.size.y * 0.5)
		sb.rotation_degrees = local_rot
		sb.ignore_texture_size = true
		sb.stretch_mode = TextureButton.STRETCH_SCALE
		var ov := _muted_overlays.get(i, null) as ColorRect
		if ov != null and is_instance_valid(ov):
			ov.position = Vector2.ZERO
			ov.size = sb.size
		var fr := _skill_frames[i] as ReferenceRect
		if fr != null and is_instance_valid(fr):
			fr.position = Vector2.ZERO
			fr.size = sb.size
		var bub := _bubbles[i] as TextureRect
		if bub == null:
			continue
		var bw := size.x * BUBBLE_WIDTH_RATIO
		var bh := bw * 0.3
		if bub.texture != null and bub.texture.get_width() > 0:
			bh = bw * float(bub.texture.get_height()) / float(bub.texture.get_width())
		bub.size = Vector2(bw, bh)
		bub.pivot_offset = bub.size * 0.5
		# 气泡在「远离卡牌」这个方向上的长度：
		# 卡牌正放（0/180）时是气泡的高，横躺（90/270）时是气泡的宽。
		var ext_y := bw if _is_sideways() else bh
		var bub_center_y := top_center_y - short_len * 0.5 - gap - ext_y * 0.5
		bub.position = Vector2(cx - bw * 0.5, bub_center_y - bh * 0.5)
		bub.rotation_degrees = local_rot
		bub.stretch_mode = TextureRect.STRETCH_SCALE
	_layout_wind_picker()


# Skill2 下面四个「东南西北」：小的方按钮，排在 Skill2 正上方一行
func _layout_wind_picker() -> void:
	var sb := _skill_buttons[1] as TextureButton
	if sb == null or _wind_buttons.is_empty():
		return
	var side := sb.size.y * 0.82
	var gap := side * 0.12
	var total := side * _wind_buttons.size() + gap * (_wind_buttons.size() - 1)
	var left := (sb.size.x - total) * 0.5
	for i in range(_wind_buttons.size()):
		var b := _wind_buttons[i] as TextureButton
		var f := _wind_frames[i] as ReferenceRect
		if b == null:
			continue
		b.size = Vector2(side, side)
		b.pivot_offset = b.size * 0.5
		b.position = Vector2(left + float(i) * (side + gap), -side - gap)
		if f != null:
			f.position = Vector2.ZERO
			f.size = b.size


func _build_wind_picker() -> void:
	var sb := _skill_buttons[1] as TextureButton
	if sb == null:
		return
	for i in range(WIND_TEX.size()):
		var b := TextureButton.new()
		b.name = "Wind%d" % (i + 1)
		var tex := load(String(WIND_TEX[i])) as Texture2D
		b.texture_normal = tex
		b.ignore_texture_size = true
		b.stretch_mode = TextureButton.STRETCH_SCALE
		b.focus_mode = Control.FOCUS_NONE
		b.mouse_filter = Control.MOUSE_FILTER_STOP
		b.visible = false
		b.z_index = 0             # 同上：不抬 z
		b.pressed.connect(_on_wind_pressed.bind(i))
		b.mouse_entered.connect(_on_wind_hover.bind(true))
		b.mouse_exited.connect(_on_wind_hover.bind(false))
		sb.add_child(b)
		var f := ReferenceRect.new()
		f.name = "Frame"
		f.editor_only = false                            # 只在编辑器画的话，运行时看不到
		f.border_color = Color(1.0, 0.16, 0.16, 1.0)     # 选中的字：红框
		f.border_width = 4.0
		f.mouse_filter = Control.MOUSE_FILTER_IGNORE
		f.visible = false
		b.add_child(f)
		_wind_buttons.append(b)
		_wind_frames.append(f)


func open_wind_picker() -> void:
	_skills_visible = true          # 技能图标必须展开着，东南西北才有地方挂
	_apply_skills()
	_wind_picker = true
	_wind_picked = -1
	for i in range(_wind_buttons.size()):
		(_wind_buttons[i] as TextureButton).visible = true
		(_wind_frames[i] as ReferenceRect).visible = false
	_layout_wind_picker()


func close_wind_picker() -> void:
	_wind_picker = false
	_wind_picked = -1
	for i in range(_wind_buttons.size()):
		(_wind_buttons[i] as TextureButton).visible = false
		(_wind_frames[i] as ReferenceRect).visible = false


# 鼠标从卡牌/技能图标移到东南西北上：保持放大（和技能按钮一样）
func _on_wind_hover(inside: bool) -> void:
	if _hidden:
		return
	if inside:
		_hover_gen += 1
		_tween_scale(_base_scale * HOVER_SCALE, 0.14)
		return
	_hover_gen += 1
	var gen := _hover_gen
	await get_tree().create_timer(0.12).timeout
	if gen != _hover_gen or _hidden:
		return
	_tween_scale(_base_scale, 0.16)


func _on_wind_pressed(i: int) -> void:
	if _hidden or not _wind_picker:
		return
	_wind_picked = i
	for k in range(_wind_frames.size()):
		(_wind_frames[k] as ReferenceRect).visible = (k == i)
	wind_picked.emit(_card_no, i)


func _apply_skills() -> void:
	for i in range(2):
		var sb := _skill_buttons[i] as TextureButton
		if sb != null:
			var has_tex := sb.texture_normal != null
			sb.visible = (not _hidden) and _skills_visible and has_tex
			sb.mouse_filter = Control.MOUSE_FILTER_IGNORE if _hidden else Control.MOUSE_FILTER_STOP
		var bub := _bubbles[i] as TextureRect
		if bub != null and (sb == null or not sb.visible):
			bub.visible = false

# 技能按钮算「卡牌的延伸」：鼠标从卡牌移到 Skill1/2 上时不能缩回去。
# 离开卡牌 / 离开技能按钮都先等 0.12 秒；这期间只要又进了卡牌或另一个技能按钮，
# 就把这一代（gen）作废，缩小动作不会执行。
func _on_hover() -> void:
	if _hidden:
		return
	_hover_gen += 1
	_tween_scale(_base_scale * HOVER_SCALE, 0.14)

func _on_unhover() -> void:
	if _hidden:
		return
	_hover_gen += 1
	var gen := _hover_gen
	await get_tree().create_timer(0.12).timeout
	if gen != _hover_gen or _hidden:
		return
	_tween_scale(_base_scale, 0.16)

# 单击人物卡：只负责展开 / 收起技能图标。
# （不再做「缩小 → 回弹」，卡牌保持当前大小：鼠标还在上面就一直是悬停放大状态）
func _on_button_down() -> void:
	touched.emit(_card_no)          # 点谁谁在上（主战 ⇄ 协战）
	# 先起「长按 0.7 秒」的计时（松手就作废）——协战卡遮罩靠它
	_press_gen += 1
	_watch_long_press(_press_gen)
	if _hidden:
		return
	_skills_visible = not _skills_visible
	if not _skills_visible:
		close_wind_picker()
	_apply_skills()
	skills_toggled.emit(_card_no, _skills_visible)

func _on_button_up() -> void:
	_press_gen += 1              # 松手 → 这一次长按作废


# 按住不放 0.7 秒 → 发 long_pressed（只发一次；松手后要重新按）
# ★ 被遮罩的卡也要能长按：不然协战卡一遮上就再也取消不了。
func _watch_long_press(gen: int) -> void:
	await get_tree().create_timer(LONG_PRESS_SEC).timeout
	if gen != _press_gen:
		return
	if not Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT):
		return                       # 已经松手（只是没收到 button_up）→ 不算长按
	long_pressed.emit(_card_no)


func _on_skill_enter(i: int) -> void:
	if _hidden or not _skills_visible:
		return
	_hover_gen += 1                       # 取消「缩回去」，保持放大
	_tween_scale(_base_scale * HOVER_SCALE, 0.14)
	var bub := _bubbles[i] as TextureRect
	if bub != null and bub.texture != null:
		bub.visible = true

# 按下技能图标 = 发动这个技能（真正能不能用由服务端判定）
var _muted_overlays := {}          # index -> ColorRect


# 技能图标上的「半透明白色遮罩」：盖住 = 这个技能不再自动询问
# 运行时改遮罩颜色：identity_card.set_cover_tint(Color(1, 0.8, 0.9, 0.9))
static func set_cover_tint(c: Color) -> void:
	COVER_TINT = c


func set_skill_muted(index: int, muted: bool) -> void:
	var sb := _skill_buttons[index] as TextureButton if index >= 0 and index < _skill_buttons.size() else null
	if sb == null:
		return
	var ov := _muted_overlays.get(index, null) as ColorRect
	if muted:
		if ov == null or not is_instance_valid(ov):
			ov = ColorRect.new()
			ov.name = "Muted%d" % (index + 1)
			ov.color = SKILL_MUTE_COLOR
			ov.mouse_filter = Control.MOUSE_FILTER_IGNORE
			sb.add_child(ov)
			_muted_overlays[index] = ov
		ov.position = Vector2.ZERO
		ov.size = sb.size
		ov.visible = true
	elif ov != null and is_instance_valid(ov):
		ov.visible = false


func is_skill_muted(index: int) -> bool:
	var ov := _muted_overlays.get(index, null) as ColorRect
	return ov != null and is_instance_valid(ov) and ov.visible


func set_skill_disabled(index: int, disabled: bool) -> void:
	var i: int = clampi(index, 0, 1)
	_skill_disabled[i] = bool(disabled)
	var sb := _skill_buttons[i] as TextureButton
	if sb == null:
		return
	sb.disabled = bool(disabled)
	sb.modulate = Color(0.42, 0.42, 0.42, 1.0) if disabled else Color(1, 1, 1, 1)


func is_skill_disabled(index: int) -> bool:
	return bool(_skill_disabled[clampi(index, 0, 1)])


# 给技能图标套一个框（Card03「自信」：整小局红色框，不能取消）
func set_skill_frame(index: int, on: bool, color := Color(1.0, 0.12, 0.12, 1.0)) -> void:
	var i := clampi(index, 0, 1)
	var sb := _skill_buttons[i] as TextureButton
	if sb == null:
		return
	var fr := _skill_frames[i] as ReferenceRect
	if fr == null or not is_instance_valid(fr):
		if not on:
			return
		fr = ReferenceRect.new()
		fr.name = "SkillFrame"
		fr.editor_only = false
		fr.mouse_filter = Control.MOUSE_FILTER_IGNORE
		fr.z_index = 0             # 同上：抬 z 会跨卡覆盖
		sb.add_child(fr)
		_skill_frames[i] = fr
	fr.border_color = color
	fr.border_width = 14.0          # 卡牌整体缩放 ~0.3，14 本地像素 ≈ 4 屏幕像素
	fr.position = Vector2.ZERO
	fr.size = sb.size
	fr.visible = on


func reset_skill_frames() -> void:
	for i in range(2):
		var fr := _skill_frames[i] as ReferenceRect
		if fr != null and is_instance_valid(fr):
			fr.visible = false


func _on_skill_pressed(i: int) -> void:
	if _hidden or not _skills_visible:
		return
	if _skill_disabled[clampi(i, 0, 1)]:
		return
	skill_pressed.emit(_card_no, i)


func _on_skill_exit(i: int) -> void:
	var bub := _bubbles[i] as TextureRect
	if bub != null:
		bub.visible = false
	if _hidden:
		return
	_hover_gen += 1
	var gen := _hover_gen
	await get_tree().create_timer(0.12).timeout
	if gen != _hover_gen or _hidden:
		return
	_tween_scale(_base_scale, 0.16)


# 发动技能成功后收起 Skill1/Skill2（相当于再点一次人物卡）
func collapse_skills() -> void:
	_skills_visible = false
	close_wind_picker()
	for b in _bubbles:
		if b != null:
			(b as TextureRect).visible = false
	_apply_skills()

func _tween_scale(target: Vector2, dur: float) -> void:
	_kill_scale_tween()
	_scale_tween = create_tween()
	_scale_tween.set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_OUT)
	_scale_tween.tween_property(self, "scale", target, dur)

func _kill_scale_tween() -> void:
	if _scale_tween != null and _scale_tween.is_valid():
		_scale_tween.kill()
