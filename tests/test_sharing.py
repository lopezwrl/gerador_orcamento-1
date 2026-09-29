from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs

from orcatech.models import Cotacao, EnvioEmail, Fornecedor, Orcamento, OrcamentoItem, ProdutoBusca, db

from .conftest import csrf_token

def make_budget(application, owner, status="aguardando_aprovacao"):
    with application.app_context():
        number = Orcamento.query.count() + 1
        supplier = Fornecedor(nome=f"Compartilhamento {owner.id}-{number}", tipo="online")
        product = ProdutoBusca(nome_pesquisado="Monitor seguro")
        db.session.add_all((supplier, product))
        db.session.flush()
        quote = Cotacao(
            produto_busca_id=product.id,
            fornecedor_id=supplier.id,
            nome_produto="Monitor IPS 27 polegadas",
            preco=899.90,
            frete=15.50,
            link="https://loja.example/monitor",
        )
        budget = Orcamento(
            numero=f"ORC-SHARE-{owner.id}-{number}",
            usuario_id=owner.id,
            solicitante="Nome Interno Solicitante",
            status=status,
            validade=date.today() + timedelta(days=10),
            condicoes_comerciais="Condição pública de pagamento",
            observacoes="OBSERVACAO_INTERNA_NAO_PUBLICAR",
        )
        db.session.add_all((quote, budget))
        db.session.flush()
        item = OrcamentoItem(
            orcamento_id=budget.id,
            produto_busca_id=product.id,
            cotacao_escolhida_id=quote.id,
            quantidade=1,
        )
        if status != "rascunho":
            item.snapshot_nome_produto = quote.nome_produto
            item.snapshot_fornecedor_nome = supplier.nome
            item.snapshot_preco_unit = 899.90
            item.snapshot_frete = 15.50
            item.snapshot_link = quote.link
        db.session.add(item)
        db.session.commit()
        result = budget.id, item.id
        db.session.expunge_all()
        return result


def _csrf(client):
    return csrf_token(client, "/")


def test_public_link_is_read_only_and_excludes_internal_data(
    client, application, make_user, login_as
):
    owner = make_user("Pessoa Interna", "owner-share@example.com")
    budget_id, _ = make_budget(application, owner)
    login_as(client, owner.email)
    assert client.get(f"/orcamento/{budget_id}").status_code == 200
    response = client.post(
        f"/orcamento/{budget_id}/compartilhar",
        data={"csrf_token": _csrf(client)},
    )
    assert response.status_code == 302
    with application.app_context():
        budget = db.session.get(Orcamento, budget_id)
        token = budget.share_token
        assert budget.share_expira_em.date() == date.today() + timedelta(days=7)
    client.post("/logout", data={"csrf_token": _csrf(client)})

    public_response = client.get(f"/p/{token}")
    assert public_response.status_code == 200
    assert b'name="robots" content="noindex, nofollow"' in public_response.data
    assert b"Monitor IPS 27 polegadas" in public_response.data
    assert "Condição pública de pagamento".encode() in public_response.data
    assert b"OBSERVACAO_INTERNA_NAO_PUBLICAR" not in public_response.data
    assert b"Nome Interno Solicitante" not in public_response.data
    assert b"owner-share@example.com" not in public_response.data
    assert b"Hist" not in public_response.data
    assert public_response.headers["Cache-Control"] == "no-store, private"
    assert client.post(f"/p/{token}").status_code != 200


def test_share_create_regenerate_revoke_and_owner_permissions(
    client, application, make_user, login_as
):
    owner = make_user("Owner", "owner-manage-share@example.com")
    other = make_user("Other", "other-manage-share@example.com")
    budget_id, _ = make_budget(application, owner)
    login_as(client, other.email)
    denied = client.post(
        f"/orcamento/{budget_id}/compartilhar",
        data={"csrf_token": _csrf(client)},
    )
    assert denied.status_code == 404
    client.post("/logout", data={"csrf_token": _csrf(client)})
    login_as(client, owner.email)
    client.post(
        f"/orcamento/{budget_id}/compartilhar",
        data={"csrf_token": _csrf(client)},
    )
    with application.app_context():
        old_token = db.session.get(Orcamento, budget_id).share_token
    detail = client.get(f"/orcamento/{budget_id}")
    assert b"wa.me/?text=" in detail.data
    share_link = detail.data.decode("utf-8").split("href=\"https://wa.me/?text=", 1)[1].split('"', 1)[0]
    whatsapp_query = parse_qs("text=" + share_link)
    assert "Orçamento ORC-SHARE" in whatsapp_query["text"][0]

    client.post(
        f"/orcamento/{budget_id}/compartilhar/regenerar",
        data={"csrf_token": _csrf(client)},
    )
    with application.app_context():
        budget = db.session.get(Orcamento, budget_id)
        new_token = budget.share_token
        assert new_token != old_token
        assert not budget.share_revogado
    assert client.get(f"/p/{old_token}").status_code == 404
    client.post(
        f"/orcamento/{budget_id}/compartilhar/revogar",
        data={"csrf_token": _csrf(client)},
    )
    assert client.get(f"/p/{new_token}").status_code == 404


