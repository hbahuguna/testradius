# MANUAL_TEST_PLAN_CLOUDROOM_INTEGRATION.md — Cloud Room Integration (Cloud VM Backend)

## Overview
Comprehensive manual testing plan covering all components of the Cloud Room integration implemented across EPIC-CR001 through EPIC-CR007.4.

## Prerequisites
- TestRadius repo cloned at `/Users/skaparwan/github/testradius`
- Python environment with dependencies installed
- Access to terminal
- (Optional) Cloud Room instance running for full E2E tests

## Test Environment Setup
```bash
cd /Users/skaparwan/github/testradius
export PYTHONPATH=/Users/skaparwan/github/testradius/apps/cell/.venv/bin/python
```

---

## EPIC-CR001: Executor Abstraction

### TC-CR001-001: Verify BaseExecutor Interface
**Objective:** Verify BaseExecutor ABC is properly defined
**Priority:** P0

**Steps:**
1. Check base.py exists
```bash
ls -la /Users/skaparwan/github/testradius/harness/execution/base.py
```
2. Verify imports work
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -c "
from harness.execution import BaseExecutor, ExecutionResult, ExecutionStatus, ExecutorConfig, StepResult
print('All imports OK')
"
```
3. Run tests
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest /Users/skaparwan/github/testradius/harness/execution/tests/test_base_executor.py -v
```

**Expected:** All 6 tests pass

### TC-CR001-002: Verify LocalPlaywrightExecutor
**Objective:** Verify local executor implements BaseExecutor correctly
**Priority:** P0

**Steps:**
1. Check file exists
```bash
ls -la /Users/skaparwan/github/testradius/harness/execution/local.py
```
2. Test instantiation
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -c "
from harness.execution import LocalPlaywrightExecutor, ExecutorConfig
from pathlib import Path
import tempfile
d = Path(tempfile.mkdtemp())
cfg = ExecutorConfig(run_id='t1', target_url='https://example.com', plan={'testCases':[]}, artifacts_dir=d)
e = LocalPlaywrightExecutor(cfg)
print(type(e).__name__)
print(e.is_running())
print(e.is_complete())
"
```
3. Run tests
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest /Users/skaparwan/github/testradius/harness/execution/tests/test_local_executor.py -v
```

**Expected:** Executor instantiates, implements all methods

### TC-CR001-003: Verify Executor Factory
**Objective:** Test factory with different configurations
**Priority:** P0

**Steps:**
1. Test default (local)
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python << 'PY'
from harness.execution import create_executor, ExecutorConfig
from pathlib import Path
import tempfile
d = Path(tempfile.mkdtemp())
cfg = ExecutorConfig(run_id='t1', target_url='https://example.com', plan={'testCases':[]}, artifacts_dir=d)
e = create_executor(cfg)
print(type(e).__name__)
PY
```
2. Test with env var
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius EXECUTOR_TYPE=local ./.venv/bin/python << 'PY'
from harness.execution import create_executor, ExecutorConfig
from pathlib import Path
import tempfile
d = Path(tempfile.mkdtemp())
cfg = ExecutorConfig(run_id='t2', target_url='https://example.com', plan={'testCases':[]}, artifacts_dir=d)
e = create_executor(cfg)
print(type(e).__name__)
PY
```
3. Test invalid type
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python << 'PY'
from harness.execution import create_executor, ExecutorConfig
from pathlib import Path
import tempfile
d = Path(tempfile.mkdtemp())
cfg = ExecutorConfig(run_id='t3', target_url='https://example.com', plan={'testCases':[]}, artifacts_dir=d)
try:
    e = create_executor(cfg, executor_type='bad')
    print('SHOULD FAIL')
except ValueError as e:
    print('OK:', str(e))
PY
```
4. Run tests
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest /Users/skaparwan/github/testradius/harness/execution/tests/test_factory.py -v
```

**Expected:** All factory tests pass

---

## EPIC-CR002: Cloud Room Client

### TC-CR002-001: Client Core - Auth & Config
**Priority:** P0

