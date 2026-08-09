from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import yaml

from shared.curves import CURVE_ALIAS_COLUMNS, CURVE_COLUMNS, LEGACY_COLUMNS
from shared.data_loader import DATASET_PATHS, REQUIRED_FILES
from shared.governance import DATASET_CONTRACTS, TRACKED_DATASET_PATHS
from shared.project_memory_guard import (
    MEMORY_MANIFEST_PATH,
    MEMORY_WRITE_APPROVAL_ENV,
    STATE_MEMORY_OPTIONAL_ENV,
    normalize_repo_path,
    validate_protected_memory_changes,
    validate_state_memory_updates,
)
from shared.schema import ALLOWED_LISTING_STATES, TERMINAL_STATES


REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATED_MACHINE_RULE_FILES = (
    "dataset_contracts.yaml",
    "curve_contracts.yaml",
    "tracked_datasets.yaml",
    "pipeline_stages.yaml",
    "task_requirements.yaml",
)


def _project_memory_dir(root: Path = REPO_ROOT) -> Path:
    return root / "project_memory"


def _machine_rules_dir(root: Path = REPO_ROOT) -> Path:
    return _project_memory_dir(root) / "01_machine_rules"


def _decisions_dir(root: Path = REPO_ROOT) -> Path:
    return _project_memory_dir(root) / "03_decisions"


