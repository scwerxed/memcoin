"""Vertragspruefung fuer EVM-Ketten (Robinhood Chain, Base, Ethereum ...).

Auf Solana heissen die Gefahren Mint- und Freeze-Authority. Auf EVM-Ketten
gibt es die nicht - dort steckt das Risiko im Vertragscode selbst:

  - eine mint-Funktion, mit der der Besitzer beliebig nachdrucken kann
  - eine Sperrliste, die dein Wallet vom Verkauf ausschliesst
  - ein Handelsschalter, der Verkaeufe abstellt
  - nachtraeglich aenderbare Verkaufsgebuehren (aus 5% werden 99%)
  - ein Proxy, hinter dem der gesamte Code ausgetauscht werden kann

Geprueft wird ueber zwei Wege, die jeder oeffentliche Knoten hergibt:
den ausgelieferten Bytecode (eth_getCode) und direkte Aufrufe (eth_call).

Grenzen, die man kennen muss:
  - Die Suche nach Funktionssignaturen findet, was im Code steht. Ein
    Vertrag kann eine Funktion besitzen, ohne sie je zu benutzen - und
    umgekehrt kann ein Proxy alles verstecken, was hier nicht auftaucht.
  - Ein echter Honeypot-Test wuerde einen Verkauf simulieren. Das braucht
    Router-Kenntnis und ein finanziertes Konto. Diese Pruefung ersetzt das
    nicht - sie faengt die haeufigen, groben Faelle ab.
"""

from __future__ import annotations

from dataclasses import dataclass

from .keccak import selektor
from .sources import HttpClient, SourceError

# Bekannte Ketten: ID -> (Name, oeffentlicher Knoten, Explorer)
KETTEN: dict[int, tuple[str, str, str]] = {
    4663: ("Robinhood Chain", "https://rpc.mainnet.chain.robinhood.com",
           "https://robinhoodchain.blockscout.com"),
    1: ("Ethereum", "https://eth.llamarpc.com", "https://etherscan.io"),
    8453: ("Base", "https://mainnet.base.org", "https://basescan.org"),
    42161: ("Arbitrum", "https://arb1.arbitrum.io/rpc", "https://arbiscan.io"),
}

# DexScreener-Kettenkuerzel -> numerische Ketten-ID
DEX_KETTEN: dict[str, int] = {
    "robinhood": 4663,
    "robinhoodchain": 4663,
    "ethereum": 1,
    "base": 8453,
    "arbitrum": 42161,
}

# EIP-1967: Speicherplatz, in dem ein Proxy seine Logikadresse haelt
SLOT_1967 = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
# EIP-1822 (aeltere Bauart)
SLOT_1822 = "0xc5f16f0fcc639fa48a6947836d9850f504798523bf8c9a3a87d5876cf622bcf7"


@dataclass(frozen=True)
class Codepruefung:
    signatur: str
    gewicht: int
    erklaerung: str


# Gewicht 100 = allein ein Ausschlusskriterium.
PRUEFUNGEN: tuple[Codepruefung, ...] = (
    Codepruefung("mint(address,uint256)", 100,
                 "Der Vertrag kann Token nachdrucken. Wer die Berechtigung hat, "
                 "kann deinen Anteil beliebig verwaessern"),
    Codepruefung("mint(uint256)", 100,
                 "Der Vertrag kann Token nachdrucken (einfache Bauart)"),
    Codepruefung("blacklist(address)", 100,
                 "Sperrliste vorhanden. Deine Adresse kann vom Handel "
                 "ausgeschlossen werden - du haeltst dann etwas, das du nicht "
                 "mehr verkaufen kannst"),
    Codepruefung("addBlackList(address)", 100,
                 "Sperrliste vorhanden (Bauart wie USDT)"),
    Codepruefung("setBlacklist(address,bool)", 100, "Sperrliste vorhanden"),
    Codepruefung("_setBlacklist(address,bool)", 100, "Sperrliste vorhanden"),
    Codepruefung("setTradingEnabled(bool)", 100,
                 "Der Handel laesst sich per Schalter abstellen. Ein Verkauf "
                 "ist dann nicht mehr moeglich"),
    Codepruefung("enableTrading()", 60,
                 "Handelsschalter vorhanden. Ueblich beim Start, bleibt aber "
                 "oft dauerhaft schaltbar"),
    Codepruefung("pause()", 100,
                 "Der Vertrag kann angehalten werden - Uebertragungen und "
                 "damit Verkaeufe stehen dann still"),
    Codepruefung("setFee(uint256)", 70,
                 "Gebuehren sind nachtraeglich aenderbar. Aus 5% Verkaufs"
                 "gebuehr koennen 99% werden, ohne dass du etwas merkst"),
    Codepruefung("setFees(uint256,uint256)", 70, "Gebuehren nachtraeglich aenderbar"),
    Codepruefung("setTaxes(uint256,uint256,uint256)", 70,
                 "Steuersaetze nachtraeglich aenderbar"),
    Codepruefung("setSellTax(uint256)", 80,
                 "Verkaufsgebuehr nachtraeglich aenderbar - der klassische "
                 "Weg, einen Ausstieg unwirtschaftlich zu machen"),
    Codepruefung("setBuyTax(uint256)", 50, "Kaufgebuehr nachtraeglich aenderbar"),
    Codepruefung("setMaxTxAmount(uint256)", 45,
                 "Obergrenze je Transaktion aenderbar - kann so klein gesetzt "
                 "werden, dass ein Verkauf praktisch unmoeglich wird"),
    Codepruefung("setMaxWalletAmount(uint256)", 40,
                 "Obergrenze je Wallet nachtraeglich aenderbar"),
    Codepruefung("excludeFromFee(address)", 25,
                 "Einzelne Adressen koennen von Gebuehren ausgenommen werden - "
                 "ueblich, begünstigt aber Insider"),
    Codepruefung("burnFrom(address,uint256)", 55,
                 "Token koennen aus fremden Wallets verbrannt werden"),
    Codepruefung("setSwapEnabled(bool)", 45, "Tauschfunktion abschaltbar"),
)

