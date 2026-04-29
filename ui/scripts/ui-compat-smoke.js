#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

const uiDir = path.resolve(__dirname, "..");
const indexPath = path.join(uiDir, "index.html");
const cloudDemoPath = path.join(uiDir, "cloud_demo.html");

function readText(filePath) {
  return fs.readFileSync(filePath, "utf8");
}

function assertContains(haystack, needle, message) {
  if (!haystack.includes(needle)) {
    throw new Error(message + "\nMissing: " + needle);
  }
}

function assertId(html, id) {
  assertContains(html, `id=\"${id}\"`, `Required UI id is missing: ${id}`);
}

function run() {
  if (!fs.existsSync(indexPath) || !fs.existsSync(cloudDemoPath)) {
    throw new Error("Expected both ui/index.html and ui/cloud_demo.html to exist.");
  }

  const indexHtml = readText(indexPath);
  const cloudDemoHtml = readText(cloudDemoPath);

  const requiredIds = [
    "supabaseUrl",
    "anonKey",
    "userId",
    "renderPrompt",
    "runRenderBtn",
    "runAllViewsBtn",
    "pollLatestBtn",
    "regionalTab",
    "runRegionalBtn",
    "requestId",
    "checkStatusBtn",
    "loadHistoryBtn",
    "targetImageUrl",
    "referenceImageUrl",
    "targetMaskUrl",
    "viewFrontImage",
    "viewLeftImage",
    "viewRightImage",
    "viewBackImage",
    "viewFrontState",
    "viewLeftState",
    "viewRightState",
    "viewBackState",
    "renderInputImageUrl",
    "renderReferenceImageUrl",
    "renderBackgroundImageUrl",
    "backgroundPresetChips",
    "manualSelectionBox",
    "maskCanvas"
  ];

  requiredIds.forEach((id) => assertId(indexHtml, id));

  const requiredApiRefs = [
    "/functions/v1/render",
    "/functions/v1/edit-regional",
    "/functions/v1/render-status",
    "/functions/v1/render-history"
  ];

  requiredApiRefs.forEach((apiRef) => {
    assertContains(indexHtml, apiRef, "Required API reference is missing in UI");
  });

  const redirectChecks = [
    'http-equiv="refresh"',
    'url=./index.html',
    'window.location.replace("./index.html")'
  ];

  redirectChecks.forEach((marker) => {
    assertContains(
      cloudDemoHtml,
      marker,
      "cloud_demo.html must be a redirect shim to canonical index.html"
    );
  });

  console.log("UI compatibility smoke check passed.");
}

try {
  run();
} catch (err) {
  console.error("UI compatibility smoke check failed.");
  console.error(err && err.message ? err.message : err);
  process.exit(1);
}
