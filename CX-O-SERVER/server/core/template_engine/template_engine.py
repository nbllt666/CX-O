"""TemplateEngine 真实实现。

对应契约:
- 接口契约: public/interface_stub/template_engine.pyi
- 数据契约: public/schema/template_registry.schema.json
- 配置契约: public/config_template/radix_config.json (template_engine 段)

实现策略:
- YAML frontmatter + Jinja2 原生渲染（extends/block/if/elif/else/for/include/filter）
- FileSystemLoader(ChoiceLoader) 加载 presets/ + custom/ 双目录
- autoescape=False（模板是 prompt，不是 HTML）
- trim_blocks=True / lstrip_blocks=True（减少空白）
- 自定义 filter: confidence_label（0-1 → 低/中/高）
- 模板仓库 data/templates/ 分 presets/ 和 custom/ 目录
- auto_init: 目录不存在时自动创建 + 创建默认预设模板

@version 1.0.0
@see public/interface_stub/template_engine.pyi
@see public/schema/template_registry.schema.json
"""

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import yaml
from jinja2 import (
    ChoiceLoader,
    Environment,
    FileSystemLoader,
    TemplateError,
    TemplateNotFound,
    TemplateSyntaxError,
)
from pydantic import BaseModel


# --------------------------------------------------------------------------- #
# 路径锚点（rules-0 §三：os.path.dirname(os.path.abspath(__file__))）
# --------------------------------------------------------------------------- #
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SERVER_CORE = os.path.dirname(_THIS_DIR)  # server/core
_SERVER_ROOT = os.path.dirname(_SERVER_CORE)  # server
_PROJECT_ROOT = os.path.dirname(_SERVER_ROOT)  # CX-O-SERVER root

_DEFAULT_TEMPLATES_DIR = os.path.join(_PROJECT_ROOT, "data", "templates")
_DEFAULT_PRESETS_DIR = os.path.join(_DEFAULT_TEMPLATES_DIR, "presets")
_DEFAULT_CUSTOM_DIR = os.path.join(_DEFAULT_TEMPLATES_DIR, "custom")


# --------------------------------------------------------------------------- #
# 枚举常量（与 template_registry.schema.json 一致）
# --------------------------------------------------------------------------- #
_CATEGORIES = {"preset", "custom"}
_WORKFLOW_MODES = {"single_turn", "multi_turn"}
_TEMPLATE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# frontmatter 正则（与 spike_jinja2.py 一致：^---\n(.*?)\n---\n(.*)$）
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def _iso_now() -> str:
    """返回 ISO 8601 带时区时间戳。"""
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Pydantic 模型（与 .pyi 存根保持一致）
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
    """模板记录。字段与 template_registry.schema.json 一致。"""

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
# 默认预设模板（auto_init 时写入，仅在文件不存在时创建）
# --------------------------------------------------------------------------- #

_DEFAULT_PRESET_DEFAULT = """---
workflow_mode: single_turn
expected_turns: 1
required_vars:
  - content
optional_vars:
  - context
extends: null
description: RADIX-Lite 默认单轮蒸馏模板
---
You are a distillation agent. Please process the following content:

{{ content }}

{% if context %}
Context: {{ context }}
{% endif %}

Extract key information and structure it appropriately.
"""

_DEFAULT_PRESET_DISTILLATION = """---
workflow_mode: multi_turn
expected_turns: 4
required_vars:
  - source_type
  - source_ref
optional_vars:
  - preread_summary
  - history
  - confidence
extends: null
description: RADIX-Lite 多轮蒸馏模板（支持历史与置信度）
---
{% block system %}
You are a multi-turn distillation agent. Source type: {{ source_type }}.
Source ref: {{ source_ref }}.
{% endblock %}

{% if preread_summary %}
[Preread Summary]
{{ preread_summary }}
{% endif %}

{% if history %}
{% for turn in history %}
[Turn {{ loop.index }}] User: {{ turn.user }}
{% endfor %}
{% endif %}

{% if confidence is defined %}
Confidence: {{ confidence | confidence_label }} ({{ confidence }})
{% if confidence < 0.6 %}
Low confidence, suggest cross_validate.
{% else %}
Ready for extract phase.
{% endif %}
{% endif %}
"""


