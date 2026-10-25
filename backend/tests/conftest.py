import math
import os
import tempfile
from datetime import date
from pathlib import Path

# Point the app at a throwaway data dir before any app module is imported.
_TMP = Path(tempfile.mkdtemp(prefix="tycoon-test-"))
os.environ["TYCOON_DATA_DIR"] = str(_TMP)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import OSU_CACHE_DIR  # noqa: E402
from app.db import Base, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import beatmap_index, mirror  # noqa: E402

FIXTURE_BEATMAP_ID = 1001
FIXTURE_SET_ID = 501


def make_osu_file(beatmap_id: int, set_id: int, n_circles: int = 200, title: str = "Test Song",
                  spacing: float | None = None, gap_ms: int = 167) -> str:
    """A jump map: circles alternating across the playfield (180 BPM 1/2 by default).

    `spacing` (px) puts the two positions closer together for easier maps."""
    header = f"""osu file format v14

[General]
AudioFilename: audio.mp3
Mode: 0

[Metadata]
Title:{title}
Artist:Test Artist
Creator:tester
Version:Insane
BeatmapID:{beatmap_id}
BeatmapSetID:{set_id}

[Difficulty]
HPDrainRate:5
CircleSize:4
OverallDifficulty:8
ApproachRate:9
SliderMultiplier:1.4
SliderTickRate:1

[TimingPoints]
0,333.333333333333,4,2,0,60,1,0

[HitObjects]
"""
    objects = []
    for i in range(n_circles):
        if spacing is None:
            x, y = (64, 96) if i % 2 == 0 else (448, 288)
        else:
            x, y = (round(256 - spacing / 2), 192) if i % 2 == 0 else (round(256 + spacing / 2), 192)
        objects.append(f"{x},{y},{1000 + i * gap_ms},{5 if i == 0 else 1},0,0:0:0:0:")
    return header + "\n".join(objects) + "\n"


STREAM_BEATMAP_ID = 1003


def make_stream_osu(beatmap_id: int, set_id: int, bpm: float = 240, stream_len: int = 32, n_streams: int = 8,
                    hp: float = 6) -> str:
    """Long 1/4 streams separated by one-beat gaps: a tapping/stamina check."""
    beat = 60000 / bpm
    header = f"""osu file format v14

[General]
Mode: 0

[Metadata]
Title:Stream Test
Artist:Test Artist
Creator:tester
Version:Streams {bpm:g}
BeatmapID:{beatmap_id}
BeatmapSetID:{set_id}

[Difficulty]
HPDrainRate:{hp:g}
CircleSize:4
OverallDifficulty:8
ApproachRate:9
SliderMultiplier:1.4
SliderTickRate:1

[TimingPoints]
0,{beat},4,2,0,60,1,0

[HitObjects]
"""
    objects, t = [], 1000.0
    for s in range(n_streams):
        for k in range(stream_len):
            x = 200 + 40 * math.cos(k / 3)
            y = 190 + 40 * math.sin(k / 3)
            objects.append(f"{x:.0f},{y:.0f},{t:.0f},{5 if k == 0 else 1},0,0:0:0:0:")
            t += beat / 4
        t += beat
    return header + "\n".join(objects) + "\n"


def make_set(
    set_id: int,
    ranked: date,
    beatmap_ids: list[int],
    status: str = "ranked",
    stars: list[float] | None = None,
    title: str = "Song",
    plays: int = 100,
) -> mirror.BeatmapSetData:
    stars = stars or [3.0 + i for i in range(len(beatmap_ids))]
    return mirror.BeatmapSetData(
        id=set_id, artist="Artist", title=title, creator="mapper", source="", tags="tag",
        status=status, ranked_date=ranked, play_count=plays, favourite_count=1, bpm=180,
        beatmaps=[
            mirror.BeatmapData(
                id=bid, version=f"Diff {i}", stars=st, ar=9, cs=4, od=8, hp=5, bpm=180,
                total_length=120, hit_length=110, max_combo=500, count_circles=300,
                count_sliders=100, play_count=10, pass_count=5,
            )
            for i, (bid, st) in enumerate(zip(beatmap_ids, stars))
        ],
    )


