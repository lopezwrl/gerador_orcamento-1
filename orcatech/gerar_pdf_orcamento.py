"""
gerar_pdf_orcamento.py — gera o PDF de um Orçamento com vários itens
(diferente de gerar_pdf.py, que gera o comparativo de UMA busca só).
Reaproveita paleta, estilos e bloco de aprovação de gerar_pdf.py.
"""

import os
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
)
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle

from .gerar_pdf import (
    _st, _aprovacao, EMPRESA, SLOGAN, PASTA_PDF,
    NAVY, ROYAL, ICE, ICE2, TEAL, TEAL2, BORDER, MUTED, TEXT, WHITE, W,
)


def _fmt_brl(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _cabecalho_orcamento(st, orcamento):
    agora = datetime.now().strftime("%d/%m/%Y às %H:%M")
    el = []

    marca_block = [Paragraph(EMPRESA, st["marca"]), Paragraph(SLOGAN, st["slogan"])]
    titulo_block = [
        Paragraph("ORÇAMENTO DE COMPRA", st["doc_titulo"]),
        Paragraph(f"Nº {orcamento.numero}", st["doc_num"]),
    ]

    topo = Table([[marca_block, titulo_block]], colWidths=[W * 0.55, W * 0.45])
    topo.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 0),
    ]))
    el.append(topo)
    el.append(Spacer(1, 14))
    el.append(HRFlowable(width="100%", thickness=2.2, color=NAVY))
    el.append(Spacer(1, 16))

    meta = Table([
        [Paragraph("ITENS NO ORÇAMENTO", st["meta_k"]), Paragraph(str(len(orcamento.itens)), st["meta_v"])],
        [Paragraph("DATA E HORA", st["meta_k"]), Paragraph(agora, st["meta_v"])],
        [Paragraph("SOLICITANTE", st["meta_k"]), Paragraph(orcamento.solicitante or "Não informado", st["meta_v"])],
        [Paragraph("STATUS", st["meta_k"]), Paragraph(orcamento.status.replace("_", " ").title(), st["meta_v"])],
    ], colWidths=[W * 0.28, W * 0.72])
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ICE2),
        ("GRID", (0, 0), (-1, -1), 0, WHITE),
        ("LINEBELOW", (0, 0), (-1, 2), 0.6, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    el.append(meta)
    el.append(Spacer(1, 22))
    return el


def _tabela_itens(st, orcamento):
    el = []
    el.append(Paragraph("Itens do Orçamento", st["secao"]))
    el.append(Spacer(1, 8))

    cab_style = st["th"]
    cel_style = st["cell"]

    linhas = [[
        Paragraph("Produto", cab_style), Paragraph("Fornecedor", cab_style),
        Paragraph("Qtd", st["th_centro"]), Paragraph("Preço Unit.", cab_style),
        Paragraph("Subtotal", cab_style),
    ]]

    for item in orcamento.itens:
        cot = item.cotacao_escolhida
        nome = cot.nome_produto if cot else item.produto_busca.nome_pesquisado
        fornecedor = cot.fornecedor.nome if cot else "—"
        preco_unit = cot.preco if cot else 0.0
        linhas.append([
            Paragraph(nome[:60], cel_style),
            Paragraph(fornecedor, cel_style),
            Paragraph(str(item.quantidade), st["cell_centro"]),
            Paragraph(_fmt_brl(preco_unit), cel_style),
            Paragraph(_fmt_brl(item.subtotal), cel_style),
        ])

    tabela = Table(linhas, colWidths=[W * 0.36, W * 0.22, W * 0.1, W * 0.16, W * 0.16])
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, ICE2]),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    el.append(tabela)
    el.append(Spacer(1, 18))
    return el


def _resumo_orcamento(st, orcamento):
    el = []
    total_style = ParagraphStyle(
        "total", fontSize=13, fontName="Helvetica-Bold",
        textColor=NAVY, alignment=TA_RIGHT, leading=16,
    )
    linha = Table([
        ["", Paragraph(f"TOTAL GERAL: {_fmt_brl(orcamento.total)}", total_style)],
    ], colWidths=[W * 0.55, W * 0.45])
    linha.setStyle(TableStyle([
        ("BACKGROUND", (1, 0), (1, 0), TEAL2),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (1, 0), (1, 0), 16),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    el.append(linha)
    if orcamento.condicoes_comerciais:
        el.append(Spacer(1, 10))
        el.append(Paragraph(f"<b>Condições comerciais:</b> {orcamento.condicoes_comerciais}", st["meta_v"]))
    if orcamento.observacoes:
        el.append(Spacer(1, 6))
        el.append(Paragraph(f"<b>Observações:</b> {orcamento.observacoes}", st["meta_v"]))
    el.append(Spacer(1, 20))
    return el


def gerar_pdf_orcamento(orcamento):
    nome_arquivo = f"orcamento_{orcamento.numero}.pdf"
    caminho = os.path.join(PASTA_PDF, nome_arquivo)

    doc = SimpleDocTemplate(
        caminho, pagesize=A4,
        leftMargin=1.6 * cm, rightMargin=1.6 * cm,
        topMargin=1.6 * cm, bottomMargin=1.6 * cm,
    )

    st = _st()
    conteudo = []
    conteudo += _cabecalho_orcamento(st, orcamento)
    conteudo += _tabela_itens(st, orcamento)
    conteudo += _resumo_orcamento(st, orcamento)
    conteudo += _aprovacao(st, orcamento.solicitante)

    doc.build(conteudo)
    print(f"[PDF] Orçamento gerado: {caminho}")
    return caminho
