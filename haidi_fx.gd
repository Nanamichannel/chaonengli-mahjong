extends CanvasLayer
## 【海底】(34-2) 技能特效 —— 运行时按「对着牌桌」算的 4 层合成（掉帧优化版）
##
## 分层数据（4 张图/帧，分辨率按重要性分配，解码像素总量 ≈ 原来 31%）：
##   v1 = M1 = (1-a₁) + a₁·C₁   相乘层的乘数 → 直接乘屏幕        640×360
##   v2 = (a₂, A₃, a₄)          叠加 / 总的 / 波浪 的 alpha        480×270
##   v3 = P3 = a₃·C₃            总的（预乘）                        640×360
##   v4 = C₄                    波浪的颜色（差值用，**只有 in 段有**）320×180
## 叠加层颜色是常数 (0.30, 0.76, 0.89)，写在着色器里。
##
## 优化点（2026-11-08 掉帧）：
##   ① 分辨率下调（4×960×540 → 640/480/320 三档）
##   ② loop / out 段**不播 v4**（那两段本来没有波浪），着���器用 use_v4 跳过差值
##   ③ 视频纹理只在**段开始时设一次**（ImageTexture 是原地更新的，不用每帧重设）
##
## 时段（60fps）：in 0..671 → loop 671..736（循环等自摸）→ out 746..1175。
## 层级 30：牌桌之上、和牌播报(31) 之下。

signal out_finished

const DIR := "res://Cailiao/UI/haidi/"
const FX_LAYER := 30

const SHADER_CODE := """
shader_type canvas_item;
uniform sampler2D screen_tex : hint_screen_texture, filter_linear;
uniform sampler2D v1 : filter_linear, repeat_disable;
uniform sampler2D v2 : filter_linear, repeat_disable;
uniform sampler2D v3 : filter_linear, repeat_disable;
uniform sampler2D v4 : filter_linear, repeat_disable;
uniform int use_v4 = 0;
const vec3 C2 = vec3(0.30, 0.76, 0.89);

void fragment() {
	vec3 b = texture(screen_tex, SCREEN_UV).rgb;      // 牌桌
	vec3 m1 = texture(v1, UV).rgb;
	// ★ 兜底：换段那一帧纹理还是空的（全黑）→按 1.0 处理，
	//   否则 b * 0 = 整屏全黑（v1 是乘数）。
	if (dot(m1, vec3(0.3333333)) < 0.002) m1 = vec3(1.0);
	vec3 c = b * m1;                                  // ① 相乘
	vec4 m = texture(v2, UV);                         // (a2, A3, a4)
	vec3 lo = 2.0 * c * C2;                           // 叠加：c<0.5
	vec3 hi = 1.0 - 2.0 * (1.0 - c) * (1.0 - C2);      // 叠加：c>=0.5
	vec3 ov = mix(lo, hi, step(vec3(0.5), c));
	c = mix(c, ov, m.r);                              // ② 叠加
	c = texture(v3, UV).rgb + (1.0 - m.g) * c;        // ③ 总的（预乘）
	if (use_v4 == 1) {
		c = mix(c, abs(c - texture(v4, UV).rgb), m.b);  // ④ 波浪（差值）
	}
	COLOR = vec4(c, 1.0);
}
"""

var state := "idle"              # idle / in / loop / out / frozen
var _rect: ColorRect = null
var _mat: ShaderMaterial = null
var _ps: Array = []              # v1..v4 的播放器（v4 可能为空闲）
var _bound := false              # 本段的纹理是否已经塞给着色器
var _bind_wait := 0              # 换段后先等几帧再换绑（那时纹理还是全黑的）
var _frozen_tex: Texture2D = null
var _tex_white: ImageTexture = null   # 中性纹理：v1 = 白（乘 1，画面原样）
var _tex_black: ImageTexture = null   # 中性纹理：v2/v3/v4 = 黑（不影响画面）


func _ready() -> void:
	layer = FX_LAYER
	name = "HaidiFxLayer"
	visible = false
	var sh := Shader.new()
	sh.code = SHADER_CODE
	_mat = ShaderMaterial.new()
	_mat.shader = sh
	# ★ 中性纹理：着色器绝不能采到「未初始化 / 空白」的采样器上（v1 是乘数，采到黑 = 整屏黑）。
	#   没数据时就用它们：画面完全原样（效果不出现）。
	_tex_white = _mk_solid(Color(1, 1, 1, 1))
	_tex_black = _mk_solid(Color(0, 0, 0, 1))
	_mat.set_shader_parameter("v1", _tex_white)
	_mat.set_shader_parameter("v2", _tex_black)
	_mat.set_shader_parameter("v3", _tex_black)
	_mat.set_shader_parameter("v4", _tex_black)
	_rect = ColorRect.new()
	_rect.name = "HaidiQuad"
	_rect.color = Color(1, 1, 1, 1)
	_rect.material = _mat
	_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_rect)
	for i in range(4):
		_ps.append(_mk_player("HaidiV%d" % (i + 1)))
	process_priority = 100


