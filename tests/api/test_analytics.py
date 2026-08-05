"""Tests for the analytics router placeholder."""


def test_analytics_status_returns_placeholder_message(client):
    """GET /analytics returns a static placeholder response."""
    response = client.get("/analytics")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "analytics endpoints coming soon",
    }
