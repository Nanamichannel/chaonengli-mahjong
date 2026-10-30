# -*- coding: utf-8 -*-
# 役种判定测试台（独立场景，和 node_2d.tscn 互不影响）
# 用法：在 Godot 里打开 scenes/yaku_test.tscn，按 F6（运行当前场景）
#
# 画面全部用代码搭出来，所以这个场景只有「一个 Control + 这个脚本」。
# 判定调用 server/judge_cli.py（Python 规则引擎），拿 JSON 回来显示。

extends Control

const CLI := "res://server/judge_cli.py"

# 几个现成例子，点一下就能填进去
const EXAMPLES := [
	{"title": "平和+一气", "hand": "123m456m789m34p55s", "win": "2p", "melds": "", "dora": "",
	 "flags": {}},
	{"title": "七对子", "hand": "11223344556677m", "win": "7m", "melds": "", "dora": "",
	 "flags": {}},
	{"title": "立直自摸+宝牌", "hand": "123m456m789m123p1s", "win": "1s", "melds": "",
	 "dora": "1s", "flags": {"自摸": true, "立直": true}},
	{"title": "国士无双", "hand": "119m19p19s1234567z", "win": "1m", "melds": "",
	 "dora": "", "flags": {"自摸": true, "亲家": true}},
	{"title": "碰了之后(副露)", "hand": "234m567m234p22s", "win": "2s", "melds": "pon:111z",
	 "dora": "", "flags": {}},
	{"title": "暗杠+岭上", "hand": "234m567m234p22s", "win": "2s", "melds": "ankan:1111m",
	 "dora": "1s", "flags": {"自摸": true, "岭上": true}},
	{"title": "抢杠", "hand": "234m567m234p567s22s", "win": "2s", "melds": "",
	 "dora": "", "flags": {"抢杠": true}},
	{"title": "大三元", "hand": "555z666z777z111m11p", "win": "1p", "melds": "", "dora": "",
	 "flags": {}},
]

const WINDS := ["dong", "nan", "xi", "bei"]
const WIND_CN := ["东", "南", "西", "北"]
const FLAG_KEYS := ["自摸", "亲家", "立直", "双立直", "一发", "岭上", "抢杠", "海底"]

var f_hand: LineEdit
var f_win: LineEdit
var f_melds: LineEdit
var f_dora: LineEdit
var f_ura: LineEdit
var opt_seat: OptionButton
var opt_round: OptionButton
var chk := {}
var out: RichTextLabel
var tip: Label


func _ready() -> void:
	_fit_window()
	get_viewport().size_changed.connect(_fit_window)
	_build_ui()
	_fill(EXAMPLES[0])
	_judge()


# 场景根节点不会自动跟窗口一样大，得自己设一下（不然结果区高度是 0）
func _fit_window() -> void:
	position = Vector2.ZERO
	size = get_viewport_rect().size


# ────────────────────────── 搭界面 ──────────────────────────
func _build_ui() -> void:
	var bg := ColorRect.new()
	bg.color = Color(0.11, 0.12, 0.14)
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(bg)

	var margin := MarginContainer.new()
	margin.set_anchors_preset(Control.PRESET_FULL_RECT)
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 24)
	add_child(margin)

	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 10)
	margin.add_child(root)

	var title := Label.new()
	title.text = "役种判定测试台　（输入牌型 → 算番 / 符 / 点）"
	title.add_theme_font_size_override("font_size", 26)
	root.add_child(title)

	var hint := Label.new()
	hint.text = ("写法：万m 筒p 索s，赤 5 写 0m/0p/0s，字牌 1z~7z = 东南西北白发中；"
		+ "和牌张也可以写 中 / dong。副露写 chi:234p、pon:555z、minkan:1111m、ankan:1111m、kakan:1111m")
	hint.add_theme_font_size_override("font_size", 13)
	hint.modulate = Color(0.72, 0.76, 0.8)
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	root.add_child(hint)

	f_hand = _row(root, "手　牌", "123m456m789m234p55s")
	f_win = _row(root, "和牌张", "2p  （也可以只写这张，手牌留 13 张）")
	f_melds = _row(root, "副　露", "（可空）如 pon:111z 或 chi:234p,pon:555z")
	f_dora = _row(root, "宝牌牌", "（可空）宝牌指示牌，如 1s；多张连着写 1s5p")
	f_ura = _row(root, "里宝牌", "（可空）里宝牌指示牌（立直时才算）")

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 18)
	root.add_child(row)

	opt_seat = _option(row, "自风", WIND_CN, 1)
	opt_round = _option(row, "场风", WIND_CN, 0)

	var sep := VSeparator.new()
	row.add_child(sep)

	for key in FLAG_KEYS:
		var c := CheckBox.new()
		c.text = key
		c.add_theme_font_size_override("font_size", 16)
		chk[key] = c
		row.add_child(c)

	var btns := HBoxContainer.new()
	btns.add_theme_constant_override("separation", 12)
	root.add_child(btns)

	var go := Button.new()
	go.text = "　判　定　"
	go.add_theme_font_size_override("font_size", 20)
	go.pressed.connect(_judge)
	btns.add_child(go)

	var ex_label := Label.new()
	ex_label.text = "例子："
	btns.add_child(ex_label)
	for e in EXAMPLES:
		var b := Button.new()
		b.text = e["title"]
		b.pressed.connect(_fill.bind(e))
		btns.add_child(b)

	tip = Label.new()
	tip.text = ""
	tip.add_theme_font_size_override("font_size", 13)
	tip.modulate = Color(0.72, 0.76, 0.8)
	root.add_child(tip)

	out = RichTextLabel.new()
	out.bbcode_enabled = false
	out.scroll_active = true
	out.selection_enabled = true
	out.size_flags_vertical = Control.SIZE_EXPAND_FILL
	out.add_theme_font_size_override("normal_font_size", 18)
	root.add_child(out)


