"""Dossier zu einem Pre-Launch-Call: was laesst sich ueberhaupt pruefen."""

from __future__ import annotations

from dataclasses import dataclass, field

from .news import Meldung, News
from .prelaunch import Textbefund, pruefe_namenskollision, pruefe_text
from .sources import DexScreener, SourceError


@dataclass
class Dossier:
    name: str
    ticker: str | None
    promoter: str
    text: Textbefund
    kollisionen: int = 0
    tote_kollisionen: int = 0
    kollision_versucht: bool = False
    kollision_geprueft: bool = False
    meldungen: list[Meldung] = field(default_factory=list)
    warnungen: list[Meldung] = field(default_factory=list)
    news_versucht: bool = False
    news_geprueft: bool = False
    promoter_urteil: str | None = None
    promoter_zahlen: dict | None = None

    @property
    def ist_toedlich(self) -> bool:
        return self.text.toedlich or bool(self.warnungen)


def erstelle_dossier(name: str, promoter: str, ticker: str | None = None,
                     promo_text: str | None = None,
                     dex: DexScreener | None = None,
                     news: News | None = None,
                     promoter_eintrag: dict | None = None) -> Dossier:
    """Sammelt alles Pruefbare. Ausgefallene Quellen werden ausgewiesen,
    nicht stillschweigend als 'unauffaellig' verbucht."""
    dossier = Dossier(name=name, ticker=ticker, promoter=promoter,
                      text=pruefe_text(promo_text))

    if dex is not None and ticker:
        dossier.kollision_versucht = True
        try:
            paare = dex.search(ticker)
        except SourceError:
            paare = []
        else:
            dossier.kollision_geprueft = True
        dossier.kollisionen, dossier.tote_kollisionen = pruefe_namenskollision(
            paare, ticker
        )

    if news is not None:
        dossier.news_versucht = True
        dossier.meldungen = news.erwaehnungen(name)
        dossier.warnungen = news.warnungen(name)
        dossier.news_geprueft = True

    if promoter_eintrag:
        from .prelaunch import bewerte_promoter
        dossier.promoter_zahlen = promoter_eintrag
        dossier.promoter_urteil = bewerte_promoter(promoter_eintrag)

    return dossier