class FakeMirror:
    """Stands in for the network: a few known beatmaps, by id."""

    def __init__(self):
        fixture_set = make_set(FIXTURE_SET_ID, date(2010, 1, 1), [FIXTURE_BEATMAP_ID, FIXTURE_BEATMAP_ID + 1])
        self.sets = {
            FIXTURE_BEATMAP_ID: fixture_set,
            FIXTURE_BEATMAP_ID + 1: fixture_set,
            2001: make_set(901, date(2020, 1, 1), [2001]),
            3001: make_set(902, date(2012, 1, 1), [3001], status="graveyard"),
            STREAM_BEATMAP_ID: make_set(903, date(2010, 1, 1), [STREAM_BEATMAP_ID]),
        }

    def get_set_for_beatmap(self, beatmap_id):
        return self.sets.get(beatmap_id)

    def search_page(self, status, offset):
        return []


class StubSyncer:
    def __init__(self):
        self.requests: list[date] = []

    def request(self, until):
        self.requests.append(until)

    def stop(self):
        pass

    def status(self, db):
        return beatmap_index.SyncStatus(beatmap_index.synced_until(db), None, False, None, 0)


def seed_pool_maps(db, n=40):
    """Indexed maps from very easy to hard (all backed by .osu files), with real star ratings."""
    import rosu_pp_py as rosu

    for i in range(n):
        bid = 5000 + i
        level = i % 20  # 0 = gentle, 19 = brutal
        if i % 3 == 0:
            content = make_stream_osu(bid, 7000 + i, bpm=120 + level * 7, stream_len=8, n_streams=6)
        else:
            content = make_osu_file(bid, 7000 + i, n_circles=150, spacing=30 + level * 20, gap_ms=330 - level * 9)
        # The mirror reports today's (lazer) star rating, ~5% above stable's.
        stars = rosu.Difficulty(lazer=False).calculate(rosu.Beatmap(content=content)).stars * 1.05
        (OSU_CACHE_DIR / f"{bid}.osu").write_text(content, encoding="utf-8")
        data = make_set(7000 + i, date(2010, 1, 1), [bid], stars=[stars])
        object.__setattr__(data.beatmaps[0], "hit_length", 200 if i % 7 == 0 else 120)
        object.__setattr__(data.beatmaps[0], "ar", 8 if i % 4 == 0 else 9)
        beatmap_index.upsert_set(db, data)
    db.commit()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    fake, stub = FakeMirror(), StubSyncer()
    monkeypatch.setattr(beatmap_index, "default_client", lambda: fake)
    monkeypatch.setattr(beatmap_index, "syncer", stub)
    from app.services import map_prefetch

    monkeypatch.setattr(map_prefetch, "prefetcher", type("NoPrefetch", (), {"request": lambda self, ids: 0})())
    yield stub


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    init_db()
    OSU_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (OSU_CACHE_DIR / f"{FIXTURE_BEATMAP_ID}.osu").write_text(
        make_osu_file(FIXTURE_BEATMAP_ID, FIXTURE_SET_ID), encoding="utf-8"
    )
    (OSU_CACHE_DIR / f"{FIXTURE_BEATMAP_ID + 1}.osu").write_text(
        make_osu_file(FIXTURE_BEATMAP_ID + 1, FIXTURE_SET_ID, n_circles=400, title="Longer Song"),
        encoding="utf-8",
    )
    (OSU_CACHE_DIR / f"{STREAM_BEATMAP_ID}.osu").write_text(
        make_stream_osu(STREAM_BEATMAP_ID, 903), encoding="utf-8"
    )
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
