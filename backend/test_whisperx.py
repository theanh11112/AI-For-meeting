"""
Test script for WhisperX service
Usage: python test_whisperx.py /path/to/audio.wav
"""

import requests
import sys
import json

def test_diarize(audio_path):
    print(f"📁 Testing with audio: {audio_path}")
    
    with open(audio_path, "rb") as f:
        files = {"file": f}
        response = requests.post("http://localhost:5167/diarize", files=files)
    
    if response.status_code == 200:
        result = response.json()
        print(f"\n✅ Success! Found {len(result['segments'])} segments:\n")
        for seg in result["segments"]:
            print(f"[{seg['speaker']}] {seg['start']:.1f}s - {seg['end']:.1f}s:")
            print(f"    {seg['text']}\n")
    else:
        print(f"❌ Error: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_whisperx.py <audio_file.wav>")
        sys.exit(1)
    
    test_diarize(sys.argv[1])
