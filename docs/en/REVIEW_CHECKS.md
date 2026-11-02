# Contribution rules and CI: source audit

[English home](../../README.en.md) · [Field provenance](DATA_PROVENANCE.md)

Checked on 2026-11-03 against personal branch `course/w1d1-review` at `5df8a31` and upstream `develop` at `c41e62d`. Workflow definitions establish what runs on a matching event; this audit does not establish GitHub branch-protection required checks or maintainer approval.

## Branch and review policy

`docs/GIT_WORKFLOW.md` calls for work on a descriptive `feature/<module>-<description>` or `fix/<module>-<description>` branch, PRs into develop, and review before merging protected integration branches. A personal course branch is an integration/reference branch, not evidence of upstream acceptance. The earlier broad reference should not be treated as a small upstream PR without narrowing its scope.

The personal workflow runs on pushes to main, develop and `course/**`, and on pull requests targeting main/develop. A plain push to `feature/**` does not match that push filter. The upstream workflow has only main/develop push filters and lacks the personal branch's wallet regression job.

## Current executable checks

| Job              | Actual requirement                                                                                                                          |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `frontend-lint`  | Node 24, npm ci, frontend ESLint, Prettier and full TypeScript check                                                                        |
| `frontend-build` | Node 24, npm ci, Next.js build; depends on frontend-lint                                                                                    |
| `backend-lint`   | Python 3.11, pinned dev/API requirements, Ruff lint and format checks for listed application/service/diagnostic paths                       |
| `wallet-report`  | Python 3.11, Node 24, API dependencies, a disposable test Redis, the 161-test wallet runner and the diagnostic trace added with these notes |
| `commitlint`     | Runs only for a pull_request event, checking the PR commit range                                                                            |

The diagnostic trace has eight scenarios; it does not add eight unit-test methods to the 161-test suite. Source audit results captured before this diagnostic addition reflect the earlier workflow; the committed workflow contains the additional trace step.

Upstream's inspected workflow uses Node 18 and has no wallet regression job. Root `package.json` permits Node >=18, while the direct TypeScript regression imports require Node 24; the existing web Dockerfile uses Node 20. Use the documented Node 24 toolchain for these checks rather than inferring test compatibility from the broad engine range. Aligning every runtime is separate work.

## Commit message examples checked with real commitlint

From the repository root, after npm dependencies are installed:

```bash
solon_message_dir="$(mktemp -d)"
printf '%s\n' 'docs(wallet): trace raw quantity sources' > "$solon_message_dir/valid.txt"
node node_modules/@commitlint/cli/cli.js --edit "$solon_message_dir/valid.txt"
printf '%s\n' 'merge: merge develop' > "$solon_message_dir/invalid.txt"
node node_modules/@commitlint/cli/cli.js --edit "$solon_message_dir/invalid.txt"
```

The first exits 0, the second 1 with a type-enum error. These commands check temporary text files; they do not create commits. The Chinese workflow guide also contains `merge:` and `hotfix:` samples that the installed configuration rejects. Branch prefixes and commit types are distinct: a hotfix branch can still use a valid `fix(wallet): ...` message. Use `chore: merge develop` for a descriptive merge message compatible with the tested configuration.

Resolved rules allow feat/fix/docs/style/refactor/perf/test/chore/revert/ci, limit subject length to 72, and header/body line length to 100. These are resolved local configuration values, including inherited rules, not a generic assertion about every Conventional Commits setup.

## Git hooks are a separate layer

Read their activation without running them:

```bash
git config --show-origin --get core.hooksPath
git ls-files .husky
sed -n '1,160p' .husky/pre-commit
```

An unset core.hooksPath normally makes the first command exit 1. A tracked hook file alone does not prove Git invokes it. The inspected local worktree has no active pre-commit file at its effective default hooks directory and no `apps/api/.venv/bin/python`; prior checks used the workspace's separate Python environment. `npm ci --ignore-scripts` installs dependencies without activating Husky's prepare step.

The tracked pre-commit script formats/fixes whole directories and runs `git add -u`; it can change and restage files. It expects Python tools at `apps/api/.venv`, runs a local mypy pipeline not present in CI, and includes Bash-specific `${PIPESTATUS[0]}`. Installed Husky 9.1.7 launches hooks with `sh -e`; this is a portability concern, not a Linux failure reproduced by this audit. [Husky recommends POSIX-compatible hooks](https://typicode.github.io/husky/how-to.html#bash).

This audit does not execute, skip or rewrite the hook. Review its mutation and shell behavior as a separate candidate rather than claiming that a green push run proves the hooks or commitlint passed. The old Chinese environment instructions mention Black/isort/flake8, while the executable dev requirements and CI use Ruff 0.8.4.

## Before proposing an upstream patch

Recheck the target branch, keep the functional regression and fix small, run the target branch's actual commands, check the commit message explicitly, and state which diagnostic dependencies were substituted. CI success, branch-protection policy, maintainer review and merge are distinct facts. Do not infer any of them from the others.
