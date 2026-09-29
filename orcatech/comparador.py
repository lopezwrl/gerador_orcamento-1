import json
import os
import time
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED

from .paths import CACHE_DIR
from .scrapers.kabum import buscar_kabum
from .scrapers.mercadolivre import buscar_mercadolivre
from .scrapers.amazon import buscar_amazon
from .scrapers.terabyte import buscar_terabyte
from .scrapers.americanas import buscar_americanas
from .scrapers.ibyte import buscar_ibyte

from .scrapers.gshield import buscar_gshield
from .scrapers.aliexpress import buscar_aliexpress

CACHE_HORAS = 6
TOTAL_LOJAS = 8  # lojas nativas fixas (apenas lojas reais, sem comparadores)

# True  = descarta itens que o filtro considera irrelevantes/acessórios.
# False = TUDO que as lojas encontraram vai para os resultados (só remove duplicados).
FILTRAR_RESULTADOS = False

# Lojas que misturam produtos de todo tipo na busca (acessórios, PCs completos etc.)
# passam SEMPRE por um filtro estrito, mesmo com FILTRAR_RESULTADOS = False.
# As demais lojas continuam exatamente como antes.
LOJAS_FILTRO_ESTRITO = {'Gshield', 'AliExpress'}

# Quantos termos da busca (tipo, processador, GB, modelo) o produto pode deixar
# de citar no título. 0 = severo (todos precisam aparecer). 1 = mais tolerante.
FILTRO_ESTRITO_TOLERANCIA = 0

