"""
IMNID Hub O3 (OpenMRS 3) Module Package
"""

import sys
from pathlib import Path

_o3app_dir = Path(__file__).resolve().parent
_interop_dir = _o3app_dir.parent

for _p in [str(_interop_dir), str(_o3app_dir)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from backend.modules.interop import register_interop_aliases
    register_interop_aliases()
except Exception:
    pass
