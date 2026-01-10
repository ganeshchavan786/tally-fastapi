"""
Audit Trail Test Script
========================
Tests DELETE, UPDATE, INSERT detection with audit logging.

Run: python test_audit_trail.py
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import requests
import json
import time
from datetime import datetime

BASE_URL = "http://localhost:8000"
COMPANY = "OM ENGINEERING"

def print_header(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

def print_result(test_name, status, details=""):
    icon = "✅" if status else "❌"
    print(f"{icon} {test_name}: {details}")

def get_sync_status():
    """Get current sync status"""
    r = requests.get(f"{BASE_URL}/api/sync/status")
    return r.json()

def wait_for_sync_complete(timeout=120):
    """Wait for sync to complete"""
    start = time.time()
    while time.time() - start < timeout:
        status = get_sync_status()
        if status.get("status") == "completed":
            return status
        if status.get("status") == "failed":
            return status
        print(f"  Sync progress: {status.get('progress', 0)}% - {status.get('current_table', '')}")
        time.sleep(3)
    return {"status": "timeout"}

def run_incremental_sync():
    """Run incremental sync"""
    print(f"\n🔄 Running incremental sync for {COMPANY}...")
    r = requests.post(f"{BASE_URL}/api/sync/incremental?company={COMPANY.replace(' ', '%20')}")
    print(f"  Started: {r.json()}")
    return wait_for_sync_complete()

def get_audit_stats():
    """Get audit statistics"""
    r = requests.get(f"{BASE_URL}/api/audit/stats?company={COMPANY.replace(' ', '%20')}")
    return r.json()

def get_audit_history(action=None, table=None, limit=20):
    """Get audit history with filters"""
    params = [f"limit={limit}", f"company={COMPANY.replace(' ', '%20')}"]
    if action:
        params.append(f"action={action}")
    if table:
        params.append(f"table_name={table}")
    
    url = f"{BASE_URL}/api/audit/history?{'&'.join(params)}"
    r = requests.get(url)
    return r.json()

def get_deleted_records(table=None, limit=20):
    """Get deleted records"""
    params = [f"limit={limit}", f"company={COMPANY.replace(' ', '%20')}"]
    if table:
        params.append(f"table_name={table}")
    
    url = f"{BASE_URL}/api/audit/deleted?{'&'.join(params)}"
    r = requests.get(url)
    return r.json()

def get_audit_sessions(limit=5):
    """Get recent audit sessions"""
    r = requests.get(f"{BASE_URL}/api/audit/sessions?limit={limit}&company={COMPANY.replace(' ', '%20')}")
    return r.json()

def get_record_history(table, guid):
    """Get history of specific record"""
    r = requests.get(f"{BASE_URL}/api/audit/record/{table}/{guid}")
    return r.json()

def test_audit_trail():
    """Main test function"""
    print_header("🔍 AUDIT TRAIL TEST")
    print(f"Company: {COMPANY}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Step 1: Get initial audit stats
    print_header("Step 1: Initial Audit Stats (Before Sync)")
    initial_stats = get_audit_stats()
    print(f"  Actions: {initial_stats.get('by_action', {})}")
    print(f"  Pending deleted records: {initial_stats.get('pending_deleted_records', 0)}")
    
    initial_inserts = initial_stats.get('by_action', {}).get('INSERT', 0)
    initial_updates = initial_stats.get('by_action', {}).get('UPDATE', 0)
    initial_deletes = initial_stats.get('by_action', {}).get('DELETE', 0)
    
    # Step 2: Run incremental sync
    print_header("Step 2: Running Incremental Sync")
    sync_result = run_incremental_sync()
    
    if sync_result.get("status") == "completed":
        print_result("Incremental Sync", True, f"Rows processed: {sync_result.get('rows_processed', 0)}")
    else:
        print_result("Incremental Sync", False, f"Status: {sync_result.get('status')}")
        return
    
    # Step 3: Get updated audit stats
    print_header("Step 3: Audit Stats (After Sync)")
    final_stats = get_audit_stats()
    print(f"  Actions: {final_stats.get('by_action', {})}")
    print(f"  Tables: {final_stats.get('by_table', {})}")
    print(f"  Pending deleted records: {final_stats.get('pending_deleted_records', 0)}")
    
    final_inserts = final_stats.get('by_action', {}).get('INSERT', 0)
    final_updates = final_stats.get('by_action', {}).get('UPDATE', 0)
    final_deletes = final_stats.get('by_action', {}).get('DELETE', 0)
    
    new_inserts = final_inserts - initial_inserts
    new_updates = final_updates - initial_updates
    new_deletes = final_deletes - initial_deletes
    
    print(f"\n  📊 Changes in this sync:")
    print(f"     New INSERTs: {new_inserts}")
    print(f"     New UPDATEs: {new_updates}")
    print(f"     New DELETEs: {new_deletes}")
    
    # Step 4: Check recent audit entries
    print_header("Step 4: Recent Audit Entries")
    
    # Check INSERTs
    if new_inserts > 0:
        inserts = get_audit_history(action="INSERT", limit=5)
        print(f"\n  📥 Recent INSERTs ({inserts.get('count', 0)} total):")
        for record in inserts.get('records', [])[:5]:
            print(f"     - {record.get('table_name')}: {record.get('record_name')} (GUID: {record.get('record_guid', '')[:20]}...)")
    
    # Check UPDATEs
    if new_updates > 0:
        updates = get_audit_history(action="UPDATE", limit=5)
        print(f"\n  ✏️ Recent UPDATEs ({updates.get('count', 0)} total):")
        for record in updates.get('records', [])[:5]:
            changed = record.get('changed_fields', [])
            print(f"     - {record.get('table_name')}: {record.get('record_name')}")
            if changed:
                print(f"       Changed fields: {changed}")
    
    # Check DELETEs
    if new_deletes > 0 or final_deletes > 0:
        deletes = get_audit_history(action="DELETE", limit=5)
        print(f"\n  🗑️ Recent DELETEs ({deletes.get('count', 0)} total):")
        for record in deletes.get('records', [])[:5]:
            print(f"     - {record.get('table_name')}: {record.get('record_name')}")
    
    # Step 5: Check deleted records for recovery
    print_header("Step 5: Deleted Records (Available for Recovery)")
    deleted = get_deleted_records(limit=10)
    print(f"  Total recoverable records: {deleted.get('count', 0)}")
    
    if deleted.get('records'):
        print("\n  Sample deleted records:")
        for record in deleted.get('records', [])[:5]:
            print(f"     ID: {record.get('id')} | {record.get('table_name')}: {record.get('record_name')}")
    
    # Step 6: Check audit sessions
    print_header("Step 6: Recent Sync Sessions")
    sessions = get_audit_sessions(limit=5)
    print(f"  Total sessions: {sessions.get('count', 0)}")
    
    if sessions.get('sessions'):
        print("\n  Recent sessions:")
        for session in sessions.get('sessions', [])[:3]:
            print(f"     - {session.get('sync_session_id', '')[:40]}...")
            print(f"       Type: {session.get('sync_type')} | Changes: {session.get('total_changes', 0)}")
    
    # Final Summary
    print_header("🎉 AUDIT TRAIL TEST - SUMMARY")
    
    print("\n┌─────────────────────────────────────────────────────────────┐")
    print("│                    TEST RESULTS                             │")
    print("├─────────────────────┬───────────┬───────────────────────────┤")
    print("│ Feature             │ Status    │ Details                   │")
    print("├─────────────────────┼───────────┼───────────────────────────┤")
    
    # Incremental Sync
    sync_ok = sync_result.get("status") == "completed"
    print(f"│ Incremental Sync    │ {'✅ PASS' if sync_ok else '❌ FAIL'}   │ {sync_result.get('rows_processed', 0)} rows processed         │")
    
    # DELETE Detection
    delete_ok = final_deletes > 0
    print(f"│ DELETE Detection    │ {'✅ PASS' if delete_ok else '⚠️ NONE'}   │ {final_deletes} records logged          │")
    
    # UPDATE Detection
    update_ok = final_updates > 0
    print(f"│ UPDATE Detection    │ {'✅ PASS' if update_ok else '⚠️ NONE'}   │ {final_updates} records logged          │")
    
    # INSERT Detection
    insert_ok = final_inserts > 0
    print(f"│ INSERT Detection    │ {'✅ PASS' if insert_ok else '⚠️ NONE'}   │ {final_inserts} records logged          │")
    
    # Audit Logging
    audit_ok = (final_inserts + final_updates + final_deletes) > 0
    print(f"│ Audit Logging       │ {'✅ PASS' if audit_ok else '❌ FAIL'}   │ {final_inserts + final_updates + final_deletes} total entries          │")
    
    # Deleted Records Recovery
    recovery_ok = final_stats.get('pending_deleted_records', 0) > 0
    print(f"│ Recovery Storage    │ {'✅ PASS' if recovery_ok else '⚠️ NONE'}   │ {final_stats.get('pending_deleted_records', 0)} records stored        │")
    
    # Session Tracking
    session_ok = sessions.get('count', 0) > 0
    print(f"│ Session Tracking    │ {'✅ PASS' if session_ok else '❌ FAIL'}   │ {sessions.get('count', 0)} sessions tracked       │")
    
    print("└─────────────────────┴───────────┴───────────────────────────┘")
    
    # Table-wise breakdown
    if final_stats.get('by_table'):
        print("\n📊 Audit Entries by Table:")
        print("┌────────────────────────┬─────────┐")
        print("│ Table                  │ Count   │")
        print("├────────────────────────┼─────────┤")
        for table, count in sorted(final_stats.get('by_table', {}).items(), key=lambda x: -x[1])[:10]:
            print(f"│ {table:<22} │ {count:>7} │")
        print("└────────────────────────┴─────────┘")
    
    # API Endpoints tested
    print("\n🔗 API Endpoints Tested:")
    print("  ✅ GET  /api/audit/stats")
    print("  ✅ GET  /api/audit/history")
    print("  ✅ GET  /api/audit/deleted")
    print("  ✅ GET  /api/audit/sessions")
    print("  ✅ POST /api/sync/incremental")
    
    print("\n" + "=" * 60)
    print("  Test completed at", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print("=" * 60)

if __name__ == "__main__":
    test_audit_trail()
