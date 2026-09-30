import csv
import io
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import os

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from .auth import admin_required, comprador_required
from .empresarial_service import (
    emitir_pedidos_compra,
    expressao_total_orcamento,
    funcionalidade_empresarial_ativa,
)
from .gerar_pdf_pedido_compra import gerar_pdf_pedido_compra
from .models import (
    CentroCusto,
    Cotacao,
    Departamento,
    Orcamento,
    OrcamentoItem,
    PedidoCompra,
    db,
)

empresarial_bp = Blueprint("empresarial", __name__, url_prefix="/empresarial")

_TRANSICOES_PEDIDO = {
    "emitido": {"enviado", "cancelado"},
    "enviado": {"recebido", "cancelado"},
    "recebido": set(),
    "cancelado": set(),
}
_STATUS_COMPROMETIDOS = ("aguardando_aprovacao", "aprovado", "compra_realizada")


@empresarial_bp.before_request
def exigir_funcionalidade_ativa():
    if not funcionalidade_empresarial_ativa():
        abort(404)


def _limite_monetario(valor):
    texto = (valor or "").strip().replace("R$", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif texto.count(".") > 1 or (
        "." in texto and len(texto.rsplit(".", 1)[1]) == 3
    ):
        texto = texto.replace(".", "")
    try:
        numero = Decimal(texto).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError("Informe um limite monetário válido.") from None
    if not numero.is_finite() or numero <= 0:
        raise ValueError("O limite monetário deve ser maior que zero.")
    if numero > Decimal("9999999999.99"):
        raise ValueError("O limite monetário não pode ultrapassar R$ 9.999.999.999,99.")
    return numero


def _codigo_valido(valor):
    codigo = (valor or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9._-]{1,30}", codigo):
        raise ValueError("Use um código de até 30 caracteres: letras, números, ponto, _ ou -.")
    return codigo


@empresarial_bp.route("/estrutura", methods=["GET", "POST"])
@admin_required
def estrutura():
    if request.method == "POST":
        acao = request.form.get("acao")
        try:
            if acao == "departamento":
                codigo = _codigo_valido(request.form.get("codigo"))
                nome = request.form.get("nome", "").strip()
                if not nome or len(nome) > 120:
                    raise ValueError("Informe um nome de departamento com até 120 caracteres.")
                if Departamento.query.filter(
                    func.lower(Departamento.codigo) == codigo.lower()
                ).first() or Departamento.query.filter(
                    func.lower(Departamento.nome) == nome.lower()
                ).first():
                    raise ValueError("Já existe um departamento com esse código ou nome.")
                db.session.add(Departamento(codigo=codigo, nome=nome))
            elif acao == "centro_custo":
                codigo = _codigo_valido(request.form.get("codigo"))
                nome = request.form.get("nome", "").strip()
                departamento_id = request.form.get("departamento_id", type=int)
                if not nome or len(nome) > 120:
                    raise ValueError("Informe um nome de centro de custo com até 120 caracteres.")
                if db.session.get(Departamento, departamento_id) is None:
                    raise ValueError("Selecione um departamento válido.")
                if CentroCusto.query.filter_by(
                    departamento_id=departamento_id, codigo=codigo
                ).first():
                    raise ValueError("Esse código já está em uso no departamento.")
                limite = _limite_monetario(request.form.get("limite_gasto"))
                db.session.add(
                    CentroCusto(
                        codigo=codigo,
                        nome=nome,
                        departamento_id=departamento_id,
                        limite_gasto=limite,
                    )
                )
            else:
                abort(400)
            db.session.commit()
            flash("Estrutura empresarial salva.", "sucesso")
            return redirect(url_for("empresarial.estrutura"))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "erro")
        except IntegrityError:
            db.session.rollback()
            flash("Não foi possível salvar: o código ou nome já está em uso.", "erro")

    departamentos = Departamento.query.order_by(Departamento.nome).all()
    centros = CentroCusto.query.order_by(
        CentroCusto.departamento_id, CentroCusto.codigo
    ).all()
    return render_template(
        "empresarial_estrutura.html",
        departamentos=departamentos,
        centros=centros,
    )


