extends Control
## 技能进场特效（Card1~46）。
##
## 结构（编辑器里就是按这个建的）：
##   特效/进场特效
##     FX (CanvasLayer, layer=200)      ← 永远压在所有界面之上（选牌 20 / 播报 31~32 / 面板 60~100）
##       Frame (Control, 全屏)          ← 尺寸基准（逻辑视口 1920x1080）
##         Scale (Node2D, scale=1.2)    ← 1600x900 的素材等比放大到逻辑视口
##           card1 (AnimationPlayer)    ← 名字必须叫 cardN（用户口径）
##           img_card1 (Sprite2D)       ← 显示节点，跟 cardN **平级**
##           ... card46 / img_card46
##
## ★ 为什么 Sprite2D 是 cardN 的**兄弟**、不是子节点：
##   Godot 的 CanvasItem 只跟「直接父节点」继承变换；父节点要是 AnimationPlayer(Node)，
##   变换链就断了 → Scale 的 1.2 白设（特效不贴着屏幕右边缘）。所以显示节点必须直接挂在 Scale 下。
##   Animation 的轨道路径因此写成 "../img_cardN:xxx"。
##
## 素材：Cailiao/UI/技能特效/atlas_cardN.png（每卡 55 帧拼成一张图集，BPTC 压缩，
##       46 张共约 92 MB 显存）。帧的裁剪偏移写在 Animation 的 img:position 轨道里，
##       所以视觉上跟 1600x900 全屏 png 完全一致，只是纹理小了 40 倍。
##
## 用户口径 2026-11-04：
##   · 技能生效那一刻播放（main.gd 的 _apply_broadcast 调 play_card）
##   · 特效贴着屏幕边缘；1600x900 设计 → 1920x1080 等比放大
##   · 上一个没放完下一个又来了 → 晚到的那个 z 更高，旧的照旧放完
##   · 60fps 的时长不能改（每帧 1/60 秒，55 帧 → 0.9167 秒）

const CARD_N := 46
const BASE_SIZE := 1600.0        # 素材设计宽度（png 1600x900）
const Z_MAX := 4000

var _players := {}               # card -> AnimationPlayer
var _sprites := {}               # card -> Sprite2D（img_cardN，Scale 的子节点）
var _scale_node: Node2D = null
var _z := 0                      # z 递增计数（后到的更大）


func _ready() -> void:
	_scale_node = get_node_or_null("FX/Frame/Scale") as Node2D
	for i in range(1, CARD_N + 1):
		var ap := get_node_or_null("FX/Frame/Scale/card%d" % i) as AnimationPlayer
		if ap == null:
			continue
		_players[i] = ap
		ap.animation_finished.connect(_on_anim_finished.bind(i))
		var sp := _scale_node.get_node_or_null("img_card%d" % i) as Sprite2D
		if sp != null:
			_sprites[i] = sp
			sp.visible = false          # 空闲不参与绘制：46 个 sprite 全关，一帧省 46 个 draw item
			sp.region_rect = Rect2(0, 0, 0, 0)
	_rescale()
	get_viewport().size_changed.connect(_rescale)


# 1600x900 素材 → 逻辑视口（1920x1080）等比放大。
# 用 Frame 的实际尺寸算，不写死 1.2：换分辨率 / 换 stretch 模式都不会错位。
func _rescale() -> void:
	if _scale_node == null or not is_instance_valid(_scale_node):
		return
	var frame := get_node_or_null("FX/Frame") as Control
	var w := 0.0
	if frame != null:
		w = frame.size.x
	if w <= 1.0:
		w = float(get_viewport_rect().size.x)
	if w <= 1.0:
		return
	var k := w / BASE_SIZE
	if not is_equal_approx(_scale_node.scale.x, k):
		_scale_node.scale = Vector2(k, k)


## 播放某张卡的进场特效。重复调用同一张 = 从头再播（z 抬到最新）。
func play_card(card: int) -> void:
	var ap := _players.get(int(card)) as AnimationPlayer
	if ap == null or not is_instance_valid(ap):
		return
	var sp := _sprites.get(int(card)) as Sprite2D
	_z += 1
	if _z > Z_MAX:
		_z = 1
	if sp != null:
		sp.z_index = _z
		sp.z_as_relative = false
		sp.visible = true
	if ap.is_playing() and String(ap.current_animation) == "play":
		ap.stop()
	ap.play("play")


## 放完不留残片：把 region 清成空。
func _on_anim_finished(_name: String, card: int) -> void:
	var ap := _players.get(int(card)) as AnimationPlayer
	if ap == null or not is_instance_valid(ap):
		return
	if ap.is_playing():
		return                    # 同一张卡又被点了一次 → 让它继续
	var sp := _sprites.get(int(card)) as Sprite2D
	if sp != null:
		sp.region_rect = Rect2(0, 0, 0, 0)
		sp.visible = false


## 立刻清掉所有正在播的特效（换局 / 重开 / 退回菜单时用）。
func clear_all() -> void:
	for card in _players:
		var ap := _players[card] as AnimationPlayer
		if ap == null or not is_instance_valid(ap):
			continue
		ap.stop()
		var sp := _sprites.get(card) as Sprite2D
		if sp != null:
			sp.region_rect = Rect2(0, 0, 0, 0)
			sp.visible = false
