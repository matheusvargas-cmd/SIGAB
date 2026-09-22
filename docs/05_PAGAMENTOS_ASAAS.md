# SIGAB — Integração de Pagamentos (Asaas)

Fase 2: transforma os botões "QUERO RENOVAR" da página `/assinatura` em
um Checkout real, hospedado pelo Asaas. Para o controle de validade em
si (trial, bloqueio por vencimento, `/assinatura`, controles do
Superadmin), ver `02_REGRAS.md` — este documento cobre só a integração
de pagamento em cima daquilo, sem repetir aquelas regras.

**Continua valendo, sem excepção:** `status_assinatura`, `plano`,
`assinatura_inicio` e `assinatura_vencimento` (em `Gabinete`) são a
única fonte de verdade sobre acesso. O Asaas só informa eventos
financeiros — quem decide liberar/renovar o gabinete é sempre o SIGAB,
nunca a tela de resultado do Checkout.

---

## 1. Variáveis de ambiente

| Variável | Obrigatória? | Descrição |
|---|---|---|
| `ASAAS_AMBIENTE` | não (padrão `sandbox`) | `sandbox` ou `producao` — só decide a URL padrão da API. |
| `ASAAS_API_URL` | não | Sobrescreve a URL da API, se necessário. |
| `ASAAS_API_KEY` | **sim**, para o checkout funcionar | Chave de API do Asaas — nunca tem valor padrão. |
| `ASAAS_WEBHOOK_TOKEN` | **sim**, para o webhook funcionar | Token comparado ao header `asaas-access-token` em todo evento recebido. |

Sem `ASAAS_API_KEY`/`ASAAS_WEBHOOK_TOKEN` configuradas, o checkout e o
webhook ficam **sempre indisponíveis** (mensagem amigável na página, 503
no webhook) — nunca existe um valor padrão/de exemplo em produção. Ver
`.env.example` para o modelo (sem nenhuma chave real).

Nenhuma dessas variáveis deve ser logada, commitada ou colocada em
teste versionado — os testes deste projeto (`tests/test_asaas.py`) usam
apenas valores claramente fictícios e nunca chamam a API real (o client
HTTP é sempre mockado).

---

## 2. Como gerar uma API Key de Sandbox

