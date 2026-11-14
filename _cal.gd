extends SceneTree

func _initialize() -> void:
	var b = load("res://addons/ae_motion/ae_builder.gd").new()
	var res: Dictionary = b.build(
		"N:/媒体/AfterEffects/AE-Motion-Export/合成 2.json",
		"res://Cailiao/UI/搜索框",
		"res://generated/_cal.tscn",
		""
	)
	for line in res.get("lines", []):
		print(line)
	var ps = load("res://generated/_cal.tscn")
	var inst: Node = ps.instantiate()
	root.add_child(inst)
	var cam: Camera3D = inst.get_node_or_null("Camera3D") as Camera3D
	if cam:
		print("cam pos=", cam.position, " fov=", snappedf(cam.fov, 0.1), " aspect=", cam.get_viewport().get_visible_rect().size)
	for n in inst.find_children("*", "Sprite3D", true, false):
		var s := n as Sprite3D
		var w := 0.0
		var h := 0.0
		if s.texture:
			w = s.texture.get_width()
			h = s.texture.get_height()
		print(s.name, " pos=", s.position, " offset=", s.offset, " tex=", w, "x", h, " pixel_size=", s.pixel_size)
	quit(0)
