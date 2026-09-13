from pathlib import Path

root = Path(__file__).resolve().parents[1]
js = (root / "static" / "final-review.js").read_text(encoding="utf-8")
sw = (root / "static" / "sw.js").read_text(encoding="utf-8")
index = (root / "static" / "index.html").read_text(encoding="utf-8")

required = [
    "const VIEW_KEY = 'shortlistai-view-mode'",
    "id='frViewModeControl'",
    'data-view="mobile"',
    'data-view="desktop"',
    "force-mobile",
    "force-desktop",
    "Mobile View enabled",
    "Desktop View enabled",
]

for marker in required:
    assert marker in js, f"missing view-mode marker: {marker}"

assert 'id="viewModeToggle"' in index, "legacy mount point missing"
assert "legacy.hidden=true" in js, "legacy one-way toggle should be hidden by v2 controller"
assert "shortlistai-v6" in sw, "installed app cache version was not bumped"

print("view mode v2 regression passed")
