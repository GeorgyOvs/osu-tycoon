"""Measure how much pp a player of a given skill earns by playing, against the NPC pp curve.

Run it on a COPY of your database (it creates careers there):

    sqlite3 data/tycoon.db ".backup /tmp/cal/tycoon.db" && ln -s $PWD/data/osu_files /tmp/cal/osu_files
    CAL_DIR=/tmp/cal python -m app.tools.calibrate_skill --levels 50,60,70,80,90 --days 150 --start 2012-10-05

For every level all sub-stats are pinned to that value (and reset daily), then 'push'/'farm' sessions are played for
`--days` days. The report compares the resulting weighted pp with world.pp_for_overall of the same skills. A ratio above 1
means the player earns more than an NPC with the same numbers. world.SKILL_OFFSET was fitted from such runs
(ratios 1.2-1.4 at levels 50-70; higher levels are limited by how many hard maps are cached locally).
"""

import argparse
import os
import sys
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--levels", default="50,60,70,80")
    parser.add_argument("--days", type=int, default=150)
    parser.add_argument("--start", default="2012-10-05")
    args = parser.parse_args()
    if "CAL_DIR" not in os.environ:
        sys.exit("set CAL_DIR to a directory holding a COPY of tycoon.db (and a link to osu_files)")
    os.environ["TYCOON_DATA_DIR"] = os.environ["CAL_DIR"]

    from fastapi.testclient import TestClient

    from app.db import SessionLocal
    from app.engine import attributes as A
    from app.engine import simulation, world
    from app.main import app
    from app.models import Player
    from app.services import beatmap_index

    class _NoSync:
        def request(self, until): ...
        def stop(self): ...

    beatmap_index.syncer = _NoSync()
    with TestClient(app) as client:
        for level in (float(x) for x in args.levels.split(",")):
            pid = client.post("/api/players", json=dict(name=f"Cal{int(level)}", country="DE", start_date=args.start,
                                                        seed=int(level) * 7 + 1, age=21)).json()["id"]

            def reset() -> None:
                with SessionLocal() as db:
                    p = db.get(Player, pid)
                    for a in p.attributes:
                        a.base, a.cap, a.rust, a.plateau = level, 115.0, 0.0, 0.0
                    p.fatigue, p.motivation, p.form, p.injury = 10.0, 80.0, 0.0, "healthy"
                    db.commit()

            reset()
            started = time.time()
            for day in range(args.days):
                r = client.post(f"/api/players/{pid}/sessions/auto", json={"preset": "push" if day % 2 == 0 else "farm", "hours": 3})
                if r.status_code != 200:
                    client.post(f"/api/players/{pid}/rest", json={"days": 1, "physio": False})
                reset()
            profile = client.get(f"/api/players/{pid}").json()
            with SessionLocal() as db:
                p = db.get(Player, pid)
                comps = A.composites(simulation.effective_values(p))
                curve = world.pp_for_overall(world.pp_overall(comps, p.in_game_date), p.in_game_date)
            print(f"level {level:>4.0f}: player {profile['total_pp']:>7.0f}pp (rank {profile['global_rank']}) · curve {curve:>7.0f}pp"
                  f" · ratio {profile['total_pp'] / curve:.2f} · {time.time() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
