import os
import json
import re
import requests
import mysql.connector
from mysql.connector import Error
from datetime import datetime
from urllib.parse import quote

# First import gtilab project to gitea using "New Migration" in Web UI. Import also Wiky and LFS files
# then run this script. It imports Issues and comments to issues and also any attachements to issues and comments

# Script needs access to MySQL database of gitea!

# in config.py set important configuration settings

# read configuration
from config import GITLAB_URL,GITLAB_TOKEN,GITLAB_PROJECT,GITEA_URL,GITEA_TOKEN,GITEA_OWNER,GITEA_REPO,MYSQL_HOST,MYSQL_PORT,MYSQL_USER,MYSQL_PASSWORD,MYSQL_DATABASE

# try to connect to mysql
try:
    # Connect to the database
    connection = mysql.connector.connect(
        host=MYSQL_HOST,       # or your container hostname
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE     # use your actual database name
    )

    if connection.is_connected():
        pass
    else:
        print("not connected")
except Error as e:
    print(f"Error: {e}")

finally:
    pass



gitea_headers = {"Authorization": f"token {GITEA_TOKEN}"}


cursor = connection.cursor()
cursor.execute("SELECT id FROM repository WHERE lower_name = %s", (GITEA_REPO.lower(),))
repo_id = cursor.fetchone()[0]



# GitLab requires URL-encoded path
url = f"{GITLAB_URL}/api/v4/projects/{requests.utils.quote(GITLAB_PROJECT, safe='')}"
headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
response = requests.get(url, headers=headers)
js=json.loads(response.content)
id_project_gitlab=js['id'];

project_id = response.json()["id"]

def iso_time_to_db_time(iso_time):
    # Parse the ISO8601 string
    dt = datetime.strptime(iso_time, '%Y-%m-%dT%H:%M:%S.%fZ')
    return int(dt.timestamp())
#    # Format as MySQL datetime string (without milliseconds)
#    mysql_time = dt.strftime('%Y-%m-%d %H:%M:%S')
#    return mysql_time

def set_issue_db(issue_G,issue):
    # Example 2: Update issue creation timestamp
    issue_id = issue['id']
    created_at =iso_time_to_db_time(issue_G['created_at'])
    updated_at =iso_time_to_db_time(issue_G['updated_at'])
    closed_at =iso_time_to_db_time(issue_G['updated_at'])
    update_query = """
    UPDATE issue 
    SET 
        created_unix = %s,
        updated_unix = %s,
        closed_unix = %s
    WHERE id = %s
    """
    cursor.execute(update_query, (created_at,updated_at,closed_at, issue_id))
    connection.commit()

    if ('new_body' in issue):
        # there were uploads of attachments
        update_query = """
        UPDATE issue 
        SET 
            content = %s
        WHERE id = %s
        """
        cursor.execute(update_query, (issue['new_body'], issue_id))
        connection.commit()

    print(f"Issue {issue_id} updated!")




# === FETCH ISSUES FROM GITLAB ===
gitlab_headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
gitlab_issues_url = f"{GITLAB_URL}/api/v4/projects/{requests.utils.quote(GITLAB_PROJECT, safe='')}/issues?scope=all&per_page=10000"
print(gitlab_issues_url)

def get_all_gitlab_issues(gitlab_url, project_id, private_token):
    issues = []
    page = 1
    per_page = 100  # max GitLab allows

    while True:
        url = f"{gitlab_url}/api/v4/projects/{requests.utils.quote(GITLAB_PROJECT, safe='')}/issues"
        params = {
            "page": page,
            "per_page": per_page,
            "state": "all"
        }
        headers = {"PRIVATE-TOKEN": private_token}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        page_issues = response.json()
        if not page_issues:
            break
        issues.extend(page_issues)
        page += 1

    issues.reverse()
    return issues

gitlab_issues = get_all_gitlab_issues(GITLAB_URL,GITLAB_PROJECT,GITLAB_TOKEN)
sorted_gitlab_issues = sorted(gitlab_issues, key=lambda x: x["iid"])  # sort issues ascending by id, issues in gitea must be created in this order
print(len(gitlab_issues))
#user_input = input("Press Enter to continue...")

