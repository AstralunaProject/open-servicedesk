import logging
import threading
import time

from .settings import get_int

log = logging.getLogger(__name__)


def run_maintenance(app, state: dict | None = None) -> dict:
    from . import mail_inbound, services
    from .extensions import db

    state = state if state is not None else {}
    result = {"closed": 0, "emails": 0}
    with app.app_context():
        try:
            result["closed"] = services.auto_close_resolved()
        except Exception:
            # A rotina roda para sempre em segundo plano; um erro aqui não pode
            # derrubar a thread, então é registrado e tentado de novo no próximo ciclo.
            db.session.rollback()
            log.exception("Falha ao fechar chamados resolvidos")
        interval = max(1, get_int("imap_interval", 5)) * 60
        if time.monotonic() - state.get("last_imap", -interval) >= interval:
            state["last_imap"] = time.monotonic()
            try:
                result["emails"] = mail_inbound.poll_mailbox()
            except Exception:
                db.session.rollback()
                log.exception("Falha ao ler caixa de e-mail (IMAP)")
    return result


def start_background_worker(app, every_seconds: int = 60) -> threading.Thread:
    state: dict = {}

    def loop():
        while True:
            run_maintenance(app, state)
            time.sleep(every_seconds)

    thread = threading.Thread(target=loop, name="chamados-worker", daemon=True)
    thread.start()
    return thread
