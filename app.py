import os
import sys
import json
import hashlib
import smtplib
import tempfile
import traceback
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import plotly.graph_objs as go
import google.generativeai as genai
from dotenv import load_dotenv
from supabase import create_client, Client
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify
)

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image
)
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

from backend_movies import get_genres, discover_movies
from backend_news import get_today_news
from backend_stocks import get_stock_data, llm_stock_advice
from backend_crypto import get_crypto_data, llm_crypto_advice
from backend_email import send_email, generate_replies
from backend_Calendar import add_task_to_calendar, get_calendar_service
from backend_travel_planner import get_user_location_google, get_nearby_places, haversine
from backend_weather import get_weather, get_user_location_city, llm_weather_advice

# ---------------- Supabase Config ----------------
load_dotenv()
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)
app.secret_key = "supersecretkey"  

# ---------------- Email Function ----------------
def send_email(receiver_email, pdf_file):
    sender_email = os.getenv("EMAIL_USER")
    sender_pass = os.getenv("EMAIL_PASS")

    if not sender_email or not sender_pass:
        return False

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = "📊 Expense Report"

    body = "Attached is your requested Expense Report."
    msg.attach(MIMEText(body, 'plain'))

    with open(pdf_file, "rb") as f:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename=Expense_Report.pdf')
        msg.attach(part)

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(sender_email, sender_pass)
    server.send_message(msg)
    server.quit()

# ---------------- Function 1: Min & Max Date ----------------
def get_min_max_date(user_id: str):
    response = supabase.table("Expense_of_Users").select("Date").eq("User_Id", user_id).execute()
    if not response.data:
        return None, None
    dates = [datetime.strptime(row["Date"], "%Y-%m-%d").date() for row in response.data]
    return min(dates), max(dates)

# ---------------- Function 2: Generate Expense Report ----------------
def generate_expense_report(user_id: str, from_date: str, end_date: str):
    query = supabase.table("Expense_of_Users").select("Date, Category, Expenses").eq("User_Id", user_id)
    if from_date == end_date:
        query = query.eq("Date", str(from_date))
    else:
        query = query.gte("Date", str(from_date)).lte("Date", str(end_date))

    response = query.execute()

    if not response.data:
        return

    df = pd.DataFrame(response.data)
    df["Date"] = pd.to_datetime(df["Date"]).dt.date

    category_totals = df.groupby("Category")["Expenses"].sum().to_dict()
    total = sum(category_totals.values())
    percentages = {k: (v / total) * 100 for k, v in category_totals.items()}

    fig, ax = plt.subplots(figsize=(7, 6))
    wedges, _ = ax.pie(
        category_totals.values(),
        startangle=140,
        shadow=True,
        wedgeprops={"edgecolor": "black"}
    )

    for i, wedge in enumerate(wedges):
        angle = (wedge.theta2 + wedge.theta1) / 2
        x = np.cos(np.deg2rad(angle))
        y = np.sin(np.deg2rad(angle))
        ax.annotate(
            f"{list(percentages.values())[i]:.1f}%",
            xy=(x, y), xytext=(1.2 * x, 1.2 * y),
            ha="center", va="center",
            arrowprops=dict(arrowstyle="-", color="black")
        )

    ax.legend(
        wedges,
        [f"{cat}: {perc:.1f}%" for cat, perc in percentages.items()],
        title="Categories",
        loc="center left",
        bbox_to_anchor=(1, 0.5)
    )
    plt.suptitle("Category-wise Expense Distribution", fontsize=14, fontweight="bold", x=0.5)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as chart_file:
        chart_path = chart_file.name
    plt.savefig(chart_path, bbox_inches="tight")
    plt.close()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as pdf_temp:
        pdf_path = pdf_temp.name

    doc = SimpleDocTemplate(pdf_path)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Expense Report", styles["Title"]))
    elements.append(Spacer(1, 20))

    table_data = [["Date", "Category", "Expenses"]] + df.values.tolist()
    table = Table(table_data, hAlign="CENTER")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("Category-wise Expenses", styles["Heading2"]))
    for cat, val in category_totals.items():
        elements.append(Paragraph(f"• {cat} : {val:.2f}", styles["Normal"]))
    elements.append(Spacer(1, 20))

    elements.append(Image(chart_path, width=350, height=250, hAlign="CENTER"))

    doc.build(elements)
    send_email(user_id, pdf_path)

    os.remove(pdf_path)
    os.remove(chart_path)

