"""HTTP-Clients fuer oeffentliche On-Chain-Datenquellen.

Bewusst ohne externe Abhaengigkeiten (nur stdlib), damit das Tool ueberall
sofort laeuft. Alle Parser sind defensiv: die APIs aendern ihre Schemata
regelmaessig, ein fehlendes Feld darf nie den ganzen Scan killen.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "memecoin-radar/1.0 (+https://github.com/scwerxed/nischeRatschlag)"


class SourceError(RuntimeError):
    """Datenquelle nicht erreichbar oder hat Muell geliefert."""


class _RateLimiter:
    """Simpler Abstandshalter zwischen Requests."""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self) -> None:
        delta = time.monotonic() - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()


class HttpClient:
    def __init__(self, timeout: float = 15.0, min_interval: float = 1.1) -> None:
        self.timeout = timeout
        self.limiter = _RateLimiter(min_interval)

    def get_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        retries: int = 3,
    ) -> Any:
        request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        request_headers.update(headers or {})
        last_error: Exception | None = None

        for attempt in range(retries):
            self.limiter.wait()
            request = urllib.request.Request(url, headers=request_headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8", errors="replace")
                return json.loads(body) if body.strip() else None
            except urllib.error.HTTPError as exc:
                # 4xx ausser 429 sind endgueltig - Retry waere Zeitverschwendung.
                if exc.code == 429:
                    last_error = exc
                    time.sleep(2 ** attempt * 2)
                    continue
                if 400 <= exc.code < 500:
                    raise SourceError(f"{url} -> HTTP {exc.code}") from exc
                last_error = exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
            time.sleep(2 ** attempt)

        raise SourceError(f"{url} nicht erreichbar: {last_error}")


    def post_form(self, url: str, data: dict[str, str], retries: int = 2) -> Any:
        """POST mit formularkodiertem Koerper - fuer Benachrichtigungs-APIs.

        Geheimnisse stehen in der URL oder im Koerper; Fehlermeldungen geben
        deshalb nie den vollstaendigen Request wieder.
        """
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        last_error: Exception | None = None

        for attempt in range(retries):
            self.limiter.wait()
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw.strip() else None
            except urllib.error.HTTPError as exc:
                if 400 <= exc.code < 500 and exc.code != 429:
                    raise SourceError(f"Benachrichtigung abgelehnt: HTTP {exc.code}") from None
                last_error = exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
            time.sleep(2 ** attempt)

        raise SourceError(f"Benachrichtigung fehlgeschlagen: {type(last_error).__name__}")


def _as_pair_list(payload: Any) -> list[dict]:
    """DexScreener liefert je nach Endpoint {'pairs': [...]}, [...] oder null."""
    if payload is None:
        return []
    if isinstance(payload, dict):
        for key in ("pairs", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


class DexScreener:
    """Preis-, Liquiditaets- und Flussdaten. Oeffentlich, kein API-Key."""

    BASE = "https://api.dexscreener.com"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def pairs_for_token(self, mint: str, chain: str = "solana") -> list[dict]:
        """Alle Handelspaare eines Tokens, bestes (liquidestes) zuerst."""
        pairs: list[dict] = []
        try:
            pairs = _as_pair_list(
                self.client.get_json(f"{self.BASE}/latest/dex/tokens/{mint}")
            )
        except SourceError:
            pairs = []
        if not pairs:
            # Neuerer Endpoint als Ausweichweg.
            try:
                pairs = _as_pair_list(
                    self.client.get_json(f"{self.BASE}/tokens/v1/{chain}/{mint}")
                )
            except SourceError:
                pairs = []
        pairs.sort(key=lambda p: _liquidity_of(p), reverse=True)
        return pairs

    def search(self, query: str) -> list[dict]:
        encoded = urllib.parse.quote(query)
        return _as_pair_list(
            self.client.get_json(f"{self.BASE}/latest/dex/search?q={encoded}")
        )

    def token_profiles(self) -> list[dict]:
        """Zuletzt auf DexScreener eingetragene Token (frische Listings)."""
        payload = self.client.get_json(f"{self.BASE}/token-profiles/latest/v1")
        return payload if isinstance(payload, list) else _as_pair_list(payload)

    def boosted(self, top: bool = True) -> list[dict]:
        """Bezahlt beworbene Token.

        Wichtig zum Verstaendnis: ein Boost ist *gekaufte Aufmerksamkeit*, kein
        Qualitaetssignal. Er ist trotzdem nuetzlich - er zeigt, wo in den
        naechsten Stunden Retail-Fluss hinstroemt.
        """
        suffix = "top" if top else "latest"
        payload = self.client.get_json(f"{self.BASE}/token-boosts/{suffix}/v1")
        return payload if isinstance(payload, list) else _as_pair_list(payload)


class RugCheck:
    """Vertrags- und Holder-Risiken (Mint-/Freeze-Authority, LP-Lock, Insider).

    Der oeffentliche Zugang ist zeitweise limitiert. Ein Key in
    RUGCHECK_API_KEY wird automatisch verwendet; ohne Antwort laeuft die
    Analyse weiter, markiert das Ergebnis aber als unvollstaendig.
    """

    BASE = "https://api.rugcheck.xyz/v1"

    def __init__(self, client: HttpClient, api_key: str | None = None) -> None:
        self.client = client
        self.api_key = api_key

    def report(self, mint: str) -> dict | None:
        headers = {"X-API-KEY": self.api_key} if self.api_key else {}
        for path in (f"/tokens/{mint}/report", f"/tokens/{mint}/report/summary"):
            try:
                payload = self.client.get_json(self.BASE + path, headers=headers, retries=2)
            except SourceError:
                continue
            if isinstance(payload, dict):
                return payload
        return None


def _liquidity_of(pair: dict) -> float:
    liquidity = pair.get("liquidity")
    if isinstance(liquidity, dict):
        try:
            return float(liquidity.get("usd") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0
