# The `published_market` schema: the read contract for market data

The Knowledge and Retrieval layer reads market data **only** from `published_market`. It never reads `market` or `ingest`. Everything here is already derived:
- **standing:** whether each license is on its register's newest edition, and when it left;
- **companies:** a registration and the license that followed it, joined into one company;
- **edition changes:** what each edition added and removed;
- **statistics:** each dataset linked to the regulations that govern its industry, and each series with its periods: months, quarters, half-years or years.

What the registers and statistics say comes from the market connectors under the [market contract](../packages/metamorph-market-contract/MARKET_CONTRACT.md): `ojk-register` for the register, `ojk-stats` for OJK's portal statistics, `bi-stats` for BI's SEKI tables and `bps-stats` for BPS's dynamic tables. The plan behind it is [market-data-layer-plan.md](market-data-layer-plan.md).

## How it is refreshed

`metamorph market publish` rebuilds the whole schema in one transaction, registers and statistics together, from every record the connectors' latest snapshots still send. Readers see the old schema or the new one, never a mix. A register holds hundreds of records, and a company or a standing depends on every record of its register, so there is no per-row change log. `register.published_at` says when the schema was last rebuilt: re-read after it changes. BPS's connector sends only the tables BPS changed, each whole; the others stay as last loaded.

## Tables

