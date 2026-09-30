"""recursos empresariais

Revision ID: c4e7a9d2310f
Revises: b1d42f0a83ce
Create Date: 2026-10-03 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c4e7a9d2310f"
down_revision = "b1d42f0a83ce"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "departamentos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(length=30), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo"),
        sa.UniqueConstraint("nome"),
    )
    op.create_table(
        "centros_custo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(length=30), nullable=False),
        sa.Column("nome", sa.String(length=120), nullable=False),
        sa.Column("departamento_id", sa.Integer(), nullable=False),
        sa.Column("limite_gasto", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.CheckConstraint("limite_gasto > 0", name="ck_centro_custo_limite_positivo"),
        sa.ForeignKeyConstraint(
            ["departamento_id"], ["departamentos.id"],
            name="fk_centros_custo_departamento_id_departamentos",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "departamento_id", "codigo",
            name="uq_centro_custo_departamento_codigo",
        ),
    )
    op.create_index(
        "ix_centros_custo_departamento_id",
        "centros_custo",
        ["departamento_id"],
        unique=False,
    )

    with op.batch_alter_table("usuarios") as batch_op:
        batch_op.add_column(sa.Column("departamento_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_usuarios_departamento_id_departamentos",
            "departamentos",
            ["departamento_id"],
            ["id"],
        )
        batch_op.create_index("ix_usuarios_departamento_id", ["departamento_id"], unique=False)

    with op.batch_alter_table("orcamentos") as batch_op:
        batch_op.add_column(sa.Column("departamento_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("centro_custo_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_orcamentos_departamento_id_departamentos",
            "departamentos",
            ["departamento_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_orcamentos_centro_custo_id_centros_custo",
            "centros_custo",
            ["centro_custo_id"],
            ["id"],
        )
        batch_op.create_index("ix_orcamentos_departamento_id", ["departamento_id"], unique=False)
        batch_op.create_index("ix_orcamentos_centro_custo_id", ["centro_custo_id"], unique=False)

    op.create_table(
        "pedidos_compra",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("numero", sa.String(length=40), nullable=False),
        sa.Column("orcamento_id", sa.Integer(), nullable=False),
        sa.Column("fornecedor_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_fornecedor_nome", sa.String(length=120), nullable=False),
        sa.Column("criado_por_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("condicoes_comerciais", sa.Text(), nullable=True),
        sa.Column("data_entrega", sa.Date(), nullable=True),
        sa.Column("nota_fiscal", sa.String(length=120), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("enviado_em", sa.DateTime(), nullable=True),
        sa.Column("recebido_em", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('emitido', 'enviado', 'recebido', 'cancelado')",
            name="ck_pedido_compra_status",
        ),
        sa.ForeignKeyConstraint(
            ["criado_por_id"], ["usuarios.id"],
            name="fk_pedidos_compra_criado_por_id_usuarios",
        ),
        sa.ForeignKeyConstraint(
            ["fornecedor_id"], ["fornecedores.id"],
            name="fk_pedidos_compra_fornecedor_id_fornecedores",
        ),
        sa.ForeignKeyConstraint(
            ["orcamento_id"], ["orcamentos.id"],
            name="fk_pedidos_compra_orcamento_id_orcamentos",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "orcamento_id", "fornecedor_id",
            name="uq_pedido_compra_orcamento_fornecedor",
        ),
    )
    op.create_index("ix_pedidos_compra_numero", "pedidos_compra", ["numero"], unique=True)
    op.create_index("ix_pedidos_compra_orcamento_id", "pedidos_compra", ["orcamento_id"], unique=False)
    op.create_index("ix_pedidos_compra_fornecedor_id", "pedidos_compra", ["fornecedor_id"], unique=False)

    op.create_table(
        "pedidos_compra_itens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pedido_compra_id", sa.Integer(), nullable=False),
        sa.Column("orcamento_item_id", sa.Integer(), nullable=False),
        sa.Column("nome_produto", sa.String(length=255), nullable=False),
        sa.Column("quantidade", sa.Integer(), nullable=False),
        sa.Column("preco_unitario", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("frete", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("link", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(
            ["orcamento_item_id"], ["orcamento_itens.id"],
            name="fk_pedidos_compra_itens_orcamento_item_id_orcamento_itens",
        ),
        sa.ForeignKeyConstraint(
            ["pedido_compra_id"], ["pedidos_compra.id"],
            name="fk_pedidos_compra_itens_pedido_compra_id_pedidos_compra",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pedidos_compra_itens_pedido_compra_id",
        "pedidos_compra_itens",
        ["pedido_compra_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_pedidos_compra_itens_pedido_compra_id",
        table_name="pedidos_compra_itens",
    )
    op.drop_table("pedidos_compra_itens")
    op.drop_index("ix_pedidos_compra_fornecedor_id", table_name="pedidos_compra")
    op.drop_index("ix_pedidos_compra_orcamento_id", table_name="pedidos_compra")
    op.drop_index("ix_pedidos_compra_numero", table_name="pedidos_compra")
    op.drop_table("pedidos_compra")

    with op.batch_alter_table("orcamentos") as batch_op:
        batch_op.drop_index("ix_orcamentos_centro_custo_id")
        batch_op.drop_index("ix_orcamentos_departamento_id")
        batch_op.drop_constraint(
            "fk_orcamentos_centro_custo_id_centros_custo", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_orcamentos_departamento_id_departamentos", type_="foreignkey"
        )
        batch_op.drop_column("centro_custo_id")
        batch_op.drop_column("departamento_id")

    with op.batch_alter_table("usuarios") as batch_op:
        batch_op.drop_index("ix_usuarios_departamento_id")
        batch_op.drop_constraint(
            "fk_usuarios_departamento_id_departamentos", type_="foreignkey"
        )
        batch_op.drop_column("departamento_id")

    op.drop_index("ix_centros_custo_departamento_id", table_name="centros_custo")
    op.drop_table("centros_custo")
    op.drop_table("departamentos")
