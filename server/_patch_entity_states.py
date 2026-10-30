# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

p = r'N:\apps\tianma\server\db.py'
s = open(p, encoding='utf-8').read()

start = s.find('    def entity_states')
end = s.find('    def wall_taken_nos')
assert start != -1 and end != -1 and end > start, 'markers not found'

new = '''    def entity_states(self, round_id: int) -> list[dict]:
        """返回 136 张牌的全局实体状态（按 seq 排序）。

        每张牌：id(实体编号)、kind(牌种)、loc(wall/dead/hand/meld/river/dora)、
        seat(归属座位，墙内为 -1)、form(显示形式)、rotated(是否横置)、slot(槽位)、
        group(副露组号，仅 loc=meld 有)。服务端只给「语义状态」，客户端据此算位置。
        """
        wall = self._rows(
            "SELECT seq, tile, entity, zone, dealt_to FROM round_wall "
            "WHERE round_id=? ORDER BY seq", (round_id,))
        hands = {r["wall_seq"]: r for r in self._rows(
            "SELECT wall_seq, seat, slot, is_drawn FROM round_hands WHERE round_id=?",
            (round_id,))}
        # 牌河：按全场打出顺序（seq）排，再按座位给每家自己的槽位号
        discards = {}
        river_counter = {}
        for r in self._rows(
                "SELECT seq, wall_seq, seat, is_riichi_tile FROM round_discards "
                "WHERE round_id=? AND called=0 ORDER BY seq", (round_id,)):
            s = int(r["seat"])
            slot = int(river_counter.get(s, 0))
            river_counter[s] = slot + 1
            discards[int(r["wall_seq"])] = {
                "seat": s, "is_riichi_tile": r["is_riichi_tile"], "slot": slot,
            }
        # 副露：seqs_json 是物理编号数组，tiles_json 是显示顺序；meld_id 是组号
        meld_seq = {}
        for r in self._rows(
                "SELECT meld_id, seat, kind, rot_index, seqs_json, tiles_json "
                "FROM round_melds WHERE round_id=?", (round_id,)):
            try:
                seqs = json.loads(r["seqs_json"] or "[]")
                tiles = json.loads(r["tiles_json"] or "[]")
            except (ValueError, TypeError):
                seqs, tiles = [], []
            for i, ws in enumerate(seqs):
                meld_seq[int(ws)] = {
                    "seat": r["seat"], "kind": r["kind"],
                    "rot": int(r["rot_index"]) == i,
                    "closed": r["kind"] == "ankan",
                    "tiles": tiles, "pos": i, "group": int(r["meld_id"]),
                }
        dora_seq = set()
        for r in self._rows(
                "SELECT indicator FROM round_dora WHERE round_id=? AND revealed=1",
                (round_id,)):
            # 宝牌指示牌本身在 round_wall 里靠 tile 匹配（indicator 是牌名）
            for w in wall:
                if w["tile"] == r["indicator"] and w["seq"] not in dora_seq and w["zone"] == "dead":
                    dora_seq.add(w["seq"])
                    break

        out = []
        for w in wall:
            seq = int(w["seq"])
            entity = w["entity"] or (w["tile"] + f"{seq:02d}")
            st = {"id": entity, "kind": w["tile"], "seq": seq,
                  "loc": "wall", "seat": -1, "form": "hidden", "rotated": False,
                  "slot": 0}
            if seq in hands:
                h = hands[seq]
                st.update({"loc": "hand", "seat": h["seat"],
                           "form": "hand", "slot": h["slot"],
                           "drawn": bool(h["is_drawn"])})
            elif seq in meld_seq:
                m = meld_seq[seq]
                form = "back_meld" if m["closed"] else "face_meld"
                st.update({"loc": "meld", "seat": m["seat"], "form": form,
                           "rotated": m["rot"], "slot": m["pos"],
                           "meld_kind": m["kind"], "group": m["group"]})
            elif seq in discards:
                d = discards[seq]
                st.update({"loc": "river", "seat": d["seat"], "form": "river",
                           "rotated": bool(d["is_riichi_tile"]), "slot": d["slot"]})
            elif seq in dora_seq:
                st.update({"loc": "dora", "seat": -1, "form": "dora"})
            elif w["zone"] in ("dead",):
                st.update({"loc": "dead", "form": "hidden"})
            out.append(st)
        return out

'''

s = s[:start] + new + s[end:]
open(p, 'w', encoding='utf-8').write(s)
print('patched entity_states OK')
