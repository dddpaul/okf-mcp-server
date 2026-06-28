---
id: TASK-1
title: Import and rename MCP engine from stacks as okf-mcp-server
status: Done
assignee: []
created_date: '2026-06-28 09:41'
updated_date: '2026-06-28 10:11'
labels: []
dependencies: []
priority: high
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Why

Несколько проектов-владельцев знаний (stacks, channels, core) должны использовать один MCP-движок как git-зависимость для федерации (один процесс на owner, decision-2). Сейчас движок живёт ВНУТРИ репозитория stacks как path-зависимость (stacks-mcp-server/), недоступная cross-repo. Этот репозиторий (okf-mcp-server) становится отдельным домом движка, owner-agnostic, подключаемым по git-URL с pin по тегу. Это deliverable B дизайна mcp-engine-extraction.

## Scope

In scope:
- Перенести содержимое пакета из источника (src-layout на hatchling: src/, tests/, pyproject.toml, uv.lock, README.md) в корень этого репозитория.
- Rename во всех местах: dist-имя stacks-mcp-server -> okf-mcp-server; import-пакет stacks_mcp_server -> okf_mcp_server (переименовать каталог src/stacks_mcp_server -> src/okf_mcp_server и все импорты); console scripts stacks-mcp-server/stacks-mcp-lint -> okf-mcp-server/okf-mcp-lint; env-переменные STACKS_MCP_OWNER/STACKS_MCP_ROOTS -> OKF_MCP_OWNER/OKF_MCP_ROOTS.
- Обновить README под новое имя/импорты/env.
- Настроить CI (pytest + mypy + ruff) на PR и на тег.
- Затегать релиз v0.2.0 после зелёного CI.

Out of scope:
- Правка кокпитов консьюмеров (stacks/channels/core: .mcp.json, mcp/server.py git-source) — отдельная работа на стороне консьюмеров.
- Изменение формата OKF или MCP-протокола — только упаковка/rename.
- Удаление stacks-mcp-server/ из исходного репозитория stacks — это отдельная задача на стороне stacks, выполняется ПОСЛЕ установки этого пакета.

## Files

Все пути ниже — в ИСТОЧНИКЕ (читать оттуда, переносить сюда):
- `/Users/paul/Private/Alfa/Projects/standard/stacks/stacks-mcp-server/src/stacks_mcp_server/{__init__,config,server,linter,cli,lint_cli}.py` (exists) — модули движка; config.py содержит резолв owner/roots.
- `/Users/paul/Private/Alfa/Projects/standard/stacks/stacks-mcp-server/tests/` (exists) — pytest-набор + fixtures (sample-project).
- `/Users/paul/Private/Alfa/Projects/standard/stacks/stacks-mcp-server/{pyproject.toml,uv.lock,README.md}` (exists) — метаданные пакета; pyproject содержит [project.scripts] и dist-имя для rename.
- `pyproject.toml` (to-create) — в корне этого репо, под именем okf-mcp-server.
- `src/okf_mcp_server/` (to-create) — переименованный пакет.

## Source

Source: /Users/paul/Private/Alfa/Projects/standard/stacks@d82455252eac
Source design doc (read-only context, do NOT modify): /Users/paul/Private/Alfa/Projects/standard/stacks/design/mcp-engine-extraction-brainstorm.md

ВАЖНО — зависимость base_dir: исходный движок дорабатывается параметром base_dir (deliverable A, TASK-87 в stacks). Перед переносом убедись, что забираешь АКТУАЛЬНУЮ версию config.py/__init__.py из источника, уже содержащую base_dir (проверь: `grep -r base_dir <source>/stacks-mcp-server/src`). Если base_dir в источнике ещё нет — STOP и сообщи пользователю (TASK-87 в stacks должна быть Done первой).

## Before starting (destination Claude validation checklist)

Before running this task, verify:
1. All `(exists)` file paths in the Files section still exist on disk (in the source repo).
2. Each AC is objectively pass/fail (grep/test/build command, not 'works correctly').
3. All dependencies in the task's frontmatter are status=Done.
4. Out-of-scope items are not accidentally pulled in (no consumer-cockpit edits, no source-side deletion).

If anything is unclear or any check fails: STOP and ask the user. Do NOT start work blindly.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Каталог src/okf_mcp_server/ существует со всеми модулями (config, server, linter, cli, lint_cli, __init__); grep -r stacks_mcp_server src/ tests/ возвращает 0 совпадений
- [x] #2 pyproject.toml в корне: name = okf-mcp-server; [project.scripts] определяет okf-mcp-server и okf-mcp-lint; нет упоминаний stacks-mcp-server
- [x] #3 grep -rn STACKS_MCP_ src/ tests/ возвращает 0 совпадений; env-переменные OKF_MCP_OWNER и OKF_MCP_ROOTS присутствуют в config
- [x] #4 uv run pytest проходит; uv run mypy . и uv run ruff check . чистые
- [x] #5 config.py содержит параметр base_dir (подтверждает перенос актуальной версии из источника после TASK-87)
- [x] #6 README обновлён под okf-mcp-server (имя, импорты okf_mcp_server, env OKF_MCP_*, console scripts)
- [x] #7 CI-конфиг существует и запускает pytest + mypy + ruff на PR и на push тега
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Plan: (1) copy src/, tests/, pyproject.toml, README.md from source @d82455252eac into repo root; (2) rename dir src/stacks_mcp_server -> src/okf_mcp_server; (3) global string rename across .py/.toml/.md: stacks_mcp_server->okf_mcp_server, stacks-mcp-server->okf-mcp-server, stacks-mcp-lint->okf-mcp-lint, STACKS_MCP_ROOTS->OKF_MCP_ROOTS, STACKS_MCP_OWNER->OKF_MCP_OWNER; (4) bump version 0.1.0->0.2.0; (5) regenerate uv.lock via uv lock; (6) manually fix README adoption sections (now standalone repo root, drop --directory/subdirectory); (7) add GitHub Actions CI (pytest+mypy+ruff on PR and tag push); (8) add Python entries to .gitignore; (9) verify uv run pytest/mypy/ruff green; (10) tag v0.2.0 — note: real green CI needs a GitHub remote (none yet), will flag at review.

AC #8 (tag v0.2.0 after green CI) BLOCKED: no git remote configured -> GitHub Actions cannot run. CI workflow (.github/workflows/ci.yml) is in place and all checks pass locally (ruff/mypy clean, 82 tests pass). Tag deferred until repo is pushed to a remote and CI goes green.

Commit: `3a56033` - task-1: import and rename MCP engine from stacks as okf-mcp-server

Commit: `407a3dd` - task-1: drop stale --directory phrasing in README linter section

AC #8 (release tag v0.2.0) extracted into TASK-2 (blocked on configuring a git remote so CI can run). Import/rename deliverable complete: package renamed, 82 tests + mypy + ruff green, CI workflow in place, README updated, reviewer APPROVED.
<!-- SECTION:NOTES:END -->