**Steps:**
1. Test missing token
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python << 'PY'
from harness.integrations.cloudroom import CloudRoomClient, CloudRoomError
try:
    c = CloudRoomClient()
    print('SHOULD FAIL')
except CloudRoomError as e:
    print('OK')
PY
```
2. Test with token
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius CLOUDROOM_TOKEN=test123 ./.venv/bin/python << 'PY'
from harness.integrations.cloudroom import CloudRoomClient
c = CloudRoomClient()
print(c.base_url)
print(len(c._generate_request_id()))
PY
```
3. Run tests
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest /Users/skaparwan/github/testradius/harness/integrations/cloudroom/tests/test_client_core.py -v
```

**Expected:** Auth works, request IDs generated

### TC-CR002-002: Sessions & Threads API
**Priority:** P0

**Steps:**
1. Test session creation
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius CLOUDROOM_TOKEN=test123 ./.venv/bin/python << 'PY'
from harness.integrations.cloudroom import CloudRoomClient
c = CloudRoomClient()
c._request = lambda *a,**k: {'session_id':'cr_test123','status':'created'}
r = c.create_session(request_id='test123')
print(r['session_id'].startswith('cr_'))
PY
```
2. Test thread creation
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius CLOUDROOM_TOKEN=test123 ./.venv/bin/python << 'PY'
from harness.integrations.cloudroom import CloudRoomClient
c = CloudRoomClient()
c._request = lambda *a,**k: {'thread_id':'t1','status':'created'}
r = c.create_thread('cr_1', prompt='hello')
print(r['thread_id'])
PY
```
3. Run tests
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest /Users/skaparwan/github/testradius/harness/integrations/cloudroom/tests/test_sessions_threads.py -v
```

**Expected:** All pass

### TC-CR002-003: Commands, Receipts & Polling
**Priority:** P0

**Steps:**
1. Run tests
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest /Users/skaparwan/github/testradius/harness/integrations/cloudroom/tests/test_commands_receipts.py -v
```

**Expected:** Send command, poll receipts, handle states

### TC-CR002-004: Artifacts & Journal
**Priority:** P0

**Steps:**
1. Run tests
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest /Users/skaparwan/github/testradius/harness/integrations/cloudroom/tests/test_artifacts_journal.py -v
```

**Expected:** All pass

### TC-CR002-005: Automations API
**Priority:** P1

**Steps:**
1. Run tests
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest /Users/skaparwan/github/testradius/harness/integrations/cloudroom/tests/test_automations.py -v
```

**Expected:** Create/list/trigger automations work

---

## EPIC-CR003: Cloud Room Executor

### TC-CR003-001: CloudRoomExecutor Scaffolding
**Priority:** P0

**Steps:**
1. Check file
```bash
ls -la /Users/skaparwan/github/testradius/harness/execution/cloudroom.py
```
2. Test instantiation
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius CLOUDROOM_TOKEN=test123 ./.venv/bin/python << 'PY'
from harness.execution import ExecutorConfig
from harness.execution.cloudroom import CloudRoomExecutor
from pathlib import Path
import tempfile
d = Path(tempfile.mkdtemp())
cfg = ExecutorConfig(run_id='t1', target_url='https://example.com', plan={'testCases':[]}, artifacts_dir=d)
e = CloudRoomExecutor(cfg)
print(type(e).__name__)
print(hasattr(e,'prepare'))
print(hasattr(e,'execute_plan'))
PY
```
3. Run tests
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest /Users/skaparwan/github/testradius/harness/execution/tests/test_cloudroom_executor.py -v
```

**Expected:** 5 tests pass

### TC-CR003-002: Plan to Prompt Conversion
**Priority:** P0

**Steps:**
1. Test prompt generation
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius CLOUDROOM_TOKEN=test123 ./.venv/bin/python << 'PY'
from harness.execution import ExecutorConfig
from harness.execution.cloudroom import CloudRoomExecutor
from pathlib import Path
import tempfile
d = Path(tempfile.mkdtemp())
cfg = ExecutorConfig(run_id='r123', target_url='https://testradius.dev', plan={'testCases':[{'id':'TC1','title':'Nav','steps':['click'],'expectedChecks':['ok']}]}, artifacts_dir=d)
e = CloudRoomExecutor(cfg)
p = e._plan_to_prompt(cfg.plan)
assert 'testradius.dev' in p
assert 'TC1' in p
assert 'browser-harness' in p
assert '/workspace/artifacts' in p
print('OK')
PY
```

