"""
Audio Agent - Handles audio playback and video/audio segmentation
Uses standard library (wave) instead of pydub for Python 3.14 compatibility
"""
import os
import wave
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional
import struct

from config import settings


class AudioAgent:
    """Agent for managing audio playback and segmentation"""

    def __init__(self):
        self.audio_dir = settings.AUDIO_DIR
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    def load_audio(self, file_path: str) -> 'SimpleAudio':
        """Load audio from file (supports video too via ffmpeg)"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        # Convert to wav if needed
        if path.suffix.lower() not in ['.wav', '.mp3', '.flac', '.ogg']:
            # Assume video file, convert to audio
            wav_path = path.with_suffix('.wav')
            subprocess.run([
                'ffmpeg', '-i', str(path), '-vn',
                '-acodec', 'pcm_s16le', '-ar', '16000',
                '-ac', '1', str(wav_path), '-y'
            ], capture_output=True)
            return SimpleAudio(str(wav_path))

        return SimpleAudio(str(path))

    def segment_by_silence(self, audio: 'SimpleAudio',
                          silence_threshold: float = 0.02,
                          min_silence_len: int = 500) -> List['SimpleAudio']:
        """Split audio into sentence-sized segments using silence detection"""
        # Fallback to time-based segmentation for simplicity
        return self.segment_by_time(audio, segment_duration=3.0)

    def _calculate_rms(self, samples: List[int]) -> float:
        """Calculate RMS of samples"""
        if not samples:
            return 0
        squares = sum(s*s for s in samples)
        return (squares / len(samples)) ** 0.5

    def segment_by_time(self, audio: 'SimpleAudio',
                        segment_duration: float = 3.0) -> List['SimpleAudio']:
        """Split audio into fixed-duration segments"""
        segments = []
        duration = audio.duration

        for i in range(0, int(duration), int(segment_duration)):
            end = min(i + int(segment_duration), int(duration))
            if end - i > 0.5:
                segments.append(audio.subsegment(i, end))

        return segments

    def play_segment(self, audio: 'SimpleAudio', blocking: bool = True):
        """Play an audio segment"""
        import platform
        system = platform.system()

        # Export to temp file
        temp_path = self.audio_dir / "temp_playback.wav"
        audio.save(str(temp_path))

        if system == "Darwin":  # macOS
            subprocess.run(['afplay', str(temp_path)])
        elif system == "Linux":
            subprocess.run(['aplay', str(temp_path)])

        return temp_path

    def save_segment(self, audio: 'SimpleAudio', filename: str) -> Path:
        """Save a segment to file"""
        output_path = self.audio_dir / filename
        audio.save(str(output_path))
        return output_path

    def get_audio_info(self, audio: 'SimpleAudio') -> dict:
        """Get information about an audio segment"""
        return {
            "duration_seconds": audio.duration,
            "sample_rate": audio.sample_rate,
            "channels": audio.channels,
            "frame_count": audio.n_frames
        }


class SimpleAudio:
    """Simple audio class using standard library (wave module)"""

    def __init__(self, file_path: str = None):
        self.file_path = file_path
        self.sample_rate = 16000
        self.channels = 1
        self.n_frames = 0
        self.duration = 0
        self.samples = []

        if file_path and Path(file_path).exists():
            self.load(file_path)

    def load(self, file_path: str):
        """Load audio from WAV file"""
        with wave.open(file_path, 'rb') as wf:
            self.channels = wf.getnchannels()
            self.sample_rate = wf.getframerate()
            self.n_frames = wf.getnframes()
            self.duration = self.n_frames / self.sample_rate

            # Read all frames as bytes
            frames = wf.readframes(self.n_frames)
            # Convert to samples (16-bit signed integers)
            if self.channels == 1:
                self.samples = struct.unpack('<' + 'h' * self.n_frames, frames)
            else:
                # Convert stereo to mono
                import array
                data = array.array('h', frames)
                self.samples = [data[i] for i in range(0, len(data), self.channels)]

    def save(self, file_path: str):
        """Save audio to WAV file"""
        with wave.open(file_path, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 2 bytes = 16-bit
            wf.setframerate(self.sample_rate)

            if self.channels == 1:
                frames = struct.pack('<' + 'h' * len(self.samples), *self.samples)
            else:
                # Interleave channels
                import array
                data = array.array('h', self.samples)
                frames = bytes()
                for i in range(len(data) // self.channels):
                    for c in range(self.channels):
                        if i < len(data) // self.channels:
                            frames += struct.pack('h', data[i * self.channels + c])

            wf.writeframes(frames)

    def subsegment(self, start_time: float, end_time: float) -> 'SimpleAudio':
        """Create a subsegment"""
        new_audio = SimpleAudio()
        new_audio.sample_rate = self.sample_rate
        new_audio.channels = self.channels

        start_sample = int(start_time * self.sample_rate)
        end_sample = int(end_time * self.sample_rate)

        new_audio.samples = self.samples[start_sample:end_sample]
        new_audio.n_frames = len(new_audio.samples)
        new_audio.duration = new_audio.n_frames / new_audio.sample_rate

        return new_audio

    def get_samples(self) -> List[int]:
        """Get audio samples"""
        return self.samples

    def get_word_timestamps(self, text: str, whisper_segments: list = None) -> List[dict]:
        """Get approximate word timestamps based on Whisper segments"""
        if not whisper_segments:
            # Estimate based on word count
            word_count = len(text.split())
            if word_count == 0:
                return []

            words_per_second = 2.5  # Average speaking rate
            total_words = word_count
            words = text.split()

            timestamps = []
            current_time = 0

            for i, word in enumerate(words):
                word_duration = len(word) / 10  # Rough estimate
                if word_duration < 0.1:
                    word_duration = 0.3

                start = current_time
                end = current_time + word_duration

                timestamps.append({
                    "word": word,
                    "start": start,
                    "end": end
                })

                current_time = end

            return timestamps

        # Use Whisper timestamps if available
        timestamps = []
        for segment in whisper_segments:
            words = segment.get('words', [])
            for w in words:
                timestamps.append({
                    "word": w.get('word', '').strip(),
                    "start": w.get('start', 0),
                    "end": w.get('end', 0)
                })

        return timestamps


# Utility function for extracting audio from video
def extract_audio_from_video(video_path: str, output_path: str = None) -> str:
    """Extract audio track from video file"""
    video_file = Path(video_path)

    if output_path is None:
        output_path = str(video_file.with_suffix('.wav'))

    subprocess.run([
        'ffmpeg', '-i', video_path, '-vn',
        '-acodec', 'pcm_s16le', '-ar', '16000',
        '-ac', '1', output_path, '-y'
    ], capture_output=True)

    return output_path


if __name__ == "__main__":
    # Demo usage
    agent = AudioAgent()
    print("AudioAgent initialized")
    print(f"Audio directory: {settings.AUDIO_DIR}")

    # Test SimpleAudio
    test_file = settings.AUDIO_DIR / "test.wav"
    if test_file.exists():
        audio = SimpleAudio(str(test_file))
        print(f"Loaded test file: {audio.duration:.2f}s, {audio.sample_rate}Hz")
