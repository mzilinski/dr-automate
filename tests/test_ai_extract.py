"""Tests für ai_extract.py und den /extract Endpoint.

DeepSeek-Aufrufe sind komplett gemockt — keine echten Netzaufrufe.
"""

import io
import json
import os
import sys
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_extract
from app import app

# --- Hilfen ---------------------------------------------------------------


def _make_deepseek_response(content: str) -> MagicMock:
    """Baut ein urlopen-Context-Manager-Mock, das `content` als choices[0].message.content liefert."""
    envelope = {"choices": [{"message": {"content": content}}]}
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps(envelope).encode("utf-8")
    cm.__exit__.return_value = False
    return cm


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.deepseek.com/v1/chat/completions",
        code=code,
        msg="err",
        hdrs=None,
        fp=io.BytesIO(b'{"error":"x"}'),
    )


# --- ai_extract.call_deepseek --------------------------------------------


def test_call_deepseek_returns_parsed_json():
    json_payload = '{"antragsteller": {"name": "Max"}, "reise_details": {}}'
    with patch("ai_extract.urllib.request.urlopen", return_value=_make_deepseek_response(json_payload)):
        result = ai_extract.call_deepseek("Reise nach Berlin", "sk-test", "prompt")
    assert result["antragsteller"]["name"] == "Max"


def test_call_deepseek_strips_code_fences():
    fenced = '```json\n{"foo": "bar"}\n```'
    with patch("ai_extract.urllib.request.urlopen", return_value=_make_deepseek_response(fenced)):
        result = ai_extract.call_deepseek("text", "sk-test", "prompt")
    assert result == {"foo": "bar"}


def test_call_deepseek_appends_sonderwuensche():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode())
        return _make_deepseek_response('{"ok": true}')

    with patch("ai_extract.urllib.request.urlopen", side_effect=fake_urlopen):
        ai_extract.call_deepseek("Reise A", "sk-test", "sys-prompt", sonderwuensche="PKW statt Bahn")

    user_msg = captured["body"]["messages"][1]["content"]
    assert "Reise A" in user_msg
    assert "PKW statt Bahn" in user_msg
    assert "Sonderwünsche" in user_msg


def test_call_deepseek_missing_key_raises_400():
    with pytest.raises(ai_extract.AIExtractError) as exc:
        ai_extract.call_deepseek("text", "", "prompt")
    assert exc.value.status_code == 400


def test_call_deepseek_empty_freitext_raises_400():
    with pytest.raises(ai_extract.AIExtractError) as exc:
        ai_extract.call_deepseek("   ", "sk-test", "prompt")
    assert exc.value.status_code == 400


def test_call_deepseek_too_long_freitext_raises_400():
    huge = "a" * (ai_extract.MAX_FREITEXT_LEN + 1)
    with pytest.raises(ai_extract.AIExtractError) as exc:
        ai_extract.call_deepseek(huge, "sk-test", "prompt")
    assert exc.value.status_code == 400


def test_call_deepseek_http_401_maps_to_401():
    with patch("ai_extract.urllib.request.urlopen", side_effect=_http_error(401)):
        with pytest.raises(ai_extract.AIExtractError) as exc:
            ai_extract.call_deepseek("text", "sk-bad", "prompt")
    assert exc.value.status_code == 401


def test_call_deepseek_http_429_maps_to_429():
    with patch("ai_extract.urllib.request.urlopen", side_effect=_http_error(429)):
        with pytest.raises(ai_extract.AIExtractError) as exc:
            ai_extract.call_deepseek("text", "sk-test", "prompt")
    assert exc.value.status_code == 429


def test_call_deepseek_http_500_maps_to_502():
    with patch("ai_extract.urllib.request.urlopen", side_effect=_http_error(500)):
        with pytest.raises(ai_extract.AIExtractError) as exc:
            ai_extract.call_deepseek("text", "sk-test", "prompt")
    assert exc.value.status_code == 502


def test_call_deepseek_timeout_maps_to_504():
    with patch("ai_extract.urllib.request.urlopen", side_effect=TimeoutError("timed out")):
        with pytest.raises(ai_extract.AIExtractError) as exc:
            ai_extract.call_deepseek("text", "sk-test", "prompt")
    assert exc.value.status_code == 504


def test_call_deepseek_malformed_response_maps_to_502():
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = b"not json at all"
    cm.__exit__.return_value = False
    with patch("ai_extract.urllib.request.urlopen", return_value=cm):
        with pytest.raises(ai_extract.AIExtractError) as exc:
            ai_extract.call_deepseek("text", "sk-test", "prompt")
    assert exc.value.status_code == 502


def test_call_deepseek_non_json_content_maps_to_502():
    with patch("ai_extract.urllib.request.urlopen", return_value=_make_deepseek_response("sorry, kein JSON")):
        with pytest.raises(ai_extract.AIExtractError) as exc:
            ai_extract.call_deepseek("text", "sk-test", "prompt")
    assert exc.value.status_code == 502


# --- /extract Endpoint ---------------------------------------------------


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


def test_extract_endpoint_success(client):
    json_payload = '{"reise_details": {"zielort": "Berlin"}}'
    with patch("ai_extract.urllib.request.urlopen", return_value=_make_deepseek_response(json_payload)):
        resp = client.post(
            "/extract",
            data={"freitext": "Reise nach Berlin"},
            headers={"X-DeepSeek-Key": "sk-test"},
        )
    assert resp.status_code == 200
    assert resp.get_json()["reise_details"]["zielort"] == "Berlin"


def test_extract_endpoint_missing_key(client):
    resp = client.post("/extract", data={"freitext": "egal"})
    assert resp.status_code == 400


def test_extract_endpoint_missing_freitext(client):
    resp = client.post("/extract", data={"freitext": ""}, headers={"X-DeepSeek-Key": "sk-test"})
    assert resp.status_code == 400


def test_extract_endpoint_invalid_key(client):
    with patch("ai_extract.urllib.request.urlopen", side_effect=_http_error(401)):
        resp = client.post(
            "/extract",
            data={"freitext": "Reise"},
            headers={"X-DeepSeek-Key": "sk-bad"},
        )
    assert resp.status_code == 401


def test_extract_endpoint_strips_citations(client):
    json_with_citations = '{"reise_details": {"zielort": "Berlin [cite: 1]"}}'
    with patch("ai_extract.urllib.request.urlopen", return_value=_make_deepseek_response(json_with_citations)):
        resp = client.post(
            "/extract",
            data={"freitext": "Reise"},
            headers={"X-DeepSeek-Key": "sk-test"},
        )
    assert resp.status_code == 200
    assert resp.get_json()["reise_details"]["zielort"] == "Berlin"


def test_extract_endpoint_does_not_log_api_key(client, caplog):
    import logging

    with patch("ai_extract.urllib.request.urlopen", side_effect=_http_error(401)):
        with caplog.at_level(logging.WARNING):
            client.post(
                "/extract",
                data={"freitext": "geheimer text"},
                headers={"X-DeepSeek-Key": "sk-very-secret-key-12345"},
            )
    all_logs = " ".join(r.getMessage() for r in caplog.records)
    assert "sk-very-secret-key-12345" not in all_logs
    assert "geheimer text" not in all_logs
