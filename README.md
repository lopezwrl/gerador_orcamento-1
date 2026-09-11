# OrçaTech — Comparador Inteligente de Preços

Aplicação web em **Flask** que pesquisa um produto simultaneamente em **7 lojas brasileiras** (Mercado Livre, KaBuM, Amazon, Terabyte, Americanas, iBytes e Gshield), filtra e classifica os resultados, e gera um **orçamento em PDF** pronto para aprovação — com histórico de buscas e relatórios/gráficos de economia.

---

## Índice

- [Principais funcionalidades](#principais-funcionalidades)
- [Como funciona a busca](#como-funciona-a-busca)
- [Estratégia de coleta por loja](#estratégia-de-coleta-por-loja)
- [Filtro de relevância e deduplicação](#filtro-de-relevância-e-deduplicação)
- [Geração do PDF](#geração-do-pdf)
- [Arquitetura e fluxo (jobs em background + SSE)](#arquitetura-e-fluxo-jobs-em-background--sse)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Stack utilizada](#stack-utilizada)
- [Como rodar localmente](#como-rodar-localmente)
- [Rodando com Docker](#rodando-com-docker)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Rotas da aplicação](#rotas-da-aplicação)
- [Persistência de dados](#persistência-de-dados)
- [Limitações conhecidas](#limitações-conhecidas)

---

## Principais funcionalidades

- **Busca paralela em 7 lojas** com técnicas diferentes por site (requests direto, Selenium, `undetected-chromedriver`, APIs internas VTEX/Next.js).
- **Progresso em tempo real** por loja (aguardando / buscando / concluído / erro) via Server-Sent Events, com fallback por polling.
- **Filtro inteligente de relevância**: remove acessórios não pedidos, produtos incompatíveis (ex.: buscar "iPhone" não deveria trazer "Galaxy"/"Redmi") e produtos de modelo/numeração diferente da busca.
- **Deduplicação** de produtos repetidos (a mesma loja renderizando o mesmo card duas vezes, por exemplo).
- **Extração automática de especificações técnicas** do nome do produto (RAM, armazenamento, tela, câmera, processador, GPU, bateria, etc.) via regex.
- **Classificação automática**: identifica o mais barato, o "premium" (mais caro) e os de custo-benefício.
- **Cache de buscas** (6 horas) por produto, para não repetir scraping desnecessário.
- **Histórico de orçamentos** (`historico.json`) com página dedicada de orçamentos e possibilidade de gerar o PDF novamente a partir de uma busca antiga.
- **Relatórios com gráficos** (Chart.js): economia acumulada, lojas mais baratas com mais frequência e produtos mais pesquisados.
- **Geração de PDF profissional** (ReportLab) com tabela comparativa, resumo da pesquisa e campo de aprovação/assinatura.

---

## Como funciona a busca

Fluxo geral, disparado pelo formulário da tela inicial (`produto` + `solicitante` opcional):

1. Um `job_id` é criado e a busca real roda em uma **thread separada** (não bloqueia o servidor Flask).
2. O usuário é redirecionado para a tela de espera (`/aguardando/<job_id>`), que escuta o progresso via `/stream/<job_id>` (SSE).
3. Internamente (`comparador.py`), as 7 lojas são consultadas **em paralelo** com `ThreadPoolExecutor`.
4. Os resultados de todas as lojas são somados, **deduplicados**, **filtrados** por relevância, **classificados** (mais barato / premium / custo-benefício) e ordenados por preço.
5. O resultado é salvo em cache (`cache/<produto>.json`) e no histórico (`historico.json`), e o usuário é redirecionado para a tela de resultados.

---

## Estratégia de coleta por loja

Cada loja tem seu próprio módulo `scraping_<loja>.py`, com a técnica mais estável encontrada para aquele site:

| Loja | Técnica | Observação |
|------|---------|------------|
| **KaBuM** | `requests` puro, lendo o `__NEXT_DATA__` embutido no HTML | Site em Next.js; não precisa de navegador. |
| **Mercado Livre** | `undetected-chromedriver` (Selenium) | O ML bloqueia Selenium "normal" com tela de verificação e bloqueia a API pública de busca (403); o `uc` mascara as fingerprints de automação. |
| **Amazon** | Selenium headless (`--headless=new`) com flags anti-detecção | Randomiza user-agent, remove a flag `AutomationControlled`. |
| **Terabyte** | Selenium headless, protegido por semáforo global | Ver seção de concorrência abaixo. |
| **Americanas** | Selenium com scroll lento (lazy-load) + fallback via `__NEXT_DATA__`/JSON embutido | Estratégia dupla para garantir link e imagem do produto. |
| **iBytes** | API pública VTEX (`catalog_system`) via `requests`, com fallback em `BeautifulSoup` | Resposta rápida (~1s), sem navegador. |
| **Gshield** | `requests` + `BeautifulSoup` (loja VTEX) | Sem navegador. |

### Controle de concorrência do Selenium (`driver_manager.py`)
Rodar vários Chromes headless ao mesmo tempo (Mercado Livre, Amazon, Terabyte, Americanas) causou instabilidades observadas em produção (`DevToolsActivePort file doesn't exist`, crash `0xC0000005`, estouro do arquivo de paginação no Windows). A solução adotada foi um **semáforo global (`SELENIUM_SEMAPHORE`, limite 2)** que restringe quantos navegadores Selenium sobem ao mesmo tempo — as lojas baseadas só em `requests` continuam 100% paralelas, sem essa limitação. Cada sessão do Chrome também recebe um `--user-data-dir` temporário isolado, evitando conflito de perfil entre buscas simultâneas.

### `lojas_customizadas.json`
Arquivo de configuração para lojas adicionais "genéricas" (seletor de container/nome/preço/link/imagem por CSS), pensado para estender a lista de lojas sem escrever um scraper dedicado. Atualmente contém apenas a **Pichau**, marcada como bloqueada por proteção antibot (Cloudflare) — **este arquivo não está integrado ao `comparador.py` no momento** (fica como referência/rascunho para uma futura loja "plugável").

---

## Filtro de relevância e deduplicação

Implementado em `comparador.py`:

- **Deduplicação**: usa `(loja, link do produto)` como chave quando o link é real; cai para `(loja, nome normalizado, preço)` quando o scraper só conseguiu um link genérico (home da loja).
- **Filtro de acessórios**: se a busca não é por um acessório (ex.: buscar "iPhone 15" não deveria trazer "capinha para iPhone 15"), produtos cujo nome bate com palavras de acessório (capa, película, cabo, carregador, etc.) são descartados — a menos que todas as palavras-chave da busca também estejam no nome.
- **Filtro de incompatibilidade**: um mapa de categorias mutuamente exclusivas (ex.: buscar "notebook" não deve trazer "smartphone"; buscar "iPhone" não deve trazer "Galaxy"/"Redmi"/"Motorola").
- **Checagem de número de modelo**: extrai números que pareçam modelo (ex.: "15" de "iPhone 15"), ignorando specs técnicas (GB, MHz, etc.) e anos — só passam produtos cujo nome contenha o mesmo número de modelo da busca.
- **Relevância por similaridade de tokens**: exige que pelo menos ~80% das palavras-chave da busca apareçam no nome do produto.
- **Extração de especificações**: um conjunto de expressões regulares reconhece RAM, armazenamento, câmera, tela, taxa de atualização, bateria, resolução, potência, processador (Intel/Ryzen), placa de vídeo (RTX/GTX), rede (3G/4G/5G), conector USB-C, Bluetooth e NFC diretamente do nome do produto, para montar uma ficha técnica resumida.

---

## Geração do PDF

`gerar_pdf.py` usa **ReportLab** para montar um PDF com identidade visual própria (paleta de cores "OrçaTech"):

- Cabeçalho com marca, número do orçamento (`ORC-AAAAMMDDHHmm`) e metadados (produto, data/hora, solicitante).
- Tabela comparativa de todos os produtos encontrados, com destaque colorido para o mais barato e o mais caro.
- Bloco de resumo: mais barato, premium, preço médio e economia possível entre o mais barato e o premium.
- Área de aprovação com linhas de assinatura (solicitante / aprovador).
- Emojis do backend (💰 🔥 ⭐) são convertidos em marcadores coloridos (`■`), já que não renderizam nativamente no ReportLab.

Os PDFs são salvos na pasta `orcamentos/` e podem ser baixados a qualquer momento — tanto de uma busca recém-feita quanto de um item do histórico.

---

## Arquitetura e fluxo (jobs em background + SSE)

- Cada busca vira um **job** guardado em memória (`_jobs`, protegido por `threading.Lock`), com status (`pending` → `running` → `done`/`error`), progresso percentual e status individual por loja.
- A busca roda numa thread `daemon` separada (`_worker`), então o servidor Flask continua respondendo outras requisições normalmente enquanto o scraping acontece.
- A tela de espera consome `/stream/<job_id>` via **Server-Sent Events** (`EventSource` no navegador), recebendo atualizações assim que o status muda — sem precisar ficar perguntando (polling) em intervalos fixos.
- `/status/<job_id>` e `/progresso/<job_id>` continuam disponíveis como alternativa via polling, para compatibilidade.
- O endpoint de streaming envia `X-Accel-Buffering: no` para evitar que um proxy reverso (ex.: nginx) segure a resposta em buffer.

---

## Estrutura do projeto

```
gerador_orcamento-1-main/
├── app.py                     # Rotas Flask, gestão de jobs em background, SSE
├── comparador.py               # Orquestra a busca paralela, filtro, dedup e classificação
├── driver_manager.py           # Gestão do ChromeDriver/Chrome (paths, flags, semáforo)
├── gerar_pdf.py                 # Geração do orçamento em PDF (ReportLab)
├── scraping_amazon.py           # Coleta via Selenium
├── scraping_americanas.py       # Coleta via Selenium + fallback __NEXT_DATA__
├── scraping_gshield.py          # Coleta via requests + BeautifulSoup (VTEX)
├── scraping_ibyte.py            # Coleta via API VTEX + fallback BeautifulSoup
├── scraping_kabum.py            # Coleta via requests + __NEXT_DATA__
├── scraping_mercadolivre.py     # Coleta via undetected-chromedriver
├── scraping_terabyte.py         # Coleta via Selenium (com semáforo)
├── lojas_customizadas.json      # Config de lojas "genéricas" adicionais (rascunho, não integrado)
├── requirements.txt             # Dependências Python
├── Dockerfile                   # Imagem com Chrome + Xvfb para rodar em servidor headless
├── templates/
│   ├── index.html               # Formulário de busca + acesso rápido ao histórico
│   ├── aguardando.html          # Tela de progresso em tempo real (SSE)
│   ├── resultados.html          # Tabela comparativa da busca atual
│   ├── orcamentos.html          # Histórico de orçamentos já gerados
│   └── relatorios.html          # Dashboards/gráficos (Chart.js)
└── .gitignore
```

---

## Stack utilizada

**Backend**
- [Flask](https://flask.palletsprojects.com/) — servidor web e roteamento
- [Selenium](https://www.selenium.dev/) + [undetected-chromedriver](https://github.com/ultrafunkamsterdam/undetected-chromedriver) — automação de navegador para lojas com proteção antibot ou muito dependentes de JavaScript
- [webdriver-manager](https://pypi.org/project/webdriver-manager/) — download automático do ChromeDriver quando não há um local
- [requests](https://docs.python-requests.org/) + [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) — coleta leve (sem navegador) nas lojas que permitem
- [ReportLab](https://www.reportlab.com/) — geração do PDF do orçamento
- [python-dotenv](https://pypi.org/project/python-dotenv/) — leitura de variáveis de ambiente do `.env`

**Frontend**
- HTML + CSS + JavaScript puro, com **Server-Sent Events** (`EventSource`) para progresso em tempo real e **Chart.js** (via CDN) para os gráficos da página de relatórios.

---

## Como rodar localmente

### Pré-requisitos
- Python 3.10+ (recomendado)
- Google Chrome instalado (necessário para as lojas coletadas via Selenium)
- `chromedriver.exe` compatível com a versão do Chrome, opcional — se não existir localmente, o `webdriver-manager` faz o download automático na primeira busca

### Passos

```bash
# 1. Entrar na pasta do projeto
cd gerador_orcamento-1-main

# 2. Criar e ativar um ambiente virtual (recomendado)
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

# 3. Instalar dependências
pip install -r requirements.txt

# 4. (Opcional) Criar um arquivo .env se o Chrome não estiver em um caminho padrão
echo CHROME_BINARY_PATH=C:\caminho\para\chrome.exe > .env

# 5. Rodar a aplicação
python app.py
```

A aplicação sobe por padrão em `http://localhost:5000` (modo debug ativado, sem reloader — para não duplicar as threads de scraping).

---

## Rodando com Docker

O `Dockerfile` já resolve a instalação do Google Chrome e do display virtual (Xvfb) necessário para rodar o navegador num servidor sem interface gráfica:

```bash
docker build -t orcatech .
docker run -p 5000:5000 orcatech
```

O container usa `xvfb-run` para criar automaticamente um display virtual (`:99`, resolução 1920x1080) antes de iniciar `python app.py`, permitindo que o Chrome rode normalmente mesmo sem monitor real.

---

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|----------|:-----------:|-----------|
| `CHROME_BINARY_PATH` | Não | Caminho completo do `chrome.exe`, usado quando o Chrome não está instalado em um dos locais padrão que o Selenium já reconhece (comum em instalação só para o usuário atual, no Windows). |
| `PORT` | Não | Porta exposta pelo container Docker (padrão `5000`). |

Variáveis são lidas de um arquivo `.env` na raiz do projeto (via `python-dotenv`), carregado antes de qualquer outro import em `app.py`.

---

## Rotas da aplicação

| Rota | Método | Descrição |
|------|--------|-----------|
| `/` | GET | Página inicial: formulário de busca + última pesquisa/histórico. |
| `/buscar` | POST | Inicia uma nova busca (cria o job e a thread de scraping) e redireciona para a tela de espera. |
| `/aguardando/<job_id>` | GET | Tela de progresso em tempo real. |
| `/stream/<job_id>` | GET | Server-Sent Events com o status/progresso do job. |
| `/status/<job_id>` | GET | Status do job em JSON (polling, fallback do SSE). |
| `/progresso/<job_id>` | GET | Alias de `/status/<job_id>` mantido por compatibilidade. |
| `/resultado/<job_id>` | GET | Tela de resultados da busca concluída. |
| `/orcamentos` | GET | Histórico de orçamentos já pesquisados. |
| `/relatorios` | GET | Dashboard com gráficos de economia, lojas e produtos mais buscados. |
| `/api/relatorios_dados` | GET | Dados agregados do histórico em JSON, usados pelos gráficos (Chart.js). |
| `/rever/<indice>` | GET | Reabre os resultados de um item do histórico (usa cache, sem nova busca). |
| `/gerar_pdf` | POST | Gera e baixa o PDF do orçamento da busca atual. |
| `/gerar_pdf_historico/<indice>` | GET/POST | Gera e baixa o PDF de um item do histórico. |

---

## Persistência de dados

O projeto não usa banco de dados — tudo é persistido em arquivos locais:

- `historico.json` — lista de todas as buscas já realizadas (produto, data, mais barato, premium, economia).
- `cache/<produto>.json` — resultado completo de uma busca, reaproveitado por até **6 horas** (evita rodar o scraping de novo para o mesmo produto).
- `orcamentos/*.pdf` — PDFs gerados, nomeados por produto e data/hora.

---

## Limitações conhecidas

- Depende de **estrutura de HTML/JSON de terceiros** (KaBuM, Mercado Livre, Amazon, etc.): mudanças nesses sites podem quebrar um scraper específico a qualquer momento — por isso cada loja falha de forma isolada (não derruba a busca das demais).
- Lojas coletadas via Selenium exigem o **Google Chrome instalado** (localmente ou dentro do container Docker) e são naturalmente mais lentas que as coletadas via `requests`.
- O semáforo de concorrência do Selenium (limite de 2 navegadores simultâneos) é uma mitigação para instabilidade observada em ambiente Windows com pouca memória virtual — pode tornar a busca mais lenta em máquinas com poucos recursos.
- `lojas_customizadas.json` ainda não está integrado ao fluxo de busca (`comparador.py`) — hoje é apenas um rascunho de configuração para uma futura loja "plugável" por seletor CSS.
- Sem autenticação/multiusuário: o histórico e o cache são globais para quem acessa a aplicação.
