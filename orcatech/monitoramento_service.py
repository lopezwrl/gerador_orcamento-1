import hashlib
import logging
import random
import re
import threading
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlsplit

from sqlalchemy import or_

from .comparador import STORE_LOCKS, comparar
from .models import (
    AlertaPreco,
    ControleVerificacaoLoja,
    Monitoramento,
    Orcamento,
    OrcamentoItem,
    PrecoHistorico,
    db,
)
from .orcamento_service import get_or_create_produto_busca, registrar_cotacao


logger = logging.getLogger(__name__)
_VERIFICACAO_LOCK = threading.Lock()
_PRECO_PERSISTENCIA_LOCK = threading.Lock()
_NOMES_LOJAS = {
    "mercadolivre": "Mercado Livre",
    "kabum": "KaBuM",
    "amazon": "Amazon",
    "terabyte": "Terabyte",
    "americanas": "Americanas",
    "ibyte": "iBytes",
    "gshield": "Gshield",
    "aliexpress": "AliExpress",
}
_INTERVALOS_HORAS = {
    "mercadolivre": 6,
    "kabum": 6,
    "amazon": 24,
    "terabyte": 6,
    "americanas": 6,
    "ibyte": 6,
    "gshield": 6,
    "aliexpress": 12,
}
_PALAVRAS_CONECTIVAS = {
    "a", "as", "ao", "aos", "com", "da", "das", "de", "do", "dos",
    "e", "em", "na", "nas", "no", "nos", "ou", "para", "por", "sem",
}
_TERMOS_ACESSORIO = {
    "almofada", "cabo", "capa", "case", "filtro", "mousepad",
    "mochila", "organizador", "pad", "pelicula", "suporte",
}


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _decimal(valor):
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not numero.is_finite():
        return None
    return numero.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _formatar_brl(valor):
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _normalizar(texto):
    texto = unicodedata.normalize("NFD", (texto or "").casefold())
    texto = "".join(
        caractere for caractere in texto
        if unicodedata.category(caractere) != "Mn"
    )
    return " ".join(re.findall(r"[a-z0-9]+", texto))


def modelos_compativeis(nome_esperado, nome_encontrado):
    esperados = set(_normalizar(nome_esperado).split()) - _PALAVRAS_CONECTIVAS
    encontrados = set(_normalizar(nome_encontrado).split())
    acessorios_adicionais = (_TERMOS_ACESSORIO & encontrados) - esperados
    return (
        bool(esperados)
        and not acessorios_adicionais
        and esperados.issubset(encontrados)
    )


def _chave_item(loja, nome, link):
    url = urlsplit((link or "").strip())
    identidade = url.path.rstrip("/") if url.scheme in {"http", "https"} else ""
    if not identidade:
        identidade = _normalizar(nome)
    material = f"{loja}|{url.netloc.casefold()}|{identidade.casefold()}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def registrar_preco_historico(
    cotacao,
    item_key=None,
    coletado_em=None,
):
    """Mantém somente o ponto mais recente de cada anúncio em cada dia."""
    coletado_em = coletado_em or _utcnow()
    preco = _decimal(cotacao.preco)
    if preco is None or preco <= 0:
        raise ValueError("O preço histórico deve ser um valor positivo.")

    fornecedor = cotacao.fornecedor
    chave = item_key or _chave_item(
        fornecedor.nome.casefold(),
        cotacao.nome_produto,
        cotacao.link,
    )
    dia = coletado_em.date()
    historico = PrecoHistorico.query.filter_by(item_key=chave, dia=dia).first()
    if historico is None:
        historico = PrecoHistorico(
            item_key=chave,
            produto_busca_id=cotacao.produto_busca_id,
            fornecedor_id=cotacao.fornecedor_id,
            cotacao_id=cotacao.id,
            nome_produto=cotacao.nome_produto,
            link=cotacao.link,
            preco=preco,
            dia=dia,
            coletado_em=coletado_em,
        )
        db.session.add(historico)
    else:
        historico.produto_busca_id = cotacao.produto_busca_id
        historico.fornecedor_id = cotacao.fornecedor_id
        historico.cotacao_id = cotacao.id
        historico.nome_produto = cotacao.nome_produto
        historico.link = cotacao.link
        historico.preco = preco
        historico.coletado_em = coletado_em
    return historico


