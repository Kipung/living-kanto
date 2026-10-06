# Entity inventory, storage, and trading

The implementation uses the pinned FireRed reference revision `037335f4c725d7c9aecdac87066f2002b4bd7e14`. Bag pockets have their source capacities and 999-item stack bounds; personal item storage has 30 stacks. Existing saves retain their optional metadata and recorded history. Existing over-capacity bags may retain their contents but cannot gain new items beyond source bounds.

Pokémon storage has fourteen named boxes with thirty positions each. An old flat box list receives a deterministic layout on access without changing Pokémon identities. Entities approach a physical PC to deposit, withdraw, rearrange, swap a full party, select boxes, and manage stored items or mail. The last usable party member is protected. Stored Pokémon retain personality, ownership, held items, and history.

Pokémon exchanges require a concrete offer, a recipient's chosen counterpart, and final proposer confirmation. Item exchanges declare exact quantities and optional payment; recipient acceptance commits both sides atomically. Offers expire, and resources, proximity, availability, and ownership are checked again at acceptance. Unaccepted offers reserve no resources. The engine does not expose a recipient's private inventory or money to the proposer. Trade evolutions and ownership of unique encounters follow the exchanged individual.

Mail retains its author, stationery, text, and attached Pokémon through an exchange. A PC mailbox holds ten letters. Free text of 1–200 characters adapts the cartridge's nine-word composer. Discarding a letter requires an explicit action; depositing or releasing an individual carrying mail is blocked.

The observer profile displays readable bag pockets, item storage, box names and positions, party members, mail, and exchange status. Observer controls do not perform entity actions. Numbered local-model choices include concrete items, partners, box selections, and trade responses; box names enforce eight characters.

Special item behavior includes reusable Poké Flute in the field and battle, guaranteed wild escape with Poké Doll or Fluffy Tail, source Game Corner prizes, Itemfinder and hidden pickups, and consensual entity VS Seeker rematches. Town Map, all six Teachy TV topics, Powder Jar inspection, and source renewable hidden-item cycles are also supported. Utility adaptations and excluded multiplayer mechanics are documented in UTILITY_ITEMS.md. Real runtime choices continue to use local models; test fixtures are separately identified.

Verification includes atomic failure and replay checks, disk reconstruction, legacy storage, pocket bounds, held-item validation, trade privacy, unique ownership, mail transfers, numbered decision bounds, and stale shared-clock decisions. Deployment and final regression evidence are recorded in the session handoff when verified.
