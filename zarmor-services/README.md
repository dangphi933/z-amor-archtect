# Z-ARMOR CLOUD — Microservices (Part 2)

Strangler-Fig migration từ monolith (`Z-ARMOR-CLOUD/main.py`) sang 7 independent services.

## Architecture

```
                    ┌─────────────┐
                    │  CloudFront │
                    │    + WAF    │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │     ALB     │
                    └──┬──┬──┬───┘
           ┌───────────┘  │  └───────────┐
    ┌──────▼─────┐  ┌─────▼──────┐  ┌───▼──────────┐
    │auth-service│  │engine-serv │  │  radar-serv   │
    │  /auth/*   │  │   /ea/*    │  │  /radar/*     │
    └────────────┘  └─────┬──────┘  └───────────────┘
                          │ Redis Stream
              ┌───────────▼───────────┐
              │  notification-service  │  (consumer only)
              └────────────────────────┘
    ┌────────────┐  ┌────────────┐  ┌────────────┐
    │user-service│  │ ml-service │  │  scheduler │
    │/user /bill │  │  /ml/*     │  │  (no HTTP) │
    └────────────┘  └────────────┘  └────────────┘
```

## Services

| Service | Port | Source (monolith) | Tuần |
|---------|------|-------------------|------|
| auth-service | 8001 | `auth.py`, `api/auth_router.py` | 1–2 |
| engine-service | 8003 | `api/ea_router.py` | 4–5 |
| notification-service | — | `telegram_engine.py`, `email_service.py` | 3 |
| user-service | 8002 | `api/identity_router.py`, `api/billing_router.py` | 5 |
| radar-service | 8004 | `radar/` | 6 |
| ml-service | 8005 | `ml/` | 6 |
| scheduler-service | — | `remarketing_scheduler.py`, `radar/scheduler.py`, `performance/scheduler.py` | 7 |

## Shared Libraries

```
shared/libs/
├── database/     — SQLAlchemy models + Base (copy từ database.py)
├── security/     — JWT verify, require_jwt, decode_jwt_unsafe
├── messaging/    — Redis stream publish/consume helpers
└── schemas/      — Shared Pydantic schemas
```

## Development

```bash
# Chạy 1 service
cd services/auth-service
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001

# Chạy toàn bộ stack
docker-compose up --build
```

## Migration Strategy

Strangler-Fig: monolith vẫn chạy song song trong suốt quá trình.
Nginx/ALB route từng path prefix sang service mới khi service đó ready.
Rollback: đổi ALB target group về monolith trong < 60 giây.
