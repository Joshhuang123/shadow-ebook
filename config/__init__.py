"""
Shadow Learning Configuration Package
"""
from .settings import (
    # Paths
    BASE_DIR,
    AUDIO_DIR,
    TEMP_DIR,
    DATA_DIR,
    WORDS_DIR,
    GRAMMAR_DIR,
    TESTS_DIR,

    # Audio settings
    AUDIO_FORMAT,
    SAMPLE_RATE,
    CHANNELS,

    # Whisper model
    WHISPER_MODEL,

    # Scoring thresholds
    MIN_SCORE_FOR_KNOWN,
    MIN_SCORE_FOR_PRACTICE,

    # Files
    KNOWN_WORDS_FILE,
    UNKNOWN_WORDS_FILE,
    GRAMMAR_NOTES_FILE,

    # Recording settings
    RECORDING_TIMEOUT,
    SILENCE_THRESHOLD,
)

__all__ = [
    'BASE_DIR',
    'AUDIO_DIR',
    'TEMP_DIR',
    'DATA_DIR',
    'WORDS_DIR',
    'GRAMMAR_DIR',
    'TESTS_DIR',
    'AUDIO_FORMAT',
    'SAMPLE_RATE',
    'CHANNELS',
    'WHISPER_MODEL',
    'MIN_SCORE_FOR_KNOWN',
    'MIN_SCORE_FOR_PRACTICE',
    'KNOWN_WORDS_FILE',
    'UNKNOWN_WORDS_FILE',
    'GRAMMAR_NOTES_FILE',
    'RECORDING_TIMEOUT',
    'SILENCE_THRESHOLD',
]
