from datetime import date
from decimal import Decimal

from orcatech.models import (
    CentroCusto,
    Cotacao,
    Departamento,
    Fornecedor,
    Orcamento,
    OrcamentoItem,
    PedidoCompra,
    ProdutoBusca,
    Usuario,
    db,
)

from .conftest import csrf_token


def _configure_enterprise(application, **overrides):
    application.config.update(
        FEATURE_EMPRESARIAL_ENABLED=True,
        ALCADA_APROVACAO_LIMITE=Decimal("10000.00"),
        ADMIN_PODE_AUTOAPROVAR=False,
        **overrides,
    )


def _create_unit(limit="50000.00", code="TEC"):
    department = Departamento(codigo=code, nome=f"Departamento {code}")
    db.session.add(department)
    db.session.flush()
    center = CentroCusto(
        codigo=f"CC-{code}",
        nome=f"Centro {code}",
        departamento_id=department.id,
        limite_gasto=Decimal(limit),
    )
    db.session.add(center)
    db.session.flush()
    return department, center


def _create_budget(owner, center, prices, status="rascunho"):
    department = center.departamento
    owner.departamento_id = department.id
    budget = Orcamento(
        numero=f"ORC-ENT-{Orcamento.query.count() + 1:04d}",
        usuario_id=owner.id,
        departamento_id=department.id,
        centro_custo_id=center.id,
        solicitante=owner.nome,
        status=status,
        validade=date.today(),
        condicoes_comerciais="Pagamento em 30 dias",
    )
    db.session.add(budget)
    db.session.flush()
    for index, (supplier_name, price, freight, quantity) in enumerate(prices):
        supplier = Fornecedor(nome=supplier_name, tipo="online")
        product = ProdutoBusca(nome_pesquisado=f"Produto {index}")
        db.session.add_all([supplier, product])
        db.session.flush()
        quote = Cotacao(
            produto_busca_id=product.id,
            fornecedor_id=supplier.id,
            nome_produto=f"Produto aprovado {index}",
            preco=price,
            frete=freight,
            link=f"https://loja.example/item-{index}",
        )
        db.session.add(quote)
        db.session.flush()
        item = OrcamentoItem(
            orcamento_id=budget.id,
            produto_busca_id=product.id,
            cotacao_escolhida_id=quote.id,
            quantidade=quantity,
        )
        if status in {"aguardando_aprovacao", "aprovado"}:
            item.snapshot_nome_produto = quote.nome_produto
            item.snapshot_fornecedor_nome = supplier.nome
            item.snapshot_preco_unit = Decimal(str(price))
            item.snapshot_frete = Decimal(str(freight))
            item.snapshot_link = quote.link
        db.session.add(item)
    db.session.commit()
    return budget.id


def test_enterprise_flag_hides_routes_by_default(client, application, make_user, login_as):
    user = make_user("Ana", "enterprise-off@example.com")
    login_as(client, user.email)

    assert client.get("/empresarial/estrutura").status_code == 404
    assert client.get("/empresarial/relatorios").status_code == 404


def test_admin_manages_departments_centers_and_user_profiles(
    client, application, make_user, login_as
):
    _configure_enterprise(application)
    admin = make_user("Admin", "enterprise-manage-admin@example.com", papel="admin")
    user = make_user("Colaborador", "enterprise-manage-user@example.com")
    login_as(client, admin.email)

    structure = client.get("/empresarial/estrutura")
    assert structure.status_code == 200
    assert b"Novo departamento" in structure.data
    created_department = client.post(
        "/empresarial/estrutura",
        data={
            "csrf_token": csrf_token(client, "/empresarial/estrutura"),
            "acao": "departamento",
            "codigo": "FIN",
            "nome": "Financeiro",
        },
    )
    assert created_department.status_code == 302
    with application.app_context():
        department = Departamento.query.filter_by(codigo="FIN").one()
        department_id = department.id

    created_center = client.post(
        "/empresarial/estrutura",
        data={
            "csrf_token": csrf_token(client, "/empresarial/estrutura"),
            "acao": "centro_custo",
            "departamento_id": str(department_id),
            "codigo": "FIN-01",
            "nome": "Operações",
            "limite_gasto": "25.000,50",
        },
    )
    assert created_center.status_code == 302
    with application.app_context():
        center = CentroCusto.query.filter_by(codigo="FIN-01").one()
        assert center.limite_gasto == Decimal("25000.50")

    users_page = client.get("/usuarios")
    assert users_page.status_code == 200
    updated = client.post(
        f"/usuarios/{user.id}/perfil",
        data={
            "csrf_token": csrf_token(client, "/usuarios"),
            "papel": "aprovador",
            "departamento_id": str(department_id),
        },
    )
    assert updated.status_code == 302
    with application.app_context():
        stored_user = db.session.get(Usuario, user.id)
        assert stored_user.papel == "aprovador"
        assert stored_user.departamento_id == department_id


