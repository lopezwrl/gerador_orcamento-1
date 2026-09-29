"""
orcamento_routes.py — rotas do carrinho de orçamento (montagem multi-produto).

Registrar em app.py:
    from orcatech.orcamento_routes import orcamento_bp
    app.register_blueprint(orcamento_bp)
"""

from datetime import date, datetime, time, timezone
import os
from flask import Blueprint, abort, render_template, request, redirect, url_for, send_file, flash
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from .auth import approver_required, owner_or_admin
from .models import Aprovacao, db, Orcamento, OrcamentoItem
from .orcamento_service import (
    get_or_create_produto_busca,
    registrar_cotacao,
    get_orcamento_ativo,
    adicionar_item_ao_orcamento,
)
from .gerar_pdf_orcamento import gerar_pdf_orcamento
from .orcamento_workflow import (
    ErroWorkflow,
    congelar_precos,
    pode_transicionar,
    transicionar,
    validade_padrao,
)

orcamento_bp = Blueprint("orcamento", __name__, url_prefix="/orcamento")
aprovacoes_bp = Blueprint("aprovacoes", __name__)


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


@orcamento_bp.route("/adicionar", methods=["POST"])
@login_required
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
@login_required
def carrinho():
    orcamento = get_orcamento_ativo(criar_se_nao_existir=False)
    return render_template("carrinho.html", orcamento=orcamento)


@orcamento_bp.route("/item/<int:item_id>/quantidade", methods=["POST"])
@login_required
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
@login_required
def remover_item(item_id):
    item = _item_do_usuario(item_id)
    if item.orcamento.status != "rascunho":
        abort(403)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for("orcamento.carrinho"))


@orcamento_bp.route("/finalizar", methods=["POST"])
@login_required
def finalizar():
    orcamento = get_orcamento_ativo(criar_se_nao_existir=False)
    if not orcamento or not orcamento.itens:
        flash("Adicione pelo menos um item antes de finalizar.", "erro")
        return redirect(url_for("orcamento.carrinho"))
    owner_or_admin(orcamento)
    if orcamento.status != "rascunho":
        abort(403)

    orcamento.solicitante = request.form.get("solicitante", "").strip() or current_user.nome
    orcamento.observacoes = request.form.get("observacoes", "").strip()
    orcamento.condicoes_comerciais = request.form.get("condicoes_comerciais", "").strip()
    orcamento.validade = orcamento.validade or validade_padrao()
    comentario = request.form.get("comentario", "").strip() or "Enviado para aprovação."
    try:
        congelar_precos(orcamento)
        transicionar(orcamento, "em_cotacao", current_user)
        transicionar(orcamento, "aguardando_aprovacao", current_user, comentario)
        db.session.commit()
    except ErroWorkflow as exc:
        db.session.rollback()
        flash(str(exc), "erro")
        return redirect(url_for("orcamento.carrinho"))

    return redirect(url_for("orcamento.detalhe", orcamento_id=orcamento.id))


