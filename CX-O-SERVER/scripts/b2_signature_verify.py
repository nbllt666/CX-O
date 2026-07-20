"""B2 签名验证脚本 v2：对比 multimodal_pipeline.py 实现与 .pyi 契约。

.p yi 契约文件本身有预存的中文标点/乱码语法错误（第 24-26 行），
不能直接 ast.parse。本脚本对 .pyi 用正则提取方法签名，
对实现用 ast.parse 提取方法签名，再对比。

仅读取 public/ 文件，不修改。
"""
import ast
import re
import sys

PYI_PATH = r"c:\CX-O\public\interface_stub\multimodal_pipeline.pyi"
IMPL_PATH = r"c:\CX-O\CX-O-SERVER\server\core\multimodal\multimodal_pipeline.py"


def extract_methods_pyi_regex(path):
    """用正则从 .pyi 提取 MultimodalPipeline 类的方法签名。

    适用于 .pyi 含语法错误的场景（仅做结构提取，不解析为 AST）。
    """
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()

    methods = {}
    # 锁定 MultimodalPipeline 类块（从 'class MultimodalPipeline:' 到下一个 class 顶层定义或文件尾）
    m = re.search(
        r"class\s+MultimodalPipeline\s*\(([^)]*)\)\s*:\s*\n(.+?)(?=\nclass\s|\Z)",
        source,
        re.DOTALL,
    )
    if not m:
        # 尝试无基类形式
        m = re.search(
            r"class\s+MultimodalPipeline\s*:\s*\n(.+?)(?=\nclass\s|\Z)",
            source,
            re.DOTALL,
        )
        if not m:
            return methods
        body = m.group(1)
    else:
        body = m.group(2)

    # 提取 def 方法签名（支持多行参数列表）
    # 模式：def name(args) -> return_type:
    pattern = re.compile(
        r"def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*([^:\n]+))?\s*:",
        re.DOTALL,
    )
    for match in pattern.finditer(body):
        name = match.group(1)
        args_raw = match.group(2).strip()
        returns = (match.group(3) or "None").strip()
        # 拆分参数：按 ',' 分割，去掉类型注解
        args = []
        if args_raw:
            for part in args_raw.split(","):
                part = part.strip()
                if not part:
                    continue
                # 取参数名（':' 之前）
                arg_name = part.split(":")[0].strip()
                if arg_name:
                    args.append(arg_name)
        methods[name] = {"args": args, "returns": returns}
    return methods


def extract_methods_impl(path):
    """用 ast.parse 从实现文件提取 MultimodalPipeline 类的方法签名。"""
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    methods = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "MultimodalPipeline":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = item.name
                    args = [a.arg for a in item.args.args]
                    returns = ast.unparse(item.returns) if item.returns else "None"
                    methods[name] = {"args": args, "returns": returns}
    return methods


def main():
    pyi_methods = extract_methods_pyi_regex(PYI_PATH)
    impl_methods = extract_methods_impl(IMPL_PATH)

    print("=" * 80)
    print(f"CONTRACT (.pyi) METHODS (regex-extracted): {len(pyi_methods)}")
    print("=" * 80)
    for name, info in pyi_methods.items():
        print(f"  {name}{tuple(info['args'])} -> {info['returns']}")

    print()
    print("=" * 80)
    print(f"IMPLEMENTATION (multimodal_pipeline.py) METHODS: {len(impl_methods)}")
    print("=" * 80)
    for name, info in impl_methods.items():
        print(f"  {name}{tuple(info['args'])} -> {info['returns']}")

    print()
    print("=" * 80)
    print("SIGNATURE MATCH REPORT")
    print("=" * 80)
    required = set(pyi_methods.keys())
    actual = set(impl_methods.keys())
    missing = required - actual
    extra = actual - required

    print(f"Required methods (from .pyi): {len(required)}")
    print(f"Implemented methods: {len(actual & required)}")
    print(f"Missing in implementation: {len(missing)}")
    for m in sorted(missing):
        print(f"  MISSING: {m}")
    print(f"Extra in implementation: {len(extra)}")
    for m in sorted(extra):
        print(f"  EXTRA: {m}")

    print()
    print("=" * 80)
    print("PER-METHOD ARGUMENT MATCH (excluding 'self')")
    print("=" * 80)
    all_match = True
    for name in sorted(required & actual):
        p = pyi_methods[name]
        i = impl_methods[name]
        p_args = [a for a in p["args"] if a != "self"]
        i_args = [a for a in i["args"] if a != "self"]
        if p_args == i_args:
            print(f"  [OK]    {name}: args match ({p_args})")
        else:
            print(f"  [DIFF]  {name}: pyi={p_args} vs impl={i_args}")
            all_match = False

    print()
    if not missing and all_match:
        print("VERDICT: ALL_SIGNATURES_MATCH")
        sys.exit(0)
    else:
        print("VERDICT: SIGNATURE_MISMATCH")
        sys.exit(1)


if __name__ == "__main__":
    main()
