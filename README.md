# Cene namirnica: Lidl, Metro Zemun, Maxi Online

Hosted dashboard for five staple groceries. The page is static and requests the latest `dist/data.json` when opened; `dist/data.js` contains the same data for inspection. It is designed to be shareable, with source links, retailer-hosted product photos, and explicit labels for different packs or specifications.

## Refresh

```bash
python3 -m pip install -r requirements.txt
python3 scripts/refresh.py
python3 scripts/check_data.py
```

The refresh fetches one fixed product per store and item from retailer-owned public sources. It replaces only today's rows and preserves older dates. The same SKU stays tracked over time. A failed fetch creates a `source_error` row with no price for that day. It writes both `dist/data.json` and `dist/data.js`.

## GitHub Pages

The workflow in `.github/workflows/pages.yml` publishes `dist/` when code is pushed to `main`. It also runs each day at 08:00 `Europe/Belgrade`, refreshes prices, checks the data, commits the updated files to preserve history, and deploys them to the same Pages URL. A manual run is available under Actions. Configure the repository's Pages source as **GitHub Actions** before the first deployment. The scheduled run may start later than its specified time when GitHub Actions is busy.

Optional daily Gmail reports use the same scheduled workflow after deployment. Configure `GMAIL_USER`, `GMAIL_APP_PASSWORD`, and `MAIL_TO` as repository Actions secrets, send one approved test with the `send_test_email` manual input, and only then set the repository Actions variable `EMAIL_ENABLED` to `true`. The script records the date and a salted recipient hash after SMTP accepts a message, so ordinary reruns skip the same recipient and day. No address or credential is stored in source. SMTP and the Git commit cannot form a single transaction; if delivery succeeds but the state commit fails, review Gmail's Sent folder before rerunning.

Current product photos come from each retailer's own public image host. The refresh obtains the image URL with the product data; it does not store image files or depend on another image service. If a retailer removes an image, the price record remains valid.

Sources: Lidl product JSON-LD (`offers.price`), Metro's public Zemun catalogue (`grossPrice` with VAT), Maxi Online's public product query (`price.value`). All prices are RSD. Maxi online prices may depend on delivery context; Lidl stock in a particular branch is unverified. Product selection and exceptions are in `scripts/refresh.py`.

The 16 November 2026 observations in `data/seed-2026-11-16.json` came from the first local run. They are real observations for Lidl and Metro only. Maxi starts on 17 November. No earlier dates are invented.

## Review before sharing

The page shows the shelf pack price, the product name and pack, a status, and a direct source link. A 2 kg flour pack and a 24-egg pack show a separately labeled unit equivalent. Lidl's 3.2% milk is visibly excluded from the 2.8% comparison. The complete basket total requires all five exact requested packs, so there is no Lidl basket total today.

To inspect a particular product, use the URL parameter `?item=flour`, `oil`, `sugar`, `eggs`, or `milk`. The data download button exports all recorded observations as JSON.
