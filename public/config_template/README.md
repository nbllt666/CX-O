# public/config_template/ — 配置契约（JSON Schema）

> 配置契约层，rules-3 §三定义。所有配置文件结构以 JSON Schema 定义，包含参数取值范围与默认值。禁止业务代码硬编码配置参数。

## 当前状态：种子阶段

本目录当前为种子阶段，schema 文件仅含源真理指针，不包含完整字段定义。完整 Schema 由后续 s0201 Skill 承接生成。

## Schema 清单与源真理

| Schema 文件 | 源真理（真实配置源） | 优先级 |
|-------------|---------------------|--------|
| `unified_config.schema.json` | `c:/CX-O/CX-O-SERVER/server/config.py` UnifiedConfig（line 437，30+ Pydantic BaseModel，15 顶层节） | P0 |
| `default_yaml.schema.json` | `c:/CX-O/config/default.yaml`（21 顶层键：server/cors/logging/database/models/model_defaults/agent/memory/context/tools/acp/security/monitoring/llm_params/tts/avatar/asr/voice_workstation/live/limits） | P0 |
| `settings_json.schema.json` | `c:/CX-O/config/settings.json`（services: danmaku/firewall/vad/sensevoice_streaming + tts） | P1 |
| `env.schema.json` | `c:/CX-O/.env.example`（F5-TTS/LLM/Orpheus TTS 三组变量 + HF_TOKEN）+ `c:/CX-O/config/env.py` EnvConfig（CXHMS_ 前缀映射） | P1 |

## 配置契约强制要求（rules-3 §三）

- **默认值**：配置契约必须包含默认值
- **自动填充**：配置加载时自动补充缺失字段（auto_fill）
- **禁止硬编码**：禁止业务代码硬编码配置参数
- **配置入口**：默认 `config/config.json`，支持 `AC_CONFIG_PATH` 覆盖（Pipeline 约定）；CX-O 后端使用 `server/config.py` 的 `get_settings()`/`get_config()`/`reload_config()`

## CX-O 配置体系现状

CX-O 存在多套配置体系，s0201 阶段需统一对齐：
1. **Pydantic UnifiedConfig**（`server/config.py`）：后端运行时配置，30+ BaseModel，最终汇聚为 `UnifiedConfig`
2. **YAML 配置**（`config/*.yaml`）：default/firewall/firewall_v3/vad/danmaku/hidden_prompt
3. **JSON 配置**（`config/settings.json`）：服务运行时设置
4. **环境变量**（`.env.example` + `config/env.py`）：CXHMS_ 前缀 + F5-TTS/LLM/Orpheus 变量
5. **config/validation.py**：ConfigValidator 含 REQUIRED_FIELDS + VALID_VALUES 枚举集

## 契约可验证性（rules-3 §五）

- **测试套件**：未闭合，待 s0201 生成完整 Schema 后补配置契约默认值填充用例
- **合规 rubric**：未闭合，待 s0201 生成后补默认值覆盖判据
- **auto_fill 校验**：待 s0201 补配置加载自动补充缺失字段测试