def test_finalization_requires_unit_and_enforces_reserved_limit(
    client, application, make_user, login_as
):
    _configure_enterprise(application)
    owner = make_user("Ana", "enterprise-owner@example.com")
    approver = make_user("Aprovador", "enterprise-owner-approver@example.com", papel="aprovador")
    with application.app_context():
        department, center = _create_unit(limit="10000.00")
        existing_owner = db.session.get(Usuario, owner.id)
        db.session.get(Usuario, approver.id).departamento_id = department.id
        department_id, center_id = department.id, center.id
        existing_budget_id = _create_budget(
            existing_owner,
            center,
            [("Fornecedor existente", 7000, 0, 1)],
            status="aprovado",
        )
        draft_id = _create_budget(
            existing_owner,
            center,
            [("Fornecedor novo", 4000, 0, 1)],
        )
    login_as(client, owner.email)

    response = client.post(
        "/orcamento/finalizar",
        data={
            "csrf_token": csrf_token(client, "/orcamento/carrinho"),
            "departamento_id": str(department_id),
            "centro_custo_id": str(center_id),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"ultrapassaria" in response.data
    with application.app_context():
        assert db.session.get(Orcamento, existing_budget_id).status == "aprovado"
        assert db.session.get(Orcamento, draft_id).status == "rascunho"


def test_finalization_rejects_center_from_another_department(
    client, application, make_user, login_as
):
    _configure_enterprise(application)
    owner = make_user("Ana", "enterprise-dept@example.com")
    with application.app_context():
        department, center = _create_unit(code="D1")
        _, other_center = _create_unit(code="D2")
        department_id, other_center_id = department.id, other_center.id
        stored_owner = db.session.get(Usuario, owner.id)
        _create_budget(stored_owner, center, [("Fornecedor", 100, 0, 1)])
    login_as(client, owner.email)

    response = client.post(
        "/orcamento/finalizar",
        data={
            "csrf_token": csrf_token(client, "/orcamento/carrinho"),
            "departamento_id": str(department_id),
            "centro_custo_id": str(other_center_id),
        },
    )
    assert response.status_code == 302
    with application.app_context():
        budget = Orcamento.query.filter_by(usuario_id=owner.id).one()
        assert budget.status == "rascunho"


def test_finalization_rejects_budget_over_center_limit(
    client, application, make_user, login_as
):
    _configure_enterprise(application)
    owner = make_user("Ana", "enterprise-over-limit@example.com")
    with application.app_context():
        _, center = _create_unit(limit="10000.00", code="OVER")
        budget_id = _create_budget(
            db.session.get(Usuario, owner.id),
            center,
            [("Fornecedor", 10001, 0, 1)],
        )
        department_id, center_id = center.departamento_id, center.id
    login_as(client, owner.email)

    response = client.post(
        "/orcamento/finalizar",
        data={
            "csrf_token": csrf_token(client, "/orcamento/carrinho"),
            "departamento_id": str(department_id),
            "centro_custo_id": str(center_id),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"ultrapassa o limite total" in response.data
    with application.app_context():
        assert db.session.get(Orcamento, budget_id).status == "rascunho"


def test_non_admin_cannot_finalize_for_another_department(
    client, application, make_user, login_as
):
    _configure_enterprise(application)
    owner = make_user("Ana", "enterprise-other-unit@example.com")
    with application.app_context():
        own_department, own_center = _create_unit(code="OWN")
        other_department, other_center = _create_unit(code="OTHER")
        own_department_id = own_department.id
        _create_budget(
            db.session.get(Usuario, owner.id),
            own_center,
            [("Fornecedor", 100, 0, 1)],
        )
        other_department_id, other_center_id = other_department.id, other_center.id
    login_as(client, owner.email)

    response = client.post(
        "/orcamento/finalizar",
        data={
            "csrf_token": csrf_token(client, "/orcamento/carrinho"),
            "departamento_id": str(other_department_id),
            "centro_custo_id": str(other_center_id),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"pr\xc3\xb3prio departamento" in response.data
    with application.app_context():
        budget = Orcamento.query.filter_by(usuario_id=owner.id).one()
        assert budget.departamento_id == own_department_id
        assert budget.status == "rascunho"


def test_department_approval_alçada_and_queue_filters(
    client, application, make_user, login_as
):
    _configure_enterprise(application)
    owner = make_user("Solicitante", "enterprise-requester@example.com")
    approver = make_user("Aprovadora", "enterprise-approver@example.com", papel="aprovador")
    other_approver = make_user(
        "Outro departamento", "enterprise-other-approver@example.com", papel="aprovador"
    )
    admin = make_user("Diretoria", "enterprise-admin@example.com", papel="admin")
    with application.app_context():
        department, center = _create_unit(code="AP1")
        other_department, _ = _create_unit(code="AP2")
        center_id = center.id
        db.session.get(Usuario, approver.id).departamento_id = department.id
        db.session.get(Usuario, other_approver.id).departamento_id = other_department.id
        budget_id = _create_budget(
            db.session.get(Usuario, owner.id),
            center,
            [("Fornecedor alçada", 10000, 0, 1)],
            status="aguardando_aprovacao",
        )

    login_as(client, approver.email)
    queue = client.get("/aprovacoes")
    assert queue.status_code == 200
    assert b"ORC-ENT" in queue.data
    denied = client.get(f"/orcamento/{budget_id}")
    assert denied.status_code == 200

    client.post("/logout", data={"csrf_token": csrf_token(client, "/")})
    login_as(client, other_approver.email)
    assert b"ORC-ENT" not in client.get("/aprovacoes").data
    assert client.get(f"/orcamento/{budget_id}").status_code == 404

    client.post("/logout", data={"csrf_token": csrf_token(client, "/")})
    login_as(client, approver.email)
    approval = client.post(
        f"/orcamento/{budget_id}/decisao",
        data={
            "csrf_token": csrf_token(client, "/"),
            "decisao": "aprovado",
            "comentario": "Dentro da alçada departamental.",
        },
    )
    assert approval.status_code == 302
    with application.app_context():
        assert db.session.get(Orcamento, budget_id).status == "aprovado"

    client.post("/logout", data={"csrf_token": csrf_token(client, "/")})
    with application.app_context():
        admin_budget_id = _create_budget(
            db.session.get(Usuario, owner.id),
            db.session.get(CentroCusto, center_id),
            [("Fornecedor acima", 10001, 0, 1)],
            status="aguardando_aprovacao",
        )
        admin_budget_numero = db.session.get(Orcamento, admin_budget_id).numero
    login_as(client, admin.email)
    response = client.get("/aprovacoes")
    assert response.status_code == 200
    assert admin_budget_numero.encode() in response.data
    assert b"ORC-ENT-0001" not in response.data
    admin_approval = client.post(
        f"/orcamento/{admin_budget_id}/decisao",
        data={
            "csrf_token": csrf_token(client, "/"),
            "decisao": "aprovado",
            "comentario": "Acima da alçada departamental.",
        },
    )
    assert admin_approval.status_code == 302
    with application.app_context():
        assert db.session.get(Orcamento, admin_budget_id).status == "aprovado"


def test_buyer_emits_supplier_orders_and_tracks_delivery(
    client, application, make_user, login_as, monkeypatch, tmp_path
):
    _configure_enterprise(application)
    owner = make_user("Solicitante", "enterprise-po-owner@example.com")
    buyer = make_user("Compradora", "enterprise-buyer@example.com", papel="comprador")
    with application.app_context():
        _, center = _create_unit(code="PO1")
        budget_id = _create_budget(
            db.session.get(Usuario, owner.id),
            center,
            [
                ("Loja A", 100, 10, 1),
                ("Loja B", 200, 20, 2),
            ],
            status="aprovado",
        )
        budget = db.session.get(Orcamento, budget_id)
        budget.itens[0].cotacao_escolhida.fornecedor.nome = "Loja A renomeada"
        db.session.commit()
    login_as(client, buyer.email)
    response = client.post(
        f"/empresarial/orcamentos/{budget_id}/pedidos",
        data={"csrf_token": csrf_token(client, "/")},
    )
    assert response.status_code == 302

    with application.app_context():
        budget = db.session.get(Orcamento, budget_id)
        pedidos = list(budget.pedidos_compra)
        assert budget.status == "compra_realizada"
        assert len(pedidos) == 2
        assert sorted(pedido.total for pedido in pedidos) == [
            Decimal("110.00"),
            Decimal("420.00"),
        ]
        assert {pedido.snapshot_fornecedor_nome for pedido in pedidos} == {"Loja A", "Loja B"}
        assert all(pedido.itens[0].nome_produto.startswith("Produto aprovado") for pedido in pedidos)
        pedido_id = pedidos[0].id
        supplier_name = pedidos[0].snapshot_fornecedor_nome
        from orcatech.gerar_pdf_pedido_compra import gerar_pdf_pedido_compra

        rendered_pdf = tmp_path / "pedido-renderizado.pdf"
        gerar_pdf_pedido_compra(db.session.get(PedidoCompra, pedido_id), str(rendered_pdf))
        assert rendered_pdf.read_bytes().startswith(b"%PDF")

    orders_page = client.get(f"/empresarial/orcamentos/{budget_id}/pedidos")
    assert orders_page.status_code == 200
    assert supplier_name.encode() in orders_page.data
    order_detail = client.get(f"/empresarial/pedidos/{pedido_id}")
    assert order_detail.status_code == 200
    assert b"Atualizar pedido" in order_detail.data

    from orcatech import empresarial_routes

    pdf_path = tmp_path / "pedido.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")
    monkeypatch.setattr(
        empresarial_routes, "gerar_pdf_pedido_compra", lambda _: str(pdf_path)
    )
    pdf_response = client.get(f"/empresarial/pedidos/{pedido_id}/pdf")
    assert pdf_response.status_code == 200
    assert pdf_response.mimetype == "application/pdf"

    response = client.post(
        f"/empresarial/pedidos/{pedido_id}/status",
        data={
            "csrf_token": csrf_token(client, "/"),
            "status": "enviado",
            "data_entrega": "2027-01-30",
            "nota_fiscal": "NF-100",
        },
    )
    assert response.status_code == 302
    with application.app_context():
        pedido = db.session.get(PedidoCompra, pedido_id)
        assert pedido.status == "enviado"
        assert pedido.data_entrega == date(2027, 1, 30)
        assert pedido.nota_fiscal == "NF-100"


def test_enterprise_reports_export_csv_and_require_buyer_or_admin(
    client, application, make_user, login_as
):
    _configure_enterprise(application)
    owner = make_user("Solicitante", "enterprise-report-owner@example.com")
    buyer = make_user("Comprador", "enterprise-report-buyer@example.com", papel="comprador")
    with application.app_context():
        _, center = _create_unit(code="REP")
        _create_budget(
            db.session.get(Usuario, owner.id),
            center,
            [("Fornecedor relatório", 500, 15, 1)],
            status="compra_realizada",
        )
    login_as(client, owner.email)
    assert client.get("/empresarial/relatorios").status_code == 403

    client.post("/logout", data={"csrf_token": csrf_token(client, "/")})
    login_as(client, buyer.email)
    page = client.get("/empresarial/relatorios")
    assert page.status_code == 200
    assert b"515,00" in page.data
    csv_response = client.get("/empresarial/relatorios.csv")
    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.content_type
    assert b"Fornecedor" not in csv_response.data
    assert b"Departamento REP" in csv_response.data
    assert b"R$ 515,00" in csv_response.data
