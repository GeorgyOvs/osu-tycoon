"""Setup and peripherals: real products, when they came out, what they cost, what they do.

Release dates are month-accurate where widely documented and approximate otherwise; prices are
launch prices in USD (approximate). A product is on sale from its release month until the end of
its `until` year (discontinued after that; owners keep using it), and gets cheaper as it ages.
Effects:
- aim / tapping: multipliers on the matching sub-stats while playing;
- ar_cap: the monitor limits High AR Reaction (a 60Hz screen can't show AR10+ well);
- ergonomics: 0..1, lowers injury risk (feeds Player.ergonomics).
"""

from dataclasses import dataclass, field
from datetime import date

DEPRECIATION_PER_YEAR = 0.10  # street price drops ~10% a year...
PRICE_FLOOR = 0.6  # ...down to 60% of launch
NEW_FOR_DAYS = 180


@dataclass(frozen=True)
class Item:
    key: str
    name: str
    category: str  # mouse | tablet | keyboard | monitor | chair | software
    year: int
    price: float  # launch price
    aim: float = 1.0
    tapping: float = 1.0
    ar_cap: float | None = None
    ergonomics: float | None = None
    requires: str | None = None  # category that must be in use (drivers need a tablet)
    notes: str = ""
    month: int = 1
    until: int | None = None  # last year it can be bought new

    @property
    def released(self) -> date:
        return date(self.year, self.month, 1)

    def available(self, on: date) -> bool:
        return on >= self.released and (self.until is None or on.year <= self.until)

    def discontinued(self, on: date) -> bool:
        return self.until is not None and on.year > self.until

    def is_new(self, on: date) -> bool:
        return 0 <= (on - self.released).days < NEW_FOR_DAYS

    def price_on(self, on: date) -> float:
        years = max(0.0, (on - self.released).days / 365.25)
        return float(round(self.price * max(PRICE_FLOOR, 1 - DEPRECIATION_PER_YEAR * int(years))))


