# 游戏影响标签与三路并行标注 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现游戏影响／非游戏影响／无法判断三级标签、三路可恢复并行标注、人工复核回填，并产出 Sayu、Dinah、Lucy 的完整分析工作簿。

**Architecture:** 类型模型定义固定方向与模块映射，提供者严格验证 Codex JSON 输出。标注阶段以独立批次文件并行调度并按原顺序合并；分析与工作簿按三级标签汇总，人工复核文件通过消息 ID 回填并重新聚合。

**Tech Stack:** Python 3.12、Pydantic、pytest、openpyxl、Codex CLI。

**Spec:** `docs/superpowers/specs/2026-09-22-game-impact-taxonomy-parallel-labeling-design.md`

## Global Constraints

- 11 个游戏二级模块保持独立，不合并。
- 非游戏影响必须归入主播表现、观众互动、技术与直播质量、系统与机器人、生活闲聊或其他非游戏内容。
- 只有无法判断的记录使用 `无法判断 / 其他 / 其他`，并为低置信度、需要人工复核。
- 标注并发峰值不超过 3，成功批次可安全复用，输出顺序必须与清洗输入一致。
- 生成的 CSV、JSON、批次文件和 XLSX 不提交 Git。

## Review Focus

- 二级模块与一级模块或一级方向不匹配时必须拒绝整批。（Task 1）
- 并发完成顺序不同不能改变最终 CSV 顺序。（Task 2）
- 限流只重试失败批次，不能覆盖成功批次。（Task 2）
- 人工复核文件中的陌生或重复消息 ID 必须拒绝导入。（Task 4）
- 主题汇总与图表必须按最终生效的三级标签重算。（Task 3、4）

---

### Task 1: 固定三级标签契约

**Files:** Modify `src/twitch_chat_workflow/models.py`, `src/twitch_chat_workflow/providers.py`, `src/twitch_chat_workflow/labeling.py`, `tests/test_codex_provider.py`, `tests/test_labeling.py`.

**Interfaces:** Produces `MessageLabel` with `impact_direction`, `primary_module`, `secondary_module`, `review_reason`; exposes `validate_taxonomy(label) -> None`.

- [ ] **Step 1: Write failing tests.** Add valid game, non-game and unable-to-determine labels; add invalid cross-mapping cases such as `游戏影响 / 战斗体验 / 剧情内容／叙事情绪` and `非游戏影响 / 主播表现 / BOSS 战`.
- [ ] **Step 2: Verify RED.** Run `pytest tests/test_codex_provider.py tests/test_labeling.py -v`; expect failures because current report-topic contract has no three-level mapping.
- [ ] **Step 3: Implement minimal contract.** Add Pydantic literals for all directions/modules, a single mapping constant, validation used by `MessageLabel` and response parsing, and CSV/batch persistence for all fields. Prompt Codex to use `无法判断 / 其他 / 其他` only when evidence is insufficient.
- [ ] **Step 4: Verify GREEN.** Run `pytest tests/test_codex_provider.py tests/test_labeling.py -v`; expect all valid mappings accepted and all invalid mappings rejected.
- [ ] **Step 5: Commit.** Run `git add src/twitch_chat_workflow/models.py src/twitch_chat_workflow/providers.py src/twitch_chat_workflow/labeling.py tests/test_codex_provider.py tests/test_labeling.py`; then `git commit -m "feat: add game impact label taxonomy"`.

### Task 2: 三路可恢复批次并行

**Files:** Modify `src/twitch_chat_workflow/labeling.py`, `src/twitch_chat_workflow/config.py`, `tests/test_labeling.py`, `tests/test_config.py`.

**Interfaces:** Consumes `LabelingConfig.concurrency`; produces ordered `labeled_chat.csv` from concurrently completed batch artifacts.

- [ ] **Step 1: Write failing tests.** Use a provider that completes batches in reverse order; assert maximum active calls is 3 and final message IDs preserve input order. Add a provider failing once for one batch; assert only that batch retries and completed batch files remain unchanged.
- [ ] **Step 2: Verify RED.** Run `pytest tests/test_labeling.py tests/test_config.py -v`; expect the current sequential loop to fail concurrency assertions.
- [ ] **Step 3: Implement minimal scheduler.** Use a bounded executor with at most `config.labeling.concurrency` futures; atomically write each successful batch, retry transient provider errors with bounded exponential backoff, and collect normalized results by batch number before one ordered CSV write.
- [ ] **Step 4: Verify GREEN.** Run `pytest tests/test_labeling.py tests/test_config.py -v`; expect concurrent execution, retry isolation and deterministic output.
- [ ] **Step 5: Commit.** Run `git add src/twitch_chat_workflow/labeling.py src/twitch_chat_workflow/config.py tests/test_labeling.py tests/test_config.py`; then `git commit -m "feat: label chat batches concurrently"`.

