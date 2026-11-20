#!/usr/bin/env bash
# Fetch and build llm-router (MIT licensed, https://github.com/zxuhan/llm-router) at a pinned commit.
# The code is not vendored into this repository; it is cloned into third_party/ (git-ignored).
set -euo pipefail
cd "$(dirname "$0")/.."
COMMIT=c1345f71ad83d018faefdb4bf3e9c99182d9936a
DIR=third_party/llm-router
command -v go >/dev/null || { echo "Go is required: brew install go"; exit 1; }
if [[ ! -d $DIR/.git ]]; then
  mkdir -p third_party
  git clone -q https://github.com/zxuhan/llm-router.git "$DIR"
fi
git -C "$DIR" fetch -q origin
git -C "$DIR" checkout -q "$COMMIT"
(cd "$DIR" && go build -o bin/router ./cmd/router)
echo "llm-router $(git -C "$DIR" rev-parse --short HEAD) built at $DIR/bin/router"