def rendere(dossier: Dossier) -> str:
    zeilen: list[str] = []
    add = zeilen.append

    add("=" * 72)
    kopf = dossier.name + (f"  [{dossier.ticker}]" if dossier.ticker else "")
    add(kopf[:72])
    add(f"Angekuendigt von: {dossier.promoter}")
    add("=" * 72)
    add("")

    add("-- Vorbemerkung " + "-" * 56)
    add("  Dieser Token existiert noch nicht auf der Blockchain. Es gibt")
    add("  keine Liquiditaet, kein Mint-Konto, keine Halterverteilung -")
    add("  und damit nichts, was sich technisch pruefen liesse. Alles")
    add("  unten sind Aussagen ueber die Ankuendigung, nicht ueber den Token.")
    add("")

    # --- Text ------------------------------------------------------- #
    add("-- Ankuendigungstext " + "-" * 51)
    add(f"  Einstufung: {dossier.text.einstufung}   ({dossier.text.punkte} Punkte)")
    if not dossier.text.treffer:
        add("  Keine bekannten Betrugsmuster gefunden.")
        add("  Das heisst nicht 'serioes' - nur 'nicht offensichtlich'.")
    for gewicht, erklaerung in dossier.text.treffer:
        marke = "  X  " if gewicht >= 100 else ("  !  " if gewicht >= 40 else "  .  ")
        add(_umbruch(erklaerung, marke))
    add("")

    # --- Namenskollisionen ------------------------------------------- #
    add("-- Kuerzel bereits vergeben " + "-" * 44)
    if not dossier.ticker:
        add("  Kein Kuerzel angegeben - nicht pruefbar.")
    elif not dossier.kollision_versucht:
        add("  Nicht abgefragt.")
    elif not dossier.kollision_geprueft:
        add("  Abfrage fehlgeschlagen - Marktdaten nicht erreichbar.")
        add("  Das Ergebnis ist damit unvollstaendig, nicht unauffaellig.")
    elif dossier.kollisionen == 0:
        add(f"  '{dossier.ticker}' existiert bisher nicht. Unauffaellig.")
    else:
        add(f"  '{dossier.ticker}' tragen bereits {dossier.kollisionen} Token,")
        add(f"  davon {dossier.tote_kollisionen} praktisch tot (unter 1.000 USD Liquiditaet).")
        if dossier.kollisionen >= 10 and dossier.tote_kollisionen >= dossier.kollisionen * 0.8:
            add("  ! Dieses Muster - vielfach vergeben, fast alles tot - ist")
            add("    typisch fuer Betrugsfabriken, die denselben Namen wiederverwenden.")
    add("")

    # --- Nachrichten -------------------------------------------------- #
    add("-- Nachrichtenlage " + "-" * 53)
    if not dossier.news_versucht:
        add("  Nicht abgefragt.")
    elif not dossier.news_geprueft:
        add("  Abfrage fehlgeschlagen. Unvollstaendig, nicht unauffaellig.")
    elif dossier.warnungen:
        add("  ACHTUNG - Betrugsmeldungen zu diesem Namen gefunden:")
        for meldung in dossier.warnungen[:5]:
            add(f"    X  {meldung.titel[:64]}")
            add(f"       {meldung.quelle} - {meldung.link[:60]}")
    elif dossier.meldungen:
        add(f"  {len(dossier.meldungen)} Erwaehnungen, keine davon eine Warnung:")
        for meldung in dossier.meldungen[:4]:
            add(f"    .  {meldung.titel[:64]}  ({meldung.quelle})")
    else:
        add("  Keine Berichterstattung gefunden.")
        add("  Bei einem frischen Memecoin ist das der Normalfall und kein")
        add("  schlechtes Zeichen. Aussagekraft haette nur der umgekehrte Fall.")
    add("")

    # --- Promoter ----------------------------------------------------- #
    add("-- Bilanz des Promoters " + "-" * 48)
    if not dossier.promoter_zahlen:
        add(f"  Noch keine erfassten Calls von '{dossier.promoter}'.")
        add("  Ab jetzt wird mitgeschrieben. Nach etwa zwanzig Calls steht")
        add("  hier, ob dir diese Quelle Geld verdient oder kostet.")
    else:
        zahlen = dossier.promoter_zahlen
        add(f"  Erfasste Calls      {zahlen['calls']}")
        add(f"  Davon gestartet     {zahlen['gelauncht']}")
        add(f"  Nie gestartet       {zahlen['verschwunden']}")
        add(f"  Beim Start NO-GO    {zahlen['ausschluss']}")
        if zahlen.get("schnitt_score") is not None:
            add(f"  Schnitt beim Start  {zahlen['schnitt_score']:.0f}/100")
        add("")
        add(_umbruch(dossier.promoter_urteil or "", "  -> "))
    add("")

    # --- Fazit -------------------------------------------------------- #
    add("-- Fazit " + "-" * 63)
    if dossier.text.toedlich:
        add("  Der Ankuendigungstext enthaelt ein Muster, das nicht auf ein")
        add("  Risiko hindeutet, sondern den Betrug selbst beschreibt. Kein")
        add("  weiterer Pruefschritt kann das aufwiegen.")
    elif dossier.warnungen:
        add("  Zu diesem Namen existieren bereits Betrugsmeldungen. Finger weg.")
    elif dossier.text.punkte >= 90:
        add("  Mehrere schwere Warnzeichen. Nichts davon ist beweisbar, aber")
        add("  die Haeufung allein reicht als Grund, es zu lassen.")
    else:
        add("  Keine offensichtlichen Betrugsmuster - was nichts beweist.")
        add("  Ein Token vor dem Start ist grundsaetzlich nicht bewertbar.")
        add("")
        add("  Sinnvolles Vorgehen: Call erfassen, NICHT vorab kaufen, und")
        add("  nach dem Start pruefen lassen. Dann gibt es echte Daten -")
        add("  und die frueheren Calls dieses Promoters bekommen eine Bilanz.")
    add("=" * 72)
    return "\n".join(zeilen)


def _umbruch(text: str, marke: str, breite: int = 72) -> str:
    import textwrap

    einzug = " " * len(marke)
    teile = textwrap.wrap(text, width=breite - len(marke)) or [""]
    return "\n".join([marke + teile[0]] + [einzug + t for t in teile[1:]])
