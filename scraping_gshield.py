"""
scraping_gshield.py — Gshield (loja VTEX)
"""

import re
import requests
from bs4 import BeautifulSoup

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://www.gshield.com.br/",
})


def _fmt_preco(valor):
    try:
        s = str(valor).strip()
        s = re.sub(r"[^\d,.]", "", s)
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


def buscar_gshield(produto):
    print(f"[Gshield] Buscando: '{produto}'")
    produtos = []
    try:
        url = f"https://www.gshield.com.br/busca/{produto.replace(' ', '+')}"
        print(f"[Gshield] GET {url}")
        r = _SESSION.get(url, timeout=12)
        print(f"[Gshield] Status: {r.status_code}")
        if r.status_code != 200 or not r.text:
            return []

        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select(".listagem-item")
        print(f"[Gshield] {len(cards)} cards .listagem-item")

        for card in cards[:15]:
            try:
                nome_tag = card.select_one(".nome-produto")
                if not nome_tag:
                    continue
                nome = nome_tag.get_text(strip=True)
                if not nome or len(nome) < 4:
                    continue

                preco_float, preco_texto = 0.0, "R$ --"
                preco_tag = card.select_one(".preco-venda")
                if preco_tag:
                    m = re.search(r"R\$\s*([\d.,]+)", preco_tag.get_text())
                    if m:
                        preco_float, preco_texto = _fmt_preco(m.group(1))
                if preco_float <= 0:
                    continue

                link = "https://www.gshield.com.br"
                a = card.select_one("a[href]")
                if a and a.get("href"):
                    href = a.get("href")
                    link = href if href.startswith("http") else "https://www.gshield.com.br" + href

                imagem = ""
                img = card.select_one("img")
                if img:
                    for attr in ("data-src", "data-lazy", "data-original", "src"):
                        v = img.get(attr, "")
                        if v and not v.startswith("data:"):
                            imagem = v if v.startswith("http") else "https:" + v if v.startswith("//") else v
                            break

                produtos.append({
                    "site":        "Gshield",
                    "nome":        nome[:200],
                    "preco_texto": preco_texto,
                    "preco":       preco_float,
                    "imagem":      imagem,
                    "link":        link,
                    "specs":       [],
                })
            except Exception:
                continue

    except Exception as e:
        print(f"[Gshield] Erro: {e}")

    print(f"[Gshield] {len(produtos)} produtos extraídos")
    return produtos