from datetime import datetime, timedelta
from decimal import Decimal

from orcatech.models import (
    AlertaPreco,
    ControleVerificacaoLoja,
    Cotacao,
    Fornecedor,
    EnvioEmail,
    Monitoramento,
    Orcamento,
    OrcamentoItem,
    PrecoHistorico,
    ProdutoBusca,
    db,
)


def _criar_monitoramento(application, user, termo, nome, loja, preco, percentual=None, valor=None):
    with application.app_context():
        produto = ProdutoBusca.query.filter_by(nome_pesquisado=termo).first()
        if not produto:
            produto = ProdutoBusca(nome_pesquisado=termo)
            db.session.add(produto)
        fornecedor = Fornecedor.query.filter_by(nome=loja).first()
        if not fornecedor:
            fornecedor = Fornecedor(nome=loja)
            db.session.add(fornecedor)
        db.session.flush()
        monitoramento = Monitoramento(
            usuario_id=user.id,
            produto_busca_id=produto.id,
            fornecedor_id=fornecedor.id,
            loja=loja.casefold().replace(" ", ""),
            nome_modelo=nome,
            preco_referencia=preco,
            gatilho_percentual=percentual,
            gatilho_valor=valor,
            proxima_verificacao=datetime(2026, 10, 3, 12),
        )
        db.session.add(monitoramento)
        db.session.commit()
        return monitoramento.id


def test_historico_guarda_um_ponto_por_anuncio_e_dia(application):
    from orcatech.monitoramento_service import persistir_resultados_precos

    primeira_coleta = datetime(2026, 10, 1, 9)
    item = {
        "site": "Amazon",
        "nome": "SSD Kingston NV2 1TB",
        "preco": 299.90,
        "link": "https://www.amazon.com.br/dp/B0ABC?ref=tracking",
    }
    with application.app_context():
        assert persistir_resultados_precos("SSD Kingston 1TB NV2", [item], primeira_coleta) == 1
        item_atualizado = dict(item, preco=279.90)
        assert persistir_resultados_precos(
            "SSD Kingston 1TB NV2",
            [item_atualizado],
            primeira_coleta + timedelta(hours=5),
        ) == 1
        assert PrecoHistorico.query.count() == 1
        historico = PrecoHistorico.query.one()
        assert historico.preco == Decimal("279.90")
        assert historico.cotacao.preco == 279.90

        assert persistir_resultados_precos(
            "SSD Kingston 1TB NV2",
            [item_atualizado],
            primeira_coleta + timedelta(days=1),
        ) == 1
        assert PrecoHistorico.query.count() == 2


def test_compatibilidade_exige_modelo_e_especificacoes():
    from orcatech.monitoramento_service import modelos_compativeis

    assert modelos_compativeis("SSD Kingston NV2 1TB", "Kingston NV2 SSD 1TB")
    assert not modelos_compativeis("SSD Kingston NV2 1TB", "SSD Kingston A400 1TB")
    assert not modelos_compativeis("Mouse Gamer USB M220", "Mouse pad gamer USB M220")


def test_gatilho_percentual_e_valor_e_deduplicacao(application, make_user):
    from orcatech.monitoramento_service import _registrar_alerta

    user = make_user("Monitor", "monitor-threshold@example.com")
    percentage_id = _criar_monitoramento(
        application,
        user,
        "Mouse Gamer M220",
        "Mouse Gamer USB M220",
        "Amazon",
        Decimal("100.00"),
        percentual=Decimal("10"),
    )
    value_id = _criar_monitoramento(
        application,
        user,
        "SSD Kingston NV2",
        "SSD Kingston NV2 1TB",
        "KaBuM",
        Decimal("100.00"),
        valor=Decimal("10.00"),
    )

    with application.app_context():
        percentage_monitor = db.session.get(Monitoramento, percentage_id)
        assert _registrar_alerta(percentage_monitor, Decimal("91.00")) is None
        assert _registrar_alerta(percentage_monitor, Decimal("90.00")) is not None
        db.session.commit()
        assert _registrar_alerta(percentage_monitor, Decimal("90.00")) is None

        value_monitor = db.session.get(Monitoramento, value_id)
        assert _registrar_alerta(value_monitor, Decimal("91.00")) is None
        assert _registrar_alerta(value_monitor, Decimal("90.00")) is not None
        db.session.commit()
        assert AlertaPreco.query.count() == 2


