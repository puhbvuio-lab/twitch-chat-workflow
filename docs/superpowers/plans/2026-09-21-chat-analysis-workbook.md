# Chat Analysis Workbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use the saved Codex CLI login to label every chat message and generate a traceable `弹幕分析.xlsx` workbook with label detail, sentiment trends, topic analysis, and original messages.

**Architecture:** A subprocess-backed `CodexSessionProvider` implements the existing provider protocol and returns schema-validated labels. Pure analysis functions derive sentiment and topic tables from the complete labeled CSV, while an isolated `openpyxl` exporter writes the four-sheet workbook atomically; the aggregate stage orchestrates compatible CSV/JSON plus workbook outputs.

**Tech Stack:** Python 3.11+, Typer, Pydantic v2, Codex CLI non-interactive mode, openpyxl, pytest.

**Spec:** `D:\twitch-chat-workflow\.worktrees\build\docs\superpowers\specs\2026-09-21-chat-analysis-workbook-design.md`

## Global Constraints

- The final workbook is exactly `04_chat_trends/弹幕分析.xlsx`.
- Workbook tabs are ordered `标签明细`, `情绪趋势`, `主题`, `原话`.
- The workbook is generated only after every label batch succeeds and `labeled_chat.csv` is complete.
- Existing `弹幕趋势.csv` and `弹幕趋势.json` remain machine-readable compatibility outputs.
- `codex_session` uses `codex exec --ephemeral --output-schema` and saved CLI authentication; the project never reads or stores auth files or tokens.
- CSV/JSON field names and sentiment enum values remain English.
- Original message text is preserved and traceable by stable `message_id`.
- Tests never call a real model, network, or saved Codex login.

## Review Focus

- A Codex response with duplicate IDs but the correct row count must fail rather than silently overwrite a message; Task 1 pins this.
- A timed-out subprocess must terminate, produce a safe bounded diagnostic, and leave the label stage retryable; Tasks 1 and 2 pin this.
- A prior successful batch may be reused only when its exact message IDs and schema still match the current batch; Task 2 pins this.
- A workbook export failure must preserve an existing complete workbook and remove the new temporary file; Task 4 pins this.
- An empty labeled dataset must create four readable sheets without invalid chart series or division-by-zero values; Tasks 3 and 4 pin this.

---

### Task 1: Implement the saved-login Codex label provider

**Files:**
- Modify: `src/twitch_chat_workflow/models.py`
- Modify: `src/twitch_chat_workflow/providers.py`
- Modify: `src/twitch_chat_workflow/config.py`
- Create: `tests/test_codex_provider.py`

**Interfaces:**
- Consumes: `list[ChatMessage]`, configured command path, model, context size, and timeout.
- Produces: `CodexSessionProvider.label(messages: list[ChatMessage]) -> list[MessageLabel]`; `CodexRunner(command: list[str], stdin: str, timeout_seconds: int) -> str`.

- [ ] **Step 1: Write failing provider tests**

Create a fake runner that records `command`, `stdin`, and timeout, returns literal JSON labels, and assert:

```python
provider = CodexSessionProvider(runner=fake, command="codex", timeout_seconds=120)
labels = provider.label([ChatMessage(message_id="m1", timestamp_seconds=1, text="好耶", original_text="好耶")])
assert labels == [MessageLabel(message_id="m1", sentiment="positive", topic="直播反馈", interest_signal=True)]
assert fake.command[:3] == ["codex", "exec", "--ephemeral"]
assert "--output-schema" in fake.command
assert '"message_id": "m1"' in fake.stdin
```

Add separate tests for malformed JSON, missing IDs, duplicate IDs, out-of-order IDs, invalid sentiment, nonzero exit, and timeout. Assert diagnostics omit a supplied sentinel resembling a token and are bounded to 800 characters.

- [ ] **Step 2: Run provider tests to verify RED**

Run: `python -m pytest tests/test_codex_provider.py -v`

Expected: collection FAIL because `CodexSessionProvider` and `CodexRunner` do not exist.

- [ ] **Step 3: Add provider configuration and structured models**

Extend `LabelingConfig` with `codex_command: str = "codex"` and `timeout_seconds: int = Field(default=300, ge=1)`. Add a private Pydantic response envelope containing `labels: list[MessageLabel]`; keep auth fields absent from every model and redacted snapshot.

- [ ] **Step 4: Implement runner and provider**

Implement a subprocess runner using `subprocess.run(..., input=stdin, text=True, encoding="utf-8", capture_output=True, timeout=timeout_seconds, check=False)`. Create a temporary JSON Schema file, invoke `codex exec --ephemeral --output-schema <path> -`, parse the final JSON, validate exact ID order and uniqueness, and always remove the schema file. Translate subprocess and validation failures into safe `RuntimeError` messages with exception chaining.

