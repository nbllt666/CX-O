"""server.core.template_engine (TemplateEngine) 单元测试。

覆盖 frontmatter 解析、渲染、模板 CRUD、预设模板、自定义 filter 与错误映射。
运行：python -m pytest tests/test_template_engine.py -v
"""
import os

import pytest
from jinja2 import TemplateNotFound, TemplateSyntaxError

from server.core.template_engine.template_engine import (
    CreateTemplateRequest,
    TemplateEngine,
    TemplateFrontmatter,
    UpdateTemplateRequest,
)


@pytest.fixture
def engine(tmp_path):
    return TemplateEngine(templates_dir=str(tmp_path))


@pytest.fixture
def custom_fm():
    return TemplateFrontmatter(
        workflow_mode="single_turn",
        expected_turns=1,
        required_vars=["content"],
        optional_vars=["context"],
        description="测试模板",
    )


class TestParseFrontmatter:
    def test_valid(self, engine):
        content = "---\nworkflow_mode: single_turn\nexpected_turns: 2\n---\nbody"
        fm, body = engine._parse_frontmatter(content)
        assert fm.workflow_mode == "single_turn"
        assert fm.expected_turns == 2
        assert body == "body"

    def test_empty_content(self, engine):
        with pytest.raises(ValueError):
            engine._parse_frontmatter("")

    def test_missing_fence(self, engine):
        with pytest.raises(ValueError):
            engine._parse_frontmatter("no fence here")

    def test_missing_workflow_mode(self, engine):
        with pytest.raises(ValueError):
            engine._parse_frontmatter("---\nexpected_turns: 1\n---\nbody")

    def test_missing_expected_turns(self, engine):
        with pytest.raises(ValueError):
            engine._parse_frontmatter("---\nworkflow_mode: single_turn\n---\nbody")

    def test_invalid_workflow_mode(self, engine):
        with pytest.raises(ValueError):
            engine._parse_frontmatter(
                "---\nworkflow_mode: crazy\nexpected_turns: 1\n---\nbody"
            )

    def test_non_int_turns(self, engine):
        with pytest.raises(ValueError):
            engine._parse_frontmatter(
                "---\nworkflow_mode: single_turn\nexpected_turns: abc\n---\nbody"
            )

    def test_turns_out_of_range(self, engine):
        with pytest.raises(ValueError):
            engine._parse_frontmatter(
                "---\nworkflow_mode: single_turn\nexpected_turns: 9\n---\nbody"
            )

    def test_none_dict(self, engine):
        with pytest.raises(ValueError):
            engine._parse_frontmatter("---\nnull\n---\nbody")

    def test_extends_empty_normalized(self, engine):
        content = (
            "---\nworkflow_mode: single_turn\nexpected_turns: 1\nextends: ''\n---\nbody"
        )
        fm, _ = engine._parse_frontmatter(content)
        assert fm.extends is None

    def test_required_vars_not_list(self, engine):
        with pytest.raises(ValueError):
            engine._parse_frontmatter(
                "---\nworkflow_mode: single_turn\nexpected_turns: 1\nrequired_vars: x\n---\nbody"
            )


class TestConfidenceLabel:
    def test_low(self, engine):
        assert engine._confidence_label(0.2) == "低"

    def test_mid(self, engine):
        assert engine._confidence_label(0.5) == "中"

    def test_high(self, engine):
        assert engine._confidence_label(0.9) == "高"

    def test_boundary_low(self, engine):
        assert engine._confidence_label(0.4) == "中"

    def test_boundary_mid(self, engine):
        assert engine._confidence_label(0.7) == "高"

    def test_missing(self, engine):
        assert engine._confidence_label("abc") == "未知"


class TestRender:
    def test_render_preset_default(self, engine):
        out = engine.render_template("default", {"content": "hello"})
        assert "hello" in out.rendered_prompt
        assert out.expected_turns == 1
        assert out.workflow_definition["workflow_mode"] == "single_turn"

    def test_render_missing_required(self, engine):
        with pytest.raises(ValueError):
            engine.render_template("default", {})

    def test_render_invalid_mode_override(self, engine):
        with pytest.raises(ValueError):
            engine.render_template("default", {"content": "x"}, workflow_mode="bad")

    def test_render_not_found(self, engine):
        with pytest.raises(KeyError):
            engine.render_template("nonexistent", {"content": "x"})

    def test_render_custom_filter(self, engine):
        out = engine.render_template(
            "distillation",
            {
                "source_type": "doc",
                "source_ref": "ref",
                "confidence": 0.9,
            },
        )
        assert "高" in out.rendered_prompt

    def test_render_loop(self, engine):
        engine.create_template(
            CreateTemplateRequest(
                template_id="looper",
                name="loop",
                frontmatter=TemplateFrontmatter(
                    workflow_mode="single_turn", expected_turns=1, required_vars=[]
                ),
                body="{% for t in items %}[{{ t }}]{% endfor %}",
            )
        )
        out = engine.render_template("looper", {"items": ["a", "b"]})
        assert out.rendered_prompt == "[a][b]"