def test_verificar_precos_agrupa_buscas_e_respeita_intervalo(
    application, make_user, monkeypatch
):
    from orcatech import monitoramento_service

    user = make_user("Group", "monitor-group@example.com")
    first_id = _criar_monitoramento(
        application,
        user,
        "SSD Kingston NV2 1TB",
        "SSD Kingston NV2 1TB",
        "Amazon",
        Decimal("100.00"),
        percentual=Decimal("10"),
    )
    second_id = _criar_monitoramento(
        application,
        user,
        "SSD Kingston NV2 1TB",
        "Kingston NV2 SSD 1TB",
        "Amazon",
        Decimal("100.00"),
        valor=Decimal("10.00"),
    )
    chamadas = []

    def comparar_fake(termo, **kwargs):
        chamadas.append((termo, kwargs))
        return {
            "do_cache": False,
            "lojas_status": {"amazon": "success"},
            "produtos": [{
                "site": "Amazon",
                "nome": "SSD Kingston NV2 1TB",
                "preco": 89.90,
                "link": "https://www.amazon.com.br/dp/B0ABC",
            }],
        }

    monkeypatch.setattr(monitoramento_service, "comparar", comparar_fake)
    application.config["MONITORAMENTO_JITTER_SEGUNDOS"] = 0
    agora = datetime(2026, 10, 3, 12)

    assert monitoramento_service.verificar_precos(application, agora) == {
        "status": "completed",
        "consultas": 1,
        "alertas": 2,
        "ignorados": 0,
    }
    assert len(chamadas) == 1
    assert chamadas[0][1]["forcar_busca"] is False
    assert chamadas[0][1]["lojas_incluir"] == {"amazon"}
    with application.app_context():
        assert db.session.get(Monitoramento, first_id).ultimo_check is not None
        assert db.session.get(Monitoramento, second_id).ultimo_check is not None
        assert PrecoHistorico.query.count() == 1
        assert AlertaPreco.query.count() == 2
        control = ControleVerificacaoLoja.query.filter_by(loja="amazon").one()
        assert control.proxima_permitida == agora + timedelta(hours=24)

    assert monitoramento_service.verificar_precos(application, agora) == {
        "status": "completed",
        "consultas": 0,
        "alertas": 0,
        "ignorados": 0,
    }
    assert len(chamadas) == 1


def test_bloqueio_aplica_backoff_e_nao_tenta_novamente(
    application, make_user, monkeypatch
):
    from orcatech import monitoramento_service

    user = make_user("Blocked", "monitor-blocked@example.com")
    _criar_monitoramento(
        application,
        user,
        "Cadeira Gamer",
        "Cadeira Gamer Reclinável",
        "KaBuM",
        Decimal("500.00"),
        valor=Decimal("20"),
    )
    chamadas = []

    def comparar_bloqueado(*_args, **_kwargs):
        chamadas.append(True)
        return {"do_cache": False, "lojas_status": {"kabum": "blocked"}, "produtos": []}

    monkeypatch.setattr(monitoramento_service, "comparar", comparar_bloqueado)
    agora = datetime(2026, 10, 3, 12)
    assert monitoramento_service.verificar_precos(application, agora)["consultas"] == 0
    assert len(chamadas) == 1
    with application.app_context():
        control = ControleVerificacaoLoja.query.filter_by(loja="kabum").one()
        assert control.falhas_consecutivas == 1
        assert control.proxima_permitida == agora + timedelta(hours=1)
        assert control.lease_ate is None
    assert monitoramento_service.verificar_precos(application, agora)["consultas"] == 0
    assert len(chamadas) == 1
    assert monitoramento_service.verificar_precos(
        application, agora + timedelta(hours=1)
    )["consultas"] == 0
    assert monitoramento_service.verificar_precos(
        application, agora + timedelta(hours=3)
    )["consultas"] == 0
    assert len(chamadas) == 3
    with application.app_context():
        control = ControleVerificacaoLoja.query.filter_by(loja="kabum").one()
        assert control.falhas_consecutivas == 3
        assert control.bloqueada_ate == agora + timedelta(hours=9)
    assert monitoramento_service.verificar_precos(
        application, agora + timedelta(hours=8)
    )["consultas"] == 0
    assert len(chamadas) == 3


