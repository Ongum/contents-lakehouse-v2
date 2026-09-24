# AGENTS.md

## Purpose

Build the Contents Lakehouse through small, reviewable milestones. The architecture and domain contracts live in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/DATA_MODEL.md](docs/DATA_MODEL.md); do not duplicate them here.

## Work modes

- **MANUAL**: implement one bounded task, run its relevant checks, stop, and report for human review before the next task.
- **AUTO**: complete bounded LOW/MEDIUM-risk work, repair implementation or test failures, and continue until the milestone boundary or a HIGH-risk decision.
- **REVIEW**: independently inspect a completed milestone and report `PASS` or concrete issues. Do not redesign it unless a blocking defect requires a change.

The requested mode wins. If none is stated, use REVIEW for analysis-only requests and AUTO for bounded implementation work.

## Risk levels

- **LOW**: tests, fixtures, documentation synchronization, existing-pattern adapters, and bounded bug fixes with no production effect.
- **MEDIUM**: additive schema evolution, new projections, cross-domain joins, pipeline entrypoints, and adapters for already-approved sources.
- **HIGH**: grain or canonical-ID changes, domain-boundary changes, destructive migration, production writes, GCP resource/IAM changes, potentially material cloud cost, adoption of a new external source, or unclear/restricted licensing.

HIGH-risk actions require explicit human approval immediately before the action. Prepare and validate the reviewable change first when possible.

## Operating rules

1. Read this file, [docs/ROADMAP.md](docs/ROADMAP.md), and only the domain documentation and code relevant to the task.
2. Confirm the active milestone, work mode, risk level, scope, and completion criteria from the request and repository evidence.
3. Preserve working code and established Bronze → Silver → Iceberg → Gold boundaries. Reuse existing schemas, IDs, storage abstractions, and provenance patterns.
4. Make the smallest coherent change. Do not refactor unrelated files, add dependencies without need, or expand domains beyond the requested milestone.
5. Never commit secrets. Use environment variables for credentials and keep raw-source lineage where data is transformed.
6. Prefer idempotent pipelines and focused tests for important transformations.

## Completion gates

A task is complete when all applicable gates pass:

- requested deliverables and acceptance criteria are satisfied;
- production data and infrastructure remain unchanged unless explicitly authorized;
- grain, deterministic IDs, idempotency, provenance, temporal semantics, nullable/unresolved behavior, and data-quality validation are correct where applicable;
- relevant unit and integration/regression tests pass, or documentation-only work has its internal links checked;
- `python -m compileall` passes when Python changes;
- `git diff --check` passes;
- no unexpected schema or canonical-ID changes are present;
- cloud work additionally covers retry behavior, observability, failure recovery, and cost awareness where applicable;
- changed files, important decisions, validation, unresolved issues, and required human decisions are reported;
- milestone completion is recorded in `docs/reports/` when a milestone closes;
- durable architectural decisions are recorded in `docs/adr/`.

## Token-efficient workflow

- Search before reading whole files; inspect only relevant sections and tests.
- Reuse repository evidence instead of restating established architecture.
- Run the smallest meaningful validation once; broaden only after a failure or unresolved risk.
- Keep reports factual and link to canonical documents instead of copying them.
- Stop when the completion gates pass; record follow-up work in the next milestone rather than extending the current task.
