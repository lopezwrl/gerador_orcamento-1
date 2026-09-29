from urllib.parse import parse_qs, urlencode, urlsplit

from orcatech.models import Usuario, db

from .conftest import csrf_token


def test_sensitive_get_routes_require_login(client):
    for path in (
        "/",
        "/buscar",
        "/orcamentos",
        "/relatorios",
        "/api/relatorios_dados",
        "/rever/0",
        "/fornecedores/",
        "/orcamento/carrinho",
    ):
        response = client.get(path)
        assert response.status_code == 302, path
        assert urlsplit(response.headers["Location"]).path == "/login"


def test_login_accepts_credentials_and_internal_next(client, make_user, login_as):
    make_user("Ana", "ana@example.com")
    response = login_as(client, "ANA@example.com")
    assert response.status_code == 302
    assert urlsplit(response.headers["Location"]).path == "/"

    client.post("/logout", data={"csrf_token": csrf_token(client, "/")})
    response = client.get("/relatorios?filtro=ativos")
    assert response.status_code == 302
    login_url = urlsplit(response.headers["Location"])
    next_url = parse_qs(login_url.query)["next"][0]
    assert next_url == "/relatorios?filtro=ativos"
    login_path = f"/login?{urlencode({'next': next_url})}"
    token = csrf_token(client, login_path)
    response = client.post(
        login_path,
        data={"csrf_token": token, "email": "ana@example.com", "senha": "SenhaSegura123!"},
    )
    assert urlsplit(response.headers["Location"]).path == "/relatorios"
    assert urlsplit(response.headers["Location"]).query == "filtro=ativos"


def test_login_rejects_external_next(client, make_user, login_as):
    make_user("Ana", "ana@example.com")
    token = csrf_token(client, "/login?next=https://evil.example")
    response = client.post(
        "/login?next=https://evil.example",
        data={"csrf_token": token, "email": "ana@example.com", "senha": "SenhaSegura123!"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_inactive_users_cannot_login(client, make_user, login_as):
    make_user("Ana", "ana@example.com", ativo=False)
    response = login_as(client, "ana@example.com")
    assert response.status_code == 200
    assert b"E-mail ou senha inv" in response.data


def test_login_error_is_generic(client, make_user, login_as):
    make_user("Ana", "ana@example.com")
    response = login_as(client, "ana@example.com", senha="senha-incorreta")
    assert response.status_code == 200
    assert b"E-mail ou senha inv" in response.data
    assert b"senha-incorreta" not in response.data


def test_login_is_rate_limited(client, application, make_user):
    make_user("Ana", "ana@example.com")
    application.config["RATELIMIT_ENABLED"] = True
    token = csrf_token(client, "/login")

    responses = [
        client.post(
            "/login",
            data={"csrf_token": token, "email": "ana@example.com", "senha": "incorreta"},
        )
        for _ in range(6)
    ]

    assert [response.status_code for response in responses] == [200] * 5 + [429]


def test_inactive_user_is_logged_out_on_next_request(client, make_user, login_as):
    from orcatech.app import app

    user = make_user("Ana", "ana@example.com")
    login_as(client, "ana@example.com")
    with app.app_context():
        user = db.session.get(Usuario, user.id)
        user.ativo = False
        db.session.commit()

    response = client.get("/relatorios")
    assert response.status_code == 302
    assert urlsplit(response.headers["Location"]).path == "/login"


def test_regular_user_cannot_manage_suppliers_or_users(client, make_user, login_as, csrf_token_for):
    make_user("Ana", "ana@example.com")
    login_as(client, "ana@example.com")

    assert client.post(
        "/fornecedores/novo",
        data={"csrf_token": csrf_token_for("/fornecedores/"), "nome": "Loja"},
    ).status_code == 403
    assert client.get("/usuarios").status_code == 403


def test_admin_can_create_and_deactivate_users(client, make_user, login_as, csrf_token_for):
    from orcatech.app import app

    admin = make_user("Admin", "admin@example.com", papel="admin")
    login_as(client, "admin@example.com")

    response = client.post(
        "/usuarios",
        data={
            "csrf_token": csrf_token_for("/usuarios"),
            "nome": "Bruno",
            "email": "bruno@example.com",
            "senha": "UmaSenhaForte123!",
            "papel": "usuario",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    with app.app_context():
        user = Usuario.query.filter_by(email="bruno@example.com").one()
        user_id = user.id

    response = client.post(
        f"/usuarios/{user_id}/ativo",
        data={"csrf_token": csrf_token_for("/usuarios")},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Usuario, user_id).ativo is False


def test_admin_user_creation_enforces_minimum_password(client, make_user, login_as, csrf_token_for):
    make_user("Admin", "admin@example.com", papel="admin")
    login_as(client, "admin@example.com")
    response = client.post(
        "/usuarios",
        data={
            "csrf_token": csrf_token_for("/usuarios"),
            "nome": "Bruno",
            "email": "bruno@example.com",
            "senha": "curta",
            "papel": "usuario",
        },
    )
    assert response.status_code == 200
    assert b"12 caracteres" in response.data


def test_posts_without_csrf_token_are_rejected(client, make_user, login_as):
    make_user("Ana", "ana@example.com")
    login_as(client, "ana@example.com")
    response = client.post("/orcamento/finalizar", data={})
    assert response.status_code == 400


def test_session_cookie_and_security_headers(client, make_user, login_as):
    make_user("Ana", "ana@example.com")
    login_response = login_as(client, "ana@example.com")
    response = client.get("/")
    cookie = login_response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in response.headers


def test_disabled_debug_is_default():
    from orcatech.app import app

    assert app.config["DEBUG"] is False
