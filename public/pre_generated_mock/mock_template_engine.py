"""TemplateEngine 预生成 Mock 实现（CX-O 迁移版）。

对应接口契约: public/interface_stub/template_engine.pyi
对应数据契约: 无独立 schema 文件，字段定义以实现 c:/CX-O/CX-O-SERVER/server/core/template_engine/template_engine.py 为准（待 s0201 重建）
对应配置契约: public/config_template/radix_config.json

Mock 策略:
- 返回符合 schema 的固定样例数据
- 内存态维护模板注册表（预置 preset-default + custom-test 两个样例）
- 异常路径通过 raise 模拟（KeyError=404 / ValueError=422 / PermissionError=403）
- 真实实现就位后，切换导入路径即可替换

@version 1.1.0
@see public/interface_stub/template_engine.pyi
@see 实现: c:/CX-O/CX-O-SERVER/server/core/template_engine/template_engine.py

CX-O 迁移版，基于 CXHMS v1.2.0 Mock 适配。
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel


# --------------------------------------------------------------------------- #
# 路径锚点（rules-0 §三：os.path.dirname(os.path.abspath(__file__))）
# --------------------------------------------------------------------------- #
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def _iso_now() -> str:
    """返回 ISO 8601 带时区时间戳。"""
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Pydantic 模型（与 .pyi 存根保持一致，Mock 自包含）
# --------------------------------------------------------------------------- #


class TemplateFrontmatter(BaseModel):
    """YAML frontmatter 解析结果。"""
    workflow_mode: str  # enum: single_turn / multi_turn
    expected_turns: int  # 1-6
    required_vars: List[str] = []
    optional_vars: List[str] = []
    extends: Optional[str] = None
    description: Optional[str] = None


class TemplateRecord(BaseModel):
    """模板记录。字段定义以实现为准（c:/CX-O/CX-O-SERVER/server/core/template_engine/template_engine.py）。"""
    template_id: str
    name: str
    category: str  # enum: preset / custom
    frontmatter: TemplateFrontmatter
    body: str
    file_path: Optional[str]
    created_at: str
    updated_at: str
    is_deleted: bool = False


class RenderResult(BaseModel):
    """渲染结果。"""
    rendered_prompt: str
    workflow_definition: Dict[str, Any]
    expected_turns: int


class CreateTemplateRequest(BaseModel):
    """创建模板请求。"""
    template_id: str
    name: str
    frontmatter: TemplateFrontmatter
    body: str


class UpdateTemplateRequest(BaseModel):
    """更新模板请求。"""
    name: Optional[str] = None
    frontmatter: Optional[TemplateFrontmatter] = None
    body: Optional[str] = None


# --------------------------------------------------------------------------- #
# 枚举常量（与实现 template_engine.py 保持一致）
# --------------------------------------------------------------------------- #

_CATEGORIES = {"preset", "custom"}
_WORKFLOW_MODES = {"single_turn", "multi_turn"}


def _make_preset_default() -> TemplateRecord:
    """构造 preset-default 模板样例。"""
    now = _iso_now()
    return TemplateRecord(
        template_id="preset-default",
        name="RADIX 默认蒸馏模板",
        category="preset",
        frontmatter=TemplateFrontmatter(
            workflow_mode="multi_turn",
            expected_turns=4,
            required_vars=["source_type", "source_ref"],
            optional_vars=["template_id"],
            extends=None,
            description="RADIX-Lite 默认多轮蒸馏模板",
        ),
        body=(
            "{# RADIX 默认蒸馏模板 #}\n"
            "你是一个记忆蒸馏 agent。请基于以下数据源进行多轮蒸馏：\n"
            "数据源类型：{{ source_type }}\n"
            "数据源引用：{{ source_ref }}\n"
            "{% if template_id %}使用模板：{{ template_id }}{% endif %}\n"
        ),
        file_path="data/templates/presets/preset-default.j2",
        created_at=now,
        updated_at=now,
        is_deleted=False,
    )


def _make_custom_test() -> TemplateRecord:
    """构造 custom-test 模板样例。"""
    now = _iso_now()
    return TemplateRecord(
        template_id="custom-test",
        name="测试用自定义模板",
        category="custom",
        frontmatter=TemplateFrontmatter(
            workflow_mode="single_turn",
            expected_turns=1,
            required_vars=["topic"],
            optional_vars=[],
            extends=None,
            description="单轮渲染测试模板",
        ),
        body=(
            "{# 自定义测试模板 #}\n"
            "请总结以下主题的关键信息：{{ topic }}\n"
        ),
        file_path="data/templates/custom/custom-test.j2",
        created_at=now,
        updated_at=now,
        is_deleted=False,
    )


class MockTemplateEngine:
    """TemplateEngine 的 Mock 实现。

    内存态维护模板注册表，YAML frontmatter + 简化 Jinja2 渲染。
    返回值以实现（c:/CX-O/CX-O-SERVER/server/core/template_engine/template_engine.py）的 TemplateRecord 定义为准。
    """

    def __init__(self) -> None:
        self._store: Dict[str, TemplateRecord] = {}
        self._seed()

    def _seed(self) -> None:
        """预置 preset-default 与 custom-test 模板。"""
        for record in (_make_preset_default(), _make_custom_test()):
            self._store[record.template_id] = record

    # ------------------------------------------------------------------ #
    # 公开 API
    # ------------------------------------------------------------------ #

    def render_template(
        self,
        template_id: str,
        variables: Dict[str, Any],
        workflow_mode: Optional[str] = None,
    ) -> RenderResult:
        """渲染 Jinja2 模板。

        Mock behavior: 简化变量替换（{{ var }}），返回渲染结果。
        缺少 required_vars 时 raise ValueError。
        """
        record = self._store.get(template_id)
        if record is None or record.is_deleted:
            raise KeyError(f"template_id 不存在（404）: {template_id}")

        fm = record.frontmatter
        # 校验必需变量
        missing = [v for v in fm.required_vars if v not in variables]
        if missing:
            raise ValueError(
                f"缺少 required_vars（422）: {missing}"
            )

        # 校验 workflow_mode 覆盖
        effective_mode = workflow_mode or fm.workflow_mode
        if effective_mode not in _WORKFLOW_MODES:
            raise ValueError(
                f"workflow_mode 无效（422）: {effective_mode}"
            )

        # 简化 Jinja2 渲染：仅替换 {{ var }}，忽略 block/for/if 等控制流
        rendered = record.body
        for key, value in variables.items():
            rendered = rendered.replace("{{ " + key + " }}", str(value))
            rendered = rendered.replace("{{" + key + "}}", str(value))

        # 简化处理：剥离 {% ... %} 控制行
        lines = []
        for line in rendered.splitlines():
            stripped = line.strip()
            if stripped.startswith("{%") and stripped.endswith("%}"):
                continue
            lines.append(line)
        rendered = "\n".join(lines)

        return RenderResult(
            rendered_prompt=rendered,
            workflow_definition={
                "workflow_mode": effective_mode,
                "expected_turns": fm.expected_turns,
            },
            expected_turns=fm.expected_turns,
        )

    def list_templates(
        self,
        category: Optional[str] = None,
    ) -> List[TemplateRecord]:
        """列出模板。

        Mock behavior: 返回未软删的模板，按 category 过滤。
        """
        if category is not None and category not in _CATEGORIES:
            raise ValueError(f"category 无效（422）: {category}")

        results: List[TemplateRecord] = []
        for record in self._store.values():
            if record.is_deleted:
                continue
            if category is not None and record.category != category:
                continue
            results.append(record)
        # 按 template_id 升序（rules-0 §三 sorting.order: ascending）
        results.sort(key=lambda r: r.template_id)
        return results

    def get_template(self, template_id: str) -> TemplateRecord:
        """获取单个模板。

        Mock behavior: 返回模板记录，不存在 raise KeyError。
        """
        record = self._store.get(template_id)
        if record is None or record.is_deleted:
            raise KeyError(f"template_id 不存在（404）: {template_id}")
        return record

    def create_template(self, request: CreateTemplateRequest) -> TemplateRecord:
        """创建自定义模板。

        Mock behavior: 仅创建 custom 模板，template_id 已存在 raise FileExistsError。
        """
        if request.template_id in self._store:
            raise FileExistsError(
                f"template_id 已存在（409）: {request.template_id}"
            )
        if not request.template_id:
            raise ValueError("template_id 不能为空（422）")
        if request.frontmatter.workflow_mode not in _WORKFLOW_MODES:
            raise ValueError(
                f"workflow_mode 无效（422）: {request.frontmatter.workflow_mode}"
            )
        if not (1 <= request.frontmatter.expected_turns <= 6):
            raise ValueError(
                f"expected_turns 超出范围 1-6（422）: "
                f"{request.frontmatter.expected_turns}"
            )

        now = _iso_now()
        record = TemplateRecord(
            template_id=request.template_id,
            name=request.name,
            category="custom",
            frontmatter=request.frontmatter,
            body=request.body,
            file_path=f"data/templates/custom/{request.template_id}.j2",
            created_at=now,
            updated_at=now,
            is_deleted=False,
        )
        self._store[request.template_id] = record
        return record

    def update_template(
        self,
        template_id: str,
        request: UpdateTemplateRequest,
    ) -> TemplateRecord:
        """更新自定义模板。

        Mock behavior: 更新 name/frontmatter/body，preset 模板 raise PermissionError。
        """
        record = self._store.get(template_id)
        if record is None or record.is_deleted:
            raise KeyError(f"template_id 不存在（404）: {template_id}")
        if record.category == "preset":
            raise PermissionError(
                f"preset 模板不可更新（403）: {template_id}"
            )

        if request.name is not None:
            record.name = request.name
        if request.frontmatter is not None:
            if request.frontmatter.workflow_mode not in _WORKFLOW_MODES:
                raise ValueError(
                    f"workflow_mode 无效（422）: "
                    f"{request.frontmatter.workflow_mode}"
                )
            if not (1 <= request.frontmatter.expected_turns <= 6):
                raise ValueError(
                    f"expected_turns 超出范围 1-6（422）"
                )
            record.frontmatter = request.frontmatter
        if request.body is not None:
            record.body = request.body

        record.updated_at = _iso_now()
        return record

    def delete_template(self, template_id: str) -> bool:
        """删除自定义模板。

        Mock behavior: 软删除 custom 模板，preset 模板 raise PermissionError。
        返回 bool（与 .pyi 签名一致）。
        """
        record = self._store.get(template_id)
        if record is None or record.is_deleted:
            raise KeyError(f"template_id 不存在（404）: {template_id}")
        if record.category == "preset":
            raise PermissionError(
                f"preset 模板不可删除（403）: {template_id}"
            )

        record.is_deleted = True
        record.updated_at = _iso_now()
        return True

    # ------------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------------ #

    def _parse_frontmatter(self, content: str) -> Tuple[TemplateFrontmatter, str]:
        """内部方法：解析 YAML frontmatter。

        Mock behavior: 简化解析——识别 ``---`` 包裹的 frontmatter 块，
        提取 workflow_mode/expected_turns/required_vars/optional_vars 等字段。
        非法格式 raise ValueError。
        """
        if not content:
            raise ValueError("content 不能为空（422）")

        lines = content.splitlines()
        if not lines or lines[0].strip() != "---":
            raise ValueError(
                "frontmatter 缺少起始 --- 分隔符（422）"
            )

        # 找结束 ---
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break
        if end_idx is None:
            raise ValueError(
                "frontmatter 缺少结束 --- 分隔符（422）"
            )

        fm_lines = lines[1:end_idx]
        body = "\n".join(lines[end_idx + 1:])

        # 简化 YAML 解析：key: value 形式
        raw: Dict[str, Any] = {}
        for line in fm_lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                raise ValueError(f"frontmatter 行格式错误（422）: {line}")
            key, _, value = line.partition(":")
            raw[key.strip()] = value.strip()

        if "workflow_mode" not in raw:
            raise ValueError("frontmatter 缺少必需字段 workflow_mode（422）")
        if "expected_turns" not in raw:
            raise ValueError("frontmatter 缺少必需字段 expected_turns（422）")

        workflow_mode = raw["workflow_mode"]
        if workflow_mode not in _WORKFLOW_MODES:
            raise ValueError(
                f"workflow_mode 无效（422）: {workflow_mode}"
            )

        try:
            expected_turns = int(raw["expected_turns"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"expected_turns 不是整数（422）: {raw['expected_turns']}"
            ) from exc
        if not (1 <= expected_turns <= 6):
            raise ValueError(
                f"expected_turns 超出范围 1-6（422）: {expected_turns}"
            )

        def _parse_list(key: str) -> List[str]:
            v = raw.get(key)
            if not v:
                return []
            # 简化：按逗号分割并 strip
            return [item.strip() for item in v.split(",") if item.strip()]

        frontmatter = TemplateFrontmatter(
            workflow_mode=workflow_mode,
            expected_turns=expected_turns,
            required_vars=_parse_list("required_vars"),
            optional_vars=_parse_list("optional_vars"),
            extends=raw.get("extends") or None,
            description=raw.get("description") or None,
        )
        return frontmatter, body
