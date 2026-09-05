from __future__ import annotations

from pathlib import Path

import pytest

import shared.project_memory as project_memory
from shared.project_memory_guard import validate_protected_memory_changes, validate_state_memory_updates


ROOT = Path(__file__).resolve().parent.parent


def test_repo_project_memory_checks_pass():
    errors = project_memory.run_checks(ROOT)
    assert errors == []


def test_build_context_returns_expected_repo_paths_for_write_and_curves():
    write_bundle = project_memory.build_context_bundle("write", "write", root=ROOT)
    valuation_bundle = project_memory.build_context_bundle("valuation", "write", root=ROOT)
    curves_bundle = project_memory.build_context_bundle("curves", "read", root=ROOT)

    assert "project_memory/00_constitution/project_mission.md" in write_bundle["loaded_paths"]
    assert "project_memory/02_state/recent_changes.md" in write_bundle["loaded_paths"]
    assert "project_memory/03_decisions/DEC-003-sold-cars-inform-hammer-bid.md" in valuation_bundle["loaded_paths"]
    assert "project_memory/01_machine_rules/pipeline_stages.yaml" in curves_bundle["loaded_paths"]
    assert "project_memory/03_decisions/DEC-002-curves-govern-resale.md" in curves_bundle["loaded_paths"]