def persistir_resultados_precos(termo_busca, produtos, coletado_em=None):
    with _PRECO_PERSISTENCIA_LOCK:
        return _persistir_resultados_precos(termo_busca, produtos, coletado_em)


def _persistir_resultados_precos(termo_busca, produtos, coletado_em=None):
    """Persiste cotações aprovadas pelo comparador e seus pontos diários."""
    coletado_em = coletado_em or _utcnow()
    validos = []
    for produto in produtos:
        loja = produto.get("site")
        nome = (produto.get("nome") or "").strip()
        preco = _decimal(produto.get("preco"))
        if loja not in _NOMES_LOJAS.values() or not nome or preco is None or preco <= 0:
            continue
        validos.append((produto, nome, preco, loja))
    if not validos:
        return 0

    produto_busca = get_or_create_produto_busca(termo_busca)
    quantidade = 0
    for produto, nome, preco, loja in validos:
        cotacao = registrar_cotacao(
            produto_busca,
            nome,
            float(preco),
            loja,
            link=(produto.get("link") or "")[:500] or None,
            imagem=(produto.get("imagem") or "")[:500] or None,
        )
        registrar_preco_historico(cotacao, coletado_em=coletado_em)
        quantidade += 1
    db.session.commit()
    return quantidade


def _intervalo_loja(loja):
    return timedelta(hours=_INTERVALOS_HORAS[loja])


def _obter_controle(loja):
    controle = ControleVerificacaoLoja.query.filter_by(loja=loja).first()
    if controle is None:
        controle = ControleVerificacaoLoja(loja=loja)
        db.session.add(controle)
        db.session.flush()
    return controle


def _reservar_controle(loja, agora):
    _obter_controle(loja)
    db.session.commit()
    reservado = (
        ControleVerificacaoLoja.query.filter_by(loja=loja)
        .filter(
            or_(
                ControleVerificacaoLoja.proxima_permitida.is_(None),
                ControleVerificacaoLoja.proxima_permitida <= agora,
            ),
            or_(
                ControleVerificacaoLoja.bloqueada_ate.is_(None),
                ControleVerificacaoLoja.bloqueada_ate <= agora,
            ),
            or_(
                ControleVerificacaoLoja.lease_ate.is_(None),
                ControleVerificacaoLoja.lease_ate <= agora,
            ),
        )
        .update(
            {"lease_ate": agora + timedelta(minutes=30)},
            synchronize_session=False,
        )
    )
    db.session.commit()
    if not reservado:
        return None
    db.session.expire_all()
    return ControleVerificacaoLoja.query.filter_by(loja=loja).one()


def _atualizar_agenda_monitoramentos(monitoramentos, proxima):
    for monitoramento in monitoramentos:
        monitoramento.ultimo_check = _utcnow()
        monitoramento.proxima_verificacao = proxima


def _precos_orcamentos_abertos(monitoramento):
    itens = (
        OrcamentoItem.query.join(Orcamento)
        .filter(
            Orcamento.usuario_id == monitoramento.usuario_id,
            Orcamento.status.in_(
                ("rascunho", "em_cotacao", "aguardando_aprovacao")
            ),
        )
        .all()
    )
    referencias = []
    for item in itens:
        if modelos_compativeis(monitoramento.nome_modelo, item.nome_produto):
            preco = _decimal(item.preco_unitario)
            if preco and preco > 0:
                referencias.append(preco)
    return referencias


