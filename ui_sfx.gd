extends Node
## ui_sfx.gd —— UI 音效（素材：Cailiao/Voice/音效/UI）
##
## 四个时机（用户 2026-11-14 指定）：
##   "hover"  鼠标悬浮到手牌上、牌刚往上抬的那一下        ← tile_piece.gd:_on_hover_enter
##   "button" 吃/碰/杠/立直/自摸/荣 按钮出现的那一下      ← main.gd:srv_layout_buttons
##   "plate"  结算播报「底座底座」横向拉开的那一下        ← 和牌播报.gd:_reveal_plate
##   "create" 账号创建成功的那一下                        ← real_start.gd:_cc_confirm
##   "discard" 一张牌打到牌桌上的那一下                   ← main.gd:_discard_at / 出牌事件
##   "stamp" 结算播报盖大红印章的那一下                   ← 和牌播报.gd:_play_level
##   "press" 真初始场景里点任意按钮的那一下                 ← hook_buttons / 手写 hit-test
##   "strips" 番种条从上往下扫开的那一下（素材 番种条扫开.wav）        ← 和牌播报.gd:_reveal_strips
##
## 用法（**不用 autoload、不用 class_name**，preload 后直接调静态方法）：
##     const UiSfx := preload("res://ui_sfx.gd")
##     UiSfx.play("hover")
## 播放器节点在第一次播放时挂到 /root 下（场景切换不会丢），资源按名字缓存，
## 4 路轮转，短音效叠在一起不会互相吞掉。

const ROOT := "res://Cailiao/Voice/音效/UI/"
const FILES := {
	"hover": "鼠标悬浮在牌上.wav",      # 0.07s
	"button": "出现按钮.wav",           # 0.20s
	"plate": "底座底座拉开.wav",        # 0.75s
	#  番种条扫开：由 1.mp3 预处理而来（见 _tmp/make_strips_wav.py）——1.mp3 自身前 50ms
	#  全静音、之后是 170ms 的渐强（25% 音量在 120ms、峰值 210ms），只裁静音仍然「慢半拍」，
	#  所以直接切到 85ms、并把起手 180ms 的渐强压平（2.4→1.0 增益），存成 WAV 免掉 mp3 延迟。
	"strips": "番种条扫开.wav",         # 番种条扫开（2026-11-15 二次修）
	"press": "按按钮.mp3",             # 真初始场景里所有按钮的点击音
	"create": "创建成功.mp3",          # 账号创建成功（用户 2026-11-15）
	"discard": "出牌.mp3",             # 牌打出去那一刻（我方点击 / 别家出牌事件）
	"stamp": "印章.mp3",               # 结算播报 满贯/跳满/倍满/三倍满/役满 大红印章
}
const DEFAULT_DB := -6.0

# ★ 2026-11-15：每首素材「首音」前的静音（实测）。不裁的话 play() 之后先静几十 ms
#   才出声 —— 用户听感就是「慢半拍」。play() 用 from_position 跳过这段。
#   印章不裁：它的对齐是按未裁的时间轴调的（见 和牌播报.gd:STAMP_SYNC_MS）。
#   番种条（strips）不在这里裁：它换成了预处理好的 番种条扫开.wav，从 0 播就是响的。
const TRIM := {
	"press": 0.032,       # 按按钮.mp3：首音 40ms
	"discard": 0.025,     # 出牌.mp3：首音 30ms
}

static var muted := false
static var _host: Node = null
static var _cache := {}
static var _players: Array = []
static var _pi := 0


static func _ensure_host() -> Node:
	if _host != null and is_instance_valid(_host):
		return _host
	var tree := Engine.get_main_loop() as SceneTree
	if tree == null or tree.root == null:
		return null
	var n := Node.new()
	n.name = "UiSfxHost"
	n.process_mode = Node.PROCESS_MODE_ALWAYS     # 暂停里也要能响
	tree.root.add_child(n)
	if n.get_parent() == null:
		# ★ 在别人的 _ready() 里第一次 play 时会踩这个：root 正在 setup 子节点，
		#   add_child 直接失败（日志：「Parent node is busy setting up children」）→
		#   播放器根本没进树，音效就整段不响 / 拖到很晚。改成延后挂。
		tree.root.add_child.call_deferred(n)
	_host = n
	_players.clear()
	for i in range(4):
		var p := AudioStreamPlayer.new()
		p.name = "Ui%d" % i
		p.volume_db = DEFAULT_DB
		n.add_child(p)
		_players.append(p)
	return n


static func _stream(sfx: String) -> AudioStream:
	if _cache.has(sfx):
		return _cache[sfx] as AudioStream
	var fname := String(FILES.get(sfx, ""))
	if fname == "":
		push_warning("ui_sfx: 不认识的音效名 %s" % sfx)
		return null
	var path := ROOT + fname
	if not ResourceLoader.exists(path):
		push_warning("ui_sfx: 找不到 %s" % path)
		return null
	var s := ResourceLoader.load(path) as AudioStream
	_cache[sfx] = s
	return s


## 给一棵子树里**所有** BaseButton 挂「按按钮」音效（幂等：靠 meta 标记）。
## 用法：场景 _ready 末尾 UiSfx.hook_buttons(self)；之后动态新建的按钮再调一次。
static func hook_buttons(root: Node, volume_db := -8.0) -> void:
	if root == null or not root.is_inside_tree():
		return
	for n in root.find_children("*", "BaseButton", true, false):
		var b := n as BaseButton
		if b == null or b.has_meta("ui_sfx_hooked"):
			continue
		b.set_meta("ui_sfx_hooked", true)
		b.pressed.connect(func() -> void: play("press", volume_db))


## 预热：开局就把播放器和四个音频读进内存（第一次 play 不再有读盘/解码那一下）
static func warm() -> void:
	if _ensure_host() == null:
		return
	for k in FILES.keys():
		_stream(String(k))


static func play(sfx: String, volume_db := DEFAULT_DB) -> void:
	if muted:
		return
	var s := _stream(sfx)
	if s == null:
		return
	if _ensure_host() == null:
		return
	var pl: AudioStreamPlayer = null
	for p in _players:
		if not (p as AudioStreamPlayer).playing:
			pl = p
			break
	if pl == null:                                # 全在放 → 轮转顶掉最早那个
		pl = _players[_pi % _players.size()]
		_pi += 1
	pl.volume_db = volume_db
	pl.stream = s
	var _from := float(TRIM.get(sfx, 0.0))     # 跳过素材开头的静音
	if pl.is_inside_tree():
		pl.play(_from)
	else:
		pl.call_deferred("play", _from)    # 宿主还没挂进树 → 下一帧再放（只差 1 帧）
