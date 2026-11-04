# 0106 — Feature `bsm.payment` (`external-reconciled`) e vínculo `--payment-id` em `bsm.account`

- **Data:** 2026-11-03
- **Status:** Aceita. Evolui as decisões `0082` (`bsm.account`), `0096` (modelo `external-reconciled`), `0100` (projeções assíncronas do Stream `DESIRED`) e `0105` (`cam.account` e `bsm`).
- **Origem:** Substituição do verificador local temporário (`SMARKEE_PAYMENT_METHODS_FILE` / `payment-methods.v1.schema.json`) por um recurso real de métodos de pagamento reconciliado com gateways externos (começando pelo Mercado Pago), preservando estritamente a conformidade PCI-DSS (`AGENTS.md` §4).

## Contexto

Para permitir a criação de Billing Accounts na modalidade paga (`--type paid`), a plataforma utilizava temporariamente um arquivo JSON local (`SMARKEE_PAYMENT_METHODS_FILE`) lido pela API de `bsm/account`. Para evoluir para um modelo de produção seguro, auditável e aderente ao loop de controle da plataforma:

1. **Segurança (PCI-DSS / `AGENTS.md` §4.1):** números de cartão (PAN) e códigos de segurança (CVV) nunca devem transitar pela API da Smarkee, pelo banco `ssot` nem pelos streams do NATS. O cliente deve tokenizar o cartão diretamente na borda (SDK do gateway) e enviar apenas um nonce descartável (`providerToken` / `--card-nonce`).
2. **Direção do vínculo e ausência de ciclo (*chicken-and-egg*):** uma Billing Account `paid` exige um método de pagamento válido antes de existir. Portanto, o método de pagamento (`bsm.payment`) pertence à Customer Account (`customerAccountId`, `cam.account`) e é referenciado pela Billing Account (`bsm.account`) por meio de `paymentId` (`--payment-id`), permitindo que múltiplos cartões coexistam na conta do cliente e sejam trocados (`sk bsm account update --payment-id`) sem recriar a Billing Account.
3. **Extensibilidade de provedores:** a arquitetura do Controller deve isolar o protocolo de gateway de pagamento em `controller/drivers/` para suportar inicialmente o **Mercado Pago** (Customers & Cards API v1) e permitir a adição futura de outros provedores (como Stripe, Adyen ou Pagar.me) sem alterar o domínio nem o motor de reconciliação.

## Decisão

1. **Nova feature `bsm/payment` (`external-reconciled`):**
   - **Papéis:** `api`, `publisher` e `controller` (`features/bsm/payment/`, pacote `bsm_payment`).
   - **Rota HTTP:** `/v1/bsm/payments` e `/v1/bsm/payments/{resourceId}`.
   - **Permissões e Roles:** `bsm.payment.{create,delete,get,list,update,operate}`, `bsm.paymentAdmin` e `bsm.paymentViewer` no projeto `roles-bsm`. A habilitação do serviço `bsm` em `sum/service` passa a conceder `bsm.payment.{create,delete,get,list,update}` juntamente com `bsm.account.{create,delete,get,list,update}`.
   - **Proteção de dados sensíveis:** `providerToken` é aceito na escrita (`POST`/`PATCH`), usado pelo `controller` para registrar o cartão no cofre do gateway externo e omitido da view `PaymentDesiredView` (`schemas/bsm/payment/resource.v1.schema.json`), nunca sendo devolvido pela API ou exibido na CLI. O estado `observed` armazena apenas metadados não sensíveis (`provider`, `methodType`, `status`, `brand`, `lastFourDigits`, `expirationMonth`, `expirationYear`, `providerCustomerId`, `providerPaymentMethodId`).
   - **Arquitetura modular de drivers (`controller/drivers/`):** protocolo `PaymentGatewayDriver` (`base.py`), `DriverRegistry` (`registry.py`) e pacote concreto `mercadopago/` (`client.py`, `driver.py`), com suporte a modo simulado determinístico (`simulation_mode=True` em dev/CI offline) e chamadas HTTP reais para a API v1 do Mercado Pago (`https://api.mercadopago.com/v1/customers`).
2. **Vínculo explícito `paymentId` em `bsm/account` e projeções NATS JetStream (decisão `0100`):**
   - `bsm/account` substitui o verificador de arquivo local (`FilePaymentMethodVerifier`) pela projeção `PaymentProjection` (`desired.bsm.payment.>`), exigindo `paymentId` obrigatório quando `type == "paid"` (validando que o método pertence ao mesmo `customerAccountId` e está ativo) e proibindo `paymentId` quando `type == "free"`.
   - `bsm/payment` consome `desired.bsm.account.>` por meio de `BillingAccountUsageProjection` (`common/dependents.py`, compartilhada entre `api` e `controller`) e bloqueia a exclusão de um método de pagamento com `409 ResourcesAttached` enquanto qualquer `bsm.account` ativa o referenciar em `paymentId`.
3. **Fluxo em duas etapas na CLI `sk`:**
   - Etapa 1: `sk bsm payment create --customer-account <id> --display-name <nome> --card-nonce <nonce> [--wait]`.
   - Etapa 2: `sk bsm account create --type paid --customer-account <id> --payment-id <payment_id> --display-name <nome> --currency BRL --billing-contacts <email> [--wait]`.
