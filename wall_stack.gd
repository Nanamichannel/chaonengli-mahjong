# -*- coding: utf-8 -*-
# wall_stack.gd —— 牌墩节点状态机
# 每个「牌墩/墩NN」节点挂本脚本。Main 只调用节点方法：
#   setup(side, width)  认领/重置：两张态、清掉宝牌覆盖
#   set_count(2|1|0)    两张态 / 一张态 / 空
#   show_dora(tile_id)  翻宝牌态：把正面指示牌盖在自己的两张态图片上
#   clear_dora()        取消翻宝牌
extends Node2D

const WALL_VERT_SIDES: Array[String] = ["top", "bottom"]
const DORA_FLIP_FOLDERS := true
const BACK_DIR := "res://Cailiao/mahjong_graphic/PNG 位图/默认风格 default style/背面 back/"
const DORA_DIR_HF := "res://Cailiao/mahjong_graphic/PNG 位图/默认风格 default style/横 翻转/"
const DORA_DIR_VF := "res://Cailiao/mahjong_graphic/PNG 位图/默认风格 default style/竖 翻转/"
# 每个方向：dir + 旋转角度 + 是否上下翻转（和 main.gd DORA_VIEW 一致）
const DORA_VIEW := {
	"left": {"dir": "h", "rot": 180.0, "flip_v": false},
	"right": {"dir": "hf", "rot": 0.0, "flip_v": true},
	"bottom": {"dir": "vf", "rot": 0.0, "flip_v": true},
	"top": {"dir": "vf", "rot": 180.0, "flip_v": true},
}

var side := "bottom"        # 这一墩在哪个方向（主视角：left/right/top/bottom）
var width := 42.0           # 显示宽度（竖墩 = wall_row_width，横墩 = wall_col_width）
var count := 2              # 剩余张数：2 / 1 / 0
var dora_tile := ""         # 翻出的宝牌指示牌（"" = 没翻）

var _art: Node = null
var _dora_cover: Node2D = null


# ── 资源读取（优先 Art 节点，找不到才按路径读，永不白板）──
func _art_node() -> Node:
	if _art == null or not is_instance_valid(_art):
		_art = get_node_or_null("../../Main/Art")
	return _art


func _load_tex(path: String) -> Texture2D:
	if ResourceLoader.exists(path):
		return load(path) as Texture2D
	return null


func _back_tex(key: String) -> Texture2D:
	var a := _art_node()
	if a != null and a.has_method("back_tex"):
		var t := a.call("back_tex", key) as Texture2D
		if t != null:
			return t
	return _load_tex(BACK_DIR + key + ".png")


func _art_dora_tex(view: String, key: String) -> Texture2D:
	var a := _art_node()
	if a != null and a.has_method("dora_tex"):
		var t := a.call("dora_tex", view, key) as Texture2D
		if t != null:
			return t
	return _load_tex((DORA_DIR_VF if view == "vf" else DORA_DIR_HF) + key + ".png")


func _hpai_node_name(tile_id: String) -> String:
	var honors := ["dong", "nan", "xi", "bei", "bai", "fa", "zhong"]
	var h := honors.find(tile_id)
	if h >= 0:
		return "h%dz" % (h + 1)
	return "h" + tile_id


func _dora_file_base(tile_id: String) -> String:
	var h := _hpai_node_name(tile_id)
	return h.substr(1) if h.begins_with("h") else tile_id


func _pai_tex(tile_id: String) -> Texture2D:
	var pai := get_node_or_null("../../Main/Pai")
	if pai == null or tile_id == "":
		return null
	var n := pai.get_node_or_null(tile_id) as Node2D
	if n == null:
		return null
	var spr := n.get_node_or_null("Sprite2D") as Sprite2D
	return spr.texture if spr != null else null


func _h_tex(tile_id: String) -> Texture2D:
	var fpai := get_node_or_null("../../Main/fPai")
	if fpai == null or tile_id == "":
		return null
	var n := fpai.get_node_or_null(_hpai_node_name(tile_id)) as Node2D
	if n == null:
		return null
	var spr := n.get_node_or_null("Sprite2D") as Sprite2D
	return spr.texture if spr != null else null


