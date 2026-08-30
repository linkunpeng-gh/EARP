# Mine 3 production-drop fixture

This is Case A's deterministic, machine-readable Golden Fixture. It is deliberately marked
`provisional`: its business terminology, model weights, thresholds, provider contracts and
ranking expectation are working assumptions for implementation, not statements of confirmed
mine operations knowledge.

`published_fixture` is a **test-fixture release label only**. It means the snapshot is hash-locked
for deterministic test import; it is not a domain approval, a production publishing decision, or
permission for an importer to coerce a stored model into `published`.

The ontology fixture contains a minimal import contract compatible with the current Ontology
services: create data domains, then TBox entity/relation types, then ABox entities/facts. The
metric catalog is Fixture metadata because the current ontology TBox has no metric table. T05 must
verify and use this setup rather than silently inventing an alternate mapping.

Prepare owns target-entity semantics. Each evidence requirement has a structured
`case-a-abox-binding/v1` expression and an expected ABox resolution; `capability_fixture.json`
binds only a logical requirement to a Provider. A Capability Resolver receives the resolved target
and must not infer or replace it.

`fixture_hashes.json` fixes SHA-256 hashes over the raw UTF-8 bytes of every executable fixture
file. The manifest and this README are excluded from the aggregate package hash so the manifest
does not create a self-reference. The current package hash is
`f9c9620f34e90c0119464e43cb1f51b4cb9daf63c26ee77e14040068dda35e66`. Run:

```bash
cd apps/earp-server
.venv/bin/python -m pytest tests/test_case_a_fixture_validation.py -q
```

before consuming the fixture. Fixture authors update all affected semantic hashes, raw-byte file
hashes and the package hash atomically in a reviewed release. T05 validates hashes and must never
generate, replace or silently rehash them.

`algorithm_fixture.json` currently specifies an algorithm identity/configuration
(`algorithm_id`, `algorithm_version_id`, `algorithm_config_hash`) but deliberately has no
executable implementation artifact hash (`implementation_artifact.status=not_built`). The
configuration hash must never be substituted for an implementation hash. It cannot support
executable Evaluate or Executable Replay. T11 must release a new fixture version with a
reproducible artifact hash; until then it may be imported only as a specification fixture. The
test validates structure and cross-file references only; it is not the production compiler or
reasoning implementation.
