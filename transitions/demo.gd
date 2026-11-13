extends Control
##
## demo.gd —— 独立演示：真初始场景 → 鉴赏
##
## 转场逻辑放在 root 下的 runner 节点里，因为 change_scene 会释放当前场景，
## 写在本场景里协程会被中断、遮罩层永远留在最上层（表现就是「点一下卡住」）。
##

const SRC_SCENE := "res://真初始场景.tscn"
const DST_SCENE := "res://鉴赏.tscn"

var _mask_tex: Array[Texture2D] = []
var _clip_tex: Array[Texture2D] = []
var _busy := false


func _ready() -> void:
	_load_tex()
	var ps := load(SRC_SCENE) as PackedScene
	if ps:
		add_child(ps.instantiate())
	print("[demo] 素材 蒙版=%d 片段=%d" % [_mask_tex.size(), _clip_tex.size()])
	if "--auto" in OS.get_cmdline_args():
		await get_tree().create_timer(0.6).timeout
		_play()


func _load_tex() -> void:
	var arr_m: Array[Texture2D] = []
	var arr_c: Array[Texture2D] = []
	for i in range(30):
		var m := load("res://transitions/masks/mask_%03d.png" % i)
		if m is Texture2D:
			arr_m.append(m)
		var c := load("res://transitions/clip/clip_%03d.png" % i)
		if c is Texture2D:
			arr_c.append(c)
	_mask_tex = arr_m
	_clip_tex = arr_c


func _input(event: InputEvent) -> void:
	if _busy:
		return
	if event is InputEventMouseButton and event.pressed:
		_play()
	elif event is InputEventKey and event.pressed and not event.echo:
		_play()


func _play() -> void:
	if _busy:
		return
	_busy = true
	var shot := ImageTexture.create_from_image(get_viewport().get_texture().get_image())

	var runner := Node.new()
	runner.name = "TransitionRunner"
	runner.set_script(load("res://transitions/runner.gd"))
	get_tree().root.add_child(runner)
	runner.mask_frames = _mask_tex
	runner.clip_frames = _clip_tex
	runner.finished.connect(func(): print("[demo] 转场完成"), CONNECT_ONE_SHOT)
	runner.play(shot, DST_SCENE)
