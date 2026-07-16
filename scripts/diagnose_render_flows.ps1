<#
.SYNOPSIS
  End-to-end diagnostics for all backbone render flows.
  Run from the repo root: .\scripts\diagnose_render_flows.ps1

.DESCRIPTION
  Fires smoke requests at every live Supabase endpoint (preflight, render,
  render-status, render-history, edit-regional) and writes full JSON logs to
  outputs/analysis/diag_<timestamp>/.  Produces a human-readable summary table.

  All calls use the ANON key so results mirror real UI requests.
  A KNOWN-GOOD public image URL is used as source/target to avoid auth issues.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

# ── config ────────────────────────────────────────────────────────────────────
$Base   = "https://eccvtkqkllegzbypaemw.supabase.co"
$Anon   = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVjY3Z0a3FrbGxlZ3pieXBhZW13Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYyNTcxODcsImV4cCI6MjA5MTgzMTg3fQ.F6ylVSRrYjOlOSZBYEBmuwpfrxBbeF74DImUNSspIgY"
$Uid    = "ec470708-d89c-4575-9d94-b57cd681bb8b"
$ImgUrl = "https://images.unsplash.com/photo-1512918728675-ed5a9ecdebfd?w=1024"
$RefUrl = "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=1024"

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutDir    = Join-Path $PSScriptRoot "..\outputs\analysis\diag_$Timestamp"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$Headers = @{
  apikey        = $Anon
  Authorization = "Bearer $Anon"
  "Content-Type" = "application/json"
}

# ── helper ────────────────────────────────────────────────────────────────────
$Results = [System.Collections.Generic.List[PSCustomObject]]::new()

function Invoke-Flow {
  param(
    [string]$Name,
    [string]$Method,
    [string]$Url,
    [string]$Body
  )

  Write-Host "`n── $Name [$Method $Url]" -ForegroundColor Cyan
  $logFile = Join-Path $OutDir "$Name.json"
  $start   = [System.Diagnostics.Stopwatch]::StartNew()
  $status  = 0
  $content = $null

  try {
    $args = @{
      Uri     = $Url
      Method  = $Method
      Headers = $Headers
    }
    if ($Body) { $args.Body = $Body }

    $resp    = Invoke-WebRequest @args -UseBasicParsing
    $status  = [int]$resp.StatusCode
    $content = $resp.Content
  } catch {
    $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { -1 }
    if ($_.Exception.Response) {
      try {
        $stream  = $_.Exception.Response.GetResponseStream()
        $reader  = New-Object System.IO.StreamReader($stream)
        $content = $reader.ReadToEnd()
        $reader.Close()
      } catch { $content = $_.Exception.Message }
    } else {
      $content = $_.Exception.Message
    }
  }

  $start.Stop()
  $elapsed = $start.ElapsedMilliseconds

  # parse JSON nicely or keep raw
  $pretty = $content
  try {
    $parsed = $content | ConvertFrom-Json -ErrorAction Stop
    $pretty = $parsed | ConvertTo-Json -Depth 12
  } catch {}

  $log = @{
    flow      = $Name
    method    = $Method
    url       = $Url
    timestamp = (Get-Date -Format "o")
    http_status = $status
    latency_ms  = $elapsed
    response    = $pretty
  } | ConvertTo-Json -Depth 15

  $log | Out-File -FilePath $logFile -Encoding utf8

  # console excerpt
  $preview = if ($pretty.Length -gt 800) { $pretty.Substring(0,800) + "`n... [truncated, full log: $logFile]" } else { $pretty }
  Write-Host "  Status : $status  |  Latency: ${elapsed}ms" -ForegroundColor $(if ($status -ge 200 -and $status -lt 300) { "Green" } else { "Red" })
  Write-Host $preview

  $Results.Add([PSCustomObject]@{
    Flow      = $Name
    Method    = $Method
    Status    = $status
    LatencyMs = $elapsed
    OK        = ($status -ge 200 -and $status -lt 300)
    LogFile   = $logFile
  })
}

