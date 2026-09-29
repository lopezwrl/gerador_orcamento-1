"""
scraping_amazon.py

Duas tentativas, nesta ordem:
  1) Selenium comum em headless (o método original do projeto), com
     timeout maior e user-agent coerente com o Chrome instalado.
  2) Se a 1 não trouxer produtos: undetected-chromedriver com janela
     fora da tela (mesmo método do Mercado Livre), passando antes pela
     home da Amazon e digitando na caixa de pesquisa.

Em qualquer falha, imprime o título da página que a Amazon devolveu e
salva o HTML em instance/debug/ para diagnóstico.
"""
import random
import time
from ..paths import DEBUG_DIR

import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .driver_manager import (
    SELENIUM_SEMAPHORE, UC_START_LOCK,
    obter_driver_path, aplicar_binary_location, aplicar_perfil_temporario,
    versao_principal_chrome,
)

SELETOR_CARD = "div[data-component-type='s-search-result']"


def buscar_amazon(produto):
    with SELENIUM_SEMAPHORE:
        produtos = _buscar_selenium(produto)
        if produtos:
            return produtos
        print("[Amazon] Método padrão sem resultado — tentando com undetected-chromedriver...")
        return _buscar_uc(produto)


# ───────────────────────── utilidades ─────────────────────────

def _pagina_de_erro(driver):
    """A Amazon devolve 'Algo deu errado' quando desconfia de automação."""
    try:
        t = (driver.title or "").lower()
    except Exception:
        return False
    return "algo deu errado" in t or "something went wrong" in t


def _aguardar_resultados(driver, segundos):
    """Espera os cards OU a página de erro. True se há cards."""
    try:
        WebDriverWait(driver, segundos).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, SELETOR_CARD) or _pagina_de_erro(d)
        )
    except Exception:
        pass
    return bool(driver.find_elements(By.CSS_SELECTOR, SELETOR_CARD))


def _diagnosticar(driver, metodo):
    try:
        print(f"[Amazon][DEBUG][{metodo}] URL final: {driver.current_url} | título: {driver.title!r}")
        arquivo_debug = DEBUG_DIR / f"debug_amazon_{metodo}.html"
        with open(arquivo_debug, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"[Amazon] HTML de diagnóstico salvo em {arquivo_debug}")
        if "captcha" in driver.page_source.lower():
            print(f"[Amazon][{metodo}] Bloqueio por CAPTCHA detectado.")
        elif _pagina_de_erro(driver):
            print(f"[Amazon][{metodo}] Amazon devolveu 'Algo deu errado' (bloqueio de automação).")
        else:
            print(f"[Amazon][{metodo}] Produtos não carregaram a tempo.")
    except Exception:
        pass


def _extrair_produtos(driver):
    produtos = []
    cards = driver.find_elements(By.CSS_SELECTOR, SELETOR_CARD)
    print(f"[Amazon] {len(cards)} produtos encontrados")

    for card in cards[:10]:
        try:
            nome = card.find_element(By.CSS_SELECTOR, "h2 span").text

            try:
                inteiro = card.find_element(
                    By.CSS_SELECTOR, ".a-price-whole"
                ).text.replace('.', '').replace(',', '')
                try:
                    centavos = card.find_element(By.CSS_SELECTOR, ".a-price-fraction").text
                except Exception:
                    centavos = "00"
                preco_float = float(f"{inteiro}.{centavos}")
                preco_texto = f"R$ {inteiro},{centavos}"
            except Exception:
                preco_float = 0.0
                preco_texto = "R$ --"

            try:
                href = card.find_element(By.CSS_SELECTOR, "h2 a").get_attribute("href")
                if href.startswith("/"):
                    href = "https://www.amazon.com.br" + href
            except Exception:
                href = "https://www.amazon.com.br"

            try:
                imagem = card.find_element(By.CSS_SELECTOR, "img.s-image").get_attribute("src")
            except Exception:
                imagem = ""

            try:
                avaliacao = card.find_element(By.CSS_SELECTOR, "span.a-icon-alt").text
            except Exception:
                avaliacao = ""

            produtos.append({
                "site": "Amazon",
                "nome": nome,
                "preco_texto": preco_texto,
                "preco": preco_float,
                "imagem": imagem,
                "link": href,
                "specs": [avaliacao] if avaliacao else [],
            })
        except Exception:
            pass
    return produtos


def _fechar(driver):
    if driver:
        try:
            driver.quit()
        except Exception:
            pass


# ───────────────── método 1: Selenium comum (original) ─────────────────

def _buscar_selenium(produto):
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=pt-BR")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # User-agent com a MESMA versão do Chrome instalado (um UA de versão
    # diferente da real, ou "HeadlessChrome", é sinal de robô).
    versao = versao_principal_chrome() or 120
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{versao}.0.0.0 Safari/537.36"
    )

    aplicar_binary_location(options)
    aplicar_perfil_temporario(options)

    driver = None
    try:
        driver = webdriver.Chrome(service=Service(obter_driver_path()), options=options)
        driver.get(f"https://www.amazon.com.br/s?k={produto.replace(' ', '+')}")

        if not _aguardar_resultados(driver, 15):
            _diagnosticar(driver, "selenium")
            return []
        return _extrair_produtos(driver)
    except Exception as e:
        print(f"[Amazon] Erro geral (selenium): {e}")
        return []
    finally:
        _fechar(driver)


# ───────────────── método 2: undetected-chromedriver ─────────────────

def _buscar_uc(produto):
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=pt-BR")
    options.add_argument("--disable-notifications")
    options.add_argument("--window-position=-2400,-2400")

    driver = None
    try:
        with UC_START_LOCK:
            driver = uc.Chrome(
                options=options, headless=False, use_subprocess=True,
                version_main=versao_principal_chrome(),
            )
        driver.set_page_load_timeout(45)

        url = f"https://www.amazon.com.br/s?k={produto.replace(' ', '+')}"

        # Aquecimento: home primeiro (sessão de visitante) e busca pela caixa
        # de pesquisa, como uma pessoa faria.
        driver.get("https://www.amazon.com.br/")
        time.sleep(random.uniform(2.0, 3.5))
        try:
            caixa = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((By.ID, "twotabsearchtextbox"))
            )
            caixa.clear()
            caixa.send_keys(produto)
            time.sleep(random.uniform(0.4, 1.0))
            caixa.send_keys(Keys.ENTER)
        except Exception:
            driver.get(url)

        for tentativa in range(3):
            if _aguardar_resultados(driver, 12):
                return _extrair_produtos(driver)
            if tentativa < 2:
                print(f"[Amazon] uc tentativa {tentativa + 1} sem resultados "
                      f"(título: {driver.title!r}) — tentando de novo...")
                time.sleep(random.uniform(3.0, 5.0))
                driver.get(url)

        _diagnosticar(driver, "uc")
        return []
    except Exception as e:
        print(f"[Amazon] Erro geral (uc): {e}")
        return []
    finally:
        _fechar(driver)