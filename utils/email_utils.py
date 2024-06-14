import os
import smtplib
from email.mime.text import MIMEText
import html
from datetime import datetime
from utils.misc_utils import log_message, load_config

def save_email_to_disk(job_name, subject, body):
    email_dir = "emails"
    os.makedirs(email_dir, exist_ok=True)
    filename = os.path.join(email_dir, f"{job_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}.txt")
    with open(filename, 'w') as f:
        f.write(f"Subject: {subject}\n\n{body}")

def create_email_content(job_name, url, summary, diff_text, score, brief_summary):
    escaped_diff_text = html.escape(diff_text)
    subject = f"GPT-diff | {job_name} | Score: {score} | {brief_summary}"
    with open('email_body_template.txt', 'r') as body_file:
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