# ── 1. Preflight ───────────────────────────────────────────────────────────────
$preflightBody = @{
  mode            = "all"
  user_id         = $Uid
  target_image_url = $ImgUrl
  selection_mode  = "automatic"
  prompt          = "diagnostic preflight"
} | ConvertTo-Json

Invoke-Flow -Name "01_preflight" -Method "POST" `
  -Url "$Base/functions/v1/preflight" `
  -Body $preflightBody

# ── 2. Render (prompt-only, no image) ──────────────────────────────────────────
$renderBodyBasic = @{
  user_id       = $Uid
  prompt        = "modern concrete house, flat roof, diagnostic render, no image conditioning"
  model_profile = "fast"
} | ConvertTo-Json

Invoke-Flow -Name "02_render_prompt_only" -Method "POST" `
  -Url "$Base/functions/v1/render" `
  -Body $renderBodyBasic

# store request_id for status poll
$r2RawPath = Join-Path $OutDir "02_render_prompt_only.json"
$requestId02 = $null
try {
  $r2Obj = (Get-Content $r2RawPath -Raw | ConvertFrom-Json -ErrorAction Stop)
  $nested = ($r2Obj.response | ConvertFrom-Json -ErrorAction Stop)
  $requestId02 = $nested.request_id
} catch {}

# ── 3. Render (with source image) ─────────────────────────────────────────────
$renderBodySource = @{
  user_id          = $Uid
  prompt           = "apply contemporary cladding with brick texture"
  input_image_url  = $ImgUrl
  model_profile    = "fast"
  strict_consistency = $false
} | ConvertTo-Json

Invoke-Flow -Name "03_render_with_source" -Method "POST" `
  -Url "$Base/functions/v1/render" `
  -Body $renderBodySource

$requestId03 = $null
try {
  $r3Obj    = (Get-Content (Join-Path $OutDir "03_render_with_source.json") -Raw | ConvertFrom-Json -ErrorAction Stop)
  $nested3  = ($r3Obj.response | ConvertFrom-Json -ErrorAction Stop)
  $requestId03 = $nested3.request_id
} catch {}

# ── 4. Render (with source + reference) ───────────────────────────────────────
$renderBodyRef = @{
  user_id               = $Uid
  prompt                = "apply reference style to facade"
  input_image_url       = $ImgUrl
  reference_image_url   = $RefUrl
  model_profile         = "fast"
  strict_consistency    = $false
} | ConvertTo-Json

Invoke-Flow -Name "04_render_source_plus_ref" -Method "POST" `
  -Url "$Base/functions/v1/render" `
  -Body $renderBodyRef

# ── 5. Render-status poll (use id from flow 02 or 03) ─────────────────────────
$statusId = if ($requestId02) { $requestId02 } elseif ($requestId03) { $requestId03 } else { $null }

if ($statusId) {
  Invoke-Flow -Name "05_render_status" -Method "GET" `
    -Url "$Base/functions/v1/render-status?request_id=$statusId&user_id=$Uid" `
    -Body $null
} else {
  Write-Host "`n── 05_render_status [SKIPPED — no request_id from prior flows]" -ForegroundColor Yellow
  $Results.Add([PSCustomObject]@{ Flow="05_render_status"; Method="GET"; Status="SKIPPED"; LatencyMs=0; OK=$false; LogFile="" })
}

# ── 6. Render-history ─────────────────────────────────────────────────────────
Invoke-Flow -Name "06_render_history" -Method "GET" `
  -Url "$Base/functions/v1/render-history?user_id=$Uid&limit=5" `
  -Body $null

# extract a real request_id from history for a second status probe
$histRawPath = Join-Path $OutDir "06_render_history.json"
$histRequestId = $null
try {
  $hObj     = (Get-Content $histRawPath -Raw | ConvertFrom-Json -ErrorAction Stop)
  $hNested  = ($hObj.response | ConvertFrom-Json -ErrorAction Stop)
  $histRequestId = $hNested.items[0].request_id
} catch {}

