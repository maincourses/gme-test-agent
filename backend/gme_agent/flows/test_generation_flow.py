from __future__ import annotations

from pathlib import Path

from ..codex.runner import CodexRunner
from ..generated_tests import ensure_generated_tests_use_existing_files, generated_test_filter, require_generated_tests_manifest
from ..git.diff import ensure_only_target_repo_changed
from ..git.repositories import prepare_target_repo, prepare_worktree_dependencies
from ..git.worktree import create_worktree
from ..prompts import continue_test_generation_prompt, skip_known_failure_prompt, test_generation_prompt


AGENT_NOTES_PATH = ".gme-agent"


def run_test_generation_job(ctx, job_id: str, module: str, api_name: str, target_repo: str) -> None:
    emit = ctx._job_emit(job_id)
    try:
        ctx.db.update_job(job_id, status="creating_worktree")
        worktree = create_worktree(ctx.config, job_id, f"testgen-{module}", emit)
        prepared_paths = prepare_worktree_dependencies(ctx.config, worktree.path, module, target_repo, emit)
        target = prepare_target_repo(ctx.config, worktree.path, target_repo, worktree.branch, emit)
        ctx.db.update_job(
            job_id,
            branch=target.branch,
            worktree_path=str(worktree.path),
            metadata=ctx._merge_metadata(
                job_id,
                {
                    **ctx._target_metadata(worktree.branch, target),
                    "prepared_paths": prepared_paths,
                },
            ),
        )

        artifact_dir = ctx._artifact_dir(job_id)
        prompt = test_generation_prompt(
            module,
            api_name,
            target.rel_path,
            _build_validation_guidance(ctx, worktree.path, artifact_dir),
        )
        (artifact_dir / "test_generation_prompt.md").write_text(prompt, encoding="utf-8")
        emit("info", f"Wrote prompt artifact: {artifact_dir / 'test_generation_prompt.md'}")

        ctx.db.update_job(job_id, status="running_codex")
        codex = CodexRunner(ctx.config, emit)
        result = codex.run(prompt, worktree.path, skill_names=ctx._test_skill_names())
        (artifact_dir / "codex_result.txt").write_text(result.final_response, encoding="utf-8")
        if result.thread_id:
            ctx.db.update_job(job_id, codex_thread_id=result.thread_id)
        if not ctx.config.codex_enabled:
            emit("warn", "Codex execution is disabled; only prompt and worktree were generated.")
        allowed_paths = [*prepared_paths, AGENT_NOTES_PATH]
        ensure_only_target_repo_changed(worktree.path, target.rel_path, allowed_support_paths=allowed_paths)
        generated_metadata = _generated_manifest_metadata(worktree.path, target.rel_path, require=ctx.config.codex_enabled)
        if generated_metadata:
            ctx.db.update_job(job_id, metadata=ctx._merge_metadata(job_id, generated_metadata))

        if ctx.config.auto_run_build:
            ctx._run_configure_and_build(job_id, worktree.path)

        if ctx.config.auto_run_tests:
            gtest_filter = generated_metadata.get("generated_gtest_filter") or "*"
            test_output = ctx._run_tests(job_id, worktree.path, gtest_filter)
            failures = ctx._record_failures(job_id, test_output, gtest_filter, artifact_dir=artifact_dir)
            if failures:
                emit("warn", f"Recorded {len(failures)} failing tests.")
                if ctx.config.auto_apply_skips:
                    skip_prompt = skip_known_failure_prompt(
                        test_output,
                        failures,
                        target.rel_path,
                    )
                    (artifact_dir / "skip_prompt.md").write_text(skip_prompt, encoding="utf-8")
                    ctx.db.update_job(job_id, status="applying_skips")
                    skip_result = codex.run(skip_prompt, worktree.path, result.thread_id, skill_names=ctx._test_skill_names())
                    (artifact_dir / "codex_skip_result.txt").write_text(skip_result.final_response, encoding="utf-8")
                    ensure_only_target_repo_changed(worktree.path, target.rel_path, allowed_support_paths=allowed_paths)
                    if ctx.config.auto_run_build:
                        ctx._run_configure_and_build(job_id, worktree.path)
                    if ctx.config.auto_rerun_after_skip:
                        ctx._run_tests(job_id, worktree.path, "*", artifact_name="gtest_output_after_skip.txt")
                else:
                    (artifact_dir / "skip_prompt.md").write_text(
                        skip_known_failure_prompt(
                            test_output,
                            failures,
                            target.rel_path,
                        ),
                        encoding="utf-8",
                    )
                    emit("warn", "auto_apply_skips is disabled; review skip_prompt.md manually.")

        ctx._write_job_artifacts(job_id, worktree.path, artifact_dir)
        ctx.db.update_job(job_id, status="needs_review", metadata=ctx._merge_metadata(job_id, {"artifact_dir": str(artifact_dir), **generated_metadata}))
        emit("info", "Job finished and is ready for review.")
        if ctx.config.auto_create_pr:
            ctx._run_pr_job(job_id)
    except Exception as exc:
        ctx.db.update_job(job_id, status="failed", error=str(exc))
        emit("error", str(exc))


