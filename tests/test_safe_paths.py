from pathlib import Path

import pytest

from shared.safe_paths import resolve_autotrader_output_path


def test_resolve_autotrader_output_path_accepts_repo_relative_output(tmp_path: Path) -> None:
    resolved = resolve_autotrader_output_path(
        "autotrader_isolated/output/results.csv",
        root_dir=tmp_path,
    )

    assert resolved == (tmp_path / "autotrader_isolated" / "output" / "results.csv").resolve()


@pytest.mark.parametrize(
    "path_value",
    [
        "autotrader_isolated/output/../../secrets.csv",
        "../outside.csv",
    ],
)
def test_resolve_autotrader_output_path_rejects_traversal(
    tmp_path: Path,
    path_value: str,
) -> None:
    with pytest.raises(ValueError, match="must stay inside"):
        resolve_autotrader_output_path(path_value, root_dir=tmp_path)


def test_resolve_autotrader_output_path_rejects_absolute_path_outside_root(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="must stay inside"):
        resolve_autotrader_output_path(tmp_path.parent / "outside.csv", root_dir=tmp_path)
