from app.extensions import db


def token_for(user):
    token = user.generate_api_token()
    db.session.commit()
    return {"Authorization": f"Bearer {token}"}


def test_api_requires_valid_token(app, requester):
    client = app.test_client()
    assert client.get("/api/v1/tickets").status_code == 401
    assert client.get("/api/v1/tickets", headers={"Authorization": "Bearer nada"}).status_code == 401


def test_api_create_list_and_comment(app, requester, agent):
    client = app.test_client()
    headers = token_for(requester)
    response = client.post(
        "/api/v1/tickets",
        json={"title": "Sem internet", "description": "Cabo ok", "category": "Internet e rede", "urgency": 1},
        headers=headers,
    )
    assert response.status_code == 201
    created = response.get_json()
    assert created["group"] == "Infraestrutura"
    assert created["requester"]["email"] == requester.email

    listing = client.get("/api/v1/tickets", headers=headers).get_json()
    assert listing["total"] == 1

    response = client.post(
        f"/api/v1/tickets/{created['id']}/comments", json={"body": "Ainda sem"}, headers=headers
    )
    assert response.status_code == 201
    assert response.get_json()["internal"] is False


def test_api_requester_cannot_open_on_behalf_or_patch(app, requester, agent):
    client = app.test_client()
    headers = token_for(requester)
    response = client.post(
        "/api/v1/tickets", json={"title": "x", "requester_email": agent.email}, headers=headers
    )
    assert response.status_code == 403
    ticket_id = client.post("/api/v1/tickets", json={"title": "x"}, headers=headers).get_json()["id"]
    assert (
        client.patch(f"/api/v1/tickets/{ticket_id}", json={"status": "closed"}, headers=headers).status_code
        == 403
    )


def test_api_agent_opens_on_behalf_and_resolves(app, requester, agent):
    client = app.test_client()
    headers = token_for(agent)
    created = client.post(
        "/api/v1/tickets",
        json={"title": "Via WhatsApp", "requester_email": requester.email, "channel": "chat"},
        headers=headers,
    ).get_json()
    assert created["channel"] == "chat"
    response = client.patch(
        f"/api/v1/tickets/{created['id']}",
        json={"status": "resolved", "resolution_notes": "Orientado por telefone"},
        headers=headers,
    )
    assert response.get_json()["status"] == "resolved"