@orcamento_bp.route("/pdf/<int:orcamento_id>")
@login_required
def pdf(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    owner_or_admin(orcamento)
    caminho_pdf = gerar_pdf_orcamento(orcamento)
    return send_file(
        caminho_pdf, as_attachment=True,
        download_name=os.path.basename(caminho_pdf),
        mimetype="application/pdf",
    )


@orcamento_bp.route("/<int:orcamento_id>")
@login_required
def detalhe(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    permitido = (
        current_user.papel == "admin"
        or orcamento.usuario_id == current_user.id
        or (
            orcamento.status == "aguardando_aprovacao"
            and current_user.papel == "aprovador"
        )
    )
    if not permitido:
        abort(404)
    pode_decidir = (
        orcamento.status == "aguardando_aprovacao"
        and (
            pode_transicionar("aguardando_aprovacao", "aprovado", current_user, orcamento)
            or pode_transicionar("aguardando_aprovacao", "reprovado", current_user, orcamento)
        )
    )
    pode_reabrir = (
        orcamento.status == "reprovado"
        and pode_transicionar("reprovado", "rascunho", current_user, orcamento)
    )
    pode_marcar_compra = (
        orcamento.status == "aprovado"
        and pode_transicionar("aprovado", "compra_realizada", current_user, orcamento)
    )
    pode_renovar = (
        orcamento.status == "aguardando_aprovacao"
        and orcamento.expirado
        and (current_user.papel == "admin" or orcamento.usuario_id == current_user.id)
    )
    return render_template(
        "orcamento_detalhe.html",
        orcamento=orcamento,
        pode_decidir=pode_decidir,
        pode_reabrir=pode_reabrir,
        pode_marcar_compra=pode_marcar_compra,
        pode_renovar=pode_renovar,
    )


@orcamento_bp.route("/<int:orcamento_id>/decisao", methods=["POST"])
@approver_required
def decidir(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    decisao = request.form.get("decisao", "")
    comentario = request.form.get("comentario", "").strip()
    if decisao not in {"aprovado", "reprovado"}:
        abort(400)
    try:
        transicionar(orcamento, decisao, current_user, comentario)
        db.session.add(
            Aprovacao(
                orcamento_id=orcamento.id,
                usuario_id=current_user.id,
                decisao=decisao,
                comentario=comentario or None,
            )
        )
        db.session.commit()
    except ErroWorkflow as exc:
        db.session.rollback()
        flash(str(exc), "erro")
        return redirect(url_for("orcamento.detalhe", orcamento_id=orcamento.id))
    flash(
        "Orçamento aprovado." if decisao == "aprovado" else "Orçamento reprovado.",
        "sucesso",
    )
    return redirect(url_for("orcamento.detalhe", orcamento_id=orcamento.id))


@orcamento_bp.route("/<int:orcamento_id>/reabrir", methods=["POST"])
@login_required
def reabrir(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    owner_or_admin(orcamento)
    try:
        transicionar(
            orcamento,
            "rascunho",
            current_user,
            request.form.get("comentario", "").strip() or "Orçamento reaberto.",
        )
        orcamento.validade = validade_padrao()
        for item in orcamento.itens:
            item.snapshot_nome_produto = None
            item.snapshot_fornecedor_nome = None
            item.snapshot_preco_unit = None
            item.snapshot_frete = None
            item.snapshot_link = None
        db.session.commit()
    except ErroWorkflow as exc:
        db.session.rollback()
        flash(str(exc), "erro")
    return redirect(url_for("orcamento.detalhe", orcamento_id=orcamento.id))


@orcamento_bp.route("/<int:orcamento_id>/renovar-validade", methods=["POST"])
@login_required
def renovar_validade(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    owner_or_admin(orcamento)
    if orcamento.status != "aguardando_aprovacao" or not orcamento.expirado:
        abort(403)
    orcamento.validade = validade_padrao()
    db.session.commit()
    flash("Validade renovada por mais dias.", "sucesso")
    return redirect(url_for("orcamento.detalhe", orcamento_id=orcamento.id))


@orcamento_bp.route("/<int:orcamento_id>/compra-realizada", methods=["POST"])
@login_required
def marcar_compra_realizada(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    owner_or_admin(orcamento)
    try:
        transicionar(
            orcamento,
            "compra_realizada",
            current_user,
            request.form.get("comentario", "").strip() or "Compra realizada.",
        )
        db.session.commit()
    except ErroWorkflow as exc:
        db.session.rollback()
        flash(str(exc), "erro")
    return redirect(url_for("orcamento.detalhe", orcamento_id=orcamento.id))


@aprovacoes_bp.route("/aprovacoes")
@approver_required
def fila():
    busca = request.args.get("q", "").strip()
    query = Orcamento.query.filter_by(status="aguardando_aprovacao")
    if busca:
        query = query.filter(
            or_(
                Orcamento.numero.ilike(f"%{busca}%"),
                Orcamento.solicitante.ilike(f"%{busca}%"),
            )
        )
    desde_texto = request.args.get("desde", "").strip()
    ate_texto = request.args.get("ate", "").strip()
    try:
        desde = date.fromisoformat(desde_texto) if desde_texto else None
        ate = date.fromisoformat(ate_texto) if ate_texto else None
    except ValueError:
        abort(400, description="Informe datas válidas para filtrar a fila.")
    if desde and ate and desde > ate:
        abort(400, description="A data inicial não pode ser posterior à data final.")
    if desde:
        query = query.filter(Orcamento.criado_em >= datetime.combine(desde, time.min))
    if ate:
        query = query.filter(Orcamento.criado_em < datetime.combine(ate, time.max))
    pagina_numero = request.args.get("page", 1, type=int)
    pagina = query.order_by(Orcamento.criado_em.asc()).paginate(
        page=max(1, pagina_numero), per_page=15, error_out=False
    )
    return render_template(
        "aprovacoes.html",
        pagina=pagina,
        busca=busca,
        desde=desde_texto,
        ate=ate_texto,
        agora=datetime.now(timezone.utc).replace(tzinfo=None),
    )