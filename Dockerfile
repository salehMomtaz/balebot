FROM python:3.11-slim

# Install ffmpeg, curl, unzip, Node.js and npm.
# Node.js >= 20 is required for the bgutil-ytdlp-pot-provider.
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    unzip \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create space for config and media cache
RUN mkdir -p /app/cache

COPY . .

# Build the PO-token provider server so it is ready at runtime.
RUN cd /app/bgutil-provider/server && npm ci && npx tsc

# Install the yt-dlp plugin so yt-dlp discovers it automatically.
RUN mkdir -p /root/.yt-dlp/plugins && \
    ln -s /app/bgutil-provider/plugin /root/.yt-dlp/plugins/bgutil

CMD ["python", "main.py"]
