"""The ingestion stacks as written in the templates (deploy/aws/ingestion), checked offline against the DAG jobs and
the live core. The account lets us create no IAM resource and no Cloud Map; every create must carry Owner=project3
(docs/aws-ingestion-permissions.md)."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from metamorph_pipeline.jobs import (
    PLATFORM_IMAGE,
    RETRIEVAL_IMAGE,
    ConnectorJob,
    ingest_jobs,
    task_family,
)

INGESTION = Path(__file__).parents[1] / "deploy/aws/ingestion"
TEMPLATES = sorted(INGESTION.glob("*.yaml"))

REGION = "ap-southeast-3"
ACCOUNT = "129712841299"
CLUSTER = f"arn:aws:ecs:{REGION}:{ACCOUNT}:cluster/metamorph"


class _Loader(yaml.SafeLoader):
    """CloudFormation's short tags (!Ref, !Sub, ...) read as {"Ref": ...} / {"Fn::Sub": ...}."""


def _tag(loader: _Loader, suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        value: Any = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {suffix if suffix == "Ref" else f"Fn::{suffix}": value}


_Loader.add_multi_constructor("!", _tag)


def template(name: str) -> dict[str, Any]:
    return yaml.load((INGESTION / name).read_text(), Loader=_Loader)  # noqa: S506 - the loader is SafeLoader


def resources(name: str, kind: str) -> list[dict[str, Any]]:
    return [r for r in template(name)["Resources"].values() if r["Type"] == kind]


def resolve(value: Any) -> Any:
    """The few intrinsics an event pattern uses, with the live account's values."""
    if isinstance(value, list):
        return [resolve(v) for v in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"Fn::ImportValue"}:
        assert value["Fn::ImportValue"] == "metamorph-cluster-arn"
        return CLUSTER
    if set(value) == {"Fn::Sub"}:
        return value["Fn::Sub"].replace("${AWS::Region}", REGION).replace("${AWS::AccountId}", ACCOUNT)
    return {key: resolve(sub) for key, sub in value.items()}


def matches(pattern: Any, event: Any) -> bool:
    """EventBridge's matching, for the operators the alert rule uses: exact values, `prefix`, `anything-but`.
    A pattern object needs each of its keys in the event; an event list matches when any element does."""
    if isinstance(event, list):
        return any(matches(pattern, item) for item in event)
    if isinstance(pattern, dict):
        if not isinstance(event, dict):
            return False
        return all(key in event and matches(sub, event[key]) for key, sub in pattern.items())
    return any(_leaf(option, event) for option in pattern)


def _leaf(option: Any, value: Any) -> bool:
    if isinstance(option, dict):
        if "prefix" in option:
            return isinstance(value, str) and value.startswith(option["prefix"])
        if "anything-but" in option:
            excluded = option["anything-but"]
            return value not in (excluded if isinstance(excluded, list) else [excluded])
        raise AssertionError(f"matcher not modelled: {option}")
    return option == value


def stopped(
    *,
    exit_code: int | None,
    cluster: str = CLUSTER,
    family: str = "metamorph-platform",
    status: str = "STOPPED",
    stop_code: str = "EssentialContainerExited",
) -> dict[str, Any]:
    container: dict[str, Any] = {"name": "app"} if exit_code is None else {"name": "app", "exitCode": exit_code}
    return {
        "source": "aws.ecs",
        "detail-type": "ECS Task State Change",
        "detail": {
            "clusterArn": cluster,
            "lastStatus": status,
            "stopCode": stop_code,
            "taskDefinitionArn": f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/{family}:7",
            "containers": [container],
        },
    }


def alert_pattern() -> dict[str, Any]:
    (rule,) = resources("alerts.yaml", "AWS::Events::Rule")
    return resolve(rule["Properties"]["EventPattern"])


def test_the_alert_rule_matches_a_failed_metamorph_task() -> None:
    assert matches(alert_pattern(), stopped(exit_code=1))
    assert matches(alert_pattern(), stopped(exit_code=137))  # killed for memory


def test_the_alert_rule_ignores_tasks_ecs_stops_itself_during_a_service_deploy() -> None:
    # A deploy replaces a service's tasks: ECS kills the old container (exit 137 or 143) and stops it with this code.
    assert not matches(alert_pattern(), stopped(exit_code=137, stop_code="ServiceSchedulerInitiated"))
    assert not matches(alert_pattern(), stopped(exit_code=143, stop_code="ServiceSchedulerInitiated"))


def test_the_alert_rule_ignores_a_clean_exit() -> None:
    assert not matches(alert_pattern(), stopped(exit_code=0))


def test_the_alert_rule_ignores_tasks_that_are_not_stopped() -> None:
    assert not matches(alert_pattern(), stopped(exit_code=1, status="RUNNING"))


def test_the_alert_rule_ignores_other_clusters_and_families() -> None:
    other_cluster = CLUSTER.replace("/metamorph", "/mira")
    assert not matches(alert_pattern(), stopped(exit_code=1, cluster=other_cluster))
    assert not matches(alert_pattern(), stopped(exit_code=1, family="mira-api"))


def families(name: str) -> set[str]:
    return {r["Properties"]["Family"] for r in resources(name, "AWS::ECS::TaskDefinition")}


def listed_families() -> set[str]:
    (rule,) = resources("alerts.yaml", "AWS::Events::Rule")
    prefixes = resolve(rule["Properties"]["EventPattern"])["detail"]["taskDefinitionArn"]
    base = f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/"
    assert all(option["prefix"].startswith(base) and option["prefix"].endswith(":") for option in prefixes)
    return {option["prefix"].removeprefix(base).removesuffix(":") for option in prefixes}


RETRIEVAL_STACK = yaml.load((INGESTION.parent / "retrieval.yaml").read_text(), Loader=_Loader)  # noqa: S506
PROCESSING_FAMILIES = {
    "metamorph-airflow",
    "metamorph-platform",  # load, registry build, market publish, health
    "metamorph-retrieval",  # the regulation and market indexes' refresh
}


def test_the_alert_rule_lists_exactly_the_processing_task_families() -> None:
    # An explicit list, not the prefix `metamorph-`: metamorph-mineru's task dies when its instance stops. No connector
    # family: collection runs on the collection host (docs/adr/0001-collection-on-a-residential-host.md).
    retrieval_tasks = [r for r in RETRIEVAL_STACK["Resources"].values() if r["Type"] == "AWS::ECS::TaskDefinition"]
    retrieval = {r["Properties"]["Family"] for r in retrieval_tasks}

    assert listed_families() == PROCESSING_FAMILIES
    assert families("jobs.yaml") | families("airflow.yaml") | retrieval >= PROCESSING_FAMILIES
    assert "metamorph-mineru" in families("mineru.yaml") - listed_families()


def test_the_alert_rule_ignores_the_mineru_task_that_stops_with_its_instance() -> None:
    assert not matches(alert_pattern(), stopped(exit_code=137, family="metamorph-mineru"))
    for family in PROCESSING_FAMILIES:
        assert matches(alert_pattern(), stopped(exit_code=1, family=family)), family


def test_the_alert_rule_names_no_connector_that_runs_elsewhere_now() -> None:
    for family in ("metamorph-ojk-connector", "metamorph-bi-stats", "metamorph-reports", "metamorph-ops"):
        assert not matches(alert_pattern(), stopped(exit_code=1, family=family)), family


def test_the_alert_rule_sends_to_the_email_topic() -> None:
    (rule,) = resources("alerts.yaml", "AWS::Events::Rule")
    (target,) = rule["Properties"]["Targets"]
    assert target["Arn"] == {"Ref": "Topic"}
    (subscription,) = template("alerts.yaml")["Resources"]["Topic"]["Properties"]["Subscription"]
    assert subscription["Protocol"] == "email"
    assert subscription["Endpoint"] == {"Ref": "AlertEmail"}


def test_the_topic_policy_lets_only_our_rule_and_our_alarms_publish() -> None:
    (policy,) = resources("alerts.yaml", "AWS::SNS::TopicPolicy")
    by_service = {s["Principal"]["Service"]: s for s in policy["Properties"]["PolicyDocument"]["Statement"]}
    assert set(by_service) == {"events.amazonaws.com", "cloudwatch.amazonaws.com"}
    assert all(s["Action"] == "sns:Publish" for s in by_service.values())
    events, alarms = by_service["events.amazonaws.com"], by_service["cloudwatch.amazonaws.com"]
    assert events["Condition"] == {"ArnEquals": {"aws:SourceArn": {"Fn::GetAtt": "Rule.Arn"}}}  # this stack's rule
    # A custom topic policy replaces SNS's default one, so the alarm needs its own grant: this account's only.
    assert alarms["Condition"] == {"StringEquals": {"aws:SourceAccount": {"Ref": "AWS::AccountId"}}}


def test_the_airflow_alarm_fires_when_its_service_has_no_running_task() -> None:
    (alarm,) = resources("alerts.yaml", "AWS::CloudWatch::Alarm")
    props = alarm["Properties"]
    assert {d["Name"]: d["Value"] for d in props["Dimensions"]}["ServiceName"] == "airflow"
    assert props["Namespace"] == "AWS/ECS"  # published without Container Insights
    assert props["Statistic"] == "SampleCount"
    assert props["ComparisonOperator"] == "LessThanThreshold" and props["Threshold"] == 1
    assert props["Period"] * props["EvaluationPeriods"] == 600  # ten minutes
    assert props["TreatMissingData"] == "breaching"  # a stopped service publishes nothing
    assert props["AlarmActions"] == [{"Ref": "Topic"}]


def test_the_alerts_stack_creates_no_iam_and_tags_its_resources() -> None:
    tpl = template("alerts.yaml")
    assert not [r for r in tpl["Resources"].values() if r["Type"].startswith("AWS::IAM::")]
    for name in ("Topic", "Alarm", "Rule"):
        tags = {t["Key"]: t["Value"] for t in tpl["Resources"][name]["Properties"]["Tags"]}
        assert tags["Owner"] == "project3"


# What the live core exports (CloudFormation list-exports, 2026-11-23). Update it when the core changes. The old
# templates also imported metamorph-exec-policy and metamorph-platform-role; the live core does not export them.
LIVE_CORE_EXPORTS = {
    "metamorph-app-role", "metamorph-blobs", "metamorph-blobs-arn", "metamorph-cluster", "metamorph-cluster-arn",
    "metamorph-database-host", "metamorph-execution-role", "metamorph-logs", "metamorph-ops", "metamorph-ops-arn",
    "metamorph-private-subnets", "metamorph-registry", "metamorph-retrieval-gateway-task", "metamorph-sg-api",
    "metamorph-sg-database", "metamorph-sg-database-ops", "metamorph-sg-load-balancer", "metamorph-sg-retrieval",
    "metamorph-sg-web", "metamorph-subnets", "metamorph-vpc",
}  # fmt: skip

# Resource types that take tags, and the property that holds them.
TAGGED = {
    "AWS::EC2::SecurityGroup": "Tags",
    "AWS::ECR::Repository": "Tags",
    "AWS::SSM::Parameter": "Tags",
}


SHARED = template("shared.yaml")


def shared_resources(of_type: str, stack: dict = SHARED) -> dict[str, dict]:
    return {name: body for name, body in stack["Resources"].items() if body["Type"] == of_type}


def exported(stack: dict) -> dict[str, str]:
    """Export name → the logical id the output refers to."""
    return {
        output["Export"]["Name"]: next(iter(output["Value"].values()))
        for output in stack.get("Outputs", {}).values()
        if "Export" in output
    }


def imported(path: Path) -> set[str]:
    return set(re.findall(r"ImportValue ([a-z0-9-]+)", path.read_text()))


@pytest.fixture
def jobs() -> list[ConnectorJob]:
    return ingest_jobs("/Users/someone/Metamorph-Sharia", ojk_credentials="/unused")


def test_no_ingestion_template_declares_an_iam_resource() -> None:
    declared = {
        f"{path.name}:{name}"
        for path in TEMPLATES
        for name, body in template(path.name)["Resources"].items()
        if body["Type"].startswith("AWS::IAM::")
    }
    assert not declared


def test_the_shared_stack_declares_no_iam_resource_and_no_cloud_map() -> None:
    types = {body["Type"] for body in SHARED["Resources"].values()}
    assert not {kind for kind in types if kind.startswith(("AWS::IAM::", "AWS::ServiceDiscovery::"))}


def test_the_shared_stack_imports_only_what_the_live_core_or_the_ingestion_layer_exports() -> None:
    ingestion_exports = {name for path in TEMPLATES for name in exported(template(path.name))}
    assert imported(INGESTION / "shared.yaml") <= LIVE_CORE_EXPORTS | ingestion_exports


def test_the_shared_stack_exports_nothing_the_live_core_exports() -> None:
    assert not set(exported(SHARED)) & LIVE_CORE_EXPORTS


def test_no_ingestion_stack_keeps_the_connectors_files_on_efs() -> None:
    # The connectors' state lives on the collection host's disk and the bundles in S3 (ADR 0001).
    for path in TEMPLATES:
        kinds = {body["Type"] for body in template(path.name)["Resources"].values()}
        assert not {kind for kind in kinds if kind.startswith("AWS::EFS::")}, path.name
        assert not re.search(r"\bEFS\b", path.read_text(), re.I), path.name
    assert not {"FilesGroup", "FilesFromJobs"} & set(SHARED["Resources"])
    assert not [name for name in exported(SHARED) if name.startswith("metamorph-efs")]


def test_every_resource_that_takes_tags_carries_owner() -> None:
    missing = []
    for name, body in SHARED["Resources"].items():
        prop = TAGGED.get(body["Type"])
        if not prop:
            continue
        tags = body["Properties"].get(prop, [])
        pairs = tags.items() if isinstance(tags, dict) else ((t["Key"], t["Value"]) for t in tags)
        if ("Owner", "project3") not in set(pairs):
            missing.append(name)
    assert not missing


def test_only_airflow_and_mineru_have_ingestion_image_repositories_scanned_immutable_and_pruned() -> None:
    repositories = {
        body["Properties"]["RepositoryName"]: body["Properties"]
        for body in shared_resources("AWS::ECR::Repository").values()
    }
    # The connectors' images are built on the collection host and never pushed (compose.yaml)
    assert set(repositories) == {"metamorph/airflow", "metamorph/mineru"}
    for name, properties in repositories.items():
        assert properties["ImageScanningConfiguration"] == {"ScanOnPush": True}
        assert properties["ImageTagMutability"] == "IMMUTABLE"
        policy = yaml.safe_load(properties["LifecyclePolicy"]["LifecyclePolicyText"])
        (rule,) = policy["rules"]
        assert rule["selection"]["countNumber"] == (2 if name == "metamorph/mineru" else 10)  # MinerU's are 20 GB
        assert rule["action"]["type"] == "expire"


def test_no_task_on_aws_reaches_mineru_directly_any_more() -> None:
    # Processing reads no PDF. The collection host reaches MinerU through its CloudFront front door.
    ingress = shared_resources("AWS::EC2::SecurityGroupIngress")
    assert "MinerULoadBalancerFromJobs" not in ingress
    assert not [
        name for name, body in ingress.items()
        if body["Properties"]["GroupId"] == {"Ref": "MinerULoadBalancerGroup"}
    ]
    assert "MinerUFromLoadBalancer" in ingress  # the load balancer still reaches the MinerU task


def test_the_database_group_accepts_airflow_and_the_tasks() -> None:
    sources = {
        body["Properties"]["SourceSecurityGroupId"]["Ref"]
        for body in shared_resources("AWS::EC2::SecurityGroupIngress").values()
        if body["Properties"]["GroupId"] == {"Fn::ImportValue": "metamorph-sg-database"}
    }
    assert sources == {"AirflowGroup", "JobsGroup"}


# The jobs stack: one task definition per image a DAG runs.
JOBS = template("jobs.yaml")


def task_definitions() -> dict[str, dict[str, Any]]:
    """Family → the task definition's properties."""
    return {
        body["Properties"]["Family"]: body["Properties"]
        for body in JOBS["Resources"].values()
        if body["Type"] == "AWS::ECS::TaskDefinition"
    }


def main_container(definition: dict[str, Any]) -> dict[str, Any]:
    (main,) = [c for c in definition["ContainerDefinitions"] if c["Name"] == "main"]
    return main


def mounted(definition: dict[str, Any], container: dict[str, Any]) -> dict[str, str]:
    """Container path → the export name of the access point mounted there."""
    access_points = {
        volume["Name"]: volume["EFSVolumeConfiguration"]["AuthorizationConfig"]["AccessPointId"]["Fn::ImportValue"]
        for volume in definition.get("Volumes", [])
    }
    return {m["ContainerPath"]: access_points[m["SourceVolume"]] for m in container.get("MountPoints", [])}


def image_tag_parameter(container: dict[str, Any]) -> str:
    match = re.search(r"\$\{(\w+)\}$", container["Image"]["Fn::Sub"][0])
    assert match
    return match.group(1)


def test_the_jobs_stack_defines_only_the_platform_task_the_processing_dags_run_on_ecs() -> None:
    assert RETRIEVAL_IMAGE != PLATFORM_IMAGE  # Retrieval's refresh belongs to the retrieval stack
    assert set(task_definitions()) == {task_family(PLATFORM_IMAGE)}


def test_the_platform_task_has_one_essential_main_container_logging_under_its_family() -> None:
    definition = task_definitions()["metamorph-platform"]
    main = main_container(definition)
    assert len(definition["ContainerDefinitions"]) == 1  # no init container: BI's SEKI inbox is the collection host's
    assert main["Essential"] is True
    assert "Command" not in main  # Airflow passes the command
    assert main["LogConfiguration"]["Options"]["awslogs-stream-prefix"] == "metamorph-platform"  # read at <family>/main
    assert definition["RequiresCompatibilities"] == ["FARGATE"]


def test_the_platform_task_mounts_no_volume_it_reads_bundles_from_s3() -> None:
    definition = task_definitions()["metamorph-platform"]
    assert "Volumes" not in definition
    assert "MountPoints" not in main_container(definition)


def test_the_jobs_stack_keeps_nothing_only_a_connector_task_read() -> None:
    text = template_text("jobs.yaml")
    gone_with_the_connectors = (
        "EFS", "ConnectorTaskRole", "ConnectorCpu", "ConnectorMemory", "_CONTACT", "/metamorph/connectors/", "inbox",
        "/metamorph/mineru/api-key", "metamorph-ops", "OPS_BUCKET",
    )  # fmt: skip
    for gone in gone_with_the_connectors:
        assert gone not in text, gone
    assert set(JOBS["Parameters"]) == {"PlatformTaskRole", "PlatformTag", "PlatformCpu", "PlatformMemory"}


def test_the_platform_task_gets_its_database_and_blobs_bucket_from_parameter_store() -> None:
    secrets = {s["Name"]: s["ValueFrom"] for s in main_container(task_definitions()["metamorph-platform"])["Secrets"]}
    assert secrets == {
        "METAMORPH_DATABASE_URL": "/metamorph/platform/database-url",
        "METAMORPH_S3_BUCKET": "/metamorph/platform/s3-bucket",  # where load-pending reads the bundles
    }


def test_the_platform_task_role_comes_from_a_parameter_named_after_the_devops_role() -> None:
    parameters = JOBS["Parameters"]
    assert parameters["PlatformTaskRole"]["Default"] == "metamorph-platform-task"
    definition = task_definitions()["metamorph-platform"]
    assert definition["TaskRoleArn"] == {"Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/${PlatformTaskRole}"}
    assert definition["ExecutionRoleArn"] == {"Fn::ImportValue": "metamorph-execution-role"}


def test_the_jobs_stack_declares_no_iam_resource_and_imports_only_live_exports() -> None:
    assert not [name for name, r in JOBS["Resources"].items() if r["Type"].startswith("AWS::IAM::")]
    ingestion_exports = {name for path in TEMPLATES for name in exported(template(path.name))}
    assert imported(INGESTION / "jobs.yaml") <= LIVE_CORE_EXPORTS | ingestion_exports
    assert not exported(JOBS)


def test_every_task_definition_is_tagged_owner_project3() -> None:
    for family, definition in task_definitions().items():
        assert {"Key": "Owner", "Value": "project3"} in definition["Tags"], family


def test_the_platform_task_size_stays_inside_the_accounts_task_cap() -> None:
    parameters = JOBS["Parameters"]
    assert (parameters["PlatformCpu"]["Default"], parameters["PlatformMemory"]["Default"]) == ("1024", "4096")
    assert max(int(v) for v in parameters["PlatformCpu"]["AllowedValues"]) <= 2048
    assert max(int(v) for v in parameters["PlatformMemory"]["AllowedValues"]) <= 8192
    definition = task_definitions()["metamorph-platform"]
    assert (definition["Cpu"], definition["Memory"]) == ({"Ref": "PlatformCpu"}, {"Ref": "PlatformMemory"})


def test_the_platform_image_comes_from_its_repository_at_a_tag_parameter() -> None:
    main = main_container(task_definitions()["metamorph-platform"])
    assert image_tag_parameter(main) == "PlatformTag"
    assert JOBS["Parameters"]["PlatformTag"]["Type"] == "String"
    assert main["Image"]["Fn::Sub"][0].startswith("${Registry}/metamorph/platform:")


def test_push_images_builds_airflow_but_no_connector_image() -> None:
    script = (Path(__file__).parents[1] / "deploy/aws/push-images.sh").read_text()
    assert re.search(r"^\s+airflow\)\s+build airflow ", script, re.M)
    assert re.search(r"^INGESTION=\(airflow\)$", script, re.M)
    jobs = ingest_jobs("/w", ojk_credentials="/unused")
    for job in jobs:
        assert job.image.rsplit(":", 1)[0].removeprefix("metamorph/") not in script, job.image
    assert "-connector" not in script

# The Airflow stack: the role by name, the UI through CloudFront behind a password check.
AIRFLOW = template("airflow.yaml")
PASSWORD = "correct horse battery staple"
PASSWORD_SHA256 = hashlib.sha256(PASSWORD.encode()).hexdigest()


def template_text(name: str) -> str:
    return (INGESTION / name).read_text()


def test_the_airflow_stack_declares_no_iam_resource() -> None:
    assert not [name for name, body in AIRFLOW["Resources"].items() if body["Type"].startswith("AWS::IAM::")]


def test_the_airflow_task_role_comes_from_a_parameter_defaulting_to_the_devops_role() -> None:
    parameter = AIRFLOW["Parameters"]["AirflowTaskRole"]
    assert parameter["Default"] == "metamorph-airflow-task"
    (task,) = resources("airflow.yaml", "AWS::ECS::TaskDefinition")
    role = task["Properties"]["TaskRoleArn"]["Fn::Sub"]
    assert role == "arn:aws:iam::${AWS::AccountId}:role/${AirflowTaskRole}"
    assert task["Properties"]["ExecutionRoleArn"] == {"Fn::ImportValue": "metamorph-execution-role"}


def test_airflow_starts_its_tasks_on_ecs() -> None:
    (task,) = resources("airflow.yaml", "AWS::ECS::TaskDefinition")
    (container,) = task["Properties"]["ContainerDefinitions"]
    environment = {e["Name"]: e["Value"] for e in container["Environment"]}
    assert environment["METAMORPH_TASK_LAUNCHER"] == "ecs"
    secrets = {s["Name"] for s in container["Secrets"] if isinstance(s, dict) and "Name" in s}
    assert {"METAMORPH_ECS_CLUSTER", "METAMORPH_ECS_SUBNETS", "METAMORPH_ECS_SECURITY_GROUP"} <= secrets


def test_airflow_on_aws_knows_the_blobs_bucket_where_the_bundles_it_loads_are() -> None:
    (task,) = resources("airflow.yaml", "AWS::ECS::TaskDefinition")
    (container,) = task["Properties"]["ContainerDefinitions"]
    secrets = {s["Name"]: s["ValueFrom"] for s in container["Secrets"] if isinstance(s, dict) and "Name" in s}
    assert secrets["METAMORPH_BUNDLES_BUCKET"] == "/metamorph/platform/s3-bucket"  # the platform task reads it already


def test_the_airflow_on_aws_is_the_processing_side() -> None:
    (task,) = resources("airflow.yaml", "AWS::ECS::TaskDefinition")
    (container,) = task["Properties"]["ContainerDefinitions"]
    environment = {e["Name"]: e["Value"] for e in container["Environment"]}
    assert environment["METAMORPH_SIDE"] == "processing"


def test_the_compose_airflow_is_the_collection_side() -> None:
    compose = yaml.safe_load((INGESTION.parents[2] / "compose.yaml").read_text())
    assert compose["services"]["airflow"]["environment"]["METAMORPH_SIDE"] == "collection"


def test_the_airflow_stack_imports_only_what_exists() -> None:
    ingestion_exports = {name for path in TEMPLATES for name in exported(template(path.name))}
    assert imported(INGESTION / "airflow.yaml") <= LIVE_CORE_EXPORTS | ingestion_exports


def test_every_airflow_resource_that_takes_tags_carries_owner() -> None:
    wanted = {
        "AWS::EC2::SecurityGroup", "AWS::ElasticLoadBalancingV2::LoadBalancer",
        "AWS::ElasticLoadBalancingV2::TargetGroup", "AWS::ECS::TaskDefinition", "AWS::ECS::Service",
        "AWS::CloudFront::Distribution", "AWS::CloudFront::VpcOrigin",
    }  # fmt: skip
    missing = []
    for name, body in AIRFLOW["Resources"].items():
        if body["Type"] not in wanted:
            continue
        tags = body["Properties"].get("Tags")
        pairs = {(t["Key"], t["Value"]) for t in tags or []}
        if ("Owner", "project3") not in pairs:
            missing.append(name)
    assert not missing


def test_the_ui_sits_behind_an_internal_load_balancer_that_only_cloudfront_reaches() -> None:
    (balancer,) = resources("airflow.yaml", "AWS::ElasticLoadBalancingV2::LoadBalancer")
    assert balancer["Properties"]["Scheme"] == "internal"
    (origin,) = resources("airflow.yaml", "AWS::CloudFront::VpcOrigin")
    assert origin["Properties"]["VpcOriginEndpointConfig"]["Arn"] == {"Ref": "LoadBalancer"}
    (group,) = [
        body for body in AIRFLOW["Resources"].values() if body["Type"] == "AWS::EC2::SecurityGroup"
    ]
    (rule,) = group["Properties"]["SecurityGroupIngress"]
    assert rule["SourcePrefixListId"] == {"Ref": "CloudFrontPrefixList"}
    (service,) = resources("airflow.yaml", "AWS::ECS::Service")
    (attached,) = service["Properties"]["LoadBalancers"]
    assert attached["ContainerPort"] == 8080


def test_airflows_base_url_is_the_cloudfront_address() -> None:
    (task,) = resources("airflow.yaml", "AWS::ECS::TaskDefinition")
    (container,) = task["Properties"]["ContainerDefinitions"]
    environment = {e["Name"]: e["Value"] for e in container["Environment"]}
    assert environment["AIRFLOW__WEBSERVER__BASE_URL"] == {"Fn::Sub": "https://${Distribution.DomainName}"}
    assert environment["AIRFLOW__WEBSERVER__ENABLE_PROXY_FIX"] == "true"


def password_check(sha256: str = PASSWORD_SHA256) -> str:
    (function,) = resources("airflow.yaml", "AWS::CloudFront::Function")
    return function["Properties"]["FunctionCode"]["Fn::Sub"].replace("${PasswordSha256}", sha256)


def run_password_check(
    authorization: str | None, sha256: str = PASSWORD_SHA256, extra: dict[str, str] | None = None
) -> dict[str, Any]:
    headers = {"host": {"value": "d111111abcdef8.cloudfront.net"}}  # CloudFront always gives the function the viewer's host
    headers |= {} if authorization is None else {"authorization": {"value": authorization}}
    headers |= {name: {"value": value} for name, value in (extra or {}).items()}
    event = json.dumps({"request": {"headers": headers}})
    script = f"{password_check(sha256)}\nconsole.log(JSON.stringify(handler({event})));"
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)  # noqa: S603, S607
    return json.loads(done.stdout)


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node runs the edge function")


