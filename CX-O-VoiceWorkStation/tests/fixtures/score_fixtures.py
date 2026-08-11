"""
歌谱测试夹具加载器（s0202 预生成 Mock 后端侧）

唯一真相源 = 同目录 score_fixtures.json（前后端同源：前端
staff/__mocks__/fixtures.ts 由该 JSON 生成，禁止手改前端副本以外的漂移源）。

夹具清单：
- minimal_v2: 最小样本（仅必填 + 占位单音符 melody）
- melody_only_v2: 纯旋律（无 chords 无伴奏轨）
- full_multitrack_v2: 多轨完整样本（melody+chords+auto 钢琴轨+manual 贝斯轨含 events+auto 鼓组轨）
- v1_piano / v1_guitar: v1 输入样本（含 accompaniment_style，供迁移测试复用）
"""
from __future__ import annotations

import json
import os
from typing import Any

_FIXTURES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "score_fixtures.json")


def _load() -> dict[str, Any]:
    with open(_FIXTURES_PATH, "r", encoding="utf-8") as fp:
        return json.load(fp)


_RAW = _load()

# 夹具名 → 歌谱 dict（不含 description 元信息）
SCORE_FIXTURES: dict[str, dict] = {
    name: entry["score"] for name, entry in _RAW.items() if not name.startswith("_")
}

# v2 夹具名（必须直接通过 validate_score）
V2_FIXTURE_NAMES = ["minimal_v2", "melody_only_v2", "full_multitrack_v2"]
# v1 夹具名（经 validate_score 自动迁移后通过）
V1_FIXTURE_NAMES = ["v1_piano", "v1_guitar"]


def get_fixture(name: str) -> dict:
    """按名取夹具歌谱（调用方自行 deepcopy 后再修改）"""
    return SCORE_FIXTURES[name]
