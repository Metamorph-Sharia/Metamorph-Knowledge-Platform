"""The ingestion stacks as written in the templates (deploy/aws/ingestion). Offline: no AWS access."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

INGESTION = Path(__file__).parents[1] / "deploy/aws/ingestion"

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
