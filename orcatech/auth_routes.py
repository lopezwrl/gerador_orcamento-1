from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import current_user, login_user, logout_user
from sqlalchemy import func

from .auth import admin_required
from .empresarial_service import funcionalidade_empresarial_ativa
from .models import Departamento, Usuario, db

auth_bp = Blueprint("auth", __name__)
limiter = Limiter(key_func=get_remote_address)


def _safe_next(target):
    if not target:
        return None
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        return None
    if parsed.path.startswith("//") or "\\" in parsed.path:
        return None
    return target


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    erro = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        usuario = Usuario.query.filter(func.lower(Usuario.email) == email).first()
        if usuario and usuario.ativo and usuario.checar_senha(senha):
            session.clear()
            login_user(usuario)
            destino = _safe_next(request.args.get("next"))
            return redirect(destino or url_for("home"))
        erro = "E-mail ou senha inválidos."
    return render_template("login.html", erro=erro)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    if current_user.is_authenticated:
        logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/usuarios", methods=["GET", "POST"])
@admin_required
def usuarios():
    erro = None
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        papel = request.form.get("papel", "usuario")
        departamento_id = request.form.get("departamento_id", type=int)
        papeis_validos = {"admin", "usuario", "aprovador"}
        if funcionalidade_empresarial_ativa():
            papeis_validos.add("comprador")
        departamento = db.session.get(Departamento, departamento_id) if departamento_id else None
        if not nome or not email or "@" not in email:
            erro = "Informe nome e um e-mail válido."
        elif len(senha) < 12:
            erro = "A senha deve ter pelo menos 12 caracteres."
        elif papel not in papeis_validos:
            erro = "O papel selecionado é inválido."
        elif departamento_id and departamento is None:
            erro = "O departamento selecionado é inválido."
        elif funcionalidade_empresarial_ativa() and papel == "aprovador" and not departamento:
            erro = "Vincule o aprovador a um departamento."
        elif Usuario.query.filter(func.lower(Usuario.email) == email).first():
            erro = "Não foi possível criar o usuário com os dados informados."
        else:
            usuario = Usuario(
                nome=nome,
                email=email,
                papel=papel,
                ativo=True,
                departamento_id=departamento.id if departamento else None,
            )
            usuario.set_senha(senha)
            db.session.add(usuario)
            db.session.commit()
            flash("Usuário criado com sucesso.", "sucesso")
            return redirect(url_for("auth.usuarios"))

    lista = Usuario.query.order_by(Usuario.nome, Usuario.email).all()
    departamentos = Departamento.query.order_by(Departamento.nome).all()
    return render_template(
        "usuarios.html",
        usuarios=lista,
        departamentos=departamentos,
        empresarial_ativa=funcionalidade_empresarial_ativa(),
        erro=erro,
    )


@auth_bp.route("/usuarios/<int:usuario_id>/perfil", methods=["POST"])
@admin_required
def atualizar_perfil_usuario(usuario_id):
    if not funcionalidade_empresarial_ativa():
        abort(404)
    usuario = db.session.get(Usuario, usuario_id)
    if usuario is None:
        abort(404)

    papel = request.form.get("papel", "")
    departamento_id = request.form.get("departamento_id", type=int)
    departamento = db.session.get(Departamento, departamento_id) if departamento_id else None
    if papel not in {"admin", "usuario", "aprovador", "comprador"}:
        flash("O papel selecionado é inválido.", "erro")
    elif departamento_id and departamento is None:
        flash("O departamento selecionado é inválido.", "erro")
    elif papel == "aprovador" and departamento is None:
        flash("Vincule o aprovador a um departamento.", "erro")
    elif usuario.id == current_user.id and usuario.papel == "admin" and papel != "admin" and (
        Usuario.query.filter_by(papel="admin", ativo=True).count() <= 1
    ):
        flash("O sistema precisa manter pelo menos um administrador ativo.", "erro")
    else:
        usuario.papel = papel
        usuario.departamento_id = departamento.id if departamento else None
        db.session.commit()
        flash("Perfil atualizado.", "sucesso")
    return redirect(url_for("auth.usuarios"))


@auth_bp.route("/usuarios/<int:usuario_id>/ativo", methods=["POST"])
@admin_required
def alternar_usuario(usuario_id):
    usuario = db.session.get(Usuario, usuario_id)
    if usuario is None:
        abort(404)
    if usuario.id == current_user.id:
        flash("Não é permitido desativar sua própria conta.", "erro")
        return redirect(url_for("auth.usuarios"))
    if usuario.ativo and usuario.papel == "admin":
        admins_ativos = Usuario.query.filter_by(papel="admin", ativo=True).count()
        if admins_ativos <= 1:
            flash("O sistema precisa manter pelo menos um administrador ativo.", "erro")
            return redirect(url_for("auth.usuarios"))
    usuario.ativo = not usuario.ativo
    db.session.commit()
    flash("Usuário atualizado.", "sucesso")
    return redirect(url_for("auth.usuarios"))
