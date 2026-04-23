import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from collectors.utils import activity_since

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _build_service(credentials_path: str):
    """Build a Google Calendar API service from a credentials file.

    Supports service account JSON (type: service_account) and OAuth2 client
    credentials JSON (installed / web). For OAuth2, a token.json file is
    expected alongside the credentials file (generated on first authorisation).
    """
    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
    except ImportError as e:
        raise ImportError(
            "Google Calendar dependencies missing. "
            "Run: pip install google-api-python-client google-auth-oauthlib"
        ) from e

    path = Path(credentials_path)
    raw = json.loads(path.read_text())

    if raw.get("type") == "service_account":
        creds = service_account.Credentials.from_service_account_info(raw, scopes=SCOPES)
    else:
        # OAuth2 flow — look for token.json next to the credentials file
        token_path = path.parent / "token.json"
        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
                creds = flow.run_local_server(port=0)
            token_path.write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def fetch_google_calendar_activity(credentials_path: str, since: datetime | None = None) -> dict:
    """Fetch calendar events attended during the activity window.

    Skips all-day events and events the user has declined.
    Returns: {"meetings": [{"title": str, "duration_minutes": int, "attendee_count": int}]}
    """
    activity: dict = {"meetings": []}
    cutoff = since or activity_since()

    try:
        service = _build_service(credentials_path)
    except ImportError as e:
        log.warning("%s", e)
        return activity
    except Exception as e:
        log.warning("Failed to build Google Calendar service: %s", e)
        return activity

    try:
        events_result = service.events().list(
            calendarId="primary",
            timeMin=cutoff.isoformat(),
            timeMax=datetime.now(timezone.utc).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        ).execute()
    except Exception as e:
        log.warning("Google Calendar API request failed: %s", e)
        return activity

    for event in events_result.get("items", []):
        start = event.get("start", {})

        # Skip all-day events (they have 'date' but not 'dateTime')
        if "dateTime" not in start:
            continue

        # Skip events the user has declined
        attendees = event.get("attendees", [])
        self_rsvp = next((a for a in attendees if a.get("self")), None)
        if self_rsvp and self_rsvp.get("responseStatus") == "declined":
            continue

        try:
            start_dt = datetime.fromisoformat(start["dateTime"])
            end_dt = datetime.fromisoformat(event["end"]["dateTime"])
            duration = int((end_dt - start_dt).total_seconds() / 60)
        except (KeyError, ValueError):
            duration = 0

        activity["meetings"].append({
            "title": event.get("summary", "Untitled"),
            "duration_minutes": duration,
            "attendee_count": len(attendees),
        })

    return activity
