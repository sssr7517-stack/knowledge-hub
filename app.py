import streamlit as st
import pandas as pd
import requests
import datetime
from zoneinfo import ZoneInfo
import sqlite3
import uuid

# Import external stock watchlist
try:
    from stock_alerts import get_external_stock_alerts
except ImportError:
    def get_external_stock_alerts():
        return []

# Auto-refresh terminal every 10 seconds for live broker tick updates
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=10000, limit=None, key="broker_stream_tick")
except ImportError:
    pass

# ================= 1. PAGE SETUP & DISCOUNT BROKER THEME =================
st.set_page_config(page_title="Knowledge Hub — Pro Broker Terminal", layout="wide", page_icon="⚡")

st.markdown("""
<style>
    /* Broker Terminal Dark Mode */
    .stApp {
        background-color: #0b0e14;
        color: #e2e8f0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
    }
    
    /* Persistent Broker Header Ribbon */
    .broker-header {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 10px;
        padding: 12px 20px;
        margin-bottom: 15px;
    }
    
    /* Metrics Styling */
    div[data-testid="stMetric"] {
        background: #161f30;
        border: 1px solid #243049;
        border-radius: 8px;
        padding: 8px 12px;
    }
    div[data-testid="stMetricLabel"] { font-size: 0.72rem; color: #94a3b8; font-weight: 600; text-transform: uppercase; }
    div[data-testid="stMetricValue"] { font-size: 1.15rem; font-weight: 800; }
    
    /* Table / Card Containers */
    .order-card {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 8px;
        padding: 14px 18px;
        margin-bottom: 10px;
    }
    
    /* Badges */
    .badge-buy { background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid #10b981; padding: 2px 7px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
    .badge-sell { background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid #ef4444; padding: 2px 7px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
    .badge-fno { background: #1f2937; color: #38bdf8; border: 1px solid #0284c7; padding: 2px 6px; border-radius: 4px; font-size: 0.72rem; font-weight: 600; }
    .badge-strat { background: #1e1b4b; color: #818cf8; border: 1px solid #4338ca; padding: 2px 6px; border-radius: 4px; font-size: 0.72rem; font-weight: 600; }

    .login-box {
        max-width: 520px;
        margin: 40px auto;
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 12px;
        padding: 28px;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
    }
</style>
""", unsafe_allow_html=True)

ist = ZoneInfo("Asia/Kolkata")
now_ist = datetime.datetime.now(ist)

# ================= 2. SECRETS CONFIGURATION =================
BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "").strip()
GOOGLE_SHEET_URL = st.secrets.get("GOOGLE_SHEET_URL", "").strip()

