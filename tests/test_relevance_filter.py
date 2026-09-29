import json

import pytest

from orcatech import comparador


def _product(nome, site="Gshield", preco=99.9):
    return {
        "site": site,
        "nome": nome,
        "preco": preco,
        "preco_texto": f"R$ {preco:.2f}",
        "link": "",
        "specs": [],
    }


@pytest.mark.parametrize(
    ("busca", "nome"),
    [
        ("Notebook i7 16GB", 'Capa Neoflex para Notebook 15,6"'),
        ("Mouse Gamer", "Mouse Pad Gamer Grande"),
        ("Teclado Mecânico", "Capa Protetora para Teclado Mecânico"),
        ("Cadeira Gamer", "Almofada para Cadeira Gamer"),
        ("SSD 1TB", "Cabo SATA para SSD 1TB"),
        ("Notebook", "Mochila para Notebook 15,6"),
        ("Monitor Gamer", "Filtro de Privacidade para Monitor Gamer"),
        ("Notebook", "Organizador de acessórios para Notebook"),
    ],
)
def test_rejeita_acessorios_e_categorias_incorretas(busca, nome, monkeypatch, tmp_path):
    arquivo_log = tmp_path / "filtro.jsonl"
    monkeypatch.setattr(comparador, "_ARQUIVO_DIAGNOSTICO_FILTRO", arquivo_log)

    assert comparador._filtrar_estrito(busca, [_product(nome)]) == []

    registro = json.loads(arquivo_log.read_text(encoding="utf-8").splitlines()[-1])
    assert registro["motivo"] in {"acessorio", "categoria", "tipo"}
    assert registro["produto"] == busca
    assert registro["item"] == nome
    assert registro["loja"] == "Gshield"
    assert "categoria" in registro
    assert "termos" in registro


@pytest.mark.parametrize(
    ("busca", "nome"),
    [
        ("Mouse Gamer", "Mouse Gamer USB M220"),
        ("Cadeira Gamer", "Cadeira Gamer Reclinável"),
        ("SSD Kingston 1TB NV2", "SSD Kingston 1TB NV2"),
        ("Teclado Mecânico", "Teclado Mecânico ABNT2"),
        ("Notebook", "Samsung Galaxy Book6"),
    ],
)
def test_preserva_produtos_da_categoria_pesquisada(busca, nome, monkeypatch, tmp_path):
    monkeypatch.setattr(
        comparador, "_ARQUIVO_DIAGNOSTICO_FILTRO", tmp_path / "filtro.jsonl"
    )
    assert comparador._filtrar_estrito(busca, [_product(nome)])


def test_filtro_de_categoria_tambem_cobre_todas_as_lojas_mistas(monkeypatch, tmp_path):
    monkeypatch.setattr(
        comparador, "_ARQUIVO_DIAGNOSTICO_FILTRO", tmp_path / "filtro.jsonl"
    )
    lojas = (
        "Gshield", "AliExpress", "Americanas", "Mercado Livre",
        "Amazon", "KaBuM", "Terabyte", "iBytes",
    )
    resultados = [
        _product("Mouse Pad Gamer XL", site=loja) for loja in lojas
    ] + [
        _product("Mouse Gamer USB M220", site=loja) for loja in lojas
    ]

    filtrados = comparador._aplicar_filtro_estrito("Mouse Gamer", resultados)

    assert len(filtrados) == len(lojas)
    assert all(item["nome"] == "Mouse Gamer USB M220" for item in filtrados)


@pytest.mark.parametrize(
    ("busca", "esperado"),
    [
        ("Notebook i7 16GB", False),
        ("Celular Samsung", False),
        ("Monitor Gamer", False),
        ("PC Gamer", False),
        ("SSD Kingston 1TB", False),
        ("Mouse Gamer", True),
        ("Teclado Mecânico", True),
        ("Capa para iPhone", True),
        ("Película para celular", True),
    ],
)
def test_portao_da_gshield_por_categoria(busca, esperado):
    assert comparador._busca_gshield_aplicavel(busca) is esperado


