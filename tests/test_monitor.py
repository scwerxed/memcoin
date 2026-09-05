"""Tests fuer den Dauerbetrieb - vollstaendig ohne Netzwerkzugriff."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar.config import Settings, Thresholds
from radar.model import TokenSnapshot
from radar.monitor import (
    Monitor,
    MonitorConfig,
    RateBudget,
    Watchlist,
    alert_kind,
    next_interval_seconds,
    should_drop,
)
from radar.notify import Alert, Notifier
from radar.scoring import evaluate
from radar.sources import SourceError
from tests.test_radar import make_pair


class SammelNotifier(Notifier):
    """Faengt Alarme ab, statt sie zu versenden."""

    name = "test"

    def __init__(self) -> None:
        self.alarme: list[Alert] = []

    def send(self, alert: Alert) -> None:
        self.alarme.append(alert)


class FakeDex:
    """DexScreener-Ersatz. Zaehlt Aufrufe, damit das Budget pruefbar ist."""

    def __init__(self, profiles=None, pairs_by_mint=None) -> None:
        self._profiles = profiles or []
        self._pairs = pairs_by_mint or {}
        self.calls = {"profiles": 0, "boosted": 0, "pairs": 0}
        self.fail_pairs_for: set[str] = set()

    def token_profiles(self):
        self.calls["profiles"] += 1
        return self._profiles

    def boosted(self, top=True):
        self.calls["boosted"] += 1
        return []

    def pairs_for_token(self, mint, chain="solana"):
        self.calls["pairs"] += 1
        if mint in self.fail_pairs_for:
            raise SourceError("simulierter Ausfall")
        pair = self._pairs.get(mint)
        return [pair] if pair else []


class TestScheduler(unittest.TestCase):
    def setUp(self):
        self.th = Thresholds()

    def test_young_tokens_are_checked_more_often(self):
        """Junge Token muessen engmaschiger geprueft werden als alte."""
        sehr_jung = next_interval_seconds(5, 50, self.th)
        jung = next_interval_seconds(30, 50, self.th)
        mittel = next_interval_seconds(120, 50, self.th)
        alt = next_interval_seconds(1000, 20, self.th)
        self.assertLess(sehr_jung, jung)
        self.assertLess(jung, mittel)
        self.assertLess(mittel, alt)

    def test_promising_old_tokens_keep_attention(self):
        """Ein alter, aber aussichtsreicher Token bekommt mehr Budget als ein alter schwacher."""
        self.assertLess(
            next_interval_seconds(1000, 70, self.th),
            next_interval_seconds(1000, 20, self.th),
        )

    def test_unknown_age_has_sane_default(self):
        self.assertGreater(next_interval_seconds(-1, 0, self.th), 0)


class TestDropLogic(unittest.TestCase):
    def setUp(self):
        self.th = Thresholds()

    def test_missing_pair_tolerated_then_dropped(self):
        """Ein kurzzeitiger Ausfall darf nicht sofort zum Verwerfen fuehren."""
        self.assertIsNone(should_drop(None, None, self.th, checks=1))
        self.assertIsNotNone(should_drop(None, None, self.th, checks=3))

    def test_drained_liquidity_is_dropped(self):
        snap = TokenSnapshot.from_pair(make_pair(liquidity={"usd": 500.0}))
        grund = should_drop(snap, None, self.th, checks=1)
        self.assertIsNotNone(grund)
        self.assertIn("Liquiditaet", grund)

    def test_too_old_is_dropped(self):
        alt_ms = int(time.time() * 1000) - int(self.th.max_age_minutes + 60) * 60_000
        snap = TokenSnapshot.from_pair(make_pair(pairCreatedAt=alt_ms))
        self.assertIsNotNone(should_drop(snap, None, self.th, checks=1))

    def test_dead_token_is_dropped(self):
        pair = make_pair(txns={"h1": {"buys": 1, "sells": 1}}, volume={"h1": 50.0})
        snap = TokenSnapshot.from_pair(pair)
        verdict = evaluate(snap, self.th)
        self.assertIsNotNone(should_drop(snap, verdict, self.th, checks=1))

    def test_healthy_token_is_kept(self):
        snap = TokenSnapshot.from_pair(make_pair())
        verdict = evaluate(snap, self.th)
        self.assertIsNone(should_drop(snap, verdict, self.th, checks=1))


class TestAlertLogic(unittest.TestCase):
    def setUp(self):
        self.th = Thresholds()

    def test_clean_token_alerts_once(self):
        verdict = evaluate(TokenSnapshot.from_pair(make_pair()), self.th)
        self.assertEqual(alert_kind(verdict, already_alerted=False, min_score=50), "kandidat")
        # Zweiter Aufruf darf nicht erneut melden.
        self.assertIsNone(alert_kind(verdict, already_alerted=True, min_score=50))

    def test_hard_fail_never_alerts(self):
        pair = make_pair(liquidity={"usd": 2_000.0}, marketCap=10_000.0, fdv=10_000.0)
        verdict = evaluate(TokenSnapshot.from_pair(pair), self.th)
        self.assertIsNone(alert_kind(verdict, False, min_score=0))

    def test_blowoff_is_never_a_buy_alert(self):
        """Der wichtigste Fall: die Kerze darf nie als Kandidat gemeldet werden."""
        pair = make_pair(priceChange={"m5": 60.0, "h1": 400.0, "h6": 900.0, "h24": 900.0},
                         txns={"h1": {"buys": 800, "sells": 200}})
        verdict = evaluate(TokenSnapshot.from_pair(pair), self.th)
        self.assertIsNone(alert_kind(verdict, already_alerted=False, min_score=0))

    def test_blowoff_alerts_exit_for_known_token(self):
        pair = make_pair(priceChange={"m5": 60.0, "h1": 400.0, "h6": 900.0, "h24": 900.0},
                         txns={"h1": {"buys": 800, "sells": 200}})
        verdict = evaluate(TokenSnapshot.from_pair(pair), self.th)
        self.assertEqual(alert_kind(verdict, already_alerted=True, min_score=0), "ausstieg")

    def test_score_below_threshold_is_silent(self):
        verdict = evaluate(TokenSnapshot.from_pair(make_pair()), self.th)
        self.assertIsNone(alert_kind(verdict, False, min_score=verdict.score + 1))


class TestRateBudget(unittest.TestCase):
    def test_budget_is_enforced(self):
        budget = RateBudget(per_minute=3)
        self.assertTrue(budget.take())
        self.assertTrue(budget.take())
        self.assertTrue(budget.take())
        self.assertFalse(budget.take())
        self.assertEqual(budget.remaining, 0)

    def test_multi_take_respects_limit(self):
        budget = RateBudget(per_minute=3)
        self.assertFalse(budget.take(4))
        self.assertTrue(budget.take(3))


class TestWatchlist(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.tmp.close()
        self.wl = Watchlist(self.tmp.name)

    def tearDown(self):
        self.wl.close()
        os.unlink(self.tmp.name)

    def test_add_is_idempotent(self):
        self.assertTrue(self.wl.add("MINT1", "profil"))
        self.assertFalse(self.wl.add("MINT1", "boost"))
        self.assertEqual(self.wl.stats()["gesamt"], 1)

    def test_due_returns_new_entries(self):
        self.wl.add("MINT1", "profil")
        self.assertEqual(len(self.wl.due(10)), 1)

    def test_updated_entry_is_not_due_again(self):
        self.wl.add("MINT1", "profil")
        self.wl.update_after_check("MINT1", "SYM", 60, "frueh", interval=600, best=60)
        self.assertEqual(self.wl.due(10), [])

    def test_dropped_entry_disappears(self):
        self.wl.add("MINT1", "profil")
        self.wl.drop("MINT1", "tot")
        self.assertEqual(self.wl.due(10), [])
        self.assertEqual(self.wl.stats()["aktiv"], 0)

    def test_survives_reopen(self):
        """Die Liste muss einen Neustart ueberleben."""
        self.wl.add("MINT1", "profil")
        self.wl.close()
        wieder = Watchlist(self.tmp.name)
        self.assertEqual(wieder.stats()["gesamt"], 1)
        self.wl = wieder


class TestMonitorLoop(unittest.TestCase):
    """Vollstaendiger Durchlauf gegen eine gefaelschte API."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.tmp.close()
        self.wl = Watchlist(self.tmp.name)
        self.notifier = SammelNotifier()
        self.settings = Settings()

    def tearDown(self):
        self.wl.close()
        os.unlink(self.tmp.name)

    def _monitor(self, dex, **kw):
        config = MonitorConfig(quiet=True, tick_seconds=0, **kw)
        return Monitor(self.settings, dex, self.wl, self.notifier, config)

    def test_discovers_and_alerts_on_clean_token(self):
        gutes_paar = make_pair(baseToken={"address": "GUT", "symbol": "GUT", "name": "Gut"})
        dex = FakeDex(
            profiles=[{"chainId": "solana", "tokenAddress": "GUT"}],
            pairs_by_mint={"GUT": gutes_paar},
        )
        self._monitor(dex, min_score=50).run(max_ticks=1)

        self.assertEqual(len(self.notifier.alarme), 1)
        alarm = self.notifier.alarme[0]
        self.assertEqual(alarm.kind, "kandidat")
        self.assertEqual(alarm.mint, "GUT")
        self.assertIn("check GUT", alarm.as_text())

    def test_does_not_alert_twice(self):
        dex = FakeDex(
            profiles=[{"chainId": "solana", "tokenAddress": "GUT"}],
            pairs_by_mint={"GUT": make_pair(baseToken={"address": "GUT", "symbol": "GUT"})},
        )
        monitor = self._monitor(dex, min_score=50)
        monitor.run(max_ticks=1)
        # Faellig machen und erneut laufen lassen
        self.wl.conn.execute("UPDATE watchlist SET next_check = 0")
        self.wl.conn.commit()
        monitor.run(max_ticks=1)
        self.assertEqual(len(self.notifier.alarme), 1)

    def test_blowoff_token_is_never_reported_as_candidate(self):
        pump = make_pair(
            baseToken={"address": "PUMP", "symbol": "PUMP"},
            priceChange={"m5": 70.0, "h1": 500.0, "h6": 900.0, "h24": 900.0},
            txns={"h1": {"buys": 900, "sells": 100}},
        )
        dex = FakeDex(profiles=[{"chainId": "solana", "tokenAddress": "PUMP"}],
                      pairs_by_mint={"PUMP": pump})
        self._monitor(dex, min_score=0).run(max_ticks=1)
        self.assertEqual(self.notifier.alarme, [])

    def test_rug_is_dropped_not_alerted(self):
        rug = make_pair(baseToken={"address": "RUG", "symbol": "RUG"},
                        liquidity={"usd": 400.0})
        dex = FakeDex(profiles=[{"chainId": "solana", "tokenAddress": "RUG"}],
                      pairs_by_mint={"RUG": rug})
        self._monitor(dex, min_score=0).run(max_ticks=1)
        self.assertEqual(self.notifier.alarme, [])
        self.assertEqual(self.wl.stats()["aktiv"], 0)

    def test_other_chains_are_ignored(self):
        dex = FakeDex(profiles=[{"chainId": "ethereum", "tokenAddress": "ETHTOKEN"}])
        self._monitor(dex).run(max_ticks=1)
        self.assertEqual(self.wl.stats()["gesamt"], 0)

    def test_api_failure_does_not_crash_loop(self):
        dex = FakeDex(profiles=[{"chainId": "solana", "tokenAddress": "GUT"}],
                      pairs_by_mint={"GUT": make_pair()})
        dex.fail_pairs_for = {"GUT"}
        self._monitor(dex).run(max_ticks=1)  # darf nicht werfen
        self.assertEqual(self.wl.stats()["aktiv"], 1)

    def test_broken_notifier_does_not_stop_monitor(self):
        class KaputterNotifier(Notifier):
            name = "kaputt"

            def send(self, alert):
                raise RuntimeError("Kanal tot")

        dex = FakeDex(profiles=[{"chainId": "solana", "tokenAddress": "GUT"}],
                      pairs_by_mint={"GUT": make_pair(baseToken={"address": "GUT",
                                                                 "symbol": "GUT"})})
        monitor = Monitor(self.settings, dex, self.wl, KaputterNotifier(),
                          MonitorConfig(quiet=True, tick_seconds=0, min_score=50))
        monitor.run(max_ticks=1)  # darf nicht werfen
        self.assertEqual(monitor.counters["gemeldet"], 1)

    def test_budget_limits_checks_per_tick(self):
        profiles = [{"chainId": "solana", "tokenAddress": f"M{i}"} for i in range(20)]
        pairs = {f"M{i}": make_pair(baseToken={"address": f"M{i}", "symbol": f"S{i}"})
                 for i in range(20)}
        dex = FakeDex(profiles=profiles, pairs_by_mint=pairs)
        # Budget 5: 2 fuer den Suchlauf, also hoechstens 3 Pruefungen.
        monitor = self._monitor(dex, requests_per_minute=5, min_score=101)
        monitor.run(max_ticks=1)
        self.assertLessEqual(dex.calls["pairs"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
