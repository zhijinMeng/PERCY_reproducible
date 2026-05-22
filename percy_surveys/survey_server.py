#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local PERCY questionnaire server (pre + post session)."""
from __future__ import print_function

import argparse
import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from profile_builder import load_schema, save_post_session, save_pre_session

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT, "static")


def session_dir(data_root, session_id):
    return os.path.join(data_root, str(session_id))


class SurveyHandler(BaseHTTPRequestHandler):
    server_version = "PercySurvey/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[survey] %s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        session = (qs.get("session") or [""])[0]

        if path in ("/", "/index.html"):
            html = (
                "<html><body><h1>PERCY Local Surveys</h1>"
                "<p>Session: <strong>%s</strong></p>"
                "<ul>"
                '<li><a href="/pre?session=%s">Pre-session profile (before dialogue)</a></li>'
                '<li><a href="/post?session=%s">Post-session feedback (after dialogue)</a></li>'
                "</ul></body></html>"
            ) % (session or "(set ?session=ID)", session, session)
            self._send_bytes(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path == "/pre":
            self._serve_form("pre_session", session)
            return
        if path == "/post":
            self._serve_form("post_session", session)
            return
        if path.startswith("/static/"):
            rel = path[len("/static/") :]
            fpath = os.path.join(STATIC_DIR, rel)
            if os.path.isfile(fpath):
                ctype = "text/javascript" if rel.endswith(".js") else "text/css"
                if rel.endswith(".html"):
                    ctype = "text/html; charset=utf-8"
                with open(fpath, "rb") as f:
                    self._send_bytes(200, f.read(), ctype)
                return

        if path == "/api/schema/pre":
            self._send_json(200, load_schema("pre_session"))
            return
        if path == "/api/schema/post":
            self._send_json(200, load_schema("post_session"))
            return

        self._send_json(404, {"error": "not found"})

    def _serve_form(self, survey_id, session):
        form_path = os.path.join(STATIC_DIR, "form.html")
        with open(form_path, "r", encoding="utf-8") as f:
            html = f.read()
        html = html.replace("{{SURVEY_ID}}", survey_id)
        html = html.replace("{{SESSION_ID}}", session or "")
        self._send_bytes(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            payload = self._read_json_body()
        except Exception as e:
            self._send_json(400, {"error": "invalid json: %s" % e})
            return

        session = str(payload.get("session_id") or "").strip()
        answers = payload.get("answers") or {}
        if not session:
            self._send_json(400, {"error": "session_id required"})
            return

        out_dir = session_dir(self.server.data_root, session)

        if path == "/api/submit/pre":
            schema = load_schema("pre_session")
            pre_path, profile_path, pairs = save_pre_session(
                out_dir, schema, answers, session_id=session
            )
            self._send_json(
                200,
                {
                    "ok": True,
                    "pre_survey": pre_path,
                    "profile_json": profile_path,
                    "profile_topics": len(pairs),
                },
            )
            return

        if path == "/api/submit/post":
            schema = load_schema("post_session")
            post_path = save_post_session(out_dir, schema, answers, session_id=session)
            self._send_json(200, {"ok": True, "post_survey": post_path})
            return

        self._send_json(404, {"error": "not found"})


def main():
    parser = argparse.ArgumentParser(description="PERCY local survey server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--data-root",
        default=os.environ.get("PERCY_DATA_DIR", os.path.join(ROOT, "..", "percy_data")),
        help="Root directory for percy_data sessions",
    )
    parser.add_argument(
        "--mode",
        choices=("pre", "post", "both"),
        default="both",
        help="Which form to open in browser",
    )
    parser.add_argument("--session", required=True, help="Session id, e.g. 27")
    parser.add_argument("--no-open", action="store_true", help="Do not open browser")
    args = parser.parse_args()

    data_root = os.path.abspath(args.data_root)
    os.makedirs(data_root, exist_ok=True)

    httpd = HTTPServer((args.host, args.port), SurveyHandler)
    httpd.data_root = data_root

    if args.mode == "pre":
        url = "http://%s:%d/pre?session=%s" % (args.host, args.port, args.session)
    elif args.mode == "post":
        url = "http://%s:%d/post?session=%s" % (args.host, args.port, args.session)
    else:
        url = "http://%s:%d/?session=%s" % (args.host, args.port, args.session)

    print("PERCY survey server")
    print("  data root: %s" % data_root)
    print("  session:   %s" % args.session)
    print("  open:      %s" % url)
    print("  Ctrl+C to stop")

    if not args.no_open:
        webbrowser.open(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
