from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import ALLOWED_STRATEGY_EXTENSIONS, MAX_IMPORT_BYTES

PYTHON_CHECKER = r'''
import ast, json, sys
src = sys.stdin.read()
try:
    tree = ast.parse(src, mode="exec")
    compile(tree, "<strategy-review>", "exec", dont_inherit=True)
    imports = {n.name.split(".")[0] for n in ast.walk(tree)
               if isinstance(n, ast.Import) for n in n.names}
    imports.update(n.module.split(".")[0] for n in ast.walk(tree)
                   if isinstance(n, ast.ImportFrom) and n.module)
    imports = sorted(imports)
    risky = sorted(set(imports) & {"ctypes", "subprocess", "socket", "requests", "urllib",
                                   "http", "os", "shutil", "importlib", "pickle"})
    dynamic = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id in {"eval", "exec", "compile", "__import__"} for n in ast.walk(tree))
    print(json.dumps({"ok": True, "imports": sorted(imports), "risky_imports": risky,
                      "dynamic_execution": dynamic}))
except (SyntaxError, ValueError, MemoryError) as exc:
    print(json.dumps({"ok": False, "error": str(exc)}))
'''


def validate_strategy(filename: str, source: str) -> dict[str, Any]:
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_STRATEGY_EXTENSIONS:
        return {"ok": False, "kind": "unsupported", "summary": "Formato não suportado. Use .mq5, .py ou .txt.", "warnings": []}
    if not source.strip():
        return {"ok": False, "kind": extension[1:], "summary": "O arquivo está vazio.", "warnings": []}
    if len(source.encode("utf-8")) > MAX_IMPORT_BYTES:
        return {"ok": False, "kind": extension[1:], "summary": "O arquivo excede o limite de 1 MB.", "warnings": []}
    if extension == ".py":
        result = _validate_python(source)
    elif extension == ".mq5":
        result = _validate_mql5(source)
    else:
        result = _validate_text_file(source)
    return _add_adaptation(result, filename, source)


def _add_adaptation(result: dict[str, Any], filename: str, source: str) -> dict[str, Any]:
    """Describe how source enters the catalog; never convert or execute it as a rule."""
    language = _detect_language(Path(filename).suffix.lower(), source)
    names = re.findall(r"\bname\s*=\s*['\"]([^'\"]{2,120})['\"]", source, re.IGNORECASE)
    suggested_name = max(names, key=len).strip() if names else Path(filename).stem.replace("_", " ").replace("-", " ").title()
    labels = re.findall(r"['\"]([^'\"]{2,50}(?:BUY|SELL|COMPRA|VENDA)[^'\"]*)['\"]", source, re.IGNORECASE)
    unique_labels = list(dict.fromkeys(label.strip() for label in labels))[:6]
    inferred_rules: list[str] = []
    if re.search(r"is_bearish\s*\(\s*2\s*\).*is_bullish\s*\(\s*1\s*\).*is_bullish\s*\(\s*0\s*\)", source, re.IGNORECASE | re.DOTALL):
        inferred_rules.append("Compra: candle 2 baixista, seguido por candles 1 e 0 altistas.")
    if re.search(r"is_bullish\s*\(\s*2\s*\).*is_bearish\s*\(\s*1\s*\).*is_bearish\s*\(\s*0\s*\)", source, re.IGNORECASE | re.DOTALL):
        inferred_rules.append("Venda: candle 2 altista, seguido por candles 1 e 0 baixistas.")
    signals = " ".join(inferred_rules + ([f"Rótulos: {', '.join(unique_labels)}."] if unique_labels else []))
    signals = signals or "Nenhum sinal extraído com segurança; revisar as condições no arquivo."
    text_excerpt = ""
    if Path(filename).suffix.lower() == ".txt" and language == "texto descritivo":
        excerpt = " ".join(source.split())[:1_200]
        text_excerpt = f"\nTrecho do texto para revisão: {excerpt}"
    warnings = list(result.get("warnings", []))
    if "plot_shape(" in source or "plotshape(" in source.lower():
        warnings.append("O arquivo desenha indicadores/sinais; isso não equivale a uma regra de envio de ordens.")
    if len(re.findall(r"\binstrument\s*\{", source, re.IGNORECASE)) > 1:
        warnings.append("Há mais de um bloco de instrumento no arquivo; confirme se são regras separadas ou duplicadas.")
    for variable in ("buyCondition", "sellCondition"):
        if len(re.findall(rf"\b{variable}\s*=", source, re.IGNORECASE)) > 1:
            warnings.append(f"A variável {variable} recebe mais de uma atribuição; confirme qual condição deve prevalecer.")
    if re.search(r"\[[ \t]*0[ \t]*\]|\([ \t]*0[ \t]*\)", source):
        warnings.append("Há referência provável ao candle atual; confirme se o sinal muda antes do fechamento (repaint).")
    if result.get("ok"):
        result["warnings"] = list(dict.fromkeys(warnings))
    result["adaptation"] = {
        "language": language,
        "suggested_name": suggested_name[:120] or "Estratégia importada",
        "engine_compatible": False,
        "status": "needs_manual_review",
        "suggested_description": (
            f"Arquivo importado: {Path(filename).name}\n"
            f"Formato identificado: {language}.\n"
            f"Elementos de sinal detectados: {signals}\n"
            "Importação para o catálogo ScalperLab: regras, ativo, período, entradas, saídas, stop, alvo e risco "
            "precisam ser confirmados e estruturados manualmente. O código original foi preservado para revisão; "
            "não foi executado nem convertido em regra operacional."
            f"{text_excerpt}"
        ),
    }
    return result


