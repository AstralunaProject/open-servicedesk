import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime

from flask import current_app

from .extensions import db


def sqlite_path() -> str | None:
    url = db.engine.url
    if url.get_backend_name() != "sqlite" or not url.database:
        return None
    return url.database


def create_backup(dest_dir: str | None = None) -> str:
    source = sqlite_path()
    if source is None:
        raise RuntimeError(
            "Backup automático disponível apenas para SQLite. "
            "Para outros bancos, use a ferramenta nativa (ex.: pg_dump)."
        )
    dest_dir = dest_dir or os.path.join(current_app.config["DATA_DIR"], "backups")
    os.makedirs(dest_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = os.path.join(dest_dir, f"chamados-backup-{stamp}.zip")

    with tempfile.TemporaryDirectory() as tmp:
        db_copy = os.path.join(tmp, "chamados.db")
        src = sqlite3.connect(source)
        dst = sqlite3.connect(db_copy)
        try:
            src.backup(dst)  # cópia consistente mesmo com o sistema em uso
        finally:
            dst.close()
            src.close()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_copy, "chamados.db")
            upload_dir = current_app.config["UPLOAD_DIR"]
            if os.path.isdir(upload_dir):
                for name in sorted(os.listdir(upload_dir)):
                    full = os.path.join(upload_dir, name)
                    if os.path.isfile(full):
                        zf.write(full, f"anexos/{name}")
    return zip_path
