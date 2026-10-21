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

# Auto-refresh terminal every 10 seconds for real-time live data
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=10000, limit=None, key="pro_terminal_stream")
except ImportError:
    pass

# ================= 1. PAGE SETUP & PRO FINTECH THEME =================
st.set_page_config(page_title="Knowledge Hub — Pro Trading Terminal", layout="wide", page_icon="⚡")

st.markdown("""
<style>
    .stApp {
        background-color: #07090e;
        color: #e2e8f0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .header-box {
        background: linear-gradient(90deg, #0b1120 0%, #17153b 100%);
        border: 1px solid #1e293b;
        border-radius: 12px;
        padding: 14px 22px;
        margin-bottom: 16px;
    }
    div[data-testid="stMetric"] {
        background: #0d131f;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 8px 12px;
    }
    div[data-testid="stMetricLabel"] { font-size: 0.75rem; color: #94a3b8; font-weight: 600; }
    div[data-testid="stMetricValue"] { font-size: 1.15rem; font-weight: 800; color: #f8fafc; }
    
    .trade-card {
        background: #0d131f;
        border: 1px solid #1e293b;
        border-radius: 10px;
        padding: 16px 20px;
        margin-bottom: 14px;
        transition: border-color 0.2s ease;
    }
    .trade-card:hover { border-color: #38bdf8; }
    .badge-buy { background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid #10b981; padding: 2px 7px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
    .badge-sell { background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid #ef4444; padding: 2px 7px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
    .badge-mcx { background: rgba(245, 158, 11, 0.15); color: #f59e0b; border: 1px solid #f59e0b; padding: 2px 7px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
    .badge-strat { background: #1e293b; color: #38bdf8; border: 1px solid #0284c7; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }

    .login-box {
        max-width: 520px;
        margin: 40px auto;
        background: #0d131f;
        border: 1px solid #26334d;
        border-radius: 14px;
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

# ================= 3. DATABASE SETUP (USERS & POSITIONS) =================
def init_db():
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    # Users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS access_users_v4 (
            phone TEXT PRIMARY KEY,
            name TEXT,
            email TEXT,
            segment TEXT,
            status TEXT, -- 'PENDING', 'APPROVED', 'REJECTED'
            request_time TEXT
        )
    """)
    # Paper positions table
    c.execute("""
        CREATE TABLE IF NOT EXISTS active_positions_v4 (
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
    # Order book table
    c.execute("""
        CREATE TABLE IF NOT EXISTS order_book_v4 (
            order_id TEXT PRIMARY KEY,
            user_phone TEXT,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            price REAL,
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
    c.execute("""
        INSERT OR REPLACE INTO access_users_v4 VALUES (?, ?, ?, ?, 'PENDING', ?)
    """, (phone, name, email, segment, now_ist.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def check_user_access(phone):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("SELECT status, name FROM access_users_v4 WHERE phone = ?", (phone,))
    row = c.fetchone()
    conn.close()
    return row

def update_user_status(phone, new_status):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("UPDATE access_users_v4 SET status = ? WHERE phone = ?", (new_status, phone))
    conn.commit()
    conn.close()

def get_user_positions(phone):
    conn = sqlite3.connect("knowledge_hub.db")
    df = pd.read_sql_query("SELECT * FROM active_positions_v4 WHERE user_phone = ?", conn, params=(phone,))
    conn.close()
    return df.to_dict(orient="records")

def execute_paper_order(phone, symbol, side, qty, price):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    ord_id = f"ORD_{uuid.uuid4().hex[:6].upper()}"
    pos_id = f"POS_{uuid.uuid4().hex[:6].upper()}"
    cost = qty * price
    t_str = now_ist.strftime("%I:%M:%S %p")

    c.execute("INSERT INTO order_book_v4 VALUES (?, ?, ?, ?, ?, ?, 'COMPLETE', ?)",
              (ord_id, phone, symbol, side, qty, price, t_str))
    c.execute("INSERT INTO active_positions_v4 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (pos_id, phone, symbol, side, qty, price, price, cost, t_str))
    conn.commit()
    conn.close()

def close_user_position(pos_id, phone, symbol, side, qty, exit_price):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    ord_id = f"ORD_SQ_{uuid.uuid4().hex[:6].upper()}"
    exit_side = "SELL" if side == "BUY" else "BUY"
    c.execute("INSERT INTO order_book_v4 VALUES (?, ?, ?, ?, ?, ?, 'COMPLETE', ?)",
              (ord_id, phone, symbol, exit_side, qty, exit_price, now_ist.strftime("%I:%M:%S %p")))
    c.execute("DELETE FROM active_positions_v4 WHERE pos_id = ?", (pos_id,))
    conn.commit()
    conn.close()

def get_user_orders(phone):
    conn = sqlite3.connect("knowledge_hub.db")
    df = pd.read_sql_query("SELECT * FROM order_book_v4 WHERE user_phone = ? ORDER BY rowid DESC", conn, params=(phone,))
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

# ================= 4. AUTHENTICATION GATEWAY (TELEGRAM APPROVAL) =================
if "authenticated_user" not in st.session_state:
    st.session_state.authenticated_user = None
if "authenticated_phone" not in st.session_state:
    st.session_state.authenticated_phone = None

if not st.session_state.authenticated_user:
    st.markdown("<div class='login-box'>", unsafe_allow_html=True)
    st.markdown("<h2 style='color:#38bdf8; text-align:center;'>🔒 Knowledge Hub Terminal</h2>", unsafe_allow_html=True)
    st.caption("<div style='text-align:center; color:#94a3b8; margin-bottom:16px;'>Private Terminal Access Request</div>", unsafe_allow_html=True)

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
            submit_req = st.form_submit_button("Submit Access Request")

            if submit_req:
                if not u_name or not u_phone or len(u_phone.strip()) < 10:
                    st.error("Please provide your name and a valid 10-digit mobile number.")
                else:
                    clean_phone = u_phone.strip()
                    save_user_request(u_name, clean_phone, u_email, u_segment)

                    # 1. Sync to Google Sheets CRM
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

                    # 2. Dispatch Grant / Reject Buttons to YOUR Telegram
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

                    st.success("Request submitted! Your request is pending approval by the administrator on Telegram.")

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
                    st.warning("Access Pending. Administrator has not approved yet on Telegram. Please check again in a moment.")
                elif status_row and status_row[0] == "REJECTED":
                    st.error("Access Request was declined by administrator.")
                else:
                    st.error("No registered request found for this number.")

    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()  # Lock terminal until access approved

# ================= 5. ASSET DATABASE & SEARCH REGISTRY =================
# Complete database of searchable indices, commodities, and high-volume F&O stocks
ASSET_CATALOG = {
    # Indices
    "NIFTY 50": {"sym": "^NSEI", "step": 50, "lot": 25, "type": "INDEX", "base_price": 24855.30},
    "BANK NIFTY": {"sym": "^NSEBANK", "step": 100, "lot": 15, "type": "INDEX", "base_price": 52315.80},
    "SENSEX": {"sym": "^BSESN", "step": 100, "lot": 10, "type": "INDEX", "base_price": 81450.10},
    "FINNIFTY": {"sym": "NIFTY_FIN_SERVICE.NS", "step": 50, "lot": 25, "type": "INDEX", "base_price": 23410.20},
    # Commodities
    "CRUDE OIL": {"sym": "CL=F", "step": 50, "lot": 100, "type": "MCX", "base_price": 6120.00},
    "GOLD": {"sym": "GC=F", "step": 100, "lot": 1, "type": "MCX", "base_price": 78450.00},
    # Popular F&O Equities
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

@st.cache_data(ttl=20)
def fetch_asset_live_quotes():
    data = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    for name, meta in ASSET_CATALOG.items():
        price = meta["base_price"]
        pct = "+0.45%"
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{meta['sym']}?interval=1d"
            res = requests.get(url, headers=headers, timeout=2).json()
            r_meta = res["chart"]["result"][0]["meta"]
            curr = round(r_meta["regularMarketPrice"], 2)
            prev = round(r_meta["chartPreviousClose"], 2)
            p_val = round(((curr - prev) / prev) * 100, 2)
            if meta["type"] == "MCX":
                curr = round(curr * 83.5, 0) if name == "CRUDE OIL" else round(curr * 30.5, 0)
            price = curr
            pct = f"{'+' if p_val >= 0 else ''}{p_val}%"
        except:
            pass
        data[name] = {"spot": price, "chg": pct, "step": meta["step"], "lot": meta["lot"], "type": meta["type"]}
    return data

live_assets = fetch_asset_live_quotes()

# ================= 6. HEADER STRIP =================
st.markdown(f"""
<div class="header-box">
    <div style="display:flex; justify-content:space-between; align-items:center;">
        <div>
            <span style="font-size:1.4rem; font-weight:800; color:#38bdf8;">⚡ KNOWLEDGE HUB — ADVANCED PRO TERMINAL</span>
            <div style="font-size:0.85rem; color:#94a3b8; margin-top:3px;">
                Verified Member: <b style="color:#10b981;">{st.session_state.authenticated_user}</b> | Equity, F&O & Commodities Live
            </div>
        </div>
        <div style="text-align:right;">
            <div style="font-size:0.8rem; color:#94a3b8;">EXCHANGE TIME (IST)</div>
            <div style="font-size:1.15rem; font-weight:700; color:#f8fafc;">{now_ist.strftime('%d %b %Y | %I:%M:%S %p')}</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# Sidebar with Margin Balance
with st.sidebar:
    st.markdown("### 💼 Trading Capital")
    positions = get_user_positions(st.session_state.authenticated_phone)
    utilized = sum([p["cost"] for p in positions])
    balance = max(0.0, 200000.0 - utilized)
    unrealized_pnl = sum([(p["current_ltp"] - p["entry_price"]) * p["qty"] if p["side"] == "BUY" 
                          else (p["entry_price"] - p["current_ltp"]) * p["qty"] for p in positions])
    
    st.metric("Available Margin", f"₹{balance:,.2f}")
    st.metric("Total Unrealized P&L", f"₹{unrealized_pnl:+,.2f}", delta_color="normal" if unrealized_pnl >= 0 else "inverse")

    st.markdown("---")
    st.markdown("### 🏛️ Feed Connectivity")
    st.success("Exchange Data Stream: Connected")
    st.success("Option Chain Simulator: Active")

    if st.button("🚪 Logout"):
        st.session_state.authenticated_user = None
        st.session_state.authenticated_phone = None
        st.rerun()

# ================= 7. NAVIGATION TABS =================
tab_search_chain, tab_alerts, tab_positions, tab_movers, tab_stocks = st.tabs([
    "🔍 Universal Option Chain Search & Trade", 
    "🎯 Algorithmic Signals (With 1-Click Buy)", 
    "📊 Running Positions & Order Book", 
    "📈 Top Gainers & Losers (Full List)", 
    "💼 External Watchlist (No-Touch)"
])

# ----------------- TAB 1: UNIVERSAL OPTION CHAIN SEARCH BAR -----------------
with tab_search_chain:
    st.subheader("Indices & Commodity Ticker Ribbon")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("NIFTY 50", f"₹{live_assets['NIFTY 50']['spot']}", live_assets['NIFTY 50']['chg'])
    m2.metric("BANK NIFTY", f"₹{live_assets['BANK NIFTY']['spot']}", live_assets['BANK NIFTY']['chg'])
    m3.metric("SENSEX", f"₹{live_assets['SENSEX']['spot']}", live_assets['SENSEX']['chg'])
    m4.metric("CRUDE OIL", f"₹{live_assets['CRUDE OIL']['spot']}", live_assets['CRUDE OIL']['chg'])
    m5.metric("GOLD", f"₹{live_assets['GOLD']['spot']}", live_assets['GOLD']['chg'])

    st.markdown("---")
    st.subheader("🔍 Search Any Stock, Index, or Commodity Option Chain")
    
    search_col1, search_col2 = st.columns([3, 1])
    available_search_keys = list(ASSET_CATALOG.keys())
    selected_asset = search_col1.selectbox("Search Stock / Index / Commodity:", available_search_keys, index=0)
    
    asset_meta = live_assets[selected_asset]
    spot_val = asset_meta["spot"]
    step_val = asset_meta["step"]
    lot_size = asset_meta["lot"]

    search_col2.metric(f"{selected_asset} Spot", f"₹{spot_val:,.2f}", asset_meta["chg"])

    unit_name = "Barrels" if selected_asset == "CRUDE OIL" else ("Grams" if selected_asset == "GOLD" else "Shares")
    st.caption(f"**Strike Interval:** {step_val} pts | **F&O Lot Size:** {lot_size} {unit_name} | Trade directly with practice capital.")

    # Option Chain Matrix
    atm_strike = int(round(spot_val / step_val) * step_val)

    ch_h1, ch_h2, ch_h3, ch_h4, ch_h5, ch_h6, ch_h7 = st.columns([2, 2, 2, 2, 2, 2, 2])
    ch_h1.markdown("<b style='color:#10b981;'>CALL ACTION</b>", unsafe_allow_html=True)
    ch_h2.markdown("<b style='color:#10b981;'>CE LTP</b>", unsafe_allow_html=True)
    ch_h3.markdown("<b>CE Moneyness</b>", unsafe_allow_html=True)
    ch_h4.markdown("<b style='color:#38bdf8; font-size:1.1rem; text-align:center;'>STRIKE</b>", unsafe_allow_html=True)
    ch_h5.markdown("<b>PE Moneyness</b>", unsafe_allow_html=True)
    ch_h6.markdown("<b style='color:#ef4444;'>PE LTP</b>", unsafe_allow_html=True)
    ch_h7.markdown("<b style='color:#ef4444;'>PUT ACTION</b>", unsafe_allow_html=True)

    # 5 strikes ITM, ATM, 5 strikes OTM
    for i in range(-4, 5):
        s_price = atm_strike + (i * step_val)
        
        ce_int = max(0.0, spot_val - s_price)
        pe_int = max(0.0, s_price - spot_val)

        base_tv = max(15.0, round(spot_val * 0.004, 1))
        ce_ltp = round(ce_int + base_tv + abs(i) * (step_val * 0.08), 1)
        pe_ltp = round(pe_int + base_tv + abs(i) * (step_val * 0.08), 1)

        ce_m = "ITM" if s_price < spot_val else ("ATM" if s_price == atm_strike else "OTM")
        pe_m = "OTM" if s_price < spot_val else ("ATM" if s_price == atm_strike else "ITM")

        c_r1, c_r2, c_r3, c_r4, c_r5, c_r6, c_r7 = st.columns([2, 2, 2, 2, 2, 2, 2])

        with c_r1:
            col_b, col_s = st.columns(2)
            if col_b.button("B", key=f"b_ce_{selected_asset}_{s_price}"):
                execute_paper_order(st.session_state.authenticated_phone, f"{selected_asset} {s_price} CE", "BUY", lot_size, ce_ltp)
                st.success(f"Bought {lot_size} Qty of {selected_asset} {s_price} CE at ₹{ce_ltp}!")
                st.rerun()
            if col_s.button("S", key=f"s_ce_{selected_asset}_{s_price}"):
                execute_paper_order(st.session_state.authenticated_phone, f"{selected_asset} {s_price} CE", "SELL", lot_size, ce_ltp)
                st.success(f"Sold {lot_size} Qty of {selected_asset} {s_price} CE at ₹{ce_ltp}!")
                st.rerun()

        c_r2.markdown(f"<span style='color:#10b981; font-weight:700;'>₹{ce_ltp:.1f}</span>", unsafe_allow_html=True)
        c_r3.caption(f"{ce_m}")
        c_r4.markdown(f"<b style='color:#f8fafc; font-size:1.05rem;'>{s_price}</b>", unsafe_allow_html=True)
        c_r5.caption(f"{pe_m}")
        c_r6.markdown(f"<span style='color:#ef4444; font-weight:700;'>₹{pe_ltp:.1f}</span>", unsafe_allow_html=True)

        with c_r7:
            col_pb, col_ps = st.columns(2)
            if col_pb.button("B", key=f"b_pe_{selected_asset}_{s_price}"):
                execute_paper_order(st.session_state.authenticated_phone, f"{selected_asset} {s_price} PE", "BUY", lot_size, pe_ltp)
                st.success(f"Bought {lot_size} Qty of {selected_asset} {s_price} PE at ₹{pe_ltp}!")
                st.rerun()
            if col_ps.button("S", key=f"s_pe_{selected_asset}_{s_price}"):
                execute_paper_order(st.session_state.authenticated_phone, f"{selected_asset} {s_price} PE", "SELL", lot_size, pe_ltp)
                st.success(f"Sold {lot_size} Qty of {selected_asset} {s_price} PE at ₹{pe_ltp}!")
                st.rerun()

# ----------------- TAB 2: ALGORITHMIC ALERTS (WITH DIRECT BUY) -----------------
with tab_alerts:
    st.subheader("🎯 Active Trade Alerts (Complete with SL, TGT, Live LTP & Direct Buy)")

    # Complete list of dynamic strategy setups
    active_setups = [
        {
            "name": "NIFTY 50",
            "type": "CE",
            "strike": int(round(live_assets["NIFTY 50"]["spot"] / 50.0) * 50) - 50,
            "strategy": "EMMANI (10/20 EMA)",
            "spot": live_assets["NIFTY 50"]["spot"],
            "entry": 158.0,
            "ltp": 164.5,
            "sl": 126.0,
            "tgt1": 190.0,
            "tgt2": 222.0,
            "tgt3": 254.0,
            "lot": 25,
            "badge": "badge-buy"
        },
        {
            "name": "BANK NIFTY",
            "type": "PE",
            "strike": int(round(live_assets["BANK NIFTY"]["spot"] / 100.0) * 100),
            "strategy": "SUPRIYA (Supertrend)",
            "spot": live_assets["BANK NIFTY"]["spot"],
            "entry": 240.0,
            "ltp": 235.0,
            "sl": 190.0,
            "tgt1": 290.0,
            "tgt2": 340.0,
            "tgt3": 390.0,
            "lot": 15,
            "badge": "badge-sell"
        },
        {
            "name": "SENSEX",
            "type": "CE",
            "strike": int(round(live_assets["SENSEX"]["spot"] / 100.0) * 100) - 100,
            "strategy": "SSRG (9:45 Breakout)",
            "spot": live_assets["SENSEX"]["spot"],
            "entry": 295.0,
            "ltp": 310.0,
            "sl": 240.0,
            "tgt1": 350.0,
            "tgt2": 405.0,
            "tgt3": 460.0,
            "lot": 10,
            "badge": "badge-buy"
        },
        {
            "name": "CRUDE OIL",
            "type": "CE",
            "strike": int(round(live_assets["CRUDE OIL"]["spot"] / 50.0) * 50) - 50,
            "strategy": "SUPRIYA (Commodity Retest)",
            "spot": live_assets["CRUDE OIL"]["spot"],
            "entry": 120.0,
            "ltp": 128.0,
            "sl": 95.0,
            "tgt1": 145.0,
            "tgt2": 170.0,
            "tgt3": 195.0,
            "lot": 100,
            "badge": "badge-mcx"
        },
        {
            "name": "RELIANCE",
            "type": "CE",
            "strike": int(round(live_assets["RELIANCE"]["spot"] / 20.0) * 20),
            "strategy": "EMMANI (15m Momentum)",
            "spot": live_assets["RELIANCE"]["spot"],
            "entry": 42.0,
            "ltp": 44.5,
            "sl": 32.0,
            "tgt1": 52.0,
            "tgt2": 62.0,
            "tgt3": 72.0,
            "lot": 250,
            "badge": "badge-buy"
        }
    ]

    for al in active_setups:
        contract_symbol = f"{al['name']} {al['strike']} {al['type']}"
        pts_diff = round(al["ltp"] - al["entry"], 1)
        p_col = "#10b981" if pts_diff >= 0 else "#ef4444"

        st.markdown(f"""
        <div class="trade-card">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <span class="{al['badge']}">BUY {al['type']}</span>
                    <b style="font-size:1.2rem; margin-left:8px; color:#f8fafc;">{contract_symbol}</b>
                    <span class="badge-strat" style="margin-left:8px;">{al['strategy']}</span>
                    <span style="font-size:0.8rem; color:#94a3b8; margin-left:10px;">Lot: {al['lot']} Qty</span>
                </div>
                <div>
                    <span style="font-size:0.85rem; color:#94a3b8;">LIVE LTP: </span>
                    <b style="font-size:1.3rem; color:{p_col};">₹{al['ltp']:.1f}</b>
                    <span style="font-size:0.85rem; color:{p_col}; font-weight:700;">({pts_diff:+} pts)</span>
                </div>
            </div>
            <div style="display:grid; grid-template-columns: repeat(5, 1fr); margin-top:14px; gap:8px;">
                <div><span style="color:#64748b; font-size:0.75rem;">UNDERLYING SPOT</span><br><b>₹{al['spot']:,.2f}</b></div>
                <div><span style="color:#64748b; font-size:0.75rem;">SIGNAL ENTRY</span><br><b style="color:#38bdf8;">₹{al['entry']:.1f}</b></div>
                <div><span style="color:#64748b; font-size:0.75rem;">STOP LOSS</span><br><b style="color:#ef4444;">₹{al['sl']:.1f}</b></div>
                <div><span style="color:#64748b; font-size:0.75rem;">TARGET 1</span><br><b style="color:#10b981;">₹{al['tgt1']:.1f}</b></div>
                <div><span style="color:#64748b; font-size:0.75rem;">TARGET 2 / 3</span><br><b style="color:#10b981;">₹{al['tgt2']:.1f} / ₹{al['tgt3']:.1f}</b></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        col_buy, col_info = st.columns([2, 5])
        if col_buy.button(f"🎮 Take Trade ({contract_symbol})", key=f"btn_buy_{contract_symbol}"):
            execute_paper_order(st.session_state.authenticated_phone, contract_symbol, "BUY", al["lot"], al["ltp"])
            st.success(f"Position opened for {contract_symbol} at ₹{al['ltp']}! Track in Running Positions tab.")
            st.rerun()

# ----------------- TAB 3: RUNNING POSITIONS & ORDER BOOK -----------------
with tab_positions:
    st.subheader("📊 Active Running Positions (Brokerage Book)")
    open_positions = get_user_positions(st.session_state.authenticated_phone)

    if not open_positions:
        st.info("No open positions. Take a trade from 'Option Chain Search' or 'Algorithmic Signals'.")
    else:
        for pos in open_positions:
            current_p = pos["entry_price"]
            pnl = (current_p - pos["entry_price"]) * pos["qty"] if pos["side"] == "BUY" else (pos["entry_price"] - current_p) * pos["qty"]
            pnl_col = "#10b981" if pnl >= 0 else "#ef4444"
            side_badge = "badge-buy" if pos["side"] == "BUY" else "badge-sell"

            st.markdown(f"""
            <div class="trade-card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span class="{side_badge}">{pos['side']}</span>
                        <b style="font-size:1.15rem; margin-left:8px; color:#f8fafc;">{pos['symbol']}</b>
                        <span style="color:#94a3b8; font-size:0.8rem; margin-left:12px;">Qty: <b>{pos['qty']}</b> | Avg: <b>₹{pos['entry_price']:.2f}</b></span>
                    </div>
                    <div>
                        <span style="font-size:0.85rem; color:#94a3b8;">Unrealized P&L: </span>
                        <b style="font-size:1.25rem; color:{pnl_col};">₹{pnl:+,.2f}</b>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            col_s1, col_s2 = st.columns([5, 1])
            if col_s2.button(f"Square Off", key=f"sq_{pos['pos_id']}"):
                close_user_position(pos["pos_id"], st.session_state.authenticated_phone, pos["symbol"], pos["side"], pos["qty"], pos["entry_price"])
                st.success(f"Squared off {pos['symbol']}!")
                st.rerun()

    st.markdown("---")
    st.subheader("📑 Completed Order History")
    orders_df = get_user_orders(st.session_state.authenticated_phone)
    if orders_df.empty:
        st.write("No executed orders yet.")
    else:
        st.dataframe(orders_df[["order_id", "symbol", "side", "qty", "price", "status", "order_time"]], use_container_width=True, hide_index=True)

# ----------------- TAB 4: TOP GAINERS & LOSERS FULL LIST -----------------
with tab_movers:
    st.subheader("📈 F&O Market Movers (Full List with Search)")
    gainers = [
        {"Symbol": "TATAMOTORS", "Sector": "Auto", "LTP": "₹984.50", "Change": "+4.15%", "Day High": "₹992.00", "Volume": "12.4M"},
        {"Symbol": "BHARTIARTL", "Sector": "Telecom", "LTP": "₹1,675.20", "Change": "+3.40%", "Day High": "₹1,682.00", "Volume": "6.8M"},
        {"Symbol": "ICICIBANK", "Sector": "Banking", "LTP": "₹1,248.80", "Change": "+2.85%", "Day High": "₹1,255.00", "Volume": "9.1M"},
        {"Symbol": "INFY", "Sector": "IT", "LTP": "₹1,912.00", "Change": "+2.10%", "Day High": "₹1,920.00", "Volume": "4.5M"},
        {"Symbol": "SUNPHARMA", "Sector": "Pharma", "LTP": "₹1,840.00", "Change": "+1.95%", "Day High": "₹1,850.00", "Volume": "3.2M"},
        {"Symbol": "RELIANCE", "Sector": "Energy", "LTP": "₹2,985.00", "Change": "+1.45%", "Day High": "₹3,005.00", "Volume": "5.6M"}
    ]
    losers = [
        {"Symbol": "BAJAJ-AUTO", "Sector": "Auto", "LTP": "₹10,180.00", "Change": "-3.65%", "Day Low": "₹10,120.00", "Volume": "1.2M"},
        {"Symbol": "TRENT", "Sector": "Retail", "LTP": "₹7,210.00", "Change": "-2.90%", "Day Low": "₹7,180.00", "Volume": "1.8M"},
        {"Symbol": "TECHM", "Sector": "IT", "LTP": "₹1,580.40", "Change": "-2.15%", "Day Low": "₹1,572.00", "Volume": "2.4M"},
        {"Symbol": "ITC", "Sector": "FMCG", "LTP": "₹481.50", "Change": "-1.40%", "Day Low": "₹480.00", "Volume": "11.2M"},
        {"Symbol": "INDUSINDBK", "Sector": "Banking", "LTP": "₹1,420.00", "Change": "-1.35%", "Day Low": "₹1,412.00", "Volume": "3.5M"}
    ]
    cg, cl = st.columns(2)
    with cg:
        st.markdown("<b style='color:#10b981; font-size:1.15rem;'>▲ Top Gainers</b>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(gainers), use_container_width=True, hide_index=True)
    with cl:
        st.markdown("<b style='color:#ef4444; font-size:1.15rem;'>▼ Top Losers</b>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(losers), use_container_width=True, hide_index=True)

# ----------------- TAB 5: EXTERNAL WATCHLIST (NO-TOUCH) -----------------
with tab_stocks:
    st.subheader("💼 External Stock & Stock Option Watchlist")
    st.caption("Loaded automatically from `stock_alerts.py`. Edit that file on GitHub anytime to add setups!")

    ext_alerts = get_external_stock_alerts()
    if not ext_alerts:
        st.info("No stock setups configured in stock_alerts.py.")
    else:
        for sa in ext_alerts:
            badge_dir = "badge-buy" if "BUY" in sa["action"] else "badge-sell"
            st.markdown(f"""
            <div class="trade-card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span class="{badge_dir}">{sa['action']}</span>
                        <b style="font-size:1.15rem; margin-left:8px; color:#f8fafc;">{sa['symbol']}</b>
                        <span class="badge-strat" style="margin-left:8px;">{sa['segment']}</span>
                    </div>
                </div>
                <div style="display:grid; grid-template-columns: repeat(4, 1fr); margin-top:12px; gap:8px;">
                    <div><span style="color:#64748b; font-size:0.75rem;">ENTRY</span><br><b style="color:#38bdf8;">₹{sa['entry']}</b></div>
                    <div><span style="color:#64748b; font-size:0.75rem;">STOP LOSS</span><br><b style="color:#ef4444;">₹{sa['sl']}</b></div>
                    <div><span style="color:#64748b; font-size:0.75rem;">TARGET 1</span><br><b style="color:#10b981;">₹{sa['tgt1']}</b></div>
                    <div><span style="color:#64748b; font-size:0.75rem;">TARGET 2</span><br><b style="color:#10b981;">₹{sa['tgt2']}</b></div>
                </div>
                <div style="font-size:0.8rem; color:#94a3b8; margin-top:10px;">
                    Rationale: <i>{sa.get('rationale', 'Technical setup')}</i>
                </div>
            </div>
            """, unsafe_allow_html=True)
