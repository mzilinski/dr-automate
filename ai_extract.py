"""DeepSeek-API-Client für die Freitext-zu-JSON-Extraktion.

BYOK-Modell: Der API-Key kommt pro Request mit (aus dem Browser/localStorage)
und wird hier nur durchgereicht — nicht gespeichert, nicht geloggt.
"""

import json
import re
import urllib.error
import urllib.request

DEEPSEEK_ENDPOINT = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT_SECONDS = 60
MAX_FREITEXT_LEN = 50_000

_CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?([\s\S]*?)\n?```\s*$", re.MULTILINE)


class AIExtractError(Exception):
    """Strukturierter Fehler mit HTTP-Status fürs Frontend."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _strip_code_fences(text: str) -> str:
    m = _CODE_FENCE_RE.match(text.strip())
    return m.group(1).strip() if m else text.strip()


def call_deepseek(
    freitext: str,
    api_key: str,
    system_prompt: str,
    sonderwuensche: str = "",
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Schickt Freitext an DeepSeek und gibt das geparste JSON zurück.

    Wirft AIExtractError mit passendem Status-Code:
      400  Eingaben fehlen/zu groß
      401  ungültiger API-Key
      429  Rate-Limit beim Provider
      502  Provider-Fehler / Parse-Fehler
      504  Timeout
    """
    if not api_key or not api_key.strip():
        raise AIExtractError("API-Key fehlt", status_code=400)
    if not freitext or not freitext.strip():
        raise AIExtractError("Freitext fehlt", status_code=400)
    if len(freitext) > MAX_FREITEXT_LEN:
        raise AIExtractError(f"Freitext zu lang (max {MAX_FREITEXT_LEN} Zeichen)", status_code=400)

    user_content = freitext.strip()
    if sonderwuensche and sonderwuensche.strip():
        user_content += "\n\n---\nZusätzliche Hinweise/Sonderwünsche:\n" + sonderwuensche.strip()

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    req = urllib.request.Request(
        DEEPSEEK_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — hardcoded HTTPS endpoint
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        # DeepSeek liefert bei 401/429 strukturierte Fehler — leiten wir kategorisiert weiter.
        if e.code == 401:
            raise AIExtractError("API-Key ungültig oder abgelaufen", status_code=401) from None
        if e.code == 429:
            raise AIExtractError("Rate-Limit bei DeepSeek erreicht", status_code=429) from None
        raise AIExtractError(f"DeepSeek-Fehler (HTTP {e.code})", status_code=502) from None
    except urllib.error.URLError as e:
        # TimeoutError ist eine Unterklasse von OSError, kommt hier als reason an.
        if isinstance(e.reason, TimeoutError):
            raise AIExtractError("DeepSeek-Anfrage hat zu lange gedauert", status_code=504) from None
        raise AIExtractError("Verbindung zu DeepSeek fehlgeschlagen", status_code=502) from None
    except TimeoutError:
        raise AIExtractError("DeepSeek-Anfrage hat zu lange gedauert", status_code=504) from None

    try:
        envelope = json.loads(body)
        content = envelope["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        raise AIExtractError("Unerwartete Antwort von DeepSeek", status_code=502) from None

    cleaned = _strip_code_fences(content)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        raise AIExtractError("DeepSeek hat kein valides JSON geliefert", status_code=502) from None
