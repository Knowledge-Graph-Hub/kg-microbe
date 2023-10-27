"""kg-microbe package."""
from importlib import metadata

from .download import download
from .transform_utils import transform

try:
    __version__ = metadata.version(__name__)
except metadata.PackageNotFoundError:
    # package is not installed
    __version__ = "0.0.0"  # pragma: no cover

__all__ = ["download", "transform"]
