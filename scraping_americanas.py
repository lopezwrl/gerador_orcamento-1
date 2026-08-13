"""
scraping_americanas.py
Estratégia dupla:
  1. Selenium: scroll lento para ativar lazy-load das imagens
  2. __NEXT_DATA__ / JSON embutido como fallback de link+imagem
"""
import re
import json
import time


def _fmt(valor):
    try:
        s = re.sub(r'[^\d,.]', '', str(valor).strip())
        if not s: return 0.0, "R$ --"
        if ',' in s and '.' in s:
            s = s.replace('.', '').replace(',', '.')
        elif ',' in s:
            s = s.replace(',', '.')
        v = float(s)
        if v <= 0: return 0.0, "R$ --"
        return v, f"R$ {v:,.2f}".replace(",","X").replace(".",",").replace("X",".")
    except Exception:
        return 0.0, "R$ --"


def _link_valido(href):
    """Retorna True se o href parece ser uma página de produto."""
    if not href or href.startswith("javascript") or href == "#":
        return False
    bad = ("/busca", "/conta", "/ajuda", "/carrinho", "/login",
           "/checkout", "/wishlist", "/categoria", "americanas.com.br/busca")
    return not any(b in href.lower() for b in bad)


def _melhor_img(driver, img_el):
    """Tenta todas as formas de extrair a URL real da imagem."""
    from selenium.webdriver.common.by import By
    attrs = ("src", "data-src", "data-lazy-src", "data-original",
             "data-zoom-image", "data-img", "srcset")
    for attr in attrs:
        val = img_el.get_attribute(attr) or ""
        if val and not val.startswith("data:") and "placeholder" not in val.lower():
            # srcset: pega a primeira URL
            if attr == "srcset":
                val = val.strip().split(",")[0].strip().split(" ")[0]
            if val and not val.startswith("data:"):
                return val.strip()
    # currentSrc via JS — funciona após lazy-load
    try:
        cs = driver.execute_script(
            "return arguments[0].currentSrc || arguments[0].src || '';", img_el
        ) or ""
        if cs and not cs.startswith("data:") and len(cs) > 20:
            return cs.strip()
    except Exception:
        pass
    return ""


def buscar_americanas(produto):
    from driver_manager import SELENIUM_SEMAPHORE
    with SELENIUM_SEMAPHORE:
        return _buscar_americanas(produto)


