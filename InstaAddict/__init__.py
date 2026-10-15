"""InstaAddict-AI - Human-like Instagram bot powered by UIAutomator2"""

__version__ = "1.4.3"
__tested_ig_version__ = "447.0.0.55.81"

import os
os.environ.setdefault("MPLBACKEND", "Agg")

from InstaAddict.core.bot_flow import start_bot


def run(**kwargs):
    start_bot(**kwargs)