def _cumpre_gatilho(monitoramento, referencia, preco_novo):
    reducao = referencia - preco_novo
    if reducao <= 0:
        return False
    if monitoramento.gatilho_percentual is not None:
        percentual = Decimal(monitoramento.gatilho_percentual)
        return reducao * 100 >= referencia * percentual
    return reducao >= Decimal(monitoramento.gatilho_valor)


def _notificar_por_email(app, monitoramento, alerta):
    if not app.config.get("ALERTAS_PRECO_POR_EMAIL"):
        return

    from .email_service import enfileirar_email

    assunto = f"Queda de preço: {monitoramento.nome_modelo}"
    url = (
        f"{app.config['APP_BASE_URL']}/monitoramentos"
        f"#monitoramento-{monitoramento.id}"
    )
    texto = (
        f"O produto {monitoramento.nome_modelo} na loja "
        f"{monitoramento.fornecedor.nome} caiu de R$ "
        f"{_formatar_brl(alerta.preco_anterior)} para R$ "
        f"{_formatar_brl(alerta.preco_novo)}.\n"
        f"Acompanhe o histórico: {url}"
    )
    try:
        enfileirar_email(
            app,
            None,
            monitoramento.usuario_id,
            monitoramento.usuario.email,
            anexar_pdf=False,
            assunto=assunto,
            mensagem_texto=texto,
        )
    except (ValueError, RuntimeError) as exc:
        logger.warning(
            "E-mail do alerta de preço %s não foi enfileirado (%s).",
            alerta.id,
            type(exc).__name__,
        )


def _registrar_alerta(monitoramento, preco_novo):
    referencias = [
        (Decimal(monitoramento.preco_referencia), "monitoramento"),
        *(
            (referencia, "orcamento")
            for referencia in _precos_orcamentos_abertos(monitoramento)
        ),
    ]
    qualificadas = [
        referencia for referencia in referencias
        if _cumpre_gatilho(monitoramento, referencia[0], preco_novo)
    ]
    if not qualificadas:
        return None

    referencia, origem = max(qualificadas, key=lambda item: item[0])
    existente = AlertaPreco.query.filter_by(
        monitoramento_id=monitoramento.id,
        preco_novo=preco_novo,
    ).first()
    if existente:
        return None

    alerta = AlertaPreco(
        monitoramento_id=monitoramento.id,
        preco_anterior=referencia,
        preco_novo=preco_novo,
        reducao=referencia - preco_novo,
        origem_referencia=origem,
    )
    db.session.add(alerta)
    db.session.flush()
    return alerta


def _registrar_falha(controle, status, agora):
    controle.falhas_consecutivas += 1
    fator = min(2 ** (controle.falhas_consecutivas - 1), 48)
    base_segundos = 3600 if status == "blocked" else 1800
    atraso = min(base_segundos * fator, 24 * 3600)
    proxima = agora + timedelta(seconds=atraso)
    if status == "blocked" and controle.falhas_consecutivas >= 3:
        controle.bloqueada_ate = agora + timedelta(hours=6)
        proxima = max(proxima, controle.bloqueada_ate)
    controle.proxima_permitida = proxima
    controle.ultimo_status = status
    return proxima


def _jitter(app):
    maximo = app.config.get("MONITORAMENTO_JITTER_SEGUNDOS", 300)
    return timedelta(seconds=random.randint(0, maximo)) if maximo else timedelta(0)


def _buscar_monitoramentos_vencidos(agora):
    vencidos = (
        Monitoramento.query.filter(
            Monitoramento.ativo.is_(True),
            Monitoramento.proxima_verificacao <= agora,
        )
        .order_by(Monitoramento.proxima_verificacao, Monitoramento.id)
        .all()
    )
    agrupados = defaultdict(list)
    for monitoramento in vencidos:
        agrupados[
            (monitoramento.loja, monitoramento.produto_busca.nome_pesquisado)
        ].append(monitoramento)
    return agrupados


