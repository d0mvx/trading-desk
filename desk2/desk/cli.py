"""Grok Bot reads the desk here: python -m desk.cli "why X" | status | report | buy X ..."""
import asyncio, sys
from . import commands, report
if __name__ == "__main__":
    t = " ".join(sys.argv[1:]) or "status"
    if t == "report":
        print(report.markdown(current=True))
    else:
        print(asyncio.run(commands.arun(t, who="grokbot"))["text"])
