# 🎬 Video Clipper

AI-Powered video clip maker with peak moment detection. Download clips from YouTube, Twitter, Instagram and more!

## Features

- 🔥 **Peak Moment Detection** - AI analyzes audio to find most engaging moments
- 📥 **Multi-Platform Support** - YouTube, Twitter, Instagram, and 1000+ sites
- ✂️ **Smart Clip Creation** - Select peak moments and create clips
- 🎥 **Quality Selection** - Choose 480p, 720p, or 1080p
- 🌐 **Web-Based** - Works on any device with a browser

## Tech Stack

- **Backend:** Python 3.14 + Flask + yt-dlp 2026
- **Frontend:** Vanilla HTML/CSS/JS
- **Audio Analysis:** NumPy peak detection

## Setup

### Backend (Railway/Render)

1. Fork this repo
2. Connect to Railway or Render
3. Set start command: `python video_clipper_web.py`
4. Deploy!

### Local Development

```bash
# Install Python 3.14
brew install python@3.14

# Install dependencies
pip3.14 install -r requirements.txt

# Run
python3.14 video_clipper_web.py
```

## API Endpoints

- `POST /api/video/info` - Get video metadata
- `POST /api/video/analyze` - Detect peak moments
- `POST /api/video/download` - Create clip
- `GET /api/download/<filename>` - Download clip

## License

MIT License - See [LICENSE](LICENSE)

## Supported Platforms

YouTube, Twitter, Instagram, Facebook, TikTok, Vimeo, and 1000+ video sites via yt-dlp

---

Made with ❤️ by [@Vibes_ankit](https://twitter.com/Vibes_ankit)
