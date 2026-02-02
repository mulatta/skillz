"""Entry point for python -m style_review."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
