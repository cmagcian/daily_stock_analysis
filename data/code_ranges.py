# -*- coding: utf-8 -*-
"""
A-share stock code ranges for scanning.

Each tuple: (code_start, code_end, market_tag) where code_start/code_end
are 6-digit strings defining the inclusive range of codes to scan.
"""

CODE_RANGES = [
    # Shanghai main board: 600000-605999
    ("600000", "605999", "sh"),
    # Shanghai STAR Market: 688000-688999
    ("688000", "688999", "sh"),
    # Shenzhen main board: 000000-003999
    ("000000", "003999", "sz"),
    # Shenzhen ChiNext: 300000-300999
    ("300000", "300999", "sz"),
    # Beijing Stock Exchange
    ("830000", "879999", "bj"),
    ("920000", "929999", "bj"),
]


def generate_all_codes() -> list[tuple[str, str]]:
    """Generate all possible A-share code strings from the ranges.

    Returns list of (code, market) tuples.
    """
    codes: list[tuple[str, str]] = []
    for start, end, _market in CODE_RANGES:
        for i in range(int(start), int(end) + 1):
            code = str(i).zfill(6)
            if code.startswith(("6", "5")):
                mkt = "sh"
            elif code.startswith(("0", "3")):
                mkt = "sz"
            else:
                mkt = "bj"
            codes.append((code, mkt))
    return codes


if __name__ == "__main__":
    codes = generate_all_codes()
    print(f"Total ranges: {len(CODE_RANGES)}")
    print(f"Total codes: {len(codes)}")
    print(f"First 5: {codes[:5]}")
    print(f"Last 5: {codes[-5:]}")
