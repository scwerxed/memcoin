"""Schwellenwerte und Tunables.

Alle Zahlen sind bewusst konservativ. Wer sie aufweicht, verschiebt keine
Wahrscheinlichkeit - er schaltet nur die Warnung ab.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field


@dataclass
class Thresholds:
    """Harte Filter (K.-o.-Kriterien) und weiche Bewertungsgrenzen."""

    # --- Harte Filter: darunter wird gar nicht erst bewertet ---
    min_liquidity_usd: float = 15_000.0
    """Unter ~15k USD Liquiditaet kommst du nicht mehr raus, ohne den Kurs
    selbst zu zerlegen. Der Einstieg ist nie das Problem, der Ausstieg schon."""

    max_mcap_to_liquidity: float = 25.0
    """Marktkapitalisierung / Liquiditaet. Hoher Wert = Papierbewertung.
    Ein Token mit 5 Mio. MCap auf 50k Liquiditaet ist keine 5 Mio. wert."""

    min_age_minutes: float = 10.0
    """Juenger als 10 Minuten: keine belastbaren Daten, reines Sniper-Revier."""

    max_age_minutes: float = 60.0 * 96
    """Aelter als 4 Tage ohne neue Dynamik: der Zug ist durch."""

    min_txns_h1: int = 40
    """Unter 40 Transaktionen pro Stunde ist niemand da ausser Bots."""

    # --- Wash-Trading- und Manipulationserkennung ---
    max_turnover_h1: float = 15.0
    """Volumen(1h) / Liquiditaet. Ueber 15x dreht kein echter Markt,
    das ist ein Bot, der sich selbst handelt, um im Ranking zu stehen."""

    min_turnover_h1: float = 0.15
    """Unter 0.15x passiert schlicht nichts."""

    max_buy_ratio_h1: float = 0.88
    """Anteil Kaeufe an allen Trades. Ueber 88% ist kein Markt, sondern
    eine koordinierte Kampagne - jemand baut die Gegenseite fuer den Ausstieg auf."""

    min_buy_ratio_h1: float = 0.30
    """Unter 30% Kaeufe: der Ausstieg laeuft bereits."""

    # --- FOMO-/Blowoff-Erkennung ---
    blowoff_change_m5: float = 25.0
    """Prozent in 5 Minuten. Wer hier kauft, kauft die Kerze, nicht den Token."""

    blowoff_change_h1: float = 150.0
    postdump_change_h1: float = -30.0

    # --- Risikomanagement ---
    max_risk_per_trade_pct: float = 1.5
    """Prozent des Gesamtkapitals, die pro Trade *maximal verloren* gehen duerfen.
    Bei einer realistischen Trefferquote von 20-30% ueberlebt nichts anderes."""

    max_price_impact_pct: float = 2.0
    """Erlaubter Preiseinfluss der eigenen Order in eine Richtung."""

    default_stop_pct: float = 35.0
    """Memecoins atmen breit. Ein 10%-Stop wird garantiert abgeraeumt."""

    # --- Positive Signale ---
    good_liquidity_usd: float = 80_000.0
    good_txns_h1: int = 300
    good_age_minutes: float = 45.0


@dataclass
class Settings:
    thresholds: Thresholds = field(default_factory=Thresholds)
    chain: str = "solana"
    request_timeout: float = 15.0
    min_request_interval: float = 1.1
    """Sekunden zwischen HTTP-Calls. DexScreener limitiert bei ca. 60/min."""

    rugcheck_api_key: str | None = field(
        default_factory=lambda: os.environ.get("RUGCHECK_API_KEY") or None
    )
    journal_path: str = field(
        default_factory=lambda: os.environ.get("RADAR_JOURNAL", "radar-journal.sqlite3")
    )

    @classmethod
    def load(cls, path: str | None = None) -> "Settings":
        """Laedt Einstellungen aus JSON; fehlende Felder bleiben auf Default."""
        settings = cls()
        path = path or os.environ.get("RADAR_CONFIG")
        if not path or not os.path.exists(path):
            return settings
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        for key, value in raw.items():
            if key == "thresholds" and isinstance(value, dict):
                for tkey, tvalue in value.items():
                    if hasattr(settings.thresholds, tkey):
                        setattr(settings.thresholds, tkey, tvalue)
            elif hasattr(settings, key):
                setattr(settings, key, value)
        return settings

    def dump(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)