**Expected:** Prompt contains all required elements

### TC-CR003-003: Thread Creation & Orchestration
**Priority:** P0

**Steps:**
1. Test thread creation flow (mocked)
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius CLOUDROOM_TOKEN=test123 ./.venv/bin/python << 'PY'
from harness.execution import ExecutorConfig
from harness.execution.cloudroom import CloudRoomExecutor
from pathlib import Path
import tempfile
d = Path(tempfile.mkdtemp())
cfg = ExecutorConfig(run_id='r123', target_url='https://testradius.dev', plan={'testCases':[{'id':'TC1','title':'Test'}]}, artifacts_dir=d)
e = CloudRoomExecutor(cfg)
e.session_id = 'cr_test'
e.client.create_thread = lambda sid, prompt=None, **k: {'thread_id':'t999'}
tid = e._create_and_start_thread()
print(tid)
print(e.thread_id)
PY
```

**Expected:** Thread created with plan prompt

### TC-CR003-004: Evidence Collection
**Priority:** P0

**Steps:**
1. Test artifact collection (mocked)
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius CLOUDROOM_TOKEN=test123 ./.venv/bin/python << 'PY'
from harness.execution import ExecutorConfig
from harness.execution.cloudroom import CloudRoomExecutor
from pathlib import Path
import tempfile
d = Path(tempfile.mkdtemp())
cfg = ExecutorConfig(run_id='r123', target_url='https://testradius.dev', plan={'testCases':[]}, artifacts_dir=d)
e = CloudRoomExecutor(cfg)
e.session_id = 'cr_test'
e.client.list_artifacts = lambda sid: {'files':['s1.png','run.webm','trace.json']}
e.client.download_artifact = lambda sid, p: b'fake'
arts = e._collect_artifacts('r123')
print(len(arts['screenshots']))
print(arts['video_path'] is not None)
print(arts['trace_path'] is not None)
PY
```

**Expected:** Artifacts collected and categorized

---

## EPIC-CR004: Orchestrator Integration

### TC-CR004-001: API Integration
**Priority:** P0

**Steps:**
1. Test API imports
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -c "
from harness.api.app import app
print(app.title)
"
```
2. Test executor endpoints exist
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python << 'PY'
from harness.api.app import app
routes = [r.path for r in app.routes]
print('/api/executor/config' in routes)
print('/api/system/executor' in routes)
print('/api/runs/{run_id}/start-executor' in routes)
PY
```

**Expected:** All endpoints registered

### TC-CR004-002: Config & Environment
**Priority:** P0

**Steps:**
1. Check .env.example
```bash
grep -A 5 "Cloud Room" /Users/skaparwan/github/testradius/.env.example
```
2. Test config
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python << 'PY'
from harness import config
print(hasattr(config, 'CLOUDROOM_URL'))
print(hasattr(config, 'CLOUDROOM_TOKEN'))
print(hasattr(config, 'EXECUTOR_TYPE'))
print(hasattr(config, 'validate_executor_config'))
PY
```
3. Test validation
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius EXECUTOR_TYPE=cloudroom ./.venv/bin/python << 'PY'
from harness import config
r = config.validate_executor_config()
print(r['valid'])
print(len(r['errors']) > 0)
PY
```

**Expected:** Config present, validation works

### TC-CR004-003: Feature Flags
**Priority:** P0

