extends Node
##
## mobile_input.gd —— 移动端输入适配（autoload: MobileInput）
##
## 桌面端完全不动（不是 mobile 就直接不处理）。
## 移动端做两件事：
##   1. 长按 0.45 秒 → 合成一次右键按下/抬起，让所有「右键=取消/关面板」的旧逻辑照常工作
##   2. 拖动超过 14px 就不算长按（避免拖动牌序时误触发取消）
##
## 已知取舍：长按触发后，抬手时系统仍会补一次左键（emulate_mouse_from_touch），
## 所以长按的路径上可能同时看到「右键取消」和「左键点击」。若某处冲突，
## 在那个界面里用 Input.get_last_mouse_velocity() 或自己的状态机区分即可。
##

const HOLD_SEC := 0.45
const MOVE_TOL := 14.0

var _index := -1
var _origin := Vector2.ZERO
var _held := 0.0
var _consumed := false


func _ready() -> void:
	set_process(false)
	if OS.has_feature("mobile"):
		set_process(true)


func _input(event: InputEvent) -> void:
	if not OS.has_feature("mobile"):
		return
	if event is InputEventScreenTouch:
		var st := event as InputEventScreenTouch
		if st.pressed and _index == -1:
			_index = st.index
			_origin = st.position
			_held = 0.0
			_consumed = false
		elif not st.pressed and st.index == _index:
			_index = -1
			_held = 0.0
	elif event is InputEventScreenDrag:
		var sd := event as InputEventScreenDrag
		if sd.index == _index and sd.position.distance_to(_origin) > MOVE_TOL:
			_consumed = true          # 当成拖动/滑手势，不再判长按


func _process(delta: float) -> void:
	if _index == -1 or _consumed:
		return
	_held += delta
	if _held >= HOLD_SEC:
		_consumed = true
		_emit_right(_origin)


func _emit_right(pos: Vector2) -> void:
	for pressed in [true, false]:
		var ev := InputEventMouseButton.new()
		ev.button_index = MOUSE_BUTTON_RIGHT
		ev.pressed = pressed
		ev.position = pos
		ev.global_position = pos
		Input.parse_input_event(ev)
