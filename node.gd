extends Node

var ap: AnimationPlayer
var _t := 0.0

func _ready() -> void:
	await get_tree().process_frame
	for n in get_tree().root.find_children("*", "Sprite2D", true, false):
		if String(n.name).find("登入") >= 0:
			print("[诊断] ", n.name,
				"  贴图=", n.texture.get_size() if n.texture else "无",
				"  缩放=", n.scale,
				"  offset=", n.offset,
				"  全局=", n.global_position)

func _process(delta: float) -> void:
	if ap == null:
		return
	_t += delta
	if _t < 0.5:
		return
	_t = 0.0
	print("[诊断] current=[", ap.current_animation,
	"]  assigned=[", ap.assigned_animation,
	"]  t=", snappedf(ap.current_animation_position, 0.01),
	"  playing=", ap.is_playing(),
	"  动画=", ap.get_animation_list())
	
