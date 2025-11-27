import asyncio
import random
import sys

from playwright.async_api import async_playwright

url = sys.argv[1]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_extra_http_headers({"User-Agent": random.choice(USER_AGENTS)})
        await page.goto(url, wait_until="load", timeout=60000)
        await page.wait_for_timeout(4000)
        html = await page.content()
        with open("tmp_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        await browser.close()


asyncio.run(main())
