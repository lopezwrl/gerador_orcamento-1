"""
scraping_ibyte.py — iBytes Teresina
Estratégia: API VTEX pública (catalog_system) → sem Selenium, resposta em ~1s
Fallback: BeautifulSoup no HTML com seletores atualizados
"""

import requests
import re
import json
from bs4 import BeautifulSoup

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.ibyte.com.br/",
})

def _fmt_preco(valor):
    try:
        s = str(valor).strip()
        if isinstance(valor, (int, float)) and valor > 1000 and ',' not in s and '.' not in s:
            v = float(valor) / 100
        else:
            s = re.sub(r'[^\d,.]', '', s)
            if not s:
                return 0.0, "R$ --"
            if ',' in s and '.' in s:
                s = s.replace('.', '').replace(',', '.')
            elif ',' in s:
                s = s.replace(',', '.')
            v = float(s)
        if v <= 0:
            return 0.0, "R$ --"
        txt = f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return v, txt
    except Exception:
        return 0.0, "R$ --"

def _buscar_api_vtex(produto):
    produtos = []
    try:
        url = (
            "https://www.ibyte.com.br/api/catalog_system/pub/products/search/"
            f"?ft={requests.utils.quote(produto)}&_from=0&_to=9"
        )
        print(f"[iBytes API] GET {url}")
        r = _SESSION.get(url, timeout=10)
        print(f"[iBytes API] Status: {r.status_code}")

        # CORREÇÃO: Aceitar status 206 (Partial Content) além do 200
        if r.status_code not in (200, 206):
            return []

        data = r.json()
        print(f"[iBytes API] {len(data)} produtos retornados")

        for item in data:
            try:
                nome = item.get("productName", "") or item.get("name", "")
                if not nome:
                    continue

                link = item.get("link", "") or item.get("url", "")
                if not link:
                    slug = item.get("linkText", "")
                    link = f"https://www.ibyte.com.br/{slug}/p" if slug else "https://www.ibyte.com.br"

                imagem = ""
                imagens = item.get("items", [{}])[0].get("images", [])
                if imagens:
                    imagem = imagens[0].get("imageUrl", "")

                preco_float = 0.0
                preco_texto = "R$ --"
                try:
                    sellers = item.get("items", [{}])[0].get("sellers", [])
                    if sellers:
                        oferta = sellers[0].get("commertialOffer", {})
                        preco_raw = oferta.get("Price", 0) or oferta.get("ListPrice", 0)
                        preco_float, preco_texto = _fmt_preco(preco_raw)
                except Exception:
                    pass

                if preco_float == 0:
                    try:
                        low = item.get("priceRange", {}).get("sellingPrice", {}).get("lowPrice", 0)
                        if low:
                            preco_float, preco_texto = _fmt_preco(low)
                    except Exception:
                        pass

                if nome and preco_float > 0:
                    produtos.append({
                        "site":        "iBytes",
                        "nome":        str(nome)[:120],
                        "preco_texto": preco_texto,
                        "preco":       preco_float,
                        "imagem":      imagem,
                        "link":        link,
                        "specs":       [],
                    })
            except Exception as e:
                print(f"[iBytes API] Erro em item: {e}")
    except Exception as e:
        print(f"[iBytes API] Erro: {e}")

    return produtos

