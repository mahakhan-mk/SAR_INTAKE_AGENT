from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path
from types import UnionType
from typing import get_args, get_origin


PROTECTED_PACKAGE_DIRS = (
    Path("app/services"),
    Path("app/repositories"),
    Path("app/assemblers"),
    Path("app/llm"),
    Path("app/domain"),
    Path("app/application"),
)
SERVICE_PACKAGE_DIR = Path("app/services")
API_DEPENDENCIES_PATH = Path("app/dependencies/api.py")
WORKER_DEPENDENCIES_PATH = Path("app/dependencies/worker.py")
API_ROUTE_DIR = Path("app/api/v1")
FORBIDDEN_IMPORTS = ("app.api", "fastapi", "starlette")
FORBIDDEN_API_DEPENDENCY_CONSTRUCTIONS = (
    "AzureExecutiveSummaryClient",
    "DocumentChecklistExecutionService",
    "ExecutiveSummaryService",
    "InherentRiskExecutionService",
    "InitialSarReportGenerationService",
    "InitialSarReportRenderer",
    "get_azure_executive_summary_client",
    "get_document_checklist_execution_service",
    "get_executive_summary_service",
    "get_inherent_risk_execution_service",
    "get_initial_sar_report_generation_service",
    "get_initial_sar_report_renderer",
)
FORBIDDEN_WORKER_DEPENDENCY_IMPORTS = ("app.api", "app.assemblers", "fastapi")
EXECUTION_SERVICE_NAMES = (
    "DocumentChecklistExecutionService",
    "ExecutiveSummaryService",
    "InherentRiskExecutionService",
    "InitialSarReportGenerationService",
)
LEGACY_COMPOSITE_SERVICE_NAMES = (
    "AIAnalysisService",
    "DocumentChecklistService",
    "DocumentService",
    "InherentRiskService",
)


def test_business_layer_does_not_import_api_or_http_frameworks() -> None:
    violations: list[str] = []
    for package_dir in PROTECTED_PACKAGE_DIRS:
        for source_path in package_dir.rglob("*.py"):
            if _should_ignore(source_path):
                continue
            violations.extend(_find_forbidden_imports(source_path))

    assert not violations, "Forbidden imports found:\n" + "\n".join(sorted(violations))


def test_services_do_not_return_api_schema_classes() -> None:
    violations: list[str] = []
    for source_path in SERVICE_PACKAGE_DIR.rglob("*.py"):
        if _should_ignore(source_path):
            continue
        module = importlib.import_module(_module_name_from_path(source_path))
        for _, class_object in inspect.getmembers(module, inspect.isclass):
            if class_object.__module__ != module.__name__:
                continue
            for method_name, method in inspect.getmembers(class_object, inspect.isfunction):
                return_annotation = inspect.signature(method).return_annotation
                if return_annotation is inspect.Signature.empty:
                    continue
                if _annotation_uses_api_class(return_annotation):
                    violations.append(f"{class_object.__module__}.{class_object.__name__}.{method_name}")

    assert not violations, "Service methods return API schema classes:\n" + "\n".join(sorted(violations))


def test_api_dependency_providers_do_not_construct_worker_execution_dependencies() -> None:
    tree = _parse_source(API_DEPENDENCIES_PATH)
    violations: list[str] = []
    forbidden_names = set(FORBIDDEN_API_DEPENDENCY_CONSTRUCTIONS)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for imported_name in _imported_names_from_node(node):
                if imported_name in forbidden_names:
                    violations.append(f"{API_DEPENDENCIES_PATH}:{node.lineno} imports {imported_name}")
        elif isinstance(node, ast.Call):
            call_name = _call_name(node.func)
            if call_name in forbidden_names:
                violations.append(f"{API_DEPENDENCIES_PATH}:{node.lineno} constructs or calls {call_name}")

    assert not violations, "API dependency providers construct worker dependencies:\n" + "\n".join(sorted(violations))


def test_worker_dependency_module_has_no_api_or_fastapi_imports() -> None:
    violations = _find_imports_matching(WORKER_DEPENDENCIES_PATH, FORBIDDEN_WORKER_DEPENDENCY_IMPORTS)

    assert not violations, "Worker dependency module imports API/FastAPI concerns:\n" + "\n".join(sorted(violations))


