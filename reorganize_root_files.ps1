# Script to reorganize root project files
# Moves MD files to docs/archive/root/ by categories

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  ROOT PROJECT FILES REORGANIZATION" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# Create folder structure
$archiveBase = "docs/archive/root"
$folders = @(
    "$archiveBase/analysis",
    "$archiveBase/fixes",
    "$archiveBase/audits",
    "$archiveBase/reports",
    "$archiveBase/plans",
    "$archiveBase/misc",
    "scripts/analysis/root_scripts"
)

Write-Host "Creating folder structure..." -ForegroundColor Yellow
foreach ($folder in $folders) {
    if (-not (Test-Path $folder)) {
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
        Write-Host "  [OK] Created: $folder" -ForegroundColor Green
    } else {
        Write-Host "  [SKIP] Exists: $folder" -ForegroundColor Gray
    }
}
Write-Host ""

# Files to keep in root (DO NOT MOVE)
$keepInRoot = @(
    "README.md",
    "TECHNICAL_SPECIFICATION.md",
    "ПОЛНОЕ_ОПИСАНИЕ_ТОРГОВОГО_БОТА.md"
)

# ANALYSIS files -> docs/archive/root/analysis/
$analysisFiles = @(
    "ANALYSIS_CLOSING_PRICE.md",
    "ANALYSIS_DATA_FOR_KIMI.md",
    "ANALYSIS_EXITANALYZER_PARAMETERS.md",
    "ANALYSIS_LIMIT_ORDER_PRICE_PROBLEM.md",
    "ANALYSIS_NEGATIVE_CLOSES_END_SESSION.md",
    "ANALYSIS_REPORT_2025-12-08.md",
    "ANALYSIS_SIGNATURES_INTERPRETATIONS.md",
    "ANALYSIS_SMALL_PROFIT_EARLY_EXIT.md",
    "ANALYSIS_STAGE2_FOR_KIMI.md",
    "ANALYSIS_STRATEGY_PLACEMENT_CLOSING.md",
    "ANALYSIS_TIMEOUT_VS_EXITANALYZER.md",
    "COMPREHENSIVE_ANALYSIS_BROKER_MATH.md",
    "COMPREHENSIVE_ARCHIVE_ANALYSIS.md",
    "COMPREHENSIVE_BOT_ANALYSIS.md",
    "FINAL_COMPREHENSIVE_ANALYSIS.md",
    "PEAK_PROFIT_USD_ANALYSIS.md",
    "SCALPING_STRATEGIES_ANALYSIS.md",
    "TRADING_EXPERT_ANALYSIS.md",
    "TRENDS_METRICS_ECONOMY_2025-12-08.md"
)

# FIXES files -> docs/archive/root/fixes/
$fixesFiles = @(
    "ALL_FIXES_COMPLETED_REPORT.md",
    "FIXES_2025-12-18.md",
    "FIXES_SMALL_PROFIT_EARLY_EXIT.md",
    "FIXES_STRATEGY_OPTIMIZATION.md",
    "SUMMARY_CLOSING_FIXES_APPLIED.md",
    "SUMMARY_EXITANALYZER_FIXES.md",
    "SUMMARY_FIXES_APPLIED.md",
    "SUMMARY_FIXES_INDENTATION.md",
    "SUMMARY_NEGATIVE_CLOSES_FIX.md",
    "SUMMARY_SIGNAL_PRICE_FIX.md",
    "SUMMARY_SYNTAX_FIXES.md",
    "SUMMARY_TRAILING_STOP_LOSS_FIX.md",
    "CORRECTION_SELL_LOGIC.md",
    "SOLUTION_SIGNAL_PRICE_FROM_ORDERBOOK.md"
)

# AUDITS files -> docs/archive/root/audits/
$auditsFiles = @(
    "AUDIT_BUNDLE_TASK_v1.3.md",
    "AUDIT_SUMMARY_2025-12-08.md",
    "FULL_AUDIT_REPORT_2025-12-08.md",
    "PROJECT_ROOT_AUDIT_REPORT.md",
    "DETAILED_MARKPX_ANALYSIS_2025-12-08.md",
    "UNINITIALIZED_MODULES_REPORT.md",
    "VERIFICATION_REPORT.md"
)

# REPORTS files -> docs/archive/root/reports/
$reportsFiles = @(
    "ALL_ERRORS_SUMMARY.md",
    "FINAL_AUDIT_DATA_FOR_KIMI.md",
    "FINAL_EXITANALYZER_ANALYSIS.md",
    "FINAL_INTEGRATION_REPORT.md",
    "FINAL_MASTER_PLAN.md",
    "FINAL_SOLUTIONS_PLAN.md",
    "FINAL_SUMMARY_ALL_FIXES.md",
    "LOG_CHECK_2025-12-18_23-00.md",
    "REFACTORING_COMPLETE_REPORT.md",
    "REORGANIZATION_COMPLETED.md",
    "SUMMARY_CLOSING_PRICE_ANALYSIS.md",
    "SUMMARY_EXITANALYZER_CHECK.md",
    "PARAMETERS_UPDATE_SUMMARY.md"
)

