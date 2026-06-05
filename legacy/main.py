#!/usr/bin/env python3
"""
Shadow Learning - English Shadowing Practice Application
Multi-agent system for English pronunciation learning through movie/cartoon shadowing
"""
import os
import sys
from pathlib import Path
from typing import List, Dict, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import settings
from agents.audio_agent import AudioAgent
from agents.recording_agent import RecordingAgent
from agents.asr_agent import ASRAgent
from agents.scoring_agent import ScoringAgent
from agents.vocabulary_agent import VocabularyAgent
from agents.grammar_agent import GrammarAgent
from agents.review_agent import ReviewAgent


class ShadowLearningApp:
    """
    Main application orchestrating all agents for shadow learning
    """

    def __init__(self):
        """Initialize all agents"""
        print("🎯 Initializing Shadow Learning App...")
        print("=" * 50)

        self.audio_agent = AudioAgent()
        self.recording_agent = RecordingAgent()
        self.asr_agent = ASRAgent()
        self.scoring_agent = ScoringAgent()
        self.vocab_agent = VocabularyAgent()
        self.grammar_agent = GrammarAgent()
        self.review_agent = ReviewAgent()

        print("✅ All agents initialized\n")

    def load_media(self, file_path: str) -> Dict:
        """
        Load a video or audio file for practice

        Args:
            file_path: Path to video/audio file

        Returns:
            Dict with media info and segments
        """
        print(f"📁 Loading media: {file_path}")
        audio = self.audio_agent.load_audio(file_path)

        # Get info
        info = self.audio_agent.get_audio_info(audio)
        print(f"   Duration: {info['duration_seconds']:.1f}s")
        print(f"   Sample rate: {info['sample_rate']}")

        # Segment by silence (sentences)
        segments = self.audio_agent.segment_by_silence(audio)

        print(f"   Segments found: {len(segments)}")

        return {
            "audio": audio,
            "info": info,
            "segments": segments
        }

    def practice_segment(self,
                         segment_audio,
                         reference_text: str = None) -> Dict:
        """
        Practice one segment: play audio, record user, score, analyze

        Args:
            segment_audio: AudioSegment to practice
            reference_text: Original sentence (optional, can be extracted via ASR)

        Returns:
            Dict with practice results
        """
        results = {}

        # 1. Play the segment
        print(f"\n🎵 Playing reference...")
        self.audio_agent.play_segment(segment_audio, blocking=True)

        # 2. Record user
        print("🎤 Now record your version (press Enter when ready, Ctrl+C to cancel)...")
        input()
        print("🎤 Recording... (speak now, will stop after silence or timeout)")
        user_audio_path = self.recording_agent.listen_for_speech()

        if not user_audio_path:
            return {"error": "No recording captured"}

        results["recording"] = user_audio_path

        # 3. Transcribe reference if not provided
        if not reference_text:
            # Save segment temporarily for ASR
            temp_path = self.audio_agent.audio_dir / "temp_reference.wav"
            segment_audio.export(str(temp_path))
            reference_text, _ = self.asr_agent.transcribe(str(temp_path))
            temp_path.unlink(missing_ok=True)

        results["reference"] = reference_text
        print(f"\n📝 Reference: {reference_text}")

        # 4. Transcribe user
        user_text, user_details = self.asr_agent.transcribe(user_audio_path)
        results["user_transcription"] = user_text
        print(f"🗣️ You said: {user_text}")

        # 5. Score pronunciation
        score_result = self.scoring_agent.calculate_pronunciation_score(
            reference_text,
            user_text,
            user_details.get("segments", [])
        )
        results["score"] = score_result

        print(f"\n📊 Score: {score_result['overall_score']}/100 ({score_result['level']})")
        if score_result['fluency']:
            print(f"   Fluency: {score_result['fluency']['wpm']} WPM, "
                  f"{score_result['fluency']['pause_count']} pauses")
        print(f"   Similarity: {score_result['similarity']}%")

        # 6. Extract and explain grammar
        grammar = self.grammar_agent.analyze_sentence(reference_text)
        results["grammar"] = grammar

        if grammar['grammar_points']:
            print(f"\n📚 Grammar points:")
            for gp in grammar['grammar_points']:
                print(f"   • {gp['explanation']}")

        # 7. Extract unknown words
        unknown_words = self.vocab_agent.identify_unknown_words(reference_text)
        results["new_words"] = list(unknown_words.keys())

        if unknown_words:
            print(f"\n🔤 New words encountered: {', '.join(unknown_words.keys())}")

        # 8. Add to review
        for word in unknown_words.keys():
            self.review_agent.add_to_review(word)

        return results

    def review_session(self, word_count: int = 10):
        """
        Run a review session for vocabulary

        Args:
            word_count: Number of words to review
        """
        print("\n📖 REVIEW SESSION")
        print("=" * 50)

        # Get words to review
        due_words = self.review_agent.get_items_for_review(word_count)
        new_words = self.review_agent.get_new_words(word_count)

        if not due_words and not new_words:
            print("No words due for review! Great job! 🎉")
            return

        # Review due words
        for item in due_words:
            print(f"\n🔁 Review: {item['word']}")
            if item['notes']:
                print(f"   Note: {item['notes']}")
            print(f"   Interval: {item['interval']} days, "
                  f"Reviews: {item['repetitions']}, "
                  f"Ease: {item['ease_factor']}")

            print("How well did you remember? (1-5)")
            print("  5 = Perfect, 4 = Easy, 3 = Hard, 2 = Wrong, 1 = Forgot")
            try:
                quality = int(input("Quality: "))
                quality = max(1, min(5, quality))
            except (ValueError, KeyboardInterrupt):
                quality = 3

            result = self.review_agent.review_word(item['word'], quality)
            print(f"   {result['message']}")

        # Learn new words
        for item in new_words:
            print(f"\n🆕 New word: {item['word']}")
            if item['notes']:
                print(f"   Context: {item['notes']}")

            # Get word details
            word_details = self.vocab_agent.get_word_details(item['word'])
            if word_details:
                # Get grammar explanation
                grammar = self.grammar_agent.analyze_sentence(item['word'])
                if grammar['grammar_points']:
                    print(f"   Grammar: {grammar['grammar_points'][0]['explanation']}")

            print("Enter quality when you'll review tomorrow:")
            try:
                input("   (Press Enter to add to tomorrow's review) ")
            except KeyboardInterrupt:
                pass

            self.review_agent.review_word(item['word'], 3)

    def show_statistics(self):
        """Show learning statistics"""
        print("\n📈 STATISTICS")
        print("=" * 50)

        vocab_stats = self.vocab_agent.get_statistics()
        review_stats = self.review_agent.get_statistics()

        print(f"\nVocabulary:")
        print(f"  Unknown words: {vocab_stats['total_unknown_words']}")
        print(f"  Known words: {vocab_stats['total_known_words']}")
        print(f"  Average mastery: {vocab_stats['average_mastery']}%")

        print(f"\nReview:")
        print(f"  Total in review: {review_stats['total_words']}")
        print(f"  Due today: {review_stats['due_today']}")
        print(f"  Learned: {review_stats['learned']}")

        # Mastery distribution
        dist = vocab_stats['mastery_distribution']
        print(f"\nMastery distribution:")
        print(f"  🔴 Learning (0-30%): {dist['learning']}")
        print(f"  🟡 Practicing (30-70%): {dist['practicing']}")
        print(f"  🟢 Familiar (70-90%): {dist['familiar']}")
        print(f"  ⭐ Mastered (90%+): {dist['mastered']}")

    def export_vocabulary(self, format: str = "json"):
        """Export vocabulary data"""
        data = self.vocab_agent.export_words(format)
        output_path = settings.WORDS_DIR / f"export.{format}"
        with open(output_path, 'w') as f:
            f.write(data)
        print(f"✅ Vocabulary exported to {output_path}")

    def cleanup(self):
        """Clean up resources"""
        self.asr_agent.unload_model()
        self.recording_agent.terminate()
        print("\n👋 Cleanup complete. Keep practicing!")


