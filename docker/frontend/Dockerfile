FROM node:20-alpine

WORKDIR /app

# Install dependencies
COPY frontend/package*.json ./
RUN npm install

# Copy application code
COPY frontend/ .

# Create non-root user
RUN adduser -D appuser
RUN chown -R appuser /app
USER appuser

EXPOSE 3000

CMD ["npx", "next", "dev", "-H", "0.0.0.0", "-p", "3000"]