def test_alerta_pode_enviar_email_assincrono_pelo_servico_existente(
    application, make_user, monkeypatch
):
    from orcatech import email_service, monitoramento_service

    user = make_user("Email", "monitor-alert-email@example.com")
    _criar_monitoramento(
        application,
        user,
        "Mouse Gamer M220",
        "Mouse Gamer USB M220",
        "Amazon",
        Decimal("100.00"),
        valor=Decimal("10.00"),
    )
    enviados = []

    class InlineExecutor:
        def submit(self, func, *args):
            func(*args)

    class FakeSMTP:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def send_message(self, mensagem):
            enviados.append(mensagem)

    monkeypatch.setattr(email_service, "executor", InlineExecutor())
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    application.config.update(
        ALERTAS_PRECO_POR_EMAIL=True,
        SMTP_HOST="smtp.example",
        SMTP_PORT="587",
        SMTP_USERNAME="",
        SMTP_PASSWORD="",
        SMTP_USE_TLS=False,
        SMTP_FROM="alertas@example.com",
        MONITORAMENTO_JITTER_SEGUNDOS=0,
    )
    monkeypatch.setattr(
        monitoramento_service,
        "comparar",
        lambda *_args, **_kwargs: {
            "do_cache": False,
            "lojas_status": {"amazon": "success"},
            "produtos": [{
                "site": "Amazon",
                "nome": "Mouse Gamer USB M220",
                "preco": 80,
                "link": "https://www.amazon.com.br/dp/M220",
            }],
        },
    )

    result = monitoramento_service.verificar_precos(
        application, datetime(2026, 10, 3, 12)
    )
    assert result["alertas"] == 1
    assert len(enviados) == 1
    assert enviados[0]["Subject"] == "Queda de preço: Mouse Gamer USB M220"
    assert "R$ 80,00" in enviados[0].get_content()
    with application.app_context():
        envio = EnvioEmail.query.one()
        assert envio.orcamento_id is None
        assert envio.sucesso is True


