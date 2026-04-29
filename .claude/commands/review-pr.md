Review the pull request: $ARGUMENTS

Follow these steps carefully. Use the `gh` CLI for all GitHub interactions.

## Step 1: Resolve the PR

Parse `$ARGUMENTS` to determine the PR. It can be:

- A full URL like `https://github.com/owner/repo/pull/123`
- A `owner/repo#123` reference
- A bare number like `123` (use the current repo)
- A description — search for it with `gh pr list --search "<description>" --limit 5` and pick the best match

Once resolved, fetch the PR metadata:

```bash
gh pr view <PR> --json number,title,body,author,state,baseRefName,headRefName,url,labels,milestone,additions,deletions,changedFiles,createdAt,updatedAt,mergedAt,reviewDecision,reviews,assignees
```

## Step 2: Gather the diff

Get the full diff of the PR:

```bash
gh pr diff <PR>
```

If the diff is very large (>3000 lines), focus on the most important files first and summarize the rest.

## Step 3: Collect PR discussion context

Fetch all comments and review threads:

```bash
gh api repos/{owner}/{repo}/pulls/{number}/comments --paginate
gh api repos/{owner}/{repo}/issues/{number}/comments --paginate
gh api repos/{owner}/{repo}/pulls/{number}/reviews --paginate
```

Pay attention to:

- Reviewer feedback and requested changes
- Author responses and explanations
- Any unresolved conversations
- Approval or rejection status

## Step 4: Find and read linked issues

Look for issue references in:

- The PR body (patterns like `#123`, `fixes #123`, `closes #123`, `resolves #123`)
- The PR branch name (patterns like `issue-123`, `fix/123`)
- Commit messages

For each linked issue, fetch its content:

```bash
gh issue view <number> --json title,body,comments,labels,state
```

Read through issue comments to understand the original problem, user reports, and any discussed solutions.

## Step 5: Analyze and validate

With all context gathered, analyze the PR critically:

1. **Intent alignment**: Does the code change actually solve the problem described in the PR and/or linked issues?
2. **Completeness**: Are there aspects of the issue or requested feature that the PR doesn't address?
3. **Scope**: Does the PR include changes unrelated to the stated goal? Are there unnecessary modifications?
4. **Correctness**: Based on the diff, are there obvious bugs, edge cases, or logic errors?
5. **Testing**: Does the PR include tests? Are they meaningful and do they cover the important cases?
6. **Breaking changes**: Could this PR break existing functionality or APIs?
7. **Unresolved feedback**: Are there reviewer comments that haven't been addressed?

## Step 6: Produce the review summary

Present the summary in this format:

---

### PR Review: `<title>` (<url>)

**Author:** <author> | **Status:** <state> | **Review decision:** <decision>
**Base:** `<base>` ← `<head>` | **Changed files:** <n> | **+<additions> / -<deletions>**

#### Problem

<1-3 sentences describing what problem this PR is trying to solve, based on the PR description and linked issues>

#### Solution

<1-3 sentences describing the approach taken in the code>

#### Key changes

<Bulleted list of the most important changes, grouped by theme. Include file paths.>

#### Linked issues

<List of linked issues with their title, state, and a one-line summary of the discussion>

#### Discussion highlights

<Summary of important comments from reviewers and the author. Flag any unresolved threads.>

#### Concerns

<List any issues found during validation: bugs, missing tests, scope creep, unaddressed feedback, etc. If none, say "No concerns found.">

#### Verdict

<One of: APPROVE / REQUEST CHANGES / NEEDS DISCUSSION, with a brief justification>

#### Suggested action

<Clear recommendation for the reviewer: what to approve, what to push back on, what to ask about>

---
