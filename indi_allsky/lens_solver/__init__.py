# Astrometric lens solver for the VirtualSky overlay.
#
# Module map:
#   projection.py -- VirtualSky's equisolid fisheye model + GMST/alt-az
#   catalog.py    -- committed star catalog loading (cached)
#   detection.py  -- star detection + exclusion masking
#   fitting.py    -- matching, staged least-squares fit, seed searches
#   solver.py     -- IndiAllSkyLensSolver orchestration (solve entry point)
#   request.py    -- request validation + config application (Flask-free)

from .catalog import CATALOG_JSON                       # noqa: F401
from .catalog import CATALOG_MAG_LIMIT                  # noqa: F401
from .catalog import CATALOG_ROW_LEN                    # noqa: F401
from .catalog import CATALOG_VALIDATED_ROW_CEILING      # noqa: F401
from .fitting import DIAMETER_FRACTION                  # noqa: F401
from .fitting import EFFECTIVE_MIN_MATCHED_STARS        # noqa: F401
from .fitting import MAX_DETECTED_STARS                 # noqa: F401
from .fitting import MAX_MATCH_RADIUS_FRACTION          # noqa: F401
from .fitting import MIN_MATCHED_STARS                  # noqa: F401
from .fitting import MIN_STAR_ALT_DEG                   # noqa: F401
from .fitting import MIN_VIABLE_DIAMETER_PX             # noqa: F401
from .fitting import RMS_GATE_FLOOR_PX                  # noqa: F401
from .fitting import _rmsGatePx                         # noqa: F401
from .fitting import _stage2MatchRadius                 # noqa: F401
from .projection import SIN45                           # noqa: F401
from .projection import predictAltAz                    # noqa: F401
from .projection import projectToPixels                 # noqa: F401
from .request import SOLVER_REQUEST_FIELDS              # noqa: F401
from .request import applySolvedValuesToConfig          # noqa: F401
from .request import parseSolverRequestValues           # noqa: F401
from .solver import MAX_SOLVE_PIXELS                    # noqa: F401
from .solver import MIN_DETECTED_STARS                  # noqa: F401
from .solver import IndiAllSkyLensSolver                # noqa: F401
from .solver import _chooseDownscaleFactor              # noqa: F401
