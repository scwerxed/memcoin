"""Tests fuer den Lagebericht - ohne Netzwerkzugriff."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar.config import Settings
from radar.digest import Lagebericht, rendere, rendere_telegram, sammle
from radar.sources import SourceError
from tests.test_radar import make_pair


class FakeDex:
    def __init__(self, boosts=None, profile=None, paare=None, fehler=False):
        self._boosts = boosts or []
        self._profile = profile or []
        self._paare = paare or {}
        self.fehler = fehler

    def boosted(self, top=True):
        if self.fehler:
            raise SourceError("Dienst tot")
        return self._boosts

    def token_profiles(self):
        if self.fehler:
            raise SourceError("Dienst tot")
        return self._profile

    def pairs_for_token(self, mint, chain="solana"):
        paar = self._paare.get(mint)
        return [paar] if paar else []


def gut(adresse, symbol):
    return make_pair(baseToken={"address": adresse, "symbol": symbol, "name": symbol})


def blowoff(adresse, symbol):
    return make_pair(
        baseToken={"address": adresse, "symbol": symbol, "name": symbol},
        priceChange={"m5": 70.0, "h1": 500.0, "h6": 900.0, "h24": 900.0},
        txns={"h1": {"buys": 900, "sells": 100}},
    )


def rug(adresse, symbol):
    return make_pair(baseToken={"address": adresse, "symbol": symbol, "name": symbol},
                     liquidity={"usd": 2_000.0}, marketCap=900_000.0, fdv=900_000.0)


class TestSammeln(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()

    def test_groups_entries_correctly(self):
        dex = FakeDex(
            boosts=[{"chainId": "solana", "tokenAddress": "G", "totalAmount": 500},
                    {"chainId": "solana", "tokenAddress": "B", "totalAmount": 300}],
            profile=[{"chainId": "solana", "tokenAddress": "R"}],
            paare={"G": gut("G", "GUT"), "B": blowoff("B", "PUMP"), "R": rug("R", "RUG")},
        )
        bericht = sammle(dex, self.settings)

        self.assertEqual(bericht.geprueft, 3)
        self.assertEqual([e.snap.symbol for e in bericht.bestanden], ["GUT"])
        self.assertEqual([e.snap.symbol for e in bericht.hype_phase], ["PUMP"])
        self.assertIn("RUG", [e.snap.symbol for e in bericht.ausgeschlossen])

    def test_blowoff_never_counts_as_passing(self):
        """Der zentrale Punkt: was senkrecht laeuft, gilt nie als bestanden."""
        dex = FakeDex(boosts=[{"chainId": "solana", "tokenAddress": "B", "totalAmount": 900}],
                      paare={"B": blowoff("B", "PUMP")})
        bericht = sammle(dex, self.settings)
        self.assertEqual(bericht.bestanden, [])
        self.assertEqual(len(bericht.hype_phase), 1)

    def test_boost_ranking(self):
        dex = FakeDex(
            boosts=[{"chainId": "solana", "tokenAddress": "A", "totalAmount": 100},
                    {"chainId": "solana", "tokenAddress": "B", "totalAmount": 900}],
            paare={"A": gut("A", "AAA"), "B": gut("B", "BBB")},
        )
        bericht = sammle(dex, self.settings)
        self.assertEqual([e.snap.symbol for e in bericht.meist_beworben], ["BBB", "AAA"])

    def test_other_chains_ignored(self):
        dex = FakeDex(boosts=[{"chainId": "ethereum", "tokenAddress": "E"}],
                      paare={"E": gut("E", "ETHX")})
        self.assertEqual(sammle(dex, self.settings).geprueft, 0)

    def test_source_failure_is_recorded_not_swallowed(self):
        bericht = sammle(FakeDex(fehler=True), self.settings)
        self.assertEqual(bericht.geprueft, 0)
        self.assertEqual(len(bericht.fehler), 2)
        self.assertIn("nicht abrufbar", bericht.fehler[0])

    def test_limit_is_respected(self):
        boosts = [{"chainId": "solana", "tokenAddress": f"M{i}"} for i in range(20)]
        paare = {f"M{i}": gut(f"M{i}", f"S{i}") for i in range(20)}
        bericht = sammle(FakeDex(boosts=boosts, paare=paare), self.settings, limit=5)
        self.assertEqual(bericht.geprueft, 5)

    def test_malformed_boost_amount_does_not_crash(self):
        dex = FakeDex(boosts=[{"chainId": "solana", "tokenAddress": "A",
                               "totalAmount": "keine-zahl"}],
                      paare={"A": gut("A", "AAA")})
        self.assertEqual(sammle(dex, Settings()).geprueft, 1)


class TestDarstellung(unittest.TestCase):
    def _bericht(self):
        dex = FakeDex(
            boosts=[{"chainId": "solana", "tokenAddress": "G", "totalAmount": 500},
                    {"chainId": "solana", "tokenAddress": "B", "totalAmount": 900}],
            paare={"G": gut("G", "GUT"), "B": blowoff("B", "PUMP")},
        )
        return sammle(dex, Settings())

    def test_report_names_both_groups(self):
        text = rendere(self._bericht())
        self.assertIn("GUT", text)
        self.assertIn("PUMP", text)
        self.assertIn("senkrecht", text)
        self.assertIn("Kein Kaufsignal", text)

    def test_short_form_omits_hype_detail(self):
        kurz = rendere(self._bericht(), kurz=True)
        self.assertNotIn("Laeuft gerade senkrecht", kurz)

    def test_empty_report_says_so_explicitly(self):
        text = rendere(Lagebericht())
        self.assertIn("leer, nicht unauffaellig", text)

    def test_failures_are_shown(self):
        bericht = Lagebericht()
        bericht.fehler.append("Beworbene Token nicht abrufbar: tot")
        self.assertIn("nicht abrufbar", rendere(bericht))

    def test_telegram_form_fits_limit(self):
        nachricht = rendere_telegram(self._bericht())
        self.assertLessEqual(len(nachricht), 4000)
        self.assertIn("GUT", nachricht)
        self.assertIn("Kein Kaufsignal", nachricht)

    def test_telegram_states_when_nothing_passes(self):
        dex = FakeDex(boosts=[{"chainId": "solana", "tokenAddress": "B"}],
                      paare={"B": blowoff("B", "PUMP")})
        nachricht = rendere_telegram(sammle(dex, Settings()))
        self.assertIn("Nichts besteht die Pruefung", nachricht)
        self.assertIn("nicht einsteigen", nachricht)


if __name__ == "__main__":
    unittest.main(verbosity=2)
