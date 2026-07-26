"""
gen_music_types.py — s0202 前后端同源生成器（模块0_歌谱契约核心 · 前端类型/Mock 数据）

从冻结契约与后端真源生成前端 TypeScript 产物（前后端同源，禁止手改生成物）：

输入（全部为已冻结锚点 / 后端真源）：
- .trae/specs/redesign-composition-staff-editor/contracts/score-v2.schema.json
- .trae/specs/redesign-composition-staff-editor/contracts/command-protocol.schema.json
- .trae/specs/redesign-composition-staff-editor/contracts/music-inventory.schema.json
- CX-O-VoiceWorkStation/tests/fixtures/score_fixtures.json（前后端唯一夹具真相源）
- CX-O-VoiceWorkStation/workstation/music/inventory.py（INVENTORY 常量与鼓键别名真源，
  经 import 取得；该模块 import 期已对冻结契约自检，漂移即 ImportError）

输出（本脚本唯一可写范围）：
- src/pages/audioWorkstation/staff/types.ts                — 契约 TS 类型
- src/pages/audioWorkstation/staff/__mocks__/fixtures.ts   — 歌谱夹具（v1/v2 输入原样）
- src/pages/audioWorkstation/staff/__mocks__/inventory.ts  — 枚举清单数据 + 存取函数

用法：python scripts/gen_music_types.py
变更流程：只改上游（契约走 s0601 / 夹具 JSON / inventory.py），再重跑本脚本。
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# 路径解析（rules-0 §三：禁止相对路径，逐层 dirname 定位）
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_FRONTEND_DIR = os.path.dirname(_SCRIPTS_DIR)
_CXO_ROOT = os.path.dirname(_FRONTEND_DIR)
_CONTRACTS_DIR = os.path.join(
    _CXO_ROOT, ".trae", "specs", "redesign-composition-staff-editor", "contracts"
)
_FIXTURES_JSON = os.path.join(
    _CXO_ROOT, "CX-O-VoiceWorkStation", "tests", "fixtures", "score_fixtures.json"
)
_BACKEND_ROOT = os.path.join(_CXO_ROOT, "CX-O-VoiceWorkStation")

_STAFF_DIR = os.path.join(_FRONTEND_DIR, "src", "pages", "audioWorkstation", "staff")
_MOCKS_DIR = os.path.join(_STAFF_DIR, "__mocks__")

# ---------------------------------------------------------------------------
# JSON Schema → TS 渲染（针对三份冻结契约的目标化渲染器）
# ---------------------------------------------------------------------------

# 数组/对象属性 → 具名接口覆盖（键 = (父接口名, 属性名)）
_ITEM_NAME_OVERRIDES: dict[tuple[str, str], str] = {
    ("ScoreV2", "melody"): "MelodyNote",
    ("ScoreV2", "chords"): "ChordEntry",
    ("ScoreV2", "accompaniment_tracks"): "AccompanimentTrack",
    ("AccompanimentTrack", "events"): "TrackEvent",
    ("MusicInventory", "instrument_groups"): "InstrumentGroup",
    ("InstrumentGroup", "instruments"): "Instrument",
    ("MusicInventory", "styles"): "StyleDef",
    ("MusicInventory", "drum_keys"): "DrumKey",
    ("CommandResult", "error"): "CommandError",
    ("UpdateNoteArgs", "patch"): "UpdateNotePatch",
    ("UpdateChordArgs", "patch"): "UpdateChordPatch",
}

# 属性 → TS 类型整体覆盖（schema 仅声明泛型 object 或需元组/契约交叉引用处）
_TYPE_OVERRIDES: dict[tuple[str, str], str] = {
    ("InstrumentGroup", "program_range"): "[number, number]",
    ("CommandResult", "snapshot"): "ScoreV2",
    ("CommandResult", "result"): "Record<string, unknown>",
    ("CommandError", "details"): "Record<string, unknown>",
    ("DraftFile", "score"): "ScoreV2",
}


def _pascal(snake: str) -> str:
    """snake_case → PascalCase"""
    return "".join(part.capitalize() or "_" for part in snake.split("_"))


def _doc(text: str, indent: str = "") -> list[str]:
    """schema description → TS 文档注释（净化闭合符）"""
    if not text:
        return []
    safe = text.replace("*/", "* /")
    return [f"{indent}/** {safe} */"]


class _RenderCtx:
    """渲染上下文：definitions 解析表 + default 填充语义开关 + 接口收集器"""

    def __init__(self, definitions: dict | None = None, fill_defaults: bool = False):
        self.definitions = definitions or {}
        self.fill_defaults = fill_defaults
        self.interfaces: list[tuple[str, str]] = []
        self.emitted: set[str] = set()


def _ref_type(ref: str, ctx: _RenderCtx) -> str:
    """解析 #/definitions/x：标量别名内联为 TS 基础类型"""
    key = ref.rsplit("/", 1)[-1]
    target = ctx.definitions.get(key, {})
    t = target.get("type")
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    return "string"


