from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import current_app

from .models import OrcamentoHistorico, db


TRANSICOES_PERMITIDAS = {
    "rascunho": {"em_cotacao"},
    "em_cotacao": {"aguardando_aprovacao"},
    "aguardando_aprovacao": {"aprovado", "reprovado"},
    "aprovado": {"compra_realizada"},
    "reprovado": {"rascunho"},
    "compra_realizada": set(),
}


class ErroWorkflow(ValueError):
    pass


def _admin_pode_autoaprovar():
    return bool(current_app.config.get("ADMIN_PODE_AUTOAPROVAR", False))


def _tem_permissao_aprovar(usuario, orcamento):
    if not usuario or not getattr(usuario, "is_authenticated", False):
        return False
    admin = usuario.papel == "admin"
    if usuario.papel not in {"admin", "aprovador"}:
        return False
    if orcamento.usuario_id == usuario.id:
        return admin and _admin_pode_autoaprovar()
    return True


def pode_transicionar(de, para, usuario, orcamento=None):
    if para not in TRANSICOES_PERMITIDAS.get(de, set()):
        return False
    if not usuario or not getattr(usuario, "is_authenticated", False):
        return False
    if orcamento is None:
        return True

    eh_dono_ou_admin = (
        usuario.papel == "admin" or orcamento.usuario_id == usuario.id
    )
    if de == "aguardando_aprovacao" and para in {"aprovado", "reprovado"}:
        if not _tem_permissao_aprovar(usuario, orcamento):
            return False
        if para == "aprovado" and orcamento.expirado:
            return False
        return True
    return eh_dono_ou_admin


def transicionar(orcamento, para, usuario, comentario=None):
    de = orcamento.status
    comentario = (comentario or "").strip() or None
    if not pode_transicionar(de, para, usuario, orcamento):
        if de == "aguardando_aprovacao" and para == "aprovado" and orcamento.expirado:
            raise ErroWorkflow("O orçamento expirou. Renove a validade antes de aprová-lo.")
        if de == "aguardando_aprovacao" and para in {"aprovado", "reprovado"}:
            if usuario and orcamento.usuario_id == usuario.id:
                raise ErroWorkflow("Quem solicitou o orçamento não pode aprová-lo.")
            raise ErroWorkflow("Você não tem permissão para decidir este orçamento.")
        raise ErroWorkflow(f"Transição de {de} para {para} não permitida.")
    if para == "reprovado" and not comentario:
        raise ErroWorkflow("Informe um comentário para reprovar o orçamento.")

    orcamento.status = para
    db.session.add(
        OrcamentoHistorico(
            orcamento_id=orcamento.id,
            status_de=de,
            status_para=para,
            usuario_id=usuario.id,
            comentario=comentario,
        )
    )
    return orcamento


def validade_padrao():
    dias = int(current_app.config.get("ORCAMENTO_VALIDADE_DIAS", 15))
    if dias < 1:
        raise RuntimeError("ORCAMENTO_VALIDADE_DIAS deve ser maior que zero.")
    return date.today() + timedelta(days=dias)


def congelar_precos(orcamento):
    if not orcamento.itens:
        raise ErroWorkflow("O orçamento precisa conter pelo menos um item.")
    for item in orcamento.itens:
        cotacao = item.cotacao_escolhida
        if not cotacao:
            raise ErroWorkflow("Todos os itens precisam ter uma cotação selecionada.")
        item.snapshot_nome_produto = cotacao.nome_produto
        item.snapshot_fornecedor_nome = cotacao.fornecedor.nome
        item.snapshot_preco_unit = _dinheiro(cotacao.preco)
        item.snapshot_frete = _dinheiro(cotacao.frete)
        item.snapshot_link = cotacao.link


def _dinheiro(valor):
    return Decimal(str(valor or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
