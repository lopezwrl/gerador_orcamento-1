from datetime import date, timedelta
from decimal import Decimal

import pytest
from pypdf import PdfReader

from orcatech.models import (
    Aprovacao,
    Cotacao,
    Fornecedor,
    Orcamento,
    OrcamentoItem,
    ProdutoBusca,
    db,
)
from orcatech.orcamento_workflow import (
    ErroWorkflow,
    TRANSICOES_PERMITIDAS,
    pode_transicionar,
    transicionar,
)

from .conftest import csrf_token


def _make_budget(owner, status="rascunho", validade=None):
    from orcatech.app import app

    with app.app_context():
        fornecedor_nome = f"Loja {owner.id}-{Orcamento.query.count() + 1}"
        supplier = Fornecedor(nome=fornecedor_nome, tipo="online")
        product = ProdutoBusca(nome_pesquisado="Notebook de teste")
        db.session.add_all((supplier, product))
        db.session.flush()
        quote = Cotacao(
            produto_busca_id=product.id,
            fornecedor_id=supplier.id,
            nome_produto="Notebook real 16 GB",
            preco=1234.56,
            frete=18.90,
            link="https://loja.example/produto",
        )
        budget = Orcamento(
            numero=f"ORC-WF-{owner.id:06d}-{Orcamento.query.count() + 1:04d}",
            usuario_id=owner.id,
            solicitante=owner.nome,
            status=status,
            validade=validade,
            condicoes_comerciais="Pagamento à vista",
            observacoes="Conferir compatibilidade",
        )
        db.session.add_all((quote, budget))
        db.session.flush()
        item = OrcamentoItem(
            orcamento_id=budget.id,
            produto_busca_id=product.id,
            cotacao_escolhida_id=quote.id,
            quantidade=2,
        )
        db.session.add(item)
        if status in {"aguardando_aprovacao", "aprovado", "reprovado", "compra_realizada"}:
            item.snapshot_nome_produto = quote.nome_produto
            item.snapshot_fornecedor_nome = supplier.nome
            item.snapshot_preco_unit = Decimal("1234.56")
            item.snapshot_frete = Decimal("18.90")
            item.snapshot_link = quote.link
        db.session.commit()
        ids = budget.id, item.id, quote.id, supplier.id
        db.session.expunge_all()
    return ids


@pytest.mark.parametrize(
    ("de", "para"),
    [
        (de, para)
        for de, destinos in TRANSICOES_PERMITIDAS.items()
        for para in destinos
    ],
)
def test_workflow_accepts_only_declared_transitions(application, make_user, de, para):
    from flask_login import login_user

    ator = make_user("Dono", f"{de}-{para}@example.com", papel="admin")
    with application.test_request_context("/"):
        login_user(ator)
        assert pode_transicionar(de, para, ator)


@pytest.mark.parametrize(
    ("de", "para"),
    [
        (de, para)
        for de, destinos in TRANSICOES_PERMITIDAS.items()
        for para in set(TRANSICOES_PERMITIDAS) - destinos
    ],
)
def test_workflow_rejects_undeclared_transitions(application, make_user, de, para):
    ator = make_user("Dono", f"inv-{de}-{para}@example.com", papel="admin")
    with application.app_context():
        budget = Orcamento(
            numero=Orcamento.gerar_numero(),
            usuario_id=ator.id,
            status=de,
        )
        db.session.add(budget)
        db.session.commit()
        with pytest.raises(ErroWorkflow):
            transicionar(budget, para, ator)
        assert budget.status == de


def test_finalize_records_each_transition_and_freezes_prices(
    client, application, make_user, login_as
):
    owner = make_user("Ana", "ana-workflow@example.com")
    budget_id, item_id, quote_id, supplier_id = _make_budget(owner)
    login_as(client, owner.email)

    response = client.post(
        "/orcamento/finalizar",
        data={
            "csrf_token": csrf_token(client, "/orcamento/carrinho"),
            "condicoes_comerciais": "Pagamento em 30 dias",
        },
    )
    assert response.status_code == 302
    with application.app_context():
        budget = db.session.get(Orcamento, budget_id)
        quote = db.session.get(Cotacao, quote_id)
        item = db.session.get(OrcamentoItem, item_id)
        fornecedor_snapshot = db.session.get(Fornecedor, supplier_id).nome
        events = list(budget.historico)
        assert budget.status == "aguardando_aprovacao"
        assert budget.validade == date.today() + timedelta(days=15)
        assert [(event.status_de, event.status_para) for event in events] == [
            ("rascunho", "em_cotacao"),
            ("em_cotacao", "aguardando_aprovacao"),
        ]
        total_congelado = budget.total
        quote.preco = 9999
        quote.frete = 999
        db.session.get(Fornecedor, supplier_id).nome = "Loja renomeada"
        db.session.commit()
        assert budget.total == total_congelado == Decimal("2488.02")
        assert item.nome_produto == "Notebook real 16 GB"
        assert item.fornecedor_nome == fornecedor_snapshot


