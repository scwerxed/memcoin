"""Keccak-256 in reinem Python.

Wird gebraucht, um Funktionssignaturen in EVM-Vertragscode wiederzufinden:
die ersten vier Bytes von keccak256("mint(address,uint256)") sind der
Selektor, nach dem im Bytecode gesucht wird.

Pythons hashlib kann das nicht - sha3_256 ist der finale SHA-3-Standard mit
anderer Polsterung als das von Ethereum verwendete Original-Keccak. Eine
externe Abhaengigkeit wollte dieses Projekt nicht, also steht es hier.

Geprueft gegen die offiziellen Testvektoren, siehe tests/test_keccak.py.
"""

from __future__ import annotations

_MASKE = (1 << 64) - 1

_RUNDENKONSTANTEN = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)

_ROTATIONEN = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)


def _rot(wert: int, n: int) -> int:
    n %= 64
    return ((wert << n) | (wert >> (64 - n))) & _MASKE


def _keccak_f(zustand: list[list[int]]) -> None:
    for runde in range(24):
        # Theta
        c = [zustand[x][0] ^ zustand[x][1] ^ zustand[x][2]
             ^ zustand[x][3] ^ zustand[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rot(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                zustand[x][y] ^= d[x]

        # Rho und Pi
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rot(zustand[x][y], _ROTATIONEN[x][y])

        # Chi
        for x in range(5):
            for y in range(5):
                zustand[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y])

        # Iota
        zustand[0][0] ^= _RUNDENKONSTANTEN[runde]


def keccak256(daten: bytes) -> bytes:
    """Keccak-256 wie in Ethereum verwendet (Polsterung 0x01, nicht 0x06)."""
    rate = 136  # 1088 Bit
    zustand = [[0] * 5 for _ in range(5)]

    # Polstern
    gepolstert = bytearray(daten)
    gepolstert.append(0x01)
    while len(gepolstert) % rate != 0:
        gepolstert.append(0x00)
    gepolstert[-1] ^= 0x80

    # Aufsaugen
    for block in range(0, len(gepolstert), rate):
        stueck = gepolstert[block:block + rate]
        for i in range(rate // 8):
            lane = int.from_bytes(stueck[i * 8:(i + 1) * 8], "little")
            zustand[i % 5][i // 5] ^= lane
        _keccak_f(zustand)

    # Ausdruecken - 32 Byte reichen, sie liegen in den ersten vier Lanes
    ausgabe = bytearray()
    for i in range(4):
        ausgabe += zustand[i % 5][i // 5].to_bytes(8, "little")
    return bytes(ausgabe)


def selektor(signatur: str) -> str:
    """Vier-Byte-Selektor einer Funktionssignatur, z. B. 'transfer(address,uint256)'."""
    return keccak256(signatur.encode("ascii")).hex()[:8]
