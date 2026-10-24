# Anchor scores

`anchor_scores.json` holds **real** historical scores for iconic maps. They show up on a map's
leaderboard once the in-game date reaches the day they were set; everything else on the board
is simulated.

Only add scores you can verify (osu!track archives, Wayback snapshots of osu! profiles,
replays with timestamps). Every entry must name its `source`; the engine refuses to load
entries without one.

```json
[
  {
    "beatmap_id": 129891,
    "player": "ExamplePlayer",
    "country": "JP",
    "mods": "HD",
    "score": 12345678,
    "accuracy": 98.76,
    "max_combo": 2385,
    "misses": 0,
    "pp": 0,
    "date": "2014-02-14",
    "source": "https://web.archive.org/web/.../osu.ppy.sh/b/129891"
  }
]
```

`mods` uses acronyms without separators (`""` for nomod, `"HDHR"`), `score` is ScoreV1, and `pp` is optional.