# PLANS files -> docs/archive/root/plans/
$plansFiles = @(
    "MASTER_PLAN_FIXES.md",
    "MASTER_TODO_ALL_PROBLEMS.md",
    "TODO_MASTER_PLAN.md",
    "QUESTIONS_AND_PLAN.md",
    "RECOMMENDATION_TIMEOUT_REMOVAL.md"
)

# MISC files -> docs/archive/root/misc/
$miscFiles = @(
    "SIGNAL_EXECUTION_BLOCKING_ANALYSIS.md",
    "archive_analysis_output.txt",
    "backtest_data_2025-12-17.json",
    "backtest_vs_reality_comparison.json",
    "improved_backtest_results.json",
    "FINAL_CORRECTIONS_2025-12-08.json",
    "signals_sample_50.csv"
)

# Handle files with special characters separately
$specialFiles = @(
    "tatus",
    "tatus --short"
)

# PYTHON SCRIPTS -> scripts/analysis/root_scripts/
$pythonScripts = @(
    "analyze_archived_logs.py",
    "analyze_backtest_vs_reality.py",
    "analyze_position_closing_logic.py",
    "manual_log_analysis.py",
    "quick_analyze.py",
    "temp_analyze_today.py",
    "improved_backtest.py",
    "export_backtest_data.py"
)

# Function to move file safely
function Move-FileSafe {
    param(
        [string]$sourcePath,
        [string]$destPath
    )
    
    if (Test-Path $sourcePath) {
        try {
            $destDir = Split-Path $destPath -Parent
            if (-not (Test-Path $destDir)) {
                New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            }
            
            Move-Item -Path $sourcePath -Destination $destPath -Force -ErrorAction Stop
            return @{Success=$true; Message="Moved: $(Split-Path $sourcePath -Leaf)"}
        }
        catch {
            return @{Success=$false; Message="Error moving $sourcePath : $_"}
        }
    }
    else {
        return @{Success=$false; Message="Not found: $sourcePath"}
    }
}

# Move files by category
$movedCount = 0
$notFoundCount = 0
$errorCount = 0

Write-Host "Moving ANALYSIS files..." -ForegroundColor Cyan
foreach ($file in $analysisFiles) {
    $result = Move-FileSafe $file "$archiveBase/analysis/$file"
    if ($result.Success) {
        Write-Host "  [OK] $($result.Message)" -ForegroundColor Green
        $movedCount++
    } elseif ($result.Message -like "Not found*") {
        Write-Host "  [SKIP] $($result.Message)" -ForegroundColor Yellow
        $notFoundCount++
    } else {
        Write-Host "  [ERROR] $($result.Message)" -ForegroundColor Red
        $errorCount++
    }
}

Write-Host "`nMoving FIXES files..." -ForegroundColor Cyan
foreach ($file in $fixesFiles) {
    $result = Move-FileSafe $file "$archiveBase/fixes/$file"
    if ($result.Success) {
        Write-Host "  [OK] $($result.Message)" -ForegroundColor Green
        $movedCount++
    } elseif ($result.Message -like "Not found*") {
        Write-Host "  [SKIP] $($result.Message)" -ForegroundColor Yellow
        $notFoundCount++
    } else {
        Write-Host "  [ERROR] $($result.Message)" -ForegroundColor Red
        $errorCount++
    }
}

Write-Host "`nMoving AUDITS files..." -ForegroundColor Cyan
foreach ($file in $auditsFiles) {
    $result = Move-FileSafe $file "$archiveBase/audits/$file"
    if ($result.Success) {
        Write-Host "  [OK] $($result.Message)" -ForegroundColor Green
        $movedCount++
    } elseif ($result.Message -like "Not found*") {
        Write-Host "  [SKIP] $($result.Message)" -ForegroundColor Yellow
        $notFoundCount++
    } else {
        Write-Host "  [ERROR] $($result.Message)" -ForegroundColor Red
        $errorCount++
    }
}

Write-Host "`nMoving REPORTS files..." -ForegroundColor Cyan
foreach ($file in $reportsFiles) {
    $result = Move-FileSafe $file "$archiveBase/reports/$file"
    if ($result.Success) {
        Write-Host "  [OK] $($result.Message)" -ForegroundColor Green
        $movedCount++
    } elseif ($result.Message -like "Not found*") {
        Write-Host "  [SKIP] $($result.Message)" -ForegroundColor Yellow
        $notFoundCount++
    } else {
        Write-Host "  [ERROR] $($result.Message)" -ForegroundColor Red
        $errorCount++
    }
}

