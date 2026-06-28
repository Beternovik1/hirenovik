# Dockerfile
# using an official and light version of python
FROM python:3.12-slim

# creating the app folder in the container
WORKDIR /app

# copying the Docker-specific requirements (scraper+DB only, no NLP/API deps)
COPY requirements-docker.txt .

# installing the requiremets libraries
RUN pip install --no-cache-dir -r requirements-docker.txt

# copying the rest of the project in the container
COPY . .

# what has to do the container when it turns on?
# run the main.py. the complete pipeline
CMD ["python", "src/main.py"]