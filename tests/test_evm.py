"""Tests fuer Keccak-256 und die EVM-Vertragspruefung - ohne Netzwerk."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar.config import Thresholds
from radar.evm import (
    NULLADRESSE,
    SLOT_1967,
    EvmRpc,
    dekodiere_adresse,
    dekodiere_string,
    dekodiere_uint,
    finde_signaturen,
    knoten_fuer,
    token_report,
)
from radar.keccak import keccak256, selektor
from radar.model import TokenSnapshot
from radar.scoring import evaluate
from radar.sources import SourceError
from tests.test_radar import make_pair


class TestKeccak(unittest.TestCase):
    """Gegen die offiziellen Vektoren - ohne das ist jeder Selektor Zufall."""

    def test_official_vectors(self):
        self.assertEqual(
            keccak256(b"").hex(),
            "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")
        self.assertEqual(
            keccak256(b"abc").hex(),
            "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45")
        self.assertEqual(
            keccak256(b"testing").hex(),
            "5f16f4c7f149ac4f9510d9cf8cf384038ad348b3bcdc01915f95de12df9d1b02")

    def test_known_selectors(self):
        for signatur, erwartet in [
            ("transfer(address,uint256)", "a9059cbb"),
            ("balanceOf(address)", "70a08231"),
            ("approve(address,uint256)", "095ea7b3"),
            ("totalSupply()", "18160ddd"),
            ("owner()", "8da5cb5b"),
            ("mint(address,uint256)", "40c10f19"),
            ("renounceOwnership()", "715018a6"),
            ("transferOwnership(address)", "f2fde38b"),
            ("pause()", "8456cb59"),
        ]:
            self.assertEqual(selektor(signatur), erwartet, signatur)

    def test_long_input_spans_blocks(self):
        """Mehr als 136 Byte erzwingt mehrere Aufsaug-Runden."""
        self.assertEqual(len(keccak256(b"a" * 500)), 32)
        self.assertNotEqual(keccak256(b"a" * 136), keccak256(b"a" * 137))


class TestDekodierung(unittest.TestCase):
    def test_address(self):
        wort = "0x" + "00" * 12 + "1234567890abcdef1234567890abcdef12345678"
        self.assertEqual(dekodiere_adresse(wort),
                         "0x1234567890abcdef1234567890abcdef12345678")

    def test_zero_address(self):
        self.assertEqual(dekodiere_adresse("0x" + "00" * 32), NULLADRESSE)

    def test_uint(self):
        self.assertEqual(dekodiere_uint("0x" + "00" * 31 + "12"), 18)
        self.assertIsNone(dekodiere_uint(None))

    def test_dynamic_string(self):
        text = b"Peptides"
        kodiert = ("0x" + "20".rjust(64, "0")
                   + hex(len(text))[2:].rjust(64, "0")
                   + text.hex().ljust(64, "0"))
        self.assertEqual(dekodiere_string(kodiert), "Peptides")

    def test_garbage_does_not_crash(self):
        for wert in (None, "0x", "0xzz", "nicht-hex"):
            dekodiere_adresse(wert)
            dekodiere_uint(wert)
            dekodiere_string(wert)


class TestSignatursuche(unittest.TestCase):
    def test_finds_mint(self):
        code = "0x6080" + selektor("mint(address,uint256)") + "abcdef"
        treffer = [p.signatur for p in finde_signaturen(code)]
        self.assertIn("mint(address,uint256)", treffer)

    def test_clean_code_finds_nothing(self):
        self.assertEqual(finde_signaturen("0x" + "60" * 200), [])

    def test_empty_code(self):
        self.assertEqual(finde_signaturen("0x"), [])
        self.assertEqual(finde_signaturen(""), [])

    def test_case_insensitive(self):
        code = ("0x" + selektor("pause()").upper()).replace("0X", "0x")
        self.assertTrue(any(p.signatur == "pause()" for p in finde_signaturen(code)))


class FakeRpc:
    """Antwortet auf JSON-RPC nach Methode und - bei eth_call - nach Selektor."""

    def __init__(self, code="0x", aufrufe=None, speicher=None, fehler=False):
        self._code = code
        self._aufrufe = aufrufe or {}
        self._speicher = speicher or {}
        self.fehler = fehler

    def post_json(self, url, payload, retries=3):
        if self.fehler:
            raise SourceError("Knoten tot")
        methode = payload["method"]
        if methode == "eth_getCode":
            return {"result": self._code}
        if methode == "eth_getStorageAt":
            return {"result": self._speicher.get(payload["params"][1], "0x" + "00" * 32)}
        if methode == "eth_call":
            sel = payload["params"][0]["data"][2:10]
            wert = self._aufrufe.get(sel)
            if wert is None:
                return {"error": {"message": "execution reverted"}}
            return {"result": wert}
        return {"result": None}


def wort_adresse(adresse: str) -> str:
    return "0x" + "00" * 12 + adresse[2:]


class TestTokenReport(unittest.TestCase):
    def _rpc(self, **kw):
        return EvmRpc("https://knoten.test", FakeRpc(**kw))

    def test_no_contract_is_fatal(self):
        bericht = token_report(self._rpc(code="0x"), "0xabc")
        self.assertEqual(bericht["evm_risiken"][0][0], 100)
        self.assertIn("kein Vertrag", bericht["evm_risiken"][0][1])

    def test_mint_with_owner_is_fatal(self):
        code = "0x" + selektor("mint(address,uint256)") + "00" * 50
        besitzer = "0x1111111111111111111111111111111111111111"
        bericht = token_report(
            self._rpc(code=code,
                      aufrufe={selektor("owner()"): wort_adresse(besitzer)}),
            "0xabc")
        schwer = [t for g, t in bericht["evm_risiken"] if g >= 100]
        self.assertTrue(any("nachdrucken" in t for t in schwer))
        self.assertEqual(bericht["evm_besitzer"], besitzer)

    def test_mint_without_owner_is_downgraded(self):
        """Ohne Besitzer ist eine mint-Funktion meist nicht mehr aufrufbar."""
        code = "0x" + selektor("mint(address,uint256)") + "00" * 50
        bericht = token_report(
            self._rpc(code=code,
                      aufrufe={selektor("owner()"): "0x" + "00" * 32}),
            "0xabc")
        self.assertEqual([g for g, _ in bericht["evm_risiken"] if g >= 100], [])
        self.assertTrue(any("abgegeben" in t for _, t in bericht["evm_risiken"]))

    def test_proxy_is_fatal(self):
        logik = "0x2222222222222222222222222222222222222222"
        bericht = token_report(
            self._rpc(code="0x6080" + "00" * 50,
                      speicher={SLOT_1967: wort_adresse(logik)}),
            "0xabc")
        self.assertEqual(bericht["evm_proxy"], logik)
        self.assertTrue(any(g >= 100 and "Proxy" in t
                            for g, t in bericht["evm_risiken"]))

    def test_blacklist_is_fatal(self):
        code = "0x" + selektor("blacklist(address)") + "00" * 50
        besitzer = "0x1111111111111111111111111111111111111111"
        bericht = token_report(
            self._rpc(code=code, aufrufe={selektor("owner()"): wort_adresse(besitzer)}),
            "0xabc")
        self.assertTrue(any(g >= 100 and "Sperrliste" in t
                            for g, t in bericht["evm_risiken"]))

    def test_sell_tax_setter_is_a_warning(self):
        code = "0x" + selektor("setSellTax(uint256)") + "00" * 50
        besitzer = "0x1111111111111111111111111111111111111111"
        bericht = token_report(
            self._rpc(code=code, aufrufe={selektor("owner()"): wort_adresse(besitzer)}),
            "0xabc")
        gewichte = [g for g, _ in bericht["evm_risiken"]]
        self.assertTrue(any(40 <= g < 100 for g in gewichte))

    def test_clean_contract_has_no_risks(self):
        bericht = token_report(
            self._rpc(code="0x6080" + "60" * 200,
                      aufrufe={selektor("owner()"): "0x" + "00" * 32}),
            "0xabc")
        self.assertEqual(bericht["evm_risiken"], [])
        self.assertTrue(any("abgegeben" in h for h in bericht["evm_hinweise"]))

    def test_unreachable_node_returns_none(self):
        self.assertIsNone(token_report(self._rpc(fehler=True), "0xabc"))

    def test_risks_sorted_by_severity(self):
        code = ("0x" + selektor("mint(address,uint256)")
                + selektor("excludeFromFee(address)") + "00" * 50)
        besitzer = "0x1111111111111111111111111111111111111111"
        bericht = token_report(
            self._rpc(code=code, aufrufe={selektor("owner()"): wort_adresse(besitzer)}),
            "0xabc")
        gewichte = [g for g, _ in bericht["evm_risiken"]]
        self.assertEqual(gewichte, sorted(gewichte, reverse=True))


class TestKnotenwahl(unittest.TestCase):
    def test_robinhood_chain_is_known(self):
        url, name = knoten_fuer("robinhood")
        self.assertIn("robinhood", url)
        self.assertEqual(name, "Robinhood Chain")

    def test_own_url_wins(self):
        url, _ = knoten_fuer("robinhood", "https://eigener.knoten.test")
        self.assertEqual(url, "https://eigener.knoten.test")

    def test_unknown_chain_without_url(self):
        self.assertIsNone(knoten_fuer("irgendeinekette"))


class TestBewertungMitEvm(unittest.TestCase):
    def test_fatal_evm_risk_becomes_hard_fail(self):
        snap = TokenSnapshot.from_pair(make_pair())
        bericht = {"_quelle": "evm",
                   "evm_risiken": [(100, "Sperrliste vorhanden")],
                   "evm_hinweise": ["Kette: Robinhood Chain"]}
        verdict = evaluate(snap, Thresholds(), bericht)
        self.assertIn("Sperrliste vorhanden", verdict.hard_fails)
        self.assertEqual(verdict.tier, "NO-GO")

    def test_medium_risk_becomes_warning(self):
        snap = TokenSnapshot.from_pair(make_pair())
        bericht = {"_quelle": "evm", "evm_risiken": [(70, "Gebuehren aenderbar")],
                   "evm_hinweise": []}
        verdict = evaluate(snap, Thresholds(), bericht)
        self.assertEqual(verdict.hard_fails, [])
        self.assertIn("Gebuehren aenderbar", verdict.warnings)

    def test_honeypot_limit_is_declared(self):
        """Die Grenze der Pruefung muss im Bericht stehen, nicht im Kleingedruckten."""
        snap = TokenSnapshot.from_pair(make_pair())
        verdict = evaluate(snap, Thresholds(),
                           {"_quelle": "evm", "evm_risiken": [], "evm_hinweise": []})
        self.assertTrue(verdict.contract_checked)
        self.assertTrue(any("Honeypot" in n for n in verdict.contract_notes))

    def test_solana_report_still_works(self):
        """Der Solana-Pfad darf durch die Erweiterung nicht kaputtgehen."""
        snap = TokenSnapshot.from_pair(make_pair())
        verdict = evaluate(snap, Thresholds(),
                           {"token": {"mintAuthority": "Auth1"}, "_quelle": "rpc"})
        self.assertTrue(any("Mint-Authority" in f for f in verdict.hard_fails))


if __name__ == "__main__":
    unittest.main(verbosity=2)
