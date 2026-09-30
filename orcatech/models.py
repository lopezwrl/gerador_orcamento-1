"""
models.py — Modelos de banco de dados do OrçaTech (SQLite via Flask-SQLAlchemy).

Como usar (em app.py):

    from orcatech.models import db, Usuario, Fornecedor, ProdutoBusca, Cotacao, Orcamento, OrcamentoItem, Aprovacao

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///orcatech.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()

Adicionar ao requirements.txt: flask-sqlalchemy
"""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import CheckConstraint, UniqueConstraint, false
import secrets
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    senha_hash = db.Column(db.String(255), nullable=False)
    papel = db.Column(
        db.String(20),
        nullable=False,
        default="usuario",
    )  # "admin" | "usuario" | "aprovador" | "comprador"
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    departamento_id = db.Column(
        db.Integer, db.ForeignKey("departamentos.id"), nullable=True, index=True
    )
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    orcamentos = db.relationship("Orcamento", back_populates="usuario", foreign_keys="Orcamento.usuario_id")
    departamento = db.relationship("Departamento", back_populates="usuarios")

    @property
    def is_active(self):
        return self.ativo

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


class Departamento(db.Model):
    __tablename__ = "departamentos"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(30), nullable=False, unique=True)
    nome = db.Column(db.String(120), nullable=False, unique=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=_utcnow)

    usuarios = db.relationship("Usuario", back_populates="departamento")
    centros_custo = db.relationship("CentroCusto", back_populates="departamento")
    orcamentos = db.relationship("Orcamento", back_populates="departamento")


