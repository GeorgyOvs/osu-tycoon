"""Double-elimination bracket layout for power-of-two fields.

Winners bracket rounds W1..Wk, losers bracket L1..L(2k-2), then a single Grand Final.
Each match knows where its two players come from (a seed, or the winner/loser of an
earlier match) and which week it's played in, so the schedule falls out of the layout.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchSpec:
    key: str
    week: int
    order: int
    stage: str
    first_to: int
    source_a: str
    source_b: str


def _seed_order(size: int) -> list[int]:
    """Standard seeding so 1 and 2 can only meet in the final: [1, 16, 8, 9, ...]."""
    order = [1]
    while len(order) < size:
        n = len(order) * 2
        order = [x for s in order for x in (s, n + 1 - s)]
    return order


def _winners_stage(remaining: int) -> str:
    return {2: "Finals", 4: "Semifinals", 8: "Quarterfinals"}.get(remaining, f"Round of {remaining}")


def _first_to(stage: str) -> int:
    if stage in ("Grand Finals", "Finals", "Losers Finals"):
        return 7
    if stage in ("Semifinals", "Quarterfinals") or stage.startswith("Losers Round") and stage[-1] in "45678":
        return 6
    return 5


def double_elimination(size: int) -> list[MatchSpec]:
    k = size.bit_length() - 1
    if size < 4 or 2**k != size:
        raise ValueError("bracket size must be a power of two >= 4")

    raw: list[tuple[int, int, int, int, str, str, str]] = []  # (week, bracket, round, index, stage, a, b)
    seeds = _seed_order(size)
    for i in range(size // 2):
        raw.append((1, 0, 1, i, _winners_stage(size), f"seed:{seeds[2 * i]}", f"seed:{seeds[2 * i + 1]}"))
    for r in range(2, k + 1):
        stage = _winners_stage(size >> (r - 1))
        for i in range(size >> r):
            raw.append((r, 0, r, i, stage, f"winner:W{r - 1}-{2 * i}", f"winner:W{r - 1}-{2 * i + 1}"))

    lb_rounds = 2 * (k - 1)
    for m in range(1, lb_rounds + 1):
        stage = "Losers Finals" if m == lb_rounds else f"Losers Round {m}"
        if m == 1:
            for i in range(size // 4):
                raw.append((2, 1, 1, i, stage, f"loser:W1-{2 * i}", f"loser:W1-{2 * i + 1}"))
        elif m % 2 == 0:
            j = m // 2
            count = size >> (j + 1)
            for i in range(count):
                # Drop-downs are mirrored so early rematches are rarer.
                raw.append((j + 1, 1, m, i, stage, f"winner:L{m - 1}-{i}", f"loser:W{j + 1}-{count - 1 - i}"))
        else:
            j = (m - 1) // 2
            for i in range(size >> (j + 2)):
                raw.append((j + 2, 1, m, i, stage, f"winner:L{m - 1}-{2 * i}", f"winner:L{m - 1}-{2 * i + 1}"))
    raw.append((k + 1, 2, 1, 0, "Grand Finals", f"winner:W{k}-0", f"winner:L{lb_rounds}-0"))

    raw.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    specs = []
    for order, (week, bracket, rnd, idx, stage, a, b) in enumerate(raw):
        key = "GF" if bracket == 2 else f"{'WL'[bracket]}{rnd}-{idx}"
        specs.append(MatchSpec(key, week, order, stage, _first_to(stage), a, b))
    return specs


def _losers_round_size(m: int, size: int) -> int:
    if m == 1:
        return size // 4
    j = m // 2
    return size >> (j + 1) if m % 2 == 0 else size >> (j + 2)


def placement(key: str, size: int) -> str | None:
    """Final placement of the player who lost match `key`; None while they're still alive."""
    if key == "GF":
        return "2nd"
    if not key.startswith("L"):
        return None  # losing in the winners bracket drops you to the losers bracket
    rnd = int(key[1:].split("-")[0])
    eliminated_before = sum(_losers_round_size(m, size) for m in range(1, rnd))
    worst = size - eliminated_before  # everyone knocked out this round shares these places
    best = worst - _losers_round_size(rnd, size) + 1
    return _ordinal(best) if best == worst else f"{_ordinal(best)}–{_ordinal(worst)}"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
