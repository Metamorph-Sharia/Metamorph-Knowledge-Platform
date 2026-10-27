"""Companies: the records on one register that were listed under the same legal name.

Until October 2021 OJK listed a provider first as registered (a letter, S-…) and then as licensed (a decision,
KEP-…): two numbers, so two records, for one company. Names are compared without case, spacing or punctuation,
and a company's names include every name it was listed under, so a renamed company stays one.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from metamorph_market import LicenseKind

from metamorph_platform.domain.market.history import HeldLicense, standing


class CompanyStatus(StrEnum):
    LICENSED = "licensed"  # its newest record is a license on the newest edition
    REGISTERED = "registered"  # its newest record is a registration on the newest edition
    LEFT = "left"  # not on the newest edition


@dataclass(frozen=True)
class Company:
    id: str  # its newest record's ID: the license, once it was licensed
    register: str
    members: tuple[str, ...]  # its records' IDs, oldest first
    status: CompanyStatus
    first_listed: date
    left_after: date | None


def companies(licenses: Sequence[HeldLicense], newest: date) -> list[Company]:
    groups = _groups_by_name(licenses)
    return [_company(sorted(group, key=_listed_order), newest) for group in groups]


def _groups_by_name(licenses: Sequence[HeldLicense]) -> list[list[HeldLicense]]:
    """Records sharing any name on the same register end in one group, through any chain of names."""
    parent = list(range(len(licenses)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    first_with: dict[tuple[str, str], int] = {}
    for index, license_ in enumerate(licenses):
        for name in license_.legal_names:
            key = (license_.register, _comparable(name))
            if not key[1]:
                continue
            if key in first_with:
                parent[root(index)] = root(first_with[key])
            else:
                first_with[key] = index
    groups: dict[int, list[HeldLicense]] = {}
    for index, license_ in enumerate(licenses):
        groups.setdefault(root(index), []).append(license_)
    return list(groups.values())


def _company(members: list[HeldLicense], newest: date) -> Company:
    latest = members[-1]
    latest_standing = standing(latest, newest)
    if not latest_standing.on_newest_list:
        status = CompanyStatus.LEFT
    elif latest.kind is LicenseKind.REGISTRATION:
        status = CompanyStatus.REGISTERED
    else:
        status = CompanyStatus.LICENSED
    return Company(
        id=latest.id,
        register=latest.register,
        members=tuple(member.id for member in members),
        status=status,
        first_listed=members[0].editions[0],
        left_after=latest_standing.left_after,
    )


def _listed_order(license_: HeldLicense) -> tuple[date, date, str]:
    return license_.editions[-1], license_.editions[0], license_.id


def _comparable(name: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", name.lower()))