@empresarial_bp.route("/departamentos/<int:departamento_id>/editar", methods=["POST"])
@admin_required
def editar_departamento(departamento_id):
    departamento = db.session.get(Departamento, departamento_id)
    if departamento is None:
        abort(404)
    try:
        codigo = _codigo_valido(request.form.get("codigo"))
        nome = request.form.get("nome", "").strip()
        if not nome or len(nome) > 120:
            raise ValueError("Informe um nome de departamento com até 120 caracteres.")
        duplicado = Departamento.query.filter(
            Departamento.id != departamento.id,
            or_(
                func.lower(Departamento.codigo) == codigo.lower(),
                func.lower(Departamento.nome) == nome.lower(),
            ),
        ).first()
        if duplicado:
            raise ValueError("Já existe um departamento com esse código ou nome.")
        departamento.codigo = codigo
        departamento.nome = nome
        db.session.commit()
        flash("Departamento atualizado.", "sucesso")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "erro")
    except IntegrityError:
        db.session.rollback()
        flash("Não foi possível atualizar: o código ou nome já está em uso.", "erro")
    return redirect(url_for("empresarial.estrutura"))


@empresarial_bp.route("/centros-custo/<int:centro_id>/editar", methods=["POST"])
@admin_required
def editar_centro_custo(centro_id):
    centro = db.session.get(CentroCusto, centro_id)
    if centro is None:
        abort(404)
    try:
        nome = request.form.get("nome", "").strip()
        if not nome or len(nome) > 120:
            raise ValueError("Informe um nome de centro de custo com até 120 caracteres.")
        centro.nome = nome
        centro.limite_gasto = _limite_monetario(request.form.get("limite_gasto"))
        db.session.commit()
        flash("Centro de custo atualizado.", "sucesso")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "erro")
    except IntegrityError:
        db.session.rollback()
        flash("Não foi possível atualizar o centro de custo.", "erro")
    return redirect(url_for("empresarial.estrutura"))


def _dados_relatorio():
    total = expressao_total_orcamento()
    linhas = (
        db.session.query(
            Orcamento.centro_custo_id,
            Orcamento.status,
            total.label("total"),
        )
        .outerjoin(OrcamentoItem)
        .outerjoin(Cotacao, OrcamentoItem.cotacao_escolhida_id == Cotacao.id)
        .filter(Orcamento.centro_custo_id.isnot(None))
        .group_by(Orcamento.centro_custo_id, Orcamento.status)
        .all()
    )
    totais = {}
    for centro_id, status, valor in linhas:
        totais.setdefault(centro_id, {}).setdefault(status, Decimal("0.00"))
        totais[centro_id][status] += Decimal(str(valor or 0))

    centros = CentroCusto.query.join(Departamento).order_by(
        Departamento.nome, CentroCusto.codigo
    ).all()
    linhas_centros = []
    por_departamento = {}
    for centro in centros:
        status_totais = totais.get(centro.id, {})
        realizado = status_totais.get("compra_realizada", Decimal("0.00"))
        comprometido = sum(
            (status_totais.get(status, Decimal("0.00")) for status in _STATUS_COMPROMETIDOS),
            Decimal("0.00"),
        )
        linhas_centros.append(
            {
                "centro": centro,
                "realizado": realizado,
                "comprometido": comprometido,
                "disponivel": Decimal(centro.limite_gasto) - comprometido,
            }
        )
        acumulado = por_departamento.setdefault(
            centro.departamento_id,
            {"realizado": Decimal("0.00"), "comprometido": Decimal("0.00")},
        )
        acumulado["realizado"] += realizado
        acumulado["comprometido"] += comprometido

    linhas_departamentos = []
    for departamento in Departamento.query.order_by(Departamento.nome).all():
        totais_depto = por_departamento.get(
            departamento.id,
            {"realizado": Decimal("0.00"), "comprometido": Decimal("0.00")},
        )
        limite = sum(
            (Decimal(centro.limite_gasto) for centro in departamento.centros_custo),
            Decimal("0.00"),
        )
        linhas_departamentos.append(
            {
                "departamento": departamento,
                "limite": limite,
                "realizado": totais_depto["realizado"],
                "comprometido": totais_depto["comprometido"],
                "disponivel": limite - totais_depto["comprometido"],
            }
        )
    return linhas_departamentos, linhas_centros


