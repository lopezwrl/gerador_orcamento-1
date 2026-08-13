"""
driver_manager.py
Usa o chromedriver.exe local da pasta do projeto.
Sem download automático desnecessário.

CORREÇÃO DESTA VERSÃO:
  - Removido _service_cache: um objeto Service não pode ser reutilizado
    entre chamadas — depois de encerrado (driver.quit()), ele fica em
    estado inválido e a próxima thread que tentar usá-lo abre uma janela
    Chrome órfã ou trava silenciosamente. Cada _driver() no scraper
    deve criar seu próprio Service via obter_driver_path().
  - pre_aquecer() mantido: só resolve o caminho do binário, não abre
    nenhuma janela Chrome — seguro chamar no __main__ do app.py.
"""

import os
import tempfile
import threading
from pathlib import Path

_PASTA_PROJETO      = Path(__file__).parent
_CHROMEDRIVER_LOCAL = _PASTA_PROJETO / "chromedriver.exe"

_path_cache  = None
_binary_cache = None
_lock        = threading.Lock()

# ─────────────────────────────────────────────────────────────────────────
# LIMITADOR DE CONCORRÊNCIA DO SELENIUM
#
# Problema observado: quando várias lojas baseadas em Selenium (Mercado
# Livre, Amazon, Terabyte, Americanas) sobem ao mesmo tempo via
# ThreadPoolExecutor, os processos chromedriver.exe tentam iniciar no
# MESMO instante. Isso já causou dois sintomas diferentes:
#   1) "unexpectedly exited. Status code was: 3221225773" (0xC0000005)
#   2) "DevToolsActivePort file doesn't exist" + WinError 1455
#      ("O arquivo de paginação é muito pequeno") — este último é um
#      erro do PRÓPRIO WINDOWS: a memória virtual da máquina não aguenta
#      abrir vários processos Chrome completos ao mesmo tempo.
#
# Solução: um semáforo global que permite só 1 navegador Selenium aberto
# por vez. As lojas via requests (Buscapé, Zoom, Bondfaro, iBytes,
# Gshield, KaBuM) não usam Selenium e continuam 100% em paralelo, sem
# qualquer limitação — só as 4 que abrem navegador ficam em fila.
#
# Isso deixa a busca alguns segundos mais lenta, mas evita o crash.
# Se AINDA travar mesmo com 1 por vez, o problema é o arquivo de
# paginação do Windows estar pequeno demais (ver README/orientação
# passada junto com este arquivo).
# ─────────────────────────────────────────────────────────────────────────
SELENIUM_SEMAPHORE = threading.Semaphore(2)


def aplicar_flags_economia_memoria(options):
    """
    Reduz o consumo de RAM/processos de cada instância do Chrome, sem
    comprometer o carregamento de páginas pesadas em JavaScript
    (Mercado Livre, Amazon). Flags mais agressivas como
    --renderer-process-limit=1 e --disable-features=site-per-process
    foram removidas: elas deixavam essas páginas lentas/incompletas
    (causando "0 cards encontrados" e timeout na Amazon).
    """
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-sync")
    options.add_argument("--metrics-recording-only")
    options.add_argument("--mute-audio")
    return options

