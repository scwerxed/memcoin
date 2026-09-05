"""Tests fuer .env-Datei und menuegefuehrte Bedienung."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar import env_file, menu


class TestEnvDatei(unittest.TestCase):
    def test_parses_simple_pairs(self):
        werte = env_file.parse("SOLANA_RPC_URL=https://knoten.test?key=abc\n"
                               "RUGCHECK_API_KEY=schluessel\n")
        self.assertEqual(werte["SOLANA_RPC_URL"], "https://knoten.test?key=abc")
        self.assertEqual(werte["RUGCHECK_API_KEY"], "schluessel")

    def test_ignores_comments_and_blanks(self):
        werte = env_file.parse("# Kommentar\n\n  \nRUGCHECK_API_KEY=x\n")
        self.assertEqual(werte, {"RUGCHECK_API_KEY": "x"})

    def test_strips_quotes(self):
        """Viele schreiben Anfuehrungszeichen aus Gewohnheit dazu."""
        werte = env_file.parse('SOLANA_RPC_URL="https://knoten.test"\n'
                               "RUGCHECK_API_KEY='geheim'\n")
        self.assertEqual(werte["SOLANA_RPC_URL"], "https://knoten.test")
        self.assertEqual(werte["RUGCHECK_API_KEY"], "geheim")

    def test_only_known_keys_are_taken(self):
        """Eine .env kann fremde Geheimnisse enthalten - die bleiben aussen vor."""
        werte = env_file.parse("AWS_SECRET_ACCESS_KEY=nicht-anfassen\n"
                               "RUGCHECK_API_KEY=ja\n")
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", werte)
        self.assertIn("RUGCHECK_API_KEY", werte)

    def test_url_with_equals_sign_survives(self):
        """RPC-Adressen enthalten '=' im Abfrageteil - darf nicht abgeschnitten werden."""
        werte = env_file.parse("SOLANA_RPC_URL=https://eu.test.com?key=a=b=c\n")
        self.assertEqual(werte["SOLANA_RPC_URL"], "https://eu.test.com?key=a=b=c")

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(env_file.load("/pfad/gibt/es/nicht/.env"), {})

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / ".env"
            env_file.save({"RUGCHECK_API_KEY": "abc123",
                           "SOLANA_RPC_URL": "https://x.test?key=1"}, pfad)
            werte = env_file.parse(pfad.read_text(encoding="utf-8"))
            self.assertEqual(werte["RUGCHECK_API_KEY"], "abc123")
            self.assertEqual(werte["SOLANA_RPC_URL"], "https://x.test?key=1")

    def test_existing_environment_wins(self):
        """Wer eine Variable bewusst im Terminal setzt, darf nicht ueberstimmt werden."""
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / ".env"
            env_file.save({"RUGCHECK_API_KEY": "aus-datei"}, pfad)
            os.environ["RUGCHECK_API_KEY"] = "aus-umgebung"
            try:
                env_file.load(pfad)
                self.assertEqual(os.environ["RUGCHECK_API_KEY"], "aus-umgebung")
            finally:
                del os.environ["RUGCHECK_API_KEY"]

    def test_saved_file_carries_warning(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / ".env"
            env_file.save({"RUGCHECK_API_KEY": "abc"}, pfad)
            inhalt = pfad.read_text(encoding="utf-8")
            self.assertIn("Geheimnisse", inhalt)
            self.assertIn("gitignore", inhalt)


class TestMaskierung(unittest.TestCase):
    def test_long_secret_is_shortened(self):
        maskiert = env_file.masked("631cb3da-8071-4f2e-a05b-af33f4c8eb03")
        self.assertNotIn("8071-4f2e-a05b", maskiert)
        self.assertTrue(maskiert.startswith("631cb3"))

    def test_empty_is_labelled(self):
        self.assertEqual(env_file.masked(None), "(nicht gesetzt)")
        self.assertEqual(env_file.masked(""), "(nicht gesetzt)")


class TestMenueAufrufe(unittest.TestCase):
    """Jede Menueauswahl muss eine gueltige Argumentliste ergeben."""

    def _mit_eingaben(self, eingaben: list[str], wahl: str):
        rest = list(eingaben)
        original = menu._eingabe

        def fake(text, standard=""):
            return rest.pop(0) if rest else standard

        menu._eingabe = fake
        try:
            return menu._baue_aufruf(wahl)
        finally:
            menu._eingabe = original

    def test_check_with_bankroll(self):
        argv = self._mit_eingaben(["MINT123", "5000"], "1")
        self.assertEqual(argv, ["check", "MINT123", "--bankroll", "5000.0"])

    def test_check_without_bankroll(self):
        self.assertEqual(self._mit_eingaben(["MINT123", ""], "1"), ["check", "MINT123"])

    def test_check_without_address_is_rejected(self):
        self.assertIsNone(self._mit_eingaben([""], "1"))

    def test_invalid_bankroll_is_dropped_not_crashing(self):
        argv = self._mit_eingaben(["MINT123", "keine-zahl"], "1")
        self.assertEqual(argv, ["check", "MINT123"])

    def test_scan_only_passing(self):
        self.assertIn("--only-passing", self._mit_eingaben(["j"], "2"))
        self.assertNotIn("--only-passing", self._mit_eingaben(["n"], "2"))

    def test_demo_and_setup(self):
        self.assertEqual(menu._baue_aufruf("6"), ["demo"])
        self.assertEqual(menu._baue_aufruf("7"), ["setup"])

    def test_unknown_choice(self):
        self.assertIsNone(menu._baue_aufruf("99"))

    def test_every_generated_call_parses(self):
        """Die zusammengebauten Argumente muessen vom Parser akzeptiert werden."""
        from radar.cli import build_parser

        faelle = [
            (["MINT123", "5000"], "1"),
            (["j"], "2"),
            (["5000", "", "45000", "1.5", "35"], "4"),
            ([], "6"),
        ]
        parser = build_parser()
        for eingaben, wahl in faelle:
            argv = self._mit_eingaben(eingaben, wahl)
            self.assertIsNotNone(argv, f"Auswahl {wahl} lieferte nichts")
            args = parser.parse_args(argv)  # wirft bei ungueltigen Argumenten
            self.assertTrue(hasattr(args, "func"))

    def test_journal_entries_parse(self):
        from radar.cli import build_parser

        parser = build_parser()
        argv = self._mit_eingaben(["a"], "5")
        self.assertEqual(argv, ["paper", "stats"])
        parser.parse_args(argv)

        argv = self._mit_eingaben(["b", "MINT", "WIF", "0.001", "75", "35", "telegram"], "5")
        args = parser.parse_args(argv)
        self.assertEqual(args.symbol, "WIF")
        self.assertEqual(args.source, "telegram")


class TestOhneTerminal(unittest.TestCase):
    def test_no_args_without_tty_prints_help_instead_of_prompting(self):
        """In cron oder als Dienst darf nie auf eine Eingabe gewartet werden."""
        from radar.cli import main

        echt = sys.stdin.isatty
        sys.stdin.isatty = lambda: False
        try:
            self.assertEqual(main([]), 0)
        finally:
            sys.stdin.isatty = echt


if __name__ == "__main__":
    unittest.main(verbosity=2)
