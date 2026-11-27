import json
from pathlib import Path
import unittest


CONFIG = Path(__file__).resolve().parents[1] / "config/media"
INPUT = {"Fn::Sub": "arn:${AWS::Partition}:s3:::${MediaBucketName}/submissions/transcode-input/*"}
OUTPUT = {"Fn::Sub": "arn:${AWS::Partition}:s3:::${MediaBucketName}/submissions/transcode-output/*"}
QUEUE = {"Fn::GetAtt": ["TranscodeQueue", "Arn"]}
RESULT = {"Fn::GetAtt": ["TranscodeResultQueue", "Arn"]}
DELIVERY_DLQ = {"Fn::GetAtt": ["TranscodeEventDeliveryDeadLetterQueue", "Arn"]}
RESULT_DLQ = {"Fn::GetAtt": ["TranscodeResultDeadLetterQueue", "Arn"]}


class MediaTranscodingTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = json.loads((CONFIG / "media-transcoding.template.json").read_text(encoding="utf-8"))
        cls.resources = cls.template["Resources"]
        runtime = cls.resources["TranscodeRuntimePolicy"]["Properties"]
        cls.runtime = {statement["Sid"]: statement for statement in runtime["PolicyDocument"]["Statement"]}
        cls.role = cls.resources["TranscodeExecutionRole"]["Properties"]
        statements = cls.role["Policies"][0]["PolicyDocument"]["Statement"]
        cls.provider = {statement["Sid"]: statement for statement in statements}

    def test_provider_trust_and_storage_are_scoped_to_staging_and_outputs(self):
        trust, = self.role["AssumeRolePolicyDocument"]["Statement"]
        self.assertEqual({"Service": "mediaconvert.amazonaws.com"}, trust["Principal"])
        self.assertEqual("sts:AssumeRole", trust["Action"])
        self.assertEqual("s3:GetObject", self.provider["ReadStagedInput"]["Action"])
        self.assertEqual(INPUT, self.provider["ReadStagedInput"]["Resource"])
        self.assertEqual(OUTPUT, self.provider["WriteTranscodeOutputs"]["Resource"])
        self.assertEqual(
            {"s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload", "s3:GetBucketLocation"},
            {action for rule in self.provider.values() for action in self.actions(rule) if action.startswith("s3:")},
        )
        self.assertEqual("s3:PutObject", self.runtime["WriteNewStagedInputs"]["Action"])
        self.assertEqual(INPUT, self.runtime["WriteNewStagedInputs"]["Resource"])
        self.assertEqual({"StringEquals": {"s3:if-none-match": "*"}}, self.runtime["WriteNewStagedInputs"]["Condition"])
        self.assertEqual([INPUT, OUTPUT], self.runtime["ReadStagingAndOutputVersions"]["Resource"])

    def test_kms_scopes_follow_bucket_encryption_context(self):
        photo = json.loads((CONFIG / "photo-submissions.template.json").read_text(encoding="utf-8"))
        key_statements = photo["Resources"]["MediaEncryptionKey"]["Properties"]["KeyPolicy"]["Statement"]
        delegation = next(statement for statement in key_statements if statement["Sid"] == "DelegateMediaEncryptionThroughS3")
        context = "kms:EncryptionContext:aws:s3:arn"
        scope = delegation["Condition"]["StringLike"][context]
        for path in ("transcode-input", "transcode-output"):
            self.assertIn({"Fn::Sub": "arn:${AWS::Partition}:s3:::${BucketName}/submissions/" + path + "/*"}, scope)
        for policies, write, prefix in (
            (self.provider, "EncryptPrivateOutputThroughS3", OUTPUT),
            (self.runtime, "EncryptStagedInputsThroughS3", INPUT),
        ):
            self.assertEqual({"Ref": "MediaEncryptionKeyArn"}, policies[write]["Resource"])
            self.assertEqual(prefix, policies[write]["Condition"]["StringLike"][context])
            self.assertEqual(
                [INPUT, OUTPUT], policies["DecryptPrivateMediaThroughS3"]["Condition"]["StringLike"][context]
            )

    def test_runtime_role_can_pass_only_transcode_role_and_use_only_queue(self):
        queue = self.resources["TranscodeQueue"]["Properties"]
        self.assertEqual("ON_DEMAND", queue["PricingPlan"])
        self.assertEqual({"Ref": "ConcurrentJobs"}, queue["ConcurrentJobs"])
        self.assertEqual(QUEUE, self.runtime["SubmitAndListOnlyThisQueue"]["Resource"])
        self.assertEqual(
            ["mediaconvert:CreateJob", "mediaconvert:ListJobs"], self.runtime["SubmitAndListOnlyThisQueue"]["Action"]
        )
        passed = self.runtime["PassOnlyTranscodeExecutionRole"]
        self.assertEqual({"Fn::GetAtt": ["TranscodeExecutionRole", "Arn"]}, passed["Resource"])
        self.assertEqual({"StringEquals": {"iam:PassedToService": "mediaconvert.amazonaws.com"}}, passed["Condition"])
        self.assertEqual({"sqs:ReceiveMessage", "sqs:DeleteMessage"}, set(self.runtime["ConsumeTranscodeResults"]["Action"]))
        self.assertEqual(RESULT, self.runtime["ConsumeTranscodeResults"]["Resource"])
        deny = self.runtime["DenyRuntimeDeadLetterAccess"]
        self.assertEqual(("Deny", "sqs:*", [RESULT_DLQ, DELIVERY_DLQ]), (deny["Effect"], deny["Action"], deny["Resource"]))

    def test_terminal_events_route_from_one_rule_to_two_distinct_failure_queues(self):
        rule = self.resources["TranscodeResultRule"]
        self.assertEqual("TranscodeResultQueuePolicy", rule["DependsOn"])
        props = rule["Properties"]
        pattern = props["EventPattern"]
        self.assertEqual(["aws.mediaconvert"], pattern["source"])
        self.assertEqual([{"Ref": "AWS::AccountId"}], pattern["account"])
        self.assertEqual([{"Ref": "AWS::Region"}], pattern["region"])
        self.assertEqual({"queue": [QUEUE], "status": ["COMPLETE", "ERROR", "CANCELED"]}, pattern["detail"])
        target, = props["Targets"]
        self.assertEqual(RESULT, target["Arn"])
        self.assertEqual({"Arn": DELIVERY_DLQ}, target["DeadLetterConfig"])
        queue = self.resources["TranscodeResultQueue"]["Properties"]
        self.assertEqual({"deadLetterTargetArn": RESULT_DLQ, "maxReceiveCount": 5}, queue["RedrivePolicy"])
        policy = self.resources["TranscodeResultQueuePolicy"]["Properties"]["PolicyDocument"]["Statement"]
        allow, direct, transport = policy
        self.assertEqual({"Service": "events.amazonaws.com"}, allow["Principal"])
        self.assertEqual([RESULT, DELIVERY_DLQ], allow["Resource"])
        self.assertEqual(allow["Condition"]["ArnEquals"], direct["Condition"]["ArnNotEquals"])
        self.assertEqual("Deny", direct["Effect"])
        self.assertEqual([RESULT, RESULT_DLQ, DELIVERY_DLQ], transport["Resource"])

    @staticmethod
    def actions(rule):
        value = rule["Action"]
        return [value] if isinstance(value, str) else value


if __name__ == "__main__":
    unittest.main()
