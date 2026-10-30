extends RefCounted

# ─────────────────────────────────────────────────────────────────────────────
# 通用「手牌展示」：原地翻面（和 c40s1 透视 / 感知 / 思路 / 同盟 同一套观感）
#
#   reveal(seat, tiles)   把这家的手牌「原地」翻成正面（只换贴图 + 摆正朝向，
#                         位置 / 尺寸 / 间距一律不动 → 不另画一层，不会挤）
#   restore_reveal()      收掉，恢复牌背
#
# ★ 2026-10-30 用户口径：四喜的东/北也走这条链，别再自己叠一层精灵。
#
# 用法（main.gd）：
#   var hand_show := HandShow.new()
#   hand_show.setup(self)
#   hand_show.reveal(seat, tiles) / restore_reveal()
# ─────────────────────────────────────────────────────────────────────────────

const HAND_COUNT := 13                # 每家 13 张手牌槽位（节点名 B01..B13）

var host: Node = null                 # Main：需要 who_of_seat / opp_hands / opp_hand_rot
var tapai: Node2D = null              # 三家手牌容器（UI/Tapai）

var _tex := {}                        # Sprite2D -> 原贴图
var _rot := {}                        # Sprite2D -> 原旋转
var _flip := {}                       # Sprite2D -> [flip_h, flip_v]


func setup(p_host: Node, p_tapai: Node2D = null) -> void:
	host = p_host
	tapai = p_tapai


func clear() -> void:
	restore_reveal()


# ── 内部 ──────────────────────────────────────────────────────────────
func _bank() -> Node2D:
	if tapai == null and host != null:
		tapai = host.get("tapai") as Node2D
	return tapai


func _who(seat: int) -> String:
	if host == null:
		return ""
	var w := String(host.call("who_of_seat", int(seat)))
	if w == "" or w == "me":
		return ""
	return w


func _sprite_of(node: Node) -> Sprite2D:
	if node == null:
		return null
	if node is Sprite2D:
		return node as Sprite2D
	for c in node.get_children():
		if c is Sprite2D:
			return c as Sprite2D
	return null


# 第 j 张（0 起）的 Sprite2D。count = 这一手有几张：
# 手牌节点只有「序号最大的后 count 张」是亮着的，所以起点 = 13 - count。
func _sprite_at(seat: int, j: int, count: int) -> Sprite2D:
	var bank := _bank()
	var who := _who(seat)
	if bank == null or who == "":
		return null
	var start: int = HAND_COUNT - clampi(count, 1, HAND_COUNT)
	var idx: int = clampi(start + int(j), 0, HAND_COUNT - 1)
	return _sprite_of(bank.get_node_or_null("%s%02d" % [who, idx + 1]))


func _face_tex(kind: String) -> Texture2D:
	if kind == "":
		return null
	var path := TileBank.VERT_DIR + TileBank.face_file(kind) + ".png"
	if not ResourceLoader.exists(path):
		return null
	return load(path) as Texture2D


# ── 原地翻面 ──────────────────────────────────────────────────────────
func reveal(seat: int, tiles: Array) -> void:
	if (tiles as Array).is_empty():
		return
	var who := _who(seat)
	if who == "":
		return
	var rot := 180.0
	if host != null and host.has_method("opp_hand_rot"):
		rot = float(host.call("opp_hand_rot", who))      # B=90 / C=180 / D=270
	var n: int = mini((tiles as Array).size(), HAND_COUNT)
	for j in range(n):
		var spr := _sprite_at(seat, j, n)
		if spr == null:
			continue
		var tex := _face_tex(String((tiles as Array)[j]))
		if tex == null:
			continue
		if not _tex.has(spr):
			_tex[spr] = spr.texture
			_rot[spr] = spr.rotation_degrees
			_flip[spr] = [spr.flip_h, spr.flip_v]
		spr.texture = tex
		# 用「全局」旋转：B/D 有的张本身就是 Sprite2D、有的套了一层 Node2D（自带 180°）
		spr.global_rotation_degrees = rot
		spr.flip_h = false                    # 牌面绝不翻转（翻成镜像就看不懂了）
		spr.flip_v = false


func restore_reveal() -> void:
	for sp in _tex.keys():
		if sp != null and is_instance_valid(sp):
			sp.texture = _tex[sp]
			if _rot.has(sp):
				sp.rotation_degrees = float(_rot[sp])
			if _flip.has(sp):
				sp.flip_h = bool(_flip[sp][0])
				sp.flip_v = bool(_flip[sp][1])
	_tex.clear()
	_rot.clear()
	_flip.clear()
