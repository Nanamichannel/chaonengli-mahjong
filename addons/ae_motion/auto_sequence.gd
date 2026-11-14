extends Node
##
## auto_sequence.gd —— 按顺序播放 AnimationPlayer 里的多段动画。
## 由导入器自动挂上，不需要手写代码。
##
## 行为：
##   - 除最后一段外，播完自动接下一段（等 animation_finished，推迟一帧再 play）
##   - 最后一段如果带 *（循环），就一直循环
##   - 最后一段如果不带 *，播完停在最后一帧，不回开头
##

@export var player_path: NodePath
@export var sequence: PackedStringArray = PackedStringArray()
## 最后一段播完后是否停在末帧（true）还是回到开头（false）
@export var hold_last_frame := true
## 进入场景就自动播第一段（生成独立场景时为 true；合并进别的场景时导入器会关掉）
@export var autoplay := true

var _ap: AnimationPlayer


func _ready() -> void:
	_ap = get_node_or_null(player_path) as AnimationPlayer
	if _ap == null:
		_ap = get_parent().get_node_or_null("AnimationPlayer") as AnimationPlayer
	if _ap == null or sequence.is_empty():
		return

	_ap.animation_finished.connect(_on_finished)
	if autoplay:
		start()


## 由外部调用开始播放（autoplay 关掉时用）
func start() -> void:
	if _ap != null and not sequence.is_empty():
		_ap.play(sequence[0])


func _on_finished(anim_name: String) -> void:
	var i := sequence.find(anim_name)
	if i < 0:
		return

	# 最后一段：停住，不要回开头
	if i + 1 >= sequence.size():
		if hold_last_frame and is_instance_valid(_ap):
			var last := _ap.get_animation(anim_name)
			if last != null:
				_ap.seek(last.length, true)
			_ap.pause()
		return

	await get_tree().process_frame
	if is_instance_valid(_ap):
		_ap.play(sequence[i + 1])
