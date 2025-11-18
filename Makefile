# Makefile for Miller development
# Windows users: Install 'make' via chocolatey or use these commands directly

.PHONY: help setup build test test-rust test-python lint format clean watch

help:  ## Show this help message
	@echo "Miller Development Commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup:  ## First-time setup: install all dependencies
	python -m venv .venv
	.venv\Scripts\activate && pip install -e ".[dev]"
	rustup component add clippy rustfmt
	cargo install cargo-watch

build:  ## Build the Rust extension
	maturin develop --release

build-dev:  ## Build the Rust extension (debug mode, faster)
	maturin develop

test:  ## Run all tests (Rust + Python)
	cargo test
	pytest python/tests/

test-rust:  ## Run only Rust tests
	cargo test

test-python:  ## Run only Python tests
	pytest python/tests/ -v

test-cov:  ## Run Python tests with coverage report
	pytest python/tests/ --cov=miller --cov-report=html --cov-report=term

test-watch:  ## Auto-run tests on file changes
	pytest-watch python/tests/

lint:  ## Run all linters
	cargo clippy -- -D warnings
	ruff check python/
	mypy python/miller/

lint-fix:  ## Auto-fix linting issues
	ruff check --fix python/

format:  ## Format all code
	cargo fmt
	black python/

format-check:  ## Check formatting without changing files
	cargo fmt -- --check
	black --check python/

clean:  ## Clean build artifacts
	cargo clean
	rm -rf target/
	rm -rf python/tests/__pycache__/
	rm -rf python/miller/__pycache__/
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name "*.egg-info" -exec rm -rf {} +

watch-rust:  ## Watch Rust files and auto-rebuild + test
	cargo watch -x "test" -x "build"

watch-python:  ## Watch Python files and auto-test
	pytest-watch python/tests/

dev:  ## Start development mode (rebuild Rust on change)
	cargo watch -s "maturin develop && pytest python/tests/"
