import json
import pytest
from unittest.mock import patch, MagicMock
from collectors.google_calendar import fetch_google_calendar_activity


def _make_event(summary, start_dt, end_dt, attendees=None, all_day=False):
    event = {"summary": summary, "end": {"dateTime": end_dt}}
    if all_day:
        event["start"] = {"date": start_dt[:10]}
    else:
        event["start"] = {"dateTime": start_dt}
    if attendees is not None:
        event["attendees"] = attendees
    return event


def _mock_service(events):
    service = MagicMock()
    service.events().list().execute.return_value = {"items": events}
    return service


def test_meeting_returned_with_correct_fields(tmp_path):
    creds_file = tmp_path / "creds.json"
    creds_file.write_text(json.dumps({"type": "service_account"}))
    event = _make_event("Sprint Planning", "2026-04-22T09:00:00+00:00", "2026-04-22T10:00:00+00:00", attendees=[{"self": True, "responseStatus": "accepted"}, {}])

    with patch("collectors.google_calendar._build_service", return_value=_mock_service([event])):
        result = fetch_google_calendar_activity(str(creds_file))

    assert len(result["meetings"]) == 1
    meeting = result["meetings"][0]
    assert meeting["title"] == "Sprint Planning"
    assert meeting["duration_minutes"] == 60
    assert meeting["attendee_count"] == 2


def test_all_day_events_skipped(tmp_path):
    creds_file = tmp_path / "creds.json"
    creds_file.write_text(json.dumps({"type": "service_account"}))
    event = _make_event("Company Holiday", "2026-04-22", "2026-04-22", all_day=True)

    with patch("collectors.google_calendar._build_service", return_value=_mock_service([event])):
        result = fetch_google_calendar_activity(str(creds_file))

    assert result["meetings"] == []


def test_declined_events_skipped(tmp_path):
    creds_file = tmp_path / "creds.json"
    creds_file.write_text(json.dumps({"type": "service_account"}))
    event = _make_event("1:1", "2026-04-22T14:00:00+00:00", "2026-04-22T14:30:00+00:00",
                         attendees=[{"self": True, "responseStatus": "declined"}])

    with patch("collectors.google_calendar._build_service", return_value=_mock_service([event])):
        result = fetch_google_calendar_activity(str(creds_file))

    assert result["meetings"] == []


def test_missing_import_returns_empty_with_warning(tmp_path, caplog):
    import logging
    creds_file = tmp_path / "creds.json"
    creds_file.write_text(json.dumps({"type": "service_account"}))

    with patch("collectors.google_calendar._build_service", side_effect=ImportError("no google")):
        with caplog.at_level(logging.WARNING, logger="collectors.google_calendar"):
            result = fetch_google_calendar_activity(str(creds_file))

    assert result == {"meetings": []}
    assert "no google" in caplog.text


def test_api_failure_returns_empty_with_warning(tmp_path, caplog):
    import logging
    creds_file = tmp_path / "creds.json"
    creds_file.write_text(json.dumps({"type": "service_account"}))
    service = MagicMock()
    service.events().list().execute.side_effect = Exception("403 Forbidden")

    with patch("collectors.google_calendar._build_service", return_value=service):
        with caplog.at_level(logging.WARNING, logger="collectors.google_calendar"):
            result = fetch_google_calendar_activity(str(creds_file))

    assert result == {"meetings": []}
    assert "403 Forbidden" in caplog.text


def test_event_without_attendees_included(tmp_path):
    creds_file = tmp_path / "creds.json"
    creds_file.write_text(json.dumps({"type": "service_account"}))
    event = _make_event("Focus block", "2026-04-22T10:00:00+00:00", "2026-04-22T11:00:00+00:00")

    with patch("collectors.google_calendar._build_service", return_value=_mock_service([event])):
        result = fetch_google_calendar_activity(str(creds_file))

    assert len(result["meetings"]) == 1
    assert result["meetings"][0]["attendee_count"] == 0


def test_duration_calculated_correctly(tmp_path):
    creds_file = tmp_path / "creds.json"
    creds_file.write_text(json.dumps({"type": "service_account"}))
    event = _make_event("Standup", "2026-04-22T09:00:00+00:00", "2026-04-22T09:15:00+00:00")

    with patch("collectors.google_calendar._build_service", return_value=_mock_service([event])):
        result = fetch_google_calendar_activity(str(creds_file))

    assert result["meetings"][0]["duration_minutes"] == 15
