import json
import logging
from types import SimpleNamespace

import openai
import pandas as pd
import pytest

from scripts import classify_repair_review_queue as cli
from shared.repair_ai_classifier import (
    AI_SUGGESTION_COLUMNS,
    ASTRA_MAX_COMPLETION_TOKENS,
    ASTRA_TIMEOUT_SECONDS,
    ClassifierResult,
    classify_repair_review_queue,
    load_ai_suggestions,
)


def suggestion(key="unknown fragment"):
    return {
        "repair_key": key,
        "decision": "Leave unclassified",
        "target_category": "",
        "canonical_defect": "",
        "severity_hint": "",
        "cost_model": "",
        "confidence": 0.5,
        "rationale": "The fragment needs operator review.",
    }


def completion(payload=None, *, content=None, finish_reason="stop", refusal=None):
    if content is None:
        content = json.dumps(payload if payload is not None else {"suggestions": [suggestion()]})
    return SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(content=content, refusal=refusal),
        )],
        usage=SimpleNamespace(
            prompt_tokens=321,
            completion_tokens=123,
            prompt_tokens_details=SimpleNamespace(cached_tokens=100),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=20),
        ),
    )


@pytest.fixture
def sdk(monkeypatch):
    state = SimpleNamespace(response=completion(), options=[], requests=[], error=None)

    def create(**kwargs):
        state.requests.append(kwargs)
        if state.error:
            raise state.error
        return state.response

    def client(**kwargs):
        state.options.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(openai, "OpenAI", client)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-sent")
    monkeypatch.delenv("AUTOSNIPER_REPAIR_AI_MODEL", raising=False)
    return state


@pytest.fixture
def paths(tmp_path):
    queue = tmp_path / "queue.csv"
    output = tmp_path / "suggestions.csv"
    pd.DataFrame([{
        "repair_key": "unknown fragment",
        "repair_item": "Unknown fragment.",
        "status": "unclassified",
        "category": "unclassified",
        "canonical_defects": "",
    }]).to_csv(queue, index=False)
    return queue, output


def test_astra_request_uses_low_reasoning_strict_schema_and_bounded_cost(sdk, paths, caplog):
    queue, output = paths
    with caplog.at_level(logging.INFO, logger="shared.repair_ai_classifier"):
        result = classify_repair_review_queue(queue_path=queue, output_path=output)

    assert not result.failed and result.suggested == 1
    request = sdk.requests[0]
    assert request["model"] == "gpt-6-astra"
    assert request["reasoning_effort"] == "low"
    assert "temperature" not in request
    assert request["max_completion_tokens"] == ASTRA_MAX_COMPLETION_TOKENS
    assert sdk.options == [{"timeout": ASTRA_TIMEOUT_SECONDS, "max_retries": 1}]
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["strict"] is True
    prompt = json.loads(request["messages"][1]["content"])
    assert prompt["rows"][0]["repair_key"] == "unknown fragment"
    assert load_ai_suggestions(output).iloc[0]["model"] == "gpt-6-astra"
    assert "prompt_tokens=321 completion_tokens=123 cached_tokens=100 reasoning_tokens=20" in caplog.text
    assert "elapsed_seconds=" in caplog.text
    assert "test-key-never-sent" not in caplog.text
    assert "Unknown fragment" not in caplog.text
    status = json.loads((output.parent / "repair_ai_run_status.json").read_text(encoding="utf-8"))
    history = pd.read_csv(output.parent / "repair_ai_run_history.csv").fillna("")
    assert status["status"] == "complete"
    assert status["model"] == "gpt-6-astra"
    assert status["considered"] == 1 and status["suggested"] == 1
    assert status["prompt_tokens"] == 321 and status["completion_tokens"] == 123
    assert status["cached_tokens"] == 100 and status["reasoning_tokens"] == 20
    assert history.iloc[-1]["status"] == "complete"


@pytest.mark.parametrize(
    "override,environment,expected",
    [
        (None, "gpt-4.1-mini", "gpt-4.1-mini"),
        ("gpt-4.1-mini", "gpt-6-astra", "gpt-4.1-mini"),
        ("gpt-6-astra", "gpt-4.1-mini", "gpt-6-astra"),
        (None, "", "gpt-6-astra"),
    ],
)
def test_model_override_precedence_and_legacy_rollback(sdk, paths, monkeypatch, override, environment, expected):
    queue, output = paths
    monkeypatch.setenv("AUTOSNIPER_REPAIR_AI_MODEL", environment)
    result = classify_repair_review_queue(queue_path=queue, output_path=output, model=override)

    assert not result.failed and result.suggested == 1
    assert sdk.requests[0]["model"] == expected
    if expected == "gpt-4.1-mini":
        assert sdk.requests[0]["temperature"] == 0
        assert "reasoning_effort" not in sdk.requests[0]
        assert "max_completion_tokens" not in sdk.requests[0]
        assert sdk.options == [{}]


