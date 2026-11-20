# scrapbook-infrastructure

## Ambiente local

Manter `scrapbook-service`, `scrapbook-ui` e `scrapbook-liquibase` ao lado deste repositório. Usar Docker Compose, Python 3, Liquibase 4.33.0 com JDK e a base de banco de F01-STORY-001.

```sh
python3 scripts/create_local_env.py
docker compose up -d --wait postgres
python3 scripts/prepare_database.py
docker compose up -d --build --wait service ui
```

O primeiro comando cria `.env` privado com senhas locais hexadecimais. Ele preserva um arquivo que já exista. A preparação explícita verifica as ferramentas, executa o bootstrap administrativo, inicializa as senhas ausentes e valida as credenciais por TCP antes de chamar o Liquibase. A API conecta como `scrapbook_app`. As senhas já definidas acompanham o volume. Em caso de divergência, confira o `.env` original e o estado do banco antes de tentar novamente. O diagnóstico identifica a etapa recusada e o código de saída quando disponível.

| Acesso em loopback | Finalidade |
| --- | --- |
| `http://127.0.0.1:5173` | UI servida pelo Nginx com proxy para API e saúde. |
| `http://127.0.0.1:5080/health` | Vitalidade da API mesmo com PostgreSQL indisponível. |
| `http://127.0.0.1:5080/health/ready` | Prontidão da base e dos privilégios da aplicação. |
| `127.0.0.1:55432` | PostgreSQL para preparo e diagnóstico local. |

`docker compose down` encerra a stack e preserva os volumes. A prontidão retorna `503` enquanto o banco estiver indisponível ou incompleto. O processo da API continua disponível para diagnóstico. Use `docker compose logs service` para consultar a classificação sanitizada da falha. A identidade local permanece desabilitada até configuração explícita.

Para uso com contas sintéticas, configure `SCRAPBOOK_DEV_IDENTITY_ENABLED=true`, `SCRAPBOOK_DEV_ALLOW_CONTAINER_BINDING=true`, `SCRAPBOOK_DEV_ACCOUNT_ID` e `SCRAPBOOK_DEV_IDENTITY_TOKEN` no `.env` privado. A segunda opção autoriza a escuta interna exigida pelo proxy. A porta publicada no host usa loopback.

Para a validação automatizada com recursos descartáveis, use o [runner da fundação](../scrapbook-tests/README.md). [Spec local](../scrapbook-docs/F01-base-da-aplicacao-e-ambientes/spec.md)
