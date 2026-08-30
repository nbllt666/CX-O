"""CX-O-SERVER 模板引擎模块（模块7 迁移版）。

RADIX-Lite 进程内模板引擎（TemplateEngine），YAML frontmatter + Jinja2 原生渲染：
    - 模板渲染：Jinja2 原生渲染（extends / block / if / elif / else / for / include / filter）
    - 模板 CRUD：preset（只读，auto_init 创建默认）/ custom（可 CRUD）
    - 工作流定义解析：frontmatter 中的 workflow_mode + expected_turns
    - 自定义 filter：confidence_label（0-1 → 低/中/高）

迁移来源: c:\\CX-O\\CXHMS\\modules\\模块7_模板引擎\\（v1.0.0）
CX-O 适配点:
    - 路径锚点改为 CX-O-SERVER 风格（data/templates/，基于 _PROJECT_ROOT 解析）
    - 配置加载改为 server.config.get_settings()（不再依赖 CXHMS 的 config/default.yaml）
    - 保留原全部方法签名与逻辑（严格匹配 .pyi 契约）

对应契约（严格匹配签名，rules-3 §二 signature_match）:
    - 接口: public/interface_stub/template_engine.pyi
    - 数据: 无独立 schema 文件，字段定义以 template_engine.py TemplateRecord 为准（待 s0201 重建）
    - 配置: public/config_template/radix_config.json（template_engine 段）
    - 运行时配置: server/config.py（template_engine 节，由主线程统一扩展，缺失时降级默认值）

@version 1.0.0
@see public/interface_stub/template_engine.pyi
@see 数据契约: template_engine.py（本包 TemplateRecord 字段定义，待 s0201 重建）
"""

from .template_engine import (
    CreateTemplateRequest,
    RenderResult,
    TemplateEngine,
    TemplateFrontmatter,
    TemplateRecord,
    UpdateTemplateRequest,
)

__all__ = [
    "TemplateEngine",
    "TemplateFrontmatter",
    "TemplateRecord",
    "RenderResult",
    "CreateTemplateRequest",
    "UpdateTemplateRequest",
]

__version__ = "1.0.0"
