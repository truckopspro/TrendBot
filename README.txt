TrendBot — shareable edition
============================

WHAT IT IS
TrendBot is a paper-trading bot. It watches stock and crypto prices,
follows trends, and makes pretend trades with pretend money so you can
see how the strategy does. It places NO real orders and cannot touch
real money — live trading is switched off in the code on purpose.

WHAT YOU NEED
- A computer with Python 3 installed (python.org).
- One extra piece, installed once. Open a terminal/command prompt in
  this folder and run:

    pip install yfinance

HOW TO RUN IT
In the same folder, run:

    python3 trendbot.py

(Windows: use "python trendbot.py" if python3 does not work.)

Each run does one full check: it prints what it would buy, sell, or
hold, and updates its paper account.

UPDATES — IT KEEPS ITSELF CURRENT
Every time it starts, TrendBot quietly checks its update home on
GitHub for a newer version. If one is posted, it downloads it, checks
it is genuine and working, swaps it in, and restarts on the new
version — all by itself. You never need to download a fresh copy.

NEWS GUARD (OPTIONAL)
If a file called news-state.json sits in the same folder as
trendbot.py, the bot reads it before buying: a stock or coin with
fresh (under 2 hours old), negative, high-impact news has its buy
held for that run, and the bot prints "held for news" with the
headline. News never makes the bot buy anything, and it never
blocks a sale. No news-state.json file means no holds — the bot
runs exactly as before.

STEP LADDER (OPTIONAL, OFF BY DEFAULT)
Version 1.2.0 adds the step ladder. It never opens a position. For
a position the bot itself opened, it can add planned steps as the
price dips below the price first paid: step 1 at -3%, step 2 at
-6.6%, step 3 at -10.92%, each step 1.2x the size of the one
before, and never more than 2x the position's normal total cost.
The stop-loss and take-profit then measure from the position's
average entry, so the stop still protects the whole position.
To try it, open trendbot.py and change LADDER_ENABLED = False to
True. Leave it False and the bot runs exactly as before.

YOUR ACCOUNT RECORD
Your paper account — cash, holdings, and trade history — lives in a
file called trendbot_paper.json, created next to trendbot.py the
first time you run it. Updates NEVER overwrite that file, so your
record carries on across every update. If you ever want to start
over, just delete trendbot_paper.json and run the bot again.

One honest note: the bot follows trends with real price data, but no
bot can promise profits. Treat it as a paper experiment and judge it
by its record over time.
