"""Everything that sits between raw attributes and how the player actually performs or learns:
gear, playstyle, age. One place, so sessions, assessments and matches all agree.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import attributes as A
from app.engine import gear, simulation
from app.models import InventoryItem, Player
from app.services import economy, life, setup, story

AIM_SUBS = [s.key for s in A.GROUPS_BY_KEY["aim"].subs] + ["awkward_angles"]
TAP_SUBS = [s.key for s in A.GROUPS_BY_KEY["tapping"].subs]
PHYSIO_COST_PER_DAY = 30.0

# Playstyle effects on sub-stats while playing.
DEVICE_STYLE = {
    "tablet": {"flow_aim": 1.05, "precision": 1.04},
    "mouse": {"distance": 1.05, "snap_aim": 1.03, "flow_aim": 0.98},
}
SINGLETAP_CAPS = {"burst": 55.0, "deathstream": 45.0}  # ~230 BPM bursts is about the singletap ceiling
SINGLETAP_BONUS = {"low_mid_bpm": 1.05}
ADAPTATION_PER_HOUR = 0.008  # share of the remaining gap closed per hour of playing
SWITCH_DEVICE, SWITCH_TAP = 0.35, 0.5  # adaptation right after switching


class ShopError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


# --- gear ------------------------------------------------------------------------------------


def ensure_gear(db: Session, player: Player) -> None:
    """Every career starts with a cheap, era-typical setup."""
    if db.scalar(select(InventoryItem.id).where(InventoryItem.player_id == player.id).limit(1)) is not None:
        return
    for key in gear.STARTER_KIT:
        db.add(InventoryItem(player_id=player.id, item_key=key, bought_on=player.in_game_date, equipped=True))
    db.flush()


def inventory(db: Session, player: Player) -> list[InventoryItem]:
    ensure_gear(db, player)
    return list(db.scalars(select(InventoryItem).where(InventoryItem.player_id == player.id)))


def equipped(db: Session, player: Player) -> list[gear.Item]:
    return [gear.CATALOG[i.item_key] for i in inventory(db, player) if i.equipped and i.item_key in gear.CATALOG]


def gear_effects(db: Session, player: Player) -> gear.Effects:
    return gear.effects(equipped(db, player), player.input_device)


def refresh_ergonomics(db: Session, player: Player) -> None:
    player.ergonomics = round(gear_effects(db, player).ergonomics, 3)


def buy(db: Session, player: Player, key: str) -> InventoryItem:
    item = gear.CATALOG.get(key)
    if item is None:
        raise ShopError(404, f"no such item '{key}'")
    if item.discontinued(player.in_game_date):
        raise ShopError(409, f"{item.name} is no longer sold")
    if not item.available(player.in_game_date):
        raise ShopError(409, f"{item.name} isn't out yet in {player.in_game_date.year}")
    if any(i.item_key == key for i in inventory(db, player)):
        raise ShopError(409, f"you already own {item.name}")
    price = item.price_on(player.in_game_date)
    if player.money < price:
        raise ShopError(409, f"{item.name} costs ${price:.0f}; you have ${player.money:.0f}")
    economy.spend(player, price, "gear", player.in_game_date)
    row = InventoryItem(player_id=player.id, item_key=key, bought_on=player.in_game_date, equipped=False)
    db.add(row)
    db.flush()
    equip(db, player, key)
    setup.reset_wear(player, item.category)  # a new item is unworn
    return row


def equip(db: Session, player: Player, key: str) -> None:
    item = gear.CATALOG.get(key)
    rows = inventory(db, player)
    mine = next((r for r in rows if r.item_key == key), None)
    if item is None or mine is None:
        raise ShopError(404, "you don't own that")
    was_equipped = mine.equipped
    for r in rows:
        other = gear.CATALOG.get(r.item_key)
        if other and other.category == item.category:
            r.equipped = r.item_key == key
    db.flush()
    refresh_ergonomics(db, player)
    if not was_equipped:
        setup.on_gear_change(player, item.category)


def pay_physio(player: Player, days: int) -> None:
    cost = PHYSIO_COST_PER_DAY * days * (0.4 if "medical_insurance" in (story.get(player, "subs") or {}) else 1.0)
    if player.money < cost:
        raise ShopError(409, f"{days} days of physiotherapy cost ${cost:.0f}; you have ${player.money:.0f}")
    economy.spend(player, cost, "physio", player.in_game_date)


# --- performance and learning ----------------------------------------------------------------


def play_skills(db: Session, player: Player) -> dict[str, float]:
    """Sub-stats as they show up while playing: attributes x gear x playstyle."""
    values = simulation.effective_values(player)
    fx = gear_effects(db, player)
    for key in AIM_SUBS:
        values[key] *= fx.aim
    for key in TAP_SUBS:
        values[key] *= fx.tapping
    if fx.ar_cap is not None:
        values["high_ar_reaction"] = min(values["high_ar_reaction"], fx.ar_cap)
    for key, mult in DEVICE_STYLE.get(player.input_device, {}).items():
        values[key] *= mult
    if player.tap_style == "singletap":
        for key, cap in SINGLETAP_CAPS.items():
            values[key] = min(values[key], cap)
        for key, mult in SINGLETAP_BONUS.items():
            values[key] *= mult
    adaptation = 0.75 + 0.25 * player.style_adaptation  # still getting used to a new setup
    play = adaptation * story.mod_product(player, "play")  # faulty gear and the like
    aim_wear, tap_wear = setup.multipliers(player)  # worn gear and unsettled settings
    for key in AIM_SUBS:
        values[key] *= play * aim_wear
    for key in TAP_SUBS:
        values[key] *= play * tap_wear
    reaction = life.reaction_multiplier(player)  # reflexes slowly fade past 25
    for key in ("high_ar_reaction", "burst", "snap_aim"):
        values[key] *= reaction
    for key, mult in story.skill_multipliers(player).items():  # sports psychologist, eye care, headphones...
        if key in values:
            values[key] *= mult
    return {k: A.clamp(v) for k, v in values.items()}


def set_playstyle(db: Session, player: Player, input_device: str | None, tap_style: str | None) -> None:
    if input_device is not None and input_device != player.input_device:
        if input_device not in gear.INPUT_CATEGORIES:
            raise ShopError(422, "input device must be mouse or tablet")
        rows = [(r, gear.CATALOG[r.item_key]) for r in inventory(db, player) if r.item_key in gear.CATALOG]
        devices = [(r, item) for r, item in rows if item.category == input_device]
        if not devices:
            raise ShopError(409, f"buy a {input_device} first")
        if not any(r.equipped for r, _ in devices):
            devices[0][0].equipped = True
        player.input_device = input_device
        player.style_adaptation *= SWITCH_DEVICE
        setup.on_device_switch(player)
    if tap_style is not None and tap_style != player.tap_style:
        if tap_style not in ("alternate", "singletap"):
            raise ShopError(422, "tap style must be alternate or singletap")
        player.tap_style = tap_style
        player.style_adaptation *= SWITCH_TAP
    refresh_ergonomics(db, player)


def progress_adaptation(player: Player, hours_played: float) -> None:
    setup.add_hours(player, hours_played)
    player.style_adaptation += (1 - player.style_adaptation) * min(1.0, ADAPTATION_PER_HOUR * hours_played)


def learning_extras(db: Session, player: Player) -> tuple[float, dict[str, float]]:
    """(learning-speed multiplier, trainable caps) for the day tick."""
    fx = gear_effects(db, player)
    caps = {"high_ar_reaction": fx.ar_cap} if fx.ar_cap is not None else {}
    from app.services import teams  # a fresh scrim with the squad speeds learning up a little

    return life.learning_multiplier(player) * teams.learning_multiplier(db, player), caps

