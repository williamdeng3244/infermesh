# SPDX-License-Identifier: Apache-2.0
"""Admin dashboard route + pin/unpin endpoints (Milestone 3)."""


def test_dashboard_served_at_root_and_admin(client):
    for path in ("/", "/admin"):
        r = client.get(path)
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        # app shell + the data source it polls + the model table
        assert "infermesh" in r.text
        assert "/api/status" in r.text
        assert "<table" in r.text


def test_pin_unpin_toggle(client, mock_pool):
    # `client` is built from `mock_pool`, so they share the same pool instance.
    r = client.post("/v1/models/echo-1/pin")
    assert r.status_code == 200 and r.json()["pinned"] is True
    assert mock_pool.get_entry("echo-1").is_pinned is True

    r = client.post("/v1/models/echo-1/unpin")
    assert r.status_code == 200 and r.json()["pinned"] is False
    assert mock_pool.get_entry("echo-1").is_pinned is False


def test_pin_unknown_model_404(client):
    assert client.post("/v1/models/does-not-exist/pin").status_code == 404
    assert client.post("/v1/models/does-not-exist/unpin").status_code == 404
