import json
from pathlib import Path
import unittest

CONFIG = Path(__file__).resolve().parents[1] / "config/media"


class MediaObservabilityTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = json.loads((CONFIG / "media-observability.template.json").read_text(encoding="utf-8"))
        cls.resources = cls.template["Resources"]

    def test_processing_filters_use_only_fixed_dimensions_and_numeric_samples(self):
        namespace = self.template["Outputs"]["MediaMetricNamespace"]["Value"]
        expected = {
            "ProcessingSamples": ("sampleCount", ["$.stage", "$.mediaType", "$.outcome"]),
            "ProcessingDurationSumSeconds": ("durationSumSeconds", ["$.stage", "$.mediaType", "$.cohort"]),
            "ProcessingDurationSamples": ("durationSampleCount", ["$.stage", "$.mediaType", "$.cohort"]),
            "ReadyDurationSumSeconds": ("durationSumSeconds", ["$.mediaType", "$.cohort"]),
            "ReadyMaximumSeconds": ("durationMaximumSeconds", ["$.mediaType", "$.cohort"]),
            "ReadyWithinTarget": ("withinTargetCount", ["$.mediaType", "$.cohort"]),
            "ReadySamples": ("sampleCount", ["$.mediaType", "$.cohort"]),
        }

        for name, (field, dimensions) in expected.items():
            with self.subTest(name=name):
                resource = self.resources[name]
                self.assertEqual("AWS::Logs::MetricFilter", resource["Type"])
                props = resource["Properties"]
                self.assertEqual({"Ref": "ServiceLogGroupName"}, props["LogGroupName"])
                pattern = props["FilterPattern"]
                self.assertIn('$.serviceName = "scrapbook-backend"', pattern)
                self.assertIn('$.eventName = "media.processing.interval"', pattern)
                self.assertIn(f"$.{field} >= 0", pattern)
                if name.startswith("Ready"):
                    self.assertIn('$.stage = "ready"', pattern)
                    self.assertIn('$.outcome = "available"', pattern)
                if name.startswith("ProcessingDuration"):
                    self.assertIn('$.stage != "ready"', pattern)
                (metric,) = props["MetricTransformations"]
                self.assertEqual(namespace, metric["MetricNamespace"])
                self.assertEqual(f"$.{field}", metric["MetricValue"])
                self.assertEqual(dimensions, [item["Value"] for item in metric["Dimensions"]])
                self.assertNotIn("DefaultValue", metric)

    def test_outbox_snapshot_metrics_have_no_replica_dimension(self):
        for name, field in (
            ("OutboxPending", "pendingCount"), ("OutboxFailed", "failedCount"),
            ("OutboxOldestAgeSeconds", "oldestPendingAgeSeconds"),
        ):
            with self.subTest(name=name):
                props = self.resources[name]["Properties"]
                self.assertIn('$.eventName = "media.processing.outbox_sample"', props["FilterPattern"])
                (metric,) = props["MetricTransformations"]
                self.assertEqual(f"$.{field}", metric["MetricValue"])
                self.assertNotIn("Dimensions", metric)

    def test_durable_job_snapshots_are_grouped_by_media_type_and_cohort(self):
        for name, field in (
            ("JobsPending", "pendingCount"), ("JobsActive", "activeCount"),
            ("JobsReconciling", "reconcilingCount"), ("JobsOldestAgeSeconds", "oldestPendingAgeSeconds"),
        ):
            with self.subTest(name=name):
                props = self.resources[name]["Properties"]
                self.assertIn('$.eventName = "media.processing.jobs_sample"', props["FilterPattern"])
                (metric,) = props["MetricTransformations"]
                self.assertEqual(f"$.{field}", metric["MetricValue"])
                self.assertEqual(["$.mediaType", "$.cohort"], [item["Value"] for item in metric["Dimensions"]])

    def test_native_alarms_observe_existing_queue_backlogs_and_optional_notifications(self):
        expected = {
            "ConfirmationDlqVisible": "ConfirmationDlqName",
            "ResultDlqVisible": "ResultDlqName",
            "DeliveryDlqVisible": "DeliveryDlqName",
        }
        self.assertEqual("", self.template["Parameters"]["AlarmTopicArn"]["Default"])
        for name, queue in expected.items():
            with self.subTest(name=name):
                resource = self.resources[name]
                self.assertEqual("AWS::CloudWatch::Alarm", resource["Type"])
                props = resource["Properties"]
                self.assertEqual("AWS/SQS", props["Namespace"])
                self.assertEqual("ApproximateNumberOfMessagesVisible", props["MetricName"])
                self.assertEqual([{"Name": "QueueName", "Value": {"Ref": queue}}], props["Dimensions"])
                self.assertEqual(1, props["Threshold"])
                self.assertEqual("notBreaching", props["TreatMissingData"])
                self.assertEqual({"Fn::If": ["AlarmNotificationsEnabled",
                    [{"Ref": "AlarmTopicArn"}], {"Ref": "AWS::NoValue"}]}, props["AlarmActions"])
        self.assertEqual({"AWS::CloudWatch::Alarm", "AWS::Logs::MetricFilter"},
            {item["Type"] for item in self.resources.values()})


if __name__ == "__main__":
    unittest.main()
