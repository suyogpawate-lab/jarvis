"""
JARVIS OSINT adapter registry.
"""

from osint.adapters.xosint import XOSINTAdapter
from osint.adapters.sigit import SIGITAdapter
from osint.adapters.threatintel import ThreatIntelAdapter
from osint.core.team import OSINTTeam


def build_osint_team():
    return OSINTTeam(
        adapters=[
            XOSINTAdapter(),
            SIGITAdapter(),
            ThreatIntelAdapter(),
        ]
    )
