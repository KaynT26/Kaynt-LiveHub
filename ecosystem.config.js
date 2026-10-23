const path = require("path");

module.exports = {
  apps: [
    {
      name: "kaynt-livehub",
      script: "headless.py",
      interpreter: path.join(__dirname, ".venv", "bin", "python"),
      cwd: __dirname,
      autorestart: true,
      watch: false,
      restart_delay: 5000,
      kill_timeout: 10000,
      time: true,
      env: {
        PYTHONUNBUFFERED: "1",
      },
    },
  ],
};
