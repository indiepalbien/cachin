# Deployment Guide

## Railway Deployment

This app uses both Python (Django) and Node.js (Tailwind CSS). Railway will automatically detect both and set them up correctly.

### Build Process

1. **Install Dependencies**
   - Python: `pip install -r requirements.txt`
   - Node.js: `npm install`

2. **Build CSS**
   - Tailwind CSS is compiled: `npm run build:css`
   - Output: `backend/expenses/static/expenses/output.css`

3. **Django Setup**
   - Migrations: `python manage.py migrate`
   - Static files: `python manage.py collectstatic --noinput`

4. **Start Server**
   - Gunicorn serves the Django app

### Configuration Files

- **`nixpacks.toml`**: Tells Railway to install both Python and Node.js
- **`Procfile`**: Defines the build and start commands
- **`package.json`**: Node.js dependencies (Tailwind CSS)
- **`tailwind.config.js`**: Tailwind configuration

### Environment Variables

Make sure these are set in Railway:
- `DATABASE_URL` (automatically set by Railway)
- Any other Django settings you need

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt
npm install

# Build CSS (once)
npm run build:css

# Or watch for changes (during development)
npm run watch:css

# Run Django
cd backend
python manage.py runserver
```

### Troubleshooting

**CSS not loading?**
- Ensure `npm run build:css` runs successfully
- Check that `output.css` exists in `backend/expenses/static/expenses/`
- Run `python manage.py collectstatic` to copy to production static location

**Railway build fails?**
- Check Railway logs for Node.js or Python errors
- Ensure `nixpacks.toml` is in the repository root
- Verify both `package.json` and `requirements.txt` are present
