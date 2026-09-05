"""Handelsjournal auf SQLite-Basis.

Der unspektakulaerste Teil des Tools und der einzige, der nachweislich
Trefferquoten verbessert. Ohne Journal erinnerst du dich an die 8x-Gewinne
und vergisst die 30 Totalverluste - und haeltst ein Minusgeschaeft fuer eine
Strategie.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    mint         TEXT    NOT NULL,
    symbol       TEXT    NOT NULL,
    opened_at    INTEGER NOT NULL,
    closed_at    INTEGER,
    entry_price  REAL    NOT NULL,
    exit_price   REAL,
    position_usd REAL    NOT NULL,
    stop_pct     REAL    NOT NULL,
    score        INTEGER,
    stage        TEXT,
    source       TEXT,
    note         TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_open ON trades(closed_at);
CREATE INDEX IF NOT EXISTS idx_trades_mint ON trades(mint);
"""


@dataclass
class Stats:
    total: int = 0
    closed: int = 0
    open_positions: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_r: float = 0.0
    expectancy_r: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    best_r: float = 0.0
    worst_r: float = 0.0
    net_usd: float = 0.0
    max_drawdown_r: float = 0.0
    by_stage: dict[str, tuple[int, float]] | None = None
    by_source: dict[str, tuple[int, float]] | None = None


class Journal:
    def __init__(self, path: str = "radar-journal.sqlite3") -> None:
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Journal":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    def open_trade(
        self,
        mint: str,
        symbol: str,
        entry_price: float,
        position_usd: float,
        stop_pct: float,
        score: int | None = None,
        stage: str | None = None,
        source: str | None = None,
        note: str | None = None,
    ) -> int:
        if entry_price <= 0 or position_usd <= 0:
            raise ValueError("Einstiegspreis und Positionsgroesse muessen positiv sein")
        cursor = self.conn.execute(
            "INSERT INTO trades (mint, symbol, opened_at, entry_price, position_usd,"
            " stop_pct, score, stage, source, note) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (mint, symbol, int(time.time()), entry_price, position_usd,
             stop_pct, score, stage, source, note),
        )
        self.conn.commit()
        return int(cursor.lastrowid or 0)

    def close_trade(self, trade_id: int, exit_price: float, note: str | None = None) -> dict:
        row = self.conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        if row is None:
            raise KeyError(f"Trade {trade_id} existiert nicht")
        if row["closed_at"] is not None:
            raise ValueError(f"Trade {trade_id} ist bereits geschlossen")
        if exit_price < 0:
            raise ValueError("Ausstiegspreis darf nicht negativ sein")

        merged_note = " | ".join(filter(None, [row["note"], note]))
        self.conn.execute(
            "UPDATE trades SET closed_at = ?, exit_price = ?, note = ? WHERE id = ?",
            (int(time.time()), exit_price, merged_note or None, trade_id),
        )
        self.conn.commit()
        return dict(self.conn.execute(
            "SELECT * FROM trades WHERE id = ?", (trade_id,)
        ).fetchone())

    def open_positions(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM trades WHERE closed_at IS NULL ORDER BY opened_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def all_trades(self, limit: int = 200) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM trades ORDER BY opened_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ #
    @staticmethod
    def trade_r(row: dict | sqlite3.Row) -> float | None:
        """Ergebnis in R (Vielfaches des riskierten Kapitals).

        R normalisiert unterschiedlich grosse Positionen auf eine Skala -
        nur so sind Trades ueberhaupt vergleichbar.
        """
        entry = row["entry_price"]
        exit_price = row["exit_price"]
        stop_pct = row["stop_pct"]
        if exit_price is None or not entry or not stop_pct:
            return None
        change_pct = (exit_price - entry) / entry * 100.0
        return change_pct / stop_pct

    def stats(self) -> Stats:
        rows = [dict(r) for r in self.conn.execute("SELECT * FROM trades").fetchall()]
        closed = [r for r in rows if r["closed_at"] is not None]

        result = Stats(total=len(rows), closed=len(closed),
                       open_positions=len(rows) - len(closed))
        if not closed:
            return result

        r_values: list[float] = []
        by_stage: dict[str, list[float]] = {}
        by_source: dict[str, list[float]] = {}

        for row in closed:
            r_value = self.trade_r(row)
            if r_value is None:
                continue
            r_values.append(r_value)
            result.net_usd += row["position_usd"] * (
                (row["exit_price"] - row["entry_price"]) / row["entry_price"]
            )
            by_stage.setdefault(row["stage"] or "unbekannt", []).append(r_value)
            by_source.setdefault(row["source"] or "unbekannt", []).append(r_value)

        if not r_values:
            return result

        wins = [r for r in r_values if r > 0]
        losses = [r for r in r_values if r <= 0]

        result.wins = len(wins)
        result.losses = len(losses)
        result.win_rate = len(wins) / len(r_values)
        result.total_r = sum(r_values)
        result.expectancy_r = result.total_r / len(r_values)
        result.avg_win_r = sum(wins) / len(wins) if wins else 0.0
        result.avg_loss_r = sum(losses) / len(losses) if losses else 0.0
        result.best_r = max(r_values)
        result.worst_r = min(r_values)

        # Maximaler Rueckschlag der kumulierten R-Kurve.
        peak = 0.0
        cumulative = 0.0
        for r_value in r_values:
            cumulative += r_value
            peak = max(peak, cumulative)
            result.max_drawdown_r = min(result.max_drawdown_r, cumulative - peak)

        result.by_stage = {
            key: (len(values), sum(values) / len(values)) for key, values in by_stage.items()
        }
        result.by_source = {
            key: (len(values), sum(values) / len(values)) for key, values in by_source.items()
        }
        return result


def format_timestamp(epoch: int | None) -> str:
    if not epoch:
        return "-"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
