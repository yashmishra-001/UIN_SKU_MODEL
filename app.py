"""
SKU & Model Standardization — Streamlit web app
Replicates the Code.gs feature set: search, dashboard, quality checks,
plus TF-IDF SKU + model name matching with confidence scoring.
"""
import streamlit as st
import pandas as pd
import re, io
from engines import SKUMatcher, ModelNameMatcher, mine_overrides, DEFAULT_CONFIG

st.set_page_config(page_title="SKU Standardizer", page_icon="🔖", layout="wide")

# ---------------- styling ----------------
st.markdown("""
<style>
.stApp { background:#f8f9fa; }
.metric-card { background:#fff; border:1px solid #e0e0e0; border-radius:10px;
               padding:14px; text-align:center; }
.big { font-size:30px; font-weight:700; color:#1a73e8; }
.big.g{color:#34a853;} .big.r{color:#ea4335;} .big.a{color:#f9ab00;}
.lbl { font-size:11px; color:#666; text-transform:uppercase; letter-spacing:.05em;}
</style>
""", unsafe_allow_html=True)

STATUS_COLOR = {
    "exact":"#34a853","override":"#1a73e8","auto_accept":"#34a853",
    "review":"#f9ab00","no_confident_match":"#ea4335","empty":"#999","empty_after_clean":"#999",
}

def color_status(val):
    return f"background-color:{STATUS_COLOR.get(val,'#fff')}22;color:{STATUS_COLOR.get(val,'#333')};font-weight:600"

# ---------------- data loading ----------------
@st.cache_data
def read_table(file_bytes, name):
    if name.lower().endswith(".csv"):
        return pd.read_csv(io.BytesIO(file_bytes))
    return pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)  # all sheets

def col_list(df, col):
    return [str(v).strip() for v in df[col].dropna().tolist() if str(v).strip()]

# ---------------- sidebar: reference data ----------------
st.sidebar.title("🔖 SKU Standardizer")
st.sidebar.caption("Load your reference data once, then match / search.")

if "master_skus" not in st.session_state:
    st.session_state.master_skus = []
    st.session_state.canon_models = []
    st.session_state.uin_lookup = {}     # clean_sku -> {uin, category, type, color}
    st.session_state.overrides = {}

ref_file = st.sidebar.file_uploader("Reference workbook (xlsx/csv)", type=["xlsx","csv"],
    help="Should contain your master SKUs, canonical model names, and (optionally) UIN lookup + mapping history.")

with st.sidebar.expander("Column / sheet mapping", expanded=False):
    master_sheet = st.text_input("Master SKU sheet", "Master_SKU")
    master_col   = st.text_input("Master SKU column (or A)", "A")
    model_sheet  = st.text_input("Model list sheet", "Sheet1")
    model_col    = st.text_input("Model column (or A)", "A")
    uin_sheet    = st.text_input("UIN lookup sheet (optional)", "LINKAGE_RESULT")

def pick_col(df, spec):
    spec = spec.strip()
    if len(spec) == 1 and spec.isalpha():       # column letter
        idx = ord(spec.upper()) - ord("A")
        return df.iloc[:, idx]
    return df[spec]

