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


def run_password_check(authorization: str | None, sha256: str = PASSWORD_SHA256) -> dict[str, Any]:
    headers = {} if authorization is None else {"authorization": {"value": authorization}}
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
    assert behavior["ViewerProtocolPolicy"] == "https-only"
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


def test_the_airflow_waf_script_is_beside_the_templates_and_valid_shell() -> None:
    script = INGESTION / "waf.sh"
    text = script.read_text()
    assert "--scope CLOUDFRONT" in text and "us-east-1" in text and "Key=Owner,Value=project3" in text
    assert "metamorph-airflow" in text
    subprocess.run(["bash", "-n", str(script)], check=True)  # noqa: S603, S607


def test_the_tunnel_is_gone() -> None:
    assert not (INGESTION / "tunnel.sh").exists()


# --- MinerU: one scheduled instance behind an internal load balancer (mineru.yaml) ---------------------------------

MINERU = template("mineru.yaml")


def minerus(of_type: str) -> dict[str, dict]:
    return shared_resources(of_type, MINERU)


def window(name: str) -> tuple[int, str]:
    """A window parameter's default, cron(minute hour day-of-month * ? *): minutes after midnight UTC, and its day-of-month."""
    expression = re.fullmatch(r"cron\((.*)\)", MINERU["Parameters"][name]["Default"])
    minute, hour, day_of_month, *_ = expression.group(1).split()
    return int(hour) * 60 + int(minute), day_of_month


def job_start(job: ConnectorJob) -> int:
    minute, hour = job.schedule.split()[:2]
    return int(hour) * 60 + int(minute)


def test_the_window_is_a_start_a_daily_end_and_a_later_end_on_the_first() -> None:
    start, start_days = window("WindowStart")
    end, end_days = window("WindowEnd")
    monthly_end, monthly_days = window("MonthlyWindowEnd")

    assert start_days == "*"  # the instance starts every day
    assert (end_days, monthly_days) == ("2-31", "1")  # the two stops share the days of the month between them
    assert (start, end, monthly_end) == (20, 3 * 60 + 15, 4 * 60 + 30)


def test_every_job_that_reads_pdfs_starts_inside_the_window(jobs) -> None:
    start, _ = window("WindowStart")
    end, _ = window("WindowEnd")
    monthly_end, _ = window("MonthlyWindowEnd")
    readers = [job for job in jobs if job.reads_pdfs]

    assert readers
    for job in readers:
        day_of_month = job.schedule.split()[2]
        # a job that runs only on the 1st has until the monthly end; any other job starts before the daily end
        assert start <= job_start(job) < (monthly_end if day_of_month == "1" else end), job.dag_id


def test_the_weekly_backup_starts_after_the_last_stop() -> None:
    from metamorph_pipeline.jobs import backup_job

    assert job_start(backup_job()) > window("MonthlyWindowEnd")[0]  # the Sunday it runs may be the 1st


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
    assert nic["GroupSet"] == [{"Fn::ImportValue": "metamorph-sg-gpu-host"}]


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
    network = props["NetworkConfiguration"]["AwsvpcConfiguration"]

    assert props["LaunchType"] == "EC2"
    assert props["DesiredCount"] == 1  # it places itself whenever the instance runs
    assert task["Properties"]["RequiresCompatibilities"] == ["EC2"]
    assert (balanced["ContainerName"], balanced["ContainerPort"]) == ("main", 8010)
    assert network["SecurityGroups"] == [{"Fn::ImportValue": "metamorph-sg-mineru"}]
    assert "ServiceRegistries" not in props


def test_the_load_balancer_is_internal_and_checks_mineru_s_health_endpoint() -> None:
    ((_, balancer),) = minerus("AWS::ElasticLoadBalancingV2::LoadBalancer").items()
    (target,) = minerus("AWS::ElasticLoadBalancingV2::TargetGroup").values()
    (listener,) = minerus("AWS::ElasticLoadBalancingV2::Listener").values()
    (task,) = minerus("AWS::ECS::TaskDefinition").values()
    (container,) = task["Properties"]["ContainerDefinitions"]

    assert balancer["Properties"]["Scheme"] == "internal"
    assert balancer["Properties"]["SecurityGroups"] == [{"Fn::ImportValue": "metamorph-sg-mineru-lb"}]
    assert target["Properties"]["TargetType"] == "ip"  # the task has its own interface (awsvpc)
    assert target["Properties"]["HealthCheckPath"] == "/v1/health"
    assert "/v1/health" in container["HealthCheck"]["Command"][-1]
    assert listener["Properties"]["Port"] == 8010  # the port the load balancer group admits from the jobs
    for resource in (balancer, target):
        assert {"Key": "Owner", "Value": "project3"} in resource["Properties"]["Tags"]


def test_the_connectors_mineru_url_is_written_from_the_load_balancer_s_address() -> None:
    ((_, setting),) = minerus("AWS::SSM::Parameter").items()
    props = setting["Properties"]

    assert props["Name"] == "/metamorph/connectors/mineru-url"
    assert props["Value"] == {"Fn::Sub": "http://${LoadBalancer.DNSName}:8010"}
    assert props["Tags"] == {"Owner": "project3"}


def test_three_schedules_start_and_stop_the_instance_with_the_scheduler_role() -> None:
    bodies = minerus("AWS::Scheduler::Schedule").values()
    schedules = {body["Properties"]["ScheduleExpression"]["Ref"]: body["Properties"] for body in bodies}

    assert MINERU["Parameters"]["SchedulerRole"]["Default"] == "metamorph-scheduler"
    assert set(schedules) == {"WindowStart", "WindowEnd", "MonthlyWindowEnd"}
    assert schedules["WindowStart"]["Target"]["Arn"] == "arn:aws:scheduler:::aws-sdk:ec2:startInstances"
    for stop in ("WindowEnd", "MonthlyWindowEnd"):
        assert schedules[stop]["Target"]["Arn"] == "arn:aws:scheduler:::aws-sdk:ec2:stopInstances"
    for props in schedules.values():
        assert props["ScheduleExpressionTimezone"] == "UTC"
        assert props["Target"]["RoleArn"] == {"Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/${SchedulerRole}"}
        assert props["Target"]["Input"] == {"Fn::Sub": '{"InstanceIds": ["${Instance}"]}'}
