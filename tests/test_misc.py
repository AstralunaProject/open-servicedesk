import zipfile

from app.backup import create_backup
from app.utils import markdown, nl2br

from .conftest import login


def test_markdown_escapes_html():
    html = markdown("# Título\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1)) **negrito**")
    assert "<script>" not in html
    assert 'href="javascript' not in html
    assert "<h2>Título</h2>" in html
    assert "<strong>negrito</strong>" in html


def test_nl2br_links_only_http():
    html = nl2br("veja https://exemplo.com.br/a?b=1 e <b>isso</b>")
    assert '<a href="https://exemplo.com.br/a?b=1"' in html
    assert "<b>" not in html


def test_backup_contains_database(app, admin, tmp_path):
    path = create_backup(str(tmp_path / "bkp"))
    with zipfile.ZipFile(path) as zf:
        assert "chamados.db" in zf.namelist()


def test_kb_drafts_hidden_from_requesters(app, requester, agent):
    agent_client = login(app, agent)
    agent_client.post("/conhecimento/novo", data={"title": "Rascunho secreto", "body": "x"})
    agent_client.post("/conhecimento/novo", data={"title": "Como usar a VPN", "body": "y", "published": "1"})
    page = login(app, requester).get("/conhecimento/").data.decode()
    assert "Como usar a VPN" in page
    assert "Rascunho secreto" not in page


def test_health_endpoint(app):
    assert app.test_client().get("/saude").get_json() == {"status": "ok"}
