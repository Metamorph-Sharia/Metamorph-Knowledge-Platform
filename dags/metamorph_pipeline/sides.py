"""Which side an Airflow is on, and so which DAGs it builds (docs/adr/0001-collection-on-a-residential-host.md).

Collection runs on the collection host, processing on AWS; each has its own Airflow, and both read the one `dags/`
folder. METAMORPH_SIDE tells an Airflow which it is. Each DAG module declares `SIDE = Side.X` at its top and builds
its DAGs only when `builds_here(SIDE)`. No Airflow import, so it is tested on its own.
"""

from __future__ import annotations

import os
from enum import StrEnum

SETTING = "METAMORPH_SIDE"


class Side(StrEnum):
    COLLECTION = "collection"  # the ingest DAGs and the connector-data backup
    PROCESSING = "processing"  # load, registry build, market publish, the indexes, health


def side_from(value: str | None) -> Side:
    try:
        return Side(value)
    except ValueError:
        values = " or ".join(side.value for side in Side)
        raise RuntimeError(f"{SETTING} is {value!r}: {values}") from None


def builds_here(dag_side: Side) -> bool:
    """Whether this Airflow builds a DAG of `dag_side`. A missing or unknown setting fails the import."""
    return dag_side is side_from(os.environ.get(SETTING))
