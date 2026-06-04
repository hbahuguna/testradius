// Load environment variables from .env file
require('dotenv').config();

const express = require('express');
const crypto = require('crypto');
const axios = require('axios');
const { Octokit } = require('@octokit/rest');
const { createAppAuth } = require('@octokit/auth-app');

const app = express();
const port = process.env.PORT || 3000;

// Middleware to parse JSON bodies and preserve raw body for webhook verification
app.use(express.json({
  verify: (req, res, buf, encoding) => {
    req.rawBody = buf.toString();
  }
}));

// Raw body parser specifically for the GitHub webhook endpoint (alternative method)
// We're keeping the above verify method, so this is not strictly needed but kept for clarity
// const rawBodyParser = bodyParser.raw({ type: 'application/json' });

// ========================
// TestSquad v2 Configuration
// ========================
const testsquadConfig = {
  apiUrl: process.env.TESTSQUAD_API_URL || 'http://localhost:8000',
  authToken: process.env.TESTSQUAD_AUTH_TOKEN || 'demo-bypass-token',
  projectMapping: process.env.TESTSQUAD_PROJECT_MAPPING
    ? JSON.parse(process.env.TESTSQUAD_PROJECT_MAPPING)
    : {},
  defaultProjectId: process.env.TESTSQUAD_PROJECT_ID || null,
};

function getProjectId(owner, repo) {
  const key = `${owner}/${repo}`;
  return testsquadConfig.projectMapping[key] || testsquadConfig.defaultProjectId;
}

async function runPrAnalysis(projectId, fullName, prNumber, commitSha, githubToken) {
  const response = await axios.post(
    `${testsquadConfig.apiUrl}/projects/${projectId}/analyze-pr`,
    {
      full_name: fullName,
      pr_number: prNumber,
      commit_sha: commitSha,
    },
    {
      headers: {
        'Authorization': `Bearer ${testsquadConfig.authToken}`,
        'X-GitHub-Token': githubToken,
        'Content-Type': 'application/json',
      },
      timeout: 120000,
    }
  );
  return response.data;
}

function buildTiaComment(analysis, owner, repo) {
  const { results, symbols_selected, total_tests_reused, pr_files_analyzed } = analysis;

  if (!results || results.length === 0) {
    return [
      `## TestRadius - Test Impact Analysis`,
      `**PR:** \`${owner}/${repo}\``,
      `**Files changed:** ${pr_files_analyzed}`,
      ``,
      `No impacted tests were identified for the changes in this PR.`,
    ].join('\n');
  }

  const lines = [
    `## TestRadius - Test Impact Analysis`,
    `**PR:** \`${owner}/${repo}\``,
    `**Files changed:** ${pr_files_analyzed}`,
    `**Symbols analyzed:** ${symbols_selected}`,
    `**Tests selected:** ${total_tests_reused}`,
    ``,
  ];

  let hasShownTable = false;
  for (const result of results) {
    const tests = result.existing_tests || [];
    if (tests.length === 0) continue;

    if (!hasShownTable) {
      lines.push(`| Test | File | Impacted Symbol |`);
      lines.push(`|------|------|-----------------|`);
      hasShownTable = true;
    }

    const first = tests[0];
    lines.push(`| \`${first.test_name}\` | \`${first.test_file}\` | \`${result.symbol_name}\` |`);
    for (let i = 1; i < tests.length; i++) {
      lines.push(`| \`${tests[i].test_name}\` | \`${tests[i].test_file}\` | \\` + ` |`);
    }
  }

  if (!hasShownTable) {
    lines.push(`All analyzed symbols already have test coverage in existing mappings.`);
  }

  lines.push(``);
  lines.push(`---`);
  lines.push(`> Analysis by TestRadius for \`${owner}/${repo}\`.`);

  return lines.join('\n');
}

async function runTestExecution(projectId, owner, repo, prNumber, commitSha, tests, githubToken) {
  const response = await axios.post(
    `${testsquadConfig.apiUrl}/projects/${projectId}/execute-tests`,
    {
      owner,
      repo,
      pr_number: prNumber,
      commit_sha: commitSha,
      github_token: githubToken,
      tests: tests.map(t => ({ name: t.test_name, file: t.test_file })),
    },
    {
      headers: {
        'Authorization': `Bearer ${testsquadConfig.authToken}`,
        'X-GitHub-Token': githubToken,
        'Content-Type': 'application/json',
      },
      timeout: 300000,
    }
  );
  return response.data;
}

