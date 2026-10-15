"""Failure alerts for every Metamorph task: the task log, plus a webhook when one is configured.

METAMORPH_ALERT_WEBHOOK_URL: a Slack-compatible incoming webhook ({"text": …}). Unset, alerts only go to the log.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from collections.abc import Mapping
from typing import Any

WEBHOOK_TIMEOUT_S = 10

log = logging.getLogger("metamorph.alerts")


def failure_message(context: Mapping[str, Any]) -> str:
    task = context["task_instance"]
    return (
        f"Metamorph: {context['dag'].dag_id}.{task.task_id} failed "
        f"(run {context['run_id']}, try {task.try_number}): {context.get('exception')} — {task.log_url}"
    )


def on_failure(context: Mapping[str, Any]) -> None:
    message = failure_message(context)
    log.error(message)
    url = os.environ.get("METAMORPH_ALERT_WEBHOOK_URL")
    if not url:
        return
    request = urllib.request.Request(
        url, data=json.dumps({"text": message}).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(request, timeout=WEBHOOK_TIMEOUT_S).close()
    except OSError as error:  # an unreachable webhook must not hide the failure it reports
        log.error("alert webhook failed: %s", error)
