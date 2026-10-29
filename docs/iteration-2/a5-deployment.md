# A5: release verification

## Status

**Verified complete on 2026-10-29 at 13:24 UTC.** After A6 completed its
unchanged baseline, the coordinator explicitly cleared this release and assigned
A5 the exclusive deployment/diagnosis slot. No provisioning, capacity/network
changes or destructive recovery were performed. The live slot is released.

Release source: `85a1e4d2cfd148ea406e00f8c9019e573eaf44a9`, an existing
`main` revision containing PR #1 (merge `85b5882`). The A5 branch changes
documentation only. Deploy the pinned source, never an iteration-2 feature branch.
An ignored source archive was prepared directly with `git archive` at that revision;
the archive contains no feature implementations. Its own virtual environment and
editable import paths were checked before repeating all full gates there.

This verifies the existing review fixes, not A1–A4 or A6 implementations. The
iteration-2 [plan](../plan-iteration-2.md) defines the coordinated release schedule.

## Preparation evidence

| Check | Result |
|---|---|
| `uv run --frozen ruff check` | Passed |
| `uv run --frozen ruff format --check` | Passed; 73 files |
| `uv run --frozen pyright` | Passed; no errors or warnings |
| `uv run --frozen pytest -q` | Passed; 108 tests |
| Capture and episode suites | Passed; 28 tests |
| Diagnostics function packaging | Passed; 21 installed entries |
| Platform API function packaging | Passed; 196 installed entries |
| Packaged workspace distributions | Both apps contain their declared workspace dependencies; no editable egg links |
| Agent dependency export | Has SHA-256 hashes; no index or direct HTTP source directives |
| Docker-context fixture | Passed; 12 assertions using Docker SDK archive-selection rules |
| Local Docker image build | Not run: Docker daemon unavailable; actual remote build verified below |
| Existing deployment inventory | Read-only function resource/deployment history, five agent versions and current image manifest captured privately |

## Release and hosted evidence

The approved `azd deploy --all --no-prompt` ran from the pinned archive between
13:19:51 and 13:21:45 UTC on 2026-10-29; exit status **0**.

| Live check | Result |
|---|---|
| Diagnostics function | New deployment ID; status 4, complete; finished 13:20:04 UTC |
| Platform API function | New deployment ID; status 4, complete; finished 13:20:33 UTC |
| Hosted agent | New version; active environment endpoint version matches |
| Remote container build | Succeeded; full build log includes `import mcp, tenacity, rca_agent.main` smoke check and successful build |
| Deployed image provenance | Hosted image digest equals successful remote-build output; differs from pre-release digest |
| Toolbox and episode-store access | Default toolbox includes MCP and search; current agent identity has its documented Cosmos data contributor role |
| Isolated hosted diagnosis | Succeeded, 13:22:28–13:23:38 UTC; CLI wall time 70.032 s |
| Episode identity checks | Unique synthetic input, creation/completion interval and rendered report match the isolated CLI response |
| `csai episodes show` | Exit 0 |
| Full API episode | Succeeded; 22,241 UTF-8 JSON bytes, below 1,500,000-byte budget |
| Full stored tool results | All 9 JSON payloads equal deterministic seed results with the exact recorded arguments |
| Truncation | All 9 `result_truncated` flags false; episode `truncated` empty |

The complete API payload, not the CLI preview, was inspected. The nine calls were
machine context, error events, logbook, three error-code lookups and three
telemetry windows. Stored payload sizes were respectively 1,021; 3,210; 717;
545/356/147; and 1,022/1,058/1,032 bytes. Equality with complete expected JSON
checks every field and the payload tails. No live result needed truncation.
Explicit truncation markers and over-budget behavior were verified by the
offline capture/budget tests, not by manufacturing an oversized hosted request.

The stored episode interval was 41.101 s; token usage was 10,345 input and 1,377
output. Captured tool durations ranged from 0.273 to 17.650 s. These are one
post-release smoke observation, not an unchanged A6 baseline or a performance
claim. Calls can overlap; subtracting their sum from wall time would not establish
model latency.

Complete deployment/build logs, pre/post environment snapshots, image manifests,
service history and the full episode remain private in ignored artifacts.
Neither source provenance of the older function packages nor general concurrent
response/episode correlation was established by this check. The latter is A4.

The isolated environment initially lacked `ruff`. After that missing-tool failure,
`uv sync --all-packages --frozen` restored dependencies using a copy of the
ignored local lock. No dependency manifest changed. Package restoration and
editable workspace imports stayed in this worktree.

