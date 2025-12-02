# Troubleshooting CSS Changes Not Reflecting

If CSS changes are not showing up after hard reload, try these steps:

## 1. Clear Vite Cache
```bash
cd frontend
rm -rf node_modules/.vite
```

## 2. Restart Dev Server
```bash
# Stop the current dev server (Ctrl+C or kill the process)
npm run dev
```

## 3. Clear Browser Cache
- **Chrome/Edge**: 
  - Open DevTools (F12)
  - Right-click the refresh button
  - Select "Empty Cache and Hard Reload"
  - Or: Ctrl+Shift+Delete → Clear cached images and files

- **Firefox**:
  - Ctrl+Shift+Delete → Clear cache
  - Or: Ctrl+F5 for hard reload

## 4. Disable Cache in DevTools
- Open DevTools (F12)
- Go to Network tab
- Check "Disable cache" checkbox
- Keep DevTools open while developing

## 5. Check You're Using Dev Server
Make sure you're viewing `http://localhost:5173` (Vite dev server) and not the built version in `/dist`

## 6. Force CSS Reload
Add a temporary query parameter to force reload:
```
http://localhost:5173?v=123
```

## 7. Check for Service Workers
- Open DevTools → Application tab → Service Workers
- Unregister any service workers if present