def test_approver_queue_and_decision_are_role_gated(
    client, application, make_user, login_as
):
    owner = make_user("Ana", "ana-queue@example.com")
    approver = make_user("Bia", "bia-queue@example.com", papel="aprovador")
    budget_id, _, _, _ = _make_budget(
        owner, status="aguardando_aprovacao", validade=date.today() + timedelta(days=4)
    )
    login_as(client, owner.email)
    assert client.get("/aprovacoes").status_code == 403
    denied = client.post(
        f"/orcamento/{budget_id}/decisao",
        data={"csrf_token": csrf_token(client, "/"), "decisao": "aprovado"},
    )
    assert denied.status_code == 403

    client.post("/logout", data={"csrf_token": csrf_token(client, "/")})
    login_as(client, approver.email)
    queue = client.get("/aprovacoes?q=ORC-WF")
    assert queue.status_code == 200
    assert b"ORC-WF" in queue.data
    detail = client.get(f"/orcamento/{budget_id}")
    assert detail.status_code == 200
    response = client.post(
        f"/orcamento/{budget_id}/decisao",
        data={
        "csrf_token": csrf_token(client, "/"),
            "decisao": "aprovado",
            "comentario": "Aprovado conforme orçamento.",
        },
    )
    assert response.status_code == 302
    with application.app_context():
        budget = db.session.get(Orcamento, budget_id)
        assert budget.status == "aprovado"
        assert [(event.status_de, event.status_para) for event in budget.historico][-1] == (
            "aguardando_aprovacao",
            "aprovado",
        )
        assert budget.aprovacoes[-1].comentario == "Aprovado conforme orçamento."


def test_requester_and_admin_cannot_self_approve_by_default(
    client, application, make_user, login_as, monkeypatch
):
    monkeypatch.setitem(application.config, "ADMIN_PODE_AUTOAPROVAR", False)
    approver = make_user("Solicitante", "self-approver@example.com", papel="aprovador")
    budget_id, _, _, _ = _make_budget(
        approver, status="aguardando_aprovacao", validade=date.today() + timedelta(days=3)
    )
    login_as(client, approver.email)
    response = client.post(
        f"/orcamento/{budget_id}/decisao",
        data={
            "csrf_token": csrf_token(client, "/"),
            "decisao": "aprovado",
        },
    )
    assert response.status_code == 302
    with application.app_context():
        assert db.session.get(Orcamento, budget_id).status == "aguardando_aprovacao"
        assert Aprovacao.query.count() == 0

    client.post("/logout", data={"csrf_token": csrf_token(client, "/")})
    admin = make_user("Admin", "self-admin@example.com", papel="admin")
    budget_id, _, _, _ = _make_budget(
        admin, status="aguardando_aprovacao", validade=date.today() + timedelta(days=3)
    )
    login_as(client, admin.email)
    response = client.post(
        f"/orcamento/{budget_id}/decisao",
        data={
            "csrf_token": csrf_token(client, "/"),
            "decisao": "aprovado",
        },
    )
    assert response.status_code == 302
    with application.app_context():
        assert db.session.get(Orcamento, budget_id).status == "aguardando_aprovacao"
    monkeypatch.setitem(application.config, "ADMIN_PODE_AUTOAPROVAR", True)
    response = client.post(
        f"/orcamento/{budget_id}/decisao",
        data={
            "csrf_token": csrf_token(client, f"/orcamento/{budget_id}"),
            "decisao": "aprovado",
        },
    )
    assert response.status_code == 302
    with application.app_context():
        assert db.session.get(Orcamento, budget_id).status == "aprovado"


def test_rejection_requires_comment_and_rejected_budget_can_be_reopened(
    client, application, make_user, login_as
):
    owner = make_user("Ana", "ana-rejection@example.com")
    approver = make_user("Bia", "bia-rejection@example.com", papel="aprovador")
    budget_id, item_id, _, _ = _make_budget(
        owner, status="aguardando_aprovacao", validade=date.today() + timedelta(days=2)
    )
    login_as(client, approver.email)
    rejected_without_comment = client.post(
        f"/orcamento/{budget_id}/decisao",
        data={
            "csrf_token": csrf_token(client, f"/orcamento/{budget_id}"),
            "decisao": "reprovado",
        },
    )
    assert rejected_without_comment.status_code == 302
    with application.app_context():
        budget = db.session.get(Orcamento, budget_id)
        assert budget.status == "aguardando_aprovacao"
        assert Aprovacao.query.count() == 0

    client.post("/logout", data={"csrf_token": csrf_token(client, "/")})
    login_as(client, approver.email)
    client.post(
        f"/orcamento/{budget_id}/decisao",
        data={
            "csrf_token": csrf_token(client, f"/orcamento/{budget_id}"),
            "decisao": "reprovado",
            "comentario": "Preço acima da política de compras.",
        },
    )
    client.post("/logout", data={"csrf_token": csrf_token(client, "/")})
    login_as(client, owner.email)
    response = client.post(
        f"/orcamento/{budget_id}/reabrir",
        data={"csrf_token": csrf_token(client, "/")},
    )
    assert response.status_code == 302
    with application.app_context():
        budget = db.session.get(Orcamento, budget_id)
        item = db.session.get(OrcamentoItem, item_id)
        assert budget.status == "rascunho"
        assert budget.historico[-1].status_para == "rascunho"
        assert item.snapshot_preco_unit is None


