"""One-time helper: sign in to the (throwaway) Gmail account and print the GMAIL_* values for backend/.env.

Usage: python scripts/get_gmail_token.py <client_id> <client_secret>
Needs a Google Cloud OAuth client of type "Desktop app".
"""
import http.server
import sys
import threading
import urllib.parse
import webbrowser

import httpx

SCOPES = "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/gmail.settings.basic"
PORT = 8765
REDIRECT = f"http://127.0.0.1:{PORT}"


def main(client_id: str, client_secret: str) -> None:
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            result.update(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab and return to the terminal.")
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, *a):
            pass

    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent"})
    print("Opening your browser. Sign in with the THROWAWAY Gmail account.\nIf nothing opens, visit:\n" + url)
    webbrowser.open(url)
    http.server.HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

    if "code" not in result:
        sys.exit(f"Authorization failed: {result.get('error', 'no code returned')}")
    r = httpx.post("https://oauth2.googleapis.com/token", data={
        "code": result["code"][0], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": REDIRECT, "grant_type": "authorization_code"})
    body = r.json()
    if "refresh_token" not in body:
        sys.exit(f"No refresh token returned: {body}")
    print(f"\nAdd to backend/.env:\n\nGMAIL_CLIENT_ID={client_id}\nGMAIL_CLIENT_SECRET={client_secret}\n"
          f"GMAIL_REFRESH_TOKEN={body['refresh_token']}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