def main():
    """Main entry point"""
    app = ShadowLearningApp()

    print("""
╔════════════════════════════════════════════════════════════╗
║          🦊 Shadow Learning - English Practice 🦊          ║
╠════════════════════════════════════════════════════════════╣
║  Commands:                                                  ║
║    load <file>    - Load video/audio file                  ║
║    practice       - Practice current segment                ║
║    list           - List loaded segments                   ║
║    review         - Vocabulary review session             ║
║    stats          - Show statistics                        ║
║    export         - Export vocabulary                      ║
║    quit           - Exit                                   ║
╚════════════════════════════════════════════════════════════╝
    """)

    media_data = None

    try:
        while True:
            cmd = input("\n🎯 Command: ").strip().lower()

            if cmd == "quit" or cmd == "exit":
                break

            elif cmd.startswith("load "):
                file_path = cmd[5:].strip()
                media_data = app.load_media(file_path)
                print(f"\nLoaded {len(media_data['segments'])} segments")

            elif cmd == "practice":
                if not media_data or not media_data['segments']:
                    print("❌ No media loaded. Use 'load <file>' first.")
                    continue

                print(f"\nWhich segment? (1-{len(media_data['segments'])}, or 'all')")
                selection = input("> ").strip()

                if selection == "all":
                    for i, seg in enumerate(media_data['segments'], 1):
                        print(f"\n--- Segment {i}/{len(media_data['segments'])} ---")
                        results = app.practice_segment(seg)
                        if "error" in results:
                            print(f"❌ {results['error']}")
                            break
                elif selection.isdigit():
                    idx = int(selection) - 1
                    if 0 <= idx < len(media_data['segments']):
                        results = app.practice_segment(media_data['segments'][idx])
                        if "error" in results:
                            print(f"❌ {results['error']}")
                    else:
                        print("Invalid segment number")
                else:
                    print("Invalid command")

            elif cmd == "review":
                app.review_session()

            elif cmd == "stats":
                app.show_statistics()

            elif cmd == "export":
                print("Export format? (json/csv/txt)")
                fmt = input("> ").strip().lower()
                if fmt in ["json", "csv", "txt"]:
                    app.export_vocabulary(fmt)
                else:
                    print("Invalid format")

            elif cmd == "list":
                if media_data:
                    print(f"\nSegments: {len(media_data['segments'])}")
                    for i in range(min(5, len(media_data['segments']))):
                        duration = media_data['segments'][i].duration
                        print(f"  {i+1}. {duration:.1f}s")
                    if len(media_data['segments']) > 5:
                        print(f"  ... and {len(media_data['segments']) - 5} more")
                else:
                    print("No media loaded")

            elif cmd == "help":
                print("""
Commands:
  load <file>    Load video/audio file
  practice       Practice segments
  list           List segments
  review         Vocabulary review
  stats          Statistics
  export         Export vocabulary
  quit           Exit
                """)

            else:
                print("Unknown command. Type 'help' for options.")

    except KeyboardInterrupt:
        print("\n\nInterrupted...")
    finally:
        app.cleanup()


if __name__ == "__main__":
    main()