**Steps:**
1. Test mode switching
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius EXECUTOR_TYPE=cloudroom ./.venv/bin/python << 'PY'
from harness.execution import get_executor_mode
print(get_executor_mode())
PY
```
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python << 'PY'
from harness.execution import get_executor_mode
print(get_executor_mode())
PY
```

**Expected:** Mode switches correctly

---

## EPIC-CR005: Artifact Sync & Evidence

### TC-CR005-001: Artifact Downloader
**Priority:** P0

**Steps:**
1. Run tests
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest /Users/skaparwan/github/testradius/harness/integrations/cloudroom/tests/test_artifacts_download.py -v
```
2. Manual test
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius CLOUDROOM_TOKEN=test123 ./.venv/bin/python << 'PY'
from harness.integrations.cloudroom import CloudRoomClient, ArtifactDownloader
from pathlib import Path
import tempfile
d = Path(tempfile.mkdtemp())
c = CloudRoomClient()
c.list_artifacts = lambda s: {'files':['a.png','b.webm']}
c.download_artifact = lambda s,p: b'x'
dl = ArtifactDownloader(c)
r = dl.download_all('cr_1', d)
print(r['count'])
print((d/'a.png').exists())
PY
```

**Expected:** Downloads files

### TC-CR005-002: Evidence Normalization
**Priority:** P0

**Steps:**
1. Run tests
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest /Users/skaparwan/github/testradius/harness/integrations/cloudroom/tests/test_normalize.py -v
```
2. Manual test
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python << 'PY'
from harness.integrations.cloudroom import EvidenceNormalizer
from pathlib import Path
import tempfile
d = Path(tempfile.mkdtemp())
src = d/'src'
src.mkdir()
(src/'s.png').write_bytes(b'png')
(src/'v.webm').write_bytes(b'webm')
norm = EvidenceNormalizer()
r = norm.normalize(src, '999', d)
print(len(r['screenshots']))
print(r['video'] is not None)
print((d/'run-999'/'manifest.json').exists())
PY
```

**Expected:** Normalized to expected structure

### TC-CR005-003: Live State Translation
**Priority:** P0

**Steps:**
1. Run tests
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest /Users/skaparwan/github/testradius/harness/integrations/cloudroom/tests/test_live_translate.py -v
```
2. Manual test
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python << 'PY'
from harness.integrations.cloudroom import LiveStateTranslator
t = LiveStateTranslator()
j = {'events':[{'message':'start'},{'message':'test done'}]}
s = t.translate(j, 'r1', 'https://x.com')
print(s['runId'])
print('progress' in s)
print('logs' in s)
print('steps' in s)
PY
```

**Expected:** Translates to harness format

---

## EPIC-CR006: Evals & Parallelism

### TC-CR006-001: Subagent Spawning
**Priority:** P1

**Steps:**
1. Run tests
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest /Users/skaparwan/github/testradius/harness/integrations/cloudroom/tests/test_subagents.py -v
```
2. Manual test
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius CLOUDROOM_TOKEN=test123 ./.venv/bin/python << 'PY'
from harness.integrations.cloudroom import CloudRoomClient, SubagentOrchestrator
c = CloudRoomClient()
c.spawn_subagent = lambda sid, prompt=None, model=None, **k: {'thread_id': f't-{model}'}
o = SubagentOrchestrator(c)
r = o.spawn_parallel('cr_1', ['p1','p2'], models=['m1','m2'])
print(len(r))
print(r[0]['status'])
PY
```

**Expected:** Spawns multiple subagents

### TC-CR006-002: Parallel Eval Runs
**Priority:** P1

**Steps:**
1. Test matrix
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius CLOUDROOM_TOKEN=test123 ./.venv/bin/python << 'PY'
from harness.integrations.cloudroom import CloudRoomClient, SubagentOrchestrator
c = CloudRoomClient()
c.spawn_subagent = lambda sid, prompt=None, model=None, **k: {'thread_id': f't-{model}'}
o = SubagentOrchestrator(c)
r = o.run_eval_matrix('cr_1', 'plan', ['gpt-4','claude','gemini'])
print(r['count'])
print(len(r['matrix']['models']))
PY
```

**Expected:** Matrix execution works

### TC-CR006-003: Automations Support
**Priority:** P1

**Steps:**
1. Run tests
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest /Users/skaparwan/github/testradius/harness/integrations/cloudroom/tests/test_automations.py -v
```

