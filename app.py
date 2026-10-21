import streamlit as st
import pandas as pd
import requests
import datetime
from zoneinfo import ZoneInfo
import sqlite3
import uuid

# ================= 1. PAGE SETUP & THEME =================
st.set_page_config(page_title="Knowledge Hub", layout="wide", page_icon="⚡")

st.markdown("""
<style>
    .stApp { background-color: #0b0e14; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    div[data-testid="stMetric"] { background-color: #121824; border: 1px solid #1e293b; border-radius: 8px; padding: 10px 14px; }
    div[data-testid="stMetricLabel"] { font-size: 0.8rem; color: #94a3b8; }
    div[data-testid="stMetricValue"] { font-size: 1.15rem; font-weight: 700; }
    .card { background-color: #121824; border: 1px solid #1e293b; border-radius: 10px; padding: 16px 20px; margin-bottom: 14px; }
    .badge-buy { background-color: rgba(0, 208, 156, 0.15); color: #00d09c; border: 1px solid #00d09c; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
    .badge-sell { background-color: rgba(235, 91, 60, 0.15); color: #eb5b3c; border: 1px solid #eb5b3c; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
</style>
""", unsafe_allow_html=True)

ist = ZoneInfo("Asia/Kolkata")
now = datetime.datetime.now(ist)

# Read Telegram Secrets safely from Streamlit Cloud
bot_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")

# ================= 2. DATABASE (SQLITE) =================
def init_db():
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY,
            strategy TEXT,
            symbol TEXT,
            action TEXT,
            underlying_price REAL,
            entry REAL,
            sl REAL,
            tgt1 REAL,
            tgt2 REAL,
            tgt3 REAL,
            time TEXT,
            status TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_signals():
    conn = sqlite3.connect("knowledge_hub.db")
    df = pd.read_sql_query("SELECT * FROM signals ORDER BY rowid DESC", conn)
    conn.close()
    return df.to_dict(orient="records")

def insert_signal(sig):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (sig['id'], sig['strategy'], sig['symbol'], sig['action'], 
          sig['underlying_price'], sig['entry'], sig['sl'], 
          sig['tgt1'], sig['tgt2'], sig['tgt3'], sig['time'], sig['status']))
    conn.commit()
    conn.close()

init_db()

# Pre-populate 1 signal if empty
if len(get_signals()) == 0:
    insert_signal({
        "id": "EMM_01",
        "strategy": "EMMANI",
        "symbol": "NIFTY 24800 CE",
        "action": "BUY",
        "underlying_price": 24855.0,
        "entry": 140.0,
        "sl": 115.0,
        "tgt1": 165.0,
        "tgt2": 190.0,
        "tgt3": 215.0,
        "time": now.strftime("%I:%M %p"),
        "status": "Active"
    })

# Session state for paper trades
if "paper_positions" not in st.session_state:
    st.session_state.paper_positions = []
if "paper_balance" not in st.session_state:
    st.session_state.paper_balance = 100000.0

# ================= 3. HEADER & LIVE INDICES =================
c1, c2 = st.columns([3, 1])
with c1:
    st.markdown("<h2 style='color:#00d09c; margin:0;'>⚡ KNOWLEDGE HUB TERMINAL</h2>", unsafe_allow_html=True)
    st.caption("Indian Market Intelligence & Personal Quantitative Trade Desk")
with c2:
    st.markdown(f"<div style='text-align:right; color:#94a3b8; font-size:0.9rem;'>IST: <b>{now.strftime('%I:%M:%S %p')}</b></div>", unsafe_allow_html=True)