def test_build_context_fails_when_required_task_file_is_missing(tmp_path):
    memory_root = tmp_path / "project_memory"
    (memory_root / "00_constitution").mkdir(parents=True)
    (memory_root / "02_state").mkdir(parents=True)
    (memory_root / "03_decisions").mkdir(parents=True)
    (memory_root / "00_constitution" / "project_mission.md").write_text("mission", encoding="utf-8")
    (memory_root / "00_constitution" / "non_negotiable_rules.md").write_text("rules", encoding="utf-8")
    (memory_root / "02_state" / "current_status.md").write_text("status", encoding="utf-8")
    (memory_root / "03_decisions" / "index.yaml").write_text("decisions: []\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ai_working_agreement.md").write_text("summary", encoding="utf-8")
    (tmp_path / "task_plan.md").write_text("summary", encoding="utf-8")
    (tmp_path / "findings.md").write_text("summary", encoding="utf-8")
    (tmp_path / "progress.md").write_text("summary", encoding="utf-8")
    (memory_root / "memory_manifest.yaml").write_text(
        "\n".join(
            [
                "project: AutoSniper",
                "version: 1",
                "load_order:",
                "  - project_memory/00_constitution/project_mission.md",
                "  - project_memory/00_constitution/non_negotiable_rules.md",
                "  - project_memory/02_state/current_status.md",
                "  - project_memory/03_decisions/index.yaml",
                "required_before_write:",
                "  - project_memory/00_constitution/non_negotiable_rules.md",
                "task_requirements:",
                "  write:",
                "    required_files:",
                "      - project_memory/02_state/missing.md",
                "protected_paths:",
                "  - project_memory/memory_manifest.yaml",
                "  - project_memory/00_constitution/",
                "  - project_memory/01_machine_rules/",
                "  - project_memory/03_decisions/",
                "state_paths:",
                "  - project_memory/02_state/",
                "legacy_summary_files:",
                "  - docs/ai_working_agreement.md",
                "  - task_plan.md",
                "  - findings.md",
                "  - progress.md",
                "approval_env:",
                "  name: AUTOSNIPER_MEMORY_WRITE_APPROVED",
                '  value: "1"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="missing.md"):
        project_memory.build_context_bundle("write", "write", root=tmp_path)


def test_protected_memory_changes_are_blocked_without_approval():
    errors = validate_protected_memory_changes(
        [
            "project_memory/00_constitution/project_mission.md",
            "project_memory/03_decisions/DEC-001-repo-memory-over-chat-memory.md",
        ],
        approval_granted=False,
    )
    assert len(errors) == 1
    assert "AUTOSNIPER_MEMORY_WRITE_APPROVED=1" in errors[0]


def test_state_memory_changes_are_allowed_without_approval():
    errors = validate_protected_memory_changes(
        ["project_memory/02_state/current_status.md"],
        approval_granted=False,
    )
    assert errors == []


def test_meaningful_code_changes_require_state_memory_update():
    errors = validate_state_memory_updates(
        ["pages/15_CURVE_BUILDER_V2.py", "shared/curve_seed_rows.py"],
        override_granted=False,
    )
    assert len(errors) == 1
    assert "project_memory/02_state/" in errors[0]
    assert "AUTOSNIPER_STATE_MEMORY_OPTIONAL=1" in errors[0]


def test_meaningful_code_changes_pass_when_state_memory_is_staged():
    errors = validate_state_memory_updates(
        [
            "pages/15_CURVE_BUILDER_V2.py",
            "project_memory/02_state/recent_changes.md",
        ],
        override_granted=False,
    )
    assert errors == []


def test_docs_and_tests_do_not_require_state_memory_update():
    errors = validate_state_memory_updates(
        [
            "docs/ai_working_agreement.md",
            "tests/test_curve_groups_v2.py",
            "README.md",
        ],
        override_granted=False,
    )
    assert errors == []


def test_staged_paths_include_deleted_files(monkeypatch):
    captured: list[str] = []

    def fake_run_git(args, root=ROOT):
        captured.extend(args)
        return ["project_memory/00_constitution/deleted.md"]

    monkeypatch.setattr(project_memory, "_run_git", fake_run_git)

    assert project_memory.staged_paths(ROOT) == [
        "project_memory/00_constitution/deleted.md"
    ]
    assert "--diff-filter=ACMRD" in captured


def test_changed_paths_uses_base_to_head_range_and_includes_deletions(monkeypatch):
    captured: list[str] = []

    def fake_run_git(args, root=ROOT):
        captured.extend(args)
        return ["project_memory/03_decisions/DEC-999-deleted.md"]

    monkeypatch.setattr(project_memory, "_run_git", fake_run_git)

    assert project_memory.changed_paths("base-sha", "head-sha", root=ROOT) == [
        "project_memory/03_decisions/DEC-999-deleted.md"
    ]
    assert "--diff-filter=ACMRD" in captured
    assert "base-sha...head-sha" in captured


def test_git_range_blocks_protected_memory_without_approval(monkeypatch):
    monkeypatch.delenv("AUTOSNIPER_MEMORY_WRITE_APPROVED", raising=False)
    monkeypatch.setattr(
        project_memory,
        "changed_paths",
        lambda *_args, **_kwargs: [
            "project_memory/00_constitution/project_mission.md"
        ],
    )

    errors = project_memory.run_checks(ROOT, base_ref="base-sha", head_ref="head-sha")

    assert any("Protected project memory files changed without approval" in error for error in errors)


def test_git_range_allows_protected_memory_with_approval(monkeypatch):
    monkeypatch.setenv("AUTOSNIPER_MEMORY_WRITE_APPROVED", "1")
    monkeypatch.setattr(
        project_memory,
        "changed_paths",
        lambda *_args, **_kwargs: [
            "project_memory/00_constitution/project_mission.md"
        ],
    )

    errors = project_memory.run_checks(ROOT, base_ref="base-sha", head_ref="head-sha")

    assert errors == []


def test_git_range_requires_state_memory_for_meaningful_source_change(monkeypatch):
    monkeypatch.delenv("AUTOSNIPER_STATE_MEMORY_OPTIONAL", raising=False)
    monkeypatch.setattr(
        project_memory,
        "changed_paths",
        lambda *_args, **_kwargs: ["shared/project_memory.py"],
    )

    errors = project_memory.run_checks(ROOT, base_ref="base-sha", head_ref="head-sha")

    assert any("Meaningful project changes require a state-memory update" in error for error in errors)


def test_git_range_accepts_source_change_with_state_memory(monkeypatch):
    monkeypatch.delenv("AUTOSNIPER_STATE_MEMORY_OPTIONAL", raising=False)
    monkeypatch.setattr(
        project_memory,
        "changed_paths",
        lambda *_args, **_kwargs: [
            "shared/project_memory.py",
            "project_memory/02_state/recent_changes.md",
        ],
    )

    errors = project_memory.run_checks(ROOT, base_ref="base-sha", head_ref="head-sha")

    assert errors == []


def test_run_checks_rejects_staged_and_git_range_together():
    errors = project_memory.run_checks(ROOT, staged=True, base_ref="base-sha")

    assert errors == ["Use either staged validation or Git-range validation, not both."]


def test_governance_workflow_enforces_pr_memory_diff_and_label_approval():
    workflow = (ROOT / ".github" / "workflows" / "governance.yml").read_text(
        encoding="utf-8"
    )

    assert "types: [opened, synchronize, reopened, labeled, unlabeled]" in workflow
    assert "protected-memory-approved" in workflow
    assert 'github.event.pull_request.base.sha' in workflow
    assert 'github.event.pull_request.head.sha' in workflow
    assert "project_memory.py check --base-ref" in workflow
    assert 'BEFORE_SHA: ${{ github.event.before }}' in workflow
    assert 'BEFORE_SHA" == "$first_parent' in workflow
    assert '.merged_at != null' in workflow
    assert r'.merge_commit_sha == \"$HEAD_SHA\"' in workflow
    assert 'approved="false"' in workflow
    assert "schema-migration-approved" in workflow
    assert 'schema_approved="false"' in workflow
    assert "AUTOSNIPER_SCHEMA_MIGRATION_APPROVED" in workflow
