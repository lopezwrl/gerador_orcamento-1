from functools import wraps

from flask import abort
from flask_login import current_user


def approver_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.papel not in {"admin", "aprovador"}:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.papel != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def comprador_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.papel not in {"admin", "comprador"}:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def owner_or_admin(orcamento):
    if not current_user.is_authenticated:
        abort(401)
    if current_user.papel != "admin" and orcamento.usuario_id != current_user.id:
        abort(404)
    return orcamento
