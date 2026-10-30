extends TextureButton

## 图片按钮（texture_normal 直接绘制 PNG），用 scale 做动效：
##   悬停 → 弹性放大
##   移出 → 弹性缩回
##   按下 → 立即缩小 → 弹性回弹 → 淡出消失
##
## ★ 透明度（modulate.a）只由「入场 / 消散」用**独立补间**控制。
##   以前悬停/移出也会 _kill_tween()，会把入场那条 alpha 0→1 的补间一起杀掉 ——
##   按钮正好出现在光标底下时会停在 0.2 左右 → 看起来半透明/几乎看不见（自摸按钮那个 bug）。

@export var press_scale := 0.88       # 按下瞬间缩到多小
@export var hover_scale := 1.10       # 悬停放大的比例
@export var vanish_on_press := true   # 按下后是否淡出消失（立直按钮要关掉，方便再点一次取消）
@export var hover_duration := 0.40    # 悬停放大时长
@export var exit_duration := 0.50     # 移出缩回时长
@export var press_duration := 0.30    # 回弹时长
@export var vanish_duration := 0.14   # 按下后淡出时长

var tween: Tween          # 只动 scale
var fade: Tween           # 只动 modulate:a
var _base_scale := Vector2.ONE


func _ready() -> void:
	_base_scale = scale
	resized.connect(_update_pivot)
	_update_pivot()
	pressed.connect(_on_clicked)
	mouse_entered.connect(_on_mouse_entered)
	mouse_exited.connect(_on_mouse_exited)


func _update_pivot() -> void:
	pivot_offset = size * 0.5


# 只在新出现时调用（main.gd 已保证同一按钮不会每帧重复调用）
func play_appear() -> void:
	_update_pivot()
	_kill_tween()
	_kill_fade()
	scale = _base_scale * 0.5
	modulate.a = 0.0
	tween = create_tween()
	tween.set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	tween.tween_property(self, "scale", _base_scale, 0.18)
	fade = create_tween()
	fade.tween_property(self, "modulate:a", 1.0, 0.12)


# 悬停：弹性放大（只动 scale，绝不碰 alpha）
func _on_mouse_entered() -> void:
	_kill_tween()
	modulate.a = 1.0                     # 万一入场补间被打断，这里兜一下
	tween = create_tween()
	tween.set_trans(Tween.TRANS_ELASTIC).set_ease(Tween.EASE_OUT)
	tween.tween_property(self, "scale", _base_scale * hover_scale, hover_duration)


# 移出：弹性缩回（同上）
func _on_mouse_exited() -> void:
	_kill_tween()
	modulate.a = 1.0
	tween = create_tween()
	tween.set_trans(Tween.TRANS_ELASTIC).set_ease(Tween.EASE_OUT)
	tween.tween_property(self, "scale", _base_scale, exit_duration)


# 按下：立即缩小 → 弹性回弹 → 淡出消失
func _on_clicked() -> void:
	_kill_tween()
	scale = _base_scale * press_scale
	tween = create_tween()
	tween.set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	tween.tween_property(self, "scale", _base_scale, press_duration)
	if not vanish_on_press:
		return
	tween.tween_interval(0.02)
	tween.tween_property(self, "scale", _base_scale * 0.55, vanish_duration)
	tween.tween_callback(_finish_vanish)
	_kill_fade()
	fade = create_tween()
	fade.tween_property(self, "modulate:a", 0.0, vanish_duration)


func _finish_vanish() -> void:
	visible = false
	scale = _base_scale
	modulate.a = 1.0


# 被外面强行隐藏时调一下：别把半透明 / 缩小状态留到下次显示
func reset_anim() -> void:
	_kill_tween()
	_kill_fade()
	scale = _base_scale
	modulate.a = 1.0


func _kill_tween() -> void:
	if tween != null and tween.is_valid():
		tween.kill()
	tween = null


func _kill_fade() -> void:
	if fade != null and fade.is_valid():
		fade.kill()
	fade = null
