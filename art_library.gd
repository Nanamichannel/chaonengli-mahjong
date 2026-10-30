# -*- coding: utf-8 -*-
# ArtLibrary：所有「图」的取用口 —— 图全部是场景里的节点，代码只按名字取。
#
# 为什么要这样（和以前的做法对比）：
#   以前：main.gd 里写死路径 `_load_tex("res://Cailiao/…/b_04.png")` 现读现用 ——
#         想加动效就得改代码，还容易写错路径、图换了代码就崩。
#   现在：图在场景里就是节点（本节点下有 牌背 / 宝牌指示牌 / 杠面 三组），
#         代码只说「我要 b_04 那张」「我要 1m 的宝牌指示牌」。
#         → 想加动效：直接给这些节点挂 AnimationPlayer / 加脚本 / 换图，代码一行不用动。
#
# 用法（main.gd 里通过 Art/… 节点调）：
#   art.call("tex", "牌背", "b_04")            # 取贴图
#   art.call("sprite", "牌背", "b_04")         # 取节点本身（想拿它做动画/复制就用这个）
#   art.call("dora_tex", "v", "1m")            # 宝牌指示牌：竖翻
#   art.call("kan_tex", "19anke")              # 杠面（暗杠那张「两张牌叠着画」的图）
extends Node2D

# ── 组名（和场景里的节点路径一致；改名的话这里跟着改）──
const GROUP_BACK := "牌背"                     # b_01 .. b_06（b_05 已在节点里裁好中间那块）
const GROUP_KAN := "杠面"                      # 槓 kan 文件夹里的图
const GROUP_DORA_V := "宝牌指示牌/竖翻"           # 「竖 翻转」文件夹
const GROUP_DORA_H := "宝牌指示牌/横翻"           # 「横 翻转」文件夹

# 宝牌指示牌的方向：main.gd 里的 DORA_VIEW 用 "h" (横) / "hf" (横翻) / "vf" (竖翻)
const DORA_DIR_OF_VIEW := {"h": GROUP_DORA_H, "hf": GROUP_DORA_H, "vf": GROUP_DORA_V}


# 按「组 / 名字」取节点
func sprite(group: String, key: String) -> Sprite2D:
	return get_node_or_null(group + "/" + key) as Sprite2D


# 按「组 / 名字」取贴图
func tex(group: String, key: String) -> Texture2D:
	var s := sprite(group, key)
	return s.texture if s != null else null


# ── 常用快捷口 ──────────────────────────────────────────────────────────────
func back_tex(key: String) -> Texture2D:                 # "b_01" / "b_02" / "b_04" / "b_05" …
	return tex(GROUP_BACK, key)


func back_sprite(key: String) -> Sprite2D:
	return sprite(GROUP_BACK, key)


func kan_tex(key: String) -> Texture2D:                  # key = kan_face_name() 的结果
	return tex(GROUP_KAN, key)


func kan_sprite(key: String) -> Sprite2D:
	return sprite(GROUP_KAN, key)


# view 可以是 "h"/"hf"/"vf"（和 DORA_VIEW 一致）；key = 文件名（1m / 0p / h1z …）
func dora_tex(view: String, key: String) -> Texture2D:
	return tex(String(DORA_DIR_OF_VIEW.get(view, GROUP_DORA_V)), key)


func dora_sprite(view: String, key: String) -> Sprite2D:
	return sprite(String(DORA_DIR_OF_VIEW.get(view, GROUP_DORA_V)), key)


# 这个组里一共登记了哪些名字（调试/自检用：能看出缺了哪几张图）
func keys(group: String) -> Array:
	var g := get_node_or_null(group)
	if g == null:
		return []
	var out := []
	for c in g.get_children():
		out.append(String(c.name))
	return out
