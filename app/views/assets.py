from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ..constants import ASSET_STATUSES, ASSET_TYPES
from ..extensions import db
from ..models import Asset, User, utcnow
from ..utils import admin_required, agent_required

bp = Blueprint("assets", __name__, url_prefix="/ativos")


def _parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@bp.route("/")
@agent_required
def index():
    query = db.select(Asset)
    text = (request.args.get("q") or "").strip()
    if text:
        like = f"%{text}%"
        query = query.where(
            db.or_(
                Asset.tag.ilike(like),
                Asset.name.ilike(like),
                Asset.serial.ilike(like),
                Asset.model.ilike(like),
                Asset.location.ilike(like),
                Asset.assigned_to.has(User.name.ilike(like)),
            )
        )
    if request.args.get("type") in ASSET_TYPES:
        query = query.where(Asset.type == request.args["type"])
    if request.args.get("status") in ASSET_STATUSES:
        query = query.where(Asset.status == request.args["status"])
    page = db.paginate(
        query.order_by(Asset.tag), page=request.args.get("page", 1, type=int), per_page=30, error_out=False
    )
    args = {k: v for k, v in request.args.items() if k != "page"}
    return render_template(
        "assets/list.html", page=page, args=args, types=ASSET_TYPES, statuses=ASSET_STATUSES
    )


@bp.route("/<int:asset_id>")
@agent_required
def view(asset_id):
    asset = db.session.get(Asset, asset_id)
    if asset is None:
        abort(404)
    return render_template("assets/view.html", asset=asset, today=date.today())


@bp.route("/novo", methods=["GET", "POST"])
@bp.route("/<int:asset_id>/editar", methods=["GET", "POST"])
@agent_required
def edit(asset_id=None):
    asset = db.session.get(Asset, asset_id) if asset_id else Asset()
    if asset is None:
        abort(404)
    if request.method == "POST":
        form = request.form
        tag = form.get("tag", "").strip()
        name = form.get("name", "").strip()
        duplicate = db.session.scalar(db.select(Asset).where(Asset.tag == tag, Asset.id != (asset.id or 0)))
        if not tag or not name:
            flash("Patrimônio e nome são obrigatórios.", "error")
        elif duplicate:
            flash("Já existe um ativo com este número de patrimônio.", "error")
        else:
            asset.tag = tag[:60]
            asset.name = name[:160]
            asset.type = form.get("type") if form.get("type") in ASSET_TYPES else "Outro"
            asset.status = form.get("status") if form.get("status") in ASSET_STATUSES else "in_use"
            for field in ("manufacturer", "model", "serial", "location"):
                setattr(asset, field, form.get(field, "").strip()[:120] or None)
            asset.notes = form.get("notes", "").strip() or None
            asset.assigned_to_id = form.get("assigned_to_id", type=int) or None
            asset.purchase_date = _parse_date(form.get("purchase_date"))
            asset.warranty_until = _parse_date(form.get("warranty_until"))
            asset.updated_at = utcnow()
            if asset.id is None:
                db.session.add(asset)
            db.session.commit()
            flash("Ativo salvo.", "success")
            return redirect(url_for("assets.view", asset_id=asset.id))
    users = db.session.scalars(db.select(User).where(User.active.is_(True)).order_by(User.name)).all()
    return render_template(
        "assets/edit.html", asset=asset, users=users, types=ASSET_TYPES, statuses=ASSET_STATUSES
    )


@bp.route("/<int:asset_id>/excluir", methods=["POST"])
@admin_required
def delete(asset_id):
    asset = db.session.get(Asset, asset_id)
    if asset is None:
        abort(404)
    for ticket in asset.tickets:
        ticket.asset = None
    db.session.delete(asset)
    db.session.commit()
    flash("Ativo excluído.", "info")
    return redirect(url_for("assets.index"))
