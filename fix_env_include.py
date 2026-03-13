import sys, os

path = r"migrations\env.py"
with open(path, "r", encoding="utf-8") as f:
    c = f.read()

# Danh sách tables mà SQLAlchemy models quản lý
INCLUDE_TABLES_CODE = '''
# Chỉ compare các tables do models quản lý, bỏ qua tables thừa trong DB
MANAGED_TABLES = {
    "license_keys", "license_activations", "trading_accounts",
    "ea_sessions", "session_history", "trade_history",
    "system_states", "risk_hard_limits", "risk_tacticals",
    "neural_profiles", "telegram_configs", "webhook_retry_queue",
    "config_audit_trail", "audit_logs", "admin_users",
}

def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table":
        return name in MANAGED_TABLES
    return True

'''

# Chèn vào trước def run_migrations_offline
if "include_object" not in c:
    c = c.replace("def run_migrations_offline", INCLUDE_TABLES_CODE + "def run_migrations_offline")
    print("Fixed: include_object added")
else:
    print("Already has include_object - skipping")

# Thêm include_object vào context.configure calls
if "include_object=include_object" not in c:
    c = c.replace(
        "context.configure(\n            url=url,",
        "context.configure(\n            url=url,\n            include_object=include_object,"
    )
    c = c.replace(
        "context.configure(\n            connection=connection,",
        "context.configure(\n            connection=connection,\n            include_object=include_object,"
    )
    print("Fixed: include_object added to context.configure")

with open(path, "w", encoding="utf-8") as f:
    f.write(c)

print("Done")
