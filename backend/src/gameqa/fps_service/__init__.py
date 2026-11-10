"""FPS analysis service shared by the CLI and the local web GUI."""

from gameqa.fps_service.analysis import FpsAnalysisResult, FpsEvent, analyze_video, output_folder
from gameqa.fps_service.store import save_results

__all__ = ["FpsAnalysisResult", "FpsEvent", "analyze_video", "output_folder", "save_results"]
