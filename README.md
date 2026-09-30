# OrçaTech — Comparador Inteligente de Preços e Orçamentos

Aplicação web em **Flask** que pesquisa um produto simultaneamente em **8 lojas** (Mercado Livre, KaBuM, Amazon, Terabyte, Americanas, iBytes, Gshield e AliExpress), filtra e classifica os resultados, permite montar um **orçamento com vários produtos e fornecedores** (carrinho) e gera o **PDF** pronto para aprovação. Os dados ficam em um banco **SQLite**, com histórico de buscas, cotações manuais e relatórios de economia.

> **Status:** comparador de preços com login, workflow de aprovação, compartilhamento, monitoramento de preços e recursos empresariais opcionais. A feature empresarial permanece desligada por padrão.

## Resumo da entrega atual

Esta versão do OrçaTech consolida o fluxo completo de comparação, aprovação e acompanhamento comercial:

- **Busca inteligente e paralela**: consulta simultânea em várias lojas, deduplicação de resultados, filtro de relevância e classificação por melhor custo-benefício.
- **Carrinho e orçamento multi-produto**: o usuário monta o pedido com itens de diferentes fornecedores, ajusta quantidades e acompanha totais em tempo real.
- **Workflow de aprovação e histórico**: orçamentos passam por estados de rascunho, cotação, aprovação, compra e reabertura, com transições registradas e validade configurável.
- **Compartilhamento e envio**: links públicos somente leitura, WhatsApp, e-mails automáticos com PDF e limites de envio por hora para evitar abuso.
- **Monitoramento de preços**: é possível acompanhar quedas de preço por produto/loja, receber alertas e consultar histórico dos últimos 90 dias.
- **Recursos empresariais opcionais**: departamentos, centros de custo, limite de gasto, pedidos por fornecedor, relatórios e controle de alçada de aprovação.
- **Operação robusta**: jobs em background, SSE para progresso em tempo real, cache de pesquisas, PDF personalizado e integração com diferentes estratégias de coleta por loja.

Esse conjunto transforma a aplicação em um sistema de compras e gestão de orçamento, com foco em acompanhamento, eficiência operacional e controle de aprovação.

---

## Índice

