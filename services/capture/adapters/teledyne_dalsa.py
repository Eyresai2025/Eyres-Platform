"""Teledyne DALSA GenTL adapter.

This adapter uses a DALSA GenTL producer through Harvesters.  Configure
EYRES_DALSA_CTI with the installed Teledyne/DALSA .cti producer path.

This is intentionally separate from Z-Trak/Sapera 3D profiler integration.
"""
from .base import AdapterCapabilities
from .genicam_harvesters import HarvesterGenicamAdapter


class TeledyneDalsaAdapter(HarvesterGenicamAdapter):
    key = "teledyne_dalsa"
    display_name = "Teledyne DALSA"
    vendor = "Teledyne DALSA"
    cti_env = "EYRES_DALSA_CTI"
    capabilities = AdapterCapabilities(
        scan_types=("area", "line"),
        sdk_name="Teledyne DALSA GenTL / Harvesters",
        install_hint=(
            "Install the Teledyne DALSA GigE/GenTL producer and set EYRES_DALSA_CTI "
            "to its .cti path. Z-Trak 3D profilers use a separate Sapera integration."
        ),
    )
