# Use Python base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory to the root of the project
WORKDIR /logging

# Install pip and upgrade it
RUN pip install --upgrade pip setuptools wheel

# Copy requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project to the working directory
COPY . .

# Expose the application port
EXPOSE 8080

# Set the entry point for the container
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
