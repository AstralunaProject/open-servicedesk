import logging

from flask import Flask, redirect, request, url_for
from sqlalchemy import event
from sqlalchemy.engine import Engine

from .config import load_config
from .extensions import csrf, db, login_manager

__version__ = "1.0.0"


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record):
    # Ativa chaves estrangeiras e WAL (melhor concorrência) quando o banco é SQLite.
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def create_app(test_config=None) -> Flask:
    app = Flask(__name__)
    load_config(app, test_config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if app.config.get("PROXY_FIX"):
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .utils import register_filters
    from .views import admin, api, assets, auth, kb, main, tickets

    for module in (auth, main, tickets, kb, assets, admin, api):
        app.register_blueprint(module.bp)
    csrf.exempt(api.bp)
    register_filters(app)

    with app.app_context():
        db.create_all()
        from .bootstrap import ensure_defaults

        ensure_defaults()

    _register_hooks(app)

    from .cli import register_cli

    register_cli(app)
    return app


def _register_hooks(app: Flask) -> None:
    from flask import render_template
    from flask_login import current_user

    from . import constants, models
    from .settings import all_settings, get_setting

    @app.before_request
    def require_setup():
        if app.extensions.get("setup_done"):
            return None
        if db.session.scalar(db.select(db.func.count(models.User.id))):
            app.extensions["setup_done"] = True
            return None
        if request.endpoint in ("auth.setup", "static", "main.health") or request.blueprint == "api":
            return None
        return redirect(url_for("auth.setup"))

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.context_processor
    def inject_globals():
        return {
            "cfg": all_settings(),
            "app_title": get_setting("app_title"),
            "company_name": get_setting("company_name"),
            "STATUSES": constants.STATUSES,
            "PRIORITIES": constants.PRIORITIES,
            "TYPES": constants.TYPES,
            "CHANNELS": constants.CHANNELS,
            "IMPACTS": constants.IMPACTS,
            "URGENCIES": constants.URGENCIES,
            "IMPACTS_FRIENDLY": constants.IMPACTS_FRIENDLY,
            "URGENCIES_FRIENDLY": constants.URGENCIES_FRIENDLY,
            "RESOLUTION_CODES": constants.RESOLUTION_CODES,
            "ROLES": constants.ROLES,
            "version": __version__,
            "me": current_user,
        }

    for code in (400, 403, 404, 413, 500):

        def handler(error, code=code):
            if code == 500:
                db.session.rollback()
            if request.blueprint == "api":
                return {"error": getattr(error, "description", "erro")}, code
            return render_template("errors/error.html", code=code, error=error), code

        app.register_error_handler(code, handler)
