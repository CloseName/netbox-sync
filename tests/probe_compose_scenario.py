"""Compatibility entrypoint for the now-authenticated production probe rehearsal."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).with_name('auth_compose_scenario.py')), run_name='__main__')
