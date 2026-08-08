# SIGAB - AI RULES

## Objetivo

Este documento define as regras obrigatórias que toda Inteligência Artificial (Codex, ChatGPT ou outra IA) deve seguir ao desenvolver o projeto SIGAB.

Estas regras têm prioridade sobre qualquer sugestão automática da IA.

Caso exista conflito entre uma sugestão e estas regras, as regras deste documento prevalecem.

---

# Filosofia do Projeto

O SIGAB é um sistema interno para Gabinetes de Vereadores.

O objetivo principal é:

- Simplicidade
- Estabilidade
- Organização
- Facilidade de manutenção
- Produtividade

Nunca implementar soluções complexas quando uma solução simples resolver o problema.

---

# Tecnologias Oficiais

Nunca alterar as tecnologias do projeto.

Obrigatório utilizar:

- Python
- FastAPI
- SQLAlchemy
- SQLite
- Jinja2
- Bootstrap 5

Não utilizar:

- Django
- Flask
- React
- Vue
- Angular
- Tailwind
- AdminLTE
- Alpine.js

---

# Estrutura do Projeto

Nunca alterar a estrutura abaixo sem autorização.

```
app/
    core/
    models/
    modules/
        dashboard/
        eleitores/
        demandas/
        agenda/
        auth/
    services/
    templates/
    static/

database/
docs/
uploads/
```

Não criar novas pastas desnecessariamente.

---

# Arquitetura

O projeto utiliza arquitetura em camadas.

## Models

Responsabilidade:

- tabelas
- colunas
- relacionamentos

Nunca conter:

- consultas
- regras
- validações
- SQL

---

## Services

Toda regra de negócio pertence aos Services.

Exemplos:

EleitorService

DemandaService

AgendaService

MigrationService

Nunca colocar regra de negócio em Controllers.

---

## Controllers

Responsáveis apenas por:

- receber requisições
- chamar Services
- renderizar templates
- redirecionar

Nunca colocar:

- SQL
- regras
- validações complexas

---

## Database

database.py deve conter apenas:

- engine
- SessionLocal
- Base
- get_db

Nunca adicionar:

- migrations
- inspect()
- ALTER TABLE
- regras de negócio
- consultas SQL

---

## MigrationService

Caso seja necessária alteração na estrutura do banco:

Criar:

```
app/services/migration_service.py
```

Nunca alterar database.py para implementar migrações.

---

# Estrutura dos Módulos

Cada módulo deverá conter apenas:

```
controller.py

service.py

templates/
```

Não criar:

- routes.py
- handlers.py
- views.py
- api.py

Caso seja necessária uma nova rota, utilizar controller.py.

---

# Banco de Dados

Banco oficial:

SQLite

ORM oficial:

SQLAlchemy

Nunca trocar para PostgreSQL, MySQL ou outro banco.

---

# Interface

Utilizar:

Bootstrap 5

Jinja2

HTML

CSS

Não utilizar frameworks JavaScript.

---

# CSS

Utilizar preferencialmente:

```
app/static/css/style.css
```

Não criar múltiplos arquivos CSS sem necessidade.

---

# JavaScript

Evitar JavaScript.

Utilizar somente quando realmente necessário.

Priorizar HTML + Bootstrap.

---

# Imports

Utilizar somente imports absolutos.

Exemplo:

```python
from app.services.eleitor_service import EleitorService
```

Nunca utilizar caminhos relativos.

---

# Nomenclatura

Classes:

PascalCase

Funções:

snake_case

Arquivos:

snake_case

Constantes:

MAIÚSCULAS

---

# CRUD

Todo módulo deverá possuir:

- Listagem
- Cadastro
- Pesquisa
- Edição
- Exclusão

Sempre manter o mesmo padrão visual.

---

# Dashboard

Dashboard apenas apresenta informações.

Nunca colocar regras de negócio.

---

# Demandas

Toda Demanda pertence obrigatoriamente a um Eleitor.

Nunca permitir Demanda sem Eleitor.

---

# Importação

A importação do MeuMandato deverá possuir Service próprio.

Nunca misturar lógica de importação com Controllers.

---

# Código

Antes de finalizar qualquer implementação verificar:

- sem imports duplicados
- sem funções duplicadas
- sem variáveis não utilizadas
- sem código morto
- sem comentários desnecessários

---

# Logs

Utilizar logging.

Nunca utilizar print().

---

# Performance

Evitar consultas desnecessárias.

Utilizar SQLAlchemy corretamente.

Priorizar simplicidade.

---

# Escopo da V1

Implementar apenas:

- Dashboard
- Eleitores
- Demandas
- Agenda
- Importação do MeuMandato

Qualquer funcionalidade fora deste escopo deverá ser autorizada.

---

# Escopo Proibido na V1

Não implementar:

- Login
- Multiusuário
- Permissões
- API pública
- WhatsApp
- Ofícios
- Protocolos
- Relatórios avançados
- Integrações externas

---

# Qualidade

Todo código deve ser:

- simples
- organizado
- legível
- reutilizável
- fácil de manter

Nunca programar pensando apenas em "funcionar".

Programar pensando em manutenção futura.

---

# Revisão Obrigatória

Antes de concluir qualquer tarefa:

1. Ler SIGAB_REVIEW_CHECKLIST.md.

2. Revisar toda a implementação.

3. Corrigir automaticamente qualquer inconsistência.

4. Somente finalizar quando todos os itens do checklist estiverem atendidos.

---

# Permissões

A IA pode:

- Ler arquivos do projeto.
- Inspecionar o banco SQLite.
- Executar SELECT.
- Validar estrutura das tabelas.
- Ler o schema.
- Executar uvicorn.
- Instalar dependências do requirements.txt.

A IA NÃO pode, sem autorização explícita:

- Excluir arquivos.
- Excluir tabelas.
- Executar DROP TABLE.
- Executar DELETE em massa.
- Executar UPDATE em massa.
- Alterar o histórico Git.
- Executar git reset --hard.
- Executar comandos destrutivos.

---------

# Autorização Permanente

A IA possui autorização permanente para:

- Ler qualquer arquivo do projeto.
- Ler o banco SQLite.
- Inspecionar o schema.
- Executar consultas SELECT.
- Validar tabelas e colunas.
- Executar uvicorn para testes.
- Instalar dependências do requirements.txt.

Sempre que precisar apenas ler informações do projeto, execute diretamente sem solicitar confirmação.

Solicite confirmação apenas para ações destrutivas ou que alterem dados existentes.

------------

## Tratamento de Erros

Como o SIGAB é uma aplicação web baseada em HTML/Jinja2, o tratamento padrão de erros deve utilizar mensagens amigáveis (flash messages) e redirecionamentos.

Não utilizar HTTPException para regras de negócio ou fluxos esperados da aplicação.

HTTPException deve ser reservada para erros técnicos ou endpoints de API.

-------------

# Regra Final

Sempre preservar a arquitetura existente.

Sempre preferir soluções simples.

Sempre revisar o código antes da entrega.

Nunca modificar a arquitetura do SIGAB sem autorização explícita.