import argparse
import json
import os
import re
import secrets
import subprocess
import time
from urllib.parse import urlsplit
from urllib.request import urlopen


IMAGE = "ghcr.io/getmoto/motoserver@sha256:120b1589c6df7e35d2092935f6ff724486bb2c4189d0e36ce795baba1400ffd2"
REGION = "us-east-1"
TEMPORARY_PREFIX = "submissions/temporary/"
CORS_HEADERS = ["content-type", "x-amz-checksum-sha256", "x-amz-sdk-checksum-algorithm"]
CREDENTIALS = {
    "AWS_ACCESS_KEY_ID": "test",
    "AWS_SECRET_ACCESS_KEY": "test",
    "AWS_EC2_METADATA_DISABLED": "true",
}


def execute(*command, env=None):
    return subprocess.run(
        command, env=env, text=True, stdout=subprocess.PIPE, check=True, timeout=120,
    ).stdout.strip()


def aws(endpoint, service, operation, *arguments):
    cli_env = {
        "PATH": os.environ["PATH"],
        "AWS_CONFIG_FILE": os.devnull,
        "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
        **CREDENTIALS,
    }
    response = execute(
        "aws", "--endpoint-url", endpoint, "--region", REGION, "--output", "json",
        "--no-cli-pager", service, operation, *arguments, env=cli_env,
    )
    return json.loads(response) if response else {}


def wait_for_moto(endpoint):
    for _ in range(50):
        try:
            with urlopen(endpoint + "/moto-api/", timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("Moto descartável indisponível.")


def configure(endpoint, bucket, ui_origin, manual_events):
    def s3(operation, *arguments):
        return aws(endpoint, "s3api", operation, "--bucket", bucket, *arguments)

    s3("create-bucket")
    s3("put-bucket-versioning", "--versioning-configuration", "Status=Enabled")
    s3("put-public-access-block", "--public-access-block-configuration",
       "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true")
    s3("put-bucket-cors", "--cors-configuration", json.dumps({"CORSRules": [{
        "AllowedOrigins": [ui_origin], "AllowedMethods": ["PUT"], "AllowedHeaders": CORS_HEADERS,
        "ExposeHeaders": ["x-amz-version-id"],
    }]}))
    queue_url = aws(endpoint, "sqs", "create-queue", "--queue-name", "photo-receipts",
                    "--attributes", "VisibilityTimeout=120")["QueueUrl"]
    if not manual_events:
        attributes = aws(endpoint, "sqs", "get-queue-attributes", "--queue-url", queue_url,
                         "--attribute-names", "QueueArn")["Attributes"]
        notification = {
            "QueueArn": attributes["QueueArn"],
            "Events": ["s3:ObjectCreated:Put"],
            "Filter": {"Key": {"FilterRules": [{"Name": "prefix", "Value": TEMPORARY_PREFIX}]}},
        }
        s3("put-bucket-notification-configuration", "--notification-configuration",
           json.dumps({"QueueConfigurations": [notification]}))
    return urlsplit(queue_url).path


def start(ui_origin, network, manual_events):
    suffix = secrets.token_hex(8)
    container = f"scrapbook-f08-media-{suffix}"
    bucket = f"scrapbook-f08-media-{suffix}"
    options = ("--network", network) if network else ()
    execute(
        "docker", "run", "--rm", "-d", "--name", container, "--publish", "127.0.0.1::5000",
        "--env", "MOTO_DISABLE_GLOBAL_CORS=true", "--env", "S3_IGNORE_SUBDOMAIN_BUCKETNAME=true",
        *options, IMAGE,
    )
    try:
        binding = execute("docker", "port", container, "5000/tcp")
        if not re.fullmatch(r"127\.0\.0\.1:[0-9]+", binding):
            raise RuntimeError("Publicação inesperada do Moto.")
        endpoint = "http://" + binding
        wait_for_moto(endpoint)
        queue_path = configure(endpoint, bucket, ui_origin, manual_events)
        api_endpoint = f"http://{container}:5000" if network else endpoint
        return {
            "container": container,
            "endpoint": endpoint,
            "bucket": bucket,
            "queueUrl": endpoint + queue_path,
            "environment": {
                **CREDENTIALS,
                "PhotoSubmissions__Enabled": "true",
                "PhotoSubmissions__Region": REGION,
                "PhotoSubmissions__Bucket": bucket,
                "PhotoSubmissions__StorageServiceUrl": api_endpoint,
                "PhotoSubmissions__BrowserStorageServiceUrl": endpoint,
                "PhotoSubmissions__QueueServiceUrl": api_endpoint,
                "PhotoSubmissions__QueueUrl": api_endpoint + queue_path,
                "PhotoSubmissions__ForcePathStyle": "true",
            },
        }
    except (Exception, KeyboardInterrupt):
        execute("docker", "rm", "-f", container)
        raise


def main():
    parser = argparse.ArgumentParser(description="Prepara S3 e SQS descartáveis para as fotos da F08.")
    actions = parser.add_subparsers(dest="action", required=True)
    start_parser = actions.add_parser("start")
    start_parser.add_argument("--ui-origin", required=True)
    start_parser.add_argument("--network")
    start_parser.add_argument("--manual-events", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}", args.ui_origin):
        parser.error("informe a origem HTTP exata da UI em 127.0.0.1")
    print(json.dumps(start(args.ui_origin, args.network, args.manual_events)))


if __name__ == "__main__":
    main()
