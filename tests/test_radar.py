"""Tests fuer Bewertungslogik, Risikorechnung und Journal."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar.config import Thresholds
from radar.journal import Journal
from radar.model import TokenSnapshot
from radar.risk import (
    expectancy,
    max_position_for_impact,
    plan_position,
    price_impact_pct,
    required_win_rate,
)
from radar.scoring import Stage, evaluate


def make_pair(**overrides) -> dict:
    """Ein plausibles, gesundes Paar als Ausgangspunkt."""
    now_ms = int(time.time() * 1000)
    pair = {
        "chainId": "solana",
        "dexId": "raydium",
        "pairAddress": "PAIR1111",
        "url": "https://dexscreener.com/solana/pair1111",
        "baseToken": {"address": "MINT1111", "symbol": "TEST", "name": "Test Token"},
        "priceUsd": "0.00042",
        "liquidity": {"usd": 120_000.0},
        "fdv": 900_000.0,
        "marketCap": 900_000.0,
        "pairCreatedAt": now_ms - 90 * 60_000,
        "volume": {"m5": 8_000.0, "h1": 240_000.0, "h6": 900_000.0, "h24": 1_500_000.0},
        "priceChange": {"m5": 1.5, "h1": 12.0, "h6": 40.0, "h24": 80.0},
        "txns": {
            "m5": {"buys": 20, "sells": 18},
            "h1": {"buys": 320, "sells": 280},
            "h6": {"buys": 1500, "sells": 1400},
            "h24": {"buys": 4000, "sells": 3800},
        },
        "info": {"socials": [{"type": "twitter"}], "websites": [{"url": "https://x.test"}]},
    }
    pair.update(overrides)
    return pair


class TestModel(unittest.TestCase):
    def test_parses_healthy_pair(self):
        snap = TokenSnapshot.from_pair(make_pair())
        self.assertEqual(snap.symbol, "TEST")
        self.assertEqual(snap.mint, "MINT1111")
        self.assertAlmostEqual(snap.liquidity_usd, 120_000.0)
        self.assertEqual(snap.txns_h1, 600)
        self.assertAlmostEqual(snap.buy_ratio_h1, 320 / 600)
        self.assertAlmostEqual(snap.turnover_h1, 2.0)
        self.assertAlmostEqual(snap.mcap_to_liquidity, 7.5)

    def test_survives_garbage_input(self):
        """Fehlende und falsch typisierte Felder duerfen nicht crashen."""
        snap = TokenSnapshot.from_pair({})
        self.assertEqual(snap.liquidity_usd, 0.0)
        self.assertEqual(snap.txns_h1, 0)
        self.assertEqual(snap.buy_ratio_h1, 0.5)
        self.assertEqual(snap.mcap_to_liquidity, float("inf"))
        self.assertEqual(snap.age_minutes, -1.0)

        weird = TokenSnapshot.from_pair(
            {"priceUsd": "nicht-eine-zahl", "liquidity": "kaputt", "txns": None}
        )
        self.assertEqual(weird.price_usd, 0.0)
        self.assertEqual(weird.liquidity_usd, 0.0)

    def test_string_numbers_are_parsed(self):
        snap = TokenSnapshot.from_pair(make_pair(priceUsd="0.5", fdv="1000"))
        self.assertAlmostEqual(snap.price_usd, 0.5)


class TestHardFilters(unittest.TestCase):
    def setUp(self):
        self.th = Thresholds()

    def test_healthy_token_passes(self):
        verdict = evaluate(TokenSnapshot.from_pair(make_pair()), self.th)
        self.assertEqual(verdict.hard_fails, [], f"unerwartet: {verdict.hard_fails}")
        self.assertGreaterEqual(verdict.score, 50)

    def test_low_liquidity_is_rejected(self):
        pair = make_pair(liquidity={"usd": 3_000.0}, marketCap=20_000.0, fdv=20_000.0)
        verdict = evaluate(TokenSnapshot.from_pair(pair), self.th)
        self.assertTrue(any("Liquiditaet" in f for f in verdict.hard_fails))
        self.assertEqual(verdict.tier, "NO-GO")

    def test_paper_valuation_is_rejected(self):
        """5 Mio. MCap auf 50k Liquiditaet - die Bewertung ist fiktiv."""
        pair = make_pair(liquidity={"usd": 50_000.0}, marketCap=5_000_000.0, fdv=5_000_000.0)
        verdict = evaluate(TokenSnapshot.from_pair(pair), self.th)
        self.assertTrue(any("Papier" in f for f in verdict.hard_fails))

    def test_wash_trading_is_rejected(self):
        pair = make_pair(volume={"m5": 0, "h1": 5_000_000.0, "h6": 0, "h24": 0})
        verdict = evaluate(TokenSnapshot.from_pair(pair), self.th)
        self.assertTrue(any("Wash-Trading" in f for f in verdict.hard_fails))

    def test_one_sided_buying_is_rejected(self):
        pair = make_pair(txns={"m5": {"buys": 0, "sells": 0},
                               "h1": {"buys": 950, "sells": 50},
                               "h6": {}, "h24": {}})
        verdict = evaluate(TokenSnapshot.from_pair(pair), self.th)
        self.assertTrue(any("Gegenseite" in f for f in verdict.hard_fails))

    def test_too_young_is_rejected(self):
        pair = make_pair(pairCreatedAt=int(time.time() * 1000) - 2 * 60_000)
        verdict = evaluate(TokenSnapshot.from_pair(pair), self.th)
        self.assertTrue(any("Sniper" in f for f in verdict.hard_fails))

    def test_dead_token_is_rejected(self):
        pair = make_pair(txns={"h1": {"buys": 3, "sells": 2}}, volume={"h1": 100.0})
        verdict = evaluate(TokenSnapshot.from_pair(pair), self.th)
        self.assertTrue(any("kein echter Markt" in f for f in verdict.hard_fails))


class TestStageDetection(unittest.TestCase):
    def test_blowoff_candle(self):
        """Der wichtigste Fall: senkrechte Kerze bei einseitigem Kaufdruck."""
        pair = make_pair(
            priceChange={"m5": 60.0, "h1": 400.0, "h6": 900.0, "h24": 900.0},
            txns={"h1": {"buys": 800, "sells": 200}},
        )
        verdict = evaluate(TokenSnapshot.from_pair(pair), Thresholds())
        self.assertIs(verdict.stage, Stage.BLOWOFF)
        self.assertLessEqual(verdict.score, 25)

    def test_post_dump(self):
        pair = make_pair(priceChange={"m5": -5.0, "h1": -60.0, "h6": 300.0, "h24": 200.0})
        verdict = evaluate(TokenSnapshot.from_pair(pair), Thresholds())
        self.assertIs(verdict.stage, Stage.NACH_DUMP)

    def test_dead_stage(self):
        pair = make_pair(txns={"h1": {"buys": 1, "sells": 1}}, volume={"h1": 50.0})
        snap = TokenSnapshot.from_pair(pair)
        verdict = evaluate(snap, Thresholds())
        self.assertIs(verdict.stage, Stage.TOT)

    def test_early_stage(self):
        pair = make_pair(
            pairCreatedAt=int(time.time() * 1000) - 25 * 60_000,
            priceChange={"m5": 3.0, "h1": 20.0, "h6": 20.0, "h24": 20.0},
        )
        verdict = evaluate(TokenSnapshot.from_pair(pair), Thresholds())
        self.assertIs(verdict.stage, Stage.FRUEH)


class TestContractReport(unittest.TestCase):
    def test_mint_authority_is_fatal(self):
        report = {"token": {"mintAuthority": "SomeAuthority111"}, "risks": []}
        verdict = evaluate(TokenSnapshot.from_pair(make_pair()), Thresholds(), report)
        self.assertTrue(any("Mint-Authority" in f for f in verdict.hard_fails))
        self.assertEqual(verdict.tier, "NO-GO")

    def test_freeze_authority_is_fatal(self):
        report = {"token": {"freezeAuthority": "Freezer111"}}
        verdict = evaluate(TokenSnapshot.from_pair(make_pair()), Thresholds(), report)
        self.assertTrue(any("einfroren" in f or "Freeze" in f for f in verdict.hard_fails))

    def test_unlocked_liquidity_is_fatal(self):
        report = {"token": {}, "markets": [{"lp": {"lpLockedPct": 4.0}}]}
        verdict = evaluate(TokenSnapshot.from_pair(make_pair()), Thresholds(), report)
        self.assertTrue(any("gesperrt" in f for f in verdict.hard_fails))

    def test_whale_concentration_is_fatal(self):
        report = {"token": {}, "topHolders": [{"pct": 40.0, "owner": "Whale1"}]}
        verdict = evaluate(TokenSnapshot.from_pair(make_pair()), Thresholds(), report)
        self.assertTrue(any("Verkaufsorder" in f for f in verdict.hard_fails))

    def test_clean_report_marks_checked(self):
        report = {
            "token": {"mintAuthority": None, "freezeAuthority": None},
            "markets": [{"lp": {"lpLockedPct": 100.0}}],
            "topHolders": [{"pct": 4.0, "owner": "Holder1"}],
            "risks": [],
        }
        verdict = evaluate(TokenSnapshot.from_pair(make_pair()), Thresholds(), report)
        self.assertTrue(verdict.contract_checked)
        self.assertEqual(verdict.hard_fails, [])

    def test_missing_report_is_flagged_not_fatal(self):
        verdict = evaluate(TokenSnapshot.from_pair(make_pair()), Thresholds(), None)
        self.assertFalse(verdict.contract_checked)
        self.assertTrue(any("nicht verfuegbar" in n for n in verdict.contract_notes))


class TestRisk(unittest.TestCase):
    def test_price_impact_grows_with_size(self):
        small = price_impact_pct(100, 100_000)
        large = price_impact_pct(10_000, 100_000)
        self.assertLess(small, large)
        self.assertLess(small, 1.0)
        self.assertGreater(large, 10.0)

    def test_impact_on_empty_pool(self):
        self.assertEqual(price_impact_pct(1000, 0), 100.0)

    def test_max_position_roundtrips_with_impact(self):
        """max_position_for_impact muss die Umkehrfunktion von price_impact_pct sein."""
        for liquidity in (20_000, 250_000, 3_000_000):
            for target in (0.5, 2.0, 5.0):
                position = max_position_for_impact(liquidity, target)
                self.assertAlmostEqual(price_impact_pct(position, liquidity), target, places=6)

    def test_position_limited_by_risk_budget(self):
        plan = plan_position(bankroll=10_000, liquidity_usd=5_000_000,
                             risk_pct=1.0, stop_pct=50.0)
        self.assertAlmostEqual(plan.position_usd, 200.0)
        self.assertAlmostEqual(plan.risk_usd, 100.0)
        self.assertFalse(plan.liquidity_capped)

    def test_position_limited_by_liquidity(self):
        """Kleiner Pool muss die Position begrenzen, egal wie gross das Konto ist."""
        plan = plan_position(bankroll=1_000_000, liquidity_usd=30_000,
                             risk_pct=1.5, stop_pct=35.0, max_impact_pct=2.0)
        self.assertTrue(plan.liquidity_capped)
        self.assertLess(plan.position_usd, 400)
        self.assertLessEqual(plan.entry_impact_pct, 2.0001)

    def test_invalid_inputs_raise(self):
        with self.assertRaises(ValueError):
            plan_position(bankroll=0, liquidity_usd=100_000)
        with self.assertRaises(ValueError):
            plan_position(bankroll=1000, liquidity_usd=100_000, stop_pct=0)

    def test_expectancy_math(self):
        self.assertAlmostEqual(expectancy(0.5, 1.0), 0.0)
        self.assertAlmostEqual(expectancy(0.25, 3.0), 0.0)
        self.assertLess(expectancy(0.2, 2.0), 0.0)
        self.assertGreater(expectancy(0.4, 3.0), 0.0)

    def test_required_win_rate(self):
        self.assertAlmostEqual(required_win_rate(1.0), 0.5)
        self.assertAlmostEqual(required_win_rate(3.0), 0.25)
        self.assertAlmostEqual(required_win_rate(9.0), 0.1)


class TestJournal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self.tmp.close()
        self.journal = Journal(self.tmp.name)

    def tearDown(self):
        self.journal.close()
        os.unlink(self.tmp.name)

    def test_open_and_close(self):
        trade_id = self.journal.open_trade("MINT", "TEST", 1.0, 100.0, 50.0, source="telegram")
        self.assertEqual(len(self.journal.open_positions()), 1)
        row = self.journal.close_trade(trade_id, 1.5)
        self.assertAlmostEqual(Journal.trade_r(row), 1.0)  # +50% bei 50% Stop = 1R
        self.assertEqual(len(self.journal.open_positions()), 0)

    def test_double_close_is_rejected(self):
        trade_id = self.journal.open_trade("MINT", "TEST", 1.0, 100.0, 50.0)
        self.journal.close_trade(trade_id, 1.5)
        with self.assertRaises(ValueError):
            self.journal.close_trade(trade_id, 2.0)

    def test_unknown_trade_raises(self):
        with self.assertRaises(KeyError):
            self.journal.close_trade(999, 1.0)

    def test_stats_are_correct(self):
        # 1 Gewinner (+2R), 3 Verlierer (-1R) => -1R gesamt, 25% Trefferquote
        wins = [(1.0, 2.0)]      # Einstieg 1.0, Ausstieg 2.0 -> +100% bei 50% Stop = 2R
        losses = [(1.0, 0.5)] * 3  # -50% bei 50% Stop = -1R
        for entry, exit_price in wins + losses:
            trade_id = self.journal.open_trade("M", "T", entry, 100.0, 50.0, stage="frueh")
            self.journal.close_trade(trade_id, exit_price)

        stats = self.journal.stats()
        self.assertEqual(stats.closed, 4)
        self.assertEqual(stats.wins, 1)
        self.assertEqual(stats.losses, 3)
        self.assertAlmostEqual(stats.win_rate, 0.25)
        self.assertAlmostEqual(stats.total_r, -1.0)
        self.assertAlmostEqual(stats.expectancy_r, -0.25)
        self.assertAlmostEqual(stats.avg_win_r, 2.0)
        self.assertAlmostEqual(stats.avg_loss_r, -1.0)

    def test_stats_on_empty_journal(self):
        stats = self.journal.stats()
        self.assertEqual(stats.closed, 0)
        self.assertEqual(stats.win_rate, 0.0)

    def test_rejects_invalid_open(self):
        with self.assertRaises(ValueError):
            self.journal.open_trade("M", "T", 0.0, 100.0, 50.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
