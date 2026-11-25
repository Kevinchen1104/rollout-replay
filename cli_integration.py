"""Exercise @current with a real Flagsmith CLI and a synthetic loopback API."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import contextmanager
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit


@contextmanager
def local_environment(binary, project):
    examples = project / "examples"
    before = json.loads((examples / "before.json").read_bytes())
    key = before["api_key"]
    environment = {"id": 42, "name": "Demo", "api_key": key, "project": 1}
    requests = []

    class FixtureAPI(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            requests.append(path)
            if path == f"/api/v1/environments/{key}/document/":
                body = before
            elif path == f"/api/v1/environments/{key}/":
                body = environment
            elif path == "/api/v1/environments/":
                body = {"count": 1, "next": None, "previous": None, "results": [environment]}
            else:
                self.send_error(404)
                return
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), FixtureAPI) as httpd, tempfile.TemporaryDirectory() as tmp:
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        try:
            host, port = httpd.server_address
            (Path(tmp) / "flagsmith.json").write_text("{}")
            # The CLI's per-host variable names normalise punctuation to underscores.
            suffix = f"{host}_{port}".replace(".", "_")
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith("FLAGSMITH_")}
            env.update({
                "PATH": str(binary.parent) + os.pathsep + env.get("PATH", ""),
                "FLAGSMITH_API_URL": f"http://{host}:{port}",
                "FLAGSMITH_SDK_API_URL": f"http://{host}:{port}",
                "FLAGSMITH_ENVIRONMENT": key, "FLAGSMITH_PROJECT": "1",
                "FLAGSMITH_API_KEY_" + suffix: "fixture.local-only-test",
                "FLAGSMITH_CONFIG_PATH": str(Path(tmp) / "flagsmith.json"),
                "XDG_CONFIG_HOME": tmp, "XDG_CACHE_HOME": tmp, "XDG_DATA_HOME": tmp,
                "APPDATA": tmp, "LOCALAPPDATA": tmp, "NO_PROXY": "127.0.0.1",
            })
            yield env, Path(tmp), requests
        finally:
            httpd.shutdown()
            worker.join()


def run_check(binary, project):
    examples = project / "examples"
    before = json.loads((examples / "before.json").read_bytes())
    with local_environment(binary, project) as (env, tmp, requests):
        cli = [str(binary), "environment", "document", "--no-input"]
        capture = subprocess.run(cli, cwd=tmp, env=env, capture_output=True, text=True, timeout=12)
        if capture.returncode or json.loads(capture.stdout) != before:
            raise RuntimeError(f"CLI document capture failed: {capture.stderr}. Requests: {requests}")
        for candidate, expected in (("before.json", 0), ("after.json", 3)):
            command = [sys.executable, str(project / "replay.py"), "@current", str(examples / candidate),
                       str(examples / "cohort.json"), "--flag", "expedited_checkout",
                       "--max-changed-percent", "10", "--json"]
            proc = subprocess.run(command, cwd=tmp, env=env, capture_output=True, text=True, timeout=20)
            assert proc.returncode == expected, (proc.returncode, proc.stderr)
            report = json.loads(proc.stdout)
            assert report["changed"] == (100 if expected else 0)
            assert report["enabled_before"] == report["enabled_after"] == 100
            print(f"{candidate}: {report['changed']} changed, exit {proc.returncode}.")
        assert sum(path.endswith("/document/") for path in requests) == 3, requests
        print(f"Verified {len(requests)} local GET requests, including 3 document reads.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("flagsmith", type=Path, help="Path to the official v2 Flagsmith CLI executable")
    run_check(parser.parse_args().flagsmith.resolve(), Path(__file__).resolve().parent)
