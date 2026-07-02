FROM node:20-alpine

WORKDIR /app

COPY apps/workbench/package*.json ./
RUN npm install

COPY apps/workbench/ .

EXPOSE 5174

CMD ["npm", "run", "dev:vite", "--", "--host", "0.0.0.0", "--port", "5174"]
