"""Quick dependency check after `pip install -r camera/requirements.txt`."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> None:
    import cv2  # noqa: F401
    import mediapipe  # noqa: F401
    import numpy  # noqa: F401
    import serial  # noqa: F401
    import rppg  # noqa: F401

    print("imports OK:")
    print("  opencv", cv2.__version__)
    print("  mediapipe", mediapipe.__version__)
    print("  numpy", numpy.__version__)
    print("  pyserial OK")
    print("  rppg Model:", rppg.Model)


if __name__ == "__main__":
    main()
