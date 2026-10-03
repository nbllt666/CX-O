"""CX-O-Autonomy P1-T1 动机引擎单测：MotivationState 四维动机状态。

覆盖：
① 初始值（对齐 manager.py：0.2/0.2/0.2/0.0；fatigue 0.0 经四维正下限收拢为 0.02）
② curiosity / social_need 随时间上升且 cap 1.0
③ creative_drive / fatigue 随时间衰减（四维统一正下限，衰减落点 ≥ 下限）
④ record_info_ingestion / record_interaction 使对应值**按比例**下降（渐近、不触 0）
⑤ record_activity 使 fatigue 上升（cap 1.0）
⑥ record_material 使 creative_drive 上升（cap 1.0）；record_creation 按比例消费之
   且与素材获取配对——只取素材会钉死 1.0，有消费则解除边界锁
⑦ clamp 边界：超 1 收拢 1、减到负收拢 0（构造 + 行为记录两条路径）
⑧ save/load 往返一致（to_dict 相等）
⑨ load 文件不存在返回默认状态
⑩ tick 支持小数分钟且确定性（纯算术，无随机源）
⑪ 焦点对象：set_focus 规整（topic 去空白 / level clamp）、to_dict 不含 focus、
   save/load 往返保留 focus、旧版无 focus 键文件按空焦点恢复（向后兼容）
⑫ 四维正下限：构造 / load / tick / 摄入 / 互动 / 活动 / 素材 / 消费全路径均不触 0

运行：python -m pytest tests/test_autonomy_motivation.py -q
"""
import json
from pathlib import Path

import pytest

from server.autonomy.core.motivation.state import MotivationState

# 默认初始值（对齐 manager.py 的 Motivations 初始值；fatigue 0.0 经四维正下限收拢为 0.02）
DEFAULT_STATE = {"curiosity": 0.2, "social_need": 0.2, "creative_drive": 0.2, "fatigue": 0.02}
# 四维统一正下限（题目：0 边界在四维上均不可达）
FLOOR = 0.02


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

    def test_decay_floors(self):
        """四维统一正下限：衰减不会把任一维度压到 0。"""
        st = MotivationState(creative_drive=0.03, fatigue=0.05)
        st.tick(1200)  # 20 小时，远超衰减量
        assert st.creative_drive == pytest.approx(FLOOR)
        assert st.fatigue == pytest.approx(FLOOR)


# ================================================================ ④ 信息摄入 / 社交互动按比例下降
class TestBehaviorDrop:
    def test_info_ingestion_drops_curiosity_proportionally(self):
        st = MotivationState(curiosity=0.5)
        st.record_info_ingestion()
        assert st.curiosity == pytest.approx(0.5 * (1 - 0.30))

    def test_interaction_drops_social_need_proportionally(self):
        st = MotivationState(social_need=0.5)
        st.record_interaction()
        assert st.social_need == pytest.approx(0.5 * (1 - 0.30))

    def test_drop_is_damped_and_never_reaches_floor(self):
        """比例式回落：幅度随剩余值递减，绝不触 0（下限兜底）。"""
        st = MotivationState(curiosity=0.05, social_need=0.05)
        st.record_info_ingestion()
        st.record_interaction()
        assert st.curiosity == pytest.approx(0.05 * 0.7)
        assert st.social_need == pytest.approx(0.05 * 0.7)
        for _ in range(50):
            st.record_info_ingestion()
            st.record_interaction()
        assert st.curiosity == pytest.approx(FLOOR)
        assert st.social_need == pytest.approx(FLOOR)


# ================================================================ ⑤ 活动提升 fatigue
class TestActivityBump:
    def test_activity_raises_fatigue(self):
        st = MotivationState(fatigue=0.0)  # 0.0 经下限收拢为 0.02
        st.record_activity()
        assert st.fatigue == pytest.approx(FLOOR + 0.15)

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


