# -*- coding: utf-8 -*-
extends RefCounted
##
## txt.gd —— 显示层文本整形（把中文全角标点换成半角，手机上显得没那么大）
##
## 只用于**显示**：协议字段、比较用的字符串一律不要走这里。
## 用法：
##   const Txt := preload("res://txt.gd")
##   lbl.text = Txt.half(some_text)

# 源 → 目标（成对放在一个扁平数组里，避免每次调用都构造 Dictionary/keys 数组）
const _SRC := "：，；（）【】、　＝／％"
const _DST := ":,;()[], =/%"


## 没有全角标点时原样返回（不额外分配字符串）
static func half(s: String) -> String:
	var need := false
	for i in _SRC.length():
		if s.contains(_SRC[i]):
			need = true
			break
	if not need:
		return s
	for i in _SRC.length():
		var c := _SRC[i]
		if s.contains(c):
			s = s.replace(c, _DST[i])
	return s
