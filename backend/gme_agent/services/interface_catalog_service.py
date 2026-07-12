from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from ..interface_catalog import load_interface_catalog


SUPPORTED_TEST_MODULES = ("base", "laws")
MAX_SELECTED_INTERFACES = 20
MAX_TESTS_PER_INTERFACE = 5
MAX_EXTRA_REQUIREMENTS_LENGTH = 2000


def list_selectable_interface_catalogs() -> dict[str, Any]:
    modules: list[dict[str, Any]] = []
    for module in SUPPORTED_TEST_MODULES:
        catalog = load_interface_catalog(module)
        files = {str(item.get("target_file") or "") for item in catalog["interfaces"]}
        files.discard("")
        modules.append(
            {
                "module": module,
                "interface_count": len(catalog["interfaces"]),
                "file_count": len(files),
                "source_catalog_counts": dict(
                    (catalog.get("summary") or {}).get("source_catalog_counts") or {}
                ),
            }
        )
    return {
        "modules": modules,
        "max_selected_interfaces": MAX_SELECTED_INTERFACES,
        "max_tests_per_interface": MAX_TESTS_PER_INTERFACE,
    }


def selectable_interface_catalog(module: str) -> dict[str, Any]:
    normalized = _supported_module(module)
    catalog = load_interface_catalog(normalized)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in catalog["interfaces"]:
        interface = _selectable_interface(item)
        _validate_target_file(normalized, interface["target_file"])
        grouped[interface["target_file"]].append(interface)

    files = [
        {
            "path": path,
            "name": Path(path).name,
            "interface_count": len(interfaces),
            "interfaces": sorted(
                interfaces,
                key=lambda item: (item["name"].lower(), item["unique_symbol"]),
            ),
        }
        for path, interfaces in sorted(grouped.items())
    ]
    return {
        "schema_version": 1,
        "module": normalized,
        "summary": {
            "interface_count": len(catalog["interfaces"]),
            "file_count": len(files),
            "source_catalog_counts": dict(
                (catalog.get("summary") or {}).get("source_catalog_counts") or {}
            ),
        },
        "files": files,
        "max_selected_interfaces": MAX_SELECTED_INTERFACES,
        "max_tests_per_interface": MAX_TESTS_PER_INTERFACE,
    }


def resolve_test_generation_selection(
    module: str,
    interface_ids: Iterable[str],
    tests_per_interface: int,
    extra_requirements: str = "",
) -> dict[str, Any]:
    normalized = _supported_module(module)
    if not isinstance(interface_ids, (list, tuple)):
        raise ValueError("interface_ids must be a list of interface IDs")
    ids = [str(value or "").strip() for value in interface_ids]
    if not ids or any(not value for value in ids):
        raise ValueError("Select at least one interface")
    if len(ids) != len(set(ids)):
        raise ValueError("Selected interface IDs must be unique")
    if len(ids) > MAX_SELECTED_INTERFACES:
        raise ValueError(f"Select at most {MAX_SELECTED_INTERFACES} interfaces per task")
    if isinstance(tests_per_interface, bool) or not isinstance(tests_per_interface, int):
        raise ValueError("tests_per_interface must be an integer")
    if not 1 <= tests_per_interface <= MAX_TESTS_PER_INTERFACE:
        raise ValueError(
            f"tests_per_interface must be between 1 and {MAX_TESTS_PER_INTERFACE}"
        )

    requirements = str(extra_requirements or "").strip()
    if len(requirements) > MAX_EXTRA_REQUIREMENTS_LENGTH:
        raise ValueError(
            f"extra_requirements must not exceed {MAX_EXTRA_REQUIREMENTS_LENGTH} characters"
        )

    catalog = load_interface_catalog(normalized)
    by_id = {str(item.get("id") or ""): item for item in catalog["interfaces"]}
    missing = [interface_id for interface_id in ids if interface_id not in by_id]
    if missing:
        raise ValueError(
            f"Selected interfaces do not belong to module {normalized}: {', '.join(missing)}"
        )

    interfaces: list[dict[str, Any]] = []
    for interface_id in ids:
        interface = _selectable_interface(by_id[interface_id])
        _validate_target_file(normalized, interface["target_file"])
        interfaces.append(interface)

    target_files = list(dict.fromkeys(item["target_file"] for item in interfaces))
    return {
        "module": normalized,
        "interface_ids": ids,
        "interfaces": interfaces,
        "target_files": target_files,
        "tests_per_interface": tests_per_interface,
        "requested_test_count": len(interfaces) * tests_per_interface,
        "extra_requirements": requirements,
    }


def selection_title(selection: dict[str, Any]) -> str:
    interfaces = list(selection.get("interfaces") or [])
    names = [str(item.get("name") or item.get("unique_symbol") or "") for item in interfaces]
    preview = ", ".join(names[:3])
    if len(names) > 3:
        preview += f" +{len(names) - 3}"
    return preview or f"{selection.get('module') or 'module'} interfaces"


def merge_selected_interfaces(
    existing: Iterable[dict[str, Any]],
    added: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in [*existing, *added]:
        interface_id = str(item.get("id") or "")
        if interface_id:
            merged[interface_id] = dict(item)
    return list(merged.values())


def _selectable_interface(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "unique_symbol": str(item.get("unique_symbol") or ""),
        "source_catalog": str(item.get("source_catalog") or ""),
        "acis_header": str(item.get("acis_header") or ""),
        "kind": str(item.get("kind") or ""),
        "parent": str(item.get("parent") or ""),
        "target_file": str(item.get("target_file") or ""),
        "test_suite": str(item.get("test_suite") or ""),
        "existing_test_count": int(item.get("existing_test_count") or 0),
    }


def _supported_module(value: str) -> str:
    module = str(value or "").strip()
    if module not in SUPPORTED_TEST_MODULES:
        supported = ", ".join(SUPPORTED_TEST_MODULES)
        raise ValueError(f"Interface selection currently supports only: {supported}")
    return module


def _validate_target_file(module: str, value: str) -> None:
    path = value.replace("\\", "/").strip("/")
    expected_prefix = f"tests/gme/src/{module}/"
    if not path.startswith(expected_prefix) or not path.endswith((".cpp", ".cc", ".cxx")):
        raise ValueError(f"Interface catalog contains an invalid target file: {value}")

