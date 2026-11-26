import argparse
import json
import re
import secrets
from urllib.parse import urlsplit

from photo_media_fixture import CREDENTIALS, REGION, aws


FIRST_CONFIRMATION = "event.first-record-confirmed.v1"


def configure(endpoint, container, visibility_timeout=30):
    if not re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}", endpoint):
        raise ValueError("Use o endpoint HTTP loopback do Moto descartável.")
    if not re.fullmatch(r"scrapbook-f08-media-[0-9a-f]{16}", container):
        raise ValueError("Informe o contêiner descartável de mídia no Docker.")
    if not 1 <= visibility_timeout <= 30:
        raise ValueError("Informe a visibilidade da fila entre 1 e 30 segundos.")

    name = "scrapbook-f09-" + secrets.token_hex(8)
    topic = aws(endpoint, "sns", "create-topic", "--name", name + "-events")["TopicArn"]
    dead_letter = aws(endpoint, "sqs", "create-queue", "--queue-name", name + "-dlq",
                      "--attributes", "MessageRetentionPeriod=1209600")["QueueUrl"]
    dead_letter_arn = queue_arn(endpoint, dead_letter)
    queue = aws(endpoint, "sqs", "create-queue", "--queue-name", name + "-lock", "--attributes", json.dumps({
        "MessageRetentionPeriod": "345600",
        "ReceiveMessageWaitTimeSeconds": "10",
        "VisibilityTimeout": str(visibility_timeout),
        "RedrivePolicy": json.dumps({"deadLetterTargetArn": dead_letter_arn, "maxReceiveCount": 5}),
    }))["QueueUrl"]
    arn = queue_arn(endpoint, queue)
    policy = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "sns.amazonaws.com"}, "Action": "sqs:SendMessage",
        "Resource": arn, "Condition": {"ArnEquals": {"aws:SourceArn": topic}},
    }]}
    aws(endpoint, "sqs", "set-queue-attributes", "--queue-url", queue,
        "--attributes", json.dumps({"Policy": json.dumps(policy)}))
    aws(endpoint, "sns", "subscribe", "--topic-arn", topic, "--protocol", "sqs", "--notification-endpoint", arn,
        "--attributes", json.dumps({
            "RawMessageDelivery": "true", "FilterPolicyScope": "MessageAttributes",
            "FilterPolicy": json.dumps({"type": [FIRST_CONFIRMATION]}),
        }))

    api_endpoint = f"http://{container}:5000"
    return {"topicArn": topic, "queueUrl": queue, "deadLetterQueueUrl": dead_letter, "environment": {
        **CREDENTIALS,
        "EventStructuralLock__Enabled": "true",
        "EventStructuralLock__Region": REGION,
        "EventStructuralLock__TopicArn": topic,
        "EventStructuralLock__QueueUrl": api_endpoint + urlsplit(queue).path,
        "EventStructuralLock__SnsServiceUrl": api_endpoint,
        "EventStructuralLock__SqsServiceUrl": api_endpoint,
    }}


def queue_arn(endpoint, queue):
    return aws(endpoint, "sqs", "get-queue-attributes", "--queue-url", queue,
               "--attribute-names", "QueueArn")["Attributes"]["QueueArn"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepara o transporte descartável da F09 no Moto local.")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--visibility-timeout", type=int, default=30, help="Visibilidade da fila de 1 a 30 segundos.")
    args = parser.parse_args()
    try:
        print(json.dumps(configure(args.endpoint, args.container, args.visibility_timeout)))
    except ValueError as error:
        parser.error(str(error))
