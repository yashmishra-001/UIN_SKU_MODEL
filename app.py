"""
SKU & Model Standardization — Streamlit web app
Replicates the Code.gs feature set: search, dashboard, quality checks,
plus TF-IDF SKU + model name matching with confidence scoring.
"""
import streamlit as st
import pandas as pd
import re, io
from engines import SKUMatcher, ModelNameMatcher, mine_overrides, derive_canonical_models, DEFAULT_CONFIG

st.set_page_config(page_title="SKU Standardizer", page_icon="🔖", layout="wide")

# ---- FIX 1: theme-aware CSS — no hardcoded backgrounds or text colors ----
st.markdown("""
<style>
/* Remove background override so Streamlit dark/light mode works properly */
.status-badge {
    display:inline-block; padding:2px 10px; border-radius:10px;
    font-size:12px; font-weight:600;
}
</style>
""", unsafe_allow_html=True)

STATUS_COLOR = {
    "exact":"#34a853","override":"#1a73e8","auto_accept":"#34a853",
    "review":"#f9ab00","no_confident_match":"#ea4335",
    "empty":"#999","empty_after_clean":"#999",
}

def color_status(val):
    return (f"background-color:{STATUS_COLOR.get(val,'#ccc')}33;"
            f"color:{STATUS_COLOR.get(val,'#333')};font-weight:600")

# ---------------- session state init ----------------
if "master_skus" not in st.session_state:
    st.session_state.master_skus   = []
    st.session_state.canon_models  = []
    st.session_state.uin_lookup    = {}
    st.session_state.overrides     = {}
    st.session_state.models_derived = False
    # ---- FIX 2: store last run results for Review Queue tab ----
    st.session_state.last_sku_df   = None
    st.session_state.last_model_df = None

# ---------------- sidebar: reference data ----------------
st.sidebar.title("🔖 SKU Standardizer")
st.sidebar.caption("Load your reference data once, then match / search.")

ref_file = st.sidebar.file_uploader(
    "Reference workbook (xlsx/csv)", type=["xlsx","csv"],
    help="Should contain: Master_SKU, Mapping_Table, and optionally LINKAGE_RESULT.")

with st.sidebar.expander("Column / sheet mapping", expanded=False):
    master_sheet = st.text_input("Master SKU sheet", "Master_SKU")
    master_col   = st.text_input("Master SKU column (or A)", "A")
    model_sheet  = st.text_input("Model list sheet (optional)", "Sheet1")
    model_col    = st.text_input("Model column (or A)", "A")
    uin_sheet    = st.text_input("UIN lookup sheet (optional)", "LINKAGE_RESULT")

@st.cache_data
def read_table(file_bytes, name):
    if name.lower().endswith(".csv"):
        return {"_csv": pd.read_csv(io.BytesIO(file_bytes))}
    return pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)

def pick_col(df, spec):
    spec = spec.strip()
    if len(spec) == 1 and spec.isalpha():
        return df.iloc[:, ord(spec.upper()) - ord("A")]
    return df[spec]

if ref_file and st.sidebar.button("Load reference data", type="primary"):
    try:
        sheets = read_table(ref_file.getvalue(), ref_file.name)

        if master_sheet in sheets:
            st.session_state.master_skus = [
                str(v).strip() for v in pick_col(sheets[master_sheet], master_col).dropna()
                if str(v).strip()]

        if model_sheet in sheets:
            st.session_state.canon_models = list({
                str(v).strip() for v in pick_col(sheets[model_sheet], model_col).dropna()
                if str(v).strip()})

        if uin_sheet in sheets:
            lut = {}
            for _, row in sheets[uin_sheet].iterrows():
                sku = str(row.get("SKU","")).strip()
                if sku:
                    lut[sku] = {
                        "uin":      str(row.get("UIN","")).strip(),
                        "category": str(row.get("Category","")).strip(),
                        "type":     str(row.get("Type","")).strip(),
                        "color":    str(row.get("Color","")).strip(),
                    }
            st.session_state.uin_lookup = lut

        if "Mapping_Table" in sheets and st.session_state.master_skus:
            mdf = sheets["Mapping_Table"]
            pairs = [(str(r.iloc[0]).strip(), str(r.iloc[1]).strip())
                     for _, r in mdf.iterrows()
                     if str(r.iloc[0]).strip() and str(r.iloc[1]).strip()]
            base = SKUMatcher(st.session_state.master_skus)
            st.session_state.overrides = mine_overrides(base, pairs)

        # Auto-derive model list from SKUs when no model sheet found
        if not st.session_state.canon_models and st.session_state.master_skus:
            st.session_state.canon_models = derive_canonical_models(
                st.session_state.master_skus)
            st.session_state.models_derived = True
        else:
            st.session_state.models_derived = False

        # reset last results when reference data reloads
        st.session_state.last_sku_df   = None
        st.session_state.last_model_df = None

        derived_note = " (models derived from SKUs)" if st.session_state.models_derived else ""
        st.sidebar.success(
            f"✓ {len(st.session_state.master_skus)} SKUs, "
            f"{len(st.session_state.canon_models)} models, "
            f"{len(st.session_state.uin_lookup)} UINs, "
            f"{len(st.session_state.overrides)} overrides."
            + derived_note)
    except Exception as e:
        st.sidebar.error(f"Load failed: {e}")

