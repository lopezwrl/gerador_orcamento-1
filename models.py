"""
models.py — Modelos de banco de dados do OrçaTech (SQLite via Flask-SQLAlchemy).

Como usar (em app.py):

    from models import db, Usuario, Fornecedor, ProdutoBusca, Cotacao, Orcamento, OrcamentoItem, Aprovacao

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///orcatech.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()

Adicionar ao requirements.txt: flask-sqlalchemy
"""

from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Usuario(db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    senha_hash = db.Column(db.String(255), nullable=False)
    papel = db.Column(db.String(20), nullable=False, default="usuario")  # "admin" | "usuario"
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    orcamentos = db.relationship("Orcamento", back_populates="usuario", foreign_keys="Orcamento.usuario_id")

    def set_senha(self, senha_plana):
        self.senha_hash = generate_password_hash(senha_plana)

    def checar_senha(self, senha_plana):
        return check_password_hash(self.senha_hash, senha_plana)

    def __repr__(self):
        return f"<Usuario {self.email} ({self.papel})>"


class Fornecedor(db.Model):
    __tablename__ = "fornecedores"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False, unique=True)
    tipo = db.Column(db.String(20), nullable=False, default="online")  # "online" | "manual"
    site = db.Column(db.String(255))
    contato = db.Column(db.String(255))
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    cotacoes = db.relationship("Cotacao", back_populates="fornecedor")

    def __repr__(self):
        return f"<Fornecedor {self.nome}>"


class ProdutoBusca(db.Model):
    __tablename__ = "produtos_busca"

    id = db.Column(db.Integer, primary_key=True)
    nome_pesquisado = db.Column(db.String(255), nullable=False, index=True)
    especificacoes = db.Column(db.JSON)  # RAM, armazenamento, tela, etc. extraídos via regex
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    cotacoes = db.relationship("Cotacao", back_populates="produto_busca")

    def __repr__(self):
        return f"<ProdutoBusca {self.nome_pesquisado}>"


class Cotacao(db.Model):
    """Cada resultado de preço encontrado (scraping ou lançado manualmente)."""
    __tablename__ = "cotacoes"

    id = db.Column(db.Integer, primary_key=True)
    produto_busca_id = db.Column(db.Integer, db.ForeignKey("produtos_busca.id"), nullable=False)
    fornecedor_id = db.Column(db.Integer, db.ForeignKey("fornecedores.id"), nullable=False)

    nome_produto = db.Column(db.String(255), nullable=False)  # nome exato do anúncio na loja
    preco = db.Column(db.Float, nullable=False)
    link = db.Column(db.String(500))
    imagem = db.Column(db.String(500))
    frete = db.Column(db.Float)
    prazo_entrega = db.Column(db.String(80))
    forma_pagamento = db.Column(db.String(120))  # ex: "Pix / Cartão em até 12x"
    origem = db.Column(db.String(20), nullable=False, default="scraping")  # "scraping" | "manual"
    coletado_em = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    produto_busca = db.relationship("ProdutoBusca", back_populates="cotacoes")
    fornecedor = db.relationship("Fornecedor", back_populates="cotacoes")

    def __repr__(self):
        return f"<Cotacao {self.nome_produto[:30]} R${self.preco} @ {self.fornecedor_id}>"


class Orcamento(db.Model):
    __tablename__ = "orcamentos"

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(40), unique=True, nullable=False)  # ORC-AAAAMMDDHHmm
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    solicitante = db.Column(db.String(120))
    status = db.Column(
        db.String(30), nullable=False, default="rascunho"
    )  # rascunho|em_cotacao|aguardando_aprovacao|aprovado|reprovado|compra_realizada
    observacoes = db.Column(db.Text)
    condicoes_comerciais = db.Column(db.Text)
    validade = db.Column(db.Date)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    usuario = db.relationship("Usuario", back_populates="orcamentos", foreign_keys=[usuario_id])
    itens = db.relationship("OrcamentoItem", back_populates="orcamento", cascade="all, delete-orphan")
    aprovacoes = db.relationship("Aprovacao", back_populates="orcamento", cascade="all, delete-orphan")

    @staticmethod
    def gerar_numero():
        return "ORC-" + datetime.now().strftime("%Y%m%d%H%M")

    @property
    def total(self):
        total = 0.0
        for item in self.itens:
            if item.cotacao_escolhida:
                total += item.cotacao_escolhida.preco * item.quantidade
        return round(total, 2)

    def __repr__(self):
        return f"<Orcamento {self.numero} ({self.status})>"


class OrcamentoItem(db.Model):
    """Um produto dentro de um orçamento (o 'carrinho')."""
    __tablename__ = "orcamento_itens"

    id = db.Column(db.Integer, primary_key=True)
    orcamento_id = db.Column(db.Integer, db.ForeignKey("orcamentos.id"), nullable=False)
    produto_busca_id = db.Column(db.Integer, db.ForeignKey("produtos_busca.id"), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False, default=1)
    cotacao_escolhida_id = db.Column(db.Integer, db.ForeignKey("cotacoes.id"))
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    orcamento = db.relationship("Orcamento", back_populates="itens")
    produto_busca = db.relationship("ProdutoBusca")
    cotacao_escolhida = db.relationship("Cotacao")

    @property
    def subtotal(self):
        if self.cotacao_escolhida:
            return round(self.cotacao_escolhida.preco * self.quantidade, 2)
        return 0.0

    def __repr__(self):
        return f"<OrcamentoItem orc={self.orcamento_id} produto={self.produto_busca_id} qtd={self.quantidade}>"


class Aprovacao(db.Model):
    __tablename__ = "aprovacoes"

    id = db.Column(db.Integer, primary_key=True)
    orcamento_id = db.Column(db.Integer, db.ForeignKey("orcamentos.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    decisao = db.Column(db.String(20), nullable=False)  # "aprovado" | "reprovado"
    comentario = db.Column(db.Text)
    decidido_em = db.Column(db.DateTime, default=datetime.utcnow)

    orcamento = db.relationship("Orcamento", back_populates="aprovacoes")
    usuario = db.relationship("Usuario")

    def __repr__(self):
        return f"<Aprovacao orc={self.orcamento_id} {self.decisao}>"
