import json
from pathlib import Path
import re
import unittest


TEMPLATE = Path(__file__).resolve().parents[1] / "config/messaging/event-structural-lock.template.json"


class EventStructuralLockTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        cls.resources = cls.template["Resources"]

    def test_operator_can_inspect_only_the_dead_letter_queue(self):
        operator_policy = self.resources["StructuralLockDlqInspectionPolicy"]
        runtime_policy = self.resources["StructuralLockRuntimePolicy"]["Properties"]
        queue_arn = {"Fn::GetAtt": ["StructuralLockDeadLetterQueue", "Arn"]}
        inspection_actions = ["sqs:GetQueueAttributes", "sqs:ReceiveMessage"]

        self.assertEqual("DlqInspectionEnabled", operator_policy["Condition"])
        self.assertEqual([{"Ref": "DlqInspectionRoleName"}], operator_policy["Properties"]["Roles"])
        self.assertEqual([{"Ref": "RuntimeRoleName"}], runtime_policy["Roles"])
        self.assertEqual(
            [
                {"Effect": "Allow", "Action": inspection_actions, "Resource": queue_arn},
                {"Effect": "Deny", "NotAction": inspection_actions, "Resource": queue_arn},
            ],
            operator_policy["Properties"]["PolicyDocument"]["Statement"],
        )
        self.assertNotIn(queue_arn, [item["Resource"] for item in runtime_policy["PolicyDocument"]["Statement"]])

    def test_queue_alarms_monitor_native_metrics_for_the_correct_queue(self):
        for resource, metric, queue in (
            ("StructuralLockDlqVisibleAlarm", "ApproximateNumberOfMessagesVisible", "StructuralLockDeadLetterQueue"),
            ("StructuralLockQueueAgeAlarm", "ApproximateAgeOfOldestMessage", "StructuralLockQueue"),
        ):
            with self.subTest(resource=resource):
                alarm = self.resources[resource]["Properties"]
                self.assertEqual("AWS/SQS", alarm["Namespace"])
                self.assertEqual(metric, alarm["MetricName"])
                self.assertEqual([{"Name": "QueueName", "Value": {"Fn::GetAtt": [queue, "QueueName"]}}], alarm["Dimensions"])
                self.assertNotIn("Condition", self.resources[resource])

    def test_terminal_alarm_uses_an_optional_counter_without_log_dimensions(self):
        metric = self.resources["StructuralLockTerminalFailureMetric"]
        alarm = self.resources["StructuralLockTerminalFailureAlarm"]
        transformation, = metric["Properties"]["MetricTransformations"]

        self.assertEqual("TerminalFailureMonitoringEnabled", metric["Condition"])
        self.assertEqual(metric["Condition"], alarm["Condition"])
        self.assertEqual({"Ref": "ServiceLogGroupName"}, metric["Properties"]["LogGroupName"])
        self.assertIn('"event.structural_lock.failed"', metric["Properties"]["FilterPattern"])
        self.assertEqual(transformation["MetricNamespace"], alarm["Properties"]["Namespace"])
        self.assertEqual(transformation["MetricName"], alarm["Properties"]["MetricName"])
        self.assertNotIn("Dimensions", transformation)
        self.assertNotIn("Dimensions", alarm["Properties"])

    def test_optional_targets_default_to_empty_and_validate_literal_names(self):
        for parameter, valid, invalid in (
            ("DlqInspectionRoleName", "scrapbook-hlg-structural-lock", "iam/scrapbook-hlg-structural-lock"),
            ("ServiceLogGroupName", "/ecs/scrapbook-hlg", "aws logs"),
            ("AlarmTopicArn", "arn:aws:sns:us-east-1:123456789012:operations", "https://example.test/topic"),
        ):
            with self.subTest(parameter=parameter):
                configuration = self.template["Parameters"][parameter]
                pattern = configuration["AllowedPattern"]
                self.assertEqual("", configuration["Default"])
                self.assertIsNotNone(re.fullmatch(pattern, ""))
                self.assertIsNotNone(re.fullmatch(pattern, valid))
                self.assertIsNone(re.fullmatch(pattern, invalid))


if __name__ == "__main__":
    unittest.main()
