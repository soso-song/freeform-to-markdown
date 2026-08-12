.PHONY: check format build privacy skill-check

check:
	uv run ruff check .
	uv run mypy src
	uv run pytest

format:
	uv run ruff format .
	uv run ruff check --fix .

build:
	uv build

privacy:
	uv run python scripts/privacy_scan.py

skill-check:
	@if [ -f "$${HOME}/.codex/skills/.system/skill-creator/scripts/quick_validate.py" ]; then \
		uv run python "$${HOME}/.codex/skills/.system/skill-creator/scripts/quick_validate.py" skills/freeform-to-markdown; \
	else \
		uv run python -c 'import pathlib,yaml; p=pathlib.Path("skills/freeform-to-markdown/SKILL.md"); t=p.read_text(); assert t.startswith("---\\n"); yaml.safe_load(t.split("---",2)[1]); print("Skill frontmatter valid (standalone check)")'; \
	fi
