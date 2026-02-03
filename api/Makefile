.PHONY: dev lint format type-check check all

# Start development server
dev:
	uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Run ruff linter
lint:
	ruff check .

# Run ruff formatter
format:
	ruff format .

# Fix linting issues
lint-fix:
	ruff check . --fix

# Run mypy type checker
type-check:
	mypy .

# Run all checks
check: lint type-check
	@echo "All checks passed!"

# Format and fix all issues
all: format lint-fix
	@echo "Code formatted and linted!"
