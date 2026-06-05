"""图模型：解析 LiteGraph 序列化结构，提供取源/取靶/属性等 helper。

LiteGraph 序列化：
  nodes: [{id, type, properties, inputs:[{name,type,link}], outputs:[{name,type,links:[]}]}]
  links: [[link_id, origin_id, origin_slot, target_id, target_slot, type], ...]
"""
from __future__ import annotations


class GraphModel:
    def __init__(self, data: dict):
        self.data = data or {}
        self.nodes: dict[int, dict] = {n["id"]: n for n in self.data.get("nodes", [])}
        # link_id -> (origin_id, origin_slot, target_id, target_slot, type)
        self.links: dict = {}
        for link in self.data.get("links", []):
            if not link:
                continue
            lid, oid, oslot, tid, tslot = link[0], link[1], link[2], link[3], link[4]
            ltype = link[5] if len(link) > 5 else None
            self.links[lid] = (oid, oslot, tid, tslot, ltype)

    # ---- 节点 ----
    def node(self, nid: int) -> dict | None:
        return self.nodes.get(nid)

    def nodes_of_type(self, ntype: str) -> list[dict]:
        return [n for n in self.nodes.values() if n.get("type") == ntype]

    def prop(self, node: dict, name: str, default=None):
        return (node.get("properties") or {}).get(name, default)

    # ---- 端口槽位 ----
    @staticmethod
    def in_slot_index(node: dict, name: str) -> int:
        for i, s in enumerate(node.get("inputs") or []):
            if s.get("name") == name:
                return i
        return -1

    @staticmethod
    def out_slot_index(node: dict, name: str) -> int:
        for i, s in enumerate(node.get("outputs") or []):
            if s.get("name") == name:
                return i
        return -1

    # ---- 取源（某输入端口连到的源 节点+输出槽）----
    def input_source(self, node: dict, input_name: str):
        idx = self.in_slot_index(node, input_name)
        if idx < 0:
            return None
        slot = (node.get("inputs") or [])[idx]
        lid = slot.get("link")
        if lid is None or lid not in self.links:
            return None
        oid, oslot, _, _, _ = self.links[lid]
        src = self.nodes.get(oid)
        if src is None:
            return None
        return src, oslot   # (源节点, 源输出槽 index)

    # ---- 取靶（某输出端口连到的所有 目标 节点+输入槽）----
    def output_targets(self, node: dict, output_name: str):
        idx = self.out_slot_index(node, output_name)
        if idx < 0:
            return []
        slot = (node.get("outputs") or [])[idx]
        out = []
        for lid in (slot.get("links") or []):
            if lid in self.links:
                _, _, tid, tslot, _ = self.links[lid]
                tnode = self.nodes.get(tid)
                if tnode is not None:
                    out.append((tnode, tslot))
        return out

    # ---- 沿 exec 输出找下一个节点（exec 1→1，取第一个）----
    def next_exec(self, node: dict, output_name: str = "out"):
        targets = self.output_targets(node, output_name)
        return targets[0][0] if targets else None
