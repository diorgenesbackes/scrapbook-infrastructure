import json
from pathlib import Path
import unittest


CONFIG = Path(__file__).resolve().parents[1] / "config/media"


class MediaProcessingTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template = json.loads((CONFIG / "media-processing.template.json").read_text(encoding="utf-8"))
        cls.resources = template["Resources"]
        cls.runtime = cls.resources["MediaPreparationRuntimePolicy"]["Properties"]["PolicyDocument"]["Statement"]
        cls.topic = template["Outputs"]["MediaEventsTopicArn"]["Value"]

    def test_subscription_routes_only_confirmed_media_from_the_known_topic(self):
        subscription = self.resources["MediaConfirmationSubscription"]
        self.assertEqual("MediaConfirmationQueuePolicy", subscription["DependsOn"])
        properties = subscription["Properties"]
        self.assertEqual(self.topic, properties["TopicArn"])
        self.assertTrue(properties["RawMessageDelivery"])
        self.assertEqual("MessageAttributes", properties["FilterPolicyScope"])
        self.assertEqual({"type": ["record.media-confirmed.v1"]}, properties["FilterPolicy"])
        policy = self.resources["MediaConfirmationQueuePolicy"]["Properties"]["PolicyDocument"]["Statement"]
        allow, direct, operator, disabled, transport = policy
        self.assertEqual({"Service": "sns.amazonaws.com"}, allow["Principal"])
        self.assertEqual({"aws:SourceArn": self.topic}, allow["Condition"]["ArnEquals"])
        self.assertEqual({"aws:SourceAccount": {"Ref": "AWS::AccountId"}}, allow["Condition"]["StringEquals"])
        self.assertEqual({"aws:SourceArn": self.topic}, direct["Condition"]["ArnNotEquals"])
        self.assertEqual("Deny", direct["Effect"])
        self.assertEqual({"aws:CalledViaLast": "sqs.amazonaws.com"}, direct["Condition"]["StringNotEqualsIfExists"])
        self.assertEqual("MediaRedriveEnabled", operator["Fn::If"][0])
        self.assertIn("aws:PrincipalArn", operator["Fn::If"][1]["Condition"]["ArnNotEquals"])
        self.assertEqual({"aws:CalledViaLast": "sqs.amazonaws.com"}, disabled["Fn::If"][2]["Condition"]["StringEquals"])
        self.assertEqual("false", transport["Condition"]["Bool"]["aws:SecureTransport"])

    def test_encrypted_queues_have_one_way_redrive_and_runtime_exclusion(self):
        queue = self.resources["MediaConfirmationQueue"]["Properties"]
        dead_letter = self.resources["MediaConfirmationDeadLetterQueue"]["Properties"]
        dead_letter_arn = {"Fn::GetAtt": ["MediaConfirmationDeadLetterQueue", "Arn"]}
        self.assertTrue(queue["SqsManagedSseEnabled"])
        self.assertTrue(dead_letter["SqsManagedSseEnabled"])
        self.assertEqual(345600, queue["MessageRetentionPeriod"])
        self.assertEqual(1209600, dead_letter["MessageRetentionPeriod"])
        self.assertEqual({"deadLetterTargetArn": dead_letter_arn, "maxReceiveCount": 5}, queue["RedrivePolicy"])
        self.assertEqual("byQueue", dead_letter["RedriveAllowPolicy"]["redrivePermission"])
        self.assertEqual(1, len(dead_letter["RedriveAllowPolicy"]["sourceQueueArns"]))
        rule, = [statement for statement in self.runtime if statement["Resource"] == dead_letter_arn]
        self.assertEqual(("Deny", "sqs:*"), (rule["Effect"], rule["Action"]))

    def test_runtime_writes_only_new_derivatives_and_reads_exact_versions(self):
        original = {"Fn::Sub": "arn:${AWS::Partition}:s3:::${MediaBucketName}/submissions/original/*"}
        derived = {"Fn::Sub": "arn:${AWS::Partition}:s3:::${MediaBucketName}/submissions/derived/*"}
        s3 = [statement for statement in self.runtime if str(statement["Action"]).startswith("s3:")]
        self.assertCountEqual(
            [("s3:GetObjectVersion", original), ("s3:GetObjectVersion", derived), ("s3:PutObject", derived)],
            [(statement["Action"], statement["Resource"]) for statement in s3],
        )
        write, = [statement for statement in s3 if statement["Action"] == "s3:PutObject"]
        self.assertEqual({"StringEquals": {"s3:if-none-match": "*"}}, write["Condition"])
        kms, = [statement for statement in self.runtime if statement["Sid"] == "UseMediaEncryptionThroughS3"]
        self.assertEqual({"Ref": "MediaEncryptionKeyArn"}, kms["Resource"])
        self.assertEqual([original, derived], kms["Condition"]["StringLike"]["kms:EncryptionContext:aws:s3:arn"])
        self.assertEqual(
            {"kms:ViaService": {"Fn::Sub": "s3.${AWS::Region}.${AWS::URLSuffix}"}},
            kms["Condition"]["StringEquals"],
        )

    def test_operational_roles_have_separate_constrained_permissions(self):
        redrive = self.resources["MediaRedriveOperatorPolicy"]
        self.assertEqual("MediaRedriveEnabled", redrive["Condition"])
        self.assertEqual([{"Ref": "MediaRedriveOperatorRoleName"}], redrive["Properties"]["Roles"])
        policy = {line["Sid"]: line for line in redrive["Properties"]["PolicyDocument"]["Statement"]}
        self.assertEqual({"Fn::GetAtt": ["MediaConfirmationDeadLetterQueue", "Arn"]},
            policy["DenyOtherRedriveSources"]["NotResource"])
        self.assertEqual({"Fn::GetAtt": ["MediaConfirmationQueue", "Arn"]},
            policy["DenyOtherRedriveDestinations"]["NotResource"])
        self.assertEqual({"aws:CalledViaLast": "sqs.amazonaws.com"},
            policy["ReturnMessagesThroughSqs"]["Condition"]["StringEquals"])

        cleanup = self.resources["MediaCleanupOperatorPolicy"]
        self.assertEqual("MediaCleanupEnabled", cleanup["Condition"])
        self.assertEqual([{"Ref": "MediaCleanupOperatorRoleName"}], cleanup["Properties"]["Roles"])
        policy = {line["Sid"]: line for line in cleanup["Properties"]["PolicyDocument"]["Statement"]}
        paths = ["submissions/derived/*", "submissions/transcode-input/*", "submissions/transcode-output/*"]
        self.assertEqual(paths, policy["ListKnownArtifactVersions"]["Condition"]["StringLike"]["s3:prefix"])
        self.assertEqual("s3:DeleteObjectVersion", policy["DeleteOnlyArtifactVersions"]["Action"])
        resources = [{"Fn::Sub": "arn:${AWS::Partition}:s3:::${MediaBucketName}/" + path} for path in paths]
        self.assertEqual(resources, policy["DeleteOnlyArtifactVersions"]["Resource"])
        self.assertEqual(resources, policy["DenyDeletionOutsideArtifactPaths"]["NotResource"])
        self.assertEqual(("Deny", "s3:DeleteObject"), (policy["DenyUnversionedDeletion"]["Effect"],
            policy["DenyUnversionedDeletion"]["Action"]))

    def test_photo_stack_delegates_encryption_for_derived_paths(self):
        photo = json.loads((CONFIG / "photo-submissions.template.json").read_text(encoding="utf-8"))
        key_policy = photo["Resources"]["MediaEncryptionKey"]["Properties"]["KeyPolicy"]["Statement"]
        grant, = [statement for statement in key_policy if statement["Sid"] == "DelegateMediaEncryptionThroughS3"]
        context = grant["Condition"]["StringLike"]["kms:EncryptionContext:aws:s3:arn"]
        self.assertIn({"Fn::Sub": "arn:${AWS::Partition}:s3:::${BucketName}/submissions/derived/*"}, context)
        self.assertEqual(
            {"Fn::GetAtt": ["MediaEncryptionKey", "Arn"]}, photo["Outputs"]["MediaEncryptionKeyArn"]["Value"]
        )


if __name__ == "__main__":
    unittest.main()
