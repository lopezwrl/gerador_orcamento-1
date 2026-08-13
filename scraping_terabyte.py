from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from driver_manager import obter_driver_path, aplicar_binary_location, aplicar_perfil_temporario, aplicar_flags_economia_memoria, SELENIUM_SEMAPHORE
import time
import re

def buscar_terabyte(produto):
    with SELENIUM_SEMAPHORE:
        return _buscar_terabyte(produto)


def _buscar_terabyte(produto):

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-notifications")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    )
    aplicar_binary_location(options)
    aplicar_perfil_temporario(options)
    aplicar_flags_economia_memoria(options)

    driver = webdriver.Chrome(
        service=Service(obter_driver_path()),
        options=options
    )
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )

    produtos = []

    try:
        url = f"https://www.terabyteshop.com.br/busca?str={produto.replace(' ', '+')}"
        print(f"[Terabyte] Acessando: {url}")
        driver.get(url)

        # CORREÇÃO: Removido o a[href*='/produto/'] que causava os 600 cards inúteis
        seletores_espera = [
            "div.pbox",
            "li.product-item",
            "div[class*='pbox']",
            "div[id*='product']"
        ]

        # ANTES: esperava 15s por CADA seletor, um atrás do outro (até 60s
        # perdidos à toa se nenhum batesse). AGORA: espera todos juntos com
        # um seletor combinado — assim que QUALQUER um deles aparecer, segue
        # em frente. Timeout único de 12s no total.
        cards = []
        combinado = ", ".join(seletores_espera)
        try:
            WebDriverWait(driver, 12).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, combinado))
            )
            for sel in seletores_espera:
                found = driver.find_elements(By.CSS_SELECTOR, sel)
                if found:
                    print(f"[Terabyte] Seletor '{sel}' → {len(found)} cards")
                    cards = found
                    break
        except Exception:
            cards = []

        if not cards:
            print("[Terabyte] Tentando com scroll...")
            for pos in [400, 800, 1400, 2000]:
                driver.execute_script(f"window.scrollTo(0, {pos});")
                time.sleep(1.5)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(3)
            # CORREÇÃO: Força o fallback a buscar divisões de produto, não links genéricos
            cards = driver.find_elements(By.CSS_SELECTOR, "div.pbox, div.product-item")
            print(f"[Terabyte] Fallback containers: {len(cards)}")

        for card in cards[:10]:
            try:
                nome = ""
                for sel in [
                    "span.prod-name", "h2", "h3",
                    "span[class*='name']", "a[class*='name']", "p[class*='name']",
                ]:
                    try:
                        nome = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                        if nome and len(nome) > 3:
                            break
                    except:
                        continue

                if not nome or len(nome) <= 3:
                    nome = card.get_attribute("title") or ""
                if not nome or len(nome) <= 3:
                    linhas = [l.strip() for l in card.text.split('\n') if l.strip() and len(l.strip()) > 5]
                    nome = linhas[0] if linhas else ""

                if not nome or len(nome) <= 3:
                    continue

                preco_float = 0.0
                preco_texto = "R$ --"
                for sel in [
                    "span.prod-new-price", "span.pricepix",
                    "span[class*='price']", "div[class*='price']",
                    "b[class*='price']", "strong[class*='price']",
                ]:
                    try:
                        raw = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                        if raw:
                            m = re.search(r'[\d\.]+,\d{2}', raw)
                            if m:
                                preco_float = float(m.group().replace('.', '').replace(',', '.'))
                                preco_texto = f"R$ {m.group()}"
                                break
                    except:
                        continue

                if preco_float == 0.0:
                    m = re.search(r'R\$\s*([\d\.]+,\d{2})', card.text)
                    if m:
                        try:
                            preco_float = float(m.group(1).replace('.', '').replace(',', '.'))
                            preco_texto = f"R$ {m.group(1)}"
                        except:
                            pass

                link = "https://www.terabyteshop.com.br"
                try:
                    if card.tag_name == "a":
                        link = card.get_attribute("href") or link
                    else:
                        href = card.find_element(By.TAG_NAME, "a").get_attribute("href") or ""
                        if href:
                            link = href if href.startswith("http") else "https://www.terabyteshop.com.br" + href
                except:
                    pass

                imagem = ""
                try:
                    img = card.find_element(By.TAG_NAME, "img")
                    imagem = img.get_attribute("src") or img.get_attribute("data-src") or ""
                except:
                    pass

                if nome and preco_float > 0:
                    produtos.append({
                        "site": "Terabyte",
                        "nome": nome[:120],
                        "preco_texto": preco_texto,
                        "preco": preco_float,
                        "imagem": imagem,
                        "link": link,
                        "specs": []
                    })
            except Exception as e:
                pass

    except Exception as e:
        print(f"[Terabyte] Erro geral: {e}")

    finally:
        driver.quit()

    print(f"[Terabyte] {len(produtos)} produtos extraídos")
    return produtos