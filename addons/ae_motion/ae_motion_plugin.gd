@tool
extends EditorPlugin
##
## 把 AE Motion 面板加到编辑器右侧。
##

const Dock := preload("res://addons/ae_motion/ae_motion_dock.gd")

var _dock: Control


func _enter_tree() -> void:
	_dock = Dock.new()
	_dock.name = "AE Motion"
	add_control_to_dock(DOCK_SLOT_RIGHT_UL, _dock)


func _exit_tree() -> void:
	if is_instance_valid(_dock):
		remove_control_from_docks(_dock)
		_dock.queue_free()
		_dock = null
