"""Tests fuer Pre-Launch-Calls, Textpruefung und Promoter-Bilanz."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar.dossier import erstelle_dossier, rendere
from radar.news import Meldung, parse_rss
from radar.prelaunch import (
    CallRegister,
    bewerte_promoter,
    pruefe_namenskollision,
    pruefe_text,
)


class TestTextpruefung(unittest.TestCase):
    def test_send_funds_is_fatal(self):
        """Die Aufforderung, vorab Geld zu schicken, ist immer toedlich."""
        for text in [
            "Sende 0.5 SOL an die Adresse unten",
            "Send 1 SOL to this wallet for your allocation",
            "Ueberweise ETH an die Presale Wallet",
        ]:
            befund = pruefe_text(text)
            self.assertTrue(befund.toedlich, f"nicht erkannt: {text}")
            self.assertEqual(befund.einstufung, "BETRUGSMUSTER")

    def test_presale_wallet_is_fatal(self):
        befund = pruefe_text("Der Presale startet, hier die Wallet: abc123")
        self.assertTrue(befund.toedlich)

    def test_guaranteed_returns_flagged(self):
        befund = pruefe_text("Garantierter Gewinn, risikofrei!")
        self.assertGreaterEqual(befund.punkte, 60)
        self.assertFalse(befund.toedlich)

    def test_referral_is_flagged(self):
        self.assertGreater(pruefe_text("Nutze meinen ref code XYZ").punkte, 40)

    def test_insider_claim_is_flagged(self):
        befund = pruefe_text("Geheimtipp nur fuer unsere Gruppe, early access")
        self.assertGreater(befund.punkte, 45)

    def test_exchange_listing_claim(self):
        self.assertGreater(pruefe_text("Binance Listing bestaetigt!").punkte, 50)

    def test_clean_text_scores_zero(self):
        befund = pruefe_text(
            "Neuer Community-Token, Launch morgen 18 Uhr auf pump.fun. "
            "Kein Presale. Contract wird beim Launch veroeffentlicht."
        )
        self.assertEqual(befund.punkte, 0)
        self.assertEqual(befund.einstufung, "UNAUFFAELLIG")
        self.assertFalse(befund.toedlich)

    def test_empty_text_is_neutral(self):
        for wert in (None, "", "   "):
            self.assertEqual(pruefe_text(wert).punkte, 0)

    def test_findings_sorted_by_severity(self):
        befund = pruefe_text("100x garantiert, sende SOL an die Presale Wallet, ref code")
        gewichte = [g for g, _ in befund.treffer]
        self.assertEqual(gewichte, sorted(gewichte, reverse=True))

    def test_leverage_is_not_a_price_target(self):
        """'10x Hebel' ist kein Kursziel - darf nicht als solches zaehlen."""
        self.assertEqual(pruefe_text("Handel mit 10x Hebel").punkte, 0)


class TestNamenskollision(unittest.TestCase):
    def _paar(self, symbol, adresse, liq):
        return {"baseToken": {"symbol": symbol, "address": adresse},
                "liquidity": {"usd": liq}}

    def test_counts_distinct_tokens(self):
        paare = [self._paar("MCAT", "A", 50000), self._paar("MCAT", "A", 40000),
                 self._paar("MCAT", "B", 500)]
        gesamt, tot = pruefe_namenskollision(paare, "MCAT")
        self.assertEqual(gesamt, 2)   # A und B, A nur einmal
        self.assertEqual(tot, 1)      # B ist tot

    def test_other_symbols_ignored(self):
        paare = [self._paar("MCAT", "A", 5000), self._paar("DOGE", "B", 5000)]
        self.assertEqual(pruefe_namenskollision(paare, "MCAT")[0], 1)

    def test_case_insensitive(self):
        paare = [self._paar("mcat", "A", 5000)]
        self.assertEqual(pruefe_namenskollision(paare, "MCAT")[0], 1)

    def test_empty_ticker(self):
        self.assertEqual(pruefe_namenskollision([], ""), (0, 0))


class TestNewsParsing(unittest.TestCase):
    RSS = """<?xml version="1.0"?><rss><channel>
      <item><title>Neuer Token MCAT gestartet</title><link>https://a.test/1</link>
        <source>Kryptoblatt</source><pubDate>Mon, 01 Sep 2026</pubDate></item>
      <item><title>MCAT: Anleger melden Rug Pull</title><link>https://a.test/2</link>
        <source>Kryptoblatt</source><pubDate>Tue, 02 Sep 2026</pubDate></item>
    </channel></rss>"""

    def test_parses_items(self):
        meldungen = parse_rss(self.RSS)
        self.assertEqual(len(meldungen), 2)
        self.assertEqual(meldungen[0].quelle, "Kryptoblatt")

    def test_detects_warnings(self):
        meldungen = parse_rss(self.RSS)
        self.assertFalse(meldungen[0].ist_warnung)
        self.assertTrue(meldungen[1].ist_warnung)

    def test_broken_xml_is_empty(self):
        self.assertEqual(parse_rss("<rss><unclosed"), [])

    def test_limit_is_respected(self):
        self.assertEqual(len(parse_rss(self.RSS, limit=1)), 1)


class TestCallRegister(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.tmp.close()
        self.reg = CallRegister(self.tmp.name)

    def tearDown(self):
        self.reg.close()
        os.unlink(self.tmp.name)

    def test_add_and_read(self):
        call_id = self.reg.add(name="MoonCat", promoter="@king", ticker="mcat")
        eintrag = self.reg.get(call_id)
        self.assertEqual(eintrag["ticker"], "MCAT")  # normalisiert
        self.assertEqual(eintrag["status"], "offen")

    def test_requires_name_and_promoter(self):
        with self.assertRaises(ValueError):
            self.reg.add(name="", promoter="@king")
        with self.assertRaises(ValueError):
            self.reg.add(name="X", promoter="  ")

    def test_link_to_launched_token(self):
        call_id = self.reg.add(name="MoonCat", promoter="@king", ticker="MCAT")
        self.reg.verknuepfe(call_id, "MINT1", 15, "blowoff", 8000.0, True)
        eintrag = self.reg.get(call_id)
        self.assertEqual(eintrag["status"], "gelauncht")
        self.assertEqual(eintrag["mint"], "MINT1")
        self.assertEqual(eintrag["ausschluss_beim_start"], 1)

    def test_open_only_filter(self):
        offen = self.reg.add(name="A", promoter="@p", ticker="A")
        zu = self.reg.add(name="B", promoter="@p", ticker="B")
        self.reg.verknuepfe(zu, "M", 60, "frueh", 50000.0, False)
        ids = [e["id"] for e in self.reg.liste(nur_offen=True)]
        self.assertEqual(ids, [offen])

    def test_invalid_status_rejected(self):
        call_id = self.reg.add(name="A", promoter="@p")
        with self.assertRaises(ValueError):
            self.reg.setze_status(call_id, "quatsch")

    def test_promoter_balance(self):
        """Ein Promoter mit lauter NO-GOs muss als solcher erkennbar sein."""
        for i in range(6):
            call_id = self.reg.add(name=f"T{i}", promoter="@schrott", ticker=f"T{i}")
            self.reg.verknuepfe(call_id, f"M{i}", 12, "blowoff", 5000.0, True)
        for i in range(4):
            call_id = self.reg.add(name=f"G{i}", promoter="@gut", ticker=f"G{i}")
            self.reg.verknuepfe(call_id, f"N{i}", 65, "frueh", 90000.0, False)
        self.reg.add(name="G9", promoter="@gut", ticker="G9")
        self.reg.setze_status(self.reg.add(name="G8", promoter="@gut", ticker="G8"),
                              "verschwunden")

        bilanz = self.reg.promoter_bilanz()
        self.assertEqual(bilanz[0]["promoter"], "@schrott", "Schlechtester zuerst")

        schrott = next(b for b in bilanz if b["promoter"] == "@schrott")
        self.assertEqual(schrott["ausschluss"], 6)
        self.assertIn("kostet Geld", bewerte_promoter(schrott))

        gut = next(b for b in bilanz if b["promoter"] == "@gut")
        self.assertEqual(gut["gelauncht"], 4)
        self.assertEqual(gut["verschwunden"], 1)
        self.assertEqual(gut["offen"], 1)

    def test_too_few_calls_says_so(self):
        call_id = self.reg.add(name="A", promoter="@neu", ticker="A")
        self.reg.verknuepfe(call_id, "M", 60, "frueh", 50000.0, False)
        eintrag = self.reg.promoter_bilanz()[0]
        self.assertIn("zu wenig", bewerte_promoter(eintrag))


class TestDossier(unittest.TestCase):
    def test_fatal_text_marks_dossier(self):
        dossier = erstelle_dossier(
            name="MoonCat", promoter="@king", ticker="MCAT",
            promo_text="Sende 0.5 SOL an die Presale Wallet",
        )
        self.assertTrue(dossier.ist_toedlich)
        text = rendere(dossier)
        self.assertIn("BETRUGSMUSTER", text)
        self.assertIn("existiert noch nicht auf der Blockchain", text)

    def test_unqueried_sources_are_labelled_as_such(self):
        """'Nicht abgefragt' darf nie als 'unauffaellig' erscheinen."""
        text = rendere(erstelle_dossier(name="X", promoter="@p", ticker="X",
                                        promo_text="harmlos"))
        self.assertIn("Nicht abgefragt", text)

    def test_failed_query_is_distinguished_from_not_queried(self):
        class KaputterDex:
            def search(self, q):
                from radar.sources import SourceError
                raise SourceError("tot")

        dossier = erstelle_dossier(name="X", promoter="@p", ticker="XYZ",
                                   promo_text="harmlos", dex=KaputterDex())
        self.assertTrue(dossier.kollision_versucht)
        self.assertFalse(dossier.kollision_geprueft)
        self.assertIn("unvollstaendig, nicht unauffaellig", rendere(dossier))

    def test_news_warning_makes_it_fatal(self):
        class NewsStub:
            def erwaehnungen(self, name, limit=8):
                return []

            def warnungen(self, name, limit=8):
                return [Meldung("XYZ scam confirmed", "https://a.test", "Blatt", "")]

        dossier = erstelle_dossier(name="XYZ", promoter="@p", promo_text="harmlos",
                                   news=NewsStub())
        self.assertTrue(dossier.ist_toedlich)
        self.assertIn("Betrugsmeldungen", rendere(dossier))

    def test_clean_dossier_still_refuses_to_endorse(self):
        text = rendere(erstelle_dossier(name="X", promoter="@p", promo_text="harmlos"))
        self.assertIn("nicht bewertbar", text)
        self.assertNotIn("Kaufsignal", text.split("Fazit")[-1].replace("kein", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
