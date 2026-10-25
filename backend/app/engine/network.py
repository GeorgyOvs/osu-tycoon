"""Regions and ping: playing a lobby, duel or tournament match against someone far away costs a little."""

REGION_OF = {
    **{c: "EU" for c in ("RU", "DE", "PL", "FR", "ES", "FI", "SE", "NL", "IT", "UA", "GB", "UK", "NO", "DK", "CZ", "TR",
                         "BY", "AT", "CH", "PT", "BE", "RO", "HU", "GR", "IE", "LT", "LV", "EE", "XX")},
    **{c: "NA" for c in ("US", "CA", "MX")},
    **{c: "SA" for c in ("BR", "AR", "CL", "CO", "PE", "UY")},
    **{c: "AS" for c in ("KR", "JP", "CN", "TW", "ID", "PH", "TH", "VN", "SG", "IN", "MY", "HK")},
    **{c: "OC" for c in ("AU", "NZ")},
}
REGION_NAMES = {"EU": "Europe", "NA": "North America", "SA": "South America", "AS": "Asia", "OC": "Oceania"}
_BASE = {
    ("EU", "EU"): 25, ("EU", "NA"): 100, ("EU", "AS"): 220, ("EU", "OC"): 290, ("EU", "SA"): 200,
    ("NA", "NA"): 40, ("NA", "AS"): 170, ("NA", "OC"): 190, ("NA", "SA"): 130,
    ("AS", "AS"): 60, ("AS", "OC"): 120, ("AS", "SA"): 330,
    ("OC", "OC"): 30, ("OC", "SA"): 280, ("SA", "SA"): 45,
}
MAX_ISP_LEVEL = 2
ISP_COST = (40.0, 90.0)  # per level, launch prices
ISP_LATENCY_CUT = 0.3  # per level
FREE_PING_MS = 60  # below this nothing changes


def region(country: str) -> str:
    return REGION_OF.get((country or "XX").upper(), "EU")


def local_ms(year: int) -> float:
    """Last-mile latency of an ordinary home connection."""
    points = [(2007, 75.0), (2012, 55.0), (2018, 30.0), (2024, 15.0)]
    if year <= points[0][0]:
        return points[0][1]
    for (y0, v0), (y1, v1) in zip(points, points[1:]):
        if year <= y1:
            return v0 + (v1 - v0) * (year - y0) / (y1 - y0)
    return points[-1][1]


def server_factor(year: int) -> float:
    """Regional servers and better routing shave long-distance latency in later years."""
    return 1.0 if year < 2018 else 0.8 if year < 2021 else 0.65


def ping(region_a: str, region_b: str, year: int, isp_level: int = 0) -> int:
    key = tuple(sorted((region_a, region_b)))
    base = _BASE.get(key, 150)
    factor = server_factor(year) if region_a != region_b else 1.0
    local = local_ms(year) * (1 - ISP_LATENCY_CUT * min(isp_level, MAX_ISP_LEVEL))
    return round(base * factor + local)


def lobby_ping(own: str, year: int, isp_level: int = 0) -> int:
    """Typical ping in a public multiplayer lobby: mostly your own region, partly the rest of the world."""
    others = [ping(own, r, year, isp_level) for r in REGION_NAMES if r != own]
    return round(0.6 * ping(own, own, year, isp_level) + 0.4 * sum(others) / len(others))


def tier(ms: int) -> str:
    return "excellent" if ms < 50 else "good" if ms < 100 else "noticeable" if ms < 150 else "poor"


def pressure_factor(ms: int) -> float:
    """Choke multiplier from lag spikes and uncertain timing (1.0 up to ~60 ms, at most +20%)."""
    return 1.0 + min(0.2, max(0.0, (ms - FREE_PING_MS) / 900))
