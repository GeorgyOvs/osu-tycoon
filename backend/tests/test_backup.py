import io
import json
import zipfile

from app.services import backup


def _player(client, name):
    return client.post("/api/players", json={"name": name, "country": "RU", "start_date": "2016-10-17",
                                             "seed": 1, "age": 17}).json()["id"]


def _names(client):
    return sorted(p["name"] for p in client.get("/api/players").json())


def _manifest(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return json.loads(z.read("manifest.json"))


def test_export_everything_or_one_career(client):
    a, b = _player(client, "Alpha"), _player(client, "Beta")
    everything = client.get("/api/backup/export")
    assert everything.status_code == 200 and everything.headers["content-type"] == "application/zip"
    assert "osu-tycoon-all-" in everything.headers["content-disposition"]
    assert [c["name"] for c in _manifest(everything.content)["careers"]] == ["Alpha", "Beta"]

    one = client.get(f"/api/backup/export?player_id={b}")
    manifest = _manifest(one.content)
    assert [c["id"] for c in manifest["careers"]] == [b] and manifest["schema_version"] > 0
    assert _names(client) == ["Alpha", "Beta"]  # exporting one career leaves the live database alone
    assert client.get("/api/backup/export?player_id=999").status_code == 404
    assert a


def test_import_replaces_the_database_and_keeps_the_old_one(client):
    beta = _player(client, "Beta")
    assert client.post(f"/api/players/{beta}/rest", json={"days": 2}).status_code == 200
    before = client.get(f"/api/players/{beta}").json()
    exported = client.get(f"/api/backup/export?player_id={beta}").content

    client.delete(f"/api/players/{beta}")
    _player(client, "Gamma")
    assert _names(client) == ["Gamma"]

    preview = client.post("/api/backup/inspect", content=exported).json()
    assert [c["name"] for c in preview["careers"]] == ["Beta"]

    result = client.post("/api/backup/import", content=exported).json()
    assert [c["name"] for c in result["careers"]] == ["Beta"]
    assert _names(client) == ["Beta"]
    after = client.get(f"/api/players/{beta}").json()
    assert after["in_game_date"] == before["in_game_date"] and after["name"] == "Beta"
    assert (backup.backups_dir() / result["backup"]).exists()

    # The kept database brings Gamma back.
    restore = io.BytesIO()
    with zipfile.ZipFile(restore, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": backup.FORMAT, "version": 1, "schema_version": 1}))
        z.write(backup.backups_dir() / result["backup"], "tycoon.db")
    client.post("/api/backup/import", content=restore.getvalue())
    assert _names(client) == ["Gamma"]


def test_bad_files_change_nothing(client):
    _player(client, "Alpha")
    assert client.post("/api/backup/import", content=b"not a zip").status_code == 422

    newer = io.BytesIO()
    with zipfile.ZipFile(newer, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": backup.FORMAT, "version": 1, "schema_version": 999}))
        z.writestr("tycoon.db", b"")
    response = client.post("/api/backup/import", content=newer.getvalue())
    assert response.status_code == 422 and "newer version" in response.json()["detail"]

    broken = io.BytesIO()
    with zipfile.ZipFile(broken, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": backup.FORMAT, "version": 1, "schema_version": 1}))
        z.writestr("tycoon.db", b"SQLite format 3\x00" + b"\x00" * 200)
    assert client.post("/api/backup/import", content=broken.getvalue()).status_code == 422
    assert _names(client) == ["Alpha"]