The capture tests retain a result longer than the old per-tool cutoff, including
its final evidence reference. Oversized results are flagged and fitted to the
1,500,000-byte episode budget. The episode tests also cover multibyte text,
arguments, errors, input and structured output. These are offline checks; they
do not establish what is currently deployed.

Both function packages were actually built with the existing hooks: locked,
hashed third-party Linux wheels plus workspace wheels. Generated wheel and
requirements intermediates were removed by the hook. Generated package trees,
the lock and the agent requirements export remain ignored.

The Docker fixture contains only `NONSECRET_A5_FIXTURE` text. It checks root and
nested `.env` and `.env.*` exclusions, private environment and function-package
exclusions, and retention of agent/platform source and the generated agent lock
export. It uses the Docker SDK's build-context selector without a daemon, not a
grep of `.dockerignore`. Actual remote image construction and its import smoke
check also passed during the release.

## Reproduce the offline checks

Start from the pinned revision in an isolated checkout with its own virtual
environment. Retain the tested ignored lock privately; do not commit it.

```bash
git rev-parse HEAD
uv run --frozen ruff check
uv run --frozen ruff format --check
uv run --frozen pyright
uv run --frozen pytest -q
uv run --frozen pytest -q \
  packages/cs-platform/tests/test_capture.py \
  packages/cs-platform/tests/test_episodes.py
(cd services/diagnostics-mcp &&
  ../../scripts/package_function.sh diagnostics-mcp diagnostics-domain)
(cd services/platform-api &&
  ../../scripts/package_function.sh platform-api cs-platform)
(cd agents/rca &&
  uv export --frozen --package rca-agent --no-dev --no-emit-workspace \
    --no-header --quiet -o requirements.lock.txt)
```

For the non-secret context fixture, install the Docker Python SDK into an
ignored, isolated tool directory if it is missing. This is verification tooling,
not an application dependency. The following runs without a Docker daemon:

```bash
mkdir -p .azure/a5-private
uv pip install --target .azure/a5-private/contextdeps docker==7.2.0
PYTHONPATH=.azure/a5-private/contextdeps uv run --frozen python - <<'PY'
from pathlib import Path
from docker.utils.build import exclude_paths

root = Path(".azure/a5-private/context-fixture")
fixtures = {
    ".env": False,
    ".env.fixture": False,
    "agents/rca/.env": False,
    "agents/rca/.env.fixture": False,
    "services/platform-api/deeper/.env": False,
    "services/platform-api/deeper/.env.fixture": False,
    "agents/rca/requirements.lock.txt": True,
    "agents/rca/src/rca_agent/main.py": True,
    "packages/cs-platform/src/cs_platform/capture.py": True,
    "uv.lock": False,
    ".azure/example/.env": False,
    "services/platform-api/.python_packages/lib/site-packages/example.py": False,
}
for name in fixtures:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("NONSECRET_A5_FIXTURE\n")
included = set(exclude_paths(str(root), Path(".dockerignore").read_text().splitlines()))
assert all((name in included) == expected for name, expected in fixtures.items())
print(f"{len(fixtures)} context assertions passed")
PY
```

Do not inspect actual environment files to test exclusions.

After deploying the pinned source and obtaining the serialized model slot, run
one unique synthetic incident, then inspect its full episode. Keep the episode
identifier in the process environment rather than this document:

