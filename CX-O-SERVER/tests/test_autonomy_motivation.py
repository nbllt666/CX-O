"""CX-O-Autonomy P1-T1 动机引擎单测：MotivationState 四维动机状态。

覆盖：
① 初始值（对齐 manager.py：0.2/0.2/0.2/0.0）
② curiosity / social_need 随时间上升且 cap 1.0
③ creative_drive / fatigue 随时间衰减且 floor 0
④ record_info_ingestion / record_interaction 使对应值下降（floor 0）
⑤ record_activity 使 fatigue 上升（cap 1.0）
⑥ record_material 使 creative_drive 上升（cap 1.0）
⑦ clamp 边界：超 1 收拢 1、减到负收拢 0（构造 + 行为记录两条路径）
⑧ save/load 往返一致（to_dict 相等）
⑨ load 文件不存在返回默认状态
⑩ tick 支持小数分钟且确定性（纯算术，无随机源）

运行：python -m pytest tests/test_autonomy_motivation.py -q
"""
from pathlib import Path

import pytest

from server.autonomy.core.motivation.state import MotivationState

# 默认初始值（对齐 manager.py 的 Motivations 初始值）
DEFAULT_STATE = {"curiosity": 0.2, "social_need": 0.2, "creative_drive": 0.2, "fatigue": 0.0}


# ================================================================ ① 初始值
class TestInitialValues:
    def test_default_state(self):
        st = MotivationState()
        assert st.to_dict() == DEFAULT_STATE

    def test_injected_values(self):
        st = MotivationState(curiosity=0.5, social_need=0.6, creative_drive=0.7, fatigue=0.1)
        assert st.to_dict() == {
            "curiosity": 0.5, "social_need": 0.6, "creative_drive": 0.7, "fatigue": 0.1,
        }


# ================================================================ ② 随时间上升 + cap 1.0
class TestTimeGrowth:
    def test_curiosity_and_social_need_grow(self):
        st = MotivationState(curiosity=0.2, social_need=0.2)
        st.tick(60)  # 1 小时
        assert st.curiosity == pytest.approx(0.2 + 0.05)
        assert st.social_need == pytest.approx(0.2 + 0.04)

    def test_growth_caps_at_one(self):
        st = MotivationState(curiosity=0.99, social_need=0.98)
        st.tick(1200)  # 20 小时，远超 cap
        assert st.curiosity == 1.0
        assert st.social_need == 1.0


# ================================================================ ③ 随时间衰减 + floor 0
class TestTimeDecay:
    def test_creative_drive_and_fatigue_decay(self):
        st = MotivationState(creative_drive=0.5, fatigue=0.4)
        st.tick(60)  # 1 小时
        assert st.creative_drive == pytest.approx(0.5 - 0.02)
        assert st.fatigue == pytest.approx(0.4 - 0.10)

    def test_decay_floors_at_zero(self):
        st = MotivationState(creative_drive=0.02, fatigue=0.05)
        st.tick(1200)  # 20 小时，远超衰减量
        assert st.creative_drive == 0.0
        assert st.fatigue == 0.0


# ================================================================ ④ 信息摄入 / 社交互动下降
class TestBehaviorDrop:
    def test_info_ingestion_drops_curiosity(self):
        st = MotivationState(curiosity=0.5)
        st.record_info_ingestion()
        assert st.curiosity == pytest.approx(0.5 - 0.30)

    def test_interaction_drops_social_need(self):
        st = MotivationState(social_need=0.5)
        st.record_interaction()
        assert st.social_need == pytest.approx(0.5 - 0.30)

    def test_drop_floors_at_zero(self):
        st = MotivationState(curiosity=0.1, social_need=0.1)
        st.record_info_ingestion()
        st.record_interaction()
        assert st.curiosity == 0.0
        assert st.social_need == 0.0


# ================================================================ ⑤ 活动提升 fatigue
class TestActivityBump:
    def test_activity_raises_fatigue(self):
        st = MotivationState(fatigue=0.0)
        st.record_activity()
        assert st.fatigue == pytest.approx(0.15)

    def test_activity_caps_fatigue_at_one(self):
        st = MotivationState(fatigue=0.9)
        st.record_activity()
        st.record_activity()
        assert st.fatigue == 1.0