# Nur-Lese-Funktionen fuer die Stammdaten
SIG_NAME = "name()"
SIG_SYMBOL = "symbol()"
SIG_DECIMALS = "decimals()"
SIG_SUPPLY = "totalSupply()"
SIG_OWNER = "owner()"
SIG_GETOWNER = "getOwner()"

NULLADRESSE = "0x0000000000000000000000000000000000000000"


def _redact(url: str) -> str:
    return url.split("?", 1)[0]


class EvmRpc:
    def __init__(self, url: str, client: HttpClient | None = None) -> None:
        self.url = url
        self.client = client or HttpClient(timeout=20.0, min_interval=0.2)
        self._id = 0

    def _call(self, methode: str, params: list) -> object:
        self._id += 1
        antwort = self.client.post_json(
            self.url,
            {"jsonrpc": "2.0", "id": self._id, "method": methode, "params": params},
        )
        if not isinstance(antwort, dict):
            raise SourceError(f"{methode}: unerwartete Antwort von {_redact(self.url)}")
        if "error" in antwort:
            fehler = antwort["error"]
            text = fehler.get("message") if isinstance(fehler, dict) else str(fehler)
            raise SourceError(f"{methode}: {text}")
        return antwort.get("result")

    # ----------------------------------------------------------------- #
    def chain_id(self) -> int | None:
        try:
            roh = self._call("eth_chainId", [])
        except SourceError:
            return None
        try:
            return int(str(roh), 16)
        except (TypeError, ValueError):
            return None

    def code(self, adresse: str) -> str:
        roh = self._call("eth_getCode", [adresse, "latest"])
        return str(roh or "0x")

    def lese(self, adresse: str, signatur: str) -> str | None:
        """eth_call ohne Argumente. None, wenn die Funktion fehlt oder abbricht."""
        try:
            roh = self._call("eth_call",
                             [{"to": adresse, "data": "0x" + selektor(signatur)}, "latest"])
        except SourceError:
            return None
        text = str(roh or "0x")
        return None if text in ("0x", "") else text

    def speicher(self, adresse: str, slot: str) -> str:
        roh = self._call("eth_getStorageAt", [adresse, slot, "latest"])
        return str(roh or "0x")


# --------------------------------------------------------------------- #
def dekodiere_adresse(wort: str | None) -> str | None:
    if not wort:
        return None
    roh = wort[2:] if wort.startswith("0x") else wort
    if len(roh) < 40:
        return None
    return "0x" + roh[-40:]


def dekodiere_uint(wort: str | None) -> int | None:
    if not wort:
        return None
    try:
        return int(wort, 16)
    except (TypeError, ValueError):
        return None


def dekodiere_string(rueckgabe: str | None) -> str | None:
    """ABI-kodierte Zeichenkette: Versatz, Laenge, Daten."""
    if not rueckgabe:
        return None
    roh = rueckgabe[2:] if rueckgabe.startswith("0x") else rueckgabe
    try:
        if len(roh) < 128:
            # Manche alten Vertraege liefern bytes32 statt string
            return bytes.fromhex(roh[:64]).rstrip(b"\x00").decode("utf-8", "replace") or None
        laenge = int(roh[64:128], 16)
        daten = roh[128:128 + laenge * 2]
        return bytes.fromhex(daten).decode("utf-8", "replace") or None
    except (ValueError, UnicodeDecodeError):
        return None


