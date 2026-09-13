"""preset_service 单元测试（Task 3 / SubTask 3.1）。

用 tmp_path 重定向预设根目录，隔离真实 data/。覆盖：
- 情感/动作预设 CRUD 全闭环（含 name 升序、覆盖语义 created_at 保留）
- agent_id 注入防护（../ 路径穿越、非法字符、超长、空串）
- 字段校验拒绝用例（name/text/tags/description/speed/volume）
- speed/volume 数值收敛（越界 clamp、非数值/NaN 拒绝）
- 并发写安全（多线程并发 save 后 JSON 可解析且全量落盘）
- 读缓存失效（外部直接改文件后能读到新值）

运行：python -m pytest tests/test_preset_service.py -x -q
"""
import json
import threading

import pytest

from server.services import preset_service as ps


@pytest.fixture
def presets_root(monkeypatch, tmp_path):
    """重定向预设根目录到 tmp_path，并清空模块级缓存，隔离测试。"""
    root = tmp_path / "presets"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ps, "_PRESETS_ROOT", root)
    monkeypatch.setattr(ps, "_CACHE", {})
    return root


# --------------------------------------------------------------------------- #
# 情感预设 CRUD
# --------------------------------------------------------------------------- #
class TestEmotionPresetCRUD:
    def test_save_returns_full_preset_with_defaults(self, presets_root):
        p = ps.save_emotion_preset("agentA", "元气满满", "元气活泼、开朗")
        assert p["name"] == "元气满满"
        assert p["text"] == "元气活泼、开朗"
        assert p["speed"] == 1.0  # 缺省值
        assert p["volume"] == 1.0
        assert p["description"] == ""
        assert p["created_at"] and p["updated_at"]

    def test_get_and_list(self, presets_root):
        ps.save_emotion_preset("agentA", "b", "t2")
        ps.save_emotion_preset("agentA", "a", "t1")
        got = ps.get_emotion_preset("agentA", "a")
        assert got["text"] == "t1"
        names = [p["name"] for p in ps.list_emotion_presets("agentA")]
        assert names == ["a", "b"]  # 升序

    def test_get_missing_returns_none(self, presets_root):
        assert ps.get_emotion_preset("agentA", "不存在") is None

    def test_overwrite_is_atomic_and_preserves_created_at(self, presets_root):
        first = ps.save_emotion_preset("agentA", "同名", "v1")
        second = ps.save_emotion_preset("agentA", "同名", "v2", speed=1.5)
        assert second["created_at"] == first["created_at"]
        assert second["updated_at"] >= first["updated_at"]
        assert second["speed"] == 1.5
        items = ps.list_emotion_presets("agentA")
        assert len(items) == 1  # 覆盖而非新增
        assert items[0]["text"] == "v2"

    def test_delete_true_then_false(self, presets_root):
        ps.save_emotion_preset("agentA", "待删", "t")
        assert ps.delete_emotion_preset("agentA", "待删") is True
        assert ps.get_emotion_preset("agentA", "待删") is None
        assert ps.delete_emotion_preset("agentA", "待删") is False  # 二次删除 False

    def test_file_layout(self, presets_root):
        ps.save_emotion_preset("agentA", "x", "t")
        f = presets_root / "agentA" / "emotion_presets.json"
        assert f.exists()
        raw = json.loads(f.read_text(encoding="utf-8"))
        assert raw["version"] == 1
        assert "x" in raw["presets"]


# --------------------------------------------------------------------------- #
# 动作预设 CRUD
# --------------------------------------------------------------------------- #
class TestActionPresetCRUD:
    def test_save_get_list_overwrite_delete(self, presets_root):
        ps.save_action_preset("agentA", "打招呼", ["[emotion:happy]", "[action:wave]"], "开心挥手")
        got = ps.get_action_preset("agentA", "打招呼")
        assert got["tags"] == ["[emotion:happy]", "[action:wave]"]
        assert got["description"] == "开心挥手"

        first = ps.save_action_preset("agentA", "打招呼", ["[action:nod]"])
        second = ps.save_action_preset("agentA", "打招呼", ["[action:nod]", "[emotion:happy]"])
        assert second["created_at"] == first["created_at"]
        assert len(ps.list_action_presets("agentA")) == 1

        assert ps.delete_action_preset("agentA", "打招呼") is True
        assert ps.delete_action_preset("agentA", "打招呼") is False

    def test_list_sorted_ascending(self, presets_root):
        ps.save_action_preset("agentA", "z", ["[action:nod]"])
        ps.save_action_preset("agentA", "a", ["[action:nod]"])
        assert [p["name"] for p in ps.list_action_presets("agentA")] == ["a", "z"]