function buildTestResultsComment(testResults, owner, repo) {
  const { status, total, passed, failed, results } = testResults;

  const overall = failed === 0 ? '✅ All tests passed' : `❌ ${failed} test(s) failed`;

  const rows = (results || []).map(r =>
    `| ${r.status === 'passed' ? '✅' : '❌'} | \`${r.name}\` | \`${r.file}\` | ${r.status} | ${r.duration} |`
  ).join('\n');

  let body = [
    `## TestRadius - Test Execution Results`,
    `**PR:** \`${owner}/${repo}\``,
    `**Status:** ${overall}`,
    `**Passed:** ${passed} / **Failed:** ${failed} / **Total:** ${total}`,
    ``,
  ];

  if (rows) {
    body.push(`| Result | Test | File | Status | Duration |`);
    body.push(`|--------|------|------|--------|----------|`);
    body.push(rows);
  }

  const failures = (results || []).filter(r => r.status === 'failed' && r.error);
  if (failures.length > 0) {
    body.push(``);
    body.push(`### Failure Details`);
    for (const f of failures) {
      body.push(``);
      body.push(`**${f.name}:**`);
      body.push('```');
      body.push(f.error.substring(0, 1000));
      body.push('```');
    }
  }

  body.push(``);
  body.push(`---`);
  body.push(`> Execution by TestRadius for \`${owner}/${repo}\`.`);

  return body.join('\n');
}

// ========================
// Route: Home
// ========================
app.get('/', (req, res) => {
  res.send('TestRadius GitHub App is running!');
});

// ========================
// Route: Initiate GitHub App installation
// ========================
app.get('/api/github/install', (req, res) => {
  const appName = process.env.GITHUB_APP_NAME;
  const installUrl = `https://github.com/apps/${appName}/installations/new`;
  res.send(`
    <h1>TestRadius GitHub App</h1>
    <p>Click <a href="${installUrl}">here</a> to install the app on your repositories.</p>
    <p>After installation, you will be redirected back to this server.</p>
  `);
});

// ========================
// Route: OAuth Callback after installation
// ========================
app.get('/api/github/callback', async (req, res) => {
  const { code } = req.query;
  if (!code) {
    return res.status(400).send('No code provided');
  }

  try {
    const tokenResponse = await axios.post(
      'https://github.com/login/oauth/access_token',
      {
        client_id: process.env.GITHUB_CLIENT_ID,
        client_secret: process.env.GITHUB_CLIENT_SECRET,
        code: code,
      },
      {
        headers: { Accept: 'application/json' },
      }
    );

    const { access_token, error } = tokenResponse.data;
    if (error) throw new Error(error);

    console.log('Installation access token received:', access_token);
    res.send(`
      <h1>Installation successful!</h1>
      <p>The TestRadius GitHub App has been installed.</p>
      <p>You can now close this window.</p>
    `);
  } catch (err) {
    console.error(err);
    res.status(500).send('Error exchanging code for token');
  }
});

// ========================
// Route: TestSquad v2 health check
// ========================
app.get('/api/testsquad/health', async (req, res) => {
  try {
    const response = await axios.get(`${testsquadConfig.apiUrl}/health`, { timeout: 5000 });
    res.json({
      status: 'connected',
      testsquad_url: testsquadConfig.apiUrl,
      testsquad_health: response.data,
    });
  } catch (err) {
    res.status(502).json({
      status: 'unreachable',
      testsquad_url: testsquadConfig.apiUrl,
      error: err.message,
    });
  }
});

