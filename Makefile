# readback: make selftest | example-site | install | install-codex | uninstall
CLAUDE_SKILLS ?= $(HOME)/.claude/skills
CODEX_HOME    ?= $(HOME)/.codex
CODEX_SKILLS  ?= $(CODEX_HOME)/skills
BIN           ?= $(HOME)/.local/bin

selftest:
	python3 tests/test_validation.py DossierTests
	python3 tests/selftest.py

selftest-lean:     ## additionally exercise the native range reader with the example toolchain
	READBACK_TEST_LEAN=1 python3 tests/test_validation.py NativeRangeTests

example-site:     ## the site of the worked example, under build/tiny-site/ (needs LaTeX and poppler for the reader)
	rm -rf build/tiny-ws build/tiny-site
	python3 skills/readback/scripts/rb.py init build/tiny-ws --artifact examples/tiny-lean --root Tiny.Main --name "Tiny sums" > /dev/null
	cp -R examples/tiny-sample/units/3 build/tiny-ws/reading/units/3
	cp -R examples/tiny-sample/notes/gauss build/tiny-ws/notes/gauss
	cd build/tiny-ws && python3 tools/rb.py check 3 > /dev/null && python3 tools/rb.py note gauss > /dev/null && python3 tools/rb.py status > /dev/null && python3 tools/rb.py site --out ../tiny-site

install:          ## the writer's skill, for Claude Code
	mkdir -p "$(CLAUDE_SKILLS)"
	rm -rf "$(CLAUDE_SKILLS)/readback"
	cp -R skills/readback "$(CLAUDE_SKILLS)/readback"
	cp -R skills/readback-reader "$(CLAUDE_SKILLS)/readback/assets/readback-reader"
	find "$(CLAUDE_SKILLS)/readback" -name __pycache__ -prune -exec rm -rf {} +
	@echo "installed: $(CLAUDE_SKILLS)/readback (start a new Claude Code session to load it)"
	@mkdir -p "$(BIN)" 2>/dev/null; if [ -d "$(BIN)" ]; then \
	  printf '#!/bin/sh\n# Start the writing agent (Claude Code) of a Readback workspace. Made by `make install` of Readback.\nexec python3 "%s/readback/scripts/rb.py" start writer "$$@"\n' "$(CLAUDE_SKILLS)" > "$(BIN)/readback-claude"; \
	  printf '#!/bin/sh\n# Start the reading agent (Codex) of a Readback workspace. Made by `make install` of Readback.\nexec python3 "%s/readback/scripts/rb.py" start reader "$$@"\n' "$(CLAUDE_SKILLS)" > "$(BIN)/readback-codex"; \
	  chmod +x "$(BIN)/readback-claude" "$(BIN)/readback-codex"; \
	  echo "installed: $(BIN)/readback-claude and $(BIN)/readback-codex (the two commands that start the agents)"; \
	  case ":$$PATH:" in *":$(BIN):"*) ;; *) echo "NOTE: $(BIN) is not on your PATH: add it, or call the two commands by their full path";; esac; \
	else echo "no $(BIN): the two start commands are $(CLAUDE_SKILLS)/readback/scripts/readback-claude and readback-codex"; fi

install-codex:    ## the reader's skill, for Codex
	mkdir -p "$(CODEX_SKILLS)"
	rm -rf "$(CODEX_SKILLS)/readback-reader"
	cp -R skills/readback-reader "$(CODEX_SKILLS)/readback-reader"
	find "$(CODEX_SKILLS)/readback-reader" -name __pycache__ -prune -exec rm -rf {} +
	@echo "installed: $(CODEX_SKILLS)/readback-reader"

uninstall:
	rm -rf "$(CLAUDE_SKILLS)/readback" "$(CODEX_SKILLS)/readback-reader"
	rm -f "$(BIN)/readback-claude" "$(BIN)/readback-codex"

.PHONY: selftest selftest-lean example-site install install-codex uninstall
