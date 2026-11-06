class_name TilePiece
extends Node2D

const SelFrame := preload("res://sel_frame.gd")   # 统一彩框（图片）

# 一张牌的 7 种显示形式，每种对应一个子 Sprite2D
const FORMS := ["face", "face_meld", "back", "back_meld", "river", "rot", "dora",
	"back_rot"]
# 横版贴图（长边是水平方向）：只有「横置」这一种；牌河是竖版扁平图
const HORZ_FORMS := ["rot", "back_rot"]

const HOVER_RAISE := 25.0      # 悬停时抬起的高度

# ── 移动动画（打牌 / 换牌 / 副露 / 配牌 / 摸牌 / 理牌 全靠这里）──
#   服务端状态是「瞬间就位」的，这里只把「已经发生的结果」演出来，
#   不参与任何逻辑判定：丢帧、卡顿最多是跳一下，不会不同步。
const FLY_SEC := 0.22                 # 默认飞行时长（秒）；距离远会略微变长
static var anim_enabled := true       # 总开关（出问题一行关掉，恢复原来的瞬移）
static var anim_scale := 1.0          # >1 = 更快，0 = 关闭

var _fly_from := Vector2.INF          # 「从哪儿飞出来」（只有出现型动画需要）
var _tw: Tween = null                 # 正在飞的补间


static func anim_on() -> bool:
	return anim_enabled and anim_scale > 0.0


# 由 main.gd 在「这张牌马上要从隐藏变可见」时调用，指定起飞的起点
func fly_from(p: Vector2) -> void:
	_fly_from = p


func is_flying() -> bool:
	return _tw != null and _tw.is_valid()


func _kill_tw() -> void:
	if _tw != null and _tw.is_valid():
		_tw.kill()
	_tw = null


func _stamp_self() -> void:
	var tb := get_parent()
	if tb is TileBank:
		stamp = (tb as TileBank).frame_id


# from → to 的补间；appear = 这是「凭空出现」（顺便做一个很小的小到大）
func _fly(from: Vector2, to: Vector2, rot_deg: float, p_scale: Vector2, dur: float, appear: bool) -> void:
	_kill_tw()
	position = from
	z_index = 50                      # 飞行中盖住别的牌
	if appear:
		scale = p_scale * 0.6
	_update_hit(false, p_scale)       # 飞行中不吃点击，免得点歪
	_tw = create_tween()
	_tw.set_trans(Tween.TRANS_CUBIC).set_ease(Tween.EASE_OUT)
	_tw.tween_property(self, "position", to, dur)
	_tw.parallel().tween_property(self, "rotation_degrees", rot_deg, dur)
	_tw.parallel().tween_property(self, "scale", p_scale, dur)
	_tw.tween_callback(_on_fly_done)


func _on_fly_done() -> void:
	_tw = null
	z_index = 1 if (_hovered and _hover_enabled) else 0
	_update_hit(_hover_enabled, scale)

signal clicked(slot_index: int)
# 牌河里的牌被点了（参数 = 这张牌在 round_discards 里的全场 seq）
signal river_clicked(discard_seq: int)
# 副露牌被点了（鬼门·乙：整组副露用彩框选中）
signal meld_clicked(meld_seat: int, meld_group: int)

var entity_id := ""
var kind := ""
var slot_index := -1           # 这张牌当前是手牌里的第几张（0 起；非手牌为 -1）
var form := ""                 # 上一次显示的形式（reset 时用来判断要不要清悬停）
var stamp := -1                # 最近一次被摆放的帧号（TileBank.end_frame 用来隐藏没再出现的牌）

var _sprites := {}
var _base_size := Vector2.ZERO
var _base_pos := Vector2.ZERO
var _hovered := false
var _hover_enabled := false
var _hit: Control
var discard_seq := -1          # 牌河里这张牌的全场 seq（换牌技能用）
var face_down := false         # 是不是被换牌技能暗置进来的
var river_seat := -1           # 这张牌是谁牌河里的（换自己牌河 / 换暗置牌要分）
var _river_clickable := false
var _meld_clickable := false        # 副露可点（鬼门选副露）
var _sel_frame: Node2D = null        # 选中框：彩框图（SelFrame）

const FORM_SPRITE := {
	"hand": "face",
	"face_meld": "face_meld",
	"back": "back",
	"back_meld": "back_meld",
	"river": "river",
	"rot": "rot",
	"back_rot": "back_rot",
	"dora": "dora",
}

# texes: form -> Texture2D；base_size: 一张竖牌的目标显示尺寸（tile_size）
func setup(p_entity_id: String, p_kind: String, texes: Dictionary, base_size: Vector2) -> void:
	entity_id = p_entity_id
	kind = p_kind
	name = p_entity_id
	_base_size = base_size
	for f in FORMS:
		var spr := _ensure(f)
		var t: Texture2D = texes.get(f)
		if t == null:
			spr.visible = false
			continue
		spr.texture = t
		var ts := t.get_size()
		if ts.x <= 0.0 or ts.y <= 0.0:
			continue
		# ★ 把原始大图缩到牌的实际显示尺寸
		var s := 0.0
		if f in HORZ_FORMS:
			s = base_size.y / ts.x          # 横版：长边 = 牌高
		else:
			s = base_size.x / ts.x          # 竖版：宽 = 牌宽
		spr.scale = Vector2.ONE * s
		spr.visible = false
	_make_hit()

