#!/bin/bash
# Download English learning materials

cd "$(dirname "$0")/../audio"

echo "📥 Downloading English learning materials..."

# TED Talks (educational, widely used for English learning)
echo "\n🎤 Downloading TED Talk sample..."
yt-dlp \
    --extract-audio \
    --audio-format wav \
    --output "ted_talk_%(title)s.%(ext)s" \
    "https://www.ted.com/talks/sir_ken_robinson_do_schools_kill_creativity" \
    2>/dev/null || echo "TED download skipped"

# ESL video - Easy English (public learning channel)
echo "\n🎬 Downloading ESL Learning video..."
yt-dlp \
    --extract-audio \
    --audio-format wav \
    --output "esl_%(title)s.%(ext)s" \
    "https://www.youtube.com/watch?v=4TL1ThZvwqo" \
    2>/dev/null || echo "ESL download skipped"

# Classic animation - Disney/Pixar clips are often used
echo "\n🎬 Downloading Pixar-style short..."
yt-dlp \
    --extract-audio \
    --audio-format wav \
    --output "animation_%(title)s.%(ext)s" \
    "https://www.youtube.com/watch?v=1bOvasb2fMQ" \
    2>/dev/null || echo "Animation download skipped"

# Story narration - Classic fairy tales
echo "\n📖 Downloading English story..."
yt-dlp \
    --extract-audio \
    --audio-format wav \
    --output "story_%(title)s.%(ext)s" \
    "https://www.youtube.com/watch?v=sLxUiLHb-nw" \
    2>/dev/null || echo "Story download skipped"

echo "\n✅ Downloads complete! Check the audio/ folder."
echo "\nTip: You can also use your own files!"
echo "   Just place MP4/MOV/MP3/WAV files in the audio/ folder."