if ($histRequestId -and -not $statusId) {
  Invoke-Flow -Name "05b_render_status_from_history" -Method "GET" `
    -Url "$Base/functions/v1/render-status?request_id=$histRequestId&user_id=$Uid" `
    -Body $null
}

# ── 7. Edit-regional (automatic, no mask) ─────────────────────────────────────
$regionalBodyAuto = @{
  user_id           = $Uid
  target_image_url  = $ImgUrl
  prompt            = "apply brick facade texture to building surface"
  edit_category     = "element_texture"
  selection_mode    = "automatic"
  model_profile     = "fast"
  strict_consistency = $false
} | ConvertTo-Json

Invoke-Flow -Name "07_regional_auto" -Method "POST" `
  -Url "$Base/functions/v1/edit-regional" `
  -Body $regionalBodyAuto

# ── 8. Edit-regional (with reference) ─────────────────────────────────────────
$regionalBodyRef = @{
  user_id               = $Uid
  target_image_url      = $ImgUrl
  reference_image_url   = $RefUrl
  prompt                = "apply reference material to facade"
  edit_category         = "element_texture"
  selection_mode        = "automatic"
  model_profile         = "fast"
  strict_consistency    = $false
} | ConvertTo-Json

Invoke-Flow -Name "08_regional_with_ref" -Method "POST" `
  -Url "$Base/functions/v1/edit-regional" `
  -Body $regionalBodyRef

# ── 9. CORS OPTIONS probe ──────────────────────────────────────────────────────
Write-Host "`n── 09_cors_options [OPTIONS $Base/functions/v1/render]" -ForegroundColor Cyan
try {
  $corsResp = Invoke-WebRequest -Uri "$Base/functions/v1/render" -Method OPTIONS `
    -Headers @{ Origin="https://example.com"; "Access-Control-Request-Method"="POST" } `
    -UseBasicParsing
  $allowOrigin = $corsResp.Headers["Access-Control-Allow-Origin"]
  $corsOk      = ($corsResp.StatusCode -in 200,204) -and $allowOrigin
  Write-Host "  Status : $($corsResp.StatusCode)  |  Allow-Origin: $allowOrigin" `
    -ForegroundColor $(if ($corsOk) { "Green" } else { "Red" })
  $Results.Add([PSCustomObject]@{
    Flow="09_cors_options"; Method="OPTIONS"
    Status=$corsResp.StatusCode; LatencyMs=0; OK=$corsOk; LogFile=""
  })
} catch {
  Write-Host "  CORS OPTIONS failed: $($_.Exception.Message)" -ForegroundColor Red
  $Results.Add([PSCustomObject]@{
    Flow="09_cors_options"; Method="OPTIONS"; Status=-1; LatencyMs=0; OK=$false; LogFile=""
  })
}

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host "`n═══════════════════════════════════════════════════════" -ForegroundColor White
Write-Host "  DIAGNOSTICS SUMMARY" -ForegroundColor White
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor White

$Results | Format-Table -AutoSize -Property @(
  @{Label="Flow";       Expression={$_.Flow}},
  @{Label="Method";     Expression={$_.Method}},
  @{Label="HTTP";       Expression={$_.Status}},
  @{Label="ms";         Expression={$_.LatencyMs}},
  @{Label="Pass";       Expression={ if ($_.OK) {"✓"} else {"✗"} }}
)

$passed  = ($Results | Where-Object { $_.OK }).Count
$total   = $Results.Count
$allPass = $passed -eq $total

Write-Host "Result: $passed / $total flows passed" `
  -ForegroundColor $(if ($allPass) { "Green" } else { "Red" })
Write-Host "Logs:   $OutDir"
Write-Host ""

if (-not $allPass) {
  Write-Host "FAILING FLOWS — check log files for diagnostics.* blocks:" -ForegroundColor Yellow
  $Results | Where-Object { -not $_.OK } | ForEach-Object {
    Write-Host "  • $($_.Flow)  (HTTP $($_.Status))  → $($_.LogFile)" -ForegroundColor Red
  }
}