func _row(parent: Node, label_text: String, placeholder: String) -> LineEdit:
	var h := HBoxContainer.new()
	h.add_theme_constant_override("separation", 10)
	parent.add_child(h)
	var l := Label.new()
	l.text = label_text
	l.custom_minimum_size = Vector2(84, 0)
	l.add_theme_font_size_override("font_size", 17)
	h.add_child(l)
	var e := LineEdit.new()
	e.placeholder_text = placeholder
	e.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	e.add_theme_font_size_override("font_size", 17)
	h.add_child(e)
	return e


func _option(parent: Node, label_text: String, items: Array, default_idx: int) -> OptionButton:
	var l := Label.new()
	l.text = label_text
	l.add_theme_font_size_override("font_size", 17)
	parent.add_child(l)
	var o := OptionButton.new()
	for it in items:
		o.add_item(it)
	o.selected = default_idx
	o.add_theme_font_size_override("font_size", 17)
	parent.add_child(o)
	return o


# ────────────────────────── 填例子 / 判定 ──────────────────────────
func _fill(e: Dictionary) -> void:
	f_hand.text = e.get("hand", "")
	f_win.text = e.get("win", "")
	f_melds.text = e.get("melds", "")
	f_dora.text = e.get("dora", "")
	f_ura.text = ""
	var flags: Dictionary = e.get("flags", {})
	for key in chk:
		chk[key].button_pressed = bool(flags.get(key, false))
	if flags.get("亲家", false):
		opt_seat.selected = opt_round.selected


func _judge() -> void:
	var py := _find_python()
	if py == "":
		out.text = "找不到 python，没法调用规则引擎。\n（装个 Python 3 并加到 PATH，或者改脚本里的 _find_python）"
		return
	var args := PackedStringArray()
	args.append(ProjectSettings.globalize_path(CLI))
	args.append("--json")
	args.append("--hand")
	args.append(f_hand.text.strip_edges())
	if f_win.text.strip_edges() != "":
		args.append("--win")
		args.append(f_win.text.strip_edges())
	if f_melds.text.strip_edges() != "":
		args.append("--melds")
		args.append(f_melds.text.strip_edges())
	if f_dora.text.strip_edges() != "":
		args.append("--dora")
		args.append(f_dora.text.strip_edges())
	if f_ura.text.strip_edges() != "":
		args.append("--ura")
		args.append(f_ura.text.strip_edges())
	args.append("--seat-wind")
	args.append(WINDS[opt_seat.selected])
	args.append("--round-wind")
	args.append(WINDS[opt_round.selected])
	var map := {"自摸": "--tsumo", "亲家": "--dealer", "立直": "--riichi",
		"双立直": "--double-riichi", "一发": "--ippatsu", "岭上": "--rinshan",
		"抢杠": "--chankan", "海底": "--last-tile"}
	for key in chk:
		if chk[key].button_pressed:
			args.append(map[key])

	var lines := PackedStringArray()
	var tmp_path := "user://yaku_result.json"
	var tmp_abs := ProjectSettings.globalize_path(tmp_path)
	if FileAccess.file_exists(tmp_path):
		DirAccess.remove_absolute(tmp_abs)
	args.append("--out")
	args.append(tmp_abs)
	var code := OS.execute(py, args, lines, true)

	# Godot 在 Windows 上读不到子进程的 stdout，所以结果走文件
	var text := ""
	if FileAccess.file_exists(tmp_path):
		var f := FileAccess.open(tmp_path, FileAccess.READ)
		if f != null:
			text = f.get_as_text()
			f.close()
	if text.strip_edges() == "":
		text = "\n".join(lines)
	if text.strip_edges() == "":
		out.text = ("拿不到判定结果（退出码 %d）。\n请确认能手动跑：\n%s --hand %s"
			% [code, ProjectSettings.globalize_path(CLI), f_hand.text])
		tip.text = "调用规则引擎失败"
		return
	var data = JSON.parse_string(text)
	if typeof(data) != TYPE_DICTIONARY:
		out.text = "返回的不是 JSON，原始输出：\n" + text
		return
	_render(data)


