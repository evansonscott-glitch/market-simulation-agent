"""
Philo Ventures Market Simulator — State Persistence & Checkpointing

Provides crash recovery for long-running simulations by saving state
after each completed interview. If a simulation crashes at interview #47
of 100, it can resume from #47 instead of starting over.

State is stored as JSON files in the output directory:
  - checkpoint.json: Current simulation state and progress
  - personas_checkpoint.json: Generated personas (saved once)
  - interviews/interview_{N}.json: Each completed interview (saved incrementally)

This approach:
  - Streams results to disk (memory-friendly for large sims)
  - Enables resume-from-crash
  - Provides real-time progress visibility
"""
import json
import os
import time
from typing import Any, Dict, List, Optional, Set

from engines.logging_config import get_logger

logger = get_logger(__name__)


class SimulationCheckpoint:
    """
    Manages simulation state persistence for crash recovery.

    Usage:
        checkpoint = SimulationCheckpoint(output_dir)
        checkpoint.save_config(config)
        checkpoint.save_personas(personas)

        for i, interview in enumerate(completed_interviews):
            checkpoint.save_interview(i, interview)

        # On crash, check for existing state:
        if checkpoint.has_existing_run():
            completed = checkpoint.get_completed_interview_indices()
            # Skip already-completed interviews
    """

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.checkpoint_path = os.path.join(output_dir, "checkpoint.json")
        self.personas_path = os.path.join(output_dir, "personas_checkpoint.json")
        self.interviews_dir = os.path.join(output_dir, "interviews")

        os.makedirs(self.interviews_dir, exist_ok=True)

    def has_existing_run(self) -> bool:
        """Check if there's an existing checkpoint from a previous run."""
        return os.path.exists(self.checkpoint_path)

    def load_checkpoint(self) -> Optional[Dict[str, Any]]:
        """Load the checkpoint state from a previous run."""
        if not self.has_existing_run():
            return None
        try:
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            logger.info(
                "Loaded checkpoint: phase=%s, progress=%s",
                state.get("phase", "unknown"),
                state.get("progress", "unknown"),
            )
            return state
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Failed to load checkpoint (will start fresh): %s", e)
            return None

    def save_state(self, phase: str, progress: str, metadata: Optional[Dict] = None) -> None:
        """
        Save the current simulation state.

        Args:
            phase: Current phase name (e.g., "personas", "interviews", "analysis").
            progress: Human-readable progress string (e.g., "47/100 interviews").
            metadata: Optional additional metadata.
        """
        state = {
            "phase": phase,
            "progress": progress,
            "timestamp": time.time(),
            "timestamp_human": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if metadata:
            state["metadata"] = metadata

        try:
            self._atomic_write(self.checkpoint_path, state)
        except Exception as e:
            logger.error("Failed to save checkpoint state: %s", e)

    def save_personas(self, personas: List[Dict]) -> None:
        """Save generated personas to checkpoint."""
        try:
            self._atomic_write(self.personas_path, personas)
            logger.debug("Saved %d personas to checkpoint", len(personas))
        except Exception as e:
            logger.error("Failed to save personas checkpoint: %s", e)

    def load_personas(self) -> Optional[List[Dict]]:
        """Load personas from a previous checkpoint."""
        if not os.path.exists(self.personas_path):
            return None
        try:
            with open(self.personas_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Failed to load personas checkpoint: %s", e)
            return None

    def save_interview(self, index: int, interview: Dict) -> None:
        """
        Save a single completed interview to disk.

        This is called after each interview completes, providing
        incremental persistence. Memory can be freed after saving.

        Args:
            index: Interview index (0-based).
            interview: The interview result dict.
        """
        interview_path = os.path.join(self.interviews_dir, f"interview_{index:04d}.json")
        try:
            self._atomic_write(interview_path, interview)
        except Exception as e:
            logger.error("Failed to save interview %d: %s", index, e)

    def get_completed_interview_indices(self) -> Set[int]:
        """Get the set of interview indices that have been completed and saved."""
        completed = set()
        if not os.path.exists(self.interviews_dir):
            return completed

        for filename in os.listdir(self.interviews_dir):
            if filename.startswith("interview_") and filename.endswith(".json"):
                try:
                    index = int(filename.replace("interview_", "").replace(".json", ""))
                    # Verify the file is valid JSON
                    filepath = os.path.join(self.interviews_dir, filename)
                    with open(filepath, "r") as f:
                        json.load(f)
                    completed.add(index)
                except (ValueError, json.JSONDecodeError):
                    continue

        return completed

    def load_interview(self, index: int) -> Optional[Dict]:
        """Load a single interview from checkpoint."""
        interview_path = os.path.join(self.interviews_dir, f"interview_{index:04d}.json")
        if not os.path.exists(interview_path):
            return None
        try:
            with open(interview_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Failed to load interview %d: %s", index, e)
            return None

    def load_all_interviews(self) -> List[Dict]:
        """Load all completed interviews from checkpoint, in order."""
        completed = sorted(self.get_completed_interview_indices())
        interviews = []
        for index in completed:
            interview = self.load_interview(index)
            if interview:
                interviews.append(interview)
        return interviews

    def mark_complete(self) -> None:
        """Mark the simulation as successfully completed."""
        self.save_state(
            phase="complete",
            progress="Simulation finished successfully",
        )
        logger.info("Simulation marked as complete in checkpoint")

    def clear(self) -> None:
        """Clear all checkpoint data (for a fresh start)."""
        import shutil
        try:
            if os.path.exists(self.interviews_dir):
                shutil.rmtree(self.interviews_dir)
                os.makedirs(self.interviews_dir, exist_ok=True)
            for path in [self.checkpoint_path, self.personas_path]:
                if os.path.exists(path):
                    os.remove(path)
            logger.info("Checkpoint cleared")
        except Exception as e:
            logger.error("Failed to clear checkpoint: %s", e)

    def _atomic_write(self, path: str, data: Any) -> None:
        """
        Write JSON data atomically using a temp file + rename.
        This prevents corrupted files from partial writes during crashes.
        """
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
