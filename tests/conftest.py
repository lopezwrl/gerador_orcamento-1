import os
from itertools import count

os.environ.setdefault("TESTING", "1")

import pytest

from orcatech.app import app
from orcatech.models import Aprovacao, Cotacao, Fornecedor, Orcamento, OrcamentoItem, ProdutoBusca, Usuario, db

_login_ip_counter = count(1)


@pytest.fixture
def application():
    app.config.update(
        TESTING=True,
        SECRET_KEY="pytest-only-secret",
        SQLALCHEMY_DATABASE_URI="sqlite://",
        WTF_CSRF_ENABLED=True,
        RATELIMIT_ENABLED=False,
        SESSION_COOKIE_SECURE=False,
        FEATURE_EMPRESARIAL_ENABLED=False,
    )
    with app.app_context():
        db.drop_all()
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(application):
    test_client = application.test_client()
    test_client.environ_base["REMOTE_ADDR"] = f"192.0.2.{next(_login_ip_counter)}"
    return test_client


@pytest.fixture
def make_user(application):
    def create_user(nome, email, papel="usuario", ativo=True, senha="SenhaSegura123!"):
        with application.app_context():
            user = Usuario(nome=nome, email=email, papel=papel, ativo=ativo)
            user.set_senha(senha)
            db.session.add(user)
            db.session.commit()
            db.session.refresh(user)
            db.session.expunge(user)
        return user

    return create_user


def csrf_token(client, path="/"):
    import re

    response = client.get(path)
    match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
    assert match, response.data.decode("utf-8")
    return match.group(1).decode("ascii")


def login(client, email, senha="SenhaSegura123!"):
    token = csrf_token(client, "/login")
    return client.post(
        "/login",
        data={"csrf_token": token, "email": email, "senha": senha},
        follow_redirects=False,
    )


@pytest.fixture
def csrf_token_for(client):
    return lambda path="/": csrf_token(client, path)


@pytest.fixture
def login_as():
    return login
