#!/usr/bin/env python3
"""
hannah_shell.py — Interactive text shell for Hannah Core.

Connects to a running Hannah Core via gRPC and sends text commands,
useful for testing NLU, the LLM Tool Agent, and intent routing
without going through Telegram or a satellite.

Usage:
  python scripts/hannah_shell.py                   # localhost:50051
  python scripts/hannah_shell.py --host 192.168.8.x --port 50051
"""

import argparse
import sys
from pathlib import Path

# Make the core package importable when running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import grpc
from hannah.proto import hannah_pb2, hannah_pb2_grpc


def main():
    parser = argparse.ArgumentParser(description="Hannah interactive text shell")
    parser.add_argument("--host", default="localhost", help="Hannah Core host")
    parser.add_argument("--port", type=int, default=50051, help="gRPC port")
    args = parser.parse_args()

    target = f"{args.host}:{args.port}"
    print(f"Connecting to Hannah Core at {target} …")

    with grpc.insecure_channel(target) as channel:
        try:
            grpc.channel_ready_future(channel).result(timeout=5)
        except grpc.FutureTimeoutError:
            print(f"Error: could not reach Hannah Core at {target}", file=sys.stderr)
            sys.exit(1)

        stub = hannah_pb2_grpc.HannahServiceStub(channel)
        print("Connected. Type your command (Ctrl+C or Ctrl+D to quit).\n")

        while True:
            try:
                text = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not text:
                continue

            try:
                resp = stub.SubmitText(
                    hannah_pb2.SubmitTextRequest(
                        text=text,
                        source_service="shell",
                        source_user_id="shell",
                    )
                )
                print(f"Hannah [{resp.intent_name}]: {resp.answer}\n")
            except grpc.RpcError as e:
                print(f"gRPC error: {e.details()}", file=sys.stderr)


if __name__ == "__main__":
    main()
