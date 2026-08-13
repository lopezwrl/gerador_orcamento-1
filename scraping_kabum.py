import requests
import re
import json

# KaBuM usa Next.js — os produtos ficam embutidos no __NEXT_DATA__ do HTML.
# Esta versão funciona em IP residencial (sua máquina).

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
})


def _fmt_preco(valor):
    try:
        s = re.sub(r'[^\d,.]', '', str(valor).strip())
        if not s:
            return 0.0, "R$ --"
        if ',' in s and '.' in s:
            s = s.replace('.', '').replace(',', '.')
        elif ',' in s:
            s = s.replace(',', '.')
        v = float(s)
        if v <= 0:
            return 0.0, "R$ --"
        txt = f"R$ {v:,.2f}".replace(",","X").replace(".",",").replace("X",".")
        return v, txt
    except Exception:
        return 0.0, "R$ --"


def _buscar_produtos_no_json(obj, depth=0):
    """
    Percorre recursivamente o __NEXT_DATA__ procurando pela lista
    de produtos reais. Reconhece pelos campos típicos de produto KaBuM.
    Ignora listas de categorias (que têm 'count_children', 'slug' sem preço).
    """
    if depth > 10:
        return []

    if isinstance(obj, list) and len(obj) >= 1 and isinstance(obj[0], dict):
        chaves = set(obj[0].keys())
        # Campos que APENAS produtos têm (não categorias)
        campos_produto = {
            "preco_por", "vlr_preco_por", "preco_promocional",
            "preco", "price", "pricePromocional",
            "dsc_nome", "des_nome", "des_path_imagem",
            "img_url", "available_stock", "dsc_disponibilidade",
        }
        if chaves & campos_produto:
            return obj

    if isinstance(obj, dict):
        # Prioriza chaves que provavelmente contêm produtos
        priority = ["catalogue", "products", "items", "data", "result", "catalog"]
        ordered = sorted(obj.keys(), key=lambda k: (0 if k in priority else 1))
        for k in ordered:
            # Pula chaves que claramente são categorias/filtros/meta
            if k in ("categories", "breadcrumb", "filters", "facets", "meta",
                     "links", "seo", "banners", "departments", "menu"):
                continue
            r = _buscar_produtos_no_json(obj[k], depth + 1)
            if r:
                return r

    return []


def buscar_kabum(produto: str):
    produtos = []

    try:
        # Visita a home para pegar cookies (evita bloqueio)
        _SESSION.get("https://www.kabum.com.br/", timeout=8)
    except Exception:
        pass

    try:
        url = f"https://www.kabum.com.br/busca/{produto.replace(' ', '-')}"
        resp = _SESSION.get(url, timeout=15)
        print(f"[KaBuM HTML] Status: {resp.status_code}")

        if resp.status_code != 200:
            print(f"[KaBuM] Bloqueado (status {resp.status_code})")
            return []

        match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            resp.text, re.DOTALL
        )
        if not match:
            print("[KaBuM] __NEXT_DATA__ não encontrado")
            return []

        next_data = json.loads(match.group(1))
        items = _buscar_produtos_no_json(next_data)
        print(f"[KaBuM __NEXT_DATA__] {len(items)} produtos encontrados")

        if items:
            print(f"[KaBuM] Chaves do item[0]: {list(items[0].keys())[:12]}")

        for item in items[:10]:
            if not isinstance(item, dict):
                continue

            # Ignora itens sem preço (são categorias disfarçadas)
            tem_preco = any(item.get(c) for c in (
                "preco_por","vlr_preco_por","preco","price","pricePromocional","preco_promocional"
            ))
            if not tem_preco:
                continue

            nome = (
                item.get("dsc_nome") or item.get("des_nome") or
                item.get("name") or item.get("nome") or
                item.get("title") or item.get("titulo") or
                item.get("product_name") or ""
            ).strip()

            preco_raw = (
                item.get("preco_por") or item.get("vlr_preco_por") or
                item.get("preco_promocional") or item.get("preco") or
                item.get("price") or item.get("pricePromocional") or 0
            )
            preco_float, preco_texto = _fmt_preco(preco_raw)

            codigo = (
                item.get("codigo") or item.get("code") or
                item.get("id") or item.get("product_id") or
                item.get("sku") or ""
            )
            link = (
                f"https://www.kabum.com.br/produto/{codigo}"
                if codigo else "https://www.kabum.com.br"
            )

            imagem = (
                item.get("img_url") or item.get("des_path_imagem") or
                item.get("img") or item.get("image") or
                item.get("imagem") or item.get("thumbnail") or ""
            )
            if imagem and imagem.startswith("/"):
                imagem = "https://www.kabum.com.br" + imagem

            if nome and preco_float > 0:
                produtos.append({
                    "site":        "KaBuM",
                    "nome":        nome[:120],
                    "preco_texto": preco_texto,
                    "preco":       preco_float,
                    "imagem":      imagem,
                    "link":        link,
                    "specs":       [],
                })

    except Exception as e:
        print(f"[KaBuM] Erro: {e}")

    print(f"[KaBuM] {len(produtos)} produtos extraídos")
    return produtos