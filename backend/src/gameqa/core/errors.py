"""Exception hierarchy shared by every module.

Catching ``GameQAError`` at the pipeline / API boundary lets us separate expected,
user-facing failures (bad file, bad config) from programming errors.
"""


class GameQAError(Exception):
    """Base class for all errors raised deliberately by gameqa."""


class ConfigError(GameQAError):
    """Configuration file or environment values are invalid."""


class VideoError(GameQAError):
    """A video could not be validated, probed or decoded."""


class UnsupportedFormatError(VideoError):
    """The file is not one of the accepted formats (FR-1). Message names the formats."""


class CorruptVideoError(VideoError):
    """The file claims to be a supported format but cannot be read as a video."""


class DetectorError(GameQAError):
    """A detector failed while processing a frame or finalising results."""

    def __init__(self, detector: str, message: str):
        super().__init__(f"[{detector}] {message}")
        self.detector = detector
