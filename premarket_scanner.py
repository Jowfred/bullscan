#!/usr/bin/env python3
"""
Pre-Market Bullish News Scanner — v2
=====================================
A desktop app that pulls headlines from free RSS feeds (Reuters, MarketWatch,
Benzinga, Globe Newswire, SEC EDGAR press releases, Yahoo Finance), scores them
0-100 for bullish conviction, tags catalysts, extracts tickers, and auto-refreshes
every 5 minutes during pre-market hours (4:00 AM - 9:30 AM ET).

Dependencies: tkinter (stdlib), tzdata (pip install tzdata) on Windows.
Run:          python premarket_scanner.py
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue
import re
import os
import sys
import json
import shutil
import hashlib
import tempfile
import subprocess
import sqlite3
import logging
import webbrowser
from datetime import datetime, timezone, timedelta
from html import unescape
from html.parser import HTMLParser
from urllib.request import urlopen, Request
from urllib.parse import quote_plus
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

# Optional: embedded web view for showing articles inline
try:
    from tkinterweb import HtmlFrame  # type: ignore
    TKINTERWEB_AVAILABLE = True
except Exception:
    TKINTERWEB_AVAILABLE = False

# ───────────────────────────── CONFIG ─────────────────────────────────────────

ET_ZONE = ZoneInfo("America/New_York")
LOG_FILE = os.path.join(os.path.expanduser("~"), "premarket_alerts.log")
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".premarket_scanner.json")
DB_FILE = os.path.join(os.path.expanduser("~"), ".premarket_stories.db")
REFRESH_INTERVAL_SEC = 300
MAX_STORIES = 80
PERSIST_MIN_SCORE = 30   # stories at/above this score get saved to DB
USER_AGENT = "Mozilla/5.0 (PremarketScanner/1.0)"
HTTP_TIMEOUT = 15

# ─── Auto-updater ─────────────────────────────────────────────────────────────
UPDATE_URL = "https://raw.githubusercontent.com/jowfred/bullscan/main/premarket_scanner.py"
APP_VERSION = "2.6.0"
UPDATE_CHECK_ON_LAUNCH = True

RSS_FEEDS = {
    "Reuters": [
        "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best",
        "https://www.reutersagency.com/feed/?best-topics=markets&post_type=best",
    ],
    "MarketWatch": [
        "https://feeds.content.dowjones.io/public/rss/mwtopstories",
        "https://feeds.content.dowjones.io/public/rss/mwmarketpulse",
    ],
    "Benzinga": [
        "https://www.benzinga.com/feed",
    ],
    "GlobeNewswire": [
        "https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies",
    ],
    "SEC EDGAR": [
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb=&owner=include&count=40&output=atom",
    ],
    "Yahoo Finance": [
        "https://finance.yahoo.com/news/rssindex",
    ],
}

CATALYST_KEYWORDS = {
    "Earnings Beat": {
        "weight": 22,
        "patterns": [
            r"\bbeats?\s+(?:on\s+)?(?:earnings|estimates|expectations|eps|revenue|q[1-4])",
            r"\btops?\s+(?:earnings|estimates|expectations|consensus)",
            r"\bcrush(?:es|ed)?\s+(?:earnings|estimates)",
            r"\bsurpass(?:es|ed)?\s+(?:estimates|expectations)",
            r"\bearnings\s+surprise",
            r"\bbetter[-\s]than[-\s]expected",
            r"\bexceed(?:s|ed)\s+(?:estimates|expectations|guidance)",
            r"\brecord\s+(?:quarter|quarterly|revenue|earnings)",
        ],
    },
    "Guidance Raise": {
        "weight": 20,
        "patterns": [
            r"\braise(?:s|d)?\s+(?:full[-\s]year\s+)?guidance",
            r"\braise(?:s|d)?\s+(?:fy|q[1-4])?\s*outlook",
            r"\bguidance\s+(?:raised|increased|boosted)",
            r"\bboost(?:s|ed)?\s+(?:guidance|outlook|forecast)",
            r"\blift(?:s|ed)?\s+(?:guidance|outlook|forecast)",
            r"\bincrease(?:s|d)?\s+(?:guidance|outlook|forecast)",
            r"\braise(?:s|d)?\s+revenue\s+(?:guidance|forecast|outlook)",
        ],
    },
    "FDA Approval": {
        "weight": 28,
        "patterns": [
            r"\bfda\s+approval",
            r"\bfda\s+approve[ds]?",
            r"\bapproved\s+by\s+(?:the\s+)?fda",
            r"\bfda\s+clear(?:s|ed|ance)",
            r"\breceives?\s+fda",
            r"\bgrant(?:s|ed)?\s+(?:fda\s+)?(?:approval|clearance|breakthrough)",
            r"\bfda\s+breakthrough",
            r"\bphase\s+3\s+(?:success|positive|topline)",
            r"\bmeets?\s+primary\s+endpoint",
        ],
    },
    "Contract Win": {
        "weight": 18,
        "patterns": [
            r"\bwins?\s+(?:\$?[\d.,]+\s*(?:million|billion|m|b)?\s+)?(?:contract|deal|award|order)",
            r"\bawarded\s+(?:\$?[\d.,]+\s*(?:million|billion|m|b)?\s+)?contract",
            r"\bsecures?\s+(?:\$?[\d.,]+\s*(?:million|billion|m|b)?\s+)?(?:contract|deal|order)",
            r"\blands?\s+(?:major\s+)?(?:contract|deal|order)",
            r"\bgovernment\s+contract",
            r"\bdod\s+contract",
            r"\bpentagon\s+(?:awards?|contract)",
        ],
    },
    "Analyst Upgrade": {
        "weight": 15,
        "patterns": [
            r"\bupgraded?\s+to\s+(?:buy|overweight|outperform|strong\s+buy)",
            r"\bupgraded?\s+(?:by|at)\s+\w+",
            r"\bprice\s+target\s+(?:raised|increased|lifted|boosted|hiked)",
            r"\braises?\s+price\s+target",
            r"\binitiated?\s+(?:at|with)\s+(?:buy|overweight|outperform)",
            r"\breiterated?\s+buy",
            r"\btop\s+pick",
        ],
    },
    "Partnership": {
        "weight": 14,
        "patterns": [
            r"\bpartnership\s+with",
            r"\bpartners?\s+with",
            r"\bstrategic\s+(?:partnership|alliance|collaboration)",
            r"\bjoint\s+venture",
            r"\bcollaboration\s+(?:agreement|with)",
            r"\bteam\s+up\s+with",
            r"\bsigns?\s+(?:agreement|deal|mou)\s+with",
        ],
    },
    "M&A / Buyout": {
        "weight": 24,
        "patterns": [
            r"\bto\s+acquire\b",
            r"\bacquisition\s+of",
            r"\bagrees?\s+to\s+(?:acquire|buy|purchase)",
            r"\bmerger\s+with",
            r"\bbuyout\s+offer",
            r"\btakeover\s+(?:bid|offer)",
            r"\bdefinitive\s+agreement",
            r"\bgoing\s+private",
        ],
    },
    "Buyback / Dividend": {
        "weight": 12,
        "patterns": [
            r"\bshare\s+(?:buyback|repurchase)",
            r"\bbuyback\s+program",
            r"\brepurchase\s+program",
            r"\bauthoriz(?:es|ed)\s+\$?[\d.,]+\s*(?:million|billion|b|m)?\s+(?:share\s+)?(?:buyback|repurchase)",
            r"\bdividend\s+(?:increase|hike|raised|boost)",
            r"\bincreases?\s+(?:quarterly\s+)?dividend",
            r"\bspecial\s+dividend",
        ],
    },
    "Patent / IP": {
        "weight": 10,
        "patterns": [
            r"\bpatent\s+(?:granted|awarded|approved|issued)",
            r"\breceives?\s+patent",
            r"\bgrants?\s+patent",
        ],
    },
    "Insider Buying": {
        "weight": 11,
        "patterns": [
            r"\binsider\s+(?:buying|purchase)",
            r"\bceo\s+buys?\s+shares",
            r"\bdirector\s+buys?\s+shares",
            r"\b13d\s+filing",
            r"\bactivist\s+stake",
        ],
    },
}

BEARISH_PATTERNS = [
    (r"\bmisses?\s+(?:earnings|estimates|expectations)", -25, "Earnings miss"),
    (r"\bdowngrade[ds]?\s+to\s+(?:sell|underweight|underperform)", -20, "Severe downgrade"),
    (r"\bdowngrade[ds]?", -12, "Downgrade"),
    (r"\bcuts?\s+(?:guidance|outlook|forecast)", -22, "Guidance cut"),
    (r"\binvestigation", -10, "Investigation"),
    (r"\bsec\s+(?:probe|investigation|charges)", -25, "SEC action"),
    (r"\bfraud", -25, "Fraud allegation"),
    (r"\bbankruptcy", -30, "Bankruptcy"),
    (r"\brecall", -10, "Product recall"),
    (r"\bdelist(?:ed|ing)?", -25, "Delisting"),
    (r"\bgoing\s+concern", -25, "Going-concern doubt"),
    (r"\bfda\s+reject", -28, "FDA rejection"),
    (r"\bcomplete\s+response\s+letter", -22, "FDA CRL"),
    (r"\bfails?\s+(?:primary\s+endpoint|trial)", -25, "Trial failure"),
    (r"\bplunge[sd]?", -10, "Sharp drop language"),
    (r"\btumble[sd]?", -8, "Decline language"),
    (r"\bcrash(?:es|ed)?", -10, "Crash language"),
    (r"\blawsuit", -8, "Lawsuit"),
    (r"\bclass[-\s]action", -10, "Class action"),
]

MAGNITUDE_BONUS = [
    (r"\$\d{1,3}(?:[\.,]\d{3})*\s*billion\b", 8, "$ billion mention"),
    (r"\$\d{1,4}(?:[\.,]\d{1,3})?\s*b\b", 6, "Billion magnitude"),
    (r"\$\d{2,4}(?:[\.,]\d{3})*\s*million\b", 4, "Million magnitude"),
    (r"\ball[-\s]time\s+high", 5, "All-time high"),
    (r"\bbreakthrough", 4, "Breakthrough"),
]

CATEGORY_COLORS = {
    "Earnings Beat":      "#10b981",
    "Guidance Raise":     "#22c55e",
    "FDA Approval":       "#a855f7",
    "Contract Win":       "#3b82f6",
    "Analyst Upgrade":    "#06b6d4",
    "Partnership":        "#ec4899",
    "M&A / Buyout":       "#f59e0b",
    "Buyback / Dividend": "#84cc16",
    "Patent / IP":        "#6366f1",
    "Insider Buying":     "#14b8a6",
}

ALL_CATEGORIES = list(CATALYST_KEYWORDS.keys())

# ───────────────────────────── UTILITIES ──────────────────────────────────────

class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)
    def get_text(self):
        return "".join(self.parts)

def strip_html(s):
    if not s:
        return ""
    try:
        p = _HTMLStripper()
        p.feed(unescape(s))
        return re.sub(r"\s+", " ", p.get_text()).strip()
    except Exception:
        return re.sub(r"<[^>]+>", "", unescape(s)).strip()

def setup_logger():
    logger = logging.getLogger("premarket")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(fh)
    return logger

LOGGER = setup_logger()

def is_premarket_now():
    now_et = datetime.now(ET_ZONE)
    if now_et.weekday() >= 5:
        return False
    start = now_et.replace(hour=4, minute=0, second=0, microsecond=0)
    end = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    return start <= now_et <= end

# ───────────────────────────── PRICE FETCHING ─────────────────────────────────
# Uses Yahoo Finance's public quote endpoint. Free, may be slightly delayed.

_PRICE_CACHE = {}        # ticker -> (timestamp, price_dict)
_PRICE_CACHE_TTL = 60    # seconds; quote endpoint is fast, don't over-call

def _fetch_quote_yahoo(ticker):
    """Yahoo's chart endpoint — no auth required, unlike the quote endpoint."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{quote_plus(ticker)}"
           f"?interval=1d&range=5d&includePrePost=true")
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "application/json",
    })
    with urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read())
    chart = data.get("chart", {})
    result = (chart.get("result") or [None])[0]
    if not result:
        return None
    meta = result.get("meta", {}) or {}
    price = meta.get("regularMarketPrice")
    if price is None:
        # Fall back to last close from indicators
        closes = (result.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
        closes = [c for c in closes if c is not None]
        if closes:
            price = closes[-1]
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if price is None or prev is None:
        return None
    change = price - prev
    change_pct = (change / prev * 100) if prev else 0
    return {"price": float(price), "change": float(change),
            "change_pct": float(change_pct), "prev_close": float(prev),
            "source": "Yahoo"}

def _fetch_quote_stooq(ticker):
    """Stooq CSV fallback. No auth, returns delayed data. US tickers get .us suffix."""
    sym = ticker.lower()
    if "." not in sym and "-" not in sym:
        sym = f"{sym}.us"
    url = f"https://stooq.com/q/l/?s={quote_plus(sym)}&f=sd2t2ohlcv&h&e=csv"
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=8) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        return None
    # Header: Symbol,Date,Time,Open,High,Low,Close,Volume
    parts = lines[1].split(",")
    if len(parts) < 7:
        return None
    try:
        close = float(parts[6])
        opn = float(parts[3])
    except ValueError:
        return None
    if close <= 0:
        return None
    change = close - opn
    change_pct = (change / opn * 100) if opn else 0
    return {"price": close, "change": change, "change_pct": change_pct,
            "prev_close": opn, "source": "Stooq"}