if ref_file and st.sidebar.button("Load reference data", type="primary"):
    try:
        data = read_table(ref_file.getvalue(), ref_file.name)
        sheets = data if isinstance(data, dict) else {"_csv": data}

        # master skus
        if master_sheet in sheets:
            st.session_state.master_skus = [str(v).strip() for v in pick_col(sheets[master_sheet], master_col).dropna() if str(v).strip()]
        # canonical models
        if model_sheet in sheets:
            st.session_state.canon_models = list({str(v).strip() for v in pick_col(sheets[model_sheet], model_col).dropna() if str(v).strip()})
        # UIN lookup (optional)
        if uin_sheet in sheets:
            udf = sheets[uin_sheet]
            lut = {}
            for _, row in udf.iterrows():
                sku = str(row.get("SKU","")).strip()
                if sku:
                    lut[sku] = {
                        "uin": str(row.get("UIN","")).strip(),
                        "category": str(row.get("Category","")).strip(),
                        "type": str(row.get("Type","")).strip(),
                        "color": str(row.get("Color","")).strip(),
                    }
            st.session_state.uin_lookup = lut
        # mapping history -> overrides
        if "Mapping_Table" in sheets and st.session_state.master_skus:
            mdf = sheets["Mapping_Table"]
            pairs = [(str(r.iloc[0]).strip(), str(r.iloc[1]).strip())
                     for _, r in mdf.iterrows() if str(r.iloc[0]).strip() and str(r.iloc[1]).strip()]
            base = SKUMatcher(st.session_state.master_skus)
            st.session_state.overrides = mine_overrides(base, pairs)
        st.sidebar.success(f"Loaded {len(st.session_state.master_skus)} SKUs, "
                           f"{len(st.session_state.canon_models)} models, "
                           f"{len(st.session_state.uin_lookup)} UINs, "
                           f"{len(st.session_state.overrides)} overrides.")
    except Exception as e:
        st.sidebar.error(f"Load failed: {e}")

master = st.session_state.master_skus
models = st.session_state.canon_models
uin_lut = st.session_state.uin_lookup
overrides = st.session_state.overrides

if not master and not models:
    st.info("👈 Upload your reference workbook in the sidebar to begin. "
            "It should contain a master SKU list and/or a canonical model name list.")
    st.stop()

# build matchers (cached on the lists)
@st.cache_resource
def build_sku_matcher(master_tuple, overrides_tuple):
    return SKUMatcher(list(master_tuple), overrides=dict(overrides_tuple))

@st.cache_resource
def build_model_matcher(models_tuple):
    return ModelNameMatcher(list(models_tuple))

sku_matcher = build_sku_matcher(tuple(master), tuple(sorted(overrides.items()))) if master else None
model_matcher = build_model_matcher(tuple(models)) if models else None

# ---------------- tabs ----------------
tab_match, tab_search, tab_dash, tab_review = st.tabs(
    ["🔧 Standardize", "🔍 Search", "📊 Dashboard", "🟡 Review Queue"])

# ============ TAB 1: STANDARDIZE ============
with tab_match:
    st.subheader("Standardize SKUs and / or Model Names")
    c1, c2 = st.columns(2)
    with c1:
        sku_text = st.text_area("Paste SKUs (one per line)", height=160,
            placeholder="wrb-sw-noise-twistgo-blk_blk-JIO\ncmb-pulse4max-std-blu_22m")
    with c2:
        model_text = st.text_area("Paste Model Names (one per line)", height=160,
            placeholder="Twist_go elite\nNoise ColorFit Pulse 2 Max")

    if st.button("Standardize", type="primary"):
        # SKUs
        if sku_text.strip() and sku_matcher:
            skus = [l.strip() for l in sku_text.splitlines() if l.strip()]
            rows = []
            for r in sku_matcher.match_batch(skus):
                uin_info = uin_lut.get(r["clean_sku"], {})
                rows.append({
                    "Input SKU": r["input"],
                    "Global SKU": r["clean_sku"],
                    "Global UIN": uin_info.get("uin",""),
                    "Confidence": r["confidence"],
                    "Status": r["status"],
                    "Alt 1": r["candidates"][1][0] if len(r["candidates"])>1 else "",
                    "Alt 2": r["candidates"][2][0] if len(r["candidates"])>2 else "",
                })
            sdf = pd.DataFrame(rows)
            st.markdown("##### SKU results")
            st.dataframe(sdf.style.map(color_status, subset=["Status"]), use_container_width=True)
            st.download_button("⬇ Download SKU results", sdf.to_csv(index=False),
                               "sku_results.csv", "text/csv")
        # Models
        if model_text.strip() and model_matcher:
            ms = [l.strip() for l in model_text.splitlines() if l.strip()]
            rows = []
            for r in model_matcher.match_batch(ms):
                rows.append({
                    "Input Model": r["input"],
                    "Global Model": r["canonical"],
                    "Confidence": r["confidence"],
                    "Status": r["status"],
                    "Alt 1": r["candidates"][1][0] if len(r["candidates"])>1 else "",
                    "Alt 2": r["candidates"][2][0] if len(r["candidates"])>2 else "",
                })
            mdf = pd.DataFrame(rows)
            st.markdown("##### Model name results")
            st.dataframe(mdf.style.map(color_status, subset=["Status"]), use_container_width=True)
            st.download_button("⬇ Download model results", mdf.to_csv(index=False),
                               "model_results.csv", "text/csv")

