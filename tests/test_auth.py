from app.extensions import db
from app.models import Category, Group, User

from .conftest import PASSWORD, login


def test_first_access_redirects_to_setup_and_creates_admin(tmp_path):
    from app import create_app

    app = create_app(
        {"TESTING": True, "WTF_CSRF_ENABLED": False, "DATA_DIR": str(tmp_path), "SECRET_KEY": "x"}
    )
    client = app.test_client()
    assert client.get("/").location.endswith("/configuracao-inicial")
    response = client.post(
        "/configuracao-inicial",
        data={
            "company_name": "Padaria Central",
            "name": "Dona Maria",
            "email": "maria@padaria.com",
            "password": "12345678",
            "confirm": "12345678",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        admin = db.session.scalar(db.select(User))
        assert admin.is_admin
        assert db.session.scalar(db.select(db.func.count(Group.id))) > 0
        assert db.session.scalar(db.select(db.func.count(Category.id))) > 0
    assert client.get("/configuracao-inicial").status_code == 302


def test_login_rejects_wrong_password(app, requester):
    client = app.test_client()
    response = client.post("/entrar", data={"email": requester.email, "password": "errada"})
    assert response.status_code == 401


def test_login_blocks_after_repeated_failures(app, requester):
    client = app.test_client()
    for _ in range(10):
        client.post("/entrar", data={"email": requester.email, "password": "errada"})
    response = client.post("/entrar", data={"email": requester.email, "password": PASSWORD})
    assert response.status_code == 429


def test_inactive_user_cannot_login(app, requester):
    requester.active = False
    db.session.commit()
    response = app.test_client().post("/entrar", data={"email": requester.email, "password": PASSWORD})
    assert response.status_code == 401


def test_login_ignores_external_next(app, requester):
    client = app.test_client()
    response = client.post(
        "/entrar?next=//evil.example.com", data={"email": requester.email, "password": PASSWORD}
    )
    assert response.location == "/"


def test_requester_cannot_open_admin_or_assets(app, requester):
    client = login(app, requester)
    assert client.get("/admin/usuarios").status_code == 403
    assert client.get("/ativos/").status_code == 403


def test_last_admin_cannot_be_demoted(app, admin):
    client = login(app, admin)
    client.post(
        f"/admin/usuarios/{admin.id}",
        data={"name": admin.name, "email": admin.email, "role": "user", "active": "1"},
    )
    db.session.refresh(admin)
    assert admin.is_admin


def test_registration_respects_allowed_domains(app, admin):
    from app.settings import set_setting

    set_setting("allow_registration", "1")
    set_setting("registration_domains", "empresa.com")
    db.session.commit()
    client = app.test_client()
    data = {"name": "Zé", "password": "12345678", "confirm": "12345678"}
    client.post("/cadastro", data={**data, "email": "ze@gmail.com"})
    assert db.session.scalar(db.select(User).where(User.email == "ze@gmail.com")) is None
    client.post("/cadastro", data={**data, "email": "ze@empresa.com"})
    assert db.session.scalar(db.select(User).where(User.email == "ze@empresa.com")) is not None
