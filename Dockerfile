FROM python:3.14-slim

# Install ffmpeg and curl
RUN apt-get update && apt-get install -y ffmpeg curl && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies - including yt-dlp
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt && pip list | grep yt

# Copy app code
COPY . .

# Expose port (Railway will set PORT env)
EXPOSE 8000

# Run the app
CMD ["python", "video_clipper_web.py"]
