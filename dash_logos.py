"""Real coin / stock logos for the GROKBOT DESK dashboard (2026-10-21, SAVIP v2).
Meme coins: DexScreener info.imageUrl (pairs / tokens batch), fallback pump.fun coins-v2 image_uri.
Stocks/ETFs: keyless logo CDNs by ticker (assets.parqet.com, fallback financialmodelingprep image-stock).
Every image is downloaded once, resized to 64x64 WebP and cached in ~/.desk/chart_cache/logos/<id>.webp, then the files
the page needs are copied to <out>/logos/ and served next to index.html (no external logo URLs on the page).
Misses are remembered (retry after 12 h). Network budget per build: a few calls, short timeouts, never raises."""
import os, io, re, json, time, shutil, hashlib
DESK = os.path.expanduser("~/.desk"); CACHE = f"{DESK}/chart_cache/logos"; META = f"{CACHE}/_meta.json"
UA = {"User-Agent": "Mozilla/5.0 (GROKBOT DESK dashboard)", "Accept": "image/*,application/json;q=0.9,*/*;q=0.5"}
RETRY_MISS_S = 12 * 3600; MAX_BYTES = 3_000_000; SIZE = 64

def _fid(s): return re.sub(r"[^A-Za-z0-9_-]", "", str(s))[:64]
def tkey(name): return re.sub(r"\s+", " ", (name or "?").split(" / ")[0].strip()[:12]).upper()

