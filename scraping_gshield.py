"""
scraping_gshield.py — Gshield

A loja migrou de gshield.com.br para www.gorilashield.com.br (Loja Integrada).
A busca antiga (/busca/<termo>) só devolve a home; a busca nova é
/buscar?q=<termo>.

Acesso ao HTML, em ordem:
  1) curl_cffi imitando o TLS de um Chrome real  (pip install curl_cffi)
  2) undetected-chromedriver com janela fora da tela (se o 1 não trouxer produtos)

Parsing: não depende de nomes de classe (o tema muda). Cada produto é achado
pelo título (<h2>/<h3> com link); o card é o menor bloco ao redor que tem foto
e preço. Se o site mudar, o HTML recebido fica salvo em debug_gshield_*.html.
"""

import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from driver_manager import SELENIUM_SEMAPHORE, UC_START_LOCK, versao_principal_chrome

BASE = "https://www.gorilashield.com.br"
_CABECALHOS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": BASE + "/",
}
_RE_PRECO = re.compile(r"R\$\s*([\d\.]+,\d{2})")
_RE_PARCELA = re.compile(r"\d+\s*x\s+de\b", re.I)


def _fmt_preco(valor):
    try:
        s = re.sub(r"[^\d,.]", "", str(valor).strip())
        if not s:
            return 0.0, "R$ --"
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", ".")
        v = float(s)
        if v <= 0:
            return 0.0, "R$ --"
        txt = f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return v, txt
    except Exception:
        return 0.0, "R$ --"


def _salvar_debug(html, sufixo):
    try:
        with open(f"debug_gshield_{sufixo}.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[Gshield] HTML salvo em debug_gshield_{sufixo}.html")
    except Exception:
        pass


# ───────────────────────── download do HTML ─────────────────────────

def _html_via_curl_cffi(url):
    try:
        from curl_cffi import requests as cffi
    except ImportError:
        print("[Gshield] curl_cffi não instalado (pip install curl_cffi) — pulando esta tentativa")
        return ""
    try:
        r = cffi.get(url, impersonate="chrome", headers=_CABECALHOS, timeout=15, allow_redirects=True)
        print(f"[Gshield] curl_cffi Status: {r.status_code} | URL final: {r.url}")
        if r.status_code == 200 and r.text:
            return r.text
    except Exception as e:
        print(f"[Gshield] curl_cffi erro: {e}")
    return ""


def _html_via_navegador(url):
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    options = uc.ChromeOptions()
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=pt-BR")
    options.add_argument("--window-position=-2400,-2400")

    driver = None
    try:
        with SELENIUM_SEMAPHORE:
            with UC_START_LOCK:
                driver = uc.Chrome(
                    options=options, headless=False, use_subprocess=True,
                    version_main=versao_principal_chrome(),
                )
            driver.set_page_load_timeout(45)
            driver.get(url)
            try:
                WebDriverWait(driver, 15).until(
                    lambda d: d.find_elements(By.CSS_SELECTOR, "h2 a, h3 a")
                )
            except Exception:
                pass
            print(f"[Gshield] navegador URL final: {driver.current_url} | título: {driver.title!r}")
            return driver.page_source
    except Exception as e:
        print(f"[Gshield] navegador erro: {e}")
        return ""
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ───────────────────────── parsing ─────────────────────────

def _titulos_com_link(soup):
    return [h for h in soup.find_all(["h2", "h3"]) if h.find("a", href=True)]


def _achar_card(titulo):
    """Menor ancestral do título que tem foto e preço e só um título de produto."""
    node = titulo.parent
    for _ in range(6):
        if node is None:
            return None
        if node.find("img") and "R$" in node.get_text(" ", strip=True):
            return node if len(_titulos_com_link(node)) <= 1 else None
        node = node.parent
    return None


