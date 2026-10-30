import io

p = "schema.sql"
t = io.open(p, encoding="utf-8").read()
old = '''    is_riichi_tile INTEGER NOT NULL DEFAULT 0, -- 立直宣言牌（横置）
'''
new = '''    is_riichi_tile INTEGER NOT NULL DEFAULT 0, -- 立直宣言牌（横置）
    face_down   INTEGER NOT NULL DEFAULT 0,    -- 1 = 暗牌（换牌技能放进牌河的）
'''
assert old in t
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="").write(t)
print("schema.sql ok")
