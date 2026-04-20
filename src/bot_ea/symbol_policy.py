from __future__ import annotations


def infer_instrument_class(symbol_name: str) -> str:
    upper = symbol_name.upper()
    if upper in {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF", "USDCAD", "NZDUSD"}:
        return "forex_major"
    if upper.startswith("XAU") or "GOLD" in upper:
        return "metal"
    if any(tag in upper for tag in ("US30", "NAS", "SPX", "GER", "UK", "JP")):
        return "index_cfd"
    return "unknown"


def default_risk_weight(symbol_name: str) -> float:
    instrument_class = infer_instrument_class(symbol_name)
    if instrument_class == "forex_major":
        return 1.00
    if instrument_class == "metal":
        return 1.30
    if instrument_class == "index_cfd":
        return 1.50
    return 1.20
