"""
IMNID Hub Interoperability Module
Provides tracker and aggregate data synchronization between EMRs (Bahmni, OpenMRS 3)
and DHIS2 platforms.
"""

import sys
import importlib
from pathlib import Path

# Add interop and o3app directories to sys.path so submodule imports resolve
_interop_dir = Path(__file__).resolve().parent
_o3app_dir = _interop_dir / "o3app"

for _p in [str(_interop_dir), str(_o3app_dir)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

def register_interop_aliases():
    """Register top-level aliases for interop and o3app submodules so they resolve in frozen/packaged environments."""
    top_level = [
        'clients', 'config', 'export', 'import_', 'rules', 'transform',
        'utils', 'emr_dhis2_tracker_sync', 'models', 'o3app', 'o3'
    ]
    for name in top_level:
        full = f'backend.modules.interop.{name}'
        try:
            mod = importlib.import_module(full)
            sys.modules.setdefault(name, mod)
        except Exception:
            pass

    o3_submodules = [
        'clients', 'clients.openmrs_client', 'clients.dhis2_client',
        'config', 'extract', 'mappings', 'models', 'schemas', 'sync', 'utils',
        'export', 'export.extractors',
        'import_', 'import_.importer', 'import_.payload_builder',
        'rules', 'rules.tracker_mapping_rules',
        'transform', 'transform.investigations', 'transform.mapping',
        'transform.matcher', 'transform.normalizers', 'transform.pipeline',
        'export_unmapped_report'
    ]
    for sub in o3_submodules:
        full = f'backend.modules.interop.o3app.{sub}'
        try:
            mod = importlib.import_module(full)
            sys.modules.setdefault(f'o3app.{sub}', mod)
        except Exception:
            pass

register_interop_aliases()
