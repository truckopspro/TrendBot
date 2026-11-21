#!/usr/bin/env python3
"""
TrendBot — personal paper-trading bot
Exported from your TrendBot Dashboard on 2026-11-21.

Shareable self-updating edition, version 1.0.0.
Each time it starts, this copy checks its update home on GitHub
(github.com/truckopspro/trendbot) for a newer version and, if one is
posted, downloads it, verifies it, and restarts on it automatically.
Updates replace only this program file — the paper account record in
trendbot_paper.json is never overwritten.

Strategy (trend following, daily bars):
  - For each watched stock, compare the 20-day moving average
    of closing prices with the 50-day moving average.
  - Fast above slow  -> trend is up   -> hold a position.
  - Fast below slow  -> trend is down -> stay in cash.
  - Each position is sized at 20% of the paper portfolio.
  - Paper account starts at $10,000.
  - Market discovery: scans DISCOVERY_UNIVERSE (50 liquid stocks/ETFs),
    scores each 0-100 from real data — momentum (today's % change, /30),
    breakout (price vs 50-day average, /25), volume (today vs
    20-day average, /20), trend strength (fast vs slow spread, /15),
    relative strength vs SPY (20-day, /10). A pick qualifies at score >= 55
    plus up >=1% today, above the slow average, and volume >=1.05x.
    The best qualifying pick not already held is paper-bought. The score
    describes today's action; it does not predict a spike.
  - Safeguards (same as the dashboard):
    * Stop-loss: every position is sold if its price falls to
      7% below its buy price.
    * Market weather: if SPY is below its 50-day average,
      no buys happen that day (sells and stop-losses still run).
    * Earnings dodge: no buy within 2 calendar days of a company's
      earnings report (dates via yfinance; skipped when unavailable).
    * Self-grading: closed trades are recorded in the state file; after
      every 5 closed discovery trades the discovery threshold adapts —
      win rate under 40% raises it 5 points (cap 75), 60% or better
      lowers it 3 (floor 45).
    * Take-profit: every position is sold in full once its gain reaches
      20% over its buy price.
    * Profit protection: once a position is up at least
      15%, a turn down (fast
      average at/below the slow one, or price below the slow average)
      sells it at that check instead of riding a deeper reversal.
    * Re-buy rule: after a take-profit or profit-protection sale the
      stock is not bought again in the same uptrend — it becomes
      buyable only after its trend turns down and then up again
      (a fresh uptrend). The blocks live in the state file.
    * Account brake: if the paper account falls 10% or more
      below the highest value it has recorded, all new buys pause.
      Holdings are not force-sold (stop-losses still apply). Buying
      resumes when the drawdown recovers above the brake line and the
      market regime is no longer Bear. The crypto sleeve below has
      its own high-water mark and brake on the same percentage.
    * Crypto sleeve: a separate paper sleeve (starts at
      $2,500) trading BTC-USD, ETH-USD, SOL, XRP, ADA
      and DOGE with the same trend, stop-loss, take-profit and
      profit-protection rules. Crypto trades 24/7, so the sleeve is
      checked on every run — including while the stock market is
      closed. Bitcoin's trend is its market gate.
    * Overnight / extended hours: the dashboard reads the feed's
      pre-market / after-hours price and computes the overnight gap
      (today's open vs yesterday's close). The gap feeds the daily
      check — a gap down of 3%+ or a gap up of 6%+ at the open blocks
      that day's buy, and smaller gaps are written into the buy
      reason. Holdings whose extended-hours price fell through their
      stop are flagged in the check notes. This export prints the
      same gap and extended move per stock; neither version ever
      trades outside regular hours.

This copy runs in PAPER mode: it prints the trades it *would* make and
tracks a pretend account in trendbot_paper.json next to this file.
It places NO real orders.

Setup:
  pip install yfinance
  python3 trendbot.py

Going live (your decision, not included):
  The live section at the bottom is disabled on purpose. To trade real
  money you would add your broker's official API yourself, keep the
  keys in environment variables (never in this file), and flip
  LIVE_TRADING to True only after paper results convince you.
"""

import json
import os
import sys
from datetime import date

try:
    import yfinance as yf
except ImportError:
    yf = None

