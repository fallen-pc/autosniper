from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import requests

from shared.data_loader import dataset_path


ALERT_LOG_PATH = dataset_path("ai/telegram_alert_log.csv")
ALERT_LOG_COLUMNS = [
    "alert_type",
    "url",
    "sent_at",
    "verdict",
]


def telegram_enabled() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def send_telegram_message(message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id or not message.strip():
        return False
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": message},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram send failed: {payload}")
    return True


def _load_alert_log() -> pd.DataFrame:
    if not ALERT_LOG_PATH.exists():
        return pd.DataFrame(columns=ALERT_LOG_COLUMNS)
    try:
        df = pd.read_csv(ALERT_LOG_PATH)
    except Exception:
        return pd.DataFrame(columns=ALERT_LOG_COLUMNS)
    for column in ALERT_LOG_COLUMNS:
        if column not in df.columns:
            df[column] = None
    return df[ALERT_LOG_COLUMNS]


def _append_alert_log(alert_type: str, url: str, verdict: Optional[str]) -> None:
    df = _load_alert_log()
    new_row = pd.DataFrame(
        [
            {
                "alert_type": alert_type,
                "url": url,
                "sent_at": datetime.now(tz=timezone.utc).isoformat(),
                "verdict": verdict,
            }
        ]
    )
    combined = pd.concat([df, new_row], ignore_index=True)
    ALERT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(ALERT_LOG_PATH, index=False)


def already_alerted(alert_type: str, url: str) -> bool:
    if not url:
        return False
    df = _load_alert_log()
    if df.empty:
        return False
    mask = (df["alert_type"].astype(str) == alert_type) & (df["url"].astype(str) == str(url))
    return bool(mask.any())


def send_once(alert_type: str, url: str, message: str, verdict: Optional[str] = None) -> bool:
    if not telegram_enabled() or not url or already_alerted(alert_type, url):
        return False
    sent = send_telegram_message(message)
    if sent:
        _append_alert_log(alert_type, url, verdict)
    return sent
