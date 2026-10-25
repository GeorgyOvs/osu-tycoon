import struct
from datetime import datetime, timezone

from tests.conftest import FIXTURE_BEATMAP_ID, FIXTURE_SET_ID, make_osu_file

from app.services import stable_files

MD5_MAP = "a" * 32
FOLDER, FILE = f"{FIXTURE_SET_ID} Test", "Test Song [Normal].osu"


def s(text: str) -> bytes:
    if not text:
        return b"\x00"
    raw = text.encode()
    return b"\x0b" + bytes([len(raw)]) + raw  # fixtures stay under 128 bytes


def ticks(dt: datetime) -> int:
    return int((dt - datetime(1, 1, 1, tzinfo=timezone.utc)).total_seconds() * 10_000_000)


def score_bytes(replay_md5, when, n300=190, n100=8, n50=1, miss=1, mods=0, mode=0):
    return (struct.pack("<Bi", mode, 20260711) + s(MD5_MAP) + s("Me") + s(replay_md5)
            + struct.pack("<6h", n300, n100, n50, 0, 0, miss) + struct.pack("<iH?i", 123456, 150, False, mods)
            + s("") + struct.pack("<qiq", ticks(when), -1, 0))


def scores_db(*scores: bytes) -> bytes:
    return (struct.pack("<ii", 20260711, 1) + s(MD5_MAP) + struct.pack("<i", len(scores)) + b"".join(scores))


def osu_db() -> bytes:
    entry = (s("Artist") + s("") + s("Test Song") + s("") + s("mapper") + s("Normal") + s("a.mp3")
             + s(MD5_MAP) + s(FILE) + b"\x04" + struct.pack("<3hq4fd", 200, 0, 0, 0, 5, 5, 5, 5, 1.4)
             + struct.pack("<4i", 0, 0, 0, 0) + struct.pack("<3i", 1, 2, 3) + struct.pack("<i", 0)
             + struct.pack("<ii", FIXTURE_BEATMAP_ID, FIXTURE_SET_ID) + struct.pack("<ibbbb", 0, 9, 9, 9, 9)
             + struct.pack("<hfB", 0, 0.7, 0) + s("") + s("") + struct.pack("<h", 0) + s("")
             + struct.pack("<?q?", False, 0, False) + s(FOLDER) + struct.pack("<q?????", 0, 0, 0, 0, 0, 0)[:13]
             + struct.pack("<iB", 0, 0))
    return struct.pack("<ii?q", 20260924, 1, True, 0) + s("Me") + struct.pack("<i", 1) + entry + struct.pack("<i", 1)


def install(tmp_path, *scores):
    (tmp_path / "scores.db").write_bytes(scores_db(*scores))
    (tmp_path / "osu!.db").write_bytes(osu_db())
    song = tmp_path / "Songs" / FOLDER
    song.mkdir(parents=True)
    (song / FILE).write_text(make_osu_file(FIXTURE_BEATMAP_ID, FIXTURE_SET_ID), encoding="utf-8")


def test_mods_and_accuracy():
    assert stable_files.mods_from_bits(8 | 64 | 512) == "HDNC"
    assert stable_files.mods_from_bits(1 | 32 | 16384) == "NFPF"
    assert stable_files.accuracy_std(10, 0, 0, 0) == 100.0
    assert round(stable_files.accuracy_std(8, 1, 0, 1), 2) == 83.33


def test_parsers_roundtrip(tmp_path):
    when = datetime(2026, 9, 13, 9, 0, tzinfo=timezone.utc)
    install(tmp_path, score_bytes("r1" * 16, when, mods=8 | 64), score_bytes("r2" * 16, when, mode=1))
    scores = stable_files.load_scores(tmp_path)
    assert [x.mods for x in scores] == ["HDDT"]  # non-standard modes are skipped
    assert scores[0].played_at == when and scores[0].max_combo == 150
    maps = stable_files.load_beatmaps(tmp_path)
    assert maps[MD5_MAP].beatmap_id == FIXTURE_BEATMAP_ID and maps[MD5_MAP].folder == FOLDER


def test_sync_baseline_then_new(client, tmp_path, monkeypatch):
    when = datetime(2026, 9, 13, 9, 0, tzinfo=timezone.utc)
    install(tmp_path, score_bytes("r1" * 16, when))
    monkeypatch.setenv("OSU_STABLE_DIR", str(tmp_path))
    pid = client.post("/api/players", json={"name": "Me", "country": "RU", "start_date": "2016-10-17",
                                             "seed": 1, "age": 17}).json()["id"]

    first = client.post(f"/api/players/{pid}/real/sync").json()
    assert first["baseline"] and first["imported"] == 1
    assert first["plays"][0]["pp"] > 0 and first["plays"][0]["stars"] > 0

    assert client.post(f"/api/players/{pid}/real/sync").json()["imported"] == 0

    install_later = datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc)
    (tmp_path / "scores.db").write_bytes(scores_db(score_bytes("r1" * 16, when),
                                                   score_bytes("r2" * 16, install_later, miss=0)))
    second = client.post(f"/api/players/{pid}/real/sync").json()
    assert not second["baseline"] and second["imported"] == 1
    assert [p["baseline"] for p in client.get(f"/api/players/{pid}/real").json()] == [False, True]


def test_sync_without_install(client, tmp_path, monkeypatch):
    monkeypatch.setenv("OSU_STABLE_DIR", str(tmp_path / "nope"))
    pid = client.post("/api/players", json={"name": "Me", "country": "RU", "start_date": "2016-10-17",
                                             "seed": 1, "age": 17}).json()["id"]
    assert client.post(f"/api/players/{pid}/real/sync").status_code == 422
