def test_health_needs_no_database(client_without_db):
    response = client_without_db.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_503_when_the_database_is_down(client_without_db):
    response = client_without_db.get("/ready")

    assert response.status_code == 503


def test_ready_reports_200_when_the_database_is_up(client):
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
