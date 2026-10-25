"""Static world data: historical legends, procedural name parts, countries, tournaments.

Legend careers are approximations written from community memory, not official records:
the shape of each career (rise, prime, hiatus, decline) matters more than exact numbers.
Extend or correct them here; each curve point is (YYYY-MM, overall rating).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Legend:
    name: str
    country: str
    # Composite skew in -1..1 per group: where this player is stronger or weaker than their overall.
    style: dict[str, float]
    curve: tuple[tuple[str, float], ...]
    # (from YYYY-MM, to YYYY-MM or None, status) - inactive / restricted / retired periods.
    breaks: tuple[tuple[str, str | None, str], ...] = ()
    note: str = ""
    # Other names the same person played under. One person = one legend, never separate entries.
    aliases: tuple[str, ...] = ()


def _s(aim=0.0, tapping=0.0, reading=0.0, technical=0.0, mentality=0.0, physical=0.0) -> dict[str, float]:
    return {"aim": aim, "tapping": tapping, "reading": reading, "technical": technical,
            "mentality": mentality, "physical": physical}


LEGENDS: tuple[Legend, ...] = (
    Legend("Cookiezi", "KR", _s(aim=0.3, tapping=0.6, reading=0.5, technical=0.2, physical=-0.2),
           (("2009-06", 45), ("2010-06", 75), ("2011-01", 88), ("2012-01", 97), ("2013-01", 99), ("2013-10", 99),
            ("2015-06", 92), ("2016-03", 97), ("2017-01", 98), ("2018-01", 92), ("2020-01", 89), ("2023-01", 86)),
           (("2013-11", "2015-05", "inactive"),),
           "Unmatched HD reading and stream snapping; later struggles with hand pain.",
           aliases=("chocomint", "nathan on osu")),
    Legend("rrtyui", "JP", _s(aim=0.3, reading=0.6, mentality=0.5),
           (("2010-06", 60), ("2012-01", 92), ("2013-01", 96), ("2014-06", 95), ("2015-01", 88)),
           (("2015-03", None, "retired"),), "Incomparable reading and clutch; 'plz enjoy game'."),
    Legend("hvick225", "KR", _s(aim=0.5, tapping=0.2, reading=0.3),
           (("2010-06", 55), ("2012-01", 90), ("2013-01", 94), ("2014-06", 92), ("2016-01", 86)),
           (("2017-06", None, "retired"),)),
    Legend("Angelsim", "KR", _s(aim=0.4, reading=0.3, mentality=0.2),
           (("2011-06", 60), ("2013-01", 90), ("2014-01", 95), ("2015-01", 94)),
           (("2016-06", None, "retired"),)),
    Legend("Yaong", "KR", _s(tapping=0.4, aim=0.2),
           (("2011-01", 70), ("2012-06", 92), ("2013-06", 90)),
           (("2014-06", None, "retired"),)),
    Legend("Doomsday", "CA", _s(tapping=0.5, physical=0.3),
           (("2011-01", 75), ("2012-01", 88), ("2013-01", 89), ("2014-06", 84)),
           (("2015-06", None, "retired"),)),
    Legend("Rafis", "PL", _s(aim=0.3, tapping=0.4, reading=0.2, mentality=0.3),
           (("2011-06", 55), ("2013-01", 85), ("2014-06", 92), ("2015-06", 97), ("2016-06", 98), ("2018-01", 94),
            ("2020-01", 90), ("2023-01", 86))),
    Legend("WubWoofWolf", "PL", _s(aim=0.4, tapping=0.3, technical=0.3),
           (("2012-01", 70), ("2013-06", 92), ("2014-06", 94), ("2015-06", 92), ("2017-01", 85)),
           (("2018-06", None, "retired"),)),
    Legend("-GN", "DE", _s(tapping=0.5, aim=0.2),
           (("2012-06", 70), ("2014-01", 92), ("2015-01", 94), ("2016-06", 90)),
           (("2018-01", None, "retired"),)),
    Legend("ThePooN", "FR", _s(reading=0.3, technical=0.4),
           (("2013-01", 70), ("2014-06", 88), ("2016-01", 87), ("2018-01", 80)),
           (("2019-01", None, "retired"),)),
    Legend("Ekoro", "FR", _s(aim=0.4),
           (("2014-01", 75), ("2015-06", 92), ("2016-06", 92), ("2018-01", 84)),
           (("2019-01", None, "retired"),)),
    Legend("Bubbleman", "US", _s(tapping=0.4),
           (("2014-06", 75), ("2015-06", 90), ("2016-06", 92), ("2018-01", 85)),
           (("2019-06", None, "retired"),)),
    Legend("Mlaw22", "US", _s(tapping=0.5),
           (("2015-06", 70), ("2016-06", 88), ("2018-01", 84)),
           (("2019-01", None, "retired"),)),
    Legend("idke", "US", _s(aim=0.3, reading=0.5),
           (("2015-01", 70), ("2016-06", 90), ("2017-06", 95), ("2019-01", 97), ("2020-06", 94), ("2022-01", 90))),
    Legend("Freddie Benson", "US", _s(aim=0.4, tapping=0.3),
           (("2015-01", 70), ("2016-06", 92), ("2017-06", 95), ("2019-01", 92), ("2020-01", 86)),
           (("2021-06", None, "retired"),)),
    Legend("Vaxei", "US", _s(aim=0.3, tapping=0.3, reading=0.3),
           (("2015-06", 60), ("2016-06", 85), ("2017-06", 94), ("2018-06", 98), ("2019-06", 99), ("2021-01", 97),
            ("2023-01", 94))),
    Legend("WhiteCat", "DE", _s(aim=0.5, tapping=0.4),
           (("2016-01", 70), ("2017-06", 95), ("2018-06", 99), ("2019-06", 98)),
           (("2020-01", None, "retired"),), "Retired early, citing hand problems."),
    Legend("Mathi", "CL", _s(aim=0.4),
           (("2016-01", 75), ("2017-06", 92), ("2018-06", 94), ("2020-01", 88), ("2022-01", 84))),
    Legend("FlyingTuna", "KR", _s(aim=0.5),
           (("2016-06", 70), ("2017-06", 92), ("2018-06", 94), ("2020-01", 88))),
    Legend("Aricin", "US", _s(tapping=0.3),
           (("2016-01", 70), ("2017-06", 89), ("2018-06", 88), ("2020-01", 82))),
    Legend("BTMC", "US", _s(tapping=0.3, mentality=0.2),
           (("2016-06", 60), ("2018-06", 82), ("2020-06", 87), ("2022-06", 86))),
    Legend("Azer", "CA", _s(aim=0.3, reading=0.3),
           (("2017-01", 70), ("2018-06", 90), ("2019-06", 95), ("2021-01", 93), ("2023-01", 88))),
    Legend("Lifeline", "US", _s(technical=0.3, reading=0.3),
           (("2017-06", 70), ("2019-01", 90), ("2020-06", 95), ("2022-01", 94), ("2024-01", 92))),
    Legend("mrekk", "AU", _s(aim=0.6, tapping=0.5, reading=0.4),
           (("2015-01", 20), ("2017-06", 30), ("2018-06", 70), ("2019-06", 82), ("2020-06", 92), ("2021-06", 101),
            ("2022-06", 106), ("2024-01", 108), ("2025-06", 109)),
           note="Untouchable modern prime: burst, flow aim and AR11 reaction."),
)

# Weighted pool for procedural players.
COUNTRIES: tuple[tuple[str, int], ...] = (
    ("US", 14), ("RU", 8), ("PL", 6), ("DE", 6), ("KR", 6), ("JP", 6), ("CA", 5), ("BR", 5), ("FR", 4),
    ("GB", 4), ("AU", 4), ("CN", 4), ("ID", 3), ("PH", 3), ("TW", 3), ("CL", 2), ("AR", 2), ("MX", 2),
    ("SE", 2), ("FI", 2), ("UA", 2), ("NL", 2), ("IT", 2), ("ES", 2), ("TH", 2), ("MY", 2), ("SG", 1),
    ("NO", 1), ("HK", 1), ("VN", 1), ("AT", 1), ("BE", 1), ("CH", 1), ("CZ", 1), ("DK", 1), ("HU", 1),
    ("PT", 1), ("RO", 1), ("NZ", 1), ("KZ", 1), ("BY", 1), ("LT", 1), ("EE", 1), ("LV", 1), ("IL", 1),
    ("TR", 1), ("PE", 1), ("CO", 1), ("VE", 1), ("ZA", 1),
)

NAME_HEADS = ("Shi", "Ryu", "Kai", "Neo", "Aki", "Rin", "Zer", "Val", "Mor", "Kuro", "Hika", "Sora", "Nyx", "Ash",
              "Ren", "Yuki", "Tae", "Min", "Lux", "Vex", "Kiri", "Fen", "Haru", "Mio", "Rai", "Sel", "Tor", "Ume")
NAME_TAILS = ("ro", "ka", "ne", "x", "on", "ira", "to", "ryu", "mi", "zu", "el", "ix", "an", "ko", "rei", "ta")
NAME_WORDS = ("cookie", "fox", "neko", "tapper", "flow", "stream", "jump", "kitsune", "mochi", "pixel", "snow",
              "nova", "echo", "drift", "frost", "storm", "byte", "lumen", "aria", "bento")


@dataclass(frozen=True)
class TournamentTemplate:
    key: str
    name: str  # {year} is substituted
    tier: str  # community | open | major | owc
    rank_min: int
    rank_max: int
    month: int
    day: int
    size: int = 32
    first_year: int = 2008
    last_year: int = 2100
    team_size: int = 1


# Base star rating of a tier's first stage, in today's terms (scaled down for older eras).
TIER_STARS = {"community6": 3.8, "community": 4.6, "open": 5.6, "major": 6.6, "owc": 6.6, "clan": 5.4}

TOURNAMENTS: tuple[TournamentTemplate, ...] = (
    TournamentTemplate("6dc_spring", "6 Digit Spring Cup {year}", "community6", 100_000, 10_000_000, 3, 10, first_year=2012),
    TournamentTemplate("6dc_autumn", "6 Digit Autumn Cup {year}", "community6", 100_000, 10_000_000, 9, 12, first_year=2012),
    TournamentTemplate("5dc_winter", "5 Digit Winter Cup {year}", "community", 10_000, 99_999, 1, 20, first_year=2012),
    TournamentTemplate("5dc_summer", "5 Digit Summer Cup {year}", "community", 10_000, 99_999, 7, 5, first_year=2012),
    TournamentTemplate("5dc_autumn", "5 Digit Autumn Cup {year}", "community", 10_000, 99_999, 10, 25, first_year=2012),
    TournamentTemplate("open_spring", "Spring Open {year}", "open", 1_000, 9_999, 4, 15, first_year=2010),
    TournamentTemplate("open_summer", "Summer Showdown {year}", "open", 1_000, 9_999, 8, 1, first_year=2010),
    TournamentTemplate("open_winter", "Winter Clash {year}", "open", 1_000, 9_999, 12, 1, first_year=2010),
    TournamentTemplate("roundtable", "The Roundtable {year}", "major", 1, 500, 5, 20, first_year=2015),
    TournamentTemplate("corsace", "Corsace Open {year}", "major", 1, 500, 2, 10, first_year=2018),
    TournamentTemplate("suiji", "Suiji Cup {year}", "major", 1, 500, 8, 25, first_year=2019),
    TournamentTemplate("clan_spring", "Clan Cup Spring {year}", "clan", 1, 10_000_000, 3, 25, size=16, first_year=2010,
                       team_size=3),
    TournamentTemplate("clan_autumn", "Clan Cup Autumn {year}", "clan", 1, 10_000_000, 11, 8, size=16,
                       first_year=2010, team_size=3),
    TournamentTemplate("owc", "osu! World Cup {year}", "owc", 1, 10_000_000, 10, 20, first_year=2011, team_size=3),
    # --- the crowded calendar of the upper ranks (generic names; dates are approximate) ---------------------
    TournamentTemplate("masters_winter", "Winter Masters {year}", "major", 1, 1_000, 1, 15, first_year=2011),
    TournamentTemplate("invitational_spring", "Spring Invitational {year}", "major", 1, 500, 4, 8, first_year=2011),
    TournamentTemplate("midsummer", "Midsummer Cup {year}", "major", 1, 1_000, 6, 28, first_year=2011),
    TournamentTemplate("masters_autumn", "Autumn Masters {year}", "major", 1, 500, 10, 5, first_year=2011),
    TournamentTemplate("invitational_summer", "Summer Invitational {year}", "major", 1, 1_000, 8, 15, first_year=2011),
    TournamentTemplate("elite_showdown", "Elite Showdown {year}", "major", 1, 200, 3, 1, size=16, first_year=2012),
    TournamentTemplate("champions", "Champions Invitational {year}", "major", 1, 100, 11, 28, size=16, first_year=2012),
    TournamentTemplate("premier_summer", "Premier League Summer {year}", "major", 1, 1_500, 7, 20, first_year=2014),
    TournamentTemplate("premier_winter", "Premier League Winter {year}", "major", 1, 1_500, 12, 14, first_year=2014),
    TournamentTemplate("gauntlet", "The Gauntlet {year}", "major", 1, 2_000, 9, 1, first_year=2016),
    TournamentTemplate("grand_prix", "Grand Prix {year}", "major", 1, 3_000, 5, 1, first_year=2015),
    # four-digit and upper five-digit ranks, which used to be thin as well
    TournamentTemplate("open_autumn", "Autumn Open {year}", "open", 1_000, 9_999, 10, 10, first_year=2011),
    TournamentTemplate("open_february", "February Open {year}", "open", 1_000, 9_999, 2, 8, first_year=2012),
    TournamentTemplate("open_midyear", "Midyear Open {year}", "open", 1_000, 9_999, 6, 1, first_year=2012),
    TournamentTemplate("open_plus_spring", "Spring Open Plus {year}", "open", 500, 4_999, 5, 12, first_year=2011),
    TournamentTemplate("open_plus_autumn", "Autumn Open Plus {year}", "open", 500, 4_999, 11, 3, first_year=2011),
    TournamentTemplate("5dc_spring", "5 Digit Spring Cup {year}", "community", 10_000, 99_999, 4, 4, first_year=2012),
    TournamentTemplate("5dc_midyear", "5 Digit Midyear Cup {year}", "community", 10_000, 99_999, 2, 28, first_year=2012),
)
