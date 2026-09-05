"""Kommandozeile fuer memecoin-radar."""

from __future__ import annotations

import argparse
import sys
import time

from .config import Settings
from .journal import Journal, format_timestamp
from .model import TokenSnapshot
from .monitor import Monitor, MonitorConfig, Watchlist
from .notify import build_notifiers
from .report import render_plan, render_verdict
from .risk import expectancy, plan_position, required_win_rate, risk_of_ruin
from .scoring import Stage, evaluate
from .sources import DexScreener, HttpClient, RugCheck, SourceError

DISCLAIMER = (
    "Hinweis: Analysewerkzeug, keine Anlageberatung. Alle Daten stammen aus\n"
    "oeffentlichen APIs und koennen unvollstaendig oder veraltet sein."
)


def _clients(settings: Settings) -> tuple[DexScreener, RugCheck]:
    http = HttpClient(settings.request_timeout, settings.min_request_interval)
    return DexScreener(http), RugCheck(http, settings.rugcheck_api_key)


def _snapshot_for(dex: DexScreener, mint: str, chain: str) -> TokenSnapshot | None:
    pairs = dex.pairs_for_token(mint, chain)
    if not pairs:
        return None
    return TokenSnapshot.from_pair(pairs[0])


# --------------------------------------------------------------------- #
def cmd_check(args: argparse.Namespace, settings: Settings) -> int:
    """Einzelnen Token pruefen - der Befehl fuer 'jemand hat mir das geschickt'."""
    dex, rug = _clients(settings)
    try:
        snap = _snapshot_for(dex, args.mint, settings.chain)
    except SourceError as exc:
        print(f"Fehler beim Abruf: {exc}", file=sys.stderr)
        return 2

    if snap is None:
        print("Kein Handelspaar gefunden. Entweder existiert der Token nicht,")
        print("oder es gibt (noch) keinen Pool - dann kannst du auch nicht verkaufen.")
        return 1

    report = None if args.no_contract else rug.report(snap.mint)
    verdict = evaluate(snap, settings.thresholds, report)
    print(render_verdict(verdict))

    if args.bankroll:
        print()
        plan = plan_position(
            bankroll=args.bankroll,
            liquidity_usd=snap.liquidity_usd,
            entry_price=snap.price_usd,
            risk_pct=min(args.risk, settings.thresholds.max_risk_per_trade_pct),
            stop_pct=args.stop,
            max_impact_pct=settings.thresholds.max_price_impact_pct,
        )
        print(render_plan(plan))

    print()
    print(DISCLAIMER)
    return 0 if verdict.tradeable else 1


def cmd_scan(args: argparse.Namespace, settings: Settings) -> int:
    """Frische und beworbene Token durchsuchen und filtern."""
    dex, rug = _clients(settings)
    candidates: dict[str, str] = {}

    try:
        if args.source in ("profiles", "all"):
            for entry in dex.token_profiles():
                if isinstance(entry, dict) and entry.get("chainId") == settings.chain:
                    address = entry.get("tokenAddress")
                    if address:
                        candidates[str(address)] = "profil"
        if args.source in ("boosted", "all"):
            for entry in dex.boosted(top=True):
                if isinstance(entry, dict) and entry.get("chainId") == settings.chain:
                    address = entry.get("tokenAddress")
                    if address:
                        candidates.setdefault(str(address), "boost")
    except SourceError as exc:
        print(f"Fehler beim Abruf: {exc}", file=sys.stderr)
        return 2

    if not candidates:
        print("Keine Kandidaten gefunden.")
        return 1

    print(f"{len(candidates)} Kandidaten gefunden, pruefe die ersten {args.limit} ...")
    print()

    results = []
    for index, (mint, source) in enumerate(list(candidates.items())[: args.limit], 1):
        try:
            snap = _snapshot_for(dex, mint, settings.chain)
        except SourceError:
            continue
        if snap is None:
            continue
        verdict = evaluate(snap, settings.thresholds, None)
        results.append((verdict, source))
        print(f"\r  geprueft: {index}/{min(args.limit, len(candidates))}", end="", flush=True)

    print("\r" + " " * 40 + "\r", end="")
    results.sort(key=lambda item: item[0].score, reverse=True)

    header = f"{'Symbol':<12} {'Score':>5} {'Phase':<10} {'Liq':>9} {'MC/Liq':>7} {'1h%':>8} {'Kauf%':>6}  Status"
    print(header)
    print("-" * len(header))

    survivors = 0
    for verdict, source in results:
        snap = verdict.snapshot
        if args.only_passing and verdict.hard_fails:
            continue
        survivors += 1
        ratio = snap.mcap_to_liquidity
        ratio_text = "inf" if ratio == float("inf") else f"{ratio:.0f}x"
        status = "AUSGESCHLOSSEN" if verdict.hard_fails else verdict.tier
        print(
            f"{snap.symbol[:12]:<12} {verdict.score:>5} {verdict.stage.value:<10} "
            f"{snap.liquidity_usd / 1000:>8.0f}k {ratio_text:>7} "
            f"{snap.price_change.get('h1', 0.0):>+7.1f}% {snap.buy_ratio_h1 * 100:>5.0f}%  {status}"
        )

    print()
    excluded = len(results) - sum(1 for v, _ in results if not v.hard_fails)
    print(f"{excluded} von {len(results)} Kandidaten scheitern an harten Ausschlusskriterien.")
    print("Das ist der Normalfall, nicht ein Fehler des Filters.")
    print()
    print("Vor jedem Einstieg zwingend einzeln pruefen:  radar check <mint>")
    print(DISCLAIMER)
    return 0


