#!/usr/bin/env python3
"""
Genera il sito statico in _site/ a partire da content/ e site.json.

Variabili d'ambiente opzionali:
  BASE_PATH  prefisso dei percorsi (es. /zulunation-sito per GitHub Pages
             senza dominio). Vuoto quando il sito gira su www.zulunation.it.
  SITE_URL   indirizzo pubblico completo, usato per RSS, sitemap e meta.
"""
import html
import json
import math
import os
import re
import shutil
import unicodedata
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"
CFG = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
DOMAIN = CFG.get("custom_domain", "").strip()
BASE = os.environ.get("BASE_PATH", "").rstrip("/")
if DOMAIN:
    BASE = ""
SITE_URL = (os.environ.get("SITE_URL") or ("https://" + DOMAIN if DOMAIN else CFG["site_url"])).rstrip("/")
if BASE and not SITE_URL.endswith(BASE):
    SITE_URL = SITE_URL + BASE
ORIGIN = SITE_URL[: -len(BASE)] if BASE else SITE_URL
PER_PAGE = int(CFG.get("posts_per_page", 24))
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre"]
E = html.escape


def slugify(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "x"


def U(path):
    """URL interno con prefisso BASE."""
    if not path:
        return path
    if path.startswith(("http://", "https://", "mailto:", "#", "tel:")):
        return path
    return BASE + path


def label_url(label):
    return U(f"/label/{slugify(label)}/")


def fmt_date(iso):
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return f"{d.day} {MESI[d.month - 1]} {d.year}"


def parse_dt(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


# ---------------------------------------------------------------- dati

def load(kind):
    items = []
    for f in sorted((ROOT / "content" / kind).glob("*.json")):
        try:
            items.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:
            print("file non valido", f, e)
    return items


POSTS = sorted(load("posts"), key=lambda p: p["published"], reverse=True)
YT_RE = re.compile(r"youtube(?:-nocookie)?\.com/embed/([A-Za-z0-9_-]{6,})")
for _p in POSTS:
    if not _p.get("cover"):
        m = YT_RE.search(_p.get("html", ""))
        if m:
            _p["cover"] = f"https://i.ytimg.com/vi/{m.group(1)}/hqdefault.jpg"
PAGES = load("pages")
LABELS = defaultdict(list)
for p in POSTS:
    for l in p["labels"]:
        LABELS[l].append(p)
LABEL_NAMES = {l.lower(): l for l in LABELS}


def find_label(name):
    return LABEL_NAMES.get(name.lower())


def kicker(p):
    """Etichetta principale da mostrare sopra il titolo."""
    pref = [n["label"] for n in CFG["nav"] if "label" in n]
    for l in pref:
        for pl in p["labels"]:
            if pl.lower() == l.lower():
                return pl
    return p["labels"][0] if p["labels"] else "Zulu Nation"


def nav_title_for(label):
    for n in CFG["nav"]:
        if n.get("label", "").lower() == label.lower():
            return n["title"]
    return label


# ---------------------------------------------------------------- componenti

def img_tag(src, alt="", cls="", eager=False):
    if not src:
        return f'<div class="ph {cls}"><span>ZN</span></div>'
    load = 'fetchpriority="high"' if eager else 'loading="lazy"'
    return f'<img class="{cls}" src="{E(U(src))}" alt="{E(alt)}" {load} decoding="async">'


def card(p, size="md", show_excerpt=False, eager=False):
    k = kicker(p)
    ex = f'<p class="dek">{E(p["excerpt"])}</p>' if show_excerpt else ""
    return f'''<article class="card card-{size}">
  <a class="card-img" href="{U(p["path"])}" tabindex="-1" aria-hidden="true">{img_tag(p.get("cover"), p["title"], eager=eager)}</a>
  <div class="card-body">
    <a class="kicker" href="{label_url(k)}">{E(nav_title_for(k))}</a>
    <h3 class="card-title"><a href="{U(p["path"])}">{E(p["title"])}</a></h3>
    {ex}
    <div class="byline">{E(p.get("author") or "Zulu Nation Italia")} · <time datetime="{p["published"][:10]}">{fmt_date(p["published"])}</time></div>
  </div>
</article>'''


def numbered_list(posts, title):
    items = "".join(
        f'<li><span class="num">{i:02d}</span><div><a class="kicker" href="{label_url(kicker(p))}">{E(nav_title_for(kicker(p)))}</a>'
        f'<a class="nl-title" href="{U(p["path"])}">{E(p["title"])}</a></div></li>'
        for i, p in enumerate(posts, 1))
    return f'<aside class="numbered"><h2 class="mini-head">{E(title)}</h2><ol>{items}</ol></aside>'


def section_head(title, href=None, tag="h2"):
    more = f'<a class="more" href="{href}">Vedi tutto <span aria-hidden="true">→</span></a>' if href else ""
    return f'<div class="sec-head"><{tag} class="sec-title">{E(title)}</{tag}>{more}</div>'


def pager(cur, total, base):
    if total <= 1:
        return ""

    def link(n):
        return U(base if n == 1 else f"{base}page/{n}/")
    parts = []
    if cur > 1:
        parts.append(f'<a class="pg prev" href="{link(cur - 1)}">← Più recenti</a>')
    nums = sorted({1, total, cur - 1, cur, cur + 1, cur - 2, cur + 2} & set(range(1, total + 1)))
    last = 0
    for n in nums:
        if n - last > 1:
            parts.append('<span class="pg gap">…</span>')
        parts.append(f'<span class="pg cur">{n}</span>' if n == cur else f'<a class="pg" href="{link(n)}">{n}</a>')
        last = n
    if cur < total:
        parts.append(f'<a class="pg next" href="{link(cur + 1)}">Meno recenti →</a>')
    return f'<nav class="pager" aria-label="Pagine">{"".join(parts)}</nav>'


ICONS = {
    "instagram": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.2c3.2 0 3.6 0 4.8.1 1.2.1 1.8.2 2.2.4.6.2 1 .5 1.4.9.4.4.7.8.9 1.4.2.4.4 1.1.4 2.2.1 1.3.1 1.6.1 4.8s0 3.6-.1 4.8c-.1 1.2-.2 1.8-.4 2.2-.2.6-.5 1-.9 1.4-.4.4-.8.7-1.4.9-.4.2-1.1.4-2.2.4-1.3.1-1.6.1-4.8.1s-3.6 0-4.8-.1c-1.2-.1-1.8-.2-2.2-.4-.6-.2-1-.5-1.4-.9-.4-.4-.7-.8-.9-1.4-.2-.4-.4-1.1-.4-2.2C2.2 15.6 2.2 15.2 2.2 12s0-3.6.1-4.8c.1-1.2.2-1.8.4-2.2.2-.6.5-1 .9-1.4.4-.4.8-.7 1.4-.9.4-.2 1.1-.4 2.2-.4C8.4 2.2 8.8 2.2 12 2.2zm0 4.8a5 5 0 100 10 5 5 0 000-10zm0 8.2a3.2 3.2 0 110-6.4 3.2 3.2 0 010 6.4zm5.2-9.6a1.2 1.2 0 100 2.4 1.2 1.2 0 000-2.4z"/></svg>',
    "youtube": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M23 7.2a3 3 0 00-2.1-2.1C19 4.6 12 4.6 12 4.6s-7 0-8.9.5A3 3 0 001 7.2 31 31 0 00.5 12 31 31 0 001 16.8a3 3 0 002.1 2.1c1.9.5 8.9.5 8.9.5s7 0 8.9-.5a3 3 0 002.1-2.1c.4-1.6.5-4.8.5-4.8s0-3.2-.5-4.8zM9.7 15V9l5.8 3-5.8 3z"/></svg>',
    "facebook": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13.5 22v-8.2h2.8l.4-3.2h-3.2V8.5c0-.9.3-1.6 1.6-1.6h1.7V4.1c-.3 0-1.3-.1-2.5-.1-2.5 0-4.2 1.5-4.2 4.3v2.4H7.3v3.2h2.8V22h3.4z"/></svg>',
    "search": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 3a7 7 0 015.6 11.2l5.1 5.1-1.4 1.4-5.1-5.1A7 7 0 1110 3zm0 2a5 5 0 100 10 5 5 0 000-10z"/></svg>',
}


def social_links(cls="social"):
    out = []
    for k, v in CFG.get("social", {}).items():
        if v:
            out.append(f'<a href="{E(v)}" target="_blank" rel="noopener" aria-label="{k.title()}">{ICONS.get(k, k)}</a>')
    return f'<div class="{cls}">{"".join(out)}</div>'


def nav_html(active=None):
    items = []
    for n in CFG["nav"]:
        if "label" in n:
            l = find_label(n["label"])
            if not l:
                continue
            href = label_url(l)
            on = active and active.lower() == l.lower()
        else:
            href = U(n["page"])
            on = active == n["page"]
        items.append(f'<li><a href="{href}"{" aria-current=page" if on else ""}>{E(n["title"])}</a></li>')
    return "".join(items)


def layout(title, body, *, desc=None, active=None, canonical="/", og_image=None, og_type="website", extra_head=""):
    full_title = f"{title} | {CFG['title']}" if title != CFG["title"] else f"{CFG['title']} — {CFG['tagline']}"
    desc = desc or CFG["description"]
    og = f'<meta property="og:image" content="{E(og_image if og_image.startswith("http") else ORIGIN + U(og_image))}">' if og_image else ""
    year = datetime.now().year
    pages_links = "".join(f'<li><a href="{U(p["path"])}">{E(p["title"])}</a></li>' for p in sorted(PAGES, key=lambda x: x["title"]))
    top_labels = sorted(LABELS.items(), key=lambda kv: -len(kv[1]))[:12]
    label_links = "".join(f'<li><a href="{label_url(l)}">{E(l)}</a></li>' for l, _ in top_labels)
    return f'''<!doctype html>
<html lang="{CFG.get("lang", "it")}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(full_title)}</title>
<meta name="description" content="{E(desc)}">
<link rel="canonical" href="{E(SITE_URL + canonical)}">
<meta property="og:title" content="{E(title)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:type" content="{og_type}">
<meta property="og:site_name" content="{E(CFG["title"])}">
{og}
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#0b0b0b">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{U("/static/style.css")}">
<link rel="alternate" type="application/rss+xml" title="{E(CFG["title"])}" href="{U("/feed.xml")}">
<link rel="icon" href="{U("/static/favicon.svg")}" type="image/svg+xml">
{extra_head}
</head>
<body>
<a class="skip" href="#main">Vai al contenuto</a>
<div class="topbar"><div class="wrap topbar-in">
  <span class="tb-text">Universal Zulu Nation · {E(CFG["tagline"])}</span>
  <div class="tb-right">{social_links()}<a class="tb-search" href="{U("/cerca/")}" aria-label="Cerca">{ICONS["search"]}<span>Cerca</span></a></div>
</div></div>
<header class="masthead">
  <div class="wrap mast-in">
    <a class="logo" href="{U("/")}" aria-label="{E(CFG["title"])} — home"><span class="logo-a">ZULU NATION</span><span class="logo-b">ITALIA</span></a>
    <p class="mast-tag">Peace · Unity · Love &amp; Having Fun</p>
  </div>
  <nav class="mainnav" aria-label="Sezioni"><div class="wrap"><ul>
    <li><a href="{U("/")}"{" aria-current=page" if active == "home" else ""}>Home</a></li>{nav_html(active)}
  </ul></div></nav>
</header>
<main id="main">
{body}
</main>
<footer class="footer">
  <div class="wrap foot-grid">
    <div class="foot-brand">
      <a class="logo logo-inv" href="{U("/")}"><span class="logo-a">ZULU NATION</span><span class="logo-b">ITALIA</span></a>
      <p>{E(CFG["description"])}</p>
      {social_links("social social-lg")}
    </div>
    <div><h3>Esplora</h3><ul>{label_links}</ul></div>
    <div><h3>Zulu Nation</h3><ul>{pages_links}<li><a href="{U("/archivio/")}">Archivio</a></li><li><a href="{U("/feed.xml")}">Feed RSS</a></li></ul></div>
  </div>
  <div class="wrap foot-bottom"><span>© {year} Universal Zulu Nation Italia</span><span>{len(POSTS)} articoli dal {POSTS[-1]["published"][:4] if POSTS else year}</span></div>
</footer>
<script src="{U("/static/site.js")}" defer></script>
</body>
</html>'''


# ---------------------------------------------------------------- scrittura

def write(path, content):
    """path relativo al sito, es. '/2026/10/x.html' o '/label/x/'."""
    p = path.lstrip("/")
    if p == "" or p.endswith("/"):
        p += "index.html"
    f = OUT / p
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


def list_page(title, posts, base, active=None, intro=""):
    pages = max(1, math.ceil(len(posts) / PER_PAGE))
    for n in range(1, pages + 1):
        chunk = posts[(n - 1) * PER_PAGE: n * PER_PAGE]
        lead = ""
        rest = chunk
        if n == 1 and len(chunk) >= 4:
            lead = f'<div class="label-lead">{card(chunk[0], "xl", True, eager=True)}</div>'
            rest = chunk[1:]
        grid = "".join(card(p) for p in rest)
        body = f'''<div class="wrap">
  <header class="page-head"><p class="eyebrow">{E(intro or "Sezione")}</p><h1 class="hash-title">{E(title)}</h1>
  <p class="count">{len(posts)} articoli{f" · pagina {n} di {pages}" if pages > 1 else ""}</p></header>
  {lead}
  <div class="grid grid-4">{grid}</div>
  {pager(n, pages, base)}
</div>'''
        path = base if n == 1 else f"{base}page/{n}/"
        write(path, layout(title if n == 1 else f"{title} — pagina {n}", body, active=active, canonical=path))


HERO_SIBLINGS = ("a", "div", "table", "p", "span", "b", "center")


def strip_cover(html_body, cover):
    """Toglie dal testo la prima immagine se coincide con la copertina mostrata in testa."""
    if not cover:
        return html_body
    soup = BeautifulSoup(html_body, "html.parser")
    img = soup.find("img")
    if not img or img.get("src") != cover:
        return html_body
    # solo se l'immagine è prima di qualunque testo significativo
    before = ""
    for el in img.find_all_previous(string=True):
        before += el
        if len(before.strip()) > 40:
            return html_body
    node = img
    while node.parent and node.parent.name in HERO_SIBLINGS and node.parent.get_text(strip=True) == "" and len(node.parent.find_all("img")) == 1:
        node = node.parent
    node.decompose()
    return str(soup)


def prefix_body(html_body):
    if not BASE:
        return html_body
    return re.sub(r'(src|href)="(/(?!/)[^"]*)"', lambda m: f'{m.group(1)}="{BASE}{m.group(2)}"', html_body)


def share_links(p):
    url = urllib.parse.quote(SITE_URL + p["path"], safe="")
    t = urllib.parse.quote(p["title"], safe="")
    return f'''<div class="share"><span>Condividi</span>
<a href="https://wa.me/?text={t}%20{url}" target="_blank" rel="noopener">WhatsApp</a>
<a href="https://www.facebook.com/sharer/sharer.php?u={url}" target="_blank" rel="noopener">Facebook</a>
<a href="https://x.com/intent/post?url={url}&text={t}" target="_blank" rel="noopener">X</a>
<button type="button" class="copy" data-url="{E(SITE_URL + p["path"])}">Copia link</button></div>'''


def build_post(p, idx):
    k = kicker(p)
    prev_p = POSTS[idx + 1] if idx + 1 < len(POSTS) else None
    next_p = POSTS[idx - 1] if idx > 0 else None
    related, seen = [], {p["path"]}
    for l in p["labels"]:
        for q in LABELS[l]:
            if q["path"] not in seen and len(related) < 4:
                related.append(q)
                seen.add(q["path"])
    for q in POSTS:
        if len(related) >= 4:
            break
        if q["path"] not in seen:
            related.append(q)
            seen.add(q["path"])
    latest = [q for q in POSTS if q["path"] != p["path"]][:6]
    body_html = prefix_body(strip_cover(p["html"], p.get("cover")))
    hero = f'<figure class="post-hero">{img_tag(p["cover"], p["title"], eager=True)}</figure>' if p.get("cover") else ""
    tags = "".join(f'<a href="{label_url(l)}">{E(l)}</a>' for l in p["labels"])
    nav = ""
    if prev_p or next_p:
        nav = '<nav class="prevnext">' + \
            (f'<a class="pn prev" href="{U(prev_p["path"])}"><span>← Precedente</span>{E(prev_p["title"])}</a>' if prev_p else "<span></span>") + \
            (f'<a class="pn next" href="{U(next_p["path"])}"><span>Successivo →</span>{E(next_p["title"])}</a>' if next_p else "<span></span>") + \
            '</nav>'
    ld = json.dumps({
        "@context": "https://schema.org", "@type": "BlogPosting", "headline": p["title"],
        "datePublished": p["published"], "dateModified": p["updated"],
        "author": {"@type": "Person", "name": p.get("author") or CFG["title"]},
        "publisher": {"@type": "Organization", "name": CFG["title"]},
        "image": (p["cover"] if p["cover"].startswith("http") else ORIGIN + U(p["cover"])) if p.get("cover") else None,
        "mainEntityOfPage": SITE_URL + p["path"],
    }, ensure_ascii=False)
    body = f'''<article class="post">
  <div class="wrap post-grid"><header class="post-head">
    <a class="kicker" href="{label_url(k)}">{E(nav_title_for(k))}</a>
    <h1 class="post-title">{E(p["title"])}</h1>
    <div class="byline">Di <strong>{E(p.get("author") or "Zulu Nation Italia")}</strong> · <time datetime="{p["published"][:10]}">{fmt_date(p["published"])}</time></div>
  </header><div class="post-side"></div></div>
  <div class="wrap-hero">{hero}</div>
  <div class="wrap post-grid">
    <div class="post-main">
      <div class="prose">{body_html}</div>
      <div class="tags">{tags}</div>
      {share_links(p)}
      {nav}
    </div>
    <div class="post-side">{numbered_list(latest, "Ultimi articoli")}</div>
  </div>
</article>
<section class="wrap related">{section_head("Leggi anche", label_url(k))}<div class="grid grid-4">{"".join(card(q) for q in related)}</div></section>'''
    write(p["path"], layout(p["title"], body, desc=p["excerpt"], active=k, canonical=p["path"],
                            og_image=p.get("cover"), og_type="article",
                            extra_head=f'<script type="application/ld+json">{ld}</script>'))


def build_page(p):
    body_html = prefix_body(p["html"])
    body = f'''<article class="post static-page">
  <header class="post-head wrap-narrow"><p class="kicker">Zulu Nation Italia</p><h1 class="post-title">{E(p["title"])}</h1></header>
  <div class="wrap-narrow"><div class="prose">{body_html}</div></div>
</article>'''
    write(p["path"], layout(p["title"], body, desc=p["excerpt"], active=p["path"], canonical=p["path"], og_image=p.get("cover")))


def build_home():
    if not POSTS:
        write("/", layout(CFG["title"], '<div class="wrap"><h1 class="hash-title">In arrivo</h1><p>I contenuti vengono importati al primo avvio.</p></div>', active="home"))
        return
    lead, s1, s2 = POSTS[0], POSTS[1:2], POSTS[2:3]
    used = {lead["path"]} | {p["path"] for p in s1 + s2}
    latest = [p for p in POSTS if p["path"] not in used][:6]
    used |= {p["path"] for p in latest}
    tl = find_label(CFG.get("trending_label", "")) or ""
    trending = [p for p in LABELS.get(tl, []) if p["path"] not in used][:6] or POSTS[9:15]
    hero = f'''<section class="hero wrap">
  <div class="hero-lead">{card(lead, "xl", True, eager=True)}</div>
  <div class="hero-side">{"".join(card(p, "lg", True) for p in s1 + s2)}</div>
</section>'''
    latest_block = f'''<section class="wrap split">
  <div>{section_head("Ultime uscite", U("/articoli/"))}<div class="grid grid-3">{"".join(card(p) for p in latest)}</div></div>
  {numbered_list(trending, nav_title_for(tl) if tl else "Da leggere")}
</section>'''
    dark = ""
    dl = find_label(CFG.get("dark_section_label", ""))
    if dl:
        dposts = [p for p in LABELS[dl] if p["path"] not in used][:4]
        used |= {p["path"] for p in dposts}
        dark = f'''<section class="band-dark"><div class="wrap">{section_head(nav_title_for(dl), label_url(dl))}
<div class="grid grid-4">{"".join(card(p) for p in dposts)}</div></div></section>'''
    rows = []
    for name in CFG.get("home_sections", []):
        l = find_label(name)
        if not l:
            continue
        ps = [p for p in LABELS[l] if p["path"] not in used][:4]
        if len(ps) < 2:
            continue
        used |= {p["path"] for p in ps}
        rows.append(f'<section class="wrap row">{section_head(nav_title_for(l), label_url(l))}<div class="grid grid-4">{"".join(card(p) for p in ps)}</div></section>')
        if len(rows) == 2 and CFG.get("cta"):
            c = CFG["cta"]
            rows.append(f'''<section class="band-accent"><div class="wrap cta">
<div><p class="eyebrow">Universal Zulu Nation</p><h2>{E(c["title"])}</h2><p>{E(c["text"])}</p></div>
<a class="btn" href="{U(c["url"])}">{E(c["button"])} →</a></div></section>''')
    labels_cloud = "".join(
        f'<a href="{label_url(l)}">{E(l)} <span>{len(ps)}</span></a>'
        for l, ps in sorted(LABELS.items(), key=lambda kv: -len(kv[1]))[:30])
    body = hero + latest_block + dark + "".join(rows) + \
        f'<section class="wrap row">{section_head("Tutti gli argomenti")}<div class="cloud">{labels_cloud}</div></section>'
    write("/", layout(CFG["title"], body, active="home", canonical="/", og_image=lead.get("cover")))


def build_archives():
    by_year = defaultdict(list)
    by_month = defaultdict(list)
    for p in POSTS:
        y, m = p["published"][:4], p["published"][5:7]
        by_year[y].append(p)
        by_month[(y, m)].append(p)
    for y, ps in by_year.items():
        list_page(f"Archivio {y}", ps, f"/{y}/", intro="Archivio")
    for (y, m), ps in by_month.items():
        list_page(f"{MESI[int(m) - 1].capitalize()} {y}", ps, f"/{y}/{m}/", intro="Archivio")
    rows = []
    for y in sorted(by_year, reverse=True):
        months = "".join(
            f'<a href="{U(f"/{y}/{m}/")}">{MESI[int(m) - 1].capitalize()} <span>{len(by_month[(y, m)])}</span></a>'
            for (yy, m) in sorted(by_month, reverse=True) if yy == y)
        rows.append(f'<div class="arch-year"><h2><a href="{U(f"/{y}/")}">{y}</a> <span>{len(by_year[y])}</span></h2><div class="cloud">{months}</div></div>')
    body = f'<div class="wrap"><header class="page-head"><p class="eyebrow">Dal {min(by_year) if by_year else ""}</p><h1 class="hash-title">Archivio</h1></header>{"".join(rows)}</div>'
    write("/archivio/", layout("Archivio", body, canonical="/archivio/"))


def build_labels():
    for l, ps in LABELS.items():
        base = f"/label/{slugify(l)}/"
        list_page(nav_title_for(l), ps, base, active=l, intro="Sezione")
        # compatibilità con i vecchi link Blogger /search/label/Nome
        if "/" not in l:
            target = U(base)
            redirect = f'<!doctype html><meta charset="utf-8"><title>{E(l)}</title><meta http-equiv="refresh" content="0;url={target}"><link rel="canonical" href="{target}"><a href="{target}">{E(l)}</a>'
            write(f"/search/label/{l}/", redirect)


def build_search():
    idx = [{"t": p["title"], "u": U(p["path"]), "d": p["published"][:10], "l": p["labels"],
            "e": p["excerpt"], "i": U(p["cover"]) if p.get("cover") else ""} for p in POSTS]
    (OUT / "search-index.json").write_text(json.dumps(idx, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    body = f'''<div class="wrap">
<header class="page-head"><p class="eyebrow">{len(POSTS)} articoli</p><h1 class="hash-title">Cerca</h1>
<form class="searchbox" role="search" onsubmit="return false"><input id="q" type="search" placeholder="Cerca articoli, eventi, artisti…" autocomplete="off" autofocus><span id="qcount"></span></form></header>
<div id="results" class="grid grid-4" data-index="{U("/search-index.json")}"></div>
</div>'''
    write("/cerca/", layout("Cerca", body, canonical="/cerca/"))


def build_feeds():
    items = []
    for p in POSTS[:30]:
        body = prefix_body(p["html"])
        body = re.sub(r'(src|href)="/(?!/)', lambda m: f'{m.group(1)}="{ORIGIN}/', body)
        items.append(f'''<item><title>{E(p["title"])}</title><link>{SITE_URL}{p["path"]}</link><guid isPermaLink="true">{SITE_URL}{p["path"]}</guid>
<pubDate>{format_datetime(parse_dt(p["published"]))}</pubDate>{"".join(f"<category>{E(l)}</category>" for l in p["labels"])}
<description>{E(body)}</description></item>''')
    now = format_datetime(datetime.now(timezone.utc))
    rss = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>{E(CFG["title"])}</title><link>{SITE_URL}/</link><description>{E(CFG["description"])}</description>
<language>it</language><lastBuildDate>{now}</lastBuildDate>{"".join(items)}</channel></rss>'''
    (OUT / "feed.xml").write_text(rss, encoding="utf-8")
    urls = [("/", None)] + [(p["path"], p["updated"]) for p in POSTS] + [(p["path"], p["updated"]) for p in PAGES] + \
        [(f"/label/{slugify(l)}/", None) for l in LABELS]
    sm = "".join(f"<url><loc>{SITE_URL}{u}</loc>{f'<lastmod>{d[:10]}</lastmod>' if d else ''}</url>" for u, d in urls)
    (OUT / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>', encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8")


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    shutil.copytree(ROOT / "static", OUT / "static")
    if (ROOT / "assets").exists():
        shutil.copytree(ROOT / "assets", OUT / "assets")
    (OUT / ".nojekyll").write_text("")
    if DOMAIN:
        (OUT / "CNAME").write_text(DOMAIN + "\n")
    build_home()
    for i, p in enumerate(POSTS):
        build_post(p, i)
    for p in PAGES:
        build_page(p)
    list_page("Tutti gli articoli", POSTS, "/articoli/", intro="Archivio completo")
    build_labels()
    build_archives()
    build_search()
    build_feeds()
    nf = '<div class="wrap notfound"><p class="eyebrow">Errore 404</p><h1 class="hash-title">Pagina non trovata</h1><p>La pagina che cerchi non c\'è o è stata spostata.</p><p><a class="btn" href="' + U("/cerca/") + '">Cerca nel sito</a> <a class="btn btn-ghost" href="' + U("/") + '">Torna alla home</a></p></div>'
    write("/404.html", layout("Pagina non trovata", nf))
    print(f"Sito generato: {len(POSTS)} articoli, {len(PAGES)} pagine, {len(LABELS)} etichette → {OUT}")


if __name__ == "__main__":
    main()