def _formatar_brl(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@empresarial_bp.route("/relatorios")
@comprador_required
def relatorios():
    departamentos, centros = _dados_relatorio()
    return render_template(
        "empresarial_relatorios.html",
        departamentos=departamentos,
        centros=centros,
    )


@empresarial_bp.route("/relatorios.csv")
@comprador_required
def exportar_relatorios():
    departamentos, centros = _dados_relatorio()
    arquivo = io.StringIO(newline="")
    escritor = csv.writer(arquivo, delimiter=";")
    escritor.writerow(
        ["Tipo", "Departamento", "Centro de custo", "Limite", "Realizado", "Comprometido", "Disponível"]
    )
    for linha in departamentos:
        escritor.writerow(
            [
                "Departamento",
                linha["departamento"].nome,
                "",
                _formatar_brl(linha["limite"]),
                _formatar_brl(linha["realizado"]),
                _formatar_brl(linha["comprometido"]),
                _formatar_brl(linha["disponivel"]),
            ]
        )
    for linha in centros:
        centro = linha["centro"]
        escritor.writerow(
            [
                "Centro de custo",
                centro.departamento.nome,
                f"{centro.codigo} - {centro.nome}",
                _formatar_brl(centro.limite_gasto),
                _formatar_brl(linha["realizado"]),
                _formatar_brl(linha["comprometido"]),
                _formatar_brl(linha["disponivel"]),
            ]
        )
    resposta = Response(
        "\ufeff" + arquivo.getvalue(),
        content_type="text/csv; charset=utf-8",
    )
    resposta.headers["Content-Disposition"] = "attachment; filename=relatorio-centros-custo.csv"
    return resposta


@empresarial_bp.route("/orcamentos/<int:orcamento_id>/pedidos", methods=["GET", "POST"])
def pedidos_orcamento(orcamento_id):
    orcamento = Orcamento.query.get_or_404(orcamento_id)
    if request.method == "POST":
        if current_user.papel not in {"admin", "comprador"}:
            abort(403)
        try:
            emitir_pedidos_compra(orcamento.id, current_user)
            db.session.commit()
            flash("Pedidos de compra emitidos por fornecedor.", "sucesso")
        except LookupError:
            db.session.rollback()
            abort(404)
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "erro")
        except IntegrityError:
            db.session.rollback()
            flash("Os pedidos não foram emitidos porque já existe um pedido para algum fornecedor.", "erro")
        return redirect(url_for("empresarial.pedidos_orcamento", orcamento_id=orcamento.id))

    if (
        current_user.papel not in {"admin", "comprador"}
        and orcamento.usuario_id != current_user.id
    ):
        abort(404)
    return render_template(
        "pedidos_compra.html",
        orcamento=orcamento,
        pedidos=orcamento.pedidos_compra,
        pode_emitir=(
            current_user.papel in {"admin", "comprador"}
            and orcamento.status == "aprovado"
            and not orcamento.pedidos_compra
        ),
    )


@empresarial_bp.route("/pedidos/<int:pedido_id>")
def detalhe_pedido(pedido_id):
    pedido = PedidoCompra.query.get_or_404(pedido_id)
    if (
        current_user.papel not in {"admin", "comprador"}
        and pedido.orcamento.usuario_id != current_user.id
    ):
        abort(404)
    return render_template(
        "pedido_compra_detalhe.html",
        pedido=pedido,
        transicoes=_TRANSICOES_PEDIDO[pedido.status],
        pode_atualizar=current_user.papel in {"admin", "comprador"},
    )


@empresarial_bp.route("/pedidos/<int:pedido_id>/status", methods=["POST"])
@comprador_required
def atualizar_pedido(pedido_id):
    pedido = PedidoCompra.query.get_or_404(pedido_id)
    novo_status = request.form.get("status", "")
    if novo_status not in _TRANSICOES_PEDIDO[pedido.status]:
        abort(400, description="Transição de status do pedido não permitida.")
    data_entrega_texto = request.form.get("data_entrega", "").strip()
    try:
        data_entrega = date.fromisoformat(data_entrega_texto) if data_entrega_texto else None
    except ValueError:
        abort(400, description="Informe uma data de entrega válida.")
    nota_fiscal = request.form.get("nota_fiscal", "").strip()
    if len(nota_fiscal) > 120:
        abort(400, description="A nota fiscal deve ter até 120 caracteres.")
    pedido.status = novo_status
    pedido.data_entrega = data_entrega
    pedido.nota_fiscal = nota_fiscal or None
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    if novo_status == "enviado":
        pedido.enviado_em = agora
    elif novo_status == "recebido":
        pedido.recebido_em = agora
    db.session.commit()
    flash("Pedido de compra atualizado.", "sucesso")
    return redirect(url_for("empresarial.detalhe_pedido", pedido_id=pedido.id))


@empresarial_bp.route("/pedidos/<int:pedido_id>/pdf")
def pdf_pedido(pedido_id):
    pedido = PedidoCompra.query.get_or_404(pedido_id)
    if (
        current_user.papel not in {"admin", "comprador"}
        and pedido.orcamento.usuario_id != current_user.id
    ):
        abort(404)
    caminho_pdf = gerar_pdf_pedido_compra(pedido)
    return send_file(
        caminho_pdf,
        as_attachment=True,
        download_name=os.path.basename(caminho_pdf),
        mimetype="application/pdf",
    )
