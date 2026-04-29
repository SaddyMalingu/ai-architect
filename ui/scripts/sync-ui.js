#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const uiDir = path.resolve(__dirname, "..");
const src = path.join(uiDir, "index.html");
const dst = path.join(uiDir, "cloud_demo.html");

if (!fs.existsSync(src)) {
  console.error("sync-ui failed: ui/index.html not found.");
  process.exit(1);
}

const shim = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Architect Cloud Studio</title>
  <meta http-equiv="refresh" content="0; url=./index.html" />
  <script>
    window.location.replace("./index.html");
  </script>
</head>
<body>
  <p>Redirecting to <a href="./index.html">index.html</a>...</p>
</body>
</html>
`;

fs.writeFileSync(dst, shim, "utf8");
console.log("Generated cloud_demo.html redirect shim to canonical index.html.");
