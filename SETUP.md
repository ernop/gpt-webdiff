# Setup Guide - GPT-WebDiff

Complete technical setup instructions for getting GPT-WebDiff running on your system.

---

## System Requirements

### Operating System
- **Linux** (Ubuntu, Debian, CentOS, etc.) - Recommended
- **macOS** - Fully supported
- **Windows** - Supported via WSL (Windows Subsystem for Linux)

### Python
- **Version**: Python 3.7 or higher
- **Recommended**: Python 3.9+

Check your version:
```bash
python3 --version
```

### Internet Connection
- Required for downloading pages and accessing AI APIs
- Stable connection recommended for reliability

---

## Installation Steps

### 1. Clone the Repository

```bash
git clone https://github.com/ernop/gpt-webdiff.git
cd gpt-webdiff
```

### 2. Set Up Python Environment (Recommended)

Using a virtual environment keeps dependencies isolated:

```bash
# Create virtual environment
python3 -m venv gpt-diff-env

# Activate it
# On Linux/Mac:
source gpt-diff-env/bin/activate

# On Windows (WSL):
source gpt-diff-env/bin/activate
```

Your prompt should now show `(gpt-diff-env)`.

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `beautifulsoup4` - HTML parsing
- `openai` - OpenAI API client (GPT models)
- `anthropic` - Anthropic API client (Claude models)
- `requests` - HTTP library

### 4. Configure API Keys

You need at least one AI API key (Claude or OpenAI).

#### Option A: Use Claude (Recommended)

