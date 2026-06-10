# SKU & Model Standardizer — Web App

A standalone web app anyone can open to clean messy SKUs and model names against
your master catalog. No coding, no Colab — just paste and match.

## Features (mirrors the Code.gs system)
- **Standardize** — paste SKUs and/or model names → clean Global SKU, Global UIN,
  confidence score, and status (auto / review / no-match), with alternatives.
- **Search** — fuzzy bidirectional lookup across UIN, SKU, Category, Model, Color.
- **Dashboard** — catalog stats (master SKUs, models, UINs, override rules).
- **Review Queue** — low-confidence matches surfaced for a human glance.

## Files
- `app.py` — the Streamlit web app
- `engines.py` — the matching engines (SKUMatcher + ModelNameMatcher)
- `requirements.txt` — dependencies

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```
Opens at http://localhost:8501

## Deploy free (anyone can access via URL)
1. Push these 3 files to a GitHub repo
2. Go to https://share.streamlit.io → "New app" → pick the repo → main file `app.py`
3. Deploy → you get a public URL like `https://yourname-sku.streamlit.app`

## Reference data
On first open, upload your reference workbook in the sidebar. It should contain:
- a **Master_SKU** sheet (master SKU list)
- a **Sheet1** with canonical model names in column A
- optionally a **LINKAGE_RESULT** sheet (SKU, UIN, Category, Type, Color) for UIN output
- optionally a **Mapping_Table** sheet (Polluted, Clean) to seed colour-override rules

Use the "Column / sheet mapping" expander in the sidebar if your tabs/columns are named differently.

## Test data format
Just one SKU or model name per line in the Standardize tab — no headers, no master needed.
The test data carries only the new unseen values; the master always comes from the reference workbook.