# ---------------- Helper Functions ----------------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def check_login(email, password):
    resp = supabase.table("users").select("*").eq("email", email).execute()
    if resp.data:
        user = resp.data[0]
        if user["password"] == hash_password(password):
            return True
    return False

def signup_user(email, password):
    resp = supabase.table("users").select("*").eq("email", email).execute()
    if resp.data:
        return False
    supabase.table("users").insert({
        "email": email,
        "password": hash_password(password),
    }).execute()
    return True

def reset_password(email, new_password):
    resp = supabase.table("users").select("*").eq("email", email).execute()
    if not resp.data:
        return False
    supabase.table("users").update({"password": hash_password(new_password)}).eq("email", email).execute()
    return True

# ---------------- Routes ----------------
@app.route("/")
def index():
    if "email" in session:
        return render_template("home.html", email=session["email"])
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"].strip()
        if check_login(email, password):
            session["email"] = email
            flash("Login successful!", "success")
            return redirect(url_for("index"))
        else:
            flash("Invalid email or password", "danger")
    return render_template("login.html", title="Smart AI Daily Planner - Login")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"].strip()
        if signup_user(email, password):
            flash("Sign up successful! Please login.", "success")
            return redirect(url_for("login"))
        else:
            flash("Email already exists. Try logging in.", "danger")
    return render_template("signup.html", title="Smart AI Daily Planner - Sign Up")

@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        email = request.form["email"].strip()
        new_password = request.form["new_password"].strip()
        if reset_password(email, new_password):
            flash("Password updated! Please login.", "success")
            return redirect(url_for("login"))
        else:
            flash("Email not found.", "danger")
    return render_template("forgot.html", title="Smart AI Daily Planner - Forgot Password")

@app.route("/logout")
def logout():
    session.pop("email", None)
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))

@app.route("/get_user_field/<field>", methods=["GET"])
def get_user_field(field):
    email = session.get("email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    allowed_fields = [
        "google_gemini_api_key",
        "client_secret_json",
        "weather_api",
        "tmdb_api",
        "news_api",
        "google_map_api",
        "zodiac_sign"
    ]
    if field not in allowed_fields:
        return jsonify({"error": "Invalid field"}), 400
    
    user = supabase.table("users").select(field).eq("email", email).execute().data
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({field: user[0].get(field)})

@app.route("/update_user_field/<field>", methods=["POST"])
def update_user_field(field):
    email = session.get("email")
    if not email:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.json
    new_value = data.get("value")
    
    allowed_fields = [
        "google_gemini_api_key",
        "client_secret_json",
        "weather_api",
        "tmdb_api",
        "news_api",
        "google_map_api",
        "zodiac_sign"
    ]
    if field not in allowed_fields:
        return jsonify({"error": "Invalid field"}), 400
    
    updates = {field: new_value}

    if field == "client_secret_json":
        updates["google_calendar_token"] = None
        updates["google_gmail_token"] = None

    supabase.table("users").update(updates).eq("email", email).execute()
    
    return jsonify({"success": True, "field": field, "value": new_value})

def check_expense_user(email):
    resp = supabase.table("Expense_of_Users").select("*").eq("User_Id", email).execute()
    return len(resp.data) > 0

@app.route("/check_expense_user")
def check_expense_user_route():
    if "email" not in session:
        return jsonify({"exists": False, "error": "Not logged in"}), 401
    email = session["email"]
    exists = check_expense_user(email)
    return jsonify({"exists": exists})