def finde_signaturen(bytecode: str) -> list[Codepruefung]:
    """Sucht die Selektoren der bekannten Gefahren im ausgelieferten Code."""
    code = (bytecode or "").lower()
    if not code.startswith("0x") or len(code) <= 2:
        return []
    return [pruefung for pruefung in PRUEFUNGEN if selektor(pruefung.signatur) in code]


def ist_proxy(rpc: EvmRpc, adresse: str) -> str | None:
    """Logikadresse, falls der Vertrag ein aufruestbarer Proxy ist."""
    for slot in (SLOT_1967, SLOT_1822):
        try:
            wert = rpc.speicher(adresse, slot)
        except SourceError:
            continue
        ziel = dekodiere_adresse(wert)
        if ziel and ziel != NULLADRESSE:
            return ziel
    return None


# --------------------------------------------------------------------- #
def token_report(rpc: EvmRpc, adresse: str) -> dict | None:
    """Bericht in der Form, die die Bewertung erwartet."""
    try:
        bytecode = rpc.code(adresse)
    except SourceError:
        return None

    risiken: list[tuple[int, str]] = []
    hinweise: list[str] = []

    if not bytecode or bytecode in ("0x", "0x0"):
        return {
            "_quelle": "evm",
            "evm_risiken": [(100, "An dieser Adresse liegt kein Vertrag. Das ist "
                                  "entweder eine gewoehnliche Wallet oder eine "
                                  "falsche Adresse - in beiden Faellen kein Token")],
            "evm_hinweise": [],
        }

    hinweise.append(f"Vertragscode vorhanden ({(len(bytecode) - 2) // 2:,} Byte)")

    # --- Aufruestbarer Proxy ------------------------------------------ #
    logik = ist_proxy(rpc, adresse)
    if logik:
        risiken.append((100,
                        f"Aufruestbarer Proxy (Logik unter {logik}). Der gesamte "
                        "Vertragscode kann jederzeit ausgetauscht werden - was "
                        "heute geprueft ist, gilt morgen nicht mehr"))

    # --- Besitzer ------------------------------------------------------ #
    besitzer = dekodiere_adresse(rpc.lese(adresse, SIG_OWNER)
                                 or rpc.lese(adresse, SIG_GETOWNER))
    if besitzer is None:
        hinweise.append("Keine owner()-Funktion gefunden")
    elif besitzer == NULLADRESSE:
        hinweise.append("Besitzrechte abgegeben (owner = 0x0)")
    else:
        hinweise.append(f"Besitzer: {besitzer}")

    # --- Gefaehrliche Funktionen im Code ------------------------------- #
    gefunden = finde_signaturen(bytecode)
    hat_besitzer = besitzer not in (None, NULLADRESSE)
    for pruefung in gefunden:
        gewicht = pruefung.gewicht
        text = pruefung.erklaerung
        if not hat_besitzer and gewicht >= 100:
            # Ohne Besitzer ist die Funktion meist nicht mehr aufrufbar.
            gewicht = 40
            text += " (Besitzrechte sind abgegeben, damit vermutlich nicht mehr aufrufbar)"
        risiken.append((gewicht, f"{pruefung.signatur}: {text}"))

    if not gefunden:
        hinweise.append("Keine der bekannten Gefahrenfunktionen im Code gefunden")

    # --- Stammdaten ---------------------------------------------------- #
    name = dekodiere_string(rpc.lese(adresse, SIG_NAME))
    symbol = dekodiere_string(rpc.lese(adresse, SIG_SYMBOL))
    stellen = dekodiere_uint(rpc.lese(adresse, SIG_DECIMALS))
    menge = dekodiere_uint(rpc.lese(adresse, SIG_SUPPLY))
    if symbol:
        hinweise.append(f"Token: {name or '?'} ({symbol}), {stellen} Nachkommastellen")
    if menge is not None and stellen is not None:
        hinweise.append(f"Gesamtmenge: {menge / (10 ** stellen):,.0f}")

    risiken.sort(key=lambda r: r[0], reverse=True)
    return {
        "_quelle": "evm",
        "evm_risiken": risiken,
        "evm_hinweise": hinweise,
        "evm_besitzer": besitzer,
        "evm_proxy": logik,
    }


def knoten_fuer(dex_kette: str, eigene_url: str | None = None) -> tuple[str, str] | None:
    """(Knoten-URL, Kettenname) fuer ein DexScreener-Kettenkuerzel."""
    if eigene_url:
        return eigene_url, dex_kette
    ketten_id = DEX_KETTEN.get((dex_kette or "").lower())
    if ketten_id is None:
        return None
    name, url, _ = KETTEN[ketten_id]
    return url, name
