# SIGAB — Deploy e Homologação

Este documento cobre exclusivamente a infraestrutura online (Fase 3):
criar o banco, rodar as migrations, configurar variáveis de ambiente,
criar o primeiro administrador, e subir a aplicação local ou em
homologação/produção. Para a arquitetura de módulos e convenções de
código, ver `README.md` e os demais documentos desta pasta.

Arquitetura de hospedagem: **Render** (aplicação) + **Neon** (PostgreSQL
gerenciado) — confirmado adequado em agosto/2026 via documentação oficial
(ver seção "Decisões" ao final).

---

## 1. Ambientes

O SIGAB reconhece três valores para `AMBIENTE`, cada um com um
comportamento diferente e não configurável por fora:

| | `local` | `homologacao` | `producao` |
|---|---|---|---|
| Banco | SQLite (padrão automático) | **PostgreSQL obrigatório** | **PostgreSQL obrigatório** |
| SECRET_KEY | valor de desenvolvimento permitido | **própria, obrigatória** | **própria, obrigatória** |
| Cookie de sessão | sem `Secure` (permite HTTP) | `Secure` (exige HTTPS) | `Secure` (exige HTTPS) |
| Schema do banco | `create_all()` automático no boot | só via `alembic upgrade head` | só via `alembic upgrade head` |
| DEBUG (tracebacks) | conforme `DEBUG` no `.env` | sempre desligado, mesmo com `DEBUG=true` | sempre desligado, mesmo com `DEBUG=true` |

As duas primeiras linhas (banco e SECRET_KEY) **derrubam o boot** com um
erro claro se estiverem erradas fora de `local` — não é um aviso, a
aplicação recusa subir. Ver `app/core/config.py`,
`exigir_secret_key_segura()` e `exigir_banco_gerenciado_fora_de_local()`.

---

## 2. Como criar o banco PostgreSQL (Neon)

1. Criar uma conta em [neon.com](https://neon.com) (não exige cartão no
   plano gratuito).
2. Criar um projeto novo — cada ambiente (homologação, produção) deve ter
   seu **próprio** projeto/banco Neon, nunca compartilhar o mesmo banco
   entre os dois.
3. Neon fornece uma *connection string* pronta, já com
   `?sslmode=require` — copiar exatamente como fornecida, ela já é
   compatível com o driver usado pelo SIGAB (`psycopg` 3, via SQLAlchemy).
4. O formato esperado pelo SIGAB é `postgresql+psycopg://...` (o prefixo
   `+psycopg` depois de `postgresql` é obrigatório — é o que diz ao
   SQLAlchemy qual driver usar). Se o Neon fornecer só
   `postgresql://...`, adicione `+psycopg` manualmente.

Para testar localmente sem depender do Neon (o que este projeto fez
durante toda a Fase 3), um PostgreSQL local qualquer serve — só trocar a
`DATABASE_URL`.

---

## 3. Como executar o Alembic

Nunca use `create_all()` fora de `local` — schema em homologação/produção
é **só** Alembic.

```bash
# a partir da raiz do projeto, com DATABASE_URL apontando pro banco certo
export DATABASE_URL="postgresql+psycopg://usuario:senha@host/banco?sslmode=require"
alembic upgrade head
```

Comandos úteis:

```bash
alembic current   # revisão aplicada no banco agora
alembic heads     # deve sempre retornar exatamente UM head
alembic history   # histórico completo, mais antiga -> mais nova
```

Um banco PostgreSQL **vazio** chega ao schema completo só com
`alembic upgrade head` — sem nenhum `create_all()` — isso foi validado
na Fase 3 criando um banco novo do zero e confirmando as 9 tabelas
(`agenda`, `alembic_version`, `categorias`, `demandas`, `eleitores`,
`gabinetes`, `membros_gabinete`, `subcategorias`, `usuarios`).

Ao alterar um model, gerar a migration com:

```bash
alembic revision --autogenerate -m "descricao_curta"
```

