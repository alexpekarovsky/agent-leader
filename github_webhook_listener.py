import hashlib
import hmac
import http.server
import json
import logging
import os
import sys
import requests

logger = logging.getLogger(__name__)

# Configuration
PORT = int(os.getenv("GITHUB_WEBHOOK_PORT", 8000))
MCP_PORT = int(os.getenv("MCP_PORT", 9000)) # Default to 9000 if not set
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", f"http://localhost:{MCP_PORT}/mcp") 
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")

class GitHubWebhookHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        # Read the request body
        content_length = int(self.headers['Content-Length'])
        payload = self.rfile.read(content_length)

        # Verify the webhook signature (fail-closed)
        if not GITHUB_WEBHOOK_SECRET:
            logger.warning("GITHUB_WEBHOOK_SECRET is not set -- rejecting all webhook requests (fail-closed)")
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Webhook secret not configured")
            return
        expected_signature = self.headers.get("X-Hub-Signature-256")
        if not self._verify_signature(payload, expected_signature):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"Invalid signature")
            return

        try:
            payload_json = json.loads(payload.decode('utf-8'))
            
            # Make JSON-RPC call to MCP server
            rpc_payload = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "orchestrator_process_github_webhook",
                    "arguments": {
                        "payload": payload_json,
                        "source": "github-webhook-listener",
                        "headers": dict(self.headers)
                    }
                },
                "id": 1 # Unique ID for the request
            }
            
            headers = {'Content-Type': 'application/json'}
            response = requests.post(MCP_SERVER_URL, json=rpc_payload, headers=headers)
            response.raise_for_status() # Raise an exception for HTTP errors
            
            mcp_response = response.json()
            if mcp_response.get("error"):
                print(f"Error from MCP server: {mcp_response['error']}", file=sys.stderr)
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Error processing webhook"}).encode('utf-8'))
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "mcp_response": mcp_response}).encode('utf-8'))
                
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid JSON payload")
        except requests.exceptions.RequestException as e:
            print(f"Error communicating with MCP server: {e}", file=sys.stderr)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": f"MCP server communication error: {e}"}).encode('utf-8'))
        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": f"Unexpected error: {e}"}).encode('utf-8'))

    def do_GET(self):
        """Handle GET requests for readiness probes."""
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"GitHub Webhook Listener is running and ready.")

    def _verify_signature(self, payload, expected_signature):
        if not expected_signature:
            return False
        mac = hmac.new(GITHUB_WEBHOOK_SECRET.encode('utf-8'), payload, hashlib.sha256)
        return hmac.compare_digest(f"sha256={mac.hexdigest()}", expected_signature)


if __name__ == "__main__":
    server_address = ('', PORT)
    httpd = http.server.HTTPServer(server_address, GitHubWebhookHandler)
    print(f"Starting GitHub webhook listener on port {PORT}...")
    print(f"Forwarding webhooks to MCP server at {MCP_SERVER_URL}")
    httpd.serve_forever()