class Logos:
    def __init__(self):
        os.makedirs(CACHE, exist_ok=True)
        try: self.m = json.load(open(META))
        except Exception: self.m = {}
        for k in ("pool", "img", "miss"): self.m.setdefault(k, {})
        self.want = {}   # tkey -> ("sol", mint|None, pool|None) | ("stk", symbol) | ("cry", symbol)
        self.t0 = time.time(); self.calls = 0
    def add_sol(self, name, mint=None, pool=None):
        k = tkey(name)
        if not k or k in ("?", "CASH"): return
        cur = self.want.get(k)
        if cur and cur[0] == "sol" and (cur[1] or not mint): return
        if cur and cur[0] != "sol": return
        self.want[k] = ("sol", mint, pool)
    def add_alp(self, sym):
        s = str(sym or "").upper().strip()
        if not s or s in self.want: return
        if "/" in s or (s.endswith("USD") and len(s) in (6, 7) and s[:-3] in ("BTC", "ETH", "SOL", "DOGE", "LTC", "AVAX", "LINK", "XRP")):
            base = s.split("/")[0] if "/" in s else s[:-3]
            self.want[s] = ("cry", base); self.want.setdefault(base, ("cry", base))
        else: self.want[s] = ("stk", s)
    # ---------------------------------------------------------------- network (all soft, budgeted)
    def _ok(self, budget_s=15, max_calls=16): return time.time() - self.t0 < budget_s and self.calls < max_calls
    def _get(self, url, timeout=6):
        import requests
        self.calls += 1
        r = requests.get(url, headers=UA, timeout=timeout, stream=True)
        if r.status_code != 200: r.close(); return None
        data = r.raw.read(MAX_BYTES + 1, decode_content=True); r.close()
        return data if len(data) <= MAX_BYTES else None
    def _save_img(self, fid, raw):
        from PIL import Image, ImageOps
        Image.MAX_IMAGE_PIXELS = 40_000_000
        im = Image.open(io.BytesIO(raw)); im.seek(0); im = im.convert("RGBA")
        im = ImageOps.fit(im, (SIZE, SIZE), method=Image.LANCZOS)
        tmp = f"{CACHE}/.{fid}.tmp.webp"; im.save(tmp, "WEBP", quality=82, method=4); os.replace(tmp, f"{CACHE}/{fid}.webp")
        return True
    def _missed(self, fid): return time.time() - self.m["miss"].get(fid, 0) < RETRY_MISS_S
    def _fetch(self, fid, urls):
        for u in urls:
            if not u or not str(u).startswith("https://") or not self._ok(): continue
            try:
                raw = self._get(u)
                if raw and self._save_img(fid, raw): self.m["miss"].pop(fid, None); return True
            except Exception: pass
        self.m["miss"][fid] = time.time(); return False
    def resolve(self, out_dir):
        try: self._resolve()
        except Exception: pass
        try: json.dump(self.m, open(META + ".tmp", "w")); os.replace(META + ".tmp", META)
        except Exception: pass
        return self._sync(out_dir)
    def _resolve(self):
        import requests
        sol = {k: v for k, v in self.want.items() if v[0] == "sol"}
        # 1) pool -> mint (+ image) via DexScreener pairs, one batch
        need = [p for _, m, p in sol.values() if not m and p and p not in self.m["pool"] and not self._missed("p_" + _fid(p))][:30]
        if need and self._ok():
            try:
                self.calls += 1
                r = requests.get("https://api.dexscreener.com/latest/dex/pairs/solana/" + ",".join(need), headers=UA, timeout=6)
                for pr in (r.json().get("pairs") or []):
                    mt = (pr.get("baseToken") or {}).get("address")
                    if mt: self.m["pool"][pr["pairAddress"]] = mt
                    iu = (pr.get("info") or {}).get("imageUrl")
                    if mt and iu: self.m["img"][mt] = iu
                for p in need:
                    if p not in self.m["pool"]: self.m["miss"]["p_" + _fid(p)] = time.time()
            except Exception: pass
        mints = {}
        for k, (_, m, p) in sol.items():
            m = m or self.m["pool"].get(p)
            if m: mints[k] = m
        self._mints = mints
        # 2) mint -> image URL via DexScreener tokens batch, then pump.fun coins-v2 for a few misses
        need = [m for m in set(mints.values()) if m not in self.m["img"] and not os.path.exists(f"{CACHE}/{_fid(m)}.webp") and not self._missed("u_" + _fid(m))][:30]
        if need and self._ok():
            try:
                self.calls += 1
                r = requests.get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(need), headers=UA, timeout=6)
                for pr in (r.json() or []):
                    mt = (pr.get("baseToken") or {}).get("address"); iu = (pr.get("info") or {}).get("imageUrl")
                    if mt and iu and mt in need: self.m["img"].setdefault(mt, iu)
            except Exception: pass
        pf = 0
        for m in need:
            if m in self.m["img"] or pf >= 3 or not self._ok(): continue
            pf += 1
            try:
                self.calls += 1
                r = requests.get(f"https://frontend-api-v3.pump.fun/coins-v2/{m}", headers=UA, timeout=6)
                iu = (r.json() or {}).get("image_uri") if r.status_code == 200 else None
                if iu: self.m["img"][m] = iu
                else: self.m["miss"]["u_" + _fid(m)] = time.time()
            except Exception: self.m["miss"]["u_" + _fid(m)] = time.time()
        # 3) download images (budgeted), in registration order: holdings first, then trades / scan / orders
        done = set()
        for k, v in self.want.items():
            if not self._ok(): break
            if v[0] == "sol":
                m = mints.get(k)
                if not m or m in done: continue
                done.add(m); fid = _fid(m)
                if os.path.exists(f"{CACHE}/{fid}.webp") or self._missed(fid) or m not in self.m["img"]: continue
                iu = self.m["img"][m]
                if iu.startswith("ipfs://"): iu = "https://ipfs.io/ipfs/" + iu[7:]
                self._fetch(fid, [iu] + ([iu.replace("https://ipfs.io/", "https://dweb.link/")] if "ipfs.io/" in iu else []))
            else:
                fid = ("s_" if v[0] == "stk" else "c_") + _fid(v[1])
                if fid in done or os.path.exists(f"{CACHE}/{fid}.webp") or self._missed(fid): continue
                done.add(fid)
                if v[0] == "stk": urls = [f"https://assets.parqet.com/logos/symbol/{v[1]}?format=png&size=128", f"https://financialmodelingprep.com/image-stock/{v[1]}.png"]
                else: urls = [f"https://assets.parqet.com/logos/crypto/{v[1]}?format=png&size=128"]
                self._fetch(fid, urls)
    def _sync(self, out_dir):
        """Copy the needed files to <out_dir>/logos, drop stale ones, return {tkey: 'logos/<id>.webp?v=..'}"""
        mp = {}; mints = getattr(self, "_mints", {})
        for k, v in self.want.items():
            fid = (_fid(mints[k]) if k in mints else None) if v[0] == "sol" else (("s_" if v[0] == "stk" else "c_") + _fid(v[1]))
            if fid and os.path.exists(f"{CACHE}/{fid}.webp"): mp[k] = fid
        try:
            dst = f"{out_dir}/logos"; os.makedirs(dst, exist_ok=True)
            keep = set(f"{f}.webp" for f in mp.values())
            for f in os.listdir(dst):
                if f.endswith(".webp") and f not in keep and time.time() - os.path.getmtime(f"{dst}/{f}") > 6 * 3600: os.remove(f"{dst}/{f}")   # keep a while: a cached index.html may still use it
            ver = {}
            for f in keep:
                s, d = f"{CACHE}/{f}", f"{dst}/{f}"
                if not os.path.exists(d) or os.path.getmtime(d) < os.path.getmtime(s): shutil.copy2(s, d)
                else: os.utime(d)
                ver[f] = hashlib.sha1(open(d, "rb").read()).hexdigest()[:8]
            return {k: f"logos/{f}.webp?v={ver[f + '.webp']}" for k, f in mp.items()}
        except Exception:
            return {}
