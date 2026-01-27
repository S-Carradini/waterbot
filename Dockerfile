# Use the official lightweight Python image as a base
FROM python:3.11-slim as app

# Install necessary packages and clean up to reduce image size
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the large 'chroma' folder first to maximize caching
COPY /application/docs/chroma /app/docs/chroma

# Set permissions for the chroma directory (if necessary)
RUN chown -R root:root /app/docs/chroma && \
    chmod -R 755 /app/docs/chroma

# Copy only requirements files first to optimize layer caching
COPY /application/requirements.txt /app/
COPY /application/requirements_full.txt /app/

# Install dependencies, using no-cache to avoid cache bloating
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r requirements_full.txt

# Copy the rest of the application code last to avoid invalidating cache during code changes
COPY /application/ /app/

# Expose the application's port
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
