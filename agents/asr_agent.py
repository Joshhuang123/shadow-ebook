"""
ASR Agent - Speech-to-Text using OpenAI Whisper (local, no API key)
"""
import torch
import whisper
from pathlib import Path
from typing import Tuple, Optional

import config.settings as settings


class ASRAgent:
    """Agent for converting speech to text using Whisper"""

    def __init__(self, model_size: str = None):
        """
        Initialize Whisper model

        Args:
            model_size: One of 'tiny', 'base', 'small', 'medium', 'large'
                       Smaller = faster, less accurate
                       Larger = slower, more accurate
        """
        if model_size is None:
            model_size = settings.WHISPER_MODEL

        print(f"Loading Whisper model ({model_size})...")

        # Check for GPU
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Using device: {device}")

        # Load model
        self.model = whisper.load_model(model_size).to(device)
        print(f"✅ Whisper {model_size} model loaded")

    def transcribe(self, audio_path: str) -> Tuple[str, dict]:
        """
        Transcribe audio file to text

        Args:
            audio_path: Path to audio file

        Returns:
            Tuple of (transcribed_text, result_dict)
        """
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        print(f"🎙️ Transcribing: {audio_file.name}")

        # Run Whisper transcription
        result = self.model.transcribe(
            str(audio_file),
            language="english",  # Focus on English for shadowing
            fp16=False  # Use fp16 on GPU, False on CPU
        )

        text = result["text"].strip()
        segments = result.get("segments", [])

        print(f"✅ Transcribed: {text[:50]}..." if len(text) > 50 else f"✅ Transcribed: {text}")

        return text, {
            "text": text,
            "segments": segments,
            "language": result.get("language", "unknown"),
            "duration": segments[-1]["end"] if segments else 0
        }

    def transcribe_with_words(self, audio_path: str) -> Tuple[str, list]:
        """
        Transcribe and get word-level timestamps

        Returns:
            Tuple of (text, list of word dicts with start/end times)
        """
        audio_file = Path(audio_path)

        # Use word-level timestamps
        result = self.model.transcribe(
            str(audio_file),
            language="english",
            word_timestamps=True,
            fp16=False
        )

        words = []
        for segment in result.get("segments", []):
            for word in segment.get("words", []):
                words.append({
                    "word": word["word"].strip(),
                    "start": word["start"],
                    "end": word["end"]
                })

        return result["text"].strip(), words

    def compare_transcriptions(self,
                                reference_text: str,
                                user_text: str) -> dict:
        """
        Compare reference (original) with user's transcription

        Returns:
            Dict with word-level comparison results
        """
        ref_words = reference_text.lower().split()
        user_words = user_text.lower().split()

        matches = []
        i, j = 0, 0

        while i < len(ref_words) and j < len(user_words):
            ref = ref_words[i]
            user = user_words[j]

            if ref == user:
                matches.append({"ref": ref, "user": user, "match": True})
                i += 1
                j += 1
            elif ref in user_words or user in ref_words:
                # Partial match - could be a substitution error
                matches.append({"ref": ref, "user": user, "match": False, "type": "substitution"})
                i += 1
                j += 1
            else:
                # Deletion or insertion
                if len(ref) < len(user):
                    matches.append({"ref": ref, "user": user, "match": False, "type": "insertion"})
                    j += 1
                else:
                    matches.append({"ref": ref, "user": "", "match": False, "type": "deletion"})
                    i += 1

        # Handle remaining words
        while i < len(ref_words):
            matches.append({"ref": ref_words[i], "user": "", "match": False, "type": "deletion"})
            i += 1

        while j < len(user_words):
            matches.append({"ref": "", "user": user_words[j], "match": False, "type": "insertion"})
            j += 1

        # Calculate accuracy
        correct = sum(1 for m in matches if m["match"])
        accuracy = (correct / len(matches)) * 100 if matches else 0

        return {
            "matches": matches,
            "accuracy": accuracy,
            "reference": reference_text,
            "user_transcription": user_text
        }

    def unload_model(self):
        """Unload model to free memory"""
        del self.model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print("✅ Whisper model unloaded")


if __name__ == "__main__":
    # Demo usage
    agent = ASRAgent(model_size="base")

    # Test with existing file
    test_audio = settings.AUDIO_DIR / "user_recording.wav"
    if test_audio.exists():
        text, details = agent.transcribe(str(test_audio))
        print(f"\nTranscription: {text}")
        print(f"Duration: {details['duration']:.2f}s")
    else:
        print("No test audio file found")

    agent.unload_model()