| Table | One row per | Columns |
|---|---|---|
| `register` | register of licensed entities | `id` (`ojk:lpbbti`), `issuer`, `name`, `governed_by[]` (regulation IDs in `published.document`), `newest_edition`, `editions`, `published_at` |
| `edition` | published edition of a register | `register`, `edition` (the date it stands at), `listed`, `joined` (since the edition before), `left`, `sha256`, `source_url`, `storage_key` (the edition's PDF in the object store) |
| `company` | company: the records listed under one legal name | `id` (its newest record's ID), `register`, `legal_name` (as last listed), `names[]` (every other legal and platform name), `business_type`, `status`, `first_listed`, `left_after` |
| `entity` | license or registration | `id`, `company_id`, `register`, `kind`, `license_number`, `license_date`, `legal_name`, `names[]`, `business_type`, `website`, `channels[]`, `first_listed`, `last_listed`, `on_newest_list`, `left_after`, `review_notes[]` |
| `listing` | edition's row for an entity | `entity_id`, `edition`, `legal_name` (as listed then), `page`, `row_number`, `cells` (the row under its printed headers) |
| `dataset` | one of a source's tables (a portal cube, a SEKI table, a BPS table) | `id` (`ojk:portal:bu_syariah_posisikeuangan`, `bi:seki:tabel1_1`, `bps:table:2263`), `source` (`ojk:portal`, `bi:seki`, `bps:table`), `industry` (null for a macro dataset), `group`, `metric` (as the source names them), `register` (its industry's register, if any), `governed_by[]`, `series`, `first_period`, `last_period`, `updated` (the source's last update), `url` (the page that shows it), `citation` (how the source asks to be cited), `published_at` |
| `series` | one statistic over time | `id`, `dataset`, `measure`, `label` (the measure and its members, e.g. `Posisi Keuangan: 003. 1. Kas dan Setara Kas`), `dimensions` (`[{name, key, label}]`), `frequency` (`monthly`, `quarterly`, `semiannual`, `annual`), `unit` (as the source states it, or null), `first_period`, `last_period`, `observations` |
| `observation` | a series' value for one period | `series_id`, `period` (the period's first day: `2026-Q2` is `2026-04-01`), `value` (as the source gives it), `provisional` (the source marks the period so, e.g. SEKI's `Aug*`), `storage_key` (the answer or workbook it was read from) |

## Values

- **`entity.kind`:**
  - `license`: berizin, granted by a decision (`KEP-49/D.05/2017`);
  - `registration`: terdaftar, confirmed by a letter (`S-735/NB.213/2019`), not yet licensed. OJK's fintech-lending list held registrations until October 2021;
  - `unknown`: the number has neither form.
- **`company.status`:**
  - `licensed`: its newest record is a license on the newest edition;
  - `registered`: its newest record is a registration on the newest edition;
  - `left`: it isn't on the newest edition. `left_after` is the last edition that listed it.
- **`business_type`:** `sharia`, `conventional` or `unknown`. A company's is its newest record's.
- **`channels`:** `android`, `ios`.
- **`review_notes`:** what is unclear about an entity, such as "business type unknown". A note never holds an entity back. Only a record the contract rejects is kept out, and it waits in the review queue.
- **`observation.value`:** as the source gives it, never rescaled. The portal gives amounts in whole rupiah, counts as counts, and ratios as it shows them. A series' `measure` and its dataset's `metric` say what is counted.
- **`dataset.governed_by`:** its industry's regulations, curated in `market.industry`:
  - a register's industry takes the register's regulations, e.g. LPBBTI takes `ojk:lpbbti`'s;
  - sharia commercial banks: `id:uu:2008:21`, `ojk:pojk:2022:16`, `ojk:pojk:2023:12`;
  - sharia BPRs: `id:uu:2008:21`, `ojk:pojk:2024:7`.

  An industry without a link is published with none, and so is a macro dataset (`industry` null).
- **`dataset.citation`:** quote it with the figure. BPS's terms also ask for the table's title, the date it was accessed and a direct link: the dataset's `metric`, `published_at` and `url`.
- **`series.frequency`:** read `period` with it. A SEKI row with a year's own figure has two series, e.g. `…:quarterly:row=1` and `…:annual:row=1`; the year's figure is BI's, never a sum made here.

## Identifiers

- **`entity.id`** is `{register}:{license key}`, e.g. `ojk:lpbbti:kep-49-d.05-2017`. The key comes from the license number, ignoring case, spacing and the dash's shape.
- **`company.id`** is the ID of its newest record. A company registered and later licensed takes its license's ID.

- **`series.id`** is the dataset, then what the source keys the series by, never a label:
  - OJK's portal: `{dataset}:{measure}:{dimension=key…}`, e.g. `ojk:portal:bu_syariah_posisikeuangan:posisi-keuangan:akun=110001010100`. A renamed account keeps its series;
  - SEKI: `{dataset}:{frequency}:row={BI's row number}`, e.g. `bi:seki:tabel1_1:monthly:row=1` (M2). SEKI has no other key; a renumbered row is reported by the connector;
  - BPS: `{dataset}:{frequency}:vervar={row}[:turvar={derived}]`, e.g. `bps:table:2263:monthly:vervar=1100` (Aceh), by BPS's IDs.

**How records join into a company:** records on the same register join when they were listed under the same legal name in any edition, ignoring case, spacing and punctuation. On OJK's fintech-lending list, 77 registrations joined the license that followed. No registration matched two licenses, and none overlapped its license in time.

## Examples

The market today, by business type:

```sql
SELECT business_type, count(*) FROM published_market.company WHERE status = 'licensed' GROUP BY business_type;
```

How the market changed, edition by edition:

```sql
SELECT edition, listed, joined, "left" FROM published_market.edition WHERE register = 'ojk:lpbbti' ORDER BY edition;
```

A company's history: its registration, its license, and the regulations governing its register:

```sql
SELECT c.legal_name, e.kind, e.license_number, e.first_listed, e.last_listed, r.governed_by
FROM published_market.company c
JOIN published_market.entity e ON e.company_id = c.id
JOIN published_market.register r ON r.id = c.register
WHERE c.legal_name ILIKE '%fintech bina bangsa%'
ORDER BY e.first_listed;
```

Sharia commercial banks' balance sheet, month by month, for one account:

```sql
SELECT o.period, o.value
FROM published_market.series s JOIN published_market.observation o ON o.series_id = s.id
WHERE s.dataset = 'ojk:portal:bu_syariah_posisikeuangan' AND s.label ILIKE '%kas dan setara kas%'
ORDER BY o.period;
```

Broad money (M2) by month, with BI's provisional marks and the citation to quote:

```sql
SELECT o.period, o.value, o.provisional, s.unit, d.citation
FROM published_market.series s
JOIN published_market.dataset d ON d.id = s.dataset
JOIN published_market.observation o ON o.series_id = s.id
WHERE s.id = 'bi:seki:tabel1_1:monthly:row=1'
ORDER BY o.period DESC LIMIT 12;
```

The statistics for an industry, beside its licensed companies and the regulations that govern both:

```sql
SELECT d.metric, d.first_period, d.last_period, d.governed_by
FROM published_market.dataset d
WHERE d.register = 'ojk:lpbbti' AND d.industry ILIKE '%syariah%'
ORDER BY d.metric;
```
