import io

p = "db.py"
t = io.open(p, encoding="utf-8").read()
old = '''        if self._schema_current():
            return
        with open(self.schema_path, "r", encoding="utf-8") as f:
'''
new = '''        if self._schema_current():
            # ★ 版本对上也不能直接 return：老库可能还缺新加的列（_migrate 负责补）
            self._migrate()
            return
        with open(self.schema_path, "r", encoding="utf-8") as f:
'''
assert old in t
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="").write(t)
print("ok")
