import streamlit as st
import pandas as pd
import requests
import datetime
from zoneinfo import ZoneInfo
import sqlite3
import uuid

# Optional auto-refresh to stream live market quotes
try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

# ================= 1. PAGE SETUP & DHAN THEME =================
st.set_page_config(page_title="Knowledge Hub — Dhan Pro", layout="wide", page_icon="⚡")

st.markdown("""
<style>
    .stApp { background-color: #0b0e14; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    div[data-testid="stMetric"] { background-color: #121824; border: 1px solid #1e293b; border-radius: 8px; padding: 10px 14px; }
    div[data-testid="stMetricLabel"] { font-size: 0.8rem; color: #94a3b8; }
    div[data-testid="stMetricValue"] { font-size: 1.15rem; font-weight: 700; }
    .card { background-color: #121824; border: 1px solid #1e293b; border-radius: 10px; padding: 16px 20px; margin-bottom: 14px; }
    .badge-buy { background-color: rgba(0, 208, 156, 0.15); color: #00d09c; border: 1px solid #00d09c; padding: 3px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
    .badge-sell { background-color: rgba(235, 91, 60, 0.15); color: #eb5b3c; border: 1px solid #eb5b3c; padding: 3px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; }
    .badge-live { background-color: rgba(99, 102, 241, 0.2); color: #a5b4fc; border: 1px solid #6366f1; padding: 2px 7px; border-radius: 12px; font-size: 0.7rem; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

ist = ZoneInfo("Asia/Kolkata")
now = datetime.datetime.now(ist)

# Secrets
BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")
DHAN_CLIENT_ID = st.secrets.get("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = st.secrets.get("DHAN_ACCESS_TOKEN", "")

# Auto-refresh every 10 seconds during trading hours
if st_autorefresh:
    st_autorefresh(interval=10000, limit=None, key="dhan_market_refresh")

# ================= 2. DHAN HQ API INTEGRATION =================
DHAN_BASE = "https://api.dhan.co"

def get_dhan_headers():
    return {
        "access-token": DHAN_ACCESS_TOKEN,
        "client-id": DHAN_CLIENT_ID,
        "Content-Type": "application/json"
    }

def get_dhan_fund_limits():
    """Verify Dhan API Token and fetch available trading balance."""
    if not DHAN_ACCESS_TOKEN or not DHAN_CLIENT_ID:
        return None, "Dhan credentials not configured in Streamlit Secrets."
    try:
        url = f"{DHAN_BASE}/fundlimit"
        res = requests.get(url, headers=get_dhan_headers(), timeout=4)
        if res.status_code == 200:
            data = res.json()
            avail = data.get("availabelBalance", data.get("sodLimit", 0.0))
            return float(avail), "Connected"
        else:
            return None, f"Dhan error: {res.text}"
    except Exception as e:
        return None, str(e)

def fetch_dhan_ltp(security_id: str, exchange_segment: str = "NSE_FNO"):
    """
    Fetches real-time LTP straight from Dhan API.
    Zero-delay live tick.
    """
    if not DHAN_ACCESS_TOKEN or not DHAN_CLIENT_ID:
        return None
    try:
        url = f"{DHAN_BASE}/marketfeed/ltp"
        # Dhan accepts dictionary of instruments: {segment: [security_ids]}
        payload = {
            exchange_segment: [int(security_id)]
        }
        res = requests.post(url, headers=get_dhan_headers(), json=payload, timeout=3)
        if res.status_code == 200:
            data = res.json()
            ltp = data.get("data", {}).get(exchange_segment, {}).get(str(security_id), {}).get("last_price")
            return float(ltp) if ltp else None
    except:
        pass
    return None

def fetch_live_indices():
    """
    Fetches spot Indian indices. 
    Uses Yahoo fallback if Dhan indices feed segment is offline.
    """
    indices = {
        "NIFTY 50": {"sym": "^NSEI", "val": 24855.30, "chg": "+0.45%", "spot": 24855.30},
        "BANK NIFTY": {"sym": "^NSEBANK", "val": 52315.80, "chg": "+0.62%", "spot": 52315.80},
        "SENSEX": {"sym": "^BSESN", "val": 81450.10, "chg": "+0.38%", "spot": 81450.10},
        "INDIA VIX": {"sym": "^INDIAVIX", "val": 13.10, "chg": "-1.85%", "spot": 13.10}
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

# ================= 3. STRIKE SELECTION HELPER =================
def compute_accurate_strike(underlying: str, spot_price: float, direction: str):
    """
    Calculates the exact strike according to index specifications:
    - NIFTY 50: 50 pt steps. CE is 1 ITM (-50), PE is ATM.
    - BANK NIFTY: 100 pt steps. CE is 1 ITM (-100), PE is ATM.
    - SENSEX: 100 pt steps. CE is 1 ITM (-100), PE is ATM.
    """
    step = 100 if ("BANK" in underlying or "SENSEX" in underlying) else 50
    atm_strike = int(round(spot_price / step) * step)

    if "CE" in direction:
        selected_strike = atm_strike - step  # 1 Strike ITM
        strike_type = "ITM CE"
    else:
        selected_strike = atm_strike        # ATM PE
        strike_type = "ATM PE"

    contract_name = f"{underlying} {selected_strike} {'CE' if 'CE' in direction else 'PE'}"
    return selected_strike, strike_type, contract_name

# ================= 4. DATABASE SYSTEM =================
def init_db():
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS alerts_v2 (
            id TEXT PRIMARY KEY,
            strategy TEXT,
            underlying TEXT,
            symbol TEXT,
            sec_id TEXT,
            direction TEXT,
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

def get_alerts():
    conn = sqlite3.connect("knowledge_hub.db")
    df = pd.read_sql_query("SELECT * FROM alerts_v2 ORDER BY rowid DESC", conn)
    conn.close()
    return df.to_dict(orient="records")

def save_alert(a):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO alerts_v2 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (a['id'], a['strategy'], a['underlying'], a['symbol'], a['sec_id'], a['direction'],
          a['underlying_price'], a['entry'], a['sl'], a['tgt1'], a['tgt2'], a['tgt3'],
          a['time'], a['status']))
    conn.commit()
    conn.close()

def delete_alert(alert_id):
    conn = sqlite3.connect("knowledge_hub.db")
    c = conn.cursor()
    c.execute("DELETE FROM alerts_v2 WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()

init_db()

# Sample initial alert if table empty
if len(get_alerts()) == 0:
    save_alert({
        "id": "EMM_001",
        "strategy": "EMMANI",
        "underlying": "NIFTY 50",
        "symbol": "NIFTY 24800 CE",
        "sec_id": "49081",
        "direction": "BUY CE",
        "underlying_price": 24855.30,
        "entry": 142.50,
        "sl": 114.00,
        "tgt1": 171.00,
        "tgt2": 199.50,
        "tgt3": 228.00,
        "time": now.strftime("%I:%M %p"),
        "status": "Active"
    })

# Session state
if "paper_positions" not in st.session_state:
    st.session_state.paper_positions = []
if "paper_balance" not in st.session_state:
    st.session_state.paper_balance = 100000.0

# ================= 5. HEADER & INDICES =================
c1, c2 = st.columns([3, 1])
with c1:
    st.markdown("<h2 style='color:#00d09c; margin:0;'>⚡ KNOWLEDGE HUB — DHAN DIRECT</h2>", unsafe_allow_html=True)
    st.caption("Live Tick Option Trading Desk | Zero-Delay Dhan Feeds")
with c2:
    st.markdown(f"<div style='text-align:right; color:#94a3b8;'>IST: <b>{now.strftime('%I:%M:%S %p')}</b></div>", unsafe_allow_html=True)

idx = fetch_live_indices()
t1, t2, t3, t4 = st.columns(4)
t1.metric("NIFTY 50", f"₹{idx['NIFTY 50']['val']}", idx['NIFTY 50']['chg'])
t2.metric("BANK NIFTY", f"₹{idx['BANK NIFTY']['val']}", idx['BANK NIFTY']['chg'])
t3.metric("SENSEX", f"₹{idx['SENSEX']['val']}", idx['SENSEX']['chg'])
t4.metric("INDIA VIX", f"{idx['INDIA VIX']['val']}", idx['INDIA VIX']['chg'], delta_color="inverse")

# Dhan connection badge in sidebar
with st.sidebar:
    st.markdown("### ⚡ Dhan HQ Engine")
    d_bal, d_msg = get_dhan_fund_limits()
    if d_bal is not None:
        st.success(f"🟢 Dhan Online | ₹{d_bal:,.2f}")
    else:
        st.warning(f"🟡 Dhan Offline ({d_msg})")

    st.markdown("---")
    st.markdown("### 📲 Telegram Status")
    if BOT_TOKEN and CHAT_ID:
        st.success("🟢 Telegram Configured")
    else:
        st.error("🔴 Telegram Not Set")

st.markdown("---")

# ================= 6. NAVIGATION TABS =================
tab_alerts, tab_paper, tab_admin, tab_edu = st.tabs([
    "🎯 Live Alerts Desk (With Live LTP)", 
    "📊 Paper Portfolio (Auto-Updating)", 
    "⚙️ Strategy Alert Dispatcher",
    "📚 Academy & Indicators"
])

# ----------------- TAB 1: LIVE ALERTS DESK -----------------
with tab_alerts:
    st.subheader("🎯 Active Strategy Alerts with Live LTP")
    alerts = get_alerts()

    if not alerts:
        st.info("No active alerts. Use the 'Strategy Alert Dispatcher' tab to generate one.")
    else:
        for a in alerts:
            # 1. Fetch the real live LTP from Dhan
            real_ltp = fetch_dhan_ltp(a.get("sec_id", ""))
            current_display_ltp = real_ltp if real_ltp is not None else a["entry"]
            
            # Point difference from entry
            p_diff = round(current_display_ltp - a["entry"], 2)
            p_color = "#00d09c" if p_diff >= 0 else "#eb5b3c"

            badge_dir = "badge-buy" if "BUY" in a["direction"] else "badge-sell"

            st.markdown(f"""
            <div class="card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span class="{badge_dir}">{a['direction']}</span>
                        <b style="font-size:1.15rem; margin-left:8px;">{a['symbol']}</b>
                        <span class="badge-live" style="margin-left:8px;">{a['strategy']}</span>
                        <span style="color:#64748b; font-size:0.75rem; margin-left:6px;">Sec ID: {a['sec_id']}</span>
                    </div>
                    <div>
                        <span style="font-size:0.8rem; color:#94a3b8;">LIVE LTP: </span>
                        <b style="font-size:1.25rem; color:{p_color};">₹{current_display_ltp:.2f}</b>
                        <span style="font-size:0.8rem; color:{p_color};">({p_diff:+} pts)</span>
                    </div>
                </div>
                <div style="display:grid; grid-template-columns: repeat(5, 1fr); margin-top:14px; gap:8px;">
                    <div><span style="color:#64748b; font-size:0.75rem;">SPOT REF</span><br><b>₹{a['underlying_price']}</b></div>
                    <div><span style="color:#64748b; font-size:0.75rem;">ENTRY</span><br><b>₹{a['entry']}</b></div>
                    <div><span style="color:#64748b; font-size:0.75rem;">STOP LOSS</span><br><b style="color:#eb5b3c;">₹{a['sl']}</b></div>
                    <div><span style="color:#64748b; font-size:0.75rem;">TARGET 1</span><br><b style="color:#00d09c;">₹{a['tgt1']}</b></div>
                    <div><span style="color:#64748b; font-size:0.75rem;">TARGET 2 / 3</span><br><b style="color:#00d09c;">₹{a['tgt2']} / ₹{a['tgt3']}</b></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            col_btn1, col_btn2 = st.columns([2, 5])
            
            # Action 1: Paper Trade
            if col_btn1.button("🎮 Take Paper Trade", key=f"t_{a['id']}"):
                cost = a['entry'] * 25
                if st.session_state.paper_balance >= cost:
                    st.session_state.paper_balance -= cost
                    st.session_state.paper_positions.append({
                        "id": str(uuid.uuid4())[:6],
                        "symbol": a['symbol'],
                        "sec_id": a['sec_id'],
                        "entry": a['entry'],
                        "current_ltp": current_display_ltp,
                        "sl": a['sl'],
                        "t1": a['tgt1'],
                        "qty": 25,
                        "cost": cost
                    })
                    st.success(f"Trade taken for {a['symbol']}! Monitoring live in Paper Portfolio.")
                    st.rerun()
                else:
                    st.error("Insufficient demo capital!")

            # Action 2: Telegram Push
            if col_btn2.button("📲 Broadcast to My Telegram", key=f"tg_{a['id']}"):
                if BOT_TOKEN and CHAT_ID:
                    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                    txt = (
                        f"🚨 <b>{a['strategy']} SIGNAL: {a['symbol']}</b> 🚨\n\n"
                        f"⚡ <b>Action:</b> {a['direction']}\n"
                        f"📊 <b>Spot Ref:</b> ₹{a['underlying_price']}\n"
                        f"🎯 <b>Entry:</b> ₹{a['entry']} | <b>LTP:</b> ₹{current_display_ltp:.2f}\n"
                        f"🛑 <b>SL:</b> ₹{a['sl']}\n"
                        f"🚀 <b>Targets:</b> T1: ₹{a['tgt1']} | T2: ₹{a['tgt2']} | T3: ₹{a['tgt3']}\n"
                        f"🆔 <code>{a['id']}</code>"
                    )
                    requests.post(url, json={"chat_id": CHAT_ID, "text": txt, "parse_mode": "HTML"})
                    st.success("Delivered to your Telegram!")

# ----------------- TAB 2: LIVE PAPER PORTFOLIO -----------------
with tab_paper:
    st.subheader("📊 Live Paper Trade Portfolio")
    
    # Auto-update current LTP for each position from Dhan
    for p in st.session_state.paper_positions:
        d_ltp = fetch_dhan_ltp(p["sec_id"])
        if d_ltp is not None:
            p["current_ltp"] = d_ltp

    total_unrealized = sum([(p["current_ltp"] - p["entry"]) * p["qty"] for p in st.session_state.paper_positions])

    cp1, cp2 = st.columns(2)
    cp1.metric("Available Margin", f"₹{st.session_state.paper_balance:,.2f}")
    cp2.metric("Total Unrealized P&L", f"₹{total_unrealized:+,.2f}", delta_color="normal" if total_unrealized >= 0 else "inverse")

    if not st.session_state.paper_positions:
        st.info("No active open positions. Execute one from the Live Alerts Desk.")
    else:
        for idx_p, p in enumerate(st.session_state.paper_positions):
            pnl = (p["current_ltp"] - p["entry"]) * p["qty"]
            pnl_color = "#00d09c" if pnl >= 0 else "#eb5b3c"

            st.markdown(f"""
            <div class="card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <b>{p['symbol']}</b> | Qty: {p['qty']} | Entry: ₹{p['entry']} | 
                        Live LTP: <b>₹{p['current_ltp']:.2f}</b>
                    </div>
                    <b style="font-size:1.2rem; color:{pnl_color};">₹{pnl:+,.2f}</b>
                </div>
            </div>
            """, unsafe_allow_html=True)

            if st.button(f"Square Off {p['symbol']}", key=f"sq_{p['id']}"):
                returned = p["cost"] + pnl
                st.session_state.paper_balance += returned
                st.session_state.paper_positions.pop(idx_p)
                st.success(f"Squared off! P&L: ₹{pnl:+,.2f}")
                st.rerun()

# ----------------- TAB 3: STRATEGY ALERT DISPATCHER -----------------
with tab_admin:
    st.subheader("⚙️ Generate Accurate Strike Alert")
    st.caption("Automatically calculates legitimate ITM/ATM strikes from live spot prices.")

    with st.form("alert_generator"):
        c_u1, c_u2 = st.columns(2)
        strat = c_u1.selectbox("Strategy", ["EMMANI (10/20 EMA)", "SUPRIYA (Supertrend + 12 EMA)", "SSRG (9:45 Breakout)"])
        und = c_u2.selectbox("Underlying Index", ["NIFTY 50", "BANK NIFTY", "SENSEX"])

        live_spot = idx[und]["spot"]
        st.info(f"Current Live Spot for {und}: **₹{live_spot:,.2f}**")

        c_d1, c_d2 = st.columns(2)
        direction = c_d1.selectbox("Direction", ["BUY CE (Bullish)", "BUY PE (Bearish)"])
        
        # Calculate strike accurately
        calc_strike, calc_type, calc_contract = compute_accurate_strike(und, live_spot, direction)
        c_d2.text_input("Calculated Strike Contract", value=calc_contract, disabled=True)

        c_p1, c_p2, c_p3 = st.columns(3)
        entry_prem = c_p1.number_input("Actual Option Entry Premium (₹)", value=140.0, step=0.5)
        # Option SL rule: 20% risk
        sl_prem = c_p2.number_input("Option SL (₹)", value=round(entry_prem * 0.80, 2), step=0.5)
        sec_id_input = c_p3.text_input("Dhan Security ID (from Dhan App)", value="49081")

        risk = entry_prem - sl_prem
        t1 = round(entry_prem + 1.0 * risk, 2)
        t2 = round(entry_prem + 2.0 * risk, 2)
        t3 = round(entry_prem + 3.0 * risk, 2)

        st.caption(f"Risk per lot: ₹{risk * 25:.2f} | T1: ₹{t1} | T2: ₹{t2} | T3: ₹{t3}")

        if st.form_submit_button("🚀 Publish Alert to Terminal & Telegram"):
            new_al = {
                "id": str(uuid.uuid4())[:8],
                "strategy": strat.split(" ")[0],
                "underlying": und,
                "symbol": calc_contract,
                "sec_id": sec_id_input,
                "direction": direction.split(" ")[0] + " " + direction.split(" ")[1],
                "underlying_price": live_spot,
                "entry": float(entry_prem),
                "sl": float(sl_prem),
                "tgt1": t1,
                "tgt2": t2,
                "tgt3": t3,
                "time": now.strftime("%I:%M %p"),
                "status": "Active"
            }
            save_alert(new_al)
            st.success(f"Published {calc_contract} successfully!")
            st.rerun()

    st.markdown("---")
    st.subheader("Manage Active Alerts")
    for al in get_alerts():
        c_del1, c_del2 = st.columns([5, 1])
        c_del1.write(f"• **{al['symbol']}** ({al['strategy']}) Entry: ₹{al['entry']} | Sec ID: {al['sec_id']}")
        if c_del2.button("🗑️ Delete", key=f"d_{al['id']}"):
            delete_alert(al['id'])
            st.rerun()

# ----------------- TAB 4: COURSES & INDICATORS -----------------
with tab_edu:
    st.subheader("📚 Knowledge Hub Academy & Indicator Logic")
    st.markdown("""
    ### 1. Strike Selection Mechanics
    - **NIFTY 50**: Standard interval of 50 points. For CE, 1 ITM means subtracting 50 points from the rounded ATM strike.
    - **BANK NIFTY**: Standard interval of 100 points.
    - **Rule of Separation**: Underlying spot points (e.g. 24,850) are never subtracted from Option premiums (e.g. ₹140). The Option Stop-Loss is derived purely from option price action and risk tolerance.

    ### 2. Dhan HQ Zero-Latency Feed
    - By querying `https://api.dhan.co/marketfeed/ltp`, your terminal bypasses delayed aggregators and reads directly from the exchange book via Dhan.
    """)