@st.cache_data(ttl=60)
def fetch_indices():
    indices = {
        "NIFTY 50": {"sym": "^NSEI", "val": 24855.30, "chg": "+0.45%"},
        "BANK NIFTY": {"sym": "^NSEBANK", "val": 52315.80, "chg": "+0.62%"},
        "SENSEX": {"sym": "^BSESN", "val": 81450.10, "chg": "+0.38%"},
        "INDIA VIX": {"sym": "^INDIAVIX", "val": 13.10, "chg": "-1.85%"}
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    for k, v in indices.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{v['sym']}?interval=1d"
            res = requests.get(url, headers=headers, timeout=2).json()
            meta = res["chart"]["result"][0]["meta"]
            curr = round(meta["regularMarketPrice"], 2)
            prev = round(meta["chartPreviousClose"], 2)
            pct = round(((curr - prev) / prev) * 100, 2)
            indices[k]["val"] = curr
            indices[k]["chg"] = f"{'+' if pct >= 0 else ''}{pct}%"
        except:
            pass
    return indices

idx = fetch_indices()
t1, t2, t3, t4 = st.columns(4)
t1.metric("NIFTY 50", f"₹{idx['NIFTY 50']['val']}", idx['NIFTY 50']['chg'])
t2.metric("BANK NIFTY", f"₹{idx['BANK NIFTY']['val']}", idx['BANK NIFTY']['chg'])
t3.metric("SENSEX", f"₹{idx['SENSEX']['val']}", idx['SENSEX']['chg'])
t4.metric("INDIA VIX", f"{idx['INDIA VIX']['val']}", idx['INDIA VIX']['chg'], delta_color="inverse")

st.markdown("---")

# ================= 4. THE 5 MAIN TABS =================
t_dash, t_stocks, t_strat, t_courses, t_ind = st.tabs([
    "1. 📊 Dashboard", 
    "2. 🔍 Stocks in Focus", 
    "3. 🎯 Strategies", 
    "4. 📚 Courses", 
    "5. 📐 Indicators"
])

# ----- TAB 1: DASHBOARD -----
with t_dash:
    st.subheader("Market Summary & Live Status")
    
    col_bal, col_pos = st.columns(2)
    col_bal.metric("Paper Capital Available", f"₹{st.session_state.paper_balance:,.2f}")
    
    total_unrealized = sum([(p["LTP"] - p["entry"]) * p["qty"] for p in st.session_state.paper_positions])
    col_pos.metric("Total Open P&L", f"₹{total_unrealized:+,.2f}", delta_color="normal" if total_unrealized >= 0 else "inverse")

    st.markdown("### 📲 Telegram Integration Check")
    if st.button("Send Test Message to My Telegram"):
        if bot_token and chat_id:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": "⚡ <b>Knowledge Hub Alert</b>: Your cloud connection is working perfectly!",
                "parse_mode": "HTML"
            }
            res = requests.post(url, json=payload)
            if res.status_code == 200:
                st.success("✅ Delivered! Check your phone.")
            else:
                st.error(f"Telegram error: {res.text}")
        else:
            st.warning("Please configure your Telegram secrets in Streamlit Cloud Settings.")

# ----- TAB 2: STOCKS IN FOCUS -----
with t_stocks:
    st.subheader("F&O Universe Watchlist")
    st.dataframe(pd.DataFrame([
        {"Stock": "RELIANCE", "LTP": "₹2,985.40", "Change": "+1.75%", "Volume": "High", "Type": "F&O Active"},
        {"Stock": "HDFCBANK", "LTP": "₹1,642.10", "Change": "-0.35%", "Volume": "Average", "Type": "F&O Active"},
        {"Stock": "ICICIBANK", "LTP": "₹1,124.00", "Change": "+2.05%", "Volume": "High", "Type": "F&O Active"},
        {"Stock": "TCS", "LTP": "₹3,920.00", "Change": "+0.80%", "Volume": "Normal", "Type": "F&O Active"}
    ]), use_container_width=True)

