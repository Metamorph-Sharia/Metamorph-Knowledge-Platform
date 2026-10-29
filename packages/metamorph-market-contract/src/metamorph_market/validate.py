"""Every problem with a record: its kind's JSON Schema, then the rules a schema can't express."""

from __future__ import annotations

import re

from metamorph_market.codec import to_dict
from metamorph_market.record import (
    Frequency,
    LicensedEntityRecord,
    MarketRecord,
    ReleaseRecord,
    ReportRecord,
    SeriesRecord,
)
from metamorph_market.schema import record_problems

DATE = re.compile(r"\d{4}-\d{2}-\d{2}$")
PERIOD_FORMS = {
    Frequency.MONTHLY: re.compile(r"\d{4}-\d{2}"),
    Frequency.QUARTERLY: re.compile(r"\d{4}-Q\d"),
    Frequency.SEMIANNUAL: re.compile(r"\d{4}-S\d"),
    Frequency.ANNUAL: re.compile(r"\d{4}"),
}


def problems(record: MarketRecord) -> list[str]:
    found = record_problems(to_dict(record))
    if isinstance(record, SeriesRecord):
        return found + _series_problems(record)
    if isinstance(record, ReportRecord):
        return found + _report_problems(record)
    if isinstance(record, ReleaseRecord):
        return found + _release_problems(record)
    return found + _entity_problems(record)


def _report_problems(record: ReportRecord) -> list[str]:
    report = record.report
    if not report.id.startswith(f"{report.issuer}:{report.family}:"):
        return [f"report.id: {report.id!r} is not of issuer {report.issuer!r} and family {report.family!r}"]
    return []


def _release_problems(record: ReleaseRecord) -> list[str]:
    release = record.release
    year = release.published_on[:4]
    if not DATE.match(release.published_on):
        return []  # the schema reports the date
    if not release.id.startswith(f"{release.issuer}:siaran-pers:{year}:"):
        return [f"release.id: {release.id!r} is not of issuer {release.issuer!r} and year {year}"]
    return []


def _entity_problems(record: LicensedEntityRecord) -> list[str]:
    found = []
    entity = record.entity
    if not entity.id.startswith(f"{entity.register}:"):
        found.append(f"entity.id: {entity.id!r} is not on register {entity.register!r}")
    files = {file.sha256 for file in record.files}
    editions: set[str] = set()
    for index, listing in enumerate(record.listings):
        if listing.file not in files:
            found.append(f"listings[{index}].file: {listing.file[:12]}… is not in files")
        if listing.edition in editions:
            found.append(f"listings[{index}].edition: {listing.edition} is listed twice")
        editions.add(listing.edition)
    return found


def _series_problems(record: SeriesRecord) -> list[str]:
    found = []
    series = record.series
    if not series.id.startswith(f"{series.dataset}:"):
        found.append(f"series.id: {series.id!r} is not in dataset {series.dataset!r}")
    files = {file.sha256 for file in record.files}
    periods: set[str] = set()
    for index, observation in enumerate(record.observations):
        if observation.file not in files:
            found.append(f"observations[{index}].file: {observation.file[:12]}… is not in files")
        if not PERIOD_FORMS[series.frequency].fullmatch(observation.period):
            found.append(f"observations[{index}].period: {observation.period} is not {series.frequency}")
        if observation.period in periods:
            found.append(f"observations[{index}].period: {observation.period} is observed twice")
        periods.add(observation.period)
    return found