@needs_node
def test_the_edge_function_asks_for_basic_auth_when_no_password_comes() -> None:
    answer = run_password_check(None)
    assert answer["statusCode"] == 401
    assert answer["headers"]["www-authenticate"]["value"].startswith("Basic")


@needs_node
def test_the_edge_function_refuses_a_wrong_password() -> None:
    answer = run_password_check(basic("admin", "wrong"))
    assert answer["statusCode"] == 401
    assert "Basic" in answer["headers"]["www-authenticate"]["value"]


@needs_node
def test_the_edge_function_refuses_a_header_that_is_not_basic() -> None:
    assert run_password_check("Bearer " + PASSWORD)["statusCode"] == 401


@needs_node
def test_the_edge_function_passes_the_right_password_and_drops_the_header() -> None:
    answer = run_password_check(basic("anyone", PASSWORD))
    assert "statusCode" not in answer
    assert "authorization" not in answer["headers"]


@needs_node
def test_the_edge_function_tells_airflow_the_viewers_host() -> None:
    # The origin sees Host = the load balancer's name: only this header carries the host the viewer used. It is set,
    # never trusted from the viewer. No scheme header: the load balancer always sends X-Forwarded-Proto: http, and
    # gunicorn answers 400 to a request whose scheme headers contradict each other (seen live, 2026-11-23).
    host = "d111111abcdef8.cloudfront.net"
    answer = run_password_check(basic("admin", PASSWORD), extra={"host": host})
    assert answer["headers"]["x-forwarded-host"] == {"value": host}
    assert "x-forwarded-ssl" not in answer["headers"]

    spoofed = {"host": host, "x-forwarded-host": "evil.example"}
    answer = run_password_check(basic("admin", PASSWORD), extra=spoofed)
    assert answer["headers"]["x-forwarded-host"] == {"value": host}