Sempre revisar o arquivo gerado antes de commitar — o autogenerate é um
ponto de partida, não uma garantia.

---

## 4. Como configurar o `.env`

Copiar `.env.example` para `.env` (nunca committar o `.env` real — já
está no `.gitignore`) e preencher:

```bash
cp .env.example .env
```

Ver a tabela completa de variáveis na seção 6. Gerar uma SECRET_KEY
própria por ambiente (nunca reaproveitar entre homologação e produção):

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## 5. Como criar o primeiro ADMIN

Não existe usuário automático nem senha padrão em nenhum lugar do
código. O único jeito de criar o primeiro administrador é:

```bash
python scripts/criar_primeiro_admin.py
```

Modo interativo: o script pergunta nome do gabinete, nome do
administrador, e-mail e senha (a senha é digitada sem aparecer na tela).

Modo não interativo (deploy automatizado) — definir antes de chamar:

```bash
export SIGAB_BOOTSTRAP_GABINETE="Gabinete do Vereador Fulano"
export SIGAB_BOOTSTRAP_NOME="Fulano de Tal"
export SIGAB_BOOTSTRAP_EMAIL="fulano@exemplo.com"
export SIGAB_BOOTSTRAP_SENHA="uma-senha-forte-com-8-ou-mais-caracteres"
python scripts/criar_primeiro_admin.py
```

Requisitos garantidos pelo script (ver código-fonte para detalhes):

- senha sempre em Argon2id, nunca texto puro;
- **em homologação/produção, exige `DATABASE_URL` apontando para
  PostgreSQL** — recusa rodar contra um SQLite esquecido;
- roda `alembic upgrade head` **antes** deste script, sempre — o script
  não cria schema nenhum em PostgreSQL;
- idempotente: se o e-mail já existir, avisa e não cria nada duplicado;
- semeia automaticamente as categorias padrão do novo gabinete.

---

## 6. Variáveis de ambiente

| Variável | Obrigatória | `local` | `homologacao`/`producao` |
|---|---|---|---|
| `AMBIENTE` | não (padrão `local`) | `local` | `homologacao` ou `producao` |
| `DATABASE_URL` | **sim fora de local** | opcional (usa SQLite padrão) | PostgreSQL, com `?sslmode=require` |
| `SECRET_KEY` | **sim fora de local** | opcional | chave própria gerada (ver seção 4) |
| `DEBUG` | não | `true` (padrão) | ignorado na prática — nunca liga fora de local |
| `SESSAO_MAX_IDADE_HORAS` | não (padrão 12) | opcional | opcional |
| `CORS_ORIGINS` | não | vazio (nenhum CORS habilitado) | deixar vazio — o SIGAB não usa CORS |
| `LOG_LEVEL` | não (padrão INFO) | opcional | opcional |

Ver `.env.example` para o modelo comentado. Nenhuma variável desta tabela
tem valor real ali — todas são exemplos fictícios.

---

## 7. Como iniciar localmente

Sem nenhum `.env`, o SIGAB sobe com SQLite, exatamente como sempre
funcionou:

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Acessar `http://127.0.0.1:8000`.

---

## 8. Como iniciar em homologação/produção

### Opção A — Render via Blueprint (`render.yaml`)

O repositório já inclui um `render.yaml` na raiz, configurado para
homologação (tier gratuito, schema via Alembic no build, health check em
`/health`). No dashboard do Render: **New > Blueprint**, apontar para o
repositório, revisar as variáveis marcadas como `sync: false`
(`DATABASE_URL` — preencher com a connection string do Neon) e confirmar.

`SECRET_KEY` é gerada automaticamente pelo próprio Render
(`generateValue: true`) — não precisa (e não deve) ser digitada por
ninguém.

### Opção B — Manual (dashboard do Render, sem Blueprint)

- **Build Command**: `pip install -r requirements.txt && alembic upgrade head`
- **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Health Check Path**: `/health`
- Variáveis de ambiente: ver seção 6.

