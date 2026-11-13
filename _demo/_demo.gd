extends Node
## 单独验证我的转场：不进游戏流程，直接跑一次并截三张图

var _t := 0.0
var _phase := 0
var _ap: Node


func _ready() -> void:
	var scene: PackedScene = load("res://真初始场景.tscn")
	_ap = scene.instantiate()
	get_tree().root.add_child(_ap)
	get_tree().current_scene = _ap
	print("[demo] 已载入真初始场景")


func _process(delta: float) -> void:
	_t += delta
	if _phase == 0 and _t > 1.5:
		get_viewport().get_texture().get_image().save_png("res://_demo_0.png")
		print("[demo] 截图 0（转场前）")
		SceneTransition.start()
		_phase = 1
	elif _phase == 1 and _t > 2.0:
		get_viewport().get_texture().get_image().save_png("res://_demo_1.png")
		print("[demo] 截图 1（转场中）")
		_phase = 2
	elif _phase == 2 and _t > 2.8:
		get_viewport().get_texture().get_image().save_png("res://_demo_2.png")
		print("[demo] 截图 2（转场后）")
		_phase = 3
	elif _phase == 3 and _t > 3.2:
		get_tree().quit()