WATCHLIST = ["AAPL","MSFT","NVDA","AMZN","GOOGL"]
DISCOVERY_UNIVERSE = ["SPY","QQQ","AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AMD","NFLX","AVGO","JPM","BAC","WFC","XOM","CVX","UNH","HD","COST","WMT","CRM","PLTR","COIN","HOOD","UBER","SHOP","ABNB","SMCI","ARM","MSTR","LLY","BRK.B","V","MA","PG","JNJ","ORCL","ADBE","NOW","INTU","QCOM","TXN","AMAT","MU","CAT","DE","GS","MS","BLK"]
DISCOVERY_THRESHOLD = 55
DISCOVERY_ENABLED = True
FAST_WINDOW = 20
SLOW_WINDOW = 50
POSITION_PCT = 20
STARTING_CASH = 10000
STOP_LOSS_PCT = 7
TAKE_PROFIT_PCT = 20
PROFIT_PROTECT_PCT = 15
BRAKE_PCT = 10
CRYPTO_UNIVERSE = ["BTC-USD","ETH-USD","SOL","XRP","ADA","DOGE"]
CRYPTO_STARTING_CASH = 2500
EARNINGS_DODGE_DAYS = 2
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trendbot_paper.json")
LIVE_TRADING = False  # <-- stays False in this export
VERSION = "1.0.0"
UPDATE_BASE = "https://raw.githubusercontent.com/truckopspro/trendbot/main"


def sma(values, window):
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def discovery_score(closes_list, volumes, price, change_pct, threshold):
    slow = sma(closes_list, SLOW_WINDOW)
    vs_slow = ((price / slow) - 1) * 100 if slow else 0
    vol_ratio = 1.0
    if volumes and len(volumes) >= 6:
        prior = [v for v in volumes[-21:-1] if v]
        if len(prior) >= 5:
            avg = sum(prior) / len(prior)
            if avg > 0:
                vol_ratio = volumes[-1] / avg
    momentum = max(0, min(change_pct, 8)) / 8 * 30
    breakout = max(0, min(vs_slow, 15)) / 15 * 25
    volume_pts = max(0, min(vol_ratio - 1, 2)) / 2 * 20
    # Trend strength + RS vs SPY approximated in dashboard; export keeps
    # the three live components scaled — see dashboard for full 100-pt score.
    trend_pts = 0
    rs_pts = 0
    score = momentum + breakout + volume_pts + trend_pts + rs_pts
    qualifies = score >= threshold and change_pct >= 1 and vs_slow > 0 and vol_ratio >= 1.05
    return score, momentum, breakout, volume_pts, vs_slow, vol_ratio, qualifies


def next_earnings_date(symbol):
    """Next earnings date (YYYY-MM-DD) from yfinance, or None if unknown."""
    try:
        cal = yf.Ticker(symbol).calendar
        raw = []
        if isinstance(cal, dict):
            raw = cal.get("Earnings Date") or []
        dates = []
        for d in raw:
            ds = d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10]
            dates.append(ds)
        today = date.today().isoformat()
        future = [d for d in dates if d >= today]
        return min(future) if future else None
    except Exception:
        return None


def earnings_block_date(symbol):
    """Earnings date if it falls within EARNINGS_DODGE_DAYS days, else None."""
    d = next_earnings_date(symbol)
    if not d:
        return None
    delta = (date.fromisoformat(d) - date.today()).days
    return d if 0 <= delta <= EARNINGS_DODGE_DAYS else None


def overnight_gap(symbol):
    """Today's open vs yesterday's close (%), or None when unavailable."""
    try:
        h = yf.Ticker(symbol).history(period="5d")
        if len(h) < 2:
            return None
        prev_close = float(h["Close"].iloc[-2])
        today_open = float(h["Open"].iloc[-1])
        if prev_close <= 0:
            return None
        return (today_open / prev_close - 1) * 100
    except Exception:
        return None


def extended_move(symbol):
    """Latest pre-market/after-hours move vs the regular close, from
    intraday bars with prepost=True. Returns (ext_price, pct) or
    (None, None). Detection only — never traded on."""
    try:
        d = yf.Ticker(symbol).history(period="5d")
        if d.empty:
            return None, None
        reg_close = float(d["Close"].iloc[-1])
        h = yf.Ticker(symbol).history(period="2d", interval="30m", prepost=True)
        if h.empty or reg_close <= 0:
            return None, None
        ext_price = float(h["Close"].iloc[-1])
        return ext_price, (ext_price / reg_close - 1) * 100
    except Exception:
        return None, None


