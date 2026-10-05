# Living Kanto fidelity matrix

| Subject | FireRed source | Engine rule | Implementation | Automatic check | Real play |
| --- | --- | --- | --- | --- | --- |
| Contract versioning | n/a (engine design) | every persisted object carries contract_version + engine_version | Implemented `contracts/base.py` | Implemented `test_contract_version_enforced` | Incomplete |
| Canonical hashing | n/a | sorted-key JSON, finite numbers only, SHA-256 | Implemented `canonical_json`/`content_hash` | Implemented round-trip + NaN rejection tests | Incomplete |
| Human privacy | engine design (PROJECT_GUIDE privacy boundary) | observations exclude other agents' private state, RNG, hidden stats | Implemented `_assert_no_hidden_leaks` recursive key gate | Implemented `test_privacy_enforcement_rejects_hidden_state` | Incomplete |
| Legal actions | engine design | engine derives legal actions; scope/arg schema validated | Implemented `LegalAction` + `HumanAction` 20-kind gate | Implemented legal-action scope/arg tests | Incomplete |
| Event log | engine design | append-only canonical events, kind gate, 256 KB cap, head hash chain | Implemented `CanonicalEvent` (49 kinds) | Implemented kind-gate + size-cap tests | Incomplete |
| Battle contract | FRLG gen-3 baseline (battle core will adapt `pokemon-showdown` gen3 logic) | phase-gated actions, hidden info excluded | Implemented observation/action/legal-action | Implemented round-trip + kind-gate tests | Incomplete |
| Run metadata | engine design | model usage receipts required for real-model runs | Implemented `RunMetadata`/`ModelUsageRecord` | Implemented nested-validation test | Incomplete |
| Map data | `pret/pokefirered` @ `037335f4…` `data/maps`, `data/layouts` | cartridge layout/warp facts | Incomplete | Incomplete | Incomplete |
| Sprites | `graphics/pokemon`, `gfx/ui/pokemon/` | original assets only, no redraws | Incomplete | Incomplete | Incomplete |
| Stats/XP/catching | FRLG constants | cartridge formulas, no Showdown-only mechanics | Incomplete | Incomplete | Incomplete |
