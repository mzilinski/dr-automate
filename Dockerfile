# Use an official lightweight Python image.
# 3.14 is very new, stick to stable 3.12 or 3.13 for containers usually, unless 3.14 is specifically needed.
# Since the local env is 3.14, let's try to find a 3.14 image or fallback to 3.13 if not available reliably yet.
# Standard Python images usually catch up fast. Let's use 3.12 for maximum compatibility for now, as features used look standard.
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies if any (e.g. for pypdf/reportlab if they need build tools, usually wheels are fine)
# Installing uv for fast package management inside container or just pip.
# Let's use pip for simplicity in the final image to avoid extra layers, or Copy uv.
# Using pip with requirements file generated from uv is cleanest.

# Copy project files
COPY . /app

# Create necessary directories
RUN mkdir -p forms out

# Install dependencies
# We can export requirements from uv or just run pip install directly for the few packages we have.
# Since we know the packages: flask gunicorn pypdf reportlab pillow
RUN pip install --no-cache-dir flask gunicorn pypdf reportlab pillow

# Expose port
EXPOSE 5000

# Run the application
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
