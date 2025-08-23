import os
import datetime
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request  

SCOPES = ['https://www.googleapis.com/auth/calendar.events']

def get_calendar_service(user_email, supabase):

    resp = supabase.table("users").select("client_secret_json, google_calendar_token").eq("email", user_email).execute()
    if not resp.data:
        return None

    row = resp.data[0]
    client_secret_json = row.get("client_secret_json")
    token_data = row.get("google_calendar_token")

    if not client_secret_json:
        return None 

    if isinstance(client_secret_json, str):
        client_secret_json = json.loads(client_secret_json)

    creds = None

    if token_data:
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  
        else:
            temp_file = f"client_secret_{user_email}.json"
            with open(temp_file, "w") as f:
                json.dump(client_secret_json, f)

            flow = InstalledAppFlow.from_client_secrets_file(temp_file, SCOPES)
            creds = flow.run_local_server(port=0)
            os.remove(temp_file)

        supabase.table("users").update({
            "google_calendar_token": json.loads(creds.to_json())
        }).eq("email", user_email).execute()

    service = build('calendar', 'v3', credentials=creds)
    return service


def add_task_to_calendar(user_email, supabase, summary, description, date, start_time, end_time):

    service = get_calendar_service(user_email, supabase)
    if service is None:
        return "⚠️ Please connect your Google Calendar first."

    start_datetime = f"{date}T{start_time}:00"
    end_datetime = f"{date}T{end_time}:00"

    event = {
        'summary': summary,
        'description': description,
        'start': {'dateTime': start_datetime, 'timeZone': 'Asia/Kolkata'},
        'end': {'dateTime': end_datetime, 'timeZone': 'Asia/Kolkata'},
    }

    created_event = service.events().insert(calendarId='primary', body=event).execute()
    return f"✅ Task '{summary}' added on {date} from {start_time} to {end_time}."