import requests
import pandas as pd
import google.generativeai as genai

def get_crypto_data(symbol: str, days: int = 30):
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{symbol}/market_chart?vs_currency=usd&days={days}"
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            return {"error": f"API error ({response.status_code})"}

        data = response.json()
        if "prices" not in data:
            return {"error": "Crypto data not available"}

        df = pd.DataFrame(data["prices"], columns=["timestamp", "price"])
        df["Date"] = pd.to_datetime(df["timestamp"], unit="ms")

        return {"symbol": symbol, "history": df}

    except Exception as e:
        return {"error": str(e)}

def llm_crypto_advice(symbol: str, df: pd.DataFrame, gemini_api_key: str):
    if not gemini_api_key:
        return "LLM suggestions unavailable: Missing Gemini API Key."

    genai.configure(api_key=gemini_api_key)

    last_price = df["price"].iloc[-1]
    pct_change = ((df["price"].iloc[-1] - df["price"].iloc[0]) / df["price"].iloc[0]) * 100

    prompt = f"""
        You are a crypto investment assistant. Analyze the 30-day trend and give a decision.

        Crypto: {symbol}
        Last Price: {last_price:.2f}
        30-day % Change: {pct_change:.2f}%
        Recent Data (last 10 days): {df[['Date','price']].tail(10).to_dict(orient='records')}

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