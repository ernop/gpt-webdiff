#!/usr/bin/env python3

# Global notes: never use docstrings. Never remove these - they are guides for future rewrites when I paste in the entire file.
# sample of the contents of .gptcron:
# weekly shikoku https://en.wikipedia.org/wiki/Shikoku 00000000000000

import os
import sys
import html
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
from bs4 import BeautifulSoup
import time
import shutil

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

script_path = os.path.abspath(__file__)
script_dir = os.path.dirname(script_path)
print('changing to:',script_dir)
os.chdir(script_dir)

BACKUP_DIR = 'gptcron_backups'
CONFIG_FILE = 'config.json'
API_KEY_FILE = 'apikey.txt'
VALID_FREQUENCIES = ['minutely', 'hourly', 'daily', 'weekly', 'monthly']
LOG_FILE = 'gpt_diff.log'
CRON_FILE = '.gptcron'
EMAIL_BODY_TEMPLATE='email_body_template.txt'

def parse_cron_file():
    jobs = []
    if not os.path.exists(CRON_FILE):
        return jobs

    with open(CRON_FILE, 'r') as f:
        lines = f.readlines()

    for line in lines:
        if line.strip() and not line.startswith('#'):
            parts = line.split()
            if len(parts) >= 3:
                frequency = parts[0]
                name = parts[1]
                url = parts[2]
                date_added = parts[3] if len(parts) > 3 else "00000000000000"
                jobs.append({"frequency": frequency, "name": name, "url": url, "date_added": date_added})
    return jobs

def backup_cron_file():
    if not os.path.exists(CRON_FILE):
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup_file = os.path.join(BACKUP_DIR, f"gptcron_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}")
    shutil.copy(CRON_FILE, backup_file)
    log_message(f"Backup created: {backup_file}")

def extract_text_from_html(html_content):
    return BeautifulSoup(html_content, 'html.parser').get_text(separator=' ', strip=True)

def load_apikey():
    with open(API_KEY_FILE, 'r') as f:
        return f.read().strip()

def save_email_to_disk(job_name, subject, body):
    email_dir = "emails"
    os.makedirs(email_dir, exist_ok=True)
    filename = os.path.join(email_dir, f"{job_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}.txt")
    with open(filename, 'w') as f:
        f.write(f"Subject: {subject}\n\n{body}")

def create_email_content(job_name, url, summary, diff_text, score, brief_summary):
    #~ import ipdb;ipdb.set_trace()
    escaped_diff_text = html.escape(diff_text)
    subject = f"GPT-diff | {job_name} | Score: {score} | {brief_summary}"
    with open(EMAIL_BODY_TEMPLATE, 'r') as body_file:
        body_template = body_file.read().strip()

    body = body_template.format(
        job_name=job_name,
        url=url,
        summary=summary,
        diff_text=escaped_diff_text,
        brief_summary=brief_summary
    )

    return subject, body



def send_email(job_name, subject, body, to_email):
    config = load_config()
    msg = MIMEText(body, 'html')
    msg['Subject'] = subject
    msg['From'] = config['email']
    msg['To'] = to_email
    save_email_to_disk(job_name, subject, body)
    log_message(f"Sending Email: Subject: {subject}, Body: {body[:1000]}...")

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
        log_message(f"Email sent to {to_email} for job {job_name}")
    except Exception as e:
        print(f"Failed to send email: {e}")
        log_message(f"Failed to send email to {to_email} for job {job_name}: {e}")

def download_url(url, name):
    output_file = f"data/{name}/{name}-{datetime.now().strftime('%Y%m%d-%H-%M-%S')}.html"
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    subprocess.run(['wget', '-O', output_file, '--user-agent', user_agent, url])
    return output_file

def get_last_file(name):
    job_dir = f"data/{name}"
    if not os.path.exists(job_dir):
        return None, None

    files = sorted([f for f in os.listdir(job_dir) if os.path.isfile(os.path.join(job_dir, f))])
    if files:
        last_file = files[-1]
        last_run_time = datetime.strptime(last_file, f"{name}-%Y%m%d-%H-%M-%S.html").timestamp()
        return os.path.join(job_dir, last_file), last_run_time
    return None, None