def _buscar_inteligentsearch(produto):
    produtos = []
    try:
        url = (
            "https://www.ibyte.com.br/_v/segment/graphql/v1"
            "?workspace=master&maxAge=short&appsEtag=remove&domain=store&locale=pt-BR"
            "&__bindingId=ibyte-store_ibyte"
        )
        query = """
        {
          productSearch(query: "%s", from: 0, to: 9) {
            products {
              productName
              link
              items { images { imageUrl } sellers { commertialOffer { Price } } }
            }
          }
        }
        """ % produto.replace('"', '\\"')
        r = _SESSION.post(url, json={"query": query}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            items = data.get("data", {}).get("productSearch", {}).get("products", [])
            for item in items:
                nome = item.get("productName", "")
                link = item.get("link", "https://www.ibyte.com.br")
                imagem = ""
                preco_float = 0.0
                preco_texto = "R$ --"
                try:
                    imagem = item["items"][0]["images"][0]["imageUrl"]
                    preco_raw = item["items"][0]["sellers"][0]["commertialOffer"]["Price"]
                    preco_float, preco_texto = _fmt_preco(preco_raw)
                except Exception:
                    pass
                if nome and preco_float > 0:
                    produtos.append({
                        "site": "iBytes", "nome": str(nome)[:120],
                        "preco_texto": preco_texto, "preco": preco_float,
                        "imagem": imagem, "link": link, "specs": [],
                    })
    except Exception as e:
        print(f"[iBytes GraphQL] Erro: {e}")
    return produtos

def _buscar_html_requests(produto):
    produtos = []
    try:
        url = f"https://www.ibyte.com.br/busca?ft={requests.utils.quote(produto)}"
        print(f"[iBytes HTML] GET {url}")
        r = _SESSION.get(url, timeout=12)
        print(f"[iBytes HTML] Status: {r.status_code}")
        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        m = re.search(r'__STATE__\s*=\s*(\{.+?\});\s*</script>', r.text, re.DOTALL)
        if m:
            try:
                state = json.loads(m.group(1))
                for key, val in state.items():
                    if not isinstance(val, dict):
                        continue
                    if "productName" not in val:
                        continue
                    nome = val.get("productName", "")
                    preco_float = 0.0
                    preco_texto = "R$ --"
                    offer_key = key.replace("Product", "CommertialOffer")
                    offer = state.get(offer_key, {})
                    if offer:
                        preco_float, preco_texto = _fmt_preco(offer.get("Price", 0))
                    if preco_float == 0:
                        try:
                            low = val.get("priceRange", {}).get("sellingPrice", {}).get("lowPrice", 0)
                            if low:
                                preco_float, preco_texto = _fmt_preco(low)
                        except Exception:
                            pass
                    slug = val.get("linkText", "")
                    link = f"https://www.ibyte.com.br/{slug}/p" if slug else "https://www.ibyte.com.br"
                    if nome and preco_float > 0:
                        produtos.append({
                            "site": "iBytes", "nome": str(nome)[:120],
                            "preco_texto": preco_texto, "preco": preco_float,
                            "imagem": "", "link": link, "specs": [],
                        })
                if produtos:
                    return produtos
            except Exception as e:
                pass

        seletores = [
            "div.vtex-product-summary-2-x-element",
            "article[class*='productSummary']",
            "div[class*='galleryItem']",
            "div[class*='product-summary']",
            "li.product-item",
            "div.product-item",
            "section[class*='product']",
        ]
        cards = []
        for sel in seletores:
            cards = soup.select(sel)
            if cards:
                break

        for card in cards[:10]:
            try:
                nome = ""
                for sel in [
                    "span[class*='productNameContainer'] span",
                    "span[class*='ProductName']",
                    "span[class*='product-name']",
                    "h2", "h3",
                ]:
                    tag = card.select_one(sel)
                    if tag:
                        nome = tag.get_text(strip=True)
                        if nome and len(nome) > 4:
                            break
                if not nome: continue

                preco_float = 0.0
                preco_texto = "R$ --"
                m2 = re.search(r'R\$\s*([\d\.]+,\d{2})', card.get_text())
                if m2:
                    preco_float, preco_texto = _fmt_preco(m2.group(1))
                if preco_float == 0: continue

                link = "https://www.ibyte.com.br"
                a = card.select_one("a[href]")
                if a:
                    href = a.get("href", "")
                    link = href if href.startswith("http") else "https://www.ibyte.com.br" + href

                imagem = ""
                img = card.select_one("img")
                if img:
                    for attr in ("data-src", "src"):
                        v = img.get(attr, "")
                        if v and not v.startswith("data:"):
                            imagem = v
                            break

                produtos.append({
                    "site": "iBytes", "nome": str(nome)[:120],
                    "preco_texto": preco_texto, "preco": preco_float,
                    "imagem": imagem, "link": link, "specs": [],
                })
            except Exception:
                pass

    except Exception:
        pass

    return produtos

def buscar_ibyte(produto):
    print(f"[iBytes] Buscando: '{produto}'")
    produtos = _buscar_api_vtex(produto)
    if not produtos:
        produtos = _buscar_inteligentsearch(produto)
    if not produtos:
        produtos = _buscar_html_requests(produto)
    print(f"[iBytes] {len(produtos)} produtos extraídos")
    return produtos