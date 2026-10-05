FROM node:22-alpine

WORKDIR /app

COPY package.json .
RUN npm install

COPY index.html .
COPY postcss.config.js .
COPY tailwind.config.js .
COPY tsconfig.json .
COPY vite.config.ts .
COPY public ./public
COPY src ./src

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
