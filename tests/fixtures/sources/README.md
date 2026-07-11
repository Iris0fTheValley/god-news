# Source contract fixtures

These files are deterministic inputs for the internal `RawSourceItem` adapter
contracts. They are not recordings of, or claims about, undocumented upstream
payloads. A network-facing adapter must consult the source's current official
contract (or an explicitly authorized observation) and map it into the matching
typed raw model before invoking a normalizer.

No fixture test performs network access or downloads referenced media.