# --------------------------------------------------------------------------- #
# agent_id 注入防护
# --------------------------------------------------------------------------- #
class TestAgentIdGuard:
    @pytest.mark.parametrize(
        "bad",
        [
            "../evil",           # 路径穿越
            "..\\evil",          # Windows 反斜杠穿越
            "a/b",               # 路径分隔符
            "",                  # 空串
            ".",                 # 当前目录
            "a" * 65,            # 超长
            "中文名",             # 非法字符（非 ASCII）
            "bad id",            # 空格
        ],
    )
    def test_invalid_agent_id_rejected_everywhere(self, presets_root, bad):
        with pytest.raises(ValueError):
            ps.save_emotion_preset(bad, "n", "t")
        with pytest.raises(ValueError):
            ps.save_action_preset(bad, "n", ["[action:nod]"])
        with pytest.raises(ValueError):
            ps.list_emotion_presets(bad)
        with pytest.raises(ValueError):
            ps.get_action_preset(bad, "n")
        with pytest.raises(ValueError):
            ps.delete_emotion_preset(bad, "n")
        with pytest.raises(ValueError):
            ps.list_all_presets(bad)
        # 防穿越：目录未被创建到根外
        assert not (presets_root.parent / "evil").exists()

    def test_valid_agent_ids_accepted(self, presets_root):
        for ok in ("default", "Agent_1", "a-b_C9", "x" * 64):
            ps.save_emotion_preset(ok, "n", "t")
            assert ps.get_emotion_preset(ok, "n") is not None


# --------------------------------------------------------------------------- #
# 字段校验
# --------------------------------------------------------------------------- #
class TestValidation:
    def test_name_rejected(self, presets_root):
        for bad in ("", "   ", "x" * 51, None):
            with pytest.raises(ValueError):
                ps.save_emotion_preset("agentA", bad, "t")

    def test_text_rejected(self, presets_root):
        for bad in ("", "   ", "t" * 201, None):
            with pytest.raises(ValueError):
                ps.save_emotion_preset("agentA", "n", bad)

    def test_description_rejected(self, presets_root):
        with pytest.raises(ValueError):
            ps.save_emotion_preset("agentA", "n", "t", description="d" * 201)
        with pytest.raises(ValueError):
            ps.save_action_preset("agentA", "n", ["[action:nod]"], description=123)

    def test_tags_rejected(self, presets_root):
        for bad in (
            None,                # 非数组
            "not-a-list",        # 字符串
            [],                  # 空数组
            [""],                # 空项
            ["emotion:happy"],   # 缺方括号
            ["[emotion:happy"],  # 左括号缺失闭合
            ["x" * 201],         # 超长项
            ["[action:wave]", 123],  # 非字符串项
        ):
            with pytest.raises(ValueError):
                ps.save_action_preset("agentA", "n", bad)

    def test_speed_volume_numeric_string_coerced(self, presets_root):
        p = ps.save_emotion_preset("agentA", "n", "t", speed="1.5", volume="0.8")
        assert p["speed"] == 1.5
        assert p["volume"] == 0.8


