from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .models import (
    AlertaPreco,
    Monitoramento,
    PrecoHistorico,
    db,
)
from .monitoramento_service import modelos_compativeis
from .orcamento_service import get_or_create_fornecedor, get_or_create_produto_busca


monitoramento_bp = Blueprint("monitoramento", __name__)
_LOJAS = {
    "Mercado Livre": "mercadolivre",
    "KaBuM": "kabum",
    "Amazon": "amazon",
    "Terabyte": "terabyte",
    "Americanas": "americanas",
    "iBytes": "ibyte",
    "Gshield": "gshield",
    "AliExpress": "aliexpress",
}
_VALOR_MAXIMO = Decimal("9999999999.99")


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _decimal_formulario(campo):
    valor = (request.form.get(campo) or "").strip().replace(",", ".")
    if not valor:
        return None
    try:
        numero = Decimal(valor)
    except InvalidOperation as exc:
        raise ValueError(f"O campo {campo.replace('_', ' ')} deve ser numérico.") from exc
    if not numero.is_finite():
        raise ValueError(f"O campo {campo.replace('_', ' ')} deve ser numérico.")
    try:
        numero = numero.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"O campo {campo.replace('_', ' ')} está fora do limite.") from exc
    if numero > _VALOR_MAXIMO:
        raise ValueError(f"O campo {campo.replace('_', ' ')} está fora do limite.")
    return numero


def _url_valida(url):
    if not url:
        return None
    if len(url) > 500:
        raise ValueError("O link do produto excede o limite permitido.")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("O link do produto deve começar com http:// ou https://.")
    return url


@monitoramento_bp.route("/monitoramentos", methods=["GET"])
@login_required
def listar():
    monitoramentos = (
        Monitoramento.query.filter_by(usuario_id=current_user.id)
        .order_by(Monitoramento.criado_em.desc())
        .all()
    )
    alertas = (
        AlertaPreco.query.join(AlertaPreco.monitoramento)
        .filter(Monitoramento.usuario_id == current_user.id)
        .order_by(AlertaPreco.lido_em.is_(None).desc(), AlertaPreco.criado_em.desc())
        .limit(100)
        .all()
    )
    limite = current_app.config["MONITORAMENTOS_LIMITE_USUARIO"]
    graficos = {}
    desde = _utcnow().date() - timedelta(days=90)
    for monitoramento in monitoramentos:
        historicos = (
            PrecoHistorico.query.filter_by(fornecedor_id=monitoramento.fornecedor_id)
            .filter(PrecoHistorico.dia >= desde)
            .order_by(PrecoHistorico.dia)
            .all()
        )
        por_dia = defaultdict(list)
        for historico in historicos:
            if modelos_compativeis(monitoramento.nome_modelo, historico.nome_produto):
                por_dia[historico.dia.isoformat()].append(float(historico.preco))
        graficos[monitoramento.id] = {
            "labels": sorted(por_dia),
            "minimos": [
                min(por_dia[dia]) for dia in sorted(por_dia)
            ],
            "medias": [
                sum(por_dia[dia]) / len(por_dia[dia]) for dia in sorted(por_dia)
            ],
        }
    return render_template(
        "monitoramentos.html",
        monitoramentos=monitoramentos,
        alertas=alertas,
        limite=limite,
        graficos=graficos,
    )


