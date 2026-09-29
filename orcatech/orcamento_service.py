"""
orcamento_service.py — funções auxiliares para o "carrinho" de orçamento:
achar/criar fornecedor, produto de busca e cotação, e gerenciar o
orçamento rascunho ativo na sessão do usuário.
"""

from .models import db, Fornecedor, ProdutoBusca, Cotacao, Orcamento, OrcamentoItem
from flask_login import current_user


def get_or_create_fornecedor(nome, tipo="online"):
    nome = (nome or "Desconhecido").strip()
    f = Fornecedor.query.filter_by(nome=nome).first()
    if not f:
        f = Fornecedor(nome=nome, tipo=tipo)
        db.session.add(f)
        db.session.flush()
    return f


def get_or_create_produto_busca(nome_pesquisado):
    nome_pesquisado = (nome_pesquisado or "").strip()
    p = ProdutoBusca.query.filter_by(nome_pesquisado=nome_pesquisado).first()
    if not p:
        p = ProdutoBusca(nome_pesquisado=nome_pesquisado)
        db.session.add(p)
        db.session.flush()
    return p


def registrar_cotacao(produto_busca, nome_produto, preco, site, link=None, imagem=None, origem="scraping"):
    """Acha uma cotação já registrada igual, ou cria uma nova."""
    fornecedor = get_or_create_fornecedor(site)

    existente = Cotacao.query.filter_by(
        produto_busca_id=produto_busca.id,
        fornecedor_id=fornecedor.id,
        nome_produto=(nome_produto or "")[:255],
        preco=preco,
    ).first()
    if existente:
        return existente

    cotacao = Cotacao(
        produto_busca_id=produto_busca.id,
        fornecedor_id=fornecedor.id,
        nome_produto=(nome_produto or "")[:255],
        preco=preco,
        link=link,
        imagem=imagem,
        origem=origem,
    )
    db.session.add(cotacao)
    db.session.flush()
    return cotacao


def get_orcamento_ativo(criar_se_nao_existir=True, usuario_id=None):
    if usuario_id is None:
        if not current_user.is_authenticated:
            return None
        usuario_id = current_user.id

    orcamento = Orcamento.query.filter_by(
        usuario_id=usuario_id,
        status="rascunho",
    ).order_by(Orcamento.criado_em.desc()).first()
    if orcamento:
        return orcamento
    if not criar_se_nao_existir:
        return None

    orcamento = Orcamento(
        numero=Orcamento.gerar_numero(),
        usuario_id=usuario_id,
        solicitante=current_user.nome if current_user.is_authenticated else None,
        status="rascunho",
    )
    db.session.add(orcamento)
    db.session.commit()
    return orcamento


def adicionar_item_ao_orcamento(produto_busca, cotacao, quantidade=1, usuario_id=None):
    orcamento = get_orcamento_ativo(usuario_id=usuario_id)

    item_existente = OrcamentoItem.query.filter_by(
        orcamento_id=orcamento.id,
        produto_busca_id=produto_busca.id,
        cotacao_escolhida_id=cotacao.id,
    ).first()

    if item_existente:
        item_existente.quantidade += quantidade
    else:
        item_existente = OrcamentoItem(
            orcamento_id=orcamento.id,
            produto_busca_id=produto_busca.id,
            quantidade=quantidade,
            cotacao_escolhida_id=cotacao.id,
        )
        db.session.add(item_existente)

    db.session.commit()
    return orcamento, item_existente
