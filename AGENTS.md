# Living Kanto development

Read docs/PROJECT_GUIDE.md before application work. When OPERATOR_CONTEXT.md exists, read it for the private development/runtime locations and current operator scope. Private operator instructions and handoffs must never be committed.

Preserve existing worlds and their complete history. Never reset a simulation to apply an improvement. Keep OpenRig stopped. Runtime human decisions use local models without scripted or cloud fallback; identified test providers are allowed in tests. Do not claim autonomous championships, sustained behavior or release acceptance without evidence.

Treat source repositories and runtime deployments as separate roles. Make application changes in the authoritative development checkout specified by the user or private operator context. Test changes before guarded deployment. Keep live databases, exported worlds, inference logs, model connection settings and machine-specific handoffs out of Git, including Git history. Store recovery copies privately and verify them before removing originals.
