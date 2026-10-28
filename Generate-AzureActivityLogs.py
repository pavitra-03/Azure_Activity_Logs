import os
import requests
import secrets
import string
from datetime import datetime

# ============================================================
# CONFIGURATION FROM ENVIRONMENT VARIABLES (GITHUB SECRETS)
# ============================================================

TENANT_ID = os.environ.get("AZURE_TENANT_ID")
CLIENT_ID = os.environ.get("AZURE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("AZURE_CLIENT_SECRET")
DOMAIN = os.environ.get("AZURE_DOMAIN", "Sacumentech432.onmicrosoft.com")

if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET]):
    print("[-] ERROR: Missing required Azure credentials.")
    print("Ensure AZURE_TENANT_ID, AZURE_CLIENT_ID, and AZURE_CLIENT_SECRET are set.")
    exit(1)

GRAPH_URL = "https://graph.microsoft.com/v1.0"
USERS_PER_DAY = 5
GROUPS_PER_DAY = 2

# ============================================================
# AUTHENTICATION
# ============================================================

token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
token_data = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "scope": "https://graph.microsoft.com/.default",
    "grant_type": "client_credentials"
}

print("[+] Authenticating with Microsoft Graph API...")
response = requests.post(token_url, data=token_data, timeout=30)

if response.status_code != 200:
    print("[-] ERROR: Authentication failed")
    print(response.text)
    exit(1)

access_token = response.json()["access_token"]
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json"
}
print("[+] Authentication successful.")

# ============================================================
# UTILITIES
# ============================================================

today = datetime.now().strftime("%Y%m%d")
print(f"[+] Target Run Date: {today}")

def generate_password():
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(chars) for _ in range(18))

# ============================================================
# CREATE GROUPS
# ============================================================

created_groups = []
print("\n[+] Creating security groups...")

for i in range(1, GROUPS_PER_DAY + 1):
    group_name = f"Securonix-Security-Group-{today}-{i:02d}"
    group_data = {
        "displayName": group_name,
        "mailEnabled": False,
        "mailNickname": f"SecuronixSecurity{today}{i:02d}",
        "securityEnabled": True
    }

    res = requests.post(f"{GRAPH_URL}/groups", headers=headers, json=group_data, timeout=30)
    if res.status_code == 201:
        group = res.json()
        created_groups.append({"id": group["id"], "displayName": group["displayName"]})
        print(f"  SUCCESS: Group created -> {group_name}")
    else:
        print(f"  ERROR: Group creation failed -> {group_name}")
        print(f"  Details: {res.text}")

# ============================================================
# CREATE USERS
# ============================================================

created_users = []
print("\n[+] Creating test users...")

for i in range(1, USERS_PER_DAY + 1):
    username = f"securonix.test.{today}.{i:02d}"
    display_name = f"Securonix Test User {today}-{i:02d}"
    upn = f"{username}@{DOMAIN}"

    user_data = {
        "accountEnabled": True,
        "displayName": display_name,
        "mailNickname": username.replace(".", ""),
        "userPrincipalName": upn,
        "passwordProfile": {
            "forceChangePasswordNextSignIn": False,
            "password": generate_password()
        }
    }

    res = requests.post(f"{GRAPH_URL}/users", headers=headers, json=user_data, timeout=30)
    if res.status_code == 201:
        user = res.json()
        created_users.append({
            "id": user["id"],
            "displayName": user["displayName"],
            "userPrincipalName": user["userPrincipalName"]
        })
        print(f"  SUCCESS: User created -> {display_name}")
    else:
        print(f"  ERROR: User creation failed -> {display_name}")
        print(f"  Details: {res.text}")

# ============================================================
# ADD USERS TO GROUPS
# ============================================================

print("\n[+] Assigning users to groups...")

for index, user in enumerate(created_users):
    if not created_groups:
        break

    group = created_groups[index % len(created_groups)]
    member_url = f"{GRAPH_URL}/groups/{group['id']}/members/$ref"
    member_data = {
        "@odata.id": f"{GRAPH_URL}/directoryObjects/{user['id']}"
    }

    res = requests.post(member_url, headers=headers, json=member_data, timeout=30)
    if res.status_code == 204:
        print(f"  SUCCESS: {user['displayName']} added to {group['displayName']}")
    else:
        print(f"  ERROR: Could not add {user['displayName']} to group")
        print(f"  Details: {res.text}")

# ============================================================
# VALIDATION
# ============================================================

print("\n[+] Running directory validation queries...")

users_res = requests.get(f"{GRAPH_URL}/users?$top=100", headers=headers, timeout=30)
if users_res.status_code == 200:
    count = len(users_res.json().get("value", []))
    print(f"  SUCCESS: Users API returned {count} records.")
else:
    print("  ERROR: Users API validation failed.")

groups_res = requests.get(f"{GRAPH_URL}/groups?$top=100", headers=headers, timeout=30)
if groups_res.status_code == 200:
    count = len(groups_res.json().get("value", []))
    print(f"  SUCCESS: Groups API returned {count} records.")
else:
    print("  ERROR: Groups API validation failed.")

print("\n" + "=" * 40)
print(" AZURE AD DATA GENERATION COMPLETE")
print("=" * 40)
print(f"Users created : {len(created_users)}")
print(f"Groups created: {len(created_groups)}")