- [Resumo da entrega atual](#resumo-da-entrega-atual)

- [Principais funcionalidades](#principais-funcionalidades)
- [Como funciona a busca](#como-funciona-a-busca)
- [Carrinho e orçamento multi-produto](#carrinho-e-orçamento-multi-produto)
- [Fornecedores e cotação manual](#fornecedores-e-cotação-manual)
- [Recursos empresariais (opcionais)](#recursos-empresariais-opcionais)
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
- [Validação local realizada](#validação-local-realizada)
- [Rotas da aplicação](#rotas-da-aplicação)
- [Persistência de dados](#persistência-de-dados)
- [Executar os testes](#executar-os-testes)
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

1. **Adicionar**: o item vira uma cotação no banco e entra no orçamento `rascunho` do usuário autenticado. Uma faixa de confirmação aparece com o link "Ver carrinho".
2. **Carrinho** (`/orcamento/carrinho`): edita a quantidade, remove itens e vê o total. O botão "Carrinho" (com contador) aparece nas telas principais.
3. **Enviar para aprovação**: informa solicitante, condições comerciais e observações. O sistema registra as transições `rascunho → em_cotacao → aguardando_aprovacao`, congela os dados comerciais dos itens, define a validade e registra cada transição no histórico.
4. **Decidir**: usuários com papel `aprovador` e administradores acessam `/aprovacoes`. A pessoa solicitante não pode aprovar o próprio orçamento; a exceção administrativa depende da configuração `ADMIN_PODE_AUTOAPROVAR`. A reprovação exige comentário.
5. **Consultar**: o detalhe em `/orcamento/<id>` exibe totais com frete, condições, validade, histórico e decisões. Itens ficam bloqueados após envio; um orçamento reprovado pode ser reaberto pelo dono ou administrador.
6. **PDF**: use o botão no detalhe ou `/orcamento/pdf/<id>`. Inclui status, validade, snapshot de preços e informações de aprovação; documentos reprovados ou expirados recebem marca d'água.
7. **Compartilhar**: no detalhe, dono/admin pode gerar, revogar ou regenerar link público, válido por padrão por 7 dias. A página pública é somente leitura, sem nome do solicitante, observações internas ou histórico. O link também pode ser aberto no WhatsApp.
8. **E-mail**: o dono/admin pode enviar o PDF para um destinatário validado; o envio é processado em segundo plano e registrado no detalhe. O limite padrão é de 5 envios por orçamento por hora. Configure SMTP no `.env`; falhas aparecem no histórico e a senha nunca é registrada.
9. **Compras empresariais**: quando habilitada, o orçamento pede departamento e centro de custo, aplica limite de gasto e encaminha a aprovação conforme a alçada configurada. Compradores emitem pedidos separados por fornecedor, acompanham entrega e nota fiscal e baixam um PDF por pedido.

Status válidos: `rascunho → em_cotacao → aguardando_aprovacao → aprovado | reprovado`; aprovado pode avançar para `compra_realizada` e reprovado pode voltar para `rascunho`. Aprovações de orçamentos expirados são bloqueadas até que o dono ou administrador renove a validade.

---

## Fornecedores e cotação manual

Em `/fornecedores/`:

- **Cadastrar e editar** fornecedores (nome, tipo `online`/`manual`, site e contato). Nomes duplicados são recusados.
- **Ativar/desativar**: fornecedores inativos não aparecem na cotação manual.
- **Lançar cotação manual**: escolha o fornecedor e informe produto, preço (aceita `1.234,56`), quantidade e, opcionalmente, frete, prazo, forma de pagamento e link. A cotação entra direto no carrinho ativo com origem `manual`.
- As lojas da busca (Amazon, KaBuM etc.) passam a existir como fornecedores automaticamente na primeira vez que um item delas é adicionado ao orçamento.

---

## Recursos empresariais (opcionais)

Os recursos empresariais são opt-in e continuam desligados em instalações já existentes. Ative-os definindo `FEATURE_EMPRESARIAL_ENABLED=true` no `.env` **depois de aplicar as migrations** e reinicie o servidor. O limite de alçada padrão é R$ 10.000 (`ALCADA_APROVACAO_LIMITE=10000.00`).

1. O administrador cadastra departamentos e centros de custo em `/empresarial/estrutura`, define o limite de cada centro e vincula usuários aos departamentos em **Gerenciar usuários**. Um aprovador precisa estar associado a um departamento.
2. Ao finalizar um orçamento, o solicitante escolhe seu departamento e um centro de custo pertencente a ele. Administradores podem selecionar qualquer unidade. O envio é bloqueado se o total superar o limite do centro ou se os orçamentos aguardando aprovação, aprovados e já comprados, somados ao novo orçamento, ultrapassarem o limite disponível.
3. Até o valor configurado em `ALCADA_APROVACAO_LIMITE`, apenas um aprovador ativo do mesmo departamento pode aprovar. Acima desse valor, a decisão fica com administradores. A regra de segregação impede a autoaprovação, salvo quando `ADMIN_PODE_AUTOAPROVAR=true`.
4. Após a aprovação, um usuário com papel `comprador` ou `admin` abre **Emitir pedidos por fornecedor** no detalhe do orçamento. O sistema cria um pedido por fornecedor, preserva nomes, preços, quantidades, frete e condições aprovadas e, na mesma transação, muda o orçamento para `compra_realizada`.
5. O comprador acompanha os estados permitidos `emitido → enviado → recebido` ou `cancelado`, informa previsão de entrega e nota fiscal e baixa o PDF do pedido. Uma emissão já existente não pode ser repetida.
6. Os relatórios em `/empresarial/relatorios` exibem limite, valor realizado, comprometido e disponível por departamento e centro de custo; **Exportar CSV** gera uma planilha separada por `;`.

Desative a funcionalidade removendo ou definindo `FEATURE_EMPRESARIAL_ENABLED=false`. As rotas e telas empresariais ficam indisponíveis; os dados já gravados não são apagados.

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
| **Gshield**       | `curl_cffi` + BeautifulSoup; fallback via Chrome quando não há produtos no HTML             | Busca em `https://www.gorilashield.com.br/buscar?q=<termo>`; só é consultada para acessórios e periféricos compatíveis com o catálogo. |
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
| `Usuario`       | Nome, e-mail, senha (hash), papel (`admin`, `usuario`, `aprovador`, `comprador`), estado ativo e departamento opcional. |
| `Fornecedor`    | Nome único, tipo (`online`/`manual`), site, contato e flag `ativo`.                      |
| `ProdutoBusca`  | Termo pesquisado e especificações extraídas.                                             |
| `Cotacao`       | Preço encontrado (scraping ou manual): produto, fornecedor, link, imagem, frete, prazo, forma de pagamento e origem. |
| `Orcamento`     | Número (`ORC-AAAAMMDDHHmmss-<sufixo>`), dono, unidade empresarial opcional, solicitante, status, observações, condições e validade. |
| `OrcamentoItem` | Item do carrinho: produto, quantidade e cotação escolhida.                               |
| `Aprovacao`     | Decisão (aprovado/reprovado), aprovador e comentário por orçamento. |
| `Departamento`, `CentroCusto` | Estrutura opcional de departamentos, limites por centro e vinculação de usuários/orçamentos. |
| `PedidoCompra`, `PedidoCompraItem` | Pedidos gerados por fornecedor a partir de orçamento aprovado, com valores congelados, entrega e nota fiscal. |
| `PrecoHistorico`, `Monitoramento`, `AlertaPreco` | Histórico de preço por anúncio, acompanhamento e alertas pessoais. |

As alterações de schema são aplicadas via Flask-Migrate, não por `create_all()` no banco local. Faça backup do arquivo SQLite antes de atualizar e, com o `.env` preenchido, execute na raiz:

```powershell
.\.venv\Scripts\python.exe -m flask --app orcatech.app:app db upgrade
.\.venv\Scripts\python.exe -m flask --app orcatech.app:app db check
```

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

### Abrir agora (instalação já configurada no Windows)

Se você já instalou as dependências, preencheu o `.env` e criou o usuário
administrador, abra o **PowerShell** e rode:

```powershell
Set-Location 'C:\Users\Suporte\Desktop\gerador_orcamento-1-main'
.\.venv\Scripts\python.exe -m flask --app orcatech.app:app db upgrade
.\.venv\Scripts\python.exe run.py
```

O comando `db upgrade` aplica migrations pendentes sem apagar os dados
existentes e pode ser executado novamente com segurança. Para uma instalação
já configurada, não repita `Copy-Item .env.example .env`: isso pode substituir
configurações locais. Mantenha a janela do PowerShell aberta e acesse
**http://127.0.0.1:5000** no navegador. Entre com o e-mail e a senha do
administrador criados anteriormente. Para encerrar, volte ao PowerShell e
pressione **Ctrl+C**.

O código integrado e não publicado precisa ser executado a partir desta pasta
do projeto; abrir outra cópia ou uma versão baixada do GitHub pode não incluir
as alterações locais ainda não enviadas.

Se a porta 5000 estiver ocupada, escolha outra porta na mesma janela:

```powershell
$env:PORT = '5001'
.\.venv\Scripts\python.exe run.py
```

Nesse caso, abra **http://127.0.0.1:5001**. Para voltar à porta padrão na mesma
janela do PowerShell, execute `Remove-Item Env:PORT -ErrorAction SilentlyContinue`.

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

#### 5. Configurar a chave secreta

Somente na primeira configuração, crie o arquivo `.env` a partir do modelo.
Se o `.env` já existir, não o substitua; mantenha a chave e as configurações
locais. Para gerar uma chave aleatória exclusiva para esta instalação:

```powershell
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Abra `.env`, substitua o valor de `SECRET_KEY` pela chave gerada e salve. Não compartilhe nem versione esse arquivo. O aplicativo se recusa a iniciar sem uma `SECRET_KEY`.

#### 6. Preparar o banco de dados

O projeto guarda o banco em `instance/orcatech.db`. Em uma instalação nova, aplique primeiro as migrations e depois crie o primeiro administrador:

```powershell
.\.venv\Scripts\python.exe -m flask --app orcatech.app:app db upgrade
.\.venv\Scripts\python.exe -m scripts.init_db
```

O script solicita nome, e-mail e senha do administrador. A senha precisa ter pelo menos 12 caracteres. Para um banco legado com dados, faça uma cópia de segurança antes de qualquer migração. Use `flask db stamp head` **somente** se confirmou que o schema existente corresponde integralmente à migration inicial; o comando apenas registra a versão, não cria nem altera tabelas.

Se o banco já existe e contém seus dados, não o recrie nem apague a pasta
`instance/`. Faça uma cópia do arquivo `instance/orcatech.db` antes da primeira
atualização e execute `db upgrade` para aplicar as novas migrations. Em seguida,
use `db check` para conferir se o schema e os modelos estão sincronizados. O
comando `scripts.init_db` só é necessário para criar o primeiro administrador;
se já houver um, ele não altera as contas existentes.

Se já existir um administrador, o script informa que não há nada a fazer. Não apague `instance/orcatech.db`: esse arquivo contém os fornecedores, cotações, orçamentos e usuários salvos.

Depois que o servidor iniciar, entre em `/login` com o e-mail e a senha do administrador. Use **Gerenciar usuários** para criar as outras contas; não compartilhe a conta administrativa.

`scripts.migrar_dados` é um comando opcional para importar cache e histórico de uma instalação antiga. Não o execute no uso normal; os dados atuais já ficam em `instance/`.

#### 7. Iniciar o servidor local

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

#### 8. Abrir o sistema no navegador

Abra o endereço correspondente à porta escolhida:

- Porta padrão: `http://127.0.0.1:5000`
- Porta alternativa `5001`: `http://127.0.0.1:5001`

Na tela inicial, digite o nome do produto, informe o solicitante se desejar e clique em **Buscar Preços**. A busca consulta as lojas em paralelo e pode levar alguns minutos, dependendo do Chrome, da internet e das respostas dos sites.

#### 9.1. Ativar os recursos empresariais (opcional)

As migrations das Fases 5 e 6 devem estar aplicadas antes de ativar a Fase 6.
Abra o `.env` e altere:

```dotenv
FEATURE_EMPRESARIAL_ENABLED=true
ALCADA_APROVACAO_LIMITE=10000.00
```

Salve o arquivo e reinicie o servidor. Entre com uma conta `admin`, abra
**Departamentos e centros de custo** e cadastre a estrutura. Depois, em
**Gerenciar usuários**, associe os aprovadores aos respectivos departamentos e
atribua o papel `comprador` a quem emitirá pedidos. O recurso continua
desativado quando `FEATURE_EMPRESARIAL_ENABLED=false`; alterar a variável não
apaga os departamentos nem os pedidos salvos.

Para usar os alertas da Fase 5, aplique as migrations e abra
**Alertas de preço** no menu. O coletor não inicia sozinho junto do servidor;
para conferir preços, execute em outra janela do PowerShell:

```powershell
Set-Location 'C:\Users\Suporte\Desktop\gerador_orcamento-1-main'
.\.venv\Scripts\python.exe -m scripts.verificar_precos
```

O comando termina depois da verificação; pode ser executado manualmente ou
agendado pelo Agendador de Tarefas do Windows. Ele respeita cache e intervalos
por loja e não força scraping quando a coleta não está permitida.

#### 10. Encerrar o servidor

Volte para a janela do PowerShell em que o servidor está rodando e pressione **Ctrl+C**. Os dados salvos em `instance/` permanecem no computador.

### macOS e Linux

Instale Python 3.10 ou superior e Google Chrome. A partir da pasta raiz do projeto, execute:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
flask --app orcatech.app:app db upgrade
python -m scripts.init_db  # somente na primeira instalação, para criar o admin
python run.py
```

Abra `http://127.0.0.1:5000`. Para usar outra porta, defina `PORT` antes de iniciar, por exemplo `PORT=5001 python run.py`. Encerre o servidor com **Ctrl+C**.

### Solução de problemas ao iniciar localmente

- **O VS Code/Pylance não encontra imports como `flask` ou `sqlalchemy`:** selecione o interpretador `.\.venv\Scripts\python.exe` em **Python: Select Interpreter**. O workspace já aponta para esse caminho por padrão; se o VS Code já tinha outro interpretador selecionado, escolha o ambiente manualmente e recarregue a janela.
- **“Address already in use” ou erro de porta ocupada:** feche o outro servidor ou escolha uma porta livre com `$env:PORT = '5001'` no PowerShell antes de iniciar.
- **O navegador mostra erro 500:** confira as mensagens na janela do servidor. Confirme que está iniciando `run.py` a partir da raiz correta do projeto.
- **`db upgrade` falha com `no such table: orcamento_itens`:** pare o servidor e não execute `stamp head`. Isso pode indicar que o banco está marcado como se a migration inicial tivesse sido aplicada, mas as tabelas não existem. Faça uma cópia do arquivo `instance/orcatech.db`; se ele tiver dados importantes, não o substitua e peça ajuda para recuperar o schema. Somente para instalação nova sem dados, preserve o banco com outro nome, deixe o Flask-Migrate criar um SQLite vazio com `db upgrade` e execute `python -m scripts.init_db` para criar o administrador.
- **O comando Python ou dependências falham:** confira se está na pasta certa e execute novamente `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.
- **Uma loja retorna poucos ou nenhum produto:** os sites podem bloquear temporariamente consultas automatizadas ou alterar suas páginas. Confira os logs do servidor e tente novamente mais tarde. As outras lojas podem continuar funcionando.
- **Chrome/ChromeDriver falha:** confirme que o Google Chrome está instalado e atualizado. O Chrome é necessário para os scrapers que usam Selenium.
- **Não encontra histórico, cache ou banco:** não mova nem apague `instance/`; o banco, o histórico, o cache e os PDFs do orçamento ficam nessa pasta.

### Validação local realizada

Em 30/09/2026, a execução foi conferida a partir da raiz do projeto no Windows,
usando o Python de `.venv`:

```powershell
.\.venv\Scripts\python.exe -c "import sys; print(sys.version)"
.\.venv\Scripts\python.exe -m flask --app orcatech.app:app db check
.\.venv\Scripts\python.exe -m pytest -q
$env:PORT = '5001'
.\.venv\Scripts\python.exe run.py
```

Com o servidor ativo, foram verificadas estas URLs:

| URL | Resultado |
| --- | --- |
| `http://127.0.0.1:5001/login` | HTTP 200; tela de login disponível |
| `http://127.0.0.1:5001/` | HTTP 302 para `/login?next=/`; redirecionamento esperado sem autenticação |
| `http://127.0.0.1:5001/favicon.ico` | HTTP 200; ícone servido corretamente |

#### Correção do erro `ERR_CONNECTION_REFUSED`

Depois da primeira validação, o processo do servidor foi encerrado. Ao tentar
abrir `http://127.0.0.1:5001/` novamente, o navegador exibiu
`ERR_CONNECTION_REFUSED` porque não havia nenhum processo escutando na porta
5001. Esse erro não indicava um problema na URL ou no navegador: era
necessário iniciar o Flask novamente.

O servidor foi reiniciado na raiz do projeto com:

```powershell
$env:PORT = '5001'
.\.venv\Scripts\python.exe run.py
```

O terminal confirmou:

```text
* Running on http://127.0.0.1:5001
```

Em seguida, a rota de login foi testada novamente e respondeu com **HTTP 200**:

```powershell
Invoke-WebRequest -Uri 'http://127.0.0.1:5001/login' -UseBasicParsing
```

Portanto, mantenha a janela do PowerShell aberta enquanto usar a aplicação.
Para iniciar novamente depois de reiniciar o computador, execute os mesmos
comandos a partir de
`C:\Users\Suporte\Desktop\gerador_orcamento-1-main`. Para encerrar o servidor,
use `Ctrl+C`; nesse caso, será necessário executar os comandos de inicialização
novamente antes de acessar o endereço no navegador.

A busca de preços não foi disparada nessa validação porque ela consulta sites
externos e pode iniciar processos do Chrome; para validá-la, faça login e
execute uma busca com acesso à internet.

#### Resultado e bloqueios encontrados no estado atual

- `db check` terminou com erro porque o autogenerate detectou operações de
  schema ainda não refletidas nas migrations, incluindo a tabela
  `controle_verificacao_lojas`, índices e estruturas de monitoramento. Não use
  `flask db stamp head` para contornar isso; crie ou aplique a migration
  correspondente depois de confirmar o schema e fazer backup de
  `instance/orcatech.db`.
- A suíte terminou com **111 testes aprovados e 12 falhos**. As falhas
  ocorreram nos testes de recursos empresariais, workflow de aprovação e
  compartilhamento porque os templates importam `_macros.html`, mas esse
  arquivo não está presente em `orcatech/templates/`. Enquanto ele não for
  restaurado ou os imports forem ajustados, as páginas autenticadas que usam o
  macro `brl` podem responder com erro 500.
- O servidor em si iniciou e as rotas públicas acima responderam
  corretamente. Esses resultados não substituem a correção dos bloqueios de
  migration e template antes de considerar a aplicação pronta para uso.

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
docker run --rm --env-file .env -v orcatech-data:/app/instance \
  --entrypoint flask orcatech --app orcatech.app:app db upgrade
docker run --rm -it --env-file .env -v orcatech-data:/app/instance \
  --entrypoint python orcatech -m scripts.init_db
docker run -p 5000:5000 --env-file .env -v orcatech-data:/app/instance orcatech
```

Crie e preencha o `.env` conforme a seção [Variáveis de ambiente](#variáveis-de-ambiente) antes de iniciar. O container usa `xvfb-run` para criar um display virtual (`:99`, 1920x1080) antes de iniciar `python run.py`. O volume mantém banco, histórico e PDFs entre execuções.

---

## Variáveis de ambiente

Lidas de um arquivo `.env` na raiz (via `python-dotenv`), carregado antes dos módulos de scraping. **Não versione o `.env`.**

| Variável             | Obrigatória | Descrição                                                                                                                             |
| -------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `SECRET_KEY`         | Sim          | Chave aleatória usada para assinar as sessões. O app falha ao iniciar se estiver ausente. Gere uma com `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `CHROME_BINARY_PATH` | Não         | Caminho completo do `chrome.exe`, quando o Chrome não está em um local padrão (comum em instalação só para o usuário, no Windows).   |
| `PORT`               | Não         | Porta local do servidor (padrão `5000`); também define a porta do container Docker.                                                   |
| `APP_ENV`            | Não         | Use `production` para ativar o atributo `Secure` do cookie de sessão (requer HTTPS).                                                   |
| `APP_BASE_URL`       | Não         | URL pública/base usada nos links compartilhados e nos alertas por e-mail; padrão local `http://127.0.0.1:5000`. |
| `FLASK_DEBUG`        | Não         | Desligado por padrão; use `1` somente em desenvolvimento local. Nunca habilite em produção.                                              |
| `RATELIMIT_STORAGE_URI` | Não      | Backend do limite de tentativas de login. Padrão local `memory://`; em produção com múltiplos workers configure um Redis compartilhado. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_FROM` | Para e-mail | Configuração SMTP usada para envio assíncrono de PDFs e notificações. `SMTP_PASSWORD` deve ficar apenas no `.env`; nunca é registrada em logs. |
| `ORCAMENTO_VALIDADE_DIAS` | Não | Validade inicial e período usado ao renovar um orçamento, em dias inteiros; padrão `15`. |
| `ADMIN_PODE_AUTOAPROVAR` | Não | Permite que um administrador aprove o próprio orçamento; padrão `false`. Aceita `true`/`1` para ativar. |
| `LINK_COMPARTILHAMENTO_DIAS` | Não | Tempo de expiração de novos links públicos, em dias; padrão `7`. |
| `ORCAMENTO_MAX_EMAILS_HORA` | Não | Máximo de envios por orçamento em uma janela de uma hora; padrão `5`. |
| `MONITORAMENTOS_LIMITE_USUARIO` | Não | Máximo de monitoramentos ativos por usuário; padrão `50`. |
| `MONITORAMENTO_JITTER_SEGUNDOS` | Não | Variação aleatória adicional entre consultas de lojas; padrão `300` segundos. Use `0` somente em testes. |
| `ALERTAS_PRECO_POR_EMAIL` | Não | Ativa e-mails assíncronos de queda de preço; padrão `false`. Requer as variáveis SMTP. |
| `FEATURE_EMPRESARIAL_ENABLED` | Não | Ativa departamentos, centros de custo, alçadas e pedidos de compra; padrão `false`. |
| `ALCADA_APROVACAO_LIMITE` | Não | Limite em reais para encaminhar a aprovação ao aprovador do departamento; valores superiores vão para administradores. Padrão `10000.00`. |

## Monitoramento de preços

Nos resultados da busca e nos itens do carrinho, use **Monitorar preço** para
salvar um produto, a loja, o preço de referência e um único gatilho: percentual
de queda ou valor em reais. Os monitoramentos e alertas são privados por
usuário. O painel `/monitoramentos` permite desativar um acompanhamento,
marcar notificações como lidas e consultar o gráfico com menor preço e média
diária dos últimos 90 dias.

O job não é iniciado automaticamente pelo servidor Flask. Para uma execução
manual, com o ambiente virtual e o `.env` configurados, rode na raiz do
projeto:

```powershell
.\.venv\Scripts\python.exe -m scripts.verificar_precos
```

No Windows, para automatizar:

1. Abra o **Agendador de Tarefas** e crie uma tarefa básica recorrente.
2. Em **Ação**, selecione **Iniciar um programa**.
3. Em **Programa/script**, informe o caminho completo de
   `.\.venv\Scripts\python.exe`.
4. Em **Adicionar argumentos**, informe `-m scripts.verificar_precos`.
5. Em **Iniciar em**, informe a pasta raiz do projeto (a mesma que contém
   `run.py`, `.env` e `scripts`).
6. Evite criar mais de uma tarefa para este job; o controle de execução impede
   sobreposição no mesmo processo e usa leases no banco para a consulta da
   loja.

O job reutiliza o cache de busca válido e nunca força atualização. Quando
precisa consultar uma loja, processa um grupo de monitores por loja e respeita
intervalos mínimos: 6 horas para Mercado Livre, KaBuM, Terabyte, Americanas,
iBytes e Gshield; 24 horas para Amazon; 12 horas para AliExpress. Há jitter
aleatório, trava compartilhada com buscas manuais, backoff exponencial e pausa
após bloqueios explícitos. Uma loja que não retorna resultados não é tratada
automaticamente como bloqueada. O comando pode ser agendado, por exemplo, a
cada 30 minutos: os limites por loja continuam sendo aplicados no servidor.

Os registros guardam no máximo um ponto por anúncio por dia. Uma atualização
no mesmo dia substitui o ponto daquele anúncio, sem criar duplicatas. Só
resultados já aprovados pelos filtros de relevância do comparador podem entrar
no histórico ou gerar alertas. Para receber também e-mails, configure SMTP e
defina `ALERTAS_PRECO_POR_EMAIL=true` no `.env`.

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
| `/monitoramentos` | GET | Monitoramentos e alertas do usuário logado, com gráficos de preço. |
| `/monitoramentos/criar` | POST | Cria um monitoramento com CSRF e limite por usuário. |
| `/monitoramentos/<id>/desativar` | POST | Desativa um monitoramento do próprio usuário. |
| `/monitoramentos/alertas/<id>/ler` | POST | Marca como lido um alerta do próprio usuário. |

### Autenticação e administração

| Rota       | Método | Descrição                                                        |
| ---------- | ------ | ---------------------------------------------------------------- |
| `/login`   | GET/POST | Autentica usuários ativos; redireciona apenas para destinos internos. |
| `/logout`  | POST   | Encerra a sessão (protegido por CSRF).                           |
| `/usuarios` | GET/POST | Admin lista e cria usuários com papéis `admin`, `aprovador` ou `usuario`. |
| `/usuarios/<id>/ativo` | POST | Admin ativa/desativa usuários sem poder desativar a própria conta ou o último admin ativo. |
| `/usuarios/<id>/perfil` | POST | Com a feature empresarial ligada, admin altera papel e departamento do usuário. |

### Carrinho e orçamento (`/orcamento`)

| Rota                              | Método | Descrição                                                  |
| --------------------------------- | ------ | ---------------------------------------------------------- |
| `/orcamento/adicionar`            | POST   | Adiciona um item (card de resultado) ao carrinho.          |
| `/orcamento/carrinho`             | GET    | Tela do carrinho.                                          |
| `/orcamento/item/<id>/quantidade` | POST   | Atualiza a quantidade (0 remove o item).                   |
| `/orcamento/item/<id>/remover`    | POST   | Remove o item.                                             |
| `/orcamento/finalizar`            | POST   | Envia orçamento para aprovação e abre seus detalhes.       |
| `/orcamento/pdf/<id>`             | GET    | Baixa o PDF de um orçamento finalizado.                    |
| `/orcamento/<id>`                 | GET    | Exibe itens, totais, condições comerciais e trilha de auditoria. |
| `/orcamento/<id>/decisao`         | POST   | Registra aprovação ou reprovação (somente aprovador/admin; CSRF). |
| `/orcamento/<id>/reabrir`         | POST   | Reabre um orçamento reprovado (dono/admin; CSRF).           |
| `/orcamento/<id>/renovar-validade` | POST   | Renova orçamento expirado aguardando aprovação (dono/admin; CSRF). |
| `/orcamento/<id>/compra-realizada` | POST  | Registra compra realizada após aprovação (dono/admin; CSRF). |
| `/aprovacoes`                     | GET    | Fila paginada por data, número ou solicitante (aprovador/admin). |
| `/orcamento/<id>/compartilhar` | POST | Gera link público para orçamento finalizado (dono/admin; CSRF). |
| `/orcamento/<id>/compartilhar/regenerar` | POST | Troca o token e invalida o link anterior. |
| `/orcamento/<id>/compartilhar/revogar` | POST | Revoga o link público atual. |
| `/empresarial/estrutura` | GET/POST | Admin cadastra departamentos e centros de custo; editar limites e nomes. |
| `/empresarial/relatorios` | GET | Admin/comprador consulta gasto, comprometido e saldo por unidade. |
| `/empresarial/relatorios.csv` | GET | Exporta o relatório empresarial em CSV. |
| `/empresarial/orcamentos/<id>/pedidos` | GET/POST | Lista ou emite pedidos separados por fornecedor; emissão somente por comprador/admin. |
| `/empresarial/pedidos/<id>` | GET | Detalhe do pedido, acessível ao comprador/admin e ao dono do orçamento. |
| `/empresarial/pedidos/<id>/status` | POST | Atualiza estado, previsão de entrega e nota fiscal (comprador/admin; CSRF). |
| `/empresarial/pedidos/<id>/pdf` | GET | Baixa o PDF do pedido (comprador/admin ou dono do orçamento). |
| `/p/<token>` | GET | Página pública somente leitura, com token, expiração e limite por IP. |
| `/orcamento/<id>/email` | POST | Enfileira e registra envio de PDF por SMTP (dono/admin; CSRF). |

Ao atualizar uma instalação existente, aplique a nova migration antes de
iniciar o servidor:

```powershell
.\.venv\Scripts\python.exe -m flask --app orcatech.app:app db upgrade
```

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

## Executar os testes

Na raiz do projeto, instale as dependências de desenvolvimento uma vez:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

No macOS ou Linux, ative `.venv` e execute `python -m pip install -r requirements-dev.txt` e `python -m pytest -q`. Os testes usam um banco SQLite temporário e não dependem de credenciais reais.

Para executar somente as regressões do filtro sem acessar lojas:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_relevance_filter.py
```

---

## Limitações conhecidas

- Depende da **estrutura de HTML/JSON de terceiros**: mudanças nos sites podem quebrar um scraper específico. Cada loja falha de forma isolada, sem derrubar as demais.
- **Amazon**: pode devolver a página "Algo deu errado" (bloqueio leve de automação), principalmente após muitas buscas seguidas. Nesse caso, aguardar algumas horas costuma resolver. A tela informa quando houve bloqueio e oferece um link para abrir a busca diretamente na Amazon. Em falha, o scraper salva o HTML em `instance/debug/`.
- **Gshield**: usa o domínio `gorilashield.com.br` e o endpoint `/buscar?q=`. Buscas por notebooks, celulares, monitores, computadores e componentes como SSD pulam a loja; resultados de categorias mistas passam pelo filtro estrito de relevância. Diagnósticos dos itens rejeitados ficam em `instance/debug/filtro_relevancia.jsonl`.
- O filtro de relevância é ativado por padrão em todas as lojas; Americanas, Mercado Livre, AliExpress e Gshield também exigem correspondência estrita de categoria e termos.
- A economia dos relatórios é calculada somente quando há anúncios aprovados do mesmo modelo: mediana dos preços do modelo menos o menor preço. Buscas sem anúncios repetidos do mesmo modelo não inventam uma economia.
- Ao atualizar para esta fase, o cache antigo é apagado para forçar novas coletas. O histórico legado é recalculado com o cache disponível; a cópia anterior fica em `instance/debug/`.
- **Americanas**: às vezes devolve cards duplicados sem foto; o código tenta recuperar as imagens via `__NEXT_DATA__`.
- Lojas via Selenium exigem o **Chrome instalado** e são mais lentas. O semáforo (limite 2) pode alongar a busca em máquinas com pouca memória.
- O histórico de buscas em arquivo ainda é compartilhado entre contas. Os rascunhos, jobs de busca, itens e PDFs de orçamento são vinculados ao usuário.
- Os papéis `aprovador` e `admin` acessam a fila; administradores não podem autoaprovar por padrão. Configure explicitamente `ADMIN_PODE_AUTOAPROVAR=true` se a política local permitir.
- Em produção, configure `APP_ENV=production`, HTTPS, uma chave secreta própria e um backend Redis para limite de tentativas compartilhado entre workers.

---

## Roadmap

- [x] **Fase 00 — Relevância:** núcleo/categoria de busca, filtro contra acessórios sem relação, portão da Gshield, diagnósticos, limpeza de caches e recálculo seguro do histórico.
- [x] **Fase 1 — Login e papéis:** Flask-Login, papéis `admin`/`usuario`, isolamento de rascunhos e jobs, proteção de ownership, gestão de contas e limite de tentativas.
- [x] **Base da Fase 2 — Segurança:** SECRET_KEY obrigatória fora dos testes, CSRF em POST, cookies e cabeçalhos seguros, debug desligado por padrão, dependências e migrations.
- [x] **Fase 3 — Workflow de aprovação:** máquina de estados, fila, segregação, auditoria, snapshots, validade e PDF com dados de aprovação.
- [x] **Fase 4 — Compartilhamento:** link público revogável com expiração, WhatsApp, envio assíncrono de PDF e notificações SMTP.
- [x] **Fase 5 — Alerta de queda de preço:** histórico de preços, monitoramento e alertas sem exceder limites das lojas.
- [x] **Fase 6 — Recursos empresariais:** departamentos, centros de custo, alçadas, pedidos por fornecedor e relatórios exportáveis.
