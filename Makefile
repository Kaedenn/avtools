# Simple Makefile to trivialize certain tasks

PYTEST ?= pytest
TESTS = ./pytest
PYTEST_ARGS ?=

.PHONY: all test clean

all:

test:
	$(PYTEST) $(TESTS) $(PYTEST_ARGS)

clean:
	find . -name __pycache__ -exec rm -rf {} \+
	find . -name '*.pyc' -exec rm -rf {} \+