func _resolve_dora_tex(view: String, tile_id: String) -> Texture2D:
	if view == "h":
		return _h_tex(tile_id)
	var nm := _dora_file_base(tile_id)
	if view == "hf":
		var t := _art_dora_tex("hf", "h" + nm)
		return t if t != null else _h_tex(tile_id)
	var t2 := _art_dora_tex("vf", nm)
	return t2 if t2 != null else _pai_tex(tile_id)


# ── 对外接口（Main 只调这些）──
func setup(side_name: String, w: float) -> void:
	side = side_name
	width = maxf(w, 1.0)
	count = 2
	_hide_dora()
	_apply_face()
	visible = true


func set_count(c: int) -> void:
	count = clampi(c, 0, 2)
	_apply_face()


func show_dora(tile_id: String) -> void:
	dora_tile = tile_id
	if tile_id == "":
		_hide_dora()
		return
	var spec: Dictionary = DORA_VIEW.get(side, {"dir": "h", "rot": 180.0, "flip_v": false})
	var view := String(spec.get("dir", "h"))
	var dora_flip: bool = bool(spec.get("flip_v", false)) and DORA_FLIP_FOLDERS
	var rot: float = float(spec.get("rot", 180.0))
	var tex := _resolve_dora_tex(view, tile_id)
	if tex == null:
		_hide_dora()
		return
	var base := get_node_or_null("Sprite2D") as Sprite2D
	var box := base.texture.get_size() * base.scale if base != null and base.texture != null else Vector2.ZERO
	if box.x <= 0.0:
		_hide_dora()
		return
	var cover := _ensure_dora_cover()
	var spr := cover.get_node_or_null("Sprite2D") as Sprite2D
	if spr == null:
		spr = Sprite2D.new()
		spr.name = "Sprite2D"
		spr.centered = true
		cover.add_child(spr)
	spr.texture = tex
	var tex_size := spr.texture.get_size()
	var swaps: bool = is_equal_approx(rot, 90.0) or is_equal_approx(rot, 270.0)
	var base_w: float = tex_size.y if swaps else tex_size.x
	var s: float = box.x / maxf(base_w, 1.0)
	var h_new: float = (tex_size.x if swaps else tex_size.y) * s
	spr.scale = Vector2.ONE * s
	spr.flip_v = dora_flip
	cover.rotation_degrees = rot
	cover.position = Vector2(0.0, (h_new - box.y) * 0.5)
	cover.z_index = 5
	cover.visible = true
	visible = true


func clear_dora() -> void:
	_hide_dora()


# ── 内部 ──
func _apply_face() -> void:
	var sp := get_node_or_null("Sprite2D") as Sprite2D
	if sp == null:
		return
	var vert: bool = WALL_VERT_SIDES.has(side)
	var key := ("b_05" if vert else "b_04") if count >= 2 else ("b_02" if vert else "b_01")
	var tex := _back_tex(key)
	if tex == null:
		sp.visible = false
		visible = false
		return
	var w := width
	var two_h := 0.0
	if count < 2:
		var two := _back_tex("b_05" if vert else "b_04")
		if two != null:
			two_h = two.get_size().y * (w / maxf(two.get_size().x, 1.0))
	sp.texture = tex
	sp.centered = true
	sp.scale = Vector2.ONE * (w / maxf(tex.get_size().x, 1.0))
	sp.rotation_degrees = 180.0 if count < 2 else 0.0
	var h: float = tex.get_size().y * sp.scale.y
	sp.position = Vector2(0.0, (two_h - h) * 0.5) if count < 2 else Vector2.ZERO
	sp.visible = count > 0
	visible = count > 0


func _ensure_dora_cover() -> Node2D:
	if _dora_cover == null or not is_instance_valid(_dora_cover):
		_dora_cover = Node2D.new()
		_dora_cover.name = "DoraCover"
		add_child(_dora_cover)
	return _dora_cover


func _hide_dora() -> void:
	dora_tile = ""
	if _dora_cover != null and is_instance_valid(_dora_cover):
		_dora_cover.visible = false
