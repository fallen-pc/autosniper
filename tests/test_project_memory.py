from __future__ import annotations

from pathlib import Path

import pytest

import shared.project_memory as project_memory
from shared.project_memory_guard import validate_protected_memory_changes


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
