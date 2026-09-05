"""Benachrichtigungskanaele fuer den Dauerbetrieb.

Bewusst getrennt vom Monitor, damit ein ausgefallener Kanal (Telegram down,
Datei nicht schreibbar) nie die Ueberwachung selbst stoppt.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass

from .sources import HttpClient, SourceError


@dataclass
class Alert:
    kind: str
    """'kandidat' = Filter bestanden, 'ausstieg' = Blowoff bei beobachtetem Token."""

    symbol: str
    mint: str
    score: int
    stage: str
    price_usd: float
    liquidity_usd: float
    age_minutes: float
    url: str
    lines: list[str]

    def as_text(self) -> str:
        kopf = {
            "kandidat": "FILTER BESTANDEN",
            "ausstieg": "BLOWOFF - AUSSTIEGSSIGNAL",
        }.get(self.kind, self.kind.upper())

        age = f"{self.age_minutes:.0f} Min." if self.age_minutes < 120 else f"{self.age_minutes / 60:.1f} Std."
        teile = [
            f"[{kopf}] {self.symbol}",
            f"Score {self.score}/100   Phase {self.stage}   Alter {age}",
            f"Preis {self.price_usd:.10f} USD   Liquiditaet {self.liquidity_usd:,.0f} USD",
            f"Mint: {self.mint}",
        ]
        if self.url:
            teile.append(self.url)
        teile.extend(self.lines)
        teile.append("")
        teile.append("Kein Kaufsignal. Vor jedem Einstieg einzeln pruefen:")
        teile.append(f"  python3 run.py check {self.mint}")
        return "\n".join(teile)

    def as_dict(self) -> dict:
        return {
            "zeit": int(time.time()),
            "art": self.kind,
            "symbol": self.symbol,
            "mint": self.mint,
            "score": self.score,
            "phase": self.stage,
            "preis_usd": self.price_usd,
            "liquiditaet_usd": self.liquidity_usd,
            "alter_minuten": round(self.age_minutes, 1),
            "url": self.url,
            "hinweise": self.lines,
        }


class Notifier:
    name = "basis"

    def send(self, alert: Alert) -> None:  # pragma: no cover - Schnittstelle
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    name = "konsole"

    def send(self, alert: Alert) -> None:
        print()
        print("=" * 72)
        print(alert.as_text())
        print("=" * 72)
        sys.stdout.flush()


class FileNotifier(Notifier):
    """Schreibt eine Zeile JSON pro Alarm - auswertbar, ohne den Monitor zu stoppen."""

    name = "datei"

    def __init__(self, path: str) -> None:
        self.path = path

    def send(self, alert: Alert) -> None:
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(alert.as_dict(), ensure_ascii=False) + "\n")


class TelegramNotifier(Notifier):
    """Schickt Alarme an deinen eigenen Bot.

    Einrichtung: bei @BotFather einen Bot anlegen, dann

        export TELEGRAM_BOT_TOKEN="123456:ABC..."
        export TELEGRAM_CHAT_ID="deine-chat-id"

    Die Chat-ID bekommst du, indem du deinem Bot einmal schreibst und
    https://api.telegram.org/bot<TOKEN>/getUpdates aufrufst.

    Das ist die sinnvolle Nutzung von Telegram in diesem Zusammenhang: dein
    eigener Kanal, in den nur deine eigene Analyse laeuft - statt eines
    Kanals, in dem dir jemand anderes sagt, was du kaufen sollst.
    """

    name = "telegram"

    def __init__(self, token: str, chat_id: str, client: HttpClient | None = None) -> None:
        if not token or not chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID muessen gesetzt sein")
        self._token = token
        self.chat_id = chat_id
        self.client = client or HttpClient(timeout=15.0, min_interval=0.5)

    def send(self, alert: Alert) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        self.client.post_form(url, {
            "chat_id": self.chat_id,
            "text": alert.as_text()[:4000],
            "disable_web_page_preview": "true",
        })

    def __repr__(self) -> str:  # Token nie in Logs oder Tracebacks
        return f"TelegramNotifier(chat_id={self.chat_id!r})"


class NotifierGroup(Notifier):
    """Verteilt an mehrere Kanaele. Ein Ausfall darf die anderen nicht mitnehmen."""

    name = "gruppe"

    def __init__(self, notifiers: list[Notifier]) -> None:
        self.notifiers = notifiers

    def send(self, alert: Alert) -> None:
        for notifier in self.notifiers:
            try:
                notifier.send(alert)
            except (SourceError, OSError, ValueError) as exc:
                print(f"  [Warnung] Kanal '{notifier.name}' fehlgeschlagen: {exc}",
                      file=sys.stderr)


def build_notifiers(console: bool = True, file_path: str | None = None,
                    telegram: bool = False) -> NotifierGroup:
    """Baut die Kanaele aus Flags und Umgebungsvariablen."""
    kanaele: list[Notifier] = []
    if console:
        kanaele.append(ConsoleNotifier())
    if file_path:
        kanaele.append(FileNotifier(file_path))
    if telegram:
        kanaele.append(TelegramNotifier(
            os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            os.environ.get("TELEGRAM_CHAT_ID", ""),
        ))
    return NotifierGroup(kanaele)
