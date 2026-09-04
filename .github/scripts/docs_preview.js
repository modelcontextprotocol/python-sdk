// Docs preview gate and PR comment. .github/workflows/docs-preview.yml wires
// these up: `authorize` decides whether a run may build and deploy a preview
// (and for which commit), `comment` reports the outcome on the pull request.
// The security model is described in the workflow's header.
'use strict';

const MARKER = '<!-- docs-preview -->';
const BOT_LOGIN = 'github-actions[bot]';

// Sets the job outputs `authorized`, `pr_number`, `head_sha` and
// `slash_attempt` for a pull_request_target or /preview-docs issue_comment run.
async function authorize({ github, context, core }) {
  const { owner, repo } = context.repo;

  async function permissionFor(username) {
    const { data } = await github.rest.repos.getCollaboratorPermissionLevel({ owner, repo, username });
    return { level: data.permission, role: data.role_name };
  }

  let authorized = false;
  let prNumber = '';
  let headSha = '';
  let slashAttempt = false;

  if (context.eventName === 'pull_request_target') {
    const pr = context.payload.pull_request;
    prNumber = String(pr.number);
    headSha = pr.head.sha;
    // No automatic preview for fork PRs: actions/checkout refuses to fetch a
    // fork's head in a pull_request_target run. A maintainer can still request
    // one with /preview-docs. (head.repo is null once the fork is deleted.)
    const headRepo = pr.head.repo;
    if (!headRepo || headRepo.id !== context.payload.repository.id) {
      core.info(`PR #${prNumber} head is on ${headRepo ? headRepo.full_name : 'a deleted fork'}; fork PRs are previewed via /preview-docs only.`);
    } else {
      // Gate on the *sender* (whoever caused this run — on synchronize that
      // is the pusher), not the PR author, so a non-admin pushing to an
      // admin-opened branch does not get an automatic build.
      const actor = context.payload.sender.login;
      const perm = await permissionFor(actor);
      authorized = perm.level === 'admin';
      core.info(`pull_request_target by ${actor} (level=${perm.level}, role=${perm.role}) → authorized=${authorized}`);
    }
  } else {
    // issue_comment: the job-level `if:` already guarantees this is a PR
    // comment starting with /preview-docs.
    slashAttempt = true;
    const actor = context.payload.comment.user.login;
    prNumber = String(context.payload.issue.number);
    const perm = await permissionFor(actor);
    authorized = perm.level === 'admin' || perm.role === 'maintain';
    if (authorized) {
      const { data: pr } = await github.rest.pulls.get({ owner, repo, pull_number: Number(prNumber) });
      if (pr.state !== 'open') {
        authorized = false;
        core.info(`PR #${prNumber} is ${pr.state}; refusing to preview.`);
      } else {
        headSha = pr.head.sha;
      }
    }
    core.info(`/preview-docs by ${actor} (level=${perm.level}, role=${perm.role}) → authorized=${authorized}`);
  }

  core.setOutput('authorized', String(authorized));
  core.setOutput('pr_number', prNumber);
  core.setOutput('head_sha', headSha);
  core.setOutput('slash_attempt', String(slashAttempt));
}

// Posts or updates the preview comment on the PR. Reads the outcome of the
// earlier jobs from the step's env: AUTHORIZED, PR_NUMBER, HEAD_SHA,
// DEPLOY_RESULT, DEPLOYMENT_URL, ALIAS_URL, RUN_URL.
async function comment({ github, context }) {
  const { owner, repo } = context.repo;
  const env = process.env;
  const issue_number = Number(env.PR_NUMBER);

  async function upsert(body) {
    const comments = await github.paginate(github.rest.issues.listComments, { owner, repo, issue_number, per_page: 100 });
    const existing = comments.find((c) => c.user?.login === BOT_LOGIN && c.body?.includes(MARKER));
    if (existing) {
      await github.rest.issues.updateComment({ owner, repo, comment_id: existing.id, body });
    } else {
      await github.rest.issues.createComment({ owner, repo, issue_number, body });
    }
  }

  if (env.AUTHORIZED !== 'true') {
    await github.rest.issues.createComment({
      owner, repo, issue_number,
      body: `@${context.actor} — only repository admins or maintainers can run \`/preview-docs\` (and the PR must be open).`,
    });
    return;
  }

  if (env.DEPLOY_RESULT !== 'success') {
    await upsert(
      `${MARKER}\n### 📚 Documentation preview\n\n` +
      `❌ Preview build **failed** for \`${env.HEAD_SHA.slice(0, 7)}\` — [workflow logs](${env.RUN_URL}).`
    );
    return;
  }

  const previewUrl = env.ALIAS_URL || env.DEPLOYMENT_URL;
  const ts = new Date().toISOString().replace('T', ' ').replace(/\.\d+Z$/, ' UTC');
  await upsert(
    `${MARKER}\n### 📚 Documentation preview\n\n` +
    `| | |\n|---|---|\n` +
    `| **Preview** | ${previewUrl} |\n` +
    `| **Deployment** | ${env.DEPLOYMENT_URL} |\n` +
    `| **Commit** | \`${env.HEAD_SHA.slice(0, 7)}\` |\n` +
    `| **Triggered by** | @${context.actor} |\n` +
    `| **Updated** | ${ts} |\n`
  );
}

module.exports = { authorize, comment };
