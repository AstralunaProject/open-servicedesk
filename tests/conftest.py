import pytest
from flask import g

from app import create_app
from app.bootstrap import seed_catalog
from app.constants import ROLE_ADMIN, ROLE_AGENT, ROLE_USER
from app.extensions import db
from app.models import Group, User
from app.settings import set_setting

PASSWORD = "senha-segura-1"


@pytest.fixture()
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DATA_DIR": str(tmp_path),
            "SECRET_KEY": "teste",
            "BASE_URL": "http://chamados.test",
        }
    )

    # Os testes mantêm um app context aberto para usar db.session diretamente, e o Flask
    # reaproveita esse contexto (e o `g`) em cada requisição do test client. Sem isto, o
    # usuário logado e as configurações em cache vazariam de uma requisição para outra.
    @app.before_request
    def reset_request_globals():
        g.pop("_login_user", None)
        g.pop("_settings", None)

    with app.app_context():
        seed_catalog()
        set_setting("business_hours_enabled", "0")
        db.session.commit()
        yield app


def make_user(email, role=ROLE_USER, name=None):
    user = User(name=name or email.split("@")[0].title(), email=email, role=role)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture()
def admin(app):
    return make_user("admin@empresa.com", ROLE_ADMIN, "Admin Geral")


@pytest.fixture()
def agent(app, admin):
    user = make_user("tecnico@empresa.com", ROLE_AGENT, "Tânia Técnica")
    for group in db.session.scalars(db.select(Group)):
        group.members.append(user)
    db.session.commit()
    return user


@pytest.fixture()
def requester(app, admin):
    return make_user("ana@empresa.com", ROLE_USER, "Ana Souza")


def login(app, user):
    client = app.test_client()
    response = client.post("/entrar", data={"email": user.email, "password": PASSWORD})
    assert response.status_code == 302
    return client
