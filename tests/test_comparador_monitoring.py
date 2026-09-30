from orcatech import comparador


def _configurar_comparador(monkeypatch, tmp_path):
    monkeypatch.setattr(comparador, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(comparador, "_cache_valido", lambda _termo: False)
    monkeypatch.setattr(comparador, "_deduplicar", lambda produtos: produtos)
    monkeypatch.setattr(
        comparador,
        "_filtrar_estrito",
        lambda _termo, produtos, validar_termos=True: produtos,
    )
    monkeypatch.setattr(comparador, "_filtrar", lambda _termo, produtos: produtos)
    monkeypatch.setattr(comparador, "_classificar", lambda produtos: produtos)


def test_busca_monitorada_chama_so_a_loja_escolhida_e_nao_grava_cache(
    monkeypatch, tmp_path
):
    _configurar_comparador(monkeypatch, tmp_path)
    chamadas = []
    monkeypatch.setattr(
        comparador,
        "buscar_amazon",
        lambda termo: chamadas.append(termo) or [{
            "site": "Amazon",
            "nome": "SSD Kingston NV2 1TB",
            "preco": 299.90,
        }],
    )

    resultado = comparador.comparar(
        "SSD Kingston 1TB",
        lojas_incluir={"amazon"},
        salvar_cache=False,
    )

    assert chamadas == ["SSD Kingston 1TB"]
    assert resultado["lojas_status"]["amazon"] == "success"
    assert resultado["lojas_status"]["kabum"] == "not_requested"
    assert len(resultado["produtos"]) == 1
    assert list(tmp_path.iterdir()) == []


def test_busca_monitorada_pula_loja_que_ja_esta_ocupada(monkeypatch, tmp_path):
    _configurar_comparador(monkeypatch, tmp_path)
    chamadas = []
    monkeypatch.setattr(
        comparador, "buscar_amazon", lambda _termo: chamadas.append(True) or []
    )

    with comparador.STORE_LOCKS["amazon"]:
        resultado = comparador.comparar(
            "SSD Kingston 1TB",
            lojas_incluir={"amazon"},
            salvar_cache=False,
            pular_lojas_ocupadas=True,
        )

    assert chamadas == []
    assert resultado["lojas_status"]["amazon"] == "busy"


def test_busca_monitorada_informa_bloqueio_da_loja(monkeypatch, tmp_path):
    _configurar_comparador(monkeypatch, tmp_path)
    job = {"lojas": {}}

    def amazon_bloqueada(_termo):
        raise comparador.BloqueioLoja("Amazon sinalizou bloqueio anti-bot.")

    monkeypatch.setattr(comparador, "buscar_amazon", amazon_bloqueada)

    resultado = comparador.comparar(
        "SSD Kingston 1TB",
        job=job,
        lojas_incluir={"amazon"},
        salvar_cache=False,
    )

    assert resultado["lojas_status"]["amazon"] == "blocked"
    assert job["lojas"]["amazon"] == {"status": "blocked", "count": 0}
    assert job["concluidas"] == 2
    assert job["lojas"]["gshield"]["status"] == "not_applicable"


def test_busca_monitorada_reaproveita_cache_valido(monkeypatch):
    produto = {
        "site": "Amazon",
        "nome": "SSD Kingston NV2 1TB",
        "preco": 299.90,
    }
    monkeypatch.setattr(comparador, "_cache_valido", lambda _termo: True)
    monkeypatch.setattr(
        comparador,
        "_ler_cache",
        lambda _termo: {"produto": "SSD Kingston 1TB", "produtos": [produto]},
    )
    monkeypatch.setattr(
        comparador,
        "_aplicar_filtro_estrito",
        lambda _termo, produtos: produtos,
    )
    monkeypatch.setattr(comparador, "_filtrar", lambda _termo, produtos: produtos)
    monkeypatch.setattr(comparador, "_classificar", lambda produtos: produtos)
    monkeypatch.setattr(
        comparador,
        "buscar_amazon",
        lambda _termo: (_ for _ in ()).throw(AssertionError("Cache miss")),
    )

    resultado = comparador.comparar(
        "SSD Kingston 1TB",
        lojas_incluir={"amazon"},
        salvar_cache=False,
    )

    assert resultado["do_cache"] is True
    assert resultado["lojas_status"]["amazon"] == "cache"
    assert resultado["produtos"] == [produto]
