
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))from isoforge.config import load
from isoforge.backends.drawthings import DrawThings
from isoforge.textures import generate_texture
c = load(); b = DrawThings(c.drawthings_url)
for subj, n in [("cracked weathered asphalt road with faded patches", "tex_asphalt_cracked"),
                ("dilapidated stained concrete wall surface with chipped paint and grime", "tex_concrete_worn")]:
    r = generate_texture(c, b, subj, n)
    print(n, r["tileable"], r["edge_diff_before"], "->", r["edge_diff_after"], flush=True)
