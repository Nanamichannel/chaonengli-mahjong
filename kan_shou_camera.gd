extends Camera2D
## 鉴赏界面摄像机：
##   · 中键拖动 + 松手惯性（摩擦衰减）
##   · 滚轮缩放视角（以鼠标为中心，平滑逼近，不跳变）
## 边界由场景脚本注入 limit_rect

@export var friction := 2600.0        ## 惯性衰减（px/s²），越大停得越快
@export var drag_gain := 1.0          ## 拖动灵敏度
@export var limit_rect := Rect2()     ## 可移动范围（世界坐标）；size=0 不限制

@export_group("滚轮缩放")
@export var zoom_step := 1.15         ## 每格滚轮的倍数
@export var zoom_min := 0.45
@export var zoom_max := 2.6      ## zoom_max_auto=false 时用这个固定上限
@export var zoom_max_auto := true    ## true = 上限取「背景板宽度铺满屏幕」
@export var zoom_smooth := 14.0       ## 逼近速度（越大越快，指数逼近，不跳变）

var backdrop_width := 0.0            ## 由场景脚本注入（背景板视觉宽度）
var _warned_ceiling := false
var _dragging := false
var _vel := Vector2.ZERO
var _zoom_target := 1.0
var _zoom_focus := Vector2.ZERO       ## 缩放锚点（滚轮时的世界坐标）
var _zoom_anchor := Vector2.ZERO      ## 该锚点对应的屏幕坐标


func _ready() -> void:
	make_current()
	_zoom_target = zoom.x


func _input(e: InputEvent) -> void:
	if e is InputEventMouseButton:
		var mb := e as InputEventMouseButton
		match mb.button_index:
			MOUSE_BUTTON_MIDDLE:
				if mb.pressed:
					_dragging = true
					_vel = Vector2.ZERO
				else:
					_dragging = false          # 松手：保留 _vel，交给 _process 做惯性
				get_viewport().set_input_as_handled()
			MOUSE_BUTTON_WHEEL_UP:
				if mb.pressed:
					_set_zoom_target(_zoom_target * zoom_step, mb)
					get_viewport().set_input_as_handled()
			MOUSE_BUTTON_WHEEL_DOWN:
				if mb.pressed:
					_set_zoom_target(_zoom_target / zoom_step, mb)
					get_viewport().set_input_as_handled()

	elif e is InputEventMouseMotion and _dragging:
		var mm := e as InputEventMouseMotion
		var d := mm.relative / zoom * drag_gain
		position -= d
		var dt := maxf(get_process_delta_time(), 0.001)
		_vel = (-d / dt).limit_length(2600.0)   # 甩速上限（配合 friction 最多滑 ~1300px）
		get_viewport().set_input_as_handled()


## 记录缩放锚点：滚轮那一帧鼠标下面是哪个世界点，缩放过程中让它钉在原地
## 上限：背景板宽度刚好铺满屏幕时对应的 zoom
## 注意：只有当背景板比屏幕窄时，这个值才是「放大上限」（>1）；
## 背景板已经比屏幕宽时算出来会 <1，那样就没法放大了，此时退回固定 zoom_max。
func _zoom_ceiling() -> float:
	if zoom_max_auto and backdrop_width > 1.0:
		var c := get_viewport_rect().size.x / backdrop_width
		if c > 1.0:
			return clampf(c, 1.0, 12.0)
		if not _warned_ceiling:
			_warned_ceiling = true
			push_warning("[鉴赏] 背景板宽 %.0f ≥ 屏幕宽，自动缩放上限无意义，退回 zoom_max=%.2f" % [backdrop_width, zoom_max])
	return zoom_max


func _set_zoom_target(z: float, mb: InputEventMouseButton) -> void:
	_zoom_target = clampf(z, zoom_min, _zoom_ceiling())
	_zoom_anchor = mb.position
	# 用事件里的屏幕坐标反算世界坐标（不依赖真实光标位置，模拟输入也一致）
	_zoom_focus = (_zoom_anchor - get_viewport_rect().size * 0.5) / zoom + position


func _process(delta: float) -> void:
	if not _dragging and _vel.length_squared() > 1.0:
		position += _vel * delta
		_vel = _vel.move_toward(Vector2.ZERO, friction * delta)

	# 平滑缩放（指数逼近，先快后慢，不会一下子跳到位）
	if absf(zoom.x - _zoom_target) > 0.0005:
		var k := 1.0 - exp(-zoom_smooth * delta)
		var z := lerpf(zoom.x, _zoom_target, k)
		zoom = Vector2(z, z)
		# 让锚点世界坐标始终落在原来的屏幕位置上
		position = _zoom_focus - (_zoom_anchor - get_viewport_rect().size * 0.5) / zoom
		_clamp_to_limit()
		return

	_clamp_to_limit()


## 把镜头限制在 limit_rect 内（视口半宽/半高按 zoom 折算）
func _clamp_to_limit() -> void:
	if limit_rect.size == Vector2.ZERO:
		return
	var half := get_viewport_rect().size * 0.5 / zoom
	var lo := limit_rect.position + half
	var hi := limit_rect.end - half
	if lo.x > hi.x:
		lo.x = (limit_rect.position.x + limit_rect.end.x) * 0.5
		hi.x = lo.x
	if lo.y > hi.y:
		lo.y = (limit_rect.position.y + limit_rect.end.y) * 0.5
		hi.y = lo.y
	position = position.clamp(lo, hi)