master   = st.session_state.master_skus
models   = st.session_state.canon_models
uin_lut  = st.session_state.uin_lookup
overrides = st.session_state.overrides

if not master and not models:
    st.info("👈 Upload your reference workbook in the sidebar to begin.")
    st.stop()

# ---- build matchers (cached on content) ----
@st.cache_resource
def build_sku_matcher(master_tuple, overrides_tuple):
    return SKUMatcher(list(master_tuple), overrides=dict(overrides_tuple))

@st.cache_resource
def build_model_matcher(models_tuple):
    return ModelNameMatcher(list(models_tuple))

sku_matcher   = build_sku_matcher(tuple(master), tuple(sorted(overrides.items()))) if master else None
model_matcher = build_model_matcher(tuple(models)) if models else None

# ---- review count for tab badge ----
def review_count():
    n = 0
    for df in [st.session_state.last_sku_df, st.session_state.last_model_df]:
        if df is not None:
            n += df["Status"].isin(["review","no_confident_match"]).sum()
    return n

rc = review_count()
review_label = f"🟡 Review Queue ({rc})" if rc > 0 else "🟡 Review Queue"

tab_match, tab_search, tab_dash, tab_review = st.tabs(
    ["🔧 Standardize", "🔍 Search", "📊 Dashboard", review_label])

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
        ran = False

        # ---- SKUs ----
        if sku_text.strip() and sku_matcher:
            ran = True
            skus = [l.strip() for l in sku_text.splitlines() if l.strip()]
            rows = []
            for r in sku_matcher.match_batch(skus):
                uin_info = uin_lut.get(r["clean_sku"], {})
                rows.append({
                    "Input SKU":  r["input"],
                    "Global SKU": r["clean_sku"],
                    "Global UIN": uin_info.get("uin",""),
                    "Confidence": r["confidence"],
                    "Status":     r["status"],
                    "Alt 1": r["candidates"][1][0] if len(r["candidates"])>1 else "",
                    "Alt 2": r["candidates"][2][0] if len(r["candidates"])>2 else "",
                })
            sdf = pd.DataFrame(rows)
            # ---- FIX 2: save to session state for Review Queue ----
            st.session_state.last_sku_df = sdf

            total = len(sdf)
            auto  = sdf["Status"].isin(["exact","override","auto_accept"]).sum()
            rev   = sdf["Status"].isin(["review","no_confident_match"]).sum()
            m1, m2, m3 = st.columns(3)
            m1.metric("Total", total)
            m2.metric("Auto-resolved", f"{auto} ({100*auto//total}%)")
            m3.metric("Needs review", rev)

            st.markdown("##### SKU results")
            st.dataframe(sdf.style.map(color_status, subset=["Status"]),
                         use_container_width=True)
            st.download_button("⬇ Download SKU results", sdf.to_csv(index=False),
                               "sku_results.csv", "text/csv")

        # ---- Model names ----
        if model_text.strip() and model_matcher:
            ran = True
            ms = [l.strip() for l in model_text.splitlines() if l.strip()]
            rows = []
            for r in model_matcher.match_batch(ms):
                rows.append({
                    "Input Model":   r["input"],
                    "Global Model":  r["canonical"],
                    "Confidence":    r["confidence"],
                    "Status":        r["status"],
                    "Alt 1": r["candidates"][1][0] if len(r["candidates"])>1 else "",
                    "Alt 2": r["candidates"][2][0] if len(r["candidates"])>2 else "",
                })
            mdf = pd.DataFrame(rows)
            # ---- FIX 2: save to session state ----
            st.session_state.last_model_df = mdf

            st.markdown("##### Model name results")
            st.dataframe(mdf.style.map(color_status, subset=["Status"]),
                         use_container_width=True)
            st.download_button("⬇ Download model results", mdf.to_csv(index=False),
                               "model_results.csv", "text/csv")

        if ran and review_count() > 0:
            st.info(f"💡 {review_count()} row(s) need review — see the **🟡 Review Queue** tab.")

