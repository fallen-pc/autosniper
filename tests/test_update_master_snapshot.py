import pandas as pd


TERMINAL = {"SOLD", "REFERRED", "WITHDRAWN"}


def _update_master_core(
    static_df: pd.DataFrame,
    scraped_status_df: pd.DataFrame,
    prev_urls: set[str],
    curr_urls: set[str],
) -> tuple[pd.DataFrame, set[str]]:
    """Core rule: snapshot-missing is non-terminal; only confirmed terminal statuses prune."""
    missing_urls = prev_urls - curr_urls
    terminal_urls = set(
        scraped_status_df.loc[
            scraped_status_df["status"].isin(TERMINAL), "url"
        ].astype(str)
    )
    pruned_static = static_df[~static_df["url"].astype(str).isin(terminal_urls)].copy()
    return pruned_static, missing_urls


def test_snapshot_missing_does_not_mark_sold_or_prune() -> None:
    missing_url = "https://example.com/lot/123"
    prev_urls = {missing_url}
    curr_urls: set[str] = set()

    static_df = pd.DataFrame(
        {
            "url": [missing_url],
            "status": ["ACTIVE"],
        }
    )

    scraped_status_df = pd.DataFrame(
        {
            "url": [],
            "status": [],
        }
    )

    pruned_static, missing_urls = _update_master_core(
        static_df, scraped_status_df, prev_urls, curr_urls
    )

    assert missing_url in missing_urls
    assert len(pruned_static) == 1
    assert pruned_static.iloc[0]["url"] == missing_url


def test_confirmed_sold_prunes_static() -> None:
    sold_url = "https://example.com/lot/999"

    static_df = pd.DataFrame({"url": [sold_url], "status": ["ACTIVE"]})
    scraped_status_df = pd.DataFrame({"url": [sold_url], "status": ["SOLD"]})

    pruned_static, _ = _update_master_core(
        static_df, scraped_status_df, {sold_url}, set()
    )

    assert len(pruned_static) == 0
