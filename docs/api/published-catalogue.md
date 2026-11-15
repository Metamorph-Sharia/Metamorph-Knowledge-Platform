# The published catalogue: `/api/v1/published`

For services that list what the platform publishes, such as MIRA's API (its regulatory catalogue in Search). It reads
only the `published` schema ([published-schema.md](../published-schema.md)): a document that is held back by the
publish gate, suppressed or never published never appears. The curation API's own reads (`/api/v1/documents`,
`/api/v1/series`) are for curators and see every state; this is not that.

## Access

- **Network.** The API sits behind an internal load balancer. A client's security group is given to the API stack as
  `CatalogueClientGroup` (deploy/aws/api.yaml), and its address is in Parameter Store at `/metamorph/api/url`.
- **Token.** Each client has its own, sent as `Authorization: Bearer <token>`. `metamorph client token NAME` makes one,
  prints it once, and prints the entry to add to `/metamorph/api/clients` (`METAMORPH_API_CLIENTS`): the client's name
  and the token's SHA-256. The token itself is kept only by the client. A client token reads the published catalogue
  and nothing else; a curator's session token doesn't open it, and a client token doesn't open curation.
- To revoke a client, remove its entry and restart the API (`aws ecs update-service … --force-new-deployment`).

## `GET /api/v1/published/regulations`

Every published regulation the filters leave, newest first, 25 to a page (`limit`, at most 100).

| Parameter | Matches |
| --- | --- |
| `q` | Words in the citation, title, an alias or the ID; every word must match (`pojk 47/2020`, `pembiayaan syariah`) |
| `issuer`, `family`, `year`, `status`, `kind` | Exactly (`ojk`, `pojk`, `2020`, `in_force`, `regulation`) |
| `cursor` | The `next_cursor` of the page before; leave it out for the first page |

```json
{"entries": [{"id": "ojk:pojk:2020:47", "citation": "POJK 47/POJK.05/2020", "title": "PERIZINAN USAHA …",
              "kind": "regulation", "issuer": "ojk", "family": "pojk", "number": "47", "year": 2020,
              "status": "in_force", "promulgated_on": "2020-11-25", "effective_on": "2020-11-26"}],
 "total": 1240, "next_cursor": "MjAyMC0xMS0yNXxvams6cG9qazoyMDIwOjQ3"}
```

- **Newest first** is by the day the regulation was made: promulgated, else enacted, else the first day of the year its
  number names, else the day it takes effect. A regulation with none of these comes last. So a regulation that takes
  effect years after it was made is listed with the year it was made.
- `year` is the year its number names. `promulgated_on` and `effective_on` are kept apart, either may be null.
- Pages are keyset-paginated: a page stays right while documents are published between two requests. A cursor this
  catalogue didn't give answers `422 {"error": "invalid"}`.
- The `id` is the platform's canonical ID. MIRA's references prefix it: `doc:ojk:pojk:2020:47`.

## `GET /api/v1/published/facets`

The same filters, and what each would leave: `total`, and `issuers`, `families`, `years` (newest first), `statuses`
and `kinds`, each a list of `{"value", "count"}`. Each facet is counted with every other filter applied but its own,
so its counts say what choosing a value would show.

## Errors

`401 {"error": "unauthorized"}` without a client's token; `422 {"error": "invalid"}` for a bad cursor or parameter.