def run_test_extension_job(ctx, job_id: str, api_name: str) -> None:
    emit = ctx._job_emit(job_id)
    try:
        job = ctx.db.get_job(job_id)
        worktree_path = job.get("worktree_path")
        if not worktree_path:
            raise RuntimeError("Selected job has no worktree path. Create a test task first.")

        worktree = Path(worktree_path)
        if not worktree.exists():
            raise RuntimeError(f"Selected job worktree does not exist: {worktree}")

        module = str(job.get("module") or "")
        target_repo = ctx._job_target_repo(job)
        artifact_dir = ctx._artifact_dir(job_id)
        prompt = continue_test_generation_prompt(
            module,
            api_name or str(job.get("api_name") or ""),
            target_repo,
            _build_validation_guidance(ctx, worktree, artifact_dir),
        )
        prompt_path = artifact_dir / "test_generation_extend_prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        emit("info", f"Wrote extension prompt artifact: {prompt_path}")

        ctx.db.update_job(
            job_id,
            status="running_codex",
            api_name=api_name or job.get("api_name") or "",
            metadata=ctx._merge_metadata(job_id, {"last_extension_prompt": api_name}),
        )
        codex = CodexRunner(ctx.config, emit)
        result = codex.run(prompt, worktree, job.get("codex_thread_id"), skill_names=ctx._test_skill_names())
        (artifact_dir / "codex_result.txt").write_text(result.final_response, encoding="utf-8")
        (artifact_dir / "codex_extend_result.txt").write_text(result.final_response, encoding="utf-8")
        if result.thread_id:
            ctx.db.update_job(job_id, codex_thread_id=result.thread_id)

        allowed_paths = list((job.get("metadata") or {}).get("prepared_paths") or [])
        if AGENT_NOTES_PATH not in allowed_paths:
            allowed_paths.append(AGENT_NOTES_PATH)
        ensure_only_target_repo_changed(worktree, target_repo, allowed_support_paths=allowed_paths)
        generated_metadata = _generated_manifest_metadata(worktree, target_repo, require=ctx.config.codex_enabled)
        if generated_metadata:
            ctx.db.update_job(job_id, metadata=ctx._merge_metadata(job_id, generated_metadata))

        if ctx.config.auto_run_build:
            ctx._run_configure_and_build(job_id, worktree)

        if ctx.config.auto_run_tests:
            gtest_filter = generated_metadata.get("generated_gtest_filter") or "*"
            test_output = ctx._run_tests(job_id, worktree, gtest_filter)
            ctx._record_failures(job_id, test_output, gtest_filter, artifact_dir=artifact_dir)

        ctx._write_job_artifacts(job_id, worktree, artifact_dir)
        ctx.db.update_job(job_id, status="needs_review", metadata=ctx._merge_metadata(job_id, {"artifact_dir": str(artifact_dir), **generated_metadata}))
        emit("info", "Test extension finished and is ready for review.")
    except Exception as exc:
        ctx.db.update_job(job_id, status="failed", error=str(exc))
        emit("error", str(exc))


def _generated_manifest_metadata(worktree: Path, target_repo: str, *, require: bool) -> dict:
    if not require:
        return {}
    manifest = require_generated_tests_manifest(worktree, target_repo)
    ensure_generated_tests_use_existing_files(worktree, target_repo, manifest["files"])
    return {
        "generated_tests": manifest["tests"],
        "generated_test_files": manifest["files"],
        "generated_gtest_filter": generated_test_filter(manifest),
    }


def _build_validation_guidance(ctx, worktree: Path, artifact_dir: Path) -> str:
    build_dir = worktree / "build" / "vscode"
    generated_filter_placeholder = "<exact-generated-filter-from-.gme-agent/generated_tests.json>"
    try:
        mapping = ctx._command_mapping(worktree, build_dir, generated_filter_placeholder, artifact_dir=artifact_dir)
        configure_command = ctx.config.configure_command.format(**mapping)
        build_command = ctx.config.build_command.format(**mapping)
        test_command = ctx.config.test_command.format(**mapping)
    except Exception as exc:
        return f"""Build validation commands:
- The GME Test Agent could not pre-render configured build commands: {exc}
- Use the Settings page command templates with these placeholders: `worktree`, `build_dir`, `test_module_name`, `develop_module_option`, `test_module_option`, `gtest_filter`, `test_executable`, `artifact_dir`, `gtest_xml_path`.
- Build directory: `{build_dir}`"""
    return f"""Build validation commands from the GME Test Agent settings:
- Build directory: `{build_dir}`
- Configure:
  `{configure_command}`
- Build:
  `{build_command}`
- Optional focused run after a successful build, after `.gme-agent/generated_tests.json` provides the exact filter:
  `{test_command}`
- These commands are authoritative for this task. If they fail because of generated test code, fix or delete the generated tests before the final response."""