// ========================
// Webhook endpoint for GitHub events
// ========================
app.post('/api/github/webhooks', async (req, res) => {
  // 1. Send immediate acknowledgment
  res.status(200).send('Webhook received');

  // 2. Get the raw payload
  const rawPayload = req.rawBody;
  if (!rawPayload) {
    console.error('Raw body is missing');
    return;
  }

  // 3. Get signature from header
  const signature = req.headers['x-hub-signature-256'];
  if (!signature) {
    console.error('Missing X-Hub-Signature-256 header');
    return;
  }

  // 4. Verify signature
  const secret = process.env.GITHUB_WEBHOOK_SECRET;
  const hmac = crypto.createHmac('sha256', secret);
  const expectedSignature = `sha256=${hmac.update(rawPayload).digest('hex')}`;

  if (!crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expectedSignature))) {
    console.error('Invalid signature - possible spoofed webhook');
    return;
  }

  // 5. Process event asynchronously
  setImmediate(async () => {
    try {
      const payload = JSON.parse(rawPayload);
      const eventType = req.headers['x-github-event'];

      if (eventType === 'pull_request' && (payload.action === 'opened' || payload.action === 'synchronize')) {
        const repoOwner = payload.repository.owner.login;
        const repoName = payload.repository.name;
        const prNumber = payload.pull_request.number;
        const installationId = payload.installation.id;

        console.log(`Processing ${payload.action} PR #${prNumber} in ${repoOwner}/${repoName}`);

        // Get installation access token using the app's private key
        const auth = createAppAuth({
          appId: process.env.GITHUB_APP_ID,
          privateKey: process.env.GITHUB_PRIVATE_KEY,
          clientId: process.env.GITHUB_CLIENT_ID,
          clientSecret: process.env.GITHUB_CLIENT_SECRET,
        });
        const installationAuth = await auth({ type: 'installation', installationId });
        const token = installationAuth.token;

        // Create Octokit instance
        const octokit = new Octokit({ auth: token });

        // Run Test Impact Analysis via TestSquad v2
        const projectId = getProjectId(repoOwner, repoName);
        if (!projectId) {
          await octokit.issues.createComment({
            owner: repoOwner,
            repo: repoName,
            issue_number: prNumber,
            body: `## TestRadius - Test Impact Analysis\n\nNo TestSquad project configured for \`${repoOwner}/${repoName}\`. Set \`TESTSQUAD_PROJECT_ID\` or \`TESTSQUAD_PROJECT_MAPPING\` to enable TIA.`,
          });
          console.log(`ℹ️ No project configured for ${repoOwner}/${repoName}, posted config notice`);
          return;
        }

        const commitSha = payload.pull_request.head.sha;
        const fullName = `${repoOwner}/${repoName}`;

        console.log(`🔍 Running TIA for ${fullName} PR #${prNumber} (${commitSha})`);
        const analysis = await runPrAnalysis(projectId, fullName, prNumber, commitSha, token);
        console.log(`🔬 TIA result: ${analysis.symbols_selected} symbols, ${analysis.total_tests_reused} reusable tests`);

        const tiaComment = buildTiaComment(analysis, repoOwner, repoName);
        await octokit.issues.createComment({
          owner: repoOwner,
          repo: repoName,
          issue_number: prNumber,
          body: tiaComment,
        });
        console.log(`✅ TIA comment posted on PR #${prNumber}`);

        // Step 2: Execute the selected tests
        const allTests = [];
        for (const r of (analysis.results || [])) {
          for (const t of (r.existing_tests || [])) {
            allTests.push(t);
          }
        }

        if (allTests.length > 0) {
          console.log(`🧪 Executing ${allTests.length} test(s) for ${fullName} PR #${prNumber}`);
          const testResults = await runTestExecution(projectId, repoOwner, repoName, prNumber, commitSha, allTests, token);
          console.log(`🧪 Test execution complete: ${testResults.passed}/${testResults.total} passed`);

          const execComment = buildTestResultsComment(testResults, repoOwner, repoName);
          await octokit.issues.createComment({
            owner: repoOwner,
            repo: repoName,
            issue_number: prNumber,
            body: execComment,
          });
          console.log(`✅ Test results comment posted on PR #${prNumber}`);

          // Set commit status based on test results
          const state = testResults.failed === 0 ? 'success' : 'failure';
          const description = testResults.failed === 0
            ? `${testResults.passed}/${testResults.total} tests passed`
            : `${testResults.failed} test(s) failed`;
          try {
            await octokit.repos.createCommitStatus({
              owner: repoOwner,
              repo: repoName,
              sha: commitSha,
              state,
              description,
              context: 'TestRadius / Tests',
              target_url: `${testsquadConfig.apiUrl}/projects/${projectId}/analyze-pr`,
            });
            console.log(`✅ Commit status set to "${state}" for ${commitSha}`);
          } catch (statusErr) {
            console.error('Failed to set commit status:', statusErr.message);
          }
        } else {
          console.log(`ℹ️ No tests to execute for ${fullName} PR #${prNumber}`);
        }
      } else {
        console.log(`Ignored event: ${eventType} (action: ${payload.action || 'undefined'})`);
      }
    } catch (err) {
      console.error('Error processing webhook:', err);
    }
  });
});

// Start the server
app.listen(port, () => {
  console.log(`Server is listening on port ${port}`);
});
