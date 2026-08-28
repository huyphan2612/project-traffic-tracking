from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "run_traffic_tracking.sh"
ECOSYSTEM = ROOT / "ecosystem.config.cjs"


def test_runner_is_executable_and_uses_safe_docker_options() -> None:
    content = RUNNER.read_text()

    assert RUNNER.stat().st_mode & stat.S_IXUSR
    assert "set -Eeuo pipefail" in content
    assert 'exec docker run' in content
    assert "--rm" in content
    assert "--init" in content
    assert "--stop-timeout 60" in content
    assert '--env-file "${ENV_FILE}"' in content
    assert "host.docker.internal:host-gateway" in content
    assert '"${IMAGE}" run' in content
    assert " main.py migrate" not in content
    assert " -d" not in content


def test_ecosystem_runs_one_instance_with_two_minute_delay() -> None:
    content = ECOSYSTEM.read_text()

    assert 'name: "traffic-tracking"' in content
    assert 'script: "./run_traffic_tracking.sh"' in content
    assert 'interpreter: "/bin/bash"' in content
    assert "instances: 1" in content
    assert 'exec_mode: "fork"' in content
    assert "autorestart: true" in content
    assert "restart_delay: 120000" in content
    assert 'min_uptime: "30s"' in content
    assert "max_restarts: 10" in content
    assert "kill_timeout: 90000" in content
    assert "cron_restart" not in content


def test_runner_passes_absolute_paths_and_runtime_options(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "docker-calls.txt"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$DOCKER_CALLS_FILE\"\n"
    )
    fake_docker.chmod(0o755)
    env_file = tmp_path / "runtime.env"
    env_file.write_text("SAVE_IMAGES=false\n")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "DOCKER_CALLS_FILE": str(calls),
            "TRAFFIC_TRACKING_ENV_FILE": str(env_file),
            "TRAFFIC_TRACKING_IMAGE": "traffic-tracking:test",
        }
    )
    subprocess.run(["bash", str(RUNNER)], cwd=tmp_path, env=env, check=True)

    invocations = calls.read_text().splitlines()
    assert invocations[0] == "image inspect traffic-tracking:test"
    run = invocations[1]
    assert f"--env-file {env_file}" in run
    assert f"src={ROOT / 'photo'},dst=/app/photo" in run
    assert "--user " in run
    assert run.endswith("traffic-tracking:test run")


def test_ecosystem_can_be_loaded_by_node_when_available() -> None:
    node = shutil.which("node")
    if node is None:
        return
    subprocess.run(
        [node, "-e", "const c=require('./ecosystem.config.cjs'); if(c.apps[0].restart_delay!==120000) process.exit(1)"],
        cwd=ROOT,
        check=True,
    )