def cmd_size(args: argparse.Namespace, settings: Settings) -> int:
    """Positionsgroesse berechnen, optional mit Live-Liquiditaet."""
    liquidity = args.liquidity
    entry = args.price

    if args.mint:
        dex, _ = _clients(settings)
        try:
            snap = _snapshot_for(dex, args.mint, settings.chain)
        except SourceError as exc:
            print(f"Fehler beim Abruf: {exc}", file=sys.stderr)
            return 2
        if snap is None:
            print("Kein Handelspaar gefunden.")
            return 1
        liquidity = snap.liquidity_usd
        entry = entry or snap.price_usd
        print(f"Live-Daten fuer {snap.short()}: Liquiditaet {liquidity:,.0f} USD")
        print()

    if liquidity <= 0:
        print("Bitte --liquidity oder --mint angeben.", file=sys.stderr)
        return 2

    risk = args.risk
    if risk > settings.thresholds.max_risk_per_trade_pct:
        print(f"Hinweis: {risk}% pro Trade liegt ueber der konfigurierten Obergrenze von "
              f"{settings.thresholds.max_risk_per_trade_pct}%. Wird uebernommen, "
              "ist aber der haeufigste Grund fuer Totalverluste.")
        print()

    plan = plan_position(
        bankroll=args.bankroll,
        liquidity_usd=liquidity,
        entry_price=entry or 0.0,
        risk_pct=risk,
        stop_pct=args.stop,
        max_impact_pct=args.max_impact,
    )
    print(render_plan(plan))
    return 0


def cmd_math(args: argparse.Namespace, settings: Settings) -> int:
    """Zeigt, welche Trefferquote eine Strategie ueberhaupt tragen kann."""
    print("-- Erwartungswert " + "-" * 54)
    print(f"  Annahme: Trefferquote {args.win_rate * 100:.0f}%, "
          f"Durchschnittsgewinn {args.avg_win}R, Verlust 1R")
    exp = expectancy(args.win_rate, args.avg_win)
    print(f"  Erwartungswert pro Trade:  {exp:+.3f}R")
    if abs(exp) < 1e-9:
        print("  -> Exakt null. Break-even vor Kosten - nach Gebuehren und")
        print("     Preiseinfluss ist das ein Minusgeschaeft.")
    elif exp < 0:
        print("  -> Negativ. Jeder weitere Trade kostet im Mittel Geld.")
    else:
        print(f"  -> Positiv. Auf 100 Trades im Mittel {exp * 100:+.1f}R"
              f" (vor Gebuehren und Preiseinfluss).")
    print()

    print("-- Notwendige Trefferquote " + "-" * 45)
    for multiple in (1.0, 1.5, 2.0, 3.0, 5.0, 10.0):
        needed = required_win_rate(multiple)
        print(f"  Bei {multiple:>4.1f}R Durchschnittsgewinn:  {needed * 100:>5.1f}% Treffer noetig")
    print()

    print("-- Ruinrisiko " + "-" * 58)
    print(f"  Monte-Carlo, {args.trades} Trades, Ruin = Kapital halbiert")
    for risk_pct in (1.0, 2.0, 5.0, 10.0, 25.0):
        ruin = risk_of_ruin(args.win_rate, risk_pct, args.avg_win, args.trades)
        bar = "#" * int(ruin * 40)
        print(f"  {risk_pct:>5.1f}% pro Trade:  {ruin * 100:>5.1f}%  {bar}")
    print()
    print("  Gleiche Strategie, gleicher Vorteil - nur die Positionsgroesse")
    print("  entscheidet ueber Ruin oder Ueberleben.")
    return 0


