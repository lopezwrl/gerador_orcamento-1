from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer, HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from datetime import datetime
import os

# ══════════════════════════════════════════════════════════
#  PALETA — mesma identidade visual usada nos HTMLs do sistema
# ══════════════════════════════════════════════════════════
NAVY    = colors.HexColor("#1e2a6e")
ROYAL   = colors.HexColor("#2d3a8c")
SKY     = colors.HexColor("#5b78e0")
ICE     = colors.HexColor("#dde5ff")
ICE2    = colors.HexColor("#f0f2fa")
TEAL    = colors.HexColor("#0a8a79")
TEAL2   = colors.HexColor("#d1fae5")
GOLD    = colors.HexColor("#e69500")
GOLD2   = colors.HexColor("#fef3c7")
PURPLE  = colors.HexColor("#7c3aed")
PURPLE2 = colors.HexColor("#ede9fe")
RED     = colors.HexColor("#dc2626")
RED2    = colors.HexColor("#fee2e2")
BORDER  = colors.HexColor("#d4d9ef")
MUTED   = colors.HexColor("#6070a8")
TEXT    = colors.HexColor("#1a2040")
TEXT2   = colors.HexColor("#374080")
WHITE   = colors.white

EMPRESA   = "ORÇATECH"
SLOGAN    = "Comparador Inteligente de Preços"
PASTA_PDF = "orcamentos"
os.makedirs(PASTA_PDF, exist_ok=True)

W = A4[0] - 3.2 * cm   # largura útil da página (margens de 1.6cm cada lado)


# ══════════════════════════════════════════════════════════
#  ESTILOS DE TEXTO
# ══════════════════════════════════════════════════════════
def _st():
    return {
        "marca": ParagraphStyle(
            "marca", fontSize=22, fontName="Helvetica-Bold",
            textColor=NAVY, spaceAfter=3, leading=26, tracking=0.5
        ),
        "slogan": ParagraphStyle(
            "slogan", fontSize=9.5, fontName="Helvetica",
            textColor=MUTED, spaceAfter=0, leading=13
        ),
        "doc_titulo": ParagraphStyle(
            "doc_titulo", fontSize=12, fontName="Helvetica-Bold",
            textColor=ROYAL, alignment=TA_RIGHT, spaceAfter=4, leading=15
        ),
        "doc_num": ParagraphStyle(
            "doc_num", fontSize=9, fontName="Helvetica",
            textColor=MUTED, alignment=TA_RIGHT, leading=12
        ),
        "secao": ParagraphStyle(
            "secao", fontSize=13, fontName="Helvetica-Bold",
            textColor=NAVY, spaceBefore=18, spaceAfter=10, leading=16
        ),
        "cell": ParagraphStyle(
            "cell", fontSize=8.5, fontName="Helvetica",
            leading=12, textColor=TEXT
        ),
        "cell_centro": ParagraphStyle(
            "cell_centro", fontSize=8.5, fontName="Helvetica",
            leading=12, textColor=TEXT, alignment=TA_CENTER
        ),
        "num_centro": ParagraphStyle(
            "num_centro", fontSize=8.5, fontName="Helvetica",
            leading=12, textColor=TEXT, alignment=TA_CENTER, wordWrap=None
        ),
        "cell_bold_centro": ParagraphStyle(
            "cell_bold_centro", fontSize=8.5, fontName="Helvetica-Bold",
            leading=12, textColor=TEXT, alignment=TA_CENTER
        ),
        "th": ParagraphStyle(
            "th", fontSize=8.5, fontName="Helvetica-Bold",
            textColor=WHITE, leading=11
        ),
        "th_centro": ParagraphStyle(
            "th_centro", fontSize=8.5, fontName="Helvetica-Bold",
            textColor=WHITE, alignment=TA_CENTER, leading=11
        ),
        "rodape": ParagraphStyle(
            "rodape", fontSize=8, fontName="Helvetica",
            textColor=MUTED, alignment=TA_CENTER, leading=11
        ),
        "meta_k": ParagraphStyle(
            "meta_k", fontSize=8.5, fontName="Helvetica-Bold",
            textColor=NAVY, leading=12
        ),
        "meta_v": ParagraphStyle(
            "meta_v", fontSize=8.5, fontName="Helvetica",
            textColor=TEXT, leading=12
        ),
    }


