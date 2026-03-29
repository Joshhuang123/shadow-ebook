# 🦊 Shadow Learning - English Shadowing Practice

English shadowing practice application using multi-agent architecture. Practice pronunciation by shadowing movie/cartoon dialogues with instant feedback.

## Features

- **🎵 Audio Agent**: Load and segment video/audio files
- **🎤 Recording Agent**: Capture your voice via microphone
- **🎙️ ASR Agent**: Whisper-powered speech-to-text (local, no API key)
- **📊 Scoring Agent**: Pronunciation accuracy and fluency scoring
- **🔤 Vocabulary Agent**: Extract and track unknown words
- **📚 Grammar Agent**: Explain sentence structures and grammar points
- **📖 Review Agent**: Spaced repetition for vocabulary retention

## Requirements

- macOS (tested) / Linux / Windows
- Python 3.11+
- FFmpeg (for video/audio processing)
- PyAudio (for microphone recording)
- 4GB+ RAM (Whisper model loading)

### Recommended: Create Virtual Environment

```bash
# Run the setup script
chmod +x setup.sh
./setup.sh

# Or manually:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Installation

```bash
# Clone or navigate to project
cd shadow-learning

# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Optional: Install FFmpeg (if needed)
# macOS: brew install ffmpeg
# Ubuntu: apt install ffmpeg
# Windows: download from ffmpeg.org
```

### Phoneme Analysis (Advanced Pronunciation Scoring)

For more accurate pronunciation assessment, install the phoneme libraries:

```bash
pip install pronouncing phonemizer
```

This enables:
- **CMU Pronouncing Dictionary**: Get phonemes (ARPAbet) for any word
- **Phoneme-level tips**: Specific guidance for each sound
- **Syllable counting**: Know how many syllables in a word
- **Stress patterns**: Understand which syllables are stressed

## Usage

### Quick Start

```bash
python main.py
```

### Command Reference

| Command | Description |
|---------|-------------|
| `load <file>` | Load video/audio file (mp4, mov, mp3, wav) |
| `practice` | Practice segments one by one |
| `list` | List loaded segments |
| `review` | Vocabulary review session |
| `stats` | Show learning statistics |
| `export` | Export vocabulary (json/csv/txt) |
| `help` | Show help |
| `quit` | Exit |

### Running a Practice Session

1. Run `python main.py`
2. Type `load /path/to/your/movie.mp4` to load a video
3. Type `practice` to start shadowing
4. Press Enter when ready, then speak after hearing the reference
5. View your score and feedback
6. Repeat for each segment

### Direct API Usage

```python
from main import ShadowLearningApp

app = ShadowLearningApp()

# Load a video
media = app.load_media("my_movie.mp4")

# Practice one segment
results = app.practice_segment(media["segments"][0])

# Check results
print(results["score"]["overall_score"])
print(results["new_words"])

# Run review
app.review_session()

# Cleanup
app.cleanup()
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  ShadowLearningApp                       │
│                    (Orchestrator)                        │
└─────────────────────┬───────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  Audio Agent │ │Recording Agent│ │  ASR Agent   │
│  (Playback)  │ │ (Microphone) │ │  (Whisper)   │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                │                │
       └────────────────┼────────────────┘
                        ▼
              ┌──────────────────┐
              │ Scoring Agent    │
              │ (Accuracy/Fluency)│
              └────────┬─────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
  ┌───────────┐ ┌───────────┐ ┌───────────┐
  │ Vocab     │ │ Grammar   │ │ Review    │
  │ Agent     │ │ Agent     │ │ Agent     │
  └───────────┘ └───────────┘ └───────────┘
```

## Configuration

Edit `config/settings.py` to customize:

- `WHISPER_MODEL`: "tiny", "base", "small", "medium", "large"
- `SAMPLE_RATE`: Recording sample rate (16000 default)
- `KNOWN_WORDS_FILE`: Path to known words list
- `MIN_SCORE_FOR_KNOWN`: Score threshold for marking words as known

## Scoring Details

- **Overall Score (0-100)**: Weighted combination of similarity, word accuracy, and fluency
- **Similarity**: Text match between reference and your transcription
- **Word Accuracy**: Per-word correctness
- **Fluency**: WPM and pause count
- **Phoneme Accuracy** (with `pronouncing` library): Compare actual phonemes from CMU Pronouncing Dictionary

### Score Levels

| Score | Level |
|-------|-------|
| 90+ | 🌟 Excellent |
| 75-89 | 👍 Great |
| 60-74 | 📚 Good |
| 40-59 | 💪 Needs Practice |
| <40 | 📖 Keep Trying |

### Phoneme Analysis

When `pronouncing` library is installed, you'll see:

```
Word: creativity
Phonemes: K R IY1 EY1 T IH1 V IH1 T IY0
Stresses: 010100100
Syllables: 5

Tips:
- K: 清辅音 'k'
- R: 卷舌 'r' 音
- IY1: 重读长 'ee' 音
- EY1: 重读长 'ay' 音
- AH: 中央 'a' 音
...
```

## Troubleshooting

### PyAudio installation fails on macOS

```bash
brew install portaudio
pip install --global-option='build_ext' --global-option='-I/usr/local/include' --global-option='-L/usr/local/lib' pyaudio
```

### Whisper model not loading

Ensure you have sufficient RAM. Use smaller models (`tiny` or `base`) for limited memory.

### No microphone input

Check system permissions for terminal/app to access microphone.

## License

MIT License - Feel free to modify and distribute.

---

Built with ❤️ for English learners
