# Personal fork and review guide

[Repository](https://github.com/fangnster/SolonAI) · [English home](../../README.en.md) · [Testing](TESTING.md)

This personal fork makes an unfinished Solana project reviewable through a bounded wallet-report and quote-contract path. The focus is exact quantities, identity, freshness, failure behavior and reproducible checks. It does not claim that every original product feature is complete.

Publishing to `main` runs CI. The inherited Vercel/Railway deployment workflow is manual only; deployment requires separately configured credentials and targets. A green code check is not a deployed-service acceptance result.

## Contribution evidence

The historical fangnster pull requests merged into the original project cover [database design](https://github.com/goodperson888/SolonAI/pull/3), [PostgreSQL/Redis integration](https://github.com/goodperson888/SolonAI/pull/6), [RPC documentation](https://github.com/goodperson888/SolonAI/pull/7), and [Docker/service integration and failure reporting](https://github.com/goodperson888/SolonAI/pull/8).

Later personal-fork work extends the wallet read contract and now replaces guessed float quote amounts with explicit raw-unit strings. These changes were developed with AI assistance as part of guided engineering practice. Historical merged PRs, personal-fork implementation, and the learner's own reproduction/changes have distinct evidence. A personal-fork update is not an upstream merge.

## Three reviewable examples

1. **Amount boundary:** maximum-u64 raw units survive RPC decoding, Python, JSON and TypeScript without a binary64 conversion. The quote route preserves input-mint base units instead of assuming nine decimals.
2. **Identity and ordering:** separate token accounts stay separate. A later Redis reservation can reject an earlier writer's late result even when the newer amount is lower. Slot is read context, not an account write version.
3. **Time and failure:** cache hits preserve the original read start; local report age grows. Missing data, read failure, unknown publication and known zero are distinct concerns. Quote-price freshness and legacy USD semantics still need work.

## Ten minute walkthrough

```bash
.venv/bin/python scripts/check_wallet_report.py --out .wallet-report-results-review
.venv/bin/python scripts/trace_wallet_sources.py --case all --out .wallet-report-results-review/provenance
.venv/bin/python scripts/demo_swap_quote.py
```

The full runner expects 175 targeted tests, real Redis publication checks, and five additional quote demonstration cases. The quote cases are not added to the test-method count. Use explicit Node 24 and Redis executable paths if they are absent from PATH.

Show the raw quantity, then the original read window, then the late-publication result. Finally show that `amount_raw="1000000"` reaches the provider unchanged, while the old `amount=1.0` body returns 422. Separate fixture evidence from actual market/RPC operation.

## Questions for review

- Why is a string quantity necessary across JSON and JavaScript?
- What is the authority for token decimals, and which component converts user-entered text?
- What does a Redis reservation order establish, and what does it not establish about Solana state?
- Why can a timed-out publish be unknown rather than failed?
- What extra records would a transaction executor need for retries, partial fills and recovery?

Authentication, production migration/recovery, optional AI dependencies, provider updates, Token-2022 and browser lifecycle remain separate follow-up work; see [status](ARCHITECTURE.md). No wallet private keys are required for these demonstrations.
