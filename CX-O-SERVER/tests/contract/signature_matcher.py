"""接口契约签名匹配工具（CX-O-SERVER 测试基础设施 Phase 1）。

基于 ``public/interface_stub/*.pyi`` 存根文件验证模块实现的方法签名是否匹配契约。

核心能力：
- ``load_stub(stub_name)`` —— 加载并解析 .pyi 存根（返回 AST 模块）
- ``match_signature(func, stub_name, func_name)`` —— 验证函数签名匹配
- ``match_class_signature(cls, stub_name, class_name)`` —— 验证类签名匹配

匹配策略：
- 参数名：严格匹配（顺序敏感），决定 ``matched``
- 参数注解 / 返回注解：best-effort 字符串归一化比较，差异记入 ``annotation_diffs``，
  默认不影响 ``matched``；调用方可通过 ``strict=True`` 要求注解也匹配
- 存根缺失 / 函数缺失：``stub_found=False`` / ``matched=False``

注意：当前 ``public/interface_stub/`` 处于种子阶段（仅 4 个代表性 .pyi），
``STUB_INDEX.md`` 标注完整 19 个存根待 s0201 补全。本工具在存根未补全时
会清晰报告 ``stub_not_found``，便于后续批次按需启用校验。
"""

from __future__ import annotations

import ast
import inspect
import os
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from tests.contract import get_public_root


# ---------------------------------------------------------------------------
# 结果数据类
# ---------------------------------------------------------------------------
@dataclass
class SignatureMatchResult:
    """函数签名匹配结果。"""

    matched: bool
    """是否匹配（默认仅参数名一致即视为匹配）"""
    stub_found: bool
    """存根文件是否存在"""
    func_found: bool
    """存根中是否存在该函数"""
    stub_name: str
    func_name: str
    stub_params: List[str] = field(default_factory=list)
    """存根定义的参数名（顺序）"""
    actual_params: List[str] = field(default_factory=list)
    """实际函数的参数名（顺序）"""
    missing_params: List[str] = field(default_factory=list)
    """存根要求但实际缺失的参数"""
    extra_params: List[str] = field(default_factory=list)
    """实际有但存根未声明的参数"""
    annotation_diffs: List[str] = field(default_factory=list)
    """注解差异描述（informational）"""
    return_diff: Optional[str] = None
    """返回注解差异描述（None 表示无差异或存根未声明返回）"""
    message: str = ""
    """人类可读的匹配结论"""

    def assert_matched(self, strict: bool = False) -> None:
        """断言匹配通过，否则抛出 AssertionError 并附详细差异。

        Args:
            strict: 为 True 时要求注解也匹配（annotation_diffs / return_diff 为空）
        """
        assert self.matched, f"签名不匹配: {self.message}\n详情: {self._detail()}"
        if strict:
            assert not self.annotation_diffs, (
                f"注解差异（strict 模式）: {self.annotation_diffs}"
            )
            assert self.return_diff is None, f"返回注解差异（strict 模式）: {self.return_diff}"

    def _detail(self) -> dict:
        return {
            "stub_params": self.stub_params,
            "actual_params": self.actual_params,
            "missing_params": self.missing_params,
            "extra_params": self.extra_params,
            "annotation_diffs": self.annotation_diffs,
            "return_diff": self.return_diff,
        }


@dataclass
class ClassSignatureMatchResult:
    """类签名匹配结果。"""

    matched: bool
    stub_found: bool
    class_found: bool
    stub_name: str
    class_name: str
    method_results: List[SignatureMatchResult] = field(default_factory=list)
    """存根类中各方法的逐项匹配结果"""
    missing_methods: List[str] = field(default_factory=list)
    """存根声明但实际类缺失的方法"""
    message: str = ""


# ---------------------------------------------------------------------------
# 存根加载
# ---------------------------------------------------------------------------
def _stub_dir() -> str:
    """返回 interface_stub 目录绝对路径。"""
    return os.path.join(get_public_root(), "interface_stub")


def _stub_path(stub_name: str) -> str:
    """返回存根文件绝对路径。

    Args:
        stub_name: 存根名（不含扩展名），如 ``chat`` / ``agents``
    """
    name = stub_name if stub_name.endswith(".pyi") else f"{stub_name}.pyi"
    return os.path.join(_stub_dir(), name)