def cmd_demo(args: argparse.Namespace, settings: Settings) -> int:
    """Zeigt die Ausgabe an drei Beispielfaellen - ohne Netzwerkzugriff."""
    import time as _time

    now_ms = int(_time.time() * 1000)

    def pair(**over):
        base = {
            "chainId": "solana", "dexId": "raydium", "pairAddress": "DEMO",
            "baseToken": {"address": "DemoMint1111111111111111111111111111111111",
                          "symbol": "DEMO", "name": "Demo Token"},
            "priceUsd": "0.00042", "liquidity": {"usd": 120_000.0},
            "fdv": 900_000.0, "marketCap": 900_000.0,
            "pairCreatedAt": now_ms - 90 * 60_000,
            "volume": {"m5": 8_000.0, "h1": 240_000.0, "h6": 900_000.0, "h24": 1_500_000.0},
            "priceChange": {"m5": 1.5, "h1": 12.0, "h6": 40.0, "h24": 80.0},
            "txns": {"m5": {"buys": 20, "sells": 18}, "h1": {"buys": 320, "sells": 280},
                     "h6": {"buys": 1500, "sells": 1400}, "h24": {"buys": 4000, "sells": 3800}},
            "info": {"socials": [{"type": "twitter"}], "websites": [{"url": "https://demo.test"}]},
        }
        base.update(over)
        return base

    clean_report = {
        "token": {"mintAuthority": None, "freezeAuthority": None},
        "markets": [{"lp": {"lpLockedPct": 100.0}}],
        "topHolders": [{"pct": 4.2, "owner": "Holder1"}],
        "risks": [],
    }

    faelle = [
        ("FALL 1 - sauberes Paar, keine Ausschlusskriterien",
         pair(), clean_report),
        ("FALL 2 - genau die Kerze, bei der Signalgruppen posten",
         pair(baseToken={"address": "PumpMint", "symbol": "PUMP", "name": "Pump Token"},
              priceChange={"m5": 62.0, "h1": 480.0, "h6": 1200.0, "h24": 1200.0},
              txns={"h1": {"buys": 900, "sells": 120}},
              volume={"h1": 600_000.0}, marketCap=4_000_000.0, fdv=4_000_000.0),
         clean_report),
        ("FALL 3 - Rug in Vorbereitung",
         pair(baseToken={"address": "RugMint", "symbol": "SAFE", "name": "Safe Moon Inu"},
              liquidity={"usd": 9_000.0}, marketCap=2_500_000.0, fdv=2_500_000.0,
              info={}),
         {"token": {"mintAuthority": "Auth1111", "freezeAuthority": "Frz11111"},
          "markets": [{"lp": {"lpLockedPct": 0.0}}],
          "topHolders": [{"pct": 46.0, "owner": "Deployer1"}],
          "risks": [{"name": "Top-Halter", "description": "Ein Wallet haelt fast die Haelfte",
                     "level": "danger"}]}),
    ]

    for titel, roh, report in faelle:
        print()
        print("#" * 72)
        print("# " + titel)
        print("#" * 72)
        verdict = evaluate(TokenSnapshot.from_pair(roh), settings.thresholds, report)
        print(render_verdict(verdict))

    print()
    print("#" * 72)
    print("# Positionsplanung: 5.000 USD Kapital auf einen 40k-Pool")
    print("#" * 72)
    print(render_plan(plan_position(bankroll=5_000, liquidity_usd=40_000,
                                    entry_price=0.00042, risk_pct=1.5, stop_pct=35.0)))
    print()
    print(DISCLAIMER)
    return 0


