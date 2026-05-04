FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch — avoids pulling CUDA binaries (~1GB saved vs default)
RUN pip install --no-cache-dir \
    torch torchvision \
    --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY detector.py .

CMD ["python", "detector.py"]