def get_next_gitea_issue_number(base_url, owner, repo, token):
    """
    Get next available issue number in Gitea repo.
    Args:
      base_url: Gitea server URL, e.g. 'https://gitea.example.com/api/v1'
      owner: repo owner username/org
      repo: repository name
      token: your Gitea personal access token (string)
    Returns:
      next issue number (int)
    """
    headers = {
        'Authorization': f'token {token}'
    }
    # We will page through issues (if many)
    page = 1
    per_page = 50
    max_number = 0

    while True:
        url = f"{base_url}/api/v1/repos/{owner}/{repo}/issues"
        params = {
            'state': 'all',    # get open and closed
            'page': page,
            'limit': per_page,
            'sort': 'created',  # sort by creation to ensure order
            'order': 'asc'
        }
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        issues = response.json()
        if not issues:
            break

        for issue in issues:
            if issue['number'] > max_number:
                print(max_number)
                max_number = issue['number']

        if len(issues) < per_page:
            break
        page += 1

    return max_number + 1

def create_gitea_issue(title, body, iid):
    # === CREATE ISSUE IN GITEA ===
    gitea_issue_url = f"{GITEA_URL}/api/v1/repos/{GITEA_OWNER}/{GITEA_REPO}/issues"
    print(gitea_issue_url)
    gitea_headers = {"Authorization": f"token {GITEA_TOKEN}"}
    if (title == "" and body == " "):
        payload = {
            "title": "auxiliary issue",
            "body": f"auxiliary",
        }
    else:
        payload = {
            "title": title,
            "body": f"{body}",
        }

    response = requests.post(gitea_issue_url, headers=gitea_headers, json=payload)
#    print("Response status:", response.status_code)
#    print("Response text:", response.text)
    created_issue = response.json()
    # solve attachements
    # STEP 1: Extract files
    matches = extract_gitlab_files(body)
    # STEP 2–4: Download, upload, rewrite
    if len(matches)>0:
        new_links = []
        for name, path in matches:
            if download_file(name, path):
                gitea_url = upload_to_gitea_issue(name,created_issue['number'])
                if gitea_url:
                    new_links.append((name, path, gitea_url))
                os.remove(name)
        # STEP 5: Rewrite comment
        new_body = rewrite_comment(body, new_links) 
        created_issue['new_body'] = new_body    # body of the comment will be updated later
    return created_issue


def extract_gitlab_files(comment):
    """Find all markdown-style upload links in the comment"""
    return re.findall(r'\[([^\]]+)\]\((/uploads/[^)]+)\)', comment)


def download_file(name, upload_path):
    """Download file from GitLab"""
    full_url = f"{GITLAB_URL}/api/v4/projects/{id_project_gitlab}{upload_path}"
    print(f"Downloading: {full_url}")
    resp = requests.get(full_url, headers=gitlab_headers)
    if resp.status_code == 200:
        with open(name, "wb") as f:
            f.write(resp.content)
        return True
    else:
        print(f"Download failed: {resp.status_code}")
        return False


def upload_to_gitea_issue(filename,issue_number):
    """Upload file to Gitea and return the new file URL
       type="/comments
    """

    url = f"{GITEA_URL}/api/v1/repos/{GITEA_OWNER}/{GITEA_REPO}/issues/{issue_number}/assets"

    files = {
    "attachment": (filename, open(filename, "rb")),
    "name": filename,
    }
    
    r = requests.post(url, headers=gitea_headers, files=files)
    if r.status_code == 201:
        js=json.loads(r.text)
        return js['browser_download_url'];
    else:
        print(f"Upload failed: {r.status_code}, {r.text}")
        return None

def upload_to_gitea_comment(filename,comment_number):
    """Upload file to Gitea and return the new file URL
       type="/comments
    """

    url = f"{GITEA_URL}/api/v1/repos/{GITEA_OWNER}/{GITEA_REPO}/issues/comments/{comment_number}/assets"

    files = {
    "attachment": (filename, open(filename, "rb")),
    "name": filename,
    }
    
    r = requests.post(url, headers=gitea_headers, files=files)
    if r.status_code == 201:
        js=json.loads(r.text)
        return js['browser_download_url'];
    else:
        print(f"Upload failed: {filename} {r.status_code}, {r.content}")
        return None


