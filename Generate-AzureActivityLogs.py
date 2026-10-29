import os
import json
import time
import csv
from datetime import datetime, timezone
from azure.identity import DefaultAzureCredential
from azure.mgmt.resource.resources import ResourceManagementClient
from azure.mgmt.monitor import MonitorManagementClient

# ============================================================
# CONFIGURATION
# ============================================================
SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID", "17654be6-a05c-4586-a5d9-e86cee340a80")
RESOURCE_GROUP_NAME = os.environ.get("AZURE_RESOURCE_GROUP", "ActivityLog-Test-RG")
TAG_NAME = "Validation"
UPDATES_TO_GENERATE = 10

# Output folder setup inside repository
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
csv_path = os.path.join(OUTPUT_DIR, f"AzureActivityLogs_{run_id}.csv")

def main():
    print("[+] Initializing Azure SDK Clients...")
    credential = DefaultAzureCredential()
    
    resource_client = ResourceManagementClient(credential, SUBSCRIPTION_ID)
    monitor_client = MonitorManagementClient(credential, SUBSCRIPTION_ID)

    resource_id = f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP_NAME}"
    run_start_utc = datetime.now(timezone.utc)

    print(f"[+] Generating {UPDATES_TO_GENERATE} tag updates on '{RESOURCE_GROUP_NAME}'...")

    # 1. Update Tags on Resource Group to Trigger Activity Logs
    for i in range(1, UPDATES_TO_GENERATE + 1):
        tag_value = f"Validation-{run_id}-{i}"
        
        # Fixed for modern Azure SDK LRO (Long Running Operation)
        poller = resource_client.tags.begin_create_or_update_at_scope(
            scope=resource_id,
            parameters={
                "properties": {
                    "tags": {TAG_NAME: tag_value}
                }
            }
        )
        poller.result()  # Wait for operation to complete
        
        print(f"  SUCCESS: Tag update {i}/{UPDATES_TO_GENERATE} applied.")
        time.sleep(2)

    # 2. Wait for Azure Activity Log propagation
    print("[+] Waiting 25 seconds for Azure Activity Logs to propagate...")
    time.sleep(25)

    # 3. Query Activity Logs
    print("[+] Fetching Activity Logs...")
    filter_query = f"eventTimestamp ge '{run_start_utc.isoformat()}' and resourceGroupName eq '{RESOURCE_GROUP_NAME}'"
    
    logs = monitor_client.activity_logs.list(filter=filter_query)

    exported_rows = []
    for event in logs:
        exported_rows.append({
            "EventTimestampUtc": event.event_timestamp.isoformat() if event.event_timestamp else "",
            "Operation": event.operation_name.value if event.operation_name else "",
            "Status": event.status.value if event.status else "",
            "Caller": event.caller if event.caller else "",
            "ResourceGroupName": event.resource_group_name if event.resource_group_name else "",
            "ResourceId": event.resource_id if event.resource_id else "",
            "CorrelationId": event.correlation_id if event.correlation_id else ""
        })

    # 4. Save to CSV
    if exported_rows:
        headers = list(exported_rows[0].keys())
        with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(exported_rows)
            
        print(f"[+] SUCCESS: Exported {len(exported_rows)} activity log records to '{csv_path}'")
    else:
        print("[-] WARNING: No activity logs retrieved in this window.")

if __name__ == "__main__":
    main()
