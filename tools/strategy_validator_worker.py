"""Small, isolated syntax checker bundled beside the frozen desktop app."""

from __future__ import annotations

import ast
import json
import sys


def main() -> int:
    source = sys.stdin.read()
    try:
        tree = ast.parse(source, mode="exec")
        compile(tree, "<strategy-review>", "exec", dont_inherit=True)
        imports = {node.name.split(".")[0] for node in ast.walk(tree)
                   if isinstance(node, ast.Import) for node in node.names}
        imports.update(node.module.split(".")[0] for node in ast.walk(tree)
                       if isinstance(node, ast.ImportFrom) and node.module)
        imports = sorted(imports)
        risky = sorted(set(imports) & {
            "ctypes", "subprocess", "socket", "requests", "urllib", "http", "os",
            "shutil", "importlib", "pickle",
        })
        dynamic = any(
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in {"eval", "exec", "compile", "__import__"}
            for node in ast.walk(tree)
        )
        report = {"ok": True, "imports": imports, "risky_imports": risky,
                  "dynamic_execution": dynamic}
    except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
        report = {"ok": False, "error": str(exc)}
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