- [ ] **Step 5: Run focused and config tests**

Run: `python -m pytest tests/test_codex_provider.py tests/test_config.py -v`

Expected: PASS.

- [ ] **Step 6: Commit provider implementation**

```powershell
git add src/twitch_chat_workflow/models.py src/twitch_chat_workflow/providers.py src/twitch_chat_workflow/config.py tests/test_codex_provider.py
git commit -m "feat: add saved-login Codex label provider"
```

### Task 2: Resume validated label batches and wire the default provider

**Files:**
- Modify: `src/twitch_chat_workflow/labeling.py`
- Modify: `src/twitch_chat_workflow/cli.py`
- Modify: `tests/test_labeling.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `CodexSessionProvider`, `batch-XXXX.json`, and `LabelingConfig`.
- Produces: complete `labeled_chat.csv`; `_load_valid_batch(path: Path, expected_ids: list[str]) -> list[MessageLabel] | None`.

- [ ] **Step 1: Add failing resume and CLI tests**

Write a counting fake provider. Pre-create `batch-0001.json` with valid rows and verify only batch 2 calls the provider. Add cases where a batch file has wrong IDs or invalid schema and must be rerun. In the CLI test, monkeypatch `CodexSessionProvider`, call the label stage with `labeling.enabled=true`, and assert the default provider is constructed when none is injected.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_labeling.py tests/test_cli.py -v`

Expected: FAIL because every batch currently calls the provider and CLI passes `None`.

- [ ] **Step 3: Implement strict batch reuse**

Read each existing batch JSON through Pydantic. Reuse it only when batch number, provider metadata, row count, exact ordered IDs, ID uniqueness, and label schema are valid. Otherwise call the provider and atomically replace that batch. Build `labeled_chat.csv` only after all batches succeed.

- [ ] **Step 4: Construct the default Codex provider in CLI orchestration**

When `name == "label"` and labeling is enabled, instantiate `CodexSessionProvider` from config. Preserve dependency injection by allowing `label_chat` tests and external callers to pass their own provider directly.

- [ ] **Step 5: Run labeling, CLI, and state tests**

Run: `python -m pytest tests/test_labeling.py tests/test_cli.py tests/test_state.py -v`

Expected: PASS.

- [ ] **Step 6: Commit resumable integration**

```powershell
git add src/twitch_chat_workflow/labeling.py src/twitch_chat_workflow/cli.py tests/test_labeling.py tests/test_cli.py
git commit -m "feat: resume Codex label batches"
```

### Task 3: Add pure sentiment and topic analysis tables

**Files:**
- Create: `src/twitch_chat_workflow/analysis.py`
- Create: `tests/test_analysis.py`

**Interfaces:**
- Consumes: labeled rows as `list[dict[str, str]]`, interval seconds, optional bounds.
- Produces: `AnalysisTables(label_rows, sentiment_rows, topic_summary_rows, topic_trend_rows, quote_rows)` via `build_analysis_tables(...)`.

- [ ] **Step 1: Write failing analysis tests from hand-checked rows**

Use five literal messages spanning two windows and two topics. Assert exact sentiment counts/shares including an empty window; topic count/share, first/last time, stable count-then-name ordering; first three unique quotes in chronological order; and window-topic shares. Add an empty-input case returning empty detail tables and zero safe values.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_analysis.py -v`

Expected: collection FAIL because `analysis.py` does not exist.

- [ ] **Step 3: Implement immutable analysis output**

Create a frozen dataclass `AnalysisTables`. Normalize blank topic to `其他`, sort input by `(timestamp_seconds, message_id)`, reuse the half-open window semantics from `aggregate_chat`, and derive all five tables without mutating input rows. Do not fuzzy-merge topics or summarize quotes with a model.

- [ ] **Step 4: Run analysis and aggregation regression tests**

Run: `python -m pytest tests/test_analysis.py tests/test_workflow_stages.py tests/test_smoke.py -v`

Expected: PASS.

- [ ] **Step 5: Commit analysis layer**

```powershell
git add src/twitch_chat_workflow/analysis.py tests/test_analysis.py
git commit -m "feat: derive sentiment and topic analysis"
```

### Task 4: Generate the four-sheet workbook atomically

**Files:**
- Create: `src/twitch_chat_workflow/workbook.py`
- Create: `tests/test_workbook.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `AnalysisTables`, destination `Path`, and interval seconds.
- Produces: `write_analysis_workbook(tables: AnalysisTables, destination: Path) -> Path`.

- [ ] **Step 1: Add openpyxl dependency and write failing workbook tests**

Add `openpyxl>=3.1,<4`. Build literal `AnalysisTables`, write to `tmp_path / "弹幕分析.xlsx"`, reload with `openpyxl.load_workbook`, and assert:

