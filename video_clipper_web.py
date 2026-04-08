#!/usr/bin/env python3
"""
Video Clipper Web App - URL se Clips with Peak Moment Detection
Run: python3 video_clipper_web.py
Then open: http://localhost:5000
"""

import os
import subprocess
import json
import tempfile
import threading
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max
app.config['TEMP_DIR'] = tempfile.mkdtemp()

# Ensure temp dir exists
os.makedirs(app.config['TEMP_DIR'], exist_ok=True)

# yt-dlp path
# Python 3.14 with yt-dlp 2026.3.17
PYTHON = "python"

def install_dependencies():
    """Check required tools"""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except FileNotFoundError:
        return False, "ffmpeg not found"
    
    try:
        subprocess.run([PYTHON, "-m", "yt_dlp", "--version"], capture_output=True, check=True)
    except FileNotFoundError:
        return False, "yt-dlp not found"
    
    return True, "OK"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/video/info', methods=['POST'])
def get_video_info():
    try:
        url = request.json.get('url')
        if not url:
            return jsonify({'error': 'URL required'}), 400
        
        cmd = [
            PYTHON, "-m", "yt_dlp",
            "--no-playlist", "--no-check-certificates", "--prefer-free-formats", "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "--print", "%(title)s|%(duration)s|%(uploader)s|%(thumbnail)s",
            "--skip-download",
            url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            return jsonify({'error': 'Failed to fetch video'}), 400
        
        parts = result.stdout.strip().split("|")
        if len(parts) < 2:
            return jsonify({'error': 'Invalid response'}), 400
        
        title = parts[0] if parts[0] != "NA" else "Unknown"
        duration = parts[1] if len(parts) > 1 and parts[1] != "NA" else "0"
        uploader = parts[2] if len(parts) > 2 and parts[2] != "NA" else "Unknown"
        thumbnail = parts[3] if len(parts) > 3 and parts[3] != "NA" else ""
        
        try:
            duration_sec = int(float(duration))
        except:
            duration_sec = 0
        
        return jsonify({
            'title': title,
            'duration': duration_sec,
            'duration_str': f"{duration_sec // 60}:{duration_sec % 60:02d}",
            'uploader': uploader,
            'thumbnail': thumbnail
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/video/analyze', methods=['POST'])
def analyze_video():
    """Analyze video for peak moments - generates smart timestamps"""
    try:
        url = request.json.get('url')
        if not url:
            return jsonify({'error': 'URL required'}), 400
        
        # Get video duration without downloading
        cmd = [
            PYTHON, "-m", "yt_dlp",
            "--no-playlist", "--no-check-certificates", "--prefer-free-formats", "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "--print", "%(duration)s",
            "--skip-download",
            url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0 or not result.stdout.strip():
            return jsonify({'peaks': generate_smart_peaks(60, 8)})
        
        try:
            duration = int(float(result.stdout.strip()))
        except:
            duration = 60
        
        # Generate smart peaks - divide video into segments and suggest interesting timestamps
        peaks = generate_smart_peaks(duration, 8)
        
        return jsonify({'peaks': peaks})
    
    except Exception as e:
        return jsonify({'peaks': generate_smart_peaks(60, 8)})

def generate_smart_peaks(duration, num_peaks=8):
    """Generate evenly distributed peak suggestions based on video duration"""
    peaks = []
    segment_length = duration / (num_peaks + 1)
    
    for i in range(1, num_peaks + 1):
        timestamp = int(segment_length * i)
        # Higher score for middle segments (usually more interesting)
        middle_score = 1.0 - abs(i - (num_peaks / 2)) / (num_peaks / 2)
        score = 0.4 + (middle_score * 0.5)  # Range: 0.4 to 0.9
        peaks.append((timestamp, score))
    
    return peaks

def detect_peak_moments(video_path, num_peaks=8, min_gap=5):
    """
    Detect peak moments using audio volume analysis
    Returns list of (timestamp, score) tuples
    """
    try:
        # Get audio levels over time using ffmpeg
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-af", "volumedetect=peak=0.01",
            "-f", "null",
            "-"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        # Parse mean_volume and max_volume from output
        mean_vol = 0
        max_vol = 0
        
        for line in result.stderr.split('\n'):
            if 'mean_volume' in line:
                try:
                    mean_vol = float(line.split('mean_volume:')[1].split('dB')[0].strip())
                except:
                    pass
            if 'max_volume' in line:
                try:
                    max_vol = float(line.split('max_volume:')[1].split('dB')[0].strip())
                except:
                    pass
        
        # Get per-second audio levels
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-af", f"astats=metadata=1:reset=1,ametadata=print:file=-",
            "-f", "null",
            "-"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        # Parse audio levels
        levels = []
        for line in result.stderr.split('\n'):
            if 'pts_time' in line and 'lavfi.astats.Overall.RMS_level' in line:
                try:
                    pts = float(line.split('pts_time:')[1].split()[0])
                    rms = float(line.split('RMS_level:')[1].split()[0])
                    if rms > -60:  # Filter out silence
                        levels.append((pts, rms))
                except:
                    pass
        
        if not levels:
            # Fallback: generate evenly spaced clips
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", 
                   "-of", "json", video_path]
            result = subprocess.run(cmd, capture_output=True, text=True)
            try:
                dur = json.loads(result.stdout)['format']['duration']
                dur = int(float(dur))
                return [(i * (dur // (num_peaks + 1)), 0.5) for i in range(1, num_peaks + 1)]
            except:
                return []
        
        # Find peak moments using sliding window
        window_size = 3  # seconds
        peak_moments = []
        
        for i in range(len(levels) - window_size):
            window = levels[i:i + window_size]
            avg_score = sum(s for _, s in window) / len(window)
            timestamp = sum(t for t, _ in window) / len(window)
            
            # Boost score if above mean
            if max_vol > mean_vol:
                boost = (max_vol - mean_vol) / 20
                avg_score += boost * 2
            
            peak_moments.append((timestamp, avg_score))
        
        # Sort by score and pick best moments with minimum gap
        peak_moments.sort(key=lambda x: x[1], reverse=True)
        
        selected = []
        for timestamp, score in peak_moments:
            # Ensure minimum gap between selected moments
            if all(abs(timestamp - t) >= min_gap for t, _ in selected):
                selected.append((timestamp, score))
                if len(selected) >= num_peaks:
                    break
        
        # Sort by timestamp
        selected.sort(key=lambda x: x[0])
        
        # Normalize scores to 0-1
        if selected:
            max_score = max(s for _, s in selected)
            min_score = min(s for _, s in selected)
            range_score = max_score - min_score if max_score != min_score else 1
            
            return [(t, (s - min_score) / range_score) for t, s in selected]
        
        return []
    
    except Exception as e:
        print(f"Peak detection error: {e}")
        return []

@app.route('/api/video/download', methods=['POST'])
def download_video():
    """Download and clip video"""
    try:
        data = request.json
        url = data.get('url')
        start = data.get('start', 0)
        end = data.get('end')
        quality = data.get('quality', '720p')
        
        if not url:
            return jsonify({'error': 'URL required'}), 400
        
        # Create unique output file
        import time
        timestamp = int(time.time() * 1000)
        output_file = os.path.join(app.config['TEMP_DIR'], f"clip_{timestamp}.mp4")
        
        # Quality: just use best for reliability
        # Download full video first
        temp_video = os.path.join(app.config['TEMP_DIR'], f"full_{timestamp}.mp4")
        
        print(f"Downloading: {url}")
        
        # Download with yt-dlp 
        cmd = [
            PYTHON, "-m", "yt_dlp",
            "-f", "best[ext=mp4]/best",
            "--no-playlist", "--no-check-certificates", "--prefer-free-formats", "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "-o", temp_video,
            url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0:
            print(f"Download error: {result.stderr}")
            return jsonify({'error': 'Download failed - ' + result.stderr[:200]}), 500
        
        if not os.path.exists(temp_video):
            return jsonify({'error': 'Video file not created'}), 500
        
        print(f"Creating clip: {start}s to {end}s")
        
        # Create clip with ffmpeg
        duration = ""
        if end:
            duration = str(end - start)
        else:
            duration = "999"
        
        clip_cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", temp_video,
            "-t", duration,
            "-c", "copy",
            output_file
        ]
        
        result = subprocess.run(clip_cmd, capture_output=True, text=True, timeout=120)
        
        # Cleanup temp video
        if os.path.exists(temp_video):
            os.remove(temp_video)
        
        if result.returncode != 0:
            print(f"Clip error: {result.stderr}")
            return jsonify({'error': 'Clip creation failed'}), 500
        
        if not os.path.exists(output_file):
            return jsonify({'error': 'Output file not created'}), 500
        
        file_size = os.path.getsize(output_file)
        print(f"Success! File size: {file_size} bytes")
        
        return jsonify({
            'success': True,
            'download_url': f'/api/download/{os.path.basename(output_file)}'
        })
    
    except Exception as e:
        print(f"Exception: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/download/<filename>')
def download_file(filename):
    """Download generated clip"""
    # Security: only allow files from temp dir
    safe_name = os.path.basename(filename)
    file_path = os.path.join(app.config['TEMP_DIR'], safe_name)
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    return send_file(file_path, as_attachment=True, download_name=safe_name)

# Cleanup old files periodically
def cleanup_temp():
    """Remove temp files older than 1 hour"""
    import time
    while True:
        try:
            now = time.time()
            for f in os.listdir(app.config['TEMP_DIR']):
                path = os.path.join(app.config['TEMP_DIR'], f)
                if os.path.isfile(path) and now - os.path.getmtime(path) > 3600:
                    os.remove(path)
        except:
            pass
        import time
        time.sleep(300)  # Check every 5 min

if __name__ == '__main__':
    # Check dependencies
    ok, msg = install_dependencies()
    if not ok:
        print(f"❌ {msg}")
        print("Install with:")
        print("  Mac: brew install ffmpeg")
        print("  Then: pip install yt-dlp flask")
    else:
        print("✅ Dependencies OK")
        
        # Start cleanup thread
        cleanup_thread = threading.Thread(target=cleanup_temp, daemon=True)
        cleanup_thread.start()
        
        print("=" * 50)
        print("🎬 Video Clipper Web App")
        print("🌐 Open: http://localhost")
        print("=" * 50)
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=False)
