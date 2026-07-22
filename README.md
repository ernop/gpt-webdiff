# GPT-WebDiff: Intelligent Web Change Monitoring

**Never miss important changes on the websites you care about.**

GPT-WebDiff is an AI-powered web monitoring tool that watches websites for you and sends intelligent email summaries when significant changes occur. Unlike traditional change detection tools that just show raw diffs, GPT-WebDiff uses advanced AI (Claude 4.5 or GPT-4o) to understand what changed and why it matters.

---

## 🌟 Key Features

### Smart Change Detection
- **AI-Powered Analysis**: Claude 4.5 reads changes and explains what they mean in plain English
- **Intelligent Scoring**: Changes are scored 0-10 based on significance, so you only get notified about what matters
- **Context-Aware**: The AI understands the context of each website (news site vs coffee shop vs company page)

### Flexible Monitoring
- Monitor websites at your preferred frequency: **minutely, hourly, daily, weekly, or monthly**
- Automatic job naming using AI (or specify your own names)
- Track unlimited websites simultaneously

### Beautiful Email Reports
- HTML-formatted email summaries with change highlights
- Detailed analysis of what changed, what was added, and what was removed
- Comparison information showing date ranges
- Visual diff highlighting

### Wikipedia vs Grokipedia Comparison (NEW!)
- Compare any topic between Wikipedia and Grokipedia
- Identify biases, missing information, and differences in emphasis
- Get detailed AI analysis in one query
- Perfect for research, fact-checking, and bias detection

---

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/ernop/gpt-webdiff.git
cd gpt-webdiff

# Install dependencies
pip install -r requirements.txt

# Configure your API keys and email
cp config_example.json config.json
# Edit config.json with your details
```

### Configuration

Edit `config.json`:
```json
{
    "login_email": "your@email.com",
    "from_email": "your@email.com",
    "to_email": "your@email.com",
    "password": "your-gmail-app-password",
    "anthropic_api_key": "sk-ant-your-key-here",
    "openai_api_key": "",
    "default_model": "claude-sonnet-4-5",
    "fallback_model": "gpt-4o"
}
```

**API Keys:**
- **Anthropic (Claude)**: Get yours at https://console.anthropic.com/
- **OpenAI**: Get yours at https://platform.openai.com/

**Email Password**: For Gmail, you need an [App Password](https://support.google.com/accounts/answer/185833), not your regular password.

---

## 📖 Usage

### Monitor a Website

```bash
# Add a website to monitor (AI will create a name automatically)
python gptcron.py add "https://example.com" daily

# Or specify your own name
python gptcron.py add "https://example.com" "my-site" daily

# Available frequencies: minutely, hourly, daily, weekly, monthly
```

### List Your Monitoring Jobs

```bash
python gptcron.py list

# Sort by date, url, or name
python gptcron.py list --sort_by date
```

### Test a Job Immediately

```bash
# Run a specific job right now
python gptcron.py test my-site

# Or test a random job
python gptcron.py test
```

### Compare Wikipedia vs Grokipedia

```bash
# Compare any topic
python gptcron.py compare_wikis "Artificial Intelligence"

# Send results via email
python gptcron.py compare_wikis "Climate Change" --send-email
```

This feature fetches the full text of both encyclopedia pages and uses AI to provide detailed analysis of:
- Key differences in content
- Missing information in either source
- Differences in emphasis or perspective
- Potential biases

Perfect for research, journalism, or understanding how different sources present information.

### Automated Monitoring

Set up a cron job to check all your sites automatically:

```bash
# Edit your crontab
crontab -e

# Add this line (adjust paths to match your system):
*/15 * * * * cd /path/to/gpt-webdiff && python3 gptcron.py check_cron >> cronlog.log 2>&1
```

This checks every 15 minutes and runs any jobs that are due.

---

## 🎯 Use Cases

### News & Current Events
- Monitor breaking news sites
- Track updates to ongoing stories
- Get alerts when important articles change

### Business Intelligence
- Watch competitor websites for changes
- Monitor product pages for pricing updates
- Track company announcements

### Research & Academia
- Monitor research paper repositories
- Track changes to Wikipedia articles
- Watch for updates to academic resources
- Compare information sources for bias

### Personal Projects
- Monitor your own websites for unexpected changes
- Track changes to documentation
- Watch for updates to hobby sites

### Fact-Checking & Media Analysis
- Compare how different sources present information
- Identify potential bias in encyclopedias
- Track how articles evolve over time

---

## 💡 How It Works

1. **Download**: GPT-WebDiff downloads the webpage at your specified frequency
2. **Compare**: It compares the new version with the previous version
3. **Analyze**: Claude 4.5 (or GPT-4o) reads the differences and creates a summary
4. **Score**: The AI assigns a significance score (0-10)
5. **Notify**: If the score is ≥7, you get an email with a detailed summary

### Example Email

```
Subject: gpt-diff | nytimes | Score: 9 | Major political announcement

=== Summary ===
The New York Times homepage has been updated with breaking news...
[Detailed, intelligent summary of what changed]

=== Changes ===
Added: New article about...
Removed: Old article about...
Modified: Updated headline from X to Y...

