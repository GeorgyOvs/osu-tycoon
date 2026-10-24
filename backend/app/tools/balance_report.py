"""Balance report: three player archetypes over a few in-game years on the real beatmap index.

    python -m app.tools.balance_report --start 2014-01-01 --months 30

Careers are created in the main database (so already-downloaded maps are reused) and deleted
afterwards. Prints a table every six months: overall, rank, pp, money, followers, injuries,
best tournament result and front-page threads.
"""

import argparse
import time
from collections import Counter
from datetime import date

from fastapi.testclient import TestClient

from app.main import app

SEEDS = {"casual": 101, "grinder": 202, "pro": 303}  # fixed: hash() changes between runs
ARCHETYPES = {
    "casual": {
        "age": 15, "occupation": "school",
        "week": [("train", "tech_maps", 2), ("train", "high_ar_edits", 2), ("train", "stream_practice", 2),
                 ("train", "watch_replays", 1), ("rest", None, 0), ("session", "farm", 3), ("rest", None, 0)],
    },
    "grinder": {
        "age": 16, "occupation": "school",
        "week": [("train", "ranked_pack_grind", 4), ("train", "stream_practice", 5), ("train", "high_ar_edits", 5),
                 ("train", "tech_maps", 4), ("train", "hidden_grind", 4), ("session", "push", 6), ("rest", None, 0)],
    },
    "pro": {
        "age": 19, "occupation": "pro",
        "week": [("train", "ranked_pack_grind", 6), ("train", "deathstream_240", 4), ("train", "high_ar_edits", 6),
                 ("session", "farm", 6), ("train", "watch_replays", 3), ("session", "push", 6), ("rest", None, 0)],
    },
}


def run(client: TestClient, name: str, start: date, months: int) -> list[dict]:
    spec = ARCHETYPES[name]
    pid = client.post("/api/players", json={"name": f"bal_{name}", "country": "DE", "start_date": start.isoformat(),
                                             "seed": SEEDS[name], "age": spec["age"],
                                             "occupation": spec["occupation"]}).json()["id"]
    end_year, end_month = start.year + (start.month - 1 + months) // 12, (start.month - 1 + months) % 12 + 1
    end = date(end_year, end_month, 1)
    rows, injuries, refusals = [], Counter(), Counter()
    next_report, step = start, 0
    try:
        while True:
            profile = client.get(f"/api/players/{pid}").json()
            today = date.fromisoformat(profile["in_game_date"])
            if today >= next_report:
                rows.append(snapshot(client, pid, profile, injuries))
                next_report = date(today.year + (today.month > 6), 1 if today.month > 6 else 7, 1)
            if today >= end:
                break
            listing = client.get(f"/api/players/{pid}/tournaments").json()
            if listing["pending_match"] and listing["pending_match"]["due"] <= listing["date"]:
                m = listing["pending_match"]
                resp = client.post(f"/api/players/{pid}/tournaments/{listing['pending_tournament_id']}/matches/{m['id']}/play")
                if resp.status_code != 200:  # the calendar can't move past an unplayable match
                    refusals[f"match failed: {resp.status_code} {resp.text[:60]}"] += 1
                    rows.append(snapshot(client, pid, client.get(f"/api/players/{pid}").json(), injuries))
                    break
                continue
            for t in listing["tournaments"]:
                if t["can_register"] and name != "casual":
                    client.post(f"/api/players/{pid}/tournaments/{t['id']}/register")
            kind, what, hours = spec["week"][step % len(spec["week"])]
            step += 1
            if kind == "train":
                resp = client.post(f"/api/players/{pid}/train", json={"drill": what, "hours_per_day": hours, "days": 1})
            elif kind == "session":
                resp = client.post(f"/api/players/{pid}/sessions/auto",
                                   json={"preset": what, "hours": hours, "stream": name == "pro"})
            else:
                resp = client.post(f"/api/players/{pid}/rest", json={"days": 1, "physio": profile["injury"]["state"] != "healthy"})
            if resp.status_code != 200:
                refusals[resp.json().get("detail", "?")[:40]] += 1
                if resp.status_code in (409, 422):  # hiatus, free time, physio money: just rest
                    client.post(f"/api/players/{pid}/rest", json={"days": 1})
            else:
                for e in resp.json().get("events", []):
                    if e["type"].startswith("INJURY") or e["type"] == "PERMANENT_DAMAGE":
                        injuries[e["type"]] += 1
    finally:
        client.delete(f"/api/players/{pid}")
    if refusals:
        rows[-1]["refusals"] = dict(refusals.most_common(3))
    return rows


def snapshot(client: TestClient, pid: int, profile: dict, injuries: Counter) -> dict:
    listing = client.get(f"/api/players/{pid}/tournaments").json()
    places = [t["user_placement"] for t in listing["tournaments"] if t.get("user_placement")]
    threads = client.get(f"/api/players/{pid}/forum", params={"limit": 100}).json()
    return {
        "date": profile["in_game_date"], "overall": round(profile["overall"], 1),
        "rank": profile["global_rank"], "pp": round(profile["total_pp"]), "money": round(profile["life"]["money"]),
        "followers": profile["life"]["followers"], "injuries": sum(injuries.values()),
        "best_place": min(places, default="-"), "threads": len(threads),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2014-01-01")
    parser.add_argument("--months", type=int, default=30)
    parser.add_argument("--only", choices=list(ARCHETYPES), default=None)
    args = parser.parse_args()
    client = TestClient(app, raise_server_exceptions=False)  # in-process; server errors become 500s we count
    for name in [args.only] if args.only else ARCHETYPES:
        t0 = time.time()
        rows = run(client, name, date.fromisoformat(args.start), args.months)
        print(f"\n== {name} ({time.time() - t0:.0f}s)")
        print(f"{'date':12}{'OVR':>6}{'rank':>10}{'pp':>7}{'money':>8}{'follow':>8}{'injur':>6}  best   threads")
        for r in rows:
            rank = f"#{r['rank']:,}" if r["rank"] else "-"
            print(f"{r['date']:12}{r['overall']:>6}{rank:>10}{r['pp']:>7}{r['money']:>8}{r['followers']:>8}"
                  f"{r['injuries']:>6}  {r['best_place']:6} {r['threads']}")
        if rows and rows[-1].get("refusals"):
            print("refusals:", rows[-1]["refusals"])


if __name__ == "__main__":
    main()
