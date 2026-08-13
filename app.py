from dotenv import load_dotenv
load_dotenv()  # lê o arquivo .env e injeta as variáveis (ex: CHROME_BINARY_PATH)
               # ANTES de qualquer outro módulo do projeto ser importado

from flask import (
    Flask, render_template, request, send_file, redirect,
    url_for, jsonify, Response
)
from comparador import (
    comparar,
    TOTAL_LOJAS,
)
from gerar_pdf import gerar_pdf
from driver_manager import pre_aquecer
import os
import json
import re
import time
import threading
from datetime import datetime

app = Flask(__name__)

HISTORICO_FILE = "historico.json"

_jobs = {}
_jobs_lock = threading.Lock()


def ler_historico():
    if not os.path.exists(HISTORICO_FILE):
        return []
    with open(HISTORICO_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_historico(produto, produtos):
    historico = ler_historico()
    validos = [p for p in produtos if p.get("preco", 0) > 0]
    if not validos:
        return
    mais_barato = min(validos, key=lambda x: x["preco"])
    premium     = max(validos, key=lambda x: x["preco"])
    economia    = premium["preco"] - mais_barato["preco"]
    historico.append({
        "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "produto": produto,
        "total": len(produtos),
        "mais_barato_nome":  mais_barato["nome"][:50],
        "mais_barato_preco": mais_barato["preco_texto"],
        "mais_barato_site":  mais_barato["site"],
        "premium_nome":  premium["nome"][:50],
        "premium_preco": premium["preco_texto"],
        "premium_site":  premium["site"],
        "economia": f"R$ {economia:,.2f}".replace(',','X').replace('.',',').replace('X','.')
    })
    with open(HISTORICO_FILE, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=2)


def ultima_pesquisa():
    historico = ler_historico()
    return historico[-1] if historico else None


def _parse_valor_brl(texto):
    """Converte 'R$ 7.735,19' -> 7735.19. Usado para reconstruir números
    a partir dos valores já formatados que ficam salvos no historico.json."""
    try:
        s = re.sub(r'[^\d,.]', '', str(texto))
        if not s:
            return 0.0
        if ',' in s and '.' in s:
            s = s.replace('.', '').replace(',', '.')
        elif ',' in s:
            s = s.replace(',', '.')
        return float(s)
    except Exception:
        return 0.0


def _worker(job_id, produto, forcar):
    with _jobs_lock:
        _jobs[job_id]["status"] = "running"
        job_ref = _jobs[job_id]

    try:
        resultado = comparar(
            produto,
            forcar_busca=forcar,
            job=job_ref,
        )
        salvar_historico(produto, resultado["produtos"])
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["resultado"] = resultado

    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["erro"] = str(e)


@app.route('/')
def home():
    ultima    = ultima_pesquisa()
    historico = ler_historico()
    return render_template('index.html', ultima=ultima, historico=historico)


@app.route('/buscar', methods=['POST'])
def buscar():
    produto     = request.form.get('produto', '').strip() or 'tecnologia'
    solicitante = request.form.get('solicitante', '').strip()
    forcar      = request.form.get('forcar_busca') == '1'

    job_id = f"{produto.lower().replace(' ','_')}_{datetime.now().strftime('%H%M%S')}"

    lojas_base = {
        "mercadolivre": {"status": "pending", "count": 0},
        "kabum":        {"status": "pending", "count": 0},
        "amazon":       {"status": "pending", "count": 0},
        "terabyte":     {"status": "pending", "count": 0},
        "americanas":   {"status": "pending", "count": 0},
        "ibyte":        {"status": "pending", "count": 0},
        "gshield":      {"status": "pending", "count": 0},
    }

    _jobs[job_id] = {
        "status": "pending",
        "produto": produto,
        "solicitante": solicitante,
        "resultado": None,
        "progresso": 0,
        "lojas": lojas_base,
        "produtos_encontrados": 0,
    }

    t = threading.Thread(
        target=_worker,
        args=(job_id, produto, forcar),
        daemon=True
    )
    t.start()

    return redirect(url_for('aguardando', job_id=job_id, solicitante=solicitante))


@app.route('/aguardando/<job_id>')
def aguardando(job_id):
    solicitante = request.args.get('solicitante', '')
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return redirect(url_for('home'))
    return render_template('aguardando.html',
                           job_id=job_id,
                           produto=job['produto'],
                           solicitante=solicitante)


@app.route('/status/<job_id>')
def status(job_id):
    """
    Retorna status completo do job incluindo progresso por loja.
    Mantido para compatibilidade — o aguardando.html deve passar a usar
    /stream/<job_id> (Server-Sent Events), mas esse endpoint continua
    funcionando como fallback via polling se precisar.
    """
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"status": "not_found"})

    return jsonify({
        "status": job["status"],
        "progresso": job.get("progresso", 0),
        "lojas": job.get("lojas", {}),
        "produtos_encontrados": job.get("produtos_encontrados", 0)
    })