def _prop_type(schema: dict, ctx: _RenderCtx, pointer: tuple[str, str] | None,
               default_iface: str) -> str:
    """渲染单个属性的 TS 类型"""
    if pointer is not None and pointer in _TYPE_OVERRIDES:
        return _TYPE_OVERRIDES[pointer]
    if "$ref" in schema:
        return _ref_type(schema["$ref"], ctx)
    t = schema.get("type")
    if t == "object":
        if not schema.get("properties"):
            return "Record<string, unknown>"
        iface = _ITEM_NAME_OVERRIDES.get(pointer, default_iface) if pointer else default_iface
        _emit_interface(iface, schema, ctx)
        return iface
    if t == "array":
        items = schema.get("items", {})
        item_iface = (
            _ITEM_NAME_OVERRIDES.get(pointer, default_iface + "Item")
            if pointer else default_iface + "Item"
        )
        return _prop_type(items, ctx, None, item_iface) + "[]"
    if t == "string":
        enum = schema.get("enum")
        if enum:
            return " | ".join(json.dumps(e, ensure_ascii=False) for e in enum)
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    return "unknown"


def _emit_interface(name: str, schema: dict, ctx: _RenderCtx) -> None:
    """由 object schema 生成 export interface 并收集（去重幂等）"""
    if name in ctx.emitted:
        return
    ctx.emitted.add(name)

    required = set(schema.get("required", []))
    properties = schema.get("properties", {})
    if ctx.fill_defaults:
        # 规范化语义：带 default 的字段经校验层填充后必然存在（score v2 快照形状）
        required |= {p for p, sub in properties.items() if "default" in sub}

    lines: list[str] = []
    lines.extend(_doc(schema.get("description", "")))
    lines.append(f"export interface {name} {{")
    for prop, sub in properties.items():
        opt = "" if prop in required else "?"
        lines.extend(_doc(sub.get("description", ""), indent="  "))
        ts = _prop_type(sub, ctx, (name, prop), name + _pascal(prop))
        lines.append(f"  {prop}{opt}: {ts};")
    lines.append("}")
    ctx.interfaces.append((name, "\n".join(lines)))


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)


def _header(title: str, sources: list[str]) -> str:
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    body = "\n".join(f"//   - {line}" for line in sources)
    return (
        "/* eslint-disable */\n"
        "// ============================================================================\n"
        f"// {title}\n"
        "// 本文件由 scripts/gen_music_types.py 自动生成（s0202 前后端同源），禁止手改。\n"
        "// 数据源：\n"
        f"{body}\n"
        f"// 生成时间：{stamp}\n"
        "// ============================================================================\n"
    )


# ---------------------------------------------------------------------------
# types.ts 生成
# ---------------------------------------------------------------------------


