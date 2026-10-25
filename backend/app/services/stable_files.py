"""Read-only access to a local osu!stable install: `scores.db` and `osu!.db`.

Nothing here talks to the client or any server; it only parses the files the client already writes.
Formats: https://osu.ppy.sh/wiki/en/Client/File_formats/Osu_%28file_format%29 (db sections).
"""
import os
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.pp import MOD_ORDER

# osu!stable mod bits -> our mod codes (only the ones the engine knows).
_MOD_BITS = {1: "NF", 2: "EZ", 4: "TD", 8: "HD", 16: "HR", 32: "SD", 64: "DT", 128: "RX", 256: "HT",
             512: "NC", 1024: "FL", 2048: "AP", 4096: "SO", 8192: "AP", 16384: "PF"}
_TICKS_EPOCH = datetime(1, 1, 1, tzinfo=timezone.utc)


class StableFileError(ValueError):
    pass


def default_install_dir() -> Path:
    env = os.getenv("OSU_STABLE_DIR")
    if env:
        return Path(env)
    return Path(os.getenv("LOCALAPPDATA", "~")).expanduser() / "osu!"


def mods_from_bits(bits: int) -> str:
    found = {code for bit, code in _MOD_BITS.items() if bits & bit}
    if "NC" in found:
        found.discard("DT")
    if "PF" in found:
        found.discard("SD")
    return "".join(m for m in MOD_ORDER if m in found)


def accuracy_std(n300: int, n100: int, n50: int, nmiss: int) -> float:
    total = n300 + n100 + n50 + nmiss
    return 100.0 * (300 * n300 + 100 * n100 + 50 * n50) / (300 * total) if total else 0.0


class _Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def take(self, fmt: str):
        size = struct.calcsize(fmt)
        if self.pos + size > len(self.data):
            raise StableFileError("unexpected end of file")
        value = struct.unpack_from("<" + fmt, self.data, self.pos)[0]
        self.pos += size
        return value

    def skip(self, n: int) -> None:
        if self.pos + n > len(self.data):
            raise StableFileError("unexpected end of file")
        self.pos += n

    def string(self) -> str:
        marker = self.take("B")
        if marker == 0:
            return ""
        if marker != 0x0B:
            raise StableFileError(f"bad string marker {marker:#x} at {self.pos - 1}")
        length = shift = 0
        while True:
            byte = self.take("B")
            length |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
        start = self.pos
        self.skip(length)
        return self.data[start:self.pos].decode("utf-8", errors="replace")


@dataclass(frozen=True)
class StableScore:
    beatmap_md5: str
    replay_md5: str
    player: str
    mods: str
    n300: int
    n100: int
    n50: int
    nmiss: int
    score: int
    max_combo: int
    played_at: datetime
    online_id: int

    @property
    def accuracy(self) -> float:
        return accuracy_std(self.n300, self.n100, self.n50, self.nmiss)


def parse_scores_db(data: bytes) -> list[StableScore]:
    """All osu!standard scores stored locally (passes and fails are both kept by the client only if passed)."""
    r = _Reader(data)
    r.take("i")  # version
    result: list[StableScore] = []
    for _ in range(r.take("i")):
        r.string()  # beatmap md5, repeated per score below
        for _ in range(r.take("i")):
            mode = r.take("B")
            version = r.take("i")
            md5, player, replay_md5 = r.string(), r.string(), r.string()
            n300, n100, n50, _geki, _katu, nmiss = (r.take("h") & 0xFFFF for _ in range(6))
            score, combo, _perfect, mod_bits = r.take("i"), r.take("H"), r.take("?"), r.take("i")
            r.string()  # unused
            ticks = r.take("q")
            r.take("i")  # always -1
            online_id = r.take("q")
            if mod_bits & 0x800000:  # Target Practice stores an extra double
                r.skip(8)
            if mode != 0:
                continue
            played = _TICKS_EPOCH + timedelta(microseconds=ticks // 10)
            result.append(StableScore(md5, replay_md5, player, mods_from_bits(mod_bits), n300, n100, n50,
                                      nmiss, score, combo, played, online_id))
            del version
    return result


@dataclass(frozen=True)
class StableBeatmap:
    md5: str
    beatmap_id: int
    beatmapset_id: int
    folder: str
    file: str
    artist: str
    title: str
    version: str


def parse_osu_db(data: bytes) -> dict[str, StableBeatmap]:
    """md5 -> beatmap for every map the client has indexed (only what the bridge needs)."""
    r = _Reader(data)
    db_version = r.take("i")
    if db_version < 20191106:
        raise StableFileError(f"osu!.db version {db_version} is too old to read")
    r.skip(4 + 1 + 8)  # folder count, account unlocked, unlock date
    r.string()  # player name
    maps: dict[str, StableBeatmap] = {}
    for _ in range(r.take("i")):
        artist, _artist_u, title, _title_u = r.string(), r.string(), r.string(), r.string()
        r.string()  # creator
        version = r.string()
        r.string()  # audio file
        md5, file = r.string(), r.string()
        r.skip(1 + 2 * 3 + 8 + 4 * 4 + 8)  # status, object counts, modified, AR/CS/HP/OD, slider velocity
        for _ in range(4):  # star ratings per mode: (0x08 int, 0x0c float) pairs
            r.skip(r.take("i") * (1 + 4 + 1 + 4))
        r.skip(4 * 3)  # drain, total, preview time
        r.skip(r.take("i") * 17)  # timing points
        beatmap_id, set_id = r.take("i"), r.take("i")
        r.skip(4 + 4 + 2 + 4 + 1)  # thread id, grades, local offset, stack leniency, mode
        r.string(), r.string()  # source, tags
        r.skip(2)  # online offset
        r.string()  # title font
        r.skip(1 + 8 + 1)  # unplayed, last played, osz2
        folder = r.string()
        r.skip(8 + 5 + 4 + 1)  # last checked, ignore/disable flags, last modification, mania scroll
        maps[md5] = StableBeatmap(md5, beatmap_id, set_id, folder, file, artist, title, version)
    return maps


def load_scores(install: Path | None = None) -> list[StableScore]:
    path = (install or default_install_dir()) / "scores.db"
    if not path.is_file():
        raise StableFileError(f"scores.db not found in {path.parent}; set OSU_STABLE_DIR")
    return parse_scores_db(path.read_bytes())


def load_beatmaps(install: Path | None = None) -> dict[str, StableBeatmap]:
    path = (install or default_install_dir()) / "osu!.db"
    if not path.is_file():
        raise StableFileError(f"osu!.db not found in {path.parent}; set OSU_STABLE_DIR")
    return parse_osu_db(path.read_bytes())
