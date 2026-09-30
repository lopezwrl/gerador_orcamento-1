"""
orcamento_routes.py — rotas do carrinho de orçamento (montagem multi-produto).

Registrar em app.py:
    from orcatech.orcamento_routes import orcamento_bp
    app.register_blueprint(orcamento_bp)
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import os
import secrets
from flask import Blueprint, abort, current_app, jsonify, render_template, request, redirect, url_for, send_file, flash
from flask_login import current_user, login_required
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload
from urllib.parse import urlencode

from .auth import approver_required, owner_or_admin
from .empresarial_service import (
    expressao_total_orcamento,
    funcionalidade_empresarial_ativa,
    usuario_pode_aprovar,
    validar_unidade_orcamento,
)
from .models import (
    Aprovacao,
    CentroCusto,
    Cotacao,
    Departamento,
    EnvioEmail,
    db,
    Orcamento,
    OrcamentoItem,
)
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
from .compartilhamento_routes import STATUS_COMPARTILHAVEIS
from .email_service import (
    enfileirar_email,
    notificar_aprovadores,
    notificar_solicitante,
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


def _quer_json():
    """True quando a requisição é AJAX/fetch, independentemente do header exato enviado."""
    x_requested_with = (request.headers.get("X-Requested-With") or "").strip().lower()
    return x_requested_with in {"fetch", "xmlhttprequest"} or request.is_json


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
@login_required
def carrinho():
    orcamento = get_orcamento_ativo(criar_se_nao_existir=False)
    return render_template(
        "carrinho.html",
        orcamento=orcamento,
        empresarial_ativa=funcionalidade_empresarial_ativa(),
        departamentos=Departamento.query.order_by(Departamento.nome).all(),
        centros_custo=CentroCusto.query.order_by(CentroCusto.nome).all(),
    )


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

    if funcionalidade_empresarial_ativa():
        departamento_id = request.form.get("departamento_id", type=int)
        centro_custo_id = request.form.get("centro_custo_id", type=int)
        orcamento.departamento_id = departamento_id
        orcamento.centro_custo_id = centro_custo_id
        try:
            validar_unidade_orcamento(
                current_user, departamento_id, centro_custo_id, orcamento
            )
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "erro")
            return redirect(url_for("orcamento.carrinho"))

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

    notificar_aprovadores(current_app._get_current_object(), orcamento.id)
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
    pode_aprovar_orcamento = (
        orcamento.status == "aguardando_aprovacao"
        and usuario_pode_aprovar(current_user, orcamento)
    )
    pode_emitir_pedido = (
        funcionalidade_empresarial_ativa()
        and orcamento.status == "aprovado"
        and current_user.papel in {"admin", "comprador"}
    )
    permitido = (
        current_user.papel == "admin"
        or orcamento.usuario_id == current_user.id
        or pode_aprovar_orcamento
        or (
            funcionalidade_empresarial_ativa()
            and current_user.papel == "comprador"
            and orcamento.status in {"aprovado", "compra_realizada"}
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
        not funcionalidade_empresarial_ativa()
        and orcamento.status == "aprovado"
        and pode_transicionar("aprovado", "compra_realizada", current_user, orcamento)
    )
    pode_renovar = (
        orcamento.status == "aguardando_aprovacao"
        and orcamento.expirado
        and (current_user.papel == "admin" or orcamento.usuario_id == current_user.id)
    )
    pode_gerenciar_link = (
        current_user.papel == "admin" or orcamento.usuario_id == current_user.id
    )
    link_ativo = (
        bool(orcamento.share_token)
        and not orcamento.share_revogado
        and orcamento.share_expira_em is not None
        and orcamento.share_expira_em > datetime.now(timezone.utc).replace(tzinfo=None)
    )
    link_publico = None
    whatsapp_url = None
    if link_ativo and pode_gerenciar_link:
        link_publico = (
            current_app.config["APP_BASE_URL"]
            + url_for("compartilhamento.publico", token=orcamento.share_token)
        )
        mensagem = f"Orçamento {orcamento.numero}: {link_publico}"
        whatsapp_url = "https://wa.me/?" + urlencode({"text": mensagem})
    return render_template(
        "orcamento_detalhe.html",
        orcamento=orcamento,
        pode_decidir=pode_decidir,
        pode_reabrir=pode_reabrir,
        pode_marcar_compra=pode_marcar_compra,
        pode_emitir_pedido=pode_emitir_pedido,
        pode_renovar=pode_renovar,
        pode_gerenciar_link=pode_gerenciar_link,
        pode_compartilhar=orcamento.status in STATUS_COMPARTILHAVEIS,
        link_ativo=link_ativo,
        link_publico=link_publico,
        whatsapp_url=whatsapp_url,
        pode_enviar_email=pode_gerenciar_link,
        envios_email=(
            EnvioEmail.query.filter_by(orcamento_id=orcamento.id)
            .order_by(EnvioEmail.criado_em.desc())
            .limit(10)
            .all()
            if pode_gerenciar_link
            else []
        ),
        pedidos_compra=orcamento.pedidos_compra if funcionalidade_empresarial_ativa() else [],
    )


@orcamento_bp.route("/<int:orcamento_id>/decisao", methods=["POST"])
@approver_required
def decidir(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    if not usuario_pode_aprovar(current_user, orcamento):
        abort(404)
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
    notificar_solicitante(
        current_app._get_current_object(), orcamento.id, current_user.id
    )
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
        orcamento.share_revogado = True
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
    if funcionalidade_empresarial_ativa():
        abort(404)
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


def _gerar_link_compartilhamento(orcamento):
    if orcamento.status not in STATUS_COMPARTILHAVEIS:
        abort(403)
    orcamento.share_token = secrets.token_urlsafe(32)
    orcamento.share_expira_em = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        days=current_app.config["LINK_COMPARTILHAMENTO_DIAS"]
    )
    orcamento.share_revogado = False


@orcamento_bp.route("/<int:orcamento_id>/compartilhar", methods=["POST"])
@login_required
def gerar_link(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    owner_or_admin(orcamento)
    if orcamento.share_token and not orcamento.share_revogado and orcamento.share_expira_em:
        if orcamento.share_expira_em > datetime.now(timezone.utc).replace(tzinfo=None):
            flash("Já existe um link público ativo. Use regenerar para trocá-lo.", "erro")
            return redirect(url_for("orcamento.detalhe", orcamento_id=orcamento.id))
    _gerar_link_compartilhamento(orcamento)
    db.session.commit()
    flash("Link público criado.", "sucesso")
    return redirect(url_for("orcamento.detalhe", orcamento_id=orcamento.id))


@orcamento_bp.route("/<int:orcamento_id>/compartilhar/regenerar", methods=["POST"])
@login_required
def regenerar_link(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    owner_or_admin(orcamento)
    _gerar_link_compartilhamento(orcamento)
    db.session.commit()
    flash("Link público regenerado; o link anterior foi invalidado.", "sucesso")
    return redirect(url_for("orcamento.detalhe", orcamento_id=orcamento.id))


@orcamento_bp.route("/<int:orcamento_id>/compartilhar/revogar", methods=["POST"])
@login_required
def revogar_link(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    owner_or_admin(orcamento)
    if not orcamento.share_token:
        abort(404)
    orcamento.share_revogado = True
    db.session.commit()
    flash("Link público revogado.", "sucesso")
    return redirect(url_for("orcamento.detalhe", orcamento_id=orcamento.id))


@orcamento_bp.route("/<int:orcamento_id>/email", methods=["POST"])
@login_required
def enviar_email(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    owner_or_admin(orcamento)
    destinatario = request.form.get("destinatario", "").strip()
    try:
        enfileirar_email(
            current_app._get_current_object(),
            orcamento.id,
            current_user.id,
            destinatario,
            anexar_pdf=True,
        )
    except ValueError as exc:
        flash(str(exc), "erro")
        return redirect(url_for("orcamento.detalhe", orcamento_id=orcamento.id))
    except RuntimeError as exc:
        flash(str(exc), "erro")
        return redirect(url_for("orcamento.detalhe", orcamento_id=orcamento.id))
    flash("E-mail enfileirado para envio em segundo plano.", "sucesso")
    return redirect(url_for("orcamento.detalhe", orcamento_id=orcamento.id))


@aprovacoes_bp.route("/aprovacoes")
@approver_required
def fila():
    busca = request.args.get("q", "").strip()
    query = Orcamento.query.filter_by(status="aguardando_aprovacao")
    if funcionalidade_empresarial_ativa():
        total = expressao_total_orcamento()
        limite = Decimal(current_app.config["ALCADA_APROVACAO_LIMITE"])
        query = query.outerjoin(OrcamentoItem).outerjoin(
            Cotacao, OrcamentoItem.cotacao_escolhida_id == Cotacao.id
        ).group_by(Orcamento.id)
        if current_user.papel == "aprovador":
            if current_user.departamento_id is None:
                query = query.filter(Orcamento.id == -1)
            else:
                query = query.filter(
                    Orcamento.departamento_id == current_user.departamento_id,
                    Orcamento.usuario_id != current_user.id,
                ).having(total <= limite)
        elif current_app.config.get("ADMIN_PODE_AUTOAPROVAR", False):
            query = query.having(
                or_(
                    total > limite,
                    and_(
                        Orcamento.usuario_id == current_user.id,
                        total <= limite,
                    ),
                )
            )
        else:
            query = query.filter(Orcamento.usuario_id != current_user.id).having(
                total > limite
            )
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
        query = query.filter(
            Orcamento.criado_em < datetime.combine(ate + timedelta(days=1), time.min)
        )
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