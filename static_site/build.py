"""Build a static, read-only copy of the fish guide into ./docs (for GitHub Pages).
Never copies users.json, secret_key, __pycache__ or user ids."""
import hashlib, json, os, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs"
PASSWORD_SHA256 = os.environ.get("GATE_SHA256", "")
shutil.rmtree(OUT, ignore_errors=True)
(OUT / "data").mkdir(parents=True); (OUT / "img").mkdir()
cat = json.loads((ROOT / "species.json").read_text("utf-8"))
for s in cat["species"]:
    im = s.get("image") or ""
    cand = im.replace("images/", "").replace("/", "-", 1) if im else ""
    if cand and (ROOT / cand).exists():
        shutil.copy(ROOT / cand, OUT / "img" / cand); s["image"] = "img/" + cand
    else:
        s["image"] = ""
(OUT / "data/catalog.json").write_text(json.dumps(cat, ensure_ascii=False), "utf-8")
shutil.copy(ROOT / "sites.json", OUT / "data/sites.json")
obs = json.loads((ROOT / "observations.json").read_text("utf-8"))
SITES = {x["id"]: x for x in json.loads((ROOT / "sites.json").read_text("utf-8"))["sites"]}
for r in obs["sightings"] + obs["dives"]:
    for k in ("userId", "email", "user", "photo"):
        r.pop(k, None)
(OUT / "data/observations.json").write_text(json.dumps(obs, ensure_ascii=False), "utf-8")
html = (Path(__file__).parent / "index.html").read_text("utf-8").replace("__HASH__", PASSWORD_SHA256)
(OUT / "index.html").write_text(html, "utf-8")
(OUT / ".nojekyll").write_text("")
print("built", OUT)