def test_query_services_do_not_reference_execution_services() -> None:
    violations: list[str] = []
    execution_names = set(EXECUTION_SERVICE_NAMES)
    for source_path in SERVICE_PACKAGE_DIR.rglob("*.py"):
        if _should_ignore(source_path):
            continue
        tree = _parse_source(source_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not node.name.endswith("QueryService"):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and child.id in execution_names:
                    violations.append(f"{source_path}:{child.lineno} {node.name} references {child.id}")
                elif isinstance(child, ast.Attribute) and child.attr in execution_names:
                    violations.append(f"{source_path}:{child.lineno} {node.name} references {child.attr}")

    assert not violations, "Query services reference execution services:\n" + "\n".join(sorted(violations))


def test_api_routes_use_explicit_services_not_legacy_composites() -> None:
    violations: list[str] = []
    legacy_names = set(LEGACY_COMPOSITE_SERVICE_NAMES)
    for source_path in API_ROUTE_DIR.rglob("*.py"):
        if _should_ignore(source_path):
            continue
        tree = _parse_source(source_path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for imported_name in _imported_names_from_node(node):
                    if imported_name in legacy_names:
                        violations.append(f"{source_path}:{node.lineno} imports {imported_name}")
            elif isinstance(node, ast.Name) and node.id in legacy_names:
                violations.append(f"{source_path}:{node.lineno} references {node.id}")

    assert not violations, "API routes depend on legacy composite services:\n" + "\n".join(sorted(violations))


def _should_ignore(source_path: Path) -> bool:
    path_parts = set(source_path.parts)
    return (
        "__pycache__" in path_parts
        or "generated" in path_parts
        or source_path.name.endswith("_generated.py")
        or source_path.name.endswith("_pb2.py")
        or source_path.name.endswith("_pb2_grpc.py")
    )


def _find_forbidden_imports(source_path: Path) -> list[str]:
    tree = _parse_source(source_path)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_import(alias.name):
                    violations.append(f"{source_path}:{node.lineno} imports {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _is_forbidden_import(module) or _is_relative_api_import(node):
                imported = "." * node.level + module
                violations.append(f"{source_path}:{node.lineno} imports {imported}")
    return violations


def _find_imports_matching(source_path: Path, forbidden_imports: tuple[str, ...]) -> list[str]:
    tree = _parse_source(source_path)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _matches_import(alias.name, forbidden_imports):
                    violations.append(f"{source_path}:{node.lineno} imports {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _matches_import(module, forbidden_imports):
                imported = "." * node.level + module
                violations.append(f"{source_path}:{node.lineno} imports {imported}")
    return violations


def _parse_source(source_path: Path) -> ast.Module:
    return ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))


def _is_forbidden_import(module_name: str) -> bool:
    return _matches_import(module_name, FORBIDDEN_IMPORTS)


def _matches_import(module_name: str, forbidden_imports: tuple[str, ...]) -> bool:
    return any(module_name == forbidden or module_name.startswith(f"{forbidden}.") for forbidden in forbidden_imports)


def _is_relative_api_import(node: ast.ImportFrom) -> bool:
    module = node.module or ""
    return node.level > 0 and (module == "api" or module.startswith("api."))


def _module_name_from_path(source_path: Path) -> str:
    return ".".join(source_path.with_suffix("").parts)


def _annotation_uses_api_class(annotation: object) -> bool:
    if isinstance(annotation, str):
        return annotation.startswith("app.api.") or "DTO" in annotation

    module_name = getattr(annotation, "__module__", "")
    if module_name.startswith("app.api"):
        return True

    origin = get_origin(annotation)
    if origin is not None and _annotation_uses_api_class(origin):
        return True

    if isinstance(annotation, UnionType):
        return any(_annotation_uses_api_class(arg) for arg in annotation.__args__)

    return any(_annotation_uses_api_class(arg) for arg in get_args(annotation))


def _imported_names_from_node(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.asname or alias.name.split(".")[-1] for alias in node.names]
    return [alias.asname or alias.name for alias in node.names]


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""