def _read_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _write_yaml(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _unique_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw_path in paths:
        normalized = normalize_repo_path(raw_path)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def load_manifest(root: Path = REPO_ROOT) -> dict[str, Any]:
    path = root / MEMORY_MANIFEST_PATH
    if not path.exists():
        raise FileNotFoundError(f"Missing project memory manifest: {path}")
    payload = _read_yaml(path)
    if not isinstance(payload, dict):
        raise ValueError("Project memory manifest must contain a mapping at the top level.")
    return payload


def _as_string_list(payload: Any, *, field_name: str) -> list[str]:
    if payload is None:
        return []
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        raise ValueError(f"Manifest field `{field_name}` must be a list of strings.")
    return [normalize_repo_path(item) for item in payload]


def _decision_entries(manifest: dict[str, Any]) -> dict[str, Any]:
    task_requirements = manifest.get("task_requirements")
    if not isinstance(task_requirements, dict):
        raise ValueError("Manifest field `task_requirements` must be a mapping.")
    return task_requirements


def _collect_required_files(manifest: dict[str, Any]) -> list[str]:
    files = _as_string_list(manifest.get("load_order"), field_name="load_order")
    files.extend(_as_string_list(manifest.get("required_before_write"), field_name="required_before_write"))
    files.extend(_as_string_list(manifest.get("legacy_summary_files"), field_name="legacy_summary_files"))
    for task_kind, details in _decision_entries(manifest).items():
        if not isinstance(details, dict):
            raise ValueError(f"Manifest task requirement `{task_kind}` must be a mapping.")
        files.extend(_as_string_list(details.get("required_files"), field_name=f"task_requirements.{task_kind}.required_files"))
    return _unique_paths(files)


def validate_manifest(root: Path = REPO_ROOT, manifest: dict[str, Any] | None = None) -> list[str]:
    try:
        manifest = manifest or load_manifest(root)
    except (FileNotFoundError, ValueError) as exc:
        return [str(exc)]

    errors: list[str] = []
    required_sections = ("load_order", "required_before_write", "task_requirements", "protected_paths", "state_paths")
    for field_name in required_sections:
        if field_name not in manifest:
            errors.append(f"Manifest missing required field `{field_name}`.")

    try:
        required_files = _collect_required_files(manifest)
    except ValueError as exc:
        return errors + [str(exc)]

    for rel_path in required_files:
        path = root / rel_path
        if not path.exists():
            errors.append(f"Required memory file missing: {rel_path}")
            continue
        if path.is_file() and not _read_text(path):
            errors.append(f"Required memory file is empty: {rel_path}")

    try:
        protected_paths = _as_string_list(manifest.get("protected_paths"), field_name="protected_paths")
        state_paths = _as_string_list(manifest.get("state_paths"), field_name="state_paths")
    except ValueError as exc:
        return errors + [str(exc)]

    for rel_path in protected_paths + state_paths:
        path = root / rel_path
        if not path.exists():
            errors.append(f"Manifest path does not exist: {rel_path}")

    approval = manifest.get("approval_env", {})
    if not isinstance(approval, dict) or approval.get("name") != MEMORY_WRITE_APPROVAL_ENV:
        errors.append(
            f"Manifest approval_env.name must be `{MEMORY_WRITE_APPROVAL_ENV}`."
        )

    return errors


def validate_decision_index(root: Path = REPO_ROOT) -> list[str]:
    index_path = root / "project_memory" / "03_decisions" / "index.yaml"
    if not index_path.exists():
        return [f"Missing decision index: {normalize_repo_path(index_path.relative_to(root))}"]

    payload = _read_yaml(index_path)
    if not isinstance(payload, dict) or not isinstance(payload.get("decisions"), list):
        return ["Decision index must contain a `decisions` list."]

    indexed_paths: list[str] = []
    indexed_ids: list[str] = []
    errors: list[str] = []
    for entry in payload["decisions"]:
        if not isinstance(entry, dict):
            errors.append("Decision index entries must be mappings.")
            continue
        decision_id = str(entry.get("id", "")).strip()
        path = normalize_repo_path(entry.get("path", ""))
        title = str(entry.get("title", "")).strip()
        status = str(entry.get("status", "")).strip()
        date = str(entry.get("date", "")).strip()
        if not decision_id or not path or not title or not status or not date:
            errors.append(f"Incomplete decision index entry: {entry}")
            continue
        indexed_ids.append(decision_id)
        indexed_paths.append(path)
        content_path = root / path
        if not content_path.exists():
            errors.append(f"Indexed decision file missing: {path}")
            continue
        content = content_path.read_text(encoding="utf-8")
        if decision_id not in content:
            errors.append(f"Decision file does not contain its id `{decision_id}`: {path}")
        if "Status:" not in content or "Date:" not in content:
            errors.append(f"Decision file missing `Status:` or `Date:` header: {path}")

    actual_paths = sorted(
        normalize_repo_path(path.relative_to(root))
        for path in _decisions_dir(root).glob("DEC-*.md")
    )
    if sorted(indexed_paths) != actual_paths:
        errors.append(
            "Decision index paths do not match decision files on disk."
        )
    if len(set(indexed_ids)) != len(indexed_ids):
        errors.append("Decision index contains duplicate decision ids.")
    return errors


def _extract_pipeline_stage_choices(root: Path = REPO_ROOT) -> list[str]:
    script_path = root / "scripts" / "pipeline_stages.py"
    if not script_path.exists():
        return []
    tree = ast.parse(script_path.read_text(encoding="utf-8"), filename=str(script_path))
    discovered: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add_argument":
            continue
        for keyword in node.keywords:
            if keyword.arg != "choices":
                continue
            try:
                value = ast.literal_eval(keyword.value)
            except ValueError:
                continue
            if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
                discovered = list(value)
    return discovered


def collect_expected_machine_rules(
    root: Path = REPO_ROOT,
    manifest: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    manifest = manifest or load_manifest(root)
    dataset_contracts = {
        contract.filename: {
            "mode": contract.mode,
            "columns": list(contract.columns),
        }
        for contract in DATASET_CONTRACTS
    }
    tracked_dataset_paths = {
        dataset_name: normalize_repo_path(path)
        for dataset_name, path in DATASET_PATHS.items()
    }
    pipeline_stage_choices = _extract_pipeline_stage_choices(root)
    task_requirements = {
        "generated_from_manifest": MEMORY_MANIFEST_PATH,
        "tasks": {
            task_kind: {
                "required_files": _as_string_list(details.get("required_files"), field_name=f"task_requirements.{task_kind}.required_files")
            }
            for task_kind, details in _decision_entries(manifest).items()
        },
    }
    return {
        "dataset_contracts.yaml": {
            "generated_from": [
                "shared.governance.DATASET_CONTRACTS",
                "shared.schema",
            ],
            "datasets": dataset_contracts,
        },
        "curve_contracts.yaml": {
            "generated_from": [
                "shared.curves.CURVE_COLUMNS",
                "shared.curves.LEGACY_COLUMNS",
                "shared.curves.CURVE_ALIAS_COLUMNS",
            ],
            "curves": {
                "required_columns": list(CURVE_COLUMNS),
                "rejected_legacy_columns": sorted(LEGACY_COLUMNS),
                "curve_alias_columns": list(CURVE_ALIAS_COLUMNS),
            },
        },
        "tracked_datasets.yaml": {
            "generated_from": [
                "shared.data_loader.DATASET_PATHS",
                "shared.data_loader.REQUIRED_FILES",
                "shared.governance.TRACKED_DATASET_PATHS",
            ],
            "required_files": list(REQUIRED_FILES),
            "tracked_dataset_paths": list(TRACKED_DATASET_PATHS),
            "named_dataset_paths": tracked_dataset_paths,
        },
        "pipeline_stages.yaml": {
            "generated_from": [
                "scripts/pipeline_stages.py",
                "shared.schema.ALLOWED_LISTING_STATES",
                "shared.schema.TERMINAL_STATES",
            ],
            "pipeline_cli": {
                "script": "scripts/pipeline_stages.py",
                "stage_choices": pipeline_stage_choices,
            },
            "listing_state_machine": {
                "allowed_states": sorted(ALLOWED_LISTING_STATES),
                "terminal_states": sorted(TERMINAL_STATES),
            },
        },
        "task_requirements.yaml": task_requirements,
    }


def refresh_machine_rules(root: Path = REPO_ROOT) -> list[str]:
    manifest = load_manifest(root)
    expected = collect_expected_machine_rules(root, manifest)
    written: list[str] = []
    for filename, payload in expected.items():
        path = _machine_rules_dir(root) / filename
        _write_yaml(path, payload)
        written.append(normalize_repo_path(path.relative_to(root)))
    return written


def validate_machine_rules(root: Path = REPO_ROOT, manifest: dict[str, Any] | None = None) -> list[str]:
    manifest = manifest or load_manifest(root)
    expected = collect_expected_machine_rules(root, manifest)
    errors: list[str] = []
    for filename, expected_payload in expected.items():
        path = _machine_rules_dir(root) / filename
        if not path.exists():
            errors.append(
                f"Generated machine-rule file missing: {normalize_repo_path(path.relative_to(root))}"
            )
            continue
        actual_payload = _read_yaml(path)
        if actual_payload != expected_payload:
            errors.append(
                f"Generated machine-rule file is stale: {normalize_repo_path(path.relative_to(root))}. "
                "Run `python scripts/project_memory.py refresh-machine-rules`."
            )
    return errors


def _run_git(args: list[str], root: Path = REPO_ROOT) -> list[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return [
        normalize_repo_path(line)
        for line in completed.stdout.splitlines()
        if line.strip()
    ]


def staged_paths(root: Path = REPO_ROOT) -> list[str]:
    return _run_git(["diff", "--cached", "--name-only", "--diff-filter=ACMRD"], root=root)


def changed_paths(
    base_ref: str,
    head_ref: str = "HEAD",
    *,
    root: Path = REPO_ROOT,
) -> list[str]:
    base = str(base_ref).strip()
    head = str(head_ref).strip() or "HEAD"
    if not base:
        raise ValueError("A non-empty base ref is required for Git-range memory validation.")
    return _run_git(
        ["diff", "--name-only", "--diff-filter=ACMRD", f"{base}...{head}"],
        root=root,
    )


def validate_memory_change_paths(paths: list[str]) -> list[str]:
    approval_granted = str(os.getenv(MEMORY_WRITE_APPROVAL_ENV, "")).strip() == "1"
    state_override_granted = str(os.getenv(STATE_MEMORY_OPTIONAL_ENV, "")).strip() == "1"
    errors = validate_protected_memory_changes(
        paths,
        approval_granted=approval_granted,
    )
    errors.extend(
        validate_state_memory_updates(
            paths,
            override_granted=state_override_granted,
        )
    )
    return errors


def run_checks(
    root: Path = REPO_ROOT,
    *,
    staged: bool = False,
    base_ref: str | None = None,
    head_ref: str = "HEAD",
) -> list[str]:
    errors: list[str] = []
    manifest: dict[str, Any] | None = None
    if staged and base_ref:
        return ["Use either staged validation or Git-range validation, not both."]
    try:
        manifest = load_manifest(root)
    except (FileNotFoundError, ValueError) as exc:
        return [str(exc)]

    errors.extend(validate_manifest(root, manifest))
    errors.extend(validate_decision_index(root))
    errors.extend(validate_machine_rules(root, manifest))
    if staged or base_ref:
        try:
            paths = (
                staged_paths(root)
                if staged
                else changed_paths(str(base_ref), head_ref, root=root)
            )
            errors.extend(validate_memory_change_paths(paths))
        except (RuntimeError, ValueError) as exc:
            errors.append(str(exc))
    return errors


def _build_context_markdown(
    *,
    task_kind: str,
    intent: str,
    sections: list[dict[str, str]],
    protected_paths: list[str],
    state_paths: list[str],
) -> str:
    lines = [
        "# AutoSniper Project Memory Context",
        "",
        f"- Task kind: `{task_kind}`",
        f"- Intent: `{intent}`",
        f"- Protected memory requires `{MEMORY_WRITE_APPROVAL_ENV}=1`",
        f"- Default writable memory: `{', '.join(state_paths)}`",
        "",
    ]
    if protected_paths:
        lines.append("## Protected Paths")
        lines.extend(f"- `{path}`" for path in protected_paths)
        lines.append("")
    for section in sections:
        lines.append(f"## {section['path']}")
        lines.append(section["content"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_context_bundle(
    task_kind: str,
    intent: str,
    *,
    root: Path = REPO_ROOT,
) -> dict[str, Any]:
    errors = run_checks(root, staged=False)
    if errors:
        raise RuntimeError(
            "Project memory checks failed before build-context:\n- " + "\n- ".join(errors)
        )

    manifest = load_manifest(root)
    task_requirements = _decision_entries(manifest)
    if task_kind not in task_requirements:
        available = ", ".join(sorted(task_requirements))
        raise ValueError(f"Unknown task kind `{task_kind}`. Available task kinds: {available}")
    if intent not in {"read", "write"}:
        raise ValueError("Intent must be `read` or `write`.")

    files = _as_string_list(manifest.get("load_order"), field_name="load_order")
    files.extend(_as_string_list(task_requirements[task_kind].get("required_files"), field_name=f"task_requirements.{task_kind}.required_files"))
    if intent == "write":
        files.extend(_as_string_list(manifest.get("required_before_write"), field_name="required_before_write"))
    files.extend(_as_string_list(manifest.get("legacy_summary_files"), field_name="legacy_summary_files"))
    files = _unique_paths(files)

    sections: list[dict[str, str]] = []
    for rel_path in files:
        path = root / rel_path
        content = path.read_text(encoding="utf-8")
        sections.append(
            {
                "path": rel_path,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "content": content,
            }
        )

    protected_paths = _as_string_list(manifest.get("protected_paths"), field_name="protected_paths")
    state_paths = _as_string_list(manifest.get("state_paths"), field_name="state_paths")
    return {
        "project": "AutoSniper",
        "task_kind": task_kind,
        "intent": intent,
        "loaded_paths": files,
        "protected_paths": protected_paths,
        "state_paths": state_paths,
        "approval_env": MEMORY_WRITE_APPROVAL_ENV,
        "sections": sections,
        "session_context_markdown": _build_context_markdown(
            task_kind=task_kind,
            intent=intent,
            sections=sections,
            protected_paths=protected_paths,
            state_paths=state_paths,
        ),
    }


def command_check(args: argparse.Namespace) -> int:
    errors = run_checks(
        staged=args.staged,
        base_ref=args.base_ref,
        head_ref=args.head_ref,
    )
    if errors:
        for error in errors:
            print(f"[project-memory] ERROR: {error}")
        return 1
    print("[project-memory] all checks passed")
    return 0


def command_refresh_machine_rules(args: argparse.Namespace) -> int:
    written = refresh_machine_rules()
    for path in written:
        print(f"[project-memory] wrote {path}")
    return 0


def command_build_context(args: argparse.Namespace) -> int:
    bundle = build_context_bundle(args.task_kind, args.intent)
    payload = json.dumps(bundle, indent=2, ensure_ascii=False)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
        print(f"[project-memory] wrote context bundle to {output_path}")
        return 0
    print(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project memory checks and context bootstrap.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser(
        "check",
        help="Validate manifest, decisions, generated rules, and changed-memory protection.",
    )
    change_source = check_parser.add_mutually_exclusive_group()
    change_source.add_argument(
        "--staged",
        action="store_true",
        help="Validate staged protected-memory and required state-memory changes.",
    )
    change_source.add_argument(
        "--base-ref",
        help="Validate protected-memory and required state-memory changes from this Git base to --head-ref.",
    )
    check_parser.add_argument(
        "--head-ref",
        default="HEAD",
        help="Git head ref for --base-ref validation (default: HEAD).",
    )
    check_parser.set_defaults(func=command_check)

    refresh_parser = subparsers.add_parser("refresh-machine-rules", help="Regenerate machine-readable rule files.")
    refresh_parser.set_defaults(func=command_refresh_machine_rules)

    context_parser = subparsers.add_parser("build-context", help="Build a task-scoped project memory context bundle.")
    context_parser.add_argument("--task-kind", required=True, help="Task kind such as write, valuation, curves, ui, scraper, or governance.")
    context_parser.add_argument("--intent", choices=("read", "write"), default="read")
    context_parser.add_argument("--output", help="Optional output JSON file path.")
    context_parser.set_defaults(func=command_build_context)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))
