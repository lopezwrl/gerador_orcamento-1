import os
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .gerar_pdf import PASTA_PDF


def _brl(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gerar_pdf_pedido_compra(pedido, caminho_saida=None):
    caminho = caminho_saida or os.path.join(
        PASTA_PDF, f"pedido_compra_{pedido.numero}.pdf"
    )
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    documento = SimpleDocTemplate(
        caminho,
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
    )
    estilos = getSampleStyleSheet()
    elementos = [
        Paragraph("OrçaTech · Pedido de Compra", estilos["Title"]),
        Paragraph(f"Número: {escape(pedido.numero)}", estilos["Heading2"]),
        Spacer(1, 8),
    ]
    metadados = [
        ["Orçamento", escape(pedido.orcamento.numero)],
        ["Fornecedor", escape(pedido.snapshot_fornecedor_nome)],
        ["Status", escape(pedido.status.replace("_", " ").title())],
        ["Emitido em", pedido.criado_em.strftime("%d/%m/%Y %H:%M")],
        [
            "Entrega prevista",
            pedido.data_entrega.strftime("%d/%m/%Y") if pedido.data_entrega else "Não definida",
        ],
        ["Nota fiscal", escape(pedido.nota_fiscal or "Não informada")],
    ]
    elementos.append(
        Table(
            metadados,
            colWidths=[4 * cm, 13 * cm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8ecf8")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d4d9ef")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            ),
        )
    )
    linhas = [["Produto", "Qtd.", "Unitário", "Frete", "Subtotal"]]
    for item in pedido.itens:
        linhas.append(
            [
                Paragraph(escape(item.nome_produto), estilos["BodyText"]),
                str(item.quantidade),
                _brl(item.preco_unitario),
                _brl(item.frete),
                _brl(item.subtotal),
            ]
        )
    elementos.extend(
        [
            Spacer(1, 16),
            Table(
                linhas,
                colWidths=[7.2 * cm, 1.3 * cm, 2.5 * cm, 2.1 * cm, 3.2 * cm],
                repeatRows=1,
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e2a6e")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d4d9ef")),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6fb")]),
                        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 7),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ]
                ),
            ),
            Spacer(1, 12),
            Paragraph(f"<b>Total do pedido: {_brl(pedido.total)}</b>", estilos["Heading2"]),
        ]
    )
    if pedido.condicoes_comerciais:
        elementos.extend(
            [
                Spacer(1, 8),
                Paragraph(
                    "<b>Condições comerciais:</b> "
                    + escape(pedido.condicoes_comerciais),
                    estilos["BodyText"],
                ),
            ]
        )
    documento.build(elementos)
    return caminho
