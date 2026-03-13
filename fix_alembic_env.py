import sys, os

path = r"migrations\env.py"
with open(path, "r", encoding="utf-8") as f:
    c = f.read()

if "sys.path.insert" not in c:
    c = 'import sys, os\nsys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n' + c
    print("Fixed: sys.path added")

c = c.replace(
    'config.set_main_option("sqlalchemy.url", SYNC_URL)',
    'config.set_main_option("sqlalchemy.url", SYNC_URL.replace("%", "%%"))'
)
print("Fixed: % escaped in URL")

with open(path, "w", encoding="utf-8") as f:
    f.write(c)

print("Done - run: alembic check")
