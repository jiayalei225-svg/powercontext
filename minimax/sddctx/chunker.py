"""工程资料切分器。

把三类异构资料切成**可检索、可追溯**的单元，每个单元都带 ``source``
（文件路径 + 行号 / 条目编号），保证上下文输出里的来源真实可核对：

- 规格文档 → 规格条目（``SPEC-XXX-000``），带 ``priority`` / ``code_refs`` 元数据
- Python 源码 → 符号（模块 / 类 / 函数），带行号区间与签名
- 测试文件 → 测试用例，并自动从 docstring 里抽取它覆盖的规格条目
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CLAUSE_HEADING = re.compile(r"^###\s+(SPEC-[A-Z]+-\d{3}(?:\.\d+)?)\s+(.+?)\s*$")
META_COMMENT = re.compile(r"<!--\s*meta:\s*(.+?)\s*-->", re.S)


@dataclass
class SpecItem:
    id: str
    title: str
    text: str
    doc_id: str
    spec_version: str
    path: str
    start_line: int
    end_line: int
    priority: str = "normal"
    code_refs: list[str] = field(default_factory=list)
    suite: str = "functional"

    @property
    def source(self) -> str:
        return f"{self.path}#{self.id}"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "kind": "spec",
            "item_id": self.id,
            "title": self.title,
            "doc_id": self.doc_id,
            "spec_version": self.spec_version,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "priority": self.priority,
            "suite": self.suite,
            "code_refs": ",".join(self.code_refs),
            "source": self.source,
            "covers": "",
        }

    def index_text(self) -> str:
        refs = " ".join(self.code_refs)
        return f"{self.id} {self.title}\n{self.text}\n{refs}"


@dataclass
class CodeSymbol:
    symbol: str
    kind: str
    path: str
    start_line: int
    end_line: int
    signature: str
    docstring: str
    text: str

    @property
    def source(self) -> str:
        return f"{self.path}::{self.symbol}"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "kind": "code",
            "item_id": self.source,
            "symbol": self.symbol,
            "code_kind": self.kind,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "signature": self.signature,
            "source": self.source,
            "code_refs": "",
            "priority": "normal",
            "doc_id": "",
            "spec_version": "",
            "title": self.symbol,
            "covers": "",
            "suite": "",
        }

    def index_text(self) -> str:
        return f"{self.symbol}\n{self.signature}\n{self.docstring}\n{self.text}"


@dataclass
class TestCase:
    name: str
    path: str
    start_line: int
    end_line: int
    docstring: str
    text: str
    covers: list[str] = field(default_factory=list)

    @property
    def source(self) -> str:
        return f"{self.path}::{self.name}"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "kind": "test",
            "item_id": self.name,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "covers": ",".join(self.covers),
            "source": self.source,
            "code_refs": "",
            "priority": "normal",
            "doc_id": "",
            "spec_version": "",
            "title": self.name,
        }

    def index_text(self) -> str:
        return f"{self.name}\n{self.docstring}\n{self.text}"


def _parse_front_matter(raw: str) -> tuple[dict[str, Any], int]:
    """解析极简 front matter，返回 (字段, 正文起始行号)。"""
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, 0
    data: dict[str, Any] = {}
    current_key: str | None = None
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            return data, index + 1
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and current_key:
            data.setdefault(current_key, [])
            if isinstance(data[current_key], list):
                data[current_key].append(line.lstrip()[2:].strip())
            continue
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            current_key = key.strip()
            data[current_key] = value.strip()
    return data, 0


def _parse_meta(block: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for part in block.split(";"):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        meta[key.strip()] = value.strip()
    return meta


def parse_spec_file(path: Path, root: Path) -> tuple[dict[str, Any], list[SpecItem]]:
    """解析一份规格文档，返回 (文档级元数据, 规格条目列表)。"""
    raw = path.read_text(encoding="utf-8")
    front, body_start = _parse_front_matter(raw)
    rel = path.relative_to(root).as_posix()
    lines = raw.splitlines()

    doc_id = str(front.get("spec_id") or path.stem)
    version = str(front.get("version") or "0.0.0")

    items: list[SpecItem] = []
    current: tuple[str, str, int] | None = None
    buffer: list[str] = []

    def flush(end_line: int) -> None:
        nonlocal current, buffer
        if current is None:
            return
        clause_id, title, start = current
        body = "\n".join(buffer).strip()
        meta: dict[str, str] = {}
        match = META_COMMENT.search(body)
        if match:
            meta = _parse_meta(match.group(1))
            body = META_COMMENT.sub("", body).strip()
        refs = [ref.strip() for ref in meta.get("code_refs", "").split(",") if ref.strip()]
        items.append(
            SpecItem(
                id=clause_id,
                title=title,
                text=body,
                doc_id=doc_id,
                spec_version=version,
                path=rel,
                start_line=start,
                end_line=end_line,
                priority=meta.get("priority", "normal"),
                code_refs=refs,
                suite=meta.get("suite", "functional"),
            )
        )
        current = None
        buffer = []

    for index in range(body_start, len(lines)):
        line = lines[index]
        match = CLAUSE_HEADING.match(line)
        if match:
            flush(index)
            current = (match.group(1), match.group(2), index + 1)
            buffer = []
            continue
        if line.startswith("## ") and current is not None:
            flush(index)
            continue
        if current is not None:
            buffer.append(line)
    flush(len(lines))

    doc_meta = {
        "doc_id": doc_id,
        "version": version,
        "path": rel,
        "item_count": len(items),
    }
    return doc_meta, items


def _signature(node: ast.AST, source_lines: list[str]) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        args = ast.unparse(node.args) if hasattr(ast, "unparse") else ""
        returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
        return f"{prefix} {node.name}({args}){returns}"
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(base) for base in node.bases)
        return f"class {node.name}({bases})" if bases else f"class {node.name}"
    return node.__class__.__name__


def parse_python_symbols(path: Path, root: Path, *, kind: str = "code") -> list[Any]:
    """解析 Python 文件的符号。

    ``kind="code"`` 产出 :class:`CodeSymbol`；``kind="test"`` 产出 :class:`TestCase`，
    并从 docstring 中抽取覆盖的规格条目编号。
    """
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    rel = path.relative_to(root).as_posix()
    try:
        tree = ast.parse(raw)
    except SyntaxError:
        return []

    results: list[Any] = []

    if kind == "code":
        module_doc = (ast.get_docstring(tree) or "").split("\n\n")[0]
        results.append(
            CodeSymbol(
                symbol=rel.replace("/", ".").removesuffix(".py"),
                kind="module",
                path=rel,
                start_line=1,
                end_line=len(lines),
                signature=f"module {rel}",
                docstring=module_doc,
                text="",
            )
        )

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}{child.name}"
                start = child.lineno
                end = getattr(child, "end_lineno", start) or start
                doc = (ast.get_docstring(child) or "").split("\n\n")[0]
                body_text = "\n".join(lines[start - 1 : end])
                if kind == "test":
                    if child.name.startswith("test"):
                        results.append(
                            TestCase(
                                name=qualname,
                                path=rel,
                                start_line=start,
                                end_line=end,
                                docstring=doc,
                                text=body_text,
                                covers=_spec_ids(doc + "\n" + body_text),
                            )
                        )
                    walk(child, qualname + ".")
                else:
                    if not child.name.startswith("__"):  # 跳过 dunder，减少检索噪声
                        results.append(
                            CodeSymbol(
                                symbol=qualname,
                                kind="function",
                                path=rel,
                                start_line=start,
                                end_line=end,
                                signature=_signature(child, lines),
                                docstring=doc,
                                text=body_text,
                            )
                        )
                    walk(child, qualname + ".")
            elif isinstance(child, ast.ClassDef):
                qualname = f"{prefix}{child.name}"
                start = child.lineno
                end = getattr(child, "end_lineno", start) or start
                if kind == "code":
                    results.append(
                        CodeSymbol(
                            symbol=qualname,
                            kind="class",
                            path=rel,
                            start_line=start,
                            end_line=end,
                            signature=_signature(child, lines),
                            docstring=(ast.get_docstring(child) or "").split("\n\n")[0],
                            text="\n".join(lines[start - 1 : min(start + 20, end)]),
                        )
                    )
                walk(child, qualname + ".")

    walk(tree, "")
    return results


def _spec_ids(text: str) -> list[str]:
    return sorted(set(re.findall(r"SPEC-[A-Z]+-\d{3}(?:\.\d+)?", text)))


def discover(root: Path, pattern: str) -> list[Path]:
    return sorted(p for p in root.rglob(pattern) if p.is_file() and ".venv" not in p.parts)
