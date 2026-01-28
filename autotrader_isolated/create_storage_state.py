"""Create a Playwright storage_state.json for Autotrader."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from playwright.async_api import Error as PlaywrightError, async_playwright


DEFAULT_URL = "https://www.autotrader.com.au/"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output" / "storage_state.json"


async def _goto_with_retries(
    page,
    url: str,
    wait_until: str,
    timeout: int,
    retries: int,
    retry_delay: float,
) -> None:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout * 1000)
            return
        except PlaywrightError as exc:
            last_exc = exc
            message = str(exc)
            if "ERR_NETWORK_CHANGED" not in message and "Timeout" not in message:
                raise
            if attempt >= retries:
                break
            await page.wait_for_timeout(int(retry_delay * 1000))
    if last_exc:
        raise last_exc


async def _create_state(
    url: str,
    output: Path,
    timeout: int,
    browser_name: str,
    slow_mo: int,
    wait_until: str,
    retries: int,
    retry_delay: float,
    wait_seconds: int,
) -> None:
    async with async_playwright() as p:
        channel: str | None = None
        browser_type = p.chromium
        if browser_name == "firefox":
            browser_type = p.firefox
        elif browser_name == "webkit":
            browser_type = p.webkit
        elif browser_name == "chrome":
            browser_type = p.chromium
            channel = "chrome"
        elif browser_name == "msedge":
            browser_type = p.chromium
            channel = "msedge"

        print(f"Launching {browser_name} (headless=False).")
        launch_kwargs = {"headless": False, "slow_mo": slow_mo or 0}
        if channel:
            launch_kwargs["channel"] = channel
        browser = await browser_type.launch(**launch_kwargs)
        context = await browser.new_context(no_viewport=True)
        page = await context.new_page()
        await _goto_with_retries(page, url, wait_until, timeout, retries, retry_delay)
        try:
            await page.bring_to_front()
        except Exception:
            pass
        print("Log in (or pass any bot checks) in the opened browser window.")
        if wait_seconds > 0:
            print(f"Waiting up to {wait_seconds} seconds before saving state.")
            try:
                await page.wait_for_event("close", timeout=wait_seconds * 1000)
            except PlaywrightError as exc:
                if "Timeout" not in str(exc):
                    raise
        else:
            try:
                input("Press Enter here when you are done...")
            except EOFError:
                fallback_seconds = 180
                print(
                    "No stdin available. Waiting up to "
                    f"{fallback_seconds} seconds before saving state."
                )
                try:
                    await page.wait_for_event("close", timeout=fallback_seconds * 1000)
                except PlaywrightError as exc:
                    if "Timeout" not in str(exc):
                        raise
        output.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(output))
        print(f"Saved storage state to {output}")
        await context.close()
        await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Playwright storage_state.json for Autotrader.")
    parser.add_argument("--url", default=DEFAULT_URL, help="URL to open for login.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination storage_state.json path.",
    )
    parser.add_argument("--timeout", type=int, default=60, help="Page load timeout in seconds.")
    parser.add_argument(
        "--browser",
        choices=["chromium", "chrome", "msedge", "firefox", "webkit"],
        default="chromium",
        help="Browser engine/channel to launch.",
    )
    parser.add_argument(
        "--slowmo",
        type=int,
        default=0,
        help="Slow down Playwright actions (ms).",
    )
    parser.add_argument(
        "--wait",
        choices=["domcontentloaded", "load", "networkidle"],
        default="domcontentloaded",
        help="Playwright wait_until mode.",
    )
    parser.add_argument("--retries", type=int, default=3, help="Retries for network hiccups.")
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=2.0,
        help="Delay between retries (seconds).",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=0,
        help="Optional time to wait for manual login before saving state (seconds).",
    )
    args = parser.parse_args()

    asyncio.run(
        _create_state(
            args.url,
            args.output,
            args.timeout,
            args.browser,
            args.slowmo,
            args.wait,
            args.retries,
            args.retry_delay,
            args.wait_seconds,
        )
    )


if __name__ == "__main__":
    main()