def cmd_monitor(args: argparse.Namespace, settings: Settings) -> int:
    """Dauerbetrieb: neue Token erfassen, reifen lassen, bei Eignung melden."""
    dex, _ = _clients(settings)

    try:
        notifier = build_notifiers(
            console=not args.no_console,
            file_path=args.log_file,
            telegram=args.telegram,
        )
    except ValueError as exc:
        print(f"Benachrichtigung nicht einrichtbar: {exc}", file=sys.stderr)
        return 2

    config = MonitorConfig(
        min_score=args.min_score,
        discovery_interval=args.discovery_interval,
        requests_per_minute=args.rpm,
        max_watchlist=args.max_watchlist,
        tick_seconds=args.tick,
    )

    print("Monitor gestartet.")
    print(f"  Meldeschwelle       Score >= {config.min_score}, keine Ausschlusskriterien")
    print(f"  Suchlauf            alle {config.discovery_interval}s")
    print(f"  Anfragebudget       {config.requests_per_minute}/Min.")
    print(f"  Kanaele             {', '.join(n.name for n in notifier.notifiers) or 'keine'}")
    print(f"  Beobachtungsliste   {args.watchlist}")
    print()
    print("Hinweis: Frisch gestartete Token werden bewusst NICHT sofort gemeldet.")
    print("Unter 10 Minuten Alter sind die Kennzahlen Rauschen. Sie stehen auf")
    print("der Liste und werden gemeldet, sobald sie bewertbar sind - falls sie")
    print("die Filter dann noch bestehen. Die meisten tun das nie.")
    print()
    print("Abbruch mit Strg+C.")
    print()

    with Watchlist(args.watchlist) as watchlist:
        monitor = Monitor(settings, dex, watchlist, notifier, config)
        return monitor.run(max_ticks=1 if args.once else None)


def cmd_paper(args: argparse.Namespace, settings: Settings) -> int:
    with Journal(settings.journal_path) as journal:
        if args.paper_command == "open":
            trade_id = journal.open_trade(
                mint=args.mint, symbol=args.symbol, entry_price=args.price,
                position_usd=args.size, stop_pct=args.stop,
                score=args.score, stage=args.stage, source=args.source, note=args.note,
            )
            print(f"Trade #{trade_id} eroeffnet: {args.symbol} @ {args.price}")
            print(f"Stop bei -{args.stop}% = {args.price * (1 - args.stop / 100):.10f}".rstrip("0"))
            return 0

        if args.paper_command == "close":
            row = journal.close_trade(args.id, args.price, args.note)
            r_value = Journal.trade_r(row)
            change = (row["exit_price"] - row["entry_price"]) / row["entry_price"] * 100
            pnl = row["position_usd"] * change / 100
            print(f"Trade #{row['id']} ({row['symbol']}) geschlossen.")
            print(f"  Kursaenderung  {change:+.1f}%")
            print(f"  Ergebnis       {r_value:+.2f}R  =  {pnl:+,.2f} USD")
            return 0

        if args.paper_command == "list":
            rows = journal.open_positions() if args.open_only else journal.all_trades()
            if not rows:
                print("Keine Trades im Journal.")
                return 0
            print(f"{'ID':>4} {'Symbol':<12} {'Eroeffnet':<17} {'Einstieg':>14} "
                  f"{'Groesse':>10} {'R':>7}  Status")
            print("-" * 78)
            for row in rows:
                r_value = Journal.trade_r(row)
                r_text = f"{r_value:+.2f}" if r_value is not None else "-"
                status = "offen" if row["closed_at"] is None else "geschlossen"
                print(f"{row['id']:>4} {row['symbol'][:12]:<12} "
                      f"{format_timestamp(row['opened_at']):<17} "
                      f"{row['entry_price']:>14.10f} {row['position_usd']:>10,.0f} "
                      f"{r_text:>7}  {status}")
            return 0

        # stats
        stats = journal.stats()
        if stats.closed == 0:
            print(f"{stats.total} Trades erfasst, davon {stats.open_positions} offen.")
            print("Noch keine abgeschlossenen Trades - keine Statistik moeglich.")
            return 0

        print("-- Journal-Statistik " + "-" * 51)
        print(f"  Trades gesamt        {stats.total}  (offen: {stats.open_positions})")
        print(f"  Abgeschlossen        {stats.closed}")
        print(f"  Treffer / Verluste   {stats.wins} / {stats.losses}")
        print(f"  Trefferquote         {stats.win_rate * 100:.1f}%")
        print()
        print(f"  Erwartungswert       {stats.expectancy_r:+.3f}R pro Trade")
        print(f"  Summe                {stats.total_r:+.2f}R  =  {stats.net_usd:+,.2f} USD")
        print(f"  Durchschn. Gewinn    {stats.avg_win_r:+.2f}R")
        print(f"  Durchschn. Verlust   {stats.avg_loss_r:+.2f}R")
        print(f"  Bester / schlechtes. {stats.best_r:+.2f}R / {stats.worst_r:+.2f}R")
        print(f"  Max. Rueckschlag     {stats.max_drawdown_r:.2f}R")
        print()

        if stats.avg_win_r > 0:
            needed = required_win_rate(stats.avg_win_r)
            print(f"  Bei deinem Gewinn/Verlust-Verhaeltnis brauchst du {needed * 100:.1f}% "
                  f"Treffer.")
            print(f"  Du hast {stats.win_rate * 100:.1f}%.  ->  "
                  f"{'Traegt sich.' if stats.win_rate > needed else 'Traegt sich nicht.'}")
            print()

        if stats.by_stage:
            print("-- Ergebnis nach Einstiegsphase " + "-" * 40)
            for stage, (count, avg) in sorted(
                stats.by_stage.items(), key=lambda item: item[1][1], reverse=True
            ):
                print(f"  {stage:<12} {count:>3} Trades   {avg:+.2f}R im Schnitt")
            print()
        if stats.by_source:
            print("-- Ergebnis nach Quelle " + "-" * 48)
            for source, (count, avg) in sorted(
                stats.by_source.items(), key=lambda item: item[1][1], reverse=True
            ):
                print(f"  {source:<20} {count:>3} Trades   {avg:+.2f}R im Schnitt")
            print()
            print("  Diese Tabelle beantwortet die eigentliche Frage: welche Signalquelle")
            print("  verdient dir Geld und welche kostet dich welches. Meist ist es die,")
            print("  von der du es am wenigsten erwartet haettest.")
        return 0


