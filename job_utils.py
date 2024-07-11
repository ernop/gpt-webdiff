
import os
import sys
import json
import time
import re
import datetime
import openai
import gpt_json
from gpt_json import attempt_to_deserialize_openai_json
from file_utils import parse_cron_file, backup_cron_file, get_last_file, compare_files, download_url, is_valid_url
from email_utils import create_email_content, send_email, create_summary_email_content
from misc_utils import log_message, load_config, load_metadata, save_metadata, extract_text_from_html, load_apikey
from openai_utils import summarize_diff, summarize_page
from bs4 import BeautifulSoup

VALID_FREQUENCIES = ['minutely', 'hourly', 'daily', 'weekly', 'monthly']

def gpt_generate_job_names(url, text):
    openai.api_key = load_apikey()
    short_text=text[:1000]
    prompt=f"""I would like to create a short alphanumeric name (also including - for spaces bewteen words) for a webpage which has content given below.
    Let's think of some reasonable options. Our goals are simplicity, directness, making sure the context makes sense,etc. For example, if the url was http://nytimes.com and the content was: 'The New York Times - Breaking News, US News, World News and Videos Skip to content Skip to site index SKIP ADVERTISEMENT U.S. International Canada Today's Paper U.S. Sections U.S. Politics New York California Education Health Obituaries Science Climate Weather Sports Business Tech The Upshot The Magazine U.S. Politics 2024 Elections ' you should return the option: 'new-york-times'. Keep it simple.  That's because the hostname part of the URL is very important; that tells you what domain / page we are really looking at. The contents and remainder of the URL can also be used to hint at the result that is best.

    In this case, we are looking at the following URL: {url} which has this initial content
    {text}.

    Please return JUST the name you suggest, simplest form possible, max 4 words or so, as a json string like this: {{result: "<your result>"}}.
    """
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant which always returns json."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=200
    )
    res = response.choices[0].message['content'].strip()
    th, got =gpt_json.attempt_to_deserialize_openai_json(res)
    if not got:
        sys.exit(4)
    jobname=th['result']
    if not re.match(r'^[a-zA-Z0-9-]+$', jobname):
        print(f"Error: Invalid job name: name must be alphanumeric.")
        sys.exit(1)
    return jobname

def add_job2(url, frequency):
    suggested_name = gpt_generate_job_names(url, text_content)
    if not re.match(r'^[a-zA-Z0-9-]+$', name):
        print(f"Error: Invalid job name: name must be alphanumeric.")
        sys.exit(1)
    if any(job['name'] == name for job in jobs):
        print(f"Error: A job with the name '{name}' already exists.")
        return

def get_gpt_name(url):
    latest_file = download_url(url, name="_no-name-yet")
    with open(latest_file, 'r', encoding='utf-8') as file:
        html_content = file.read()
        soup = BeautifulSoup(html_content, 'html.parser')
        text_content = soup.get_text(separator = ' ', strip=True)
        response = gpt_generate_job_names(url, text_content)
        return response

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

    if last_successful_time:
        # Compare with the last successful file
        job_dir = f"data/{name}"
        files = sorted([f for f in os.listdir(job_dir) if os.path.isfile(os.path.join(job_dir, f))])
        last_successful_file = next((f for f in files if datetime.datetime.strptime(f, f"{name}-%Y%m%d-%H-%M-%S.html").timestamp() > last_successful_time), files[0])
        diff_text = compare_files(os.path.join(job_dir, last_successful_file), latest_file)

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

            if (last_successful_time is None and score > 0) or score >= 5:
                subject, body = create_email_content(job["name"], url, brief_summary, summary, diff_text, score)
                send_email(job["name"], subject, body, load_config()['to_email'])
                metadata[name] = {"last_successful_time": time.time()}
                changes_detected=True
                save_metadata(metadata)
            else:
                log_message(f"Score {score} below threshold for job {name}. Email not sent.")
        else:
            log_message(f"No changes detected for job: {name}")

    else: # First-time check: summarize the entire page
        with open(latest_file, 'r') as f:
            html_content = f.read()
        context_text = extract_text_from_html(html_content)
        log_message(f"First-time check for job {name} at {url}")
        if context_text=='':
            summary, brief_summary='',''
            log_message(f"First-time check for job {name} at {url} got no data from the page.")
        else:
            summary, brief_summary = summarize_page(context_text, url, name)
            subject, body = create_summary_email_content(job["name"], url, brief_summary, summary)
            send_email(job["name"], subject, body, load_config()['to_email'])
            changes_detected=True
            metadata[name] = {"last_successful_time": time.time()}
            save_metadata(metadata)

    return changes_detected

def add_job(name, url, frequency):
    if name==None:
        name= get_gpt_name(url)
    if frequency==None:
        frequency='weekly'

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
    cron_entry = f"{frequency} {name} {url} {datetime.datetime.now().strftime('%Y%m%d%H%M%S')}\n"
    with open('.gptcron', 'a') as f:
        f.write(cron_entry)
    print(f"Job '{name}' added successfully.")
    log_message(f"Job added: {name}, {url}, {frequency}")

def remove_job(name):
    jobs = parse_cron_file()
    backup_cron_file()
    with open('.gptcron', 'w') as f:
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
    num_dir = -1 if direction == 'increase' else 1
    new_index = current_index + num_dir

    if new_index < 0 or new_index >= len(VALID_FREQUENCIES):
        print(f"Error: Cannot change frequency. Current frequency is '{job['frequency']}' and no {'lower' if direction == 'decrease' else 'higher'} frequency available.")
        return

    new_frequency = VALID_FREQUENCIES[new_index]
    job["frequency"] = new_frequency
    backup_cron_file()

    with open('.gptcron', 'w') as f:
        for j in jobs:
            f.write(f"{j['frequency']} {j['name']} {j['url']} {j['date_added']}\n")

    print(f"Job '{name}' frequency changed from '{VALID_FREQUENCIES[current_index]}' to '{new_frequency}' successfully.")
    log_message(f"Job '{name}' frequency changed from '{VALID_FREQUENCIES[current_index]}' to '{new_frequency}'")

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
    with open('.gptcron', 'w') as f:
        for job in jobs:
            f.write(f"{job['frequency']} {job['name']} {job['url']} {job['date_added']}\n")

    print(f"Jobs sorted by {sort_by} and saved back to .gptcron")
    log_message(f"Jobs sorted by {sort_by} and saved back to .gptcron")


def parse_frequency(frequency):
    return {'hourly': 3600, 'daily': 86400, 'weekly': 604800, 'minutely': 59, 'monthly': 2592000}[frequency]

def check_cron(force = True):
    now = time.time()
    total_jobs = 0
    jobs_with_changes = 0
    emails_sent = 0
    emails_failed = 0
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

                        if (now >= next_run_time) or force:
                            log_message(f"Running job: {name}")
                            changes_detected = run_job(name)
                            if changes_detected:
                                jobs_with_changes += 1
                                emails_sent += 1
                                log_message(f"Changes were detected for job: {name}")
                            else:
                                log_message(f"No changes detected for job: {name}")
                        else:
                            fut=next_run_time - now
                            log_message(f"Not running job: {name} because its next run time is {fut:.0f}s in the future.")
                    else:
                        print('bad job entry:', line)

    log_message(f"Checked cron jobs. Total: {total_jobs}, Changes: {jobs_with_changes}, Emails Sent: {emails_sent}, Emails Failed: {emails_failed}")
