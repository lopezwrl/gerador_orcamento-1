"""
fornecedores_routes.py — cadastro de fornecedores e cotação manual.

Registrar em app.py:
    from orcatech.fornecedores_routes import fornecedores_bp
    app.register_blueprint(fornecedores_bp)
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from .auth import admin_required

from .models import db, Fornecedor, Cotacao
from .orcamento_service import (
    get_or_create_produto_busca,
    adicionar_item_ao_orcamento,
)

fornecedores_bp = Blueprint("fornecedores", __name__, url_prefix="/fornecedores")


def _parse_preco(texto):
    """Aceita '1234.56', '1.234,56' ou 'R$ 1.234,56'. Retorna float ou None."""
    s = "".join(c for c in str(texto or "") if c.isdigit() or c in ",.")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


@fornecedores_bp.route("/")
def listar():
    fornecedores = Fornecedor.query.order_by(Fornecedor.ativo.desc(), Fornecedor.nome).all()
    return render_template("fornecedores.html", fornecedores=fornecedores)


@fornecedores_bp.route("/novo", methods=["POST"])
@admin_required
def novo():
    nome = request.form.get("nome", "").strip()
    if not nome:
        flash("Informe o nome do fornecedor.", "erro")
        return redirect(url_for("fornecedores.listar"))
    if Fornecedor.query.filter(db.func.lower(Fornecedor.nome) == nome.lower()).first():
        flash(f'Já existe um fornecedor chamado "{nome}".', "erro")
        return redirect(url_for("fornecedores.listar"))

    tipo = request.form.get("tipo", "manual")
    db.session.add(Fornecedor(
        nome=nome,
        tipo=tipo if tipo in ("online", "manual") else "manual",
        site=request.form.get("site", "").strip() or None,
        contato=request.form.get("contato", "").strip() or None,
    ))
    db.session.commit()
    flash(f'Fornecedor "{nome}" cadastrado.', "sucesso")
    return redirect(url_for("fornecedores.listar"))


@fornecedores_bp.route("/<int:fornecedor_id>/editar", methods=["POST"])
@admin_required
def editar(fornecedor_id):
    f = Fornecedor.query.get_or_404(fornecedor_id)
    nome = request.form.get("nome", "").strip()
    if not nome:
        flash("O nome não pode ficar vazio.", "erro")
        return redirect(url_for("fornecedores.listar"))

    outro = Fornecedor.query.filter(
        db.func.lower(Fornecedor.nome) == nome.lower(), Fornecedor.id != f.id
    ).first()
    if outro:
        flash(f'Já existe outro fornecedor chamado "{nome}".', "erro")
        return redirect(url_for("fornecedores.listar"))

    tipo = request.form.get("tipo", f.tipo)
    f.nome = nome
    f.tipo = tipo if tipo in ("online", "manual") else f.tipo
    f.site = request.form.get("site", "").strip() or None
    f.contato = request.form.get("contato", "").strip() or None
    db.session.commit()
    flash("Fornecedor atualizado.", "sucesso")
    return redirect(url_for("fornecedores.listar"))


@fornecedores_bp.route("/<int:fornecedor_id>/ativo", methods=["POST"])
@admin_required
def alternar_ativo(fornecedor_id):
    f = Fornecedor.query.get_or_404(fornecedor_id)
    f.ativo = not f.ativo
    db.session.commit()
    flash(f'"{f.nome}" {"ativado" if f.ativo else "desativado"}.', "sucesso")
    return redirect(url_for("fornecedores.listar"))


@fornecedores_bp.route("/cotacao-manual", methods=["POST"])
def cotacao_manual():
    """Lança uma cotação recebida por fora (telefone, e-mail, loja física)
    e já coloca no carrinho ativo."""
    fornecedor = Fornecedor.query.get(request.form.get("fornecedor_id", type=int))
    produto_pesquisado = request.form.get("produto_busca", "").strip()
    nome = request.form.get("nome", "").strip() or produto_pesquisado
    preco = _parse_preco(request.form.get("preco"))
    frete = _parse_preco(request.form.get("frete"))
    quantidade = max(1, request.form.get("quantidade", 1, type=int) or 1)

    if not fornecedor or not fornecedor.ativo:
        flash("Escolha um fornecedor ativo.", "erro")
        return redirect(url_for("fornecedores.listar"))
    if not produto_pesquisado or not preco or preco <= 0:
        flash("Informe o produto e um preço válido.", "erro")
        return redirect(url_for("fornecedores.listar"))

    produto_busca = get_or_create_produto_busca(produto_pesquisado)
    cotacao = Cotacao(
        produto_busca_id=produto_busca.id,
        fornecedor_id=fornecedor.id,
        nome_produto=nome[:255],
        preco=preco,
        link=request.form.get("link", "").strip() or None,
        frete=frete,
        prazo_entrega=request.form.get("prazo_entrega", "").strip()[:80] or None,
        forma_pagamento=request.form.get("forma_pagamento", "").strip()[:120] or None,
        origem="manual",
    )
    db.session.add(cotacao)
    db.session.flush()
    adicionar_item_ao_orcamento(produto_busca, cotacao, quantidade=quantidade)

    flash(f'Cotação de "{fornecedor.nome}" adicionada ao orçamento.', "sucesso")
    return redirect(url_for("fornecedores.listar"))
