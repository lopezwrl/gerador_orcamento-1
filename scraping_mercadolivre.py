"""
scraping_mercadolivre.py

O Mercado Livre passou a:
  1) Bloquear Selenium "normal" com uma tela de verificação
     (/gz/account-verification) assim que detecta as fingerprints
     padrão do ChromeDriver.
  2) Bloquear também a API pública de busca (403 forbidden) sem token.

Solução: usar undetected-chromedriver (uc), que remove/mascara as
fingerprints que o ML usa pra flagar automação (navigator.webdriver,
strings cdc_ no chromedriver, etc). Instale antes de rodar:

    pip install undetected-chromedriver
"""
import re
from urllib.parse import urlparse

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

try:
    from driver_manager import SELENIUM_SEMAPHORE
except Exception:
    import threading
    SELENIUM_SEMAPHORE = threading.Semaphore(2)


_SELETORES_CARD = [
    "li.ui-search-layout__item",
    "div.ui-search-result__wrapper",
    "div[class*='poly-card']",
    "li[class*='ui-search-layout']",
    "div[class*='ui-search-result']",
]

_RE_LINK_PRODUTO = re.compile(r'/(MLB-?\d{6,})', re.I)


def buscar_mercadolivre(produto):
    with SELENIUM_SEMAPHORE:
        return _buscar_mercadolivre(produto)


def _extrair_de_card(card):
    nome = ""
    for sel in ["h3", "h2", "[class*='poly-component__title']",
                "a[class*='title']", "span[class*='title']"]:
        try:
            t = card.find_element(By.CSS_SELECTOR, sel).text.strip()
            if t:
                nome = t
                break
        except Exception:
            continue
    if not nome:
        linhas = [l.strip() for l in card.text.split('\n') if len(l.strip()) > 5]
        nome = linhas[0] if linhas else ""

    preco_float, preco_texto = 0.0, "R$ --"
    try:
        inteiro = card.find_element(
            By.CSS_SELECTOR, ".andes-money-amount__fraction"
        ).text.replace('.', '').strip()
        try:
            centavos = card.find_element(
                By.CSS_SELECTOR, ".andes-money-amount__cents"
            ).text.strip()
        except Exception:
            centavos = "00"
        if inteiro:
            preco_float = float(f"{inteiro}.{centavos}")
            preco_texto = f"R$ {inteiro},{centavos}"
    except Exception:
        m = re.search(r'R\$\s*([\d\.]+,\d{2})', card.text)
        if m:
            try:
                preco_float = float(m.group(1).replace('.', '').replace(',', '.'))
                preco_texto = f"R$ {m.group(1)}"
            except Exception:
                pass

    link = ""
    try:
        link = card.find_element(By.TAG_NAME, "a").get_attribute("href") or ""
    except Exception:
        pass

    imagem = ""
    try:
        img = card.find_element(By.TAG_NAME, "img")
        imagem = img.get_attribute("data-src") or img.get_attribute("src") or ""
    except Exception:
        pass

    return nome, preco_float, preco_texto, link, imagem


def _fallback_por_links(driver):
    produtos = []
    try:
        anchors = driver.find_elements(By.TAG_NAME, "a")
    except Exception:
        return produtos

    vistos = set()
    for a in anchors:
        try:
            href = a.get_attribute("href") or ""
            if not href or not _RE_LINK_PRODUTO.search(href):
                continue
            if href in vistos:
                continue

            container = a
            texto = a.text.strip()
            for _ in range(4):
                if re.search(r'R\$\s*[\d\.]+,\d{2}', texto):
                    break
                try:
                    container = container.find_element(By.XPATH, "..")
                    texto = container.text.strip()
                except Exception:
                    break

            if not re.search(r'R\$\s*[\d\.]+,\d{2}', texto):
                continue

            vistos.add(href)
            nome, preco_float, preco_texto, link, imagem = _extrair_de_card(container)
            if not link:
                link = href
            if nome and preco_float > 0:
                produtos.append({
                    "site": "Mercado Livre",
                    "nome": nome,
                    "preco_texto": preco_texto,
                    "preco": preco_float,
                    "imagem": imagem,
                    "link": link,
                    "specs": []
                })
            if len(produtos) >= 10:
                break
        except Exception:
            continue

    return produtos