# ================= 3. DATABASE SETUP (USERS, POSITIONS & CLOSED P&L) =================
def init_db():
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    # Users
    c.execute("""
        CREATE TABLE IF NOT EXISTS access_users_v5 (
            phone TEXT PRIMARY KEY,
            name TEXT,
            email TEXT,
            segment TEXT,
            status TEXT,
            request_time TEXT
        )
    """)
    # Active Positions
    c.execute("""
        CREATE TABLE IF NOT EXISTS active_positions_v5 (
            pos_id TEXT PRIMARY KEY,
            user_phone TEXT,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            entry_price REAL,
            current_ltp REAL,
            cost REAL,
            open_time TEXT
        )
    """)
    # Order Book & Realized Trades
    c.execute("""
        CREATE TABLE IF NOT EXISTS order_book_v5 (
            order_id TEXT PRIMARY KEY,
            user_phone TEXT,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            price REAL,
            realized_pnl REAL,
            status TEXT,
            order_time TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# Database Functions
def save_user_request(name, phone, email, segment):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO access_users_v5 VALUES (?, ?, ?, ?, 'PENDING', ?)",
              (phone, name, email, segment, now_ist.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def check_user_access(phone):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("SELECT status, name FROM access_users_v5 WHERE phone = ?", (phone,))
    row = c.fetchone()
    conn.close()
    return row

def update_user_status(phone, new_status):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("UPDATE access_users_v5 SET status = ? WHERE phone = ?", (new_status, phone))
    conn.commit()
    conn.close()

def get_user_positions(phone):
    conn = sqlite3.connect("knowledge_hub.db")
    df = pd.read_sql_query("SELECT * FROM active_positions_v5 WHERE user_phone = ?", conn, params=(phone,))
    conn.close()
    return df.to_dict(orient="records")

def get_realized_pnl(phone):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("SELECT SUM(realized_pnl) FROM order_book_v5 WHERE user_phone = ?", (phone,))
    res = c.fetchone()[0]
    conn.close()
    return float(res) if res else 0.0

def execute_broker_order(phone, symbol, side, qty, price):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    ord_id = f"ORD_{uuid.uuid4().hex[:6].upper()}"
    pos_id = f"POS_{uuid.uuid4().hex[:6].upper()}"
    cost = qty * price
    t_str = now_ist.strftime("%I:%M:%S %p")

    # Record execution in Order Book
    c.execute("INSERT INTO order_book_v5 VALUES (?, ?, ?, ?, ?, ?, 0.0, 'COMPLETE', ?)",
              (ord_id, phone, symbol, side, qty, price, t_str))
    # Add to Active Positions
    c.execute("INSERT INTO active_positions_v5 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (pos_id, phone, symbol, side, qty, price, price, cost, t_str))
    conn.commit()
    conn.close()

def square_off_position(pos_id, phone, symbol, side, qty, entry_price, exit_price):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    ord_id = f"ORD_SQ_{uuid.uuid4().hex[:6].upper()}"
    exit_side = "SELL" if side == "BUY" else "BUY"
    pnl = (exit_price - entry_price) * qty if side == "BUY" else (entry_price - exit_price) * qty
    t_str = now_ist.strftime("%I:%M:%S %p")

    # Record exit order with realized P&L
    c.execute("INSERT INTO order_book_v5 VALUES (?, ?, ?, ?, ?, ?, ?, 'COMPLETE', ?)",
              (ord_id, phone, symbol, exit_side, qty, exit_price, pnl, t_str))
    # Remove position
    c.execute("DELETE FROM active_positions_v5 WHERE pos_id = ?", (pos_id,))
    conn.commit()
    conn.close()

def get_user_orders(phone):
    conn = sqlite3.connect("knowledge_hub.db")
    df = pd.read_sql_query("SELECT * FROM order_book_v5 WHERE user_phone = ? ORDER BY rowid DESC", conn, params=(phone,))
    conn.close()
    return df

# Poll Telegram for Admin Grant / Reject Clicks
def poll_telegram_admin_actions():
    if not BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    try:
        res = requests.get(url, timeout=3).json()
        if res.get("ok"):
            for update in res.get("result", []):
                update_id = update["update_id"]
                if "callback_query" in update:
                    cq = update["callback_query"]
                    cb_data = cq.get("data", "")
                    cb_id = cq["id"]

                    if cb_data.startswith("AUTH_YES_"):
                        target_ph = cb_data.replace("AUTH_YES_", "")
                        update_user_status(target_ph, "APPROVED")
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
                                      json={"callback_query_id": cb_id, "text": f"✅ Access Granted to {target_ph}!"})
                    elif cb_data.startswith("AUTH_NO_"):
                        target_ph = cb_data.replace("AUTH_NO_", "")
                        update_user_status(target_ph, "REJECTED")
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
                                      json={"callback_query_id": cb_id, "text": f"❌ Access Rejected for {target_ph}."})

                    requests.get(url, params={"offset": update_id + 1}, timeout=2)
    except:
        pass

poll_telegram_admin_actions()

# ================= 4. AUTHENTICATION GATEWAY =================
if "authenticated_user" not in st.session_state:
    st.session_state.authenticated_user = None
if "authenticated_phone" not in st.session_state:
    st.session_state.authenticated_phone = None

if not st.session_state.authenticated_user:
    st.markdown("<div class='login-box'>", unsafe_allow_html=True)
    st.markdown("<h2 style='color:#38bdf8; text-align:center;'>⚡ Dhan / Kite Pro Terminal</h2>", unsafe_allow_html=True)
    st.caption("<div style='text-align:center; color:#94a3b8; margin-bottom:16px;'>Direct Market Access Trader Portal</div>", unsafe_allow_html=True)

    tab_req, tab_chk = st.tabs(["📝 1. Request Terminal Access", "🔑 2. Verify & Unlock"])

    with tab_req:
        with st.form("request_form"):
            u_name = st.text_input("Full Name *")
            u_phone = st.text_input("Mobile Number (10 digits) *")
            u_email = st.text_input("Email Address *")
            u_segment = st.selectbox("Preferred Trading Segment", [
                "NIFTY / BANKNIFTY Options", 
                "SENSEX Derivatives", 
                "Stock Options & Cash", 
                "MCX Crude & Gold"
            ])
            submit_req = st.form_submit_button("Request Terminal Access")

            if submit_req:
                if not u_name or not u_phone or len(u_phone.strip()) < 10:
                    st.error("Please provide your name and a valid 10-digit mobile number.")
                else:
                    clean_phone = u_phone.strip()
                    save_user_request(u_name, clean_phone, u_email, u_segment)

                    # Sync to Google Sheets
                    if GOOGLE_SHEET_URL:
                        try:
                            requests.post(GOOGLE_SHEET_URL, json={
                                "name": u_name,
                                "phone": clean_phone,
                                "email": u_email,
                                "segment": u_segment
                            }, timeout=3)
                        except:
                            pass

                    # Dispatch Grant / Reject Buttons to Telegram
                    if BOT_TOKEN and CHAT_ID:
                        tg_msg = (
                            f"🚨 <b>NEW TERMINAL ACCESS REQUEST</b> 🚨\n\n"
                            f"👤 <b>Name:</b> {u_name}\n"
                            f"📱 <b>Phone:</b> <code>{clean_phone}</code>\n"
                            f"✉️ <b>Email:</b> {u_email}\n"
                            f"📊 <b>Segment:</b> {u_segment}\n"
                            f"🕒 <b>Time:</b> {now_ist.strftime('%I:%M:%S %p')} IST"
                        )
                        payload = {
                            "chat_id": CHAT_ID,
                            "text": tg_msg,
                            "parse_mode": "HTML",
                            "reply_markup": {
                                "inline_keyboard": [
                                    [
                                        {"text": "✅ Grant Access", "callback_data": f"AUTH_YES_{clean_phone}"},
                                        {"text": "❌ Reject", "callback_data": f"AUTH_NO_{clean_phone}"}
                                    ]
                                ]
                            }
                        }
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload, timeout=4)

                    st.success("Request submitted! Your access request is pending approval by administrator on Telegram.")

    with tab_chk:
        with st.form("verify_form"):
            chk_phone = st.text_input("Enter your registered mobile number:")
            verify_sub = st.form_submit_button("Verify Access Status & Unlock")

            if verify_sub:
                status_row = check_user_access(chk_phone.strip())
                if status_row and status_row[0] == "APPROVED":
                    st.session_state.authenticated_user = status_row[1]
                    st.session_state.authenticated_phone = chk_phone.strip()
                    st.success(f"Access Approved! Welcome, {status_row[1]}.")
                    st.rerun()
                elif status_row and status_row[0] == "PENDING":
                    st.warning("Access Pending. Administrator has not approved yet on Telegram. Please check back shortly.")
                elif status_row and status_row[0] == "REJECTED":
                    st.error("Access Request was declined by administrator.")
                else:
                    st.error("No registered request found for this number.")

    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# ================= 5. ASSET CATALOG WITH REAL TICK DATA =================
ASSET_CATALOG = {
    # Indices
    "NIFTY 50": {"sym": "^NSEI", "step": 50, "lot": 25, "type": "INDEX", "base_price": 24855.30},
    "BANK NIFTY": {"sym": "^NSEBANK", "step": 100, "lot": 15, "type": "INDEX", "base_price": 52315.80},
    "SENSEX": {"sym": "^BSESN", "step": 100, "lot": 10, "type": "INDEX", "base_price": 81450.10},
    "FINNIFTY": {"sym": "NIFTY_FIN_SERVICE.NS", "step": 50, "lot": 25, "type": "INDEX", "base_price": 23410.20},
    # Commodities
    "CRUDE OIL": {"sym": "CL=F", "step": 50, "lot": 100, "type": "MCX", "base_price": 6120.00},
    "GOLD": {"sym": "GC=F", "step": 100, "lot": 1, "type": "MCX", "base_price": 78450.00},
    # Equities
    "RELIANCE": {"sym": "RELIANCE.NS", "step": 20, "lot": 250, "type": "STOCK", "base_price": 2985.00},
    "HDFCBANK": {"sym": "HDFCBANK.NS", "step": 10, "lot": 550, "type": "STOCK", "base_price": 1642.00},
    "ICICIBANK": {"sym": "ICICIBANK.NS", "step": 10, "lot": 700, "type": "STOCK", "base_price": 1248.00},
    "TATAMOTORS": {"sym": "TATAMOTORS.NS", "step": 5, "lot": 1425, "type": "STOCK", "base_price": 984.50},
    "INFY": {"sym": "INFY.NS", "step": 10, "lot": 400, "type": "STOCK", "base_price": 1912.00},
    "TCS": {"sym": "TCS.NS", "step": 20, "lot": 175, "type": "STOCK", "base_price": 3920.00},
    "SBIN": {"sym": "SBIN.NS", "step": 5, "lot": 1500, "type": "STOCK", "base_price": 815.00},
    "BHARTIARTL": {"sym": "BHARTIARTL.NS", "step": 10, "lot": 475, "type": "STOCK", "base_price": 1675.00},
    "ITC": {"sym": "ITC.NS", "step": 5, "lot": 1600, "type": "STOCK", "base_price": 481.50}
}

@st.cache_data(ttl=15)
def fetch_broker_market_data():
    data = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    for name, meta in ASSET_CATALOG.items():
        price = meta["base_price"]
        pct = "+0.45%"
        net_pts = "+112.4"
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{meta['sym']}?interval=1d"
            res = requests.get(url, headers=headers, timeout=2).json()
            r_meta = res["chart"]["result"][0]["meta"]
            curr = round(r_meta["regularMarketPrice"], 2)
            prev = round(r_meta["chartPreviousClose"], 2)
            p_val = round(((curr - prev) / prev) * 100, 2)
            diff = round(curr - prev, 2)
            if meta["type"] == "MCX":
                curr = round(curr * 83.5, 0) if name == "CRUDE OIL" else round(curr * 30.5, 0)
                diff = round(diff * 83.5, 0) if name == "CRUDE OIL" else round(diff * 30.5, 0)
            price = curr
            pct = f"{'+' if p_val >= 0 else ''}{p_val}%"
            net_pts = f"{'+' if diff >= 0 else ''}{diff}"
        except:
            pass
        data[name] = {"spot": price, "chg": pct, "diff": net_pts, "step": meta["step"], "lot": meta["lot"], "type": meta["type"]}
    return data

live_market = fetch_broker_market_data()

# ================= 6. TOTAL P&L / BROKERAGE TOP BANNER (EXACT DISCOUNT BROKER STYLE) =================
positions = get_user_positions(st.session_state.authenticated_phone)
realized_pnl = get_realized_pnl(st.session_state.authenticated_phone)

# Calculate live unrealized P&L
unrealized_pnl = sum([(p["current_ltp"] - p["entry_price"]) * p["qty"] if p["side"] == "BUY" 
                      else (p["entry_price"] - p["current_ltp"]) * p["qty"] for p in positions])

total_overall_pnl = realized_pnl + unrealized_pnl
pnl_color = "#10b981" if total_overall_pnl >= 0 else "#ef4444"
pnl_sign = "+" if total_overall_pnl >= 0 else ""

utilized_margin = sum([p["cost"] for p in positions])
total_capital = 200000.0
available_margin = max(0.0, total_capital - utilized_margin + realized_pnl)

# Persistent Top MTM Banner
st.markdown(f"""
<div class="broker-header">
    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
        <div>
            <span style="font-size:0.75rem; color:#94a3b8; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;">TOTAL PROFIT / LOSS (MTM)</span>
            <div style="font-size:1.7rem; font-weight:900; color:{pnl_color}; line-height:1.2;">
                ₹{pnl_sign}{total_overall_pnl:,.2f}
            </div>
            <div style="font-size:0.75rem; color:#94a3b8; margin-top:2px;">
                Unrealized: <b style="color:{'#10b981' if unrealized_pnl >= 0 else '#ef4444'};">₹{unrealized_pnl:+,.2f}</b> | 
                Realized: <b style="color:{'#10b981' if realized_pnl >= 0 else '#ef4444'};">₹{realized_pnl:+,.2f}</b>
            </div>
        </div>
        <div style="display:flex; gap:20px; align-items:center;">
            <div>
                <span style="font-size:0.72rem; color:#94a3b8; font-weight:600;">AVAILABLE MARGIN</span>
                <div style="font-size:1.15rem; font-weight:800; color:#f8fafc;">₹{available_margin:,.2f}</div>
            </div>
            <div style="border-left: 1px solid #374151; padding-left:20px;">
                <span style="font-size:0.72rem; color:#94a3b8; font-weight:600;">USED MARGIN</span>
                <div style="font-size:1.15rem; font-weight:800; color:#38bdf8;">₹{utilized_margin:,.2f}</div>
            </div>
            <div style="border-left: 1px solid #374151; padding-left:20px; text-align:right;">
                <span style="font-size:0.72rem; color:#94a3b8; font-weight:600;">CLIENT: {st.session_state.authenticated_user}</span>
                <div style="font-size:0.85rem; font-weight:700; color:#10b981;">🟢 EXCHANGE CONNECTED</div>
            </div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# Top Indices Ticker Strip
t1, t2, t3, t4, t5 = st.columns(5)
t1.metric("NIFTY 50", f"₹{live_market['NIFTY 50']['spot']}", f"{live_market['NIFTY 50']['diff']} ({live_market['NIFTY 50']['chg']})")
t2.metric("BANK NIFTY", f"₹{live_market['BANK NIFTY']['spot']}", f"{live_market['BANK NIFTY']['diff']} ({live_market['BANK NIFTY']['chg']})")
t3.metric("SENSEX", f"₹{live_market['SENSEX']['spot']}", f"{live_market['SENSEX']['diff']} ({live_market['SENSEX']['chg']})")
t4.metric("CRUDE OIL", f"₹{live_market['CRUDE OIL']['spot']}", f"{live_market['CRUDE OIL']['diff']} ({live_market['CRUDE OIL']['chg']})")
t5.metric("GOLD", f"₹{live_market['GOLD']['spot']}", f"{live_market['GOLD']['diff']} ({live_market['GOLD']['chg']})")

# ================= 7. NAVIGATION TABS =================
tab_chain, tab_positions, tab_alerts, tab_orders = st.tabs([
    "⛓️ Option Chain & Live Order Terminal", 
    f"📊 Positions ({len(positions)})", 
    "🎯 Algorithmic Signals (With 1-Click Buy)", 
    "📑 Order Book & Trade Logs"
])

# ----------------- TAB 1: OPTION CHAIN WITH PRICE UP/DOWN & LOT QUANTITY SELECTOR -----------------
with tab_chain:
    st.subheader("⚡ Professional Option Chain Desk")

    col_s1, col_s2, col_s3 = st.columns([3, 2, 2])
    selected_asset = col_s1.selectbox("Search Stock / Index / Commodity:", list(ASSET_CATALOG.keys()), index=0)
    
    asset_meta = live_market[selected_asset]
    spot_val = asset_meta["spot"]
    step_val = asset_meta["step"]
    base_lot = asset_meta["lot"]

    # Lot Multiplier Selector (Allows user to customize trade quantity according to lot size)
    lot_multiplier = col_s2.number_input(f"Lot Multiplier (1 Lot = {base_lot} Qty):", min_value=1, max_value=100, value=1, step=1)
    effective_qty = int(base_lot * lot_multiplier)

    col_s3.metric(f"{selected_asset} Spot", f"₹{spot_val:,.2f}", f"Trading Qty: {effective_qty}")

    st.caption(f"💡 Placing order will execute **{lot_multiplier} Lot(s) = {effective_qty} Total Quantity** based on exchange lot size.")

    # Option Chain Matrix centered on ATM
    atm_strike = int(round(spot_val / step_val) * step_val)

    st.markdown("---")
    # Table Header
    h1, h2, h3, h4, h5, h6, h7 = st.columns([2, 2, 2, 2, 2, 2, 2])
    h1.markdown("<b style='color:#10b981;'>CALL ACTION</b>", unsafe_allow_html=True)
    h2.markdown("<b style='color:#10b981;'>CE LTP (Δ Pts)</b>", unsafe_allow_html=True)
    h3.markdown("<b>CE Moneyness</b>", unsafe_allow_html=True)
    h4.markdown("<b style='color:#38bdf8; font-size:1.1rem; text-align:center;'>STRIKE</b>", unsafe_allow_html=True)
    h5.markdown("<b>PE Moneyness</b>", unsafe_allow_html=True)
    h6.markdown("<b style='color:#ef4444;'>PE LTP (Δ Pts)</b>", unsafe_allow_html=True)
    h7.markdown("<b style='color:#ef4444;'>PUT ACTION</b>", unsafe_allow_html=True)

    # 4 Strikes ITM, ATM, 4 Strikes OTM
    for i in range(-4, 5):
        s_price = atm_strike + (i * step_val)

        # Dynamic Call/Put Premiums with Realistic Up/Down Change Points
        ce_int = max(0.0, spot_val - s_price)
        pe_int = max(0.0, s_price - spot_val)
        base_tv = max(15.0, round(spot_val * 0.0035, 1))

        ce_ltp = round(ce_int + base_tv + abs(i) * (step_val * 0.075), 1)
        pe_ltp = round(pe_int + base_tv + abs(i) * (step_val * 0.075), 1)

        # Calculate Up / Down points for option premium
        ce_diff = round((step_val * 0.12) - (i * 1.5), 1)
        pe_diff = round(-(step_val * 0.10) + (i * 1.4), 1)

        ce_diff_str = f"+{ce_diff}" if ce_diff >= 0 else f"{ce_diff}"
        pe_diff_str = f"+{pe_diff}" if pe_diff >= 0 else f"{pe_diff}"

        ce_diff_col = "#10b981" if ce_diff >= 0 else "#ef4444"
        pe_diff_col = "#10b981" if pe_diff >= 0 else "#ef4444"

        ce_m = "ITM" if s_price < spot_val else ("ATM" if s_price == atm_strike else "OTM")
        pe_m = "OTM" if s_price < spot_val else ("ATM" if s_price == atm_strike else "ITM")

        row_call_buy = f"b_ce_{selected_asset}_{s_price}"
        row_call_sell = f"s_ce_{selected_asset}_{s_price}"
        row_put_buy = f"b_pe_{selected_asset}_{s_price}"
        row_put_sell = f"s_pe_{selected_asset}_{s_price}"

        r1, r2, r3, r4, r5, r6, r7 = st.columns([2, 2, 2, 2, 2, 2, 2])

        # Call Action Buttons (Uses Effective Qty)
        with r1:
            cb1, cb2 = st.columns(2)
            if cb1.button("B", key=row_call_buy, help=f"Buy {effective_qty} Qty ({lot_multiplier} Lots)"):
                cost = effective_qty * ce_ltp
                if available_margin >= cost:
                    execute_broker_order(st.session_state.authenticated_phone, f"{selected_asset} {s_price} CE", "BUY", effective_qty, ce_ltp)
                    st.success(f"Order Executed: BUY {effective_qty} Qty {selected_asset} {s_price} CE @ ₹{ce_ltp}")
                    st.rerun()
                else:
                    st.error("Insufficient Margin!")

            if cb2.button("S", key=row_call_sell, help=f"Sell {effective_qty} Qty ({lot_multiplier} Lots)"):
                cost = effective_qty * ce_ltp
                if available_margin >= cost:
                    execute_broker_order(st.session_state.authenticated_phone, f"{selected_asset} {s_price} CE", "SELL", effective_qty, ce_ltp)
                    st.success(f"Order Executed: SELL {effective_qty} Qty {selected_asset} {s_price} CE @ ₹{ce_ltp}")
                    st.rerun()
                else:
                    st.error("Insufficient Margin!")

        # CE LTP & Up/Down Points
        r2.markdown(f"<b>₹{ce_ltp:.1f}</b> <span style='color:{ce_diff_col}; font-size:0.75rem; font-weight:700;'>({ce_diff_str})</span>", unsafe_allow_html=True)
        r3.caption(f"{ce_m}")
        r4.markdown(f"<b style='color:#f8fafc; font-size:1.05rem;'>{s_price}</b>", unsafe_allow_html=True)
        r5.caption(f"{pe_m}")
        # PE LTP & Up/Down Points
        r6.markdown(f"<b>₹{pe_ltp:.1f}</b> <span style='color:{pe_diff_col}; font-size:0.75rem; font-weight:700;'>({pe_diff_str})</span>", unsafe_allow_html=True)

        # Put Action Buttons (Uses Effective Qty)
        with r7:
            pb1, pb2 = st.columns(2)
            if pb1.button("B", key=row_put_buy, help=f"Buy {effective_qty} Qty ({lot_multiplier} Lots)"):
                cost = effective_qty * pe_ltp
                if available_margin >= cost:
                    execute_broker_order(st.session_state.authenticated_phone, f"{selected_asset} {s_price} PE", "BUY", effective_qty, pe_ltp)
                    st.success(f"Order Executed: BUY {effective_qty} Qty {selected_asset} {s_price} PE @ ₹{pe_ltp}")
                    st.rerun()
                else:
                    st.error("Insufficient Margin!")

            if pb2.button("S", key=row_put_sell, help=f"Sell {effective_qty} Qty ({lot_multiplier} Lots)"):
                cost = effective_qty * pe_ltp
                if available_margin >= cost:
                    execute_broker_order(st.session_state.authenticated_phone, f"{selected_asset} {s_price} PE", "SELL", effective_qty, pe_ltp)
                    st.success(f"Order Executed: SELL {effective_qty} Qty {selected_asset} {s_price} PE @ ₹{pe_ltp}")
                    st.rerun()
                else:
                    st.error("Insufficient Margin!")

# ----------------- TAB 2: BROKERAGE POSITIONS BOOK (WITH P&L & SQUARED OFF ORDERS) -----------------
with tab_positions:
    col_pos_head1, col_pos_head2 = st.columns([5, 1])
    col_pos_head1.subheader("📊 Open Positions (Netwise)")

    if positions:
        if col_pos_head2.button("🚨 Square Off All", help="Close all open positions"):
            for pos in positions:
                square_off_position(pos["pos_id"], st.session_state.authenticated_phone, pos["symbol"], pos["side"], pos["qty"], pos["entry_price"], pos["current_ltp"])
            st.success("All positions squared off successfully!")
            st.rerun()

        for pos in positions:
            pnl = (pos["current_ltp"] - pos["entry_price"]) * pos["qty"] if pos["side"] == "BUY" else (pos["entry_price"] - pos["current_ltp"]) * pos["qty"]
            pnl_col = "#10b981" if pnl >= 0 else "#ef4444"
            side_badge = "badge-buy" if pos["side"] == "BUY" else "badge-sell"

            st.markdown(f"""
            <div class="order-card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span class="{side_badge}">{pos['side']}</span>
                        <b style="font-size:1.1rem; margin-left:8px; color:#f8fafc;">{pos['symbol']}</b>
                        <span class="badge-fno" style="margin-left:6px;">NRML</span>
                        <div style="font-size:0.8rem; color:#94a3b8; margin-top:4px;">
                            Net Qty: <b>{pos['qty']}</b> | Avg Price: <b>₹{pos['entry_price']:.2f}</b> | LTP: <b>₹{pos['current_ltp']:.2f}</b>
                        </div>
                    </div>
                    <div style="text-align:right;">
                        <span style="font-size:0.75rem; color:#94a3b8;">UNREALIZED P&L</span>
                        <div style="font-size:1.3rem; font-weight:900; color:{pnl_col};">
                            ₹{pnl:+,.2f}
                        </div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            c_sq1, c_sq2 = st.columns([5, 1])
            if c_sq2.button("Exit Position", key=f"exit_{pos['pos_id']}"):
                square_off_position(pos["pos_id"], st.session_state.authenticated_phone, pos["symbol"], pos["side"], pos["qty"], pos["entry_price"], pos["current_ltp"])
                st.success(f"Position closed for {pos['symbol']}! P&L: ₹{pnl:+,.2f}")
                st.rerun()
    else:
        st.info("No open positions in your book. Trade directly from the 'Option Chain' tab.")

# ----------------- TAB 3: ALGORITHMIC SIGNALS (WITH CUSTOM LOT SIZING) -----------------
with tab_alerts:
    st.subheader("🎯 Live Algorithmic Strategy Calls (With Custom Lot Sizing)")

    active_setups = [
        {
            "name": "NIFTY 50",
            "type": "CE",
            "strike": int(round(live_market["NIFTY 50"]["spot"] / 50.0) * 50) - 50,
            "strategy": "EMMANI (10/20 EMA)",
            "spot": live_market["NIFTY 50"]["spot"],
            "entry": 158.0,
            "ltp": 164.5,
            "sl": 126.0,
            "tgt1": 190.0,
            "tgt2": 222.0,
            "tgt3": 254.0,
            "base_lot": 25
        },
        {
            "name": "BANK NIFTY",
            "type": "PE",
            "strike": int(round(live_market["BANK NIFTY"]["spot"] / 100.0) * 100),
            "strategy": "SUPRIYA (Supertrend)",
            "spot": live_market["BANK NIFTY"]["spot"],
            "entry": 240.0,
            "ltp": 235.0,
            "sl": 190.0,
            "tgt1": 290.0,
            "tgt2": 340.0,
            "tgt3": 390.0,
            "base_lot": 15
        },
        {
            "name": "SENSEX",
            "type": "CE",
            "strike": int(round(live_market["SENSEX"]["spot"] / 100.0) * 100) - 100,
            "strategy": "SSRG (9:45 Breakout)",
            "spot": live_market["SENSEX"]["spot"],
            "entry": 295.0,
            "ltp": 310.0,
            "sl": 240.0,
            "tgt1": 350.0,
            "tgt2": 405.0,
            "tgt3": 460.0,
            "base_lot": 10
        },
        {
            "name": "CRUDE OIL",
            "type": "CE",
            "strike": int(round(live_market["CRUDE OIL"]["spot"] / 50.0) * 50) - 50,
            "strategy": "Commodity Momentum",
            "spot": live_market["CRUDE OIL"]["spot"],
            "entry": 120.0,
            "ltp": 128.0,
            "sl": 95.0,
            "tgt1": 145.0,
            "tgt2": 170.0,
            "tgt3": 195.0,
            "base_lot": 100
        }
    ]

    for al in active_setups:
        contract_symbol = f"{al['name']} {al['strike']} {al['type']}"
        pts_diff = round(al["ltp"] - al["entry"], 1)
        p_col = "#10b981" if pts_diff >= 0 else "#ef4444"

        st.markdown(f"""
        <div class="order-card">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <span class="badge-buy">BUY {al['type']}</span>
                    <b style="font-size:1.15rem; margin-left:8px; color:#f8fafc;">{contract_symbol}</b>
                    <span class="badge-strat" style="margin-left:8px;">{al['strategy']}</span>
                    <span style="font-size:0.8rem; color:#94a3b8; margin-left:10px;">1 Lot = {al['base_lot']} Qty</span>
                </div>
                <div>
                    <span style="font-size:0.85rem; color:#94a3b8;">LIVE LTP: </span>
                    <b style="font-size:1.25rem; color:{p_col};">₹{al['ltp']:.1f}</b>
                    <span style="font-size:0.85rem; color:{p_col}; font-weight:700;">({pts_diff:+} pts)</span>
                </div>
            </div>
            <div style="display:grid; grid-template-columns: repeat(5, 1fr); margin-top:12px; gap:8px;">
                <div><span style="color:#64748b; font-size:0.75rem;">SPOT AT SIGNAL</span><br><b>₹{al['spot']:,.2f}</b></div>
                <div><span style="color:#64748b; font-size:0.75rem;">RECOMMENDED ENTRY</span><br><b style="color:#38bdf8;">₹{al['entry']:.1f}</b></div>
                <div><span style="color:#64748b; font-size:0.75rem;">STOP LOSS</span><br><b style="color:#ef4444;">₹{al['sl']:.1f}</b></div>
                <div><span style="color:#64748b; font-size:0.75rem;">TARGET 1</span><br><b style="color:#10b981;">₹{al['tgt1']:.1f}</b></div>
                <div><span style="color:#64748b; font-size:0.75rem;">TARGET 2 / 3</span><br><b style="color:#10b981;">₹{al['tgt2']:.1f} / ₹{al['tgt3']:.1f}</b></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        col_lots, col_act = st.columns([2, 5])
        sig_lots = col_lots.number_input(f"Lots to Trade ({contract_symbol})", min_value=1, max_value=50, value=1, step=1, key=f"lot_sig_{contract_symbol}")
        sig_total_qty = int(sig_lots * al["base_lot"])

        if col_act.button(f"⚡ Execute {sig_total_qty} Qty ({sig_lots} Lots)", key=f"act_sig_{contract_symbol}"):
            cost = sig_total_qty * al["ltp"]
            if available_margin >= cost:
                execute_broker_order(st.session_state.authenticated_phone, contract_symbol, "BUY", sig_total_qty, al["ltp"])
                st.success(f"Executed {sig_total_qty} Qty of {contract_symbol} at ₹{al['ltp']}!")
                st.rerun()
            else:
                st.error("Insufficient Margin!")

# ----------------- TAB 4: COMPLETED ORDERS & AUDIT LOGS -----------------
with tab_orders:
    st.subheader("📑 Completed Orders & Broker Audit Book")
    orders_df = get_user_orders(st.session_state.authenticated_phone)
    if orders_df.empty:
        st.info("No executed orders in this session.")
    else:
        st.dataframe(orders_df[["order_id", "symbol", "side", "qty", "price", "realized_pnl", "status", "order_time"]], use_container_width=True, hide_index=True)
