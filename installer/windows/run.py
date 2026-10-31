"""Runs SkyScope in the background on Windows (started by start.ps1 with pythonw.exe, which has no console):
its messages go to skyscope.log beside it. Arguments are passed on to skyscope.py (e.g. --host 127.0.0.1).
Designed and Created by Project Moon Pi."""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.stdout = sys.stderr = open(os.path.join(HERE, "skyscope.log"), "a", buffering=1, encoding="utf-8")
sys.path.insert(0, HERE)
sys.argv = [os.path.join(HERE, "skyscope.py"), "--web-only", "--no-browser", *sys.argv[1:]]
runpy.run_path(sys.argv[0], run_name="__main__")
