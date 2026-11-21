# TrendBot — shareable edition (self-update home)

TrendBot is a personal **paper-trading** bot. It follows daily price
trends (20-day vs 50-day moving averages) on a small watchlist, scans a
50-stock universe for a daily discovery pick, and runs a separate
24/7 crypto paper sleeve — all with pretend money. It places **no real
orders**; live trading is disabled in the code on purpose.

This repository is the update home for the shareable edition:

- `trendbot.py` — the bot itself (single file, needs Python 3 and
  `pip install yfinance`).
- `version.json` — the current version number and the sha256 of
  `trendbot.py`.

## How updates work

Every time a copy of the bot starts, it fetches `version.json` from
this repo. If the posted version is newer than the one it is running,
it downloads the new `trendbot.py`, checks the sha256 matches, checks
the file compiles, swaps it in, and restarts on the new version.
Updates only ever replace the program file — each person's paper
account record (`trendbot_paper.json`, kept next to their copy) is
never touched, so their pretend account and trade history survive
every update.

To publish an update: replace `trendbot.py`, bump `version` in
`version.json`, and set `sha256` to the new file's hash.
