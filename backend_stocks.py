import yfinance as yf
import pandas as pd
import google.generativeai as genai

def get_stock_data(symbol: str, days: int = 30):
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period=f"{days}d")
        if hist.empty:
            return {"error": "No stock data found"}
        hist.reset_index(inplace=True)
        return {"symbol": symbol.upper(), "history": hist}
    except Exception as e:
        return {"error": str(e)}

def llm_stock_advice(symbol: str, hist: pd.DataFrame, gemini_api_key: str):
    if not gemini_api_key:
        return "LLM suggestions unavailable: Missing Gemini API Key."

    genai.configure(api_key=gemini_api_key)

    last_price = hist["Close"].iloc[-1]
    pct_change = ((hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0]) * 100

    prompt = f"""
        You are an expert financial assistant. Analyze the stock trend and give a decision.

        Stock: {symbol}
        Last Price: {last_price:.2f}
        30-day % Change: {pct_change:.2f}%
        Recent Data (last 10 days): {hist[['Date','Close']].tail(10).to_dict(orient='records')}

        Rules for decision:
        - Strong Buy = 30d % change > +15% or consistent sharp uptrend
        - Buy = 30d % change between +5% and +15% or steady uptrend
        - Hold = 30d % change between -5% and +5% or sideways movement
        - Sell = 30d % change between -15% and -5% or steady decline
        - Strong Sell = 30d % change < -15% or sharp continuous downtrend

        Your task:
        1. Always pick exactly ONE decision from: Strong Buy, Buy, Hold, Sell, Strong Sell.
        2. Always provide EXACTLY 3 concise reasons (≤15 words each).
        3. Follow the output format strictly:

        Decision: <Strong Buy / Buy / Hold / Sell / Strong Sell>
        Reason 1: <short reason>
        Reason 2: <short reason>
        Reason 3: <short reason>
        """

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = model.generate_content(prompt)
        return getattr(resp, "text", None) or "AI could not generate advice."
    except Exception as e:
        return f"LLM error: {e}"