def compare_files(file1, file2):
    with open(file1, 'r') as f1, open(file2, 'r') as f2:
        return ''.join(difflib.unified_diff(f1.readlines(), f2.readlines()))

def is_valid_url(url):
    regex = re.compile(
        r'^(?:http|ftp)s?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|'
        r'\[?[A-F0-9]*:[A-F0-9:]+\]?)'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None

def add_job(name, url, frequency):
    if not re.match(r'^[a-zA-Z0-9-]+$', name):
        print(f"Error: Invalid job name: name must be alphanumeric.")
        sys.exit(1)
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    if not is_valid_url(url):
        print("Error: Invalid URL format.")
        sys.exit(1)
    if frequency not in VALID_FREQUENCIES:
        print(f"Error: Invalid frequency, must be 'hourly', 'daily', 'weekly', 'minutely'")
        sys.exit(1)

    jobs = parse_cron_file()
    if any(job['name'] == name for job in jobs):
        print(f"Error: A job with the name '{name}' already exists.")
        return

    backup_cron_file()
    cron_entry = f"{frequency} {name} {url} {datetime.now().strftime('%Y%m%d%H%M%S')}\n"
    with open(CRON_FILE, 'a') as f:
        f.write(cron_entry)
    print(f"Job '{name}' added successfully.")
    log_message(f"Job added: {name}, {url}, {frequency}")

def remove_job(name):
    jobs = parse_cron_file()
    backup_cron_file()
    with open(CRON_FILE, 'w') as f:
        for job in jobs:
            if job["name"] != name:
                f.write(f"{job['frequency']} {job['name']} {job['url']} {job['date_added']}\n")
            else:
                log_message(f"Job removed: {job['name']}")

    print(f"Job '{name}' removed successfully.")

def change_frequency(name, direction):
    jobs = parse_cron_file()
    job = next((job for job in jobs if job["name"] == name), None)
    if not job:
        print(f"No job found with the name {name}")
        return

    current_index = VALID_FREQUENCIES.index(job["frequency"])

    num_dir=-1 if direction=='increase' else 1

    new_index = current_index + (num_dir)

    if new_index < 0 or new_index >= len(VALID_FREQUENCIES):
        print(f"Error: Cannot change frequency. Current frequency is '{job['frequency']}' and no {'lower' if direction == 'decrease' else 'higher'} frequency available.")
        return

    new_frequency = VALID_FREQUENCIES[new_index]
    job["frequency"] = new_frequency
    backup_cron_file()

    with open(CRON_FILE, 'w') as f:
        for j in jobs:
            f.write(f"{j['frequency']} {j['name']} {j['url']} {j['date_added']}\n")

    print(f"Job '{name}' frequency changed from '{VALID_FREQUENCIES[current_index]}' to '{new_frequency}' successfully.")
    log_message(f"Job '{name}' frequency changed from '{VALID_FREQUENCIES[current_index]}' to '{new_frequency}'")

def log_message(message):
    with open(LOG_FILE, 'a') as log_file:
        msg=f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n"
        print(msg)
        log_file.write(msg)

def list_jobs(sort_by=None):
    jobs = parse_cron_file()
    if not jobs:
        print("No jobs found.")
        return

    if sort_by == "date":
        jobs.sort(key=lambda x: x["date_added"])
    elif sort_by == "url":
        jobs.sort(key=lambda x: x["url"].split('//')[-1])
    elif sort_by == "name":
        jobs.sort(key=lambda x: x["name"].lower())

    max_lengths = [max(len(str(job[key])) for job in jobs) for key in ["frequency", "name", "url", "date_added"]]

    print("Current monitoring jobs:")
    print(f"{'Frequency'.ljust(max_lengths[0])}  {'Name'.ljust(max_lengths[1])}  {'URL'.ljust(max_lengths[2])}  {'Date Added'.ljust(max_lengths[3])}")
    print("=" * (sum(max_lengths) + 6))
    for job in jobs:
        print(f"{job['frequency'].ljust(max_lengths[0])}  {job['name'].ljust(max_lengths[1])}  {job['url'].ljust(max_lengths[2])}  {job['date_added'].ljust(max_lengths[3])}")

def save_sorted_jobs(sort_by):
    jobs = parse_cron_file()
    if not jobs:
        print("No jobs found.")
        return

    if sort_by == "date":
        jobs.sort(key=lambda x: x["date_added"])
    elif sort_by == "url":
        jobs.sort(key=lambda x: x["url"].split('//')[-1])
    elif sort_by == "name":
        jobs.sort(key=lambda x: x["name"])

    backup_cron_file()
    with open(CRON_FILE, 'w') as f:
        for job in jobs:
            f.write(f"{job['frequency']} {job['name']} {job['url']} {job['date_added']}\n")

    print(f"Jobs sorted by {sort_by} and saved back to {CRON_FILE}")
    log_message(f"Jobs sorted by {sort_by} and saved back to {CRON_FILE}")

def run_job(name):
    jobs = parse_cron_file()
    job = next((job for job in jobs if job["name"] == name), None)

    if not job:
        print(f"No job found with the name {name}")
        return False

    url = job["url"]
    metadata = load_metadata()
    last_successful_time = metadata.get(name, {}).get("last_successful_time", None)
    latest_file = download_url(url, name)
    changes_detected = False

    job_dir = f"data/{name}"
    files = sorted([f for f in os.listdir(job_dir) if os.path.isfile(os.path.join(job_dir, f))])

    if last_successful_time:
        last_successful_file = next((f for f in files if datetime.strptime(f, f"{name}-%Y%m%d-%H-%M-%S.html").timestamp() > last_successful_time), files[0])
        diff_text = compare_files(os.path.join(job_dir, last_successful_file), latest_file)
    else:
        with open(latest_file, 'r') as f:
            diff_text = f.read()
        changes_detected = True

    if diff_text:
        with open(latest_file, 'r') as f:
            html_content = f.read()
        log_message(f"Detected changes for job {name} at {url}")
        summary, score, brief_summary = summarize_diff(diff_text, html_content, url, name)

        output_json = {
            "job_name": job["name"],
            "url": url,
            "summary": summary,
            "diff_text": diff_text,
            "score": score
        }
        print(json.dumps(output_json))

        #the difficulty is when we fail json parsing AND its the first time we run.
        if (last_successful_time is None and score>0) or score >= 5:
            subject, body = create_email_content(job["name"], url, summary, diff_text, score, brief_summary)
            send_email(job["name"], subject, body, load_config()['email'])
            metadata[name] = {"last_successful_time": time.time()}
            save_metadata(metadata)
        else:
            log_message(f"Score {score} below threshold for job {name}. Email not sent.")
    else:
        log_message(f"No changes detected for job: {name}")

    return changes_detected

def normal(s):
    return json.loads(s)

def magic(s):
    fix=s.strip('```json\n').strip('\n```')
    if fix.startswith('json'):
        fix=fix[4:]
    return json.loads(fix)

def magic2(s):
    s = html.unescape(s)  # Unescape HTML entities
    s = s.strip('```json\n').strip('\n```')
    return json.loads(s)

def magic3(s):
    s = html.unescape(s)  # Unescape HTML entities
    s = s.replace('\\\n', '')  # Remove escaped newlines
    s = s.replace('\\', '')  # Remove other escape sequences
    s = s.strip('```json\n').strip('\n```')
    return json.loads(s)


def summarize_diff(diff_text, html_content, url, name):
    openai.api_key = load_apikey()
    context_text = extract_text_from_html(html_content)

    loaded_prompt = open('prompt.txt').read().strip()
    combined_text = f"Diff:\n{diff_text}\n{context_text}"[:20000]

    prompt = f"""{loaded_prompt}
        {combined_text}

        Please provide your response in the following JSON format:
        {{
            "summary": "your_summary_here",
            "brief_summary": "a one-sentence, pure text summary of the changes",
            "score": your_score_here (integer from 1 to 10),
        }}
    """

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant which always returns json."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=3500
    )

    response_text = response.choices[0].message['content'].strip()
    unique_id = f"{time.strftime('%Y%m%d%H%M%S')}_{hashlib.md5(url.encode()).hexdigest()}"

    raw_response_filename = f"openai_responses/{name}_{unique_id}_parsed_bad.json"
    got=False
    for attempt in [normal, magic, magic2, magic3]:
        try:
            response_json = attempt(response_text)
            summary = response_json['summary']
            score = int(response_json['score'])
            brief_summary=response_json['brief_summary']
            raw_response_filename = f"openai_responses/{name}_{unique_id}_parsed_okay.json"
            got=True
            #once we parse one,break
            break
        except (json.JSONDecodeError, KeyError, ValueError):
            log_message(f"Error parsing JSON response: {response_text}")
            os.makedirs('openai_responses', exist_ok=True)
            summary = "Error parsing response"
            brief_summary="Fail"
            score = 0
    if not got:
        #i mean, we might as well die= here? no point going on
        import ipdb;ipdb.set_trace()
    #either success (by some method or other) or failure (if all failed.)
    with open(raw_response_filename, 'w') as f:
        f.write(response_text)
    return summary, score, brief_summary