CATALOG: dict[str, Item] = {i.key: i for i in [
    # --- mice -------------------------------------------------------------------------------
    Item("generic_mouse", "Generic 125Hz optical mouse", "mouse", 2007, 15, aim=0.96, ergonomics=0.3),
    Item("mx518", "Logitech MX518", "mouse", 2007, 50, aim=0.99, ergonomics=0.55, until=2011,
         notes="The mid-2000s classic everyone seemed to own."),
    Item("deathadder", "Razer DeathAdder", "mouse", 2007, 60, aim=1.0, ergonomics=0.6, until=2012,
         notes="Big ergonomic shape; a staple of early osu! mouse players."),
    Item("gaming_mouse", "Logitech G400", "mouse", 2011, 50, aim=1.0, ergonomics=0.6, month=8, until=2013),
    Item("zowie_ec2", "Zowie EC2-A", "mouse", 2014, 70, aim=1.01, ergonomics=0.65, month=3, until=2019),
    Item("g_pro", "Logitech G Pro", "mouse", 2016, 70, aim=1.01, ergonomics=0.65, month=8, until=2020),
    Item("finalmouse_ul", "Finalmouse Ultralight Pro", "mouse", 2018, 60, aim=1.02, ergonomics=0.6, month=4, until=2019,
         notes="67 g honeycomb shell; sold out within minutes of every drop."),
    Item("model_o", "Glorious Model O", "mouse", 2019, 50, aim=1.02, ergonomics=0.65, month=6),
    Item("light_wireless", "Logitech G Pro X Superlight", "mouse", 2020, 150, aim=1.03, ergonomics=0.75, month=12,
         notes="63 g wireless with no compromises."),
    Item("viper_v2", "Razer Viper V2 Pro", "mouse", 2022, 150, aim=1.03, ergonomics=0.75, month=8),
    Item("superlight2", "Logitech G Pro X Superlight 2", "mouse", 2023, 160, aim=1.04, ergonomics=0.78, month=9,
         notes="8 kHz polling."),
    # --- tablets ----------------------------------------------------------------------------
    Item("graphire4", "Wacom Graphire4", "tablet", 2007, 100, aim=0.97, ergonomics=0.6, until=2008),
    Item("wacom_bamboo", "Wacom Bamboo Pen (CTL-460)", "tablet", 2009, 70, aim=0.98, ergonomics=0.6, month=9, until=2013,
         notes="Higher latency, but a pen is easier on the wrist."),
    Item("intuos4", "Wacom Intuos4 S", "tablet", 2009, 230, aim=1.0, ergonomics=0.7, month=4, until=2012,
         notes="Professional tablet, professional price."),
    Item("huion_h420", "Huion H420", "tablet", 2012, 30, aim=0.97, ergonomics=0.55, until=2019,
         notes="Dirt cheap, a little jittery."),
    Item("wacom_ctl480", "Wacom Intuos Pen S (CTL-480)", "tablet", 2013, 80, aim=1.02, ergonomics=0.65, month=9, until=2017,
         notes="The gold standard of osu! tablets."),
    Item("intuos_pro_m", "Wacom Intuos Pro M (PTH-660)", "tablet", 2017, 350, aim=1.02, ergonomics=0.8, month=1,
         notes="Huge area and great build; overkill for most."),
    Item("xp_deco01", "XP-Pen Deco 01", "tablet", 2017, 60, aim=1.0, ergonomics=0.6, month=10),
    Item("ctl472", "One by Wacom S (CTL-472)", "tablet", 2018, 60, aim=1.02, ergonomics=0.65, month=1,
         notes="The CTL-480's spiritual successor: no buttons, low latency."),
    Item("ctl4100", "Wacom Intuos S (CTL-4100)", "tablet", 2018, 80, aim=1.02, ergonomics=0.65, month=1),
    Item("huion_h640p", "Huion Inspiroy H640P", "tablet", 2019, 40, aim=1.01, ergonomics=0.6, month=3),
    # --- drivers ----------------------------------------------------------------------------
    Item("tablet_driver", "Hawku TabletDriver", "software", 2017, 0, aim=1.02, requires="tablet", month=6,
         notes="Low-latency driver with smoothing control."),
    Item("otd", "OpenTabletDriver", "software", 2020, 0, aim=1.025, requires="tablet", month=6,
         notes="Open-source, cross-platform successor."),
    # --- keyboards --------------------------------------------------------------------------
    Item("rubber_dome", "Rubber dome keyboard", "keyboard", 2007, 10, tapping=0.95, ergonomics=0.3),
    Item("g15", "Logitech G15", "keyboard", 2007, 80, tapping=0.97, ergonomics=0.45, until=2010),
    Item("cherry_mx", "Razer BlackWidow (Cherry MX Blue)", "keyboard", 2010, 80, tapping=1.0, ergonomics=0.55, month=9,
         until=2014),
    Item("filco", "Filco Majestouch-2 (Cherry MX)", "keyboard", 2011, 130, tapping=1.0, ergonomics=0.65),
    Item("k70", "Corsair K70 (Cherry MX Red)", "keyboard", 2013, 130, tapping=1.01, ergonomics=0.6, month=5),
    Item("osu_keypad", "2-key osu! keypad", "keyboard", 2016, 40, tapping=1.02, ergonomics=0.65,
         notes="Two keys and nothing else; comfortable for long streams."),
    Item("wooting_one", "Wooting One (analog optical)", "keyboard", 2017, 160, tapping=1.02, ergonomics=0.65, month=11,
         notes="Adjustable actuation point."),
    Item("wooting_60he", "Wooting 60HE (Hall effect, rapid trigger)", "keyboard", 2022, 175, tapping=1.05,
         ergonomics=0.7, month=2, notes="Rapid trigger: bursts and fast streams get noticeably easier."),
    Item("apex_pro_mini", "SteelSeries Apex Pro Mini", "keyboard", 2022, 180, tapping=1.04, ergonomics=0.68, month=6,
         notes="Adjustable actuation; rapid trigger came in a later update."),
    Item("wooting_80he", "Wooting 80HE", "keyboard", 2024, 200, tapping=1.06, ergonomics=0.72, month=5),
    # --- monitors ---------------------------------------------------------------------------
    Item("lcd_60", "60Hz LCD", "monitor", 2007, 150, ar_cap=60),
    Item("crt", "Secondhand CRT monitor (85-100Hz)", "monitor", 2007, 40, ar_cap=85, until=2010,
         notes="Zero input lag and smooth motion, if your desk can take the weight."),
    Item("hz_120", "Samsung 2233RZ (120Hz)", "monitor", 2009, 400, ar_cap=80, month=4, until=2012),
    Item("xl2411t", "BenQ XL2411T (144Hz)", "monitor", 2012, 330, ar_cap=95, month=10, until=2016),
    Item("hz_144", "Asus VG248QE (144Hz)", "monitor", 2013, 280, ar_cap=95, month=6,
         notes="A massive boost for reading high AR."),
    Item("hz_240", "BenQ Zowie XL2540 (240Hz)", "monitor", 2017, 500, ar_cap=108, month=3),
    Item("vg259qm", "Asus TUF VG259QM (280Hz)", "monitor", 2020, 330, ar_cap=110, month=6),
    Item("hz_360", "Asus ROG Swift PG259QN (360Hz)", "monitor", 2020, 700, ar_cap=115, month=9),
    Item("xl2566k", "BenQ Zowie XL2566K (360Hz)", "monitor", 2022, 600, ar_cap=116, month=11),
    Item("pg248qp", "Asus ROG Swift Pro PG248QP (540Hz)", "monitor", 2024, 900, ar_cap=120, month=3),
    # --- chair & desk -----------------------------------------------------------------------
    Item("basic_chair", "Kitchen chair", "chair", 2007, 0, ergonomics=0.2),
    Item("office_chair", "Cheap office chair", "chair", 2007, 80, ergonomics=0.5),
    Item("ergo_chair", "Ergonomic chair and desk setup", "chair", 2007, 250, ergonomics=0.85),
    Item("secretlab", "Secretlab Titan", "chair", 2018, 400, ergonomics=0.82, month=3),
    Item("aeron", "Herman Miller Aeron", "chair", 2007, 900, ergonomics=0.95, notes="Absurdly expensive, absurdly comfortable."),
]}

