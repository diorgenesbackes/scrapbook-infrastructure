from io import BytesIO
import json
import re
from threading import Lock
from urllib.parse import urlsplit


class LockAcknowledgmentFixture:
    def __init__(self, application):
        self.application = application
        self.exercise_lock = Lock()
        self.failed = False

    def __call__(self, environ, start_response):
        if environ.get("HTTP_X_AMZ_TARGET") == "AmazonSQS.DeleteMessage" and self.lock_queue_requested(environ):
            with self.exercise_lock:
                if not self.failed:
                    self.failed = True
                    print("F092_LOCK_ACK_DROPPED", flush=True)
                    start_response("503 Service Unavailable", [("Content-Type", "application/x-amz-json-1.0"),
                        ("x-amzn-errortype", "ServiceUnavailable")])
                    return [b'{"__type":"ServiceUnavailable","message":"Synthetic acknowledgment failure"}']
        return self.application(environ, start_response)

    @staticmethod
    def lock_queue_requested(environ):
        length = int(environ.get("CONTENT_LENGTH") or "0")
        body = environ["wsgi.input"].read(length)
        environ["wsgi.input"] = BytesIO(body)
        try:
            path = urlsplit(json.loads(body)["QueueUrl"]).path
            return re.fullmatch(r"/[0-9]{12}/scrapbook-f09-[0-9a-f]{16}-lock", path) is not None
        except (ValueError, KeyError, TypeError, AttributeError):
            return False


if __name__ == "__main__":
    from moto.moto_server.werkzeug_app import DomainDispatcherApplication, create_backend_app
    from werkzeug.serving import run_simple

    application = LockAcknowledgmentFixture(DomainDispatcherApplication(create_backend_app))
    run_simple("0.0.0.0", 5000, application, threaded=True)
