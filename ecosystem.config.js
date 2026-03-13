// ecosystem.config.js — PM2 config for Z-Armor Cloud (Windows)
module.exports = {
  apps: [
    {
      name: "z-armor-core",
      script: "ZARMOR_START.py",
      interpreter: "python",

      // Windows: force UTF-8 via env
      env: {
        PYTHONIOENCODING: "utf-8",
        PYTHONUTF8: "1",
        PYTHONLEGACYWINDOWSSTDIO: "0",
      },

      // Restart policy
      autorestart: true,
      watch: false,
      max_restarts: 5,          // Giới hạn 5 lần restart — tránh crash loop
      min_uptime: "10s",        // Nếu chết trước 10s → tính là unstable
      restart_delay: 3000,      // Đợi 3s trước khi restart

      // Log
      out_file: "logs/z-armor-out.log",
      error_file: "logs/z-armor-error.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      merge_logs: true,
    },
  ],
};