os.makedirs(CACHE_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════
# NORMALIZAÇÃO
# ═══════════════════════════════════════════════════════════════════

def _norm(texto):
    import unicodedata
    t = texto.lower().strip()
    t = unicodedata.normalize('NFD', t)
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    return t

def _tokens(texto):
    return set(re.findall(r'\b\w+\b', _norm(texto)))

_STOP = {
    'de','do','da','dos','das','para','com','sem','e','ou','em','um',
    'uma','o','a','os','as','no','na','por','pro','the','and','for',
    'with','la','le','global','preto','azul','branco','verde','dourado',
    'prata','roxo','rose','cinza','dual','sim','nfc','oled','lcd','ips',
    'amoled','super','novo','new','original','oficial','lacrado',
    'versao','cor','cores',
}

_PALAVRAS_SPEC = {
    'gb','tb','mb','mhz','mp','hz','w','mah','pol','polegada',
    'ram','rom','cpu','gpu','ghz','nm','ms','fps','nit','px',
}

# ═══════════════════════════════════════════════════════════════════
# SPECS
# ═══════════════════════════════════════════════════════════════════

_SPEC_PATTERNS = [
    (re.compile(r'(\d+)\s*gb\s*ram\b', re.I),                             'Memória RAM',          1),
    (re.compile(r'\bram\s*(\d+)\s*gb\b', re.I),                           'Memória RAM',          1),
    (re.compile(r'(\d+)\s*tb\b(?!\s*ram)', re.I),                         'Armazenamento_TB',     2),
    (re.compile(r'(\d+)\s*gb(?!\s*ram)(?!\s*de\s*ram)(?!\s*gddr)', re.I), 'Armazenamento_GB',     2),
    (re.compile(r'(\d+)\s*mp\b', re.I),                                   'Câmera',               3),
    (re.compile(r'(\d+[.,]?\d*)\s*(?:"|\bpol(?:egadas?)?\b)', re.I),      'Tela',                 4),
    (re.compile(r'(\d+)\s*hz\b', re.I),                                   'Taxa de Atualização',  5),
    (re.compile(r'(\d+)\s*mah\b', re.I),                                  'Bateria',              6),
    (re.compile(r'(\d{3,5})\s*x\s*(\d{3,5})\b'),                          'Resolução',            7),
    (re.compile(r'(\d+(?:[.,]\d+)?)\s*w\b(?!att)', re.I),                 'Potência',             8),
    (re.compile(r'(\d+)\s*mb/s\b', re.I),                                 'Velocidade Leitura',   9),
    (re.compile(r'\b(i[3579])[\s-]?\d{3,5}\w*', re.I),                    'Processador',         10),
    (re.compile(r'\b(ryzen\s*[3579])\b', re.I),                           'Processador',         10),
    (re.compile(r'\b(rtx\s*\d{3,4})\b', re.I),                            'Placa de Vídeo',      11),
    (re.compile(r'\b(gtx\s*\d{3,4})\b', re.I),                            'Placa de Vídeo',      11),
    (re.compile(r'\b(5g|4g|3g)\b', re.I),                                 'Rede',                12),
    (re.compile(r'\b(usb-?c|type-?c)\b', re.I),                           'Conector',            13),
    (re.compile(r'\b(bluetooth\s*[\d.]*)\b', re.I),                       'Conectividade',       14),
    (re.compile(r'\b(nfc)\b', re.I),                                      'NFC',                 15),
]

_UNIDADE_POR_LABEL = {
    'Memória RAM': 'GB', 'Armazenamento_GB': 'GB', 'Armazenamento_TB': 'TB',
    'Câmera': 'MP', 'Tela': '"', 'Taxa de Atualização': 'Hz',
    'Bateria': 'mAh', 'Potência': 'W', 'Velocidade Leitura': 'MB/s',
}

def _extrair_specs(nome, max_specs=6):
    if not nome:
        return []
    achados = []
    labels_vistos = set()
    for pattern, label, prioridade in _SPEC_PATTERNS:
        categoria = 'Armazenamento' if label.startswith('Armazenamento') else label
        if categoria in labels_vistos:
            continue
        m = pattern.search(nome)
        if not m:
            continue
        if label == 'Resolução':
            valor = f"{m.group(1)} x {m.group(2)} px"
        elif label == 'Tela':
            valor = f'{m.group(1).replace(",",".")}\"'
        elif label in ('Processador','Placa de Vídeo','Rede','Conector','Conectividade','NFC'):
            valor = m.group(1).strip().upper() if label in ('Rede','Conector','NFC') else m.group(0).strip()
        else:
            unidade = _UNIDADE_POR_LABEL.get(label, '')
            valor = f"{m.group(1)}{unidade}"
        achados.append((prioridade, categoria, valor))
        labels_vistos.add(categoria)
    achados.sort(key=lambda x: x[0])
    return [f"{label}: {valor}" for _, label, valor in achados[:max_specs]]

# ═══════════════════════════════════════════════════════════════════
# DEDUPLICAÇÃO
# ═══════════════════════════════════════════════════════════════════

# Links "genéricos" que alguns scrapers usam como fallback quando não
# conseguem extrair o link real do produto (home da loja). Não podem
# ser usados como chave de deduplicação, senão produtos DIFERENTES da
# mesma loja (que caíram nesse fallback) seriam descartados por engano.
_LINKS_GENERICOS = {
    "https://www.americanas.com.br",
    "https://www.terabyteshop.com.br",
    "https://www.gshield.com.br",
    "https://www.ibyte.com.br",
    "https://www.kabum.com.br",
    "https://www.amazon.com.br",
}

def _deduplicar(produtos):
    """
    Remove produtos duplicados. Causa raiz observada: algumas lojas
    (ex.: Americanas) às vezes renderizam o MESMO card duas vezes no
    HTML (uma versão com imagem carregada, outra sem, por exemplo),
    e como cada card vira um item na lista, o mesmo produto entra
    repetido no resultado final.

    Chave de deduplicação:
      - Se o produto tem um link de produto real (não é um dos links
        genéricos de home usados como fallback): (loja, link).
      - Caso contrário: (loja, nome normalizado, preço) — cobre os
        casos em que o link não foi capturado.
    """
    vistos = set()
    resultado = []
    duplicados = 0

    for p in produtos:
        site = p.get('site', '')
        link = (p.get('link') or '').strip().lower().rstrip('/')

        if link and link not in _LINKS_GENERICOS:
            chave = (site, link)
        else:
            chave = (site, _norm(p.get('nome', '')), round(p.get('preco', 0), 2))

        if chave in vistos:
            duplicados += 1
            continue

        vistos.add(chave)
        resultado.append(p)

    if duplicados:
        print(f"[Dedup] {duplicados} produto(s) duplicado(s) removido(s)")

    return resultado

# ═══════════════════════════════════════════════════════════════════
# FILTRO
# ═══════════════════════════════════════════════════════════════════

_ACESSORIOS = {
    'pelicula','capa','capinha','case','carcaca','bumper','protetor',
    'skin','adesivo','sticker','grip','holder','pop','socket','anel',
    'suporte','kickstand','cabo','carregador','fonte','adaptador',
    'carregamento','dock','hub','splitter','conector','plug','tomada',
    'auricular','earphone','earbuds','headset','pano','microfibra',
    'limpa','limpeza','spray','bateria','touch','flex','microfone',
    'lente','botao','tampa','traseira','reposicao','modulo','cartao',
    'microsd','sdxc','sdhc','pendrive','toner','tinta','cartucho',
    'refil','extensor','arm','fixacao','book','livro','manual','curso',
    'frontal','compativel','usado',
}

_BUSCA_EH_ACESSORIO = {
    'pelicula','capa','capinha','carregador','cabo','fone','suporte',
    'cartao','memoria','adaptador','bateria','hub','dock','fonte',
    'headset','earphone','earbuds','kit',
}

_INCOMPAT = {
    'redmi':      {'notebook','computador','desktop','monitor','tablet','impressora','processador','placa'},
    'iphone':     {'notebook','computador','desktop','monitor','tablet','impressora','galaxy','redmi','motorola','samsung'},
    'galaxy':     {'notebook','computador','desktop','monitor','tablet','impressora','iphone','redmi','motorola'},
    'motorola':   {'notebook','computador','desktop','monitor','tablet','impressora','iphone','redmi','galaxy'},
    'smartphone': {'notebook','computador','desktop','monitor','impressora'},
    'celular':    {'notebook','computador','desktop','monitor','impressora'},
    'notebook':   {'smartphone','celular','iphone','galaxy','redmi','motorola','desktop'},
    'computador': {'smartphone','celular','iphone','galaxy','redmi','motorola'},
    'desktop':    {'smartphone','celular','iphone','galaxy','redmi','motorola'},
    'rtx':        {'notebook','computador','desktop','monitor'},
    'gtx':        {'notebook','computador','desktop','monitor'},
    'monitor':    {'notebook','computador','smartphone','celular','tablet'},
    'ssd':        {'notebook','computador','desktop'},
    'fone':       {'notebook','computador','monitor','smartphone','celular','tablet'},
}

_RE_SPEC = re.compile(
    r'\b\d+(\.\d+)?\s*(gb|tb|mb|mp|mah|mhz|ghz|hz|w|pol|polegada|nm|ms|fps|nit)\b',
    re.IGNORECASE
)

def _extrair_num_modelo(texto):
    t = _norm(texto)
    t = _RE_SPEC.sub(' ', t)
    t = re.sub(r'\b5g\b|\b4g\b|\b3g\b|\blte\b', ' ', t)
    t = re.sub(r'\d+\.\d+', ' ', t)
    nums = re.findall(r'\b(\d{1,4})\b', t)
    resultado = set()
    for n in nums:
        ni = int(n)
        if 1 <= ni <= 9999 and not (2015 <= ni <= 2030):
            resultado.add(n)
    return resultado

def _modelo_bate(num_busca, nome_produto):
    n = nome_produto.lower()
    n = _RE_SPEC.sub(' ', n)
    n = re.sub(r'\b5g\b|\b4g\b|\b3g\b|\blte\b', ' ', n)
    n = re.sub(r'\d+\.\d+', ' ', n)
    return bool(re.search(r'\b' + re.escape(num_busca) + r'\b', n))

def _filtrar(produto, produtos):
    b_tok = _tokens(produto)
    busca_eh_acessorio = bool(b_tok & _BUSCA_EH_ACESSORIO)
    chaves = [
        t for t in b_tok
        if t not in _STOP and not t.isdigit()
        and len(t) > 1 and t not in _PALAVRAS_SPEC
    ]
    nums_modelo_busca = _extrair_num_modelo(produto)
    incompat = set()
    for cat, bloco in _INCOMPAT.items():
        if cat in b_tok:
            incompat |= bloco

    resultado = []
    c_acess = c_incompat = c_modelo = c_relev = 0

    for p in produtos:
        nome  = p.get('nome', '')
        n_tok = _tokens(nome)

        if not busca_eh_acessorio:
            if n_tok & _ACESSORIOS:
                if not all(c in n_tok for c in chaves):
                    c_acess += 1
                    continue

        if incompat and (n_tok & incompat):
            c_incompat += 1
            continue

        if nums_modelo_busca:
            algum_bate = any(_modelo_bate(nb, nome) for nb in nums_modelo_busca)
            if not algum_bate:
                c_modelo += 1
                continue

        if not chaves:
            resultado.append(p)
            continue

        matches   = sum(1 for c in chaves if c in n_tok)
        threshold = max(1, round(len(chaves) * 0.80))
        if matches >= threshold:
            resultado.append(p)
        else:
            c_relev += 1

    print(
        f"[Filtro] '{produto}': {len(produtos)} -> {len(resultado)} "
        f"| acess:{c_acess} incompat:{c_incompat} modelo:{c_modelo} irrelevante:{c_relev}"
    )
    return resultado

# ═══════════════════════════════════════════════════════════════════
# FILTRO ESTRITO (só para as lojas em LOJAS_FILTRO_ESTRITO)
# ═══════════════════════════════════════════════════════════════════
#
# Regras, na ordem:
#   1. Tipo do produto: se a busca cita notebook/PC/celular/tablet/monitor,
#      o título precisa citar o mesmo tipo (ou sinônimo: notebook = laptop...).
#   2. Acessório: capa, mochila, película, suporte etc. ANTES da palavra do
#      tipo ("Capa Neoflex para Notebook") reprova. "Para/compatível com"
#      antes do tipo também reprova.
#   3. Termos da busca: processador (i7), GB/TB/Hz etc. e número de modelo
#      precisam aparecer no título (aceita "16GB", "16 GB" e "16G").

_NOTEBOOKS   = {'notebook', 'laptop', 'ultrabook', 'chromebook', 'netbook'}
_COMPUTADORES = {'computador', 'pc', 'desktop', 'cpu', 'minipc'}
_CELULARES   = {'celular', 'smartphone', 'telefone', 'iphone', 'galaxy',
                'redmi', 'poco', 'xiaomi', 'motorola', 'realme', 'samsung'}

# palavra digitada na busca -> palavras aceitas no título
_SINONIMOS = {
    'notebook': _NOTEBOOKS, 'laptop': _NOTEBOOKS, 'ultrabook': _NOTEBOOKS,
    'computador': _COMPUTADORES, 'pc': _COMPUTADORES, 'desktop': _COMPUTADORES,
    'celular': _CELULARES, 'smartphone': _CELULARES, 'telefone': _CELULARES,
    'tablet': {'tablet', 'ipad'},
    'monitor': {'monitor'},
    'fone': {'fone', 'headset', 'headphone', 'earbuds', 'earphone', 'auricular'},
}

# tipos "principais": nesses, acessório/peça no lugar do produto é reprovado
_DISPOSITIVOS = {'notebook', 'laptop', 'ultrabook', 'computador', 'pc',
                 'desktop', 'celular', 'smartphone', 'telefone', 'tablet', 'monitor'}

_ACESS_ESTRITO = {
    'capa', 'capinha', 'case', 'cases', 'mochila', 'sleeve', 'bolsa', 'maleta',
    'pasta', 'bag', 'luva', 'pelicula', 'protetor', 'skin', 'adesivo', 'suporte',
    'base', 'cooler', 'carregador', 'fonte', 'cabo', 'adaptador', 'hub', 'dock',
    'mouse', 'mousepad', 'teclado', 'webcam', 'cadeado', 'limpeza', 'organizador',
    'estojo', 'alca',
}
_PECAS_ESTRITO = {
    'bateria', 'memoria', 'hd', 'ssd', 'placa', 'tela', 'display', 'dobradica',
}
_MARCADORES_PARA = {'para', 'pra', 'p', 'for', 'compativel', 'compat', 'pro'}

# PCs de mesa que não podem aparecer numa busca de notebook
_NAO_NOTEBOOK = {'desktop', 'gabinete', 'torre', 'minipc', 'aio'}

_RE_TOKEN_SPEC = re.compile(r'\d+(?:gb|tb|mb|mhz|ghz|hz|mah|mp|pol|w)')
_RE_SPEC_BUSCA = re.compile(r'(\d+)\s*(gb|tb|hz|mah|mp|w)\b')


def _filtrar_estrito(produto, produtos):
    b_norm = _norm(produto)
    b_tok  = _tokens(produto)

    dispositivos = [w for w in b_tok if w in _DISPOSITIVOS]
    palavras_tipo = set()
    for w in dispositivos:
        palavras_tipo |= _SINONIMOS[w]
    if not palavras_tipo:
        # busca por marca/linha de celular ("iphone 13", "galaxy s23"):
        # a própria marca faz o papel de tipo, para reprovar "Capa iPhone 13"
        palavras_tipo = set(b_tok & _CELULARES)
    eh_busca_notebook = bool(palavras_tipo) and palavras_tipo <= _NOTEBOOKS

    # se a própria busca é por acessório/peça, não aplicamos a regra de acessório
    busca_acessorio = bool(b_tok & (_ACESS_ESTRITO | _PECAS_ESTRITO))
    acess_ativos = (_ACESS_ESTRITO | _PECAS_ESTRITO) - b_tok

    chaves = [
        t for t in b_tok
        if t not in _STOP and not t.isdigit() and len(t) > 1
        and t not in _PALAVRAS_SPEC and not _RE_TOKEN_SPEC.fullmatch(t)
    ]
    specs = _RE_SPEC_BUSCA.findall(b_norm)
    nums_modelo = _extrair_num_modelo(produto)

    aprovados = []
    motivos = {'tipo': 0, 'acessorio': 0, 'termos': 0}

    for p in produtos:
        nome = p.get('nome', '')
        nome_norm = _norm(nome)
        n_lista = re.findall(r'\w+', nome_norm)
        n_tok = set(n_lista)

        # 1) tipo do produto + 2) acessório
        if palavras_tipo:
            idx = next((i for i, t in enumerate(n_lista) if t in palavras_tipo), None)
            if idx is None:
                motivos['tipo'] += 1
                continue
            antes = n_lista[:idx]
            if set(antes) & acess_ativos:
                motivos['acessorio'] += 1
                continue
            if not busca_acessorio and (set(antes[-4:]) & _MARCADORES_PARA):
                motivos['acessorio'] += 1
                continue
            if eh_busca_notebook and (
                (n_tok & _NAO_NOTEBOOK) or re.search(r'\bmini\s*pc\b', nome_norm)
            ):
                motivos['tipo'] += 1
                continue

        # 3) termos da busca
        faltando = 0
        for c in chaves:
            ok = (n_tok & _SINONIMOS[c]) if c in _SINONIMOS else (c in n_tok)
            if not ok:
                faltando += 1
        for num, un in specs:
            sufixo = {'gb': r'g(?:b)?', 'tb': r't(?:b)?'}.get(un, un)
            if not re.search(rf'(?<![\d.]){num}\s*{sufixo}\b', nome_norm):
                faltando += 1
        for nb in nums_modelo:
            if not _modelo_bate(nb, nome):
                faltando += 1
        if faltando > FILTRO_ESTRITO_TOLERANCIA:
            motivos['termos'] += 1
            continue

        aprovados.append(p)

    loja = produtos[0].get('site', '?') if produtos else '?'
    print(
        f"[FiltroEstrito] {loja} '{produto}': {len(produtos)} -> {len(aprovados)} "
        f"| tipo:{motivos['tipo']} acessorio:{motivos['acessorio']} termos:{motivos['termos']}"
    )
    return aprovados


def _aplicar_filtro_estrito(produto, produtos):
    """Filtra só as lojas de LOJAS_FILTRO_ESTRITO; as outras passam direto."""
    outros = [p for p in produtos if p.get('site') not in LOJAS_FILTRO_ESTRITO]
    resultado = list(outros)
    for loja in LOJAS_FILTRO_ESTRITO:
        da_loja = [p for p in produtos if p.get('site') == loja]
        if da_loja:
            resultado += _filtrar_estrito(produto, da_loja)
    return resultado

# ═══════════════════════════════════════════════════════════════════
# CLASSIFICAÇÃO
# ═══════════════════════════════════════════════════════════════════

def _classificar(produtos):
    for p in produtos:
        if not p.get('specs'):
            p['specs'] = _extrair_specs(p.get('nome', ''))
    validos = [p for p in produtos if p.get('preco', 0) > 0]
    if not validos:
        for p in produtos:
            p['tipo'] = '⭐ Custo Benefício'
        return produtos
    menor = min(validos, key=lambda x: x['preco'])
    maior = max(validos, key=lambda x: x['preco'])
    for p in produtos:
        if   p['preco'] == menor['preco']: p['tipo'] = '💰 Mais Barato'
        elif p['preco'] == maior['preco']: p['tipo'] = '🔥 Premium'
        else:                              p['tipo'] = '⭐ Custo Benefício'
    return produtos

# ═══════════════════════════════════════════════════════════════════
# PROGRESSO
# ═══════════════════════════════════════════════════════════════════

_job_lock = threading.Lock()

def _iniciar(job, loja):
    if not job:
        return
    try:
        job['lojas'][loja] = {'status': 'running', 'count': 0}
    except Exception:
        pass

def _marcar(job, loja, status, n, total_lojas):
    if not job:
        return
    try:
        with _job_lock:
            job['lojas'][loja] = {'status': status, 'count': n}
            concluidas = sum(
                1 for v in job['lojas'].values()
                if isinstance(v, dict) and v.get('status') in ('done', 'error')
            )
            job['progresso']  = int((concluidas / total_lojas) * 100)
            job['concluidas'] = concluidas
    except Exception as e:
        print(f'[Progresso] {e}')

# ═══════════════════════════════════════════════════════════════════
# CACHE
# ═══════════════════════════════════════════════════════════════════

def _cache_path(produto):
    return os.path.join(CACHE_DIR, _norm(produto).replace(' ', '_') + '.json')

def _cache_valido(produto):
    p = _cache_path(produto)
    return os.path.exists(p) and (time.time() - os.path.getmtime(p)) < CACHE_HORAS * 3600

def _salvar_cache(produto, dados):
    with open(_cache_path(produto), 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

def _ler_cache(produto):
    with open(_cache_path(produto), 'r', encoding='utf-8') as f:
        return json.load(f)

# ═══════════════════════════════════════════════════════════════════
# COMPARAR
# ═══════════════════════════════════════════════════════════════════

def comparar(produto, forcar_busca=False, job=None):
    """
    FLUXO:
      As 10 lojas fixas rodam em paralelo (ThreadPoolExecutor) e o
      resultado é mesclado, filtrado e classificado ao final.
    """
    total_lojas = TOTAL_LOJAS

    if not forcar_busca and _cache_valido(produto):
        print(f"[Cache] '{produto}'")
        dados = _ler_cache(produto)
        dados['do_cache'] = True
        # Cache antigo pode ter sido salvo antes do filtro estrito: reaplica.
        prods = _aplicar_filtro_estrito(produto, dados.get('produtos', []))
        dados['produtos'] = sorted(
            _classificar(prods),
            key=lambda p: (p.get('preco', 0) == 0, p.get('preco', 0))
        )
        if job:
            nomes_lojas = ['mercadolivre','kabum','amazon','terabyte','americanas','ibyte','gshield','aliexpress']
            total = len(nomes_lojas)
            with _job_lock:
                for nome in nomes_lojas:
                    job['lojas'][nome] = {'status': 'done', 'count': 0}
                job['progresso']  = 100
                job['concluidas'] = total
        return dados

    print(f"[Busca] Pesquisando '{produto}'...")
    todos = []

    inicio = time.time()

    lojas_fixas = [
        ('mercadolivre', buscar_mercadolivre),
        ('kabum',        buscar_kabum),
        ('amazon',       buscar_amazon),
        ('terabyte',     buscar_terabyte),
        ('americanas',   buscar_americanas),
        ('ibyte',        buscar_ibyte),
        ('gshield',      buscar_gshield),
        ('aliexpress',   buscar_aliexpress),
    ]

    def _rodar(nome_loja, fn):
        _iniciar(job, nome_loja)
        try:
            print(f"-> {nome_loja} iniciado...")
            t0  = time.time()
            res = fn(produto)
            dt  = time.time() - t0
            print(f"[OK] {nome_loja} concluido em {dt:.1f}s ({len(res)} produtos)")
            _marcar(job, nome_loja, 'done', len(res), total_lojas)
            return res
        except Exception as e:
            print(f"[ERRO] {nome_loja} falhou: {e}")
            _marcar(job, nome_loja, 'error', 0, total_lojas)
            return []

    # ── Lojas fixas, todas em paralelo ─────────────────────────────────────
    with ThreadPoolExecutor(max_workers=max(total_lojas, 1)) as executor:
        futuros = {
            executor.submit(_rodar, nome, fn): nome
            for nome, fn in lojas_fixas
        }
        for futuro in as_completed(futuros):
            try:
                res = futuro.result()
                todos.extend(res)
            except Exception as e:
                print(f"[Busca] Erro em futuro: {e}")

    print(f"[Busca] Todas as lojas concluidas em {time.time() - inicio:.1f}s (paralelo)")

    todos = _deduplicar(todos)
    todos = _aplicar_filtro_estrito(produto, todos)

    filtrados = _filtrar(produto, todos) if FILTRAR_RESULTADOS else list(todos)
    filtrados = _classificar(filtrados)
    filtrados = sorted(
        filtrados,
        key=lambda p: (p.get('preco', 0) == 0, p.get('preco', 0))
    )

    if job:
        try:
            job['produtos_encontrados'] = len(filtrados)
        except Exception:
            pass

    dados = {'produto': produto, 'do_cache': False, 'produtos': filtrados}
    _salvar_cache(produto, dados)
    print(f"[Busca] {len(todos)} brutos -> {len(filtrados)} relevantes.")
    return dados