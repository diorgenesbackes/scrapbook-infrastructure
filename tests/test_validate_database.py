from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from validate_hlg_network import validate_database


class DatabaseInventoryTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            environment="production", vpc_id="vpc-prod", database_subnet_ids=["subnet-a", "subnet-b"],
            database_group_id="sg-prod",
        )
        self.database = {
            "Engine": "postgres", "DBInstanceStatus": "available", "PubliclyAccessible": False,
            "StorageEncrypted": True, "Endpoint": {"Port": 5432}, "MultiAZ": True,
            "BackupRetentionPeriod": 35, "LatestRestorableTime": "2026-11-21T12:00:00Z",
            "DBSubnetGroup": {"VpcId": "vpc-prod", "Subnets": [
                {"SubnetIdentifier": "subnet-a"}, {"SubnetIdentifier": "subnet-b"},
            ]},
            "VpcSecurityGroups": [{"VpcSecurityGroupId": "sg-prod"}],
        }

    def test_accepts_production_topology(self):
        self.assertEqual(validate_database(self.database, self.config), [])

    def test_rejects_violations_of_production_requirements(self):
        for field, value, error in (
            ("MultiAZ", False, "Multi-AZ"), ("BackupRetentionPeriod", 7, "35 dias"),
            ("LatestRestorableTime", None, "restauração"), ("PubliclyAccessible", True, "privado"),
            ("StorageEncrypted", False, "criptografado"), ("Engine", "mysql", "PostgreSQL"),
            ("DBInstanceStatus", "creating", "disponível"), ("Endpoint", {"Port": 3306}, "5432"),
            ("VpcSecurityGroups", [], "security group"),
            ("DBSubnetGroup", {"VpcId": "vpc-hlg", "Subnets": []}, "sub-redes"),
        ):
            with self.subTest(field=field):
                self.assertIn(error, " ".join(validate_database(self.database | {field: value}, self.config)))

    def test_accepts_homologation_defaults(self):
        self.config.environment = "hlg"
        single_zone = self.database | {"MultiAZ": False, "BackupRetentionPeriod": 7, "LatestRestorableTime": None}
        self.assertEqual(validate_database(single_zone, self.config), [])

    def test_rejects_absent_database(self):
        self.assertIn("não consta", validate_database({}, self.config)[0])
