import os
import sys
import subprocess
import hashlib
import difflib
import smtplib
import json
from email.mime.text import MIMEText
from datetime import datetime
import openai

CONFIG_FILE = 'config.json'
API_KEY_FILE = 'apikey.txt'

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def load_apikey():
    with open(API_KEY_FILE, 'r') as f:
        return f.read().strip()

def send_email(subject, body, to_email):
    config = load_config()
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = config['email']
    msg['To'] = to_email

    with smtplib.SMTP('localhost') as server:
        server.sendmail(config['email'], [to_email], msg.as_string())

def download_url(url, name):
    output_file = f"data/{name}/{name}-{datetime.now().strftime('%Y%m%d%H%M%S')}.html"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    subprocess.run(['wget', '-O', output_file, url])
    return output_file

def compute_hash(file_path):
    hasher = hashlib.md5()
    with open(file_path, 'rb') as f:
        hasher.update(f.read())
    return hasher.hexdigest()

def get_last_file(name):
    files = sorted([f for f in os.listdir(f"data/{name}") if os.path.isfile(os.path.join(f"data/{name}", f))])
    return os.path.join(f"data/{name}", files[-1]) if files else None

def compare_files(file1, file2):
    with open(file1, 'r') as f1, open(file2, 'r') as f2:
        diff = difflib.unified_diff(f1.readlines(), f2.readlines())
    return ''.join(diff)

def summarize_diff(diff_text):
    openai.api_key = load_apikey()
    response = openai.Completion.create(
        engine="gpt-4o",
        prompt=f"Summarize the following diff of two webpages from high level down to all details. Extrude lots and lots of text in your output:\n\n{diff_text}",
        max_tokens=1500
    )
    return response.choices[0].text.strip()

def add_job(name, url, frequency):
    cron_entry = f"{frequency} /usr/bin/python3 /mnt/d/proj/gpt-diff/gpt-diff/gpt_diff.py run {name} {url}\n"
    with open('.gptcron', 'a') as f:
        f.write(cron_entry)

def run_job(name, url):
    latest_file = download_url(url, name)
    last_file = get_last_file(name)

    if last_file:
        diff_text = compare_files(last_file, latest_file)
        if diff_text:
            summary = summarize_diff(diff_text)
            send_email(f"Changes detected for {name}", f"Summary:\n{summary}\n\nDiff:\n{diff_text}", load_config()['email'])

def check_cron():
    import ipdb;ipdb.set_trace()
    if os.path.exists('.gptcron'):
        with open('.gptcron', 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    parts = line.split()
                    if len(parts) >= 3:
                        frequency = parts[0]
                        command = parts[1]
                        name = parts[2]
                        url = parts[3]
                        if command == '/usr/bin/python3' and 'gpt_diff.py' in parts[1]:
                            run_job(name, url)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: gpt_diff.py <add|run|check_cron> <name> <URL> [frequency]")
        sys.exit(1)

    command = sys.argv[1]
    name = sys.argv[2]

    if command == "add":
        if len(sys.argv) != 5:
            print("Usage: gpt_diff.py add <name> <URL> <frequency>")
            sys.exit(1)
        url = sys.argv[3]
        frequency = sys.argv[4]
        add_job(name, url, frequency)
    elif command == "run":
        if len(sys.argv) != 4:
            print("Usage: gpt_diff.py run <name> <URL>")
            sys.exit(1)
        url = sys.argv[3]
        run_job(name, url)
    elif command == "check_cron":
        check_cron()
    else:
        print("Invalid command")
        sys.exit(1)
