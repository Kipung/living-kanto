# Parallel people, shared world time

The local human model reports `RadixArk/Qwen3.8-27B-NVFP4`, served as `qwen38`. One model server answers independent requests for 100 humans. Each human's memories, goals, observations and Pokémon belong to that individual; the model does not receive a single omniscient world-director prompt. Pokémon behavior remains in the rules engine.

Production scheduling uses a bounded queue of independent human decisions. The live configuration is four concurrent requests, within the model server's reported eight-request limit. That is a request limit, not a requirement to load four model copies. Accepted actions commit atomically in the rules engine. Unrelated changes elsewhere in the world must not invalidate a person's decision merely because the global save version increased; relevant actor, target and battle changes still require re-observation.

Everyone uses the same integer simulated time. Movement is an accepted, persistent intention whose physical steps occur as that clock advances. Two people walking for ten seconds overlap within the same ten-second interval. A slow model response must not block another person's accepted journey. Work and rest also have deadlines on this clock. Battle input from the user pauses advancement as required by the project guide.

At 1×, the scheduler aims for one world second per real second. At 5× and 20× it requests the corresponding shared pace. Processing limits may make the world slower; elapsed time must never be reported independently per character. Fastest advances through scheduled engine work and may wait when only model requests are pending. Pause stops advancement and rejects late decisions from the cancelled generation. Restart begins paused and does not simulate time spent offline.

The observer animates only recorded traversal. Thinking, talking, working, resting and battling are valid reasons for a person to stay in place. Parallel scheduling does not guarantee that all 100 people are walking simultaneously.

Legacy manually stepped histories retain their original event semantics. Shared-clock activation is an explicit saved event; earlier receipts and state hashes are preserved.
