# SIGAB

Sistema para Gestão de Gabinetes de Vereadores.

---

# Objetivo

O SIGAB foi desenvolvido para organizar o atendimento realizado pelos gabinetes parlamentares.

O sistema substitui planilhas e controles manuais por uma aplicação simples, rápida e fácil de utilizar.

A primeira versão possui foco exclusivamente na rotina diária do gabinete.

---

# Tecnologias

- Python 3.14
- FastAPI
- SQLAlchemy
- SQLite
- Jinja2
- Bootstrap 5

---

# Estrutura do Projeto

```
SIGAB/

│
├── app/
│   ├── core/
│   ├── models/
│   ├── modules/
│   │   ├── dashboard/
│   │   ├── eleitores/
│   │   ├── demandas/
│   │   ├── agenda/
│   │   └── auth/
│   │
│   ├── services/
│   ├── templates/
│   └── static/
│
├── database/
├── docs/
├── uploads/
│
├── main.py
├── requirements.txt
│
├── SIGAB_AI_RULES.md
├── SIGAB_CONTEXT.md
├── ROADMAP.md
├── CHANGELOG.md
└── README.md
```

---

# Como executar

Criar ambiente virtual

```bash
python -m venv .venv
```

Ativar

Windows

```bash
.venv\Scripts\activate
```

Linux

```bash
source .venv/bin/activate
```

---

Instalar dependências

```bash
pip install -r requirements.txt
```

---

Executar

```bash
uvicorn main:app --reload
```

---

Acessar

```
http://127.0.0.1:8000
```

---

# Banco de Dados

Banco utilizado

SQLite

Arquivo

```
database/sigab.db
```

---

# Organização

O projeto segue arquitetura modular.

Cada módulo possui:

```
controller.py

service.py

templates/
```

Não utilizar:

- routes.py
- views.py
- handlers.py

---

# Módulos

## Dashboard

Resumo das informações.

---

## Eleitores

Cadastro dos cidadãos.

É o principal módulo do sistema.

---

## Demandas

Solicitações realizadas pelos cidadãos.

Toda demanda pertence obrigatoriamente a um Eleitor.

---

## Agenda

Controle de compromissos.

---

# Documentação

Antes de iniciar qualquer desenvolvimento, consultar:

```
SIGAB_AI_RULES.md
SIGAB_CONTEXT.md
ROADMAP.md
```

Esses documentos definem toda a arquitetura do projeto.

---

# Convenções

Classes

```
PascalCase
```

Funções

```
snake_case
```

Arquivos

```
snake_case
```

---

# Commits

Exemplos

```
Release 0.1.1 - Fundação

Release 0.2.0 - Eleitores

Release 0.3.0 - Demandas

Release 0.4.0 - Dashboard
```

---

# Princípios

O SIGAB deve ser:

- simples
- rápido
- estável
- organizado
- fácil de manter

Evitar soluções complexas.

Priorizar produtividade.

---

# Escopo da Primeira Versão

A V1 contempla apenas:

- Dashboard
- Eleitores
- Demandas
- Agenda
- Importação do Meu Mandato

Qualquer funcionalidade fora deste escopo deverá ser aprovada antes da implementação.

---

# Licença

Projeto privado.

Desenvolvido para gestão de gabinetes parlamentares.