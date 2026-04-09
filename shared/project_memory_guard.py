from __future__ import annotations

from pathlib import Path
from typing import Iterable


PROJECT_MEMORY_ROOT = "project_memory"
MEMORY_MANIFEST_PATH = f"{PROJECT_MEMORY_ROOT}/memory_manifest.yaml"
STATE_PATH_PREFIX = f"{PROJECT_MEMORY_ROOT}/02_state/"
PROTECTED_MEMORY_PREFIXES = (
    f"{PROJECT_MEMORY_ROOT}/00_constitution/",
    f"{PROJECT_MEMORY_ROOT}/01_machine_rules/",
    f"{PROJECT_MEMORY_ROOT}/03_decisions/",
)
MEMORY_WRITE_APPROVAL_ENV = "AUTOSNIPER_MEMORY_WRITE_APPROVED"
STATE_MEMORY_OPTIONAL_ENV = "AUTOSNIPER_STATE_MEMORY_OPTIONAL"
STATE_MEMORY_REQUIRED_PREFIXES = (
    "config/",
    "pages/",
    "scripts/",
    "shared/",
    "governance/",
)
STATE_MEMORY_EXEMPT_PREFIXES = (
    "project_memory/",
    "tests/",
    "docs/",
    ".github/",
    ".githooks/",
)
STATE_MEMORY_REQUIRED_FILES = {
    "app.py",
    "DASHBOARD.py",
    "status_app.py",
}
STATE_MEMORY_EXEMPT_FILES = {
    ".gitattributes",
    ".gitignore",
    "README.md",
    "CHANGELOG.md",
    "requirements.txt",
    "task_plan.md",
    "findings.md",
    "progress.md",
}


def normalize_repo_path(path: str | Path) -> str:
    text = str(path).replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text


def is_state_memory_path(path: str | Path) -> bool:
    normalized = normalize_repo_path(path)
    return normalized.startswith(STATE_PATH_PREFIX)


def is_protected_memory_path(path: str | Path) -> bool:
    normalized = normalize_repo_path(path)
    if normalized == MEMORY_MANIFEST_PATH:
        return True
    return any(normalized.startswith(prefix) for prefix in PROTECTED_MEMORY_PREFIXES)


def requires_state_memory_update(path: str | Path) -> bool:
    normalized = normalize_repo_path(path)
    if not normalized:
        return False
    if is_state_memory_path(normalized) or is_protected_memory_path(normalized):
        return False
    if normalized in STATE_MEMORY_EXEMPT_FILES:
        return False
    if any(normalized.startswith(prefix) for prefix in STATE_MEMORY_EXEMPT_PREFIXES):
        return False
    if normalized in STATE_MEMORY_REQUIRED_FILES:
        return True
    return any(normalized.startswith(prefix) for prefix in STATE_MEMORY_REQUIRED_PREFIXES)


def validate_protected_memory_changes(
    paths: Iterable[str | Path],
    *,
    approval_granted: bool = False,
) -> list[str]:
    normalized_paths = [normalize_repo_path(path) for path in paths]
    protected = [
        path
        for path in normalized_paths
        if is_protected_memory_path(path)
    ]
    if not protected or approval_granted:
        return []

    listed = "\n".join(f"  - {path}" for path in protected[:12])
    if len(protected) > 12:
        listed += f"\n  - ... and {len(protected) - 12} more"
    return [
        "Protected project memory files changed without approval.\n"
        "Only `project_memory/02_state/` is writable by default.\n"
        f"Set {MEMORY_WRITE_APPROVAL_ENV}=1 only for intentional constitution/rules/decision changes.\n"
        f"Protected paths:\n{listed}"
    ]


def validate_state_memory_updates(
    paths: Iterable[str | Path],
    *,
    override_granted: bool = False,
) -> list[str]:
    normalized_paths = [normalize_repo_path(path) for path in paths]
    if override_granted:
        return []

    state_paths = [path for path in normalized_paths if is_state_memory_path(path)]
    if state_paths:
        return []

    trigger_paths = [path for path in normalized_paths if requires_state_memory_update(path)]
    if not trigger_paths:
        return []

    listed = "\n".join(f"  - {path}" for path in trigger_paths[:12])
    if len(trigger_paths) > 12:
        listed += f"\n  - ... and {len(trigger_paths) - 12} more"
    return [
        "Meaningful project changes require a state-memory update in the same commit.\n"
        "Stage at least one file under `project_memory/02_state/` describing the current status, issue, change, or next action.\n"
        f"Set {STATE_MEMORY_OPTIONAL_ENV}=1 only for intentional exceptions.\n"
        f"Triggering paths:\n{listed}"
    ]
