"""Builds the manual: manual-src.html + shots/*.png -> manual.html (one self-contained page) and the PDF.
   python3 build.py [out_dir]     (the PDF needs Playwright + Chromium)
A figure is {{img:name}}: shots/name.png. If the picture isn't there yet, the figure is left out."""
import base64, os, re, sys
here = os.path.dirname(os.path.abspath(__file__))
out = sys.argv[1] if len(sys.argv) > 1 else here
src = open(os.path.join(here, "manual-src.html"), encoding="utf-8").read()

def fig(m):
    name, cap = m.group(1), m.group(2)
    p = os.path.join(here, "shots", name + ".png")
    if not os.path.exists(p):
        return ""
    b = base64.b64encode(open(p, "rb").read()).decode()
    return ('<figure class="shot"><img src="data:image/png;base64,%s" alt="%s" width="320" height="240">'
            '<figcaption>%s</figcaption></figure>' % (b, cap, cap))
html = re.sub(r"\{\{img:([a-z0-9-]+)\|([^}]*)\}\}", fig, src)
os.makedirs(out, exist_ok=True)
open(os.path.join(out, "manual.html"), "w", encoding="utf-8").write(html)
print("manual.html", len(html) // 1024, "KB")
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto("file://" + os.path.join(out, "manual.html"))
        pg.emulate_media(media="print")
        pg.wait_for_timeout(500)
        pg.pdf(path=os.path.join(out, "Console-on-MPC-Sample-Manual.pdf"), format="Letter", print_background=True,
               margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
               display_header_footer=True, header_template="<span></span>",
               footer_template='<div style="font:9px sans-serif;color:#777;width:100%;padding:0 14mm;display:flex;justify-content:space-between"><span>Console on the Akai MPC Sample</span><span>page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>')
        b.close()
    print("pdf done")
except Exception as e:
    print("no pdf:", e)