class TemplateEngine:
    """TemplateEngine 真实实现。

    进程内引擎，使用 YAML frontmatter + Jinja2 原生渲染。
    模板仓库 data/templates/ 分 presets/（只读）和 custom/（可 CRUD）目录。

    Attributes:
        templates_dir: 模板根目录（presets/ 和 custom/ 的父目录）
        presets_dir: 预设模板目录（只读）
        custom_dir: 自定义模板目录（可 CRUD）
    """

    def __init__(
        self,
        templates_dir: Optional[str] = None,
        presets_dir: Optional[str] = None,
        custom_dir: Optional[str] = None,
        autoescape: bool = False,
        trim_blocks: bool = True,
        lstrip_blocks: bool = True,
    ) -> None:
        """初始化 TemplateEngine。

        Args:
            templates_dir: 模板根目录。None=使用默认 data/templates/
            presets_dir: 预设目录。None=templates_dir/presets
            custom_dir: 自定义目录。None=templates_dir/custom
            autoescape: Jinja2 autoescape。默认 False（prompt 不转义）
            trim_blocks: Jinja2 trim_blocks。默认 True
            lstrip_blocks: Jinja2 lstrip_blocks。默认 True
        """
        # rules-0 §三：禁止相对路径，所有路径基于 _PROJECT_ROOT 解析
        if templates_dir is None:
            self.templates_dir = _DEFAULT_TEMPLATES_DIR
        elif os.path.isabs(templates_dir):
            self.templates_dir = templates_dir
        else:
            self.templates_dir = os.path.join(_PROJECT_ROOT, templates_dir)

        if presets_dir is None:
            self.presets_dir = os.path.join(self.templates_dir, "presets")
        elif os.path.isabs(presets_dir):
            self.presets_dir = presets_dir
        else:
            self.presets_dir = os.path.join(_PROJECT_ROOT, presets_dir)

        if custom_dir is None:
            self.custom_dir = os.path.join(self.templates_dir, "custom")
        elif os.path.isabs(custom_dir):
            self.custom_dir = custom_dir
        else:
            self.custom_dir = os.path.join(_PROJECT_ROOT, custom_dir)

        self.autoescape = autoescape
        self.trim_blocks = trim_blocks
        self.lstrip_blocks = lstrip_blocks

        # auto_init: 目录补全（rules-0 §三 auto_init: data补全）
        self._ensure_dirs()
        # auto_init: 默认预设模板补全
        self._ensure_default_presets()

        # 构建 Jinja2 Environment
        # 使用 ChoiceLoader 加载 presets/ 和 custom/ 双目录
        # 这样 extends/include 可以用 "parent.j2" 引用任一目录的模板
        self._env = self._build_environment()

    # ------------------------------------------------------------------ #
    # 初始化辅助
    # ------------------------------------------------------------------ #

    def _ensure_dirs(self) -> None:
        """确保 templates/presets/custom 三个目录存在。"""
        for d in (self.templates_dir, self.presets_dir, self.custom_dir):
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)

    def _ensure_default_presets(self) -> None:
        """确保默认预设模板存在（仅在文件不存在时创建，不覆盖）。"""
        defaults = {
            "default.j2": _DEFAULT_PRESET_DEFAULT,
            "distillation.j2": _DEFAULT_PRESET_DISTILLATION,
        }
        for filename, content in defaults.items():
            path = os.path.join(self.presets_dir, filename)
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

    def _build_environment(self) -> Environment:
        """构建 Jinja2 Environment。

        Returns:
            配置好的 Jinja2 Environment
        """
        loader = ChoiceLoader(
            [
                FileSystemLoader(self.presets_dir),
                FileSystemLoader(self.custom_dir),
            ]
        )
        env = Environment(
            loader=loader,
            autoescape=self.autoescape,
            trim_blocks=self.trim_blocks,
            lstrip_blocks=self.lstrip_blocks,
        )
        # 注册自定义 filter: confidence_label（0-1 → 低/中/高）
        env.filters["confidence_label"] = self._confidence_label
        return env

    @staticmethod
    def _confidence_label(value: Any) -> str:
        """自定义 filter: 将 0-1 的置信度映射为 低/中/高。

        Args:
            value: 置信度数值（0-1）

        Returns:
            "低" / "中" / "高"
        """
        try:
            v = float(value)
        except (TypeError, ValueError):
            return "未知"
        if v < 0.4:
            return "低"
        elif v < 0.7:
            return "中"
        else:
            return "高"

    # ------------------------------------------------------------------ #
    # 公开 API（严格匹配 .pyi 签名）
    # ------------------------------------------------------------------ #

    def render_template(
        self,
        template_id: str,
        variables: Dict[str, Any],
        workflow_mode: Optional[str] = None,
    ) -> RenderResult:
        """渲染 Jinja2 模板。

        解析 YAML frontmatter 获取 meta，Jinja2 渲染 body。

        Args:
            template_id: 模板 ID
            variables: 渲染变量
            workflow_mode: 工作流模式覆盖（None=使用 frontmatter 中的值）

        Returns:
            RenderResult: rendered_prompt + workflow_definition + expected_turns

        Raises:
            KeyError: template_id 不存在（404）
            ValueError: frontmatter 解析失败 / 缺少 required_vars / workflow_mode 无效（422）
            jinja2.TemplateSyntaxError: Jinja2 语法错误（422）
            jinja2.TemplateNotFound: extends 引用的父模板不存在（422）
        """
        # 获取模板记录（不存在 raise KeyError）
        record = self.get_template(template_id)

        fm = record.frontmatter

        # 校验 workflow_mode 覆盖
        effective_mode = workflow_mode if workflow_mode is not None else fm.workflow_mode
        if effective_mode not in _WORKFLOW_MODES:
            raise ValueError(
                f"workflow_mode 无效（422）: {effective_mode}，"
                f"合法值: {sorted(_WORKFLOW_MODES)}"
            )

        # 校验 required_vars 是否全部存在
        missing = [v for v in fm.required_vars if v not in variables]
        if missing:
            raise ValueError(
                f"缺少 required_vars（422）: {missing}，"
                f"已提供变量: {sorted(variables.keys())}"
            )

        # Jinja2 真实渲染（支持 extends/block/if/elif/else/for/include/filter）
        # 使用解析后的 body 渲染，避免 YAML frontmatter 泄漏进 prompt
        try:
            template = self._env.from_string(record.body)
            rendered_prompt = template.render(**variables)
        except TemplateNotFound as exc:
            # extends/include 引用的父模板不存在
            raise TemplateNotFound(
                f"extends/include 引用的父模板不存在（422）: {exc.name}"
            ) from exc
        except TemplateSyntaxError as exc:
            # Jinja2 语法错误
            raise TemplateSyntaxError(
                f"Jinja2 语法错误（422）: {exc.message}",
                lineno=exc.lineno,
            ) from exc
        except TemplateError as exc:
            # 其他 Jinja2 错误（TemplateAssertionError 等）
            raise TemplateSyntaxError(
                f"Jinja2 渲染错误（422）: {exc}",
                lineno=0,
            ) from exc

        return RenderResult(
            rendered_prompt=rendered_prompt,
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

        Args:
            category: 分类过滤（None=全部，preset/custom=指定分类）

        Returns:
            模板记录列表（按 template_id 升序）

        Raises:
            ValueError: category 不在 {preset, custom} 中（422）
            RuntimeError: 文件 IO 异常（500）
        """
        if category is not None and category not in _CATEGORIES:
            raise ValueError(
                f"category 无效（422）: {category}，"
                f"合法值: {sorted(_CATEGORIES)}"
            )

        results: List[TemplateRecord] = []

        # 扫描 presets/
        if category is None or category == "preset":
            results.extend(self._scan_dir(self.presets_dir, "preset"))

        # 扫描 custom/
        if category is None or category == "custom":
            results.extend(self._scan_dir(self.custom_dir, "custom"))

        # 按 template_id 升序（rules-0 §三 sorting.order: ascending）
        results.sort(key=lambda r: r.template_id)
        return results

    def get_template(self, template_id: str) -> TemplateRecord:
        """获取单个模板。

        Args:
            template_id: 模板 ID

        Returns:
            模板记录

        Raises:
            KeyError: template_id 不存在（404）
        """
        # 校验 template_id 格式（避免路径注入）
        if not template_id or not _TEMPLATE_ID_PATTERN.match(template_id):
            raise KeyError(
                f"template_id 不存在或格式非法（404）: {template_id}"
            )

        # 先查 custom/，再查 presets/（custom 优先级更高，允许覆盖）
        for category, base_dir in (
            ("custom", self.custom_dir),
            ("preset", self.presets_dir),
        ):
            file_path = os.path.join(base_dir, f"{template_id}.j2")
            if os.path.isfile(file_path):
                return self._load_template_file(
                    template_id, category, file_path
                )

        raise KeyError(f"template_id 不存在（404）: {template_id}")

    def create_template(self, request: CreateTemplateRequest) -> TemplateRecord:
        """创建自定义模板。

        仅创建 custom 模板，preset 模板由系统预置。

        Args:
            request: 创建请求（template_id + name + frontmatter + body）

        Returns:
            创建的模板记录

        Raises:
            FileExistsError: template_id 已存在（409）
            ValueError: frontmatter 无效 / template_id 格式不合法（422）
            IOError: 文件写入失败（500）
        """
        # 校验 template_id 格式
        if not request.template_id or not _TEMPLATE_ID_PATTERN.match(
            request.template_id
        ):
            raise ValueError(
                f"template_id 格式不合法（422）: {request.template_id}，"
                f"仅允许字母/数字/下划线/连字符"
            )

        # 校验 frontmatter
        self._validate_frontmatter(request.frontmatter)

        # 校验 template_id 不冲突（custom + presets 均查）
        # 注意：preset 已存在的 template_id 也不允许在 custom 中创建同名，避免歧义
        if self._exists(request.template_id):
            raise FileExistsError(
                f"template_id 已存在（409）: {request.template_id}"
            )

        # name 持久化策略：schema frontmatter 不允许 name 字段（additionalProperties: false），
        # 故当 description 为 None 时，用 name 填充 description 作为 name 的持久化载体。
        # _load_template_file 中 name = frontmatter.description or template_id，
        # 保证重新加载后 name 与创建时一致。
        effective_frontmatter = request.frontmatter
        if request.frontmatter.description is None:
            effective_frontmatter = request.frontmatter.model_copy(
                update={"description": request.name}
            )

        # 写入文件
        file_path = os.path.join(self.custom_dir, f"{request.template_id}.j2")
        content = self._compose_template_content(
            effective_frontmatter, request.body
        )
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as exc:
            raise IOError(f"文件写入失败（500）: {file_path}: {exc}") from exc

        now = _iso_now()
        record = TemplateRecord(
            template_id=request.template_id,
            name=request.name,
            category="custom",
            frontmatter=effective_frontmatter,
            body=request.body,
            file_path=file_path,
            created_at=now,
            updated_at=now,
            is_deleted=False,
        )
        return record

    def update_template(
        self,
        template_id: str,
        request: UpdateTemplateRequest,
    ) -> TemplateRecord:
        """更新自定义模板。

        Args:
            template_id: 模板 ID
            request: 更新请求（name / frontmatter / body，None=不更新）

        Returns:
            更新后的模板记录

        Raises:
            KeyError: template_id 不存在（404）
            ValueError: frontmatter 无效（422）
            PermissionError: 尝试更新 preset 模板（403）
            IOError: 文件写入失败（500）
        """
        # 获取现有记录（不存在 raise KeyError）
        record = self.get_template(template_id)

        # preset 模板不可更新
        if record.category == "preset":
            raise PermissionError(
                f"preset 模板不可更新（403）: {template_id}"
            )

        # 应用更新
        new_name = request.name if request.name is not None else record.name
        new_frontmatter = (
            request.frontmatter
            if request.frontmatter is not None
            else record.frontmatter
        )
        new_body = request.body if request.body is not None else record.body

        # 校验新 frontmatter
        self._validate_frontmatter(new_frontmatter)

        # name 持久化策略：与 create_template 一致——当 description 为 None 时，
        # 用 new_name 填充 description 作为 name 的持久化载体，保证重新加载后 name 一致。
        effective_frontmatter = new_frontmatter
        if new_frontmatter.description is None:
            effective_frontmatter = new_frontmatter.model_copy(
                update={"description": new_name}
            )

        # 写回文件
        file_path = os.path.join(self.custom_dir, f"{template_id}.j2")
        content = self._compose_template_content(effective_frontmatter, new_body)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as exc:
            raise IOError(f"文件写入失败（500）: {file_path}: {exc}") from exc

        now = _iso_now()
        updated = TemplateRecord(
            template_id=template_id,
            name=new_name,
            category="custom",
            frontmatter=effective_frontmatter,
            body=new_body,
            file_path=file_path,
            created_at=record.created_at,
            updated_at=now,
            is_deleted=False,
        )
        return updated

    def delete_template(self, template_id: str) -> bool:
        """删除自定义模板。

        仅删除 custom 模板，preset 模板不可删除。

        Args:
            template_id: 模板 ID

        Returns:
            是否删除成功

        Raises:
            KeyError: template_id 不存在（404）
            PermissionError: 尝试删除 preset 模板（403）
            IOError: 文件删除失败（500）
        """
        # 获取现有记录（不存在 raise KeyError）
        record = self.get_template(template_id)

        # preset 模板不可删除
        if record.category == "preset":
            raise PermissionError(
                f"preset 模板不可删除（403）: {template_id}"
            )

        # 物理删除文件
        file_path = os.path.join(self.custom_dir, f"{template_id}.j2")
        try:
            os.remove(file_path)
        except FileNotFoundError as exc:
            # 文件已被外部删除，视为不存在
            raise KeyError(
                f"template_id 不存在（404）: {template_id}"
            ) from exc
        except OSError as exc:
            raise IOError(f"文件删除失败（500）: {file_path}: {exc}") from exc

        return True

    # ------------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------------ #

    def _parse_frontmatter(
        self, content: str
    ) -> Tuple[TemplateFrontmatter, str]:
        """内部方法：解析 YAML frontmatter。

        Args:
            content: 模板文件内容（含 frontmatter）

        Returns:
            (TemplateFrontmatter, body_string) 元组

        Raises:
            ValueError: YAML 格式错误 / 缺少必需字段（422）
        """
        if not content:
            raise ValueError("content 不能为空（422）")

        match = _FRONTMATTER_RE.match(content)
        if not match:
            raise ValueError(
                "frontmatter 格式错误（422）: 缺少 `---\\n...\\n---\\n` 包裹块"
            )

        fm_raw_str, body = match.group(1), match.group(2)

        # YAML 解析
        try:
            fm_dict = yaml.safe_load(fm_raw_str)
        except yaml.YAMLError as exc:
            raise ValueError(
                f"frontmatter YAML 解析失败（422）: {exc}"
            ) from exc

        if not isinstance(fm_dict, dict):
            raise ValueError(
                "frontmatter 必须是 YAML dict（422）"
            )

        # 必需字段校验
        if "workflow_mode" not in fm_dict:
            raise ValueError(
                "frontmatter 缺少必需字段 workflow_mode（422）"
            )
        if "expected_turns" not in fm_dict:
            raise ValueError(
                "frontmatter 缺少必需字段 expected_turns（422）"
            )

        workflow_mode = fm_dict["workflow_mode"]
        if workflow_mode not in _WORKFLOW_MODES:
            raise ValueError(
                f"workflow_mode 无效（422）: {workflow_mode}，"
                f"合法值: {sorted(_WORKFLOW_MODES)}"
            )

        try:
            expected_turns = int(fm_dict["expected_turns"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"expected_turns 不是整数（422）: {fm_dict['expected_turns']}"
            ) from exc
        if not (1 <= expected_turns <= 6):
            raise ValueError(
                f"expected_turns 超出范围 1-6（422）: {expected_turns}"
            )

        # 可选字段
        required_vars = fm_dict.get("required_vars") or []
        optional_vars = fm_dict.get("optional_vars") or []
        if not isinstance(required_vars, list):
            raise ValueError(
                "required_vars 必须是列表（422）"
            )
        if not isinstance(optional_vars, list):
            raise ValueError(
                "optional_vars 必须是列表（422）"
            )

        extends = fm_dict.get("extends")
        # extends 为空字符串时归一化为 None
        if isinstance(extends, str) and not extends.strip():
            extends = None

        description = fm_dict.get("description")
        if isinstance(description, str) and not description.strip():
            description = None

        frontmatter = TemplateFrontmatter(
            workflow_mode=workflow_mode,
            expected_turns=expected_turns,
            required_vars=[str(v) for v in required_vars],
            optional_vars=[str(v) for v in optional_vars],
            extends=extends,
            description=description,
        )
        return frontmatter, body

    # ------------------------------------------------------------------ #
    # 私有辅助方法
    # ------------------------------------------------------------------ #

    def _scan_dir(
        self, dir_path: str, category: str
    ) -> List[TemplateRecord]:
        """扫描指定目录下的所有 .j2 模板。

        Args:
            dir_path: 目录绝对路径
            category: 类别（preset / custom）

        Returns:
            模板记录列表
        """
        results: List[TemplateRecord] = []
        if not os.path.isdir(dir_path):
            return results

        try:
            entries = sorted(os.listdir(dir_path))
        except OSError as exc:
            raise RuntimeError(
                f"扫描目录失败（500）: {dir_path}: {exc}"
            ) from exc

        for entry in entries:
            if not entry.endswith(".j2"):
                continue
            template_id = entry[:-3]  # 去掉 .j2 后缀
            if not _TEMPLATE_ID_PATTERN.match(template_id):
                # 跳过不符合命名规范的文件（不阻断）
                continue
            file_path = os.path.join(dir_path, entry)
            if not os.path.isfile(file_path):
                continue
            try:
                record = self._load_template_file(
                    template_id, category, file_path
                )
                results.append(record)
            except (ValueError, OSError):
                # 单个模板解析失败不阻断整体扫描
                continue
        return results

    def _load_template_file(
        self, template_id: str, category: str, file_path: str
    ) -> TemplateRecord:
        """从文件加载单个模板记录。

        Args:
            template_id: 模板 ID
            category: 类别（preset / custom）
            file_path: 文件绝对路径

        Returns:
            模板记录

        Raises:
            ValueError: frontmatter 解析失败
            OSError: 文件读取失败
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as exc:
            raise OSError(f"读取模板文件失败: {file_path}: {exc}") from exc

        frontmatter, body = self._parse_frontmatter(content)

        # 用文件的 mtime 作为 created_at / updated_at
        try:
            mtime = os.path.getmtime(file_path)
            ts = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        except OSError:
            ts = _iso_now()

        # name 默认取 frontmatter.description 或 template_id
        name = frontmatter.description or template_id

        return TemplateRecord(
            template_id=template_id,
            name=name,
            category=category,
            frontmatter=frontmatter,
            body=body,
            file_path=file_path,
            created_at=ts,
            updated_at=ts,
            is_deleted=False,
        )

    def _exists(self, template_id: str) -> bool:
        """检查 template_id 在 custom/ 或 presets/ 是否已存在。

        Args:
            template_id: 模板 ID

        Returns:
            True=存在，False=不存在
        """
        if not template_id or not _TEMPLATE_ID_PATTERN.match(template_id):
            return False
        for base_dir in (self.custom_dir, self.presets_dir):
            file_path = os.path.join(base_dir, f"{template_id}.j2")
            if os.path.isfile(file_path):
                return True
        return False

    def _validate_frontmatter(self, fm: TemplateFrontmatter) -> None:
        """校验 frontmatter 字段合法性。

        Args:
            fm: 待校验的 frontmatter

        Raises:
            ValueError: 字段非法（422）
        """
        if fm.workflow_mode not in _WORKFLOW_MODES:
            raise ValueError(
                f"workflow_mode 无效（422）: {fm.workflow_mode}，"
                f"合法值: {sorted(_WORKFLOW_MODES)}"
            )
        if not (1 <= fm.expected_turns <= 6):
            raise ValueError(
                f"expected_turns 超出范围 1-6（422）: {fm.expected_turns}"
            )
        if not isinstance(fm.required_vars, list):
            raise ValueError("required_vars 必须是列表（422）")
        if not isinstance(fm.optional_vars, list):
            raise ValueError("optional_vars 必须是列表（422）")

    def _compose_template_content(
        self, frontmatter: TemplateFrontmatter, body: str
    ) -> str:
        """将 frontmatter + body 组装为模板文件内容。

        Args:
            frontmatter: frontmatter 对象
            body: Jinja2 模板体

        Returns:
            完整模板文件内容（YAML frontmatter + body）
        """
        fm_dict: Dict[str, Any] = {
            "workflow_mode": frontmatter.workflow_mode,
            "expected_turns": frontmatter.expected_turns,
            "required_vars": frontmatter.required_vars,
            "optional_vars": frontmatter.optional_vars,
            "extends": frontmatter.extends,
        }
        if frontmatter.description is not None:
            fm_dict["description"] = frontmatter.description

        fm_yaml = yaml.safe_dump(
            fm_dict,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        ).strip()
        return f"---\n{fm_yaml}\n---\n{body}"
