"""
Configuration settings for Shadow Learning Application
"""
import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent.parent
AUDIO_DIR = BASE_DIR / "audio"
TEMP_DIR = AUDIO_DIR / "temp"  # Temporary files (auto-cleaned)
DATA_DIR = BASE_DIR / "data"
WORDS_DIR = DATA_DIR / "words"
GRAMMAR_DIR = DATA_DIR / "grammar"
TESTS_DIR = BASE_DIR / "tests"

# Whisper model size (options: tiny, base, small, medium, large)
WHISPER_MODEL = "base"

# Audio settings
AUDIO_FORMAT = "wav"
SAMPLE_RATE = 16000
CHANNELS = 1

# Scoring thresholds
MIN_SCORE_FOR_KNOWN = 80  # Score above this = word is known
MIN_SCORE_FOR_PRACTICE = 60  # Score above this = needs practice

# Known words file (simple list for comparison)
KNOWN_WORDS_FILE = WORDS_DIR / "known_words.txt"

# Unknown words tracking
UNKNOWN_WORDS_FILE = WORDS_DIR / "unknown_words.json"

# Grammar notes file
GRAMMAR_NOTES_FILE = GRAMMAR_DIR / "grammar_notes.json"

# Recording settings
RECORDING_TIMEOUT = 10  # seconds
SILENCE_THRESHOLD = 500  # RMS threshold for silence detection
