import os
import smtplib
from email.mime.text import MIMEText
import html
from datetime import datetime
from misc_utils import log_message, load_config

def save_email_to_disk(job_name, subject, body):
    email_dir = "emails"
    os.makedirs(email_dir, exist_ok=True)
    filename = os.path.join(email_dir, f"{job_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}.txt")
    with open(filename, 'w') as f:
        f.write(f"Subject: {subject}\n\n{body}")

#email a copy of the .gptcron file to the user in settings.
def email_me_gptcron():
    now=datetime.now()
    subject=f"Backup of .gptcron, as of {now.year}/{now.month}/{now.day}"
    with open('.gptcron', 'r') as f:
        lines = f.readlines()
    body='<br>\n'.join(lines)
    to_email= load_config()['to_email']
    inner_send_email(subject, body,to_email)

def create_email_content(job_name, url, brief_summary, summary, diff_text, score):
    escaped_diff_text = html.escape(diff_text)
    formatted_summary = summary.replace('\n', '<br>')
    subject = f"GPT-diff | {job_name} | Score: {score} | {brief_summary}"

    with open('email_body_template.txt', 'r') as body_file:
        body_template = body_file.read().strip()

    body = body_template.format(
        job_name=job_name,
        url=url,
        summary=formatted_summary,
        diff_text=escaped_diff_text,
        brief_summary=brief_summary
    )

    return subject, body

def create_summary_email_content(job_name, url, brief_summary, summary):
    subject = f"GPT-diff | New job added: {job_name} | {brief_summary}"
    with open('summary_email_body_template.txt', 'r') as body_file:
        body_template = body_file.read().strip()

    body = body_template.format(
        job_name=job_name,
        url=url,
        summary=summary,
        brief_summary=brief_summary
    )

    return subject, body

def send_email(job_name, subject, body, to_email):
    save_email_to_disk(job_name, subject, body)
    log_message(f"Sending Email: Subject: {subject}, Body: {body[:1000]}...")
    inner_send_email(subject, body, to_email)
    print(f"Email sent to {to_email}")
    log_message(f"Email sent to {to_email} for job {job_name}")

def inner_send_email(subject, body, to_email):
    config = load_config()
    msg = MIMEText(body, 'html')
    msg['Subject'] = subject
    msg['From'] = config['from_email']
    msg['To'] = to_email
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    smtp_user = config['login_email']
    smtp_password = config['password']

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, [to_email], msg.as_string())
        server.quit()
    except Exception as e:
        print(f"Failed to send email: {e}")
        log_message(f"Failed to send email to {to_email}: {e}")