```python
assert workbook.sheetnames == ["标签明细", "情绪趋势", "主题", "原话"]
assert workbook["标签明细"].freeze_panes == "A2"
assert workbook["标签明细"].auto_filter.ref is not None
assert workbook["标签明细"]["F2"].value == "原始弹幕"
assert len(workbook["情绪趋势"]._charts) == 1
assert len(workbook["主题"]._charts) == 1
```

Also test percentage number formats, Chinese yes/no values, representative quotes, empty data without charts, and atomic failure by monkeypatching save to raise while a sentinel destination already exists.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_workbook.py -v`

Expected: collection FAIL because `write_analysis_workbook` does not exist.

- [ ] **Step 3: Implement workbook layout and charts**

Create four sheets in required order, write Chinese headers and typed values, add filters and freeze panes, set bounded column widths/wrapping, apply one consistent header style, and format shares as `0.0%`. Add a 0–100% line chart from sentiment shares and a Top 10 topic count bar chart only when data rows exist.

- [ ] **Step 4: Implement atomic save**

Save to a unique sibling `.tmp.xlsx`, reopen it once to verify the four sheet names, then use `Path.replace(destination)`. In `finally`, remove only that explicit temporary path if it still exists. Never delete or overwrite the previous destination before validation succeeds.

- [ ] **Step 5: Run workbook tests**

Run: `python -m pytest tests/test_workbook.py -v`

Expected: PASS.

- [ ] **Step 6: Commit workbook exporter**

```powershell
git add pyproject.toml src/twitch_chat_workflow/workbook.py tests/test_workbook.py
git commit -m "feat: export chat analysis workbook"
```

### Task 5: Integrate the workbook into aggregation, CLI, state, and docs

**Files:**
- Modify: `src/twitch_chat_workflow/aggregation.py`
- Modify: `src/twitch_chat_workflow/cli.py`
- Modify: `tests/test_workflow_stages.py`
- Modify: `tests/test_smoke.py`
- Modify: `README.md`
- Modify: `examples/job.json`

**Interfaces:**
- Consumes: complete `labeled_chat.csv`, `build_analysis_tables`, and `write_analysis_workbook`.
- Produces: `弹幕趋势.csv`, `弹幕趋势.json`, and `弹幕分析.xlsx` from `aggregate_stage`.

- [ ] **Step 1: Write failing integration tests**

Enable labeling in the smoke config, use a deterministic fake provider, run acquire → clean → label → aggregate, then assert all three final files exist and the workbook has the required sheets. Add a test where labeling is disabled or `labeled_chat.csv` is absent and assert aggregate raises a clear error without creating `弹幕分析.xlsx`.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_workflow_stages.py tests/test_smoke.py -v`

Expected: FAIL because aggregate neither requires labels nor writes a workbook.

- [ ] **Step 3: Integrate analysis and workbook artifacts**

Make aggregate require the complete labeled file, read it once, build `AnalysisTables`, continue writing compatible trend CSV/JSON, and atomically write `弹幕分析.xlsx`. Include all three paths in the stage artifact list and add a workbook format version to the aggregation fingerprint.

- [ ] **Step 4: Update README and example**

Set `labeling.enabled` to `true` in the example. Document saved Codex CLI login, optional command/timeout settings, retry behavior, the four sheets, charts, output paths, failure behavior, and the requirement that all label batches succeed.

- [ ] **Step 5: Run the complete suite**

Run: `python -m pytest -q`

Expected: all tests PASS without network or real Codex calls.

- [ ] **Step 6: Inspect only intended changes and commit**

Run: `git diff --check` and `git status --short`.

Expected: only planned source, test, dependency, example, and README files are changed; no generated workbook, auth data, prompt payload, or pytest temp directory is tracked.

```powershell
git add README.md examples/job.json pyproject.toml src/twitch_chat_workflow tests
git commit -m "feat: generate traceable chat analysis workbook"
```

### Task 6: Final verification and GitHub delivery

**Files:**
- Verify: all tracked project files.

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: a tested branch synchronized with GitHub `main`.

- [ ] **Step 1: Run fresh full verification**

Run: `python -m pytest -q`

Expected: zero failures and zero errors.

- [ ] **Step 2: Verify interface and security boundaries**

Run: `rg -n "auth\.json|access[_-]?token|OPENAI_API_KEY|CODEX_ACCESS_TOKEN" src tests README.md examples`.

Expected: no code reads or writes authentication files/tokens; README may only state that credentials are not stored.

Run: `git diff origin/main..HEAD --check` and `git status --short`.

Expected: clean tracked worktree and no whitespace errors.

- [ ] **Step 3: Push only after all checks pass**

```powershell
git push origin HEAD:main
```
