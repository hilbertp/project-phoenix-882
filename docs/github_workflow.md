# Project Phoenix Git and GitHub Workflow

This workflow is intentionally lightweight. It exists to keep reviewable slices clean, reduce branch mistakes, and make it easy to resume work when context is lost.

## Branch action must be stated first

Before any implementation handoff, one of these must be decided explicitly:

- stay on current branch
- create new branch
- checkpoint current branch first, then create new branch

## Branch naming

Create every reviewable slice from `main` on a new branch.

- Implementation slice: `area-short-slice-name`
- Spike: `spike-area-short-question`
- Infra or process slice: `infra-short-slice-name`

Keep names short, concrete, and tied to one reviewable outcome.

Examples:

- `db1-s1-swing-read-surface`
- `db1-review-writeback-validation`
- `spike-db1-s2-leg-ranking-shape`
- `infra-github-workflow-contributor-process`

## When to stay on a branch vs create a new one

Stay on the same branch only when the work is still the same reviewable slice.

Exact rule: same merge decision = same branch; new reviewable slice = new branch.

Create a new branch if any of these become true:

- the goal changes
- the reviewer would need a separate decision
- the work introduces a different acceptance object
- the current branch is already in review and new work would mix concerns

Rule of thumb: one branch should answer one review question.

## Spikes vs implementation slices

Use a spike branch when the goal is learning, shape validation, or technical proof rather than merge-ready implementation.

- Spike branches start with `spike-`
- A spike may produce notes, findings, or a narrow prototype
- Do not keep building production implementation on top of a spike branch once the answer is known
- If the spike leads to real implementation, start a fresh implementation branch from `main`
- If a spike result is worth keeping, checkpoint and push the spike branch, but do not continue implementation on that same branch; start a fresh implementation branch from `main`

Use an implementation branch when the goal is a reviewable repo change that can be accepted and merged.

## Required preflight before work starts

Before starting any slice:

1. make sure the previous slice is either merged or explicitly parked with checkpoint commit and push
2. update local `main`
3. create a new branch from `main`
4. confirm the branch name matches the slice goal
5. write down the review object in one sentence before coding

Minimal command sequence:

```bash
git checkout main
git pull --ff-only origin main
git checkout -b area-short-slice-name
```

## Required slice sequence

Every reviewable slice should follow this order:

1. branch from `main`
2. implement one slice
3. checkpoint commit
4. push branch
5. open PR
6. get stakeholder acceptance
7. merge

Do not start a new slice until the previous slice is either merged or explicitly parked with checkpoint commit and push.

## Safe parking rule for unfinished work

If you must switch focus before a slice is merged, park it safely.

Required parking sequence:

1. make the branch state coherent
2. create a checkpoint commit with a message that says what is done and what remains
3. push the branch
4. leave a short note in the PR body or branch context if a PR already exists

Example checkpoint commit messages:

- `checkpoint: db1 review summary API wired, tests still pending`
- `checkpoint: spike captured candidate leg scoring options`

Do not leave important slice state only in local uncommitted changes.

## Before opening a PR

Before PR creation:

1. confirm the branch still contains one slice only
2. remove unrelated edits
3. run the relevant checks for the slice
4. make a checkpoint commit if the latest local state is not committed
5. push the branch
6. open the PR with a clear review object

## Before merge

Before merge:

1. confirm stakeholder acceptance is explicit
2. confirm the PR describes included and excluded scope
3. confirm the branch is up to date enough for a safe merge
4. merge the reviewed slice
5. do not keep adding new work to the merged branch

After merge, stop using the merged branch for new work.

## Rebase or update-from-main rule

Keep this rule simple:

- Use the repo's normal update path consistently
- Do not rebase just for ceremony
- Update from `main` only when needed for clean review or merge

Use the lightest safe option your team is already using. The main rule is that the PR should merge cleanly and still represent one slice.

## Resume after merge

After a slice is merged:

1. return to `main`
2. pull the merged state
3. start the next slice from fresh `main`

Minimal command sequence:

```bash
git checkout main
git pull --ff-only origin main
git checkout -b next-slice-name
```

Do not continue new slice work on the old branch after merge.

## DB1-style examples

Example 1: implementation slice

- Branch: `db1-review-summary-reader`
- Goal: expose the DB1 review summary reader payload for review use
- Stay on this branch while the work remains only about the summary reader slice
- If you next decide to add writeback validation, start a new branch from `main`

Example 2: spike then implementation

- Spike branch: `spike-db1-s2-leg-ranking-shape`
- Goal: test whether candidate leg ranking should use alternating pivots and simple scoring
- Once the spike answers the question, start a new branch such as `db1-s2-leg-read-surface` from `main`
- Do not turn the spike branch into the final implementation branch

Example 3: parked work stays parked

- Parked branch: `db1-s1-raw-1h-swing-detection`
- If that branch is checkpointed and pushed but not merged, it must not be reused for `db1-s2-candidate-leg-scoring`
- The `db1-s2-candidate-leg-scoring` slice must start from `main` on a new branch