# TradeZen Frontend Dockerfile
FROM node:20-alpine

WORKDIR /app

# Install dependencies with clean cache
COPY package.json package-lock.json ./
RUN npm ci

# Copy frontend source code
COPY . .

EXPOSE 5173

# Start Vite dev server accessible from outside the container
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
