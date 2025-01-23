# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory
WORKDIR /app

# Copy the current directory contents into the container
COPY . /app

# Install required Python packages
RUN apt-get update && apt-get install -y \
    wget unzip && \
    pip install --no-cache-dir -r requirements.txt

# Set environment variables
ENV GRID_URL=http://selenium-hub:4444/wd/hub

# Run the Python script
CMD ["python", "main.py"]
