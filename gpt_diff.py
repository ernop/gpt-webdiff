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
import argparse
import re

CONFIG_FILE = 'config.json'
API_KEY_FILE = 'apikey.txt'
VALID_FREQUENCIES = ['daily', 'hourly', 'weekly']

from bs4 import BeautifulSoup

def extract_text_from_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    return soup.get_text(separator=' ', strip=True)

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def load_apikey():
    with open(API_KEY_FILE, 'r') as f:
        return f.read().strip()

def send_email(job_name, url, summary, diff_text, to_email):
    config = load_config()
    msg = MIMEText(f"Job: {job_name}\nURL: {url}\n\nSummary:\n{summary}\n\nDiff:\n{diff_text}")
    msg['Subject'] = f"Changes detected for {job_name} ({url})"
    msg['From'] = config['email']
    msg['To'] = to_email

    # Using Gmail's SMTP server
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    smtp_user = config['email']
    smtp_password = config['password']

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, [to_email], msg.as_string())
        server.quit()
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Failed to send email: {e}")

def download_url(url, name):
    output_file = f"data/{name}/{name}-{datetime.now().strftime('%Y%m%d-%H-%M-%S')}.html"
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
    context_text = extract_text_from_html(html_content)
    combined_text = f"Diff:\n{diff_text}\n\nContext:\n{context_text[:3000]}"  # Adjust the length as needed
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": f"Summarize the following diff of two webpages from high level down to all details. Extrude lots and lots of text in your output:\n\n{diff_text}"}
        ],
        max_tokens=1500
    )
    return response.choices[0].message['content'].strip()

def is_valid_url(url):
    regex = re.compile(
        r'^(?:http|ftp)s?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|'  # ...or ipv4
        r'\[?[A-F0-9]*:[A-F0-9:]+\]?)'  # ...or ipv6
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None

def add_job(name, url, frequency):
    if not name.isalnum():
        print("Error: Job name must be alphanumeric.")
        sys.exit(1)

    if not is_valid_url(url):
        print("Error: Invalid URL format.")
        sys.exit(1)

    if frequency not in VALID_FREQUENCIES:
        print(f"Error: Invalid frequency. Valid options are: {', '.join(VALID_FREQUENCIES)}")
        sys.exit(1)

    cron_entry = f"{frequency} /usr/bin/python3 /mnt/d/proj/gpt-diff/gpt_diff.py run {name} {url}\n"
    with open('.gptcron', 'a') as f:
        f.write(cron_entry)
    print(f"Job '{name}' added successfully.")

def save_email_to_disk(job_name, subject, body):
    email_dir = "emails"
    os.makedirs(email_dir, exist_ok=True)
    filename = os.path.join(email_dir, f"{job_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}.txt")
    with open(filename, 'w') as f:
        f.write(f"Subject: {subject}\n\n{body}")

def run_job(name, url):
    latest_file = download_url(url, name)
    last_file = get_last_file(name)

    if last_file:
        diff_text = compare_files(last_file, latest_file)
        if diff_text:
            with open(latest_file, 'r') as f:
                html_content = f.read()
            summary = summarize_diff(diff_text, html_content)
            send_email(name, url, summary, diff_text, load_config()['email'])

def list_jobs():
    if not os.path.exists('.gptcron'):
        print("No jobs found.")
        return

    with open('.gptcron', 'r') as f:
        jobs = f.readlines()

    if not jobs:
        print("No jobs found.")
        return

    print("Current monitoring jobs:")
    for job in jobs:
        if job.strip() and not job.startswith('#'):
            print(job.strip())

def check_cron():
    if os.path.exists('.gptcron'):
        with open('.gptcron', 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    parts = line.split()
                    if len(parts) >= 4:
                        frequency = parts[0]
                        command = parts[1]
                        name = parts[2]
                        url = parts[3]
                        if command == '/usr/bin/python3' and 'gpt_diff.py' in command:
                            run_job(name, url)

def setup_argparse():
    parser = argparse.ArgumentParser(
        description='GPT-Diff: Monitor web pages for changes and get detailed email summaries of those changes.'
    )
    subparsers = parser.add_subparsers(dest='command', help='Sub-command help')

    add_parser = subparsers.add_parser('add', help='Add a new URL to monitor. Usage: add <name> <URL> <frequency>')
    add_parser.add_argument('name', type=str, help='Alphanumeric label for this job')
    add_parser.add_argument('url', type=str, help='URL to monitor')
    add_parser.add_argument('frequency', type=str, choices=VALID_FREQUENCIES, help='Frequency to check the URL (e.g., daily, hourly, weekly)')

    run_parser = subparsers.add_parser('run', help='Run the monitoring for a specific URL. Usage: run <name> <URL>')
    run_parser.add_argument('name', type=str, help='Alphanumeric label for this job')
    run_parser.add_argument('url', type=str, help='URL to monitor')

    subparsers.add_parser('check_cron', help='Check and run all scheduled cron jobs. Usage: check_cron')
    subparsers.add_parser('list', help='List all monitoring jobs. Usage: list')

    return parser

if __name__ == "__main__":
    parser = setup_argparse()
    args = parser.parse_args()

    if args.command == "add":
        add_job(args.name, args.url, args.frequency)
    elif args.command == "run":
        run_job(args.name, args.url)
    elif args.command == "check_cron":
        check_cron()
    elif args.command == "list":
        list_jobs()
    else:
        parser.print_help()
