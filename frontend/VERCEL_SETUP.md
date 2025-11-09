# Vercel Deployment Setup Guide

This guide explains how to configure your WaterBot frontend on Vercel to connect to your backend API.

## Quick Setup

### 1. Environment Variables in Vercel

1. Go to your Vercel project dashboard
2. Navigate to **Settings** → **Environment Variables**
3. Add the following environment variable:

   **Variable Name:** `VITE_API_BASE_URL`  
   **Value:** Your backend API URL (e.g., `https://waterbot-app.azurewebsites.net`)

   **Important:** Make sure to select all environments (Production, Preview, Development)

### 2. Deploy

After setting the environment variable, redeploy your application:

```bash
# If using Vercel CLI
vercel --prod

# Or push to your main branch to trigger automatic deployment
git push origin main
```

## Configuration Options

### Option 1: Direct API Calls (Recommended)

This is the current setup. The frontend makes direct API calls to your backend URL.

**Pros:**
- Simple configuration
- No proxy overhead
- Works with any backend URL

**Cons:**
- Requires CORS configuration on backend
- Backend URL must be publicly accessible

**Backend CORS Configuration:**

Make sure your FastAPI backend allows requests from your Vercel domain:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://your-vercel-app.vercel.app",
        "https://your-custom-domain.com",
        "http://localhost:5173",  # For local development
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Option 2: Vercel Rewrites (Alternative)

If you prefer to use Vercel rewrites to proxy requests, update `vercel.json`:

```json
{
  "rewrites": [
    {
      "source": "/api/:path*",
      "destination": "https://your-backend-url.azurewebsites.net/:path*"
    }
  ]
}
```

Then update `api.js` to use `/api` prefix instead of direct backend URL.

## Troubleshooting

### Issue: API calls failing with CORS errors

**Solution:** 
1. Check that `VITE_API_BASE_URL` is set correctly in Vercel
2. Verify backend CORS configuration allows your Vercel domain
3. Check browser console for specific error messages

### Issue: Environment variable not working

**Solution:**
1. Make sure variable name starts with `VITE_` (required for Vite)
2. Redeploy after adding environment variables
3. Check that the variable is set for the correct environment (Production/Preview/Development)

### Issue: WebSocket connections not working

**Solution:**
- WebSocket connections (`/transcribe`) require direct connection to backend
- Vercel rewrites don't support WebSocket upgrades
- Ensure backend WebSocket endpoint is publicly accessible
- Consider using a different approach for WebSocket connections (e.g., separate service)

## Testing Locally

To test with your backend URL locally:

1. Create a `.env.local` file in the `frontend/` directory:
```bash
VITE_API_BASE_URL=https://your-backend-url.azurewebsites.net
```

2. Restart your dev server:
```bash
npm run dev
```

## Production Checklist

- [ ] Set `VITE_API_BASE_URL` in Vercel environment variables
- [ ] Configure CORS on backend to allow Vercel domain
- [ ] Test API calls from production deployment
- [ ] Verify WebSocket connections (if using `/transcribe`)
- [ ] Check browser console for any errors
- [ ] Test all API endpoints (chat, sources, ratings, etc.)

## Additional Resources

- [Vercel Environment Variables](https://vercel.com/docs/concepts/projects/environment-variables)
- [Vite Environment Variables](https://vitejs.dev/guide/env-and-mode.html)
- [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/)