def _detect_language(extension: str, source: str) -> str:
    lowered = source.lower()
    if extension == ".mq5":
        return "MQL5"
    if extension == ".py":
        return "Python"
    if any(marker in lowered for marker in ("instrument {", "instrument{", "plot_shape(", "conditional(", "input_group")):
        return "Quadcode/Lua ou DSL de indicador semelhante"
    if any(marker in lowered for marker in ("void ontick", "int oninit", "#property", "order_send")):
        return "código semelhante a MQL5/Python (arquivo .txt)"
    if any(marker in lowered for marker in ("def ", "import ", "class ")):
        return "código semelhante a Python (arquivo .txt)"
    return "texto descritivo"


def _validate_text_file(source: str) -> dict[str, Any]:
    language = _detect_language(".txt", source)
    summary = ("Script textual reconhecido para análise estática; nenhuma sintaxe específica foi compilada."
               if language != "texto descritivo" else
               "Texto importado para o catálogo; organize manualmente as condições da estratégia.")
    return {"ok": True, "kind": "txt", "summary": summary, "warnings": []}


def _validate_python(source: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-c", PYTHON_CHECKER],
            input=source, text=True, capture_output=True, timeout=3, check=False,
            env={"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"ok": False, "kind": "py", "summary": "A análise isolada não terminou no limite de tempo.", "warnings": []}
    try:
        report = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"ok": False, "kind": "py", "summary": "Não foi possível analisar a sintaxe Python.", "warnings": []}
    if not report.get("ok"):
        return {"ok": False, "kind": "py", "summary": "Erro de sintaxe Python: " + str(report.get("error", "desconhecido"))[:240], "warnings": []}
    warnings = []
    if report.get("risky_imports"):
        warnings.append("Importações com acesso externo ou ao sistema: " + ", ".join(report["risky_imports"]))
    if report.get("dynamic_execution"):
        warnings.append("Foi detectado uso de execução dinâmica de código.")
    return {"ok": True, "kind": "py", "summary": "Sintaxe Python válida; o código não foi executado.",
            "warnings": warnings, "imports": report.get("imports", [])}


def _validate_mql5(source: str) -> dict[str, Any]:
    pairs = {"{": "}", "(": ")", "[": "]"}
    stack: list[str] = []
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = 0
    while index < len(source):
        char = source[index]
        nxt = source[index + 1] if index + 1 < len(source) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
        elif block_comment:
            if char == "*" and nxt == "/":
                block_comment = False
                index += 1
        elif quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char == "/" and nxt == "/":
            line_comment = True
            index += 1
        elif char == "/" and nxt == "*":
            block_comment = True
            index += 1
        elif char in {"'", '"'}:
            quote = char
        elif char in pairs:
            stack.append(pairs[char])
        elif char in pairs.values():
            if not stack or stack.pop() != char:
                return {"ok": False, "kind": "mq5", "summary": "Delimitadores MQL5 não estão balanceados.", "warnings": []}
        index += 1
    if stack or quote or block_comment:
        return {"ok": False, "kind": "mq5", "summary": "Código MQL5 incompleto: delimitador, texto ou comentário aberto.", "warnings": []}
    warnings = []
    if "WebRequest(" in source or "ShellExecute" in source or "#import" in source:
        warnings.append("O arquivo contém chamada externa ou importação nativa; exige revisão de segurança.")
    if "int OnInit" not in source and "void OnStart" not in source and "void OnTick" not in source:
        warnings.append("Não foi identificada uma função de entrada Expert Advisor/Script comum.")
    return {"ok": True, "kind": "mq5", "summary": "Estrutura e delimitadores MQL5 parecem consistentes; compilação não executada.", "warnings": warnings}