# 透明点击区：手牌的悬停/点击都由这张牌自己处理（不经过 main.gd）
func _make_hit() -> void:
	_hit = Control.new()
	_hit.name = "Hit"
	_hit.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_hit)
	_hit.mouse_entered.connect(_on_hover_enter)
	_hit.mouse_exited.connect(_on_hover_exit)
	_hit.gui_input.connect(_on_hit_gui_input)

func _ensure(f: String) -> Sprite2D:
	if _sprites.has(f) and is_instance_valid(_sprites[f]):
		return _sprites[f]
	var spr := Sprite2D.new()
	spr.name = f
	spr.centered = true
	spr.visible = false
	add_child(spr)
	_sprites[f] = spr
	return spr

func show_form(f: String) -> void:
	for key in _sprites:
		var spr: Sprite2D = _sprites[key]
		if is_instance_valid(spr):
			spr.visible = (key == f)

# 某个显示形式在父节点坐标系里的**实际**尺寸（含节点 p_scale）
# ★ 副露摆位用它，别用 mw / mrw×(302/360) 之类的估算 —— 估大一点就会裂出缝
func form_size(f: String, p_scale: Vector2 = Vector2.ONE) -> Vector2:
	var spr: Sprite2D = _sprites.get(String(FORM_SPRITE.get(f, "")))
	if spr == null or spr.texture == null:
		return _base_size * p_scale
	return spr.texture.get_size() * spr.scale * p_scale


func apply_form(f: String) -> void:
	show_form(String(FORM_SPRITE.get(f, "")))

# form 用服务端语义（hand/face_meld/back/back_meld/river/rot/dora）
# pos/rot 是相对父节点（TileBank）的坐标；p_scale 用于副露/其他家等整体缩放
func apply_state(f: String, pos: Vector2, rot_deg: float = 0.0, p_scale: Vector2 = Vector2.ONE) -> void:
	var sprite_name := String(FORM_SPRITE.get(f, ""))
	var want_vis := sprite_name != ""
	var was_vis := visible and form != ""            # 上一帧是不是已经在台面上
	var is_hand := sprite_name == "face"
	form = f
	_hover_enabled = is_hand
	if is_hand:
		# 这张牌原来是牌河里可点的（换牌技能），现在进手里了：
		# 不清掉的话点击会走 river_clicked 分支 → 手牌永远选不中
		_river_clickable = false
		discard_seq = -1
	if not is_hand:
		# 离开手牌 → 清掉悬停，避免残留抬起
		_hovered = false
		# ★ 也清掉「选牌时 50% 暗」的残留：牌是同一个 TilePiece 复用的，
		#   手牌里选中/没选中会改 modulate；变成副露/牌河的牌以后没人再改回来，
		#   于是友引摊完面子那几张会带着 50% 亮度进副露区。
		modulate = Color(1.0, 1.0, 1.0, 1.0)
	var lift := -HOVER_RAISE if (_hover_enabled and _hovered) else 0.0
	var target := pos + Vector2(0.0, lift)
	var moved := (not was_vis) or position.distance_to(target) > 1.0 \
		or absf(rot_deg - rotation_degrees) > 0.5 or (p_scale - scale).length() > 0.02
	_base_pos = pos

	if not want_vis:
		# 这张牌下台了（进牌山 / 被技能拿走）：不用动画，直接隐藏
		_kill_tw()
		position = target
		rotation_degrees = rot_deg
		scale = p_scale
		visible = false
		z_index = 0
		_fly_from = Vector2.INF
		apply_form(f)
		_update_hit(false, p_scale)
		_stamp_self()
		return

	var dur := 0.0
	if anim_on() and moved:
		if was_vis:
			# 同台面内挪动：按距离微调时长，远一点多给点时间；但别太慢
			dur = FLY_SEC * clampf(position.distance_to(target) / 200.0, 0.5, 1.5)
		else:
			dur = FLY_SEC * 0.8          # 出现（配牌 / 摸牌）：干脆一点
		dur = dur / maxf(anim_scale, 0.05)

	if dur <= 0.001:
		# 目标没变（0.6 秒轮询、40 多处重复调用都会打到这儿）→ 一个字都不要动，
		# 否则正在飞的补间会被瞬间拽回终点。
		_kill_tw()
		position = target
		rotation_degrees = rot_deg
		scale = p_scale
		_fly_from = Vector2.INF
		z_index = 1 if (_hovered and _hover_enabled) else 0
	else:
		var from := position
		if not was_vis and _fly_from != Vector2.INF:
			from = _fly_from            # 配牌 / 摸牌：从牌山那个方向飞过来
		_fly_from = Vector2.INF
		_fly(from, target, rot_deg, p_scale, dur, not was_vis)

	visible = true
	apply_form(f)
	_update_hit(_hover_enabled and not is_flying(), p_scale)
	if _sel_frame != null and is_instance_valid(_sel_frame):
		SelFrame.fit(_sel_frame, _base_size)          # 换形态/缩放后框跟着变
	_stamp_self()

