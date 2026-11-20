# Daily update for GitHub Pages

The single workflow `.github/workflows/pages.yml` is scheduled daily at 10:52 `Europe/Belgrade`. It runs `scripts/refresh.py` and `scripts/check_data.py`, commits `dist/data.json` and `dist/data.js` to keep the date history, and deploys `dist/` to the same GitHub Pages site.

If a retailer source fails, the refresh records `source_error` with no price instead of reusing an older price. The data check prints each failed source in the Actions log. Check the latest Actions run and the public page after the first scheduled execution; a saved schedule alone does not prove that an unattended refresh has succeeded.
