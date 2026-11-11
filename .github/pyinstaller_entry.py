"""PyInstaller entry point: run the CLI and pass its exit code to the OS."""

import sys

from jamstockex.__main__ import main

sys.exit(main())
