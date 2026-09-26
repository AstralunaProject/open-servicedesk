import random
import secrets
from datetime import timedelta

from . import services
from .bootstrap import seed_catalog
from .constants import ROLE_AGENT, ROLE_USER
from .extensions import db
from .models import Asset, Category, Group, KBArticle, User, utcnow
from .sla import apply_sla

SAMPLE_TICKETS = [
    (
        "Computador muito lento",
        "Desde ontem o computador demora vários minutos para abrir o sistema.",
        "Computador / Notebook",
    ),
    (
        "Impressora não imprime",
        "A impressora do 3º andar mostra erro de papel atolado, mas não há papel preso.",
        "Impressoras",
    ),
    (
        "Sem acesso à pasta do financeiro",
        "Preciso de acesso à pasta \\\\servidor\\financeiro.",
        "Acesso e senhas",
    ),
    ("Internet caindo toda hora", "O Wi-Fi da sala de reunião cai a cada 10 minutos.", "Internet e rede"),
    ("Instalar Power BI", "Preciso do Power BI Desktop para relatórios.", "Software"),
    ("Erro ao emitir nota fiscal", "O ERP apresenta 'rejeição 539' ao emitir NF-e.", "Sistemas / ERP"),
    ("Trocar senha do e-mail", "Esqueci minha senha do e-mail.", "E-mail"),
    ("Ramal mudo", "O ramal 2045 está sem tom de discagem.", "Telefonia"),
]
REQUEST_CATEGORIES = {"Software", "Acesso e senhas"}

VPN_ARTICLE = (
    "## Antes de começar\n\nVocê precisa do **usuário de rede** e do aplicativo de VPN instalado.\n\n"
    "1. Abra o aplicativo de VPN\n"
    "2. Informe o servidor `vpn.empresa.com.br`\n"
    "3. Entre com seu usuário e senha\n\n"
    "> Se aparecer erro de certificado, abra um chamado na categoria *Internet e rede*."
)


def _user(rnd, name, email, role, password):
    existing = db.session.scalar(db.select(User).where(User.email == email))
    if existing:
        return existing
    user = User(
        name=name, email=email, role=role, department=rnd.choice(["Financeiro", "RH", "Vendas", "Logística"])
    )
    user.set_password(password)
    db.session.add(user)
    return user


def _people(rnd, password):
    agents = [
        _user(rnd, "Carla Mendes", "carla@demo.local", ROLE_AGENT, password),
        _user(rnd, "Bruno Alves", "bruno@demo.local", ROLE_AGENT, password),
    ]
    requesters = [
        _user(rnd, "Ana Souza", "ana@demo.local", ROLE_USER, password),
        _user(rnd, "Pedro Lima", "pedro@demo.local", ROLE_USER, password),
        _user(rnd, "Júlia Rocha", "julia@demo.local", ROLE_USER, password),
    ]
    db.session.flush()
    for group in db.session.scalars(db.select(Group)):
        group.members.extend(a for a in agents if a not in group.members)
    return agents, requesters


def _assets(requesters):
    items = [
        ("Notebook Dell Latitude", "Notebook", "Dell", requesters[0]),
        ("Impressora HP 3º andar", "Impressora", "HP", None),
        ("Servidor de arquivos", "Servidor", "Dell", None),
        ("Desktop Recepção", "Desktop", "Lenovo", requesters[1]),
    ]
    for i, (name, kind, maker, owner) in enumerate(items):
        tag = f"PAT-{1001 + i}"
        if db.session.scalar(db.select(Asset).where(Asset.tag == tag)) is None:
            db.session.add(
                Asset(tag=tag, name=name, type=kind, manufacturer=maker, assigned_to=owner, location="Matriz")
            )


def _tickets(rnd, agents, requesters):
    categories = {c.name: c for c in db.session.scalars(db.select(Category))}
    now = utcnow()
    for title, description, category in SAMPLE_TICKETS * 2:
        ticket = services.create_ticket(
            rnd.choice(requesters),
            title,
            description,
            category=categories.get(category),
            impact=rnd.choice([1, 2, 3, 3]),
            urgency=rnd.choice([1, 2, 2, 3]),
            type="request" if category in REQUEST_CATEGORIES else "incident",
            channel=rnd.choice(["portal", "portal", "email", "phone"]),
        )
        ticket.created_at = now - timedelta(days=rnd.randint(0, 20), hours=rnd.randint(0, 8))
        apply_sla(ticket)
        db.session.commit()
        _work_on(rnd, ticket, rnd.choice(agents))


def _work_on(rnd, ticket, agent):
    roll = rnd.random()
    if roll < 0.25:
        return
    services.update_ticket(ticket, agent, {"assignee_id": agent.id})
    services.add_comment(ticket, agent, "Olá! Estou verificando e retorno em breve.")
    ticket.first_response_at = ticket.created_at + timedelta(minutes=rnd.randint(10, 180))
    if roll > 0.55:
        services.update_ticket(
            ticket,
            agent,
            {
                "status": "resolved",
                "resolution_code": "solved",
                "resolution_notes": "Problema corrigido remotamente.",
            },
        )
        ticket.resolved_at = ticket.first_response_at + timedelta(hours=rnd.randint(1, 30))
        if rnd.random() > 0.3:
            ticket.satisfaction = rnd.choice([3, 4, 5, 5])
    db.session.commit()


def load_demo_data() -> str:
    seed_catalog()
    rnd = random.Random(42)
    password = secrets.token_urlsafe(9)
    agents, requesters = _people(rnd, password)
    _assets(requesters)
    db.session.add(
        KBArticle(
            title="Como conectar na VPN",
            summary="Passo a passo para acessar a rede da empresa de casa.",
            body=VPN_ARTICLE,
            category=db.session.scalar(db.select(Category).where(Category.name == "Internet e rede")),
            author=agents[0],
            published=True,
        )
    )
    db.session.commit()
    _tickets(rnd, agents, requesters)
    return password
