#!/usr/bin/env python3
"""
Importa articoli, pagine e immagini dal blog Blogger originale.

- Elenco articoli dal feed JSON di Blogger (paginazione con published-max,
  più affidabile di start-index).
- Il testo completo viene letto dalla pagina HTML di ogni articolo
  (div.post-body), quindi funziona anche se il feed è impostato su "breve".
- Le immagini vengono scaricate in assets/img, ridimensionate e convertite
  in WebP; nel testo gli indirizzi vengono riscritti verso le copie locali.
- Incrementale: un articolo viene riletto solo se su Blogger risulta
  modificato (campo "updated"). Usa --full per rileggere tutto.

Uso: python scripts/sync.py [--full] [--limit N]
"""
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
POSTS_DIR = CONTENT / "posts"
PAGES_DIR = CONTENT / "pages"
IMG_DIR = ROOT / "assets" / "img"
MANIFEST = CONTENT / "images.json"
CONFIG = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
BLOG = os.environ.get("SOURCE_BLOG", CONFIG["source_blog"]).rstrip("/")
BLOG_HOSTS = {urllib.parse.urlparse(BLOG).netloc, "zulunationitalia.blogspot.com", "zulunationitalia.blogspot.it",
              "www.zulunation.it", "zulunation.it"}
UA = "Mozilla/5.0 (compatible; ZulunationSync/1.0)"
MAX_W = int(CONFIG.get("image_max_width", 1600))
QUALITY = int(CONFIG.get("image_quality", 80))

IMG_HOST_RE = re.compile(r"(blogger\.googleusercontent\.com|\.bp\.blogspot\.com|\.ggpht\.com|lh\d\.googleusercontent\.com"
                         + (("|" + os.environ["EXTRA_IMG_HOST"]) if os.environ.get("EXTRA_IMG_HOST") else "") + ")")


def log(*a):
    print(*a, flush=True)


HTML_BLOCKED = [0]
_page_lock = threading.Lock()
_last_page = [0.0]
PAGE_DELAY = float(os.environ.get("SYNC_PAGE_DELAY", "1.5"))