def test_busca_por_acessorio_pode_retornar_o_acessorio_pedido(monkeypatch, tmp_path):
    monkeypatch.setattr(
        comparador, "_ARQUIVO_DIAGNOSTICO_FILTRO", tmp_path / "filtro.jsonl"
    )
    resultados = comparador._filtrar_estrito(
        "Capa para iPhone 15",
        [_product("Capa Neoflex para iPhone 15")],
    )
    assert len(resultados) == 1


def test_filtro_global_esta_ativo_por_padrao():
    assert comparador.FILTRAR_RESULTADOS is True


def test_economia_usa_mediana_somente_de_anuncios_do_mesmo_modelo():
    from orcatech.app import economia_mesmo_modelo

    produtos = [
        {"nome": "Mouse Gamer USB M220 Preto", "preco": 100},
        {"nome": "Mouse Gamer USB M220", "preco": 110},
        {"nome": "Mouse Gamer USB M220", "preco": 1000},
        {"nome": "Mouse Gamer diferente", "preco": 500},
    ]

    assert economia_mesmo_modelo(produtos) == 10


def test_nao_chama_gshield_para_busca_fora_do_catalogo(monkeypatch, tmp_path):
    monkeypatch.setattr(
        comparador, "_ARQUIVO_DIAGNOSTICO_FILTRO", tmp_path / "filtro.jsonl"
    )
    monkeypatch.setattr(comparador, "_salvar_cache", lambda *_: None)
    monkeypatch.setattr(comparador, "buscar_mercadolivre", lambda _: [])
    monkeypatch.setattr(comparador, "buscar_kabum", lambda _: [])
    monkeypatch.setattr(comparador, "buscar_amazon", lambda _: [])
    monkeypatch.setattr(comparador, "buscar_terabyte", lambda _: [])
    monkeypatch.setattr(comparador, "buscar_americanas", lambda _: [])
    monkeypatch.setattr(comparador, "buscar_ibyte", lambda _: [])
    monkeypatch.setattr(
        comparador,
        "buscar_gshield",
        lambda _: pytest.fail("Gshield não deve ser chamada para notebook"),
    )
    monkeypatch.setattr(comparador, "buscar_aliexpress", lambda _: [])
    job = {"lojas": {nome: {"status": "pending", "count": 0} for nome in (
        "mercadolivre", "kabum", "amazon", "terabyte", "americanas", "ibyte",
        "gshield", "aliexpress",
    )}}

    comparador.comparar("Notebook i7", forcar_busca=True, job=job)

    assert job["lojas"]["gshield"]["status"] == "not_applicable"
    assert job["progresso"] == 100


def test_gshield_sem_resultado_relevante_fica_explicito(monkeypatch, tmp_path):
    monkeypatch.setattr(
        comparador, "_ARQUIVO_DIAGNOSTICO_FILTRO", tmp_path / "filtro.jsonl"
    )
    monkeypatch.setattr(comparador, "_salvar_cache", lambda *_: None)
    monkeypatch.setattr(comparador, "buscar_mercadolivre", lambda _: [])
    monkeypatch.setattr(comparador, "buscar_kabum", lambda _: [])
    monkeypatch.setattr(comparador, "buscar_amazon", lambda _: [])
    monkeypatch.setattr(comparador, "buscar_terabyte", lambda _: [])
    monkeypatch.setattr(comparador, "buscar_americanas", lambda _: [])
    monkeypatch.setattr(comparador, "buscar_ibyte", lambda _: [])
    monkeypatch.setattr(
        comparador,
        "buscar_gshield",
        lambda _: [_product("Mouse Pad Gamer")],
    )
    monkeypatch.setattr(comparador, "buscar_aliexpress", lambda _: [])
    job = {"lojas": {nome: {"status": "pending", "count": 0} for nome in (
        "mercadolivre", "kabum", "amazon", "terabyte", "americanas", "ibyte",
        "gshield", "aliexpress",
    )}}

    resultado = comparador.comparar("Mouse Gamer", forcar_busca=True, job=job)

    assert not any(produto["site"] == "Gshield" for produto in resultado["produtos"])
    assert job["lojas"]["gshield"]["status"] == "no_relevant"