def effective_threshold(state):
    return max(45, min(75, DISCOVERY_THRESHOLD + state.get("threshold_adjustment", 0)))


def maybe_adjust_threshold(state):
    closed = [c for c in state.get("closed_trades", []) if c["source"] == "discovery"]
    evaluated = state.get("threshold_evaluated", 0)
    adj = state.get("threshold_adjustment", 0)
    while evaluated + 5 <= len(closed):
        evaluated += 5
        wr = sum(1 for c in closed if c["win"]) / len(closed) * 100
        if wr < 40:
            adj += 5
        elif wr >= 60:
            adj -= 3
        adj = max(45, min(75, DISCOVERY_THRESHOLD + adj)) - DISCOVERY_THRESHOLD
        print(f"Self-grade: after {evaluated} closed discovery trades, win rate {wr:.0f}% — discovery threshold is now {DISCOVERY_THRESHOLD + adj} (base {DISCOVERY_THRESHOLD}).")
    state["threshold_evaluated"] = evaluated
    state["threshold_adjustment"] = adj


def record_close(state, symbol, source, buy_price, sell_price):
    pnl = (sell_price / buy_price - 1) * 100 if buy_price else 0
    state.setdefault("closed_trades", []).append(
        {"symbol": symbol, "source": source, "pnl_pct": round(pnl, 2), "win": pnl > 0}
    )
    if source == "discovery":
        maybe_adjust_threshold(state)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"cash": STARTING_CASH, "holdings": {}, "closed_trades": [], "threshold_adjustment": 0, "threshold_evaluated": 0, "profit_blocks": {}, "account_high_water": STARTING_CASH, "brake_active": False, "crypto": {"cash": CRYPTO_STARTING_CASH, "holdings": {}, "high_water": CRYPTO_STARTING_CASH, "brake_active": False}}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _version_tuple(text):
    parts = []
    for piece in str(text).strip().split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def check_for_update():
    """Self-update check (shareable edition).

    Looks at UPDATE_BASE/version.json on GitHub. If a newer version is
    posted there, downloads the new trendbot.py, verifies its sha256
    and that it compiles, swaps it in for this file, and restarts on
    it. Only this script file is ever replaced — trendbot_paper.json
    (your paper account record) is never touched. Any problem
    (offline, bad data) just prints one line and lets the bot run
    as-is.
    """
    import hashlib
    import py_compile
    import urllib.request

    try:
        with urllib.request.urlopen(UPDATE_BASE + "/version.json", timeout=10) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        remote_version = str(info["version"])
        remote_sha = str(info["sha256"]).lower()
        if _version_tuple(remote_version) <= _version_tuple(VERSION):
            return
        script = os.path.abspath(__file__)
        tmp_path = script + ".update-tmp"
        with urllib.request.urlopen(UPDATE_BASE + "/trendbot.py", timeout=30) as resp:
            payload = resp.read()
        if hashlib.sha256(payload).hexdigest() != remote_sha:
            print("Update check skipped: downloaded file failed its integrity check.")
            return
        with open(tmp_path, "wb") as f:
            f.write(payload)
        try:
            py_compile.compile(tmp_path, doraise=True)
        except Exception:
            os.remove(tmp_path)
            print("Update check skipped: downloaded file did not compile.")
            return
        os.replace(tmp_path, script)
        print(f"TrendBot updated itself to version {remote_version} - restarting on the new version.", flush=True)
        os.execv(sys.executable, [sys.executable, script] + sys.argv[1:])
    except Exception as exc:
        print(f"Update check skipped: {exc}")


