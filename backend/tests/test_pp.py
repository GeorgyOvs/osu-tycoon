import pytest

from app.services import pp
from tests.conftest import make_osu_file


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", ""),
        ("NM", ""),
        ("hd,dt", "HDDT"),
        ("DT HD", "HDDT"),
        ("HDNC", "HDNC"),
        ("DTNC", "NC"),
        ("PFSD", "PF"),
        ("hrhdfl", "HDHRFL"),
    ],
)
def test_normalize_mods(raw, expected):
    assert pp.normalize_mods(raw) == expected


@pytest.mark.parametrize("raw", ["XX", "HDD", "EZHR", "DTHT", "NFSD"])
def test_normalize_mods_rejects_invalid(raw):
    with pytest.raises(pp.InvalidMods):
        pp.normalize_mods(raw)


@pytest.fixture(scope="module")
def osu_file() -> bytes:
    return make_osu_file(1, 1).encode()


def test_calculate_basic(osu_file):
    r = pp.calculate(osu_file, accuracy=100)
    assert r.pp > 0
    assert r.stars > 0
    assert r.max_combo == 200
    assert r.ar == pytest.approx(9)


def test_mods_change_difficulty(osu_file):
    nm = pp.calculate(osu_file, accuracy=100)
    dt = pp.calculate(osu_file, "DT", accuracy=100)
    hr = pp.calculate(osu_file, "HR", accuracy=100)
    assert dt.stars > nm.stars and dt.pp > nm.pp
    assert dt.bpm == pytest.approx(nm.bpm * 1.5)
    assert hr.cs > nm.cs


def test_misses_and_accuracy_reduce_pp(osu_file):
    fc = pp.calculate(osu_file, accuracy=100)
    assert pp.calculate(osu_file, accuracy=95).pp < fc.pp
    assert pp.calculate(osu_file, accuracy=100, misses=5).pp < fc.pp


def test_invalid_beatmap():
    with pytest.raises(pp.InvalidBeatmap):
        pp.calculate(b"not a beatmap")
