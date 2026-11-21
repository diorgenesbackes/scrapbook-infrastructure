import argparse
import json
from pathlib import Path
import sys


def read_inventory(directory, filename, key):
    try:
        with (directory / filename).open(encoding="utf-8") as source:
            entries = json.load(source)[key]
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            raise ValueError
        return entries
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError(f"Inventário ausente ou inválido em {filename}.") from None


def effective_route_table(subnet_id, tables):
    explicit = []
    main = []
    for table in tables:
        for association in table["Associations"]:
            matches_subnet = association.get("SubnetId") == subnet_id
            is_main = association.get("Main") is True
            if (matches_subnet or is_main) and (
                association.get("AssociationState", {}).get("State", "associated") != "associated"
            ):
                return None
            if matches_subnet:
                explicit.append(table)
            if is_main:
                main.append(table)
    candidates = explicit or main
    return candidates[0] if len(candidates) == 1 else None


def validate_network(inventory, args):
    errors = []
    public_ids = set(args.public_subnet_ids)
    database_ids = set(args.database_subnet_ids)
    if public_ids & database_ids:
        errors.append("As sub-redes públicas e de banco devem ser distintas.")
    for subnet_ids, label in ((public_ids, "públicas"), (database_ids, "de banco")):
        subnets = [
            subnet for subnet in inventory["subnets"].values()
            if subnet["SubnetId"] in subnet_ids
            and subnet["VpcId"] == args.vpc_id and subnet["State"] == "available"
        ]
        zones = {subnet["AvailabilityZone"] for subnet in subnets}
        if len(subnets) != len(subnet_ids) or len(zones) < 2:
            errors.append(f"As sub-redes {label} devem estar disponíveis na VPC em ao menos duas zonas.")

    vpc = inventory["vpcs"].get(args.vpc_id, {})
    if vpc.get("IsDefault") is not False or vpc.get("State") != "available":
        errors.append("A VPC informada deve ser dedicada e estar disponível.")
    tables = [table for table in inventory["routes"].values() if table["VpcId"] == args.vpc_id]
    if any(route.get("NatGatewayId") for table in tables for route in table["Routes"]):
        errors.append("A configuração inicial da VPC não deve ter rotas para NAT Gateway.")
    for subnet_id in sorted(public_ids | database_ids):
        table = effective_route_table(subnet_id, tables)
        if table is None:
            errors.append(f"Não foi possível identificar a tabela de rotas de {subnet_id}.")
            continue
        internet_routes = [route for route in table["Routes"] if route.get("GatewayId", "").startswith("igw-")]
        has_public_default = any(
            route.get("DestinationCidrBlock") == "0.0.0.0/0" and route.get("State") == "active"
            for route in internet_routes
        )
        if subnet_id in public_ids and not has_public_default:
            errors.append(f"A sub-rede pública {subnet_id} precisa de rota IPv4 ativa para Internet Gateway.")
        if subnet_id in database_ids:
            subnet = inventory["subnets"].get(subnet_id, {})
            if subnet.get("MapPublicIpOnLaunch") is not False or internet_routes or any(
                route.get("EgressOnlyInternetGatewayId") for route in table["Routes"]
            ):
                errors.append(f"A sub-rede de banco {subnet_id} deve ser privada.")
    return errors


def allows_only_group_sources(permissions, port, expected_groups):
    sources = set()
    for rule in permissions:
        if (rule.get("IpProtocol"), rule.get("FromPort"), rule.get("ToPort")) != ("tcp", port, port):
            return False
        if any(rule.get(field) for field in ("IpRanges", "Ipv6Ranges", "PrefixListIds")):
            return False
        group_pairs = rule["UserIdGroupPairs"]
        if not group_pairs:
            return False
        sources.update(pair["GroupId"] for pair in group_pairs)
    return sources == expected_groups


