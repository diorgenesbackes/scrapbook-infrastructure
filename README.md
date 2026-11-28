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

## Recepção de fotos e vídeos da F08

O [template CloudFormation](config/media/photo-submissions.template.json) prepara um bucket S3 privado e versionado por ambiente, uma fila de provas de PUT e de conclusão de multipart e uma fila de falhas. Cada stack cria uma chave KMS própria com rotação automática. O bucket aplica SSE-KMS aos novos objetos por padrão, e a chave é retida junto com o bucket em caso de remoção ou substituição. As versões temporárias usam `submissions/temporary/` e as preservadas usam `submissions/original/`. A fila aceita publicação do bucket especificado na própria conta. A role da tarefa recebe acesso aos dois prefixos e pode excluir versões somente no prefixo temporário. A exclusão depende da reconciliação da aplicação, sem regra de expiração automática no bucket. O uso da chave pela role exige uma operação do S3 na região e o ARN de um objeto nesses prefixos. O S3 Bucket Key fica desabilitado para manter o contexto de criptografia por objeto.

Informe `BucketName`, `NamePrefix`, `UiOrigins` e `RuntimeRoleName` ao preparar a stack. Use as origens HTTPS aprovadas da interface do ambiente em `UiOrigins`. A flag `EnablePhotoIngestion` é `false` por padrão. Ativá-la instala a notificação e as permissões operacionais da role da tarefa. A configuração publicada da API usa as saídas `MediaBucketName` e `ReceiptQueueUrl` em `PhotoSubmissions__Bucket` e `PhotoSubmissions__QueueUrl`, a região da stack em `PhotoSubmissions__Region` e as credenciais da tarefa. A UI usa a saída HTTPS `BrowserUploadOrigin` como origem exata permitida no build e na política de conteúdo. Habilitar `PhotoSubmissions__Enabled` depende do aceite do aviso vigente e da validação AWS em homologação descrita na [spec](../scrapbook-docs/F08-envio-e-confirmacao/spec.md).

