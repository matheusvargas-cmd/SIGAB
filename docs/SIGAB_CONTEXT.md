# SIGAB - CONTEXTO DO PROJETO

# Objetivo

O SIGAB (Sistema para Gestão de Gabinetes) é um sistema web desenvolvido para utilização em gabinetes de vereadores.

O objetivo é substituir planilhas e sistemas genéricos por uma aplicação simples, rápida e focada na rotina diária dos assessores parlamentares.

A prioridade do projeto NÃO é possuir dezenas de funcionalidades.

A prioridade é resolver muito bem os problemas do dia a dia do gabinete.

---

# Público-alvo

O sistema será utilizado por:

- Vereadores
- Assessores Parlamentares
- Chefes de Gabinete

Os usuários possuem pouco conhecimento técnico.

A interface deve ser extremamente simples.

---

# Fluxo principal do gabinete

O funcionamento do gabinete gira em torno de um cidadão.

O cidadão procura o gabinete.

O gabinete registra esse cidadão.

Após isso são abertas demandas relacionadas a esse cidadão.

Todo o restante do sistema existe para acompanhar essas demandas.

Portanto:

ELEITOR → DEMANDAS

Este é o núcleo do sistema.

---

# Conceito de Eleitor

No sistema, "Eleitor" representa qualquer cidadão atendido pelo gabinete.

Não significa necessariamente um eleitor cadastrado na Justiça Eleitoral.

Pode ser:

- cidadão
- morador
- comerciante
- líder comunitário
- representante de associação

Todo atendimento começa por um Eleitor.

---

# Conceito de Demanda

Uma demanda representa qualquer solicitação feita pelo cidadão.

Exemplos:

- troca de lâmpada
- operação tapa-buraco
- limpeza de lote
- poda de árvore
- pedido de consulta médica
- transporte
- vaga em escola
- manutenção de estrada
- fiscalização
- reunião
- visita

Toda demanda pertence obrigatoriamente a um Eleitor.

Nunca permitir demanda sem eleitor.

---

# Ciclo de vida de uma Demanda

Nova

↓

Em análise

↓

Encaminhada

↓

Em andamento

↓

Concluída

ou

Cancelada

Este fluxo deve ser respeitado em todo o sistema.

---

# Cadastro de Eleitor

Campos principais:

Nome

Telefone

WhatsApp

Data de nascimento

Endereço

Bairro

Cidade

Observações

Não adicionar dezenas de campos.

O cadastro deve ser rápido.

---

# Cadastro de Demanda

Campos mínimos:

Eleitor

Tipo

Descrição

Secretaria responsável

Status

Data de abertura

Observações

Sempre manter simplicidade.

---

# Dashboard

O Dashboard é apenas um resumo.

Não deve possuir regras de negócio.

Ele apresenta informações como:

Quantidade de Eleitores

Quantidade de Demandas

Demandas em andamento

Demandas concluídas

Aniversariantes do dia

Agenda de hoje

Últimos atendimentos

---

# Agenda

A agenda controla:

Compromissos

Reuniões

Visitas

Eventos

Lembretes

A agenda não substitui um calendário completo.

Ela serve apenas para organizar a rotina do gabinete.

---

# Pesquisa

A pesquisa é uma das funcionalidades mais utilizadas.

Sempre priorizar pesquisa rápida.

Pesquisar por:

Nome

Telefone

WhatsApp

Bairro

Cidade

A pesquisa deve exigir o menor número possível de cliques.

---

# Importação

O sistema deverá importar dados exportados do sistema MeuMandato.

A importação deve preservar:

Eleitores

Telefones

Endereços

Demandas (quando disponíveis)

Nunca apagar dados existentes sem confirmação.

---

# Filosofia do sistema

O SIGAB deve ser:

rápido

simples

leve

intuitivo

estável

Não criar funcionalidades complexas sem necessidade.

---

# Interface

A interface deve lembrar sistemas administrativos.

Layout limpo.

Poucas cores.

Poucos botões.

Poucas telas.

O usuário deve aprender o sistema em poucos minutos.

---

# Performance

O sistema será utilizado em computadores simples.

Priorizar desempenho.

Evitar consultas desnecessárias.

Evitar JavaScript excessivo.

---

# Evolução futura

O projeto poderá futuramente incluir:

- Usuários
- Permissões
- Protocolos
- Ofícios
- Documentos
- Relatórios
- Integração com WhatsApp
- Painel gerencial
- API

Essas funcionalidades NÃO fazem parte da primeira versão.

---

# Escopo da primeira versão

A primeira versão deve conter apenas:

Dashboard

Eleitores

Demandas

Agenda

Importação do MeuMandato

Nada além disso.

Somente após essas funcionalidades estarem concluídas novas funcionalidades poderão ser implementadas.

---

# Regra principal

Sempre que houver mais de uma forma de implementar uma funcionalidade, escolher a alternativa mais simples, mais legível e mais fácil de manter.

O SIGAB é um sistema de produtividade, não um laboratório de tecnologias.

Todo código produzido deve priorizar clareza, estabilidade e facilidade de manutenção.