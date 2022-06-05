# Simple Makefile to trivialize certain tasks

PYTEST ?= pytest
TESTS = ./pytest
PYTEST_ARGS ?=

.PHONY: all test

all:

test:
	$(PYTEST) $(TESTS) $(PYTEST_ARGS)
