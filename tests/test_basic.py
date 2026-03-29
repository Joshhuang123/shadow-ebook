"""
Unit tests for Shadow Learning core components
"""
import unittest
import tempfile
import json
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestConfigSettings(unittest.TestCase):
    """Test configuration settings"""

    def test_base_dir_exists(self):
        """Test that BASE_DIR is set correctly"""
        from config import settings
        self.assertTrue(settings.BASE_DIR.exists())

    def test_audio_dir_exists(self):
        """Test that AUDIO_DIR exists or can be created"""
        from config import settings
        settings.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        self.assertTrue(settings.AUDIO_DIR.exists())

    def test_temp_dir_exists(self):
        """Test that TEMP_DIR exists or can be created"""
        from config import settings
        settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        self.assertTrue(settings.TEMP_DIR.exists())

    def test_sample_rate_is_positive(self):
        """Test that SAMPLE_RATE is a positive integer"""
        from config import settings
        self.assertIsInstance(settings.SAMPLE_RATE, int)
        self.assertGreater(settings.SAMPLE_RATE, 0)


class TestScoringAgent(unittest.TestCase):
    """Test ScoringAgent functionality"""

    def setUp(self):
        from agents.scoring_agent import ScoringAgent
        self.agent = ScoringAgent()

    def test_calculate_similarity_identical(self):
        """Test similarity of identical texts"""
        text = "Hello world"
        similarity = self.agent.calculate_similarity(text, text)
        self.assertEqual(similarity, 100.0)

    def test_calculate_similarity_different(self):
        """Test similarity of different texts"""
        similarity = self.agent.calculate_similarity("Hello world", "Goodbye moon")
        self.assertLess(similarity, 50.0)

    def test_calculate_similarity_similar(self):
        """Test similarity of similar texts"""
        similarity = self.agent.calculate_similarity(
            "I like to learn English",
            "I like learning English"
        )
        self.assertGreater(similarity, 50.0)

    def test_word_accuracy(self):
        """Test word accuracy calculation"""
        result = self.agent._calculate_word_accuracy(
            ["hello", "world"],
            ["hello", "world"]
        )
        self.assertEqual(result["accuracy"], 100.0)

    def test_word_accuracy_partial(self):
        """Test partial word accuracy"""
        result = self.agent._calculate_word_accuracy(
            ["hello", "beautiful", "world"],
            ["hello", "world"]
        )
        self.assertLess(result["accuracy"], 100.0)
        self.assertGreater(result["accuracy"], 0)

    def test_get_word_phonemes(self):
        """Test getting word phonemes"""
        result = self.agent.get_word_phonemes("hello")
        self.assertIn("word", result)
        self.assertEqual(result["word"], "hello")


class TestVocabularyAgent(unittest.TestCase):
    """Test VocabularyAgent functionality"""

    def setUp(self):
        from agents.vocabulary_agent import VocabularyAgent
        self.agent = VocabularyAgent()

    def test_identify_unknown_words(self):
        """Test identifying unknown words"""
        unknown = self.agent.identify_unknown_words(
            "This is a test sentence with some unusual words like xylophone."
        )
        self.assertIsInstance(unknown, dict)

    def test_get_statistics(self):
        """Test getting vocabulary statistics"""
        stats = self.agent.get_statistics()
        self.assertIn("total_unknown_words", stats)
        self.assertIn("total_known_words", stats)
        self.assertIn("average_mastery", stats)
        self.assertIn("mastery_distribution", stats)

    def test_get_word_details(self):
        """Test getting word details"""
        details = self.agent.get_word_details("hello")
        self.assertIsInstance(details, dict)


class TestGrammarAgent(unittest.TestCase):
    """Test GrammarAgent functionality"""

    def setUp(self):
        from agents.grammar_agent import GrammarAgent
        self.agent = GrammarAgent()

    def test_analyze_sentence(self):
        """Test sentence analysis"""
        result = self.agent.analyze_sentence("I am learning English.")
        self.assertIn("grammar_points", result)
        self.assertIsInstance(result["grammar_points"], list)

    def test_analyze_empty_sentence(self):
        """Test analyzing empty sentence"""
        result = self.agent.analyze_sentence("")
        self.assertIn("grammar_points", result)


class TestReviewAgent(unittest.TestCase):
    """Test ReviewAgent functionality (SM-2 algorithm)"""

    def setUp(self):
        from agents.review_agent import ReviewAgent
        self.agent = ReviewAgent()

    def test_add_to_review(self):
        """Test adding word to review queue"""
        self.agent.add_to_review("testword")
        items = self.agent.get_new_words()
        words = [w["word"] for w in items]
        self.assertIn("testword", words)

    def test_review_word_sm2(self):
        """Test SM-2 algorithm interval calculation"""
        self.agent.add_to_review("anothertest")

        # Quality 5 (perfect) should increase interval
        result = self.agent.review_word("anothertest", 5)
        self.assertEqual(result["quality"], 5)
        self.assertIn("new_interval", result)
        self.assertGreater(result["new_interval"], 0)

    def test_get_statistics(self):
        """Test getting review statistics"""
        stats = self.agent.get_statistics()
        self.assertIn("total_words", stats)
        self.assertIn("due_today", stats)


class TestTempFileManager(unittest.TestCase):
    """Test temporary file management"""

    def test_temp_file_creation(self):
        """Test creating and tracking temp files"""
        from services.shadow_learning_service import TempFileManager
        manager = TempFileManager()

        temp_file = manager.create_temp_file("test_", ".wav")
        self.assertTrue(str(temp_file).startswith(str(manager.temp_dir)))

    def test_cleanup_old_files(self):
        """Test cleanup doesn't crash"""
        from services.shadow_learning_service import TempFileManager
        manager = TempFileManager()

        # Should not raise any errors
        manager.cleanup_old_files(max_age_hours=0)


class TestRecordingManager(unittest.TestCase):
    """Test recording manager functionality"""

    def test_initial_state(self):
        """Test initial recording state"""
        from services.shadow_learning_service import RecordingManager
        manager = RecordingManager()

        self.assertFalse(manager.is_recording)
        self.assertIsNone(manager.get_result())


if __name__ == "__main__":
    unittest.main(verbosity=2)
