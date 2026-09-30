from decimal import Decimal

from flask import current_app
from sqlalchemy import func

from .models import (
    CentroCusto,
    Cotacao,
    Departamento,
    Orcamento,
    OrcamentoItem,
    PedidoCompra,
    PedidoCompraItem,
    Usuario,
    db,
)


_STATUS_RESERVAM_CUSTO = (
    "aguardando_aprovacao",
    "aprovado",
    "compra_realizada",
)


def funcionalidade_empresarial_ativa():
    return bool(current_app.config.get("FEATURE_EMPRESARIAL_ENABLED", False))


def usuario_pode_aprovar(usuario, orcamento):
    if not funcionalidade_empresarial_ativa():
        return usuario.papel in {"admin", "aprovador"}
    limite = Decimal(current_app.config["ALCADA_APROVACAO_LIMITE"])
    if orcamento.total <= limite:
        return (
            usuario.papel == "aprovador"
            and usuario.departamento_id == orcamento.departamento_id
        ) or (
            usuario.papel == "admin"
            and orcamento.usuario_id == usuario.id
            and current_app.config.get("ADMIN_PODE_AUTOAPROVAR", False)
        )
    return usuario.papel == "admin" and (
        orcamento.usuario_id != usuario.id
        or current_app.config.get("ADMIN_PODE_AUTOAPROVAR", False)
    )


def aprovadores_do_orcamento(orcamento):
    ativos = Usuario.query.filter(Usuario.ativo.is_(True))
    if funcionalidade_empresarial_ativa() and orcamento.total <= Decimal(
        current_app.config["ALCADA_APROVACAO_LIMITE"]
    ):
        return (
            ativos.filter(
                Usuario.papel == "aprovador",
                Usuario.departamento_id == orcamento.departamento_id,
            )
            .order_by(Usuario.id)
            .all()
        )
    administradores = ativos.filter(Usuario.papel == "admin")
    if not current_app.config.get("ADMIN_PODE_AUTOAPROVAR", False):
        administradores = administradores.filter(Usuario.id != orcamento.usuario_id)
    return administradores.order_by(Usuario.id).all()


def expressao_total_orcamento():
    preco = func.coalesce(OrcamentoItem.snapshot_preco_unit, Cotacao.preco, 0)
    frete = func.coalesce(OrcamentoItem.snapshot_frete, Cotacao.frete, 0)
    return func.coalesce(
        func.sum(preco * OrcamentoItem.quantidade + frete),
        0,
    )


def validar_unidade_orcamento(usuario, departamento_id, centro_custo_id, orcamento):
    departamento = db.session.get(Departamento, departamento_id)
    centro_custo = (
        CentroCusto.query.filter_by(id=centro_custo_id)
        .with_for_update()
        .first()
    )
    if not departamento or not centro_custo:
        raise ValueError("Selecione um departamento e um centro de custo válidos.")
    if centro_custo.departamento_id != departamento.id:
        raise ValueError("O centro de custo não pertence ao departamento selecionado.")
    if usuario.papel != "admin" and usuario.departamento_id != departamento.id:
        raise ValueError("Você só pode orçar para o seu próprio departamento.")

    if orcamento.total > Decimal(centro_custo.limite_gasto):
        raise ValueError("O orçamento ultrapassa o limite total deste centro de custo.")

    existentes = Orcamento.query.filter(
        Orcamento.centro_custo_id == centro_custo.id,
        Orcamento.status.in_(_STATUS_RESERVAM_CUSTO),
    ).all()
    reservado = sum((item.total for item in existentes), Decimal("0.00"))
    if reservado + orcamento.total > Decimal(centro_custo.limite_gasto):
        raise ValueError(
            "A finalização foi bloqueada: o total comprometido ultrapassaria "
            "o limite do centro de custo."
        )

    destinatarios = aprovadores_do_orcamento(orcamento)
    destinatarios = [destino for destino in destinatarios if destino.id != usuario.id]
    if not destinatarios and not (
        usuario.papel == "admin"
        and current_app.config.get("ADMIN_PODE_AUTOAPROVAR", False)
    ):
        if orcamento.total <= Decimal(current_app.config["ALCADA_APROVACAO_LIMITE"]):
            raise ValueError(
                "Não há aprovador ativo vinculado ao departamento. "
                "Peça ao administrador para configurar um."
            )
        raise ValueError("Não há administrador ativo disponível para aprovar este valor.")
    return departamento, centro_custo


def emitir_pedidos_compra(orcamento_id, usuario):
    if not funcionalidade_empresarial_ativa():
        raise ValueError("A funcionalidade empresarial está desativada.")
    if usuario.papel not in {"admin", "comprador"}:
        raise ValueError("Somente um comprador ou administrador pode emitir pedidos.")

    orcamento = (
        Orcamento.query.filter_by(id=orcamento_id)
        .with_for_update()
        .first()
    )
    if orcamento is None:
        raise LookupError("Orçamento não encontrado.")
    if orcamento.status != "aprovado":
        raise ValueError("Só é possível emitir pedidos para um orçamento aprovado.")
    if not orcamento.itens:
        raise ValueError("O orçamento aprovado não contém itens.")
    if orcamento.pedidos_compra:
        raise ValueError("Já existem pedidos emitidos para este orçamento.")

    itens_por_fornecedor = {}
    for item in orcamento.itens:
        cotacao = item.cotacao_escolhida
        if cotacao is None or cotacao.fornecedor is None:
            raise ValueError(
                "Não foi possível identificar o fornecedor de todos os itens."
            )
        itens_por_fornecedor.setdefault(cotacao.fornecedor_id, []).append(item)

    pedidos = []
    for fornecedor_id, itens in itens_por_fornecedor.items():
        fornecedor_nome = (
            itens[0].snapshot_fornecedor_nome or itens[0].cotacao_escolhida.fornecedor.nome
        )
        pedido = PedidoCompra(
            numero=PedidoCompra.gerar_numero(),
            orcamento_id=orcamento.id,
            fornecedor_id=fornecedor_id,
            snapshot_fornecedor_nome=fornecedor_nome,
            criado_por_id=usuario.id,
            status="emitido",
            condicoes_comerciais=orcamento.condicoes_comerciais,
        )
        db.session.add(pedido)
        db.session.flush()
        for item in itens:
            db.session.add(
                PedidoCompraItem(
                    pedido_compra_id=pedido.id,
                    orcamento_item_id=item.id,
                    nome_produto=item.nome_produto,
                    quantidade=item.quantidade,
                    preco_unitario=item.preco_unitario,
                    frete=item.frete,
                    link=item.link,
                )
            )
        pedidos.append(pedido)

    from .orcamento_workflow import transicionar

    transicionar(
        orcamento,
        "compra_realizada",
        usuario,
        "Pedidos de compra emitidos por fornecedor.",
    )
    return pedidos
