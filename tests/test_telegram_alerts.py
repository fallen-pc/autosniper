from __future__ import annotations

import pandas as pd

from shared import telegram_alerts


def _configure_alert_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(telegram_alerts, "ALERT_LOG_PATH", tmp_path / "telegram_alert_log.csv")
    monkeypatch.setattr(telegram_alerts, "ALERT_STATE_PATH", tmp_path / "telegram_alert_state.csv")


def _enable_telegram(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")


def test_send_once_records_success_and_suppresses_duplicate(monkeypatch, tmp_path) -> None:
    _configure_alert_paths(monkeypatch, tmp_path)
    _enable_telegram(monkeypatch)
    sent_messages: list[str] = []
    monkeypatch.setattr(telegram_alerts, "send_telegram_message", lambda message: sent_messages.append(message) or True)

    assert telegram_alerts.send_once("listing_bid_ready", "https://example.test/car-1", "Buy candidate", "Buy") is True
    assert telegram_alerts.send_once("listing_bid_ready", "https://example.test/car-1", "Buy candidate again", "Buy") is False

    assert sent_messages == ["Buy candidate"]
    log_df = pd.read_csv(telegram_alerts.ALERT_LOG_PATH)
    assert log_df[["alert_type", "url", "verdict"]].to_dict("records") == [
        {
            "alert_type": "listing_bid_ready",
            "url": "https://example.test/car-1",
            "verdict": "Buy",
        }
    ]


def test_send_on_state_change_persists_latest_state_and_suppresses_unchanged(monkeypatch, tmp_path) -> None:
    _configure_alert_paths(monkeypatch, tmp_path)
    _enable_telegram(monkeypatch)
    sent_messages: list[str] = []
    monkeypatch.setattr(telegram_alerts, "send_telegram_message", lambda message: sent_messages.append(message) or True)

    assert telegram_alerts.send_on_state_change(
        "daily_ai_analysis_summary",
        "daily",
        "buy_count=1",
        "One Buy candidate",
        "Buy",
    ) is True
    assert telegram_alerts.send_on_state_change(
        "daily_ai_analysis_summary",
        "daily",
        "buy_count=1",
        "Duplicate summary",
        "Buy",
    ) is False
    assert telegram_alerts.send_on_state_change(
        "daily_ai_analysis_summary",
        "daily",
        "buy_count=0",
        "No Buy candidates",
        "Watch",
    ) is True

    assert sent_messages == ["One Buy candidate", "No Buy candidates"]
    assert telegram_alerts.get_alert_state("daily_ai_analysis_summary", "daily") == "buy_count=0"
    state_df = pd.read_csv(telegram_alerts.ALERT_STATE_PATH)
    assert len(state_df) == 1
    assert state_df.iloc[0][["alert_scope", "url", "state_value", "verdict"]].to_dict() == {
        "alert_scope": "daily_ai_analysis_summary",
        "url": "daily",
        "state_value": "buy_count=0",
        "verdict": "Watch",
    }


def test_alert_helpers_do_not_write_when_telegram_disabled(monkeypatch, tmp_path) -> None:
    _configure_alert_paths(monkeypatch, tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(
        telegram_alerts,
        "send_telegram_message",
        lambda message: (_ for _ in ()).throw(AssertionError("should not send")),
    )

    assert telegram_alerts.send_once("listing_bid_ready", "https://example.test/car-1", "Buy candidate") is False
    assert telegram_alerts.send_on_state_change("listing_bid_ready", "https://example.test/car-1", "Buy", "Buy") is False
    assert not telegram_alerts.ALERT_LOG_PATH.exists()
    assert not telegram_alerts.ALERT_STATE_PATH.exists()
