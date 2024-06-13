This now works if installed via cron. See the *_example files in this dir.

I want to make a command line program for "gpt-diff". It should be like "gpt-diff add <name> <URL> [daily|hourly|weekly] etc.". That would do the following:

1. set up a periodic repeated action to call a wget on that URL and save the results to a file. Then it would compare the current results to the last results, if any, using gpt-4o. So that if the first time, the page said one thing, the 2nd time, the page would say another thing.

If there was a change, that change would trigger an email to me, at my email address. The email would

The program doing the downloading should:
1. be run periodically by a real cron job (which would check all teh gpt-cron jobs I had).
2. download the latest
3. compare to the prior, if any, using a local diff tool
4. if there is any technical bit difference, send the data to gpt4o for summarizing. it should say a general, detailed description.
5. I have an apikey for this so that is fine.
6. once results are back email them to me - both the summarized words of difference, and also the actual diff file produce from the filesystem

I will run this on WSL in windows. The apikey is in a file called apikey.txt

This system also has cron.

So we should also create a general cron that runs say hourly which does all the jobs. Our gptcron jobs will be stored in our own .gptcron file. There will also be a config file which contains my email address.  So when the program runs, it does the work for ech one.

The <name> field must be an alphanumeric label for this job. the data for that job goes in the folder data/<name>. In there, there are lots of files which are named <name-date of last download of the file contents>.  Those are available if needed for deeper comparisons.


Can you give me a general set of intro files for this? It should be written in python

The API at openAI we use must be "gpt-4o" (or later models) even if you haven't head of it yet.

The provided script is a web monitoring tool that tracks changes to specific URLs and sends detailed email summaries of detected changes. It works by periodically downloading the web pages, comparing them with previously downloaded versions, and using OpenAI to generate summaries of the differences. It includes functionalities to add, run, list, and check monitoring jobs, each configured with specific frequencies (hourly, daily, weekly).

We will never use Function Docstrings because they are a waste of space.


#Our goal for ignoring small changes, yet also making sure we get aggretage email coverage of all historical change, too:  Now let's talk about this issue: imagine that we do the diff, but in the end, decide not to send the email because the change threshold was not reached. In that case, we both want to 1) NOT send the email, which is good, but 2) the next time we check we want to check the FULL interval. I.e. if the times we check are T1, T2, T3 and the first interval (T1 to T2) doesn't have enough change to send an email, the next time we check (T3) we should REMEMBER that we didn't send an email, and do the full check on the diff (i.e. between T1 to T3). That way, when we reach a large enough amount of change, we'll send an email, AND the total coverage we have of sites we monitor is going to be constant. Sites can't just slowly modify little by little, and end up having the changes be lost, since none of them met the threshold.  What are general options to implement this method? List 3 main ideas we might try to make this change. Once you list the summary, we will continue our discussion and figure out which one to do. Now, I'm just looking for your proposals for the easiest, safest, and best ways to do this, in general.


okay, it sends emails, but there are problems.  See image:

1. the subject is too long. I want the score, the name of the page and sender, and a new VERY BRIEF summary of the changes.
2. The body of the email doesn't contain any details now? I want all the details, and I want them to be very easy to read. So the top part should explain the full diff, including what was added, what was changed (including before/after), and what was removed.
3. The next section of the email should contain as best as you can a copy of the full text diff, and since it contains html, we have to protect it somehow so I can see the raw diff of the file within gmail.
