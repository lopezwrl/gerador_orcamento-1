"""
orcamento_routes.py — rotas do carrinho de orçamento (montagem multi-produto).

Registrar em app.py:
    from orcamento_routes import orcamento_bp
    app.register_blueprint(orcamento_bp)
"""

from flask import Blueprint, render_template, request, redirect, url_for, send_file, flash
import os

from models import db, Orcamento, OrcamentoItem
from orcamento_service import (
    get_or_create_produto_busca,
    registrar_cotacao,
    get_orcamento_ativo,
    adicionar_item_ao_orcamento,
    limpar_orcamento_ativo,
)
from gerar_pdf_orcamento import gerar_pdf_orcamento

orcamento_bp = Blueprint("orcamento", __name__, url_prefix="/orcamento")


@orcamento_bp.app_context_processor
def injetar_carrinho_count():
    """Disponibiliza `carrinho_count` (nº de itens do rascunho) em todos os templates."""
    try:
        orc = get_orcamento_ativo(criar_se_nao_existir=False)
        return {"carrinho_count": len(orc.itens) if orc else 0}
    except Exception:
        return {"carrinho_count": 0}


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
        flash("Não foi possível adicionar esse item ao orçamento.", "erro")
        return redirect(request.referrer or url_for("home"))

    produto_busca = get_or_create_produto_busca(produto_pesquisado)
    cotacao = registrar_cotacao(
        produto_busca, nome_produto=nome, preco=preco, site=site,
        link=link, imagem=imagem, origem="scraping",
    )
    adicionar_item_ao_orcamento(produto_busca, cotacao, quantidade=quantidade)

    flash(f'"{nome[:40]}" adicionado ao orçamento.', "sucesso")
    return redirect(request.referrer or url_for("orcamento.carrinho"))


@orcamento_bp.route("/carrinho")
def carrinho():
    orcamento = get_orcamento_ativo(criar_se_nao_existir=False)
    return render_template("carrinho.html", orcamento=orcamento)


@orcamento_bp.route("/item/<int:item_id>/quantidade", methods=["POST"])
def atualizar_quantidade(item_id):
    item = OrcamentoItem.query.get_or_404(item_id)
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
    item = OrcamentoItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for("orcamento.carrinho"))


@orcamento_bp.route("/finalizar", methods=["POST"])
def finalizar():
    orcamento = get_orcamento_ativo(criar_se_nao_existir=False)
    if not orcamento or not orcamento.itens:
        flash("Adicione pelo menos um item antes de finalizar.", "erro")
        return redirect(url_for("orcamento.carrinho"))

    orcamento.solicitante = request.form.get("solicitante", "").strip()
    orcamento.observacoes = request.form.get("observacoes", "").strip()
    orcamento.condicoes_comerciais = request.form.get("condicoes_comerciais", "").strip()
    orcamento.status = "aguardando_aprovacao"
    db.session.commit()

    limpar_orcamento_ativo()
    return redirect(url_for("orcamento.pdf", orcamento_id=orcamento.id))


@orcamento_bp.route("/pdf/<int:orcamento_id>")
def pdf(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    caminho_pdf = gerar_pdf_orcamento(orcamento)
    return send_file(
        caminho_pdf, as_attachment=True,
        download_name=os.path.basename(caminho_pdf),
        mimetype="application/pdf",
    )