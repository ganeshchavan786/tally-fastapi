"""
Tally Sync Test Script
======================
This script tests the complete sync flow:
1. Check Tally connection
2. List all companies
3. Full sync for selected companies
4. Incremental sync for selected companies

Run: python test_sync.py
"""

import requests
import time
import json
import os
from datetime import datetime

# Configuration
API_BASE_URL = "http://localhost:8000"
LOG_FILE = f"sync_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

# Colors for terminal (Windows compatible)
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'

def log(message, level="INFO"):
    """Log message to console and file"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{level}] {message}"
    
    # Write to log file
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_line + "\n")
    
    # Print to console with colors
    if level == "ERROR":
        print(f"{Colors.RED}{log_line}{Colors.END}")
    elif level == "SUCCESS":
        print(f"{Colors.GREEN}{log_line}{Colors.END}")
    elif level == "WARNING":
        print(f"{Colors.YELLOW}{log_line}{Colors.END}")
    else:
        print(log_line)

def print_header(title):
    """Print a formatted header"""
    print(f"\n{Colors.CYAN}{'=' * 70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}  {title}{Colors.END}")
    print(f"{Colors.CYAN}{'=' * 70}{Colors.END}\n")

def print_section(title):
    """Print a section header"""
    print(f"\n{Colors.YELLOW}--- {title} ---{Colors.END}\n")

def check_api_running():
    """Check if the FastAPI server is running"""
    print_section("Step 1: Checking API Server")
    try:
        response = requests.get(f"{API_BASE_URL}/api/health", timeout=5)
        if response.status_code == 200:
            log("API Server is running", "SUCCESS")
            return True
        else:
            log(f"API Server returned status {response.status_code}", "ERROR")
            return False
    except requests.exceptions.ConnectionError:
        log("API Server is not running! Please start with: python run.py", "ERROR")
        return False
    except Exception as e:
        log(f"Error checking API: {e}", "ERROR")
        return False

def check_tally_connection():
    """Check Tally connection"""
    print_section("Step 2: Checking Tally Connection")
    try:
        response = requests.get(f"{API_BASE_URL}/api/health", timeout=10)
        data = response.json()
        
        tally_status = data.get("components", {}).get("tally", {})
        if tally_status.get("status") == "healthy":
            log(f"Tally Connected: {tally_status.get('server')}:{tally_status.get('port')}", "SUCCESS")
            return True
        else:
            log(f"Tally not connected: {tally_status.get('message', 'Unknown error')}", "ERROR")
            return False
    except Exception as e:
        log(f"Error checking Tally: {e}", "ERROR")
        return False

def get_companies():
    """Get list of companies from Tally"""
    print_section("Step 3: Getting Company List")
    try:
        response = requests.get(f"{API_BASE_URL}/api/data/companies", timeout=30)
        data = response.json()
        
        companies = data.get("companies", [])
        current_company = data.get("current_company", "")
        
        if companies:
            log(f"Found {len(companies)} companies in Tally", "SUCCESS")
            print(f"\n  {'No.':<5} {'Company Name':<50} {'Current':<10}")
            print(f"  {'-' * 65}")
            for i, company in enumerate(companies, 1):
                is_current = "Yes" if company.get("is_current") else ""
                name = company.get("name", "Unknown")
                print(f"  {i:<5} {name:<50} {is_current:<10}")
            print()
            return companies
        else:
            log("No companies found in Tally", "WARNING")
            return []
    except Exception as e:
        log(f"Error getting companies: {e}", "ERROR")
        return []

def select_companies(companies):
    """Let user select companies for sync"""
    print_section("Step 4: Select Companies for Sync")
    
    if not companies:
        return []
    
    print("  Enter company numbers separated by comma (e.g., 1,2,3)")
    print("  Or enter 'all' to sync all companies")
    print("  Or enter 'q' to quit\n")
    
    while True:
        choice = input("  Your choice: ").strip().lower()
        
        if choice == 'q':
            return []
        elif choice == 'all':
            return [c.get("name") for c in companies]
        else:
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(",")]
                selected = []
                for idx in indices:
                    if 0 <= idx < len(companies):
                        selected.append(companies[idx].get("name"))
                    else:
                        print(f"  Invalid number: {idx + 1}")
                if selected:
                    return selected
            except ValueError:
                print("  Invalid input. Please enter numbers separated by comma.")

def run_full_sync(companies, parallel=False):
    """Run full sync for selected companies"""
    mode = "PARALLEL" if parallel else "SEQUENTIAL"
    print_section(f"Step 5: Running Full Sync ({mode})")
    
    if not companies:
        log("No companies selected for full sync", "WARNING")
        return None
    
    log(f"Starting {mode} full sync for {len(companies)} companies...", "INFO")
    start_time = time.time()
    
    try:
        # For single company, use direct API (faster for timing test)
        if len(companies) == 1:
            response = requests.post(
                f"{API_BASE_URL}/api/sync/full",
                params={"company": companies[0], "parallel": parallel},
                timeout=30
            )
            data = response.json()
            log(f"Started: {data.get('message', 'Sync started')}", "INFO")
        else:
            # Add to queue for multiple companies
            response = requests.post(
                f"{API_BASE_URL}/api/sync/queue",
                json={"companies": companies, "sync_type": "full"},
                timeout=30
            )
            data = response.json()
            log(f"Queue: {data.get('message', 'Added to queue')}", "INFO")
            
            # Start queue processing
            response = requests.post(f"{API_BASE_URL}/api/sync/queue/start", timeout=30)
            data = response.json()
            log(f"Started: {data.get('message', 'Processing started')}", "INFO")
        
        # Monitor progress
        success = monitor_sync_progress(f"Full Sync ({mode})")
        elapsed = time.time() - start_time
        
        return elapsed if success else None
        
    except Exception as e:
        log(f"Full sync error: {e}", "ERROR")
        return None

def run_incremental_sync(companies):
    """Run incremental sync for selected companies"""
    print_section("Step 6: Running Incremental Sync")
    
    if not companies:
        log("No companies selected for incremental sync", "WARNING")
        return False
    
    log(f"Starting incremental sync for {len(companies)} companies...", "INFO")
    
    try:
        # Add to queue
        response = requests.post(
            f"{API_BASE_URL}/api/sync/queue",
            json={"companies": companies, "sync_type": "incremental"},
            timeout=30
        )
        data = response.json()
        log(f"Queue: {data.get('message', 'Added to queue')}", "INFO")
        
        # Start queue processing
        response = requests.post(f"{API_BASE_URL}/api/sync/queue/start", timeout=30)
        data = response.json()
        log(f"Started: {data.get('message', 'Processing started')}", "INFO")
        
        # Monitor progress
        return monitor_sync_progress("Incremental Sync")
        
    except Exception as e:
        log(f"Incremental sync error: {e}", "ERROR")
        return False

def monitor_sync_progress(sync_type):
    """Monitor sync progress until completion"""
    print(f"\n  Monitoring {sync_type} progress...\n")
    
    last_status = ""
    start_time = time.time()
    
    while True:
        try:
            response = requests.get(f"{API_BASE_URL}/api/sync/status", timeout=10)
            data = response.json()
            
            status = data.get("status", "unknown")
            progress = data.get("progress", 0)
            current_table = data.get("current_table", "")
            rows_processed = data.get("rows_processed", 0)
            current_company = data.get("current_company", "")
            
            # Build status line
            status_line = f"  [{status.upper()}] {progress}% | Company: {current_company} | Table: {current_table} | Rows: {rows_processed}"
            
            # Only print if status changed
            if status_line != last_status:
                print(f"\r{status_line:<100}", end="", flush=True)
                last_status = status_line
            
            # Check if completed
            if status in ["completed", "failed", "cancelled", "idle"]:
                elapsed = time.time() - start_time
                print()  # New line after progress
                
                if status == "completed":
                    log(f"{sync_type} completed! Rows: {rows_processed}, Time: {elapsed:.1f}s", "SUCCESS")
                    return True
                elif status == "failed":
                    error = data.get("error_message", "Unknown error")
                    log(f"{sync_type} failed: {error}", "ERROR")
                    return False
                elif status == "idle" and rows_processed > 0:
                    log(f"{sync_type} completed! Rows: {rows_processed}, Time: {elapsed:.1f}s", "SUCCESS")
                    return True
                else:
                    log(f"{sync_type} ended with status: {status}", "WARNING")
                    return False
            
            time.sleep(1)
            
        except Exception as e:
            log(f"Error monitoring progress: {e}", "ERROR")
            time.sleep(2)

def show_database_stats():
    """Show database statistics"""
    print_section("Database Statistics")
    
    try:
        response = requests.get(f"{API_BASE_URL}/api/data/counts", timeout=10)
        data = response.json()
        
        # API returns direct table:count mapping (not nested in "counts" key)
        counts = data if isinstance(data, dict) else {}
        total = sum(counts.values()) if counts else 0
        
        print(f"  {'Table':<35} {'Rows':<10}")
        print(f"  {'-' * 45}")
        
        for table, count in sorted(counts.items()):
            if count > 0:
                print(f"  {table:<35} {count:<10}")
        
        print(f"  {'-' * 45}")
        print(f"  {'TOTAL':<35} {total:<10}")
        print()
        
        log(f"Total rows in database: {total}", "SUCCESS")
        
    except Exception as e:
        log(f"Error getting database stats: {e}", "ERROR")

def show_synced_companies():
    """Show synced companies from database"""
    print_section("Synced Companies")
    
    try:
        response = requests.get(f"{API_BASE_URL}/api/data/synced-companies", timeout=10)
        data = response.json()
        
        companies = data.get("companies", [])
        
        if companies:
            print(f"  {'Company Name':<40} {'Last Sync':<20} {'Sync Count':<10}")
            print(f"  {'-' * 70}")
            
            for company in companies:
                name = company.get("company_name", "Unknown")[:38]
                last_sync = company.get("last_sync_at", "Never")[:18] if company.get("last_sync_at") else "Never"
                sync_count = company.get("sync_count", 0)
                print(f"  {name:<40} {last_sync:<20} {sync_count:<10}")
            print()
        else:
            log("No companies synced yet", "INFO")
            
    except Exception as e:
        log(f"Error getting synced companies: {e}", "ERROR")

def run_timing_comparison(companies):
    """Run Sequential vs Parallel sync timing comparison"""
    print_section("TIMING COMPARISON: Sequential vs Parallel")
    
    if not companies:
        log("No companies selected", "WARNING")
        return
    
    company = companies[0]  # Use first company for comparison
    log(f"Testing with company: {company}", "INFO")
    
    results = {}
    
    # Test 1: Sequential Full Sync
    print(f"\n{Colors.CYAN}Test 1: Sequential Full Sync{Colors.END}")
    log("Starting Sequential sync...", "INFO")
    seq_time = run_full_sync([company], parallel=False)
    if seq_time:
        results['sequential'] = seq_time
        log(f"Sequential sync completed in {seq_time:.2f} seconds", "SUCCESS")
    else:
        log("Sequential sync failed", "ERROR")
        return
    
    # Small delay between tests
    print(f"\n{Colors.YELLOW}Waiting 3 seconds before parallel test...{Colors.END}")
    time.sleep(3)
    
    # Test 2: Parallel Full Sync
    print(f"\n{Colors.CYAN}Test 2: Parallel Full Sync{Colors.END}")
    log("Starting Parallel sync...", "INFO")
    par_time = run_full_sync([company], parallel=True)
    if par_time:
        results['parallel'] = par_time
        log(f"Parallel sync completed in {par_time:.2f} seconds", "SUCCESS")
    else:
        log("Parallel sync failed", "ERROR")
        return
    
    # Show comparison
    print_section("TIMING RESULTS")
    print(f"""
  {Colors.BOLD}{'Mode':<20} {'Time (seconds)':<15} {'Speed':<15}{Colors.END}
  {'-' * 50}
  {'Sequential':<20} {results['sequential']:<15.2f} {'baseline':<15}
  {'Parallel':<20} {results['parallel']:<15.2f} {f"{results['sequential']/results['parallel']:.2f}x faster" if results['parallel'] < results['sequential'] else 'slower':<15}
  {'-' * 50}
    """)
    
    speedup = results['sequential'] / results['parallel'] if results['parallel'] > 0 else 0
    if speedup > 1:
        log(f"Parallel sync is {speedup:.2f}x FASTER!", "SUCCESS")
    else:
        log(f"Parallel sync was slower (possible Tally bottleneck)", "WARNING")
    
    # Save to log
    log(f"TIMING: Sequential={results['sequential']:.2f}s, Parallel={results['parallel']:.2f}s, Speedup={speedup:.2f}x", "INFO")

def main_menu():
    """Show main menu"""
    print(f"""
  {Colors.BOLD}Options:{Colors.END}
  
  1. Full Sync - Sequential (original)
  2. Full Sync - Parallel (faster)
  3. Incremental Sync (only changes)
  4. TIMING TEST: Sequential vs Parallel
  5. Both (Full + Incremental test)
  6. Show Database Stats
  7. Show Synced Companies
  8. Check Connections
  q. Quit
    """)
    return input("  Select option: ").strip().lower()

def main():
    """Main function"""
    # Enable Windows terminal colors
    os.system('')
    
    print_header("TALLY SYNC TEST SCRIPT")
    log(f"Log file: {LOG_FILE}", "INFO")
    
    # Initial checks
    if not check_api_running():
        print(f"\n{Colors.RED}Please start the API server first: python run.py{Colors.END}\n")
        return
    
    if not check_tally_connection():
        print(f"\n{Colors.RED}Please ensure Tally is running and accessible{Colors.END}\n")
        return
    
    # Get companies
    companies = get_companies()
    if not companies:
        print(f"\n{Colors.RED}No companies found. Please open companies in Tally.{Colors.END}\n")
        return
    
    while True:
        choice = main_menu()
        
        if choice == 'q':
            log("Exiting...", "INFO")
            break
        elif choice == '1':
            selected = select_companies(companies)
            if selected:
                run_full_sync(selected, parallel=False)
                show_database_stats()
        elif choice == '2':
            selected = select_companies(companies)
            if selected:
                run_full_sync(selected, parallel=True)
                show_database_stats()
        elif choice == '3':
            selected = select_companies(companies)
            if selected:
                run_incremental_sync(selected)
                show_database_stats()
        elif choice == '4':
            selected = select_companies(companies)
            if selected:
                run_timing_comparison(selected)
                show_database_stats()
        elif choice == '5':
            selected = select_companies(companies)
            if selected:
                log("Running Full Sync first...", "INFO")
                run_full_sync(selected, parallel=True)
                show_database_stats()
                
                print(f"\n{Colors.YELLOW}Make some changes in Tally, then press Enter to run Incremental Sync...{Colors.END}")
                input()
                
                log("Running Incremental Sync...", "INFO")
                run_incremental_sync(selected)
                show_database_stats()
        elif choice == '6':
            show_database_stats()
        elif choice == '7':
            show_synced_companies()
        elif choice == '8':
            check_api_running()
            check_tally_connection()
            companies = get_companies()
        else:
            print(f"\n{Colors.RED}Invalid option. Please try again.{Colors.END}")
    
    print_header("TEST COMPLETED")
    log(f"Log saved to: {LOG_FILE}", "SUCCESS")
    print(f"\n  View log file: {LOG_FILE}\n")

if __name__ == "__main__":
    main()
