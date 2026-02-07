# Dockerfile for gopilot LSP server
#
# Build:
#   docker build -t gopilot .
#
# Run:
#   docker run --rm -it gopilot

FROM python:3.11-slim

LABEL maintainer="gopilot"
LABEL description="AI-powered LSP server for Neovim using Ollama"

# Set working directory
WORKDIR /app

# Copy package files
COPY README.md .
COPY setup.py .
COPY requirements.txt .
COPY gopilot/ ./gopilot/

# Install the package
RUN pip install --no-cache-dir -e .

# Create non-root user for security
RUN useradd -m -s /bin/bash gopilot
USER gopilot

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default command
ENTRYPOINT ["gopilot"]
CMD ["--mode", "tcp", "--host", "0.0.0.0", "--port", "2087"]

# Expose TCP port
EXPOSE 2087
