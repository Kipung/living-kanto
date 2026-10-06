# Individual aspirations and commitments

The first implementation adds private, persistent `individual_life` records without changing existing identities, homes, relationships, roles, goals, or achievements. Existing saves require no destructive conversion. Before a person reflects, the inspector falls back to their existing goal and labels the missing reflection.

Local models may choose `set_aspiration`, `set_commitment`, `complete_commitment`, or `abandon_commitment`, using the existing staged numbered decision protocol. Each accepts at most 200 characters and records the model explanation and provenance. A person must finish or abandon an active commitment before replacing it. Reflection never awards money, badges, knowledge, or relationship improvements. Completion is explicitly a self-reported assessment, not an independently verified achievement.

Private observations include the aspiration, current commitment, up to eight recent accepted decisions, and up to eight archived commitments. The commitment captures baseline money, badges, caught species, and location. Subsequent observations compute factual differences from that baseline. Repeated identical action/argument pairs produce an advisory notice; the engine does not substitute a different action or script a routine.

The shared-clock dependency token includes the life record. A new reflection invalidates older proposals for the same person. Life changes and recent choices are recorded in the existing atomic, hashed event transaction and replay normally. They do not advance the shared clock separately. Existing scheduling, movement, battles, services and pause/retry behavior remain authoritative.

The observer inspector displays aspiration, reason, current commitment, status and reflection. Private facts are supplied only to their owner; these fields are visible to the observer just like existing private memories.

Deployment: Spark 1, `/home/kip/living-kanto-deploy/living-kanto`; rollback save and prior source are in `backups/individual-life/`. A tested isolated deployment source is under `work/individual-life-runtime`. The canonical repository contains the same targeted edits while retaining unrelated ongoing development.

Limits: this provides continuity and reflection, not a complete motivation architecture. It does not manufacture unique biographies, assign new occupations, verify free-text commitment completion, add journal-writing mechanics, or establish that characters have subjective experiences. Longer live observation is needed to assess whether it reduces repetitive conversations and produces distinct behavior. Runtime throughput may change because the prompts and persisted life records are larger.