def cmd_watch(args: argparse.Namespace, settings: Settings) -> int:
    """Token beobachten und bei Phasenwechsel warnen."""
    dex, _ = _clients(settings)
    last_stage: Stage | None = None
    print(f"Beobachte {args.mint} alle {args.interval}s. Abbruch mit Strg+C.")
    print()
    try:
        while True:
            try:
                snap = _snapshot_for(dex, args.mint, settings.chain)
            except SourceError as exc:
                print(f"  Abruf fehlgeschlagen: {exc}")
                time.sleep(args.interval)
                continue
            if snap is None:
                print("  Kein Paar gefunden.")
                time.sleep(args.interval)
                continue

            verdict = evaluate(snap, settings.thresholds, None)
            stamp = time.strftime("%H:%M:%S")
            marker = ""
            if last_stage is not None and verdict.stage is not last_stage:
                marker = f"   <<< PHASENWECHSEL: {last_stage.value} -> {verdict.stage.value}"
            last_stage = verdict.stage

            print(
                f"[{stamp}] {snap.symbol:<10} {snap.price_usd:.10f}  "
                f"1h {snap.price_change.get('h1', 0.0):+6.1f}%  "
                f"Liq {snap.liquidity_usd / 1000:>6.0f}k  "
                f"Kauf {snap.buy_ratio_h1 * 100:>3.0f}%  "
                f"Score {verdict.score:>3}  {verdict.stage.value}{marker}"
            )
            if marker and verdict.stage is Stage.BLOWOFF:
                print("           " + Stage.BLOWOFF.erklaerung)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nBeobachtung beendet.")
    return 0