=== Full Diff ===
[Technical diff for reference]
```

---

## 🤖 AI Models

GPT-WebDiff supports both Claude (Anthropic) and OpenAI models:

### Default: Claude Sonnet 4.5
- More reliable and accurate
- Better at understanding context
- Produces higher quality summaries
- Recommended for best results

### Fallback: GPT-4o
- Automatically used if Claude fails
- Also produces excellent results
- Good for compatibility

### Configurable
You can change the default model in `config.json`:
```json
{
    "default_model": "claude-sonnet-4-5",
    "fallback_model": "gpt-4o"
}
```

Supported models:
- `claude-sonnet-4-5` (recommended)
- `claude-opus-4`
- `gpt-4o`
- `gpt-4-turbo`
- `gpt-4`

---

## 📊 Commands Reference

| Command | Description | Example |
|---------|-------------|---------|
| `add` | Add a new monitoring job | `python gptcron.py add https://example.com daily` |
| `list` | List all jobs | `python gptcron.py list` |
| `remove` | Remove a job | `python gptcron.py remove job-name` |
| `run` | Run a job immediately | `python gptcron.py run job-name` |
| `test` | Test a job (forces comparison) | `python gptcron.py test job-name` |
| `check_cron` | Check and run all due jobs | `python gptcron.py check_cron` |
| `bump` | Increase job frequency | `python gptcron.py bump job-name` |
| `unbump` | Decrease job frequency | `python gptcron.py unbump job-name` |
| `search` | Search jobs by name/URL | `python gptcron.py search keyword` |
| `compare_wikis` | Compare Wikipedia vs Grokipedia | `python gptcron.py compare_wikis "Topic"` |
| `email-backup` | Email backup of job list | `python gptcron.py email-backup` |

---

## 💰 Cost

### Monitoring Costs
- **Per check**: ~$0.001-0.005 (only when changes detected)
- **Typical usage** (10 daily jobs): ~$0.30-0.50/month
- Claude Sonnet 4.5 is very cost-effective

### Wiki Comparison Costs
- **Per comparison**: ~$0.01-0.02
- Sends full page content (up to 50K characters) to AI

Both Claude and OpenAI offer generous free tiers for trying out the service.

---

## 🔒 Security & Privacy

- Your API keys are stored locally in `config.json` (never shared)
- All data processing happens on your machine
- AI providers (Anthropic/OpenAI) process the content but don't store it
- Downloaded pages are stored locally in the `data/` folder
- Email uses secure SMTP with TLS

**Important**: Never commit `config.json` or `apikey.txt` to version control!

---

## 🛠️ Advanced Features

### Historical Tracking
- All versions of monitored pages are saved
- Compare any two versions
- Track changes over time

### Threshold-Based Notifications
- Only get notified when changes are significant
- Configurable minimum score (default: 7)
- Prevents notification fatigue

### Smart Aggregation
- If multiple small changes don't meet the threshold, they're accumulated
- Next check compares against the last emailed version
- Ensures complete coverage even with many small changes

### Backup System
- Automatic backups of your job list
- Email yourself a backup anytime
- Easy recovery if something goes wrong

---

## 📚 Documentation

- **[SETUP.md](SETUP.md)** - Detailed setup instructions
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Live systemd deployment and update workflow
- **[AGENTS.md](AGENTS.md)** - Guide for AI agents working on this project
- **[USAGE_GUIDE.md](USAGE_GUIDE.md)** - Detailed usage examples
- **[IMPROVEMENTS.md](IMPROVEMENTS.md)** - Technical improvement notes

### Automated Tests

The test suite mocks websites, AI providers, and SMTP, so it does not need API keys
or email credentials:

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs the same suite on supported Python versions for every push and
pull request. Before deployment, also run one real check with the configured provider
and email account.

---

## 🤝 Contributing

Contributions are welcome! This project can be improved in many ways:

- Better diff algorithms
- Support for more AI models
- Web interface
- Mobile app
- More comparison sources
- Visual diff rendering
- And more!

See [AGENTS.md](AGENTS.md) for guidelines on contributing.

---

## 📝 License

This project is open source. Feel free to use, modify, and distribute.

---

## 🆘 Support & Issues

- **Issues**: Open an issue on GitHub
- **Questions**: Check the documentation files
- **Feature Requests**: Open an issue with the "enhancement" label

---

## 🎉 Why GPT-WebDiff?

**Traditional change monitors** just tell you "something changed" and show you a messy diff.

**GPT-WebDiff** tells you:
- **What** changed in plain English
- **Why** it matters (scored 0-10)
- **Context** about the change
- **Details** in an easy-to-read format

It's like having a personal assistant watching the web for you, who only interrupts when something actually matters.

---

## 🚀 Get Started Now

```bash
git clone https://github.com/ernop/gpt-webdiff.git
cd gpt-webdiff
pip install -r requirements.txt
cp config_example.json config.json
# Edit config.json with your API keys
python gptcron.py add "https://news.ycombinator.com" hourly
```

That's it! You'll get intelligent email alerts whenever Hacker News has significant changes.

---

**Built with ❤️ using Claude 4.5 and GPT-4o**