def test_invalid_expired_and_revoked_tokens_return_same_not_found(
    client, application, make_user, login_as
):
    owner = make_user("Owner", "owner-share-status@example.com")
    expired_id, _ = make_budget(application, owner)
    revoked_id, _ = make_budget(application, owner)
    with application.app_context():
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        expired = db.session.get(Orcamento, expired_id)
        expired.share_token = "expired-token"
        expired.share_expira_em = now - timedelta(seconds=1)
        revoked = db.session.get(Orcamento, revoked_id)
        revoked.share_token = "revoked-token"
        revoked.share_expira_em = now + timedelta(days=1)
        revoked.share_revogado = True
        db.session.commit()
    invalid_response = client.get("/p/does-not-exist")
    expired_response = client.get("/p/expired-token")
    revoked_response = client.get("/p/revoked-token")
    assert invalid_response.status_code == expired_response.status_code == 404
    assert invalid_response.status_code == revoked_response.status_code == 404
    assert invalid_response.data == expired_response.data == revoked_response.data


def test_draft_cannot_be_shared(client, application, make_user, login_as):
    owner = make_user("Owner", "owner-draft-share@example.com")
    budget_id, _ = make_budget(application, owner, status="rascunho")
    login_as(client, owner.email)
    response = client.post(
        f"/orcamento/{budget_id}/compartilhar",
        data={"csrf_token": _csrf(client)},
    )
    assert response.status_code == 403


def test_public_endpoint_is_rate_limited_per_ip(
    client, application, make_user, monkeypatch
):
    owner = make_user("Owner", "owner-public-limit@example.com")
    budget_id, _ = make_budget(application, owner)
    with application.app_context():
        budget = db.session.get(Orcamento, budget_id)
        budget.share_token = "rate-limit-token"
        budget.share_expira_em = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
        db.session.commit()
    monkeypatch.setitem(application.config, "RATELIMIT_ENABLED", True)
    responses = [client.get("/p/rate-limit-token") for _ in range(61)]
    assert responses[-1].status_code == 429


class _InlineExecutor:
    def submit(self, function, *args, **kwargs):
        function(*args, **kwargs)


class _DeferredExecutor:
    def __init__(self):
        self.tasks = []

    def submit(self, function, *args, **kwargs):
        self.tasks.append((function, args, kwargs))

    def run_pending(self):
        tasks, self.tasks = self.tasks, []
        for function, args, kwargs in tasks:
            function(*args, **kwargs)


class _FakeSMTP:
    sent = []
    logged_in = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def starttls(self, context):
        self.context = context

    def login(self, username, password):
        self.logged_in.append((username, password))

    def send_message(self, message):
        self.sent.append(message)


