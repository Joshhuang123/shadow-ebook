"""
Recording Agent - Captures user voice input via microphone
"""
import os
import wave
import threading
import time
import struct
from pathlib import Path
from typing import Optional, List
from collections import deque

import pyaudio
import numpy as np

import config.settings as settings


class RecordingAgent:
    """Agent for recording user voice input"""

    def __init__(self):
        self.audio = pyaudio.PyAudio()
        self.is_recording = False
        self.current_stream = None
        self.frames: List[bytes] = []
        self.record_thread = None
        self.audio_levels: deque = deque(maxlen=10)  # Track recent audio levels

    def get_input_device(self) -> int:
        """Get the default input device index"""
        try:
            info = self.audio.get_default_input_device_info()
            return info['index']
        except Exception:
            return 0  # Fallback to first device

    def record_callback(self, in_data, frame_count, time_info, status):
        """Callback for recording stream"""
        if self.is_recording:
            self.frames.append(in_data)
            # Calculate audio level for this chunk
            try:
                samples = np.frombuffer(in_data, dtype=np.int16)
                rms = np.sqrt(np.mean(samples.astype(float) ** 2))
                self.audio_levels.append(rms)
            except Exception:
                pass
        return (in_data, pyaudio.paContinue)

    def start_recording(self, timeout: int = None):
        """Start recording from microphone"""
        if timeout is None:
            timeout = settings.RECORDING_TIMEOUT

        self.is_recording = True
        self.frames = []
        self.audio_levels.clear()

        # Open recording stream
        self.current_stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=settings.CHANNELS,
            rate=settings.SAMPLE_RATE,
            input=True,
            input_device_index=self.get_input_device(),
            frames_per_buffer=1024,
            stream_callback=self.record_callback
        )

        self.current_stream.start_stream()

        # Set timeout timer
        if timeout > 0:
            self.record_thread = threading.Timer(timeout, self._auto_stop)
            self.record_thread.start()

        print(f"Recording started (timeout: {timeout}s)...")

    def _auto_stop(self):
        """Auto stop when timeout"""
        if self.is_recording:
            self.stop_recording()

    def stop_recording(self) -> str:
        """Stop recording and save to file"""
        self.is_recording = False

        if self.current_stream:
            try:
                self.current_stream.stop_stream()
                self.current_stream.close()
            except Exception:
                pass
            self.current_stream = None

        if self.record_thread:
            self.record_thread.cancel()
            self.record_thread = None

        # Check if we have any frames
        if not self.frames:
            print("No audio recorded")
            return ""

        # Save recording
        timestamp = int(time.time())
        filename = f"user_recording_{timestamp}.wav"
        filepath = settings.AUDIO_DIR / filename

        try:
            with wave.open(str(filepath), 'wb') as wf:
                wf.setnchannels(settings.CHANNELS)
                wf.setsampwidth(self.audio.get_sample_size(pyaudio.paInt16))
                wf.setframerate(settings.SAMPLE_RATE)
                wf.writeframes(b''.join(self.frames))

            print(f"Recording saved: {filepath}")
            return str(filepath)
        except Exception as e:
            print(f"Error saving recording: {e}")
            return ""

    def cancel_recording(self):
        """Cancel recording without saving"""
        self.is_recording = False

        if self.current_stream:
            try:
                self.current_stream.stop_stream()
                self.current_stream.close()
            except Exception:
                pass
            self.current_stream = None

        if self.record_thread:
            self.record_thread.cancel()
            self.record_thread = None

        self.frames = []
        print("Recording cancelled")

    def get_current_level(self) -> float:
        """Get current audio input level (RMS)"""
        if not self.audio_levels:
            return 0.0
        return float(np.mean(list(self.audio_levels)))

    def is_silent(self, threshold: float = 500) -> bool:
        """Check if current audio is below silence threshold"""
        level = self.get_current_level()
        return level < threshold

    def listen_for_speech(self,
                          silence_duration: float = 1.5,
                          timeout: float = 30.0,
                          silence_threshold: float = 500) -> str:
        """
        Record speech with automatic silence detection.

        This method:
        1. Starts recording
        2. Waits for speech to begin
        3. Records while speech is ongoing
        4. Auto-stops after silence_duration seconds of silence
        5. Returns the saved file path

        Args:
            silence_duration: Seconds of silence before stopping
            timeout: Maximum recording time in seconds
            silence_threshold: RMS threshold for silence detection

        Returns:
            Path to saved audio file, or empty string if failed
        """
        self.frames = []
        self.audio_levels.clear()
        self.is_recording = True

        # Open recording stream
        self.current_stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=settings.CHANNELS,
            rate=settings.SAMPLE_RATE,
            input=True,
            input_device_index=self.get_input_device(),
            frames_per_buffer=1024,
            stream_callback=self.record_callback
        )

        self.current_stream.start_stream()
        print(f"Listening... (max {timeout}s, silence threshold: {silence_threshold})")

        start_time = time.time()
        speech_detected = False
        silence_start = None
        check_interval = 0.1  # Check every 100ms

        try:
            while self.is_recording:
                elapsed = time.time() - start_time

                # Check timeout
                if elapsed >= timeout:
                    print(f"Timeout reached ({timeout}s)")
                    break

                # Get current audio level
                current_level = self.get_current_level()

                if current_level > silence_threshold:
                    # Speech detected
                    if not speech_detected:
                        print("Speech detected!")
                        speech_detected = True
                    silence_start = None

                elif speech_detected and current_level <= silence_threshold:
                    # Potential silence after speech
                    if silence_start is None:
                        silence_start = time.time()
                    else:
                        silence_time = time.time() - silence_start
                        if silence_time >= silence_duration:
                            print(f"Silence detected for {silence_duration}s, stopping...")
                            break

                time.sleep(check_interval)

        except KeyboardInterrupt:
            print("Recording interrupted by user")

        # Stop recording
        self.is_recording = False

        if self.current_stream:
            try:
                self.current_stream.stop_stream()
                self.current_stream.close()
            except Exception:
                pass
            self.current_stream = None

        # Check if we have any audio
        if not self.frames:
            print("No audio recorded")
            return ""

        # Check if we actually detected speech
        if not speech_detected:
            print("No speech detected")
            return ""

        # Save the recording
        timestamp = int(time.time())
        filename = f"user_recording_{timestamp}.wav"
        filepath = settings.AUDIO_DIR / filename

        try:
            with wave.open(str(filepath), 'wb') as wf:
                wf.setnchannels(settings.CHANNELS)
                wf.setsampwidth(self.audio.get_sample_size(pyaudio.paInt16))
                wf.setframerate(settings.SAMPLE_RATE)
                wf.writeframes(b''.join(self.frames))

            print(f"Recording saved: {filepath}")
            return str(filepath)
        except Exception as e:
            print(f"Error saving recording: {e}")
            return ""

    def terminate(self):
        """Clean up PyAudio resources"""
        try:
            if self.is_recording:
                self.stop_recording()
            self.audio.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    # Demo usage
    print("Recording Agent Demo")
    print("=" * 40)
    print("This will record your voice and auto-stop when you pause.")
    print("Speak something, then stay silent for 1.5 seconds.")
    print()

    agent = RecordingAgent()

    filepath = agent.listen_for_speech(
        silence_duration=1.5,
        timeout=30.0
    )

    if filepath:
        print(f"\nSuccess! Recording saved to: {filepath}")
    else:
        print("\nNo recording made.")

    agent.terminate()
