#!/usr/bin/env python3
"""
Dev-only smoke-test fixture -- NOT part of the OTel pipeline.

Serves a tiny synthetic /metrics endpoint on :9464 shaped like Claude Code's
real OTel Prometheus exporter output, so the docker-compose stack (Prometheus
scrape config + Grafana dashboard queries) can be verified end-to-end BEFORE
the real CLAUDE_CODE_ENABLE_TELEMETRY / OTEL_METRICS_EXPORTER env vars are set
on this machine.

Usage:
    python3 fake_claude_metrics.py
    # then in another terminal: curl localhost:9464/metrics

Values increase a little on every scrape so rate()/increase() panels have
something non-zero to show. Ctrl-C to stop. Every series is tagged
source="live" to match how the real exporter's data will be labeled by
Prometheus's scrape config (see ../prometheus/prometheus.yml).
"""

import http.server
import itertools

_counter = itertools.count()


def render() -> str:
    n = next(_counter)
    input_tok = 1000 + n * 137
    output_tok = 400 + n * 53
    cache_read = 5000 + n * 900
    cache_creation = 200 + n * 20
    sessions = 1 + n // 5
    prs = 1 + n // 20
    cost = round(0.01 * (n + 1), 4)

    lines = [
        "# TYPE claude_code_token_usage_total counter",
        f'claude_code_token_usage_total{{type="input",model="claude-sonnet-5",agent_name="custom",source="live"}} {input_tok}',
        f'claude_code_token_usage_total{{type="output",model="claude-sonnet-5",agent_name="custom",source="live"}} {output_tok}',
        f'claude_code_token_usage_total{{type="cacheRead",model="claude-sonnet-5",agent_name="custom",source="live"}} {cache_read}',
        f'claude_code_token_usage_total{{type="cacheCreation",model="claude-sonnet-5",agent_name="custom",source="live"}} {cache_creation}',
        "# TYPE claude_code_cost_usage_total counter",
        f'claude_code_cost_usage_total{{model="claude-sonnet-5",agent_name="custom",source="live"}} {cost}',
        "# TYPE claude_code_session_count_total counter",
        f'claude_code_session_count_total{{source="live"}} {sessions}',
        "# TYPE claude_code_pull_request_count_total counter",
        f'claude_code_pull_request_count_total{{source="live"}} {prs}',
        "# TYPE claude_code_commit_count_total counter",
        f'claude_code_commit_count_total{{source="live"}} {n // 3}',
        "# TYPE claude_code_lines_of_code_count_total counter",
        f'claude_code_lines_of_code_count_total{{type="added",model="claude-sonnet-5",source="live"}} {n * 12}',
        f'claude_code_lines_of_code_count_total{{type="removed",model="claude-sonnet-5",source="live"}} {n * 4}',
        "# TYPE claude_code_active_time_total counter",
        f'claude_code_active_time_total{{type="user",source="live"}} {n * 8}',
        f'claude_code_active_time_total{{type="cli",source="live"}} {n * 15}',
    ]
    return "\n".join(lines) + "\n"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        body = render().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *a):
        pass  # keep stdout quiet


if __name__ == "__main__":
    server = http.server.HTTPServer(("127.0.0.1", 9464), Handler)
    print(
        "Fake Claude Code /metrics endpoint on http://127.0.0.1:9464/metrics (Ctrl-C to stop)"
    )
    server.serve_forever()
