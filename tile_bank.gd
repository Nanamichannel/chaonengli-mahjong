class_name TileBank
extends Node2D

# 某张手牌被点击（参数 = 它在手牌里的显示序号）
signal hand_clicked(slot_index: int)
# 牌河里的牌被点（换牌技能）
signal river_clicked(discard_seq: int)

const ROOT_DIR := "res://Cailiao/mahjong_graphic/PNG 位图/"
const BASE_DIR := ROOT_DIR + "默认风格 default style/"
const VERT_DIR := BASE_DIR + "竖 vertical/"
const HORZ_DIR := BASE_DIR + "横 horizontal/"
const FLAT_DIR := ROOT_DIR + "扁平风格 flat style/"   # 牌河用的竖版扁平图 f*.png
const BACK_DIR := BASE_DIR + "背面 back/"
const BACK_KEY := "b_02"      # 竖向牌背（手牌暗置 / 暗杠两侧）
const BACK_H_KEY := "b_01"    # 横向牌背（暗置 + 横置：立直宣言牌 / 伏兵）

const TILE_KINDS: Array[String] = [
	"1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
	"1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p",
	"1s", "2s", "3s", "4s", "5s", "6s", "7s", "8s", "9s",
	"dong", "nan", "xi", "bei", "bai", "fa", "zhong",
]
const RED_FIVES := {"0m": "5m", "0p": "5p", "0s": "5s"}
const HONOR_Z := {"dong": "1z", "nan": "2z", "xi": "3z", "bei": "4z",
	"bai": "5z", "fa": "6z", "zhong": "7z"}

var _pieces := {}
var _order: Array[String] = []

# 与服务端 tiles.build_entities 完全一致：每种 4 张，赤 5 的第 4 张变成 0x01
static func entity_ids() -> Array[String]:
	var out: Array[String] = []
	for t in TILE_KINDS:
		if RED_FIVES.values().has(t):
			out.append("%s01" % t)
			out.append("%s02" % t)
			out.append("%s03" % t)
			for red in RED_FIVES:
				if RED_FIVES[red] == t:
					out.append("%s01" % red)
		else:
			for i in range(1, 5):
				out.append("%s%02d" % [t, i])
	return out

static func kind_of_entity(entity_id: String) -> String:
	if entity_id.length() >= 3 and entity_id.substr(0, 2) in [
			"1m", "2m", "3m", "4m", "5m", "6m", "7m", "8m", "9m",
			"1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p",
			"1s", "2s", "3s", "4s", "5s", "6s", "7s", "8s", "9s",
			"0m", "0p", "0s"]:
		return entity_id.substr(0, 2)
	for h in HONOR_Z:
		if entity_id.begins_with(h):
			return h
	return entity_id

static func face_file(kind: String) -> String:
	return HONOR_Z.get(kind, kind)

# 扁平风格竖版文件名：1m -> f1m、dong -> f1z、0m -> f0mn
static func flat_file(kind: String) -> String:
	if kind.begins_with("0"):
		return "f0" + kind.substr(1) + "n"
	return "f" + HONOR_Z.get(kind, kind)

func _load_tex(path: String) -> Texture2D:
	var t := load(path)
	return t as Texture2D

# base_size = 一张竖牌的目标显示尺寸（main.gd 的 tile_size）
func build(base_size: Vector2) -> void:
	_order = entity_ids()
	var back_tex := _load_tex(BACK_DIR + BACK_KEY + ".png")
	var back_h_tex := _load_tex(BACK_DIR + BACK_H_KEY + ".png")
	for eid in _order:
		var k := kind_of_entity(eid)
		var ff := face_file(k)
		var vtex := _load_tex(VERT_DIR + ff + ".png")
		var htex := _load_tex(HORZ_DIR + "h" + ff + ".png")
		var ftex := _load_tex(FLAT_DIR + flat_file(k) + ".png")
		var texes := {
			"face": vtex,
			"face_meld": vtex,
			"back": back_tex,
			"back_meld": back_tex,
			"river": ftex,
			"rot": htex,
			"back_rot": back_h_tex,
			"dora": vtex,
		}
		var piece: TilePiece
		if _pieces.has(eid) and is_instance_valid(_pieces[eid]):
			piece = _pieces[eid]
		else:
			piece = TilePiece.new()
			add_child(piece)
			_pieces[eid] = piece
			piece.clicked.connect(func(idx: int): hand_clicked.emit(idx))
			piece.river_clicked.connect(func(seq: int): river_clicked.emit(seq))
		piece.setup(eid, k, texes, base_size)
		piece.visible = false

func piece(entity_id: String) -> TilePiece:
	return _pieces.get(entity_id) as TilePiece

func all_pieces() -> Array:
	return _pieces.values()

var frame_id := 0

# 开始一帧：不预先隐藏任何牌。本帧内被 apply_state 摆放过的牌会得到新 stamp。
func begin_frame() -> void:
	frame_id += 1

# 结束一帧：只有「这一帧完全没有再出现」的牌才隐藏。
# 正被悬停的手牌每帧都会被重新摆放，因此不会被隐藏 → 不会触发 mouse_exited → 不会自己落下。
func end_frame() -> void:
	for eid in _pieces:
		var p: TilePiece = _pieces[eid]
		if is_instance_valid(p) and p.stamp != frame_id:
			p.hide_piece()

func reset() -> void:
	for eid in _pieces:
		var p: TilePiece = _pieces[eid]
		if is_instance_valid(p):
			p.hide_piece()
