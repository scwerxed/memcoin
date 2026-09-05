"""Tests fuer die direkte Blockchain-Abfrage - ohne Netzwerkzugriff."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar.config import Thresholds
from radar.model import TokenSnapshot
from radar.onchain import PUBLIC_RPC, SolanaRpc, _redact, merge_reports
from radar.scoring import evaluate
from radar.sources import RugCheck, SourceError
from tests.test_radar import make_pair

MINT = "So11111111111111111111111111111111111111112"


class FakeHttp:
    """Antwortet auf JSON-RPC-Aufrufe nach Methodenname."""

    def __init__(self, antworten: dict, fehler: Exception | None = None) -> None:
        self.antworten = antworten
        self.fehler = fehler
        self.aufrufe: list[str] = []

    def post_json(self, url, payload, retries=3):
        method = payload["method"]
        self.aufrufe.append(method)
        if self.fehler:
            raise self.fehler
        return self.antworten.get(method)


def mint_antwort(mint_authority=None, freeze_authority=None, supply="1000000000"):
    return {
        "jsonrpc": "2.0", "id": 1,
        "result": {"value": {"data": {"parsed": {
            "type": "mint",
            "info": {
                "mintAuthority": mint_authority,
                "freezeAuthority": freeze_authority,
                "supply": supply,
                "decimals": 9,
            },
        }}}},
    }


def holder_antwort(betraege):
    return {
        "jsonrpc": "2.0", "id": 2,
        "result": {"value": [{"address": f"KONTO{i}", "amount": str(b)}
                             for i, b in enumerate(betraege)]},
    }


class TestSolanaRpc(unittest.TestCase):
    def test_reads_authorities_from_mint_account(self):
        http = FakeHttp({
            "getAccountInfo": mint_antwort("AuthXYZ", "FreezeXYZ"),
            "getTokenLargestAccounts": holder_antwort([500_000_000, 100_000_000]),
        })
        bericht = SolanaRpc("https://knoten.test?key=geheim", http).token_report(MINT)

        self.assertIsNotNone(bericht)
        self.assertEqual(bericht["token"]["mintAuthority"], "AuthXYZ")
        self.assertEqual(bericht["token"]["freezeAuthority"], "FreezeXYZ")
        self.assertEqual(bericht["_quelle"], "rpc")

    def test_renounced_authorities_are_none(self):
        http = FakeHttp({"getAccountInfo": mint_antwort(None, None),
                         "getTokenLargestAccounts": holder_antwort([1])})
        bericht = SolanaRpc("https://knoten.test", http).token_report(MINT)
        self.assertIsNone(bericht["token"]["mintAuthority"])
        self.assertIsNone(bericht["token"]["freezeAuthority"])

    def test_holder_percentages(self):
        http = FakeHttp({
            "getAccountInfo": mint_antwort(supply="1000"),
            "getTokenLargestAccounts": holder_antwort([600, 200, 50]),
        })
        bericht = SolanaRpc("https://knoten.test", http).token_report(MINT)
        anteile = [round(h["pct"]) for h in bericht["topHoldersRpc"]]
        self.assertEqual(anteile, [60, 20, 5])

    def test_nonexistent_account_returns_none(self):
        http = FakeHttp({"getAccountInfo": {"jsonrpc": "2.0", "id": 1,
                                            "result": {"value": None}}})
        self.assertIsNone(SolanaRpc("https://knoten.test", http).token_report(MINT))

    def test_non_mint_account_returns_none(self):
        """Eine Wallet-Adresse statt einer Mint-Adresse darf nicht durchgehen."""
        http = FakeHttp({"getAccountInfo": {"jsonrpc": "2.0", "id": 1, "result": {
            "value": {"data": {"parsed": {"type": "account", "info": {}}}}}}})
        self.assertIsNone(SolanaRpc("https://knoten.test", http).token_report(MINT))

    def test_rpc_error_is_raised_as_source_error(self):
        http = FakeHttp({"getAccountInfo": {"jsonrpc": "2.0", "id": 1,
                                            "error": {"message": "Limit erreicht"}}})
        with self.assertRaises(SourceError) as ctx:
            SolanaRpc("https://knoten.test", http).mint_info(MINT)
        self.assertIn("Limit erreicht", str(ctx.exception))

    def test_unreachable_node_yields_none_report(self):
        http = FakeHttp({}, fehler=SourceError("Knoten tot"))
        self.assertIsNone(SolanaRpc("https://knoten.test", http).token_report(MINT))

    def test_holder_failure_does_not_lose_authorities(self):
        """Faellt nur die Halterabfrage aus, muessen die Authorities bleiben."""
        class TeilweiseKaputt(FakeHttp):
            def post_json(self, url, payload, retries=3):
                if payload["method"] == "getTokenLargestAccounts":
                    raise SourceError("Zeitueberschreitung")
                return super().post_json(url, payload, retries)

        http = TeilweiseKaputt({"getAccountInfo": mint_antwort("AuthXYZ")})
        bericht = SolanaRpc("https://knoten.test", http).token_report(MINT)
        self.assertEqual(bericht["token"]["mintAuthority"], "AuthXYZ")
        self.assertNotIn("topHoldersRpc", bericht)

    def test_public_node_is_default(self):
        rpc = SolanaRpc()
        self.assertEqual(rpc.url, PUBLIC_RPC)
        self.assertFalse(rpc.is_custom)
        self.assertTrue(SolanaRpc("https://eigener.test?key=x").is_custom)


class TestSecretHandling(unittest.TestCase):
    def test_key_is_stripped_from_error_messages(self):
        """Der Schluessel steht in der URL - er darf in keiner Meldung auftauchen."""
        self.assertEqual(_redact("https://eu.fluxrpc.com?key=GEHEIM123"),
                         "https://eu.fluxrpc.com")

    def test_error_message_contains_no_key(self):
        http = FakeHttp({"getAccountInfo": "kaputt"})
        with self.assertRaises(SourceError) as ctx:
            SolanaRpc("https://eu.fluxrpc.com?key=GEHEIM123", http).mint_info(MINT)
        self.assertNotIn("GEHEIM123", str(ctx.exception))


class TestMergeReports(unittest.TestCase):
    def test_node_wins_on_authorities(self):
        """Der Knoten liest das Mint-Konto selbst - er hat hier Vorrang."""
        rpc = {"token": {"mintAuthority": "AuthXYZ", "freezeAuthority": None},
               "_quelle": "rpc"}
        rug = {"token": {"mintAuthority": None, "freezeAuthority": None},
               "markets": [{"lp": {"lpLockedPct": 100.0}}]}
        zusammen = merge_reports(rpc, rug)
        self.assertEqual(zusammen["token"]["mintAuthority"], "AuthXYZ")
        self.assertEqual(zusammen["markets"][0]["lp"]["lpLockedPct"], 100.0)

    def test_single_source_passes_through(self):
        rug = {"token": {}, "risks": []}
        self.assertIs(merge_reports(None, rug), rug)
        rpc = {"token": {}, "_quelle": "rpc"}
        self.assertIs(merge_reports(rpc, None), rpc)
        self.assertIsNone(merge_reports(None, None))

    def test_rugcheck_holders_beat_rpc_holders(self):
        """RugCheck loest Pools auf, der reine Knotenabruf nicht."""
        rpc = {"token": {}, "topHoldersRpc": [{"pct": 80.0}], "_quelle": "rpc"}
        rug = {"token": {}, "topHolders": [{"pct": 5.0, "owner": "W"}]}
        zusammen = merge_reports(rpc, rug)
        self.assertNotIn("topHoldersRpc", zusammen)
        self.assertEqual(zusammen["topHolders"][0]["pct"], 5.0)


class TestScoringWithRpcReport(unittest.TestCase):
    def setUp(self):
        self.th = Thresholds()
        self.snap = TokenSnapshot.from_pair(make_pair())

    def test_mint_authority_from_node_is_fatal(self):
        bericht = {"token": {"mintAuthority": "AuthXYZ"}, "_quelle": "rpc"}
        verdict = evaluate(self.snap, self.th, bericht)
        self.assertTrue(any("Mint-Authority" in f for f in verdict.hard_fails))

    def test_pool_account_is_not_treated_as_whale(self):
        """Das groesste Konto ist der Pool - das darf kein Ausschluss sein."""
        bericht = {
            "token": {"mintAuthority": None, "freezeAuthority": None},
            "topHoldersRpc": [{"pct": 78.0}, {"pct": 3.0}, {"pct": 2.0}],
            "_quelle": "rpc",
        }
        verdict = evaluate(self.snap, self.th, bericht)
        self.assertEqual(verdict.hard_fails, [])
        self.assertTrue(any("Liquiditaetspool" in n for n in verdict.contract_notes))

    def test_second_holder_concentration_warns(self):
        bericht = {
            "token": {"mintAuthority": None, "freezeAuthority": None},
            "topHoldersRpc": [{"pct": 50.0}, {"pct": 30.0}],
            "_quelle": "rpc",
        }
        verdict = evaluate(self.snap, self.th, bericht)
        self.assertEqual(verdict.hard_fails, [])
        self.assertTrue(any("Zweitgroesster" in w for w in verdict.warnings))

    def test_rpc_source_is_declared(self):
        bericht = {"token": {"mintAuthority": None}, "_quelle": "rpc"}
        verdict = evaluate(self.snap, self.th, bericht)
        self.assertTrue(verdict.contract_checked)
        self.assertTrue(any("RPC-Knoten" in n for n in verdict.contract_notes))
        self.assertTrue(any("Liquiditaet" in n for n in verdict.contract_notes))


class TestRugCheckEndpoint(unittest.TestCase):
    """Der Endpunkt muss mit und ohne /v1 entgegengenommen werden koennen."""

    def test_default_endpoint(self):
        rug = RugCheck(client=None)
        self.assertEqual(rug.base, "https://api.rugcheck.xyz/v1")

    def test_url_without_version_gets_v1(self):
        rug = RugCheck(client=None, base_url="https://api.rugcheck.xyz")
        self.assertEqual(rug.base, "https://api.rugcheck.xyz/v1")

    def test_url_with_version_is_kept(self):
        rug = RugCheck(client=None, base_url="https://api.rugcheck.xyz/v1")
        self.assertEqual(rug.base, "https://api.rugcheck.xyz/v1")

    def test_trailing_slash_and_whitespace_are_tolerated(self):
        """Aus der Zwischenablage kommen Adressen oft mit Schraegstrich oder Leerzeichen."""
        rug = RugCheck(client=None, base_url="  https://eigener.anbieter.test/v1/  ")
        self.assertEqual(rug.base, "https://eigener.anbieter.test/v1")

    def test_custom_provider_endpoint(self):
        rug = RugCheck(client=None, base_url="https://rugcheck.fluxrpc.com")
        self.assertEqual(rug.base, "https://rugcheck.fluxrpc.com/v1")

    def test_request_uses_configured_base_and_header(self):
        class SpionClient:
            def __init__(self):
                self.urls, self.headers = [], []

            def get_json(self, url, headers=None, retries=3):
                self.urls.append(url)
                self.headers.append(headers or {})
                return {"token": {}}

        spion = SpionClient()
        rug = RugCheck(spion, api_key="test-key", base_url="https://eigener.test")
        rug.report("MINT123")
        self.assertEqual(spion.urls[0], "https://eigener.test/v1/tokens/MINT123/report")
        self.assertEqual(spion.headers[0]["X-API-KEY"], "test-key")

    def test_no_header_without_key(self):
        class SpionClient:
            def __init__(self):
                self.headers = []

            def get_json(self, url, headers=None, retries=3):
                self.headers.append(headers or {})
                return {"token": {}}

        spion = SpionClient()
        RugCheck(spion).report("MINT123")
        self.assertNotIn("X-API-KEY", spion.headers[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