### Task 3: 三级主题分析与工作簿

**Files:** Modify `src/twitch_chat_workflow/analysis.py`, `src/twitch_chat_workflow/workbook.py`, `tests/test_analysis.py`, `tests/test_workbook.py`, `README.md`.

**Interfaces:** Consumes taxonomy-complete label rows; produces direction/module/submodule summary rows, trends, charts and an `人工复核` sheet.

- [ ] **Step 1: Write failing tests.** Assert direction, primary and secondary summaries are distinct; assert `BOSS 战` is not merged with `常规战斗`; assert non-game technical rows are not counted as game impact; assert the workbook includes an `人工复核` sheet with low-confidence records.
- [ ] **Step 2: Verify RED.** Run `pytest tests/test_analysis.py tests/test_workbook.py -v`; expect failures because current tables only support one report topic and four sheets.
- [ ] **Step 3: Implement minimal analysis/export.** Build three summary levels and secondary-module trend rows; create workbook sheets 标签明细、情绪趋势、主题、原话、人工复核; chart secondary Top 10; include direction/module/submodule and review reason in audit sheets.
- [ ] **Step 4: Verify GREEN.** Run `pytest tests/test_analysis.py tests/test_workbook.py -v && pytest -q`; expect all workbook structure, mapping and full-suite tests to pass.
- [ ] **Step 5: Commit.** Run `git add src/twitch_chat_workflow/analysis.py src/twitch_chat_workflow/workbook.py tests/test_analysis.py tests/test_workbook.py README.md`; then `git commit -m "feat: report game and non-game impact"`.

### Task 4: 人工复核导入与审核版报告

**Files:** Create `src/twitch_chat_workflow/review.py`; modify `src/twitch_chat_workflow/cli.py`; create `tests/test_review.py`; modify `src/twitch_chat_workflow/workbook.py`.

**Interfaces:** Produces `export_review_workbook(paths) -> Path` and `apply_review_workbook(config, paths, review_path) -> Path`.

- [ ] **Step 1: Write failing tests.** Export two review rows, edit one approved row, import it, and assert the final label changes. Add duplicate ID, unknown ID and invalid mapping cases that must raise without producing an audited workbook.
- [ ] **Step 2: Verify RED.** Run `pytest tests/test_review.py -v`; expect import/export functions to be absent.
- [ ] **Step 3: Implement minimal review loop.** Generate a separate `弹幕人工复核.xlsx` with immutable evidence columns and dropdown-constrained editable final fields; validate returned IDs and mappings; merge only `审核状态=已确认` rows, write an audit CSV, and generate `弹幕分析_人工审核版.xlsx`.
- [ ] **Step 4: Verify GREEN.** Run `pytest tests/test_review.py -v && pytest -q`; expect safe merge behavior and a green suite.
- [ ] **Step 5: Commit.** Run `git add src/twitch_chat_workflow/review.py src/twitch_chat_workflow/cli.py src/twitch_chat_workflow/workbook.py tests/test_review.py`; then `git commit -m "feat: support human label review"`.

### Task 5: Sayu、Dinah、Lucy 全量回归运行

**Files:** Read each source chat CSV discovered under `D:/主播分析结果/弹幕数据/`; generate ignored output directories under `D:/twitch-chat-workflow/results/`.

**Interfaces:** Consumes full Sayu, Dinah and Lucy chat records; produces one complete analysis workbook and one review workbook per streamer.

- [ ] **Step 1: Locate and count sources.** Use `rg --files D:/主播分析结果/弹幕数据` and record exact input paths and row counts in per-job configuration snapshots.
- [ ] **Step 2: Stage independent jobs.** Convert each source to raw JSONL without modifying it; set `batch_size=20`, `concurrency=3`, and distinct output paths.
- [ ] **Step 3: Run three jobs.** Run clean, label and aggregate for Sayu, Dinah and Lucy; do not run more than three Codex subprocesses within any job and preserve resumable artifacts.
- [ ] **Step 4: Verify artifacts.** Check every labeled CSV has the same number of rows as its clean CSV, all mappings are valid, all workbooks contain five sheets, and review-workbook counts match the flagged rows.
- [ ] **Step 5: Commit source only.** Run `git add README.md src tests docs/superpowers`; then `git commit -m "test: verify game impact workflow"`. Do not add generated outputs.
