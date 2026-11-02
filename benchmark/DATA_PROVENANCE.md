# Data provenance

CleanBench was constructed by reviewing real relational and spreadsheet tables
collected from public sources. The released corpus contains 500 relational
tables (`pbi_500`) and 500 spreadsheet tables (`bing21_500`). Dataset identifiers
and source basenames are preserved so labels remain traceable to the frozen
tables.

The cell labels, row/relation labels, exclusion scopes, and legacy immunity
records are copied byte-for-byte from the final construction artifacts. The
cell-label SHA-256 is:

```text
941c91fd13eee4a2ab7169e9a9fa3b833e9913530843719f91984e079011f3a2
```

The source CSVs match the `dirty_sha256` entries in the frozen source manifest
used for the paper. The release includes their names, dimensions, SHA-256
digests, and original-row maps. The public archive replaces internal metadata
with a portable manifest; it does not alter the CSV bytes. The archive does not
include repaired/clean reference tables, intermediate model responses, private
workspaces, or experiment artifacts.

The project code's MIT license covers project-authored software. It does not
grant new rights in third-party table content or override the terms of original
sources. No blanket third-party data license is asserted here. Preserve source
identifiers and any notices in the tables when redistributing them.
