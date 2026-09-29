from orcatech.models import Cotacao, Fornecedor, Orcamento, OrcamentoItem, ProdutoBusca, db

from .conftest import csrf_token


def _make_budget(owner):
    from orcatech.app import app

    with app.app_context():
        supplier = Fornecedor(nome="Loja Online", tipo="online")
        product = ProdutoBusca(nome_pesquisado="Notebook")
        db.session.add_all((supplier, product))
        db.session.flush()
        quote = Cotacao(
            produto_busca_id=product.id,
            fornecedor_id=supplier.id,
            nome_produto="Notebook de teste",
            preco=1000,
        )
        budget = Orcamento(
            numero=f"ORC-{owner.id:08d}",
            usuario_id=owner.id,
            solicitante=owner.nome,
            status="rascunho",
        )
        db.session.add_all((quote, budget))
        db.session.flush()
        item = OrcamentoItem(
            orcamento_id=budget.id,
            produto_busca_id=product.id,
            cotacao_escolhida_id=quote.id,
            quantidade=1,
        )
        db.session.add(item)
        db.session.commit()
        ids = budget.id, item.id
        db.session.expunge_all()
    return ids


def test_user_cannot_change_another_users_budget_item(client, make_user, login_as):
    from orcatech.app import app

    owner = make_user("Ana", "ana@example.com")
    _, item = _make_budget(owner)
    make_user("Bruno", "bruno@example.com")
    login_as(client, "bruno@example.com")

    response = client.post(
        f"/orcamento/item/{item}/quantidade",
        data={"csrf_token": csrf_token(client), "quantidade": "99"},
    )
    assert response.status_code == 404
    with app.app_context():
        assert db.session.get(OrcamentoItem, item).quantidade == 1


def test_user_cannot_remove_another_users_item(client, make_user, login_as):
    from orcatech.app import app

    owner = make_user("Ana", "ana@example.com")
    make_user("Bruno", "bruno@example.com")
    _, item = _make_budget(owner)
    login_as(client, "bruno@example.com")

    response = client.post(
        f"/orcamento/item/{item}/remover",
        data={"csrf_token": csrf_token(client)},
    )
    assert response.status_code == 404
    with app.app_context():
        assert db.session.get(OrcamentoItem, item) is not None


def test_user_cannot_download_another_users_budget_pdf(client, make_user, login_as):
    owner = make_user("Ana", "ana@example.com")
    make_user("Bruno", "bruno@example.com")
    budget, _ = _make_budget(owner)
    login_as(client, "bruno@example.com")

    response = client.get(f"/orcamento/pdf/{budget}")
    assert response.status_code == 404


def test_owner_can_access_own_draft_and_cannot_read_other_draft(
    client, make_user, login_as, monkeypatch, tmp_path
):
    owner = make_user("Ana", "ana@example.com")
    other = make_user("Bruno", "bruno@example.com")
    budget, _ = _make_budget(owner)
    login_as(client, "ana@example.com")

    cart = client.get("/orcamento/carrinho")
    assert cart.status_code == 200
    assert b"Notebook de teste" in cart.data
    from orcatech import orcamento_routes

    pdf_path = tmp_path / "owned-budget.pdf"
    pdf_path.write_bytes(b"%PDF test")
    monkeypatch.setattr(orcamento_routes, "gerar_pdf_orcamento", lambda _: str(pdf_path))
    assert client.get(f"/orcamento/pdf/{budget}").status_code == 200

    client.post("/logout", data={"csrf_token": csrf_token(client, "/")})
    login_as(client, "bruno@example.com")
    cart = client.get("/orcamento/carrinho")
    assert cart.status_code == 200
    assert b"Notebook de teste" not in cart.data


def test_active_draft_is_scoped_to_current_user(application, make_user):
    from flask_login import login_user

    from orcatech.orcamento_service import get_orcamento_ativo

    first = make_user("Ana", "ana@example.com")
    second = make_user("Bruno", "bruno@example.com")
    with application.test_request_context("/"):
        login_user(first)
        first_draft = get_orcamento_ativo()
        first_user_id = first.id
        first_draft_user_id, first_draft_id = first_draft.usuario_id, first_draft.id
    with application.test_request_context("/"):
        login_user(second)
        second_draft = get_orcamento_ativo()
        second_user_id = second.id
        second_draft_user_id, second_draft_id = second_draft.usuario_id, second_draft.id

    assert first_draft_user_id == first_user_id
    assert second_draft_user_id == second_user_id
    assert first_draft_id != second_draft_id
