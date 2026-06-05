"""
Shadow Learning Service - Shared service layer for CLI and Web GUI
Provides unified API for all learning functionality
"""
import os
import json
import wave
import time
import threading
import tempfile
import atexit
from pathlib import Path
from typing import Dict, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, asdict
import weakref

from config import settings
from agents.audio_agent import AudioAgent
from agents.asr_agent import ASRAgent
from agents.scoring_agent import ScoringAgent
from agents.vocabulary_agent import VocabularyAgent
from agents.grammar_agent import GrammarAgent
from agents.review_agent import ReviewAgent


@dataclass
class PracticeResult:
    """Result of a practice session for one segment"""
    segment_index: int
    reference_text: str
    user_text: str
    overall_score: int
    similarity: float
    word_accuracy: float
    fluency_wpm: float
    level: str
    problem_words: List[Dict]
    grammar_points: List[Dict]


@dataclass
class SessionStats:
    """Statistics for a practice session"""
    total_segments: int
    practiced_segments: int
    average_score: float
    total_time_seconds: int
    words_encountered: int
    new_words: int


class TempFileManager:
    """Manages temporary files with automatic cleanup"""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if TempFileManager._initialized:
            return
        TempFileManager._initialized = True

        self.temp_files: weakref.WeakSet = weakref.WeakSet()
        self.temp_dir = settings.AUDIO_DIR / "temp"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # Register cleanup on exit
        atexit.register(self.cleanup_all)

    def create_temp_file(self, prefix: str = "temp_", suffix: str = ".wav") -> Path:
        """Create a tracked temporary file"""
        timestamp = int(time.time() * 1000)
        filename = f"{prefix}{timestamp}{suffix}"
        filepath = self.temp_dir / filename
        self.temp_files.add(filepath)
        return filepath

    def track_file(self, filepath: Path):
        """Track an existing file for cleanup"""
        self.temp_files.add(filepath)

    def cleanup_file(self, filepath: Path):
        """Remove a specific temporary file"""
        try:
            if filepath.exists():
                filepath.unlink()
        except Exception:
            pass

    def cleanup_all(self):
        """Remove all temporary files"""
        # Clean tracked files
        for filepath in list(self.temp_files):
            self.cleanup_file(filepath)

        # Clean any remaining temp files in directory
        if self.temp_dir.exists():
            for f in self.temp_dir.glob("*"):
                try:
                    f.unlink()
                except Exception:
                    pass

    def cleanup_old_files(self, max_age_hours: int = 24):
        """Remove files older than specified hours"""
        if not self.temp_dir.exists():
            return

        cutoff = time.time() - (max_age_hours * 3600)
        for f in self.temp_dir.glob("*"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception:
                pass


class RecordingManager:
    """Manages recording with non-blocking support"""

    def __init__(self):
        self._recording_thread: Optional[threading.Thread] = None
        self._recording_result: Optional[str] = None
        self._recording_error: Optional[str] = None
        self._is_recording = False
        self._recording_agent = None
        self._lock = threading.Lock()

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def start_async_recording(self,
                               on_complete: Optional[Callable[[str], None]] = None,
                               on_error: Optional[Callable[[str], None]] = None,
                               silence_duration: float = 1.5,
                               timeout: float = 30.0) -> bool:
        """
        Start recording in a background thread.

        Args:
            on_complete: Callback when recording completes successfully
            on_error: Callback when recording fails
            silence_duration: Seconds of silence before auto-stop
            timeout: Maximum recording time

        Returns:
            True if recording started successfully
        """
        with self._lock:
            if self._is_recording:
                return False

            self._recording_result = None
            self._recording_error = None
            self._is_recording = True

        def record():
            try:
                from agents.recording_agent import RecordingAgent
                self._recording_agent = RecordingAgent()

                result = self._recording_agent.listen_for_speech(
                    silence_duration=silence_duration,
                    timeout=timeout
                )

                with self._lock:
                    self._recording_result = result
                    self._is_recording = False

                if self._recording_agent:
                    try:
                        self._recording_agent.terminate()
                    except Exception:
                        pass

                if result and Path(result).exists():
                    if on_complete:
                        on_complete(result)
                else:
                    error = "No speech detected or recording failed"
                    self._recording_error = error
                    if on_error:
                        on_error(error)

            except Exception as e:
                with self._lock:
                    self._is_recording = False
                    self._recording_error = str(e)
                if on_error:
                    on_error(str(e))

        self._recording_thread = threading.Thread(target=record, daemon=True)
        self._recording_thread.start()
        return True

    def stop_recording(self) -> Optional[str]:
        """Manually stop recording and return the file path"""
        with self._lock:
            if not self._is_recording or not self._recording_agent:
                return self._recording_result

            try:
                result = self._recording_agent.stop_recording()
                self._is_recording = False
                self._recording_result = result
                return result
            except Exception:
                return self._recording_result

    def get_result(self) -> Optional[str]:
        """Get the recording result (file path)"""
        with self._lock:
            return self._recording_result

    def get_error(self) -> Optional[str]:
        """Get any recording error"""
        with self._lock:
            return self._recording_error


class ShadowLearningService:
    """
    Main service class providing unified API for shadow learning functionality.
    Used by both CLI (main.py) and Web GUI (webgui.py).
    """

    def __init__(self):
        """Initialize all agents and managers"""
        self.audio_agent = AudioAgent()
        self.asr_agent = ASRAgent()
        self.scoring_agent = ScoringAgent()
        self.vocab_agent = VocabularyAgent()
        self.grammar_agent = GrammarAgent()
        self.review_agent = ReviewAgent()

        self.temp_manager = TempFileManager()
        self.recording_manager = RecordingManager()

        # Session state
        self.current_media = None
        self.segments: List[Dict] = []
        self.session_scores: List[int] = []
        self.session_start_time: Optional[datetime] = None

        # Clean up old temp files on start
        self.temp_manager.cleanup_old_files()

    # ==================== Material Loading ====================

    def load_material(self, file_path: str, segment_duration: float = 5.0) -> Dict:
        """
        Load and segment an audio/video file.

        Args:
            file_path: Path to audio/video file
            segment_duration: Duration of each segment in seconds

        Returns:
            Dict with segments info
        """
        path = Path(file_path)
        if not path.exists():
            path = settings.AUDIO_DIR / file_path

        if not path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        try:
            # Load and segment
            audio = self.audio_agent.load_audio(str(path))
            segments = self.audio_agent.segment_by_time(audio, segment_duration=segment_duration)

            self.current_media = str(path)
            self.segments = []
            self.session_scores = []
            self.session_start_time = datetime.now()

            # Process each segment
            for i, seg in enumerate(segments):
                # Save temp segment
                temp_path = self.temp_manager.create_temp_file(f"segment_{i}_", ".wav")
                self.audio_agent.save_segment(seg, temp_path.name)

                # Transcribe
                text, details = self.asr_agent.transcribe(str(temp_path))

                # Get phonemes
                phonemes = self._get_word_phonemes(text)

                self.segments.append({
                    "index": i,
                    "text": text.strip(),
                    "phonemes": phonemes,
                    "audio_path": str(temp_path),
                    "duration": seg.duration
                })

            return {
                "success": True,
                "segments": self.segments,
                "total": len(self.segments),
                "media_path": self.current_media
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    def _get_word_phonemes(self, text: str) -> List[str]:
        """Get phoneme tips for words in text"""
        phonemes = []
        words = text.lower().split()

        for word in words:
            clean_word = ''.join(c for c in word if c.isalpha())
            if not clean_word:
                continue

            info = self.scoring_agent.get_word_phonemes(clean_word)
            if info.get("tips"):
                phonemes.extend(info["tips"][:2])

        return list(set(phonemes))[:10]

    # ==================== Audio Playback ====================

    def play_segment(self, segment_index: int, blocking: bool = False) -> Dict:
        """Play an audio segment"""
        if not 0 <= segment_index < len(self.segments):
            return {"success": False, "error": "Invalid segment index"}

        seg = self.segments[segment_index]
        audio_path = Path(seg["audio_path"])

        if not audio_path.exists():
            return {"success": False, "error": "Audio file not found"}

        try:
            audio = self.audio_agent.load_audio(str(audio_path))
            self.audio_agent.play_segment(audio, blocking=blocking)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== Recording ====================

    def start_recording_async(self,
                               on_complete: Callable[[str], None] = None,
                               on_error: Callable[[str], None] = None) -> Dict:
        """
        Start recording in background (non-blocking).

        Returns immediately with status. Use callbacks for completion.
        """
        if self.recording_manager.is_recording:
            return {"success": False, "error": "Already recording"}

        started = self.recording_manager.start_async_recording(
            on_complete=on_complete,
            on_error=on_error
        )

        return {"success": started, "message": "Recording started"}

    def stop_recording(self) -> Dict:
        """Stop current recording"""
        result = self.recording_manager.stop_recording()
        if result and Path(result).exists():
            return {"success": True, "path": result}
        return {"success": False, "error": "No recording available"}

    def get_recording_status(self) -> Dict:
        """Get current recording status"""
        return {
            "is_recording": self.recording_manager.is_recording,
            "result": self.recording_manager.get_result(),
            "error": self.recording_manager.get_error()
        }

    # ==================== Scoring ====================

    def score_recording(self, segment_index: int, recording_path: str = None) -> Dict:
        """
        Score user's pronunciation against a reference segment.

        Args:
            segment_index: Index of the reference segment
            recording_path: Path to user's recording (optional, uses last recording)

        Returns:
            Dict with scoring results
        """
        recording_path = recording_path or self.recording_manager.get_result()

        if not recording_path:
            return {"success": False, "error": "No recording available"}

        if not Path(recording_path).exists():
            return {"success": False, "error": "Recording file not found"}

        if not 0 <= segment_index < len(self.segments):
            return {"success": False, "error": "Invalid segment index"}

        try:
            reference = self.segments[segment_index]["text"]

            # Transcribe user's recording
            user_text, user_details = self.asr_agent.transcribe(recording_path)

            if not user_text.strip():
                return {"success": False, "error": "Could not transcribe recording"}

            # Calculate scores
            similarity = self.scoring_agent.calculate_similarity(reference, user_text)

            word_accuracy = self.scoring_agent._calculate_word_accuracy(
                reference.lower().split(),
                user_text.lower().split()
            )

            # Calculate fluency
            user_audio = self.audio_agent.load_audio(recording_path)
            user_words = user_audio.get_word_timestamps(
                user_text, user_details.get("segments", [])
            )
            fluency = self.scoring_agent.calculate_fluency(user_words)

            # Overall score
            overall = round(
                similarity * 0.5 +
                word_accuracy["accuracy"] * 0.3 +
                fluency["fluency_score"] * 0.2
            )

            # Feedback level (适合小学生的鼓励性反馈)
            if overall >= 90:
                level = "太棒了！发音非常标准！"
            elif overall >= 75:
                level = "很好！继续加油！"
            elif overall >= 60:
                level = "不错！再练习一下会更好！"
            elif overall >= 40:
                level = "继续努力！多听几遍原声！"
            else:
                level = "别灰心！慢慢来，多练习！"

            # Problem words
            problem_words = []
            for w_acc in word_accuracy["words"]:
                if w_acc["accuracy"] < 70:
                    suggestion = self.scoring_agent._get_pronunciation_tip(w_acc["word"])
                    problem_words.append({
                        "word": w_acc["word"],
                        "accuracy": w_acc["accuracy"],
                        "suggestion": suggestion
                    })

            # Grammar analysis
            grammar_result = self.grammar_agent.analyze_sentence(reference)
            grammar_points = [
                {"explanation": gp["explanation"]}
                for gp in grammar_result.get("grammar_points", [])
            ][:3]

            # Track vocabulary
            self.vocab_agent.identify_unknown_words(reference)

            # Save score
            self.session_scores.append(overall)

            return {
                "success": True,
                "overall": overall,
                "level": level,
                "similarity": round(similarity, 1),
                "word_accuracy": round(word_accuracy["accuracy"], 1),
                "fluency": {
                    "wpm": round(fluency.get("wpm", 0), 1),
                    "feedback": fluency.get("feedback", "")
                },
                "problem_words": problem_words[:5],
                "grammar_points": grammar_points
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    # ==================== Review ====================

    def get_review_words(self, limit: int = 10) -> Dict:
        """Get words for review session"""
        due_words = self.review_agent.get_items_for_review(limit)
        new_words = self.review_agent.get_new_words(limit)

        return {
            "success": True,
            "due_words": due_words,
            "new_words": new_words,
            "total_due": len(due_words),
            "total_new": len(new_words)
        }

    def submit_review(self, word: str, quality: int) -> Dict:
        """Submit a review result for a word"""
        result = self.review_agent.review_word(word, quality)
        result["success"] = "error" not in result
        return result

    # ==================== Statistics ====================

    def get_statistics(self) -> Dict:
        """Get learning statistics"""
        vocab_stats = self.vocab_agent.get_statistics()
        review_stats = self.review_agent.get_statistics()

        # Session stats
        session_stats = {}
        if self.session_start_time:
            elapsed = (datetime.now() - self.session_start_time).total_seconds()
            avg_score = (
                sum(self.session_scores) / len(self.session_scores)
                if self.session_scores else 0
            )
            session_stats = {
                "practice_time_minutes": round(elapsed / 60),
                "segments_practiced": len(self.session_scores),
                "average_score": round(avg_score)
            }

        return {
            "success": True,
            "vocabulary": vocab_stats,
            "review": review_stats,
            "session": session_stats
        }

    # ==================== Export ====================

    def export_vocabulary(self, format: str = "json") -> Dict:
        """Export vocabulary data"""
        if format not in ["json", "csv", "txt"]:
            return {"success": False, "error": "Invalid format. Use json, csv, or txt."}

        try:
            data = self.vocab_agent.export_words(format)
            output_path = settings.WORDS_DIR / f"export.{format}"
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(data)
            return {
                "success": True,
                "path": str(output_path),
                "message": f"导出成功！文件保存在: {output_path}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== Cleanup ====================

    def cleanup(self):
        """Clean up resources"""
        try:
            self.asr_agent.unload_model()
        except Exception:
            pass

        self.temp_manager.cleanup_all()

    def __del__(self):
        """Destructor for cleanup"""
        self.cleanup()