## 4×4 纯色纹理（中性兜底用）
func _mk_solid(c: Color) -> ImageTexture:
	var img := Image.create_empty(4, 4, false, Image.FORMAT_RGBA8)
	img.fill(c)
	return ImageTexture.create_from_image(img)


## 纹理里到底有没有真内容（刚 play() 的那几帧是全黑的）
func _tex_has_content(t: Texture2D) -> bool:
	var img := t.get_image()
	if img == null or img.is_empty():
		return false
	var w := img.get_width()
	var h := img.get_height()
	if w <= 0 or h <= 0:
		return false
	var sum := 0.0
	for yy in [h / 4, h / 2, (h * 3) / 4]:
		for xx in [w / 4, w / 2, (w * 3) / 4]:
			var c := img.get_pixel(xx, yy)
			sum += float(c.r) + float(c.g) + float(c.b)
	return sum > 0.002


func _mk_player(nm: String) -> VideoStreamPlayer:
	var p := VideoStreamPlayer.new()
	p.name = nm
	p.expand = true
	p.loop = false
	p.volume_db = -80.0
	p.autoplay = false
	p.visible = false
	p.finished.connect(_on_finished.bind(nm))
	add_child(p)
	return p


func _load(path: String) -> VideoStream:
	if not ResourceLoader.exists(path):
		push_warning("海底特效：缺少 " + path)
		return null
	return load(path) as VideoStream


func _fit() -> void:
	var vp := Vector2(1920, 1080)
	if is_inside_tree():
		vp = get_viewport().get_visible_rect().size
	_rect.position = Vector2.ZERO
	_rect.size = vp


## seg: in / loop / out
func _start(seg: String, loop: bool) -> bool:
	var n := 4 if seg == "in" else 3
	var streams: Array = []
	for i in range(n):
		var s := _load(DIR + "haidi_%s_v%d.ogv" % [seg, i + 1])
		if s == null:
			return false
		streams.append(s)
	# 不在用的那几路停掉（省解码）
	for i in range(4):
		var p: VideoStreamPlayer = _ps[i]
		if i >= n:
			p.stop()
			p.stream = null
			_mat.set_shader_parameter("v%d" % (i + 1), _tex_black)   # 不要参考已释放的纹理
	_fit()
	visible = true
	# ★ 换段：刚 play() 时 get_video_texture() 已经有对象，但内容是**全黑**（还没解出第一帧）。
	#   先留 3 帧继续用上一段的纹理 —— 段间内容本来就连续（实测
	#   in 末 0.843 ≈ loop 首 0.842 ≈ out 首 0.831），看不见跳变。
	_bind_wait = 3
	_bound = false
	for i in range(n):
		var p: VideoStreamPlayer = _ps[i]
		p.loop = loop
		p.stream = streams[i]
		p.paused = false
		p.play()
	_mat.set_shader_parameter("use_v4", 1 if seg == "in" else 0)
	return true


func play_in() -> void:
	if state != "idle":
		return
	if not _start("in", false):
		return
	state = "in"


func play_out() -> void:
	if state == "out" or state == "frozen":
		return
	if not _start("out", false):
		return
	state = "out"


func is_running_out() -> bool:
	return state == "out"


func is_active() -> bool:
	return state != "idle"


func frozen_texture() -> Texture2D:
	return _frozen_tex


func clear() -> void:
	state = "idle"
	for p in _ps:
		if p != null and is_instance_valid(p):
			p.stop()
			p.stream = null
			p.visible = false
	_frozen_tex = null
	_bound = false
	_bind_wait = 0
	if _mat != null:
		_mat.set_shader_parameter("v1", _tex_white)
		_mat.set_shader_parameter("v2", _tex_black)
		_mat.set_shader_parameter("v3", _tex_black)
		_mat.set_shader_parameter("v4", _tex_black)
	visible = false


func _process(_dt: float) -> void:
	if state == "idle" or _mat == null:
		return
	if _bound:
		return                                   # 纹理已经绑过：ImageTexture 原地更新，不用每帧再设
	if _bind_wait > 0:
		_bind_wait -= 1
		return                                   # 换段后的前几帧：先别换绑（那时是空的黑纹理）
	var ok := true
	for i in range(4):
		var p: VideoStreamPlayer = _ps[i]
		if p.stream == null:
			continue
		var t := p.get_video_texture()
		if t == null:
			ok = false                           # 还没解出第一帧
			continue
		if i == 0 and not _tex_has_content(t):
			ok = false                           # v1（乘数）还是空纹理 → 这一帧先不换绑
			continue
		_mat.set_shader_parameter("v%d" % (i + 1), t)
	_bound = ok


func _on_finished(nm: String) -> void:
	if nm != "HaidiV1":
		return                                   # 只按 v1 的事件走
	if state == "in":
		if _start("loop", true):
			state = "loop"
		else:
			state = "idle"
			visible = false
		return
	if state == "out":
		for p in _ps:
			p.paused = true                      # 全部停在最后一帧
		var t: Texture2D = _ps[0].get_video_texture()
		if t != null:
			_frozen_tex = t
		state = "frozen"
		emit_signal("out_finished")