class CentroCusto(db.Model):
    __tablename__ = "centros_custo"
    __table_args__ = (
        UniqueConstraint("departamento_id", "codigo", name="uq_centro_custo_departamento_codigo"),
        CheckConstraint("limite_gasto > 0", name="ck_centro_custo_limite_positivo"),
    )

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(30), nullable=False)
    nome = db.Column(db.String(120), nullable=False)
    departamento_id = db.Column(
        db.Integer, db.ForeignKey("departamentos.id"), nullable=False, index=True
    )
    limite_gasto = db.Column(db.Numeric(12, 2), nullable=False)
    criado_em = db.Column(db.DateTime, nullable=False, default=_utcnow)

    departamento = db.relationship("Departamento", back_populates="centros_custo")
    orcamentos = db.relationship("Orcamento", back_populates="centro_custo")


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
    departamento_id = db.Column(
        db.Integer, db.ForeignKey("departamentos.id"), nullable=True, index=True
    )
    centro_custo_id = db.Column(
        db.Integer, db.ForeignKey("centros_custo.id"), nullable=True, index=True
    )
    solicitante = db.Column(db.String(120))
    status = db.Column(
        db.String(30), nullable=False, default="rascunho"
    )  # rascunho|em_cotacao|aguardando_aprovacao|aprovado|reprovado|compra_realizada
    observacoes = db.Column(db.Text)
    condicoes_comerciais = db.Column(db.Text)
    validade = db.Column(db.Date)
    share_token = db.Column(db.String(128), unique=True, index=True)
    share_expira_em = db.Column(db.DateTime)
    share_revogado = db.Column(
        db.Boolean, nullable=False, default=False, server_default=false()
    )
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    usuario = db.relationship("Usuario", back_populates="orcamentos", foreign_keys=[usuario_id])
    departamento = db.relationship("Departamento", back_populates="orcamentos")
    centro_custo = db.relationship("CentroCusto", back_populates="orcamentos")
    itens = db.relationship("OrcamentoItem", back_populates="orcamento", cascade="all, delete-orphan")
    aprovacoes = db.relationship("Aprovacao", back_populates="orcamento", cascade="all, delete-orphan")
    historico = db.relationship(
        "OrcamentoHistorico",
        back_populates="orcamento",
        cascade="all, delete-orphan",
        order_by="OrcamentoHistorico.criado_em",
    )
    envios_email = db.relationship(
        "EnvioEmail", back_populates="orcamento", cascade="all, delete-orphan"
    )
    pedidos_compra = db.relationship(
        "PedidoCompra", back_populates="orcamento", cascade="all, delete-orphan"
    )

    @staticmethod
    def gerar_numero():
        return "ORC-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(3).upper()

    @property
    def total(self):
        return sum((item.subtotal + item.frete for item in self.itens), Decimal("0.00"))

    @property
    def expirado(self):
        return self.validade is not None and self.validade < date.today()

    @property
    def aguardando_desde(self):
        eventos = [
            evento.criado_em
            for evento in self.historico
            if evento.status_para == "aguardando_aprovacao"
        ]
        return max(eventos, default=self.criado_em)

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
    snapshot_nome_produto = db.Column(db.String(255))
    snapshot_fornecedor_nome = db.Column(db.String(120))
    snapshot_preco_unit = db.Column(db.Numeric(12, 2))
    snapshot_frete = db.Column(db.Numeric(12, 2))
    snapshot_link = db.Column(db.String(500))
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    orcamento = db.relationship("Orcamento", back_populates="itens")
    produto_busca = db.relationship("ProdutoBusca")
    cotacao_escolhida = db.relationship("Cotacao")

    @staticmethod
    def _dinheiro(valor):
        return Decimal(str(valor or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def nome_produto(self):
        if self.snapshot_nome_produto is not None:
            return self.snapshot_nome_produto
        return self.cotacao_escolhida.nome_produto if self.cotacao_escolhida else self.produto_busca.nome_pesquisado

    @property
    def fornecedor_nome(self):
        if self.snapshot_fornecedor_nome is not None:
            return self.snapshot_fornecedor_nome
        return self.cotacao_escolhida.fornecedor.nome if self.cotacao_escolhida else "—"

    @property
    def preco_unitario(self):
        if self.snapshot_preco_unit is not None:
            return self._dinheiro(self.snapshot_preco_unit)
        return self._dinheiro(self.cotacao_escolhida.preco if self.cotacao_escolhida else 0)

    @property
    def frete(self):
        if self.snapshot_frete is not None:
            return self._dinheiro(self.snapshot_frete)
        return self._dinheiro(self.cotacao_escolhida.frete if self.cotacao_escolhida else 0)

    @property
    def link(self):
        if self.snapshot_link is not None:
            return self.snapshot_link
        return self.cotacao_escolhida.link if self.cotacao_escolhida else None

    @property
    def subtotal(self):
        return (self.preco_unitario * self.quantidade).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

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


class OrcamentoHistorico(db.Model):
    __tablename__ = "orcamento_historico"

    id = db.Column(db.Integer, primary_key=True)
    orcamento_id = db.Column(db.Integer, db.ForeignKey("orcamentos.id"), nullable=False, index=True)
    status_de = db.Column(db.String(30), nullable=False)
    status_para = db.Column(db.String(30), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    comentario = db.Column(db.Text)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    orcamento = db.relationship("Orcamento", back_populates="historico")
    usuario = db.relationship("Usuario")


class EnvioEmail(db.Model):
    __tablename__ = "envios_email"

    id = db.Column(db.Integer, primary_key=True)
    orcamento_id = db.Column(db.Integer, db.ForeignKey("orcamentos.id"), nullable=True, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    destinatario = db.Column(db.String(254), nullable=False)
    sucesso = db.Column(db.Boolean)
    erro = db.Column(db.Text)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    orcamento = db.relationship("Orcamento", back_populates="envios_email")
    usuario = db.relationship("Usuario")


class PrecoHistorico(db.Model):
    __tablename__ = "precos_historico"
    __table_args__ = (
        UniqueConstraint("item_key", "dia", name="uq_preco_historico_item_dia"),
    )

    id = db.Column(db.Integer, primary_key=True)
    item_key = db.Column(db.String(64), nullable=False, index=True)
    produto_busca_id = db.Column(
        db.Integer, db.ForeignKey("produtos_busca.id"), nullable=False, index=True
    )
    fornecedor_id = db.Column(
        db.Integer, db.ForeignKey("fornecedores.id"), nullable=False, index=True
    )
    cotacao_id = db.Column(db.Integer, db.ForeignKey("cotacoes.id"), nullable=True)
    nome_produto = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(500))
    preco = db.Column(db.Numeric(12, 2), nullable=False)
    dia = db.Column(db.Date, nullable=False, index=True)
    coletado_em = db.Column(db.DateTime, nullable=False, default=_utcnow)

    produto_busca = db.relationship("ProdutoBusca")
    fornecedor = db.relationship("Fornecedor")
    cotacao = db.relationship("Cotacao")


class Monitoramento(db.Model):
    __tablename__ = "monitoramentos"
    __table_args__ = (
        UniqueConstraint(
            "usuario_id",
            "produto_busca_id",
            "fornecedor_id",
            "nome_modelo",
            name="uq_monitoramentos_usuario_produto_loja_modelo",
        ),
        CheckConstraint(
            "(gatilho_percentual IS NULL) != (gatilho_valor IS NULL)",
            name="ck_monitoramentos_gatilho_exclusivo",
        ),
        CheckConstraint(
            "gatilho_percentual IS NULL OR "
            "(gatilho_percentual > 0 AND gatilho_percentual <= 100)",
            name="ck_monitoramentos_gatilho_percentual",
        ),
        CheckConstraint(
            "gatilho_valor IS NULL OR gatilho_valor > 0",
            name="ck_monitoramentos_gatilho_valor",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, index=True)
    produto_busca_id = db.Column(
        db.Integer, db.ForeignKey("produtos_busca.id"), nullable=False, index=True
    )
    fornecedor_id = db.Column(
        db.Integer, db.ForeignKey("fornecedores.id"), nullable=False, index=True
    )
    loja = db.Column(db.String(30), nullable=False, index=True)
    nome_modelo = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(500))
    preco_referencia = db.Column(db.Numeric(12, 2), nullable=False)
    gatilho_percentual = db.Column(db.Numeric(5, 2))
    gatilho_valor = db.Column(db.Numeric(12, 2))
    ativo = db.Column(db.Boolean, nullable=False, default=True, index=True)
    ultimo_check = db.Column(db.DateTime)
    proxima_verificacao = db.Column(db.DateTime, nullable=False, default=_utcnow, index=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=_utcnow)

    usuario = db.relationship("Usuario")
    produto_busca = db.relationship("ProdutoBusca")
    fornecedor = db.relationship("Fornecedor")
    alertas = db.relationship(
        "AlertaPreco", back_populates="monitoramento", cascade="all, delete-orphan"
    )


class AlertaPreco(db.Model):
    __tablename__ = "alertas_preco"
    __table_args__ = (
        UniqueConstraint(
            "monitoramento_id", "preco_novo", name="uq_alerta_preco_monitoramento_preco"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    monitoramento_id = db.Column(
        db.Integer, db.ForeignKey("monitoramentos.id"), nullable=False, index=True
    )
    preco_anterior = db.Column(db.Numeric(12, 2), nullable=False)
    preco_novo = db.Column(db.Numeric(12, 2), nullable=False)
    reducao = db.Column(db.Numeric(12, 2), nullable=False)
    origem_referencia = db.Column(db.String(20), nullable=False, default="monitoramento")
    criado_em = db.Column(db.DateTime, nullable=False, default=_utcnow, index=True)
    lido_em = db.Column(db.DateTime)

    monitoramento = db.relationship("Monitoramento", back_populates="alertas")


class ControleVerificacaoLoja(db.Model):
    __tablename__ = "controle_verificacao_lojas"

    id = db.Column(db.Integer, primary_key=True)
    loja = db.Column(db.String(30), nullable=False, unique=True)
    ultima_verificacao = db.Column(db.DateTime)
    proxima_permitida = db.Column(db.DateTime)
    bloqueada_ate = db.Column(db.DateTime)
    lease_ate = db.Column(db.DateTime)
    falhas_consecutivas = db.Column(db.Integer, nullable=False, default=0)
    ultimo_status = db.Column(db.String(20))
    ultimo_erro_tipo = db.Column(db.String(80))


class PedidoCompra(db.Model):
    __tablename__ = "pedidos_compra"
    __table_args__ = (
        UniqueConstraint(
            "orcamento_id", "fornecedor_id",
            name="uq_pedido_compra_orcamento_fornecedor",
        ),
        CheckConstraint(
            "status IN ('emitido', 'enviado', 'recebido', 'cancelado')",
            name="ck_pedido_compra_status",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(40), nullable=False, unique=True, index=True)
    orcamento_id = db.Column(
        db.Integer, db.ForeignKey("orcamentos.id"), nullable=False, index=True
    )
    fornecedor_id = db.Column(
        db.Integer, db.ForeignKey("fornecedores.id"), nullable=False, index=True
    )
    snapshot_fornecedor_nome = db.Column(db.String(120), nullable=False)
    criado_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="emitido")
    condicoes_comerciais = db.Column(db.Text)
    data_entrega = db.Column(db.Date)
    nota_fiscal = db.Column(db.String(120))
    criado_em = db.Column(db.DateTime, nullable=False, default=_utcnow)
    enviado_em = db.Column(db.DateTime)
    recebido_em = db.Column(db.DateTime)

    orcamento = db.relationship("Orcamento", back_populates="pedidos_compra")
    fornecedor = db.relationship("Fornecedor")
    criado_por = db.relationship("Usuario")
    itens = db.relationship(
        "PedidoCompraItem", back_populates="pedido_compra", cascade="all, delete-orphan"
    )

    @staticmethod
    def gerar_numero():
        return "PC-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(3).upper()

    @property
    def total(self):
        return sum(
            (item.subtotal + item.frete for item in self.itens),
            Decimal("0.00"),
        )


class PedidoCompraItem(db.Model):
    __tablename__ = "pedidos_compra_itens"

    id = db.Column(db.Integer, primary_key=True)
    pedido_compra_id = db.Column(
        db.Integer, db.ForeignKey("pedidos_compra.id"), nullable=False, index=True
    )
    orcamento_item_id = db.Column(
        db.Integer, db.ForeignKey("orcamento_itens.id"), nullable=False
    )
    nome_produto = db.Column(db.String(255), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    preco_unitario = db.Column(db.Numeric(12, 2), nullable=False)
    frete = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    link = db.Column(db.String(500))

    pedido_compra = db.relationship("PedidoCompra", back_populates="itens")
    orcamento_item = db.relationship("OrcamentoItem")

    @property
    def subtotal(self):
        return Decimal(self.preco_unitario) * self.quantidade
