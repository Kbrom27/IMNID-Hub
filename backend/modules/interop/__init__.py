"""
IMNID Hub Interoperability Module
Provides tracker and aggregate data synchronization between EMRs (Bahmni, OpenMRS 3)
and DHIS2 platforms.
"""

import os
import sys
from pathlib import Path

# Add interop directory to sys.path so submodule imports resolve
_interop_dir = Path(__file__).resolve().parent
_interop_dir_str = str(_interop_dir)
if _interop_dir_str not in sys.path:
    sys.path.insert(0, _interop_dir_str)

# Ensure aliases are registered in sys.modules so imports like `from clients...`
# work reliably in all environments (source, container, and PyInstaller frozen).
try:
    from backend.modules.interop import (
        config,
        clients,
        export,
        rules,
        transform,
        utils,
        emr_dhis2_tracker_sync,
    )
    for mod_name, mod_obj in [
        ("config", config),
        ("clients", clients),
        ("export", export),
        ("rules", rules),
        ("transform", transform),
        ("utils", utils),
        ("emr_dhis2_tracker_sync", emr_dhis2_tracker_sync),
    ]:
        sys.modules.setdefault(mod_name, mod_obj)
except Exception:
    pass