def main():
    if yf is None:
        sys.exit("Missing dependency: run  pip install yfinance  first.")
    state = load_state()
    state.setdefault("closed_trades", [])
    state.setdefault("threshold_adjustment", 0)
    state.setdefault("threshold_evaluated", 0)
    state.setdefault("profit_blocks", {})
    state.setdefault("account_high_water", STARTING_CASH)
    state.setdefault("brake_active", False)
    state.setdefault("crypto", {"cash": CRYPTO_STARTING_CASH, "holdings": {}, "high_water": CRYPTO_STARTING_CASH, "brake_active": False})
    profit_blocks = state["profit_blocks"]
    cash = state["cash"]
    holdings = state["holdings"]

    closes = {}
    prices = {}
    fetch_symbols = list(dict.fromkeys(list(WATCHLIST) + list(holdings.keys()) + ["SPY"]))
    for symbol in fetch_symbols:
        hist = yf.Ticker(symbol).history(period="6mo")
        if hist.empty:
            print(f"{symbol}: no data — skipped")
            continue
        closes[symbol] = list(hist["Close"])
        prices[symbol] = float(hist["Close"].iloc[-1])

    total = cash + sum(
        holdings[s]["shares"] * prices.get(s, holdings[s]["avg_cost"])
        for s in holdings
    )
    print(f"Paper account: ${total:,.2f}  (cash ${cash:,.2f})")

    # Market weather — SPY vs its slow average gates every buy today.
    market_down = False
    if "SPY" in closes:
        spy_slow = sma(closes["SPY"], SLOW_WINDOW)
        if spy_slow is not None:
            market_down = prices["SPY"] < spy_slow
            if market_down:
                print("Market check: downtrend — no buys today.")
            else:
                print(f"Market check: SPY ${prices['SPY']:.2f} is above its {SLOW_WINDOW}-day average (${spy_slow:.2f}) — buys allowed.")

    # Account brake — pause all new buys when the account falls
    # BRAKE_PCT or more below its high-water mark. Holdings are not
    # force-sold. Releases when the drawdown recovers above the line
    # and the market check no longer blocks buys.
    state["account_high_water"] = max(state.get("account_high_water", STARTING_CASH), total)
    hw = state["account_high_water"]
    drawdown = (hw - total) / hw * 100 if hw > 0 else 0
    brake_active = state.get("brake_active", False)
    if drawdown >= BRAKE_PCT:
        brake_active = True
    elif brake_active and not market_down:
        brake_active = False
    state["brake_active"] = brake_active
    print(f"Account brake: {'ON - new buys paused' if brake_active else 'off'} (drawdown {drawdown:.1f}% from high-water ${hw:,.2f}, trips at {BRAKE_PCT}%)")

    # Overnight / extended hours — detection that feeds today's buys
    # via the gap gate below. Nothing trades outside regular hours.
    print("Overnight / extended hours:")
    for symbol in fetch_symbols:
        gap = overnight_gap(symbol)
        ext_price, ext_pct = extended_move(symbol)
        bits = []
        if gap is not None:
            bits.append(f"gapped {gap:+.2f}% at today's open vs yesterday's close")
        if ext_price is not None:
            bits.append(f"latest extended-hours ${ext_price:.2f} ({ext_pct:+.2f}% vs regular close)")
        print(f"  {symbol}: " + ("; ".join(bits) if bits else "no extended-hours data reported"))

    # Stop-loss pass — every position, before trend logic, sells even
    # when the market check blocks buys.
    stopped = set()
    for symbol in list(holdings.keys()):
        if symbol not in prices:
            continue
        price = prices[symbol]
        avg_cost = holdings[symbol]["avg_cost"]
        stop = round(avg_cost * (1 - STOP_LOSS_PCT / 100), 2)
        if price <= stop:
            shares = holdings[symbol]["shares"]
            proceeds = round(shares * price, 2)
            record_close(state, symbol, holdings[symbol].get("source", "watchlist"), avg_cost, price)
            del holdings[symbol]
            stopped.add(symbol)
            cash = round(cash + proceeds, 2)
            loss = (price / avg_cost - 1) * 100 if avg_cost else 0
            print(f"SELL {symbol}: {shares} shares @ ${price:.2f} = ${proceeds:,.2f} (stop-loss hit — bought at ${avg_cost:.2f}, stop set at ${stop:.2f}, {loss:.1f}% result)")

    # Take-profit pass — every remaining position up at least
    # TAKE_PROFIT_PCT is sold in full, even when buys are blocked.
    # The sale leaves a re-buy block (see below).
    profit_taken = set()
    for symbol in list(holdings.keys()):
        if symbol not in prices:
            continue
        price = prices[symbol]
        avg_cost = holdings[symbol]["avg_cost"]
        if not avg_cost:
            continue
        gain = (price / avg_cost - 1) * 100
        if gain >= TAKE_PROFIT_PCT:
            target = round(avg_cost * (1 + TAKE_PROFIT_PCT / 100), 2)
            shares = holdings[symbol]["shares"]
            proceeds = round(shares * price, 2)
            record_close(state, symbol, holdings[symbol].get("source", "watchlist"), avg_cost, price)
            del holdings[symbol]
            profit_taken.add(symbol)
            fast = sma(closes.get(symbol, []), FAST_WINDOW)
            slow = sma(closes.get(symbol, []), SLOW_WINDOW)
            saw_down = fast is not None and slow is not None and fast < slow
            profit_blocks[symbol] = {"saw_downtrend": saw_down, "sell_price": price}
            cash = round(cash + proceeds, 2)
            print(f"SELL {symbol}: {shares} shares @ ${price:.2f} = ${proceeds:,.2f} (Take-profit hit — bought at ${avg_cost:.2f}, target ${target:.2f}, +{gain:.1f}% gain. Waiting for a fresh uptrend before buying again.)")

    # Re-buy block maintenance — note when a blocked stock's trend has
    # turned down; a later uptrend then counts as fresh.
    for symbol, block in profit_blocks.items():
        if block.get("saw_downtrend") or symbol in holdings or symbol not in closes:
            continue
        fast = sma(closes[symbol], FAST_WINDOW)
        slow = sma(closes[symbol], SLOW_WINDOW)
        if fast is not None and slow is not None and fast < slow:
            block["saw_downtrend"] = True

    trade_symbols = list(WATCHLIST) + [s for s in holdings if s not in WATCHLIST]
    for symbol in trade_symbols:
        if symbol not in closes:
            continue
        price = prices[symbol]
        fast = sma(closes[symbol], FAST_WINDOW)
        slow = sma(closes[symbol], SLOW_WINDOW)
        if fast is None or slow is None:
            print(f"{symbol}: not enough history yet")
            continue
        trend_up = fast > slow
        # Profit protection — up at least PROFIT_PROTECT_PCT and turning
        # down (trend down or price below the slow average): sell now.
        if symbol in holdings:
            avg_cost = holdings[symbol]["avg_cost"]
            gain = (price / avg_cost - 1) * 100 if avg_cost else 0
            if gain >= PROFIT_PROTECT_PCT and (not trend_up or price < slow):
                shares = holdings[symbol]["shares"]
                proceeds = round(shares * price, 2)
                record_close(state, symbol, holdings[symbol].get("source", "watchlist"), avg_cost, price)
                del holdings[symbol]
                profit_taken.add(symbol)
                profit_blocks[symbol] = {"saw_downtrend": True, "sell_price": price}
                cash = round(cash + proceeds, 2)
                print(f"SELL {symbol}: {shares} shares @ ${price:.2f} = ${proceeds:,.2f} (Profit protection — trend turned down — bought at ${avg_cost:.2f}, +{gain:.1f}% gain. Waiting for a fresh uptrend before buying again.)")
                continue
        if trend_up and symbol not in holdings and symbol in WATCHLIST:
            if symbol in stopped or symbol in profit_taken:
                print(f"SKIP {symbol}: sold earlier in this run — not re-buying today")
                continue
            block = profit_blocks.get(symbol)
            if block:
                if block.get("saw_downtrend"):
                    del profit_blocks[symbol]
                    print(f"{symbol}: fresh uptrend after the post-profit dip — buyable again")
                else:
                    print(f"SKIP {symbol}: waiting for a fresh uptrend — sold for profit; buyable again only after the trend turns down and then up again")
                    continue
            if market_down:
                print(f"SKIP {symbol}: trend up, but the market check blocked all buys today")
                continue
            if brake_active:
                print(f"SKIP {symbol}: trend up, but the account brake is on - new buys paused until the account recovers")
                continue
            ed = earnings_block_date(symbol)
            if ed:
                print(f"Skipped {symbol} — earnings on {ed}")
                continue
            gap = overnight_gap(symbol)
            if gap is not None and (gap <= -3 or gap >= 6):
                print(f"SKIP {symbol}: overnight gap gate — gapped {gap:+.2f}% at today's open; the bot waits a day rather than trade into the overnight move")
                continue
            budget = min(cash, total * POSITION_PCT / 100)
            shares = round(budget / price, 4)
            if shares > 0 and shares * price >= 10:
                cost = round(shares * price, 2)
                holdings[symbol] = {"shares": shares, "avg_cost": price, "source": "watchlist"}
                cash = round(cash - cost, 2)
                print(f"BUY  {symbol}: {shares} shares @ ${price:.2f} = ${cost:,.2f} (trend up)")
        elif not trend_up and symbol in holdings:
            shares = holdings[symbol]["shares"]
            proceeds = round(shares * price, 2)
            record_close(state, symbol, holdings[symbol].get("source", "watchlist"), holdings[symbol]["avg_cost"], price)
            del holdings[symbol]
            cash = round(cash + proceeds, 2)
            print(f"SELL {symbol}: {shares} shares @ ${price:.2f} = ${proceeds:,.2f} (trend down — to cash)")
        else:
            state_txt = "holding" if symbol in holdings else "in cash"
            print(f"HOLD {symbol}: {state_txt} @ ${price:.2f} (fast ${fast:.2f} vs slow ${slow:.2f})")

    # --- Market discovery scan ---
    if DISCOVERY_ENABLED:
        print("\nDiscovery scan — ranking the broader market:")
        ranked = []
        for symbol in DISCOVERY_UNIVERSE:
            try:
                hist = yf.Ticker(symbol).history(period="6mo")
            except Exception:
                continue
            if hist.empty:
                continue
            cl = list(hist["Close"])
            vols = list(hist["Volume"]) if "Volume" in hist else []
            price = float(cl[-1])
            prev = float(cl[-2]) if len(cl) >= 2 else price
            change_pct = ((price / prev) - 1) * 100 if prev else 0
            score, mom, brk, vol_pts, vs_slow, vol_ratio, qualifies = discovery_score(cl, vols, price, change_pct, effective_threshold(state))
            ranked.append((score, symbol, price, change_pct, mom, brk, vol_pts, vs_slow, vol_ratio, qualifies))
        ranked.sort(reverse=True)
        for score, symbol, price, change_pct, mom, brk, vol_pts, vs_slow, vol_ratio, qualifies in ranked[:8]:
            flag = "QUALIFIES" if qualifies else "—"
            print(f"  {symbol}: score {score:.1f}/100 (momentum {mom:.1f}/30, breakout {brk:.1f}/25, volume {vol_pts:.1f}/20) up {change_pct:.2f}% today, {vs_slow:.2f}% vs slow avg, vol {vol_ratio:.2f}x {flag}")
        if market_down:
            print("  Market check: downtrend — no buys today (discovery buy skipped).")
        elif brake_active:
            print("  Account brake is on — discovery buy skipped today.")
        else:
            bought = False
            for r in ranked:
                if not r[9] or r[1] in holdings or r[1] in stopped or r[1] in profit_taken:
                    continue
                dblock = profit_blocks.get(r[1])
                if dblock:
                    if dblock.get("saw_downtrend"):
                        del profit_blocks[r[1]]
                        print(f"  {r[1]}: fresh uptrend after the post-profit dip — buyable again.")
                    else:
                        print(f"  Skipped {r[1]} — waiting for a fresh uptrend after its profit sale.")
                        continue
                ed = earnings_block_date(r[1])
                if ed:
                    print(f"  Skipped {r[1]} — earnings on {ed}.")
                    continue
                score, symbol, price = r[0], r[1], r[2]
                budget = min(cash, total * POSITION_PCT / 100)
                shares = round(budget / price, 4)
                if shares > 0 and shares * price >= 10:
                    cost = round(shares * price, 2)
                    holdings[symbol] = {"shares": shares, "avg_cost": price, "source": "discovery"}
                    cash = round(cash - cost, 2)
                    print(f"BUY  {symbol}: {shares} shares @ ${price:.2f} = ${cost:,.2f} (discovery pick, score {score:.1f})")
                    bought = True
                break
            if not bought:
                print("  No discovery pick qualified today — staying in cash on discovery.")

    # --- Crypto sleeve (24/7) — separate paper cash, own brake ---
    print("\nCrypto sleeve - trades around the clock, even while stocks are closed:")
    sleeve = state["crypto"]
    c_cash = sleeve["cash"]
    c_holdings = sleeve["holdings"]
    c_prices = {}
    c_closes = {}
    for symbol in CRYPTO_UNIVERSE:
        try:
            hist = yf.Ticker(symbol).history(period="6mo")
        except Exception:
            continue
        if hist.empty:
            continue
        c_closes[symbol] = list(hist["Close"])
        c_prices[symbol] = float(hist["Close"].iloc[-1])
    btc_fast = sma(c_closes.get("BTC-USD", []), FAST_WINDOW)
    btc_slow = sma(c_closes.get("BTC-USD", []), SLOW_WINDOW)
    btc_down_c = btc_fast is not None and btc_slow is not None and btc_fast < btc_slow
    c_total = c_cash + sum(c_holdings[s]["shares"] * c_prices.get(s, c_holdings[s]["avg_cost"]) for s in c_holdings)
    sleeve["high_water"] = max(sleeve.get("high_water", CRYPTO_STARTING_CASH), c_total)
    c_hw = sleeve["high_water"]
    c_dd = (c_hw - c_total) / c_hw * 100 if c_hw > 0 else 0
    c_brake = sleeve.get("brake_active", False)
    if c_dd >= BRAKE_PCT:
        c_brake = True
    elif c_brake and not btc_down_c:
        c_brake = False
    sleeve["brake_active"] = c_brake
    print(f"  Sleeve value {c_total:.2f} (cash {c_cash:.2f}) - brake {'ON' if c_brake else 'off'}, drawdown {c_dd:.1f}% from high-water {c_hw:.2f}; Bitcoin trend {'down - buys blocked' if btc_down_c else 'not down'}")
    for symbol in CRYPTO_UNIVERSE:
        if symbol not in c_closes:
            continue
        price = c_prices[symbol]
        fast = sma(c_closes[symbol], FAST_WINDOW)
        slow = sma(c_closes[symbol], SLOW_WINDOW)
        if fast is None or slow is None:
            print(f"  {symbol}: not enough history yet")
            continue
        if symbol in c_holdings:
            avg_cost = c_holdings[symbol]["avg_cost"]
            stop = round(avg_cost * (1 - STOP_LOSS_PCT / 100), 2)
            gain = (price / avg_cost - 1) * 100 if avg_cost else 0
            exit_reason = None
            if price <= stop:
                exit_reason = "stop-loss"
            elif gain >= TAKE_PROFIT_PCT:
                exit_reason = "take-profit"
            elif fast < slow:
                exit_reason = "trend down"
            if exit_reason:
                shares = c_holdings[symbol]["shares"]
                proceeds = round(shares * price, 2)
                record_close(state, symbol, "crypto", avg_cost, price)
                del c_holdings[symbol]
                c_cash = round(c_cash + proceeds, 2)
                print(f"  SELL {symbol}: {shares} @ {price:.2f} = {proceeds:.2f} ({exit_reason})")
                continue
            print(f"  HOLD {symbol}: @ {price:.2f} ({gain:+.1f}% vs buy)")
        elif fast > slow and not btc_down_c and not c_brake:
            budget = min(c_cash, c_total * POSITION_PCT / 100)
            shares = round(budget / price, 4)
            if shares > 0 and shares * price >= 10:
                cost = round(shares * price, 2)
                c_holdings[symbol] = {"shares": shares, "avg_cost": price, "source": "crypto"}
                c_cash = round(c_cash - cost, 2)
                print(f"  BUY  {symbol}: {shares} @ {price:.2f} = {cost:.2f} (trend up)")
            else:
                print(f"  {symbol}: trend up, not enough sleeve cash")
        else:
            print(f"  {symbol}: in cash @ {price:.2f} (fast {fast:.4f} vs slow {slow:.4f})")
    sleeve["cash"] = c_cash
    sleeve["holdings"] = c_holdings

    closed = state.get("closed_trades", [])
    if closed:
        wins = sum(1 for c in closed if c["win"])
        print(f"Record so far: {len(closed)} closed trades, {wins} wins ({wins / len(closed) * 100:.0f}% win rate). Discovery threshold: {effective_threshold(state)} (base {DISCOVERY_THRESHOLD}).")

    state["cash"] = cash
    state["holdings"] = holdings
    save_state(state)
    print(f"Done — {date.today().isoformat()}. Paper only; no real orders placed.")


# ---------------------------------------------------------------------------
# LIVE TRADING — DISABLED IN THIS EXPORT
# Turning this on is a separate, deliberate step that is NOT part of the
# download: it needs your broker's API keys in environment variables and
# your own review of every order type. TrendBot's dashboard keeps live
# trading locked for the same reason.
# ---------------------------------------------------------------------------
if LIVE_TRADING:
    raise SystemExit("Live trading is disabled in this export.")

if __name__ == "__main__":
    check_for_update()
    main()