class TestListTemplates:
    def test_empty(self, engine):
        # auto_init 仅生成预设模板，custom 应为空
        assert engine.list_templates(category="custom") == []

    def test_after_create(self, engine, custom_fm):
        engine.create_template(
            CreateTemplateRequest(template_id="t1", name="T1", frontmatter=custom_fm, body="body")
        )
        ids = [t.template_id for t in engine.list_templates()]
        assert "t1" in ids

    def test_category_filter(self, engine, custom_fm):
        engine.create_template(
            CreateTemplateRequest(template_id="c1", name="C1", frontmatter=custom_fm, body="body")
        )
        custom = engine.list_templates(category="custom")
        preset = engine.list_templates(category="preset")
        assert any(t.template_id == "c1" for t in custom)
        assert all(t.category == "preset" for t in preset)

    def test_invalid_category(self, engine):
        with pytest.raises(ValueError):
            engine.list_templates(category="bad")

    def test_sorted_by_id(self, engine, custom_fm):
        for tid in ["zeta", "alpha"]:
            engine.create_template(
                CreateTemplateRequest(template_id=tid, name=tid, frontmatter=custom_fm, body="body")
            )
        ids = [t.template_id for t in engine.list_templates(category="custom")]
        assert ids == sorted(ids)


class TestGetTemplate:
    def test_get_preset(self, engine):
        rec = engine.get_template("default")
        assert rec.category == "preset"

    def test_not_found(self, engine):
        with pytest.raises(KeyError):
            engine.get_template("nope")

    def test_invalid_id(self, engine):
        with pytest.raises(KeyError):
            engine.get_template("bad id/../x")

    def test_custom_overrides_preset(self, engine, tmp_path):
        # 直接写入 custom 同名文件，验证 get_template 优先 custom 目录
        custom_path = os.path.join(tmp_path, "custom", "default.j2")
        with open(custom_path, "w", encoding="utf-8") as f:
            f.write("---\nworkflow_mode: single_turn\nexpected_turns: 1\n---\ncustom body")
        rec = engine.get_template("default")
        assert rec.category == "custom"
        assert rec.body == "custom body"


class TestCreateTemplate:
    def test_create_file(self, engine):
        # description 为 None 时，name 通过 description 持久化
        fm = TemplateFrontmatter(
            workflow_mode="single_turn", expected_turns=1, required_vars=["content"]
        )
        rec = engine.create_template(
            CreateTemplateRequest(template_id="t1", name="T1", frontmatter=fm, body="body")
        )
        assert os.path.isfile(rec.file_path)
        loaded = engine.get_template("t1")
        assert loaded.name == "T1"

    def test_create_duplicate_preset(self, engine, custom_fm):
        with pytest.raises(FileExistsError):
            engine.create_template(
                CreateTemplateRequest(template_id="default", name="x", frontmatter=custom_fm, body="body")
            )

    def test_create_duplicate_custom(self, engine, custom_fm):
        engine.create_template(CreateTemplateRequest(template_id="t1", name="T1", frontmatter=custom_fm, body="b"))
        with pytest.raises(FileExistsError):
            engine.create_template(CreateTemplateRequest(template_id="t1", name="T2", frontmatter=custom_fm, body="b2"))

    def test_create_invalid_id(self, engine, custom_fm):
        with pytest.raises(ValueError):
            engine.create_template(
                CreateTemplateRequest(template_id="bad id", name="x", frontmatter=custom_fm, body="b")
            )

    def test_create_invalid_frontmatter(self, engine):
        bad = TemplateFrontmatter(
            workflow_mode="bad", expected_turns=1, required_vars=[]
        )
        with pytest.raises(ValueError):
            engine.create_template(
                CreateTemplateRequest(template_id="t1", name="x", frontmatter=bad, body="b")
            )


class TestUpdateTemplate:
    def test_update_body(self, engine, custom_fm):
        engine.create_template(CreateTemplateRequest(template_id="t1", name="T1", frontmatter=custom_fm, body="old"))
        updated = engine.update_template(
            "t1", UpdateTemplateRequest(body="new body")
        )
        assert updated.body == "new body"

    def test_update_preset_forbidden(self, engine):
        with pytest.raises(PermissionError):
            engine.update_template("default", UpdateTemplateRequest(body="x"))

    def test_update_not_found(self, engine):
        with pytest.raises(KeyError):
            engine.update_template("nope", UpdateTemplateRequest(body="x"))

    def test_update_persists(self, engine, custom_fm):
        engine.create_template(CreateTemplateRequest(template_id="t1", name="T1", frontmatter=custom_fm, body="old"))
        engine.update_template("t1", UpdateTemplateRequest(body="persisted"))
        assert engine.get_template("t1").body == "persisted"


class TestDeleteTemplate:
    def test_delete_custom(self, engine, custom_fm):
        engine.create_template(CreateTemplateRequest(template_id="t1", name="T1", frontmatter=custom_fm, body="b"))
        assert engine.delete_template("t1") is True
        with pytest.raises(KeyError):
            engine.get_template("t1")

    def test_delete_preset_forbidden(self, engine):
        with pytest.raises(PermissionError):
            engine.delete_template("default")

    def test_delete_not_found(self, engine):
        with pytest.raises(KeyError):
            engine.delete_template("nope")


class TestScanDir:
    def test_skips_invalid_names(self, engine, tmp_path):
        with open(os.path.join(tmp_path, "custom", "bad name.j2"), "w") as f:
            f.write("---\nworkflow_mode: single_turn\nexpected_turns: 1\n---\nb")
        with open(os.path.join(tmp_path, "custom", "readme.txt"), "w") as f:
            f.write("ignore")
        recs = engine.list_templates(category="custom")
        assert all(t.template_id != "bad name" for t in recs)
        assert all(t.template_id != "readme" for t in recs)

    def test_skips_broken_template(self, engine, tmp_path):
        with open(os.path.join(tmp_path, "custom", "broken.j2"), "w") as f:
            f.write("not-a-template")
        recs = engine.list_templates(category="custom")
        assert all(t.template_id != "broken" for t in recs)