# ================================================================ ⑥ 素材提升 creative_drive
class TestMaterialBump:
    def test_material_raises_creative_drive(self):
        st = MotivationState(creative_drive=0.2)
        st.record_material()
        assert st.creative_drive == pytest.approx(0.2 + 0.10)

    def test_material_caps_creative_drive_at_one(self):
        st = MotivationState(creative_drive=0.95)
        st.record_material()
        assert st.creative_drive == 1.0


# ================================================================ ⑦ clamp 边界（超 1 减 0）
class TestClampBounds:
    def test_constructor_clamps_above_one(self):
        st = MotivationState(curiosity=1.5, social_need=2.0, creative_drive=3.0, fatigue=99.0)
        assert st.to_dict() == {"curiosity": 1.0, "social_need": 1.0, "creative_drive": 1.0, "fatigue": 1.0}

    def test_constructor_clamps_below_zero(self):
        st = MotivationState(curiosity=-0.5, social_need=-1.0, creative_drive=-2.0, fatigue=-0.1)
        assert st.to_dict() == {"curiosity": 0.0, "social_need": 0.0, "creative_drive": 0.0, "fatigue": 0.0}

    def test_behavior_paths_clamp_both_directions(self):
        st = MotivationState(curiosity=0.1, social_need=0.1, creative_drive=0.99, fatigue=0.99)
        st.record_info_ingestion()  # 0.1 - 0.30 -> 0.0
        st.record_interaction()      # 0.1 - 0.30 -> 0.0
        st.record_material()         # 0.99 + 0.10 -> 1.0
        st.record_activity()         # 0.99 + 0.15 -> 1.0
        assert st.curiosity == 0.0
        assert st.social_need == 0.0
        assert st.creative_drive == 1.0
        assert st.fatigue == 1.0


# ================================================================ ⑧ save/load 往返一致
class TestPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        st = MotivationState(curiosity=0.8, social_need=0.3, creative_drive=0.6, fatigue=0.4)
        st.record_activity()
        st.tick(30)
        path = st.save(store_path=str(tmp_path))
        assert path.endswith("motivation_state.json")

        loaded = MotivationState.load(store_path=str(tmp_path))
        assert loaded.to_dict() == st.to_dict()

    def test_save_returns_existing_path(self, tmp_path):
        st = MotivationState(curiosity=0.5)
        path = st.save(store_path=str(tmp_path))
        assert Path(path).exists()


# ================================================================ ⑨ load 文件不存在返回默认
class TestLoadMissing:
    def test_load_missing_file_returns_default(self, tmp_path):
        loaded = MotivationState.load(store_path=str(tmp_path / "not_exists"))
        assert loaded.to_dict() == DEFAULT_STATE


# ================================================================ ⑩ tick 小数分钟确定性
class TestTickFractionalDeterministic:
    def test_fractional_minutes(self):
        st = MotivationState(curiosity=0.2, social_need=0.2, creative_drive=0.3, fatigue=0.3)
        st.tick(7.5)  # 7.5 分钟 = 0.125 小时
        assert st.curiosity == pytest.approx(0.2 + 0.05 * 0.125)
        assert st.social_need == pytest.approx(0.2 + 0.04 * 0.125)
        assert st.creative_drive == pytest.approx(0.3 - 0.02 * 0.125)
        assert st.fatigue == pytest.approx(0.3 - 0.10 * 0.125)

    def test_split_tick_equals_single_tick(self):
        # 15 分钟两次 == 30 分钟一次（纯算术确定性）
        a = MotivationState(curiosity=0.2, social_need=0.2, creative_drive=0.3, fatigue=0.3)
        a.tick(15)
        a.tick(15)
        b = MotivationState(curiosity=0.2, social_need=0.2, creative_drive=0.3, fatigue=0.3)
        b.tick(30)
        assert a.to_dict() == pytest.approx(b.to_dict())