def test_email_is_queued_with_pdf_and_records_smtp_result(
    client, application, make_user, login_as, monkeypatch, tmp_path
):
    from orcatech import email_service, gerar_pdf_orcamento

    owner = make_user("Owner", "owner-email@example.com")
    budget_id, _ = make_budget(application, owner)
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF simulated")
    executor = _DeferredExecutor()
    monkeypatch.setattr(email_service, "executor", executor)
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(gerar_pdf_orcamento, "PASTA_PDF", str(tmp_path))
    monkeypatch.setattr(
        gerar_pdf_orcamento,
        "gerar_pdf_orcamento",
        lambda _budget, caminho_saida=None: str(pdf_path),
    )
    application.config.update(
        SMTP_HOST="smtp.example",
        SMTP_PORT="587",
        SMTP_USERNAME="smtp-user@example.com",
        SMTP_PASSWORD="smtp-secret-not-logged",
        SMTP_USE_TLS=True,
        SMTP_FROM="orcatech@example.com",
    )
    _FakeSMTP.sent.clear()
    _FakeSMTP.logged_in.clear()
    login_as(client, owner.email)
    response = client.post(
        f"/orcamento/{budget_id}/email",
        data={
            "csrf_token": _csrf(client),
            "destinatario": "destino@example.com",
        },
    )
    assert response.status_code == 302
    assert len(executor.tasks) == 1
    with application.app_context():
        assert EnvioEmail.query.one().sucesso is None
    executor.run_pending()
    assert len(_FakeSMTP.sent) == 1
    sent = _FakeSMTP.sent[0]
    assert sent["To"] == "destino@example.com"
    attachments = list(sent.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_content_type() == "application/pdf"
    assert attachments[0].get_payload(decode=True) == b"%PDF simulated"
    assert _FakeSMTP.logged_in == [("smtp-user@example.com", "smtp-secret-not-logged")]
    with application.app_context():
        entry = EnvioEmail.query.one()
        assert entry.sucesso is True
        assert entry.erro is None
        assert entry.destinatario == "destino@example.com"


def test_email_rejects_bad_addresses_and_enforces_budget_hour_limit(
    client, application, make_user, login_as, monkeypatch, tmp_path
):
    from orcatech import email_service, gerar_pdf_orcamento

    owner = make_user("Owner", "owner-email-limit@example.com")
    budget_id, _ = make_budget(application, owner)
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF")
    monkeypatch.setattr(email_service, "executor", _InlineExecutor())
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(gerar_pdf_orcamento, "PASTA_PDF", str(tmp_path))
    monkeypatch.setattr(
        gerar_pdf_orcamento,
        "gerar_pdf_orcamento",
        lambda _budget, caminho_saida=None: str(pdf_path),
    )
    application.config["ORCAMENTO_MAX_EMAILS_HORA"] = 1
    application.config.update(
        SMTP_HOST="smtp.example",
        SMTP_PORT="587",
        SMTP_USERNAME="",
        SMTP_PASSWORD="",
        SMTP_USE_TLS=False,
        SMTP_FROM="orcatech@example.com",
    )
    login_as(client, owner.email)
    invalid = client.post(
        f"/orcamento/{budget_id}/email",
        data={"csrf_token": _csrf(client), "destinatario": "nao-e-email"},
    )
    assert invalid.status_code == 302
    with application.app_context():
        assert EnvioEmail.query.count() == 0
    first = client.post(
        f"/orcamento/{budget_id}/email",
        data={"csrf_token": _csrf(client), "destinatario": "destino@example.com"},
    )
    second = client.post(
        f"/orcamento/{budget_id}/email",
        data={"csrf_token": _csrf(client), "destinatario": "destino@example.com"},
    )
    assert first.status_code == second.status_code == 302
    with application.app_context():
        assert EnvioEmail.query.count() == 1


def test_email_failure_is_persisted_and_visible(
    client, application, make_user, login_as, monkeypatch
):
    from orcatech import email_service

    owner = make_user("Owner", "owner-email-failure@example.com")
    budget_id, _ = make_budget(application, owner)
    monkeypatch.setattr(email_service, "executor", _InlineExecutor())
    application.config.update(
        SMTP_HOST="",
        SMTP_PORT="587",
        SMTP_USERNAME="",
        SMTP_PASSWORD="",
        SMTP_USE_TLS=False,
        SMTP_FROM="",
    )
    login_as(client, owner.email)
    response = client.post(
        f"/orcamento/{budget_id}/email",
        data={
            "csrf_token": _csrf(client),
            "destinatario": "destino@example.com",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Falha".encode() in response.data
    with application.app_context():
        envio = EnvioEmail.query.one()
        assert envio.sucesso is False
        assert envio.erro == "Falha no envio (ValueError)."


def test_workflow_notifies_approver_and_requester_asynchronously(
    client, application, make_user, login_as, monkeypatch
):
    from orcatech import email_service

    owner = make_user("Owner", "owner-notify@example.com")
    approver = make_user("Approver", "approver-notify@example.com", papel="aprovador")
    budget_id, _ = make_budget(application, owner, status="rascunho")
    monkeypatch.setattr(email_service, "executor", _InlineExecutor())
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)
    application.config.update(
        ORCAMENTO_MAX_EMAILS_HORA=5,
        SMTP_HOST="smtp.example",
        SMTP_PORT="587",
        SMTP_USERNAME="",
        SMTP_PASSWORD="",
        SMTP_USE_TLS=False,
        SMTP_FROM="orcatech@example.com",
    )
    _FakeSMTP.sent.clear()
    login_as(client, owner.email)
    finalized = client.post(
        "/orcamento/finalizar",
        data={"csrf_token": csrf_token(client, "/orcamento/carrinho")},
    )
    assert finalized.status_code == 302
    assert "Acesse o sistema: http://127.0.0.1:5000/aprovacoes" in _FakeSMTP.sent[0].get_content()
    with application.app_context():
        assert EnvioEmail.query.count() == 1
        assert EnvioEmail.query.one().destinatario == approver.email
    client.post("/logout", data={"csrf_token": _csrf(client)})
    login_as(client, approver.email)
    decision = client.post(
        f"/orcamento/{budget_id}/decisao",
        data={
            "csrf_token": csrf_token(client, f"/orcamento/{budget_id}"),
            "decisao": "aprovado",
        },
    )
    assert decision.status_code == 302
    assert f"Acesse o sistema: http://127.0.0.1:5000/orcamento/{budget_id}" in _FakeSMTP.sent[1].get_content()
    with application.app_context():
        assert EnvioEmail.query.count() == 2
        recipients = {email.destinatario for email in EnvioEmail.query.all()}
        assert recipients == {owner.email, approver.email}
