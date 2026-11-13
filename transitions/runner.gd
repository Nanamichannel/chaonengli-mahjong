extends Node
##
## runner.gd —— 挂在 root 下的转场执行体
##
## 关键：它自己不是「当前场景」，所以 change_scene 不会把它一起释放，
## 协程能跑完，遮罩层也能正确清理。
##

signal finished

const DURATION := 1.25

var mask_frames: Array[Texture2D] = []
var clip_frames: Array[Texture2D] = []
var target_scene := ""


func play(shot_texture: ImageTexture, target: String) -> void:
	target_scene = target
	var layer := CanvasLayer.new()
	layer.layer = 128
	add_child(layer)

	var snap := TextureRect.new()
	snap.texture = shot_texture
	snap.set_anchors_preset(Control.PRESET_FULL_RECT)
	snap.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var mat := ShaderMaterial.new()
	mat.shader = load("res://transitions/wipe.gdshader")
	snap.material = mat
	layer.add_child(snap)

	var clip := TextureRect.new()
	clip.set_anchors_preset(Control.PRESET_FULL_RECT)
	clip.mouse_filter = Control.MOUSE_FILTER_IGNORE
	clip.modulate.a = 0.0
	layer.add_child(clip)

	get_tree().change_scene_to_file(target)
	await get_tree().process_frame
	await get_tree().process_frame

	var n := mask_frames.size()
	var c := clip_frames.size()
	var t := 0.0
	while t < DURATION:
		t += get_process_delta_time()
		var p := clampf(t / DURATION, 0.0, 1.0)
		if n > 0:
			mat.set_shader_parameter("mask_tex", mask_frames[mini(int(p * (n - 1)), n - 1)])
		if c > 0:
			clip.texture = clip_frames[mini(int(p * (c - 1)), c - 1)]
			clip.modulate.a = clampf(minf(p / 0.15, (0.72 - p) / 0.12), 0.0, 1.0)
		await get_tree().process_frame

	layer.queue_free()
	finished.emit()
	queue_free()