func _find_python() -> String:
	for name in ["python", "python3", "py"]:
		var probe := PackedStringArray()
		if OS.execute(name, PackedStringArray(["--version"]), probe, true) == 0:
			return name
	return ""


func _render(r: Dictionary) -> void:
	var L := PackedStringArray()
	var mode := "自摸" if r.get("tsumo") else "荣和"
	var head := "手牌：%s　（%s %s）" % [r.get("hand", "?"), mode, r.get("win", "?")]
	if r.get("melds") and r["melds"].size() > 0:
		head += "　副露：" + "、".join(PackedStringArray(r["melds"]))
	L.append(head)
	L.append("")

	if not r.get("ok"):
		L.append("✗ 判定不了：" + str(r.get("error", "?")))
		if r.get("try_waits") and r["try_waits"].size() > 0:
			L.append("　提示：这副牌现在听 " + "、".join(PackedStringArray(r["try_waits"])))
		out.text = "\n".join(L)
		tip.text = "判定失败：看看牌写对没有（牌数一共要 14 张）"
		return

	var yakus := PackedStringArray()
	for y in r.get("yaku", []):
		yakus.append("%s %d番" % [y["name"], y["han"]])
	L.append("役种：" + "、".join(yakus))
	if int(r.get("yakuman", 0)) > 0:
		L.append("番数：役满 ×%d" % int(r["yakuman"]))
	else:
		L.append("番数：%d 番　　符数：%d 符" % [int(r.get("han", 0)), int(r.get("fu", 0))])
		var items := PackedStringArray()
		var total := 0
		for it in r.get("fu_items", []):
			items.append("%s %d" % [it[0], int(it[1])])
			total += int(it[1])
		if items.size() > 0:
			L.append("符数明细：" + " + ".join(items) + " → %d 符" % int(r.get("fu", 0)))

	var p: Dictionary = r.get("points", {})
	if r.get("tsumo"):
		if p.has("from_dealer") and p.has("from_other") and int(p["from_dealer"]) != int(p["from_other"]):
			L.append("点数：自摸　亲付 %d / 子付 %d（共 %d）"
				% [int(p["from_dealer"]), int(p["from_other"]), int(p["total"])])
		else:
			L.append("点数：自摸 %d 点all（共 %d）" % [int(p.get("each", 0)), int(p.get("total", 0))])
	else:
		L.append("点数：荣和 %d 点（放铳者付 %d）" % [int(p.get("total", 0)), int(p.get("total", 0))])
	if str(p.get("limit", "")) != "":
		L.append("段位：" + str(p["limit"]))

	if r.get("sets_text") and r["sets_text"].size() > 0:
		var wait_cn := {"ryanmen": "两面", "kanchan": "嵌张", "penchan": "边张",
			"tanki": "单骑", "shanpon": "双碰", "none": "—"}
		L.append("拆解：" + "、".join(PackedStringArray(r["sets_text"]))
			+ "　雀头 " + str(r.get("pair_text", ""))
			+ "　听牌形 " + str(wait_cn.get(str(r.get("wait", "")), str(r.get("wait", "")))))
	out.text = "\n".join(L)
	tip.text = "判定完成（数据来自 server/judge_cli.py）"
