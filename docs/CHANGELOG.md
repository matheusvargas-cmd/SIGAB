# CHANGELOG

Todas as alterações relevantes do projeto SIGAB serão registradas neste documento.

---

# Versionamento

Formato utilizado:

```
MAJOR.MINOR.PATCH
```

Exemplo:

```
0.1.0
```

- MAJOR → Grandes mudanças de arquitetura.
- MINOR → Novos módulos ou funcionalidades.
- PATCH → Correções e pequenos ajustes.

---

# Release 0.1.0

## Status

Concluída

## Data

08/08/2026

## Alterações

- Estrutura inicial do projeto criada.
- Configuração do FastAPI.
- Configuração do SQLAlchemy.
- Banco SQLite.
- Estrutura modular definida.
- Layout inicial.
- Dashboard base.
- Organização de pastas.

---

# Release 0.1.1

## Status

Concluída

## Data

08/08/2026

## Alterações

- Correção da inicialização do projeto.
- Ajustes no carregamento de templates.
- Correções de rotas.
- Correções de importações.
- Estrutura estabilizada.

---

# Release 0.1.2

## Status

Concluída

## Data

08/08/2026

## Alterações

- Interface Bootstrap 5.
- Menu lateral.
- Dashboard inicial.
- CSS próprio.
- Estrutura visual definitiva da V1.

---

# Release 0.2.0

## Status

Concluída

## Data

08/08/2026

## Objetivo

Módulo de Eleitores.

### Funcionalidades

- Cadastro
- Pesquisa
- Listagem
- Edição
- Exclusão

### Alterações

- Model de Eleitor completo com os campos da release.
- CRUD de eleitores com pesquisa por nome, telefone, WhatsApp, cidade e bairro.
- Telas Bootstrap 5 para listagem, cadastro e edição.
- Bloqueio de exclusão para eleitores com demandas vinculadas.
- Estrutura visual de paginação preparada para evolução futura.
- MigrationService para compatibilidade do banco SQLite existente.

---

# Release 0.3.0

## Status

Planejada

## Objetivo

Módulo de Demandas.

### Funcionalidades

- Cadastro
- Alteração de Status
- Histórico por Eleitor
- Pesquisa

---

# Release 0.4.0

## Status

Planejada

## Objetivo

Dashboard completo.

### Indicadores

- Total de Eleitores
- Total de Demandas
- Demandas em andamento
- Demandas concluídas
- Agenda de hoje
- Aniversariantes

---

# Release 0.5.0

## Status

Concluída

## Data

09/08/2026

## Objetivo

Agenda.

### Funcionalidades

- Cadastro, listagem, edição, visualização e exclusão de compromissos
- Pesquisa por título, descrição, local, responsável, status e eleitor
- Paginação (20 por página) e ordenação cronológica (futuros primeiro, passados continuam acessíveis)
- Destaque visual para compromisso de hoje e compromissos já passados
- Status: Agendado, Confirmado, Realizado, Cancelado
- Vínculo opcional com Eleitor

### Alterações

- Model `Agenda` completado com `eleitor_id` (opcional), `responsavel`, `telefone_contato` e `status`.
- `AgendaService` criado seguindo o padrão de `EleitorService`/`DemandaService`.
- `MigrationService.atualizar_schema_agenda()` para compatibilidade com banco SQLite existente.
- Templates `agenda/lista.html`, `agenda/formulario.html` e `agenda/visualizar.html` usando a identidade visual Conecta360 já existente.

---

# Release 0.6.0

## Status

Planejada

## Objetivo

Importação do sistema Meu Mandato.

### Funcionalidades

- Importar Eleitores
- Importar Telefones
- Importar Endereços
- Importar Demandas (quando disponíveis)

---

# Histórico Futuro

Todas as novas versões deverão seguir o padrão:

## Release X.Y.Z

### Data

AAAA-MM-DD

### Alterações

- Item 1
- Item 2
- Item 3

### Correções

- Correção 1
- Correção 2

### Observações

Informações importantes da versão.

---

# Política de Versionamento

Cada release deverá:

- Compilar sem erros.
- Executar normalmente.
- Possuir commit próprio.
- Atualizar este arquivo antes da conclusão.

Nunca finalizar uma implementação sem registrar a alteração correspondente neste CHANGELOG.