def fetch(url, binary=False, tries=5, polite=False):
    """Scarica un URL. polite=True distanzia le richieste al blog per evitare l'errore 429."""
    last = None
    for i in range(tries):
        if polite:
            with _page_lock:
                wait = PAGE_DELAY - (time.time() - _last_page[0])
                if wait > 0:
                    time.sleep(wait)
                _last_page[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = r.read()
                return data if binary else data.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                break
            if e.code == 429:
                ra = e.headers.get("Retry-After")
                pause = int(ra) if ra and ra.isdigit() else 20 * (i + 1)
                log(f"   … Blogger chiede di rallentare, attendo {pause}s")
                time.sleep(min(pause, 180))
                continue
            time.sleep(2 * (i + 1))
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise last


# ---------------------------------------------------------------- feed

def feed_entries(kind="posts"):
    """Tutti gli entry del feed, deduplicati per id."""
    seen = {}
    if kind == "pages":
        data = json.loads(fetch(f"{BLOG}/feeds/pages/default?alt=json&max-results=500", polite=True))
        for e in data["feed"].get("entry", []):
            seen[e["id"]["$t"]] = e
        return list(seen.values())
    cursor = None
    for _ in range(100):
        url = f"{BLOG}/feeds/posts/default?alt=json&max-results=150&orderby=published"
        if cursor:
            url += "&published-max=" + urllib.parse.quote(cursor)
        data = json.loads(fetch(url, polite=True))
        entries = data["feed"].get("entry", [])
        added = 0
        for e in entries:
            if e["id"]["$t"] not in seen:
                seen[e["id"]["$t"]] = e
                added += 1
        if not added:
            break
        cursor = entries[-1]["published"]["$t"]
    return list(seen.values())


def alt_link(e):
    for l in e.get("link", []):
        if l.get("rel") == "alternate":
            return l["href"]
    return None


# ---------------------------------------------------------------- immagini

def normalize_img_url(url):
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    url = url.replace("http://", "https://")
    # formato /img/b/.../s1600/nome.jpg oppure /w640-h480/nome.jpg
    url = re.sub(r"/(s\d+(-[a-zA-Z0-9-]+)?|w\d+(-h\d+)?(-[a-zA-Z0-9-]+)?|h\d+(-[a-zA-Z0-9-]+)?)/([^/]+)$",
                 r"/s1600/\6", url)
    # formato /img/a/...=s1600 oppure =w640-h480
    url = re.sub(r"=(s\d+|w\d+(-h\d+)?)(-[a-zA-Z0-9-]+)?$", "=s1600", url)
    return url


class ImageStore:
    def __init__(self):
        self.map = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
        self.changed = False
        self.lock = threading.Lock()

    def prefetch(self, urls):
        urls = [u for u in dict.fromkeys(urls) if u and IMG_HOST_RE.search(u)]
        if urls:
            with ThreadPoolExecutor(max_workers=8) as ex:
                list(ex.map(self.get, urls))

    def save(self):
        if self.changed:
            with self.lock:
                snapshot = dict(self.map)
            MANIFEST.write_text(json.dumps(snapshot, indent=1, sort_keys=True), encoding="utf-8")

    def get(self, url):
        """Ritorna il percorso locale (/assets/img/...) o None se non scaricabile."""
        if not url or url.startswith("data:"):
            return None
        norm = normalize_img_url(url)
        rec = self.map.get(norm)
        if rec and rec.get("file") and (IMG_DIR / rec["file"]).exists():
            return "/assets/img/" + rec["file"]
        if rec and rec.get("fail", 0) >= 3:
            return None
        try:
            raw = fetch(norm, binary=True)
            name = self._store(norm, raw)
            self.map[norm] = {"file": name}
            self.changed = True
            return "/assets/img/" + name
        except Exception as e:  # noqa
            # se la versione grande non esiste prova l'originale
            try:
                if norm != url:
                    raw = fetch(url, binary=True)
                    name = self._store(norm, raw)
                    self.map[norm] = {"file": name}
                    self.changed = True
                    return "/assets/img/" + name
            except Exception:
                pass
            r = self.map.setdefault(norm, {})
            r["fail"] = r.get("fail", 0) + 1
            self.changed = True
            log("   ! immagine non scaricata:", norm[:110], "-", e)
            return None

    def _store(self, norm, raw):
        h = hashlib.sha1(norm.encode()).hexdigest()[:16]
        IMG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            im = Image.open(io.BytesIO(raw))
            if getattr(im, "is_animated", False):
                ext = (im.format or "gif").lower()
                name = f"{h}.{ 'gif' if ext == 'gif' else ext }"
                (IMG_DIR / name).write_bytes(raw)
                return name
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA" if "transparency" in im.info or im.mode in ("LA", "P") else "RGB")
            if im.width > MAX_W:
                im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
            name = f"{h}.webp"
            im.save(IMG_DIR / name, "WEBP", quality=QUALITY, method=5)
            return name
        except Exception:
            ext = os.path.splitext(urllib.parse.urlparse(norm).path)[1][:5] or ".bin"
            name = h + ext
            (IMG_DIR / name).write_bytes(raw)
            return name


# ---------------------------------------------------------------- pulizia HTML

KEEP_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "iframe": {"src", "allowfullscreen", "allow", "title"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
    "video": {"src", "controls", "poster"},
    "source": {"src", "type"},
    "audio": {"src", "controls"},
}


def internal_path(href):
    """Trasforma link al vecchio blog in percorsi interni."""
    try:
        u = urllib.parse.urlparse(href)
    except Exception:
        return href
    if u.netloc in BLOG_HOSTS:
        path = u.path or "/"
        if path.startswith("/search/label/"):
            label = urllib.parse.unquote(path[len("/search/label/"):])
            return "/label/" + slugify(label) + "/"
        return path + (("#" + u.fragment) if u.fragment else "")
    return href


def slugify(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "x"


def clean_html(html, images):
    soup = BeautifulSoup(html, "html.parser")
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    for t in soup.find_all(["script", "style", "noscript", "meta", "link"]):
        t.decompose()
    for a in soup.find_all("a", attrs={"name": "more"}):
        a.decompose()
    for t in soup.find_all(["font", "o:p"]):
        t.unwrap()

    first_img = None
    urls = []
    for img in soup.find_all("img"):
        urls.append(img.get("src") or img.get("data-src") or "")
        if img.parent and img.parent.name == "a":
            urls.append(img.parent.get("href", ""))
    images.prefetch(urls)
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if IMG_HOST_RE.search(src):
            local = images.get(src)
            if local:
                img["src"] = local
                first_img = first_img or local
        elif src.startswith("http://"):
            img["src"] = "https://" + src[7:]
        parent = img.parent
        if parent and parent.name == "a" and IMG_HOST_RE.search(parent.get("href", "")):
            local = images.get(parent["href"])
            if local:
                parent["href"] = local
                parent["class"] = "lightbox"

    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        if src.startswith("//"):
            iframe["src"] = "https:" + src
        wrap = soup.new_tag("div", attrs={"class": "embed"})
        iframe.wrap(wrap)

    for a in soup.find_all("a", href=True):
        a["href"] = internal_path(a["href"])
        if a["href"].startswith("http"):
            a["target"] = "_blank"
            a["rel"] = "noopener"

    for tag in soup.find_all(True):
        cls = tag.get("class") or []
        if isinstance(cls, str):
            cls = [cls]
        keep = KEEP_ATTRS.get(tag.name, set())
        new_cls = []
        if "separator" in cls:
            new_cls.append("media")
        if "tr-caption-container" in cls:
            new_cls.append("caption-table")
        if "tr-caption" in cls:
            new_cls.append("caption")
        if "lightbox" in cls:
            new_cls.append("lightbox")
        if "embed" in cls:
            new_cls.append("embed")
        attrs = {k: v for k, v in tag.attrs.items() if k in keep or (tag.name == "a" and k in ("target", "rel"))}
        if new_cls:
            attrs["class"] = " ".join(new_cls)
        if tag.name == "img":
            attrs["loading"] = "lazy"
            attrs.setdefault("alt", "")
        tag.attrs = attrs

    # span senza attributi: inutili
    for s in soup.find_all("span"):
        if not s.attrs:
            s.unwrap()

    out = str(soup)
    out = out.replace("\xa0", " ")
    out = re.sub(r"(<br\s*/?>\s*){3,}", "<br><br>", out)
    out = re.sub(r"<div>\s*(<br\s*/?>)?\s*</div>", "", out)
    out = re.sub(r"<p>\s*</p>", "", out)
    return out.strip(), first_img


def text_excerpt(html, n=220):
    t = BeautifulSoup(html, "html.parser").get_text(" ")
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:") + "…"


def extract_body(page_html):
    soup = BeautifulSoup(page_html, "html.parser")
    body = soup.select_one(".post-body") or soup.select_one(".entry-content") or soup.select_one("article")
    return body.decode_contents() if body else ""


# ---------------------------------------------------------------- main

def process(entry, kind, images, existing, full):
    link = alt_link(entry)
    if not link:
        return None
    path = urllib.parse.urlparse(link).path
    updated = entry["updated"]["$t"]
    key = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-").replace("-html", "")
    target = (POSTS_DIR if kind == "post" else PAGES_DIR) / f"{key}.json"
    old = existing.get(target.name)
    if old and old.get("updated") == updated and not old.get("partial") and not full:
        return target.name
    log(f" > {kind}: {entry['title']['$t'][:80]}")
    partial = False
    feed_html = (entry.get("content") or {}).get("$t")
    if feed_html:
        # feed "completo": il testo intero arriva già dal feed, nessuna pagina da scaricare
        raw = feed_html
    elif HTML_BLOCKED[0] >= 2:
        if old and not old.get("partial"):
            return target.name
        raw = (entry.get("summary") or {}).get("$t", "")
        partial = True
    else:
        try:
            raw = extract_body(fetch(link, polite=True, tries=2))
            if not raw.strip():
                raise ValueError("corpo articolo vuoto")
            HTML_BLOCKED[0] = 0
        except Exception as e:
            log("   ! pagina non leggibile:", link, e)
            if getattr(e, "code", None) == 429:
                HTML_BLOCKED[0] += 1
                if HTML_BLOCKED[0] >= 2:
                    log("   Blogger blocca le pagine: per questo giro tengo i riassunti e riprovo al prossimo.")
            if old and not old.get("partial"):
                return target.name
            raw = (entry.get("summary") or {}).get("$t", "")
            partial = True
    html, first_img = clean_html(raw, images)
    cover = None
    thumb = (entry.get("media$thumbnail") or {}).get("url")
    if first_img:
        cover = first_img
    elif thumb:
        cover = images.get(thumb)
    authors = entry.get("author") or [{}]
    data = {
        "id": entry["id"]["$t"].split("-")[-1],
        "kind": kind,
        "title": entry["title"]["$t"].strip() or "Senza titolo",
        "path": path,
        "published": entry["published"]["$t"],
        "updated": updated,
        "labels": [c["term"] for c in entry.get("category", [])],
        "author": (authors[0].get("name") or {}).get("$t", ""),
        "cover": cover,
        "excerpt": text_excerpt(html),
        "source_url": link,
        "html": html,
    }
    if partial:
        data["partial"] = True  # verrà riletto al prossimo giro
    target.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return target.name


START = time.time()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="rilegge tutti gli articoli")
    ap.add_argument("--limit", type=int, default=0, help="solo i primi N articoli (test)")
    ap.add_argument("--max-minutes", type=float, default=float(os.environ.get("SYNC_MAX_MINUTES", 0) or 0),
                    help="si ferma dopo N minuti salvando il lavoro fatto (0 = nessun limite)")
    args = ap.parse_args()

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    images = ImageStore()

    for kind, d, feed_kind in (("post", POSTS_DIR, "posts"), ("page", PAGES_DIR, "pages")):
        existing = {}
        for f in d.glob("*.json"):
            try:
                existing[f.name] = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
        entries = feed_entries(feed_kind)
        if args.limit and kind == "post":
            entries = entries[: args.limit]
        log(f"{feed_kind}: {len(entries)} sul blog, {len(existing)} già importati")
        keep = set()
        stopped = False
        for i, e in enumerate(entries):
            if args.max_minutes and time.time() - START > args.max_minutes * 60:
                log(f"Tempo massimo raggiunto: continuo al prossimo giro ({i}/{len(entries)}).")
                stopped = True
                break
            name = process(e, kind, images, existing, args.full)
            if name:
                keep.add(name)
            if i % 20 == 0:
                images.save()
        if not args.limit and not stopped:
            for name in set(existing) - keep:
                log(" - rimosso (non più sul blog):", name)
                (d / name).unlink()
    images.save()
    log("Fatto.")


if __name__ == "__main__":
    sys.exit(main())
