from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from gme_agent.interface_catalog import (
    generate_catalogs,
    list_interface_catalogs,
    load_interface_catalog,
)
from gme_agent.services.interface_catalog_service import (
    list_selectable_interface_catalogs,
    resolve_test_generation_selection,
    selectable_interface_catalog,
)
from gme_agent.services.orchestrator import Orchestrator
from gme_agent.settings.config import AgentConfig
from gme_agent.storage.db import AgentDb


class InterfaceCatalogGeneratorTests(unittest.TestCase):
    def test_generator_creates_one_validated_catalog_per_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acis_root = root / "symbols" / "acis_symbol"
            self._write_catalog(
                acis_root / "BASE_acis_symbol.csv",
                [
                    {
                        "ACIS头文件名": "vector.hxx",
                        "模块名": "基础",
                        "类型": "函数",
                        "元素唯一标识": "int parallel(const SPAvector &, const SPAvector &, const double)",
                        "父元素": "",
                    }
                ],
            )
            self._write_catalog(
                acis_root / "LAW_acis_symbol.csv",
                [
                    {
                        "ACIS头文件名": "law_base.hxx",
                        "模块名": "解方程",
                        "类型": "成员函数",
                        "元素唯一标识": "int law::zero(double) const",
                        "父元素": "law",
                    }
                ],
            )
            self._write(
                root / "tests/gme/src/base/vector_test.cpp",
                '''TEST_F(Base_VectorTest, ParallelOne) {
    RecordProperty("UniqueSymbol", "int parallel(const SPAvector &, const SPAvector &, const double)");
}

TEST_F(Base_VectorTest, ParallelTwo) {
    RecordProperty("UniqueSymbol", "int parallel(const SPAvector &, const SPAvector &, const double)");
}

TEST_F(Base_VectorTest, GmeOnly) {
    RecordProperty("UniqueSymbol", "GME");
}
''',
            )
            self._write(
                root / "tests/gme/src/laws/law_base_test.cpp",
                '''TEST_F(Laws_BaseTest, Zero) {
    RecordProperty("UniqueSymbol", "int law::zero(double) const");
}

TEST_F(Laws_BaseTest, NotRegistered) {
    RecordProperty("UniqueSymbol", "int law::missing() const");
}

TEST_F(Laws_BaseTest, MissingProperty) {
    EXPECT_TRUE(true);
}

TEST_F(Laws_BaseTest, Zero) {
    RecordProperty("UniqueSymbol", "int law::zero(double) const");
}
''',
            )
            output = root / "output"

            generated = generate_catalogs(root, root / "symbols", ["base", "laws"], output)

            self.assertEqual([catalog["module"] for _, catalog in generated], ["base", "laws"])
            base = json.loads((output / "base.json").read_text(encoding="utf-8"))
            laws = json.loads((output / "laws.json").read_text(encoding="utf-8"))

            self.assertEqual(base["summary"]["interface_count"], 1)
            self.assertEqual(base["summary"]["registered_symbol_occurrences"], 2)
            self.assertEqual(base["summary"]["special_symbol_occurrences"], 1)
            self.assertEqual(base["interfaces"][0]["name"], "parallel")
            self.assertEqual(base["interfaces"][0]["existing_test_count"], 2)
            self.assertEqual(base["interfaces"][0]["source_catalog"], "BASE_acis_symbol.csv")
            self.assertEqual(base["interfaces"][0]["target_file"], "tests/gme/src/base/vector_test.cpp")
            self.assertEqual(base["interfaces"][0]["test_suite"], "Base_VectorTest")

            self.assertEqual(laws["summary"]["interface_count"], 1)
            self.assertEqual(laws["summary"]["tests_with_multiple_unique_symbols"], 0)
            self.assertEqual(laws["summary"]["unregistered_symbol_occurrences"], 1)
            self.assertEqual(laws["summary"]["tests_without_unique_symbol"], 1)
            self.assertEqual(
                laws["excluded"]["unregistered_symbols"][0]["value"],
                "int law::missing() const",
            )

    def test_generator_reports_dynamic_and_ignores_commented_properties(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_catalog(
                root / "symbols/BASE_acis_symbol.csv",
                [
                    {
                        "ACIS头文件名": "base.hxx",
                        "模块名": "基础",
                        "类型": "函数",
                        "元素唯一标识": "int initialize_base()",
                        "父元素": "",
                    }
                ],
            )
            self._write(
                root / "tests/gme/src/base/base_test.cpp",
                '''// RecordProperty("UniqueSymbol", "int initialize_base()");
TEST_P(Base_Test, Dynamic) {
    RecordProperty("UniqueSymbol", unique_symbol_);
}
''',
            )

            generated = generate_catalogs(root, root / "symbols", ["base"], root / "out")
            catalog = generated[0][1]

            self.assertEqual(catalog["summary"]["interface_count"], 0)
            self.assertEqual(catalog["summary"]["record_property_occurrences"], 1)
            self.assertEqual(catalog["summary"]["dynamic_symbol_occurrences"], 1)

    def test_static_loader_lists_and_validates_catalogs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(
                root / "laws.json",
                json.dumps({"schema_version": 1, "module": "laws", "interfaces": []}),
            )

            self.assertEqual(list_interface_catalogs(root), ["laws"])
            self.assertEqual(load_interface_catalog("laws", root)["interfaces"], [])
            with self.assertRaises(ValueError):
                load_interface_catalog("../laws", root)

    def test_runtime_catalog_exposes_only_base_and_laws_grouped_by_cpp(self) -> None:
        index = list_selectable_interface_catalogs()

        self.assertEqual([item["module"] for item in index["modules"]], ["base", "laws"])
        laws = selectable_interface_catalog("laws")
        self.assertEqual(laws["summary"]["interface_count"], 587)
        self.assertEqual(laws["summary"]["file_count"], len(laws["files"]))
        self.assertTrue(all(file["path"].startswith("tests/gme/src/laws/") for file in laws["files"]))
        self.assertTrue(all(file["interfaces"] for file in laws["files"]))

        selected = [laws["files"][0]["interfaces"][0], laws["files"][1]["interfaces"][0]]
        selection = resolve_test_generation_selection(
            "laws",
            [item["id"] for item in selected],
            2,
            "cover tolerance boundaries",
        )
        self.assertEqual(selection["requested_test_count"], 4)
        self.assertEqual(selection["extra_requirements"], "cover tolerance boundaries")
        self.assertEqual(len(selection["target_files"]), 2)

    def test_runtime_catalog_rejects_unsupported_or_invalid_selection(self) -> None:
        with self.assertRaisesRegex(ValueError, "supports only"):
            selectable_interface_catalog("kernel")
        with self.assertRaisesRegex(ValueError, "must be a list"):
            resolve_test_generation_selection("base", {"unexpected": "value"}, 1)
        with self.assertRaisesRegex(ValueError, "at least one"):
            resolve_test_generation_selection("base", [], 1)
        with self.assertRaisesRegex(ValueError, "between 1 and 5"):
            resolve_test_generation_selection("base", ["missing"], 0)

    def test_orchestrator_persists_structured_selection_without_trusting_paths(self) -> None:
        catalog = selectable_interface_catalog("base")
        interface = catalog["files"][0]["interfaces"][0]
        with tempfile.TemporaryDirectory() as tmp:
            db = AgentDb(Path(tmp) / "agent.db")
            try:
                orchestrator = Orchestrator(AgentConfig(), db)
                with mock.patch.object(orchestrator, "_start_thread") as start_thread:
                    job = orchestrator.create_test_generation_job(
                        "base",
                        interface_ids=[interface["id"]],
                        tests_per_interface=2,
                        extra_requirements="cover a negative input",
                    )

                self.assertEqual(job["metadata"]["selected_interface_ids"], [interface["id"]])
                self.assertEqual(job["metadata"]["selected_target_files"], [interface["target_file"]])
                self.assertEqual(job["metadata"]["requested_test_count"], 2)
                self.assertEqual(
                    job["metadata"]["selected_interfaces"][0]["unique_symbol"],
                    interface["unique_symbol"],
                )
                selection = start_thread.call_args.args[-1]
                self.assertEqual(selection["interfaces"][0]["target_file"], interface["target_file"])
            finally:
                db.close()

    @staticmethod
    def _write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _write_catalog(path: Path, rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=["ACIS头文件名", "模块名", "类型", "元素唯一标识", "父元素"],
            )
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
