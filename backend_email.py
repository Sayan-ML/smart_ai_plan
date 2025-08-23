import os
import pickle
import base64
import json
import markdown 
from datetime import datetime, timedelta
from email.mime.text import MIMEText

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send'
]

def init_llm(api_key: str):
    if not api_key:
        raise ValueError("Google API Key is required")
    return ChatGoogleGenerativeAI(model="gemini-2.0-flash", api_key=api_key)

def get_gmail_service(user_email: str, supabase, client_secret_json: str):
    creds = None

    resp = supabase.table("users").select("google_gmail_token").eq("email", user_email).execute()
    if resp.data and resp.data[0].get("google_gmail_token"):
        try:
            token_data = resp.data[0]["google_gmail_token"]
            creds = pickle.loads(base64.b64decode(token_data.encode()))
        except Exception as e:
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())

            token_data = base64.b64encode(pickle.dumps(creds)).decode()
            supabase.table("users").update({"google_gmail_token": token_data}).eq("email", user_email).execute()
        except Exception as e:
            creds = None

    if not creds or not creds.valid:
        client_config = json.loads(client_secret_json)
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        creds = flow.run_local_server(port=0)

        token_data = base64.b64encode(pickle.dumps(creds)).decode()
        supabase.table("users").update({"google_gmail_token": token_data}).eq("email", user_email).execute()

    return build('gmail', 'v1', credentials=creds)

def get_last_48h_emails(user_email, supabase, client_secret_json):
    service = get_gmail_service(user_email, supabase, client_secret_json)

    now = datetime.utcnow()
    two_days_ago = now - timedelta(days=2)
    query = f"after:{int(two_days_ago.timestamp())}"

    emails = []
    page_token = None

    try:
        while True:
            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=100,
                pageToken=page_token
            ).execute()

            messages = results.get('messages', [])
            if not messages:
                break

            for msg in messages:
                message = service.users().messages().get(
                    userId='me', id=msg['id'], format='full'
                ).execute()

                payload = message['payload']
                headers = payload.get('headers', [])
                subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
                sender = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")

                body = ""
                if 'parts' in payload:
                    for part in payload['parts']:
                        if part['mimeType'] == 'text/plain' and 'data' in part['body']:
                            body = base64.urlsafe_b64decode(part['body']['data']).decode()
                            break
                elif 'body' in payload and 'data' in payload['body']:
                    body = base64.urlsafe_b64decode(payload['body']['data']).decode()

                emails.append({
                    "id": msg['id'],
                    "from": sender,
                    "subject": subject,
                    "body": body
                })

            page_token = results.get('nextPageToken')
            if not page_token:
                break

    except HttpError as e:
        return []

    return emails

def summarize_emails(emails, gemini_key):
    if not emails:
        return "No emails in the last 48 hours."

    combined_text = ""
    for e in emails:
        combined_text += f"From: {e['from']}\nSubject: {e['subject']}\n{e['body']}\n\n"

    combined_text = combined_text.replace("{", "{{").replace("}", "}}")

    human_template = HumanMessagePromptTemplate.from_template(
        "Summarize the following emails in concise bullet points:\n{email_text}"
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an email assistant."),
        human_template
    ])

    chat = init_llm(gemini_key)
    summary = chat(prompt.format_prompt(email_text=combined_text).to_messages())

    try:
        summary_html = markdown.markdown(summary.content)
        summary_html = summary_html.replace("</li>", "</li><br>")
    except Exception:
        summary_html = summary.content

    return summary_html

def generate_replies(email_body, gemini_key):
    chat = init_llm(gemini_key)
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an email assistant."),
        ("user", f"""
            Email:
            {email_body}

            Generate exactly 3 separate, concise, professional reply options.
            Number them clearly as 1., 2., and 3. Do not include anything else.
            """)
    ])
    reply = chat(prompt.format_prompt().to_messages())
    text = reply.content

    options = []
    for i in range(1, 4):
        start = text.find(f"{i}.")
        end = text.find(f"{i+1}.") if i < 3 else len(text)
        option = text[start:end].strip()
        if option.startswith(f"{i}."):
            option = option[len(f"{i}."):].strip()
        options.append(option)
    while len(options) < 3:
        options.append("")

    return options

def send_email(user_email, supabase, client_secret_json, to, subject, body_text):
    service = get_gmail_service(user_email, supabase, client_secret_json)

    message = MIMEText(body_text)
    message['to'] = to
    message['subject'] = subject
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    body = {'raw': raw_message}

    try:
        sent_message = service.users().messages().send(userId='me', body=body).execute()
        return True, f"Email sent! Message ID: {sent_message['id']}"
    except HttpError as error:
        return False, f"An error occurred: {error}"