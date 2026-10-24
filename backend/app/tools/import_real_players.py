"""Import real top players from the osu! API v2 into app/data/real_players.json.

Usage (credentials from https://osu.ppy.sh/home/account/edit -> OAuth -> New OAuth Application):

    set OSU_CLIENT_ID=12345
    set OSU_CLIENT_SECRET=...
    python -m app.tools.import_real_players --count 1000

What we get per player: username and previous usernames, country, join date, current global
rank and pp, and the highest rank with its date. osu! only started recording highest ranks a few
years ago, so careers that peaked earlier get an approximate peak. Careers in the game are built
from these anchors (join -> peak -> now); nothing else about the person is invented.
Requests are throttled to stay well inside the API's rate limits.
"""

import argparse
import json
import os
import time
from pathlib import Path

import httpx

API = "https://osu.ppy.sh/api/v2"
TOKEN_URL = "https://osu.ppy.sh/oauth/token"
OUT = Path(__file__).resolve().parent.parent / "data" / "real_players.json"
REQUEST_DELAY = 1.1  # seconds; ~55 requests/minute


def token(client: httpx.Client, client_id: str, secret: str) -> str:
    resp = client.post(TOKEN_URL, data={"client_id": client_id, "client_secret": secret,
                                        "grant_type": "client_credentials", "scope": "public"})
    resp.raise_for_status()
    return resp.json()["access_token"]


def top_user_ids(client: httpx.Client, count: int) -> list[int]:
    ids: list[int] = []
    page = 1
    while len(ids) < count:
        resp = client.get(f"{API}/rankings/osu/performance", params={"cursor[page]": page})
        resp.raise_for_status()
        rows = resp.json().get("ranking", [])
        if not rows:
            break
        ids += [r["user"]["id"] for r in rows]
        page += 1
        time.sleep(REQUEST_DELAY)
    return ids[:count]


def player_record(user: dict) -> dict:
    stats = user.get("statistics") or {}
    highest = user.get("rank_highest") or {}
    return {
        "id": user["id"],
        "name": user["username"],
        "previous_names": user.get("previous_usernames") or [],
        "country": (user.get("country_code") or "XX")[:2],
        "join_date": (user.get("join_date") or "")[:10],
        "current_rank": stats.get("global_rank"),
        "current_pp": stats.get("pp"),
        "highest_rank": highest.get("rank"),
        "highest_rank_date": (highest.get("updated_at") or "")[:10] or None,
    }


def fetch(client: httpx.Client, ids: list[int], progress=print) -> list[dict]:
    out = []
    for i, user_id in enumerate(ids, start=1):
        resp = client.get(f"{API}/users/{user_id}/osu", params={"key": "id"})
        if resp.status_code == 200:
            out.append(player_record(resp.json()))
        if i % 50 == 0:
            progress(f"  {i}/{len(ids)}")
        time.sleep(REQUEST_DELAY)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=1000)
    args = parser.parse_args()
    client_id, secret = os.getenv("OSU_CLIENT_ID"), os.getenv("OSU_CLIENT_SECRET")
    if not client_id or not secret:
        raise SystemExit("Set OSU_CLIENT_ID and OSU_CLIENT_SECRET first (see the module docstring).")
    with httpx.Client(timeout=30, headers={"User-Agent": "osu-tycoon/0.1 (local game engine)"}) as client:
        client.headers["Authorization"] = f"Bearer {token(client, client_id, secret)}"
        print(f"Fetching the top {args.count} players...")
        ids = top_user_ids(client, args.count)
        players = fetch(client, ids)
    payload = {"fetched": time.strftime("%Y-%m-%d"), "source": "osu! API v2", "players": players}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Saved {len(players)} players to {OUT}")


if __name__ == "__main__":
    main()
