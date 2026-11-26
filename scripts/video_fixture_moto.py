from base64 import b64encode
from hashlib import sha256

from moto.s3.exceptions import S3ClientError
from moto.s3.models import FakeMultipart
from moto.s3.responses import ActionResult, S3Response
from moto.server import main


set_part = FakeMultipart.set_part
serialize = S3Response.serialized
upload_part = S3Response.upload_part


def digest(body):
    return b64encode(sha256(body).digest()).decode("ascii")


def store_sha256(multipart, number, body):
    part = set_part(multipart, number, body)
    part.fixture_sha256 = digest(body)
    return part


def verify_sha256(response):
    checksum = response.headers.get("x-amz-checksum-sha256")
    if checksum and digest(response.body) != checksum:
        raise S3ClientError("BadDigest", "Checksum SHA-256 inválido na fixture.")
    status, headers, body = upload_part(response)
    if checksum and status == 200:
        headers["x-amz-checksum-sha256"] = checksum
    return status, headers, body


def serialize_list_parts(response, result, *args, **kwargs):
    if isinstance(result, ActionResult) and response.data.get("Action") == "ListParts":
        listing = result.result
        multipart = response.backend.get_bucket(listing["Bucket"]).multiparts[listing["UploadId"]]
        for part in listing["Parts"]:
            part["ChecksumSHA256"] = multipart.parts[part["PartNumber"]].fixture_sha256
    return serialize(response, result, *args, **kwargs)


if __name__ == "__main__":
    FakeMultipart.set_part = store_sha256
    S3Response.upload_part = verify_sha256
    S3Response.serialized = serialize_list_parts
    main(["--host", "0.0.0.0", "--port", "5000"])
