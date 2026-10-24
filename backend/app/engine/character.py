"""Creation options shared by the API and the character builder."""
from app.engine import attributes as A

BUDGET = 4
GROUP_LABELS = {"aim": "аим", "tapping": "тэппинг", "reading": "ридинг",
                "technical": "техника", "mentality": "психология", "physical": "физика"}
PERKS = {
    "quick_learner": {"label": "Быстро учится", "cost": 3, "description": "Все навыки растут на 25% быстрее.", "talent": 1.25},
    "slow_learner": {"label": "Медленно учится", "cost": -3, "description": "Все навыки растут на 20% медленнее.", "talent": 0.8},
    "high_ceiling": {"label": "Большой потенциал", "cost": 3, "description": "Потолок всех навыков +7.", "cap": 7},
    "low_ceiling": {"label": "Ограниченный потенциал", "cost": -3, "description": "Потолок всех навыков −7.", "cap": -7},
}
for group in A.GROUPS:
    for suffix, label, cost, affinity, base in (
        ("gift", "Талант", 2, 1.3, 5), ("weakness", "Слабость", -2, 0.75, -3),
    ):
        PERKS[f"{group.key}_{suffix}"] = {
            "label": f"{label}: {GROUP_LABELS[group.key]}", "cost": cost, "group": group.key,
            "description": f"Старт {base:+}; скорость обучения {round((affinity - 1) * 100):+}% в этой группе.",
            "affinity": affinity, "base": base,
        }

PRESETS = {
    "farmer": {"label": "Фармер", "perks": ["aim_gift", "reading_gift", "tapping_weakness"]},
    "streamer": {"label": "Стример", "perks": ["tapping_gift", "physical_gift", "aim_weakness"]},
    "technician": {"label": "Технарь", "perks": ["technical_gift", "reading_gift", "physical_weakness"]},
    "tournament": {"label": "Турнирный игрок", "perks": ["mentality_gift", "technical_gift", "aim_weakness"]},
    "prodigy": {"label": "Неогранённый талант", "perks": ["quick_learner", "high_ceiling", "mentality_weakness"]},
}
CONFLICTS = [("quick_learner", "slow_learner"), ("high_ceiling", "low_ceiling")]
CONFLICTS += [(f"{g.key}_gift", f"{g.key}_weakness") for g in A.GROUPS]


def resolve(preset: str, selected: list[str] | None, unbalanced: bool) -> list[str]:
    if preset not in ("random", "custom") and preset not in PRESETS:
        raise ValueError("Unknown character preset")
    if preset == "random":
        if selected:
            raise ValueError("Choose custom mode to select perks")
        return []
    perks = list(selected if selected is not None else PRESETS.get(preset, {}).get("perks", []))
    if len(perks) != len(set(perks)) or any(p not in PERKS for p in perks):
        raise ValueError("Unknown or duplicate perk")
    if any(a in perks and b in perks for a, b in CONFLICTS):
        raise ValueError("Conflicting perks")
    if not unbalanced and sum(PERKS[p]["cost"] for p in perks) > BUDGET:
        raise ValueError("Not enough balance points")
    return perks


def apply(player, preset: str, perks: list[str], unbalanced: bool) -> None:
    player.character_build = {"preset": preset, "perks": perks, "unbalanced": unbalanced}
    for key in perks:
        perk = PERKS[key]
        player.talent *= perk.get("talent", 1)
        player.potential = A.clamp(player.potential + perk.get("cap", 0))
        for attr in player.attributes:
            attr.cap = A.clamp(attr.cap + perk.get("cap", 0))
            if A.GROUP_OF[attr.key] == perk.get("group"):
                attr.base = A.clamp(attr.base + perk.get("base", 0))
                attr.affinity *= perk.get("affinity", 1)
