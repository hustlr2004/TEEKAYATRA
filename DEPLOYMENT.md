# Live domain deployment guide

This project is a FastAPI backend + Vite React frontend. For a custom domain deployment, the simplest production setup is:

- Frontend: Vercel
- Backend: Render
- Custom domains: one for the frontend, one for the API

## 1) Backend deployment on Render

1. Push this repo to GitHub.
2. In Render, create a new Web Service.
3. Connect the repository.
4. Set the root directory to `backend`.
5. Build command:

```bash
pip install -r requirements.txt
```

6. Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 10000
```

7. Add environment variables:

```bash
DATABASE_URL=sqlite:////tmp/teeka_yatra.db
ALLOWED_ORIGINS=https://your-frontend-domain.com,https://www.your-frontend-domain.com
```

8. Save and deploy.
9. Copy the Render backend URL, for example:

```text
https://teeka-yatra-api.onrender.com
```

## 2) Frontend deployment on Vercel

1. In Vercel, import the repo.
2. Set the root directory to `frontend`.
3. Build command:

```bash
npm install && npm run build
```

4. Output directory:

```text
dist
```

5. Add environment variable:

```bash
VITE_API_BASE=https://teeka-yatra-api.onrender.com
```

6. Deploy.

## 3) Custom domain setup

- Add a custom domain to the frontend app, for example:

```text
https://app.yourdomain.com
```

- Add a custom domain to the backend API, for example:

```text
https://api.yourdomain.com
```

- Update `ALLOWED_ORIGINS` on the backend to include the frontend domain.

## 4) Production notes

- The backend has CORS enabled for localhost and configured domains.
- The frontend reads the API base from `VITE_API_BASE`.
- If you use a production DB later, replace the SQLite database with Postgres for better scale and persistence.

## 5) Demo credentials

The app seeds demo users. Use the login flow on the frontend and enter:

- OTP: `123456`
- Any demo phone number
- Consent checkbox selected

## 6) Common checks

After deployment, validate:

```bash
curl https://your-api-domain.com/health
```

and open:

```text
https://your-frontend-domain.com
```
