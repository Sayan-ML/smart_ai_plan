import requests
import traceback

def get_weather(city: str, api_key: str):
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        main = data.get("main", {})
        wind = data.get("wind", {})
        sys_ = data.get("sys", {})
        weather_list = data.get("weather", [{}])

        return {
            "city": city,
            "temp": main.get("temp"),
            "feels_like": main.get("feels_like"),
            "humidity": main.get("humidity"),
            "pressure": main.get("pressure"),
            "condition": weather_list[0].get("description", "unknown"),
            "wind_speed": wind.get("speed"),
            "sunrise": sys_.get("sunrise"),
            "sunset": sys_.get("sunset"),
        }
    except Exception as e:
        return {"error": f"Weather API failed: {str(e)}"}

def get_user_location_city():

    try:
        res = requests.get("http://ip-api.com/json", timeout=10)
        if res.status_code == 200:
            data = res.json()
            return data.get("city")  
    except:
        return None
    return None

def llm_weather_advice(city: str, weather: dict, gemini_api_key: str, user_context: str = "") -> str:
    if not gemini_api_key:
        return "LLM suggestions unavailable: Missing GEMINI_API_KEY."

    try:
        import google.generativeai as genai
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
    except Exception as e:
        return f"LLM init error: {e}"

    prompt = f"""
        You are a helpful daily-planner assistant. Based on the following current weather, give concise, practical suggestions for someone in {city}.
        Avoid generic platitudes; focus on actionable tips. If rain or poor air/wind conditions are likely problems, mention precautions.
        Keep it to exactly 4 bullet points, no emojis.

        Weather JSON:
        {weather}

        User context (optional): {user_context if user_context else "N/A"}

        Output format:
        - One short title line (e.g., "Today’s Weather Tips for {city}")
        - Exactly 4 bullets, each ≤ 16 words
    """

    try:
        resp = model.generate_content(prompt, request_options={"timeout": 15})
        text = getattr(resp, "text", None)

        if not text:
            try:
                text = resp.candidates[0].content.parts[0].text
            except Exception:
                text = None

        return text or "Sorry, I couldn’t generate suggestions right now."
    except Exception as e:
        return f"LLM error: {e}"