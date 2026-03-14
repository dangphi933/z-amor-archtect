# MIGRATION RUNBOOK — Strangler Fig Pattern
# Z-ARMOR CLOUD: Monolith → Microservices
# ==========================================
# Version: 2.0  |  Thời gian ước tính: 4–6 tuần
# Rollback target: < 60 giây (đổi ALB target group)

---

## PRE-FLIGHT CHECKLIST

```bash
# 1. Backup DB production
pg_dump $DATABASE_URL > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. Verify Redis reachable
redis-cli -u $REDIS_URL ping

# 3. Tag monolith hiện tại
git tag monolith-stable-$(date +%Y%m%d)

# 4. Kiểm tra envs
diff .env.example .env | grep "^<"   # tất cả keys phải được set
```

---

## PHASE 1 — Shared Infrastructure (Tuần 1)

### 1.1 Cài shared libs
```bash
# Verify shared lib syntax
python3 -m py_compile shared/libs/database/models.py
python3 -m py_compile shared/libs/security/jwt_utils.py
python3 -m py_compile shared/libs/messaging/redis_streams.py
```

### 1.2 Khởi động Redis Streams (song song với monolith)
```bash
docker-compose up -d postgres redis
# Tạo consumer group trước khi service khởi động
redis-cli XGROUP CREATE stream:notifications notification-service $ MKSTREAM
```

### 1.3 Kiểm tra shared DB models khớp với production schema
```bash
python3 -c "
from shared.libs.database.models import engine, Base
# Chỉ inspect — KHÔNG create
from sqlalchemy import inspect
insp = inspect(engine)
tables = insp.get_table_names()
print('Tables found:', tables)
"
```

---

## PHASE 2 — Auth Service (Tuần 1–2)

**Rủi ro:** Thấp — JWT secret chia sẻ giữa monolith và service mới.

### 2.1 Deploy auth-service
```bash
docker-compose up -d auth-service
curl http://localhost:8001/health   # → {"status":"ok"}
```

### 2.2 Smoke test
```bash
# Request OTP
curl -X POST http://localhost:8001/auth/magic-request \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com"}'

# Verify endpoint up
curl http://localhost:8001/auth/me \
  -H "Authorization: Bearer $TEST_TOKEN"
```

### 2.3 ALB Rule — route /auth/* → auth-service
```
# AWS ALB Listener Rule (thêm TRƯỚC rule monolith)
Priority: 10
Condition: path-pattern = /auth/*
Action: Forward → auth-service target group (port 8001)

# Rule monolith giữ nguyên với priority cao hơn (backup)
Priority: 999
Condition: path-pattern = /*
Action: Forward → monolith target group
```

### 2.4 Verify production 24h
```bash
# Check error rate
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApplicationELB \
  --metric-name HTTPCode_Target_5XX_Count \
  --dimensions Name=TargetGroup,Value=auth-service-tg \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 --statistics Sum
```

---

## PHASE 3 — Engine Service (Tuần 2–3)

**Rủi ro:** CAO — EA heartbeat critical path, mất heartbeat → EA dừng giao dịch.

### 3.1 Deploy SONG SONG (shadow mode)
```bash
docker-compose up -d engine-service notification-service

# Kiểm tra handshake (dùng test account)
curl -X POST http://localhost:8003/ea/handshake \
  -H "Content-Type: application/json" \
  -d '{"license_key":"TEST_KEY","mt5_login":"12345678"}'
```

### 3.2 Load test trước khi chuyển traffic
```bash
# 100 heartbeats đồng thời
pip install locust
locust -f tests/locustfile_heartbeat.py \
  --headless -u 100 -r 10 --run-time 60s \
  --host http://localhost:8003
# Target: p99 < 200ms, error rate < 0.1%
```

### 3.3 ALB Rule — route /ea/* → engine-service
```
Priority: 20
Condition: path-pattern = /ea/*
Action: Forward → engine-service target group (port 8003)
```

### 3.4 Monitor Redis stream backlog
```bash
# Notification stream không được lag quá 100 messages
redis-cli XLEN stream:notifications
redis-cli XINFO GROUPS stream:notifications
```

---

## PHASE 4 — Notification Service (Tuần 2)

**Rủi ro:** Thấp — async, không ảnh hưởng EA.

```bash
docker-compose up -d notification-service

# Verify consumer group đang process
redis-cli XINFO CONSUMERS stream:notifications notification-service
# → Kỳ vọng: pending = 0 hoặc rất thấp

# Test manual publish
redis-cli XADD stream:notifications '*' \
  event_type DEFCON3_SILENT \
  payload '{"message":"Test notification from runbook"}'
```

---

## PHASE 5 — Radar + ML + User Service (Tuần 3–4)

Deploy theo thứ tự:
1. **radar-service** (port 8004) — độc lập, đọc DB + Yahoo Finance
2. **user-service** (port 8002) — dependencies: DB + JWT từ auth-service
3. **ml-service** (port 8005) — dependencies: radar-service + DB

```bash
docker-compose up -d radar-service
sleep 10
curl http://localhost:8004/health
curl http://localhost:8004/radar/symbols   # → danh sách symbols

docker-compose up -d user-service
curl http://localhost:8002/health

docker-compose up -d ml-service
curl http://localhost:8005/health
```

### ALB Rules
```
Priority: 30  path=/radar/*  → radar-service:8004
Priority: 40  path=/user/*   → user-service:8002
Priority: 50  path=/billing/* → user-service:8002
Priority: 60  path=/ml/*     → ml-service:8005
```

---

## PHASE 6 — Scheduler Service (Tuần 4)

```bash
docker-compose up -d scheduler-service
# Không có HTTP — kiểm tra logs
docker logs zarmor-scheduler-service -f --tail 50
# Kỳ vọng: "Scheduler started", "Jobs registered: 5"
```

---

## ROLLBACK PROCEDURE

### Rollback toàn bộ (< 60 giây)
```bash
# Xóa tất cả ALB rules priority 10–60
# ALB tự route toàn bộ về monolith (priority 999)
aws elbv2 delete-rule --rule-arn <rule-arn>

# Hoặc trong console: ALB → Listeners → Rules → Delete rules 10-60
```

### Rollback 1 service
```bash
# Ví dụ rollback auth-service
aws elbv2 modify-rule \
  --rule-arn <auth-rule-arn> \
  --actions Type=forward,TargetGroupArn=<monolith-tg-arn>
```

---

## MONITORING CHECKLIST (sau mỗi phase)

```bash
# Error rate per service
for port in 8001 8002 8003 8004 8005; do
  echo "Port $port:"
  curl -s http://localhost:$port/health || echo "DOWN"
done

# Redis stream health
redis-cli XINFO GROUPS stream:notifications

# DB connections
psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity WHERE state='active';"

# Notification lag (phải < 50)
redis-cli XLEN stream:notifications
```

---

## FINAL CUTOVER — Tắt monolith

Chỉ thực hiện sau khi tất cả services stable 72h+:

```bash
# 1. Verify tất cả routes đã chuyển
aws elbv2 describe-rules --listener-arn <listener-arn>

# 2. Scale down monolith (KHÔNG xóa ngay)
aws ecs update-service --service monolith --desired-count 0

# 3. Monitor 24h, nếu ổn
# aws ecs delete-service --service monolith
```
