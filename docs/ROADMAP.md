# SIGAB - ROADMAP

## Objetivo

Este documento define a evolução oficial do projeto SIGAB.

Nenhum módulo deverá ser iniciado antes da conclusão do módulo anterior.

---

# RELEASE 0.1

## Fundação

Status: ✅ Concluído

- Estrutura inicial do projeto
- FastAPI
- SQLite
- SQLAlchemy
- Bootstrap 5
- Dashboard inicial
- Layout base

---

# RELEASE 0.2

## Cadastro de Eleitores

Status: ✅ Concluído

### Funcionalidades

- Cadastro
- Listagem
- Pesquisa
- Edição
- Exclusão

Campos

- Nome
- Telefone
- WhatsApp
- Nascimento
- Endereço
- Bairro
- Cidade
- Observações

Objetivo:

Permitir localizar rapidamente qualquer cidadão atendido pelo gabinete.

---

# RELEASE 0.3

## Demandas

Status: ⏳

Funcionalidades

- Nova demanda
- Alterar status
- Histórico por eleitor
- Pesquisa

Status possíveis

- Nova
- Em análise
- Encaminhada
- Em andamento
- Concluída
- Cancelada

Toda demanda pertence obrigatoriamente a um Eleitor.

---

# RELEASE 0.4

## Dashboard

Status: ⏳

Indicadores

- Total de Eleitores
- Demandas em andamento
- Demandas concluídas
- Aniversariantes
- Agenda de hoje

O Dashboard apenas apresenta informações.

Nunca conter regras de negócio.

---

# RELEASE 0.5

## Agenda

Status: ✅ Concluído

- Compromissos
- Visitas
- Reuniões
- Eventos
- Lembretes

---

# RELEASE 0.6

## Importação Meu Mandato

Status: ⏳

Importar

- Eleitores
- Telefones
- Endereços
- Demandas (quando disponíveis)

Nunca apagar dados existentes automaticamente.

---

# RELEASE 0.7

## Ajustes

Status: ⏳

- Melhorias visuais
- Otimizações
- Correções
- Relatórios básicos

---

# Fora do escopo da V1

Não desenvolver nesta fase:

- Multiusuário
- Permissões
- API pública
- WhatsApp
- Protocolo
- Ofícios
- Documentos
- Relatórios avançados
- Integrações externas

---

# Regra do projeto

Antes de iniciar qualquer nova implementação, verificar:

- SIGAB_AI_RULES.md
- SIGAB_CONTEXT.md
- ROADMAP.md

Caso exista conflito entre uma solicitação e estes documentos, solicitar confirmação antes de modificar a arquitetura do sistema.