1. Criar (ou entrar em) uma conta em [asaas.com](https://www.asaas.com).
2. No painel, ativar o modo **Sandbox** (ambiente de testes — nenhum
   valor real é cobrado, nenhum saldo real é movido).
3. Em Configurações → Integrações → API, gerar uma **API Key de
   Sandbox**. Copiar o valor e definir como `ASAAS_API_KEY` no `.env`
   (nunca no código).
4. Em Configurações → Webhooks, cadastrar a URL pública deste ambiente
   terminando em `/webhooks/asaas` (ex.:
   `https://<seu-dominio-de-homologacao>/webhooks/asaas`) e definir um
   **Token de autenticação** — o Asaas exige um token forte (tokens
   curtos/previsíveis são rejeitados). Gerar um com:
   ```
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   Colar o mesmo valor em `ASAAS_WEBHOOK_TOKEN`.

---

## 3. Fluxo

1. O gabinete vencido acessa `/assinatura` e informa CPF/CNPJ (exigido
   pelo Asaas para identificar o pagador — o SIGAB nunca pede nem
   armazena dado de cartão).
2. `POST /assinatura/checkout` localiza/cria o cliente no Asaas
   (`AsaasService.obter_ou_criar_cliente`, buscado por
   `externalReference`, nunca duplicado) e cria um Checkout recorrente
   (`AsaasService.criar_checkout`, `chargeTypes=RECURRENT`), então
   redireciona o navegador para a URL hospedada pelo Asaas.
3. O pagador conclui o pagamento na tela do Asaas (cartão, Pix ou
   boleto). Isso **não** libera nada no SIGAB — só o Webhook confirma.
4. O Asaas chama `POST /webhooks/asaas` com o evento (`CHECKOUT_PAID`
   na primeira cobrança; `PAYMENT_CONFIRMED`/`PAYMENT_RECEIVED` nas
   cobranças seguintes da assinatura recorrente). O SIGAB:
   - valida o header `asaas-access-token`;
   - verifica se o `id` do evento já foi processado (idempotência —
     tabela `asaas_webhook_events`, `event_id` único); se já foi,
     responde 200 sem processar de novo;
   - localiza o gabinete pelo `externalReference`
     (`gabinete-<id>-<PLANO>`, gerado pelo próprio SIGAB, nunca aceito
     cru vindo de qualquer requisição do navegador);
   - renova (`AssinaturaService.aplicar_pagamento_confirmado`): se a
     assinatura já tinha vencido, o novo período conta a partir de
     hoje (`hoje_operacional()`, `America/Sao_Paulo`); se ainda estava
     válida, conta a partir do vencimento atual — nunca perde dias já
     pagos.
5. O pagador retorna para `/assinatura/sucesso`, `/cancelado` ou
   `/expirado` (conforme `successUrl`/`cancelUrl`/`expiredUrl`) — essas
   páginas só informam a situação; **nunca** liberam a assinatura por
   si só.

---

## 4. Como testar em Sandbox

1. Definir `ASAAS_AMBIENTE=sandbox`, `ASAAS_API_KEY` e
   `ASAAS_WEBHOOK_TOKEN` (passo 2 acima) no `.env` local ou de
   homologação.
2. Fazer login com um usuário de um gabinete com assinatura vencida
   (ou usar o Superadmin para forçar o vencimento de um gabinete de
   teste em `/superadmin/gabinetes/<id>/editar`).
3. Acessar `/assinatura`, preencher um CPF de teste do Sandbox (o Asaas
   documenta CPFs válidos para uso em Sandbox) e clicar em "QUERO
   RENOVAR".
4. Concluir o pagamento na tela do Asaas com um dos meios de teste do
   Sandbox (cartão de teste, Pix de teste).
5. Confirmar em `/superadmin/gabinetes` que o gabinete voltou a
   `ATIVO` com o vencimento correto, e em
   `SELECT * FROM asaas_webhook_events` que o evento foi gravado com
   `status = 'PROCESSADO'`.

Para testar só a lógica (sem depender de rede/Sandbox real), rodar:
```
DATABASE_URL=postgresql://usuario:senha@localhost/sigab_teste \
SECRET_KEY=qualquer-coisa-com-32-caracteres-ou-mais \
AMBIENTE=local \
python3 -m unittest tests.test_asaas -v
```

---

## 5. Trocar Sandbox → Produção

1. Gerar uma API Key de **produção** no painel do Asaas (fora do modo
   Sandbox) e um novo token de Webhook de produção — nunca reaproveitar
   os valores de Sandbox.
2. Cadastrar o Webhook de produção apontando para o domínio real,
   terminando em `/webhooks/asaas`.
3. No ambiente de produção, definir:
   ```
   ASAAS_AMBIENTE=producao
   ASAAS_API_KEY=<chave de produção>
   ASAAS_WEBHOOK_TOKEN=<token de produção>
   ```
   (`ASAAS_API_URL` pode continuar vazio — `producao` já aponta para
   `https://api.asaas.com/v3` automaticamente.)
4. Rodar `alembic upgrade head` no banco de produção antes do deploy
   (mesma regra de sempre — nunca `create_all()`/`ALTER TABLE`
   automático fora de `local`).

---

## 6. Limitações conhecidas desta primeira implementação

- O checkout cobre só os dois planos existentes (Mensal/Anual);
- Os eventos de webhook tratados são os necessários para o fluxo atual
  (`CHECKOUT_PAID`, `CHECKOUT_CANCELED`, `CHECKOUT_EXPIRED`,
  `SUBSCRIPTION_CREATED`, `PAYMENT_CONFIRMED`, `PAYMENT_RECEIVED`,
  `PAYMENT_OVERDUE`, `PAYMENT_DELETED`, `PAYMENT_REFUNDED`) — um evento
  fora dessa lista é apenas ignorado (200, sem ação), nunca causa erro;
- Um evento de webhook que falha durante o processamento (bug, banco
  indisponível etc.) é registrado com `status = 'ERRO'` e não é
  reprocessado automaticamente nem por uma nova entrega do mesmo
  `event_id` — precisa de intervenção manual (reenviar o evento pelo
  painel do Asaas, ou reprocessar manualmente a partir do registro em
  `asaas_webhook_events`);
- CPF/CNPJ é validado só por formato (11 ou 14 dígitos), sem checagem de
  dígito verificador — o Asaas faz a validação definitiva do lado dele;
- Este ambiente de desenvolvimento não tem acesso de rede ao Asaas
  (Sandbox ou produção); a integração foi validada com o client HTTP
  mockado (`tests/test_asaas.py`) e com uma chamada real (bloqueada pelo
  proxy de rede deste ambiente, retornando erro tratado normalmente) —
  o teste ponta a ponta contra o Sandbox real precisa ser feito pelo
  responsável, com uma API Key de Sandbox verdadeira.
