#!/usr/bin/env python3

"""
Top-level configuration for the imagemanage.py test suite
"""

import pytest
import os
import shutil

from helpers import debugging
from helpers.debugging import *

pytest_plugins = ["pytester"]

ICONS_PATH = "/usr/share/icons/Yaru/256x256"

# To allow tests to import the modules being tested
sys.path.append(os.path.join(os.path.dirname(__file__), os.pardir))

def pytest_addoption(parser):
  parser.addoption("--icons-path", action="store", default=ICONS_PATH, help="override {ICONS_PATH} path")
  parser.addoption("--debug-tests", action="store_true", help="enable debugging within tests")

def pytest_configure(config):
  if config.getoption("--debug-tests"):
    debugging.logger.setLevel(logging.DEBUG)
    write_to_terminal("Debugging enabled")
  else:
    write_to_terminal("Debugging disabled")
  debugging.logger.info("Debug logging enabled")

@pytest.fixture(scope="session")
def assets_config(pytestconfig, tmp_path_factory):
  "Provide all the configuration needed for interacting with testing assets"
  assets_local = tmp_path_factory.mktemp("test-assets")
  return {
    "icons-path": pytestconfig.getoption("--icons-path"),
    "assets-local": assets_local,
    "icons-local": os.path.join(assets_local, "icons")
  }

@pytest.fixture(scope="session")
def local_icons(pytestconfig, assets_config):
  ipath = assets_config["icons-path"]
  ilocal = assets_config["icons-local"]
  debug_write(f"Copying {ipath} to {ilocal}...")
  shutil.copytree(ipath, ilocal)
  return ilocal

# vim: set ts=2 sts=2 sw=2:

