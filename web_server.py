#!/usr/bin/env python3
"""
Shadow Learning Web Server
Flask-based web interface for English shadowing practice
"""
import os
import sys
import json
from pathlib import Path
from flask import Flask, render_template, jsonify, request, send_from_directory

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

app = Flask(__name__, template_folder='web', static_folder='web')

# Import services
from services import ShadowLearningService

# Initialize service
service = ShadowLearningService()

# ==================== Routes ====================

@app.route('/')
def index():
    """Serve main page"""
    return render_template('simple_web.html')

@app.route('/api/init')
def init():
    """Initialize the API"""
    return jsonify({"success": True, "message": "Shadow Learning API ready"})

@app.route('/api/materials')
def list_materials():
    """List available audio materials"""
    audio_dir = Path(__file__).parent / 'audio'
    materials = []
    for f in audio_dir.glob('*'):
        if f.suffix.lower() in ['.wav', '.mp3', '.mp4', '.m4a', '.flac']:
            materials.append({
                "name": f.name,
                "size": f.stat().st_size,
                "type": f.suffix[1:].lower()
            })
    return jsonify({"success": True, "materials": materials})

@app.route('/api/load', methods=['POST'])
def load_material():
    """Load audio/video file"""
    data = request.get_json()
    filename = data.get('filename')

    if not filename:
        return jsonify({"success": False, "error": "No filename provided"})

    result = service.load_material(filename)
    return jsonify(result)

@app.route('/api/segments')
def get_segments():
    """Get current segments"""
    if not service.current_media:
        return jsonify({"success": False, "error": "No material loaded"})

    segments = []
    for i, seg in enumerate(service.current_media.get('segments', [])):
        segments.append({
            "index": i,
            "text": seg.get('text', ''),
            "start": seg.get('start', 0),
            "end": seg.get('end', 0),
            "duration": seg.get('end', 0) - seg.get('start', 0)
        })

    return jsonify({"success": True, "segments": segments})

@app.route('/api/play/<int:index>')
def play_segment(index):
    """Play a segment"""
    result = service.play_segment(index, blocking=False)
    return jsonify(result)

@app.route('/api/record/start')
def start_recording():
    """Start recording"""
    result = service.start_recording_async(
        on_complete=lambda path: print(f"Recording complete: {path}"),
        on_error=lambda err: print(f"Recording error: {err}")
    )
    return jsonify(result)

@app.route('/api/record/stop')
def stop_recording():
    """Stop recording"""
    result = service.stop_recording()
    return jsonify(result)

@app.route('/api/record/status')
def recording_status():
    """Get recording status"""
    status = service.get_recording_status()
    return jsonify(status)

@app.route('/api/replay')
def replay_recording():
    """Replay user's recording"""
    # Get the last recording
    recording = service.recording_manager.get_result() if hasattr(service, 'recording_manager') else None

    if recording and Path(recording).exists():
        try:
            service.audio_agent.play_segment(
                service.audio_agent.load_audio(recording),
                blocking=False
            )
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    return jsonify({"success": False, "error": "No recording available"})

@app.route('/api/score/<int:segment_index>')
def score_recording(segment_index):
    """Score user's pronunciation"""
    recording = service.recording_manager.get_result() if hasattr(service, 'recording_manager') else None
    result = service.score_recording(segment_index, recording)
    return jsonify(result)

@app.route('/api/review')
def get_review():
    """Get words for review"""
    result = service.get_review_words(10)
    return jsonify(result)

@app.route('/api/review', methods=['POST'])
def submit_review():
    """Submit review result"""
    data = request.get_json()
    word = data.get('word')
    quality = data.get('quality', 0)

    result = service.submit_review(word, quality)
    return jsonify(result)

@app.route('/api/stats')
def get_statistics():
    """Get learning statistics"""
    result = service.get_statistics()
    return jsonify(result)

@app.route('/api/vocabulary')
def get_vocabulary():
    """Get vocabulary list"""
    result = service.get_vocabulary()
    return jsonify(result)

@app.route('/api/grammar/<sentence>')
def analyze_grammar(sentence):
    """Analyze grammar in a sentence"""
    from agents.grammar_agent import GrammarAgent
    agent = GrammarAgent()
    result = agent.analyze_sentence(sentence)
    return jsonify({"success": True, "analysis": result})

@app.route('/api/cleanup')
def cleanup():
    """Cleanup resources"""
    service.cleanup()
    return jsonify({"success": True})

# ==================== Main ====================

if __name__ == '__main__':
    print("🦊 Shadow Learning Web Server")
    print("=" * 50)
    print("🌐 Opening browser at: http://localhost:5001")
    print("Press Ctrl+C to stop")
    print()

    # Open browser
    import webbrowser
    webbrowser.open('http://localhost:5001')

    # Run server
    app.run(host='0.0.0.0', port=5001, debug=False)
