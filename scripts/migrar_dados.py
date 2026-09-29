"""
migrar_dados.py — importa os dados existentes de instance/cache/ e do histórico
para o banco SQLite recém-criado, sem perder nada do histórico atual.

Rodar UMA VEZ, depois que o banco já foi criado (db.create_all()):

    python -m scripts.migrar_dados

Idempotente: pode rodar de novo sem duplicar (usa get_or_create por nome).
"""

import glob
import json
import os
from datetime import datetime

from orcatech.app import app
from orcatech.models import db, Fornecedor, ProdutoBusca, Cotacao, Orcamento, OrcamentoItem
from orcatech.paths import CACHE_DIR, HISTORICO_FILE


def get_or_create_fornecedor(nome):
    nome = (nome or "Desconhecido").strip()
    f = Fornecedor.query.filter_by(nome=nome).first()
    if not f:
        f = Fornecedor(nome=nome, tipo="online")
        db.session.add(f)
        db.session.flush()
    return f


def get_or_create_produto_busca(nome_pesquisado):
    p = ProdutoBusca.query.filter_by(nome_pesquisado=nome_pesquisado).first()
    if not p:
        p = ProdutoBusca(nome_pesquisado=nome_pesquisado)
        db.session.add(p)
        db.session.flush()
    return p


def migrar_cache():
    """Cada arquivo cache/<produto>.json vira um ProdutoBusca + N Cotacoes."""
    arquivos = glob.glob(os.path.join(CACHE_DIR, "*.json"))
    total_cotacoes = 0
    for caminho in arquivos:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)

        nome_produto = dados.get("produto", os.path.basename(caminho).replace(".json", ""))
        produto_busca = get_or_create_produto_busca(nome_produto)

        for p in dados.get("produtos", []):
            preco = p.get("preco", 0)
            if not preco or preco <= 0:
                continue
            fornecedor = get_or_create_fornecedor(p.get("site"))

            existe = Cotacao.query.filter_by(
                produto_busca_id=produto_busca.id,
                fornecedor_id=fornecedor.id,
                nome_produto=p.get("nome", "")[:255],
                preco=preco,
            ).first()
            if existe:
                continue

            cotacao = Cotacao(
                produto_busca_id=produto_busca.id,
                fornecedor_id=fornecedor.id,
                nome_produto=p.get("nome", "")[:255],
                preco=preco,
                link=p.get("link"),
                imagem=p.get("imagem"),
                origem="scraping",
            )
            if produto_busca.especificacoes is None and p.get("specs"):
                produto_busca.especificacoes = p.get("specs")

            db.session.add(cotacao)
            total_cotacoes += 1

    db.session.commit()
    print(f"[cache] {len(arquivos)} produtos processados, {total_cotacoes} cotações novas importadas.")


def migrar_historico():
    """
    historico.json só guarda o resumo (mais barato / premium) de cada busca.
    Viramos cada entrada num Orcamento de 1 item em status 'compra_realizada'
    pra manter o histórico visível na tela de orçamentos, ligado à cotação
    mais barata já importada via migrar_cache().
    """
    if not os.path.exists(HISTORICO_FILE):
        print("[historico] arquivo não encontrado, pulando.")
        return

    with open(HISTORICO_FILE, "r", encoding="utf-8") as f:
        historico = json.load(f)

    criados = 0
    for h in historico:
        numero = "ORC-LEGADO-" + h.get("data", "").replace("/", "").replace(" ", "").replace(":", "")
        if Orcamento.query.filter_by(numero=numero).first():
            continue

        produto_busca = get_or_create_produto_busca(h.get("produto", "—"))

        cotacao = (
            Cotacao.query.filter_by(produto_busca_id=produto_busca.id)
            .order_by(Cotacao.preco.asc())
            .first()
        )

        orcamento = Orcamento(
            numero=numero,
            solicitante=None,
            status="compra_realizada",
            observacoes="Importado automaticamente do historico.json legado.",
        )
        db.session.add(orcamento)
        db.session.flush()

        item = OrcamentoItem(
            orcamento_id=orcamento.id,
            produto_busca_id=produto_busca.id,
            quantidade=1,
            cotacao_escolhida_id=cotacao.id if cotacao else None,
        )
        db.session.add(item)
        criados += 1

    db.session.commit()
    print(f"[historico] {criados} orçamentos legados importados.")


if __name__ == "__main__":
    with app.app_context():
        db.create_all()  # garante que as tabelas existem
        migrar_cache()
        migrar_historico()
    print("Migração concluída.")
