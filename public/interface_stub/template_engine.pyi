"""TemplateEngine 接口契约存根。

定义 RADIX-Lite 模板引擎的渲染接口 + 模板 CRUD 签名。
实现必须严格匹配此存根定义的签名，否则契约测试不通过。

模板系统：YAML frontmatter + Jinja2 原生渲染
支持：extends / block / if / elif / else / for / include / filter
模板仓库：data/templates/presets/（预设） + data/templates/custom/（自定义）

@version 1.0.0
@see public/schema/template_registry.schema.json
@see public/config_template/radix_config.json
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


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


class TemplateEngine:
    """TemplateEngine 接口契约。

    进程内引擎，使用 YAML frontmatter + Jinja2 原生渲染。
    模板仓库 data/templates/ 分 presets/ 和 custom/ 目录。
    """

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
        ...

    def list_templates(
        self,
        category: Optional[str] = None,
    ) -> List[TemplateRecord]:
        """列出模板。

        Args:
            category: 分类过滤（None=全部，preset/custom=指定分类）

        Returns:
            模板记录列表

        Raises:
            RuntimeError: 文件 IO 异常（500）
        """
        ...

    def get_template(self, template_id: str) -> TemplateRecord:
        """获取单个模板。

        Args:
            template_id: 模板 ID

        Returns:
            模板记录

        Raises:
            KeyError: template_id 不存在（404）
        """
        ...

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
        ...

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
        ...

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
        ...

    def _parse_frontmatter(self, content: str) -> tuple:
        """内部方法：解析 YAML frontmatter。

        Args:
            content: 模板文件内容（含 frontmatter）

        Returns:
            (frontmatter_dict, body_string) 元组

        Raises:
            ValueError: YAML 格式错误 / 缺少必需字段（422）
        """
        ...
