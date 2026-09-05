"""Normalisiertes Datenmodell fuer ein Handelspaar."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


def _f(value: Any, default: float = 0.0) -> float:
    """Robuste Float-Konvertierung - APIs liefern Zahlen mal als String."""
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result else default  # NaN abfangen


def _d(value: Any) -> dict:
    """APIs liefern verschachtelte Felder gelegentlich als String oder null."""
    return value if isinstance(value, dict) else {}


def _l(value: Any) -> list:
    return value if isinstance(value, list) else []


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class TokenSnapshot:
    """Momentaufnahme eines Paares, aus DexScreener-Rohdaten normalisiert."""

    mint: str = ""
    symbol: str = "?"
    name: str = ""
    chain: str = "solana"
    dex: str = ""
    pair_address: str = ""
    url: str = ""

    price_usd: float = 0.0
    liquidity_usd: float = 0.0
    fdv: float = 0.0
    market_cap: float = 0.0
    created_at_ms: int = 0

    volume: dict[str, float] = field(default_factory=dict)
    price_change: dict[str, float] = field(default_factory=dict)
    txns: dict[str, tuple[int, int]] = field(default_factory=dict)

    socials: int = 0
    websites: int = 0
    boosts: int = 0

    raw: dict = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ #
    @classmethod
    def from_pair(cls, pair: dict) -> "TokenSnapshot":
        pair = _d(pair)
        base = _d(pair.get("baseToken"))
        liquidity = _d(pair.get("liquidity"))
        info = _d(pair.get("info"))
        boosts = _d(pair.get("boosts"))

        volume = {
            key: _f(_d(pair.get("volume")).get(key))
            for key in ("m5", "h1", "h6", "h24")
        }
        change = {
            key: _f(_d(pair.get("priceChange")).get(key))
            for key in ("m5", "h1", "h6", "h24")
        }
        txns: dict[str, tuple[int, int]] = {}
        for key in ("m5", "h1", "h6", "h24"):
            entry = _d(_d(pair.get("txns")).get(key))
            txns[key] = (_i(entry.get("buys")), _i(entry.get("sells")))

        return cls(
            mint=str(base.get("address") or ""),
            symbol=str(base.get("symbol") or "?"),
            name=str(base.get("name") or ""),
            chain=str(pair.get("chainId") or "solana"),
            dex=str(pair.get("dexId") or ""),
            pair_address=str(pair.get("pairAddress") or ""),
            url=str(pair.get("url") or ""),
            price_usd=_f(pair.get("priceUsd")),
            liquidity_usd=_f(liquidity.get("usd")),
            fdv=_f(pair.get("fdv")),
            market_cap=_f(pair.get("marketCap") or pair.get("fdv")),
            created_at_ms=_i(pair.get("pairCreatedAt")),
            volume=volume,
            price_change=change,
            txns=txns,
            socials=len(_l(info.get("socials"))),
            websites=len(_l(info.get("websites"))),
            boosts=_i(boosts.get("active")),
            raw=pair if isinstance(pair, dict) else {},
        )

    # --------------------------- abgeleitete Kennzahlen ---------------- #
    @property
    def age_minutes(self) -> float:
        """Alter des Paares in Minuten; -1 wenn unbekannt."""
        if not self.created_at_ms:
            return -1.0
        return max(0.0, (time.time() * 1000 - self.created_at_ms) / 60_000)

    @property
    def txns_h1(self) -> int:
        buys, sells = self.txns.get("h1", (0, 0))
        return buys + sells

    @property
    def buy_ratio_h1(self) -> float:
        """Kaufanteil 0..1. 0.5 = ausgeglichen. Bei 0 Trades: 0.5."""
        buys, sells = self.txns.get("h1", (0, 0))
        total = buys + sells
        return buys / total if total else 0.5

    @property
    def turnover_h1(self) -> float:
        """Volumen(1h) geteilt durch Liquiditaet - wie oft der Pool umgeschlagen wird."""
        if self.liquidity_usd <= 0:
            return 0.0
        return self.volume.get("h1", 0.0) / self.liquidity_usd

    @property
    def mcap_to_liquidity(self) -> float:
        """Bewertung im Verhaeltnis zum tatsaechlich handelbaren Kapital."""
        if self.liquidity_usd <= 0:
            return float("inf")
        return (self.market_cap or self.fdv) / self.liquidity_usd

    @property
    def has_links(self) -> bool:
        return (self.socials + self.websites) > 0

    def short(self) -> str:
        return f"{self.symbol} ({self.mint[:4]}..{self.mint[-4:]})" if self.mint else self.symbol
