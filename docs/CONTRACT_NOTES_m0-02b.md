# Lead contracts follow-up: rename chain-link field prior_state_hash -> previous_head.
# This is a shared-contract fix per operator review: the old name conflated the
# event-chain link with WorldState content hashes. Workers must not edit contracts;
# this file documents the mechanical rename they must adopt in store/tests.
#
# In work/engine, apply to server/tests/helpers.py and any store code:
#   make_event(..., previous_head=...)   (was: prior=... / prior_state_hash=...)
#   CanonicalEvent.previous_head          (was: prior_state_hash)
#   StateUpdate.previous_head             (was: prior_state_hash)
#
# Semantics: previous_head = event_hash of the immediately preceding CanonicalEvent
# in this run's chain (genesis uses "0"*64). It is NOT a WorldState.state_hash and
# must never be compared equal to one. Keep the two hash chains separate:
#   - event chain: CanonicalEvent.event_hash / previous_head
#   - world state: WorldState.state_hash / compute_state_hash(), StateUpdate.state_hash
#
# Replay acceptance (operator-mandated): replay must reconstruct WorldState objects
# by applying StateUpdate deltas and compare the replayed state to the stored
# post-event snapshot AND its recomputed compute_state_hash() — not just the chain head.