@app.route("/add_expense", methods=["POST"])
def add_expense():
    if "email" not in session:
        return jsonify({"success": False, "error": "Not logged in"}), 401

    data = request.get_json()
    category = data.get("category")
    try:
        amount = float(data.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid amount"}), 400

    email = session["email"]
    today = datetime.now().strftime("%Y-%m-%d")  # Example: 2025-08-22

    try:
        supabase.table("Expense_of_Users").insert({
            "User_Id": email,
            "Category": category,
            "Expenses": amount,
            "Date": today
        }).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    
@app.route("/get_expense_date_range", methods=["GET"])
def get_expense_date_range():
    if "email" not in session:
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user_id = session["email"]
    min_date, max_date = get_min_max_date(user_id)
    if not min_date or not max_date:
        return jsonify({"success": False, "exists": False})

    return jsonify({
        "success": True,
        "exists": True,
        "min_date": str(min_date),
        "max_date": str(max_date)
    })

@app.route("/generate_expense_report", methods=["POST"])
def generate_expense_report_route():
    if "email" not in session:
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user_id = session["email"]
    data = request.get_json()
    from_date = data.get("from_date")
    end_date = data.get("end_date")

    try:
        generate_expense_report(user_id, from_date, end_date)
        return jsonify({"success": True, "message": "Report generated and emailed!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    
@app.route("/weather", methods=["GET", "POST"])
def weather():

    if "email" not in session:
        return jsonify({"error": "Not logged in"}), 403

    try:
        user_resp = supabase.table("users").select(
            "weather_api, google_gemini_api_key"
        ).eq("email", session["email"]).execute()

        if not user_resp.data:
            return jsonify({"error": "User not found"}), 404

        user = user_resp.data[0]
        weather_api = user.get("weather_api")
        gemini_api = user.get("google_gemini_api_key")

        if request.method == "POST":
            new_weather = request.json.get("weather_api")
            new_gemini = request.json.get("google_gemini_api_key")
            update_data = {}
            if new_weather:
                update_data["weather_api"] = new_weather.strip()
            if new_gemini:
                update_data["google_gemini_api_key"] = new_gemini.strip()

            if update_data:
                supabase.table("users").update(update_data).eq(
                    "email", session["email"]
                ).execute()
                return jsonify({"success": True, "message": "API keys saved!"})

        missing = []
        if not weather_api:
            missing.append("weather_api")
        if not gemini_api:
            missing.append("google_gemini_api_key")

        if missing:
            return jsonify({"need_api": True, "missing": missing})

        city = get_user_location_city() or "London"
        weather_data = get_weather(city, weather_api)
        advice = llm_weather_advice(city, weather_data, gemini_api)
        return jsonify({"weather": weather_data, "advice": advice})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/stocks", methods=["GET", "POST"])
def stocks():
    if "email" not in session:
        return redirect(url_for("login"))
    
    resp = supabase.table("users").select("google_gemini_api_key").eq("email", session["email"]).execute()
    if not resp.data:
        flash("User not found.", "danger")
        return redirect(url_for("login"))

    user = resp.data[0]
    gemini_key = user.get("google_gemini_api_key")

    if not gemini_key:
        if request.method == "POST":
            new_key = request.form.get("google_gemini_api_key").strip()
            if new_key:
                supabase.table("users").update({"google_gemini_api_key": new_key}).eq("email", session["email"]).execute()
                flash("Gemini API key saved!", "success")
                return redirect(url_for("stocks"))
        return render_template("key_setup.html", service="Stocks", field_name="google_gemini_api_key")

    return render_template("stocks.html", email=session["email"])

@app.route("/api/stocks", methods=["POST"])
def api_stocks():
    if "email" not in session:
        return jsonify({"error": "Not logged in"}), 403

    resp = supabase.table("users").select("google_gemini_api_key").eq("email", session["email"]).execute()
    if not resp.data:
        return jsonify({"error": "User not found"}), 404
    user = resp.data[0]
    gemini_key = user.get("google_gemini_api_key")
    if not gemini_key:
        return jsonify({"error": "Missing Gemini API key"}), 400

    data = request.get_json()
    symbol = data.get("symbol")
    if not symbol:
        return jsonify({"error": "Missing stock symbol"}), 400

    stock = get_stock_data(symbol)
    if "error" in stock:
        return jsonify(stock), 400

    hist = stock["history"]
    last_price = hist["Close"].iloc[-1]
    pct_change = ((last_price - hist["Close"].iloc[0]) / hist["Close"].iloc[0]) * 100
    highest = hist["Close"].max()
    lowest = hist["Close"].min()

    ai_text = llm_stock_advice(symbol, hist, gemini_key)

    if "Strong Buy" in ai_text:
        decision = "Strong Buy"
    elif "Buy" in ai_text:
        decision = "Buy"
    elif "Hold" in ai_text:
        decision = "Hold"
    elif "Sell" in ai_text:
        decision = "Sell"
    elif "Strong Sell" in ai_text:
        decision = "Strong Sell"
    else:
        decision = "No Decision"

    return jsonify({
        "symbol": stock["symbol"],
        "last_price": round(last_price, 2),
        "pct_change": round(pct_change, 2),
        "highest": round(highest, 2),
        "lowest": round(lowest, 2),
        "history": hist.to_dict(orient="records"),
        "advice": ai_text,      
        "decision": decision   
    })

# ---------------------------
# 🌐 Crypto Page
# ---------------------------
@app.route("/crypto", methods=["GET", "POST"])
def crypto():
    if "email" not in session:
        return redirect(url_for("login"))

    resp = supabase.table("users").select("google_gemini_api_key").eq("email", session["email"]).execute()
    if not resp.data:
        flash("User not found.", "danger")
        return redirect(url_for("login"))

    user = resp.data[0]
    gemini_key = user.get("google_gemini_api_key")

    if not gemini_key:
        if request.method == "POST":
            new_key = request.form.get("google_gemini_api_key").strip()
            if new_key:
                supabase.table("users").update({"google_gemini_api_key": new_key}).eq("email", session["email"]).execute()
                flash("Gemini API key saved!", "success")
                return redirect(url_for("crypto"))
        return render_template("key_setup.html", service="Crypto", field_name="google_gemini_api_key")

    return render_template("crypto.html", email=session["email"])

# ---------------------------
# 🌐 API: Crypto Data + AI Advice
# ---------------------------

CRYPTO_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "SOL": "solana",
    "DOGE": "dogecoin"
}

CRYPTO_NAMES = {v: k for k, v in CRYPTO_MAP.items()} 

@app.route("/api/crypto", methods=["POST"])
def api_crypto():
    if "email" not in session:
        return jsonify({"error": "Not logged in"}), 403

    resp = supabase.table("users").select("google_gemini_api_key").eq("email", session["email"]).execute()
    if not resp.data:
        return jsonify({"error": "User not found"}), 404
    user = resp.data[0]
    gemini_key = user.get("google_gemini_api_key")
    if not gemini_key:
        return jsonify({"error": "Missing Gemini API key"}), 400

    data = request.get_json()
    symbol = data.get("symbol")
    if not symbol:
        return jsonify({"error": "Missing crypto symbol"}), 400

    coin_id = CRYPTO_MAP.get(symbol, symbol.lower())

    crypto = get_crypto_data(coin_id)
    if "error" in crypto:
        return jsonify(crypto), 400

    df = crypto["history"]
    last_price = df["price"].iloc[-1]
    pct_change = ((df["price"].iloc[-1] - df["price"].iloc[0]) / df["price"].iloc[0]) * 100
    highest = df["price"].max()
    lowest = df["price"].min()

    ai_text = llm_crypto_advice(coin_id, df, gemini_key)

    if "Strong Buy" in ai_text:
        decision = "Strong Buy"
    elif "Buy" in ai_text:
        decision = "Buy"
    elif "Hold" in ai_text:
        decision = "Hold"
    elif "Sell" in ai_text:
        decision = "Sell"
    elif "Strong Sell" in ai_text:
        decision = "Strong Sell"
    else:
        decision = "No Decision"

    history = [
        {"Date": row.Date.strftime("%Y-%m-%d %H:%M"), "price": float(row.price)}
        for _, row in df.iterrows()
    ]

    return jsonify({
        "symbol": coin_id,
        "name": CRYPTO_NAMES.get(coin_id, coin_id.upper()),
        "last_price": round(last_price, 2),
        "pct_change": round(pct_change, 2),
        "highest": round(highest, 2),
        "lowest": round(lowest, 2),
        "history": history,       
        "advice": ai_text,
        "decision": decision
    })

@app.route("/horoscope", methods=["GET", "POST"])
def horoscope():
    email = session.get("email")
    if not email:
        return jsonify({"error": "Not logged in"}), 403

    user = supabase.table("users").select("google_gemini_api_key, zodiac_sign").eq("email", email).execute().data[0]

    gemini_key = user.get("google_gemini_api_key")
    zodiac_sign = user.get("zodiac_sign")

    if request.method == "POST":
        data = request.json
        updates = {}
        if "google_gemini_api_key" in data:
            updates["google_gemini_api_key"] = data["google_gemini_api_key"]
        if "zodiac_sign" in data:
            updates["zodiac_sign"] = data["zodiac_sign"]
        if updates:
            supabase.table("users").update(updates).eq("email", email).execute()
            return jsonify({"message": "Saved!"})
    
    missing = []
    if not gemini_key:
        missing.append("google_gemini_api_key")
    if not zodiac_sign:
        missing.append("zodiac_sign")
    if missing:
        return jsonify({"need_api": True, "missing": missing})

    horoscope = get_ai_horoscope(zodiac_sign, gemini_key)
    return jsonify({
        "zodiac": zodiac_sign.capitalize(),
        "horoscope": horoscope
    })

def get_ai_horoscope(sign: str, gemini_key: str):
    
    genai.configure(api_key=gemini_key)

    GEMINI_MODEL = genai.GenerativeModel("gemini-1.5-flash")
    prompt = f"Give me today's horoscope for {sign} in simple, positive, practical language (3–4 sentences)."
    try:
        response = GEMINI_MODEL.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"⚠️ Error: {e}"

@app.route("/email", methods=["GET", "POST"])
def email_ai():
    if "email" not in session:
        return redirect(url_for("login"))

    resp = supabase.table("users").select("*").eq("email", session["email"]).execute()
    if not resp.data:
        flash("User not found.", "danger")
        return redirect(url_for("login"))

    user = resp.data[0]
    gemini_key = user.get("google_gemini_api_key")
    client_secret = user.get("client_secret_json")

    if not gemini_key or not client_secret:
        if request.method == "POST":
            new_gemini = request.form.get("gemini_key", "").strip()
            new_client = request.form.get("client_secret_json", "").strip()

            update_data = {}
            if new_gemini:
                update_data["google_gemini_api_key"] = new_gemini
            if new_client:
                update_data["client_secret_json"] = new_client

            if update_data:
                supabase.table("users").update(update_data).eq("email", session["email"]).execute()
                flash("Keys updated successfully! Please continue.", "success")
                return redirect(url_for("email_ai"))

        return render_template("email_setup.html",
                               gemini_key=gemini_key,
                               client_secret=client_secret)

    return render_template("email_assistant.html", email=session["email"])

@app.route("/api/summarize_emails", methods=["GET"])
def api_summarize_emails():
    if "email" not in session:
        return jsonify({"error": "Not logged in"}), 401

    resp = supabase.table("users").select("*").eq("email", session["email"]).execute()
    if not resp.data:
        return jsonify({"error": "User not found"}), 404

    user = resp.data[0]
    gemini_key = user.get("google_gemini_api_key")
    client_secret_json = user.get("client_secret_json")

    if not gemini_key or not client_secret_json:
        return jsonify({"error": "Missing API credentials"}), 400

    from backend_email import get_last_48h_emails, summarize_emails
    emails = get_last_48h_emails(session["email"], supabase, client_secret_json)

    summary = summarize_emails(emails, gemini_key)
    return jsonify({"summary": summary, "emails": emails})

@app.route("/api/generate_replies", methods=["POST"])
def api_generate_replies():
    if "email" not in session:
        return jsonify({"error": "Not logged in"}), 401

    resp = supabase.table("users").select("*").eq("email", session["email"]).execute()
    if not resp.data:
        return jsonify({"error": "User not found"}), 404

    user = resp.data[0]
    gemini_key = user.get("google_gemini_api_key")

    if not gemini_key:
        return jsonify({"error": "Missing Gemini API key"}), 400

    data = request.get_json()
    email_body = data.get("body", "")
    if not email_body:
        return jsonify({"error": "No email body provided"}), 400
    
    replies = generate_replies(email_body, gemini_key)
    return jsonify({"replies": replies})

@app.route("/api/send_email", methods=["POST"])
def api_send_email():
    if "email" not in session:
        return jsonify({"error": "Not logged in"}), 401

    resp = supabase.table("users").select("*").eq("email", session["email"]).execute()
    if not resp.data:
        return jsonify({"error": "User not found"}), 404

    user = resp.data[0]
    client_secret_json = user.get("client_secret_json")

    if not client_secret_json:
        return jsonify({"error": "Missing Gmail credentials"}), 400

    data = request.get_json()
    to = data.get("to")
    subject = data.get("subject")
    body_text = data.get("body")

    if not to or not subject or not body_text:
        return jsonify({"error": "Missing fields"}), 400

    success, msg = send_email(
        user_email=session["email"],
        supabase=supabase,
        client_secret_json=client_secret_json,
        to=to,
        subject=subject,
        body_text=body_text
    )

    return jsonify({"success": success, "message": msg})

@app.route("/reminders", methods=["GET", "POST"])
def reminders():
    if "email" not in session:
        return redirect(url_for("login"))

    email = session["email"]
    resp = supabase.table("users").select("client_secret_json").eq("email", email).execute()
    has_secret = resp.data and resp.data[0]["client_secret_json"]

    if not has_secret:
        if request.method == "POST":
            client_secret_json = request.form["client_secret_json"]

            try:
                parsed = json.loads(client_secret_json)
                client_secret_json = json.dumps(parsed)  
            except Exception:
                flash("⚠️ Invalid JSON format. Please paste the full Google Client Secret JSON.", "error")
                return redirect(url_for("reminders"))

            supabase.table("users").update({"client_secret_json": client_secret_json}).eq("email", email).execute()
            flash("✅ Google Client Secret saved! Now connect your Google account.", "success")
            return redirect(url_for("reminders"))

        return render_template("reminders_setup.html")

    if request.method == "POST":
        title = request.form["title"]
        desc = request.form["description"]
        date = request.form["date"]
        start_time = request.form["start_time"]
        end_time = request.form["end_time"]

        add_task_to_calendar(email, supabase, title, desc, date, start_time, end_time)
        flash("✅ Task added successfully to Google Calendar!", "success")  

        return redirect(url_for("reminders"))   
    return render_template("reminders.html")

@app.route("/news", methods=["GET"])
def news():
    if "email" not in session:
        return redirect(url_for("login"))

    resp = supabase.table("users").select("news_api").eq("email", session["email"]).execute()
    if not resp.data:
        return redirect(url_for("login"))

    user = resp.data[0]

    if not user or not user.get("news_api"):
        return render_template("news_api_setup.html")

    try:
        news_articles = get_today_news(user["news_api"], limit=10)
        return render_template("news.html", news=news_articles)
    except Exception as e:
        return render_template("news.html", news=None, error=str(e))

@app.route("/setup_news_api", methods=["POST"])
def setup_news_api():
    if "email" not in session:
        return redirect(url_for("login"))

    news_api = request.form.get("news_api")
    if news_api:
        supabase.table("users").update({"news_api": news_api}).eq("email", session["email"]).execute()
    return redirect(url_for("news"))

@app.route("/expenses")
def expenses():
    return "<h2>Expense tracker coming soon 💰</h2>"

@app.route("/movies", methods=["GET", "POST"])
def movies():
    if "email" not in session:
        return redirect(url_for("login"))

    resp = supabase.table("users").select("tmdb_api").eq("email", session["email"]).execute()
    if not resp.data:
        flash("User not found!", "danger")
        return redirect(url_for("index"))

    user = resp.data[0]
    tmdb_key = user.get("tmdb_api")

    if not tmdb_key:
        if request.method == "POST":
            new_key = request.form.get("tmdb_api").strip()
            supabase.table("users").update({"tmdb_api": new_key}).eq("email", session["email"]).execute()
            flash("TMDB API key saved!", "success")
            return redirect(url_for("movies"))
        return render_template("TMDB_API_setup.html")

    return render_template("movies.html", email=session["email"])

@app.route("/api/movies/genres")
def api_movies_genres():
    if "email" not in session:
        return jsonify([])
    resp = supabase.table("users").select("tmdb_api").eq("email", session["email"]).execute()
    if not resp.data or not resp.data[0].get("tmdb_api"):
        return jsonify([])
    api_key = resp.data[0]["tmdb_api"]
    return jsonify(get_genres(api_key))

@app.route("/api/movies", methods=["POST"])
def api_movies():
    if "email" not in session:
        return jsonify([])
    resp = supabase.table("users").select("tmdb_api").eq("email", session["email"]).execute()
    if not resp.data or not resp.data[0].get("tmdb_api"):
        return jsonify([])
    api_key = resp.data[0]["tmdb_api"]

    data = request.get_json()
    genres = data.get("genre")
    year = data.get("year")
    lang = data.get("language")
    num_movies = int(data.get("num_movies", 5))

    movies = discover_movies(api_key, genres, year, lang, num_movies)
    return jsonify(movies)

@app.route("/travel", methods=["GET", "POST"])
def travel():
    if "email" not in session:
        flash("Please log in to access Travel Planner.", "danger")
        return redirect(url_for("login"))

    resp = supabase.table("users").select("*").eq("email", session["email"]).execute()
    if not resp.data:
        flash("User not found!", "danger")
        return redirect(url_for("index"))

    user = resp.data[0]
    api_key = user.get("google_map_api")

    if not api_key:
        if request.method == "POST":
            new_key = request.form.get("google_map_api").strip()
            supabase.table("users").update({"google_map_api": new_key}).eq("email", session["email"]).execute()
            flash("Google Maps API Key saved!", "success")
            return redirect(url_for("travel"))
        return render_template("travel_key_form.html")

    location = get_user_location_google(api_key)
    lat, lon = location.get("lat"), location.get("lng")

    if not lat or not lon:
        flash("❌ Could not detect location. Please check your API key.", "danger")
        return render_template("travel.html", places=[], lat=None, lon=None, api_key=api_key)

    selected_types = request.args.getlist("place_types")
    if not selected_types:
        selected_types = ["restaurant"]

    places = []
    for t in selected_types:
        results = get_nearby_places(api_key, lat, lon, place_type=t, radius=2000)
        for p in results:
            p["distance"] = haversine(lat, lon, p["lat"], p["lon"])
            p["type"] = t
        places.extend(results)

    return render_template(
        "travel.html",
        places=places,
        lat=lat,
        lon=lon,
        api_key=api_key,
        selected_types=selected_types
    )

if __name__ == "__main__":
    app.run(debug=True)
