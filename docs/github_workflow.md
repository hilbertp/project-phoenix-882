# Git And GitHub Workflow

This workflow keeps reviewable slices small, explicit, and recoverable. It is designed for normal day-to-day work in Project Phoenix, where context can be lost across terminals, editor windows, or handoffs.

## Branch naming

Create every reviewable slice from `main` on a fresh branch.

- Implementation slice: `area-short-slice-name`
- Spike: `spike-area-short-question`
- Infra or process slice: `infra-short-slice-name`
- Docs-only slice: `docs-short-slice-name`

Use lowercase words with hyphens. Keep names specific enough that the branch tells you what is under review.

Examples:

- `db1-s1-raw-1h-swing-detection`
- `db1-s2-candidate-leg-scoring`
- `infra-github-workflow-contributor-process`
- `spike-db1-s2-leg-ranking-options`

## Stay on a branch or create a new one

Stay on the current branch only if the new work is still part of the same reviewable slice and would belong in the same PR.

Create a new branch if any of the following is true:

- the goal changed
- the reviewer would want a separate decision
- the work touches a different slice, lane, or acceptance target
- the current slice is already in review or ready for review
- you are tempted to say "while I am here"

Rule of thumb: one branch should map to one PR and one clear review object.

## Spikes vs implementation slices

Use a spike branch when the goal is to answer a question, test an approach, or reduce uncertainty.

- Branch name starts with `spike-`
- Output is notes, evidence, or a narrow proof
- Do not quietly grow a spike into production implementation

Use an implementation branch when the goal is a reviewable repository change that can merge.

- Branch name does not start with `spike-`
- Output is production-facing code, docs, or infrastructure changes intended to merge

If a spike proves the path forward, start a new implementation branch from `main`. Do not continue the implementation on the spike branch.

## Preflight before starting work

Before writing code or docs:

1. Make sure the current slice is merged or intentionally parked.
2. Return to `main` and update it.
3. Confirm the working tree is clean.
4. Create a new branch from `main`.
5. State the slice goal in one sentence before you start.

Minimal command sequence:

```bash
git checkout main
git pull --ff-only origin main
git status --short
git checkout -b <new-branch-name>
```

If `git status --short` is not clean, stop and either finish, park, or discard the old work before starting the new slice.

## Required working sequence

Every reviewable slice should follow this order:

1. branch
2. implement
3. checkpoint commit
4. push
5. PR
6. stakeholder acceptance
7. merge

Do not start the next slice before the current slice is either merged or intentionally parked with a checkpoint commit and push.

## Safe parking rule for unfinished work

If you need to switch focus before the slice is merged, park the branch safely.

Required parking sequence:

1. clean up obviously broken partial edits
2. commit a checkpoint with a truthful message
3. push the branch
4. leave a short note in the PR description or branch context about what remains

Checkpoint commit message examples:

- `checkpoint: DB1.S2 candidate leg scoring surface wired, review notes pending`
- `checkpoint: spike results captured, ranking comparison incomplete`

Do not leave important work only in local uncommitted changes.

## Before opening a PR

Before creating the PR:

1. confirm the branch still represents one reviewable slice
2. confirm the branch is pushed
3. confirm the diff does not contain unrelated cleanup
4. add checkpoint or test evidence
5. fill the PR template with included and excluded scope

The PR should make it easy for a reviewer to answer: what is the slice, what changed, what did not change, and what evidence supports it.

## Before merge

Before merging:

1. stakeholder acceptance exists for the stated review object
2. open questions are resolved or explicitly parked for later
3. the branch is up to date enough to merge cleanly
4. the PR description still matches the actual diff

Merge the reviewed branch, then stop using it for new work.

## Rebase or update-from-main rule

Keep this simple.

- If your branch is short-lived and `main` has not moved in a way that affects you, finish the slice and merge without extra churn.
- If `main` changed in a way that conflicts with your slice, update your branch before PR or before merge.
- If your branch has been open long enough that you no longer trust its base, update it.

Practical rule:

1. update from `main` before opening the PR if there are likely conflicts or stale assumptions
2. update again before merge if the PR no longer merges cleanly

Prefer one clean rebase onto `main` for a small local branch:

```bash
git checkout main
git pull --ff-only origin main
git checkout <your-branch>
git rebase main
```

If the branch is already shared and others are working on it, coordinate before rewriting history.

## Resume after merge

After a slice merges:

1. return to `main`
2. pull the merged result
3. delete the local branch if no longer needed
4. start the next slice from fresh `main`

Minimal command sequence:

```bash
git checkout main
git pull --ff-only origin main
git branch -d <merged-branch>
git checkout -b <next-branch>
```

Do not resume new work on the old merged branch.

## DB1-style examples

### Example 1: implementation slice

Goal: add raw 1H swing detection for DB1.S1.

- Branch: `db1-s1-raw-1h-swing-detection`
- Stay on branch while the work remains limited to the DB1.S1 swing detection slice and its tests
- Before switching away, create a checkpoint commit and push
- Open one PR for that slice only
- After acceptance and merge, start the next DB1 slice from fresh `main`

### Example 2: spike followed by implementation

Goal: compare ranking ideas for DB1.S2 candidate legs.

- Spike branch: `spike-db1-s2-leg-ranking-options`
- Use the spike to compare methods and capture evidence
- When the ranking direction is chosen, start `db1-s2-candidate-leg-scoring` from `main`
- Do not continue implementation on the spike branch
- Open the PR only from the implementation branch
