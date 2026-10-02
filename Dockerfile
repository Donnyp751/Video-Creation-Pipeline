FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/kids-video-ai
COPY pyproject.toml README.md ./
COPY app ./app
COPY frontend ./frontend
RUN pip install --no-cache-dir .

# The workspace (projects/, assets/, config/, kidsvideo.db, .cache/) is mounted here.
WORKDIR /workspace
ENV KIDSVIDEO_HOME=/workspace
EXPOSE 8000
CMD ["kidsvideo", "serve", "--host", "0.0.0.0", "--port", "8000"]
