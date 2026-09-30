"""historico e monitoramento de preços

Revision ID: b1d42f0a83ce
Revises: 9c4ca14d49b2
Create Date: 2026-10-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b1d42f0a83ce"
down_revision = "9c4ca14d49b2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("envios_email") as batch_op:
        batch_op.alter_column(
            "orcamento_id",
            existing_type=sa.Integer(),
            nullable=True,
        )

    op.create_table(
        "precos_historico",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_key", sa.String(length=64), nullable=False),
        sa.Column("produto_busca_id", sa.Integer(), nullable=False),
        sa.Column("fornecedor_id", sa.Integer(), nullable=False),
        sa.Column("cotacao_id", sa.Integer(), nullable=True),
        sa.Column("nome_produto", sa.String(length=255), nullable=False),
        sa.Column("link", sa.String(length=500), nullable=True),
        sa.Column("preco", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("dia", sa.Date(), nullable=False),
        sa.Column("coletado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cotacao_id"], ["cotacoes.id"]),
        sa.ForeignKeyConstraint(["fornecedor_id"], ["fornecedores.id"]),
        sa.ForeignKeyConstraint(["produto_busca_id"], ["produtos_busca.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_key", "dia", name="uq_preco_historico_item_dia"),
    )
    with op.batch_alter_table("precos_historico") as batch_op:
        batch_op.create_index("ix_precos_historico_dia", ["dia"], unique=False)
        batch_op.create_index("ix_precos_historico_fornecedor_id", ["fornecedor_id"], unique=False)
        batch_op.create_index("ix_precos_historico_item_key", ["item_key"], unique=False)
        batch_op.create_index("ix_precos_historico_produto_busca_id", ["produto_busca_id"], unique=False)

    op.create_table(
        "monitoramentos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("produto_busca_id", sa.Integer(), nullable=False),
        sa.Column("fornecedor_id", sa.Integer(), nullable=False),
        sa.Column("loja", sa.String(length=30), nullable=False),
        sa.Column("nome_modelo", sa.String(length=255), nullable=False),
        sa.Column("link", sa.String(length=500), nullable=True),
        sa.Column("preco_referencia", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("gatilho_percentual", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("gatilho_valor", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("ativo", sa.Boolean(), nullable=False),
        sa.Column("ultimo_check", sa.DateTime(), nullable=True),
        sa.Column("proxima_verificacao", sa.DateTime(), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(gatilho_percentual IS NULL) != (gatilho_valor IS NULL)",
            name="ck_monitoramentos_gatilho_exclusivo",
        ),
        sa.CheckConstraint(
            "gatilho_percentual IS NULL OR "
            "(gatilho_percentual > 0 AND gatilho_percentual <= 100)",
            name="ck_monitoramentos_gatilho_percentual",
        ),
        sa.CheckConstraint(
            "gatilho_valor IS NULL OR gatilho_valor > 0",
            name="ck_monitoramentos_gatilho_valor",
        ),
        sa.ForeignKeyConstraint(["fornecedor_id"], ["fornecedores.id"]),
        sa.ForeignKeyConstraint(["produto_busca_id"], ["produtos_busca.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "usuario_id",
            "produto_busca_id",
            "fornecedor_id",
            "nome_modelo",
            name="uq_monitoramentos_usuario_produto_loja_modelo",
        ),
    )
    with op.batch_alter_table("monitoramentos") as batch_op:
        batch_op.create_index("ix_monitoramentos_ativo", ["ativo"], unique=False)
        batch_op.create_index("ix_monitoramentos_fornecedor_id", ["fornecedor_id"], unique=False)
        batch_op.create_index("ix_monitoramentos_loja", ["loja"], unique=False)
        batch_op.create_index("ix_monitoramentos_produto_busca_id", ["produto_busca_id"], unique=False)
        batch_op.create_index("ix_monitoramentos_proxima_verificacao", ["proxima_verificacao"], unique=False)
        batch_op.create_index("ix_monitoramentos_usuario_id", ["usuario_id"], unique=False)

    op.create_table(
        "alertas_preco",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("monitoramento_id", sa.Integer(), nullable=False),
        sa.Column("preco_anterior", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("preco_novo", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("reducao", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("origem_referencia", sa.String(length=20), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("lido_em", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["monitoramento_id"], ["monitoramentos.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "monitoramento_id",
            "preco_novo",
            name="uq_alerta_preco_monitoramento_preco",
        ),
    )
    with op.batch_alter_table("alertas_preco") as batch_op:
        batch_op.create_index("ix_alertas_preco_criado_em", ["criado_em"], unique=False)
        batch_op.create_index("ix_alertas_preco_monitoramento_id", ["monitoramento_id"], unique=False)

    op.create_table(
        "controle_verificacao_lojas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("loja", sa.String(length=30), nullable=False),
        sa.Column("ultima_verificacao", sa.DateTime(), nullable=True),
        sa.Column("proxima_permitida", sa.DateTime(), nullable=True),
        sa.Column("bloqueada_ate", sa.DateTime(), nullable=True),
        sa.Column("lease_ate", sa.DateTime(), nullable=True),
        sa.Column("falhas_consecutivas", sa.Integer(), nullable=False),
        sa.Column("ultimo_status", sa.String(length=20), nullable=True),
        sa.Column("ultimo_erro_tipo", sa.String(length=80), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("loja"),
    )
    controle_lojas = sa.table(
        "controle_verificacao_lojas",
        sa.column("loja", sa.String(length=30)),
        sa.column("falhas_consecutivas", sa.Integer()),
    )
    op.bulk_insert(
        controle_lojas,
        [
            {"loja": loja, "falhas_consecutivas": 0}
            for loja in (
                "mercadolivre", "kabum", "amazon", "terabyte",
                "americanas", "ibyte", "gshield", "aliexpress",
            )
        ],
    )


def downgrade():
    op.drop_table("controle_verificacao_lojas")
    with op.batch_alter_table("alertas_preco") as batch_op:
        batch_op.drop_index("ix_alertas_preco_monitoramento_id")
        batch_op.drop_index("ix_alertas_preco_criado_em")
    op.drop_table("alertas_preco")
    with op.batch_alter_table("monitoramentos") as batch_op:
        batch_op.drop_index("ix_monitoramentos_usuario_id")
        batch_op.drop_index("ix_monitoramentos_proxima_verificacao")
        batch_op.drop_index("ix_monitoramentos_produto_busca_id")
        batch_op.drop_index("ix_monitoramentos_loja")
        batch_op.drop_index("ix_monitoramentos_fornecedor_id")
        batch_op.drop_index("ix_monitoramentos_ativo")
    op.drop_table("monitoramentos")
    with op.batch_alter_table("precos_historico") as batch_op:
        batch_op.drop_index("ix_precos_historico_produto_busca_id")
        batch_op.drop_index("ix_precos_historico_item_key")
        batch_op.drop_index("ix_precos_historico_fornecedor_id")
        batch_op.drop_index("ix_precos_historico_dia")
    op.drop_table("precos_historico")
    op.execute("DELETE FROM envios_email WHERE orcamento_id IS NULL")
    with op.batch_alter_table("envios_email") as batch_op:
        batch_op.alter_column(
            "orcamento_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