```bash
uv run --frozen csai diagnose \
  "M-0007: Pressure excursions; purge flow looks lower than normal. UNIQUE_SYNTHETIC_RELEASE_MARKER." \
  --target hosted
printf 'Paste the episode ID printed by this diagnosis: '
read -r A5_EPISODE_ID
export A5_EPISODE_ID
: "${A5_EPISODE_ID:?An episode ID from this diagnosis is required}"
uv run --frozen csai episodes show "$A5_EPISODE_ID"
uv run --frozen python - <<'PY'
import json
import os
from csai.environment import load_environment
from csai.platform import PlatformClient
from cs_platform.episodes import EPISODE_MAX_BYTES
from diagnostics_mcp.tools import DiagnosticsTools

load_environment()
episode = PlatformClient.from_env().get_episode(os.environ["A5_EPISODE_ID"])
tools = DiagnosticsTools.from_seed()
methods = {
    "get_machine_context": tools.machine_context,
    "get_error_events": tools.error_events,
    "get_logbook": tools.logbook,
    "lookup_error_code": tools.error_code,
    "get_telemetry_window": tools.telemetry_window,
}
assert episode.status == "succeeded"
assert len(episode.model_dump_json().encode()) <= EPISODE_MAX_BYTES
assert not episode.truncated, "Full-payload verification requires an untruncated episode"
assert episode.tool_calls
diagnostic_calls = 0
search_calls = 0
for call in episode.tool_calls:
    assert call.error is None
    assert call.result is not None
    assert not call.result_truncated, f"{call.name}: stored result was truncated"
    name = call.name.rpartition("___")[2]
    if name == "azure_ai_search":
        search_calls += 1
        continue
    assert name in methods, f"Unexpected tool: {call.name}"
    expected = methods[name](**call.arguments)
    assert json.loads(call.result) == expected.model_dump(mode="json")
    diagnostic_calls += 1
assert diagnostic_calls, "No diagnostic payloads were compared"
print(f"Full stored diagnostic payload checks passed ({diagnostic_calls} calls)")
if search_calls:
    print(
        f"{search_calls} search payload(s) present and untruncated; "
        "retrieval contents require a separate comparison, not diagnostic seed equality"
    )
PY
```

In addition, compare the unique input, request time window and rendered stored
report with the CLI output, as done for this release. Do not use this workaround
as authoritative correlation for simultaneous identical requests.

## Private inventory and recovery

Before any release, private ignored artifacts record the active environment,
function resources and successful deployment IDs/times, existing hosted versions,
current container configuration and image manifest/digest. Raw identifiers,
endpoints, environment values and Azure output are deliberately absent here.
The inventory was collected with `az functionapp show`,
`az webapp log deployment list`, the installed projects SDK's
`agents.list_versions`, and `az acr repository show`, using environment-derived
arguments rather than hard-coded resource names.

Recovery is a coordinator decision, not an automatic destructive rollback:

1. Stop further releases and retain the failing release logs privately.
2. Keep the existing hosted version and immutable image reference. Restore its
   routing only through a supported hosting workflow after explicit approval.
3. For each function, identify a retained known-good deployment package, or the
   exact prior source plus matching lock, before code-only recovery. Deployment
   IDs/timestamps alone do not prove source provenance or provide a package.
   The original function source/package provenance is **not yet verified**.
4. With approval, use a service-scoped deployment of the recovered artifact
   (`azd deploy SERVICE --from-package APPROVED_PACKAGE`) or verified approved
   source. Do not assume Functions supports selecting an old deployment by ID.
5. If artifacts cannot be recovered, record that limitation and choose an
   approved forward fix instead. Re-run the hosted/episode checks after recovery.

Never delete versions or network-injected resources, provision infrastructure,
change networking/capacity, purge resources or perform an automatic rollback.

## Coordinated release checklist

- [x] Pin existing main source containing PR #1.
- [x] Pass full offline gates, budget tests, packaging and fixture verification.
- [x] Record existing versions, image reference and guarded recovery procedure.
- [x] Receive explicit baseline-cleared release message from the coordinator.
- [x] Deploy all three services from the pinned source with the approved
      `azd deploy --all`; retain complete output privately and inspect hook/build
      results, not just the command summary.
- [x] Verify both Functions deployments succeeded and the new hosted version
      references the new image; inspect the remote image import smoke check.
- [x] Obtain the serialized model slot and run one isolated hosted diagnosis.
- [x] Run `uv run csai episodes show EPISODE_ID`.
- [x] Fetch the same full episode using
      `PlatformClient.from_env().get_episode(episode_id)`, not only the CLI
      summary. Compare its unique synthetic request, timestamps and report with
      the isolated response. This is not a proof of A4 correlation.
- [x] Inspect every stored tool result and truncation flag. Check serialized
      episode bytes against `EPISODE_MAX_BYTES`. For an untruncated result, compare
      the complete payload/evidence tail with the deterministic diagnostic tool
      output where available. Do not infer completeness from a preview.
- [x] Check truncation indicators: none occurred in the hosted smoke; offline
      overflow cases verify `result_truncated` and
      `episode.truncated` explicitly. Do not manufacture a huge hosted request;
      the offline tests exercise the overflow path without model costs.
- [x] Record sanitized post-release evidence and verification time here; mark
      A5 complete only if the release and hosted checks pass.

`csai eval rca --target local` was not run: this preparation changes no
instructions, schemas, tools, capture implementation or eval data, and model
traffic is reserved for the serialized measurement/release schedule. The approved
single hosted diagnosis, full API payload verification and deployment passed.
