"""Periodischer Lagebericht: was ist gerade heiss - und was davon haelt stand.

"Hype" ist nicht messbar, indem man liest, worueber geschrieben wird - das
meiste davon ist bezahlte Platzierung. Messbar ist er auf zwei Wegen, die
beide auf der Kette stehen:

  1. Bezahlte Bewerbung. Wer einen Boost kauft, bezahlt dafuer, dass du
     den Token siehst. Das ist gekaufte Aufmerksamkeit - kein
     Qualitaetssignal, aber ein zuverlaessiger Hinweis darauf, wohin in
     den naechsten Stunden Retail-Fluss stroemt.
  2. Umschlag. Volumen im Verhaeltnis zur Liquiditaet zeigt, wo tatsaechlich
     Kapital bewegt wird statt nur geredet.

Der Bericht trennt beides von der Frage, ob man den Token anfassen sollte.
Diese beiden Fragen fallen fast nie zusammen - das ist der ganze Punkt.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .config import Settings
from .model import TokenSnapshot
from .scoring import Stage, Verdict, evaluate
from .sources import DexScreener, SourceError


@dataclass
class Eintrag:
    verdict: Verdict
    quelle: str
    boost: int = 0

    @property
    def snap(self) -> TokenSnapshot:
        return self.verdict.snapshot


@dataclass
class Lagebericht:
    zeitpunkt: float = field(default_factory=time.time)
    geprueft: int = 0
    eintraege: list[Eintrag] = field(default_factory=list)
    fehler: list[str] = field(default_factory=list)

    @property
    def bestanden(self) -> list[Eintrag]:
        return [e for e in self.eintraege
                if not e.verdict.hard_fails and e.verdict.stage not in
                (Stage.BLOWOFF, Stage.NACH_DUMP, Stage.TOT)]

    @property
    def hype_phase(self) -> list[Eintrag]:
        return [e for e in self.eintraege if e.verdict.stage is Stage.BLOWOFF]

    @property
    def ausgeschlossen(self) -> list[Eintrag]:
        return [e for e in self.eintraege if e.verdict.hard_fails]

    @property
    def meist_beworben(self) -> list[Eintrag]:
        return sorted([e for e in self.eintraege if e.boost > 0],
                      key=lambda e: e.boost, reverse=True)


def sammle(dex: DexScreener, settings: Settings, limit: int = 30) -> Lagebericht:
    """Holt beworbene und frisch eingetragene Token und bewertet sie."""
    bericht = Lagebericht()
    kandidaten: dict[str, tuple[str, int]] = {}

    try:
        for eintrag in dex.boosted(top=True) or []:
            if not isinstance(eintrag, dict) or eintrag.get("chainId") != settings.chain:
                continue
            adresse = eintrag.get("tokenAddress")
            if not adresse:
                continue
            try:
                betrag = int(float(eintrag.get("totalAmount") or eintrag.get("amount") or 0))
            except (TypeError, ValueError):
                betrag = 0
            kandidaten[str(adresse)] = ("beworben", betrag)
    except SourceError as exc:
        bericht.fehler.append(f"Beworbene Token nicht abrufbar: {exc}")

    try:
        for eintrag in dex.token_profiles() or []:
            if not isinstance(eintrag, dict) or eintrag.get("chainId") != settings.chain:
                continue
            adresse = eintrag.get("tokenAddress")
            if adresse:
                kandidaten.setdefault(str(adresse), ("neu eingetragen", 0))
    except SourceError as exc:
        bericht.fehler.append(f"Neue Eintraege nicht abrufbar: {exc}")

    for mint, (quelle, boost) in list(kandidaten.items())[:limit]:
        try:
            paare = dex.pairs_for_token(mint, settings.chain)
        except SourceError:
            continue
        if not paare:
            continue
        snap = TokenSnapshot.from_pair(paare[0])
        bericht.geprueft += 1
        bericht.eintraege.append(
            Eintrag(evaluate(snap, settings.thresholds, None), quelle, boost)
        )

    bericht.eintraege.sort(key=lambda e: e.verdict.score, reverse=True)
    return bericht


# --------------------------------------------------------------------- #
def _geld(wert: float) -> str:
    if wert >= 1_000_000:
        return f"{wert / 1_000_000:.1f}M"
    if wert >= 1_000:
        return f"{wert / 1_000:.0f}k"
    return f"{wert:.0f}"


def _zeile(eintrag: Eintrag) -> str:
    snap = eintrag.snap
    return (f"  {snap.symbol[:10]:<10} {eintrag.verdict.score:>3}/100  "
            f"{eintrag.verdict.stage.value:<9} "
            f"Liq {_geld(snap.liquidity_usd):>6}  "
            f"1h {snap.price_change.get('h1', 0.0):>+7.1f}%  "
            f"Kauf {snap.buy_ratio_h1 * 100:>3.0f}%")


def rendere(bericht: Lagebericht, kurz: bool = False) -> str:
    zeilen: list[str] = []
    add = zeilen.append
    stempel = time.strftime("%d.%m.%Y %H:%M", time.localtime(bericht.zeitpunkt))

    add("=" * 72)
    add(f" LAGEBERICHT  {stempel}")
    add("=" * 72)

    if bericht.fehler:
        for fehler in bericht.fehler:
            add(f"  ! {fehler}")
        add("")

    if not bericht.eintraege:
        add("  Keine Daten erhalten. Der Bericht ist leer, nicht unauffaellig.")
        add("=" * 72)
        return "\n".join(zeilen)

    add(f" {bericht.geprueft} Token geprueft   |   "
        f"{len(bericht.bestanden)} bestanden   "
        f"{len(bericht.hype_phase)} in Hype-Phase   "
        f"{len(bericht.ausgeschlossen)} ausgeschlossen")
    add("")

    # --- Wo Geld fuer Aufmerksamkeit ausgegeben wird ------------------ #
    beworben = bericht.meist_beworben
    if beworben:
        add("-- Am staerksten beworben " + "-" * 46)
        add("   Gekaufte Aufmerksamkeit. Sagt nichts ueber Qualitaet - aber")
        add("   zeigt, wohin in den naechsten Stunden Retail-Fluss stroemt.")
        add("")
        for eintrag in beworben[:8]:
            marke = "X" if eintrag.verdict.hard_fails else (
                "!" if eintrag.verdict.stage is Stage.BLOWOFF else " ")
            add(f" {marke}{_zeile(eintrag)}   ({eintrag.boost} Boosts)")
        add("")

    # --- Was die Pruefung besteht ------------------------------------ #
    add("-- Besteht die Pruefung " + "-" * 48)
    if not bericht.bestanden:
        add("   Nichts. Das ist der Normalfall und kein Fehler des Filters.")
    else:
        for eintrag in bericht.bestanden[:10]:
            add(_zeile(eintrag))
        add("")
        add("   Kein Kaufsignal. Nur: kein Ausschlusskriterium erfuellt.")
        add("   Vor jedem Einstieg einzeln pruefen:")
        for eintrag in bericht.bestanden[:3]:
            add(f"     python run.py check {eintrag.snap.mint}")
    add("")

    if kurz:
        add("=" * 72)
        return "\n".join(zeilen)

    # --- Hype-Phase --------------------------------------------------- #
    if bericht.hype_phase:
        add("-- Laeuft gerade senkrecht " + "-" * 45)
        add("   Genau diese Token stehen jetzt in den Signalgruppen. Wer hier")
        add("   kauft, liefert den Ausstieg fuer die, die vorher drin waren.")
        add("")
        for eintrag in bericht.hype_phase[:8]:
            add(_zeile(eintrag))
        add("")

    # --- Ausgeschlossen ------------------------------------------------ #
    if bericht.ausgeschlossen:
        add("-- Ausgeschlossen " + "-" * 54)
        for eintrag in bericht.ausgeschlossen[:6]:
            grund = eintrag.verdict.hard_fails[0]
            add(f"  {eintrag.snap.symbol[:10]:<10} {grund[:56]}")
        weitere = len(bericht.ausgeschlossen) - 6
        if weitere > 0:
            add(f"  ... und {weitere} weitere")
        add("")

    add("=" * 72)
    add(" Analysewerkzeug, keine Anlageberatung. Dass ein Token hier steht,")
    add(" heisst nur: er ist gerade auffaellig. Nicht: er ist gut.")
    add("=" * 72)
    return "\n".join(zeilen)


def rendere_telegram(bericht: Lagebericht) -> str:
    """Kurzfassung fuer die Benachrichtigung - 4000 Zeichen Obergrenze."""
    stempel = time.strftime("%d.%m. %H:%M", time.localtime(bericht.zeitpunkt))
    teile = [f"LAGEBERICHT {stempel}",
             f"{bericht.geprueft} geprueft, {len(bericht.bestanden)} bestanden, "
             f"{len(bericht.hype_phase)} in Hype-Phase", ""]

    if bericht.bestanden:
        teile.append("BESTEHT DIE PRUEFUNG:")
        for eintrag in bericht.bestanden[:5]:
            snap = eintrag.snap
            teile.append(f"  {snap.symbol} {eintrag.verdict.score}/100 "
                         f"{eintrag.verdict.stage.value} Liq {_geld(snap.liquidity_usd)}")
            teile.append(f"  {snap.mint}")
    else:
        teile.append("Nichts besteht die Pruefung. Normalfall.")

    if bericht.hype_phase:
        teile.append("")
        teile.append("LAEUFT SENKRECHT (nicht einsteigen):")
        for eintrag in bericht.hype_phase[:4]:
            teile.append(f"  {eintrag.snap.symbol} "
                         f"{eintrag.snap.price_change.get('h1', 0.0):+.0f}% 1h")

    teile.append("")
    teile.append("Kein Kaufsignal. Vor Einstieg: run.py check <mint>")
    return "\n".join(teile)[:4000]
