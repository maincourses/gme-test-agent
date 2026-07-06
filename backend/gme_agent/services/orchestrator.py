from __future__ import annotations

from pathlib import Path
from typing import Any
import threading
import uuid

from ..flows.bug_fix_flow import run_fix_job
from ..flows.build_test_flow import (
    record_failures,
    run_build_job,
    run_configure_and_build,
    run_tests,
    run_tests_job,
)
from ..flows.generated_test_edit_flow import delete_generated_tests
from ..flows.pr_flow import run_cleanup_job, run_pr_job
from ..flows.skip_pr_flow import run_skip_pr_job
from ..flows.test_generation_flow import run_test_extension_job, run_test_generation_job
from ..git.worktree import normalize_repo_path
from ..settings.config import AgentConfig
from ..storage.db import AgentDb
from .artifact_service import artifact_dir_for_job, write_job_artifacts
from .failure_service import failure_filter, update_failure_status
from .job_service import delete_job_record


class Orchestrator:
    def __init__(self, config: AgentConfig, db: AgentDb):
        self.config = config
        self.db = db

    def set_config(self, config: AgentConfig) -> None:
        self.config = config

    def create_test_generation_job(self, module: str, api_name: str) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        title = f"Generate {module} tests"
        target_repo = self._test_target_repo()
        job = self.db.create_job(
            job_id=job_id,
            job_type="test_generation",
            title=title,
            module=module,
            api_name=api_name,
            metadata={"target_repo": target_repo, "pr_strategy": self.config.pr_strategy},
        )
        self._start_thread(self._run_test_generation_job, job_id, module, api_name, target_repo)
        return job

    def extend_test_generation_job(self, job_id: str, api_name: str) -> dict[str, Any]:
        job = self.db.get_job(job_id)
        if job.get("type") != "test_generation":
            raise ValueError("Only test-generation jobs can be extended.")
        self._start_thread(self._run_test_extension_job, job_id, api_name)
        return job

    def create_fix_job(self, failure_id: str) -> dict[str, Any]:
        failure = self.db.get_failure(failure_id)
        source_job = self.db.get_job(failure["job_id"]) if failure.get("job_id") else {}
        module = str(source_job.get("module") or failure.get("metadata", {}).get("module") or "")
        target_repo = self._module_target_repo(module) if module else "."
        job_id = str(uuid.uuid4())
        job = self.db.create_job(
            job_id=job_id,
            job_type="bug_fix",
            title=f"Fix {failure_id}",
            module=module,
            api_name="",
            metadata={"failure_id": failure_id, "target_repo": target_repo, "pr_strategy": self.config.pr_strategy},
        )
        failure_metadata = dict(failure.get("metadata") or {})
        failure_metadata["fix_job_id"] = job_id
        self.db.update_failure(failure_id, status="fixing", metadata=failure_metadata)
        self._start_thread(self._run_fix_job, job_id, failure)
        return job

    def run_tests_for_job(self, job_id: str, gtest_filter: str = "*") -> dict[str, Any]:
        job = self.db.get_job(job_id)
        self._start_thread(self._run_tests_job, job_id, gtest_filter)
        return job

    def build_job(self, job_id: str) -> dict[str, Any]:
        job = self.db.get_job(job_id)
        self._start_thread(self._run_build_job, job_id)
        return job

    def create_pr_for_job(self, job_id: str) -> dict[str, Any]:
        job = self.db.get_job(job_id)
        self._start_thread(self._run_pr_job, job_id)
        return job

    def create_skip_pr_for_job(self, job_id: str) -> dict[str, Any]:
        job = self.db.get_job(job_id)
        self._start_thread(self._run_skip_pr_job, job_id)
        return job

    def cleanup_job_worktree(self, job_id: str) -> dict[str, Any]:
        job = self.db.get_job(job_id)
        self._start_thread(self._run_cleanup_job, job_id)
        return job

    def delete_job(self, job_id: str, *, cleanup_worktree: bool = True, delete_artifacts: bool = True) -> dict[str, Any]:
        return delete_job_record(self, job_id, cleanup_worktree=cleanup_worktree, delete_artifacts=delete_artifacts)

    def delete_generated_tests_for_job(self, job_id: str, tests: list[dict[str, str]]) -> dict[str, Any]:
        return delete_generated_tests(self, job_id, tests)

    def update_failure_status(self, failure_id: str, status: str) -> dict[str, Any]:
        return update_failure_status(self.db, failure_id, status)

    def _start_thread(self, target, *args) -> None:
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()

    def _emit(self, job_id: str, level: str, message: str) -> None:
        self.db.add_event(job_id, level, message)

    def _job_emit(self, job_id: str):
        return lambda level, message: self._emit(job_id, level, message)

    def _run_test_generation_job(self, job_id: str, module: str, api_name: str, target_repo: str) -> None:
        run_test_generation_job(self, job_id, module, api_name, target_repo)

    def _run_test_extension_job(self, job_id: str, api_name: str) -> None:
        run_test_extension_job(self, job_id, api_name)

    def _run_fix_job(self, job_id: str, failure: dict[str, Any]) -> None:
        run_fix_job(self, job_id, failure)

    def _run_tests_job(self, job_id: str, gtest_filter: str) -> None:
        run_tests_job(self, job_id, gtest_filter)

    def _run_build_job(self, job_id: str) -> None:
        run_build_job(self, job_id)

    def _run_cleanup_job(self, job_id: str) -> None:
        run_cleanup_job(self, job_id)

    def _run_pr_job(self, job_id: str) -> None:
        run_pr_job(self, job_id)

    def _run_skip_pr_job(self, job_id: str) -> None:
        run_skip_pr_job(self, job_id)

    def _run_configure_and_build(self, job_id: str, worktree: Path) -> str:
        return run_configure_and_build(self, job_id, worktree)

    def _run_tests(
        self,
        job_id: str,
        worktree: Path,
        gtest_filter: str,
        *,
        artifact_name: str = "gtest_output.txt",
    ) -> str:
        return run_tests(self, job_id, worktree, gtest_filter, artifact_name=artifact_name)

    def _record_failures(self, job_id: str, test_output: str, gtest_filter: str, *, artifact_dir: Path) -> list[dict[str, Any]]:
        return record_failures(self, job_id, test_output, gtest_filter, artifact_dir=artifact_dir)

    def _artifact_dir(self, job_id: str) -> Path:
        return artifact_dir_for_job(self.config, job_id)

    def _command_mapping(self, worktree: Path, build_dir: Path, gtest_filter: str, *, artifact_dir: Path | None = None) -> dict[str, str]:
        artifact_dir = artifact_dir or Path(self.config.artifact_root)
        gtest_xml_path = self._gtest_xml_path(artifact_dir)
        module_name = self._current_job_module_for_artifact(artifact_dir)
        develop_module_option = self._develop_module_option(module_name)
        test_module_option = self._test_module_option(module_name)
        test_executable = self.config.test_executable.format(
            worktree=str(worktree),
            build_dir=str(build_dir),
            gtest_filter=gtest_filter,
            test_module_name=module_name,
            develop_module_option=develop_module_option,
            test_module_option=test_module_option,
            artifact_dir=str(artifact_dir),
            gtest_xml_path=str(gtest_xml_path),
        )
        return {
            "worktree": str(worktree),
            "build_dir": str(build_dir),
            "gtest_filter": gtest_filter,
            "test_executable": test_executable,
            "test_module_name": module_name,
            "develop_module_option": develop_module_option,
            "test_module_option": test_module_option,
            "artifact_dir": str(artifact_dir),
            "gtest_xml_path": str(gtest_xml_path),
        }

    def _reproduce_command(self, gtest_filter: str) -> str:
        build_dir = "{build_dir}"
        test_executable = self.config.test_executable.format(
            worktree="{worktree}",
            build_dir=build_dir,
            gtest_filter=gtest_filter,
            test_module_name="{test_module_name}",
            develop_module_option="{develop_module_option}",
            test_module_option="{test_module_option}",
            artifact_dir="{artifact_dir}",
            gtest_xml_path="{gtest_xml_path}",
        )
        return self.config.test_command.format(
            worktree="{worktree}",
            build_dir=build_dir,
            gtest_filter=gtest_filter,
            test_executable=test_executable,
            test_module_name="{test_module_name}",
            develop_module_option="{develop_module_option}",
            test_module_option="{test_module_option}",
            artifact_dir="{artifact_dir}",
            gtest_xml_path="{gtest_xml_path}",
        )

    def _gtest_xml_path(self, artifact_dir: Path) -> Path:
        return Path(
            self.config.gtest_xml_path.format(
                artifact_dir=str(artifact_dir),
                worktree="{worktree}",
                build_dir="{build_dir}",
                test_executable="{test_executable}",
                gtest_filter="{gtest_filter}",
                test_module_name="{test_module_name}",
                develop_module_option="{develop_module_option}",
                test_module_option="{test_module_option}",
            )
        )

    def _current_job_module_for_artifact(self, artifact_dir: Path) -> str:
        job_id = artifact_dir.name
        try:
            job = self.db.get_job(job_id)
        except Exception:
            return ""
        return normalize_repo_path(str(job.get("module") or "")).replace("/", "_")

    @staticmethod
    def _test_module_option(module_name: str) -> str:
        normalized = "".join(ch if ch.isalnum() else "_" for ch in module_name).strip("_")
        if not normalized:
            return ""
        return f"-DTEST_{normalized.upper()}=ON"

    @staticmethod
    def _develop_module_option(module_name: str) -> str:
        normalized = "".join(ch if ch.isalnum() else "_" for ch in module_name).strip("_")
        if not normalized:
            return ""
        return f"-DDEVELOP_{normalized.upper()}=ON"

    def _write_job_artifacts(self, job_id: str, worktree: Path, artifact_dir: Path) -> None:
        write_job_artifacts(self, job_id, worktree, artifact_dir)

    def _merge_metadata(self, job_id: str, extra: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(self.db.get_job(job_id).get("metadata") or {})
        metadata.update(extra)
        return metadata

    def _target_metadata(self, superproject_branch: str, target) -> dict[str, str]:
        return {
            "superproject_branch": superproject_branch,
            "target_repo": target.rel_path,
            "target_repo_path": str(target.path),
            "target_branch": target.branch,
            "target_base_branch": target.base_branch,
        }

    def _test_target_repo(self) -> str:
        return normalize_repo_path(self.config.test_target_repo)

    def _test_skill_names(self) -> list[str]:
        names = [
            self.config.test_generation_skill,
            "gme-module-test-analyzer",
            "gme-acis-interface-analyzer",
            "gme-test-writer",
        ]
        result = []
        for name in names:
            if name and name not in result:
                result.append(name)
        return result

    def _bug_fix_skill_names(self) -> list[str]:
        return [self.config.bug_fix_skill] if self.config.bug_fix_skill else []

    def _module_target_repo(self, module: str) -> str:
        module = normalize_repo_path(module)
        if module == ".":
            return "."
        return normalize_repo_path(f"{normalize_repo_path(self.config.module_repo_root)}/{module}")

    def _job_target_repo(self, job: dict[str, Any]) -> str:
        metadata = job.get("metadata") or {}
        if metadata.get("target_repo"):
            return normalize_repo_path(metadata["target_repo"])
        if job.get("type") == "test_generation":
            return self._test_target_repo()
        module = str(job.get("module") or "")
        return self._module_target_repo(module) if module else "."

    @staticmethod
    def _target_repo_path(worktree: Path, target_repo: str) -> Path:
        target_repo = normalize_repo_path(target_repo)
        return worktree if target_repo == "." else worktree / target_repo

    @staticmethod
    def _failure_filter(failure: dict[str, Any]) -> str:
        return failure_filter(failure)

    def _pr_body(self, job: dict[str, Any]) -> str:
        metadata = job.get("metadata") or {}
        return "\n".join(
            [
                f"Automated GME Test Agent job: `{job['id']}`",
                "",
                f"Type: `{job['type']}`",
                f"Status before PR: `{job['status']}`",
                f"Module: `{job.get('module') or ''}`",
                f"API: `{job.get('api_name') or ''}`",
                f"Target repo: `{metadata.get('target_repo') or self._job_target_repo(job)}`",
                "",
                "Review the generated artifacts and logs in the local agent UI.",
            ]
        )