def rewrite_comment(comment, mappings):
    """Replace old links with new Gitea URLs"""
    for old_name, old_path, new_url in mappings:
        old_md = f"[{old_name}]({old_path})"
        new_md = f"[{old_name}]({new_url})"
        comment = comment.replace(old_md, new_md)
    return comment



def create_gitea_note(note,created_issue):

    gitea_headers = {"Authorization": f"token {GITEA_TOKEN}"}
    comment_body = f"{note['body']}"

    gitea_comment_url = f"{GITEA_URL}/api/v1/repos/{GITEA_OWNER}/{GITEA_REPO}/issues/{created_issue['number']}/comments"
    comment_payload = {"body": comment_body}

    comment_response = requests.post(gitea_comment_url, headers=gitea_headers, json=comment_payload)

    if comment_response.status_code != 201:
            print("Failed to create comment:", comment_response.status_code, comment_response.text)
    created_comment = comment_response.json()
    # solve attachements
    # STEP 1: Extract files
    matches = extract_gitlab_files(comment_body)
    # STEP 2–4: Download, upload, rewrite
    if len(matches)>0:
        new_links = []
        for name, path in matches:
            if download_file(name, path):
                gitea_url = upload_to_gitea_comment(name,created_comment['id'])
                if gitea_url:
                    new_links.append((name, path, gitea_url))
                os.remove(name)
        # STEP 5: Rewrite comment
        new_body = rewrite_comment(comment_body, new_links) 
        created_comment['new_body'] = new_body    # body of the comment will be updated later

    set_comment_db(note,created_comment)






def set_comment_db(note,comment):
    # Example 2: Update issue creation timestamp
    comment_id = comment['id']
    created_at =iso_time_to_db_time(note['created_at'])
    updated_at =iso_time_to_db_time(note['updated_at'])
    update_query = """
    UPDATE comment 
    SET 
        created_unix = %s,
        updated_unix = %s
    WHERE id = %s
    """
    cursor.execute(update_query, (created_at,updated_at, comment_id))
    connection.commit()
    
    if ('new_body' in comment):
        # there were uploads of attachments
        update_query = """
        UPDATE comment 
        SET 
            content = %s
        WHERE id = %s
        """
        cursor.execute(update_query, (comment['new_body'], comment_id))
        connection.commit()
    print(f"Comment {comment_id} updated!")


# Get current next issue number from Gitea (start at 1 if empty)
current_number = get_next_gitea_issue_number(GITEA_URL,GITEA_OWNER,GITEA_REPO,GITEA_TOKEN)
print("current gitea issue number",current_number)
if (current_number > sorted_gitlab_issues[-1]["iid"]):
    print("Curent gitea issue number is greater than first gitlab issue number")
    print("first gitlab issues will be skipped")
else:
    print(f"first gitea issue to be created is {current_number}")
for issue in sorted_gitlab_issues:
    title = issue["title"]
    iid = issue["iid"]
    if (iid<current_number):
        print(f"skipping issue {iid}")
        continue
    body = issue["description"] or ""
    state = issue["state"]  # open or closed

    print(f"\n-----------------------------------\nMigrating issue: {iid} {title} [{state}]")

#    if (current_number < id):
#        # must create auxiliary issues
    created_issue=create_gitea_issue(title, body, iid)
    if created_issue['number'] != iid:
        print("Created issue number is not the same as gitlab issue number")

    set_issue_db(issue,created_issue)

    if state == "closed":
        issue_number = created_issue["number"]
        close_url = f"{GITEA_URL}/api/v1/repos/{GITEA_OWNER}/{GITEA_REPO}/issues/{issue_number}"
        requests.patch(close_url, headers=gitea_headers, json={"state": "closed"})

    # Get GitLab issue comments (notes)
    gitlab_notes_url = f"{GITLAB_URL}/api/v4/projects/{requests.utils.quote(GITLAB_PROJECT, safe='')}/issues/{issue['iid']}/notes"
    notes_response = requests.get(gitlab_notes_url, headers=gitlab_headers)
    notes = notes_response.json()

    for note in notes:
        # Skip system notes (like "closed the issue")
        #if note.get("system"):
        #    continue
        create_gitea_note(note,created_issue)


if connection.is_connected():
    cursor.close()
    connection.close()