# --------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radar",
        description="Memecoin-Analyse: On-Chain-Daten, Rug-Filter, Risikomanagement.",
        epilog="Analysewerkzeug, keine Anlageberatung.",
    )
    parser.add_argument("--config", help="Pfad zu einer JSON-Konfiguration")
    parser.add_argument("--chain", default=None, help="Chain-ID (Standard: solana)")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Einzelnen Token pruefen (Mint-Adresse)")
    check.add_argument("mint")
    check.add_argument("--bankroll", type=float, default=0.0,
                       help="Gesamtkapital - ergaenzt die Positionsplanung")
    check.add_argument("--risk", type=float, default=1.5, help="Risiko pro Trade in Prozent")
    check.add_argument("--stop", type=float, default=35.0, help="Stop in Prozent")
    check.add_argument("--no-contract", action="store_true",
                       help="Vertragspruefung ueberspringen (schneller)")
    check.set_defaults(func=cmd_check)

    scan = sub.add_parser("scan", help="Neue und beworbene Token durchsuchen")
    scan.add_argument("--source", choices=["profiles", "boosted", "all"], default="all")
    scan.add_argument("--limit", type=int, default=25, help="Anzahl zu pruefender Token")
    scan.add_argument("--only-passing", action="store_true",
                      help="Nur Token ohne harte Ausschlusskriterien anzeigen")
    scan.set_defaults(func=cmd_scan)

    size = sub.add_parser("size", help="Positionsgroesse und Preiseinfluss berechnen")
    size.add_argument("--bankroll", type=float, required=True)
    size.add_argument("--liquidity", type=float, default=0.0)
    size.add_argument("--mint", help="Liquiditaet live vom Markt holen")
    size.add_argument("--price", type=float, default=0.0)
    size.add_argument("--risk", type=float, default=1.5)
    size.add_argument("--stop", type=float, default=35.0)
    size.add_argument("--max-impact", type=float, default=2.0)
    size.set_defaults(func=cmd_size)

    math_cmd = sub.add_parser("math", help="Erwartungswert und Ruinrisiko durchrechnen")
    math_cmd.add_argument("--win-rate", type=float, default=0.25)
    math_cmd.add_argument("--avg-win", type=float, default=3.0, help="Durchschnittsgewinn in R")
    math_cmd.add_argument("--trades", type=int, default=200)
    math_cmd.set_defaults(func=cmd_math)

    paper = sub.add_parser("paper", help="Handelsjournal fuehren und auswerten")
    paper_sub = paper.add_subparsers(dest="paper_command", required=True)

    p_open = paper_sub.add_parser("open", help="Position eroeffnen")
    p_open.add_argument("--mint", required=True)
    p_open.add_argument("--symbol", required=True)
    p_open.add_argument("--price", type=float, required=True)
    p_open.add_argument("--size", type=float, required=True, help="Positionsgroesse in USD")
    p_open.add_argument("--stop", type=float, default=35.0)
    p_open.add_argument("--score", type=int)
    p_open.add_argument("--stage")
    p_open.add_argument("--source", help="Woher kam das Signal? Entscheidend fuer die Auswertung")
    p_open.add_argument("--note")

    p_close = paper_sub.add_parser("close", help="Position schliessen")
    p_close.add_argument("--id", type=int, required=True)
    p_close.add_argument("--price", type=float, required=True)
    p_close.add_argument("--note")

    p_list = paper_sub.add_parser("list", help="Trades auflisten")
    p_list.add_argument("--open-only", action="store_true")

    paper_sub.add_parser("stats", help="Auswertung anzeigen")
    paper.set_defaults(func=cmd_paper)

    monitor = sub.add_parser("monitor", help="Dauerbetrieb: neue Token beobachten und melden")
    monitor.add_argument("--min-score", type=int, default=55,
                         help="Meldeschwelle (Standard: 55)")
    monitor.add_argument("--discovery-interval", type=int, default=300,
                         help="Sekunden zwischen Suchlaeufen nach neuen Token")
    monitor.add_argument("--rpm", type=int, default=50,
                         help="Anfragebudget pro Minute (API-Limit liegt bei ca. 60)")
    monitor.add_argument("--max-watchlist", type=int, default=400)
    monitor.add_argument("--tick", type=int, default=15, help="Sekunden pro Durchlauf")
    monitor.add_argument("--watchlist", default="radar-watchlist.sqlite3")
    monitor.add_argument("--log-file", help="Alarme zusaetzlich als JSON-Zeilen speichern")
    monitor.add_argument("--telegram", action="store_true",
                         help="Alarme an den eigenen Telegram-Bot senden "
                              "(TELEGRAM_BOT_TOKEN und TELEGRAM_CHAT_ID setzen)")
    monitor.add_argument("--no-console", action="store_true")
    monitor.add_argument("--once", action="store_true",
                         help="Nur einen Durchlauf (fuer cron oder Aufgabenplanung)")
    monitor.set_defaults(func=cmd_monitor)

    demo = sub.add_parser("demo", help="Beispielausgabe ohne Netzwerkzugriff")
    demo.set_defaults(func=cmd_demo)

    watch = sub.add_parser("watch", help="Token beobachten, Phasenwechsel melden")
    watch.add_argument("mint")
    watch.add_argument("--interval", type=int, default=60, help="Sekunden zwischen Abrufen")
    watch.set_defaults(func=cmd_watch)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.load(args.config)
    if args.chain:
        settings.chain = args.chain
    try:
        return int(args.func(args, settings))
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        return 130
    except (ValueError, KeyError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
