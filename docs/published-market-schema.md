# The `published_market` schema: the read contract for market data

The Knowledge and Retrieval layer reads market data **only** from `published_market`. It never reads `market` or `ingest`. Everything here is already derived:
- **standing:** whether each license is on its register's newest edition, and when it left;
- **companies:** a registration and the license that followed it, joined into one company;
- **edition changes:** what each edition added and removed.

What the registers say comes from the market connectors under the [market contract](../packages/metamorph-market-contract/MARKET_CONTRACT.md). The plan behind it is [market-data-layer-plan.md](market-data-layer-plan.md).

## How it is refreshed

`metamorph market publish` rebuilds the whole schema in one transaction, from every record the connectors' latest snapshots still send. Readers see the old schema or the new one, never a mix. A register holds hundreds of records, and a company or a standing depends on every record of its register, so there is no per-row change log. `register.published_at` says when the schema was last rebuilt: re-read after it changes.

## Tables

| Table | One row per | Columns |
|---|---|---|
| `register` | register of licensed entities | `id` (`ojk:lpbbti`), `issuer`, `name`, `governed_by[]` (regulation IDs in `published.document`), `newest_edition`, `editions`, `published_at` |
| `edition` | published edition of a register | `register`, `edition` (the date it stands at), `listed`, `joined` (since the edition before), `left`, `sha256`, `source_url`, `storage_key` (the edition's PDF in the object store) |
| `company` | company: the records listed under one legal name | `id` (its newest record's ID), `register`, `legal_name` (as last listed), `names[]` (every other legal and platform name), `business_type`, `status`, `first_listed`, `left_after` |
| `entity` | license or registration | `id`, `company_id`, `register`, `kind`, `license_number`, `license_date`, `legal_name`, `names[]`, `business_type`, `website`, `channels[]`, `first_listed`, `last_listed`, `on_newest_list`, `left_after`, `review_notes[]` |
| `listing` | edition's row for an entity | `entity_id`, `edition`, `legal_name` (as listed then), `page`, `row_number`, `cells` (the row under its printed headers) |

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

## Identifiers

- **`entity.id`** is `{register}:{license key}`, e.g. `ojk:lpbbti:kep-49-d.05-2017`. The key comes from the license number, ignoring case, spacing and the dash's shape.
- **`company.id`** is the ID of its newest record. A company registered and later licensed takes its license's ID.

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
