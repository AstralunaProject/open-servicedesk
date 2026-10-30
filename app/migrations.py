"""Versões do schema, aplicadas na inicialização.

Banco novo: `create_all` cria o schema atual e grava a última versão.
Banco existente: roda, em ordem, as migrações acima da versão gravada.

Ao mudar um modelo, acrescente ao fim de MIGRATIONS uma função com o SQL equivalente
para quem já tem o banco. Nunca edite nem reordene uma migração publicada.
"""

import logging

from sqlalchemy import inspect, text

from .extensions import db

log = logging.getLogger(__name__)


def _index_resolved_at(conn) -> None:
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tickets_resolved_at ON tickets (resolved_at)"))


MIGRATIONS = [_index_resolved_at]
LATEST = len(MIGRATIONS)


def current_version(conn) -> int | None:
    if not inspect(conn).has_table("schema_version"):
        return None
    return conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar()


def upgrade() -> None:
    with db.engine.begin() as conn:
        fresh = not inspect(conn).has_table("tickets")
        version = current_version(conn)
        if version is None:
            conn.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"))
            # Bancos de antes das migrações já estão no schema da versão 0.
            version = LATEST if fresh else 0
            conn.execute(text("INSERT INTO schema_version (version) VALUES (:v)"), {"v": version})

    db.create_all()

    for number, migration in enumerate(MIGRATIONS[version:], start=version + 1):
        log.info("Atualizando o banco para a versão %s (%s)", number, migration.__name__.lstrip("_"))
        with db.engine.begin() as conn:
            migration(conn)
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": number})
