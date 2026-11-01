extends RefCounted

# ── 统一的「选手牌」界面（默认视觉）────────────────────────────────
#   手牌亮度全部 50% → 单击选中（恢复亮度、再点取消）
#   → 选满 x 张后出现「开始」按钮 → 点「开始」把选中的 slot_index 交给 on_confirm。
#
# 用法（main.gd 里，一个实例 hand_pick 全局共用）：
#   hand_pick.begin(自己的 picks 数组, 3, {"on_change": _refresh_xx_btn,
#                                          "on_confirm": _xx_confirm,
#                                          "start_btn": true, "min": 1})
#   hand_pick.toggle(3)     # 点了第 3 张手牌
#   hand_pick.sync()        # 手牌重画后重新上暗
#   hand_pick.end()         # 收起（把亮度还给「立直」那套规则）
#
# picks 是**按引用**传进来的数组，所以各技能原来的代码照样能读它。
# 自己带「开始」按钮的界面（策略/南风/压制/换牌/避开）传 start_btn=false，
# 用 on_change 回调去刷新自己的按钮；ready() 就是「选够了没有」。

const DEFAULT_START_TEX := "res://Cailiao/UI/tiaoguo.png"
const BTN_W := 220.0

var host: Node = null            # Main：放 UI、弹 toast、读立直状态
var bank = null                  # TileBank（遍历手牌 piece 用）
var active := false
var picks: Array = []
var want := 1
var min_pick := 1
var on_change := Callable()
var on_confirm := Callable()
var ui: Control = null
var start_btn: TextureButton = null


func setup(p_host: Node, p_bank) -> void:
	host = p_host
	bank = p_bank


func begin(p_picks: Array, p_want: int, opts := {}) -> void:
	active = true
	picks = p_picks
	picks.clear()
	want = maxi(1, int(p_want))
	min_pick = clampi(int(opts.get("min", want)), 0, want)
	on_change = opts.get("on_change", Callable())
	on_confirm = opts.get("on_confirm", Callable())
	if bool(opts.get("start_btn", false)):
		_make_ui(String(opts.get("start_tex", DEFAULT_START_TEX)))
	sync()
	refresh()


func has(i: int) -> bool:
	return picks.has(int(i))


func count() -> int:
	return picks.size()


# 选够了没有（自带按钮的界面拿它决定「开始」的显隐）
func ready() -> bool:
	return active and picks.size() >= min_pick and picks.size() <= want


func toggle(i: int) -> void:
	if not active:
		return
	var idx := int(i)
	if idx < 0:
		return
	if picks.has(idx):
		picks.erase(idx)
	elif picks.size() < want:
		picks.append(idx)
	else:
		if host != null:
			host.call("_toast", "最多选 %d 张" % want)
		return
	sync()
	refresh()


# 刷新「开始」按钮 + 通知调用方（选中的张数变了）
func refresh() -> void:
	if start_btn != null and is_instance_valid(start_btn):
		start_btn.visible = ready()
	if on_change.is_valid():
		on_change.call()


# 手牌亮度：选牌时全变 50%、选中的恢复；没在选牌时退回「立直」那套暗化
func sync() -> void:
	if bank == null:
		return
	var riichi := false
	if host != null:
		riichi = bool(host.get("riichi_selecting"))
	for q in bank.all_pieces():
		var tp := q as TilePiece
		if tp == null or not tp.visible or tp.form != "hand":
			continue
		if active:
			tp.set_dimmed(not picks.has(tp.slot_index))
		else:
			var ok := true
			if riichi and host != null:
				ok = bool(host.call("srv_can_riichi_with", tp.kind))
			tp.set_dimmed(riichi and not ok)


func end() -> void:
	active = false
	if ui != null and is_instance_valid(ui):
		ui.queue_free()
	ui = null
	start_btn = null
	sync()


func _make_ui(tex_path: String) -> void:
	if ui != null or host == null:
		return
	var vp: Vector2 = host.call("get_viewport_rect").size
	var holder: Node = host.get_parent()
	if holder == null:
		holder = host
	ui = Control.new()
	ui.name = "HandPickUI"
	ui.z_index = 250
	holder.add_child(ui)
	ui.position = Vector2.ZERO
	var tex: Texture2D = null
	if host != null and host.has_method("btn_tex"):
		tex = host.call("btn_tex", "ok") as Texture2D      # 用牌桌的「确认」贴图（自带字）
	if tex == null:
		tex = load(tex_path) as Texture2D
	var bh := 70.0
	if tex != null and tex.get_width() > 0:
		bh = BTN_W * float(tex.get_height()) / float(tex.get_width())
	start_btn = TextureButton.new()
	start_btn.name = "HandPickStart"
	start_btn.texture_normal = tex
	start_btn.ignore_texture_size = true
	start_btn.stretch_mode = TextureButton.STRETCH_SCALE
	start_btn.focus_mode = Control.FOCUS_NONE
	start_btn.size = Vector2(BTN_W, bh)
	start_btn.position = Vector2((vp.x - BTN_W) * 0.5, vp.y - 330.0)
	start_btn.visible = false
	if on_confirm.is_valid():
		start_btn.pressed.connect(on_confirm)
	ui.add_child(start_btn)
	