func _update_hit(enabled: bool, p_scale: Vector2) -> void:
	if _hit == null:
		return
	_hit.mouse_filter = Control.MOUSE_FILTER_STOP \
		if (enabled or _meld_clickable) else Control.MOUSE_FILTER_IGNORE
	# _hit 是子节点，节点自身的 scale 已经缩放它了；再乘 p_scale 会变成平方，
	# 牌河/牌山的点击框就会又小又偏。这里只按基准尺寸来。
	var sz := _base_size
	_hit.size = sz
	_hit.position = -sz * 0.5

# 父节点 reset() 时调用：只隐藏，不动 _hovered（否则每次轮询都会把抬起状态清掉）
func hide_piece() -> void:
	_kill_tw()
	visible = false
	_hover_enabled = false
	if _hit != null:
		_hit.mouse_filter = Control.MOUSE_FILTER_IGNORE
	if form != "hand":
		_hovered = false
		z_index = 0

# 立直选牌：不能保持听牌的牌亮度降到 50%
func set_dimmed(v: bool) -> void:
	modulate = Color(0.5, 0.5, 0.5, 1.0) if v else Color(1.0, 1.0, 1.0, 1.0)


# 整体亮度（1.0 = 正常）。压制视角里牌河的暗置牌是「明牌但 65% 亮」。
func set_alpha(a: float) -> void:
	var v := clampf(float(a), 0.05, 1.0)
	modulate = Color(v, v, v, 1.0)

# ── 悬停抬起：动效完全由这张牌自己负责 ──
func _on_hover_enter() -> void:
	if not _hover_enabled or _hovered or is_flying():
		return                                # 正在飞 → 先别抢位置，落地再说
	_hovered = true
	z_index = 1
	position = _base_pos + Vector2(0.0, -HOVER_RAISE)

func _on_hover_exit() -> void:
	if not _hovered:
		return
	_hovered = false
	if is_flying():
		return                                # 位置归补间管
	z_index = 0
	position = _base_pos

# 换牌技能：牌河里的牌临时变成可点
func set_river_info(seq: int, down: bool, seat := -1) -> void:
	discard_seq = seq
	face_down = down
	river_seat = seat


func set_river_clickable(v: bool) -> void:
	_river_clickable = v
	if _hit != null and not _hover_enabled:
		_hit.mouse_filter = Control.MOUSE_FILTER_STOP if v else Control.MOUSE_FILTER_IGNORE


# 副露牌可点（鬼门）：和手牌/牌河一样走自己的 Hit 控制，不吃别的逻辑
func set_meld_clickable(v: bool) -> void:
	_meld_clickable = v
	if _hit != null and not _hover_enabled:
		_hit.mouse_filter = Control.MOUSE_FILTER_STOP if v else Control.MOUSE_FILTER_IGNORE


# 选中的牌河牌：黄色框
# ── 彩框（彩虹描边）：两个来源共用同一道框，各记一份，互不覆盖 ──
#   _frame_pick  = 技能选牌（点选牌河牌 / 选副露）
#   _frame_claim = 鸣牌提示（这张牌能被吃 / 碰 / 杠）
var _frame_pick := false
var _frame_claim := false


func set_selected_frame(v: bool) -> void:
	if _frame_pick == v:
		return
	_frame_pick = v
	_frame_sync()


func set_claim_frame(v: bool) -> void:
	if _frame_claim == v:
		return
	_frame_claim = v
	_frame_sync()


func _frame_sync() -> void:
	# 彩框 = 自绘的彩虹描边（sel_frame_item.gd），盖在牌上；不吃鼠标
	var sz := _base_size                              # 局部分尺寸：父节点 scale 会再乘一次
	if _sel_frame == null:
		_sel_frame = SelFrame.attach(self, sz)
	else:
		SelFrame.fit(_sel_frame, sz)
	if _sel_frame != null:
		_sel_frame.visible = _frame_pick or _frame_claim


func _on_hit_gui_input(event: InputEvent) -> void:
	if _river_clickable:
		if event is InputEventMouseButton:
			var mb2 := event as InputEventMouseButton
			if mb2.pressed and mb2.button_index == MOUSE_BUTTON_LEFT:
				river_clicked.emit(discard_seq)
				if _hit != null:
					_hit.accept_event()
		return
	if _meld_clickable:
		if event is InputEventMouseButton:
			var mb3 := event as InputEventMouseButton
			if mb3.pressed and mb3.button_index == MOUSE_BUTTON_LEFT:
				meld_clicked.emit(int(get_meta("meld_seat", -1)),
					int(get_meta("meld_group", -1)))
				if _hit != null:
					_hit.accept_event()
		return
	if not _hover_enabled:
		return
	if event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		if mb.pressed and mb.button_index == MOUSE_BUTTON_LEFT:
			clicked.emit(slot_index)
			if _hit != null:
				_hit.accept_event()
