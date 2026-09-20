# -*- coding: utf-8 -*-
"""
A-share stock code ranges for scanning.

Based on actual listing ranges (not theoretical):
- Shanghai: 600xxx-603xxx (main board), 605xxx (sparse), 688xxx (STAR)
- Shenzhen: 000xxx-002xxx (main), 300xxx-301xxx (ChiNext)
"""

CODE_RANGES = [
    # Shanghai main board - most A-shares are in this range
    ("600001", "603999", "sh"),
    # Shanghai sparse range
    ("605000", "605999", "sh"),
    # Shanghai STAR Market
    ("688000", "688999", "sh"),
    # Shenzhen main board
    ("000001", "002999", "sz"),
    # Shenzhen ChiNext
    ("300001", "301000", "sz"),
]


def generate_all_codes() -> list[tuple[str, str]]:
    """Generate all possible A-share code strings from the ranges."""
    codes: list[tuple[str, str]] = []
    for start, end, _market in CODE_RANGES:
        for i in range(int(start), int(end) + 1):
            code = str(i).zfill(6)
            if code.startswith(("6", "5")):
                mkt = "sh"
            elif code.startswith(("0", "3")):
                mkt = "sz"
            else:
                continue
            codes.append((code, mkt))
    return codes


if __name__ == "__main__":
    codes = generate_all_codes()
    sh = sum(1 for c, m in codes if m == "sh")
    sz = sum(1 for c, m in codes if m == "sz")
    print(f"Total: {len(codes)} (SH:{sh} SZ:{sz})")
    print(f"First 5: {codes[:5]}")
    print(f"Last 5: {codes[-5:]}")