Em ambos os casos, depois do primeiro deploy bem-sucedido, criar o
primeiro admin via shell do Render (`SIGAB_BOOTSTRAP_*` como variáveis de
ambiente da sessão de shell, não do serviço) chamando
`python scripts/criar_primeiro_admin.py` — ver seção 5.

### Sobre o tier gratuito do Render

Um serviço web gratuito do Render hiberna após 15 minutos sem tráfego e
leva ~1 minuto para voltar na próxima requisição — aceitável para
homologação, **não recomendado para produção real** com uso diário pelo
gabinete (nesse caso, migrar para um plano pago, sem downtime). O mesmo
vale para o Neon: o compute do plano gratuito também escala a zero após
5 minutos ocioso; a aplicação já lida com isso corretamente
(`pool_pre_ping=True` detecta a conexão morta e reconecta, acordando o
banco de forma transparente).

---

## 9. Como fazer rollback

**Código**: o deploy do Render está sempre atrelado a um commit. Reverter
= fazer deploy de um commit anterior (pelo dashboard, ou
`git revert`/`git reset` + push, conforme a política de git do time).

**Schema**: cada migration tem um `downgrade()` gerado, mas **essa fase
não exercitou nenhum downgrade real** — trate migrations como
avanço-only na prática. Se uma migration causar problema em produção, o
caminho mais seguro é:

1. Reverter o **código** (deploy do commit anterior) primeiro — a
   aplicação anterior costuma continuar funcionando sobre um schema mais
   novo (colunas novas nullable não quebram código antigo).
2. Só reverter o **schema** (`alembic downgrade -1`) se o passo 1 não for
   suficiente, e só depois de testar o downgrade localmente contra uma
   cópia do banco.
3. Para qualquer problema que envolva perda de dados, restaurar a partir
   do backup/point-in-time-restore do Neon é sempre mais seguro que
   downgrade de schema.

---

## 10. Como verificar a saúde da aplicação

```bash
curl https://<host>/health
```

- `200 {"status":"ok"}` — aplicação de pé e banco acessível.
- `503 {"status":"erro"}` — aplicação de pé, banco inacessível.
- Sem resposta — aplicação fora do ar (processo não subiu, ou está
  hibernando no tier gratuito — a primeira requisição some ~1 min antes
  de responder).

Nunca retorna `DATABASE_URL`, hostname, `SECRET_KEY` ou stack trace,
mesmo com o banco fora do ar — ver `main.py`.

Distinto de `/_heartbeat` (`POST`), que existe só para o launcher desktop
detectar abas de navegador fechadas e não verifica banco nenhum — não
usar `/_heartbeat` como health check de deploy.

---

## Decisões (Fase 3)

- **Render + Neon confirmados** em agosto/2026 via documentação oficial:
  Render segue com tier gratuito de 750h/mês (hiberna após 15 min
  ocioso, sem disco persistente) e planos pagos a partir de instâncias
  Starter; Neon com pricing 100% baseado em uso desde a reforma mais
  recente (sem piso mensal), tier gratuito com 100 CU-hora/projeto/mês e
  0,5 GB de armazenamento. Nenhuma mudança que invalide a escolha
  anterior.
- **PostgreSQL passou a ser obrigatório** (erro fatal no boot) fora de
  `local`, não mais apenas um aviso — decisão da Fase 3, simétrica à
  SECRET_KEY (já era obrigatória desde a Fase 1).
- **`alembic upgrade head` roda dentro do `buildCommand`**, não em
  `preDeployCommand` — esse campo do Render exige instância paga, e esta
  fase usa o tier gratuito para homologação. Como o comando é idempotente
  (não faz nada se o schema já está atualizado), rodá-lo a cada build é
  seguro.
- **Sem armazenamento externo (S3 etc.) nesta fase** — toda importação de
  CSV já era, desde antes da Fase 3, inteiramente em memória (nunca grava
  em disco), então não há nenhuma dependência de disco persistente para
  resolver.
