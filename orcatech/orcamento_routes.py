"""
orcamento_routes.py — rotas do carrinho de orçamento (montagem multi-produto).

Registrar em app.py:
    from orcatech.orcamento_routes import orcamento_bp
    app.register_blueprint(orcamento_bp)
"""

from flask import Blueprint, abort, jsonify, render_template, request, redirect, url_for, send_file, flash
import os
from flask_login import current_user
from sqlalchemy.orm import joinedload

from .auth import owner_or_admin
from .models import db, Orcamento, OrcamentoItem
from .orcamento_service import (
    get_or_create_produto_busca,
    registrar_cotacao,
    get_orcamento_ativo,
    adicionar_item_ao_orcamento,
)
from .gerar_pdf_orcamento import gerar_pdf_orcamento

orcamento_bp = Blueprint("orcamento", __name__, url_prefix="/orcamento")


@orcamento_bp.app_context_processor
def injetar_carrinho_count():
    """Disponibiliza `carrinho_count` (nº de itens do rascunho) em todos os templates."""
    orc = get_orcamento_ativo(criar_se_nao_existir=False)
    return {"carrinho_count": len(orc.itens) if orc else 0}


def _item_do_usuario(item_id):
    item = (
        OrcamentoItem.query.options(joinedload(OrcamentoItem.orcamento))
        .filter_by(id=item_id)
        .first_or_404()
    )
    owner_or_admin(item.orcamento)
    return item


def _quer_json():
    """True quando a requisição é AJAX/fetch, independentemente do header exato enviado."""
    x_requested_with = (request.headers.get("X-Requested-With") or "").strip().lower()
    return x_requested_with in {"fetch", "xmlhttprequest"} or request.is_json


@orcamento_bp.route("/adicionar", methods=["POST"])
def adicionar():
    """
    Chamado pelo botão 'Adicionar ao orçamento' de cada card em resultados.html.
    Espera no form: produto_busca (termo pesquisado), nome, preco, site,
    link, imagem, quantidade (opcional, default 1).
    """
    produto_pesquisado = request.form.get("produto_busca", "").strip()
    nome = request.form.get("nome", "").strip()
    site = request.form.get("site", "").strip()
    link = request.form.get("link") or None
    imagem = request.form.get("imagem") or None
    try:
        preco = float(request.form.get("preco", "0"))
    except ValueError:
        preco = 0.0
    try:
        quantidade = max(1, int(request.form.get("quantidade", "1")))
    except ValueError:
        quantidade = 1

    if not produto_pesquisado or not nome or preco <= 0:
        if _quer_json():
            return jsonify(ok=False, msg="Não foi possível adicionar esse item ao orçamento."), 400
        flash("Não foi possível adicionar esse item ao orçamento.", "erro")
        return redirect(request.referrer or url_for("home"))

    produto_busca = get_or_create_produto_busca(produto_pesquisado)
    cotacao = registrar_cotacao(
        produto_busca, nome_produto=nome, preco=preco, site=site,
        link=link, imagem=imagem, origem="scraping",
    )
    orcamento, item = adicionar_item_ao_orcamento(produto_busca, cotacao, quantidade=quantidade)

    if _quer_json():
        return jsonify(ok=True, quantidade=item.quantidade, count=len(orcamento.itens))

    flash(f'"{nome[:40]}" adicionado ao orçamento.', "sucesso")
    return redirect(request.referrer or url_for("orcamento.carrinho"))


@orcamento_bp.route("/carrinho")
def carrinho():
    orcamento = get_orcamento_ativo(criar_se_nao_existir=False)
    return render_template("carrinho.html", orcamento=orcamento)


@orcamento_bp.route("/item/<int:item_id>/quantidade", methods=["POST"])
def atualizar_quantidade(item_id):
    item = _item_do_usuario(item_id)
    if item.orcamento.status != "rascunho":
        abort(403)
    try:
        nova_qtd = int(request.form.get("quantidade", item.quantidade))
    except ValueError:
        nova_qtd = item.quantidade

    if nova_qtd <= 0:
        db.session.delete(item)
    else:
        item.quantidade = nova_qtd
    db.session.commit()
    return redirect(url_for("orcamento.carrinho"))


@orcamento_bp.route("/item/<int:item_id>/remover", methods=["POST"])
def remover_item(item_id):
    item = _item_do_usuario(item_id)
    if item.orcamento.status != "rascunho":
        abort(403)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for("orcamento.carrinho"))


@orcamento_bp.route("/finalizar", methods=["POST"])
def finalizar():
    orcamento = get_orcamento_ativo(criar_se_nao_existir=False)
    if not orcamento or not orcamento.itens:
        flash("Adicione pelo menos um item antes de finalizar.", "erro")
        return redirect(url_for("orcamento.carrinho"))

    orcamento.solicitante = request.form.get("solicitante", "").strip() or current_user.nome
    orcamento.observacoes = request.form.get("observacoes", "").strip()
    orcamento.condicoes_comerciais = request.form.get("condicoes_comerciais", "").strip()
    orcamento.status = "aguardando_aprovacao"
    db.session.commit()

    return redirect(url_for("orcamento.pdf", orcamento_id=orcamento.id))


@orcamento_bp.route("/pdf/<int:orcamento_id>")
def pdf(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    owner_or_admin(orcamento)
    caminho_pdf = gerar_pdf_orcamento(orcamento)
    return send_file(
        caminho_pdf, as_attachment=True,
        download_name=os.path.basename(caminho_pdf),
        mimetype="application/pdf",
    )