"""Text-Extraktion aus hochgeladenen PDFs (``/extract``) im Kindprozess.

``/extract`` ist für Gäste offen. pypdf im Worker-Prozess zu parsen hieße:
ein präpariertes PDF (Kompressionsbombe, teure Content-Streams) blockiert
einen der vier gunicorn-Threads unbegrenzt oder treibt den Container
(256 MB) in den OOM-Kill. Deshalb läuft das Parsen in einem eigenen
Python-Prozess mit Wanduhr-Timeout, CPU- und Speicherlimit, und höchstens
zwei Uploads werden gleichzeitig verarbeitet.
"""

import subprocess
import sys
import threading

TIMEOUT_SECONDS = 20
CPU_SECONDS = 15
MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
_EXIT_TOO_MANY_PAGES = 3

_SLOTS = threading.BoundedSemaphore(2)


class PdfTextError(Exception):
    """Fehler mit HTTP-Status fürs Frontend."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def extract(raw: bytes, max_pages: int) -> str:
    """Gibt den Text des PDFs zurück (leer bei Scans ohne Textebene)."""
    if not _SLOTS.acquire(timeout=5):
        raise PdfTextError("Gerade werden zu viele PDFs verarbeitet — bitte gleich noch einmal versuchen.", 503)
    try:
        proc = subprocess.run(  # nosec B603 — fester Interpreter + dieses Modul, keine Nutzereingabe im Befehl
            [sys.executable, "-I", __file__, str(max_pages)],
            input=raw,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise PdfTextError("Das PDF konnte nicht rechtzeitig gelesen werden.") from None
    finally:
        _SLOTS.release()
    if proc.returncode == _EXIT_TOO_MANY_PAGES:
        raise PdfTextError(f"PDF zu lang (max {max_pages} Seiten).")
    if proc.returncode != 0:
        raise PdfTextError("PDF konnte nicht gelesen werden.")
    return proc.stdout.decode("utf-8", errors="replace").strip()


def _child(max_pages: int) -> None:
    import resource

    for limit, value in ((resource.RLIMIT_CPU, CPU_SECONDS), (resource.RLIMIT_AS, MEMORY_LIMIT_BYTES)):
        try:
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            pass  # z. B. RLIMIT_AS unter macOS — der Timeout greift trotzdem

    import io

    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(sys.stdin.buffer.read()))
    if len(reader.pages) > max_pages:
        sys.exit(_EXIT_TOO_MANY_PAGES)
    text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
    sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    _child(int(sys.argv[1]))
