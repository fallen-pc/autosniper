from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import requests

from shared.csv_utils import CSV_READ_ERRORS
from shared.data_loader import dataset_path

logger = logging.getLogger(__name__)


ALERT_LOG_PATH = dataset_path("ai/telegram_alert_log.csv")
ALERT_LOG_COLUMNS = [
    "alert_type",
    "url",
    "sent_at",
    "verdict",
]
ALERT_STATE_PATH = dataset_path("ai/telegram_alert_state.csv")
ALERT_STATE_COLUMNS = [
    "alert_scope",
    "url",
    "state_value",
    "updated_at",
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
    except CSV_READ_ERRORS as exc:
        logger.warning(
            "Unreadable Telegram alert log %s (%s: %s); duplicate alerts may be re-sent.",
            ALERT_LOG_PATH,
            type(exc).__name__,
            exc,
        )
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


def _load_alert_state() -> pd.DataFrame:
    if not ALERT_STATE_PATH.exists():
        return pd.DataFrame(columns=ALERT_STATE_COLUMNS)
    try:
        df = pd.read_csv(ALERT_STATE_PATH)
    except CSV_READ_ERRORS as exc:
        logger.warning(
            "Unreadable Telegram alert state %s (%s: %s); state-change alerts may be re-sent.",
            ALERT_STATE_PATH,
            type(exc).__name__,
            exc,
        )
        return pd.DataFrame(columns=ALERT_STATE_COLUMNS)
    for column in ALERT_STATE_COLUMNS:
        if column not in df.columns:
            df[column] = None
    return df[ALERT_STATE_COLUMNS]


def _upsert_alert_state(
    alert_scope: str,
    url: str,
    state_value: str,
    verdict: Optional[str],
) -> None:
    df = _load_alert_state()
    mask = (df["alert_scope"].astype(str) == str(alert_scope)) & (df["url"].astype(str) == str(url))
    updated_at = datetime.now(tz=timezone.utc).isoformat()
    row = {
        "alert_scope": alert_scope,
        "url": url,
        "state_value": state_value,
        "updated_at": updated_at,
        "verdict": verdict,
    }
    if mask.any():
        df.loc[mask, ALERT_STATE_COLUMNS] = [row[column] for column in ALERT_STATE_COLUMNS]
    else:
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(ALERT_STATE_PATH, index=False)


def get_alert_state(alert_scope: str, url: str) -> Optional[str]:
    if not alert_scope or not url:
        return None
    df = _load_alert_state()
    if df.empty:
        return None
    mask = (df["alert_scope"].astype(str) == str(alert_scope)) & (df["url"].astype(str) == str(url))
    if not mask.any():
        return None
    state_value = df.loc[mask, "state_value"].iloc[-1]
    if state_value is None or (isinstance(state_value, float) and pd.isna(state_value)):
        return None
    return str(state_value)


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


def send_on_state_change(
    alert_scope: str,
    url: str,
    state_value: str,
    message: str,
    verdict: Optional[str] = None,
) -> bool:
    if not telegram_enabled() or not url or not state_value or not message.strip():
        return False
    previous_state = get_alert_state(alert_scope, url)
    if previous_state == state_value:
        return False
    sent = send_telegram_message(message)
    if sent:
        _append_alert_log(alert_scope, url, verdict)
        _upsert_alert_state(alert_scope, url, state_value, verdict)
    return sent
