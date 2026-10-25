"""Money in detail: a ledger of where it came from and went, realistic living costs/taxes (opt-in), loans.

Every career keeps the ledger (so the budget view works everywhere). Only careers created with the
'realistic economy' option (character_build['economy'] == 'realistic') pay living costs, tuition, taxes
and interest; everyone else keeps the original simple balance.
"""

from datetime import date

from app.models import Player
from app.services import story

WEEKLY_GROSS = {"school": 10.0, "university": 80.0, "work": 360.0, "pro": 0.0}
WEEKLY_LIVING = {"school": 0.0, "university": 30.0, "work": 120.0, "pro": 150.0}
WEEKLY_TUITION = {"university": 18.0}
SALARY_TAX = 0.20
WINNINGS_TAX = 0.15  # prizes, sponsors and stream income
DEBT_INTEREST = 0.015  # per month on a negative balance
LOAN_INTEREST = 0.02  # per month on a loan
DEBT_LIMIT = -500.0  # realistic careers: below this a pro has to take a job
LEDGER_MONTHS = 18

INCOME_CATEGORIES = ("salary", "prize", "sponsor", "stream", "event", "loan", "other")
COST_CATEGORIES = ("living", "tuition", "tax", "gear", "physio", "interest", "repay", "event_cost", "services", "subscription")


def realistic(player: Player) -> bool:
    return (player.character_build or {}).get("economy") == "realistic"


def hardcore(player: Player) -> bool:
    return bool((player.character_build or {}).get("hardcore"))


def record(player: Player, category: str, amount: float, on: date) -> None:
    """Add `amount` (negative = cost) to the month's ledger."""
    if not amount:
        return
    ledger = {m: dict(v) for m, v in (story.get(player, "ledger") or {}).items()}
    month = ledger.setdefault(on.strftime("%Y-%m"), {})
    month[category] = round(month.get(category, 0.0) + amount, 2)
    for old in sorted(ledger)[:-LEDGER_MONTHS]:
        del ledger[old]
    story.put(player, "ledger", ledger)


def earn(player: Player, amount: float, category: str, on: date) -> float:
    """Income that is taxed in realistic careers (prizes, sponsors, stream). Returns what reached the wallet."""
    tax = round(amount * WINNINGS_TAX, 2) if realistic(player) else 0.0
    record(player, category, amount, on)
    if tax:
        record(player, "tax", -tax, on)
    player.money += amount - tax
    return amount - tax


def spend(player: Player, amount: float, category: str, on: date) -> None:
    player.money -= amount
    record(player, category, -amount, on)


def weekly(player: Player, on: date) -> float:
    """The Sunday payment. Realistic: gross pay minus tax, living costs and tuition; otherwise the old net."""
    from app.services import life

    if not realistic(player):
        net = life.WEEKLY_INCOME[player.occupation]
        record(player, "salary" if net >= 0 else "living", net, on)
        player.money += net
        return net
    gross = WEEKLY_GROSS[player.occupation]
    tax = round(gross * SALARY_TAX, 2) if player.occupation == "work" else 0.0
    living = WEEKLY_LIVING[player.occupation]
    tuition = WEEKLY_TUITION.get(player.occupation, 0.0)
    record(player, "salary", gross, on)
    record(player, "tax", -tax, on)
    record(player, "living", -living, on)
    record(player, "tuition", -tuition, on)
    net = gross - tax - living - tuition
    player.money += net
    return net


def monthly(player: Player, on: date) -> list[str]:
    """First of the month: interest, then a short statement of the previous month. Returns activity-log lines."""
    lines: list[str] = []
    if realistic(player):
        if player.money < 0:
            fee = round(-player.money * DEBT_INTEREST, 2)
            player.money -= fee
            record(player, "interest", -fee, on)
        loan = story.get(player, "loan") or 0.0
        if loan > 0:
            fee = round(loan * LOAN_INTEREST, 2)
            story.put(player, "loan", round(loan + fee, 2))
            record(player, "interest", -fee, on)
        prev = date(on.year - (on.month == 1), on.month - 1 or 12, 1).strftime("%Y-%m")
        inc, cost = totals((story.get(player, "ledger") or {}).get(prev, {}))
        if inc or cost:
            lines.append(f"Monthly statement ({prev}): income ${inc:,.0f}, costs ${cost:,.0f}, net ${inc - cost:,.0f}.")
    return lines


def totals(month: dict) -> tuple[float, float]:
    income = sum(v for k, v in month.items() if v > 0 and k != "loan")
    costs = -sum(v for k, v in month.items() if v < 0 and k != "repay")
    return round(income, 2), round(costs, 2)


def statement(player: Player, months: int = 6) -> list[dict]:
    ledger = story.get(player, "ledger") or {}
    out = []
    for key in sorted(ledger)[-months:]:
        inc, cost = totals(ledger[key])
        out.append({"month": key, "categories": ledger[key], "income": inc, "costs": cost, "net": round(inc - cost, 2)})
    return out


def weekly_burn(player: Player, occupation: str) -> float:
    """What a week costs in this occupation before any winnings."""
    if realistic(player):
        gross = WEEKLY_GROSS[occupation]
        return WEEKLY_LIVING[occupation] + WEEKLY_TUITION.get(occupation, 0.0) + (gross * SALARY_TAX if occupation == "work" else 0) - gross
    from app.services import life

    return -life.WEEKLY_INCOME[occupation]


def runway(player: Player) -> dict:
    """How long the money lasts as things stand, and if the player went pro."""
    ledger = story.get(player, "ledger") or {}
    recent = [totals(ledger[k]) for k in sorted(ledger)[-2:]]
    winnings = sum(
        v * (1 - (WINNINGS_TAX if realistic(player) else 0.0)) for k in sorted(ledger)[-2:]
        for c, v in ledger[k].items() if c in ("prize", "sponsor", "stream") and v > 0) / max(1, len(recent)) / 4.35
    out = {}
    for label, occ in (("now", player.occupation), ("pro", "pro")):
        burn = weekly_burn(player, occ) - (winnings if occ == "pro" or label == "now" else 0.0)
        out[label] = None if burn <= 0 else round(max(0.0, player.money) / burn, 1)
    return {"weekly_burn": round(weekly_burn(player, player.occupation), 1), "winnings_per_week": round(winnings, 1),
            "weeks_left_now": out["now"], "weeks_left_pro": out["pro"]}


def loan_limit(player: Player) -> float:
    return max(300.0, 10 * max(0.0, WEEKLY_GROSS[player.occupation] - WEEKLY_LIVING[player.occupation]))


def take_loan(player: Player, amount: float, on: date) -> None:
    owed = story.get(player, "loan") or 0.0
    if amount <= 0 or owed + amount > loan_limit(player):
        raise ValueError(f"you can borrow at most ${max(0.0, loan_limit(player) - owed):,.0f} more")
    story.put(player, "loan", round(owed + amount, 2))
    player.money += amount
    record(player, "loan", amount, on)


def repay(player: Player, amount: float, on: date) -> float:
    owed = story.get(player, "loan") or 0.0
    amount = min(amount, owed, max(0.0, player.money))
    if amount <= 0:
        raise ValueError("nothing to repay: no loan or no money")
    player.money -= amount
    story.put(player, "loan", round(owed - amount, 2))
    record(player, "repay", -amount, on)
    if owed - amount <= 0.01:
        story.put(player, "loan", 0.0)
        story.put(player, "loans_repaid", (story.get(player, "loans_repaid") or 0) + 1)
    return amount
