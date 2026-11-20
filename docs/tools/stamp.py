"""
stamp.py - write the build marker into index.html.

"I refreshed and nothing changed" is nearly always a browser showing a cached page, and there is no
way to tell by looking.  So the page carries a visible marker - the date and the commit it was built
from - in the header, next to the title.  Run this before committing a change to the page:

    python3 tools/stamp.py

It also puts the same commit on the <script> tag as ?v=..., so a fresh index.html always fetches a
fresh app.js rather than the cached one.  (GitHub Pages serves everything with a ten-minute cache and
there is no way to change that, so a hard refresh - Ctrl+Shift+R - is still the quick cure.)
"""
import datetime
import pathlib
import re
import subprocess
import sys

PAGE = pathlib.Path(__file__).resolve().parent.parent / "index.html"


def short_sha():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=PAGE.parent, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "local"


def main():
    sha = short_sha()
    # Malaysia time, which is where this is written
    stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    marker = f"build {stamp:%d %b %Y %H:%M} ({sha})"
    text = PAGE.read_text()
    new = re.sub(r'(<span class="sub build" id="build">)[^<]*(</span>)',
                 lambda m: m.group(1) + marker + m.group(2), text, count=1)
    new = re.sub(r'(<script type="module" src="app\.js)(\?v=[^"]*)?(">)',
                 lambda m: f'{m.group(1)}?v={sha}{m.group(3)}', new, count=1)
    if new == text:
        print("Nothing to stamp: the marker or the script tag is not where it was expected.")
        return 1
    PAGE.write_text(new)
    print(f"index.html stamped: {marker}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