# the timespan in seconds.
def parse_frequency(frequency):
    return {'hourly': 3600, 'daily': 86400, 'weekly': 604800, 'minutely': 59, 'monthly': 2592000}[frequency]

def check_cron():
    now = time.time()
    total_jobs = 0
    jobs_with_changes = 0
    emails_sent = 0
    emails_failed = 0
    #~ import ipdb;ipdb.set_trace()
    if os.path.exists('.gptcron'):
        with open('.gptcron', 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    parts = line.split()
                    if len(parts) >= 3:
                        total_jobs += 1
                        frequency, name, url = parts[0], parts[1], parts[2]
                        _, last_run_time = get_last_file(name)
                        if last_run_time is None:
                            last_run_time = 0
                        next_run_time = last_run_time + parse_frequency(frequency)

                        if now >= next_run_time:
                            log_message(f"Running job: {name}")
                            changes_detected= run_job(name)
                            if changes_detected:
                                jobs_with_changes += 1
                                emails_sent += 1
                                log_message(f"Changes were detected for job: {name}")
                            else:
                                log_message(f"No changes detected for job: {name}")
                        else:
                            log_message(f"Not running job: {name} because its next run time is {next_run_time-now}s in the future.")
                    else:
                        print('bad job entry:',line)

    log_message(f"Checked cron jobs. Total: {total_jobs}, Changes: {jobs_with_changes}, Emails Sent: {emails_sent}, Emails Failed: {emails_failed}")

def debug_json_parsing(job_name):
    import ipdb
    ipdb.set_trace()
    job_dir = f"openai_responses/"
    files = sorted([f for f in os.listdir(job_dir) if 'parsed_bad' in f and job_name in f])
    if not files:
        print(f"No failed response files found for job {job_name}")
        return

    last_failed_file = os.path.join(job_dir, files[-1])
    with open(last_failed_file, 'r') as f:
        raw_text = f.read()

    print(f"Debugging last failed response from {last_failed_file}")

    for attempt in [normal, magic, magic2, magic3]:
        try:
            response_json = attempt(raw_text)
            print("Parsed JSON:", response_json)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"Error parsing JSON with {attempt.__name__}: {e}")