# ============ TAB 2: SEARCH ============
with tab_search:
    st.subheader("Search the catalog")
    st.caption("Fuzzy bidirectional search — type in any field and press Enter.")
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

    if any([q_uin, q_sku, q_cat, q_mod, q_col]):
        if uin_lut:
            res = []
            for sku, info in uin_lut.items():
                if q_uin and not bimatch(info.get("uin",""),      q_uin): continue
                if q_sku and not bimatch(sku,                     q_sku): continue
                if q_cat and not bimatch(info.get("category",""), q_cat): continue
                if q_mod and not bimatch(sku,                     q_mod): continue
                if q_col and not bimatch(info.get("color",""),    q_col): continue
                res.append({"UIN":info.get("uin",""),"SKU":sku,
                            "Category":info.get("category",""),
                            "Type":info.get("type",""),
                            "Color":info.get("color","")})
                if len(res) >= 100: break
            st.write(f"{len(res)} result(s)")
            if res:
                st.dataframe(pd.DataFrame(res), use_container_width=True)
        else:
            hits = [s for s in master if any(bimatch(s,q) for q in [q_sku,q_mod] if q)]
            st.write(f"{len(hits)} result(s) in master SKU list")
            if hits:
                st.dataframe(pd.DataFrame({"SKU":hits[:100]}), use_container_width=True)

# ============ TAB 3: DASHBOARD ============
with tab_dash:
    st.subheader("Catalog overview")

    # ---- FIX 1: use st.metric() — theme-aware, no custom HTML needed ----
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Master SKUs",       len(master))
    c2.metric("Canonical Models",  len(models))
    c3.metric("UIN Entries",       len(uin_lut))
    c4.metric("Override Rules",    len(overrides))
    c5.metric("Junk Tokens",       len(DEFAULT_CONFIG["junk_tokens"]))

    if st.session_state.models_derived:
        st.caption("ℹ️ Model list was derived from SKUs (no separate model sheet provided).")

    if uin_lut:
        cats = {}
        for info in uin_lut.values():
            c = info.get("category","") or "—"
            cats[c] = cats.get(c,0)+1
        st.markdown("##### Products by category")
        st.bar_chart(pd.Series(cats).sort_values(ascending=False))

# ============ TAB 4: REVIEW QUEUE — FIX 2 ============
with tab_review:
    st.subheader("Review Queue")
    st.caption("Low-confidence rows from the last Standardize run. "
               "Check the Alt 1 / Alt 2 columns to find the right match.")

    has_results = (st.session_state.last_sku_df is not None or
                   st.session_state.last_model_df is not None)

    if not has_results:
        st.info("No results yet — run a batch in the 🔧 Standardize tab first.")
    else:
        # SKU review rows
        if st.session_state.last_sku_df is not None:
            rev_sku = st.session_state.last_sku_df[
                st.session_state.last_sku_df["Status"].isin(
                    ["review","no_confident_match"])].copy()
            rev_sku = rev_sku.sort_values("Confidence", ascending=False)
            if len(rev_sku):
                st.markdown(f"##### SKU — {len(rev_sku)} row(s) to review")
                st.dataframe(rev_sku.style.map(color_status, subset=["Status"]),
                             use_container_width=True)
                st.download_button("⬇ Download SKU review queue",
                                   rev_sku.to_csv(index=False),
                                   "sku_review.csv","text/csv",
                                   key="dl_sku_review")
            else:
                st.success("✅ All SKU rows were auto-resolved — nothing to review.")

        # Model review rows
        if st.session_state.last_model_df is not None:
            rev_mod = st.session_state.last_model_df[
                st.session_state.last_model_df["Status"].isin(
                    ["review","no_confident_match"])].copy()
            rev_mod = rev_mod.sort_values("Confidence", ascending=False)
            if len(rev_mod):
                st.markdown(f"##### Model names — {len(rev_mod)} row(s) to review")
                st.dataframe(rev_mod.style.map(color_status, subset=["Status"]),
                             use_container_width=True)
                st.download_button("⬇ Download model review queue",
                                   rev_mod.to_csv(index=False),
                                   "model_review.csv","text/csv",
                                   key="dl_mod_review")
            else:
                st.success("✅ All model rows were auto-resolved — nothing to review.")
