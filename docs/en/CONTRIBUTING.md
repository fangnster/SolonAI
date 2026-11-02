# Contributing

[English home](../../README.en.md) · [Testing](TESTING.md)

## Reviewable changes

Use a feature or bugfix branch and keep a change centered on a concrete behavior. Explain the failing input, expected result and actual validation. Avoid combining quantity semantics, new protocols, agent integrations and deployment changes without a shared reason.

For wallet changes, preserve these contracts:

- Raw quantities and read slots remain canonical integer strings across JSON boundaries.
- Known zero is not missing data; failed reads do not become empty successful reports.
- Token account identity is program/account, not mint alone.
- Read-context slots and UI request sequence numbers are not account write versions.
- Cache hits preserve the read start. Shared publication never bypasses the reservation check on errors.
- Client age grows and clock anomalies do not make data appear fresh.

## Validation

Run the wallet regression entry point, relevant frontend checks, and Ruff commands in [TESTING.md](TESTING.md). Record the environment and concrete outcomes. Name any checks not run; distinguish injected dependencies from real infrastructure.

Commit only source, configuration and useful documentation. Exclude `.env` files, wallet keys, virtual environments, node_modules, generated Next output and runtime result directories. The tracked historical TypeScript build-info file should not be included merely because a local type check refreshed it.

Existing Husky hooks can modify files and require tools in `apps/api/.venv`; inspect staged changes again after hooks run. CI is the shared check, and local setup should use the documented runtime rather than silently skipping failures.

## Commit and pull-request format

Use the repository's Conventional Commit types, for example:

```text
fix(wallet): preserve raw token quantities during conversion
```

A pull-request description should lead with the problem and resulting behavior, then list relevant validation and material limits. Link the target base and regression when helpful. Do not claim live deployment, complete coverage, independent authorship or external review without evidence.

Publishing a branch does not mean it is merged into main or an upstream repository. Review and deployment are separate states.
