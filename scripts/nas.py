"""Stdlib client for documented Synology File Station JSON APIs (Python 3.10+)."""
import argparse
import json
import os
from pathlib import Path
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

VERSIONS = {"Info": 2, "List": 2, "Search": 2, "CreateFolder": 2,
            "Rename": 2, "CopyMove": 3, "Delete": 2}
READS = {("Info", "get"), ("List", "list_share"), ("List", "list"),
         ("List", "getinfo"), ("Search", "status"), ("Search", "list"),
         ("CopyMove", "status"), ("Delete", "status")}
METHODS = {"Info": {"get"}, "List": {"list_share", "list", "getinfo"},
           "Search": {"start", "status", "list", "stop", "clean"},
           "CreateFolder": {"create"}, "Rename": {"rename"},
           "CopyMove": {"start", "status", "stop"},
           "Delete": {"start", "status", "stop"}}


class Client:
    def __init__(self, url, insecure=False):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Invalid DSM origin")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("Origin must not contain credentials or path")
        self.url = url.rstrip("/")
        self.https = parsed.scheme == "https"
        context = ssl.create_default_context(cafile=os.getenv("SYNOLOGY_CA_FILE") or None)
        if insecure:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        self.opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPSHandler(context=context))
        self.sid = None
        self.info = {}

    def request(self, path, params):
        if path.startswith("/") or any(c in path for c in ("..", ":", "?", "#", "\\")):
            raise ValueError("Invalid CGI path")
        encoded = {k: json.dumps(v, ensure_ascii=False, separators=(",", ":"))
                   if isinstance(v, (dict, list, bool)) else str(v)
                   for k, v in params.items()}
        req = urllib.request.Request(self.url + "/webapi/" + path,
                                     data=urllib.parse.urlencode(encoded).encode(), method="POST")
        with self.opener.open(req, timeout=30) as response:
            result = json.load(response)
        if not result.get("success"):
            code = result.get("error", {}).get("code", "unknown")
            raise RuntimeError(f"DSM API failed: code={code}")
        return result.get("data", {})

    def discover(self):
        names = ["SYNO.API.Auth"] + ["SYNO.FileStation." + k for k in VERSIONS]
        self.info = self.request("query.cgi", dict(api="SYNO.API.Info", version=1,
                                                  method="query", query=",".join(names)))
        return self.info

    def invoke(self, api, method, params, cap):
        spec = self.info.get(api)
        if not spec:
            raise ValueError("API not advertised")
        version = min(spec["maxVersion"], cap)
        if version < spec["minVersion"]:
            raise ValueError("No implemented compatible API version")
        fields = dict(params, api=api, version=version, method=method)
        if self.sid:
            fields["_sid"] = self.sid
        return self.request(spec["path"], fields)

    def login(self):
        if not self.https:
            raise ValueError("Refusing credentials over HTTP; use HTTPS")
        user, password = os.getenv("SYNOLOGY_USER"), os.getenv("SYNOLOGY_PASSWORD")
        if not user or not password:
            raise ValueError("Set SYNOLOGY_USER and SYNOLOGY_PASSWORD")
        params = dict(account=user, passwd=password, session="FileStation", format="sid")
        if os.getenv("SYNOLOGY_OTP"):
            params["otp_code"] = os.environ["SYNOLOGY_OTP"]
        self.sid = self.invoke("SYNO.API.Auth", "login", params, 6)["sid"]

    def logout(self):
        if self.sid:
            try:
                self.invoke("SYNO.API.Auth", "logout", {"session": "FileStation"}, 6)
            except Exception:
                print("Warning: logout not confirmed; session may persist", file=sys.stderr)
            finally:
                self.sid = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("SYNOLOGY_URL"))
    parser.add_argument("--insecure", action="store_true", help="Temporary TLS diagnostic only")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("discover")
    for name in ("shares", "list"):
        p = sub.add_parser(name)
        if name == "list":
            p.add_argument("path")
        p.add_argument("--limit", type=int, default=100)
        p.add_argument("--offset", type=int, default=0)
    p = sub.add_parser("call")
    p.add_argument("api")
    p.add_argument("method")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--params", default="{}")
    group.add_argument("--params-file")
    p.add_argument("--write", action="store_true", help="Enable an already authorized mutation")
    args = parser.parse_args()
    if not args.url:
        parser.error("Set SYNOLOGY_URL or supply --url")
    if args.command == "call":
        suffix = args.api.removeprefix("SYNO.FileStation.")
        if args.api != "SYNO.FileStation." + suffix or args.method not in METHODS.get(suffix, set()):
            parser.error("Unsupported File Station API/method")
        if (suffix, args.method) not in READS and not args.write:
            parser.error("State-changing method requires --write and task authorization")
        raw = Path(args.params_file).read_text(encoding="utf-8-sig") if args.params_file else args.params
        params = json.loads(raw)
        reserved = {"api", "version", "method", "_sid", "sid", "passwd", "password", "account"}
        if not isinstance(params, dict) or any(k.lower() in reserved for k in params):
            parser.error("Params must be an object without reserved/auth fields")
    if args.command in {"shares", "list"} and (args.limit < 1 or args.offset < 0):
        parser.error("limit must be positive and offset nonnegative")
    client = Client(args.url, args.insecure)
    try:
        info = client.discover()
        if args.command == "discover":
            return info
        client.login()
        if args.command == "call":
            return client.invoke(args.api, args.method, params, VERSIONS[suffix])
        params = {"offset": args.offset, "limit": args.limit}
        if args.command == "list":
            params["folder_path"] = args.path
        return client.invoke("SYNO.FileStation.List", "list" if args.command == "list" else "list_share", params, 2)
    finally:
        client.logout()


if __name__ == "__main__":
    try:
        print(json.dumps({"success": True, "data": main()}, ensure_ascii=False, indent=2))
    except (urllib.error.URLError, TimeoutError):
        print(json.dumps({"success": False, "error": "Connection/TLS failed; verify LAN reachability and CA trust"}), file=sys.stderr)
        sys.exit(1)
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else "Invalid configuration, parameters, or response; consult SKILL.md"
        print(json.dumps({"success": False, "error": message}), file=sys.stderr)
        sys.exit(1)