def test_expired_budget_requires_renewal_before_approval(
    client, application, make_user, login_as
):
    owner = make_user("Ana", "ana-expired@example.com")
    approver = make_user("Bia", "bia-expired@example.com", papel="aprovador")
    budget_id, _, _, _ = _make_budget(
        owner, status="aguardando_aprovacao", validade=date.today() - timedelta(days=1)
    )
    login_as(client, approver.email)
    response = client.post(
        f"/orcamento/{budget_id}/decisao",
        data={
            "csrf_token": csrf_token(client, f"/orcamento/{budget_id}"),
            "decisao": "aprovado",
        },
    )
    assert response.status_code == 302
    with application.app_context():
        assert db.session.get(Orcamento, budget_id).status == "aguardando_aprovacao"
    client.post("/logout", data={"csrf_token": csrf_token(client, "/")})
    login_as(client, owner.email)
    response = client.post(
        f"/orcamento/{budget_id}/renovar-validade",
        data={"csrf_token": csrf_token(client, f"/orcamento/{budget_id}")},
    )
    assert response.status_code == 302
    with application.app_context():
        budget = db.session.get(Orcamento, budget_id)
        assert budget.validade >= date.today()
        assert not budget.expirado


def test_approved_budget_cannot_be_edited(client, application, make_user, login_as):
    owner = make_user("Ana", "ana-readonly@example.com")
    budget_id, item_id, _, _ = _make_budget(owner, status="aprovado")
    login_as(client, owner.email)
    response = client.post(
        f"/orcamento/item/{item_id}/quantidade",
        data={
            "csrf_token": csrf_token(client, "/"),
            "quantidade": "9",
        },
    )
    assert response.status_code == 403
    with application.app_context():
        assert db.session.get(OrcamentoItem, item_id).quantidade == 2
    response = client.post(
        f"/orcamento/{budget_id}/compra-realizada",
        data={"csrf_token": csrf_token(client, "/")},
    )
    assert response.status_code == 302
    with application.app_context():
        budget = db.session.get(Orcamento, budget_id)
        assert budget.status == "compra_realizada"
        assert budget.historico[-1].status_para == "compra_realizada"


def test_pdf_contains_budget_snapshot_and_approval(application, make_user, tmp_path, monkeypatch):
    from orcatech import gerar_pdf_orcamento

    owner = make_user("Ana", "ana-pdf@example.com")
    approver = make_user("Bia", "bia-pdf@example.com", papel="aprovador")
    budget_id, _, _, _ = _make_budget(owner, status="aprovado")
    with application.app_context():
        budget = db.session.get(Orcamento, budget_id)
        db.session.add(
            Aprovacao(
                orcamento_id=budget.id,
                usuario_id=approver.id,
                decisao="aprovado",
                comentario="Aprovado com condição comercial.",
            )
        )
        db.session.commit()
        monkeypatch.setattr(gerar_pdf_orcamento, "PASTA_PDF", str(tmp_path))
        caminho = gerar_pdf_orcamento.gerar_pdf_orcamento(budget)
        texto = "\n".join(page.extract_text() or "" for page in PdfReader(caminho).pages)
        assert "ORC-WF" in texto
        assert "Notebook real 16 GB" in texto
        assert "Pagamento à vista" in texto
        assert "Aprovado por Bia" in texto
        assert "Aprovado com condição comercial" in texto


def test_pdf_marks_rejected_and_expired_budgets(application, make_user, tmp_path, monkeypatch):
    from orcatech import gerar_pdf_orcamento

    owner = make_user("Ana", "ana-watermark@example.com")
    rejected_id, _, _, _ = _make_budget(owner, status="reprovado")
    expired_id, _, _, _ = _make_budget(
        owner,
        status="aguardando_aprovacao",
        validade=date.today() - timedelta(days=1),
    )
    with application.app_context():
        monkeypatch.setattr(gerar_pdf_orcamento, "PASTA_PDF", str(tmp_path))
        rejected_path = gerar_pdf_orcamento.gerar_pdf_orcamento(
            db.session.get(Orcamento, rejected_id)
        )
        expired_path = gerar_pdf_orcamento.gerar_pdf_orcamento(
            db.session.get(Orcamento, expired_id)
        )
        rejected_text = "\n".join(
            page.extract_text() or "" for page in PdfReader(rejected_path).pages
        )
        expired_text = "\n".join(
            page.extract_text() or "" for page in PdfReader(expired_path).pages
        )
        assert "REPROVADO" in rejected_text
        assert "EXPIRADO" in expired_text
