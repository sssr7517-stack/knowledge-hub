# stock_alerts.py
# Add or update stock & stock option alerts here freely without touching app.py!

STOCK_WATCHLIST_ALERTS = [
    {
        "symbol": "RELIANCE 3000 CE",
        "underlying": "RELIANCE",
        "segment": "STOCK OPTION",
        "action": "BUY CE",
        "entry": 42.50,
        "sl": 32.00,
        "tgt1": 53.00,
        "tgt2": 64.00,
        "rationale": "Resistance breakout at ₹2,980 with high volume accumulation."
    },
    {
        "symbol": "TATAMOTORS",
        "underlying": "TATAMOTORS",
        "segment": "EQUITY CASH",
        "action": "BUY",
        "entry": 985.00,
        "sl": 965.00,
        "tgt1": 1010.00,
        "tgt2": 1035.00,
        "rationale": "10 EMA bounce on 15m timeframe + Auto sector tailwind."
    },
    {
        "symbol": "HDFCBANK 1660 PE",
        "underlying": "HDFCBANK",
        "segment": "STOCK OPTION",
        "action": "BUY PE",
        "entry": 24.00,
        "sl": 18.00,
        "tgt1": 30.00,
        "tgt2": 36.00,
        "rationale": "Breakdown below daily support level."
    }
]

def get_external_stock_alerts():
    return STOCK_WATCHLIST_ALERTS
