extends TextureButton

# 选卡按钮：悬停 = 蓝色细框；选中 = 彩虹描边（勾一圈后常亮，统一走 SelFrame）
signal card_clicked(card_no: int)

const SelFrame := preload("res://sel_frame.gd")

var card_no := 0
var hovered := false
var selected := false
var _border: ReferenceRect
var _sel_frame: Node2D = null

func _ready() -> void:
	_border = get_node_or_null("Border") as ReferenceRect
	if _border == null:
		_border = ReferenceRect.new()
		_border.name = "Border"
		add_child(_border)
	_border.editor_only = false
	_border.mouse_filter = Control.MOUSE_FILTER_IGNORE
	# 选中框：与牌桌上那套彩虹描边完全一致（按钮自己带 scale，线宽在下面按 scale 折算）
	_sel_frame = SelFrame.attach(self, size, SelFrame.TEX_YELLOW, Color(1, 1, 1, 1), false, 6)
	mouse_entered.connect(_on_enter)
	mouse_exited.connect(_on_exit)
	pressed.connect(_on_pressed)
	_update_border()

func _on_enter() -> void:
	hovered = true
	_update_border()

func _on_exit() -> void:
	hovered = false
	_update_border()

func _on_pressed() -> void:
	card_clicked.emit(card_no)

func set_selected(v: bool) -> void:
	selected = v
	_update_border()

func _update_border() -> void:
	# 选卡时按钮被缩小到 0.2~0.3 倍，线宽/圆角要反着折算，否则屏幕上粗细不固定
	var k := maxf(scale.x, 0.01)
	if _sel_frame != null and is_instance_valid(_sel_frame):
		_sel_frame.set("line_width", 5.5 / k)
		_sel_frame.set("corner_radius", 10.0 / k)
		if _sel_frame.has_method("refresh"):
			_sel_frame.call("refresh")
		_sel_frame.visible = selected
	if _border == null:
		return
	_border.position = Vector2(-4, -4) / k
	_border.size = size + Vector2(8, 8) / k
	if selected:
		_border.visible = false                  # 选中交给彩虹框，避免黄蓝叠在一起
	elif hovered:
		_border.border_color = Color(0.25, 0.62, 1.0, 1.0)   # 悬停：蓝
		_border.border_width = 3.0 / k
		_border.visible = true
	else:
		_border.visible = false