# ============ TAB 2: SEARCH (replicates UIN SEARCH) ============
with tab_search:
    st.subheader("Search the catalog")
    st.caption("Fuzzy bidirectional search across UIN, SKU, Category, Model, Color.")
    cc = st.columns(5)
    q_uin = cc[0].text_input("UIN")
    q_sku = cc[1].text_input("SKU")
    q_cat = cc[2].text_input("Category")
    q_mod = cc[3].text_input("Model")
    q_col = cc[4].text_input("Color")

    def norm_s(x): return re.sub(r"[\s\-_/]+","",str(x).lower())
    def bimatch(dbv, qv):
        d, q = norm_s(dbv), norm_s(qv)
        return q in d or d in q

    if any([q_uin,q_sku,q_cat,q_mod,q_col]):
        if uin_lut:
            res = []
            for sku, info in uin_lut.items():
                if q_uin and not bimatch(info.get("uin",""), q_uin): continue
                if q_sku and not bimatch(sku, q_sku): continue
                if q_cat and not bimatch(info.get("category",""), q_cat): continue
                if q_mod and not bimatch(sku, q_mod): continue
                if q_col and not bimatch(info.get("color",""), q_col): continue
                res.append({"UIN":info.get("uin",""),"SKU":sku,
                            "Category":info.get("category",""),
                            "Type":info.get("type",""),"Color":info.get("color","")})
                if len(res)>=100: break
            st.write(f"{len(res)} result(s)")
            st.dataframe(pd.DataFrame(res), use_container_width=True)
        else:
            # fall back to searching master SKU list
            hits = [s for s in master if any(bimatch(s,q) for q in [q_sku,q_mod] if q)]
            st.write(f"{len(hits)} result(s) in master SKU list")
            st.dataframe(pd.DataFrame({"SKU":hits[:100]}), use_container_width=True)

# ============ TAB 3: DASHBOARD ============
with tab_dash:
    st.subheader("Catalog overview")
    cols = st.columns(5)
    stats = [("Master SKUs", len(master), ""),
             ("Canonical Models", len(models), ""),
             ("UIN Entries", len(uin_lut), "g"),
             ("Override Rules", len(overrides), "a"),
             ("Junk Tokens", len(DEFAULT_CONFIG["junk_tokens"]), "")]
    for col,(lbl,val,cls) in zip(cols, stats):
        col.markdown(f'<div class="metric-card"><div class="big {cls}">{val}</div>'
                     f'<div class="lbl">{lbl}</div></div>', unsafe_allow_html=True)
    if uin_lut:
        cats = {}
        for info in uin_lut.values():
            c = info.get("category","") or "—"
            cats[c] = cats.get(c,0)+1
        st.markdown("##### Products by category")
        st.bar_chart(pd.Series(cats).sort_values(ascending=False))

# ============ TAB 4: REVIEW QUEUE ============
with tab_review:
    st.subheader("Review queue")
    st.caption("After a Standardize run, low-confidence matches appear here for a human glance.")
    st.info("Run a batch in the Standardize tab; rows with status 'review' or 'no_confident_match' "
            "are the ones to verify. Use the Alt 1 / Alt 2 columns to pick the right match.")