1. Get an API key from [Anthropic Console](https://console.anthropic.com/)
2. Copy `config_example.json` to `config.json`:
   ```bash
   cp config_example.json config.json
   ```
3. Edit `config.json` and add your Anthropic key:
   ```json
   {
       "anthropic_api_key": "sk-ant-your-actual-key-here"
   }
   ```

#### Option B: Use OpenAI

1. Get an API key from [OpenAI Platform](https://platform.openai.com/)
2. Copy `config_example.json` to `config.json`:
   ```bash
   cp config_example.json config.json
   ```
3. Edit `config.json` and add your OpenAI key:
   ```json
   {
       "openai_api_key": "sk-your-actual-key-here"
   }
   ```

#### Option C: Use Both (Best)

Having both allows automatic fallback:
```json
{
    "anthropic_api_key": "sk-ant-your-anthropic-key",
    "openai_api_key": "sk-your-openai-key",
    "default_model": "claude-sonnet-4-5",
    "fallback_model": "gpt-4o"
}
```

#### Legacy Method (OpenAI only)

Alternatively, create `apikey.txt` with just your OpenAI key:
```bash
echo "sk-your-openai-key-here" > apikey.txt
```

### 5. Configure Email Settings

For email notifications, you need to configure Gmail SMTP.

Edit `config.json`:

```json
{
    "login_email": "your.email@gmail.com",
    "from_email": "your.email@gmail.com",
    "to_email": "your.email@gmail.com",
    "password": "your-gmail-app-password"
}
```

#### Getting a Gmail App Password

**Important**: You cannot use your regular Gmail password for SMTP. You need an "App Password".

1. Go to your [Google Account](https://myaccount.google.com/)
2. Navigate to **Security** → **2-Step Verification** (enable if not already)
3. Scroll to **App passwords**
4. Generate a new app password for "Mail"
5. Copy the 16-character password (it looks like: `abcd efgh ijkl mnop`)
6. Paste it into `config.json` as the `password` field

**Note**: Remove the spaces: `abcdefghijklmnop`

### 6. Verify Installation

Test that everything is working:

```bash
# Check help works
python gptcron.py help

# Try listing (should be empty initially)
python gptcron.py list
```

If you see the help text, you're good to go!

---

## Complete config.json Example

Here's a complete configuration file:

```json
{
    "login_email": "john@gmail.com",
    "from_email": "john@gmail.com",
    "to_email": "john@gmail.com",
    "password": "abcdefghijklmnop",
    "anthropic_api_key": "sk-ant-api03-abc123...",
    "openai_api_key": "sk-proj-abc123...",
    "default_model": "claude-sonnet-4-5",
    "fallback_model": "gpt-4o"
}
```

**Security Warning**: Never commit this file! It's already in `.gitignore`.

---

## Quick Test

Let's verify everything works by adding and testing a simple monitoring job:

```bash
# Add a test job
python gptcron.py add "https://example.com" "test-site" daily

# Test it immediately
python gptcron.py test test-site

# Check if it worked
python gptcron.py list

# Remove the test
python gptcron.py remove test-site
```

If you got an email (or saw output that it would send one), success! 🎉

---

## Setting Up Automated Monitoring

### Using Cron (Linux/Mac)

Cron will automatically check your monitored sites at regular intervals.

1. Edit your crontab:
   ```bash
   crontab -e
   ```

2. Add this line (adjust paths to match your installation):
   ```bash
   */15 * * * * cd /full/path/to/gpt-webdiff && /full/path/to/python3 gptcron.py check_cron >> cronlog.log 2>&1
   ```

   This checks every 15 minutes.

3. Find your paths:
   ```bash
   # Current directory
   pwd

   # Python path (if using venv)
   which python3
   ```

4. Example with virtual environment:
   ```bash
   */15 * * * * cd /home/john/gpt-webdiff && /home/john/gpt-webdiff/gpt-diff-env/bin/python gptcron.py check_cron >> cronlog.log 2>&1
   ```

5. Save and exit (usually `Ctrl+X`, then `Y`, then `Enter`)

6. Verify cron is running:
   ```bash
   crontab -l
   ```

### Cron Frequency Options

```bash
# Every minute
* * * * * cd /path && python3 gptcron.py check_cron >> cronlog.log 2>&1

# Every 5 minutes
*/5 * * * * cd /path && python3 gptcron.py check_cron >> cronlog.log 2>&1

# Every 15 minutes (recommended)
*/15 * * * * cd /path && python3 gptcron.py check_cron >> cronlog.log 2>&1

# Every hour
0 * * * * cd /path && python3 gptcron.py check_cron >> cronlog.log 2>&1

# Every day at 9 AM
0 9 * * * cd /path && python3 gptcron.py check_cron >> cronlog.log 2>&1
```

### Using Windows Task Scheduler (Windows)

If not using WSL, you can use Task Scheduler:

1. Open Task Scheduler
2. Create Basic Task
3. Trigger: Choose frequency (e.g., Daily, Every 15 minutes)
4. Action: Start a program
5. Program: `C:\Python39\python.exe`
6. Arguments: `C:\path\to\gpt-webdiff\gptcron.py check_cron`
7. Start in: `C:\path\to\gpt-webdiff`

---

## Directory Structure After Setup

After setup, your directory should look like this:

```
gpt-webdiff/
├── gptcron.py                # Main program
├── config.json               # Your configuration (DO NOT COMMIT)
├── config_example.json       # Template for others
├── apikey.txt                # Optional legacy key file (DO NOT COMMIT)
├── requirements.txt          # Dependencies list
├── .gptcron                  # Job definitions (created after first job)
├── job_metadata.json         # Job state (created automatically)
├── log.log                   # Application logs (created automatically)
├── cronlog.log               # Cron output (created if using cron)
├── README.md                 # Documentation
├── SETUP.md                  # This file
├── AGENTS.md                 # For AI assistants
├── USAGE_GUIDE.md            # Usage examples
├── data/                     # Downloaded pages (created automatically)
├── emails/                   # Sent emails (created automatically)
├── openai_responses/         # AI responses (created automatically)
├── wiki_comparisons/         # Wiki comparisons (created automatically)
└── gptcron_backups/          # Config backups (created automatically)
```

---

## Common Setup Issues

### Issue: "No module named 'openai'"

**Solution**:
```bash
pip install -r requirements.txt
```

Make sure you've activated your virtual environment first!

### Issue: "No module named 'anthropic'"

**Solution**:
```bash
pip install anthropic
```

Or set `default_model` to `gpt-4o` in config.json to use OpenAI instead.

### Issue: "ModuleNotFoundError: No module named 'bs4'"

**Solution**:
```bash
pip install beautifulsoup4
```

### Issue: "Failed to send email"

**Possible causes**:

1. **Using regular password instead of app password**
   - Solution: Get a Gmail app password (see instructions above)

2. **2-Step Verification not enabled**
   - Solution: Enable it in Google Account settings

3. **Firewall blocking SMTP**
   - Solution: Allow port 587 outbound

4. **Wrong email configuration**
   - Solution: Double-check `config.json` email fields

### Issue: "API key not found"

**Solution**:
```bash
# Check if config.json exists
ls -la config.json

# Check contents (hide your real keys!)
cat config.json
```

Make sure the API key is in the correct field:
- `anthropic_api_key` for Claude
- `openai_api_key` for OpenAI

### Issue: Cron job not running

**Debug steps**:

1. Check cron is installed:
   ```bash
   which cron
   crontab -l
   ```

2. Check logs:
   ```bash
   tail -f cronlog.log
   tail -f log.log
   ```

3. Test command manually:
   ```bash
   cd /path/to/gpt-webdiff
   python3 gptcron.py check_cron
   ```

4. Check paths are absolute in crontab

5. Make sure script has execute permissions:
   ```bash
   chmod +x gptcron.py
   ```

### Issue: "Permission denied" when writing files

**Solution**:
```bash
# Make sure you own the directory
ls -la

# If not, take ownership:
sudo chown -R $USER:$USER .

# Or run from your home directory
cd ~
git clone https://github.com/ernop/gpt-webdiff.git
```

---

## Testing Your Setup

### Test 1: CLI Works
```bash
python gptcron.py help
```
Expected: Help text showing all commands

### Test 2: Config Loads
```bash
python gptcron.py list
```
Expected: "No jobs found." (or your job list if you've added jobs)

### Test 3: AI Works
```bash
python gptcron.py add "https://example.com" "test" daily
python gptcron.py test test
```
Expected: Output showing AI analysis and score

### Test 4: Email Works
After Test 3, check your email inbox. You should have received an email.

### Test 5: Cron Works
After setting up cron, wait for the scheduled time and check:
```bash
tail -f log.log
tail -f cronlog.log
```

---

## Minimal Working Setup

The absolute minimum to get started:

1. **Python 3.7+** installed
2. **One API key** (Claude or OpenAI)
3. **config.json** with API key configured
4. **Email configured** (for notifications)

You can skip:
- Virtual environment (not recommended but optional)
- Cron setup (can run manually)
- Both API keys (one is enough)

---

## Next Steps After Setup

1. **Add your first real monitoring job**:
   ```bash
   python gptcron.py add "https://news.ycombinator.com" hourly
   ```

2. **Try the wiki comparison feature**:
   ```bash
   python gptcron.py compare_wikis "Python programming language"
   ```

3. **Set up automated monitoring** (see cron instructions above)

4. **Read the usage guide**: Check `USAGE_GUIDE.md` for more examples

5. **Monitor your logs**:
   ```bash
   tail -f log.log
   ```

---

## Upgrading

To update to the latest version:

```bash
cd gpt-webdiff
git pull origin master
pip install -r requirements.txt --upgrade
```

Your config.json and data will be preserved (they're in .gitignore).

---

## Backup Your Configuration

Email yourself a backup of your job list:

```bash
python gptcron.py email-backup
```

This sends a copy of your `.gptcron` file to your configured email.

You should also manually backup:
- `config.json` (contains your settings)
- `.gptcron` (contains your job definitions)
- `job_metadata.json` (contains job state)

---

## Security Best Practices

1. **Never commit sensitive files**:
   - ❌ Don't commit `config.json`
   - ❌ Don't commit `apikey.txt`
   - ✅ These are already in `.gitignore`

2. **Protect your config file**:
   ```bash
   chmod 600 config.json
   ```

3. **Use app passwords**, not real passwords for email

4. **Keep API keys secure**:
   - Don't share them
   - Rotate them periodically
   - Monitor usage on provider dashboards

5. **Review permissions**:
   ```bash
   # Only you should read/write
   ls -la config.json
   # Should show: -rw------- (or -rw-r-----)
   ```

---

## Getting Help

### Check Logs
```bash
tail -f log.log
tail -f cronlog.log
```

### Test Individual Components

**Test AI connection**:
```bash
python gptcron.py add "https://example.com" "test" daily
python gptcron.py run test
```

**Test email**:
```bash
python gptcron.py email-backup
```

**Test cron logic**:
```bash
python gptcron.py check_cron force
```

### Common Log Messages

**"Warning: anthropic package not installed"**
- Not an error if you're using OpenAI
- Or install: `pip install anthropic`

**"Primary model failed: ..."**
- Normal if one API is down
- Should automatically try fallback

**"No changes detected"**
- Normal - means website hasn't changed
- Not an error

---

## Uninstallation

If you want to remove everything:

```bash
# Remove cron job
crontab -e
# Delete the gpt-webdiff line

# Deactivate virtual environment
deactivate

# Remove directory
cd ..
rm -rf gpt-webdiff
```

Your emails and cloud-stored data remain (API providers keep logs).

---

## FAQ

**Q: Which AI model should I use?**
A: Claude Sonnet 4.5 is recommended for better quality. GPT-4o works great too.

**Q: How much does it cost?**
A: Typically $0.30-0.50/month for 10 daily-monitored sites. Very affordable.

**Q: Can I use it without email?**
A: Currently no, email is required for notifications. A future version might support webhooks.

**Q: Does it work on Windows?**
A: Yes, via WSL (Windows Subsystem for Linux). Native Windows is not officially supported.

**Q: How many sites can I monitor?**
A: Unlimited! But be aware of costs and API rate limits.

**Q: What if a site requires login?**
A: Currently not supported. It only monitors public pages.

**Q: Can it monitor JavaScript-heavy sites?**
A: Partially. It gets the HTML but may miss dynamically-loaded content.

**Q: Is my data private?**
A: Downloaded pages are stored locally. Page content is sent to AI providers (Anthropic/OpenAI) for analysis but not stored by them.

---

**You're ready! Start monitoring the web with AI-powered intelligence.** 🚀

For usage examples, see `USAGE_GUIDE.md`.

For technical details, see `AGENTS.md`.