# Caminhos onde o Chrome costuma ser instalado no Windows.
# Cobre instalação padrão (admin), 32 bits e instalação por usuário
# (comum quando o Chrome foi instalado sem privilégios de administrador).
_CAMINHOS_CHROME_WINDOWS = [
    os.environ.get("CHROME_BINARY_PATH", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
]


def localizar_chrome_binary() -> str:
    """
    Tenta localizar o executável do Chrome (chrome.exe) instalado na
    máquina. Retorna "" se não encontrar — nesse caso o Selenium usa o
    comportamento padrão dele, que já é suficiente no Linux/Mac.

    Isso resolve o erro 'cannot find Chrome binary' que ocorre no
    Windows quando o Chrome não está em um dos caminhos que o Selenium
    procura automaticamente (ex: instalado só para o usuário atual).

    Pode ser sobrescrito definindo a variável de ambiente
    CHROME_BINARY_PATH com o caminho completo do chrome.exe.
    """
    global _binary_cache
    if _binary_cache is not None:
        return _binary_cache

    with _lock:
        if _binary_cache is not None:
            return _binary_cache
        for caminho in _CAMINHOS_CHROME_WINDOWS:
            if caminho and Path(caminho).exists():
                print(f"[Driver] Chrome encontrado em: {caminho}")
                _binary_cache = caminho
                return _binary_cache
        print(
            "[Driver] ⚠️  Chrome não encontrado nos caminhos padrão. "
            "Se o erro 'cannot find Chrome binary' aparecer, defina a "
            "variável de ambiente CHROME_BINARY_PATH com o caminho do "
            "chrome.exe (ex: no .env: CHROME_BINARY_PATH=C:\\...\\chrome.exe)."
        )
        _binary_cache = ""
        return _binary_cache


def aplicar_binary_location(options):
    """
    Define options.binary_location se conseguirmos localizar o Chrome.
    Chamar isso logo após criar as Options() em cada scraper, antes de
    criar o webdriver.Chrome(...).
    """
    caminho = localizar_chrome_binary()
    if caminho:
        options.binary_location = caminho
    return options


def aplicar_perfil_temporario(options):
    """
    Define um --user-data-dir novo e isolado (pasta temporária) para
    cada sessão do navegador.

    Sem isso, o Chrome/Brave tenta usar o perfil padrão do usuário. Se
    já existir outra instância do navegador aberta (ou um lock antigo
    sobrando de uma execução anterior que travou), o navegador some
    silenciosamente antes do ChromeDriver conseguir se conectar —
    é exatamente o erro "DevToolsActivePort file doesn't exist".

    Cada chamada gera uma pasta nova em %TEMP%, então múltiplas buscas
    em paralelo (threads) nunca disputam o mesmo perfil, e o usuário
    pode deixar o navegador normal aberto sem conflito.

    Também adiciona --remote-allow-origins=*: a partir do Chrome/Chromium
    111 essa flag passou a ser obrigatória para o ChromeDriver conseguir
    se conectar ao DevTools do navegador. Sem ela, o navegador abre e
    fecha sozinho quase instantaneamente — outra causa comum do mesmo
    erro "DevToolsActivePort file doesn't exist".
    """
    pasta = tempfile.mkdtemp(prefix="orcatech_chrome_")
    options.add_argument(f"--user-data-dir={pasta}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--remote-allow-origins=*")
    return options


def _resolver_caminho() -> str:
    if _CHROMEDRIVER_LOCAL.exists():
        print(f"[Driver] chromedriver.exe local: {_CHROMEDRIVER_LOCAL}")
        return str(_CHROMEDRIVER_LOCAL)

    print("[Driver] chromedriver.exe não encontrado — baixando versão compatível...")
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        caminho = ChromeDriverManager().install()
        print(f"[Driver] Baixado: {caminho}")
        return caminho
    except Exception as e:
        print(f"[Driver] Falha no download: {e}")
        return ""


def obter_driver_path() -> str:
    """
    Retorna o caminho (str) do chromedriver.exe.
    Thread-safe: resolve uma vez e cacheia só o PATH (não o Service).
    Cada scraper cria seu próprio Service(obter_driver_path()).
    """
    global _path_cache
    if _path_cache:
        return _path_cache
    with _lock:
        if not _path_cache:
            _path_cache = _resolver_caminho()
    return _path_cache


def get_service():
    """
    Retorna um Service NOVO a cada chamada.
    Nunca cacheia Service — objetos Service são de uso único por sessão.
    """
    from selenium.webdriver.chrome.service import Service
    return Service(obter_driver_path())


def pre_aquecer():
    """
    Resolve o caminho do ChromeDriver uma vez antes de aceitar
    requisições — evita corrida entre threads paralelas no primeiro uso.
    Não abre nenhuma janela Chrome.
    """
    print("[Driver] Verificando chromedriver...")
    caminho = obter_driver_path()
    if caminho:
        print(f"[Driver] Pronto → {caminho}")
    else:
        print("[Driver] ⚠️  ChromeDriver não encontrado!")
    return caminho