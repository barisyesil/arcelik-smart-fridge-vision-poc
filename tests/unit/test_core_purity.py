"""core/ paketinde AWS importu olmadığını makineye zorlatır.

AST ile taradığımız için `import boto3` string'ini bir yorumda görmekten değil, gerçek
bir import ifadesinden şikâyet eder.
"""

from __future__ import annotations

import ast
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parents[2] / "src" / "core"
FORBIDDEN_ROOTS = {"boto3", "botocore", "aws_cdk", "aws_lambda_powertools", "constructs"}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_has_no_aws_imports():
    offenders = {
        path.name: sorted(bad)
        for path in sorted(CORE_DIR.rglob("*.py"))
        if (bad := _imported_roots(path) & FORBIDDEN_ROOTS)
    }
    assert not offenders, f"core/ içinde AWS importu var: {offenders}"


def test_core_does_not_import_handlers_or_adapters():
    """Bağımlılık yönü tek taraflı: handlers/adapters -> core, tersi asla."""
    offenders = {
        path.name: sorted(bad)
        for path in sorted(CORE_DIR.rglob("*.py"))
        if (bad := _imported_roots(path) & {"handlers", "adapters", "infra"})
    }
    assert not offenders, f"core/ dışa bağımlı hale gelmiş: {offenders}"