STARTER_KIT = ("generic_mouse", "rubber_dome", "lcd_60", "basic_chair")
INPUT_CATEGORIES = ("mouse", "tablet")


@dataclass
class Effects:
    aim: float = 1.0
    tapping: float = 1.0
    ar_cap: float | None = None
    ergonomics: float = 0.3
    missing: list[str] = field(default_factory=list)


def effects(equipped: list[Item], input_device: str) -> Effects:
    """Combined effect of the equipped items for the player's chosen input device."""
    by_cat = {i.category: i for i in equipped}
    out = Effects()
    device = by_cat.get(input_device)
    if device is None:
        out.missing.append(input_device)
        out.aim = 0.85  # playing tablet-style on a borrowed mouse, or vice versa
    else:
        out.aim = device.aim
    driver = by_cat.get("software")
    if driver and driver.requires == input_device:
        out.aim *= driver.aim
    keyboard = by_cat.get("keyboard")
    out.tapping = keyboard.tapping if keyboard else 0.95
    monitor = by_cat.get("monitor")
    out.ar_cap = monitor.ar_cap if monitor else 60
    parts = [i.ergonomics for i in (device, keyboard, by_cat.get("chair")) if i and i.ergonomics is not None]
    out.ergonomics = sum(parts) / len(parts) if parts else 0.3
    return out
