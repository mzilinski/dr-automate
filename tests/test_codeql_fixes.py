"""Regressionstests für CodeQL-Funde (ReDoS in den Zitat-Regexen, Open Redirect)."""

from __future__ import annotations

import time

import pytest

import ki_kontext


@pytest.mark.parametrize("fn", [ki_kontext._strip_citations, ki_kontext._strip_citations_raw])
@pytest.mark.parametrize("text", [" " * 200_000 + "x", "[cite:" * 50_000], ids=["leerraum", "offene_marker"])
def test_zitat_regex_linear(fn, text):
    start = time.perf_counter()
    fn(text)
    # Vorher quadratisch: 40 000 Leerzeichen ≈ 1 s, 200 000 ≈ 25 s; 48 000 Zeichen `[cite:` ≈ 0,1 s.
    assert time.perf_counter() - start < 1.0


@pytest.mark.parametrize(
    ("eingabe", "erwartet"),
    [
        ("Berlin [cite: 1]", "Berlin"),
        ("a  [cite: 1, 2] b", "a b"),
        ("x\n\t[CITE: 4]y", "xy"),
        ("  [cite: 3]", ""),
    ],
)
def test_zitate_werden_weiter_entfernt(eingabe, erwartet):
    assert ki_kontext._strip_citations(eingabe) == erwartet
    assert ki_kontext._strip_citations_raw(eingabe).strip() == erwartet


def test_rohtext_entfernt_start_end_marker():
    assert ki_kontext._strip_citations_raw('[cite_start]{"a": 1}[cite_end]') == '{"a": 1}'


@pytest.mark.parametrize(
    ("referer", "ziel"),
    [
        ("http://localhost/abrechnung?x=1", "/abrechnung"),
        ("http://localhost/gibt-es-nicht", "/"),
        ("http://localhost.evil.example/abrechnung", "/"),
        ("https://evil.example/phish", "/"),
        ("//evil.example/phish", "/"),
        ("/\\evil.example", "/"),
        ("javascript:alert(1)", "/"),
        (None, "/"),
    ],
)
def test_csrf_redirect_bleibt_auf_eigenem_host(app_module, referer, ziel):
    app_module.app.config["WTF_CSRF_ENABLED"] = True
    try:
        headers = {"Accept": "text/html"}
        if referer:
            headers["Referer"] = referer
        with app_module.app.test_client() as c:
            r = c.post("/abrechnung/calc", data={"json_data": "{}"}, headers=headers)
        assert r.status_code == 302
        assert r.headers["Location"] == ziel
    finally:
        app_module.app.config["WTF_CSRF_ENABLED"] = False