def _gen_types_ts(score_schema: dict, command_schema: dict, inventory_schema: dict) -> str:
    parts: list[str] = [
        _header(
            "types.ts — 作曲区契约 TS 类型（歌谱 v2 / 命令协议 / 音乐枚举清单）",
            [
                f"score-v2.schema.json        x-version: {score_schema.get('x-version')}",
                f"command-protocol.schema.json x-version: {command_schema.get('x-version')}",
                f"music-inventory.schema.json  x-version: {inventory_schema.get('x-version')}",
            ],
        ),
        "",
        "// ---------------------------------------------------------------------------",
        "// 歌谱 v2（ScoreV2 = 经 validate_score 规范化后的快照形状：带 default 字段必然存在）",
        "// ---------------------------------------------------------------------------",
        "",
    ]

    # 歌谱 v2：fill_defaults=True（规范化快照）
    score_ctx = _RenderCtx(fill_defaults=True)
    _emit_interface("ScoreV2", score_schema, score_ctx)
    parts.extend(body for _, body in score_ctx.interfaces)

    # 音乐枚举清单（实例形状，仅 required 必填）
    parts.append("")
    parts.append("// ---------------------------------------------------------------------------")
    parts.append("// 音乐枚举清单（GM 128 音色 / 节奏型 / 鼓键映射）")
    parts.append("// ---------------------------------------------------------------------------")
    parts.append("")
    inv_ctx = _RenderCtx()
    _emit_interface("MusicInventory", inventory_schema, inv_ctx)
    parts.extend(body for _, body in inv_ctx.interfaces)

    # 命令协议
    parts.append("")
    parts.append("// ---------------------------------------------------------------------------")
    parts.append("// 歌谱编辑命令协议（20 命令人机同构）")
    parts.append("// ---------------------------------------------------------------------------")
    parts.append("")

    definitions = command_schema.get("definitions", {})
    cmd_enum = command_schema["properties"]["command"]["enum"]
    parts.append("/** 命令名枚举（20 命令，schema properties.command.enum 原样） */")
    parts.append(f"export const COMMAND_NAMES = {json.dumps(cmd_enum, ensure_ascii=False, indent=2)} as const;")
    parts.append("")
    parts.append("export type CommandName = (typeof COMMAND_NAMES)[number];")
    parts.append("")

    # 错误码
    error_codes = [e["code"] for e in command_schema.get("x-error-codes", [])]
    parts.append("/** 错误码枚举（schema x-error-codes 原样） */")
    parts.append(f"export const ERROR_CODES = {json.dumps(error_codes, ensure_ascii=False, indent=2)} as const;")
    parts.append("")
    parts.append("export type ErrorCode = (typeof ERROR_CODES)[number];")
    parts.append("")

    cmd_ctx = _RenderCtx(definitions=definitions)
    for key, sub in definitions.items():
        if key.startswith("args_"):
            _emit_interface(_pascal(key[len("args_"):]) + "Args", sub, cmd_ctx)
    _emit_interface("CommandResult", definitions["command_result"], cmd_ctx)
    _emit_interface("DraftFile", definitions["draft_file"], cmd_ctx)
    parts.extend(body for _, body in cmd_ctx.interfaces)

    # 命令 → args 映射与可判别联合
    parts.append("")
    parts.append("/** 命令名 → args 类型映射 */")
    parts.append("export interface CommandArgsMap {")
    for cmd in cmd_enum:
        parts.append(f"  {cmd}: {_pascal(cmd)}Args;")
    parts.append("}")
    parts.append("")
    parts.append("/** 命令请求（可判别联合：command 与 args 形状一一对应） */")
    parts.append("export type CommandRequest = {")
    parts.append("  [K in CommandName]: { command: K; args: CommandArgsMap[K] };")
    parts.append("}[CommandName];")
    parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# fixtures.ts 生成
# ---------------------------------------------------------------------------


