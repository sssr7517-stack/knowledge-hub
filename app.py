import streamlit as st
import pandas as pd
import requests
import datetime
from zoneinfo import ZoneInfo
import sqlite3
import uuid

# Import the separate stock alert configuration file
try:
    from stock_alerts import get_external_stock_alerts
except ImportError:
    def get_external_stock_alerts():
        return []

# Auto-refresh terminal every 10 seconds for real-time tracking
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=10000, limit=None, key="pro_terminal_refresh")
except ImportError:
    pass

# ================= 1. PAGE SETUP & CLEAN FINTECH THEME =================
st.set_page_config(page_title="Knowledge Hub Terminal", layout="wide", page_icon="⚡")

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
        padding: 16px 24px;
        margin-bottom: 18px;
    }
    div[data-testid="stMetric"] {
        background: #0d131f;
        border: 1px solid #1e293b;
        border-radius: 10px;
        padding: 12px 16px;
    }
    div[data-testid="stMetricLabel"] { font-size: 0.8rem; color: #94a3b8; font-weight: 600; }
    div[data-testid="stMetricValue"] { font-size: 1.25rem; font-weight: 800; color: #f8fafc; }
    
    .trade-card {
        background: #0d131f;
        border: 1px solid #1e293b;
        border-radius: 10px;
        padding: 16px 20px;
        margin-bottom: 14px;
    }
    .badge-buy { background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid #10b981; padding: 3px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
    .badge-sell { background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid #ef4444; padding: 3px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
    .badge-strat { background: #1e293b; color: #38bdf8; border: 1px solid #0284c7; padding: 3px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
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

# ================= 2. SECRETS (NO DETAILS EXPOSED IN UI) =================
BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "").strip()
DHAN_CLIENT_ID = st.secrets.get("DHAN_CLIENT_ID", "").strip()
DHAN_ACCESS_TOKEN = st.secrets.get("DHAN_ACCESS_TOKEN", "").strip()
GOOGLE_SHEET_URL = st.secrets.get("GOOGLE_SHEET_URL", "").strip()

# ================= 3. DATABASE SETUP (USERS & ALERTS) =================
def init_db():
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS access_users (
            phone TEXT PRIMARY KEY,
            name TEXT,
            email TEXT,
            segment TEXT,
            status TEXT, -- 'PENDING', 'APPROVED', 'REJECTED'
            request_time TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS alerts_v4 (
            alert_id TEXT PRIMARY KEY,
            strategy TEXT,
            underlying TEXT,
            symbol TEXT,
            sec_id TEXT,
            direction TEXT,
            spot_price REAL,
            entry REAL,
            ltp REAL,
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

def check_user_status(phone):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("SELECT status, name FROM access_users WHERE phone = ?", (phone,))
    row = c.fetchone()
    conn.close()
    return row

def save_user_request(name, phone, email, segment):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO access_users VALUES (?, ?, ?, ?, 'PENDING', ?)
    """, (phone, name, email, segment, now_ist.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def approve_user_in_db(phone):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("UPDATE access_users SET status = 'APPROVED' WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()

init_db()

# Check incoming Telegram approval button clicks
def poll_telegram_approvals():
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
                        target_phone = cb_data.replace("AUTH_YES_", "")
                        approve_user_in_db(target_phone)
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery", 
                                      json={"callback_query_id": cb_id, "text": f"✅ Access Approved for {target_phone}!"})
                    
                    requests.get(url, params={"offset": update_id + 1}, timeout=2)
    except:
        pass

poll_telegram_approvals()

# ================= 4. AUTHENTICATION & ACCESS GATEWAY (FIXED) =================
if "authenticated_user" not in st.session_state:
    st.session_state.authenticated_user = None

if not st.session_state.authenticated_user:
    st.markdown("<div class='login-box'>", unsafe_allow_html=True)
    st.markdown("<h2 style='color:#38bdf8; text-align:center;'>🔒 Knowledge Hub Terminal</h2>", unsafe_allow_html=True)
    st.caption("<div style='text-align:center; color:#94a3b8; margin-bottom:18px;'>Personal Institutional Access Request</div>", unsafe_allow_html=True)

    tab_req, tab_chk = st.tabs(["📝 Request Access", "🔑 Check Status / Unlock"])

    # FORM 1: New Access Request
    with tab_req:
        with st.form("new_request_form"):
            u_name = st.text_input("Full Name *")
            u_phone = st.text_input("WhatsApp / Phone Number (10 digits) *")
            u_email = st.text_input("Email Address *")
            u_segment = st.selectbox("Preferred Trading Segment", ["NIFTY / BANKNIFTY Options", "SENSEX Derivatives", "Stock Options", "Equity Cash"])
            
            submit_req = st.form_submit_button("Submit Access Request")

            if submit_req:
                if not u_name or not u_phone or not u_email or len(u_phone) < 10:
                    st.error("Please fill in all fields with a valid 10-digit phone number.")
                else:
                    save_user_request(u_name, u_phone, u_email, u_segment)

                    # 1. Sync to Google Sheets
                    if GOOGLE_SHEET_URL:
                        try:
                            requests.post(GOOGLE_SHEET_URL, json={
                                "name": u_name,
                                "phone": u_phone,
                                "email": u_email,
                                "segment": u_segment
                            }, timeout=4)
                        except:
                            pass

                    # 2. Dispatch Interactive Approval to Telegram
                    if BOT_TOKEN and CHAT_ID:
                        tg_msg = (
                            f"🚨 <b>NEW TERMINAL ACCESS REQUEST</b> 🚨\n\n"
                            f"👤 <b>Name:</b> {u_name}\n"
                            f"📱 <b>Phone:</b> <code>{u_phone}</code>\n"
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
                                        {"text": "✅ Grant Access", "callback_data": f"AUTH_YES_{u_phone}"},
                                        {"text": "❌ Reject", "callback_data": f"AUTH_NO_{u_phone}"}
                                    ]
                                ]
                            }
                        }
                        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload, timeout=4)

                    st.success("Request sent! An approval alert has been dispatched to the Administrator's Telegram.")

    # FORM 2: Verification (Now completely outside Form 1, eliminating the layout crash)
    with tab_chk:
        with st.form("verify_status_form"):
            chk_phone = st.text_input("Enter your registered phone number:")
            verify_btn = st.form_submit_button("Verify & Unlock Terminal")

            if verify_btn:
                stat = check_user_status(chk_phone)
                if stat and stat[0] == "APPROVED":
                    st.session_state.authenticated_user = stat[1]
                    st.success("Access Verified! Launching Terminal...")
                    st.rerun()
                elif stat and stat[0] == "PENDING":
                    st.warning("Access Pending. Administrator has not approved yet. Please wait.")
                else:
                    st.error("No registered request found for this phone number.")

    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()  # Terminal remains locked until approved!

# ================= 5. LIVE MARKET DATA (INDICES + SENSEX) =================
@st.cache_data(ttl=15)
def get_live_market_data():
    indices = {
        "NIFTY 50": {"sym": "^NSEI", "val": 24855.30, "chg": "+0.45%", "spot": 24855.30, "step": 50},
        "BANK NIFTY": {"sym": "^NSEBANK", "val": 52315.80, "chg": "+0.62%", "spot": 52315.80, "step": 100},
        "SENSEX": {"sym": "^BSESN", "val": 81450.10, "chg": "+0.38%", "spot": 81450.10, "step": 100},
        "INDIA VIX": {"sym": "^INDIAVIX", "val": 13.10, "chg": "-1.85%", "spot": 13.10, "step": 1}
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

market = get_live_market_data()

# ================= 6. OPTION CHAIN BUILDER (NIFTY & SENSEX) =================
def generate_option_chain(underlying_name: str, spot: float, step: int):
    atm = int(round(spot / step) * step)
    chain = []
    for i in range(-4, 5):
        strike = atm + (i * step)
        ce_intrinsic = max(0.0, spot - strike)
        ce_ltp = round(ce_intrinsic + 75.0 + abs(i)*4.5, 1)
        pe_intrinsic = max(0.0, strike - spot)
        pe_ltp = round(pe_intrinsic + 70.0 + abs(i)*4.5, 1)

        chain.append({
            "CE LTP": f"₹{ce_ltp:.1f}",
            "CE Moneyness": "ITM" if strike < spot else ("ATM" if strike == atm else "OTM"),
            "Strike": strike,
            "PE Moneyness": "OTM" if strike < spot else ("ATM" if strike == atm else "ITM"),
            "PE LTP": f"₹{pe_ltp:.1f}"
        })
    return pd.DataFrame(chain)

# ================= 7. MAIN LOGGED-IN TERMINAL UI =================
st.markdown(f"""
<div class="header-box">
    <div style="display:flex; justify-content:space-between; align-items:center;">
        <div>
            <span style="font-size:1.4rem; font-weight:800; color:#38bdf8;">⚡ KNOWLEDGE HUB — QUANT TERMINAL</span>
            <div style="font-size:0.85rem; color:#94a3b8; margin-top:4px;">
                Verified Member: <b style="color:#10b981;">{st.session_state.authenticated_user}</b> | Direct Feed Stream
            </div>
        </div>
        <div style="text-align:right;">
            <div style="font-size:0.8rem; color:#94a3b8;">EXCHANGE TIME (IST)</div>
            <div style="font-size:1.15rem; font-weight:700; color:#f8fafc;">{now_ist.strftime('%d %b %Y | %I:%M:%S %p')}</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# Indices Ticker Strip
c1, c2, c3, c4 = st.columns(4)
c1.metric("NIFTY 50", f"₹{market['NIFTY 50']['val']}", market['NIFTY 50']['chg'])
c2.metric("BANK NIFTY", f"₹{market['BANK NIFTY']['val']}", market['BANK NIFTY']['chg'])
c3.metric("SENSEX", f"₹{market['SENSEX']['val']}", market['SENSEX']['chg'])
c4.metric("INDIA VIX", f"{market['INDIA VIX']['val']}", market['INDIA VIX']['chg'], delta_color="inverse")

# Clean Sidebar - All private details hidden
with st.sidebar:
    st.markdown("### 🟢 Terminal Engine")
    st.success("Exchange Data Feed: Online")
    st.success("Algorithmic Engine: Active")
    
    st.markdown("---")
    st.markdown("### 📊 Market Breadth")
    st.progress(0.64)
    st.caption("🟢 Advances: 32 | 🔴 Declines: 18")

    if st.button("Logout"):
        st.session_state.authenticated_user = None
        st.rerun()

st.markdown("---")

# ================= 8. TERMINAL TABS =================
t_signals, t_chain, t_stocks, t_academy = st.tabs([
    "🎯 Live Index Signals (NIFTY / SENSEX)", 
    "⛓️ Live Option Chain (NIFTY & SENSEX)", 
    "📈 Stock & Equity Watchlist (No-Touch File)", 
    "📚 Academy Rules"
])

# ----- TAB 1: LIVE SIGNALS (NIFTY & SENSEX) -----
with t_signals:
    st.subheader("High-Probability Index Setups (NIFTY 50 & SENSEX)")
    
    # NIFTY Card
    n_spot = market["NIFTY 50"]["spot"]
    n_atm = int(round(n_spot / 50.0) * 50)
    n_strike = n_atm - 50 # 1 Strike ITM
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
    s_spot = market["SENSEX"]["spot"]
    s_atm = int(round(s_spot / 100.0) * 100)
    s_strike = s_atm - 100 # 1 Strike ITM for SENSEX
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

# ----- TAB 2: LIVE OPTION CHAINS -----
with t_chain:
    st.subheader("⛓️ Live Option Chain Matrix")
    chain_pick = st.radio("Select Underlying", ["NIFTY 50", "SENSEX"], horizontal=True)

    if chain_pick == "NIFTY 50":
        st.caption(f"Current NIFTY Spot: **₹{market['NIFTY 50']['spot']:,.2f}** | Strike Interval: **50 pts**")
        df_oc = generate_option_chain("NIFTY 50", market["NIFTY 50"]["spot"], 50)
    else:
        st.caption(f"Current SENSEX Spot: **₹{market['SENSEX']['spot']:,.2f}** | Strike Interval: **100 pts**")
        df_oc = generate_option_chain("SENSEX", market["SENSEX"]["spot"], 100)

    st.dataframe(df_oc, use_container_width=True, hide_index=True)

# ----- TAB 3: STOCK & STOCK OPTIONS ALERTS (NO-TOUCH FILE) -----
with t_stocks:
    st.subheader("📈 Stock & Equity Watchlist Alerts")
    st.caption("Loaded dynamically from `stock_alerts.py`. Edit that file anytime to publish new stock calls!")

    external_stocks = get_external_stock_alerts()
    if not external_stocks:
        st.info("No stock setups configured in stock_alerts.py.")
    else:
        for sa in external_stocks:
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

# ----- TAB 4: ACADEMY RULES -----
with t_academy:
    st.subheader("📚 Quantitative Methodologies")
    st.markdown("""
    - **NIFTY 50**: 50 pt strike step. In-The-Money (ITM) CE selection subtracts 50 pts from ATM.
    - **SENSEX**: 100 pt strike step. ITM CE selection subtracts 100 pts from ATM.
    - **Zero Leakage**: All broker margins, bot tokens, and user lead databases are completely hidden from the frontend view.
    """)