def _extrair_produto_pagina_unica(driver):
    try:
        nome = ""
        for sel in ["h1.ui-pdp-title", "h1"]:
            try:
                nome = driver.find_element(By.CSS_SELECTOR, sel).text.strip()
                if nome:
                    break
            except Exception:
                continue
        if not nome:
            return None

        preco_float, preco_texto = 0.0, "R$ --"
        try:
            container = driver.find_element(By.CSS_SELECTOR, ".ui-pdp-price__second-line")
            inteiro = container.find_element(By.CSS_SELECTOR, ".andes-money-amount__fraction").text.replace('.', '').strip()
            try:
                centavos = container.find_element(By.CSS_SELECTOR, ".andes-money-amount__cents").text.strip()
            except Exception:
                centavos = "00"
            if inteiro:
                preco_float = float(f"{inteiro}.{centavos}")
                preco_texto = f"R$ {inteiro},{centavos}"
        except Exception:
            m = re.search(r'R\$\s*([\d\.]+,\d{2})', driver.find_element(By.TAG_NAME, "body").text)
            if m:
                try:
                    preco_float = float(m.group(1).replace('.', '').replace(',', '.'))
                    preco_texto = f"R$ {m.group(1)}"
                except Exception:
                    pass

        imagem = ""
        try:
            img = driver.find_element(By.CSS_SELECTOR, "figure.ui-pdp-gallery__figure img, img.ui-pdp-image")
            imagem = img.get_attribute("src") or img.get_attribute("data-zoom") or ""
        except Exception:
            pass

        if nome and preco_float > 0:
            return {
                "site": "Mercado Livre",
                "nome": nome,
                "preco_texto": preco_texto,
                "preco": preco_float,
                "imagem": imagem,
                "link": driver.current_url,
                "specs": []
            }
    except Exception as e:
        print(f"[Mercado Livre] Erro extraindo produto único: {e}")
    return None


def _buscar_mercadolivre(produto):
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=pt-BR")
    options.add_argument("--disable-notifications")
    # Joga a janela pra fora da área visível da tela, assim ela nunca
    # aparece pro usuário — mas continua sendo um Chrome "normal" (não
    # headless), que é o que evita o bloqueio do Mercado Livre.
    options.add_argument("--window-position=-2400,-2400")

    driver = None
    produtos = []

    try:
        # headless=False: abre janela visível. O ML detecta headless com
        # muito mais facilidade, então rodar com janela real evita o
        # bloqueio quase por completo.
        driver = uc.Chrome(options=options, headless=False, use_subprocess=True, version_main=151)
        driver.set_page_load_timeout(45)

        url = f"https://lista.mercadolivre.com.br/{produto.replace(' ', '-')}"
        print(f"[Mercado Livre] Acessando: {url}")
        driver.get(url)

        # ── Checa bloqueio explícito (tela de verificação) ──
        if "account-verification" in driver.current_url:
            print(f"[Mercado Livre] BLOQUEADO por verificação anti-bot: {driver.current_url}")
            print("[Mercado Livre] Tente novamente mais tarde, ou rode com headless=False.")
            return []

        # ── Checa se caiu direto numa página de produto único ──
        hostname_atual = urlparse(driver.current_url).hostname or ""
        if hostname_atual != "lista.mercadolivre.com.br":
            print(f"[Mercado Livre] Redirecionado para página de produto: {driver.current_url}")
            produto_unico = _extrair_produto_pagina_unica(driver)
            if produto_unico:
                produtos = [produto_unico]
            return produtos

        # Fecha popup de "calculando frete / confirme seu CEP" se aparecer
        try:
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Entendi')]"))
            ).click()
        except Exception:
            pass

        combinado = ", ".join(_SELETORES_CARD)
        try:
            WebDriverWait(driver, 25).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, combinado))
            )
        except Exception:
            print("[Mercado Livre] Nenhum seletor conhecido apareceu em 25s...")

        cards = []
        seletor_usado = None
        for sel in _SELETORES_CARD:
            found = driver.find_elements(By.CSS_SELECTOR, sel)
            if len(found) >= 2:
                cards = found
                seletor_usado = sel
                break

        if cards:
            print(f"[Mercado Livre] {len(cards)} cards via '{seletor_usado}'")
            for card in cards[:10]:
                try:
                    nome, preco_float, preco_texto, link, imagem = _extrair_de_card(card)
                    if not nome or preco_float <= 0:
                        continue
                    produtos.append({
                        "site": "Mercado Livre",
                        "nome": nome,
                        "preco_texto": preco_texto,
                        "preco": preco_float,
                        "imagem": imagem,
                        "link": link,
                        "specs": []
                    })
                except Exception as e:
                    print(f"[Mercado Livre] Erro em card: {e}")
        else:
            print("[Mercado Livre] Nenhum seletor de card bateu — tentando fallback por link de produto...")
            produtos = _fallback_por_links(driver)
            if not produtos:
                titulo = driver.title
                corpo = driver.find_element(By.TAG_NAME, "body").text[:300].replace("\n", " ")
                print(f"[Mercado Livre][DEBUG] title='{titulo}' | url={driver.current_url}")
                print(f"[Mercado Livre][DEBUG] início do corpo: {corpo}")

    except Exception as e:
        print(f"[Mercado Livre] Erro geral: {e}")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    print(f"[Mercado Livre] {len(produtos)} produtos extraídos")
    return produtos