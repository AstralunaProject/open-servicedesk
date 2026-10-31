from sqlalchemy import inspect, text

from app import create_app
from app.extensions import db
from app.migrations import LATEST, current_version


def _config(tmp_path):
    return {"TESTING": True, "DATA_DIR": str(tmp_path), "SECRET_KEY": "teste"}


def _indexes(conn):
    return {i["name"] for i in inspect(conn).get_indexes("tickets")}


def test_new_database_starts_at_latest_version(tmp_path):
    app = create_app(_config(tmp_path))
    with app.app_context(), db.engine.connect() as conn:
        assert current_version(conn) == LATEST
        assert "ix_tickets_resolved_at" in _indexes(conn)


def test_database_from_before_migrations_is_upgraded(tmp_path):
    app = create_app(_config(tmp_path))
    with app.app_context(), db.engine.begin() as conn:
        conn.execute(text("DROP TABLE schema_version"))
        conn.execute(text("DROP INDEX ix_tickets_resolved_at"))
    with app.app_context():
        db.engine.dispose()

    upgraded = create_app(_config(tmp_path))
    with upgraded.app_context(), db.engine.connect() as conn:
        assert current_version(conn) == LATEST
        assert "ix_tickets_resolved_at" in _indexes(conn)


def test_restart_does_not_rerun_migrations(tmp_path, monkeypatch):
    create_app(_config(tmp_path))
    calls = []
    monkeypatch.setattr("app.migrations.MIGRATIONS", [lambda conn: calls.append(conn)] * LATEST)
    create_app(_config(tmp_path))
    assert calls == []
