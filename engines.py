"""Matching engines — shared by the Streamlit app. Pure Python, no Streamlit deps."""
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DEFAULT_CONFIG = {
    "junk_tokens": {
        "jio","prtnr","prt","exc","ex","bogo","sbi","fitelo","hlthfyme","abhi","co","d",
        "herbit","amzn","flpkrt","myntra","ajio","croma","rcom","partner",
        "apolo","apollo","healthifyme","unidays","fitpass","pay","paytm","cliq","tatacliq","vijaysales",
        "cmb","pulltab","ny","strap",
    },
    "abbreviations": {
        "slv":"slvr","msh":"mesh","win":"wine","wn":"wine",
        "colrfit":"colorfit","clrfit":"colorfit","glmtl":"glossymtl",
        "elite":"mtl","leather":"lthr","nylon":"ny","standard":"std",
        "meshmetal":"meshmtl","glossymetal":"glossymtl","mattemetal":"mattemtl",
    },
    "model_aliases": {
        "twist go":"twistgo","halo 2":"halo2","halo 3":"halo3","diva 2":"diva2",
        "crew 2":"crew2","champ 3":"champ3","active 2":"active2","explorer 2":"explorer2",
        "agile 2":"agile2","force plus":"forceplus","vortex plus":"vortexplus",
        "halo plus":"haloplus","colorfit pro":"colorfitpro","colorfit pulse":"colorfitpulse",
    },
    "auto_accept": 0.85,
    "review_floor": 0.60,
    "ngram_range": (2, 4),
}


class SKUMatcher:
    def __init__(self, master_skus, config=None, overrides=None):
        self.config = config or DEFAULT_CONFIG
        self.overrides = overrides or {}
        seen, self.master = set(), []
        for m in master_skus:
            m = str(m).strip()
            if m and m not in seen: seen.add(m); self.master.append(m)
        self._build()

    def normalize(self, sku):
        s = str(sku).lower().strip()
        s = re.sub(r"\bnoise\b", "", s)
        s = re.sub(r"[_\-\.\s/]+", "-", s)
        s = re.sub(r"-+", "-", s).strip("-")
        toks = []
        for t in s.split("-"):
            if not t or t in self.config["junk_tokens"]: continue
            if re.fullmatch(r"\d{2}mm?(strap)?", t): continue
            toks.append(self.config["abbreviations"].get(t, t))
        r = " ".join(toks)
        r = re.sub(r'(?<=[a-z]) (?=[0-9])', '', r)
        r = re.sub(r'(?<=[0-9]) (?=[a-z])', '', r)
        for sf, jf in self.config["model_aliases"].items():
            r = r.replace(sf, jf)
        return re.sub(r' +', ' ', r).strip()

    def _build(self):
        self.norm_master = [self.normalize(m) for m in self.master]
        self.master_set = set(self.master)
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=self.config["ngram_range"])
        self.M = self.vec.fit_transform(self.norm_master)

    def match(self, polluted, top_k=3):
        raw = str(polluted).strip()
        if not raw: return self._r(raw, "", 0.0, "empty", [])
        key = self.normalize(raw)
        if key in self.overrides:
            return self._r(raw, self.overrides[key], 1.0, "override", [(self.overrides[key],1.0)])
        if raw in self.master_set:
            return self._r(raw, raw, 1.0, "exact", [(raw,1.0)])
        if not key: return self._r(raw, "", 0.0, "empty_after_clean", [])
        sims = cosine_similarity(self.vec.transform([key]), self.M)[0]
        order = sims.argsort()[::-1][:top_k]
        cands = [(self.master[i], float(sims[i])) for i in order]
        best, score = cands[0]
        status = ("auto_accept" if score>=self.config["auto_accept"]
                  else "review" if score>=self.config["review_floor"]
                  else "no_confident_match")
        return self._r(raw, best, score, status, cands)

    def match_batch(self, items, top_k=3):
        return [self.match(p, top_k=top_k) for p in items]

    @staticmethod
    def _r(inp, clean, score, status, cands):
        return {"input":inp,"clean_sku":clean,"confidence":round(float(score),4),
                "status":status,"candidates":cands}


