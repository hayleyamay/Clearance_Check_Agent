FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Prevent Streamlit's first-run interactive prompt (asks for an email /
# usage-stats confirmation) from hanging container startup indefinitely -
# a well-known gotcha when running Streamlit in a fresh container.
RUN mkdir -p /root/.streamlit && \
    printf '[general]\nemail = ""\n' > /root/.streamlit/credentials.toml
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Cloud Run injects the PORT env var (usually 8080) - shell form so it expands
CMD streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true