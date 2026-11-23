"""The ingestion stacks as written in the templates (deploy/aws/ingestion), checked offline against the DAG jobs and
the live core. The account lets us create no IAM resource and no Cloud Map; every create must carry Owner=project3
(docs/aws-ingestion-permissions.md)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from metamorph_pipeline.jobs import ConnectorJob, ingest_jobs

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
    *, exit_code: int | None, cluster: str = CLUSTER, family: str = "metamorph-bi-connector", status: str = "STOPPED"
) -> dict[str, Any]:
    container: dict[str, Any] = {"name": "app"} if exit_code is None else {"name": "app", "exitCode": exit_code}
    return {
        "source": "aws.ecs",
        "detail-type": "ECS Task State Change",
        "detail": {
            "clusterArn": cluster,
            "lastStatus": status,
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


def test_the_alert_rule_ignores_a_clean_exit() -> None:
    assert not matches(alert_pattern(), stopped(exit_code=0))


def test_the_alert_rule_ignores_tasks_that_are_not_stopped() -> None:
    assert not matches(alert_pattern(), stopped(exit_code=1, status="RUNNING"))


def test_the_alert_rule_ignores_other_clusters_and_families() -> None:
    other_cluster = CLUSTER.replace("/metamorph", "/mira")
    assert not matches(alert_pattern(), stopped(exit_code=1, cluster=other_cluster))
    assert not matches(alert_pattern(), stopped(exit_code=1, family="mira-api"))


def test_the_alert_rule_sends_to_the_email_topic() -> None:
    (rule,) = resources("alerts.yaml", "AWS::Events::Rule")
    (target,) = rule["Properties"]["Targets"]
    assert target["Arn"] == {"Ref": "Topic"}
    (subscription,) = template("alerts.yaml")["Resources"]["Topic"]["Properties"]["Subscription"]
    assert subscription["Protocol"] == "email"
    assert subscription["Endpoint"] == {"Ref": "AlertEmail"}


def test_the_topic_policy_lets_only_eventbridge_publish() -> None:
    (policy,) = resources("alerts.yaml", "AWS::SNS::TopicPolicy")
    (statement,) = policy["Properties"]["PolicyDocument"]["Statement"]
    assert statement["Principal"] == {"Service": "events.amazonaws.com"}
    assert statement["Action"] == "sns:Publish"


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

# Images that live outside the ingestion layer: the core's platform repository, and Retrieval's own stack.
NOT_INGESTION_IMAGES = {"metamorph-platform:dev", "metamorph/retrieval:dev"}
# Resource types that take tags, and the property that holds them.
TAGGED = {
    "AWS::EC2::SecurityGroup": "Tags",
    "AWS::EFS::FileSystem": "FileSystemTags",
    "AWS::EFS::AccessPoint": "AccessPointTags",
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


@pytest.mark.xfail(
    strict=False,
    reason="airflow, jobs and mineru still declare roles until tickets 03-05 land; ticket 07 removes this mark",
)
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


def test_every_connector_has_its_own_access_point(jobs) -> None:
    points = {name: body["Properties"] for name, body in shared_resources("AWS::EFS::AccessPoint").items()}
    by_path = {p["RootDirectory"]["Path"]: name for name, p in points.items()}
    exports = exported(SHARED)
    connectors = {}
    for job in jobs:
        data = next(m.target for m in job.mounts if m.target.startswith("/workspace/"))
        connectors[job.connector] = data.removeprefix("/workspace")  # /OJK-Source-Connector/data
    assert len(connectors) == 9
    for connector, path in connectors.items():
        assert path in by_path, f"no access point for {connector} at {path}"
        assert exports.get(f"metamorph-efs-{connector}-data") == by_path[path]
    assert "/bundles" in by_path
    assert exports.get("metamorph-efs-bundles") == by_path["/bundles"]
    assert len(points) == 10  # nine connectors and bundles: no credentials access point (JDIH needs none)


def test_every_access_point_is_owned_by_the_connectors_user() -> None:
    for body in shared_resources("AWS::EFS::AccessPoint").values():
        assert body["Properties"]["PosixUser"] == {"Uid": "1000", "Gid": "1000"}
        assert body["Properties"]["RootDirectory"]["CreationInfo"]["OwnerUid"] == "1000"


def test_the_file_system_is_tagged_at_creation_with_owner_and_project() -> None:
    (files,) = shared_resources("AWS::EFS::FileSystem").values()
    tags = {tag["Key"]: tag["Value"] for tag in files["Properties"]["FileSystemTags"]}
    assert tags["Owner"] == "project3"
    assert tags["Project"] == "metamorph"
    assert files["Properties"]["Encrypted"] is True


def test_every_resource_that_takes_tags_carries_owner(jobs) -> None:
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


def test_every_image_a_dag_runs_has_a_scanned_immutable_repository_keeping_ten(jobs) -> None:
    repositories = {
        body["Properties"]["RepositoryName"]: body["Properties"]
        for body in shared_resources("AWS::ECR::Repository").values()
    }
    images = {job.image.rsplit(":", 1)[0] for job in jobs} - {i.rsplit(":", 1)[0] for i in NOT_INGESTION_IMAGES}
    assert len(images) == 9
    wanted = images | {"metamorph/airflow", "metamorph/mineru", "metamorph/ops"}
    assert set(repositories) == wanted
    for properties in repositories.values():
        assert properties["ImageScanningConfiguration"] == {"ScanOnPush": True}
        assert properties["ImageTagMutability"] == "IMMUTABLE"
        policy = yaml.safe_load(properties["LifecyclePolicy"]["LifecyclePolicyText"])
        (rule,) = policy["rules"]
        assert rule["selection"]["countNumber"] == 10
        assert rule["action"]["type"] == "expire"


def test_the_database_group_accepts_airflow_and_the_tasks() -> None:
    sources = {
        body["Properties"]["SourceSecurityGroupId"]["Ref"]
        for body in shared_resources("AWS::EC2::SecurityGroupIngress").values()
        if body["Properties"]["GroupId"] == {"Fn::ImportValue": "metamorph-sg-database"}
    }
    assert sources == {"AirflowGroup", "JobsGroup"}
