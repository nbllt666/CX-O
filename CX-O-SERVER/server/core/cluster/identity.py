"""节点身份：首次生成持久化，再次加载不变。

契约字段对齐 public/schema/cluster_identity.schema.json：
node_id / node_name / endpoint / created_at / capabilities。
"""
from __future__ import annotations

import json
import socket
import uuid
from datetime import datetime
from pathlib import Path


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


class NodeIdentity:
    """节点唯一身份。node_id 首次生成后持久化不变，接管时靠它识别『这是谁的副本』。"""

    node_id: str = ""
    node_name: str = ""
    endpoint: str = ""
    created_at: str = ""

    def load_or_create(self, data_dir, config=None) -> str:
        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        identity_file = data_dir / "node_identity.json"

        if identity_file.exists():
            try:
                with open(identity_file, "r", encoding="utf-8") as f:
                    doc = json.load(f)
                self.node_id = str(doc["node_id"])
                self.node_name = str(doc.get("node_name") or getattr(config, "node_name", "") or "")
                self.endpoint = str(doc.get("endpoint") or "")
                self.created_at = str(doc.get("created_at") or "")
                return self.node_id
            except (json.JSONDecodeError, KeyError, OSError):
                # 损坏/字段缺失：走重建路径（完好文件上保持幂等）
                pass

        node_id = "cxo-node-" + uuid.uuid4().hex
        scheme = getattr(config, "transport", "https") or "https"
        default_port = 8443 if scheme == "https" else 8080
        host = getattr(config, "bind", "0.0.0.0") or "0.0.0.0"
        if host in ("0.0.0.0", "::", ""):
            host = socket.gethostname() or "localhost"
        endpoint = f"{scheme}://{host}:{default_port}"

        self.node_id = node_id
        self.node_name = str(getattr(config, "node_name", "") or "")
        self.endpoint = endpoint
        self.created_at = _now_iso()

        doc = {
            "node_id": node_id,
            "node_name": self.node_name,
            "endpoint": endpoint,
            "created_at": self.created_at,
            "capabilities": {},
        }
        tmp = identity_file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        tmp.replace(identity_file)
        return node_id

    def as_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "endpoint": self.endpoint,
            "created_at": self.created_at,
            "capabilities": {},
        }