**Expected:** All pass

---

## EPIC-CR007: Testing, Docs & Hardening

### TC-CR007-001: E2E Spike Test Script
**Priority:** P1

**Steps:**
1. Check script exists
```bash
ls -la /Users/skaparwan/github/testradius/scripts/test_cloudroom_e2e.py
```
2. Run without token (should skip gracefully)
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python /Users/skaparwan/github/testradius/scripts/test_cloudroom_e2e.py
```

**Expected:** Skips or runs based on env

### TC-CR007-002: Error Handling & Resilience
**Priority:** P0

**Steps:**
1. Run tests
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest /Users/skaparwan/github/testradius/harness/integrations/cloudroom/tests/test_errors.py -v
```
2. Test health check failure
```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius CLOUDROOM_TOKEN=test123 ./.venv/bin/python << 'PY'
from harness.integrations.cloudroom import CloudRoomClient, CloudRoomError
c = CloudRoomClient()
c._request = lambda *a,**k: (_ for _ in ()).throw(CloudRoomError('fail'))
print(c.health_check())
PY
```

**Expected:** Graceful failure handling

### TC-CR007-003: Documentation
**Priority:** P1

**Steps:**
1. Check README
```bash
grep -n "Cloud Room" /Users/skaparwan/github/testradius/README.md | head -5
```
2. Check docs
```bash
ls -la /Users/skaparwan/github/testradius/docs/CLOUDROOM_INTEGRATION.md
grep -n "Configuration" /Users/skaparwan/github/testradius/docs/CLOUDROOM_INTEGRATION.md
```

**Expected:** Docs present

### TC-CR007-004: Security Review
**Priority:** P0

**Steps:**
1. Check security constraints in code
```bash
grep -n "_get_security_constraints" /Users/skaparwan/github/testradius/harness/execution/cloudroom.py
```
2. Check no secrets logged
```bash
grep -rn "CLOUDROOM_TOKEN" /Users/skaparwan/github/testradius/harness/integrations/cloudroom | grep -v "__pycache__" | grep -v ".pyc"
```
3. Verify token only from env
```bash
grep -n "os.environ.*CLOUDROOM_TOKEN" /Users/skaparwan/github/testradius/harness/integrations/cloudroom/client.py
```

**Expected:** Security measures in place

---

## Full Regression Test

Run all Cloud Room related tests together:

```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python -m pytest \
  /Users/skaparwan/github/testradius/harness/execution/tests \
  /Users/skaparwan/github/testradius/harness/integrations/cloudroom/tests \
  -v -o addopts=""
```

**Expected:** All tests pass (38+ tests)

## Smoke Test with Factory

```bash
cd /Users/skaparwan/github/testradius/apps/cell && PYTHONPATH=/Users/skaparwan/github/testradius ./.venv/bin/python << 'PY'
# Test all imports
from harness.execution import BaseExecutor, LocalPlaywrightExecutor, CloudRoomExecutor, create_executor, get_executor_mode
from harness.integrations.cloudroom import CloudRoomClient, ArtifactDownloader, EvidenceNormalizer, LiveStateTranslator, SubagentOrchestrator
print('All imports successful')
PY
```

**Expected:** No import errors

## Checklist
- [ ] All EPIC-CR001 tests pass
- [ ] All EPIC-CR002 tests pass
- [ ] All EPIC-CR003 tests pass
- [ ] All EPIC-CR004 tests pass
- [ ] All EPIC-CR005 tests pass
- [ ] All EPIC-CR006 tests pass
- [ ] All EPIC-CR007 tests pass
- [ ] Full regression passes
- [ ] No secrets in code/logs
- [ ] Feature flags work
- [ ] Docs complete
