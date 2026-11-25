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

Para habilitar convites em um `.env` criado antes da F04, rode `python3 scripts/create_local_env.py --enable-invitations` e recrie a API com `docker compose up -d --build --wait service ui`. O script acrescenta dois segredos independentes ao arquivo privado e preserva as credenciais existentes. Arquivos novos já recebem as chaves. Preserve as chaves enquanto o volume contiver convites pendentes. Ambientes publicados precisam de sua própria configuração de chaves persistente.

A suíte de criação de eventos prepara duas contas sintéticas em um PostgreSQL descartável. Ela usa duas instâncias locais da API com credenciais de Development distintas e executa a interface em loopback. Execute `python3 -B event_stack.py --browser` no repositório [scrapbook-tests](../scrapbook-tests/README.md).

Para a validação automatizada com recursos descartáveis, use o [runner da fundação](../scrapbook-tests/README.md). [Spec local](../scrapbook-docs/F01-base-da-aplicacao-e-ambientes/spec.md)

## Origem do link dos convidados

No GitHub, `UI_ORIGIN` é a origem HTTPS da interface de cada ambiente e `API_ORIGIN` a origem HTTPS da API. O build do Amplify converte `UI_ORIGIN` em `VITE_PUBLIC_SITE_ORIGIN`, e a publicação confere a origem incorporada ao artefato. O endereço é somente a origem, sem caminho, query ou barra final. Na stack local, o link usa a origem loopback acessada, incluindo a porta.

Antes da tiragem do piloto, confira o domínio definitivo e a leitura de uma amostra impressa em Android e iPhone. [Escopo e critérios](../scrapbook-docs/F05-pagina-publica-qr-code-e-prazos/spec.md)

## Recepção de fotos da F08

O [template CloudFormation](config/media/photo-submissions.template.json) prepara um bucket S3 privado e versionado por ambiente, uma fila de provas de PUT e uma fila de falhas. As versões temporárias usam `submissions/temporary/` e as preservadas usam `submissions/original/`. A fila aceita publicação do bucket especificado na própria conta. A role da tarefa recebe acesso aos dois prefixos e pode excluir versões somente no prefixo temporário. A exclusão depende da reconciliação da aplicação, sem regra de expiração automática no bucket.

Informe `BucketName`, `NamePrefix`, `UiOrigins` e `RuntimeRoleName` ao preparar a stack. Use as origens HTTPS aprovadas da interface do ambiente em `UiOrigins`. A flag `EnablePhotoIngestion` é `false` por padrão. Ativá-la instala a notificação e as permissões operacionais da role da tarefa. A configuração publicada da API usa as saídas `MediaBucketName` e `ReceiptQueueUrl` em `PhotoSubmissions__Bucket` e `PhotoSubmissions__QueueUrl`, a região da stack em `PhotoSubmissions__Region` e as credenciais da tarefa. A UI usa a saída HTTPS `BrowserUploadOrigin` como origem exata permitida no build e na política de conteúdo. Habilitar `PhotoSubmissions__Enabled` depende do aceite do aviso vigente e da validação AWS em homologação descrita na [spec](../scrapbook-docs/F08-envio-e-confirmacao/spec.md).

Para assegurar o tratamento de falhas em homologação, conferir a origem do evento e a presença de `eventTime` e `versionId` após um PUT assinado, o acesso CORS pela origem aprovada, a preservação do original e a limpeza apenas da versão temporária elegível. A fila de falhas mantém evidências para diagnóstico. Planeje a reconciliação antes de um replay, pois a política da fila exige que a publicação venha do bucket configurado.

### Emulador descartável

Use o Docker e a AWS CLI local para iniciar uma instância em porta aleatória de loopback.

```sh
python3 -B scripts/photo_media_fixture.py start --ui-origin http://127.0.0.1:5173 --manual-events
```

A saída JSON traz `container`, `endpoint`, `bucket`, `queueUrl` e as variáveis `environment` para o serviço de teste em Development. Informe `--network` com a rede Docker descartável se a API rodar em contêiner. Use `endpoint` como origem permitida de upload na UI local. Remova a instância após o teste com `docker rm -f <container>`.

Para controlar prazos no laboratório, o runner faz um PUT no bucket versionado e publica o envelope sintético com o `VersionId` devolvido pelo PUT, a chave do objeto e o instante do cenário. O Moto encaminha uma notificação automática quando o filtro coincide, mas a versão fixada da imagem omite `versionId` dessa notificação. A verificação de autorização IAM, assinatura e entrega do envelope completo depende da AWS em homologação.
