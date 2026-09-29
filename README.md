# OrçaTech — Comparador Inteligente de Preços e Orçamentos

Aplicação web em **Flask** que pesquisa um produto simultaneamente em **8 lojas** (Mercado Livre, KaBuM, Amazon, Terabyte, Americanas, iBytes, Gshield e AliExpress), filtra e classifica os resultados, permite montar um **orçamento com vários produtos e fornecedores** (carrinho) e gera o **PDF** pronto para aprovação. Os dados ficam em um banco **SQLite**, com histórico de buscas, cotações manuais e relatórios de economia.

> **Status:** em evolução de um comparador de preços simples para um sistema de compras (múltiplos produtos, fornecedores e aprovação). Login e fluxo de aprovação ainda estão no [roadmap](#roadmap).

---

## Índice

- [Principais funcionalidades](#principais-funcionalidades)
- [Como funciona a busca](#como-funciona-a-busca)
- [Carrinho e orçamento multi-produto](#carrinho-e-orçamento-multi-produto)
- [Fornecedores e cotação manual](#fornecedores-e-cotação-manual)
- [Estratégia de coleta por loja](#estratégia-de-coleta-por-loja)
- [Filtro de relevância e deduplicação](#filtro-de-relevância-e-deduplicação)
- [Geração do PDF](#geração-do-pdf)
- [Arquitetura e fluxo (jobs em background + SSE)](#arquitetura-e-fluxo-jobs-em-background--sse)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Banco de dados](#banco-de-dados)
- [Stack utilizada](#stack-utilizada)
- [Como rodar localmente](#como-rodar-localmente)
- [Executar no Windows passo a passo](#executar-no-windows-passo-a-passo)
- [Rodando com Docker](#rodando-com-docker)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Rotas da aplicação](#rotas-da-aplicação)
- [Persistência de dados](#persistência-de-dados)
- [Limitações conhecidas](#limitações-conhecidas)
- [Roadmap](#roadmap)

---

## Principais funcionalidades

- **Busca paralela em 8 lojas**, com técnica diferente por site (requests direto, Selenium, `undetected-chromedriver`, APIs internas VTEX/Next.js).
- **Progresso em tempo real** por loja (aguardando / buscando / concluído / erro) via Server-Sent Events, com fallback por polling.
- **Carrinho de orçamento**: adicione produtos de lojas diferentes com um clique, ajuste quantidades e finalize com solicitante, observações e condições comerciais.
- **PDF do orçamento** com todos os itens (produto, fornecedor, quantidade, preço unitário, subtotal e total geral).
- **Fornecedores e cotação manual**: cadastre fornecedores (online ou manuais) e lance cotações recebidas por telefone, e-mail ou loja física direto no carrinho.
- **Filtro inteligente de relevância**: remove acessórios não pedidos, produtos incompatíveis e modelos de numeração diferente da busca.
- **Deduplicação** de produtos repetidos.
- **Extração automática de especificações técnicas** do nome do produto (RAM, armazenamento, tela, câmera, processador, GPU, bateria etc.) via regex.
- **Classificação automática**: mais barato, "premium" (mais caro) e custo-benefício.
- **Cache de buscas** (6 horas) por produto.
- **Histórico de buscas** e página de orçamentos, com possibilidade de gerar o PDF novamente a partir de uma busca antiga.
- **Relatórios com gráficos** (Chart.js): economia acumulada, lojas mais baratas e produtos mais pesquisados.
- **Interface com modo claro/escuro** (preferência salva no navegador) e animações de entrada e de transição entre páginas.
- **Cards de resultado expansíveis**: tocar em um card abre os detalhes só dele; os demais continuam fechados.

---

## Como funciona a busca

Fluxo geral, disparado pelo formulário da tela inicial (`produto` + `solicitante` opcional):

1. Um `job_id` é criado e a busca roda em uma **thread separada** (não bloqueia o servidor Flask).
2. O usuário é redirecionado para `/aguardando/<job_id>`, que acompanha o progresso via `/stream/<job_id>` (SSE).
3. Internamente (`comparador.py`), as lojas são consultadas **em paralelo** com `ThreadPoolExecutor`.
4. Os resultados são somados, **deduplicados**, **filtrados** por relevância, **classificados** e ordenados por preço.
5. O resultado é salvo em `instance/cache/` e no histórico `instance/historico.json`; o usuário é levado para a tela de resultados.

---

## Carrinho e orçamento multi-produto

Cada card da tela de resultados tem o botão **Adicionar ao orçamento**. O fluxo:

1. **Adicionar**: o item vira uma cotação no banco e entra no orçamento em `rascunho` do navegador atual (guardado na sessão, sem exigir login). Uma faixa de confirmação aparece com o link "Ver carrinho".
2. **Carrinho** (`/orcamento/carrinho`): edita a quantidade, remove itens e vê o total. O botão "Carrinho" (com contador) aparece nas telas principais.
3. **Finalizar**: informa solicitante, condições comerciais e observações. O orçamento passa para o status `aguardando_aprovacao`, o rascunho da sessão é limpo e o PDF é baixado.
4. **Reabrir o PDF** a qualquer momento por `/orcamento/pdf/<id>`.

Status previstos para um orçamento: `rascunho → em_cotacao → aguardando_aprovacao → aprovado / reprovado → compra_realizada`. Hoje o sistema grava `rascunho` e `aguardando_aprovacao`; os demais entram com o fluxo de aprovação.

---

## Fornecedores e cotação manual

Em `/fornecedores/`:

- **Cadastrar e editar** fornecedores (nome, tipo `online`/`manual`, site e contato). Nomes duplicados são recusados.
- **Ativar/desativar**: fornecedores inativos não aparecem na cotação manual.
- **Lançar cotação manual**: escolha o fornecedor e informe produto, preço (aceita `1.234,56`), quantidade e, opcionalmente, frete, prazo, forma de pagamento e link. A cotação entra direto no carrinho ativo com origem `manual`.
- As lojas da busca (Amazon, KaBuM etc.) passam a existir como fornecedores automaticamente na primeira vez que um item delas é adicionado ao orçamento.

---

## Estratégia de coleta por loja

Cada loja tem seu módulo em `orcatech/scrapers/`, com a técnica mais estável encontrada para aquele site:

| Loja              | Técnica                                                                                     | Observação                                                                                                                              |
| ----------------- | ------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **KaBuM**         | `requests` puro, lendo o `__NEXT_DATA__` embutido no HTML                                   | Site em Next.js; não precisa de navegador.                                                                                              |
| **Mercado Livre** | `undetected-chromedriver` (Selenium)                                                        | O ML bloqueia Selenium comum e a API pública de busca (403). A versão do Chrome é detectada automaticamente.                            |
| **Amazon**        | 1) Selenium headless comum; 2) fallback com `undetected-chromedriver`                       | Bloqueio leve de automação ("Algo deu errado") pode ocorrer; o fallback busca pela home e pela caixa de pesquisa, com até 3 tentativas. |
| **Terabyte**      | Selenium headless, protegido por semáforo global                                            | Ver seção de concorrência abaixo.                                                                                                       |
| **Americanas**    | Selenium com scroll lento (lazy-load) + fallback via `__NEXT_DATA__`/JSON embutido          | Estratégia dupla para garantir link e imagem do produto.                                                                                |
| **iBytes**        | API pública VTEX (`catalog_system`) via `requests`, com fallback em `BeautifulSoup`         | Resposta rápida, sem navegador.                                                                                                         |
| **Gshield**       | `requests` + `BeautifulSoup` (loja VTEX)                                                    | Pode retornar 403 (proteção anti-bot). Ver [limitações](#limitações-conhecidas).                                                        |
| **AliExpress**    | Módulo próprio de coleta                                                                    | Ver o arquivo correspondente em `orcatech/scrapers/`.                                                                                  |

### Controle de concorrência do Selenium (`scrapers/driver_manager.py`)

Rodar vários Chromes ao mesmo tempo causou instabilidades no Windows (`DevToolsActivePort file doesn't exist`, crash `0xC0000005`, estouro do arquivo de paginação). Por isso:

- Um **semáforo global (`SELENIUM_SEMAPHORE`, limite 2)** restringe quantos navegadores Selenium sobem ao mesmo tempo. Lojas baseadas só em `requests` continuam 100% paralelas.
- Um **lock (`UC_START_LOCK`)** serializa apenas a *criação* do `undetected-chromedriver`, evitando disputa pelo chromedriver remendado em disco quando Mercado Livre e Amazon abrem juntos.
- **`versao_principal_chrome()`** detecta a versão do Chrome instalado (registro do Windows, com fallback pela pasta de versão ao lado do `chrome.exe`), evitando o erro de "ChromeDriver only supports Chrome version X". Se o erro voltar, apague `%APPDATA%\undetected_chromedriver`.
- Cada sessão do Chrome recebe um `--user-data-dir` temporário isolado.

---

## Filtro de relevância e deduplicação

Implementado em `comparador.py`:

- **Deduplicação**: chave `(loja, link do produto)` quando o link é real; `(loja, nome normalizado, preço)` quando o scraper só obteve um link genérico.
- **Filtro de acessórios**: se a busca não é por acessório, produtos com palavras como capa, película, cabo ou carregador são descartados, a menos que todas as palavras da busca também estejam no nome.
- **Filtro de incompatibilidade**: categorias mutuamente exclusivas (buscar "notebook" não traz "smartphone"; "iPhone" não traz "Galaxy"/"Redmi"/"Motorola").
- **Número de modelo**: extrai números que pareçam modelo (ex.: "15" de "iPhone 15"), ignorando specs (GB, MHz) e anos.
- **Similaridade de tokens**: exige ~80% das palavras-chave da busca no nome do produto.
- **Especificações**: regex para RAM, armazenamento, câmera, tela, taxa de atualização, bateria, resolução, potência, processador, placa de vídeo, rede, USB-C, Bluetooth e NFC.

---

## Geração do PDF

Dois geradores, com a mesma identidade visual ("OrçaTech"), usando **ReportLab**:

- **`gerar_pdf.py`**: PDF de uma busca (tabela comparativa, destaque do mais barato e do mais caro, resumo com preço médio e economia possível, área de assinatura).
- **`gerar_pdf_orcamento.py`**: PDF do orçamento multi-produto (itens, fornecedor, quantidade, preço unitário, subtotal e total geral).

Emojis (💰 🔥 ⭐) são convertidos em marcadores coloridos, pois não renderizam no ReportLab. Os PDFs são salvos em `instance/orcamentos/`.

---

## Arquitetura e fluxo (jobs em background + SSE)

- Cada busca vira um **job** em memória (`_jobs`, protegido por `threading.Lock`), com status (`pending → running → done/error`), progresso e status por loja.
- A busca roda numa thread `daemon` (`_worker`); o Flask continua respondendo durante o scraping.
- A tela de espera consome `/stream/<job_id>` via **Server-Sent Events**; `/status/<job_id>` e `/progresso/<job_id>` seguem disponíveis como polling.
- O streaming envia `X-Accel-Buffering: no` para evitar buffer em proxy reverso (nginx).

---

## Estrutura do projeto

```
gerador_orcamento-1-main/
├── run.py                       # Inicializador da aplicação
├── requirements.txt             # Dependências Python
├── Dockerfile                   # Imagem com Chrome + Xvfb
├── README.md
├── .gitignore
├── orcatech/                    # Código e recursos da aplicação Flask
│   ├── app.py                   # Rotas principais, jobs em background e SSE
│   ├── comparador.py            # Busca paralela, filtro, dedup e classificação
│   ├── models.py                # Modelos SQLAlchemy
│   ├── *_routes.py              # Rotas de orçamento e fornecedores
│   ├── *_service.py             # Serviços de orçamento
│   ├── gerar_pdf*.py            # Geração de PDFs
│   ├── paths.py                 # Caminhos dos dados locais
│   ├── scrapers/                # Scrapers e gerenciador do Chrome
│   ├── templates/               # Templates HTML do Flask
│   └── static/                  # Arquivos estáticos
├── scripts/                     # Comandos de banco e testes manuais
│   ├── init_db.py
│   ├── migrar_dados.py
│   └── testar_*.py
└── instance/                    # Banco, histórico, cache e PDFs (não versionados)
```

---

## Banco de dados

SQLite via **Flask-SQLAlchemy** (`sqlite:///orcatech.db`, criado em `instance/`).

| Modelo          | Função                                                                                   |
| --------------- | ---------------------------------------------------------------------------------------- |
| `Usuario`       | Nome, e-mail, senha (hash) e papel (`admin` / `usuario`). Preparado para o login.        |
| `Fornecedor`    | Nome único, tipo (`online`/`manual`), site, contato e flag `ativo`.                      |
| `ProdutoBusca`  | Termo pesquisado e especificações extraídas.                                             |
| `Cotacao`       | Preço encontrado (scraping ou manual): produto, fornecedor, link, imagem, frete, prazo, forma de pagamento e origem. |
| `Orcamento`     | Número (`ORC-AAAAMMDDHHmm`), solicitante, status, observações, condições e validade.     |
| `OrcamentoItem` | Item do carrinho: produto, quantidade e cotação escolhida.                               |
| `Aprovacao`     | Decisão (aprovado/reprovado) e comentário por orçamento. Tabela pronta; a tela ainda não. |

---

## Stack utilizada

**Backend**

- [Flask](https://flask.palletsprojects.com/) e [Flask-SQLAlchemy](https://flask-sqlalchemy.palletsprojects.com/) (SQLite)
- [Selenium](https://www.selenium.dev/) + [undetected-chromedriver](https://github.com/ultrafunkamsterdam/undetected-chromedriver)
- [webdriver-manager](https://pypi.org/project/webdriver-manager/)
- [requests](https://docs.python-requests.org/) + [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/)
- [ReportLab](https://www.reportlab.com/) (PDF)
- [python-dotenv](https://pypi.org/project/python-dotenv/)

**Frontend**

- HTML + CSS + JavaScript puro (sem framework), com Server-Sent Events, Chart.js (CDN), tema claro/escuro e View Transitions.

---

## Como rodar localmente

### Pré-requisitos

- Python 3.10+
- Google Chrome instalado (para as lojas via Selenium)
- Windows, macOS ou Linux
- Acesso à internet para instalar as dependências e consultar as lojas

### Windows — execução passo a passo

Os comandos abaixo são para **PowerShell** e devem ser executados na pasta raiz do projeto, onde estão `run.py`, `requirements.txt` e a pasta `orcatech/`.

#### 1. Abrir o PowerShell na pasta do projeto

Abra o PowerShell pelo menu Iniciar. Entre na pasta do projeto (ajuste o caminho caso ela esteja em outro local):

```powershell
Set-Location 'C:\Users\Suporte\Desktop\gerador_orcamento-1-main'
```

Confirme que está na pasta correta:

```powershell
Get-ChildItem
```

Você deve encontrar `run.py`, `requirements.txt`, `orcatech/`, `scripts/` e, normalmente, `.venv/`.

#### 2. Conferir o Python

```powershell
python --version
```

É necessário Python 3.10 ou superior. Se o comando `python` não for reconhecido, instale o Python e habilite a opção **Add Python to PATH** durante a instalação.

#### 3. Criar ou conferir o ambiente virtual

Este projeto usa o ambiente virtual `.venv`. Se a pasta `.venv` já existir, pule a criação e use o Python dela nos próximos passos.

Para criar o ambiente quando ele ainda não existir:

```powershell
python -m venv .venv
```

Não é obrigatório ativar o ambiente virtual: os comandos abaixo chamam diretamente o Python instalado dentro de `.venv`, evitando diferenças entre versões do Python.

#### 4. Instalar as dependências

Execute este passo na primeira instalação ou depois de uma alteração em `requirements.txt`:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

#### 5. Preparar o banco de dados na primeira execução

O projeto guarda o banco em `instance/orcatech.db`. Se esse arquivo já existir, o banco local já está criado e **não é necessário repetir esta etapa**.

Somente em uma instalação nova, crie as tabelas e o usuário administrador:

```powershell
.\.venv\Scripts\python.exe -m scripts.init_db
```

O comando pode solicitar nome, e-mail e senha do administrador. Se já existir um administrador, o script informa que não há nada a fazer. Não apague `instance/orcatech.db`: esse arquivo contém os fornecedores, cotações, orçamentos e usuários salvos.

`scripts.migrar_dados` é um comando opcional para importar cache e histórico de uma instalação antiga. Não o execute no uso normal; os dados atuais já ficam em `instance/`.

#### 6. Iniciar o servidor local

Na mesma janela do PowerShell, execute:

```powershell
.\.venv\Scripts\python.exe run.py
```

Por padrão, o servidor usa a porta `5000`. Se essa porta já estiver ocupada por outro processo, inicie o OrçaTech em `5001`:

```powershell
$env:PORT = '5001'
.\.venv\Scripts\python.exe run.py
```

O valor de `PORT` vale para a janela atual do PowerShell. Se abrir outra janela ou quiser voltar para a porta padrão, remova a variável antes de iniciar:

```powershell
Remove-Item Env:PORT -ErrorAction SilentlyContinue
```

Deixe a janela do servidor aberta enquanto estiver usando o sistema. As mensagens de inicialização e de busca aparecem nela.

#### 7. Abrir o sistema no navegador

Abra o endereço correspondente à porta escolhida:

- Porta padrão: `http://127.0.0.1:5000`
- Porta alternativa `5001`: `http://127.0.0.1:5001`

Na tela inicial, digite o nome do produto, informe o solicitante se desejar e clique em **Buscar Preços**. A busca consulta as lojas em paralelo e pode levar alguns minutos, dependendo do Chrome, da internet e das respostas dos sites.

#### 8. Encerrar o servidor

Volte para a janela do PowerShell em que o servidor está rodando e pressione **Ctrl+C**. Os dados salvos em `instance/` permanecem no computador.

### macOS e Linux

Instale Python 3.10 ou superior e Google Chrome. A partir da pasta raiz do projeto, execute:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m scripts.init_db  # somente na primeira instalação
python run.py
```

Abra `http://127.0.0.1:5000`. Para usar outra porta, defina `PORT` antes de iniciar, por exemplo `PORT=5001 python run.py`. Encerre o servidor com **Ctrl+C**.

### Solução de problemas ao iniciar localmente

- **“Address already in use” ou erro de porta ocupada:** feche o outro servidor ou escolha uma porta livre com `$env:PORT = '5001'` no PowerShell antes de iniciar.
- **O navegador mostra erro 500:** confira as mensagens na janela do servidor. Confirme que está iniciando `run.py` a partir da raiz correta do projeto.
- **O comando Python ou dependências falham:** confira se está na pasta certa e execute novamente `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.
- **Uma loja retorna poucos ou nenhum produto:** os sites podem bloquear temporariamente consultas automatizadas ou alterar suas páginas. Confira os logs do servidor e tente novamente mais tarde. As outras lojas podem continuar funcionando.
- **Chrome/ChromeDriver falha:** confirme que o Google Chrome está instalado e atualizado. O Chrome é necessário para os scrapers que usam Selenium.
- **Não encontra histórico, cache ou banco:** não mova nem apague `instance/`; o banco, o histórico, o cache e os PDFs do orçamento ficam nessa pasta.

### Atalhos para iniciar depois da configuração inicial

Para uso diário, basta abrir o PowerShell, entrar na pasta do projeto e iniciar o servidor:

```powershell
Set-Location 'C:\Users\Suporte\Desktop\gerador_orcamento-1-main'
$env:PORT = '5001'  # opcional; use se a porta 5000 estiver ocupada
.\.venv\Scripts\python.exe run.py
```

Depois, abra `http://127.0.0.1:5001` se definiu a porta alternativa; caso contrário, abra `http://127.0.0.1:5000`.

---

## Rodando com Docker

O `Dockerfile` instala o Google Chrome e o display virtual (Xvfb) necessários para rodar o navegador sem interface gráfica:

```bash
docker build -t orcatech .
docker run -p 5000:5000 orcatech
```

O container usa `xvfb-run` para criar um display virtual (`:99`, 1920x1080) antes de iniciar `python run.py`. Como os dados ficam em `instance/`, monte essa pasta como volume se quiser que eles sobrevivam ao container. Para criar as tabelas e o usuário admin, execute `python -m scripts.init_db`.

---

## Variáveis de ambiente

Lidas de um arquivo `.env` na raiz (via `python-dotenv`), carregado antes dos módulos de scraping. **Não versione o `.env`.**

| Variável             | Obrigatória | Descrição                                                                                                                             |
| -------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `SECRET_KEY`         | Recomendada | Chave usada para assinar a sessão (o carrinho depende dela). Sem ela, o app usa um valor padrão inseguro. Defina uma chave longa e aleatória. |
| `CHROME_BINARY_PATH` | Não         | Caminho completo do `chrome.exe`, quando o Chrome não está em um local padrão (comum em instalação só para o usuário, no Windows).   |
| `PORT`               | Não         | Porta local do servidor (padrão `5000`); também define a porta do container Docker.                                                   |

---

## Rotas da aplicação

### Busca e histórico

| Rota                            | Método   | Descrição                                                                    |
| ------------------------------- | -------- | ---------------------------------------------------------------------------- |
| `/`                             | GET      | Página inicial: formulário de busca + última pesquisa/histórico.             |
| `/buscar`                       | POST     | Inicia uma busca (cria o job e a thread) e redireciona para a tela de espera. |
| `/aguardando/<job_id>`          | GET      | Tela de progresso em tempo real.                                             |
| `/stream/<job_id>`              | GET      | Server-Sent Events com o status do job.                                      |
| `/status/<job_id>`              | GET      | Status do job em JSON (polling).                                             |
| `/progresso/<job_id>`           | GET      | Alias de `/status/<job_id>`.                                                 |
| `/resultado/<job_id>`           | GET      | Resultados da busca concluída.                                               |
| `/orcamentos`                   | GET      | Histórico de buscas.                                                         |
| `/relatorios`                   | GET      | Dashboard de economia, lojas e produtos mais buscados.                       |
| `/api/relatorios_dados`         | GET      | Dados agregados do histórico em JSON (Chart.js).                             |
| `/rever/<indice>`               | GET      | Reabre os resultados de um item do histórico (usa cache).                    |
| `/gerar_pdf`                    | POST     | PDF da busca atual.                                                          |
| `/gerar_pdf_historico/<indice>` | GET/POST | PDF de um item do histórico.                                                 |

### Carrinho e orçamento (`/orcamento`)

| Rota                              | Método | Descrição                                                  |
| --------------------------------- | ------ | ---------------------------------------------------------- |
| `/orcamento/adicionar`            | POST   | Adiciona um item (card de resultado) ao carrinho.          |
| `/orcamento/carrinho`             | GET    | Tela do carrinho.                                          |
| `/orcamento/item/<id>/quantidade` | POST   | Atualiza a quantidade (0 remove o item).                   |
| `/orcamento/item/<id>/remover`    | POST   | Remove o item.                                             |
| `/orcamento/finalizar`            | POST   | Finaliza o orçamento e gera o PDF.                         |
| `/orcamento/pdf/<id>`             | GET    | Baixa o PDF de um orçamento finalizado.                    |

### Fornecedores (`/fornecedores`)

| Rota                              | Método | Descrição                                            |
| --------------------------------- | ------ | ---------------------------------------------------- |
| `/fornecedores/`                  | GET    | Lista, cadastro e formulário de cotação manual.      |
| `/fornecedores/novo`              | POST   | Cadastra um fornecedor.                              |
| `/fornecedores/<id>/editar`       | POST   | Edita um fornecedor.                                 |
| `/fornecedores/<id>/ativo`        | POST   | Ativa ou desativa um fornecedor.                     |
| `/fornecedores/cotacao-manual`    | POST   | Lança uma cotação manual e adiciona ao carrinho.     |

---

## Persistência de dados

- **`instance/orcatech.db`** (SQLite): fornecedores, produtos pesquisados, cotações, orçamentos, itens e usuários.
- **`instance/historico.json`**: lista das buscas já realizadas (usada pelas telas de histórico e relatórios).
- **`instance/cache/<produto>.json`**: resultado completo de uma busca, reaproveitado por até **6 horas**.
- **`instance/orcamentos/*.pdf`**: PDFs gerados.
- **`instance/debug/`**: HTMLs de diagnóstico dos scrapers, quando necessário.

Nenhum desses arquivos deve ser versionado (veja o `.gitignore`).

---

## Limitações conhecidas

- Depende da **estrutura de HTML/JSON de terceiros**: mudanças nos sites podem quebrar um scraper específico. Cada loja falha de forma isolada, sem derrubar as demais.
- **Amazon**: pode devolver a página "Algo deu errado" (bloqueio leve de automação), principalmente após muitas buscas seguidas. Nesse caso, aguardar algumas horas costuma resolver. Em falha, o scraper salva o HTML em `instance/debug/`.
- **Gshield**: retorna 403 (anti-bot) no `requests`, resultando em 0 produtos. Ainda não investigado.
- **Americanas**: às vezes devolve cards duplicados sem foto; o código tenta recuperar as imagens via `__NEXT_DATA__`.
- Lojas via Selenium exigem o **Chrome instalado** e são mais lentas. O semáforo (limite 2) pode alongar a busca em máquinas com pouca memória.
- **Sem autenticação**: qualquer pessoa com acesso à aplicação vê o histórico e pode mexer nos fornecedores. O carrinho é por navegador (sessão), não por usuário.

---

## Roadmap

- [ ] **Login** (Flask-Login) com papéis admin/usuário, proteção de rotas sensíveis (fornecedores, finalizar orçamento) e vínculo do orçamento ao usuário logado.
- [ ] **Compartilhamento**: link público somente leitura, botão de WhatsApp e envio do PDF por e-mail.
- [ ] **Workflow de aprovação**: tela para aprovar/reprovar com comentário e status completo do orçamento.
- [ ] **Alerta de queda de preço**: comparar cotações novas com as já salvas e agendar verificações (APScheduler ou tarefa agendada do Windows).
- [ ] Recursos empresariais (departamentos, centro de custo, pedido de compra), se virar sistema oficial de uma empresa.
- [ ] Segurança geral: `SECRET_KEY` definida no `.env` sem fallback no código e dependências (`flask-sqlalchemy`, `werkzeug`, `flask-login`) no `requirements.txt`.