def fetch_quote(ticker):
    """
    Returns {'price': float, 'change': float, 'change_pct': float, 'prev_close': float, 'source': str}
    or None if unavailable. Cached for 60s. Tries Yahoo first, falls back to Stooq.
    """
    if not ticker:
        return None
    now = datetime.now(timezone.utc).timestamp()
    cached = _PRICE_CACHE.get(ticker)
    if cached and (now - cached[0] < _PRICE_CACHE_TTL):
        return cached[1]

    # Try Yahoo first
    for fetcher_name, fetcher in (("Yahoo", _fetch_quote_yahoo), ("Stooq", _fetch_quote_stooq)):
        try:
            result = fetcher(ticker)
            if result and result.get("price"):
                _PRICE_CACHE[ticker] = (now, result)
                return result
        except (HTTPError, URLError) as e:
            LOGGER.debug(f"{fetcher_name} quote failed for {ticker}: {e}")
        except Exception as e:
            LOGGER.debug(f"{fetcher_name} quote error for {ticker}: {e}")

    # Cache the failure briefly so we don't hammer dead endpoints
    _PRICE_CACHE[ticker] = (now, None)
    return None

# ───────────────────────────── STORY DATABASE ─────────────────────────────────

def db_connect():
    """Open the SQLite store and ensure schema exists."""
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stories (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            story_key     TEXT UNIQUE,
            title         TEXT,
            summary       TEXT,
            link          TEXT,
            source        TEXT,
            published     TEXT,     -- ISO 8601 UTC
            captured_at   TEXT,     -- when we first saw it (UTC)
            score         INTEGER,
            catalysts     TEXT,     -- JSON list
            tickers       TEXT,     -- JSON list
            session_date  TEXT      -- ET date string (YYYY-MM-DD)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            story_id    INTEGER,
            ticker      TEXT,
            captured_at TEXT,        -- UTC ISO
            price       REAL,
            change_pct  REAL,
            kind        TEXT,        -- 'headline' | 'open' | 'review'
            FOREIGN KEY (story_id) REFERENCES stories(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON stories(session_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_story ON price_snapshots(story_id)")
    conn.commit()
    return conn

def session_date_for(dt_utc):
    """The 'trading session date' a story belongs to (ET date). Stories before
    the next pre-market open belong to the prior session."""
    et = dt_utc.astimezone(ET_ZONE) if dt_utc.tzinfo else dt_utc.replace(tzinfo=ET_ZONE)
    # Stories captured 4 AM ET onward belong to that day's session.
    # Before 4 AM: belong to the previous calendar day's session.
    if et.hour < 4:
        et = et - timedelta(days=1)
    return et.strftime("%Y-%m-%d")

def db_save_story(story):
    """Insert a story if not already present. Returns story DB id."""
    try:
        conn = db_connect()
        published = story.get("published") or datetime.now(timezone.utc)
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        captured = datetime.now(timezone.utc)
        session = session_date_for(captured)

        cur = conn.execute("SELECT id FROM stories WHERE story_key=?", (story["story_key"],))
        row = cur.fetchone()
        if row:
            sid = row[0]
        else:
            cur = conn.execute("""
                INSERT INTO stories (story_key,title,summary,link,source,published,
                                     captured_at,score,catalysts,tickers,session_date)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                story["story_key"], story["title"], story.get("summary", ""),
                story.get("link", ""), story.get("source", ""),
                published.isoformat(), captured.isoformat(),
                int(story.get("score", 0)),
                json.dumps(story.get("catalysts", [])),
                json.dumps(story.get("tickers", [])),
                session,
            ))
            sid = cur.lastrowid
        conn.commit()
        conn.close()
        return sid
    except Exception as e:
        LOGGER.warning(f"db_save_story failed: {e}")
        return None

def db_save_snapshot(story_id, ticker, price_info, kind):
    if not story_id or not price_info:
        return
    try:
        conn = db_connect()
        conn.execute("""
            INSERT INTO price_snapshots (story_id,ticker,captured_at,price,change_pct,kind)
            VALUES (?,?,?,?,?,?)
        """, (story_id, ticker, datetime.now(timezone.utc).isoformat(),
              price_info["price"], price_info["change_pct"], kind))
        conn.commit()
        conn.close()
    except Exception as e:
        LOGGER.warning(f"db_save_snapshot failed: {e}")

def db_load_stories(days_back=2):
    """Load all stored stories from the past N sessions."""
    out = []
    try:
        cutoff = (datetime.now(ET_ZONE) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        conn = db_connect()
        conn.row_factory = sqlite3.Row
        cur = conn.execute("""
            SELECT * FROM stories WHERE session_date >= ?
            ORDER BY datetime(published) DESC
        """, (cutoff,))
        for r in cur.fetchall():
            out.append({
                "id": r["id"],
                "story_key": r["story_key"],
                "title": r["title"],
                "summary": r["summary"] or "",
                "link": r["link"] or "",
                "source": r["source"] or "",
                "published": datetime.fromisoformat(r["published"]),
                "captured_at": datetime.fromisoformat(r["captured_at"]),
                "score": r["score"],
                "catalysts": json.loads(r["catalysts"] or "[]"),
                "tickers": json.loads(r["tickers"] or "[]"),
                "session_date": r["session_date"],
                "persisted": True,
            })
        conn.close()
    except Exception as e:
        LOGGER.warning(f"db_load_stories failed: {e}")
    return out

def db_get_headline_price(story_id, ticker):
    """Return the earliest captured price for this (story, ticker), or None."""
    try:
        conn = db_connect()
        cur = conn.execute("""
            SELECT price, captured_at, change_pct FROM price_snapshots
            WHERE story_id=? AND ticker=?
            ORDER BY datetime(captured_at) ASC LIMIT 1
        """, (story_id, ticker))
        row = cur.fetchone()
        conn.close()
        if row:
            return {"price": row[0], "captured_at": row[1], "change_pct": row[2]}
    except Exception as e:
        LOGGER.warning(f"db_get_headline_price failed: {e}")
    return None

def db_purge_old(days=14):
    """Drop very old stories so DB doesn't grow forever."""
    try:
        cutoff = (datetime.now(ET_ZONE) - timedelta(days=days)).strftime("%Y-%m-%d")
        conn = db_connect()
        cur = conn.execute("DELETE FROM stories WHERE session_date < ?", (cutoff,))
        conn.execute("DELETE FROM price_snapshots WHERE story_id NOT IN (SELECT id FROM stories)")
        conn.commit()
        deleted = cur.rowcount
        conn.close()
        if deleted:
            LOGGER.info(f"Purged {deleted} old stories from DB.")
    except Exception as e:
        LOGGER.warning(f"db_purge_old failed: {e}")

# ───────────────────────────── AUTO-UPDATER ───────────────────────────────────

def _local_script_path():
    """Path to the running script file."""
    try:
        return os.path.abspath(__file__)
    except NameError:
        return os.path.abspath(sys.argv[0])

def _sha256(data_bytes):
    return hashlib.sha256(data_bytes).hexdigest()

def fetch_remote_script():
    """Fetch the remote script. Returns bytes, or raises."""
    req = Request(UPDATE_URL, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()

def check_for_update():
    """
    Check GitHub for a newer version of the script.
    Returns dict: {'available': bool, 'remote_bytes': bytes|None, 'reason': str}
    """
    try:
        local_path = _local_script_path()
        if not os.path.exists(local_path):
            return {"available": False, "remote_bytes": None,
                    "reason": "Local script path not found."}

        with open(local_path, "rb") as f:
            local_bytes = f.read()

        remote_bytes = fetch_remote_script()

        # Basic sanity: refuse to install anything that isn't a Python script
        head = remote_bytes[:200].decode("utf-8", errors="ignore")
        if "tkinter" not in remote_bytes[:8000].decode("utf-8", errors="ignore") \
                and "PreMarketScanner" not in remote_bytes[:20000].decode("utf-8", errors="ignore"):
            return {"available": False, "remote_bytes": None,
                    "reason": "Remote content doesn't look like the scanner script."}

        if _sha256(local_bytes) == _sha256(remote_bytes):
            return {"available": False, "remote_bytes": None,
                    "reason": "Already up to date."}

        return {"available": True, "remote_bytes": remote_bytes, "reason": "Update available."}

    except (HTTPError, URLError) as e:
        return {"available": False, "remote_bytes": None,
                "reason": f"Couldn't reach update server: {e}"}
    except Exception as e:
        LOGGER.exception("Update check failed")
        return {"available": False, "remote_bytes": None,
                "reason": f"Update check error: {e}"}

def apply_update(remote_bytes):
    """
    Write the remote script to the local path (backing up the old one).
    Returns the local path on success, or raises.
    """
    local_path = _local_script_path()
    backup_path = local_path + ".bak"

    # Validate it parses as Python first — never write garbage
    try:
        compile(remote_bytes, "<remote-update>", "exec")
    except SyntaxError as e:
        raise RuntimeError(f"Downloaded update has a syntax error: {e}")

    # Back up current file
    try:
        shutil.copy2(local_path, backup_path)
    except Exception as e:
        LOGGER.warning(f"Couldn't create backup: {e}")

    # Write atomically: temp file in same dir, then replace
    target_dir = os.path.dirname(local_path)
    fd, tmp_path = tempfile.mkstemp(prefix=".update_", suffix=".py", dir=target_dir)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(remote_bytes)
        os.replace(tmp_path, local_path)
    except Exception:
        try: os.remove(tmp_path)
        except Exception: pass
        raise

    LOGGER.info(f"Updated script at {local_path} (backup at {backup_path})")
    return local_path

def restart_app():
    """Relaunch the script in a new process and exit the current one."""
    script_path = _local_script_path()
    python_exe = sys.executable or "python"
    try:
        # On Windows, DETACHED_PROCESS isn't needed if we just use Popen + exit
        subprocess.Popen([python_exe, script_path],
                         close_fds=True,
                         cwd=os.path.dirname(script_path) or None)
    except Exception as e:
        LOGGER.exception("Failed to restart")
        messagebox.showerror(
            "Restart failed",
            f"Update installed, but couldn't auto-restart.\n\n"
            f"Please close this window and re-open the app manually.\n\nError: {e}"
        )
        return
    # Exit current process
    os._exit(0)

# ───────────────────────────── TICKER EXTRACTION ──────────────────────────────

TICKER_BLACKLIST = {
    "CEO","CFO","COO","CTO","USA","US","UK","EU","FDA","SEC","IPO","ETF","NYSE",
    "NASDAQ","AI","API","GDP","CPI","PPI","FOMC","FED","ECB","BOJ","WTI","OPEC",
    "Q1","Q2","Q3","Q4","FY","EPS","PE","EV","ESG","ESPN","CNBC","WSJ","NYT",
    "PR","HQ","ER","TV","NEW","FOR","AND","THE","NOT","BUT","ALL","ANY","BIG",
    "OUT","TOP","WIN","DEAL","UP","ON","OFF","IN","AT","TO","BY","OF","IS","IT",
    "AS","BE","HAS","HAD","WAS","WAY","ITS","HIS","HER","WHO","WHY","HOW","NOW",
    "ONE","TWO","TEN","HOT","GET","LOW","HIGH","BUY","SELL","CUT","RISE","FALL",
    "GAIN","LOSS","NEWS","REPORT","ALERT","UPDATE","BREAKING","LIVE","WATCH",
    "STOCK","SHARES","MARKET","TODAY","WEEK","YEAR","MONTH","DAY","JAN","FEB",
    "MAR","APR","MAY","JUN","JUL","AUG","SEP","SEPT","OCT","NOV","DEC",
    "MON","TUE","WED","THU","FRI","SAT","SUN","ICYMI",
}

_RE_DOLLAR_TICK = re.compile(r"\$([A-Z]{1,5})\b")
_RE_PAREN_TICK  = re.compile(
    r"\(\s*(?:NYSE|NASDAQ|NasdaqGS|NasdaqGM|NasdaqCM|AMEX|OTC|NYSEARCA|NYSEAM|NYSE\s+American|TSX|TSXV|LSE)\s*:\s*([A-Z\.]{1,6})\s*\)",
    re.IGNORECASE,
)
_RE_BARE_TICK = re.compile(r"\b([A-Z]{2,5})\b")

def extract_tickers(text):
    if not text:
        return []
    found, seen = [], set()
    for m in _RE_DOLLAR_TICK.findall(text):
        t = m.upper()
        if t not in seen and t not in TICKER_BLACKLIST:
            seen.add(t); found.append(t)
    for m in _RE_PAREN_TICK.findall(text):
        t = m.upper()
        if t not in seen and t not in TICKER_BLACKLIST:
            seen.add(t); found.append(t)
    if not found:
        for m in _RE_BARE_TICK.findall(text):
            if m in TICKER_BLACKLIST or m in seen:
                continue
            if re.search(
                rf"\b{m}\b\s+(?:shares|stock|Corp|Corp\.|Inc|Inc\.|Ltd|Holdings|Technologies|Therapeutics|Pharmaceuticals|Biosciences|Group|plc|N\.V\.)\b",
                text,
            ):
                seen.add(m); found.append(m)
                if len(found) >= 5:
                    break
    return found[:6]

# ───────────────────────────── SCORING ────────────────────────────────────────

def score_story(title, summary):
    """Returns (score 0-100, list of catalyst tags, breakdown list).
    Breakdown is a list of (label, delta, source_text) tuples explaining scoring."""
    text = f"{title}\n{summary}".lower()
    score = 0
    tags = []
    breakdown = []

    for category, cfg in CATALYST_KEYWORDS.items():
        for pat in cfg["patterns"]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                score += cfg["weight"]
                tags.append(category)
                breakdown.append((category, cfg["weight"], m.group(0)))
                break

    for pat, bonus, label in MAGNITUDE_BONUS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            score += bonus
            breakdown.append((label, bonus, m.group(0)))

    for pat, penalty, label in BEARISH_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            score += penalty
            breakdown.append((label, penalty, m.group(0)))

    title_lower = title.lower()
    title_bonus = 0
    for cfg in CATALYST_KEYWORDS.values():
        for pat in cfg["patterns"]:
            if re.search(pat, title_lower, re.IGNORECASE):
                title_bonus += 4
                break
    title_bonus = min(title_bonus, 12)
    if title_bonus:
        score += title_bonus
        breakdown.append(("Headline emphasis", title_bonus, "(catalyst words in title)"))

    final = max(0, min(100, score))
    return final, tags, breakdown

def conviction_label(score, has_bearish):
    """Plain-English label for a score. NOT a trade recommendation."""
    if has_bearish:
        return "MIXED SIGNAL", "#f59e0b", "This story contains both bullish and bearish language. Read carefully."
    if score >= 75:
        return "STRONG BULL SIGNAL", "#10b981", "Multiple strong catalysts detected in this headline."
    if score >= 50:
        return "BULLISH", "#22c55e", "Clear bullish catalyst in this story."
    if score >= 25:
        return "MILDLY BULLISH", "#eab308", "Some bullish language detected — verify with the source."
    if score >= 10:
        return "WEAK SIGNAL", "#f97316", "Minor bullish hints, but the signal is weak."
    return "NO SIGNAL", "#6b7280", "No meaningful bullish catalyst found in this headline."

# ───────────────────────────── RSS PARSING ────────────────────────────────────

def fetch_feed(url):
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
    })
    with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        raw = resp.read()
    for enc in ("utf-8", "latin-1", "windows-1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")

def parse_feed(content, source):
    stories = []
    try:
        if content.startswith("\ufeff"):
            content = content.lstrip("\ufeff")
        root = ET.fromstring(content)
    except ET.ParseError as e:
        LOGGER.warning(f"Parse error for {source}: {e}")
        return stories

    def localname(tag):
        return tag.split("}", 1)[-1] if "}" in tag else tag

    items = [elem for elem in root.iter() if localname(elem.tag) in ("item", "entry")]

    for item in items:
        title = link = summary = ""
        pubdate = None
        for child in item:
            name = localname(child.tag)
            if name == "title":
                title = strip_html(child.text or "")
            elif name == "link":
                href = child.attrib.get("href")
                link = href if href else (child.text or "").strip()
            elif name in ("description", "summary", "content", "encoded"):
                if not summary:
                    summary = strip_html(child.text or "")
            elif name in ("pubDate", "published", "updated", "date"):
                dt_text = (child.text or "").strip()
                if dt_text:
                    try:
                        pubdate = parsedate_to_datetime(dt_text)
                    except (TypeError, ValueError):
                        try:
                            pubdate = datetime.fromisoformat(dt_text.replace("Z", "+00:00"))
                        except Exception:
                            pubdate = None
        if not title:
            continue
        if pubdate and pubdate.tzinfo is None:
            pubdate = pubdate.replace(tzinfo=timezone.utc)
        stories.append({
            "title": title,
            "summary": summary[:1500],
            "link": link,
            "source": source,
            "published": pubdate or datetime.now(timezone.utc),
        })
    return stories

def fetch_all_feeds(progress_cb=None):
    all_stories = []
    total = sum(len(v) for v in RSS_FEEDS.values())
    done = 0
    for source, urls in RSS_FEEDS.items():
        for url in urls:
            done += 1
            if progress_cb:
                try: progress_cb(done, total, source)
                except Exception: pass
            try:
                raw = fetch_feed(url)
                stories = parse_feed(raw, source)
                all_stories.extend(stories)
                LOGGER.info(f"Fetched {len(stories)} from {source}")
            except (HTTPError, URLError) as e:
                LOGGER.warning(f"Network error for {source} {url}: {e}")
            except Exception as e:
                LOGGER.warning(f"Unexpected error for {source} {url}: {e}")
    return all_stories

def dedupe_stories(stories):
    seen, out = {}, []
    for s in stories:
        key = re.sub(r"[^a-z0-9]+", "", s["title"].lower())[:120]
        if key in seen:
            continue
        seen[key] = True
        out.append(s)
    return out

# ───────────────────────────── GUI / THEME ────────────────────────────────────

PALETTE = {
    "bg":           "#0a0e1c",
    "bg_alt":       "#0f1424",
    "panel":        "#161c30",
    "panel_alt":    "#1a2138",
    "panel_hover":  "#1f2745",
    "border":       "#2a3454",
    "border_soft":  "#1e2640",
    "text":         "#e8ecf5",
    "text_dim":     "#9aa5c4",
    "text_mute":    "#5e6a8c",
    "accent":       "#22d3ee",
    "accent_hi":    "#67e8f9",
    "accent_2":     "#10b981",
    "warn":         "#f59e0b",
    "danger":       "#ef4444",
    "score_bg":     "#1f2747",
    "highlight":    "#1e3a8a",
    "shadow":       "#050811",
}

FONT_DISPLAY = "Segoe UI"   # Windows default; falls back gracefully on other OSes
FONT_MONO = "Consolas"


def color_for_score(score):
    if score >= 70: return "#10b981"
    if score >= 45: return "#22c55e"
    if score >= 25: return "#eab308"
    if score >= 10: return "#f97316"
    return "#6b7280"


def time_ago(dt):
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    secs = int(delta.total_seconds())
    if secs < 0: secs = 0
    if secs < 60:    return f"{secs}s ago"
    if secs < 3600:  return f"{secs // 60}m ago"
    if secs < 86400: return f"{secs // 3600}h ago"
    return dt.astimezone(ET_ZONE).strftime("%b %d, %I:%M %p ET")


# ─────────────────────────── DETAIL PANEL ─────────────────────────────────────

class StoryDetailPanel(tk.Frame):
    """Inline detail view — overlays the results area inside the main window
    instead of opening as a separate Toplevel popup."""

    def __init__(self, master, story, on_close, **kw):
        super().__init__(master, bg=PALETTE["bg"], **kw)
        self.story = story
        self.on_close = on_close
        self._build()

    def _build(self):
        s = self.story
        score = s["score"]
        score_color = color_for_score(score)
        has_bearish = any(d[1] < 0 for d in s.get("breakdown", []))
        label, label_color, label_desc = conviction_label(score, has_bearish)

        # Top bar: back button + close
        topbar = tk.Frame(self, bg=PALETTE["bg_alt"], height=44)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        back_btn = tk.Button(topbar, text="◀  Back to stories",
            bg=PALETTE["bg_alt"], fg=PALETTE["accent"],
            font=(FONT_DISPLAY, 10, "bold"), bd=0, relief="flat",
            cursor="hand2", activebackground=PALETTE["panel"],
            command=self.on_close, padx=14, pady=8)
        back_btn.pack(side="left", padx=14, pady=6)

        tk.Label(topbar, text="Story Details", bg=PALETTE["bg_alt"],
                 fg=PALETTE["text_mute"], font=(FONT_DISPLAY, 10)
                 ).pack(side="left", pady=12)

        tk.Frame(self, bg=PALETTE["border"], height=1).pack(fill="x")

        # Header band with score
        header = tk.Frame(self, bg=PALETTE["panel"])
        header.pack(fill="x")

        hpad = tk.Frame(header, bg=PALETTE["panel"])
        hpad.pack(fill="x", padx=24, pady=18)

        meta = tk.Frame(hpad, bg=PALETTE["panel"])
        meta.pack(fill="x")
        tk.Label(meta, text=s["source"].upper(), bg=PALETTE["panel"],
                 fg=PALETTE["accent"], font=(FONT_DISPLAY, 9, "bold")
                 ).pack(side="left")
        tk.Label(meta, text=f"  ·  {time_ago(s['published'])}",
                 bg=PALETTE["panel"], fg=PALETTE["text_mute"],
                 font=(FONT_DISPLAY, 9)).pack(side="left")

        tk.Label(hpad, text=s["title"], bg=PALETTE["panel"],
                 fg=PALETTE["text"], font=(FONT_DISPLAY, 14, "bold"),
                 anchor="w", justify="left", wraplength=720
                 ).pack(fill="x", pady=(8, 12))

        score_row = tk.Frame(hpad, bg=PALETTE["panel"])
        score_row.pack(fill="x")

        score_box = tk.Frame(score_row, bg=score_color, width=90, height=60)
        score_box.pack(side="left")
        score_box.pack_propagate(False)
        tk.Label(score_box, text=str(score), bg=score_color, fg="#0a0e1c",
                 font=(FONT_DISPLAY, 26, "bold")).pack(expand=True)

        label_box = tk.Frame(score_row, bg=PALETTE["panel"])
        label_box.pack(side="left", padx=(16, 0), fill="both", expand=True)
        tk.Label(label_box, text=label, bg=PALETTE["panel"],
                 fg=label_color, font=(FONT_DISPLAY, 13, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(label_box, text=label_desc, bg=PALETTE["panel"],
                 fg=PALETTE["text_dim"], font=(FONT_DISPLAY, 9),
                 anchor="w", justify="left", wraplength=600
                 ).pack(fill="x", pady=(2, 0))

        # Scrollable body
        body_wrap = tk.Frame(self, bg=PALETTE["bg"])
        body_wrap.pack(fill="both", expand=True)

        canvas = tk.Canvas(body_wrap, bg=PALETTE["bg"], highlightthickness=0)
        sb = ttk.Scrollbar(body_wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = tk.Frame(canvas, bg=PALETTE["bg"])
        bid = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(bid, width=e.width))
        canvas.bind_all("<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        if s.get("summary"):
            self._section(body, "STORY SUMMARY")
            tk.Label(body, text=s["summary"], bg=PALETTE["bg"],
                     fg=PALETTE["text"], font=(FONT_DISPLAY, 10),
                     anchor="w", justify="left", wraplength=700
                     ).pack(fill="x", padx=24, pady=(0, 16))

        if s.get("tickers"):
            self._section(body, "TICKERS DETECTED")
            for t in s["tickers"][:6]:
                self._ticker_card(body, t)
            tk.Label(body,
                text="Each ticker has a TradingView chart and quick research links. "
                     "Always verify the ticker matches the company in the headline.",
                bg=PALETTE["bg"], fg=PALETTE["text_mute"],
                font=(FONT_DISPLAY, 8), anchor="w", justify="left", wraplength=700
                ).pack(fill="x", padx=24, pady=(4, 16))

        if s.get("catalysts"):
            self._section(body, "CATALYST TAGS")
            cat_wrap = tk.Frame(body, bg=PALETTE["bg"])
            cat_wrap.pack(fill="x", padx=24, pady=(0, 16))
            for cat in s["catalysts"]:
                color = CATEGORY_COLORS.get(cat, PALETTE["accent"])
                tk.Label(cat_wrap, text=f"  {cat}  ", bg=color, fg="#0a0e1c",
                         font=(FONT_DISPLAY, 9, "bold")
                         ).pack(side="left", padx=(0, 6), pady=2)

        self._section(body, "SCORE BREAKDOWN")
        bd = s.get("breakdown", [])
        if not bd:
            tk.Label(body, text="No scoring components matched (likely a story loaded from previous session).",
                     bg=PALETTE["bg"], fg=PALETTE["text_mute"],
                     font=(FONT_DISPLAY, 10), anchor="w"
                     ).pack(fill="x", padx=24, pady=(0, 16))
        else:
            tbl = tk.Frame(body, bg=PALETTE["bg"])
            tbl.pack(fill="x", padx=24, pady=(0, 16))
            for label_text, delta, matched in bd:
                row = tk.Frame(tbl, bg=PALETTE["panel_alt"])
                row.pack(fill="x", pady=1)
                sign = "+" if delta >= 0 else ""
                delta_color = PALETTE["accent_2"] if delta >= 0 else PALETTE["danger"]
                tk.Label(row, text=f" {sign}{delta} ",
                         bg=delta_color, fg="#0a0e1c",
                         font=(FONT_DISPLAY, 10, "bold"), width=5
                         ).pack(side="left")
                tk.Label(row, text=f"  {label_text}",
                         bg=PALETTE["panel_alt"], fg=PALETTE["text"],
                         font=(FONT_DISPLAY, 10, "bold"), anchor="w"
                         ).pack(side="left", padx=(4, 0), pady=8)
                tk.Label(row, text=f"  \u201C{matched}\u201D  ",
                         bg=PALETTE["panel_alt"], fg=PALETTE["text_mute"],
                         font=(FONT_DISPLAY, 9, "italic"), anchor="w"
                         ).pack(side="left", padx=(4, 8), pady=8)

        self._section(body, "WHAT THIS SCORE MEANS")
        disc = (
            "The Bull Score is a keyword-based heuristic. A high score means the "
            "headline contains language commonly associated with bullish catalysts "
            "(earnings beats, FDA approvals, M&A, guidance raises, etc.).\n\n"
            "A high score is NOT a trade recommendation. The market often prices "
            "in news before retail traders can react. Headlines can also be "
            "misleading \u2014 read the source article carefully.\n\n"
            "Before considering any trade, verify:\n"
            "   \u2022 The actual numbers (is the beat meaningful or barely above estimates?)\n"
            "   \u2022 Pre-market price action and volume\n"
            "   \u2022 Float, short interest, and dilution risk\n"
            "   \u2022 Whether the news is truly new or already known\n"
            "   \u2022 Your own risk tolerance and position sizing\n\n"
            "This tool helps you triage news faster. The decision is yours."
        )
        tk.Label(body, text=disc, bg=PALETTE["bg"], fg=PALETTE["text_dim"],
                 font=(FONT_DISPLAY, 9), anchor="w", justify="left",
                 wraplength=700).pack(fill="x", padx=24, pady=(0, 16))

        # Footer actions
        footer = tk.Frame(self, bg=PALETTE["panel"])
        footer.pack(side="bottom", fill="x")
        fpad = tk.Frame(footer, bg=PALETTE["panel"])
        fpad.pack(fill="x", padx=24, pady=14)

        if s.get("link"):
            tk.Button(fpad, text="\U0001F4F0  OPEN SOURCE ARTICLE",
                bg=PALETTE["accent"], fg="#0a0e1c",
                font=(FONT_DISPLAY, 10, "bold"), bd=0, relief="flat",
                activebackground=PALETTE["accent_hi"], cursor="hand2",
                command=lambda: webbrowser.open(s["link"]),
                padx=14, pady=8).pack(side="left")

        tk.Button(fpad, text="\u25C0  Back to stories",
            bg=PALETTE["panel_alt"], fg=PALETTE["text_dim"],
            font=(FONT_DISPLAY, 10), bd=0, relief="flat",
            activebackground=PALETTE["panel_hover"], cursor="hand2",
            command=self.on_close, padx=14, pady=8).pack(side="right")

    def _section(self, parent, title):
        hdr = tk.Frame(parent, bg=PALETTE["bg"])
        hdr.pack(fill="x", padx=24, pady=(14, 6))
        tk.Frame(hdr, bg=PALETTE["accent"], width=3, height=14).pack(side="left", padx=(0, 8))
        tk.Label(hdr, text=title, bg=PALETTE["bg"],
                 fg=PALETTE["text_dim"], font=(FONT_DISPLAY, 9, "bold")
                 ).pack(side="left")

    def _ticker_card(self, parent, ticker):
        """Full-width card per ticker: live price + TradingView CTA + research links."""
        card = tk.Frame(parent, bg=PALETTE["panel"],
                        highlightthickness=1, highlightbackground=PALETTE["border"])
        card.pack(fill="x", padx=24, pady=(0, 8))

        # Left column: big ticker symbol
        left = tk.Frame(card, bg=PALETTE["highlight"], width=90)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text=f"${ticker}", bg=PALETTE["highlight"],
                 fg=PALETTE["text"], font=(FONT_DISPLAY, 16, "bold")
                 ).pack(expand=True, padx=8, pady=14)

        # Right column
        right = tk.Frame(card, bg=PALETTE["panel"])
        right.pack(side="left", fill="both", expand=True, padx=14, pady=10)

        # Live price row — populated asynchronously
        price_row = tk.Frame(right, bg=PALETTE["panel"])
        price_row.pack(fill="x", pady=(0, 6))
        price_lbl = tk.Label(price_row, text="Loading price…",
                              bg=PALETTE["panel"], fg=PALETTE["text_mute"],
                              font=(FONT_DISPLAY, 11, "bold"))
        price_lbl.pack(side="left")

        # Look up headline price from DB if this story is persisted
        story_id = self.story.get("db_id") or self._find_story_id()
        headline_info = db_get_headline_price(story_id, ticker) if story_id else None

        def update_price():
            q = fetch_quote(ticker)
            if not q:
                try: price_lbl.config(text="Price unavailable", fg=PALETTE["text_mute"])
                except tk.TclError: pass
                return
            color = PALETTE["accent_2"] if q["change_pct"] >= 0 else PALETTE["danger"]
            sign = "+" if q["change_pct"] >= 0 else ""
            text = f"${q['price']:.2f}  ({sign}{q['change_pct']:.2f}% today)"
            try:
                price_lbl.config(text=text, fg=color)
            except tk.TclError:
                pass

            # If we have a stored headline price, show outcome (this is the "review")
            if headline_info:
                hp = headline_info["price"]
                delta = q["price"] - hp
                delta_pct = (delta / hp * 100) if hp else 0
                outcome_color = PALETTE["accent_2"] if delta_pct >= 0 else PALETTE["danger"]
                outcome_sign = "+" if delta_pct >= 0 else ""
                try:
                    captured = datetime.fromisoformat(headline_info["captured_at"])
                    captured_str = captured.astimezone(ET_ZONE).strftime("%b %d, %I:%M %p ET")
                except Exception:
                    captured_str = "earlier"
                outcome = tk.Label(price_row,
                    text=f"   ●   Since headline (${hp:.2f} at {captured_str}): "
                         f"{outcome_sign}${delta:.2f} ({outcome_sign}{delta_pct:.2f}%)",
                    bg=PALETTE["panel"], fg=outcome_color,
                    font=(FONT_DISPLAY, 9, "bold"))
                try: outcome.pack(side="left", padx=(8, 0))
                except tk.TclError: pass

        threading.Thread(target=update_price, daemon=True).start()

        # TradingView CTA
        tv_url = f"https://www.tradingview.com/symbols/{quote_plus(ticker)}/"
        tk.Button(right,
            text=f"📈   OPEN ${ticker} CHART ON TRADINGVIEW",
            bg=PALETTE["accent_2"], fg="#0a0e1c",
            font=(FONT_DISPLAY, 10, "bold"),
            bd=0, relief="flat", cursor="hand2",
            activebackground="#34d399",
            command=lambda u=tv_url: webbrowser.open(u),
            padx=10, pady=8, anchor="w").pack(fill="x")

        # Research links
        sec_row = tk.Frame(right, bg=PALETTE["panel"])
        sec_row.pack(fill="x", pady=(8, 0))
        tk.Label(sec_row, text="Research:", bg=PALETTE["panel"],
                 fg=PALETTE["text_mute"], font=(FONT_DISPLAY, 8)
                 ).pack(side="left", padx=(0, 6))
        for label, url in [
            ("Yahoo Finance", f"https://finance.yahoo.com/quote/{quote_plus(ticker)}"),
            ("Finviz", f"https://finviz.com/quote.ashx?t={quote_plus(ticker)}"),
            ("SEC Filings", f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={quote_plus(ticker)}&type=&dateb=&owner=include&count=40"),
            ("Google News", f"https://news.google.com/search?q={quote_plus(ticker)}+stock"),
        ]:
            b = tk.Label(sec_row, text=f"  {label}  ",
                         bg=PALETTE["panel_alt"], fg=PALETTE["accent_hi"],
                         font=(FONT_DISPLAY, 8, "bold"),
                         cursor="hand2", padx=4, pady=4)
            b.pack(side="left", padx=(0, 4))
            b.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))

    def _find_story_id(self):
        """Look up the story's DB id by story_key, if it exists."""
        key = self.story.get("story_key")
        if not key:
            return None
        try:
            conn = db_connect()
            cur = conn.execute("SELECT id FROM stories WHERE story_key=?", (key,))
            row = cur.fetchone()
            conn.close()
            return row[0] if row else None
        except Exception:
            return None


# ─────────────────────────── STORY CARD ───────────────────────────────────────

class StoryCard(tk.Frame):
    def __init__(self, master, story, on_click, on_pin=None, watchlist=None,
                 show_outcome=False, **kw):
        super().__init__(master, bg=PALETTE["panel"], bd=0, highlightthickness=1,
                         highlightbackground=PALETTE["border_soft"], **kw)
        self.story = story
        self.on_click = on_click
        self.on_pin = on_pin
        self.watchlist = watchlist or set()
        self.show_outcome = show_outcome
        self._build()
        self._bind_click(self)

    def _bind_click(self, widget):
        widget.bind("<Button-1>", self._handle_click)
        widget.bind("<Enter>", self._on_enter)
        widget.bind("<Leave>", self._on_leave)
        for child in widget.winfo_children():
            # Don't override interactive widgets that have their own bindings
            if not isinstance(child, (tk.Button,)):
                self._bind_click(child)

    def _on_enter(self, _e):
        self.config(highlightbackground=PALETTE["accent"])

    def _on_leave(self, _e):
        self.config(highlightbackground=PALETTE["border_soft"])

    def _handle_click(self, _evt=None):
        if self.on_click:
            self.on_click(self.story)

    def _build(self):
        s = self.story
        score = s["score"]
        bull_color = color_for_score(score)

        # Left score column
        left = tk.Frame(self, bg=bull_color, width=6)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        content = tk.Frame(self, bg=PALETTE["panel"])
        content.pack(side="left", fill="both", expand=True)

        # Top: source · time · score
        top = tk.Frame(content, bg=PALETTE["panel"])
        top.pack(fill="x", padx=14, pady=(11, 4))

        tk.Label(top, text=s["source"].upper(), bg=PALETTE["panel"],
                 fg=PALETTE["accent"], font=(FONT_DISPLAY, 8, "bold")
                 ).pack(side="left")
        tk.Label(top, text=f"  ·  {time_ago(s['published'])}",
                 bg=PALETTE["panel"], fg=PALETTE["text_mute"],
                 font=(FONT_DISPLAY, 9)).pack(side="left")

        # "FROM PREVIOUS SESSION" badge for stories carried over from earlier sessions
        if s.get("persisted"):
            today_session = session_date_for(datetime.now(timezone.utc))
            if s.get("session_date") and s["session_date"] != today_session:
                tk.Label(top, text="  ⏱ REVIEW  ", bg="#6366f1", fg=PALETTE["text"],
                         font=(FONT_DISPLAY, 8, "bold")
                         ).pack(side="left", padx=(8, 0))

        # Score badge
        score_wrap = tk.Frame(top, bg=PALETTE["panel"])
        score_wrap.pack(side="right")
        score_lbl = tk.Label(score_wrap, text=f"  {score}  ",
                             bg=bull_color, fg="#0a0e1c",
                             font=(FONT_DISPLAY, 11, "bold"))
        score_lbl.pack(side="right")
        tk.Label(score_wrap, text="BULL  ", bg=PALETTE["panel"],
                 fg=PALETTE["text_mute"], font=(FONT_DISPLAY, 8)
                 ).pack(side="right", pady=(2, 0))

        # Title
        tk.Label(content, text=s["title"], bg=PALETTE["panel"],
                 fg=PALETTE["text"], font=(FONT_DISPLAY, 11, "bold"),
                 anchor="w", justify="left", wraplength=720
                 ).pack(fill="x", padx=14, pady=(2, 4))

        # Summary preview
        if s.get("summary"):
            summ = s["summary"]
            if len(summ) > 220:
                summ = summ[:220].rsplit(" ", 1)[0] + "…"
            tk.Label(content, text=summ, bg=PALETTE["panel"],
                     fg=PALETTE["text_dim"], font=(FONT_DISPLAY, 9),
                     anchor="w", justify="left", wraplength=720
                     ).pack(fill="x", padx=14, pady=(0, 8))

        # Outcome row — only in Outcomes view, shows price-since-headline async
        if self.show_outcome and s.get("tickers"):
            self._build_outcome_row(content, s)

        # Score bar
        bar_bg = tk.Frame(content, bg=PALETTE["score_bg"], height=4)
        bar_bg.pack(fill="x", padx=14, pady=(0, 8))
        bar_bg.pack_propagate(False)

        # Persistent fill rectangle — resized rather than recreated. Throttle to avoid lag.
        self._bar_fill = tk.Frame(bar_bg, bg=bull_color, height=4)
        self._bar_fill.place(x=0, y=0, width=2, height=4)
        self._bar_resize_job = None
        self._bar_bg = bar_bg

        def _draw_bar(_e=None):
            try:
                w = bar_bg.winfo_width()
                fill_w = max(2, int(w * score / 100))
                self._bar_fill.place_configure(width=fill_w)
            except tk.TclError:
                pass
            self._bar_resize_job = None

        def _schedule_bar(_e=None):
            if self._bar_resize_job is not None:
                try: self.after_cancel(self._bar_resize_job)
                except Exception: pass
            self._bar_resize_job = self.after(40, _draw_bar)

        bar_bg.bind("<Configure>", _schedule_bar)

        # Bottom: tickers + tags + actions
        bot = tk.Frame(content, bg=PALETTE["panel"])
        bot.pack(fill="x", padx=14, pady=(0, 12))

        for tk_sym in s.get("tickers", [])[:5]:
            tk.Label(bot, text=f" ${tk_sym} ", bg=PALETTE["highlight"],
                     fg=PALETTE["text"], font=(FONT_DISPLAY, 9, "bold")
                     ).pack(side="left", padx=(0, 5))
        for cat in s.get("catalysts", []):
            color = CATEGORY_COLORS.get(cat, PALETTE["accent"])
            tk.Label(bot, text=f" {cat} ", bg=color, fg="#0a0e1c",
                     font=(FONT_DISPLAY, 8, "bold")
                     ).pack(side="left", padx=(0, 5))

        # Right side: watchlist badge + pin button + click hint
        if s.get("watch_match"):
            tk.Label(bot, text="  ★ WATCHLIST  ", bg=PALETTE["warn"],
                     fg="#0a0e1c", font=(FONT_DISPLAY, 8, "bold")
                     ).pack(side="right", padx=(4, 0))

        # Pin to watchlist button — only show if there are tickers to pin AND on_pin is wired
        if s.get("tickers") and self.on_pin:
            tickers_to_pin = set(s["tickers"][:3])
            pin_already = bool(tickers_to_pin) and tickers_to_pin.issubset(self.watchlist)
            btn_text = "✓ Pinned" if pin_already else "📌 Pin Tickers"
            btn_bg = PALETTE["panel_alt"] if pin_already else PALETTE["accent"]
            btn_fg = PALETTE["text_mute"] if pin_already else "#0a0e1c"
            pin_btn = tk.Button(bot, text=btn_text,
                bg=btn_bg, fg=btn_fg,
                font=(FONT_DISPLAY, 8, "bold"),
                bd=0, relief="flat", cursor="hand2",
                activebackground=PALETTE["accent_hi"],
                command=self._handle_pin, padx=8, pady=3)
            pin_btn.pack(side="right", padx=(0, 6))

        # "View details" hint
        tk.Label(bot, text="Click for details →", bg=PALETTE["panel"],
                 fg=PALETTE["text_mute"], font=(FONT_DISPLAY, 8, "italic")
                 ).pack(side="right", padx=(0, 10))

    def _handle_pin(self):
        """Called when the user clicks the Pin button. Doesn't propagate to card click."""
        if self.on_pin:
            self.on_pin(self.story)

    def _build_outcome_row(self, parent, s):
        """A row showing 'Price at headline → Price now' for each ticker. Async."""
        outcome_frame = tk.Frame(parent, bg=PALETTE["bg_alt"])
        outcome_frame.pack(fill="x", padx=14, pady=(0, 8))

        # The "review unlock" rule: results are only meaningful after market opens.
        # Show "Locked" badge if it's still pre-market or earlier the same day.
        story_published = s.get("published")
        if story_published and story_published.tzinfo is None:
            story_published = story_published.replace(tzinfo=timezone.utc)

        now_et = datetime.now(ET_ZONE)
        # Review is "unlocked" if at least one full market open (9:30 AM ET) has elapsed since publication
        review_unlocked = True
        if story_published:
            pub_et = story_published.astimezone(ET_ZONE)
            # Unlock if today's date is after pub date AND it's past 11:30 AM ET on review day
            same_day = pub_et.date() == now_et.date()
            if same_day and now_et.hour < 11:
                review_unlocked = False

        header_row = tk.Frame(outcome_frame, bg=PALETTE["bg_alt"])
        header_row.pack(fill="x", padx=10, pady=(6, 2))
        tk.Label(header_row, text="📊  OUTCOME REVIEW",
                 bg=PALETTE["bg_alt"], fg=PALETTE["text_mute"],
                 font=(FONT_DISPLAY, 8, "bold")
                 ).pack(side="left")

        if not review_unlocked:
            tk.Label(header_row, text="🔒 Available after 11:30 AM ET review window",
                     bg=PALETTE["bg_alt"], fg=PALETTE["warn"],
                     font=(FONT_DISPLAY, 8, "italic")
                     ).pack(side="left", padx=(10, 0))
            return

        # Render one row per ticker, async-fill prices
        for ticker in s["tickers"][:3]:
            row = tk.Frame(outcome_frame, bg=PALETTE["bg_alt"])
            row.pack(fill="x", padx=10, pady=2)

            tk.Label(row, text=f"${ticker}", bg=PALETTE["bg_alt"],
                     fg=PALETTE["text"], font=(FONT_DISPLAY, 10, "bold"),
                     width=8, anchor="w").pack(side="left")

            status = tk.Label(row, text="Loading review…",
                              bg=PALETTE["bg_alt"], fg=PALETTE["text_mute"],
                              font=(FONT_DISPLAY, 9))
            status.pack(side="left", padx=(8, 0))

            self._async_load_outcome(s, ticker, status)

        # Add a tiny bottom padding
        tk.Frame(outcome_frame, bg=PALETTE["bg_alt"], height=4).pack(fill="x")

    def _async_load_outcome(self, story, ticker, label_widget):
        """Background fetch of headline-time + current price for one ticker."""
        def worker():
            story_id = story.get("db_id")
            if not story_id:
                # Try lookup via story_key
                try:
                    conn = db_connect()
                    cur = conn.execute("SELECT id FROM stories WHERE story_key=?",
                                       (story.get("story_key", ""),))
                    row = cur.fetchone()
                    conn.close()
                    story_id = row[0] if row else None
                except Exception:
                    story_id = None
            headline_info = db_get_headline_price(story_id, ticker) if story_id else None
            current = fetch_quote(ticker)

            def update():
                try:
                    if not current:
                        label_widget.config(text="Current price unavailable", fg=PALETTE["text_mute"])
                        return
                    if not headline_info:
                        label_widget.config(
                            text=f"${current['price']:.2f} now  ·  No headline price recorded",
                            fg=PALETTE["text_dim"])
                        return
                    hp = headline_info["price"]
                    cp = current["price"]
                    delta = cp - hp
                    delta_pct = (delta / hp * 100) if hp else 0
                    color = PALETTE["accent_2"] if delta_pct >= 0 else PALETTE["danger"]
                    sign = "+" if delta_pct >= 0 else ""
                    label_widget.config(
                        text=f"${hp:.2f} → ${cp:.2f}     {sign}{delta_pct:.2f}%   ({sign}${delta:.2f})",
                        fg=color, font=(FONT_DISPLAY, 10, "bold"))
                except tk.TclError:
                    pass
            label_widget.after(0, update)

        threading.Thread(target=worker, daemon=True).start()


# ─────────────────────────── MAIN WINDOW ──────────────────────────────────────

class PreMarketScanner(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pre-Market Bullish News Scanner")
        self.geometry("1240x820")
        self.minsize(960, 620)
        self.configure(bg=PALETTE["bg"])

        self.stories = []
        self.filtered = []
        self.watchlist = set()
        self.active_categories = set(ALL_CATEGORIES)
        self.min_score = tk.IntVar(value=20)
        self.show_only_watchlist = tk.BooleanVar(value=False)
        self.auto_refresh = tk.BooleanVar(value=True)
        self.fetch_thread = None
        self.fetch_queue = queue.Queue()
        self.next_refresh_at = None
        self._refresh_job = None

        self._load_settings()
        self._build_ui()
        self._schedule_refresh(initial=True)
        self._tick_clock()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Check for updates on launch (non-blocking, won't notify unless update found)
        if UPDATE_CHECK_ON_LAUNCH:
            self.after(2500, self._silent_update_check_on_launch)

        # Background DB housekeeping
        threading.Thread(target=lambda: db_purge_old(days=14), daemon=True).start()

    def _load_settings(self):
        if not os.path.exists(SETTINGS_FILE):
            return
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.watchlist = set(data.get("watchlist", []))
            self.min_score.set(int(data.get("min_score", 20)))
            cats = data.get("categories")
            if cats:
                self.active_categories = set(c for c in cats if c in ALL_CATEGORIES)
            self.show_only_watchlist.set(bool(data.get("only_watchlist", False)))
            self.auto_refresh.set(bool(data.get("auto_refresh", True)))
        except Exception as e:
            LOGGER.warning(f"Failed to load settings: {e}")

    def _save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "watchlist": sorted(self.watchlist),
                    "min_score": int(self.min_score.get()),
                    "categories": sorted(self.active_categories),
                    "only_watchlist": bool(self.show_only_watchlist.get()),
                    "auto_refresh": bool(self.auto_refresh.get()),
                }, f, indent=2)
        except Exception as e:
            LOGGER.warning(f"Failed to save settings: {e}")

    def _build_ui(self):
        # Header
        header = tk.Frame(self, bg=PALETTE["bg_alt"], height=78)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)
        # accent stripe under header
        tk.Frame(self, bg=PALETTE["border"], height=1).pack(side="top", fill="x")

        hleft = tk.Frame(header, bg=PALETTE["bg_alt"])
        hleft.pack(side="left", padx=24, pady=14)
        tk.Label(hleft, text="◆  BULL SCANNER",
                 bg=PALETTE["bg_alt"], fg=PALETTE["accent"],
                 font=(FONT_DISPLAY, 17, "bold")
                 ).pack(anchor="w")
        tk.Label(hleft, text="Pre-market catalyst detection  ·  4:00–9:30 AM ET",
                 bg=PALETTE["bg_alt"], fg=PALETTE["text_mute"],
                 font=(FONT_DISPLAY, 9)).pack(anchor="w", pady=(2, 0))

        status_frame = tk.Frame(header, bg=PALETTE["bg_alt"])
        status_frame.pack(side="right", padx=24, pady=14)
        self.clock_lbl = tk.Label(status_frame, text="",
                                  bg=PALETTE["bg_alt"], fg=PALETTE["text"],
                                  font=(FONT_DISPLAY, 13, "bold"))
        self.clock_lbl.pack(anchor="e")
        self.status_lbl = tk.Label(status_frame, text="Idle",
                                    bg=PALETTE["bg_alt"], fg=PALETTE["text_dim"],
                                    font=(FONT_DISPLAY, 9))
        self.status_lbl.pack(anchor="e", pady=(2, 0))

        # Body
        body = tk.Frame(self, bg=PALETTE["bg"])
        body.pack(fill="both", expand=True)
        self._build_sidebar(body)
        self._build_results(body)

        # Footer
        footer = tk.Frame(self, bg=PALETTE["bg_alt"], height=26)
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)
        tk.Label(footer, text=f"  Logging: {LOG_FILE}",
                 bg=PALETTE["bg_alt"], fg=PALETTE["text_mute"],
                 font=(FONT_DISPLAY, 8)).pack(side="left", padx=12, pady=6)
        tk.Label(footer, text=f"v{APP_VERSION}  ·  ",
                 bg=PALETTE["bg_alt"], fg=PALETTE["text_mute"],
                 font=(FONT_DISPLAY, 8)).pack(side="right", padx=0, pady=6)
        self.count_lbl = tk.Label(footer, text="0 stories",
                                  bg=PALETTE["bg_alt"], fg=PALETTE["text_mute"],
                                  font=(FONT_DISPLAY, 8))
        self.count_lbl.pack(side="right", padx=12, pady=6)

    def _build_sidebar(self, parent):
        side = tk.Frame(parent, bg=PALETTE["bg_alt"], width=280)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        # divider
        tk.Frame(parent, bg=PALETTE["border"], width=1).pack(side="left", fill="y")

        # Refresh button
        self.refresh_btn = tk.Button(side, text="⟳   REFRESH NOW",
            bg=PALETTE["accent"], fg="#0a0e1c",
            font=(FONT_DISPLAY, 10, "bold"), bd=0, relief="flat",
            activebackground=PALETTE["accent_hi"], cursor="hand2",
            command=self._manual_refresh, padx=10, pady=12)
        self.refresh_btn.pack(fill="x", padx=18, pady=(20, 8))

        tk.Checkbutton(side, text="Auto-refresh every 5 min (pre-market)",
            variable=self.auto_refresh, bg=PALETTE["bg_alt"],
            fg=PALETTE["text_dim"], selectcolor=PALETTE["panel"],
            activebackground=PALETTE["bg_alt"], activeforeground=PALETTE["text"],
            font=(FONT_DISPLAY, 8), anchor="w",
            command=self._on_auto_refresh_toggle
            ).pack(fill="x", padx=18, pady=(0, 8))

        # Watchlist
        self._section_header(side, "WATCHLIST")
        tk.Label(side, text="Tickers to track (comma-separated):",
            bg=PALETTE["bg_alt"], fg=PALETTE["text_mute"],
            font=(FONT_DISPLAY, 8), anchor="w", justify="left"
            ).pack(fill="x", padx=18, pady=(0, 4))
        self.watch_entry = tk.Entry(side, bg=PALETTE["panel"], fg=PALETTE["text"],
            insertbackground=PALETTE["text"], relief="flat",
            font=(FONT_DISPLAY, 10))
        self.watch_entry.pack(fill="x", padx=18, ipady=7)
        if self.watchlist:
            self.watch_entry.insert(0, ", ".join(sorted(self.watchlist)))
        self.watch_entry.bind("<Return>", lambda e: self._update_watchlist())

        wbtn = tk.Frame(side, bg=PALETTE["bg_alt"])
        wbtn.pack(fill="x", padx=18, pady=(8, 4))
        tk.Button(wbtn, text="Apply", bg=PALETTE["accent_2"], fg="#0a0e1c",
            font=(FONT_DISPLAY, 9, "bold"), bd=0, relief="flat", cursor="hand2",
            command=self._update_watchlist
            ).pack(side="left", fill="x", expand=True, padx=(0, 4), ipady=5)
        tk.Button(wbtn, text="Clear", bg=PALETTE["panel"], fg=PALETTE["text_dim"],
            font=(FONT_DISPLAY, 9), bd=0, relief="flat", cursor="hand2",
            command=self._clear_watchlist
            ).pack(side="left", fill="x", expand=True, ipady=5)

        tk.Checkbutton(side, text="Show only watchlist matches",
            variable=self.show_only_watchlist, bg=PALETTE["bg_alt"],
            fg=PALETTE["text_dim"], selectcolor=PALETTE["panel"],
            activebackground=PALETTE["bg_alt"], activeforeground=PALETTE["text"],
            font=(FONT_DISPLAY, 8), anchor="w",
            command=self._apply_filters
            ).pack(fill="x", padx=18, pady=(4, 0))

        # Min score
        self._section_header(side, "MIN BULL SCORE")
        srow = tk.Frame(side, bg=PALETTE["bg_alt"])
        srow.pack(fill="x", padx=18)
        self.score_value_lbl = tk.Label(srow, text=f"{self.min_score.get()}+",
            bg=PALETTE["bg_alt"], fg=PALETTE["accent"],
            font=(FONT_DISPLAY, 16, "bold"))
        self.score_value_lbl.pack(side="left")
        tk.Label(srow, text="threshold", bg=PALETTE["bg_alt"],
            fg=PALETTE["text_mute"], font=(FONT_DISPLAY, 8)
            ).pack(side="left", padx=6, pady=(10, 0))

        ttk.Scale(side, from_=0, to=100, orient="horizontal",
            variable=self.min_score, command=self._on_score_change
            ).pack(fill="x", padx=18, pady=(4, 10))

        # Categories
        self._section_header(side, "CATALYST CATEGORIES")
        self.category_vars = {}
        cat_frame = tk.Frame(side, bg=PALETTE["bg_alt"])
        cat_frame.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        for cat in ALL_CATEGORIES:
            var = tk.BooleanVar(value=cat in self.active_categories)
            self.category_vars[cat] = var
            row = tk.Frame(cat_frame, bg=PALETTE["bg_alt"])
            row.pack(fill="x", anchor="w", pady=1)
            swatch = tk.Frame(row, bg=CATEGORY_COLORS.get(cat, PALETTE["accent"]),
                              width=10, height=14)
            swatch.pack(side="left", padx=(0, 8), pady=2)
            swatch.pack_propagate(False)
            tk.Checkbutton(row, text=cat, variable=var,
                bg=PALETTE["bg_alt"], fg=PALETTE["text"],
                selectcolor=PALETTE["panel"],
                activebackground=PALETTE["bg_alt"],
                activeforeground=PALETTE["text"],
                font=(FONT_DISPLAY, 9), anchor="w",
                command=self._on_category_change
                ).pack(side="left", anchor="w")

        # Updater section
        self._section_header(side, "APP UPDATES")
        self.update_btn = tk.Button(side, text="⤓  CHECK FOR UPDATES",
            bg=PALETTE["panel"], fg=PALETTE["accent"],
            font=(FONT_DISPLAY, 9, "bold"), bd=0, relief="flat",
            activebackground=PALETTE["panel_hover"], cursor="hand2",
            command=self._manual_update_check, padx=10, pady=8)
        self.update_btn.pack(fill="x", padx=18, pady=(0, 16))

    def _section_header(self, parent, text):
        tk.Frame(parent, bg=PALETTE["border"], height=1).pack(fill="x", padx=14, pady=(18, 8))
        tk.Label(parent, text=text, bg=PALETTE["bg_alt"],
            fg=PALETTE["text_mute"], font=(FONT_DISPLAY, 8, "bold"),
            anchor="w").pack(fill="x", padx=18, pady=(0, 6))

    def _build_results(self, parent):
        self._results_parent = parent
        main = tk.Frame(parent, bg=PALETTE["bg"])
        main.pack(side="right", fill="both", expand=True)
        self._results_main = main

        # Tabs row
        top = tk.Frame(main, bg=PALETTE["bg"])
        top.pack(fill="x", padx=24, pady=(18, 0))

        self.view_mode = tk.StringVar(value="live")

        self.tab_live_btn = tk.Button(top, text="📰  LIVE STORIES",
            bg=PALETTE["accent"], fg="#0a0e1c",
            font=(FONT_DISPLAY, 11, "bold"), bd=0, relief="flat",
            cursor="hand2", activebackground=PALETTE["accent_hi"],
            command=lambda: self._set_view("live"),
            padx=14, pady=8)
        self.tab_live_btn.pack(side="left", padx=(0, 4))

        self.tab_outcomes_btn = tk.Button(top, text="📊  OUTCOMES",
            bg=PALETTE["panel"], fg=PALETTE["text_dim"],
            font=(FONT_DISPLAY, 11, "bold"), bd=0, relief="flat",
            cursor="hand2", activebackground=PALETTE["panel_hover"],
            command=lambda: self._set_view("outcomes"),
            padx=14, pady=8)
        self.tab_outcomes_btn.pack(side="left", padx=(0, 4))

        self.view_hint = tk.Label(top, text="   Click any story for details · pin tickers to your watchlist",
                 bg=PALETTE["bg"], fg=PALETTE["text_mute"],
                 font=(FONT_DISPLAY, 9))
        self.view_hint.pack(side="left", pady=(6, 0))

        # Divider line beneath tabs
        tk.Frame(main, bg=PALETTE["border"], height=1).pack(fill="x", padx=24, pady=(10, 0))

        list_frame = tk.Frame(main, bg=PALETTE["bg"])
        list_frame.pack(fill="both", expand=True, padx=18, pady=(10, 14))

        self.canvas = tk.Canvas(list_frame, bg=PALETTE["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.cards_frame = tk.Frame(self.canvas, bg=PALETTE["bg"])
        self.canvas_window = self.canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.cards_frame.bind("<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        # Throttle width updates so dragging the window doesn't thrash all cards
        self._canvas_resize_job = None
        def _on_canvas_resize(e):
            if self._canvas_resize_job is not None:
                try: self.after_cancel(self._canvas_resize_job)
                except Exception: pass
            w = e.width
            self._canvas_resize_job = self.after(
                60,
                lambda: self.canvas.itemconfig(self.canvas_window, width=w),
            )
        self.canvas.bind("<Configure>", _on_canvas_resize)

        self.canvas.bind_all("<MouseWheel>",
            lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

        tk.Label(self.cards_frame,
            text="\n\n\n No stories yet. Click ⟳ REFRESH NOW to scan feeds.\n",
            bg=PALETTE["bg"], fg=PALETTE["text_mute"],
            font=(FONT_DISPLAY, 11), justify="center").pack(pady=40)

    # ─────────── Filter handlers ───────────
    def _on_score_change(self, *_):
        self.score_value_lbl.config(text=f"{self.min_score.get()}+")
        self._apply_filters()
        self._save_settings()

    def _on_category_change(self):
        self.active_categories = {c for c, v in self.category_vars.items() if v.get()}
        self._apply_filters()
        self._save_settings()

    def _on_auto_refresh_toggle(self):
        self._save_settings()
        self._schedule_refresh()

    def _update_watchlist(self):
        raw = self.watch_entry.get().strip().upper()
        if not raw:
            self.watchlist = set()
        else:
            parts = re.split(r"[,\s]+", raw)
            self.watchlist = {p.strip("$").strip() for p in parts if p.strip()}
        self.watch_entry.delete(0, tk.END)
        self.watch_entry.insert(0, ", ".join(sorted(self.watchlist)))
        self._rescore_watch_matches()
        self._apply_filters()
        self._save_settings()

    def _clear_watchlist(self):
        self.watchlist = set()
        self.watch_entry.delete(0, tk.END)
        self.show_only_watchlist.set(False)
        self._rescore_watch_matches()
        self._apply_filters()
        self._save_settings()

    def _rescore_watch_matches(self):
        for s in self.stories:
            s["watch_match"] = bool(self.watchlist & set(s.get("tickers", [])))

    def _apply_filters(self):
        min_score = int(self.min_score.get())
        only_watch = self.show_only_watchlist.get()
        cats = self.active_categories
        view = self.view_mode.get() if hasattr(self, "view_mode") else "live"

        filtered = []
        for s in self.stories:
            # Outcomes view: only show persisted stories that have tickers (so review makes sense)
            if view == "outcomes":
                if not s.get("persisted"):
                    continue
                if not s.get("tickers"):
                    continue
            if s["score"] < min_score:
                continue
            s_cats = set(s.get("catalysts", []))
            if s_cats and not (s_cats & cats):
                continue
            if only_watch and not s.get("watch_match"):
                continue
            filtered.append(s)

        if view == "outcomes":
            # Sort by published date — newest first — so latest catalysts are reviewed first
            filtered.sort(key=lambda x: -(x["published"].timestamp() if x.get("published") else 0))
        else:
            filtered.sort(key=lambda x: (
                not x.get("watch_match", False),
                -x["score"],
                -(x["published"].timestamp() if x.get("published") else 0),
            ))
        self.filtered = filtered
        self._render_cards()

    def _render_cards(self):
        for child in self.cards_frame.winfo_children():
            child.destroy()

        view = self.view_mode.get() if hasattr(self, "view_mode") else "live"

        if not self.filtered:
            empty_msg = (
                "\n\n\n No tracked outcomes yet.\n "
                "Stories with score 30+ get their headline prices saved.\n "
                "Check back later to see how they played out.\n"
                if view == "outcomes"
                else "\n\n\n No stories match your filters.\n Try lowering the bull score or expanding categories.\n"
            )
            tk.Label(self.cards_frame, text=empty_msg,
                bg=PALETTE["bg"], fg=PALETTE["text_mute"],
                font=(FONT_DISPLAY, 11), justify="center"
                ).pack(pady=40)
        else:
            for s in self.filtered[:MAX_STORIES]:
                StoryCard(self.cards_frame, s,
                          on_click=self._on_card_click,
                          on_pin=self._pin_story_tickers,
                          watchlist=self.watchlist,
                          show_outcome=(view == "outcomes")
                          ).pack(fill="x", padx=6, pady=4)

        view_label = "outcomes" if view == "outcomes" else "stories"
        self.count_lbl.config(
            text=f"Showing {len(self.filtered)} {view_label}  "
        )
        self.canvas.yview_moveto(0)

    def _pin_story_tickers(self, story):
        """Add this story's tickers to the watchlist."""
        new_tickers = set(story.get("tickers", [])[:3])
        if not new_tickers:
            return
        added = new_tickers - self.watchlist
        self.watchlist |= new_tickers
        # Refresh the entry box
        self.watch_entry.delete(0, tk.END)
        self.watch_entry.insert(0, ", ".join(sorted(self.watchlist)))
        self._rescore_watch_matches()
        self._apply_filters()
        self._save_settings()
        if added:
            LOGGER.info(f"PINNED to watchlist: {','.join(sorted(added))}")

    def _set_view(self, mode):
        """Switch between 'live' and 'outcomes' views."""
        self.view_mode.set(mode)
        if mode == "live":
            self.tab_live_btn.config(bg=PALETTE["accent"], fg="#0a0e1c")
            self.tab_outcomes_btn.config(bg=PALETTE["panel"], fg=PALETTE["text_dim"])
            self.view_hint.config(text="   Click any story for details · pin tickers to your watchlist")
        else:
            self.tab_live_btn.config(bg=PALETTE["panel"], fg=PALETTE["text_dim"])
            self.tab_outcomes_btn.config(bg=PALETTE["accent"], fg="#0a0e1c")
            self.view_hint.config(text="   Tracked stories with price-since-headline. Review after market open.")
        self._apply_filters()

    def _on_card_click(self, story):
        LOGGER.info(
            f"OPENED | score={story['score']} | "
            f"tickers={','.join(story.get('tickers', [])) or '-'} | "
            f"cats={','.join(story.get('catalysts', [])) or '-'} | "
            f"{story['source']} | {story['title']}"
        )
        try:
            self._show_detail_panel(story)
        except Exception as e:
            LOGGER.exception(f"Failed to show detail panel: {e}")

    def _show_detail_panel(self, story):
        """Hide the results area and overlay the detail panel inside the main window."""
        # Hide the results main frame
        if hasattr(self, "_results_main"):
            self._results_main.pack_forget()
        # Tear down any previous detail
        if hasattr(self, "_detail_panel") and self._detail_panel:
            try: self._detail_panel.destroy()
            except Exception: pass
        # Build new panel inside the same parent
        self._detail_panel = StoryDetailPanel(
            self._results_parent, story, on_close=self._hide_detail_panel)
        self._detail_panel.pack(side="right", fill="both", expand=True)

    def _hide_detail_panel(self):
        if hasattr(self, "_detail_panel") and self._detail_panel:
            try: self._detail_panel.destroy()
            except Exception: pass
            self._detail_panel = None
        if hasattr(self, "_results_main"):
            self._results_main.pack(side="right", fill="both", expand=True)

    # ─────────── Fetch ───────────
    def _manual_refresh(self):
        self._start_fetch()

    def _start_fetch(self):
        if self.fetch_thread and self.fetch_thread.is_alive():
            return
        self.refresh_btn.config(state="disabled", text="Fetching…")
        self.status_lbl.config(text="Fetching feeds…", fg=PALETTE["warn"])
        self.fetch_thread = threading.Thread(target=self._fetch_worker, daemon=True)
        self.fetch_thread.start()
        self.after(200, self._poll_fetch_queue)

    def _fetch_worker(self):
        try:
            def prog(done, total, source):
                self.fetch_queue.put(("progress", (done, total, source)))
            stories = fetch_all_feeds(progress_cb=prog)
            stories = dedupe_stories(stories)
            for s in stories:
                score, cats, breakdown = score_story(s["title"], s.get("summary", ""))
                s["score"] = score
                s["catalysts"] = cats
                s["breakdown"] = breakdown
                s["tickers"] = extract_tickers(f"{s['title']} {s.get('summary', '')}")
                s["watch_match"] = bool(self.watchlist & set(s["tickers"]))
                s["story_key"] = re.sub(r"[^a-z0-9]+", "", s["title"].lower())[:120]

                # Persist high-scoring stories + capture headline-time prices
                if score >= PERSIST_MIN_SCORE:
                    story_id = db_save_story(s)
                    s["db_id"] = story_id
                    if story_id and s["tickers"]:
                        for t in s["tickers"][:3]:  # cap to first 3 tickers
                            # Only capture once per (story, ticker)
                            existing = db_get_headline_price(story_id, t)
                            if existing is None:
                                q = fetch_quote(t)
                                if q:
                                    db_save_snapshot(story_id, t, q, "headline")

            stories.sort(
                key=lambda x: x.get("published") or datetime.now(timezone.utc),
                reverse=True
            )

            # Merge with persisted stories from this and previous session
            persisted = db_load_stories(days_back=2)
            new_keys = {s["story_key"] for s in stories}
            for p in persisted:
                if p["story_key"] not in new_keys:
                    # Add persisted-only stories so user can see yesterday's catalysts
                    p["breakdown"] = []  # not stored, fine
                    p["watch_match"] = bool(self.watchlist & set(p.get("tickers", [])))
                    stories.append(p)

            self.fetch_queue.put(("done", stories))
        except Exception as e:
            LOGGER.exception("Fetch worker error")
            self.fetch_queue.put(("error", str(e)))

    def _poll_fetch_queue(self):
        try:
            while True:
                kind, payload = self.fetch_queue.get_nowait()
                if kind == "progress":
                    done, total, source = payload
                    self.status_lbl.config(
                        text=f"Fetching {source} ({done}/{total})…",
                        fg=PALETTE["warn"])
                elif kind == "done":
                    self._on_fetch_complete(payload)
                    return
                elif kind == "error":
                    self.refresh_btn.config(state="normal", text="⟳   REFRESH NOW")
                    self.status_lbl.config(text=f"Error: {payload}", fg=PALETTE["danger"])
                    return
        except queue.Empty:
            pass
        self.after(200, self._poll_fetch_queue)

    def _on_fetch_complete(self, stories):
        prev_keys = {self._story_key(s) for s in self.stories}
        self.stories = stories

        new_alerts = []
        for s in stories:
            if self._story_key(s) in prev_keys:
                continue
            if s["score"] >= 40 or s.get("watch_match"):
                new_alerts.append(s)

        for s in new_alerts:
            LOGGER.info(
                f"ALERT | score={s['score']} | "
                f"tickers={','.join(s.get('tickers', [])) or '-'} | "
                f"cats={','.join(s.get('catalysts', [])) or '-'} | "
                f"watch={'Y' if s.get('watch_match') else 'N'} | "
                f"{s['source']} | {s['title']} | {s.get('link', '')}"
            )

        self._apply_filters()

        now_str = datetime.now(ET_ZONE).strftime("%I:%M:%S %p ET")
        self.status_lbl.config(
            text=f"Last refresh: {now_str}  ·  {len(new_alerts)} new alerts",
            fg=PALETTE["accent_2"],
        )
        self.refresh_btn.config(state="normal", text="⟳   REFRESH NOW")
        self._schedule_refresh()

    @staticmethod
    def _story_key(s):
        return re.sub(r"[^a-z0-9]+", "", s["title"].lower())[:120]

    def _schedule_refresh(self, initial=False):
        if self._refresh_job is not None:
            try: self.after_cancel(self._refresh_job)
            except Exception: pass
            self._refresh_job = None

        if initial:
            self.after(800, self._start_fetch)
            return

        if not self.auto_refresh.get():
            self.next_refresh_at = None
            return

        if not is_premarket_now():
            self._refresh_job = self.after(60_000, self._schedule_refresh)
            self.next_refresh_at = None
            return

        self.next_refresh_at = datetime.now(timezone.utc) + timedelta(seconds=REFRESH_INTERVAL_SEC)
        self._refresh_job = self.after(REFRESH_INTERVAL_SEC * 1000, self._auto_refresh_tick)

    def _auto_refresh_tick(self):
        if not self.auto_refresh.get():
            self._schedule_refresh()
            return
        if not is_premarket_now():
            self._schedule_refresh()
            return
        self._start_fetch()

    def _tick_clock(self):
        now_et = datetime.now(ET_ZONE)
        is_pm = is_premarket_now()
        marker = "● PRE-MARKET" if is_pm else "○ off-hours"
        marker_color = PALETTE["accent_2"] if is_pm else PALETTE["text_mute"]
        self.clock_lbl.config(text=now_et.strftime("%I:%M:%S %p ET"))

        cur = self.status_lbl.cget("text")
        if "Fetching" not in cur and "Error" not in cur:
            extra = ""
            if self.next_refresh_at:
                secs = int((self.next_refresh_at - datetime.now(timezone.utc)).total_seconds())
                if secs > 0:
                    extra = f"  ·  next refresh in {secs // 60}m {secs % 60:02d}s"
            self.status_lbl.config(text=f"{marker}{extra}", fg=marker_color)
        self.after(1000, self._tick_clock)

    def _on_close(self):
        self._save_settings()
        LOGGER.info("Scanner closed.")
        self.destroy()

    # ─────────── Auto-updater ───────────
    def _silent_update_check_on_launch(self):
        """Background check on launch. Doesn't bother user if no update."""
        def worker():
            result = check_for_update()
            self.after(0, lambda: self._handle_update_result(result, silent=True))
        threading.Thread(target=worker, daemon=True).start()

    def _manual_update_check(self):
        """Triggered by the sidebar button — always shows a result."""
        self.update_btn.config(state="disabled", text="Checking…")
        def worker():
            result = check_for_update()
            self.after(0, lambda: self._handle_update_result(result, silent=False))
        threading.Thread(target=worker, daemon=True).start()

    def _handle_update_result(self, result, silent):
        try: self.update_btn.config(state="normal", text="⤓  CHECK FOR UPDATES")
        except Exception: pass

        if result["available"]:
            remote_bytes = result["remote_bytes"]
            kb = len(remote_bytes) // 1024
            answer = messagebox.askyesno(
                "Update Available",
                f"A new version of Bull Scanner is available "
                f"({kb} KB).\n\n"
                f"Install now? The app will back up your current version "
                f"and restart automatically.",
                parent=self,
            )
            if answer:
                self._install_update(remote_bytes)
            return

        # No update available — only show message if user asked
        if not silent:
            messagebox.showinfo("No Updates",
                f"{result.get('reason', 'You are running the latest version.')}\n\n"
                f"Current version: v{APP_VERSION}",
                parent=self)
        else:
            LOGGER.info(f"Launch update check: {result.get('reason', 'no update')}")

    def _install_update(self, remote_bytes):
        try:
            local_path = apply_update(remote_bytes)
        except Exception as e:
            messagebox.showerror("Update Failed",
                f"Couldn't install the update:\n\n{e}\n\n"
                f"Your current version is unchanged.",
                parent=self)
            return

        messagebox.showinfo("Update Installed",
            f"Update installed successfully.\n\n"
            f"The app will restart now.\n\n"
            f"(Old version backed up to: {os.path.basename(local_path)}.bak)",
            parent=self)
        self._save_settings()
        LOGGER.info("Update installed; restarting.")
        restart_app()


def main():
    LOGGER.info("Pre-Market Scanner starting up.")
    app = PreMarketScanner()
    style = ttk.Style(app)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("Horizontal.TScale",
        background=PALETTE["bg_alt"],
        troughcolor=PALETTE["panel"])
    style.configure("Vertical.TScrollbar",
        background=PALETTE["panel"],
        troughcolor=PALETTE["bg"],
        bordercolor=PALETTE["bg"],
        arrowcolor=PALETTE["text_dim"])
    app.mainloop()


if __name__ == "__main__":
    main()
