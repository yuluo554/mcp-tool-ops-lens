"""`python -m opslens` 通路入口。

与 console script（opslens）是两条不同的 sys.path 来源通路，CI 两条都要冒烟。
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
