# Live deployment

The live instance runs as the unprivileged `gptwebdiff` user from `/opt/gpt-webdiff`:

- `app/` — Git checkout plus ignored runtime state and `config.json`
- `venv/` — Python virtual environment
- `gpt-webdiff.timer` — starts one check every 15 minutes
- `gpt-webdiff.service` — one-shot worker; systemd prevents overlapping runs
- Logs — `journalctl -u gpt-webdiff.service`

## Initial installation

Copy `deploy/` to the server and run:

```bash
sudo deploy/install.sh master
sudo install -o gptwebdiff -g gptwebdiff -m 0600 config.json /opt/gpt-webdiff/app/config.json
sudo -u gptwebdiff /opt/gpt-webdiff/venv/bin/python /opt/gpt-webdiff/app/gptcron.py list
sudo systemctl enable --now gpt-webdiff.timer
```

Do not enable the timer until `config.json` contains valid email and AI credentials.

## Updating

Install `deploy/update.sh` as `/usr/local/sbin/update-gpt-webdiff`, then run:

```bash
sudo update-gpt-webdiff
```

This performs a fast-forward-only pull, updates dependencies, and runs the tests. Pass `--run-now` to trigger a monitoring check after a successful update.

## Managing monitored sites

Run commands as the service user so state files keep the correct ownership:

```bash
sudo -u gptwebdiff /opt/gpt-webdiff/venv/bin/python /opt/gpt-webdiff/app/gptcron.py list
sudo -u gptwebdiff /opt/gpt-webdiff/venv/bin/python /opt/gpt-webdiff/app/gptcron.py add "https://example.com" "example" daily
sudo -u gptwebdiff /opt/gpt-webdiff/venv/bin/python /opt/gpt-webdiff/app/gptcron.py test example
```

## Operational checks

```bash
systemctl status gpt-webdiff.timer
systemctl status gpt-webdiff.service
journalctl -u gpt-webdiff.service --since today
systemctl list-timers gpt-webdiff.timer
```

Back up `config.json`, `.gptcron`, `job_metadata.json`, and `data/`. They are runtime state and intentionally not tracked by Git.
