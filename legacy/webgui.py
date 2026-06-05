"""
Shadow Learning Web GUI Backend
Connects HTML frontend with core learning functionality
Uses non-blocking recording for better UX
"""
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import webview

from config import settings
from services import ShadowLearningService


class ShadowLearningAPI:
    """Backend API for Shadow Learning Web GUI"""

    def __init__(self):
        self.service = ShadowLearningService()
        self.window = None
        self._recording_complete = False
        self._recording_path: Optional[str] = None

    def init(self) -> dict:
        """Initialize the API - called by frontend on load"""
        return {"success": True, "message": "Shadow Learning API ready"}

    # ==================== Material Loading ====================

    def load_material(self, filename: str = None) -> dict:
        """Load an audio file and segment it"""
        # If no filename, try to find any audio file
        if not filename:
            audio_files = list(settings.AUDIO_DIR.glob("*.wav")) + \
                         list(settings.AUDIO_DIR.glob("*.mp3")) + \
                         list(settings.AUDIO_DIR.glob("*.mp4"))
            if audio_files:
                filename = audio_files[0].name
            else:
                return {"success": False, "error": "No audio files found"}

        result = self.service.load_material(filename)
        return result

    def select_file(self) -> dict:
        """Open file dialog to select audio/video file"""
        try:
            result = webview.windows[0].create_file_dialog(
                webview.FILE_DIALOG_OPEN,
                file_types=('Audio Files (*.wav;*.mp3;*.flac)|*.wav;*.mp3;*.flac|'
                           'Video Files (*.mp4;*.mkv;*.avi)|*.mp4;*.mkv;*.avi|'
                           'All files (*.*)|*.*')
            )

            if result and len(result) > 0:
                selected_path = Path(result[0])
                # Copy to audio directory
                import shutil
                dest_path = settings.AUDIO_DIR / selected_path.name
                if not dest_path.exists():
                    shutil.copy(selected_path, dest_path)
                return {"success": True, "filename": selected_path.name}

            return {"success": False, "error": "No file selected"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== Audio Playback ====================

    def play_audio(self, segment_index: int) -> dict:
        """Play audio segment by index"""
        return self.service.play_segment(segment_index, blocking=False)

    # ==================== Recording (Non-blocking) ====================

    def start_recording(self) -> dict:
        """
        Start recording in background thread.
        Returns immediately - frontend should poll get_recording_status()
        """
        def on_complete(path: str):
            self._recording_complete = True
            self._recording_path = path

        def on_error(error: str):
            self._recording_complete = True
            self._recording_path = None
            print(f"Recording error: {error}")

        self._recording_complete = False
        self._recording_path = None

        result = self.service.start_recording_async(
            on_complete=on_complete,
            on_error=on_error
        )
        return result

    def stop_recording(self) -> dict:
        """Manually stop recording"""
        return self.service.stop_recording()

    def get_recording_status(self) -> dict:
        """Get current recording status (for polling)"""
        status = self.service.get_recording_status()
        status["complete"] = self._recording_complete
        if self._recording_complete and self._recording_path:
            status["path"] = self._recording_path
        return status

    def replay_recording(self) -> dict:
        """Replay user's recording"""
        recording_path = self._recording_path or self.service.recording_manager.get_result()

        if recording_path and Path(recording_path).exists():
            try:
                audio = self.service.audio_agent.load_audio(recording_path)
                threading.Thread(
                    target=self.service.audio_agent.play_segment,
                    args=(audio, False),
                    daemon=True
                ).start()
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "No recording available"}

    # ==================== Scoring ====================

    def score_recording(self, segment_index: int) -> dict:
        """Score user's pronunciation against reference segment"""
        recording_path = self._recording_path
        return self.service.score_recording(segment_index, recording_path)

    # ==================== Review ====================

    def get_review_words(self, limit: int = 10) -> dict:
        """Get words for review session"""
        return self.service.get_review_words(limit)

    def submit_review(self, word: str, quality: int) -> dict:
        """Submit a review result"""
        return self.service.submit_review(word, quality)

    # ==================== Statistics ====================

    def get_statistics(self) -> dict:
        """Get learning statistics"""
        return self.service.get_statistics()

    # ==================== Export ====================

    def export_vocabulary(self, format: str = "json") -> dict:
        """Export vocabulary data"""
        return self.service.export_vocabulary(format)

    # ==================== Session Management ====================

    def finish_session(self) -> dict:
        """Finish current session and get summary"""
        stats = self.service.get_statistics()
        return {
            "success": True,
            "session": stats.get("session", {}),
            "vocabulary": stats.get("vocabulary", {})
        }

    def cleanup(self):
        """Clean up resources"""
        self.service.cleanup()


def main():
    """Launch the web GUI application"""
    # Create API instance
    api = ShadowLearningAPI()

    # Find the HTML file
    html_path = Path(__file__).parent / "web" / "index.html"
    if not html_path.exists():
        # Fallback to same directory
        html_path = Path(__file__).parent / "index.html"

    # Create the webview window
    window = webview.create_window(
        "🦊 Shadow Learning - 英语影子跟读",
        str(html_path),
        js_api=api,
        width=1000,
        height=750,
        resizable=True,
        min_size=(800, 600)
    )

    api.window = window

    # Start the webview
    webview.start(debug=False)

    # Cleanup on exit
    api.cleanup()


if __name__ == "__main__":
    main()
