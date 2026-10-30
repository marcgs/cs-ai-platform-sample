"""Offline-first episode analytics; no Azure access occurs on import."""

from episode_analysis.pipeline import analyze, prepare

__all__ = ["analyze", "prepare"]
