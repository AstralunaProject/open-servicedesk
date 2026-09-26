from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import Category, KBArticle, utcnow
from ..utils import agent_required

bp = Blueprint("kb", __name__, url_prefix="/conhecimento")


def _visible_query():
    query = db.select(KBArticle)
    if not current_user.is_agent:
        query = query.where(KBArticle.published.is_(True), KBArticle.internal.is_(False))
    return query


@bp.route("/")
@login_required
def index():
    query = _visible_query()
    text = (request.args.get("q") or "").strip()
    if text:
        like = f"%{text}%"
        query = query.where(
            db.or_(KBArticle.title.ilike(like), KBArticle.body.ilike(like), KBArticle.summary.ilike(like))
        )
    category = request.args.get("category", "")
    if category.isdigit():
        query = query.where(KBArticle.category_id == int(category))
    page = db.paginate(
        query.order_by(KBArticle.updated_at.desc()),
        page=request.args.get("page", 1, type=int),
        per_page=20,
        error_out=False,
    )
    categories = db.session.scalars(db.select(Category).order_by(Category.name)).all()
    return render_template("kb/list.html", page=page, q=text, category=category, categories=categories)


@bp.route("/<int:article_id>")
@login_required
def view(article_id):
    article = db.session.get(KBArticle, article_id)
    if article is None:
        abort(404)
    if not current_user.is_agent and (not article.published or article.internal):
        abort(404)
    article.views += 1
    db.session.commit()
    return render_template("kb/view.html", article=article)


@bp.route("/novo", methods=["GET", "POST"])
@bp.route("/<int:article_id>/editar", methods=["GET", "POST"])
@agent_required
def edit(article_id=None):
    article = db.session.get(KBArticle, article_id) if article_id else KBArticle(author=current_user)
    if article is None:
        abort(404)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Informe o título.", "error")
        else:
            article.title = title[:200]
            article.summary = request.form.get("summary", "").strip()[:300] or None
            article.body = request.form.get("body", "")
            article.category_id = request.form.get("category_id", type=int) or None
            article.published = request.form.get("published") == "1"
            article.internal = request.form.get("internal") == "1"
            article.updated_at = utcnow()
            if article.id is None:
                db.session.add(article)
            db.session.commit()
            flash("Artigo salvo.", "success")
            return redirect(url_for("kb.view", article_id=article.id))
    categories = db.session.scalars(db.select(Category).order_by(Category.name)).all()
    return render_template("kb/edit.html", article=article, categories=categories)


@bp.route("/<int:article_id>/excluir", methods=["POST"])
@agent_required
def delete(article_id):
    article = db.session.get(KBArticle, article_id)
    if article is None:
        abort(404)
    db.session.delete(article)
    db.session.commit()
    flash("Artigo excluído.", "info")
    return redirect(url_for("kb.index"))