def test_airflow_takes_its_host_from_that_header_and_http_links_come_back_as_https() -> None:
    # ProxyFix reads X-Forwarded-Host and nothing the load balancer wrote (its X-Forwarded-Proto is http, -Port 80).
    # Airflow's absolute links (a sign-in's next=) then say http, and CloudFront sends those back to https.
    (task,) = resources("airflow.yaml", "AWS::ECS::TaskDefinition")
    (container,) = task["Properties"]["ContainerDefinitions"]
    environment = {e["Name"]: e["Value"] for e in container["Environment"]}
    assert "FORWARDED_ALLOW_IPS" not in environment
    assert environment["AIRFLOW__WEBSERVER__PROXY_FIX_X_HOST"] == "1"
    assert environment["AIRFLOW__WEBSERVER__PROXY_FIX_X_PROTO"] == "0"
    assert environment["AIRFLOW__WEBSERVER__PROXY_FIX_X_PORT"] == "0"
    (distribution,) = resources("airflow.yaml", "AWS::CloudFront::Distribution")
    behavior = distribution["Properties"]["DistributionConfig"]["DefaultCacheBehavior"]
    assert behavior["ViewerProtocolPolicy"] == "redirect-to-https"


@needs_node
def test_a_password_with_a_colon_still_matches() -> None:
    tricky = PASSWORD + ":with:colons"
    answer = run_password_check(basic("admin", tricky), hashlib.sha256(tricky.encode()).hexdigest())
    assert "statusCode" not in answer