# ================================================================ ⑥b 创作消费（素材的配对侧）
class TestCreationConsume:
    def test_creation_damps_creative_drive_proportionally(self):
        st = MotivationState(creative_drive=0.8)
        st.record_creation()
        assert st.creative_drive == pytest.approx(0.4)  # 消费当前值的 50%

    def test_repeated_creation_never_reaches_zero(self):
        """比例式消费 + 正下限：50 次消费后落在 motivation_min（0 不可达）。"""
        st = MotivationState(creative_drive=0.8)
        for _ in range(50):
            st.record_creation()
        assert st.creative_drive == pytest.approx(0.02)

    def test_zero_consume_ratio_keeps_value(self):
        """ratio=0 表示不消费；越界比例被收拢到 [0, _MAX_RATIO]（上界严格 <1）。"""
        st = MotivationState(creative_drive=0.5, creative_consume_ratio=0.0)
        st.record_creation()
        assert st.creative_drive == pytest.approx(0.5)
        st.record_creation()
        assert st.creative_drive == pytest.approx(0.5)
        assert MotivationState(creative_consume_ratio=9.9).creative_consume_ratio == 0.99
        assert MotivationState(creative_consume_ratio=-1).creative_consume_ratio == 0.0
        # 即便 ratio 被配到上界，仍不会被清空（下限兜底）
        st_hi = MotivationState(creative_drive=0.5, creative_consume_ratio=1.0)
        st_hi.record_creation()
        assert st_hi.creative_drive == pytest.approx(0.02)

    def test_material_only_would_pin_creative_drive_but_creation_releases_it(self):
        """GN-004 Q5 边界锁：只取素材会把 creative_drive 钉在 1.0；创作消费提供泄压阀。

        时间衰减仅 0.02/h（且受正下限约束，不再归 0），故缺配对时 creative_drive 会长期
        贴死在 1.0 —— 与"动机退化为常量"属同类缺陷。
        """
        pinned = MotivationState(creative_drive=0.5)
        for _ in range(6):
            pinned.record_material()  # 只取素材、从不创作
        assert pinned.creative_drive == 1.0  # 旧行为：钉死上限

        released = MotivationState(creative_drive=0.5)
        low = 1.0
        for _ in range(6):
            released.record_material()
            released.record_creation()
            low = min(low, released.creative_drive)
        assert low >= 0.02  # 有泄压阀：不再钉死上限，且不触 0 侧（正下限兜底）

    def test_material_creation_alternation_converges_to_positive_fixed_point(self):
        """"素材 +0.10 / 创作 ×0.5" 的交替稳态 = 0.10/(1/0.5−1) = 0.10 > 0（0 侧不可达）。"""
        st = MotivationState(creative_drive=0.5)
        for _ in range(30):
            st.record_material()
            st.record_creation()
        assert st.creative_drive == pytest.approx(0.10, abs=0.01)


# ================================================================ ⑥c 四维正下限（0 侧不可达）
class TestMotivationNonZeroFloor:
    """四维统一正下限：0 边界在构造 / load / tick / 各行为反馈的全部路径上均不可达。"""

    def test_constructor_and_load_floor(self, tmp_path):
        st = MotivationState(curiosity=0.0, social_need=0.0, creative_drive=0.0, fatigue=0.0)
        assert st.to_dict() == {
            "curiosity": FLOOR, "social_need": FLOOR,
            "creative_drive": FLOOR, "fatigue": FLOOR,
        }
        # 旧盘（饱和态四维含 0）恢复后同样不触 0
        (tmp_path / "motivation_state.json").write_text(
            json.dumps({"curiosity": 1.0, "social_need": 1.0,
                        "creative_drive": 0.0, "fatigue": 0.0}),
            encoding="utf-8",
        )
        loaded = MotivationState.load(store_path=str(tmp_path))
        assert loaded.to_dict()["creative_drive"] == pytest.approx(FLOOR)
        assert loaded.to_dict()["fatigue"] == pytest.approx(FLOOR)

    def test_all_paths_keep_every_dimension_above_zero(self):
        """穷举写入路径（tick 衰减 / 摄入 / 互动 / 活动 / 素材 / 消费）后四维仍 ≥ 下限。"""
        st = MotivationState(curiosity=0.05, social_need=0.05,
                             creative_drive=0.05, fatigue=0.05)
        for _ in range(200):
            st.tick(60)                # 时间演化
            st.record_info_ingestion()
            st.record_interaction()
            st.record_activity()
            st.record_material()
            st.record_creation()
        assert min(st.to_dict().values()) >= FLOOR

    def test_custom_floor_can_be_relaxed(self):
        """下限可注入（默认 0.02）；设为 0 时退回"允许触 0"的旧语义（显式 opt-in）。"""
        st = MotivationState(curiosity=0.5, motivation_min=0.0)
        for _ in range(50):
            st.record_info_ingestion()
        assert 0.0 <= st.curiosity < 0.01

    def test_floor_upper_bound_prevents_ceiling_pin(self):
        """下限收拢到严格小于上限：`motivation_min=1.0` 会令四维恒钉 1.0，故被收到 0.99。"""
        assert MotivationState(motivation_min=9.9).motivation_min == 0.99
        assert MotivationState(motivation_min=1.0).motivation_min == 0.99
        assert MotivationState(motivation_min=-5).motivation_min == 0.0
        # 即便取到上界，四维仍严格小于 1.0（不会与上限重合）
        st = MotivationState(motivation_min=0.99)
        assert max(st.to_dict().values()) < 1.0