@pytest.mark.parametrize("response", [
    completion(content=""),
    completion(content=" "),
    completion(content="not json"),
    completion(content="{}"),
    completion(content="[]"),
    completion(content="null"),
    completion(refusal="Cannot classify"),
    completion(finish_reason="length"),
    completion(finish_reason="content_filter"),
    SimpleNamespace(choices=[], usage=None),
    completion({"suggestions": []}),
    completion({"suggestions": None}),
    completion({"suggestions": [None]}),
    completion({"suggestions": [suggestion("unexpected")]}),
    completion({"suggestions": [suggestion(), suggestion()]}),
    completion({"suggestions": [suggestion(), suggestion("extra")]}),
    completion({"suggestions": [suggestion()], "extra": True}),
    completion({"suggestions": [{"repair_key": "unknown fragment"}]}),
    completion({"suggestions": [{**suggestion(), "decision": "Invented decision"}]}),
    completion({"suggestions": [{**suggestion(), "confidence": float("nan")}]}),
    completion({"suggestions": [{**suggestion(), "confidence": True}]}),
    completion({"suggestions": [{**suggestion(), "confidence": 1.5}]}),
    completion({"suggestions": [{**suggestion(), "canonical_defect": []}]}),
])
def test_invalid_api_response_preserves_existing_file(sdk, paths, response):
    queue, output = paths
    sdk.response = response
    # Force refresh must preserve even the old suggestion for the requested key.
    pd.DataFrame([{
        "repair_key": "unknown fragment",
        "repair_item": "Previous operator-facing suggestion",
        "model": "gpt-4.1-mini",
    }]).to_csv(output, index=False)
    before = output.read_bytes()

    result = classify_repair_review_queue(queue_path=queue, output_path=output, force=True)

    assert result.failed
    assert result.considered == 1 and result.suggested == 0
    assert result.skipped_reason
    assert output.read_bytes() == before


def test_partial_response_cannot_write_a_subset(sdk, paths):
    queue, output = paths
    rows = pd.read_csv(queue).fillna("")
    second = rows.iloc[0].to_dict()
    second["repair_key"] = "another fragment"
    pd.concat([rows, pd.DataFrame([second])], ignore_index=True).to_csv(queue, index=False)

    result = classify_repair_review_queue(queue_path=queue, output_path=output)

    assert result.failed and result.considered == 2
    assert "missing=1" in result.skipped_reason
    assert not output.exists()


def test_null_content_fails_closed(sdk, paths):
    queue, output = paths
    sdk.response.choices[0].message.content = None
    result = classify_repair_review_queue(queue_path=queue, output_path=output)
    assert result.failed and "Empty repair classification response" in result.skipped_reason
    assert not output.exists()


@pytest.mark.parametrize("keys", [[], ["wrong key"], ["unknown fragment", "unknown fragment"]])
def test_injected_caller_cannot_bypass_coverage_check(paths, keys):
    queue, output = paths
    result = classify_repair_review_queue(
        queue_path=queue,
        output_path=output,
        caller=lambda rows, **kwargs: pd.DataFrame({"repair_key": keys}),
    )
    assert result.failed and not output.exists()


def test_dry_run_skips_api_without_writing(sdk, paths):
    queue, output = paths
    result = classify_repair_review_queue(queue_path=queue, output_path=output, dry_run=True)
    assert not result.failed and result.suggested == 0
    assert result.skipped_reason == "dry_run: classifier call skipped"
    assert not sdk.requests
    assert not output.exists()
    assert not (output.parent / "repair_ai_run_status.json").exists()
    assert not (output.parent / "repair_ai_run_history.csv").exists()


def test_cache_identity_includes_repair_item_until_force_refresh(sdk, paths):
    queue, output = paths
    pd.DataFrame([{
        "repair_key": "unknown fragment",
        "repair_item": "Old suggestion",
        "model": "gpt-4.1-mini",
    }]).to_csv(output, index=False)

    refreshed_for_new_item = classify_repair_review_queue(queue_path=queue, output_path=output)
    assert refreshed_for_new_item.considered == 1 and len(sdk.requests) == 1

    refreshed = classify_repair_review_queue(queue_path=queue, output_path=output, force=True)
    assert refreshed.suggested == 1 and len(sdk.requests) == 2
    saved = load_ai_suggestions(output)
    assert len(saved) == 1 and list(saved.columns) == AI_SUGGESTION_COLUMNS
    assert saved.iloc[0]["model"] == "gpt-6-astra"


def test_cli_api_failure_has_nonzero_exit(sdk, paths, monkeypatch, capsys):
    queue, output = paths
    sdk.error = TimeoutError("request timed out")
    monkeypatch.setattr("sys.argv", ["classify", "--queue", str(queue), "--output", str(output)])
    assert cli.main() == 1
    assert "repair_ai_classifier_failed=TimeoutError: request timed out" in capsys.readouterr().out
    assert not output.exists()


def test_cli_missing_key_remains_an_optional_successful_skip(paths, monkeypatch, capsys):
    queue, output = paths
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["classify", "--queue", str(queue), "--output", str(output)])
    assert cli.main() == 0
    assert "repair_ai_classifier_skipped=OPENAI_API_KEY missing" in capsys.readouterr().out
    assert not output.exists()


def test_cli_success_exit(paths, monkeypatch, capsys):
    queue, output = paths
    monkeypatch.setattr("sys.argv", ["classify", "--queue", str(queue), "--output", str(output)])
    monkeypatch.setattr(cli, "classify_repair_review_queue", lambda **kwargs: ClassifierResult(1, 1, output))
    assert cli.main() == 0
    assert "repair_ai_classifier_complete considered=1 suggested=1" in capsys.readouterr().out