def setup_argparse():
    parser = argparse.ArgumentParser(description='GPT-Diff: Monitor web pages for changes and get detailed email summaries of those changes.')
    subparsers = parser.add_subparsers(dest='command', help='Sub-command help')

    add_parser = subparsers.add_parser('add', help='Add a new URL to monitor. Usage: add <your name for the site> <URL> [weekly|daily|hourly|minutely]')
    add_parser.add_argument('name', type=str, help='Alphanumeric label for this job')
    add_parser.add_argument('url', type=str, help='URL to monitor')
    add_parser.add_argument('frequency', type=str, choices=VALID_FREQUENCIES, help='Frequency to check the URL (e.g weekly|daily|hourly|minutely)')

    run_parser = subparsers.add_parser('run', help='Run the monitoring for a specific URL. Usage: run <name>')
    run_parser.add_argument('name', type=str, help='Alphanumeric label for this job')

    subparsers.add_parser('check_cron', help='Check and run all scheduled cron jobs.')

    list_parser = subparsers.add_parser('list', help='List all monitoring jobs.')
    list_parser.add_argument('--sort_by', choices=['date', 'url', 'name'], help='Sort jobs by date, url, or name')

    remove_parser = subparsers.add_parser('remove', help='Remove a job. Usage: remove <name>')
    remove_parser.add_argument('name', type=str, help='Alphanumeric label for this job')

    save_parser = subparsers.add_parser('save_sorted', help='Save sorted jobs to a file. Usage: save_sorted --sort_by <sort_by>')
    save_parser.add_argument('--sort_by', choices=['date', 'url', 'name'], required=True, help='Sort jobs by date, url, or name')

    inc_freq_parser = subparsers.add_parser('inc_frequency', help='Increase the frequency of a job. Usage: inc_frequency <name>')
    inc_freq_parser.add_argument('name', type=str, help='Alphanumeric label for this job')

    dec_freq_parser = subparsers.add_parser('dec_frequency', help='Decrease the frequency of a job. Usage: decrease_frequency <name>')
    dec_freq_parser.add_argument('name', type=str, help='Alphanumeric label for this job')

    debug_parser = subparsers.add_parser('reparse', help='Debug JSON parsing by dropping into ipdb')
    debug_parser.add_argument('name', type=str, help='Alphanumeric label for the job to debug')

    return parser