def test_queda_compara_tambem_preco_de_orcamento_aberto(
    application, make_user, monkeypatch
):
    from orcatech import monitoramento_service

    user = make_user("Budget reference", "monitor-budget-reference@example.com")
    monitor_id = _criar_monitoramento(
        application,
        user,
        "SSD Kingston NV2 1TB",
        "SSD Kingston NV2 1TB",
        "Amazon",
        Decimal("120.00"),
        percentual=Decimal("10"),
    )
    with application.app_context():
        monitor = db.session.get(Monitoramento, monitor_id)
        cotacao = Cotacao.query.filter_by(nome_produto=monitor.nome_modelo).first()
        if cotacao is None:
            cotacao = Cotacao(
                produto_busca_id=monitor.produto_busca_id,
                fornecedor_id=monitor.fornecedor_id,
                nome_produto=monitor.nome_modelo,
                preco=150.00,
                origem="scraping",
            )
            db.session.add(cotacao)
            db.session.flush()
        budget = Orcamento(
            numero=Orcamento.gerar_numero(),
            usuario_id=user.id,
            status="rascunho",
        )
        db.session.add(budget)
        db.session.flush()
        db.session.add(OrcamentoItem(
            orcamento_id=budget.id,
            produto_busca_id=monitor.produto_busca_id,
            quantidade=1,
            cotacao_escolhida_id=cotacao.id,
        ))
        db.session.commit()

    monkeypatch.setattr(
        monitoramento_service,
        "comparar",
        lambda *_args, **_kwargs: {
            "do_cache": False,
            "lojas_status": {"amazon": "success"},
            "produtos": [{
                "site": "Amazon",
                "nome": "Kingston NV2 SSD 1TB",
                "preco": 130.00,
                "link": "https://www.amazon.com.br/dp/NV2",
            }],
        },
    )
    result = monitoramento_service.verificar_precos(
        application, datetime(2026, 10, 3, 12)
    )
    assert result["alertas"] == 1
    with application.app_context():
        alerta = AlertaPreco.query.one()
        assert alerta.preco_anterior == Decimal("150.00")
        assert alerta.origem_referencia == "orcamento"


def test_monitoramento_e_alertas_sao_isolados_por_usuario(
    client, application, make_user, login_as, csrf_token_for
):
    owner = make_user("Owner", "monitor-owner@example.com")
    other = make_user("Other", "monitor-other@example.com")
    monitor_id = _criar_monitoramento(
        application,
        owner,
        "Mouse Gamer M220",
        "Mouse Gamer USB M220",
        "Amazon",
        Decimal("100.00"),
        percentual=Decimal("10"),
    )
    with application.app_context():
        monitor = db.session.get(Monitoramento, monitor_id)
        db.session.add(AlertaPreco(
            monitoramento_id=monitor.id,
            preco_anterior=Decimal("100.00"),
            preco_novo=Decimal("90.00"),
            reducao=Decimal("10.00"),
            origem_referencia="monitoramento",
        ))
        db.session.commit()
        alerta_id = AlertaPreco.query.one().id

    login_as(client, other.email)
    page = client.get("/monitoramentos")
    assert page.status_code == 200
    assert b"Mouse Gamer USB M220" not in page.data
    response = client.post(
        f"/monitoramentos/{monitor_id}/desativar",
        data={"csrf_token": csrf_token_for("/")},
    )
    assert response.status_code == 404
    response = client.post(
        f"/monitoramentos/alertas/{alerta_id}/ler",
        data={"csrf_token": csrf_token_for("/")},
    )
    assert response.status_code == 404

    with application.app_context():
        assert db.session.get(Monitoramento, monitor_id).ativo is True
        assert db.session.get(AlertaPreco, alerta_id).lido_em is None


def test_criar_monitoramento_exige_login_csrf_e_um_gatilho(
    client, make_user, login_as, csrf_token_for
):
    anonimo = client.post(
        "/monitoramentos/criar",
        data={"csrf_token": csrf_token_for("/login")},
    )
    assert anonimo.status_code == 302
    user = make_user("Creator", "monitor-create@example.com")
    login_as(client, user.email)
    csrf = csrf_token_for("/")
    payload = {
        "termo_busca": "SSD Kingston 1TB NV2",
        "nome_modelo": "SSD Kingston NV2 1TB",
        "fornecedor": "Amazon",
        "preco_referencia": "500.00",
        "gatilho_percentual": "10",
        "gatilho_valor": "25",
    }
    sem_csrf = client.post("/monitoramentos/criar", data=payload)
    assert sem_csrf.status_code == 400
    response = client.post(
        "/monitoramentos/criar",
        data={**payload, "csrf_token": csrf},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Informe exatamente um gatilho".encode() in response.data

    response = client.post(
        "/monitoramentos/criar",
        data={
            **payload,
            "gatilho_valor": "",
            "csrf_token": csrf,
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Monitoramento de preço criado".encode() in response.data
