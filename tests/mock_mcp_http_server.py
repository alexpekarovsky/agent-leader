import http.server
import json
import os
import sys
import threading
import time
from urllib.parse import urlparse

# This is a minimal HTTP server that acts as an MCP server for testing purposes.
# It receives JSON-RPC requests via HTTP POST, and responds as if it were orchestrator_mcp_server.py.
# This allows the github_webhook_listener.py to communicate with it over HTTP as expected.

# Mock ORCH to avoid loading the full orchestrator engine
class MockOrchestratorEngine:
    def process_github_webhook(self, payload, source, headers):
        # In a real scenario, this would call the actual Orchestrator.process_github_webhook
        # For this mock, we just return a successful response based on the input
        event_type = headers.get("X-GitHub-Event", "unknown")
        repo_full_name = payload.get("repository", {}).get("full_name", "unknown/repo")
        status = "ci_updated" # Default mock status
        ci_state = "passed" # Default mock CI state

        if event_type == "pull_request":
            action = payload.get("action")
            if action == "closed" and payload.get("pull_request", {}).get("merged"):
                status = "pr_merged"
            elif action == "closed":
                status = "pr_closed"
            else:
                status = "pr_updated"
        elif event_type == "check_run":
            ci_state = payload.get("check_run", {}).get("conclusion", "success")
            if ci_state == "success":
                ci_state = "passed"
            elif ci_state == "failure":
                ci_state = "failed"
            status = "ci_updated"

        return {
            "event_type": event_type,
            "repo": repo_full_name,
            "status": status,
            "details": f"Mock processed {event_type} for {repo_full_name}",
            "ci_state": ci_state,
        }

    def initialize(self):
        # Mock initialization logic
        return {"ok": True, "message": "Mock Orchestrator initialized"}


# Global mock ORCH instance
ORCH = MockOrchestratorEngine()


class MockMCPHTTPHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        # Only handle /mcp endpoint
        if self.path != "/mcp":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            json_rpc_request = json.loads(post_data.decode('utf-8'))
            
            method = json_rpc_request.get("method")
            params = json_rpc_request.get("params", {})
            request_id = json_rpc_request.get("id")
            
            response_payload = {}
            if method == "initialize":
                result = ORCH.initialize()
                response_payload = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result,
                }
            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                
                if tool_name == "orchestrator_process_github_webhook":
                    payload = tool_args.get("payload", {})
                    source = tool_args.get("source", "github")
                    headers = tool_args.get("headers", {}) # Extract headers from args
                    
                    # Call the mock orchestrator method
                    result = ORCH.process_github_webhook(payload=payload, source=source, headers=headers)
                    
                    response_payload = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(result),
                                }
                            ]
                        },
                    }
                else:
                    response_payload = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": f"Mock method not found for tool: {tool_name}",
                        },
                    }
            else:
                response_payload = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Mock method not found: {method}",
                    },
                }

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response_payload).encode('utf-8'))
            
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid JSON")
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))

    def do_GET(self):
        # Respond to GET requests for readiness checks
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Mock MCP HTTP server is running")


def run_mock_server(port):
    server_address = ('localhost', port)
    httpd = http.server.HTTPServer(server_address, MockMCPHTTPHandler)
    print(f"Mock MCP HTTP server starting on port {port}", file=sys.stderr)
    httpd.serve_forever()

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", 9000))
    # Run in a thread to allow graceful shutdown
    server_thread = threading.Thread(target=run_mock_server, args=(port,), daemon=True)
    server_thread.start()
    # Keep the main thread alive for a while, or until an external signal
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Mock MCP HTTP server shutting down.", file=sys.stderr)
        sys.exit(0)