def test_the_edge_function_is_a_published_cloudfront_function_on_every_request() -> None:
    (function,) = resources("airflow.yaml", "AWS::CloudFront::Function")
    assert function["Properties"]["AutoPublish"] is True
    (distribution,) = resources("airflow.yaml", "AWS::CloudFront::Distribution")
    behavior = distribution["Properties"]["DistributionConfig"]["DefaultCacheBehavior"]
    (association,) = behavior["FunctionAssociations"]
    assert association["EventType"] == "viewer-request"
    assert behavior["CachePolicyId"] == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"  # CachingDisabled


def test_the_distribution_takes_an_optional_web_acl() -> None:
    assert AIRFLOW["Parameters"]["WebAclArn"]["Default"] == ""
    (distribution,) = resources("airflow.yaml", "AWS::CloudFront::Distribution")
    assert distribution["Properties"]["DistributionConfig"]["WebACLId"] == {
        "Fn::If": ["HasWebAcl", {"Ref": "WebAclArn"}, {"Ref": "AWS::NoValue"}]
    }


def test_nothing_in_the_airflow_template_embeds_a_plain_password() -> None:
    passwords = [name for name in AIRFLOW["Parameters"] if "password" in name.lower()]
    assert passwords == ["PasswordSha256"]
    parameter = AIRFLOW["Parameters"]["PasswordSha256"]
    assert parameter["AllowedPattern"] == "[0-9a-f]{64}"
    assert "Default" not in parameter  # no stand-in hash, so no stand-in password
    assert "${PasswordSha256}" in template_text("airflow.yaml")  # the code takes the hash from the parameter
    environment_values = json.dumps(AIRFLOW["Resources"]["Task"]["Properties"])
    assert "_AIRFLOW_WWW_USER_PASSWORD" in environment_values
    assert re.search(r"_AIRFLOW_WWW_USER_PASSWORD.*ValueFrom.*/metamorph/airflow/admin-password", environment_values)


