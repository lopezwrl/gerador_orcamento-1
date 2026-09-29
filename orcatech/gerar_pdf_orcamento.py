import os
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .gerar_pdf import (
    BORDER,
    ICE2,
    NAVY,
    PASTA_PDF,
    SLOGAN,
    TEAL2,
    W,
    WHITE,
    _st,
)


def _fmt_brl(valor):
    valor = Decimal(str(valor or 0))
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _marca_dagua(orcamento):
    if orcamento.status == "reprovado":
        return "REPROVADO"
    if orcamento.expirado:
        return "EXPIRADO"
    return None


def _desenhar_marca_dagua(orcamento):
    texto = _marca_dagua(orcamento)

    def desenhar(canvas, _doc):
        if not texto:
            return
        canvas.saveState()
        canvas.setFillColor(colors.Color(0.7, 0.05, 0.05, alpha=0.16))
        canvas.setFont("Helvetica-Bold", 42)
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(35)
        canvas.drawCentredString(0, 0, texto)
        canvas.restoreState()

    return desenhar


def _cabecalho(st, orcamento):
    criado = orcamento.criado_em.strftime("%d/%m/%Y %H:%M") if orcamento.criado_em else "—"
    validade = orcamento.validade.strftime("%d/%m/%Y") if orcamento.validade else "Não definida"
    tabela = Table(
        [[
            [
                Paragraph("OrçaTech", st["marca"]),
                Paragraph(escape(SLOGAN), st["slogan"]),
            ],
            Paragraph("<b>ORÇAMENTO DE COMPRA</b><br/>Nº " + escape(orcamento.numero), st["doc_titulo"]),
        ]],
        colWidths=[W * 0.52, W * 0.48],
    )
    tabela.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    meta = [
        ("Número", escape(orcamento.numero)),
        ("Status", escape(orcamento.status.replace("_", " ").title())),
        ("Data", criado),
        ("Validade", validade),
        ("Solicitante", escape(orcamento.solicitante or "Não informado")),
    ]
    linhas = [
        [Paragraph(f"<b>{chave}</b>", st["meta_k"]), Paragraph(valor, st["meta_v"])]
        for chave, valor in meta
    ]
    metadados = Table(linhas, colWidths=[W * 0.27, W * 0.73])
    metadados.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ICE2),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return [tabela, Spacer(1, 8), HRFlowable(width="100%", thickness=2, color=NAVY), Spacer(1, 10), metadados, Spacer(1, 16)]


def _tabela_itens(st, orcamento):
    cabecalho = ["Produto", "Fornecedor", "Qtd.", "Unitário", "Subtotal", "Frete"]
    linhas = [[Paragraph(f"<b>{escape(texto)}</b>", st["th"]) for texto in cabecalho]]
    for item in orcamento.itens:
        linhas.append([
            Paragraph(escape(item.nome_produto[:90]), st["cell"]),
            Paragraph(escape(item.fornecedor_nome), st["cell"]),
            Paragraph(str(item.quantidade), st["cell_centro"]),
            Paragraph(_fmt_brl(item.preco_unitario), st["cell"]),
            Paragraph(_fmt_brl(item.subtotal), st["cell"]),
            Paragraph(_fmt_brl(item.frete), st["cell"]),
        ])
    tabela = Table(
        linhas,
        colWidths=[W * 0.28, W * 0.19, W * 0.08, W * 0.15, W * 0.15, W * 0.15],
        repeatRows=1,
    )
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, ICE2]),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return [Paragraph("Itens do orçamento", st["secao"]), Spacer(1, 6), tabela]


def _resumo(st, orcamento):
    total_style = ParagraphStyle(
        "total_orcamento",
        fontSize=13,
        fontName="Helvetica-Bold",
        textColor=NAVY,
        alignment=TA_RIGHT,
        leading=16,
    )
    elementos = [
        Spacer(1, 12),
        Table(
            [["", Paragraph(f"TOTAL GERAL: {_fmt_brl(orcamento.total)}", total_style)]],
            colWidths=[W * 0.5, W * 0.5],
            style=TableStyle([
                ("BACKGROUND", (1, 0), (1, 0), TEAL2),
                ("TOPPADDING", (0, 0), (-1, -1), 11),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
                ("RIGHTPADDING", (1, 0), (1, 0), 12),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ]),
        ),
    ]
    if orcamento.condicoes_comerciais:
        elementos.extend([
            Spacer(1, 10),
            Paragraph("<b>Condições comerciais:</b> " + escape(orcamento.condicoes_comerciais), st["meta_v"]),
        ])
    if orcamento.observacoes:
        elementos.extend([
            Spacer(1, 5),
            Paragraph("<b>Observações:</b> " + escape(orcamento.observacoes), st["meta_v"]),
        ])

    if orcamento.status == "aprovado":
        decisao = next(
            (aprovacao for aprovacao in reversed(orcamento.aprovacoes) if aprovacao.decisao == "aprovado"),
            None,
        )
        if decisao:
            data_decisao = decisao.decidido_em.strftime("%d/%m/%Y %H:%M")
            texto = f"<b>Aprovado por {escape(decisao.usuario.nome)} em {data_decisao}.</b>"
            if decisao.comentario:
                texto += "<br/>Comentário: " + escape(decisao.comentario)
            elementos.extend([Spacer(1, 12), Paragraph(texto, st["meta_v"])])
    return elementos


def gerar_pdf_orcamento(orcamento):
    os.makedirs(PASTA_PDF, exist_ok=True)
    caminho = os.path.join(PASTA_PDF, f"orcamento_{orcamento.numero}.pdf")
    doc = SimpleDocTemplate(
        caminho,
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
    )
    estilos = _st()
    conteudo = _cabecalho(estilos, orcamento)
    conteudo.extend(_tabela_itens(estilos, orcamento))
    conteudo.extend(_resumo(estilos, orcamento))
    marca_dagua = _desenhar_marca_dagua(orcamento)
    doc.build(conteudo, onFirstPage=marca_dagua, onLaterPages=marca_dagua)
    return caminho