def verificar_precos(app, agora=None):
    """Executa no máximo uma consulta por loja e por intervalo permitido."""
    if not _VERIFICACAO_LOCK.acquire(blocking=False):
        return {"status": "already_running", "consultas": 0, "alertas": 0}

    try:
        with app.app_context():
            agora = agora or _utcnow()
            agrupados = _buscar_monitoramentos_vencidos(agora)
            por_loja = defaultdict(list)
            for chave, monitoramentos in agrupados.items():
                por_loja[chave[0]].append((chave, monitoramentos))

            resumo = {"status": "completed", "consultas": 0, "alertas": 0, "ignorados": 0}
            for loja, grupos in por_loja.items():
                if loja not in STORE_LOCKS:
                    logger.error("Monitoramento com identificador de loja inválido: %s", loja)
                    resumo["ignorados"] += len(grupos)
                    continue

                grupos.sort(
                    key=lambda par: min(m.proxima_verificacao for m in par[1])
                )
                (chave, monitoramentos) = grupos[0]
                if STORE_LOCKS[loja].locked():
                    resumo["ignorados"] += 1
                    continue

                controle = _reservar_controle(loja, agora)
                if not controle:
                    resumo["ignorados"] += len(grupos)
                    continue
                termo_busca = chave[1]
                try:
                    resultado = comparar(
                        termo_busca,
                        forcar_busca=False,
                        lojas_incluir={loja},
                        salvar_cache=False,
                        pular_lojas_ocupadas=True,
                    )
                    status_loja = resultado.get("lojas_status", {}).get(loja, "error")
                    if status_loja == "busy":
                        controle.lease_ate = None
                        db.session.commit()
                        resumo["ignorados"] += 1
                        continue
                    if status_loja in {"blocked", "error"}:
                        proxima = _registrar_falha(controle, status_loja, agora)
                        controle.lease_ate = None
                        controle.ultimo_erro_tipo = status_loja
                        _atualizar_agenda_monitoramentos(monitoramentos, proxima)
                        db.session.commit()
                        continue

                    intervalo = _intervalo_loja(loja)
                    proxima = agora + intervalo + _jitter(app)
                    controle.lease_ate = None
                    controle.falhas_consecutivas = 0
                    controle.ultimo_status = "success"
                    controle.ultimo_erro_tipo = None
                    controle.bloqueada_ate = None
                    if not resultado.get("do_cache"):
                        controle.ultima_verificacao = agora
                        controle.proxima_permitida = proxima
                        persistir_resultados_precos(
                            termo_busca, resultado.get("produtos", []), coletado_em=agora
                        )
                        resultados_da_loja = [
                            produto for produto in resultado.get("produtos", [])
                            if produto.get("site") == _NOMES_LOJAS[loja]
                        ]
                        alertas_novos = []
                        for monitoramento in monitoramentos:
                            for produto in resultados_da_loja:
                                if not modelos_compativeis(
                                    monitoramento.nome_modelo, produto.get("nome", "")
                                ):
                                    continue
                                preco = _decimal(produto.get("preco"))
                                if preco and preco > 0:
                                    alerta = _registrar_alerta(monitoramento, preco)
                                    if alerta:
                                        resumo["alertas"] += 1
                                        alertas_novos.append((monitoramento, alerta))
                    else:
                        alertas_novos = []
                    _atualizar_agenda_monitoramentos(monitoramentos, proxima)
                    db.session.commit()
                    for monitoramento, alerta in alertas_novos:
                        _notificar_por_email(app, monitoramento, alerta)
                    resumo["consultas"] += 1
                except Exception:
                    db.session.rollback()
                    controle = db.session.get(ControleVerificacaoLoja, controle.id)
                    controle.lease_ate = None
                    proxima = _registrar_falha(controle, "error", agora)
                    db.session.commit()
                    raise

            return resumo
    finally:
        _VERIFICACAO_LOCK.release()
