#!/usr/bin/env bash
# Risk-rule enforcement tests (isolated temp dirs, no network, no live state). Usage: tests/run_all.sh
cd "$HOME/.desk" && exec ./venv/bin/python -W ignore -m unittest discover -s tests -p "test_*.py" -v
