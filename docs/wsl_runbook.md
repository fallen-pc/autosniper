# AutoSniper Sandbox WSL Runbook

Purpose: repeat the known-good sandbox bring-up path inside WSL without dragging in the wrong repo, wrong interpreter, or wrong environment.

## Use this repo
- Sandbox repo root: `/mnt/c/Users/ewanf/Desktop/autosniper-main-sandbox`
- Do not use the main repo when validating sandbox runtime fixes.

## Use this Python environment
- Preferred Linux-side venv: `/home/ewanf/.cache/autosniper-test-venv`
- Reason: the WSL venv created on `/mnt/c` was unreliable for compiled packages.

## Launch recipe
From WSL:

```bash
cd /mnt/c/Users/ewanf/Desktop/autosniper-main-sandbox
/home/ewanf/.cache/autosniper-test-venv/bin/python -m streamlit run app.py --server.headless true --server.port 8503
```

Use another port if 8503 is already occupied.

## Minimum dependency bring-up pattern
Install only what the live run actually asks for, into the Linux-side venv.

Examples already needed during bring-up:

```bash
/home/ewanf/.cache/autosniper-test-venv/bin/pip install streamlit
/home/ewanf/.cache/autosniper-test-venv/bin/pip install beautifulsoup4==4.14.3
/home/ewanf/.cache/autosniper-test-venv/bin/pip install playwright==1.58.0
/home/ewanf/.cache/autosniper-test-venv/bin/pip install python-dotenv==1.2.2
/home/ewanf/.cache/autosniper-test-venv/bin/pip install openai==2.26.0
/home/ewanf/.cache/autosniper-test-venv/bin/pip install matplotlib
/home/ewanf/.cache/autosniper-test-venv/bin/pip install scikit-learn
```

## Playwright/browser setup
Use the venv interpreter, not global Node/npm shortcuts.

```bash
/home/ewanf/.cache/autosniper-test-venv/bin/python -m playwright install chromium
/home/ewanf/.cache/autosniper-test-venv/bin/python -m playwright install-deps chromium
```

If OS packages are still missing, minimal fallback tried during bring-up was:

```bash
sudo apt install -y libnspr4 libnss3
```

## Known good bring-up principles
- Use `sys.executable`-driven page entrypoints where patched; do not assume `python` exists in PATH.
- Launch from the sandbox repo root so `app.py` and its curated navigation resolve correctly.
- Prefer WSL + Linux-side venv over Windows PowerShell + Windows venv for sandbox runtime validation.

## What is already fixed in sandbox bring-up
- bare `python` shell-outs in key Streamlit pages replaced with active-interpreter usage
- the retired Mappings editor is no longer part of the supported app
- selected live deprecation/warning sites cleaned up in a bounded way
- additional click-through render bugs fixed in `pages/15_CURVE_BUILDER_V2.py`; the standalone style-guide page was later retired

## What is not guaranteed by this runbook
- all datasets exist
- all external services/credentials are configured
- all pages are logically correct end-to-end
- all warnings are cleaned up

This runbook only captures the path that got the sandbox app broadly launchable and click-through testable.
