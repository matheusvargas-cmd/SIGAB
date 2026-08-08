# SIGAB - REVIEW CHECKLIST

## Objetivo

Este documento define a revisão obrigatória antes da conclusão de qualquer implementação.

Nenhuma tarefa poderá ser considerada concluída sem que todos os itens abaixo tenham sido verificados.

---

# 1. Arquitetura

- [ ] Leu README.md
- [ ] Leu SIGAB_AI_RULES.md
- [ ] Leu SIGAB_CONTEXT.md
- [ ] Leu ROADMAP.md
- [ ] Leu CHANGELOG.md

- [ ] Respeitou toda a arquitetura existente.
- [ ] Não alterou a estrutura do projeto.
- [ ] Não criou arquivos desnecessários.
- [ ] Não criou novas tecnologias.

---

# 2. Estrutura

Verificar:

- [ ] Estrutura de pastas preservada.
- [ ] Nome dos arquivos segue padrão.
- [ ] Não existem arquivos duplicados.
- [ ] Não existem controllers duplicados.
- [ ] Não existem templates duplicados.

---

# 3. Models

Os Models devem conter apenas:

- definição das tabelas
- colunas
- relacionamentos

Verificar:

- [ ] Nenhuma regra de negócio.
- [ ] Nenhuma consulta SQL.
- [ ] Nenhuma lógica de aplicação.

---

# 4. Services

Verificar:

- [ ] Toda regra de negócio está em Services.
- [ ] Nenhuma regra ficou em Controllers.
- [ ] Nenhuma regra ficou em Models.
- [ ] Nenhuma regra ficou em database.py.

---

# 5. Controllers

Verificar:

- [ ] Apenas recebem requisições.
- [ ] Chamam Services.
- [ ] Renderizam templates.
- [ ] Redirecionam corretamente.

Não conter:

- SQL
- lógica de negócio
- validações complexas

---

# 6. Database

database.py deve conter apenas:

- engine
- SessionLocal
- Base
- get_db

Verificar:

- [ ] Sem migrations.
- [ ] Sem inspect().
- [ ] Sem ALTER TABLE.
- [ ] Sem regras de negócio.
- [ ] Sem código duplicado.

---

# 7. MigrationService

Caso exista evolução do banco:

Verificar:

- [ ] Utiliza MigrationService.
- [ ] Não altera database.py.

---

# 8. SQLAlchemy

Verificar:

- [ ] Models registrados corretamente.
- [ ] Relacionamentos válidos.
- [ ] Session utilizada corretamente.
- [ ] Nenhum commit desnecessário.

---

# 9. Código

Verificar:

- [ ] Sem imports duplicados.
- [ ] Sem imports não utilizados.
- [ ] Sem funções duplicadas.
- [ ] Sem variáveis não utilizadas.
- [ ] Sem código morto.
- [ ] Sem comentários desnecessários.

---

# 10. Templates

Verificar:

- [ ] Bootstrap 5.
- [ ] Layout consistente.
- [ ] Navegação funcionando.
- [ ] Links funcionando.
- [ ] Formulários funcionando.

Não utilizar:

- React
- Vue
- Angular
- AdminLTE
- Tailwind

---

# 11. CSS

Verificar:

- [ ] Utiliza style.css.
- [ ] Não criou CSS desnecessário.
- [ ] Interface consistente.

---

# 12. JavaScript

Verificar:

- [ ] Utilizado apenas quando necessário.
- [ ] Não existem scripts desnecessários.

---

# 13. CRUD

Todo CRUD deve possuir:

- [ ] Listagem
- [ ] Cadastro
- [ ] Edição
- [ ] Exclusão
- [ ] Pesquisa

---

# 14. Banco

Verificar:

- [ ] SQLite funcionando.
- [ ] Persistência validada.
- [ ] Dados gravando corretamente.

---

# 15. Navegação

Verificar:

- [ ] Menu funcionando.
- [ ] Rotas funcionando.
- [ ] Links funcionando.
- [ ] Botões funcionando.

---

# 16. Testes Manuais

Executar obrigatoriamente:

- [ ] uvicorn inicia sem erros.
- [ ] Dashboard abre.
- [ ] Menu lateral funciona.
- [ ] CRUD funciona.
- [ ] Templates renderizam corretamente.

---

# 17. Revisão Final

Antes de concluir:

- [ ] Revisou todos os arquivos alterados.
- [ ] Corrigiu automaticamente inconsistências.
- [ ] Projeto compila sem erros.
- [ ] Projeto executa sem erros.
- [ ] Não existem warnings relevantes.

---

# Relatório Final

Ao finalizar qualquer tarefa, informar obrigatoriamente:

## Arquivos Criados

Lista dos arquivos criados.

---

## Arquivos Modificados

Lista dos arquivos alterados.

---

## Funcionalidades Implementadas

Resumo das funcionalidades.

---

## Pendências

Informar o que não foi implementado.

---

## Melhorias Futuras

Listar apenas sugestões.

Não implementar funcionalidades fora do escopo sem autorização.

---

# Regra Geral

Nenhuma implementação poderá ser considerada concluída sem que todos os itens deste checklist tenham sido verificados.

Caso exista qualquer inconsistência, ela deverá ser corrigida antes da entrega.