# ══════════════════════════════════════════════════════════
#  CABEÇALHO
# ══════════════════════════════════════════════════════════
def _cabecalho(st, produto, solicitante):
    agora   = datetime.now().strftime("%d/%m/%Y às %H:%M")
    num_orc = f"ORC-{datetime.now().strftime('%Y%m%d%H%M')}"
    el = []

    marca_block = [
        Paragraph(EMPRESA, st["marca"]),
        Paragraph(SLOGAN, st["slogan"]),
    ]
    titulo_block = [
        Paragraph("ORÇAMENTO DE COMPRA", st["doc_titulo"]),
        Paragraph(f"Nº {num_orc}", st["doc_num"]),
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

    # Metadados — espaçamento generoso, sem aperto
    meta = Table([
        [Paragraph("PRODUTO PESQUISADO", st["meta_k"]), Paragraph(produto, st["meta_v"])],
        [Paragraph("DATA E HORA",        st["meta_k"]), Paragraph(agora, st["meta_v"])],
        [Paragraph("SOLICITANTE",        st["meta_k"]), Paragraph(solicitante or "Não informado", st["meta_v"])],
    ], colWidths=[W * 0.28, W * 0.72])
    meta.setStyle(TableStyle([
        ("BACKGROUND",      (0, 0), (-1, -1), ICE2),
        ("ROUNDEDCORNERS",  [6, 6, 6, 6]),
        ("GRID",            (0, 0), (-1, -1), 0, WHITE),
        ("LINEBELOW",       (0, 0), (-1, 1), 0.6, BORDER),
        ("TOPPADDING",      (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING",   (0, 0), (-1, -1), 10),
        ("LEFTPADDING",     (0, 0), (-1, -1), 14),
        ("RIGHTPADDING",    (0, 0), (-1, -1), 14),
        ("VALIGN",          (0, 0), (-1, -1), "MIDDLE"),
    ]))
    el.append(meta)
    el.append(Spacer(1, 22))
    return el


# ══════════════════════════════════════════════════════════
#  TABELA COMPARATIVA
# ══════════════════════════════════════════════════════════
def _marcador(cor):
    """Pequeno quadrado colorido — substitui emojis que não renderizam no ReportLab."""
    return f'<font color="{cor.hexval()}">■</font>'


def _tabela_resultados(st, produtos):
    el = []
    el.append(Paragraph("Comparativo de Preços", st["secao"]))

    cab = [
        Paragraph("#",             st["th_centro"]),
        Paragraph("Loja",          st["th"]),
        Paragraph("Produto",       st["th"]),
        Paragraph("Preço",         st["th_centro"]),
        Paragraph("Classificação", st["th_centro"]),
    ]
    linhas = [cab]

    precos = [p.get("preco", 0) for p in produtos if p.get("preco", 0) > 0]
    menor  = min(precos) if precos else None
    maior  = max(precos) if precos else None

    cores_linha = []
    for i, p in enumerate(produtos, 1):
        preco = p.get("preco", 0)
        nome = p.get("nome", "—")
        if len(nome) > 85:
            nome = nome[:82] + "..."

        tipo_raw = p.get("tipo", "—")
        # Remove qualquer emoji que tenha vindo do backend e troca por marcador colorido
        tipo_limpo = tipo_raw
        for em in ("💰", "🔥", "⭐"):
            tipo_limpo = tipo_limpo.replace(em, "").strip()

        if preco == menor:
            cor_tipo = TEAL
        elif preco == maior:
            cor_tipo = PURPLE
        else:
            cor_tipo = GOLD

        tipo_html = f'{_marcador(cor_tipo)} {tipo_limpo}'

        linhas.append([
            Paragraph(str(i), st["num_centro"]),
            Paragraph(p.get("site", "—"), st["cell"]),
            Paragraph(nome, st["cell"]),
            Paragraph(p.get("preco_texto", "—"), st["cell_bold_centro"]),
            Paragraph(tipo_html, st["cell_centro"]),
        ])
        if preco == menor:
            cores_linha.append((i, "menor"))
        elif preco == maior:
            cores_linha.append((i, "maior"))

    t = Table(
        linhas,
        colWidths=[W * 0.06, W * 0.175, W * 0.415, W * 0.14, W * 0.21],
        repeatRows=1
    )

    ts = TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, ICE2]),
        ("LINEBELOW",      (0, 0), (-1, -2), 0.5, BORDER),
        ("LINEBELOW",      (0, -1), (-1, -1), 0, WHITE),
        ("TOPPADDING",     (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING",  (0, 0), (-1, 0), 10),
        ("TOPPADDING",     (0, 1), (-1, -1), 9),
        ("BOTTOMPADDING",  (0, 1), (-1, -1), 9),
        ("LEFTPADDING",    (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 10),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
    ])
    for row_i, tipo in cores_linha:
        if tipo == "menor":
            ts.add("BACKGROUND", (3, row_i), (3, row_i), TEAL2)
            ts.add("TEXTCOLOR",  (3, row_i), (3, row_i), TEAL)
        else:
            ts.add("BACKGROUND", (3, row_i), (3, row_i), PURPLE2)
            ts.add("TEXTCOLOR",  (3, row_i), (3, row_i), PURPLE)

    t.setStyle(ts)
    el.append(t)
    el.append(Spacer(1, 22))
    return el


# ══════════════════════════════════════════════════════════
#  RESUMO DA PESQUISA
# ══════════════════════════════════════════════════════════
def _resumo(st, produtos):
    validos = [p for p in produtos if p.get("preco", 0) > 0]
    if not validos:
        return []

    barato   = min(validos, key=lambda x: x["preco"])
    premium  = max(validos, key=lambda x: x["preco"])
    media    = sum(p["preco"] for p in validos) / len(validos)
    economia = premium["preco"] - barato["preco"]
    lojas    = len(set(p["site"] for p in validos))

    def fmt(v):
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def linha_resumo(cor, label, nome, loja, valor, cor_val):
        return [
            Paragraph(f"{_marcador(cor)} {label}", ParagraphStyle(
                "rl", fontSize=9, fontName="Helvetica-Bold", textColor=NAVY, leading=12)),
            Paragraph(nome[:60], ParagraphStyle(
                "rn", fontSize=8.5, leading=12, textColor=TEXT)),
            Paragraph(loja, st["cell_centro"]),
            Paragraph(valor, ParagraphStyle(
                "rv", fontSize=9.5, fontName="Helvetica-Bold",
                textColor=cor_val, alignment=TA_CENTER, leading=12)),
        ]

    cab = [
        Paragraph("Indicador", st["th"]),
        Paragraph("Produto",   st["th"]),
        Paragraph("Loja",      st["th_centro"]),
        Paragraph("Valor",     st["th_centro"]),
    ]

    dados = [
        cab,
        linha_resumo(TEAL,   "Mais Barato",        barato["nome"],  barato["site"],  barato["preco_texto"],  TEAL),
        linha_resumo(PURPLE, "Premium",             premium["nome"], premium["site"], premium["preco_texto"], PURPLE),
        linha_resumo(NAVY,   "Preço Médio",         f"Média entre {len(validos)} produtos", f"{lojas} lojas", fmt(media), TEXT),
        linha_resumo(GOLD,   "Economia Possível",   "Diferença entre mais barato e premium", "", fmt(economia), GOLD),
    ]

    t = Table(dados, colWidths=[W * 0.22, W * 0.46, W * 0.16, W * 0.16])
    t.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0), ROYAL),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, ICE2]),
        ("BACKGROUND",     (0, 4), (-1, 4), GOLD2),
        ("LINEBELOW",      (0, 0), (-1, -2), 0.5, BORDER),
        ("TOPPADDING",     (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 10),
        ("LEFTPADDING",    (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 12),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
    ]))

    # KeepTogether garante que o título e a tabela não fiquem separados
    # entre duas páginas (evita o "buraco" de uma linha cortada no topo)
    bloco = KeepTogether([Paragraph("Resumo da Pesquisa", st["secao"]), t])
    return [bloco, Spacer(1, 22)]


