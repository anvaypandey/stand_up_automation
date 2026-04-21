from unittest.mock import MagicMock


def mock_response(data: dict, ok: bool = True, status_code: int = 200) -> MagicMock:
    """Build a fake requests.Response."""
    m = MagicMock()
    m.ok = ok
    m.status_code = status_code
    m.json.return_value = data
    return m
