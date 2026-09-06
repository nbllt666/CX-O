"""
Mock 与契约一致性验证入口（s0202）：歌谱夹具经真实 validate_score 校验

每个 v2 夹具必须直接通过模块0 的真实 validate_score；v1 夹具经自动迁移后通过。
这是「预生成 Mock 与冻结契约一致」的程序化断言，前端 staff/__mocks__/fixtures.ts
与本夹具同源（同一 JSON 生成），后端通过即覆盖两侧快照一致性。
"""
from __future__ import annotations

import pytest

from tests.fixtures.score_fixtures import (
    SCORE_FIXTURES,
    V1_FIXTURE_NAMES,
    V2_FIXTURE_NAMES,
    get_fixture,
)
from workstation.music import validate_score


class TestV2Fixtures:
    """v2 夹具：必须经真实 validate_score 校验通过"""

    @pytest.mark.parametrize("name", V2_FIXTURE_NAMES)
    def test_v2_fixture_passes_validation(self, name):
        ok, errors, normalized = validate_score(get_fixture(name))
        assert ok is True, f"夹具 {name} 未通过 validate_score: {errors}"
        assert errors == []
        assert normalized is not None
        # 规范化产物为 v2 形状
        assert "accompaniment_style" not in normalized
        assert "accompaniment_tracks" in normalized

    def test_full_multitrack_fixture_structure(self):
        """多轨完整样本：auto 钢琴轨 + manual 贝斯轨（含 events）+ auto 鼓组轨"""
        ok, errors, normalized = validate_score(get_fixture("full_multitrack_v2"))
        assert ok is True, errors
        tracks = {t["id"]: t for t in normalized["accompaniment_tracks"]}
        assert set(tracks) == {"trk_piano", "trk_bass", "trk_drum"}
        assert tracks["trk_piano"]["mode"] == "auto"
        assert tracks["trk_piano"]["style"] == "block_chords"
        assert tracks["trk_piano"]["events"] == []
        assert tracks["trk_bass"]["mode"] == "manual"
        assert len(tracks["trk_bass"]["events"]) == 4
        assert tracks["trk_drum"]["program"] == -1
        assert tracks["trk_drum"]["style"] == "rock_4beat"


class TestV1Fixtures:
    """v1 夹具：经 validate_score 自动迁移后通过，且迁移结果符合 x-migration"""

    @pytest.mark.parametrize("name", V1_FIXTURE_NAMES)
    def test_v1_fixture_migrates_and_passes(self, name):
        ok, errors, normalized = validate_score(get_fixture(name))
        assert ok is True, f"v1 夹具 {name} 迁移后未通过: {errors}"
        assert "accompaniment_style" not in normalized
        assert len(normalized["accompaniment_tracks"]) == 1
        track = normalized["accompaniment_tracks"][0]
        assert track["id"] == "trk_0"
        assert track["program"] == 0
        assert track["mode"] == "auto"

    def test_v1_piano_maps_to_block_chords(self):
        ok, _, normalized = validate_score(get_fixture("v1_piano"))
        assert ok is True
        assert normalized["accompaniment_tracks"][0]["style"] == "block_chords"

    def test_v1_guitar_style_preserved(self):
        ok, _, normalized = validate_score(get_fixture("v1_guitar"))
        assert ok is True
        assert normalized["accompaniment_tracks"][0]["style"] == "guitar"


def test_fixture_registry_complete():
    """夹具登记完整性：5 个夹具全部注册，v1/v2 名单与实际一致"""
    assert set(SCORE_FIXTURES) == set(V2_FIXTURE_NAMES) | set(V1_FIXTURE_NAMES)
