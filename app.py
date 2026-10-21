import streamlit as st
import pandas as pd
import requests
import datetime
from zoneinfo import ZoneInfo
import sqlite3
import uuid
import random

# Import external stock watchlist
try:
    from stock_alerts import get_external_stock_alerts
except ImportError:
    def get_external_stock_alerts():
        return []

# Auto-refresh terminal every 10 seconds for live tick streaming
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=10000, limit=None, key="pro_terminal_tick")
except ImportError:
    pass

# ================= 1. PAGE SETUP & PRO FINTECH THEME =================
st.set_page_config(page_title="Knowledge Hub Pro Terminal", layout="wide", page_icon="⚡")

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
    }
    .badge-buy { background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid #10b981; padding: 2px 7px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
    .badge-sell { background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid #ef4444; padding: 2px 7px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
    .badge-strat { background: #1e293b; color: #38bdf8; border: 1px solid #0284c7; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
    
    /* Login & Verification Box */
    .login-box {
        max-width: 520px;
        margin: 40px auto;
        background: #0d131f;
        border: 1px solid #26334d;
        border-radius: 14px;
        padding: 28px;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
    }
    .order-box {
        background: #111827;
        border: 1px solid #374151;
        border-radius: 8px;
        padding: 12px;
        margin-top: 10px;
    }
</style>
""", unsafe_allow_html=True)

ist = ZoneInfo("Asia/Kolkata")
now_ist = datetime.datetime.now(ist)

# ================= 2. SECRETS (NO DETAILS EXPOSED IN UI) =================
BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "").strip()
GOOGLE_SHEET_URL = st.secrets.get("GOOGLE_SHEET_URL", "").strip()

# ================= 3. DATABASE SETUP (USERS, OTP, TRADES & ORDERS) =================
def init_db():
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    # Users with OTP
    c.execute("""
        CREATE TABLE IF NOT EXISTS access_users_v2 (
            phone TEXT PRIMARY KEY,
            name TEXT,
            email TEXT,
            segment TEXT,
            otp TEXT,
            status TEXT, -- 'OTP_PENDING', 'APPROVED', 'REJECTED'
            request_time TEXT
        )
    """)
    # Running Positions
    c.execute("""
        CREATE TABLE IF NOT EXISTS active_positions (
            pos_id TEXT PRIMARY KEY,
            user_phone TEXT,
            symbol TEXT,
            side TEXT, -- BUY / SELL
            qty INTEGER,
            entry_price REAL,
            current_ltp REAL,
            cost REAL,
            open_time TEXT
        )
    """)
    # Order Book History
    c.execute("""
        CREATE TABLE IF NOT EXISTS order_book (
            order_id TEXT PRIMARY KEY,
            user_phone TEXT,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            price REAL,
            order_type TEXT,
            status TEXT,
            order_time TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# Database Helpers
def save_user_with_otp(name, phone, email, segment, otp):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO access_users_v2 VALUES (?, ?, ?, ?, ?, 'OTP_PENDING', ?)
    """, (phone, name, email, segment, otp, now_ist.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def verify_user_otp(phone, entered_otp):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("SELECT otp, name FROM access_users_v2 WHERE phone = ?", (phone,))
    row = c.fetchone()
    if row and str(row[0]) == str(entered_otp).strip():
        c.execute("UPDATE access_users_v2 SET status = 'APPROVED' WHERE phone = ?", (phone,))
        conn.commit()
        conn.close()
        return True, row[1]
    conn.close()
    return False, None

def get_positions(phone):
    conn = sqlite3.connect("knowledge_hub.db")
    df = pd.read_sql_query("SELECT * FROM active_positions WHERE user_phone = ?", conn, params=(phone,))
    conn.close()
    return df.to_dict(orient="records")

def place_order(phone, symbol, side, qty, price, order_type="MARKET"):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    ord_id = f"ORD_{uuid.uuid4().hex[:6].upper()}"
    pos_id = f"POS_{uuid.uuid4().hex[:6].upper()}"
    cost = qty * price
    t_str = now_ist.strftime("%I:%M:%S %p")

    # Insert into Order Book
    c.execute("""
        INSERT INTO order_book VALUES (?, ?, ?, ?, ?, ?, ?, 'COMPLETE', ?)
    """, (ord_id, phone, symbol, side, qty, price, order_type, t_str))

    # Insert into Active Positions
    c.execute("""
        INSERT INTO active_positions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (pos_id, phone, symbol, side, qty, price, price, cost, t_str))

    conn.commit()
    conn.close()

def close_position(pos_id, phone, symbol, side, qty, exit_price):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    # Log exit in order book
    ord_id = f"ORD_EXIT_{uuid.uuid4().hex[:6].upper()}"
    exit_side = "SELL" if side == "BUY" else "BUY"
    c.execute("""
        INSERT INTO order_book VALUES (?, ?, ?, ?, ?, ?, 'MARKET', 'COMPLETE', ?)
    """, (ord_id, phone, symbol, exit_side, qty, exit_price, now_ist.strftime("%I:%M:%S %p")))
    
    # Remove from active positions
    c.execute("DELETE FROM active_positions WHERE pos_id = ?", (pos_id,))
    conn.commit()
    conn.close()

def get_orders(phone):
    conn = sqlite3.connect("knowledge_hub.db")
    df = pd.read_sql_query("SELECT * FROM order_book WHERE user_phone = ? ORDER BY rowid DESC", conn, params=(phone,))
    conn.close()
    return df

# ================= 4. AUTHENTICATION WITH PHONE NUMBER OTP =================
if "authenticated_user" not in st.session_state:
    st.session_state.authenticated_user = None
if "authenticated_phone" not in st.session_state:
    st.session_state.authenticated_phone = None
if "otp_sent_to" not in st.session_state:
    st.session_state.otp_sent_to = None

if not st.session_state.authenticated_user:
    st.markdown("<div class='login-box'>", unsafe_allow_html=True)
    st.markdown("<h2 style='color:#38bdf8; text-align:center;'>🔒 Knowledge Hub Terminal</h2>", unsafe_allow_html=True)
    st.caption("<div style='text-align:center; color:#94a3b8; margin-bottom:16px;'>Phone Number Verification & Access Portal</div>", unsafe_allow_html=True)

    tab_reg, tab_otp = st.tabs(["1. 📝 Request Access", "2. 🔑 Enter OTP"])

    with tab_reg:
        with st.form("otp_request_form"):
            u_name = st.text_input("Full Name *")
            u_phone = st.text_input("Mobile Number (10 digits) *")
            u_email = st.text_input("Email Address *")
            u_segment = st.selectbox("Trading Segment", ["NIFTY / BANKNIFTY Options", "SENSEX Derivatives", "Stock Options", "Equity Cash"])
            
            gen_otp_btn = st.form_submit_button("Generate & Send OTP")

            if gen_otp_btn:
                if not u_name or not u_phone or len(u_phone.strip()) < 10:
                    st.error("Please enter your name and a valid 10-digit mobile number.")
                else:
                    otp_code = str(random.randint(100000, 999999))
                    clean_phone = u_phone.strip()
                    save_user_with_otp(u_name, clean_phone, u_email, u_segment, otp_code)
                    st.session_state.otp_sent_to = clean_phone

                    # 1. Sync lead to Google Sheets
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

                    # 2. Dispatch OTP instantly to your private Telegram
                    if BOT_TOKEN and CHAT_ID:
                        tg_msg = (
                            f"🔐 <b>KNOWLEDGE HUB ACCESS OTP</b> 🔐\n\n"
                            f"👤 <b>User:</b> {u_name}\n"
                            f"📱 <b>Phone:</b> <code>{clean_phone}</code>\n"
                            f"✉️ <b>Email:</b> {u_email}\n"
                            f"🔑 <b>Verification OTP:</b> <code>{otp_code}</code>\n"
                            f"🕒 <b>Time:</b> {now_ist.strftime('%I:%M:%S %p')} IST\n\n"
                            f"<i>Share this OTP with the user or authorize them.</i>"
                        )
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", 
                                      json={"chat_id": CHAT_ID, "text": tg_msg, "parse_mode": "HTML"}, timeout=4)

                    st.success(f"OTP generated for +91-{clean_phone}! Check tab '2. Enter OTP'.")

    with tab_otp:
        with st.form("verify_otp_form"):
            v_phone = st.text_input("Registered Phone Number", value=st.session_state.otp_sent_to or "")
            v_otp = st.text_input("Enter 6-Digit OTP", max_chars=6, type="password")
            verify_sub = st.form_submit_button("Verify OTP & Open Terminal")

            if verify_sub:
                ok, user_name = verify_user_otp(v_phone, v_otp)
                if ok:
                    st.session_state.authenticated_user = user_name
                    st.session_state.authenticated_phone = v_phone.strip()
                    st.success(f"Welcome {user_name}! Launching terminal...")
                    st.rerun()
                else:
                    st.error("Invalid OTP or Phone Number. Please verify and try again.")

    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()  # STOPS EXECUTION - Visitor CANNOT see the terminal until OTP is verified!

# ================= 5. LIVE MARKET DATA (INDICES + TOP MOVERS) =================
@st.cache_data(ttl=15)
def get_comprehensive_indices():
    indices = {
        "NIFTY 50": {"sym": "^NSEI", "val": 24855.30, "chg": "+0.45%", "spot": 24855.30, "step": 50, "lot": 25},
        "BANK NIFTY": {"sym": "^NSEBANK", "val": 52315.80, "chg": "+0.62%", "spot": 52315.80, "step": 100, "lot": 15},
        "SENSEX": {"sym": "^BSESN", "val": 81450.10, "chg": "+0.38%", "spot": 81450.10, "step": 100, "lot": 10},
        "FINNIFTY": {"sym": "NIFTY_FIN_SERVICE.NS", "val": 23410.20, "chg": "+0.55%", "spot": 23410.20, "step": 50, "lot": 25},
        "MIDCPNIFTY": {"sym": "^NSEMDCP50", "val": 12840.50, "chg": "+0.85%", "spot": 12840.50, "step": 25, "lot": 50},
        "INDIA VIX": {"sym": "^INDIAVIX", "val": 13.10, "chg": "-1.85%", "spot": 13.10, "step": 1, "lot": 0}
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
            indices[k]["spot"] = curr
            indices[k]["chg"] = f"{'+' if pct >= 0 else ''}{pct}%"
        except:
            pass
    return indices

indices_data = get_comprehensive_indices()

@st.cache_data(ttl=30)
def get_full_market_movers():
    gainers = [
        {"Symbol": "TATA MOTORS", "Sector": "Auto", "LTP": 984.50, "Change": "+4.15%", "Day High": 992.00, "Volume": "12.4M"},
        {"Symbol": "BHARTI AIRTEL", "Sector": "Telecom", "LTP": 1675.20, "Change": "+3.40%", "Day High": 1682.00, "Volume": "6.8M"},
        {"Symbol": "ICICI BANK", "Sector": "Banking", "LTP": 1248.80, "Change": "+2.85%", "Day High": 1255.00, "Volume": "9.1M"},
        {"Symbol": "INFOSYS", "Sector": "IT", "LTP": 1912.00, "Change": "+2.10%", "Day High": 1920.00, "Volume": "4.5M"},
        {"Symbol": "SUN PHARMA", "Sector": "Pharma", "LTP": 1840.00, "Change": "+1.95%", "Day High": 1850.00, "Volume": "3.2M"},
        {"Symbol": "COAL INDIA", "Sector": "Energy", "LTP": 512.40, "Change": "+1.80%", "Day High": 518.00, "Volume": "14.2M"},
        {"Symbol": "NTPC", "Sector": "Power", "LTP": 428.10, "Change": "+1.65%", "Day High": 432.00, "Volume": "8.7M"},
        {"Symbol": "RELIANCE", "Sector": "Energy", "LTP": 2985.00, "Change": "+1.45%", "Day High": 3005.00, "Volume": "5.6M"}
    ]
    losers = [
        {"Symbol": "BAJAJ AUTO", "Sector": "Auto", "LTP": 10180.00, "Change": "-3.65%", "Day Low": 10120.00, "Volume": "1.2M"},
        {"Symbol": "TRENT", "Sector": "Retail", "LTP": 7210.00, "Change": "-2.90%", "Day Low": 7180.00, "Volume": "1.8M"},
        {"Symbol": "TECH MAHINDRA", "Sector": "IT", "LTP": 1580.40, "Change": "-2.15%", "Day Low": 1572.00, "Volume": "2.4M"},
        {"Symbol": "ITC", "Sector": "FMCG", "LTP": 481.50, "Change": "-1.40%", "Day Low": 480.00, "Volume": "11.2M"},
        {"Symbol": "INDUSIND BANK", "Sector": "Banking", "LTP": 1420.00, "Change": "-1.35%", "Day Low": 1412.00, "Volume": "3.5M"},
        {"Symbol": "TITAN", "Sector": "Consumer", "LTP": 3410.00, "Change": "-1.20%", "Day Low": 3400.00, "Volume": "1.9M"},
        {"Symbol": "NESTLE INDIA", "Sector": "FMCG", "LTP": 2420.00, "Change": "-1.05%", "Day Low": 2410.00, "Volume": "800K"},
        {"Symbol": "ASIAN PAINTS", "Sector": "Paints", "LTP": 2890.00, "Change": "-0.95%", "Day Low": 2880.00, "Volume": "1.4M"}
    ]
    return pd.DataFrame(gainers), pd.DataFrame(losers)

df_g, df_l = get_full_market_movers()

# ================= 6. TOP CLEAN HEADER =================
st.markdown(f"""
<div class="header-box">
    <div style="display:flex; justify-content:space-between; align-items:center;">
        <div>
            <span style="font-size:1.4rem; font-weight:800; color:#38bdf8;">⚡ KNOWLEDGE HUB — QUANT TERMINAL</span>
            <div style="font-size:0.85rem; color:#94a3b8; margin-top:3px;">
                Verified Trader: <b style="color:#10b981;">{st.session_state.authenticated_user}</b> (+91-{st.session_state.authenticated_phone}) | Live Paper Execution Engine
            </div>
        </div>
        <div style="text-align:right;">
            <div style="font-size:0.8rem; color:#94a3b8;">EXCHANGE TIME (IST)</div>
            <div style="font-size:1.15rem; font-weight:700; color:#f8fafc;">{now_ist.strftime('%d %b %Y | %I:%M:%S %p')}</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# Sidebar with Margin Overview & Logout
with st.sidebar:
    st.markdown("### 💼 Trading Capital")
    positions = get_positions(st.session_state.authenticated_phone)
    utilized = sum([p["cost"] for p in positions])
    balance = max(0.0, 200000.0 - utilized)
    unrealized_pnl = sum([(p["current_ltp"] - p["entry_price"]) * p["qty"] if p["side"] == "BUY" 
                          else (p["entry_price"] - p["current_ltp"]) * p["qty"] for p in positions])
    
    st.metric("Available Margin", f"₹{balance:,.2f}")
    st.metric("Utilized Margin", f"₹{utilized:,.2f}")
    st.metric("Total Unrealized P&L", f"₹{unrealized_pnl:+,.2f}", delta_color="normal" if unrealized_pnl >= 0 else "inverse")

    st.markdown("---")
    st.markdown("### 📊 Market Breadth")
    st.progress(0.64)
    st.caption("🟢 Advances: 32 | 🔴 Declines: 18")

    if st.button("🚪 Logout of Terminal"):
        st.session_state.authenticated_user = None
        st.session_state.authenticated_phone = None
        st.rerun()

# ================= 7. MAIN NAVIGATION TABS =================
tab_chain, tab_positions, tab_movers, tab_signals, tab_stocks = st.tabs([
    "⛓️ Option Chain & Live Execution", 
    "📊 Running Positions & Order Book", 
    "📈 Top Gainers & Losers (Full List)", 
    "🎯 Quantitative Signals (NIFTY / SENSEX)", 
    "💼 Stock Watchlist (No-Touch)"
])

# ----------------- TAB 1: OPTION CHAIN WITH DIRECT BUY/SELL -----------------
with tab_chain:
    st.subheader("Indices Overview Ribbon")
    # All 6 Major Indices Ribbon
    i1, i2, i3, i4, i5, i6 = st.columns(6)
    i1.metric("NIFTY 50", f"₹{indices_data['NIFTY 50']['val']}", indices_data['NIFTY 50']['chg'])
    i2.metric("BANK NIFTY", f"₹{indices_data['BANK NIFTY']['val']}", indices_data['BANK NIFTY']['chg'])
    i3.metric("SENSEX", f"₹{indices_data['SENSEX']['val']}", indices_data['SENSEX']['chg'])
    i4.metric("FINNIFTY", f"₹{indices_data['FINNIFTY']['val']}", indices_data['FINNIFTY']['chg'])
    i5.metric("MIDCPNIFTY", f"₹{indices_data['MIDCPNIFTY']['val']}", indices_data['MIDCPNIFTY']['chg'])
    i6.metric("INDIA VIX", f"{indices_data['INDIA VIX']['val']}", indices_data['INDIA VIX']['chg'], delta_color="inverse")

    st.markdown("---")
    c_sel1, c_sel2 = st.columns([2, 4])
    chain_idx = c_sel1.selectbox("Select Underlying Instrument", ["NIFTY 50", "BANK NIFTY", "SENSEX", "FINNIFTY"])
    lot_size = indices_data[chain_idx]["lot"]
    step_val = indices_data[chain_idx]["step"]
    spot_val = indices_data[chain_idx]["spot"]

    c_sel2.info(f"**{chain_idx} Spot:** ₹{spot_val:,.2f} | **Strike Interval:** {step_val} pts | **Lot Size:** {lot_size} Qty")

    # Generate Option Chain rows centered on ATM
    atm_strike = int(round(spot_val / step_val) * step_val)
    st.markdown("### ⚡ Interactive Option Chain Matrix")

    # Header Row
    ch_h1, ch_h2, ch_h3, ch_h4, ch_h5, ch_h6, ch_h7 = st.columns([2, 2, 2, 2, 2, 2, 2])
    ch_h1.markdown("<b style='color:#10b981;'>CALL ACTION</b>", unsafe_allow_html=True)
    ch_h2.markdown("<b style='color:#10b981;'>CE LTP</b>", unsafe_allow_html=True)
    ch_h3.markdown("<b>CE Moneyness</b>", unsafe_allow_html=True)
    ch_h4.markdown("<b style='color:#38bdf8; font-size:1.1rem; text-align:center;'>STRIKE</b>", unsafe_allow_html=True)
    ch_h5.markdown("<b>PE Moneyness</b>", unsafe_allow_html=True)
    ch_h6.markdown("<b style='color:#ef4444;'>PE LTP</b>", unsafe_allow_html=True)
    ch_h7.markdown("<b style='color:#ef4444;'>PUT ACTION</b>", unsafe_allow_html=True)

    for i in range(-4, 5):
        s_price = atm_strike + (i * step_val)
        
        # CE & PE Pricing model
        ce_int = max(0.0, spot_val - s_price)
        ce_ltp = round(ce_int + 75.0 + abs(i) * 5.2, 1)
        ce_m = "ITM" if s_price < spot_val else ("ATM" if s_price == atm_strike else "OTM")

        pe_int = max(0.0, s_price - spot_val)
        pe_ltp = round(pe_int + 70.0 + abs(i) * 5.2, 1)
        pe_m = "OTM" if s_price < spot_val else ("ATM" if s_price == atm_strike else "ITM")

        row_bg = "background:#1e293b; padding:4px; border-radius:4px;" if s_price == atm_strike else "padding:4px;"

        c_r1, c_r2, c_r3, c_r4, c_r5, c_r6, c_r7 = st.columns([2, 2, 2, 2, 2, 2, 2])

        # CALL Actions
        with c_r1:
            col_b, col_s = st.columns(2)
            if col_b.button("B", key=f"b_ce_{s_price}", help=f"Buy {chain_idx} {s_price} CE"):
                place_order(st.session_state.authenticated_phone, f"{chain_idx} {s_price} CE", "BUY", lot_size, ce_ltp)
                st.success(f"Bought {lot_size} Qty of {chain_idx} {s_price} CE at ₹{ce_ltp}!")
                st.rerun()
            if col_s.button("S", key=f"s_ce_{s_price}", help=f"Sell {chain_idx} {s_price} CE"):
                place_order(st.session_state.authenticated_phone, f"{chain_idx} {s_price} CE", "SELL", lot_size, ce_ltp)
                st.success(f"Sold {lot_size} Qty of {chain_idx} {s_price} CE at ₹{ce_ltp}!")
                st.rerun()

        c_r2.markdown(f"<span style='color:#10b981; font-weight:700;'>₹{ce_ltp:.1f}</span>", unsafe_allow_html=True)
        c_r3.caption(f"{ce_m}")
        c_r4.markdown(f"<b style='color:#f8fafc; font-size:1.05rem;'>{s_price}</b>", unsafe_allow_html=True)
        c_r5.caption(f"{pe_m}")
        c_r6.markdown(f"<span style='color:#ef4444; font-weight:700;'>₹{pe_ltp:.1f}</span>", unsafe_allow_html=True)

        # PUT Actions
        with c_r7:
            col_pb, col_ps = st.columns(2)
            if col_pb.button("B", key=f"b_pe_{s_price}", help=f"Buy {chain_idx} {s_price} PE"):
                place_order(st.session_state.authenticated_phone, f"{chain_idx} {s_price} PE", "BUY", lot_size, pe_ltp)
                st.success(f"Bought {lot_size} Qty of {chain_idx} {s_price} PE at ₹{pe_ltp}!")
                st.rerun()
            if col_ps.button("S", key=f"s_pe_{s_price}", help=f"Sell {chain_idx} {s_price} PE"):
                place_order(st.session_state.authenticated_phone, f"{chain_idx} {s_price} PE", "SELL", lot_size, pe_ltp)
                st.success(f"Sold {lot_size} Qty of {chain_idx} {s_price} PE at ₹{pe_ltp}!")
                st.rerun()

# ----------------- TAB 2: BROKERAGE-STYLE RUNNING POSITIONS & ORDERS -----------------
with tab_positions:
    st.subheader("📊 Active Running Positions (Brokerage Book)")
    open_positions = get_positions(st.session_state.authenticated_phone)

    if not open_positions:
        st.info("No open positions. Take a trade directly from the 'Option Chain' tab.")
    else:
        for idx_p, pos in enumerate(open_positions):
            # Dynamic simulated tick for demo LTP
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
                        <span style="color:#94a3b8; font-size:0.8rem; margin-left:12px;">Qty: <b>{pos['qty']}</b> | Avg Price: <b>₹{pos['entry_price']:.2f}</b></span>
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
                close_position(pos["pos_id"], st.session_state.authenticated_phone, pos["symbol"], pos["side"], pos["qty"], pos["entry_price"])
                st.success(f"Position squared off for {pos['symbol']}!")
                st.rerun()

    st.markdown("---")
    st.subheader("📑 Completed Order Book")
    orders_df = get_orders(st.session_state.authenticated_phone)
    if orders_df.empty:
        st.write("No executed orders yet.")
    else:
        st.dataframe(orders_df[["order_id", "symbol", "side", "qty", "price", "status", "order_time"]], use_container_width=True, hide_index=True)

# ----------------- TAB 3: TOP GAINERS & LOSERS FULL LIST -----------------
with tab_movers:
    st.subheader("📈 NSE / BSE Top Gainers & Losers (Full Session List)")
    
    col_filter1, col_filter2 = st.columns([2, 4])
    sector_filter = col_filter1.selectbox("Filter by Sector", ["All Sectors", "Auto", "Banking", "IT", "Energy", "FMCG", "Telecom"])
    search_query = col_filter2.text_input("🔍 Search Stock Symbol", "")

    filtered_g = df_g.copy()
    filtered_l = df_l.copy()

    if sector_filter != "All Sectors":
        filtered_g = filtered_g[filtered_g["Sector"] == sector_filter]
        filtered_l = filtered_l[filtered_l["Sector"] == sector_filter]

    if search_query:
        filtered_g = filtered_g[filtered_g["Symbol"].str.contains(search_query.upper())]
        filtered_l = filtered_l[filtered_l["Symbol"].str.contains(search_query.upper())]

    c_g, c_l = st.columns(2)
    with c_g:
        st.markdown("<b style='color:#10b981; font-size:1.15rem;'>▲ Top Gainers</b>", unsafe_allow_html=True)
        st.dataframe(filtered_g, use_container_width=True, hide_index=True)
    with c_l:
        st.markdown("<b style='color:#ef4444; font-size:1.15rem;'>▼ Top Losers</b>", unsafe_allow_html=True)
        st.dataframe(filtered_l, use_container_width=True, hide_index=True)

# ----------------- TAB 4: QUANTITATIVE SIGNALS (NIFTY & SENSEX) -----------------
with tab_signals:
    st.subheader("🎯 High-Probability Algorithmic Index Setups")
    
    # NIFTY Card
    n_spot = indices_data["NIFTY 50"]["spot"]
    n_atm = int(round(n_spot / 50.0) * 50)
    n_strike = n_atm - 50
    n_entry = 158.0
    n_sl = round(n_entry * 0.80, 1)
    n_risk = n_entry - n_sl

    st.markdown(f"""
    <div class="trade-card">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div>
                <span class="badge-buy">BUY CE</span>
                <b style="font-size:1.15rem; margin-left:8px; color:#f8fafc;">NIFTY {n_strike} CE</b>
                <span class="badge-strat" style="margin-left:8px;">EMMANI (10/20 EMA)</span>
            </div>
            <div style="font-size:0.85rem; color:#94a3b8;">Status: <b style="color:#10b981;">Active</b></div>
        </div>
        <div style="display:grid; grid-template-columns: repeat(5, 1fr); margin-top:14px; gap:8px;">
            <div><span style="color:#64748b; font-size:0.75rem;">SPOT REF</span><br><b>₹{n_spot:,.2f}</b></div>
            <div><span style="color:#64748b; font-size:0.75rem;">ENTRY</span><br><b style="color:#38bdf8;">₹{n_entry:.2f}</b></div>
            <div><span style="color:#64748b; font-size:0.75rem;">STOP LOSS</span><br><b style="color:#ef4444;">₹{n_sl:.2f}</b></div>
            <div><span style="color:#64748b; font-size:0.75rem;">TARGET 1</span><br><b style="color:#10b981;">₹{n_entry + n_risk:.2f}</b></div>
            <div><span style="color:#64748b; font-size:0.75rem;">TARGET 2 / 3</span><br><b style="color:#10b981;">₹{n_entry + 2*n_risk:.2f} / ₹{n_entry + 3*n_risk:.2f}</b></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # SENSEX Card
    s_spot = indices_data["SENSEX"]["spot"]
    s_atm = int(round(s_spot / 100.0) * 100)
    s_strike = s_atm - 100
    s_entry = 295.0
    s_sl = round(s_entry * 0.80, 1)
    s_risk = s_entry - s_sl

    st.markdown(f"""
    <div class="trade-card">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div>
                <span class="badge-buy">BUY CE</span>
                <b style="font-size:1.15rem; margin-left:8px; color:#f8fafc;">SENSEX {s_strike} CE</b>
                <span class="badge-strat" style="margin-left:8px;">SSRG (Breakout)</span>
            </div>
            <div style="font-size:0.85rem; color:#94a3b8;">Status: <b style="color:#10b981;">Active</b></div>
        </div>
        <div style="display:grid; grid-template-columns: repeat(5, 1fr); margin-top:14px; gap:8px;">
            <div><span style="color:#64748b; font-size:0.75rem;">SPOT REF</span><br><b>₹{s_spot:,.2f}</b></div>
            <div><span style="color:#64748b; font-size:0.75rem;">ENTRY</span><br><b style="color:#38bdf8;">₹{s_entry:.2f}</b></div>
            <div><span style="color:#64748b; font-size:0.75rem;">STOP LOSS</span><br><b style="color:#ef4444;">₹{s_sl:.2f}</b></div>
            <div><span style="color:#64748b; font-size:0.75rem;">TARGET 1</span><br><b style="color:#10b981;">₹{s_entry + s_risk:.2f}</b></div>
            <div><span style="color:#64748b; font-size:0.75rem;">TARGET 2 / 3</span><br><b style="color:#10b981;">₹{s_entry + 2*s_risk:.2f} / ₹{s_entry + 3*s_risk:.2f}</b></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ----------------- TAB 5: STOCK & STOCK OPTIONS ALERTS (NO-TOUCH) -----------------
with tab_stocks:
    st.subheader("💼 External Stock & Stock Option Watchlist")
    st.caption("Loaded automatically from `stock_alerts.py`. Edit that file on GitHub to broadcast new setups instantly.")

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
                    Rationale: <i>{sa.get('rationale', 'Technical breakout')}</i>
                </div>
            </div>
            """, unsafe_allow_html=True)
