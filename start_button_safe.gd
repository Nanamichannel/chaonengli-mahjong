extends TextureButton

# 给用户自己的开始按钮用的动效：不改变 pivot / 初始缩放，只做悬停放大、按下缩小回弹（不消失）
@export var hover_scale := 1.08
@export var press_scale := 0.92
@export var hover_time := 0.30
@export var exit_time := 0.40
@export var press_time := 0.28

var tween: Tween
var base_scale := Vector2.ONE

func _ready() -> void:
	base_scale = scale
	# 缩放锚点改到自身中心；同时补偿位置，保证按钮视觉位置不变
	pivot_offset = size * 0.5
	position -= pivot_offset * (Vector2.ONE - scale)
	mouse_entered.connect(_on_enter)
	mouse_exited.connect(_on_exit)
	pressed.connect(_on_press)

func _on_enter() -> void:
	_tween_to(base_scale * hover_scale, Tween.TRANS_ELASTIC, Tween.EASE_OUT, hover_time)

func _on_exit() -> void:
	_tween_to(base_scale, Tween.TRANS_ELASTIC, Tween.EASE_OUT, exit_time)

func _on_press() -> void:
	scale = base_scale * press_scale
	_tween_to(base_scale, Tween.TRANS_BACK, Tween.EASE_OUT, press_time)

func _tween_to(target: Vector2, trans: Tween.TransitionType, ease: Tween.EaseType, dur: float) -> void:
	if tween != null and tween.is_valid():
		tween.kill()
	tween = create_tween()
	tween.set_trans(trans).set_ease(ease)
	tween.tween_property(self, "scale", target, dur)
