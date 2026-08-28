module.exports = {
  apps: [
    {
      name: "traffic-tracking",
      cwd: __dirname,
      script: "./run_traffic_tracking.sh",
      interpreter: "/bin/bash",
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      restart_delay: 120000,
      min_uptime: "30s",
      max_restarts: 10,
      kill_timeout: 90000,
      watch: false,
      time: true,
    },
  ],
};