def load_metadata():
    if not os.path.exists('job_metadata.json'):
        return {}
    with open('job_metadata.json', 'r') as f:
        return json.load(f)

def save_metadata(metadata):
    with open('job_metadata.json', 'w') as f:
        json.dump(metadata, f)

def print_help():
    help_text = """
    GPT-Diff: Monitor web pages for changes and get detailed email summaries of those changes.

    Usage:
      add <name> <url> <frequency>       Add a new URL to monitor (frequency: weekly|daily|hourly|minutely)
      run <name>                        Run the monitoring for a specific URL
      check_cron                        Check and run all scheduled cron jobs
      list [--sort_by <sort_by>]        List all monitoring jobs (sort_by: date, url, name)
      remove <name>                     Remove a job
      save_sorted --sort_by <sort_by>   Save sorted jobs to a file (sort_by: date, url, name)
      inc_frequency <name>              Increase the frequency of a job
      dec_frequency <name>              Decrease the frequency of a job
      help, -h, --h                     Show this help message
    """
    print(help_text)

if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] in ["help", "-h", "--h"]:
            print_help()
        else:
            parser = setup_argparse()
            args = parser.parse_args()
            log_message(f"Command called: {args.command}")

            if args.command == "add":
                add_job(args.name, args.url, args.frequency)
            elif args.command == "run":
                run_job(args.name)
            elif args.command == "check_cron":
                check_cron()
            elif args.command == "list":
                list_jobs(args.sort_by)
            elif args.command == "remove":
                remove_job(args.name)
            elif args.command == "save_sorted":
                save_sorted_jobs(args.sort_by)
            elif args.command == "inc_frequency":
                change_frequency(args.name, "increase")
            elif args.command == "dec_frequency":
                change_frequency(args.name, "decrease")
            elif args.command == "reparse":
                debug_json_parsing(args.name)
            else:
                parser.print_help()
    except Exception as e:
        log_message(f"Unexpected error: {e}")
        raise