def _buscar_americanas(produto):
    print(f"[Americanas] Buscando: '{produto}'")

    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from driver_manager import obter_driver_path, aplicar_binary_location, aplicar_perfil_temporario, aplicar_flags_economia_memoria

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        # NÃO bloqueamos imagens — precisamos delas
        options.add_experimental_option("excludeSwitches", ["enable-automation","enable-logging"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        # Garante imagens habilitadas
        prefs = {"profile.managed_default_content_settings.images": 1}
        options.add_experimental_option("prefs", prefs)
        aplicar_binary_location(options)
        aplicar_perfil_temporario(options)
        aplicar_flags_economia_memoria(options)

        driver = webdriver.Chrome(
            service=Service(obter_driver_path()), options=options
        )
        driver.set_page_load_timeout(35)
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        produtos = []

        try:
            url = f"https://www.americanas.com.br/busca/{produto.replace(' ','%20')}"
            print(f"[Americanas] {url}")
            driver.get(url)

            # ── Aguarda cards ──
            SELS = [
                "div[data-testid='product-card']",
                "div[class*='ProductCard']",
                "div[class*='product-card']",
                "li[class*='product']",
                "article[class*='product']",
            ]
            cards = []
            for sel in SELS:
                try:
                    WebDriverWait(driver, 12).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                    )
                    found = driver.find_elements(By.CSS_SELECTOR, sel)
                    if len(found) >= 2:
                        print(f"[Americanas] {len(found)} cards via '{sel}'")
                        cards = found
                        break
                except Exception:
                    continue

            if not cards:
                print("[Americanas] Nenhum card DOM → tentando __NEXT_DATA__")
                return _fallback_next_data(driver)

            # ── SCROLL LENTO para disparar lazy-load de imagens ──
            altura = driver.execute_script("return document.body.scrollHeight") or 3000
            passo  = max(150, altura // 20)
            pos    = 0
            while pos < altura:
                driver.execute_script(f"window.scrollTo(0, {pos});")
                time.sleep(0.25)
                pos += passo
            # Volta ao topo e aguarda browser renderizar imagens
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(2.0)

            # Recarrega referências após scroll
            for sel in SELS:
                found = driver.find_elements(By.CSS_SELECTOR, sel)
                if len(found) >= 2:
                    cards = found
                    break

            # ── Extração ──
            for card in cards[:10]:
                try:
                    texto = card.text.strip()
                    if not texto:
                        continue

                    # Nome
                    nome = ""
                    for sel_n in ["h2","h3","[class*='Title']","[class*='title']",
                                  "[class*='Name']","[class*='name']"]:
                        try:
                            el = card.find_element(By.CSS_SELECTOR, sel_n)
                            t = el.text.strip()
                            if t and len(t) > 5:
                                nome = t; break
                        except Exception:
                            continue
                    if not nome:
                        linhas = [l.strip() for l in texto.split('\n')
                                  if len(l.strip()) > 5
                                  and not re.match(r'^R\$', l.strip())]
                        nome = linhas[0] if linhas else ""
                    if not nome or len(nome) <= 4:
                        continue

                    # Preço — pega o MENOR valor (com desconto)
                    precos_raw = re.findall(r'R\$\s*([\d\.]+,\d{2})', texto)
                    preco_float, preco_texto = 0.0, "R$ --"
                    if precos_raw:
                        candidatos = []
                        for pr in precos_raw:
                            v, t = _fmt(pr)
                            if v > 0:
                                candidatos.append((v, t))
                        if candidatos:
                            preco_float, preco_texto = min(candidatos, key=lambda x: x[0])
                    if preco_float == 0:
                        continue

                    # ── Link ──
                    link = ""
                    try:
                        anchors = card.find_elements(By.TAG_NAME, "a")
                        for a in anchors:
                            href = a.get_attribute("href") or ""
                            if _link_valido(href):
                                link = href; break
                        # Fallback: qualquer anchor não-genérico
                        if not link and anchors:
                            for a in anchors:
                                href = a.get_attribute("href") or ""
                                if href and not any(b in href.lower()
                                                    for b in ("javascript","#","conta","ajuda")):
                                    link = href; break
                    except Exception:
                        pass
                    if not link:
                        link = "https://www.americanas.com.br"
                    elif not link.startswith("http"):
                        link = "https://www.americanas.com.br" + link

                    # ── Imagem ──
                    imagem = ""
                    try:
                        imgs = card.find_elements(By.TAG_NAME, "img")
                        for img in imgs:
                            alt = (img.get_attribute("alt") or "").lower()
                            # Pula ícones de UI
                            if any(x in alt for x in ("carrinho","cesta","logo",
                                                        "icon","arrow","seta","adicionar")):
                                continue
                            url_img = _melhor_img(driver, img)
                            if url_img and len(url_img) > 20:
                                # Prefere imagens de produto (costumam ter "image" ou "produto" na URL)
                                imagem = url_img
                                break
                    except Exception:
                        pass

                    produtos.append({
                        "site": "Americanas", "nome": nome[:120],
                        "preco_texto": preco_texto, "preco": preco_float,
                        "imagem": imagem, "link": link, "specs": [],
                    })
                    status_img = "✓ foto" if imagem else "✗ sem foto"
                    print(f"[Americanas] {status_img} | {nome[:40]} | {preco_texto}")

                except Exception as e:
                    print(f"[Americanas] card erro: {e}")

            # Se não veio nenhuma imagem, tenta fallback via __NEXT_DATA__
            sem_foto = [p for p in produtos if not p.get("imagem")]
            if sem_foto:
                print(f"[Americanas] {len(sem_foto)} sem foto → tentando __NEXT_DATA__ para imagens")
                extra = _fallback_next_data(driver)
                # Enriquecer com imagem pelo nome
                mapa = {p["nome"][:60].lower(): p.get("imagem","") for p in extra}
                for p in produtos:
                    if not p["imagem"]:
                        for chave, img in mapa.items():
                            # Match parcial por palavras
                            palavras_p = set(p["nome"].lower().split())
                            palavras_c = set(chave.split())
                            if len(palavras_p & palavras_c) >= 2 and img:
                                p["imagem"] = img
                                break

        finally:
            driver.quit()

        com_foto = sum(1 for p in produtos if p.get("imagem"))
        print(f"[Americanas] {len(produtos)} produtos | {com_foto} com foto")
        return produtos

    except Exception as e:
        print(f"[Americanas] Erro geral: {e}")
        return []


def _fallback_next_data(driver):
    """Extrai produtos do __NEXT_DATA__ embutido na página."""
    produtos = []
    try:
        html = driver.page_source
        m = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
        )
        if not m:
            return []
        data = json.loads(m.group(1))
        items = _buscar_na_arvore(data)
        for item in items[:10]:
            try:
                nome = item.get("name","") or item.get("title","")
                if not nome: continue
                preco_raw = (item.get("price",0) or item.get("salePrice",0)
                             or item.get("offers",{}).get("primaryOffer",{}).get("price",0))
                pf, pt = _fmt(preco_raw)
                if pf == 0: continue
                # Imagem
                imagem = ""
                for campo in ("image","thumbnail","img"):
                    raw = item.get(campo,"")
                    if isinstance(raw, list): raw = raw[0] if raw else ""
                    if isinstance(raw, dict): raw = raw.get("url","") or raw.get("src","")
                    if raw and not str(raw).startswith("data:"):
                        imagem = str(raw); break
                if not imagem:
                    try:
                        imgs = item.get("images",[])
                        if imgs:
                            first = imgs[0]
                            imagem = (first.get("url","") or first.get("src","")) if isinstance(first,dict) else str(first)
                    except Exception: pass
                if imagem and imagem.startswith("//"): imagem = "https:" + imagem
                link = item.get("url","") or item.get("link","")
                if link and not link.startswith("http"):
                    link = "https://www.americanas.com.br" + link
                produtos.append({
                    "site":"Americanas","nome":str(nome)[:120],
                    "preco_texto":pt,"preco":pf,
                    "imagem":imagem,"link":link or "https://www.americanas.com.br",
                    "specs":[],
                })
            except Exception:
                continue
    except Exception as e:
        print(f"[Americanas __NEXT_DATA__] {e}")
    return produtos


def _buscar_na_arvore(obj, depth=0):
    if depth > 12: return []
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        if set(obj[0].keys()) & {"name","price","salePrice","image","url","offers"}:
            return obj
    if isinstance(obj, dict):
        for key in ("products","items","data","result","search","catalog"):
            if key in obj:
                r = _buscar_na_arvore(obj[key], depth+1)
                if r: return r
        for key, val in obj.items():
            if key in ("meta","seo","links","breadcrumb","filters","facets"):
                continue
            if isinstance(val, (dict,list)):
                r = _buscar_na_arvore(val, depth+1)
                if r: return r
    return []