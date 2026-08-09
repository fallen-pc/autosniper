from pathlib import Path


def resolve_autotrader_output_path(path_value: object, *, root_dir: Path) -> Path:
    """Resolve an Autotrader output path without allowing it to escape its data directory."""
    repo_root = root_dir.resolve()
    output_root = (repo_root / "autotrader_isolated" / "output").resolve()
    candidate = Path(str(path_value).strip())
    resolved = (candidate if candidate.is_absolute() else repo_root / candidate).resolve()

    try:
        resolved.relative_to(output_root)
    except ValueError as exc:
        raise ValueError(f"Output path must stay inside {output_root}") from exc
    return resolved