# ══════════════════════════════════════════════════════════
#  ÁREA DE APROVAÇÃO
# ══════════════════════════════════════════════════════════
def _aprovacao(st, solicitante):
    el = []
    el.append(Paragraph("Aprovação do Orçamento", st["secao"]))

    obs_style = ParagraphStyle(
        "obs", fontSize=8.5, fontName="Helvetica-Bold", textColor=NAVY, leading=12
    )
    linha_style = ParagraphStyle("linha", fontSize=10, alignment=TA_CENTER, textColor=BORDER)
    nome_style  = ParagraphStyle("nomeassin", fontSize=8.5, alignment=TA_CENTER, textColor=MUTED, leading=12)

    t = Table([
        [Paragraph("Observações / Recomendação:", obs_style), ""],
        ["", ""],
        [Paragraph("_" * 36, linha_style), Paragraph("_" * 36, linha_style)],
        [Paragraph(solicitante or "Responsável pela Pesquisa", nome_style),
         Paragraph("Aprovador", nome_style)],
    ], colWidths=[W * 0.5, W * 0.5])

    t.setStyle(TableStyle([
        ("SPAN",           (0, 0), (1, 0)),
        ("BACKGROUND",     (0, 0), (-1, 0), ICE2),
        ("TOPPADDING",     (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING",  (0, 0), (-1, 0), 10),
        ("TOPPADDING",     (0, 1), (-1, 1), 24),
        ("TOPPADDING",     (0, 2), (-1, 2), 6),
        ("BOTTOMPADDING",  (0, 3), (-1, 3), 0),
        ("TOPPADDING",     (0, 3), (-1, 3), 4),
        ("LEFTPADDING",    (0, 0), (-1, -1), 14),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 14),
        ("LINEBELOW",      (0, 0), (-1, 0), 0.6, BORDER),
        ("BOX",            (0, 0), (-1, -1), 0.6, BORDER),
    ]))
    el.append(t)
    el.append(Spacer(1, 26))
    el.append(HRFlowable(width="100%", thickness=0.8, color=BORDER))
    el.append(Spacer(1, 8))
    el.append(Paragraph(
        f"Documento gerado automaticamente pelo {EMPRESA}  ·  "
        f"{datetime.now().strftime('%d/%m/%Y às %H:%M')}",
        st["rodape"]
    ))
    return [KeepTogether(el[:2])] + el[2:]


# ══════════════════════════════════════════════════════════
#  MONTAGEM FINAL DO PDF
# ══════════════════════════════════════════════════════════
def gerar_pdf(produto, produtos, solicitante=""):
    nome_arquivo = (
        f"orcamento_{produto.replace(' ', '_')}_"
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    )
    caminho = os.path.join(PASTA_PDF, nome_arquivo)

    doc = SimpleDocTemplate(
        caminho, pagesize=A4,
        leftMargin=1.6 * cm, rightMargin=1.6 * cm,
        topMargin=1.6 * cm, bottomMargin=1.6 * cm
    )

    st = _st()
    conteudo = []
    conteudo += _cabecalho(st, produto, solicitante)
    conteudo += _tabela_resultados(st, produtos)
    conteudo += _resumo(st, produtos)
    conteudo += _aprovacao(st, solicitante)

    doc.build(conteudo)
    print(f"[PDF] Gerado: {caminho}")
    return caminho