WAF_SCRIPT = INGESTION / "waf.sh"


def waf_calls(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run waf.sh with an `aws` that only records its arguments, one call per line."""
    fake = tmp_path / "aws"
    fake.write_text(f'#!/bin/bash\necho "$@" >> {tmp_path}/calls\necho id-1 token-1\n')
    fake.chmod(0o755)
    environment = {"PATH": f"{tmp_path}:/usr/bin:/bin"}
    return subprocess.run(  # noqa: S603
        ["/bin/bash", str(WAF_SCRIPT), *arguments], env=environment, capture_output=True, text=True, check=False
    )


def test_the_waf_script_is_beside_the_templates_and_valid_shell() -> None:
    text = WAF_SCRIPT.read_text()
    assert "--scope CLOUDFRONT" in text and "us-east-1" in text and "Key=Owner,Value=project3" in text
    subprocess.run(["bash", "-n", str(WAF_SCRIPT)], check=True)  # noqa: S603, S607


def test_the_waf_script_makes_airflows_rate_limit_when_no_target_is_named(tmp_path) -> None:
    assert waf_calls(tmp_path, "create").returncode == 0
    (call,) = (tmp_path / "calls").read_text().splitlines()
    assert "--name metamorph-airflow" in call and '"Limit":300' in call


def test_the_waf_script_makes_minerus_rate_limit_under_its_own_name_and_a_limit_for_polling(tmp_path) -> None:
    assert waf_calls(tmp_path, "create", "mineru").returncode == 0
    (call,) = (tmp_path / "calls").read_text().splitlines()
    assert "--name metamorph-mineru" in call and "--scope CLOUDFRONT" in call
    assert int(re.search(r'"Limit":(\d+)', call).group(1)) > 300  # a job polls every 5 s, and several run at once


def test_the_waf_script_deletes_only_the_named_targets_web_acl(tmp_path) -> None:
    assert waf_calls(tmp_path, "delete", "mineru").returncode == 0
    lookup, deletion = (tmp_path / "calls").read_text().splitlines()
    assert "metamorph-mineru" in lookup
    assert "--name metamorph-mineru" in deletion and "--id id-1" in deletion and "--lock-token token-1" in deletion


def test_the_waf_script_refuses_a_target_it_does_not_know(tmp_path) -> None:
    result = waf_calls(tmp_path, "create", "elsewhere")
    assert result.returncode != 0 and "usage" in result.stderr
    assert not (tmp_path / "calls").exists()


def test_the_tunnel_is_gone() -> None:
    assert not (INGESTION / "tunnel.sh").exists()


# --- MinerU: one scheduled instance behind an internal load balancer (mineru.yaml) ---------------------------------

MINERU = template("mineru.yaml")


def minerus(of_type: str) -> dict[str, dict]:
    return shared_resources(of_type, MINERU)


def window(name: str) -> tuple[int, str, str]:
    """A window parameter's default, cron(minute hour day-of-month month day-of-week year): minutes after midnight UTC,
    its day-of-month and its day-of-week."""
    expression = re.fullmatch(r"cron\((.*)\)", MINERU["Parameters"][name]["Default"])
    minute, hour, day_of_month, _, day_of_week, _ = expression.group(1).split()
    return int(hour) * 60 + int(minute), day_of_month, day_of_week


def job_start(job: ConnectorJob) -> int:
    minute, hour = job.schedule.split()[:2]
    return int(hour) * 60 + int(minute)


def test_the_window_is_weekdays_08_45_to_12_45_wib_and_to_13_15_on_the_first_days_of_the_month() -> None:
    start, _, start_days = window("WindowStart")
    end, end_dates, _ = window("WindowEnd")
    monthly_end, monthly_dates, _ = window("MonthlyWindowEnd")

    assert start_days == "MON-FRI"  # the instance starts on weekdays only
    # The month's first weekday is always among the 1st to 3rd: those days end later, the rest at the usual hour
    assert (end_dates, monthly_dates) == ("4-31", "1-3")
    assert (start, end, monthly_end) == (1 * 60 + 45, 5 * 60 + 45, 6 * 60 + 15)  # UTC; WIB is 7 hours ahead


def test_a_stop_repeats_every_hour_outside_the_window_so_a_hand_start_ends_within_an_hour() -> None:
    start, _, _ = window("WindowStart")
    monthly_end, _, _ = window("MonthlyWindowEnd")
    minute, hours, *_ = re.fullmatch(r"cron\((.*)\)", MINERU["Parameters"]["HourlyStop"]["Default"]).group(1).split()
    stops = sorted(int(hour) * 60 + int(minute) for part in hours.split(",") for hour in range(
        int(part.split("-")[0]), int(part.split("-")[-1]) + 1))
    gaps = [(later - earlier) % (24 * 60) for earlier, later in zip(stops, stops[1:] + stops[:1], strict=True)]

    assert not [stop for stop in stops if start <= stop <= monthly_end]  # none inside the window
    assert min(stop for stop in stops if stop > monthly_end) - monthly_end <= HOUR  # the first after the longest day
    assert sorted(gaps)[:-1] == [HOUR] * (len(gaps) - 1)  # an hour apart; the one longer gap holds the window


HOUR = 60  # a PDF job needs time to run before the instance stops under it: it must start this long before the end


def test_every_job_that_reads_pdfs_starts_inside_the_window_with_an_hour_to_run(jobs) -> None:
    start, _, _ = window("WindowStart")
    end, _, _ = window("WindowEnd")
    monthly_end, _, _ = window("MonthlyWindowEnd")
    readers = [job for job in jobs if job.reads_pdfs]

    assert readers
    for job in readers:
        # the monthly full pass is meant for the first weekday, when the window is longer; any other job must fit the
        # usual end, which a first weekday that is also its day only lengthens
        job_end = monthly_end if job.monthly else end
        assert start <= job_start(job) <= job_end - HOUR, job.dag_id


def test_the_weekly_backup_starts_after_the_last_stop() -> None:
    from metamorph_pipeline.jobs import backup_job

    assert job_start(backup_job()) > window("MonthlyWindowEnd")[0]  # the Friday it runs may be the 1st to 3rd


def test_the_mineru_stack_has_no_auto_scaling_iam_cloud_map_or_launch_template() -> None:
    types = {body["Type"] for body in MINERU["Resources"].values()}
    banned = (
        "AWS::IAM::", "AWS::AutoScaling::", "AWS::ServiceDiscovery::", "AWS::EC2::LaunchTemplate",
        "AWS::ECS::Capacity", "AWS::ECS::ClusterCapacity",
    )  # fmt: skip

    assert not {kind for kind in types if kind.startswith(banned)}


def test_the_gpu_instance_is_one_g5_xlarge_with_a_small_public_tagged_root_disk() -> None:
    ((_, instance),) = minerus("AWS::EC2::Instance").items()
    props = instance["Properties"]
    tags = {t["Key"]: t["Value"] for t in props["Tags"]}
    (disk,) = props["BlockDeviceMappings"]
    (nic,) = props["NetworkInterfaces"]

    assert MINERU["Parameters"]["InstanceType"]["Default"] == "g5.xlarge"
    assert props["InstanceType"] == {"Ref": "InstanceType"}
    assert MINERU["Parameters"]["GpuImageId"]["Default"].endswith("/gpu/recommended/image_id")
    assert props["ImageId"] == {"Ref": "GpuImageId"}
    assert tags == {"Name": "metamorph-mineru", "Owner": "project3"}  # the scheduler role may stop only this name
    assert MINERU["Parameters"]["VolumeGiB"]["MaxValue"] <= 100  # the account's limit
    assert disk["Ebs"]["VolumeSize"] == {"Ref": "VolumeGiB"}
    assert nic["AssociatePublicIpAddress"] is True  # ECR without a NAT gateway
    assert {"Fn::ImportValue": "metamorph-sg-gpu-host"} in nic["GroupSet"]


def test_the_instance_profile_is_a_parameter_defaulting_to_the_one_devops_made() -> None:
    ((_, instance),) = minerus("AWS::EC2::Instance").items()

    assert MINERU["Parameters"]["InstanceProfile"]["Default"] == "metamorph-mineru-instance"
    assert instance["Properties"]["IamInstanceProfile"] == {"Ref": "InstanceProfile"}


def test_the_instance_joins_the_cluster_with_gpu_support_and_an_attribute_the_service_requires() -> None:
    ((_, instance),) = minerus("AWS::EC2::Instance").items()
    user_data = instance["Properties"]["UserData"]["Fn::Base64"]["Fn::Sub"][0]
    attribute = re.search(r'ECS_INSTANCE_ATTRIBUTES=\{"(\w+)": ?"(\w+)"\}', user_data)
    (service,) = minerus("AWS::ECS::Service").values()
    (constraint,) = service["Properties"]["PlacementConstraints"]

    assert "ECS_CLUSTER=${Cluster}" in user_data
    assert "ECS_ENABLE_GPU_SUPPORT=true" in user_data
    assert attribute
    assert constraint == {"Type": "memberOf", "Expression": f"attribute:{attribute[1]} == {attribute[2]}"}


def test_the_service_runs_one_mineru_task_on_ec2_behind_the_load_balancer() -> None:
    (service,) = minerus("AWS::ECS::Service").values()
    props = service["Properties"]
    (task,) = minerus("AWS::ECS::TaskDefinition").values()
    (balanced,) = props["LoadBalancers"]
    (container,) = task["Properties"]["ContainerDefinitions"]

    assert props["LaunchType"] == "EC2"
    assert props["DesiredCount"] == 1  # it places itself whenever the instance runs
    assert task["Properties"]["RequiresCompatibilities"] == ["EC2"]
    assert (balanced["ContainerName"], balanced["ContainerPort"]) == ("main", 8010)
    assert "ServiceRegistries" not in props


def test_the_mineru_task_shares_the_instance_s_interface_so_a_stop_leaves_it_one() -> None:
    # awsvpc gave the task its own interface, which a stop leaves attached; EC2 gives no automatic public address at
    # start to an instance with two, so the ECS agent never connected again (2026-11-24). Bridge mode adds none.
    (service,) = minerus("AWS::ECS::Service").values()
    (task,) = minerus("AWS::ECS::TaskDefinition").values()
    (target,) = minerus("AWS::ElasticLoadBalancingV2::TargetGroup").values()
    ((_, instance),) = minerus("AWS::EC2::Instance").items()
    (container,) = task["Properties"]["ContainerDefinitions"]
    (nic,) = instance["Properties"]["NetworkInterfaces"]

    assert task["Properties"]["NetworkMode"] == "bridge"
    assert container["PortMappings"] == [{"ContainerPort": 8010, "HostPort": 8010}]
    assert "NetworkConfiguration" not in service["Properties"]
    assert target["Properties"]["TargetType"] == "instance"
    assert {"Fn::ImportValue": "metamorph-sg-mineru"} in nic["GroupSet"]  # what the load balancer may reach on 8010
    assert nic["DeleteOnTermination"] is True


def test_the_load_balancer_is_internal_and_checks_mineru_s_health_endpoint() -> None:
    ((_, balancer),) = minerus("AWS::ElasticLoadBalancingV2::LoadBalancer").items()
    (target,) = minerus("AWS::ElasticLoadBalancingV2::TargetGroup").values()
    (listener,) = minerus("AWS::ElasticLoadBalancingV2::Listener").values()
    (task,) = minerus("AWS::ECS::TaskDefinition").values()
    (container,) = task["Properties"]["ContainerDefinitions"]

    assert balancer["Properties"]["Scheme"] == "internal"
    assert balancer["Properties"]["SecurityGroups"] == [{"Fn::ImportValue": "metamorph-sg-mineru-lb"}]
    assert target["Properties"]["HealthCheckPath"] == "/v1/health"
    assert "/v1/health" in container["HealthCheck"]["Command"][-1]
    assert listener["Properties"]["Port"] == 8010  # the port the load balancer group admits from the jobs
    for resource in (balancer, target):
        assert {"Key": "Owner", "Value": "project3"} in resource["Properties"]["Tags"]


def test_the_load_balancer_drops_idle_connections_before_mineru_s_server_does() -> None:
    (balancer,) = minerus("AWS::ElasticLoadBalancingV2::LoadBalancer").values()
    attributes = {a["Key"]: a["Value"] for a in balancer["Properties"]["LoadBalancerAttributes"]}
    assert int(attributes["idle_timeout.timeout_seconds"]) < 5  # uvicorn's keep-alive; otherwise a poll can get a 502


# The front door: CloudFront -> VPC origin -> the internal load balancer, for the collection host's connectors.


def front_door() -> dict[str, Any]:
    (distribution,) = minerus("AWS::CloudFront::Distribution").values()
    return distribution["Properties"]["DistributionConfig"]


def test_the_front_door_reaches_the_internal_load_balancer_through_a_vpc_origin() -> None:
    ((_, balancer),) = minerus("AWS::ElasticLoadBalancingV2::LoadBalancer").items()
    (origin,) = minerus("AWS::CloudFront::VpcOrigin").values()
    config = origin["Properties"]["VpcOriginEndpointConfig"]
    (listener,) = minerus("AWS::ElasticLoadBalancingV2::Listener").values()
    (served,) = front_door()["Origins"]

    assert balancer["Properties"]["Scheme"] == "internal"
    assert config["Arn"] == {"Ref": "LoadBalancer"}
    assert (config["OriginProtocolPolicy"], config["HTTPPort"]) == ("http-only", listener["Properties"]["Port"])
    assert served["DomainName"] == {"Fn::GetAtt": "LoadBalancer.DNSName"}
    assert served["VpcOriginConfig"]["VpcOriginId"] == {"Fn::GetAtt": "Origin.Id"}


def test_the_load_balancer_sits_where_a_vpc_origin_reaches_it_and_cloudfront_is_admitted_by_prefix_list() -> None:
    ((_, balancer),) = minerus("AWS::ElasticLoadBalancingV2::LoadBalancer").items()
    (rule,) = [body["Properties"] for body in minerus("AWS::EC2::SecurityGroupIngress").values()]

    assert balancer["Properties"]["Subnets"] == {"Fn::Split": [",", {"Fn::ImportValue": "metamorph-private-subnets"}]}
    assert rule["GroupId"] == {"Fn::ImportValue": "metamorph-sg-mineru-lb"}  # the group the jobs' own rule is on
    assert rule["SourcePrefixListId"] == {"Ref": "CloudFrontPrefixList"}
    assert (rule["FromPort"], rule["ToPort"]) == (8010, 8010)
    assert "SourceSecurityGroupId" not in rule and "CidrIp" not in rule


def test_viewers_use_https_and_every_method_but_nothing_is_cached() -> None:
    behavior = front_door()["DefaultCacheBehavior"]

    assert behavior["ViewerProtocolPolicy"] == "redirect-to-https"
    assert set(behavior["AllowedMethods"]) == {"GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"}
    assert behavior["CachePolicyId"] == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"  # Managed-CachingDisabled


def test_the_api_keys_header_reaches_the_origin_and_no_password_is_asked_at_the_edge() -> None:
    behavior = front_door()["DefaultCacheBehavior"]

    # Managed-AllViewerExceptHostHeader: every viewer header, Authorization included, which MinerU checks itself
    assert behavior["OriginRequestPolicyId"] == "b689b0a8-53d0-40ab-baf2-68738e2966ac"
    assert "FunctionAssociations" not in behavior and "LambdaFunctionAssociations" not in behavior
    assert not minerus("AWS::CloudFront::Function")


def test_cloudfront_drops_an_idle_connection_before_the_load_balancer_does() -> None:
    (balancer,) = minerus("AWS::ElasticLoadBalancingV2::LoadBalancer").values()
    attributes = {a["Key"]: a["Value"] for a in balancer["Properties"]["LoadBalancerAttributes"]}
    (served,) = front_door()["Origins"]

    # CloudFront -> balancer -> MinerU, each hanging up before the one behind it, or a poll can get a 502
    assert 0 < served["VpcOriginConfig"]["OriginKeepaliveTimeout"] < int(attributes["idle_timeout.timeout_seconds"])


def test_the_front_door_takes_an_optional_web_acl_from_waf_sh() -> None:
    assert MINERU["Parameters"]["WebAclArn"]["Default"] == ""
    assert "HasWebAcl" in MINERU["Conditions"]
    assert front_door()["WebACLId"] == {"Fn::If": ["HasWebAcl", {"Ref": "WebAclArn"}, {"Ref": "AWS::NoValue"}]}
    prefix_list = "CloudFrontPrefixList"
    assert MINERU["Parameters"][prefix_list]["Default"] == AIRFLOW["Parameters"][prefix_list]["Default"]


def test_the_front_door_s_address_is_an_output() -> None:
    assert MINERU["Outputs"]["FrontDoorUrl"]["Value"] == {"Fn::Sub": "https://${Distribution.DomainName}"}


def test_every_front_door_resource_carries_owner() -> None:
    for kind in ("AWS::CloudFront::Distribution", "AWS::CloudFront::VpcOrigin"):
        ((_, resource),) = minerus(kind).items()
        assert {"Key": "Owner", "Value": "project3"} in resource["Properties"]["Tags"], kind


def test_mineru_is_reached_only_through_its_front_door_so_no_internal_address_is_published() -> None:
    # The parameter held the load balancer's address for the connector tasks that ran on AWS: they run elsewhere now.
    assert not minerus("AWS::SSM::Parameter")
    assert "MinerUUrl" not in MINERU["Outputs"]
    assert "mineru-url" not in template_text("mineru.yaml")


def test_four_schedules_start_and_stop_the_instance_with_the_scheduler_role() -> None:
    bodies = minerus("AWS::Scheduler::Schedule").values()
    schedules = {body["Properties"]["ScheduleExpression"]["Ref"]: body["Properties"] for body in bodies}

    assert MINERU["Parameters"]["SchedulerRole"]["Default"] == "metamorph-scheduler"
    assert set(schedules) == {"WindowStart", "WindowEnd", "MonthlyWindowEnd", "HourlyStop"}
    assert schedules["WindowStart"]["Target"]["Arn"] == "arn:aws:scheduler:::aws-sdk:ec2:startInstances"
    for stop in ("WindowEnd", "MonthlyWindowEnd", "HourlyStop"):
        assert schedules[stop]["Target"]["Arn"] == "arn:aws:scheduler:::aws-sdk:ec2:stopInstances"
    for props in schedules.values():
        assert props["ScheduleExpressionTimezone"] == "UTC"
        assert props["Target"]["RoleArn"] == {"Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/${SchedulerRole}"}
        assert props["Target"]["Input"] == {"Fn::Sub": '{"InstanceIds": ["${Instance}"]}'}


# --- The weekly backup's expiry, the check command and the README ---------------------------------------------------

FOUNDATION = yaml.load((INGESTION.parent / "foundation.yaml").read_text(), Loader=_Loader)  # noqa: S506


def test_the_ops_bucket_expires_the_weekly_backups_after_35_days() -> None:
    rules = FOUNDATION["Resources"]["Ops"]["Properties"]["LifecycleConfiguration"]["Rules"]
    (backups,) = [rule for rule in rules if rule.get("Prefix") == "backups/"]
    assert backups["Status"] == "Enabled"
    assert backups["ExpirationInDays"] == 35  # five weekly copies, and a week of slack
    assert {"transfer/", "exports/"} <= {rule.get("Prefix") for rule in rules}  # the existing rules are kept


CHECK = INGESTION / "check.sh"


def test_the_check_command_is_valid_shell_and_calls_aws_only_to_read() -> None:
    subprocess.run(["bash", "-n", str(CHECK)], check=True)  # noqa: S603, S607
    verbs = re.findall(r"\baws\s+(?:--\S+\s+\S+\s+)*[a-z0-9-]+\s+([a-z0-9-]+)", CHECK.read_text())
    assert verbs
    assert all(verb.startswith(("describe-", "get-", "list-")) for verb in verbs), verbs


def test_the_check_command_looks_at_every_thing_it_promises() -> None:
    text = CHECK.read_text()
    for role in ("metamorph-airflow-task", "metamorph-platform-task"):
        assert role in text
    assert "metamorph-scheduler" in text
    assert "metamorph-mineru-instance" in text  # the role and the instance profile
    for service in ("ecs-tasks.amazonaws.com", "scheduler.amazonaws.com", "ec2.amazonaws.com"):
        assert service in text
    assert "metamorph-ingestion-$name" in text
    assert "for name in shared jobs mineru airflow alerts" in text  # the five stacks, each complete
    for call in ("describe-instances", "describe-services"):
        assert call in text


def test_the_check_command_looks_at_the_minerus_front_door_and_no_longer_at_what_was_retired() -> None:
    text = CHECK.read_text()
    assert "FrontDoorUrl" in text  # the stack's output names the distribution
    assert "list-distributions" in text  # deployed, with its rate limit's web ACL attached
    assert "WebACLId" in text
    for retired in ("metamorph-connector-task", "describe-access-points", "ACCESS_POINTS", "efs", "EFS"):
        assert retired not in text, retired


README = INGESTION / "README.md"


def test_the_readme_names_every_template_and_every_image_tag_the_jobs_stack_takes() -> None:
    text = README.read_text()
    for path in TEMPLATES:
        assert path.name in text, path.name
    for parameter in JOBS["Parameters"]:
        if parameter.endswith("Tag"):
            assert parameter in text, parameter
    assert "check.sh" in text and "waf.sh" in text


def test_the_readme_describes_nothing_that_is_gone() -> None:
    text = README.read_text()
    gone_things = (
        "tunnel.sh", "CAPABILITY_NAMED_IAM", "ssm:StartSession", "Superseded", "Every night", "OjkTag", "BiStatsTag",
        "ReportsTag", "transfer/connector-data", "run_task ops",
    )  # fmt: skip
    for gone in gone_things:
        assert gone not in text, gone
    rows = [line for line in text.splitlines() if line.startswith("| `metamorph-ingestion-")]
    assert len(rows) == 5
    assert not [row for row in rows if "Cloud Map" in row]  # the shared stack no longer makes the namespace
    assert not [row for row in rows if "EFS" in row]


def section(heading: str) -> str:
    """The README's text under one `## ` heading."""
    text = README.read_text()
    start = text.index(f"\n## {heading}") + 1
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


def test_the_readme_describes_the_two_sides_and_what_joins_them() -> None:
    text = section("The two sides")
    for needle in ("collection host", "METAMORPH_SIDE", "collection", "processing", "bundle", "s3://", "_COMPLETE",
                   "ingest_ojk", "backup_connector_data", "load_bundles", "load-pending"):
        assert needle in text, needle
    assert "docs/adr/0001-collection-on-a-residential-host.md" in README.read_text()  # why collection is off AWS


def numbered(heading: str) -> list[str]:
    return re.findall(r"^\d+\. (.*)$", section(heading), re.M)


def test_the_readme_gives_the_cutover_order_and_deletes_nothing_before_the_gate() -> None:
    steps = numbered("The cutover")
    markers = ("hand run", "loaded on AWS", "check.sh", "first scheduled weekday", "retirement")

    assert len(steps) == len(markers)
    for step, marker in zip(steps, markers, strict=True):
        assert marker in step, (marker, step)
    assert "inside MinerU's window" in steps[0]


def test_the_readme_orders_the_retirement_so_no_stack_drops_what_another_still_imports() -> None:
    text = section("The retirement")
    order = [text.index(marker) for marker in
             ("batch-delete-image", "deploy ingestion/jobs", "deploy ingestion/shared", "deploy ingestion/mineru",
              "deploy ingestion/alerts", "aws ssm delete-parameters")]

    assert order == sorted(order)  # the images first (a repository with images cannot be deleted), tasks before EFS
    assert "DeletionPolicy: Retain" in text  # the file system outlives its stack: delete it by hand
    assert "/metamorph/connectors/mineru-url" in text and "/metamorph/mineru/api-key" in text  # one goes, one stays


def test_the_readme_tells_the_collection_hosts_operator_to_sign_in_again_and_how_to_start_mineru_by_hand() -> None:
    text = README.read_text()
    assert "aws sso login" in text
    for setting in ("METAMORPH_AWS_PROFILE", "METAMORPH_BUNDLES_BUCKET", "METAMORPH_OPS_BUCKET"):
        assert setting in text, setting
    assert "aws ec2 start-instances" in section("The window")  # MinerU's hand start
    assert "ec2:StartInstances" in text or "start-instances" in text


def test_the_readme_says_what_a_held_bundle_does() -> None:
    text = section("A held bundle")
    assert "load_bundles" in text and "held" in text and "alert" in text
    assert "no build runs" in text  # the registry build waits for the held bundle's connector, though others loaded
    assert "load-pending" in text


def test_the_compose_airflow_is_given_the_aws_session_the_buckets_and_minerus_address_from_the_env_file() -> None:
    compose = yaml.safe_load((INGESTION.parents[2] / "compose.yaml").read_text())
    environment = compose["services"]["airflow"]["environment"]
    documented = (INGESTION.parents[2] / ".env.example").read_text()

    for key in ("METAMORPH_AWS_CONFIG", "METAMORPH_AWS_PROFILE", "METAMORPH_BUNDLES_BUCKET", "METAMORPH_OPS_BUCKET",
                "METAMORPH_MINERU_URL", "METAMORPH_MINERU_API_KEY"):
        assert key in environment and key in documented, key
    assert environment["METAMORPH_BUNDLES_BUCKET"].startswith("${METAMORPH_BUNDLES_BUCKET")  # from .env, no value
    assert "metamorph-blobs" not in environment["METAMORPH_BUNDLES_BUCKET"]


def test_the_blobs_bucket_expires_uploaded_bundles_after_35_days() -> None:
    (bucket,) = [r for r in FOUNDATION["Resources"].values() if r["Properties"].get("BucketName") == {"Fn::Sub": "metamorph-blobs-${AWS::AccountId}"}]
    rules = bucket["Properties"]["LifecycleConfiguration"]["Rules"]
    (bundles,) = [rule for rule in rules if rule.get("Prefix") == "bundles/"]
    assert bundles["Status"] == "Enabled"
    assert bundles["ExpirationInDays"] == 35  # loaded within the hour; a month to replay one by hand