def _gen_fixtures_ts(fixtures_raw: dict, score_version: str) -> str:
    meta = {
        name: entry.get("description", "")
        for name, entry in fixtures_raw.items()
        if not name.startswith("_")
    }
    scores = {
        name: entry["score"]
        for name, entry in fixtures_raw.items()
        if not name.startswith("_")
    }
    v2_names = [n for n in scores if not n.startswith("v1")]
    v1_names = [n for n in scores if n.startswith("v1")]

    parts = [
        _header(
            "fixtures.ts — 歌谱夹具（v1/v2 输入原样，前后端唯一真相源的 TS 投影）",
            [
                "CX-O-VoiceWorkStation/tests/fixtures/score_fixtures.json（唯一真相源，变更只改该 JSON）",
                f"score-v2.schema.json        x-version: {score_version}（v2 夹具校验基准）",
            ],
        ),
        "",
        "/** 夹具元信息（description 原样） */",
        f"export const SCORE_FIXTURE_META: Record<string, string> = {json.dumps(meta, ensure_ascii=False, indent=2)};",
        "",
        "/**",
        " * 歌谱夹具输入原样（v1 夹具含已移除字段 accompaniment_style，属迁移测试输入；",
        " * v2 夹具为冻结契约输入形状）。消费方：mockDraftBackend.createDraft 种子、",
        " * validateScore 冒烟、渲染层快照冒烟。",
        " */",
        f"export const SCORE_FIXTURES: Record<string, Record<string, unknown>> = {json.dumps(scores, ensure_ascii=False, indent=2)};",
        "",
        f"export const V2_FIXTURE_NAMES = {json.dumps(v2_names, ensure_ascii=False)} as const;",
        f"export const V1_FIXTURE_NAMES = {json.dumps(v1_names, ensure_ascii=False)} as const;",
        "",
        "/** 按名取夹具（深拷贝，防调用方原地篡改常量） */",
        "export function getFixture(name: string): Record<string, unknown> {",
        "  const score = SCORE_FIXTURES[name];",
        "  if (!score) {",
        "    throw new Error(`未知歌谱夹具: ${name}（可用: ${Object.keys(SCORE_FIXTURES).join('、')}）`);",
        "  }",
        "  return JSON.parse(JSON.stringify(score)) as Record<string, unknown>;",
        "}",
        "",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# inventory.ts 生成（后端 inventory.py 为真源）
# ---------------------------------------------------------------------------


def _gen_inventory_ts(inventory: dict, aliases: dict, inventory_version: str) -> str:
    parts = [
        _header(
            "inventory.ts — 音乐枚举清单数据 + 存取函数（前后端同源）",
            [
                "CX-O-VoiceWorkStation/workstation/music/inventory.py（INVENTORY 与鼓键别名唯一真源，经 import 取得）",
                f"music-inventory.schema.json  x-version: {inventory_version}（形状基准）",
            ],
        ),
        "",
        "import type { MusicInventory, StyleDef } from '../types';",
        "",
        "/** 音乐枚举清单（GM 16 组 128 音色 / 4 节奏型 / 10 鼓键，后端 INVENTORY 原样投影） */",
        f"export const INVENTORY: MusicInventory = {json.dumps(inventory, ensure_ascii=False, indent=2)};",
        "",
        "/** 鼓键别名 → 规范键名（实现层数据，扩展属数据层变更） */",
        f"export const DRUM_KEY_ALIASES: Record<string, string> = {json.dumps(aliases, ensure_ascii=False, indent=2)};",
        "",
        "/** 鼓键解析索引：规范键名 + 别名 + 中文显示名 → MIDI 音号（模块加载期构建） */",
        "const DRUM_KEY_INDEX: Record<string, number> = (() => {",
        "  const index: Record<string, number> = {};",
        "  for (const entry of INVENTORY.drum_keys) {",
        "    index[entry.key] = entry.midi;",
        "    index[entry.name] = entry.midi;",
        "  }",
        "  for (const [alias, canonical] of Object.entries(DRUM_KEY_ALIASES)) {",
        "    index[alias] = index[canonical];",
        "  }",
        "  return index;",
        "})();",
        "",
        "/** 按 id 查节奏型定义（含 applies_to）；未命中返回 undefined */",
        "export function getStyle(styleId: string): StyleDef | undefined {",
        "  const hit = INVENTORY.styles.find((style) => style.id === styleId);",
        "  return hit ? (JSON.parse(JSON.stringify(hit)) as StyleDef) : undefined;",
        "}",
        "",
        "/**",
        " * GM 鼓键名 → MIDI 音号（如 \"kick\"→36）。",
        " * 接受规范键名、实现层别名（如 \"bd\"/\"hh\"）与中文显示名（如 \"底鼓\"）。",
        " */",
        "export function resolveDrumKey(key: string): number {",
        "  if (typeof key === 'string') {",
        "    const midi = DRUM_KEY_INDEX[key.trim()];",
        "    if (midi !== undefined) {",
        "      return midi;",
        "    }",
        "  }",
        "  const available = INVENTORY.drum_keys.map((entry) => entry.key).join('、');",
        "  throw new Error(`未定义的鼓键名: ${JSON.stringify(key)}（可用键名: ${available}）`);",
        "}",
        "",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(content)


def main() -> int:
    started = time.monotonic()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] [INFO] gen_music_types 启动")

    score_schema = _load_json(os.path.join(_CONTRACTS_DIR, "score-v2.schema.json"))
    command_schema = _load_json(os.path.join(_CONTRACTS_DIR, "command-protocol.schema.json"))
    inventory_schema = _load_json(os.path.join(_CONTRACTS_DIR, "music-inventory.schema.json"))
    fixtures_raw = _load_json(_FIXTURES_JSON)

    # 后端真源经 import 取得（import 期 inventory 模块已对冻结契约自检）
    if _BACKEND_ROOT not in sys.path:
        sys.path.insert(0, _BACKEND_ROOT)
    from workstation.music.inventory import _DRUM_KEY_ALIASES, INVENTORY

    types_ts = _gen_types_ts(score_schema, command_schema, inventory_schema)
    fixtures_ts = _gen_fixtures_ts(fixtures_raw, score_schema.get("x-version", "?"))
    inventory_ts = _gen_inventory_ts(INVENTORY, _DRUM_KEY_ALIASES, inventory_schema.get("x-version", "?"))

    outputs = {
        os.path.join(_STAFF_DIR, "types.ts"): types_ts,
        os.path.join(_MOCKS_DIR, "fixtures.ts"): fixtures_ts,
        os.path.join(_MOCKS_DIR, "inventory.ts"): inventory_ts,
    }
    for path, content in outputs.items():
        _write(path, content)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [INFO] 已生成 {path}（{len(content)} 字符）")

    elapsed = time.monotonic() - started
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [INFO] gen_music_types 完成，耗时 {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