# --------------------------------------------------------------------------- #
# 数值收敛
# --------------------------------------------------------------------------- #
class TestNumberClamp:
    def test_speed_clamped(self, presets_root):
        assert ps.save_emotion_preset("agentA", "hi", "t", speed=9)["speed"] == ps.SPEED_MAX
        assert ps.save_emotion_preset("agentA", "lo", "t", speed=0.01)["speed"] == ps.SPEED_MIN

    def test_volume_clamped(self, presets_root):
        assert ps.save_emotion_preset("agentA", "hi", "t", volume=5)["volume"] == ps.VOLUME_MAX
        assert ps.save_emotion_preset("agentA", "lo", "t", volume=0.001)["volume"] == ps.VOLUME_MIN

    def test_non_numeric_rejected(self, presets_root):
        with pytest.raises(ValueError):
            ps.save_emotion_preset("agentA", "n", "t", speed="快一点")
        with pytest.raises(ValueError):
            ps.save_emotion_preset("agentA", "n", "t", volume=float("nan"))
        with pytest.raises(ValueError):
            ps.save_emotion_preset("agentA", "n", "t", speed=float("inf"))


# --------------------------------------------------------------------------- #
# 并发写安全
# --------------------------------------------------------------------------- #
class TestConcurrentWrites:
    def test_concurrent_distinct_names_all_persisted(self, presets_root):
        """多线程并发保存不同 name：JSON 不损坏且全量落盘。"""
        barrier = threading.Barrier(8)
        errors = []

        def worker(i: int):
            try:
                barrier.wait()  # 最大化并发竞争
                for j in range(5):
                    ps.save_emotion_preset("agentA", f"p{i}_{j}", f"t{i}_{j}")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        f = presets_root / "agentA" / "emotion_presets.json"
        raw = json.loads(f.read_text(encoding="utf-8"))  # 可解析 = 未写坏
        assert len(raw["presets"]) == 40  # 8 线程 × 5 个全部在盘
        assert len(ps.list_emotion_presets("agentA")) == 40

    def test_concurrent_same_name_file_never_corrupt(self, presets_root):
        """多线程并发覆盖同名预设：文件始终可解析且只有一份。"""
        barrier = threading.Barrier(10)
        errors = []

        def worker(i: int):
            try:
                barrier.wait()
                ps.save_emotion_preset("agentA", "同名", f"v{i}")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        raw = json.loads(
            (presets_root / "agentA" / "emotion_presets.json").read_text(encoding="utf-8")
        )
        assert list(raw["presets"].keys()) == ["同名"]


# --------------------------------------------------------------------------- #
# 缓存失效
# --------------------------------------------------------------------------- #
class TestCache:
    def test_cache_invalidate_on_save(self, presets_root):
        ps.save_emotion_preset("agentA", "n", "v1")
        ps.save_emotion_preset("agentA", "n", "v2")  # 保存后缓存必须失效
        assert ps.get_emotion_preset("agentA", "n")["text"] == "v2"

    def test_external_edit_detected_via_mtime(self, presets_root):
        """外部直接改文件（绕过服务）：mtime 失效机制能读到新值。"""
        ps.save_emotion_preset("agentA", "n", "v1")
        f = presets_root / "agentA" / "emotion_presets.json"
        external = {"version": 1, "presets": {"n": {"name": "n", "text": "外部修改"}}}
        f.write_text(json.dumps(external, ensure_ascii=False), encoding="utf-8")
        assert ps.get_emotion_preset("agentA", "n")["text"] == "外部修改"

    def test_corrupt_file_returns_empty(self, presets_root):
        """文件损坏（非法 JSON）时不抛异常，返回空集。"""
        d = presets_root / "agentA"
        d.mkdir(parents=True, exist_ok=True)
        (d / "emotion_presets.json").write_text("{broken json", encoding="utf-8")
        assert ps.list_emotion_presets("agentA") == []


# --------------------------------------------------------------------------- #
# 聚合查询
# --------------------------------------------------------------------------- #
class TestListAll:
    def test_list_all_presets(self, presets_root):
        ps.save_emotion_preset("agentA", "e1", "t")
        ps.save_action_preset("agentA", "a1", ["[action:nod]"])
        both = ps.list_all_presets("agentA")
        assert [p["name"] for p in both[ps.KIND_EMOTION]] == ["e1"]
        assert [p["name"] for p in both[ps.KIND_ACTION]] == ["a1"]