# ================================================================ ⑦ clamp 边界（超 1 减 0）
class TestClampBounds:
    def test_constructor_clamps_above_one(self):
        st = MotivationState(curiosity=1.5, social_need=2.0, creative_drive=3.0, fatigue=99.0)
        assert st.to_dict() == {"curiosity": 1.0, "social_need": 1.0, "creative_drive": 1.0, "fatigue": 1.0}

    def test_constructor_clamps_below_zero(self):
        # 四维下限均为 motivation_min（默认 0.02），故不归 0
        st = MotivationState(curiosity=-0.5, social_need=-1.0, creative_drive=-2.0, fatigue=-0.1)
        assert st.to_dict() == {"curiosity": FLOOR, "social_need": FLOOR,
                                "creative_drive": FLOOR, "fatigue": FLOOR}

    def test_behavior_paths_clamp_both_directions(self):
        st = MotivationState(curiosity=0.1, social_need=0.1, creative_drive=0.99, fatigue=0.99)
        st.record_info_ingestion()   # 0.1 * 0.7 -> 0.07
        st.record_interaction()      # 0.1 * 0.7 -> 0.07
        st.record_material()         # 0.99 + 0.10 -> 1.0
        st.record_activity()         # 0.99 + 0.15 -> 1.0
        assert st.curiosity == pytest.approx(0.07)
        assert st.social_need == pytest.approx(0.07)
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


# ================================================================ ⑪ 焦点对象（curiosity 的指向性）
class TestFocus:
    def test_default_focus_is_empty(self):
        assert MotivationState().to_focus_dict() == {"topic": "", "level": 0.0}

    def test_constructor_normalizes_focus(self):
        st = MotivationState(focus_topic="  量子计算  ", focus_level=1.7)
        assert st.to_focus_dict() == {"topic": "量子计算", "level": 1.0}

    def test_set_focus_strips_topic_and_clamps_level(self):
        st = MotivationState()
        st.set_focus("  AI 芯片出口管制  ", 1.4)
        assert st.focus_topic == "AI 芯片出口管制"
        assert st.focus_level == 1.0
        st.set_focus("某话题", -0.5)
        assert st.to_focus_dict() == {"topic": "某话题", "level": 0.0}

    def test_to_dict_excludes_focus(self):
        """to_dict 只承载四标量（审计面契约），focus 单独经 to_focus_dict 提供。"""
        st = MotivationState()
        st.set_focus("某话题", 0.8)
        assert "focus" not in st.to_dict()

    def test_save_load_roundtrip_keeps_focus(self, tmp_path):
        st = MotivationState(focus_topic="量子计算", focus_level=0.66)
        st.save(store_path=str(tmp_path))
        loaded = MotivationState.load(store_path=str(tmp_path))
        assert loaded.to_focus_dict() == {"topic": "量子计算", "level": 0.66}

    def test_load_legacy_file_without_focus(self, tmp_path):
        """旧版 motivation_state.json（无 focus 键）按空焦点恢复，不抛错（向后兼容）。"""
        (tmp_path / "motivation_state.json").write_text(
            json.dumps({"curiosity": 0.5, "social_need": 0.4}), encoding="utf-8"
        )
        loaded = MotivationState.load(store_path=str(tmp_path))
        assert loaded.curiosity == 0.5
        assert loaded.to_focus_dict() == {"topic": "", "level": 0.0}