Para habilitar também vídeo em homologação após a validação da stack, aplique o changeset `f08-story-004-video-multipart` e configure `PhotoSubmissions__VideoEnabled=true` com `PhotoSubmissions__Enabled=true`. A imagem de serviço inclui `/usr/bin/ffprobe`. A tarefa precisa de um diretório temporário gravável com capacidade para um vídeo de até 500.000.000 bytes por réplica. O Compose limita o tmpfs da API a 3 GiB por réplica para compartilhar espaço com os trabalhadores de preparação de mídia. Para o ambiente publicado, confira o diretório temporário gravável da tarefa e o espaço efêmero disponível antes de habilitar o vídeo. O cliente solicita URLs por parte, e a API lista e conclui o multipart. A role pode listar partes e abortar uploads no prefixo temporário. A ação de listar multiparts abertos está limitada ao bucket desta stack e a API verifica a chave esperada. [Permissões do S3](https://docs.aws.amazon.com/service-authorization/latest/reference/list_s3.html)

Para assegurar o tratamento de falhas em homologação, conferir a origem do evento e a presença de `eventTime` e `versionId` após um PUT assinado e após `CompleteMultipartUpload`, o acesso CORS pela origem aprovada, o ARN da chave KMS do ambiente no temporário e no original preservado e a limpeza apenas da versão temporária elegível.

A fila de falhas mantém evidências para diagnóstico. Para habilitar o redrive nativo, informe em `RedriveOperatorRoleName` o nome exato de uma role operacional existente na conta, dedicada a uma única stack, com caminho IAM `/` e acesso separado da role da tarefa. O parâmetro fica vazio por padrão. A política operacional permite iniciar, consultar e cancelar o redrive na DLQ desta stack e restringe a movimentação e o envio às filas esperadas mesmo quando outras políticas dão acesso ao SQS. Na fila de provas, o S3 publica as notificações do bucket configurado e o SQS devolve mensagens em nome da role operacional. As duas filas usam criptografia gerenciada pelo SQS.

Antes de iniciar o redrive, diagnostique a causa e confirme que as versões temporárias ainda são elegíveis para reconciliação. Use `StartMessageMoveTask` na DLQ com a fila de provas de origem como destino e uma taxa compatível com o consumidor. Acompanhe a tarefa com `ListMessageMoveTasks` e registre o resultado da reconciliação. Valide em homologação o redrive de uma mensagem de teste gerada pelo S3 e a recusa de `SendMessage` direto pela role operacional com o redrive habilitado.

### Emulador descartável

Use o Docker e a AWS CLI local para iniciar uma instância em porta aleatória de loopback.

```sh
python3 -B scripts/photo_media_fixture.py start --ui-origin http://127.0.0.1:5173 --manual-events
```

A saída JSON traz `container`, `endpoint`, `bucket`, `queueUrl` e as variáveis `environment` para o serviço de teste em Development. Informe `--network` com a rede Docker descartável se a API rodar em contêiner. Use `--video` para habilitar o vídeo e o adaptador que acrescenta os checksums SHA-256 calculados aos resultados de `ListParts` do Moto. Use `endpoint` como origem permitida de upload na UI local. Remova a instância após o teste com `docker rm -f <container>`.

No Moto fixado, `ListObjectVersions` copia todas as versões antes de filtrar o prefixo e o registro interno retém essas cópias. O adaptador de `--video` fornece ao Moto cópias somente para leitura dos metadados dessa listagem, sem duplicar os bytes do objeto. A fixture mantém os originais no armazenamento versionado para leitura, verificação de checksum e `CopyObject`.

Para controlar prazos no laboratório, o runner publica um envelope sintético com a chave e o `VersionId` observado após PUT ou conclusão multipart e com o instante do cenário. O Moto encaminha uma notificação automática quando o filtro coincide, mas a versão fixada da imagem omite `versionId` dessa notificação. A verificação de autorização IAM, assinatura e entrega do envelope completo depende da AWS em homologação.

## Travamento após primeiro registro

O template da F09 define o tópico de eventos internos, a fila Standard de travamento e a DLQ dedicada. A assinatura filtra o atributo `type` para `event.first-record-confirmed.v1` e entrega o envelope JSON diretamente. As filas usam criptografia gerenciada pelo SQS. A role da aplicação publica no tópico e consome a fila própria, que aceita entregas do tópico configurado. [Template da F09](config/messaging/event-structural-lock.template.json) · [Assinaturas SNS](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-sns-subscription.html) · [Filas SQS](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-sqs-queue.html)

No ambiente publicado, informe `NamePrefix` e o nome da role da tarefa ECS em `RuntimeRoleName`. Use as saídas `EventsTopicArn` e `StructuralLockQueueUrl` para configurar `EventStructuralLock__TopicArn` e `EventStructuralLock__QueueUrl` na API, junto da região em `EventStructuralLock__Region`. Habilite `EventStructuralLock__Enabled` depois de conferir o tópico, a fila, os grants e os candidatos dependentes. A desativação suspende o fluxo e preserva o estado no banco e o trabalho pendente. [Spec da F09](../scrapbook-docs/F09-travamento-apos-primeiro-registro/spec.md)

Em `DlqInspectionRoleName`, informe o nome exato de uma role operacional existente, dedicada a essa stack na mesma conta e distinta da role de execução. A política autoriza `sqs:GetQueueAttributes` e `sqs:ReceiveMessage` sobre a DLQ da stack. Inspecione uma entrega pela saída `StructuralLockDeadLetterQueueUrl` com visibilidade zero para mantê-la disponível. O comando operacional da aplicação recupera o fato canônico validado pelo mesmo tópico SNS e preserva a entrega original na DLQ até a expiração. [Inspeção e redrive no SQS](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-configure-dead-letter-queue-redrive.html)

Os alarmes CloudWatch observam uma ou mais mensagens visíveis na DLQ em um minuto e idade de fila superior a 30 segundos em dois períodos de um minuto. Informe em `ServiceLogGroupName` o grupo CloudWatch Logs já usado pela tarefa ECS para habilitar o alarme de falha terminal. O filtro conta ocorrências de `event.structural_lock.failed` do serviço em um minuto, sem dimensões de evento, mensagem ou correlação. Informe em `AlarmTopicArn` um tópico SNS Standard de operação para notificar a transição para `ALARM`. Confira a política de publicação pelo CloudWatch, a assinatura e a notificação dos três alarmes em homologação. Os parâmetros de inspeção, grupo de logs e notificação são opcionais. [Métricas do SQS](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-available-cloudwatch-metrics.html) · [Notificações do CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Notify_Users_Alarm_Changes.html)

O helper `scripts/event_structural_lock_fixture.py` cria tópico, fila e DLQ isolados numa instância Moto em loopback. O runner de integração repassa `--endpoint` e `--container` do emulador descartável. Para ensaiar falhas mais rapidamente, pode informar `--visibility-timeout` de 1 a 30 segundos no emulador. O padrão é 30 segundos e a DLQ recebe a entrega após cinco recebimentos esgotados. O aceite publicado confere as permissões IAM, as métricas e as políticas na AWS.

## Preparação de mídias confirmadas

A primeira entrega da F10 admite os arquivos confirmados pela F08 em segundo plano e gera as duas versões JPEG privadas de cada foto. A configuração começa desabilitada. Antes de ativar, aplicar a geração Liquibase `f10-story-001-media-preparation` e atualizar a stack da F08 para disponibilizar a saída `MediaEncryptionKeyArn` e autorizar o contexto KMS dos derivados.

Use as saídas `MediaBucketName` e `MediaEncryptionKeyArn` da stack da F08, o nome de um tópico SNS Standard na mesma conta e região e a role de execução existente como parâmetros do [template da F10](config/media/media-processing.template.json). O tópico pode ser compartilhado com a F09. A assinatura da F10 filtra `record.media-confirmed.v1` pelo atributo `type` e tem fila e DLQ próprias. O runtime consome apenas sua fila e lê as versões dos originais. O acesso aos derivados abrange a verificação por versão e a escrita condicional com `If-None-Match: *`. [Escrita condicional no S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes-enforce.html)

Com F08 configurada, informe `MediaProcessing__Region`, `MediaProcessing__TopicArn` e `MediaProcessing__QueueUrl` com a região e as saídas `MediaEventsTopicArn` e `MediaConfirmationQueueUrl`. Os endpoints opcionais `MediaProcessing__SnsServiceUrl` e `MediaProcessing__SqsServiceUrl` servem ao emulador em desenvolvimento. Configure `MediaProcessing__Enabled=true` após validar o candidato e o escopo da role. Para pausar, desabilite a flag e preserve as filas, as tentativas e os objetos versionados para retomada. [Especificação da F10](../scrapbook-docs/F10-processamento-de-midias/spec.md)

## Conversão privada de áudio

A F10-STORY-002 seleciona os trabalhos de áudio confirmados e prepara uma saída M4A/AAC para reprodução. A configuração parte das stacks de mídia da F08 e de confirmação da F10. Atualize o contexto KMS do bucket com os prefixos de conversão antes de aplicar o [template de transcodificação](config/media/media-transcoding.template.json). Informe o bucket, a chave de mídia, a role da tarefa e o limite de jobs concorrentes de acordo com a quota do ambiente. [Fila MediaConvert](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-mediaconvert-queue.html)

O template concede à tarefa criação e listagem de jobs na fila configurada, leitura de estado no escopo da conta e região, e passagem somente da role de execução do MediaConvert. O serviço grava a entrada com escrita condicional sob `submissions/transcode-input/`. A role do MediaConvert lê esse prefixo e escreve somente em `submissions/transcode-output/`. A tarefa verifica a versão da saída antes de publicá-la no banco. [Permissões do MediaConvert](https://docs.aws.amazon.com/service-authorization/latest/reference/list_mediaconvert.html) · [Escrita condicional no S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes-enforce.html)

A regra EventBridge encaminha resultados terminais da fila do ambiente para o SQS. Falhas de entrega da regra e falhas de consumo têm DLQs próprias. A role da tarefa recebe e confirma somente na fila de resultado. [Política de destino do EventBridge](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-use-resource-based.html) · [DLQ de destino](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-rule-dlq.html)

Configure `MediaAudioProcessing__Region`, `MediaAudioProcessing__QueueArn`, `MediaAudioProcessing__JobRoleArn` e `MediaAudioProcessing__ResultQueueUrl` com a região e as saídas do template. A flag `MediaAudioProcessing__Enabled` começa desabilitada. Antes de ativar, use mídia sintética na homologação para confirmar a matriz F08, as saídas reais, a entrega dos eventos, KMS, versionamento e escopo de IAM. Em laboratório, os endpoints `MediaAudioProcessing__MediaConvertServiceUrl` e `MediaAudioProcessing__SqsServiceUrl` permitem validar o contrato com emuladores. Para pausar, desabilite a flag e preserve o estado dos trabalhos, das filas e dos objetos da tentativa.

Na configuração com vídeo F08 e áudio F10 simultâneos, cada réplica pode ocupar até 778.000.000 bytes com um vídeo e um áudio em inspeção e duas preparações de áudio. Garanta um diretório temporário gravável com pelo menos 1 GiB disponível por réplica no ambiente publicado.

## Conversão privada de vídeo

A F10-STORY-003 usa as mesmas filas, roles e prefixos da conversão de áudio. Habilite a admissão e a conversão de áudio conforme as seções anteriores. Para vídeo, configure também `PhotoSubmissions__VideoEnabled=true` e `MediaAudioProcessing__VideoEnabled=true`. A flag de processamento de vídeo começa desabilitada. Valide a matriz e os limites do MediaConvert em homologação antes de ativar. A role do MediaConvert lê somente as entradas privadas e a aplicação prepara arquivos ISO autocontidos antes de enviá-los ao provedor.

Com vídeo F10 habilitado, o orçamento por réplica soma dois estágios de até 1.012.000.000 bytes, um vídeo F08 de até 500.000.000 bytes e um áudio F08 de até 50.000.000 bytes. A verificação de uma saída ocupa uma das duas vagas do estágio. O Compose disponibiliza tmpfs gravável de 3 GiB. Garanta pelo menos 3 GiB livres no diretório temporário da tarefa publicada e confira o uso de memória e espaço com a carga representativa.

## Operação de recuperação de mídias

Aplique a geração Liquibase `f10-story-004-media-recovery` antes de executar o modo operacional e use um login exclusivo com a role `scrapbook_media_operator`. O processo `media-recover` começa desabilitado. O limite da varredura histórica é o instante UTC da primeira ativação da F10. Mantenha esse instante nas retomadas. [Procedimento e critérios](../scrapbook-docs/F10-processamento-de-midias/dev-back/f10-story-004.md)

Os parâmetros de IAM opcionais ficam vazios por padrão. Informe roles preexistentes na mesma conta e com caminho IAM `/`. Separe as roles por stack e ambiente. Cada role de redrive tem um `Deny` que restringe origem e destino ao par configurado. Compartilhar uma role nas duas stacks impede o redrive em ambas.

| Parâmetro | Escopo |
| --- | --- |
| `MediaConfirmationRedriveRoleName` no template de preparação | DLQ da confirmação para a fila de confirmação via SQS. |
| `TranscodeResultRedriveRoleName` no template de conversão | DLQ de consumo do resultado para a fila de resultado via SQS. A DLQ de entrega do EventBridge serve para diagnosticar falhas de entrega. |
| `MediaCleanupOperatorRoleName`, `MediaCleanupArtifactKey` e `MediaCleanupArtifactVersionId` no template de preparação | Listagem pela chave e exclusão da versão exata comprovada no bucket da F08. |

O responsável pelo provisionamento confere a elegibilidade do par e configura a política da sessão de limpeza. Use um par por execução e mantenha a alteração das políticas fora da role que executa o runner. Remova a autorização do par depois de registrar o resultado.

Em homologação, use a role de redrive correspondente e confirme que a mensagem canônica tem a proteção idempotente ativa antes de devolver a DLQ. Em seguida, confirme que `StartMessageMoveTask` preserva o `messageId` do envelope e recusa destinos diferentes da fila de origem. Confira também a recusa de `SendMessage` direto e a recusa de exclusão de outra chave ou versão pela role de limpeza. Use dados sintéticos e registre o resultado. [Redrive no SQS](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-configure-dead-letter-queue-redrive.html)

## Monitoramento da preparação de mídias

O [template de observabilidade F10](config/media/media-observability.template.json) lê o grupo Standard de logs JSON existente. Informe um `MonitoringName` exclusivo por ambiente, `ServiceLogGroupName` e os nomes das três filas de falhas existentes. Confirme o nome da fila de confirmação, de resultado e de entrega EventBridge e mantenha suas políticas e retenção próprias. `AlarmTopicArn` é opcional. As métricas do template não exigem publicação direta em CloudWatch pela role do runtime.

Use soma para contagens e acumulados dos intervalos de processamento e máximo para a maior latência e o estoque amostrado da Outbox. Use as métricas nativas por nome de fila para consumo, mensagens em trânsito e idade da fila. Os alarmes de DLQ observam ao menos uma mensagem visível em um minuto. Confira entrega SNS, configuração da fila, sinais ECS/RDS e coleta antes da ativação. [Procedimento de homologação](../scrapbook-docs/F10-processamento-de-midias/dev-infra/f10-story-005.md)