def load_stub(stub_name: str) -> Optional[ast.Module]:
    """加载并解析 .pyi 存根文件。

    Args:
        stub_name: 存根名（不含扩展名），如 ``chat`` / ``memory``

    Returns:
        解析后的 AST 模块；文件不存在时返回 None
    """
    path = _stub_path(stub_name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    return ast.parse(source, filename=path)


def list_available_stubs() -> List[str]:
    """列出 ``public/interface_stub/`` 下所有可用的 .pyi 存根名（不含扩展名）。"""
    stub_dir = _stub_dir()
    if not os.path.isdir(stub_dir):
        return []
    return [
        os.path.splitext(f)[0]
        for f in os.listdir(stub_dir)
        if f.endswith(".pyi")
    ]


# ---------------------------------------------------------------------------
# AST 解析辅助
# ---------------------------------------------------------------------------
def _ast_annotation_str(node: Optional[ast.expr]) -> Optional[str]:
    """将 AST 注解节点归一化为字符串（去空格）。"""
    if node is None:
        return None
    try:
        return _normalize_annotation(ast.unparse(node))
    except Exception:
        return None


def _normalize_annotation(ann: Optional[str]) -> Optional[str]:
    """归一化注解字符串：去空格、统一大小写无关的 None 表示。"""
    if ann is None:
        return None
    norm = ann.replace(" ", "")
    # 统一 Optional[X] 与 X | None 的常见变体（best-effort）
    norm = norm.replace("NoneType", "None")
    return norm


def _ast_func_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> List[str]:
    """提取 AST 函数定义的参数名列表（顺序敏感，含 posonly/kwonly/vararg/kwarg）。"""
    params: List[str] = []
    a = node.args
    for arg in a.posonlyargs:
        params.append(arg.arg)
    for arg in a.args:
        params.append(arg.arg)
    if a.vararg:
        params.append(f"*{a.vararg.arg}")
    for arg in a.kwonlyargs:
        params.append(arg.arg)
    if a.kwarg:
        params.append(f"**{a.kwarg.arg}")
    return params


def _ast_func_param_annotations(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    """提取 AST 函数各参数的归一化注解字符串。"""
    anns: dict = {}
    a = node.args
    for arg in a.posonlyargs:
        anns[arg.arg] = _ast_annotation_str(arg.annotation)
    for arg in a.args:
        anns[arg.arg] = _ast_annotation_str(arg.annotation)
    if a.vararg:
        anns[f"*{a.vararg.arg}"] = _ast_annotation_str(a.vararg.annotation)
    for arg in a.kwonlyargs:
        anns[arg.arg] = _ast_annotation_str(arg.annotation)
    if a.kwarg:
        anns[f"**{a.kwarg.arg}"] = _ast_annotation_str(a.kwarg.annotation)
    return anns


def _ast_func_return(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Optional[str]:
    """提取 AST 函数返回注解。"""
    return _ast_annotation_str(node.returns)


def _find_func_in_module(
    module: ast.Module, func_name: str
) -> Optional[ast.FunctionDef | ast.AsyncFunctionDef]:
    """在模块顶层查找指定名称的函数定义（含 async）。"""
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return node
    return None


def _find_class_in_module(module: ast.Module, class_name: str) -> Optional[ast.ClassDef]:
    """在模块顶层查找指定名称的类定义。"""
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    return None


def _class_methods(cls_node: ast.ClassDef) -> List[ast.FunctionDef | ast.AsyncFunctionDef]:
    """提取类中所有方法定义（含 async）。"""
    return [
        n
        for n in cls_node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


# ---------------------------------------------------------------------------
# 实际函数签名提取（inspect）
# ---------------------------------------------------------------------------
def _inspect_params(func: Callable) -> List[str]:
    """用 inspect 提取实际函数参数名列表（顺序敏感）。"""
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return []
    params: List[str] = []
    for name, p in sig.parameters.items():
        if p.kind == inspect.Parameter.VAR_POSITIONAL:
            params.append(f"*{name}")
        elif p.kind == inspect.Parameter.VAR_KEYWORD:
            params.append(f"**{name}")
        else:
            params.append(name)
    return params


def _inspect_param_annotations(func: Callable) -> dict:
    """提取实际函数各参数的归一化注解字符串。"""
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return {}
    anns: dict = {}
    for name, p in sig.parameters.items():
        key = f"*{name}" if p.kind == inspect.Parameter.VAR_POSITIONAL else (
            f"**{name}" if p.kind == inspect.Parameter.VAR_KEYWORD else name
        )
        ann = p.annotation
        ann_str = _normalize_annotation(
            ann if isinstance(ann, str) else (getattr(ann, "__name__", None) or str(ann))
            if ann is not inspect.Parameter.empty
            else None
        )
        anns[key] = ann_str
    return anns


def _inspect_return(func: Callable) -> Optional[str]:
    """提取实际函数返回注解。"""
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return None
    ann = sig.return_annotation
    if ann is inspect.Signature.empty:
        return None
    return _normalize_annotation(
        ann if isinstance(ann, str) else (getattr(ann, "__name__", None) or str(ann))
    )


# ---------------------------------------------------------------------------
# 公共匹配 API
# ---------------------------------------------------------------------------
def match_signature(
    func: Callable,
    stub_name: str,
    func_name: str,
    strict: bool = False,
) -> SignatureMatchResult:
    """验证函数签名是否匹配存根定义。

    Args:
        func: 待验证的实际可调用对象
        stub_name: 存根名（不含扩展名），如 ``chat``
        func_name: 存根中待匹配的函数名
        strict: 为 True 时要求参数注解与返回注解也匹配

    Returns:
        SignatureMatchResult
    """
    module = load_stub(stub_name)
    if module is None:
        return SignatureMatchResult(
            matched=False,
            stub_found=False,
            func_found=False,
            stub_name=stub_name,
            func_name=func_name,
            message=f"存根文件不存在: {stub_name}.pyi",
        )

    stub_func = _find_func_in_module(module, func_name)
    if stub_func is None:
        return SignatureMatchResult(
            matched=False,
            stub_found=True,
            func_found=False,
            stub_name=stub_name,
            func_name=func_name,
            message=f"存根中未找到函数: {func_name}",
        )

    stub_params = _ast_func_params(stub_func)
    actual_params = _inspect_params(func)

    missing = [p for p in stub_params if p not in actual_params]
    extra = [p for p in actual_params if p not in stub_params]
    param_names_match = not missing and not extra

    # 注解差异（best-effort，不影响默认 matched）
    stub_anns = _ast_func_param_annotations(stub_func)
    actual_anns = _inspect_param_annotations(func)
    annotation_diffs: List[str] = []
    for p in stub_params:
        s = stub_anns.get(p)
        a = actual_anns.get(p)
        if s is not None and a is not None and s != a:
            annotation_diffs.append(f"参数 '{p}': 存根={s!r} 实际={a!r}")
        elif s is not None and a is None:
            annotation_diffs.append(f"参数 '{p}': 存根={s!r} 实际未标注")

    # 返回注解差异
    stub_ret = _ast_func_return(stub_func)
    actual_ret = _inspect_return(func)
    return_diff: Optional[str] = None
    if stub_ret is not None and actual_ret is not None and stub_ret != actual_ret:
        return_diff = f"返回注解: 存根={stub_ret!r} 实际={actual_ret!r}"
    elif stub_ret is not None and actual_ret is None:
        return_diff = f"返回注解: 存根={stub_ret!r} 实际未标注"

    matched = param_names_match
    if strict:
        matched = matched and not annotation_diffs and return_diff is None

    if matched:
        msg = f"函数 '{func_name}' 签名匹配存根 '{stub_name}'"
        if annotation_diffs or return_diff:
            msg += "（含注解差异，非 strict 模式下不影响匹配）"
    else:
        msg = f"函数 '{func_name}' 签名不匹配存根 '{stub_name}'"
        if missing:
            msg += f"；缺失参数 {missing}"
        if extra:
            msg += f"；多余参数 {extra}"

    return SignatureMatchResult(
        matched=matched,
        stub_found=True,
        func_found=True,
        stub_name=stub_name,
        func_name=func_name,
        stub_params=stub_params,
        actual_params=actual_params,
        missing_params=missing,
        extra_params=extra,
        annotation_diffs=annotation_diffs,
        return_diff=return_diff,
        message=msg,
    )


def match_class_signature(
    cls: type,
    stub_name: str,
    class_name: str,
    strict: bool = False,
) -> ClassSignatureMatchResult:
    """验证类签名是否匹配存根定义。

    逐方法调用 ``match_signature`` 比较存根类中声明的方法。

    Args:
        cls: 待验证的实际类
        stub_name: 存根名（不含扩展名）
        class_name: 存根中待匹配的类名
        strict: 为 True 时要求方法注解也匹配

    Returns:
        ClassSignatureMatchResult
    """
    module = load_stub(stub_name)
    if module is None:
        return ClassSignatureMatchResult(
            matched=False,
            stub_found=False,
            class_found=False,
            stub_name=stub_name,
            class_name=class_name,
            message=f"存根文件不存在: {stub_name}.pyi",
        )

    stub_class = _find_class_in_module(module, class_name)
    if stub_class is None:
        return ClassSignatureMatchResult(
            matched=False,
            stub_found=True,
            class_found=False,
            stub_name=stub_name,
            class_name=class_name,
            message=f"存根中未找到类: {class_name}",
        )

    method_results: List[SignatureMatchResult] = []
    missing_methods: List[str] = []
    all_matched = True

    for stub_method in _class_methods(stub_class):
        mname = stub_method.name
        actual_method = getattr(cls, mname, None)
        if actual_method is None:
            missing_methods.append(mname)
            all_matched = False
            method_results.append(
                SignatureMatchResult(
                    matched=False,
                    stub_found=True,
                    func_found=False,
                    stub_name=stub_name,
                    func_name=mname,
                    message=f"实际类 {cls.__name__} 缺失方法 {mname}",
                )
            )
            continue

        result = match_signature(actual_method, stub_name, mname, strict=strict)
        method_results.append(result)
        if not result.matched:
            all_matched = False

    if missing_methods:
        msg = f"类 '{class_name}' 缺失方法: {missing_methods}"
    elif all_matched:
        msg = f"类 '{class_name}' 全部方法签名匹配存根 '{stub_name}'"
    else:
        failed = [r.func_name for r in method_results if not r.matched]
        msg = f"类 '{class_name}' 部分方法签名不匹配: {failed}"

    return ClassSignatureMatchResult(
        matched=all_matched,
        stub_found=True,
        class_found=True,
        stub_name=stub_name,
        class_name=class_name,
        method_results=method_results,
        missing_methods=missing_methods,
        message=msg,
    )
