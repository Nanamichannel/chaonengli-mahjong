extends SceneTree

var _t := 0.0

func _initialize() -> void:
	var b = load("res://addons/ae_motion/ae_builder.gd").new()
	var res: Dictionary = b.build(
		"N:/媒体/AfterEffects/AE-Motion-Export/搜索框.json",
		"res://Cailiao/UI/搜索框",
		"res://generated/_3d2.tscn",
		"",
		"play:0-30"
	)
	for line in res.get("lines", []):
		print(line)

	var ps = load("res://generated/_3d2.tscn")
	var inst: Node = ps.instantiate()
	root.add_child(inst)
	var cam: Camera3D = inst.get_node_or_null("Camera3D") as Camera3D
	if cam:
		print("相机 pos=", cam.position, " fov=", snappedf(cam.fov, 0.1), " current=", cam.current)
	var with_tex := 0
	var without := 0
	for n in inst.find_children("*", "Sprite3D", true, false):
		if (n as Sprite3D).texture != null:
			with_tex += 1
			if with_tex <= 3:
				print("  ", n.name, " pos=", (n as Sprite3D).position)
		else:
			without += 1
	print("有贴图=", with_tex, " 无贴图=", without)

func _process(delta: float) -> bool:
	_t += delta
	if _t > 1.0:
		var img := root.get_texture().get_image()
		img.save_png("user://_3d2.png")
		print("saved")
		return true
	return false
