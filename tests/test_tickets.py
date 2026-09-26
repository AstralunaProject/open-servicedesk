import io

from app import services
from app.constants import STATUS_CLOSED, STATUS_IN_PROGRESS, STATUS_RESOLVED, STATUS_WAITING_USER
from app.extensions import db
from app.models import Category, Comment, Ticket, utcnow
from app.settings import set_setting

from .conftest import login, make_user


def open_ticket(client, **extra):
    category = db.session.scalar(db.select(Category).where(Category.name == "Impressoras"))
    data = {
        "type": "incident",
        "category_id": category.id,
        "title": "Impressora não imprime",
        "description": "Mostra papel atolado",
        "impact": "2",
        "urgency": "1",
        **extra,
    }
    response = client.post("/chamados/novo", data=data, content_type="multipart/form-data")
    assert response.status_code == 302, response.data
    return db.session.scalar(db.select(Ticket).order_by(Ticket.id.desc()))


def test_requester_opens_ticket_routed_by_category(app, requester, agent):
    ticket = open_ticket(login(app, requester))
    assert ticket.requester_id == requester.id
    assert ticket.group.name == "Service Desk (N1)"
    assert ticket.priority == 2
    assert ticket.response_due and ticket.resolution_due
    assert ticket.number == f"CH{ticket.id:06d}"


def test_requester_cannot_see_other_people_tickets(app, requester, agent):
    ticket = open_ticket(login(app, requester))
    other = make_user("outro@empresa.com")
    client = login(app, other)
    assert client.get(f"/chamados/{ticket.id}").status_code == 403
    assert ticket.number.encode() not in client.get("/chamados/?view=todos").data


def test_internal_notes_are_hidden_from_requester(app, requester, agent):
    ticket = open_ticket(login(app, requester))
    agent_client = login(app, agent)
    agent_client.post(f"/chamados/{ticket.id}/comentar", data={"body": "segredo da equipe", "internal": "1"})
    agent_client.post(f"/chamados/{ticket.id}/comentar", data={"body": "Resposta pública"})
    page = login(app, requester).get(f"/chamados/{ticket.id}").data.decode()
    assert "Resposta pública" in page
    assert "segredo da equipe" not in page


def test_requester_cannot_create_internal_note(app, requester, agent):
    client = login(app, requester)
    ticket = open_ticket(client)
    client.post(f"/chamados/{ticket.id}/comentar", data={"body": "tentativa", "internal": "1"})
    comment = db.session.scalar(db.select(Comment).where(Comment.ticket_id == ticket.id))
    assert comment.internal is False


def test_full_lifecycle(app, requester, agent):
    ticket = open_ticket(login(app, requester))
    agent_client = login(app, agent)

    agent_client.post(f"/chamados/{ticket.id}/assumir")
    db.session.refresh(ticket)
    assert ticket.assignee_id == agent.id
    assert ticket.status == STATUS_IN_PROGRESS
    assert ticket.first_response_at is not None

    agent_client.post(f"/chamados/{ticket.id}/atualizar", data={"status": "resolved"})
    db.session.refresh(ticket)
    assert ticket.status == STATUS_IN_PROGRESS, "resolver sem descrever a solução deve falhar"

    agent_client.post(
        f"/chamados/{ticket.id}/atualizar",
        data={"status": "resolved", "resolution_code": "solved", "resolution_notes": "Troquei o rolete."},
    )
    db.session.refresh(ticket)
    assert ticket.status == STATUS_RESOLVED
    assert ticket.resolved_at is not None

    requester_client = login(app, requester)
    requester_client.post(f"/chamados/{ticket.id}/avaliar", data={"score": "5", "comment": "Rápido!"})
    db.session.refresh(ticket)
    assert ticket.satisfaction == 5

    requester_client.post(f"/chamados/{ticket.id}/reabrir")
    db.session.refresh(ticket)
    assert ticket.status == STATUS_IN_PROGRESS
    assert ticket.resolved_at is None
    assert ticket.satisfaction is None


def test_requester_reply_resumes_waiting_ticket(app, requester, agent):
    ticket = open_ticket(login(app, requester))
    agent_client = login(app, agent)
    agent_client.post(
        f"/chamados/{ticket.id}/comentar", data={"body": "Qual o modelo?", "then_status": STATUS_WAITING_USER}
    )
    db.session.refresh(ticket)
    assert ticket.status == STATUS_WAITING_USER
    assert ticket.sla_paused_at is not None

    login(app, requester).post(f"/chamados/{ticket.id}/comentar", data={"body": "HP 408"})
    db.session.refresh(ticket)
    assert ticket.status == STATUS_IN_PROGRESS
    assert ticket.sla_paused_at is None


def test_attachments_respect_ticket_permissions(app, requester, agent):
    client = login(app, requester)
    ticket = open_ticket(client, files=(io.BytesIO(b"conteudo"), "erro.txt"))
    attachment = ticket.attachments[0]
    assert client.get(f"/chamados/anexo/{attachment.id}").data == b"conteudo"
    stranger = login(app, make_user("x@empresa.com"))
    assert stranger.get(f"/chamados/anexo/{attachment.id}").status_code == 403


def test_html_attachment_is_forced_to_download(app, requester, agent):
    client = login(app, requester)
    ticket = open_ticket(client, files=(io.BytesIO(b"<script>alert(1)</script>"), "x.html"))
    response = client.get(f"/chamados/anexo/{ticket.attachments[0].id}")
    assert response.headers["Content-Type"] == "application/octet-stream"
    assert "attachment" in response.headers["Content-Disposition"]


def test_search_by_number_and_csv_export(app, requester, agent):
    ticket = open_ticket(login(app, requester))
    agent_client = login(app, agent)
    page = agent_client.get(f"/chamados/?view=todos&q={ticket.number}").data.decode()
    assert ticket.title in page
    csv = agent_client.get("/chamados/exportar.csv?view=todos").data.decode("utf-8-sig")
    assert ticket.number in csv.splitlines()[1]


def test_auto_close_resolved_tickets(app, requester, agent):
    ticket = open_ticket(login(app, requester))
    services.update_ticket(ticket, agent, {"status": "resolved", "resolution_notes": "ok"})
    ticket.resolved_at = utcnow().replace(year=utcnow().year - 1)
    set_setting("auto_close_days", "5")
    db.session.commit()
    assert services.auto_close_resolved() == 1
    assert ticket.status == STATUS_CLOSED


def test_dashboard_renders_for_agent(app, requester, agent):
    open_ticket(login(app, requester))
    page = login(app, agent).get("/").data.decode()
    assert "Em aberto" in page
    assert "Impressora não imprime" in page