def validate_security_groups(groups, args):
    group_ids = (args.alb_group_id, args.api_group_id, args.migration_group_id, args.database_group_id)
    if len(set(group_ids)) != len(group_ids) or any(
        groups.get(group_id, {}).get("VpcId") != args.vpc_id for group_id in group_ids
    ):
        return ["Os quatro security groups devem ser distintos e pertencer à VPC informada."]

    api = groups[args.api_group_id]["IpPermissions"]
    migrator = groups[args.migration_group_id]["IpPermissions"]
    database = groups[args.database_group_id]["IpPermissions"]
    errors = []
    if not allows_only_group_sources(api, 8080, {args.alb_group_id}):
        errors.append("A API deve receber TCP 8080 exclusivamente do grupo do ALB.")
    if migrator:
        errors.append("O grupo do migrador deve ficar sem regras de entrada.")
    if not allows_only_group_sources(database, 5432, {args.api_group_id, args.migration_group_id}):
        errors.append("O RDS deve receber TCP 5432 exclusivamente dos grupos da API e do migrador.")
    return errors


def validate_database(database, args):
    if not database:
        return ["A instância RDS informada não consta no inventário."]
    errors = []
    if database.get("Engine") != "postgres" or database.get("DBInstanceStatus") != "available":
        errors.append("A instância deve usar PostgreSQL e estar disponível.")
    if database.get("PubliclyAccessible") is not False or database.get("StorageEncrypted") is not True:
        errors.append("O RDS deve ser privado e ter armazenamento criptografado.")
    if database.get("Endpoint", {}).get("Port") != 5432:
        errors.append("O RDS deve escutar na porta 5432.")
    subnet_group = database["DBSubnetGroup"]
    subnet_ids = {subnet["SubnetIdentifier"] for subnet in subnet_group["Subnets"]}
    if subnet_group["VpcId"] != args.vpc_id or subnet_ids != set(args.database_subnet_ids):
        errors.append("O grupo de sub-redes do RDS deve conter as sub-redes de banco informadas na VPC.")
    group_ids = {group["VpcSecurityGroupId"] for group in database["VpcSecurityGroups"]}
    if group_ids != {args.database_group_id}:
        errors.append("A instância RDS deve usar somente o security group de banco informado.")
    return errors


def main():
    parser = argparse.ArgumentParser(description="Valida o inventário de rede e RDS de homologação.")
    parser.add_argument("inventory", type=Path, help="Diretório com as respostas JSON da AWS CLI.")
    parser.add_argument("--vpc-id", required=True)
    parser.add_argument("--db-identifier", required=True)
    parser.add_argument("--public-subnet-ids", nargs="+", required=True)
    parser.add_argument("--database-subnet-ids", nargs="+", required=True)
    parser.add_argument("--alb-group-id", required=True)
    parser.add_argument("--api-group-id", required=True)
    parser.add_argument("--migration-group-id", required=True)
    parser.add_argument("--database-group-id", required=True)
    args = parser.parse_args()

    resources = (
        ("vpcs", "vpcs.json", "Vpcs", "VpcId"),
        ("subnets", "subnets.json", "Subnets", "SubnetId"),
        ("routes", "route-tables.json", "RouteTables", "RouteTableId"),
        ("groups", "security-groups.json", "SecurityGroups", "GroupId"),
        ("databases", "rds.json", "DBInstances", "DBInstanceIdentifier"),
    )
    try:
        inventory = {
            name: {entry[id_key]: entry for entry in read_inventory(args.inventory, filename, key)}
            for name, filename, key, id_key in resources
        }
        errors = validate_network(inventory, args)
        errors.extend(validate_security_groups(inventory["groups"], args))
        errors.extend(validate_database(inventory["databases"].get(args.db_identifier), args))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    except (AttributeError, KeyError, TypeError):
        print("Inventário incompleto ou incompatível com a saída da AWS CLI.", file=sys.stderr)
        return 2

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Inventário de rede e RDS de homologação validado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
