#!/usr/bin/env python3
import os, subprocess, json, tempfile, threading, re
from flask import Flask, render_template, request, jsonify, send_file

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config['TEMP_DIR'] = tempfile.mkdtemp()
os.makedirs(app.config['TEMP_DIR'], exist_ok=True)
PYTHON = "python"

INVIDIOUS = ["https://yewtu.be", "https://invidious.snopyta.org", "https://invidious.kavin.rocks"]

def get_video_id(url):
    patterns = [r'(?:v=|\/embed\/|youtu\.be\/)([a-zA-Z0-9_-]{11})', r'youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})']
    for p in patterns:
        m = re.search(p, url)
        if m: return m.group(1)
    return None

def safe_int(val, default=0):
    try: return int(val)
    except: return default

def safe_float(val, default=0.0):
    try: return float(val)
    except: return default

def get_video_info_invidious(video_id):
    for inst in INVIDIOUS:
        try:
            r = subprocess.run(["curl", "-s", "--max-time", "10", f"{inst}/api/v1/videos/{video_id}"], capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout:
                d = json.loads(r.stdout)
                dur = d.get('lengthSeconds', 0)
                return {
                    'title': d.get('title','Unknown'),
                    'duration': safe_int(dur),
                    'duration_str': d.get('formattedLength','0:00'),
                    'uploader': d.get('author','Unknown'),
                    'thumbnail': d.get('thumbnailUrl','')
                }
        except: continue
    return None

def get_video_info_ytdlp(url):
    cmd = [PYTHON, "-m", "yt_dlp", "--no-playlist", "--print", "%(title)s|%(duration)s|%(uploader)s|%(thumbnail)s", "--skip-download", "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0: return None
    parts = r.stdout.strip().split("|")
    if len(parts) < 2: return None
    title = parts[0] if parts[0] and parts[0] != "NA" else "Unknown"
    dur_str = parts[1] if len(parts) > 1 and parts[1] and parts[1] != "NA" else "0"
    uploader = parts[2] if len(parts) > 2 and parts[2] and parts[2] != "NA" else "Unknown"
    thumbnail = parts[3] if len(parts) > 3 and parts[3] and parts[3] != "NA" else ""
    return {
        'title': title,
        'duration': safe_int(safe_float(dur_str)),
        'uploader': uploader,
        'thumbnail': thumbnail
    }

def install_dependencies():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except: return False, "ffmpeg not found"
    try:
        subprocess.run([PYTHON, "-m", "yt_dlp", "--version"], capture_output=True, check=True)
    except: return False, "yt-dlp not found"
    return True, "OK"

@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/video/info', methods=['POST'])
def get_video_info():
    try:
        url = request.json.get('url')
        if not url: return jsonify({'error': 'URL required'}), 400
        vid = get_video_id(url)
        if vid:
            info = get_video_info_invidious(vid)
            if info: return jsonify(info)
        info = get_video_info_ytdlp(url)
        if info: return jsonify(info)
        return jsonify({'error': 'Failed to fetch video info'}), 400
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/api/video/analyze', methods=['POST'])
def analyze_video():
    try:
        url = request.json.get('url')
        if not url: return jsonify({'error': 'URL required'}), 400
        vid = get_video_id(url)
        duration = 60
        if vid:
            for inst in INVIDIOUS:
                try:
                    r = subprocess.run(["curl", "-s", "--max-time", "10", f"{inst}/api/v1/videos/{vid}"], capture_output=True, text=True, timeout=15)
                    if r.returncode == 0:
                        d = json.loads(r.stdout)
                        duration = safe_int(d.get('lengthSeconds', 60))
                        break
                except: continue
        return jsonify({'peaks': generate_smart_peaks(duration, 8)})
    except: return jsonify({'peaks': generate_smart_peaks(60, 8)})

def generate_smart_peaks(duration, num_peaks=8):
    peaks = []
    seg = max(duration / (num_peaks + 1), 1)
    for i in range(1, num_peaks + 1):
        ts = int(seg * i)
        mid = 1.0 - abs(i - (num_peaks / 2)) / (num_peaks / 2)
        peaks.append((ts, 0.4 + (mid * 0.5)))
    return peaks

def detect_peak_moments(video_path, num_peaks=8, min_gap=5):
    try:
        r = subprocess.run(["ffmpeg", "-i", video_path, "-af", "volumedetect=peak=0.01", "-f", "null", "-"], capture_output=True, text=True, timeout=60)
        mean_vol, max_vol = 0.0, 0.0
        for l in r.stderr.split('\n'):
            if 'mean_volume' in l:
                try: mean_vol = float(l.split('mean_volume:')[1].split('dB')[0].strip())
                except: pass
            if 'max_volume' in l:
                try: max_vol = float(l.split('max_volume:')[1].split('dB')[0].strip())
                except: pass
        r = subprocess.run(["ffmpeg", "-i", video_path, "-af", "astats=metadata=1:reset=1,ametadata=print:file=-", "-f", "null", "-"], capture_output=True, text=True, timeout=120)
        levels = []
        for l in r.stderr.split('\n'):
            if 'pts_time' in l and 'lavfi.astats.Overall.RMS_level' in l:
                try:
                    pts = float(l.split('pts_time:')[1].split()[0])
                    rms = float(l.split('RMS_level:')[1].split()[0])
                    if rms > -60: levels.append((pts, rms))
                except: pass
        if not levels:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", video_path], capture_output=True, text=True)
            try:
                dur = int(float(json.loads(r.stdout)['format']['duration']))
                return [(i*(dur//(num_peaks+1)), 0.5) for i in range(1, num_peaks+1)]
            except: return []
        window, peak_moments = 3, []
        for i in range(len(levels)-window):
            w = levels[i:i+window]
            avg = sum(s for _,s in w)/len(w)
            ts = sum(t for t,_ in w)/len(w)
            if max_vol > mean_vol: avg += ((max_vol - mean_vol) / 20) * 2
            peak_moments.append((ts, avg))
        peak_moments.sort(key=lambda x: x[1], reverse=True)
        selected = []
        for ts, sc in peak_moments:
            if all(abs(ts-t) >= min_gap for t,_ in selected):
                selected.append((ts, sc))
                if len(selected) >= num_peaks: break
        selected.sort(key=lambda x: x[0])
        if selected:
            max_s, min_s = max(s for _,s in selected), min(s for _,s in selected)
            rng = max_s - min_s if max_s != min_s else 1
            return [(t, (s-min_s)/rng) for t,s in selected]
        return []
    except Exception as e:
        print(f"Peak error: {e}")
        return []

@app.route('/api/video/download', methods=['POST'])
def download_video():
    try:
        data = request.json
        url, start, end = data.get('url'), data.get('start', 0), data.get('end')
        if not url: return jsonify({'error': 'URL required'}), 400
        import time
        ts = int(time.time() * 1000)
        out_file = os.path.join(app.config['TEMP_DIR'], f"clip_{ts}.mp4")
        temp_video = os.path.join(app.config['TEMP_DIR'], f"full_{ts}.mp4")
        print(f"Downloading: {url}")
        cmd = [PYTHON, "-m", "yt_dlp", "-f", "best[ext=mp4]/best", "--no-playlist", "-o", temp_video, "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", url]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0: return jsonify({'error': 'Download failed - ' + r.stderr[:200]}), 500
        if not os.path.exists(temp_video): return jsonify({'error': 'Video file not created'}), 500
        print(f"Creating clip: {start}s to {end}s")
        dur = str(end - start) if end else "999"
        r = subprocess.run(["ffmpeg", "-y", "-ss", str(start), "-i", temp_video, "-t", dur, "-c", "copy", out_file], capture_output=True, text=True, timeout=120)
        if os.path.exists(temp_video): os.remove(temp_video)
        if r.returncode != 0: return jsonify({'error': 'Clip creation failed'}), 500
        if not os.path.exists(out_file): return jsonify({'error': 'Output file not created'}), 500
        return jsonify({'success': True, 'download_url': f'/api/download/{os.path.basename(out_file)}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download/<filename>')
def download_file(filename):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(app.config['TEMP_DIR'], safe_name)
    if not os.path.exists(file_path): return jsonify({'error': 'File not found'}), 404
    return send_file(file_path, as_attachment=True, download_name=safe_name)

def cleanup_temp():
    import time
    while True:
        try:
            now = time.time()
            for f in os.listdir(app.config['TEMP_DIR']):
                p = os.path.join(app.config['TEMP_DIR'], f)
                if os.path.isfile(p) and now - os.path.getmtime(p) > 3600: os.remove(p)
        except: pass
        time.sleep(300)

if __name__ == '__main__':
    ok, msg = install_dependencies()
    if not ok:
        print(f"❌ {msg}")
    else:
        print("✅ Dependencies OK")
        threading.Thread(target=cleanup_temp, daemon=True).start()
        print("=" * 50)
        print("🎬 Video Clipper Web App")
        print("🌐 Open: http://localhost")
        print("=" * 50)
        port = int(os.environ.get('PORT', 8080))
        app.run(host='0.0.0.0', port=port, debug=False)
