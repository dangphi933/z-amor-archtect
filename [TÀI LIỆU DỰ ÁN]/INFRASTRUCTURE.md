# 🏛️ Z-ARMOR: CLOUD INFRASTRUCTURE ARCHITECTURE
**Phiên bản:** 7.0 (Dockerized Deployment)


## 1. SƠ ĐỒ TOÀN CẢNH (TOPOLOGY)

Hệ thống Z-ARMOR được thiết kế theo mô hình Micro-monolith, triển khai hoàn toàn bằng **Docker Containers** để đảm bảo khả năng mở rộng không giới hạn (Infinite Scalability) và miễn nhiễm với xung đột Hệ điều hành.

```text
[ 🌐 GLOBAL TRADERS ] ───────(HTTP/REST)───────┐
                                               ▼
┌─────────────────────────────────────────────────────────┐
│              LỚP BẢO VỆ & PHÂN LUỒNG (PROXY)            │
│  - Nginx / Traefik Reverse Proxy                        │
│  - SSL/TLS Encryption (HTTPS)                           │
└──────────────────────────┬──────────────────────────────┘
                           │ (Port 8000)
       ┌───────────────────┴───────────────────┐
       ▼                                       ▼
┌─────────────┐                        ┌───────────────┐
│ DOCKER CORE │                        │ VOLUME LƯU TRỮ│
│ (Container) │======[ Z-ARMOR CLOUD ]=│ - SQLite DB   │
│ - Python 3.11     (FastAPI + Uvicorn)│ - Logs        │
│ - Linux Alpine                       │ (Bọc ngoài VPS│
└─────────────┘           │            └───────────────┘
                          │ (Async Webhooks)
       ┌──────────────────┼───────────────────┐
       ▼                  ▼                   ▼
┌────────────┐     ┌──────────────┐    ┌──────────────┐
│ LARK SUITE │     │ PAYMENT GATE │    │ TELEGRAM API │
│(Automation)│     │(Stripe/Crypto│    │ (Bot Alerts) │
└────────────┘     └──────────────┘    └──────────────┘