# ----- TAB 3: STRATEGIES -----
with t_strat:
    st.subheader("Active Quantitative Signals")
    signals = get_signals()

    for s in signals:
        badge = "badge-buy" if s["action"] == "BUY" else "badge-sell"
        st.markdown(f"""
        <div class="card">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <span class="{badge}">{s['action']}</span>
                    <b style="font-size:1.1rem; margin-left:8px;">{s['symbol']}</b>
                    <span style="color:#94a3b8; font-size:0.85rem; margin-left:10px;">Strategy: {s['strategy']}</span>
                </div>
                <div style="color:#64748b; font-size:0.8rem;">Time: {s['time']}</div>
            </div>
            <div style="display:grid; grid-template-columns: repeat(4, 1fr); margin-top:12px; gap:8px;">
                <div><span style="color:#64748b; font-size:0.75rem;">SPOT REF</span><br><b>₹{s['underlying_price']}</b></div>
                <div><span style="color:#64748b; font-size:0.75rem;">OPTION ENTRY</span><br><b>₹{s['entry']}</b></div>
                <div><span style="color:#64748b; font-size:0.75rem;">OPTION SL</span><br><b style="color:#eb5b3c;">₹{s['sl']}</b></div>
                <div><span style="color:#64748b; font-size:0.75rem;">TARGET 1 / 2</span><br><b style="color:#00d09c;">₹{s['tgt1']} / ₹{s['tgt2']}</b></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        col_a, col_b = st.columns([2, 5])
        if col_a.button(f"🎮 Take Paper Trade ({s['id']})", key=f"take_{s['id']}"):
            cost = s['entry'] * 25
            if st.session_state.paper_balance >= cost:
                st.session_state.paper_balance -= cost
                st.session_state.paper_positions.append({
                    "id": str(uuid.uuid4())[:6],
                    "symbol": s['symbol'],
                    "entry": s['entry'],
                    "LTP": s['entry'],
                    "sl": s['sl'],
                    "qty": 25,
                    "cost": cost
                })
                st.success(f"Paper trade taken for {s['symbol']}!")
                st.rerun()
            else:
                st.error("Insufficient demo capital!")

    st.markdown("---")
    st.subheader("Open Paper Positions")
    if not st.session_state.paper_positions:
        st.write("No open positions.")
    else:
        for idx_p, p in enumerate(st.session_state.paper_positions):
            pnl = (p["LTP"] - p["entry"]) * p["qty"]
            pnl_color = "#00d09c" if pnl >= 0 else "#eb5b3c"
            
            c_p1, c_p2, c_p3 = st.columns([3, 2, 2])
            c_p1.markdown(f"**{p['symbol']}** | Entry: ₹{p['entry']} | Qty: {p['qty']}")
            
            new_ltp = c_p2.number_input(f"Current Premium (₹)", value=float(p["LTP"]), step=1.0, key=f"ltp_{p['id']}")
            p["LTP"] = new_ltp

            if c_p3.button("Square Off", key=f"sq_{p['id']}"):
                returned = p["cost"] + pnl
                st.session_state.paper_balance += returned
                st.session_state.paper_positions.pop(idx_p)
                st.success(f"Position closed! Realized P&L: ₹{pnl:+,.2f}")
                st.rerun()

# ----- TAB 4: COURSES -----
with t_courses:
    st.subheader("Trading Academy")
    tier = st.radio("Select Level:", ["1. Beginner", "2. Intermediate", "3. Advanced (Options & Derivatives)"], horizontal=True)
    if "Beginner" in tier:
        st.write("Understand NSE/BSE, bid-ask spreads, order execution types, and position sizing.")
    elif "Intermediate" in tier:
        st.write("Price action structures, Supertrend mechanics, EMA crossover systems, and trend confirmation.")
    else:
        st.write("Options Delta, Theta, Gamma, Strike selection (ITM vs ATM), and volatility dynamics.")

# ----- TAB 5: INDICATORS -----
with t_ind:
    st.subheader("Indicator Library & Mathematical Formulas")
    st.markdown("""
    - **10 EMA / 20 EMA**: Exponential weights giving priority to recent closed price points.
    - **Supertrend (10, 3)**: ATR volatility bands acting as dynamic trailing stop losses.
    - **Separate Price Series Rule**: Spot points never equal option points; option delta determines actual point movement.
    """)