@app.route('/progresso/<job_id>')
def progresso(job_id):
    """Alias mantido para compatibilidade retroativa."""
    return status(job_id)


@app.route('/stream/<job_id>')
def stream(job_id):
    """
    Server-Sent Events: empurra o status do job para o navegador assim que
    ele muda, em vez do front ficar perguntando (polling) a cada X segundos.
    O cliente consome com `new EventSource('/stream/<job_id>')`.
    """
    def gerar():
        ultimo_estado = None
        tentativas_sem_job = 0

        while True:
            with _jobs_lock:
                job = _jobs.get(job_id)

            if not job:
                tentativas_sem_job += 1
                # Job pode ainda não ter sido registrado por uma fração de
                # segundo (corrida entre o redirect e a thread). Só desiste
                # de fato depois de algumas tentativas.
                if tentativas_sem_job > 5:
                    yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                    break
                time.sleep(0.3)
                continue

            estado = {
                "status": job.get("status", "pending"),
                "progresso": job.get("progresso", 0),
                "lojas": job.get("lojas", {}),
                "produtos_encontrados": job.get("produtos_encontrados", 0),
            }

            if estado != ultimo_estado:
                yield f"data: {json.dumps(estado)}\n\n"
                ultimo_estado = estado

            if estado["status"] in ("done", "error"):
                break

            time.sleep(0.6)

    resp = Response(gerar(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"  # evita buffer se houver nginx na frente
    resp.headers["Connection"] = "keep-alive"
    return resp


@app.route('/resultado/<job_id>')
def resultado(job_id):
    solicitante = request.args.get('solicitante', '')
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job or job["status"] != "done":
        return redirect(url_for('aguardando', job_id=job_id, solicitante=solicitante))
    res = job["resultado"]
    return render_template('resultados.html',
                           produto=res['produto'],
                           solicitante=solicitante,
                           produtos=res['produtos'],
                           do_cache=res['do_cache'])


@app.route('/orcamentos')
def orcamentos():
    historico = ler_historico()
    with _jobs_lock:
        jobs_ativos = {jid: j for jid, j in _jobs.items()
                       if j["status"] in ("pending", "running")}
    return render_template('orcamentos.html', historico=historico, jobs_ativos=jobs_ativos)


@app.route('/relatorios')
def relatorios():
    historico = ler_historico()
    return render_template('relatorios.html', historico=historico, total_lojas=TOTAL_LOJAS)


@app.route('/api/relatorios_dados')
def relatorios_dados():
    """
    Dados agregados do historico.json prontos para alimentar gráficos
    (Chart.js ou similar) na página de relatórios: economia acumulada,
    lojas mais baratas e produtos mais pesquisados.
    """
    historico = ler_historico()
    if not historico:
        return jsonify({"vazio": True})

    economias = [_parse_valor_brl(h.get("economia", "0")) for h in historico]

    economia_acumulada = []
    soma = 0.0
    for e in economias:
        soma += e
        economia_acumulada.append(round(soma, 2))

    contagem_lojas = {}
    for h in historico:
        loja = h.get("mais_barato_site") or "—"
        contagem_lojas[loja] = contagem_lojas.get(loja, 0) + 1

    contagem_produtos = {}
    for h in historico:
        p = (h.get("produto") or "—").strip().lower()
        contagem_produtos[p] = contagem_produtos.get(p, 0) + 1
    top_produtos = sorted(contagem_produtos.items(), key=lambda kv: -kv[1])[:8]

    return jsonify({
        "vazio": False,
        "total_buscas":   len(historico),
        "economia_total": round(sum(economias), 2),
        "economia_media": round(sum(economias) / len(economias), 2) if economias else 0,
        "labels":             [h.get("produto", "—")[:24] for h in historico],
        "datas":              [h.get("data", "") for h in historico],
        "economias":          economias,
        "economia_acumulada": economia_acumulada,
        "lojas_mais_baratas": contagem_lojas,
        "top_produtos": [{"produto": p, "vezes": v} for p, v in top_produtos],
    })


@app.route('/rever/<int:indice>')
def rever(indice):
    historico = ler_historico()
    if indice < 0 or indice >= len(historico):
        return redirect(url_for('orcamentos'))
    item    = historico[indice]
    produto = item['produto']
    resultado = comparar(produto, forcar_busca=False)
    return render_template('resultados.html',
                           produto=produto,
                           solicitante='',
                           produtos=resultado['produtos'],
                           do_cache=resultado['do_cache'])


@app.route('/gerar_pdf', methods=['POST'])
def baixar_pdf():
    produto     = request.form.get('produto', 'produto')
    solicitante = request.form.get('solicitante', '')
    resultado   = comparar(produto)
    caminho_pdf = gerar_pdf(produto, resultado['produtos'], solicitante)
    return send_file(caminho_pdf, as_attachment=True,
                     download_name=os.path.basename(caminho_pdf),
                     mimetype='application/pdf')


@app.route('/gerar_pdf_historico/<int:indice>', methods=['POST'])
def gerar_pdf_historico(indice):
    historico = ler_historico()
    if indice < 0 or indice >= len(historico):
        return redirect(url_for('orcamentos'))
    item        = historico[indice]
    produto     = item['produto']
    solicitante = request.form.get('solicitante', '')
    resultado   = comparar(produto, forcar_busca=False)
    caminho_pdf = gerar_pdf(produto, resultado['produtos'], solicitante)
    return send_file(caminho_pdf, as_attachment=True,
                     download_name=os.path.basename(caminho_pdf),
                     mimetype='application/pdf')


# ─────────────────────────────────────────────────────────────────────────────
# PATCH para app.py — substitua APENAS o bloco do if __name__ == '__main__'
#
# PROBLEMA: pre_aquecer() abre uma janela Chrome VISÍVEL porque o driver_manager
# provavelmente cria um driver sem as flags headless para testar a conexão.
# Isso causa a "aba preta" que você vê ao iniciar o servidor.
#
# SOLUÇÃO: não chamar pre_aquecer() ao iniciar — o ChromeDriver já é
# baixado automaticamente pelo webdriver-manager na primeira busca real.
# Se quiser manter o pré-aquecimento, ele deve rodar headless e só baixar
# o binário (sem abrir janela). Veja comentário abaixo.
# ─────────────────────────────────────────────────────────────────────────────

# SUBSTITUA o bloco final do app.py por este:

if __name__ == '__main__':
    print("✓ OrçaTech iniciado")

    # NÃO chame pre_aquecer() aqui.
    # O webdriver-manager baixa o ChromeDriver automaticamente na primeira
    # busca que usar Selenium. Chamar pre_aquecer() abre uma janela Chrome
    # visível na área de trabalho antes mesmo de qualquer busca.
    #
    # Se quiser garantir que o driver está baixado sem abrir janela, faça:
    #
    #   from driver_manager import obter_driver_path
    #   try:
    #       obter_driver_path()   # só resolve o binário, não abre o Chrome
    #       print("✓ ChromeDriver pronto")
    #   except Exception as e:
    #       print(f"⚠ ChromeDriver: {e}")

    app.run(debug=True, use_reloader=False, threaded=True)