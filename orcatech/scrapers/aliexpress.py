"""
scraping_aliexpress.py — AliExpress Brasil (Playwright)

Busca pública em https://pt.aliexpress.com/w/wholesale-<termo>.html (moeda
em R$, títulos em português) renderizada num Chromium real via Playwright,
com configurações para não parecer automação.

Requisitos:
    pip install playwright
(usa o Google Chrome já instalado via channel="chrome"; se não achar, cai no
Chromium do Playwright — nesse caso rode uma vez:  playwright install chromium)

Interface igual à das outras lojas: buscar_aliexpress(produto) -> lista de
dicts {site, nome, preco_texto, preco, imagem, link, specs}.
"""
import re
from urllib.parse import quote

from ..paths import DEBUG_DIR
from .driver_manager import SELENIUM_SEMAPHORE, versao_principal_chrome
from .errors import BloqueioLoja

BASE = "https://pt.aliexpress.com"
SELETOR_CARDS = "div.search-item-card-wrapper-gallery, a.search-card-item"
_RE_PRECO = re.compile(r"R\$\s*([\d\.,]+)")


# ───────────────────────── utilidades ─────────────────────────

def _fmt_preco(txt):
    """Acha o primeiro 'R$ 9,04' no texto. Retorna (float, 'R$ 9,04')."""
    m = _RE_PRECO.search(txt or "")
    if not m:
        return 0.0, "R$ --"
    s = m.group(1).rstrip(".,")
    try:
        if "," in s:
            v = float(s.replace(".", "").replace(",", "."))
        elif re.fullmatch(r"\d+\.\d{2}", s):
            v = float(s)
        else:
            v = float(s.replace(".", ""))
    except ValueError:
        return 0.0, "R$ --"
    if v <= 0:
        return 0.0, "R$ --"
    return v, f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _url_abs(u):
    u = (u or "").strip()
    if not u or u.startswith("data:"):
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return BASE + u
    return u


def _extrair_nome(texto_card):
    linhas = [l.strip() for l in (texto_card or "").split("\n") if l.strip()]
    candidatas = [
        l for l in linhas
        if len(l) >= 15 and "R$" not in l
        and not re.fullmatch(r"[\d\.\,\+\s]*(vendido|vendidos)?", l, re.I)
    ]
    return max(candidatas, key=len) if candidatas else ""


def _extrair_card(card):
    txt = card.inner_text() or ""
    preco, preco_texto = _fmt_preco(txt)
    nome = _extrair_nome(txt)

    link = ""
    try:
        if card.evaluate("e => e.tagName") == "A":
            link = card.get_attribute("href") or ""
        else:
            a = card.query_selector("a")
            link = (a.get_attribute("href") if a else "") or ""
    except Exception:
        pass

    imagem = ""
    try:
        img = card.query_selector("img")
        if img:
            imagem = img.get_attribute("src") or img.get_attribute("data-src") or ""
    except Exception:
        pass

    return nome, preco, preco_texto, _url_abs(link), _url_abs(imagem)


def _diagnosticar(page):
    try:
        print(f"[AliExpress][DEBUG] URL final: {page.url} | título: {page.title()!r}")
        html = page.content()
        arquivo_debug = DEBUG_DIR / "debug_aliexpress.html"
        with open(arquivo_debug, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[AliExpress] HTML de diagnóstico salvo em {arquivo_debug}")
        baixo = html.lower()
        bloqueada = (
            "punish" in page.url
            or "captcha" in baixo
            or "slide to verify" in baixo
        )
        if bloqueada:
            print("[AliExpress] Verificação anti-bot (captcha/slider) detectada.")
        elif "login" in page.url:
            print("[AliExpress] Redirecionou para login.")
        else:
            print("[AliExpress] Nenhum card conhecido apareceu (seletores podem ter mudado).")
        return bloqueada
    except Exception:
        return False


# ───────────────────────── busca ─────────────────────────

def buscar_aliexpress(produto):
    with SELENIUM_SEMAPHORE:
        return _buscar_aliexpress(produto)


def _buscar_aliexpress(produto):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[AliExpress] Playwright não instalado. Rode: pip install playwright")
        return []

    termo = quote(produto.strip().replace(" ", "-"), safe="-")
    url = f"{BASE}/w/wholesale-{termo}.html"
    print(f"[AliExpress] Buscando: '{produto}'")
    print(f"[AliExpress] GET {url}")

    args = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    versao = versao_principal_chrome() or 124
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{versao}.0.0.0 Safari/537.36"
    )

    produtos = []
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chrome", headless=True, args=args)
            except Exception:
                print("[AliExpress] Chrome instalado não encontrado — usando Chromium do Playwright")
                browser = p.chromium.launch(headless=True, args=args)

            try:
                context = browser.new_context(
                    user_agent=user_agent, locale="pt-BR",
                    viewport={"width": 1920, "height": 1080},
                )
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)

                try:
                    page.wait_for_selector(SELETOR_CARDS, timeout=20000)
                except Exception:
                    if _diagnosticar(page):
                        raise BloqueioLoja("AliExpress sinalizou verificação anti-bot.")
                    return []

                # rola a página para o AliExpress carregar preços/imagens (lazy load)
                for _ in range(3):
                    page.mouse.wheel(0, 1400)
                    page.wait_for_timeout(700)

                cards = page.query_selector_all(SELETOR_CARDS)
                print(f"[AliExpress] {len(cards)} cards encontrados")

                for card in cards[:25]:
                    try:
                        nome, preco, preco_texto, link, imagem = _extrair_card(card)
                        if not nome or preco <= 0 or not link:
                            continue
                        produtos.append({
                            "site": "AliExpress",
                            "nome": nome[:200],
                            "preco_texto": preco_texto,
                            "preco": preco,
                            "imagem": imagem,
                            "link": link,
                            "specs": [],
                        })
                        if len(produtos) >= 10:
                            break
                    except Exception:
                        continue
            finally:
                browser.close()
    except BloqueioLoja:
        raise
    except Exception as e:
        print(f"[AliExpress] Erro geral: {e}")

    print(f"[AliExpress] {len(produtos)} produtos extraídos")
    return produtos