class ModelNameMatcher:
    STRIP_TOKENS = {
        "noise","colorfit","cf",
        "std","standard","lthr","leather","mtl","elite","meshmtl","meshmetal",
        "glossymtl","glossymetal","mattemtl","mattemetal","ny","nylon","msh","mesh","glmtl","si","ri",
        "blk","wht","gld","slvr","pnk","blu","grn","gry","brn","rgld","nckl","cprgld","bge",
        "win","wine","tgry","mnt","rse","prpl","nblk","hslvr","slv","mbrwn","mpnk",
        "black","white","gold","silver","pink","blue","green","grey","gray","brown","red",
    }
    ABBR = {"colrfit":"colorfit","clrfit":"colorfit","colourfit":"colorfit"}

    def __init__(self, canonical_names, auto_accept=0.80, review_floor=0.55):
        self.auto_accept, self.review_floor = auto_accept, review_floor
        seen, self.names = set(), []
        for n in canonical_names:
            n = str(n).strip()
            if n and n not in seen: seen.add(n); self.names.append(n)
        self.norm_names = [self.normalize(n) for n in self.names]
        self.exact_map = {self.normalize(n): n for n in self.names}
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2,4))
        self.M = self.vec.fit_transform(self.norm_names)

    def normalize(self, s):
        s = str(s).lower().strip()
        s = re.sub(r"[_\-\.\s/]+", " ", s)
        toks = []
        for t in s.split():
            t = self.ABBR.get(t, t)
            if t in self.STRIP_TOKENS: continue
            toks.append(t)
        r = " ".join(toks)
        # fully join: SKU-derived model tokens are joined (e.g. "activegps","pulse2max"),
        # while humans type spaced ("Active Gps","Pulse 2 Max") — collapse to one token form
        r = re.sub(r'\s+', '', r)
        return r.strip()

    def match(self, messy, top_k=3):
        raw = str(messy).strip()
        norm = self.normalize(raw)
        if not norm: return self._r(raw, "", 0.0, "empty", [])
        if norm in self.exact_map:
            return self._r(raw, self.exact_map[norm], 1.0, "exact", [(self.exact_map[norm],1.0)])
        sims = cosine_similarity(self.vec.transform([norm]), self.M)[0]
        order = sims.argsort()[::-1][:top_k]
        cands = [(self.names[i], float(sims[i])) for i in order]
        best, score = cands[0]
        status = ("auto_accept" if score>=self.auto_accept
                  else "review" if score>=self.review_floor
                  else "no_confident_match")
        return self._r(raw, best, score, status, cands)

    def match_batch(self, items, top_k=3):
        return [self.match(p, top_k=top_k) for p in items]

    @staticmethod
    def _r(inp, canon, score, status, cands):
        return {"input":inp,"canonical":canon,"confidence":round(float(score),4),
                "status":status,"candidates":cands}


def mine_overrides(matcher, mapping_pairs):
    """Seed override rules from (polluted, clean) history where base pipeline disagrees."""
    overrides = {}
    mset = matcher.master_set
    for polluted, clean in mapping_pairs:
        if clean not in mset: continue
        base = matcher.match(polluted)["clean_sku"]
        if base != clean:
            overrides[matcher.normalize(polluted)] = clean
    return overrides


# ---------------------------------------------------------------
#  Derive a canonical model list directly from master SKUs
#  (for catalogs that have no separate model-name list)
# ---------------------------------------------------------------
_PREFIXES = ["wrb-sw_alt","wrb-sw","wrb-sb","aud-hdphn","aud-spkr","aud-case",
             "aud-erphn","pwr-cable","pwr-chrgr","pwr-tag1","cmb"]
_MATERIALS = {"std","mtl","lthr","meshmtl","glossymtl","mattemtl","si","ny","ri",
              "sport","sprt","spt","mesh","glmtl"}

def _extract_model_token(sku):
    s = str(sku).lower().replace("_", "-")
    for p in _PREFIXES:
        if s.startswith(p + "-"):
            s = s[len(p)+1:]; break
    parts, mp = s.split("-"), []
    for seg in parts:
        if seg in _MATERIALS: break
        mp.append(seg)
    return "".join(mp)

def _canonicalize_model(token):
    # strip product-line prefixes so colorfit/cf/none collapse together
    for pre in ("colorfit", "cf"):
        if token.startswith(pre) and len(token) > len(pre):
            return token[len(pre):]
    return token

def derive_canonical_models(master_skus):
    """Return a sorted list of canonical model tokens extracted from master SKUs.
       Use when the catalog has SKUs but no separate model-name list."""
    seen = {}
    for sku in master_skus:
        tok = _extract_model_token(sku)
        if not tok:
            continue
        canon = _canonicalize_model(tok)
        seen[canon] = seen.get(canon, 0) + 1
    return sorted(seen.keys())
