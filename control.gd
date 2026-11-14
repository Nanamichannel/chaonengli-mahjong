extends Node2D

var ap: AnimationPlayer
var _t := 0.0

func _ready() -> void:
	ap = get_node_or_null("AnimationPlayer")
	if ap == null:
		ap = find_child("AnimationPlayer", true, false)
	if ap == null:
		print("[检查] 没找到 AnimationPlayer")
		return

	print("[检查] 动画列表：", ap.get_animation_list())
	for nm in ap.get_animation_list():
		var a: Animation = ap.get_animation(nm)
		print("  ", nm, "  长度=", a.length, "  loop=", a.loop_mode, "  轨道=", a.get_track_count())

	ap.animation_finished.connect(_on_finished)
	ap.play("intro")
	print("[检查] 开始播 intro")

func _on_finished(nm: String) -> void:
	print("[检查] 播完了：", nm)
	if nm == "intro":
		ap.call_deferred("play", "idle")

func _process(delta: float) -> void:
	if ap == null:
		return
	_t += delta
	if _t < 0.5:
		return
	_t = 0.0
	var p := "?"
	var n := get_node_or_null("人物 null/人物3")
	if n != null and n is Node2D:
		p = str((n as Node2D).position)
	print("[检查] 当前=", ap.current_animation, "  在播=", ap.is_playing(),
		"  时间=", snappedf(ap.current_animation_position, 0.01), "  人物3位置=", p)
