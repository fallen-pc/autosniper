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
