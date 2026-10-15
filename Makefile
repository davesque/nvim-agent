SKILL_DIR := $(CURDIR)/skill/neovim

.PHONY: test
test:
	uv run pytest

.PHONY: lint
lint:
	uv run ruff check
	uv run ruff format --check
	uv run ty check

.PHONY: format
format:
	uv run ruff check --fix
	uv run ruff format

.PHONY: check
check: lint test

# Symlink the skill into the Claude Code and Codex user skill directories.
.PHONY: install
install:
	mkdir -p $(HOME)/.claude/skills $(HOME)/.agents/skills
	ln -sfn $(SKILL_DIR) $(HOME)/.claude/skills/neovim
	ln -sfn $(SKILL_DIR) $(HOME)/.agents/skills/neovim

.PHONY: uninstall
uninstall:
	rm -f $(HOME)/.claude/skills/neovim $(HOME)/.agents/skills/neovim