def _preco_do_card(texto):
    """Ignora o preço da parcela ('6x de R$ 6,66') e usa o último preço antes dela
    (numa oferta aparece 'R$ 79,99 R$ 39,97': o último é o preço atual)."""
    corte = _RE_PARCELA.search(texto)
    trecho = texto[:corte.start()] if corte else texto
    precos = _RE_PRECO.findall(trecho) or _RE_PRECO.findall(texto)
    return _fmt_preco(precos[-1]) if precos else (0.0, "R$ --")


def _url_abs(u):
    u = (u or "").strip()
    if not u or u.startswith("data:"):
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return BASE + u
    return u


def _parse(html):
    soup = BeautifulSoup(html, "html.parser")
    produtos, vistos = [], set()

    # 1) Tema moderno Loja Integrada (web component <product-card>)
    cards = soup.find_all("product-card")
    if not cards:
        cards = soup.find_all(lambda tag: tag.name in ("div", "article") and "gs-product-card" in tag.get("class", []))

    for card in cards:
        try:
            a = card.find("a", attrs={"data-id": "product-url"}) or card.find("a", href=True)
            if not a:
                continue
            nome = (a.get("title") or a.get_text(" ", strip=True)).strip()
            rel_url = card.get("data-url") or a.get("href", "")
            link = _url_abs(rel_url)
            if len(nome) < 3 or not link or link in vistos:
                continue

            texto = card.get_text(" ", strip=True)
            preco, preco_texto = _preco_do_card(texto)
            if preco <= 0:
                continue

            img = card.find("img", attrs={"data-id": "product-image"}) or card.find("img")
            imagem = ""
            if img:
                for attr in ("src", "data-src", "data-lazy", "data-original"):
                    imagem = _url_abs(img.get(attr, ""))
                    if imagem:
                        break

            vistos.add(link)
            produtos.append({
                "site": "Gshield", "nome": nome[:200],
                "preco_texto": preco_texto, "preco": preco,
                "imagem": imagem, "link": link, "specs": [],
            })
        except Exception:
            continue

    # 2) Fallback para tema clássico (título h2/h3 com link)
    if not produtos:
        for titulo in _titulos_com_link(soup):
            try:
                a = titulo.find("a", href=True)
                if not a:
                    continue
                nome = (a.get("title") or titulo.get_text(" ", strip=True)).strip()
                link = _url_abs(a["href"])
                if len(nome) < 4 or not link or link in vistos:
                    continue

                card = _achar_card(titulo)
                if card is None:
                    continue

                texto = card.get_text(" ", strip=True).replace(nome, " ")
                preco, preco_texto = _preco_do_card(texto)
                if preco <= 0:
                    continue

                imagem = ""
                for img in card.find_all("img"):
                    for attr in ("src", "data-src", "data-lazy", "data-original"):
                        imagem = _url_abs(img.get(attr, ""))
                        if imagem:
                            break
                    if imagem:
                        break

                vistos.add(link)
                produtos.append({
                    "site": "Gshield", "nome": nome[:200],
                    "preco_texto": preco_texto, "preco": preco,
                    "imagem": imagem, "link": link, "specs": [],
                })
            except Exception:
                continue

    print(f"[Gshield] {len(produtos)} produtos no HTML")
    return produtos[:15]


def buscar_gshield(produto):
    print(f"[Gshield] Buscando: '{produto}'")
    url = f"{BASE}/buscar?q={quote_plus(produto)}"
    print(f"[Gshield] GET {url}")

    produtos = []
    try:
        html = _html_via_curl_cffi(url)
        if html:
            produtos = _parse(html)
            if not produtos:
                _salvar_debug(html, "curl")
        if not produtos:
            print("[Gshield] Sem resultado pelo método leve — tentando com navegador...")
            html = _html_via_navegador(url)
            if html:
                produtos = _parse(html)
                if not produtos:
                    _salvar_debug(html, "navegador")
    except Exception as e:
        print(f"[Gshield] Erro: {e}")

    print(f"[Gshield] {len(produtos)} produtos extraídos")
    return produtos