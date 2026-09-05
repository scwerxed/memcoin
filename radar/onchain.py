"""Direkte Abfrage der Blockchain ueber einen Solana-RPC-Knoten.

Der Vorteil gegenueber einem Auswertungsdienst: das hier ist die Quelle
selbst. Mint- und Freeze-Authority stehen unveraenderlich im Mint-Konto -
kein Dritter dazwischen, kein Abfragelimit von zehn Berichten pro Minute,
keine Verzoegerung.

Eingerichtet wird der Knoten ueber eine Umgebungsvariable:

    export SOLANA_RPC_URL="https://eu.fluxrpc.com?key=DEIN-SCHLUESSEL"

Der Schluessel steht nirgends im Code und wird nie protokolliert.
"""

from __future__ import annotations

from typing import Any

from .sources import HttpClient, SourceError

# Ohne eigenen Knoten: der oeffentliche Endpunkt. Streng limitiert und fuer
# Dauerbetrieb ungeeignet, aber besser als gar keine Vertragspruefung.
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"


def _redact(url: str) -> str:
    """URL ohne Abfrageteil - dort steht bei den meisten Anbietern der Schluessel."""
    return url.split("?", 1)[0]


class SolanaRpc:
    def __init__(self, url: str | None = None, client: HttpClient | None = None) -> None:
        self.url = url or PUBLIC_RPC
        self.client = client or HttpClient(timeout=20.0, min_interval=0.2)
        self._id = 0

    @property
    def is_custom(self) -> bool:
        return self.url != PUBLIC_RPC

    def _call(self, method: str, params: list) -> Any:
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        antwort = self.client.post_json(self.url, payload)

        if not isinstance(antwort, dict):
            raise SourceError(f"{method}: unerwartete Antwort von {_redact(self.url)}")
        if "error" in antwort:
            fehler = antwort["error"]
            meldung = fehler.get("message") if isinstance(fehler, dict) else str(fehler)
            raise SourceError(f"{method}: {meldung}")
        return antwort.get("result")

    # ----------------------------------------------------------------- #
    def mint_info(self, mint: str) -> dict | None:
        """Geparste Felder des Mint-Kontos: Authorities, Angebot, Nachkommastellen."""
        result = self._call("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        if not isinstance(result, dict):
            return None
        value = result.get("value")
        if not isinstance(value, dict):
            return None  # Konto existiert nicht
        data = value.get("data")
        if not isinstance(data, dict):
            return None  # nicht geparst - kein Token-Mint
        parsed = data.get("parsed")
        if not isinstance(parsed, dict) or parsed.get("type") != "mint":
            return None
        info = parsed.get("info")
        return info if isinstance(info, dict) else None

    def largest_accounts(self, mint: str) -> list[dict]:
        """Die groessten Token-Konten.

        Achtung bei der Auswertung: das groesste Konto ist fast immer der
        Liquiditaetspool selbst. Das ist kein Klumpenrisiko, sondern die
        Handelbarkeit - wer das verwechselt, verwirft jeden gesunden Token.
        """
        result = self._call("getTokenLargestAccounts", [mint])
        if not isinstance(result, dict):
            return []
        value = result.get("value")
        return [item for item in (value or []) if isinstance(item, dict)]

    # ----------------------------------------------------------------- #
    def token_report(self, mint: str) -> dict | None:
        """Bericht in derselben Form, die die Bewertung von RugCheck erwartet."""
        try:
            info = self.mint_info(mint)
        except SourceError:
            return None
        if info is None:
            return None

        bericht: dict[str, Any] = {
            "token": {
                "mintAuthority": info.get("mintAuthority"),
                "freezeAuthority": info.get("freezeAuthority"),
                "supply": info.get("supply"),
                "decimals": info.get("decimals"),
            },
            "_quelle": "rpc",
        }

        try:
            konten = self.largest_accounts(mint)
        except SourceError:
            konten = []

        angebot = _to_float(info.get("supply"))
        if konten and angebot > 0:
            anteile = []
            for konto in konten:
                betrag = _to_float(konto.get("amount"))
                if betrag > 0:
                    anteile.append({
                        "pct": betrag / angebot * 100.0,
                        "address": konto.get("address"),
                    })
            # Bewusst unter eigenem Namen: diese Liste enthaelt Pool-Konten und
            # darf deshalb nicht als Ausschlusskriterium gewertet werden.
            bericht["topHoldersRpc"] = sorted(
                anteile, key=lambda a: a["pct"], reverse=True
            )[:10]

        return bericht


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def merge_reports(rpc: dict | None, rugcheck: dict | None) -> dict | None:
    """Fuehrt beide Quellen zusammen - jede fuer das, worin sie zuverlaessig ist.

    Der Knoten liefert Authorities unmittelbar aus dem Mint-Konto, also
    unbestreitbar. RugCheck steuert bei, was ein reiner Knotenabruf nicht
    hergibt: Sperrung der Liquiditaet und die Aufloesung, welche Halter
    Pools sind und welche echte Wallets.
    """
    if rpc is None:
        return rugcheck
    if rugcheck is None:
        return rpc

    zusammen = dict(rugcheck)
    token = dict(zusammen.get("token") or {})
    # Der Knoten hat bei den Authorities Vorrang.
    for feld in ("mintAuthority", "freezeAuthority", "supply", "decimals"):
        if feld in (rpc.get("token") or {}):
            token[feld] = rpc["token"][feld]
    zusammen["token"] = token

    if "topHoldersRpc" in rpc and "topHolders" not in zusammen:
        zusammen["topHoldersRpc"] = rpc["topHoldersRpc"]
    zusammen["_quelle"] = "rpc+rugcheck"
    return zusammen
