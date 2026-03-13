import re

path = r"migrations\versions\009_partition_trade_history.py"
with open(path, "r", encoding="utf-8") as f:
    c = f.read()

print(c)