@monitoramento_bp.route("/monitoramentos/criar", methods=["POST"])
@login_required
def criar():
    try:
        termo_busca = (request.form.get("termo_busca") or "").strip()
        nome_modelo = (request.form.get("nome_modelo") or "").strip()
        loja = (request.form.get("fornecedor") or "").strip()
        preco_referencia = _decimal_formulario("preco_referencia")
        gatilho_percentual = _decimal_formulario("gatilho_percentual")
        gatilho_valor = _decimal_formulario("gatilho_valor")
        link = _url_valida((request.form.get("link") or "").strip())

        if not termo_busca or len(termo_busca) > 255:
            raise ValueError("Informe um termo de busca com até 255 caracteres.")
        if not nome_modelo or len(nome_modelo) > 255:
            raise ValueError("Informe o nome do produto com até 255 caracteres.")
        if loja not in _LOJAS:
            raise ValueError("A loja selecionada não é válida.")
        if preco_referencia is None or not preco_referencia.is_finite() or preco_referencia <= 0:
            raise ValueError("O preço de referência deve ser maior que zero.")
        if (gatilho_percentual is None) == (gatilho_valor is None):
            raise ValueError("Informe exatamente um gatilho: percentual ou valor em reais.")
        if gatilho_percentual is not None and not Decimal("0") < gatilho_percentual <= Decimal("100"):
            raise ValueError("O percentual deve ser maior que 0 e no máximo 100.")
        if gatilho_valor is not None and gatilho_valor <= 0:
            raise ValueError("O valor do gatilho deve ser maior que zero.")

        produto_busca = get_or_create_produto_busca(termo_busca)
        fornecedor = get_or_create_fornecedor(loja)
        existente = Monitoramento.query.filter_by(
            usuario_id=current_user.id,
            produto_busca_id=produto_busca.id,
            fornecedor_id=fornecedor.id,
            nome_modelo=nome_modelo,
        ).first()
        if existente:
            if not existente.ativo:
                existente.ativo = True
                existente.link = link
                existente.preco_referencia = preco_referencia
                existente.gatilho_percentual = gatilho_percentual
                existente.gatilho_valor = gatilho_valor
                existente.proxima_verificacao = _utcnow()
                db.session.commit()
                flash("Monitoramento reativado com os novos parâmetros.", "sucesso")
                return redirect(url_for("monitoramento.listar"))
            flash("Este produto já está sendo monitorado.", "sucesso")
            return redirect(url_for("monitoramento.listar"))

        ativos = Monitoramento.query.filter_by(
            usuario_id=current_user.id, ativo=True
        ).count()
        limite = current_app.config["MONITORAMENTOS_LIMITE_USUARIO"]
        if ativos >= limite:
            raise ValueError(f"Você atingiu o limite de {limite} monitoramentos ativos.")

        monitoramento = Monitoramento(
            usuario_id=current_user.id,
            produto_busca_id=produto_busca.id,
            fornecedor_id=fornecedor.id,
            loja=_LOJAS[loja],
            nome_modelo=nome_modelo,
            link=link,
            preco_referencia=preco_referencia,
            gatilho_percentual=gatilho_percentual,
            gatilho_valor=gatilho_valor,
            proxima_verificacao=_utcnow(),
        )
        db.session.add(monitoramento)
        db.session.commit()
        flash("Monitoramento de preço criado.", "sucesso")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "erro")
    return redirect(url_for("monitoramento.listar"))


@monitoramento_bp.route("/monitoramentos/<int:monitoramento_id>/desativar", methods=["POST"])
@login_required
def desativar(monitoramento_id):
    monitoramento = db.session.get(Monitoramento, monitoramento_id)
    if not monitoramento or monitoramento.usuario_id != current_user.id:
        abort(404)
    monitoramento.ativo = False
    db.session.commit()
    flash("Monitoramento desativado.", "sucesso")
    return redirect(url_for("monitoramento.listar"))


@monitoramento_bp.route("/monitoramentos/alertas/<int>alerta_id>/ler", methods=["POST"])
@login_required
def marcar_como_lido(alerta_id):
    alerta = (
        AlertaPreco.query.join(AlertaPreco.monitoramento)
        .filter(
            AlertaPreco.id == alerta_id,
            Monitoramento.usuario_id == current_user.id,
        )
        .first()
    )
    if not alerta:
        abort(404)
    if alerta.lido_em is None:
        alerta.lido_em = _utcnow()
        db.session.commit()
    return redirect(url_for("monitoramento.listar"))