Write-Host "`nMoving PLANS files..." -ForegroundColor Cyan
foreach ($file in $plansFiles) {
    $result = Move-FileSafe $file "$archiveBase/plans/$file"
    if ($result.Success) {
        Write-Host "  [OK] $($result.Message)" -ForegroundColor Green
        $movedCount++
    } elseif ($result.Message -like "Not found*") {
        Write-Host "  [SKIP] $($result.Message)" -ForegroundColor Yellow
        $notFoundCount++
    } else {
        Write-Host "  [ERROR] $($result.Message)" -ForegroundColor Red
        $errorCount++
    }
}

Write-Host "`nMoving MISC files..." -ForegroundColor Cyan
foreach ($file in $miscFiles) {
    $result = Move-FileSafe $file "$archiveBase/misc/$file"
    if ($result.Success) {
        Write-Host "  [OK] $($result.Message)" -ForegroundColor Green
        $movedCount++
    } elseif ($result.Message -like "Not found*") {
        Write-Host "  [SKIP] $($result.Message)" -ForegroundColor Yellow
        $notFoundCount++
    } else {
        Write-Host "  [ERROR] $($result.Message)" -ForegroundColor Red
        $errorCount++
    }
}

# Handle special files with spaces/special chars
Write-Host "`nMoving special files..." -ForegroundColor Cyan
foreach ($file in $specialFiles) {
    $escapedFile = $file
    if (Test-Path $escapedFile) {
        try {
            $destPath = "$archiveBase/misc/$escapedFile"
            $destDir = Split-Path $destPath -Parent
            if (-not (Test-Path $destDir)) {
                New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            }
            Move-Item -Path $escapedFile -Destination $destPath -Force -ErrorAction Stop
            Write-Host "  [OK] Moved: $escapedFile" -ForegroundColor Green
            $movedCount++
        } catch {
            Write-Host "  [ERROR] Error moving $escapedFile : $_" -ForegroundColor Red
            $errorCount++
        }
    } else {
        Write-Host "  [SKIP] Not found: $escapedFile" -ForegroundColor Yellow
        $notFoundCount++
    }
}

Write-Host "`nMoving PYTHON scripts..." -ForegroundColor Cyan
foreach ($file in $pythonScripts) {
    $result = Move-FileSafe $file "scripts/analysis/root_scripts/$file"
    if ($result.Success) {
        Write-Host "  [OK] $($result.Message)" -ForegroundColor Green
        $movedCount++
    } elseif ($result.Message -like "Not found*") {
        Write-Host "  [SKIP] $($result.Message)" -ForegroundColor Yellow
        $notFoundCount++
    } else {
        Write-Host "  [ERROR] $($result.Message)" -ForegroundColor Red
        $errorCount++
    }
}

# Move reorganization plan to archive
if (Test-Path "ROOT_AUDIT_AND_REORGANIZATION_PLAN.md") {
    $result = Move-FileSafe "ROOT_AUDIT_AND_REORGANIZATION_PLAN.md" "$archiveBase/ROOT_AUDIT_AND_REORGANIZATION_PLAN.md"
    if ($result.Success) {
        Write-Host "`n[OK] $($result.Message)" -ForegroundColor Green
        $movedCount++
    }
}

# Create README in archive
$readmeContent = @"
# ARCHIVE OF ROOT PROJECT FILES

This archive contains files that were moved from the project root during reorganization.

Reorganization Date: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

## Structure

- analysis/ - Analysis and research files (19 files)
- fixes/ - Fix reports (14 files)
- audits/ - System audits (7 files)
- reports/ - Work reports (13 files)
- plans/ - Development plans (5 files)
- misc/ - Miscellaneous files (JSON, CSV, TXT)

## Files that remained in root

- README.md - Main project instruction
- TECHNICAL_SPECIFICATION.md - Technical specification
- ПОЛНОЕ_ОПИСАНИЕ_ТОРГОВОГО_БОТА.md - Full bot description

## Python Scripts

Python analysis scripts were moved to scripts/analysis/root_scripts/

## Statistics

- Total files moved: ~75
- MD files: ~58
- Python scripts: 8
- Data files: 9
"@

$readmePath = "$archiveBase/README.md"
Set-Content -Path $readmePath -Value $readmeContent -Encoding UTF8
Write-Host "`n[OK] Created README.md in archive" -ForegroundColor Green

# Final statistics
Write-Host "`n" 
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  FINAL STATISTICS" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Files moved successfully: $movedCount" -ForegroundColor Green
Write-Host "  Files not found: $notFoundCount" -ForegroundColor Yellow
Write-Host "  Errors: $errorCount" -ForegroundColor $(if ($errorCount -eq 0) { "Green" } else { "Red" })
Write-Host "  Files remaining in root (docs): $($keepInRoot.Count)" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

if ($errorCount -eq 0) {
    Write-Host "SUCCESS! Reorganization completed successfully!" -ForegroundColor Green
    Write-Host "See detailed plan in: $archiveBase/ROOT_AUDIT_AND_REORGANIZATION_PLAN.md`n" -ForegroundColor Cyan
} else {
    Write-Host "WARNING! Some errors occurred during reorganization.`n" -ForegroundColor Yellow
}
