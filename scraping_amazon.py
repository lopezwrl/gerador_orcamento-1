from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from driver_manager import obter_driver_path, aplicar_binary_location, aplicar_perfil_temporario
import time
import random

def buscar_amazon(produto):

    options = Options()
    # CORREÇÃO: Utilizando a nova implementação headless, menos detectável
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    
    # Randomiza o navegador base sutilmente
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ]
    options.add_argument(f"user-agent={random.choice(user_agents)}")
    
    aplicar_binary_location(options)
    aplicar_perfil_temporario(options)

    driver = webdriver.Chrome(
        service=Service(obter_driver_path()),
        options=options
    )
    
    # Evasão básica
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    produtos = []

    try:
        query = produto.replace(' ', '+')
        url = f"https://www.amazon.com.br/s?k={query}"
        driver.get(url)
        
        # CORREÇÃO: Espera explícita para garantir que a página carregou ou verificar CAPTCHA
        try:
            WebDriverWait(driver, 6).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-component-type='s-search-result']"))
            )
        except:
            if "captcha" in driver.page_source.lower():
                print("[Amazon] Bloqueio por CAPTCHA detectado.")
            else:
                print("[Amazon] Produtos não carregaram a tempo.")
            return []

        cards = driver.find_elements(
            By.CSS_SELECTOR,
            "div[data-component-type='s-search-result']"
        )

        print(f"[Amazon] {len(cards)} produtos encontrados")

        for card in cards[:10]:
            try:
                nome = card.find_element(By.CSS_SELECTOR, "h2 span").text

                try:
                    inteiro = card.find_element(
                        By.CSS_SELECTOR, ".a-price-whole"
                    ).text.replace('.', '').replace(',', '')
                    try:
                        centavos = card.find_element(
                            By.CSS_SELECTOR, ".a-price-fraction"
                        ).text
                    except:
                        centavos = "00"
                    preco_float = float(f"{inteiro}.{centavos}")
                    preco_texto = f"R$ {inteiro},{centavos}"
                except:
                    preco_float = 0.0
                    preco_texto = "R$ --"

                try:
                    link_elem = card.find_element(By.CSS_SELECTOR, "h2 a")
                    href = link_elem.get_attribute("href")
                    if href.startswith("/"):
                        href = "https://www.amazon.com.br" + href
                except:
                    href = "https://www.amazon.com.br"

                try:
                    imagem = card.find_element(
                        By.CSS_SELECTOR, "img.s-image"
                    ).get_attribute("src")
                except:
                    imagem = ""

                try:
                    avaliacao = card.find_element(
                        By.CSS_SELECTOR, "span.a-icon-alt"
                    ).text
                except:
                    avaliacao = ""

                produtos.append({
                    "site": "Amazon",
                    "nome": nome,
                    "preco_texto": preco_texto,
                    "preco": preco_float,
                    "imagem": imagem,
                    "link": href,
                    "specs": [avaliacao] if avaliacao else []
                })

            except Exception as e:
                pass

    except Exception as e:
        print(f"[Amazon] Erro geral: {e}")

    finally:
        driver.quit()

    return produtos