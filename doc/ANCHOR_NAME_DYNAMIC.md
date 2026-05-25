## Dynamic anchor names

This service now resolves anchor names dynamically:

- Prefer validated anchor names in `ops.endpoint_names`.
- If missing, query the nearest stedsnavn record at request time.

### Performance implications

- Each uncached lookup performs a spatial query against stedsnavn. Cost depends on spatial index quality and search radius.
- A short in-memory TTL cache is used to reduce repeated lookups for the same anchor.
- Large batch requests can still generate many queries; consider batching or prefetching if you hit performance limits.

### stiflyt-db removal checklist

- Remove the migration that precomputes anchor names.
- Remove any stedsnavn name assignment logic that only exists to support that migration.
- Keep stedsnavn tables available in the database for runtime queries from this service.

### Notes

- Route-specific overrides still work via `ops.endpoint_names` when a `rutenummer` is provided.
- Global anchor names (stored with `rutenummer = NULL`) apply to all routes sharing the anchor unless overridden.
