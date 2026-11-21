import argparse
import json


def metric_widget(x, y, title, metrics, stat):
    return {
        "type": "metric", "x": x, "y": y, "width": 12, "height": 6,
        "properties": {
            "title": title, "region": "us-east-1", "view": "timeSeries",
            "period": 60, "stat": stat, "metrics": metrics,
        },
    }


def build_dashboard(load_balancer, target_group, cluster, service):
    alb = ["AWS/ApplicationELB"]
    ecs = ["AWS/ECS"]
    return {
        "widgets": [
            metric_widget(0, 0, "Prontidão da API", [
                alb + ["HealthyHostCount", "LoadBalancer", load_balancer, "TargetGroup", target_group],
            ], "Minimum"),
            metric_widget(12, 0, "Latência da API em segundos", [
                alb + ["TargetResponseTime", "LoadBalancer", load_balancer, "TargetGroup", target_group],
            ], "p95"),
            metric_widget(0, 6, "Respostas 5xx", [
                alb + ["HTTPCode_ELB_5XX_Count", "LoadBalancer", load_balancer],
                alb + ["HTTPCode_Target_5XX_Count", "LoadBalancer", load_balancer, "TargetGroup", target_group],
            ], "Sum"),
            metric_widget(12, 6, "Utilização ECS", [
                ecs + ["CPUUtilization", "ClusterName", cluster, "ServiceName", service],
                ecs + ["MemoryUtilization", "ClusterName", cluster, "ServiceName", service],
            ], "Average"),
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Gera um painel CloudWatch para os recursos de homologação.")
    parser.add_argument("--load-balancer", required=True, help="Sufixo app/nome/id do ARN do ALB.")
    parser.add_argument("--target-group", required=True, help="Sufixo targetgroup/nome/id do ARN.")
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--service", required=True)
    args = parser.parse_args()
    if not args.load_balancer.startswith("app/") or not args.target_group.startswith("targetgroup/"):
        parser.error("Informe os sufixos do ALB e do grupo de destino.")
    print(json.dumps(build_dashboard(**vars(args)), indent=2))


if __name__ == "__main__":
    main()
