# MediMate — Presentation guide

**Opening (40 seconds).** Introduce MediMate as a Python application that helps organize household medicine information, multiple daily intake schedules, inventory, and records.

**Architecture (45 seconds).** Demonstrate the GitHub repository. Explain that `Launch_App.ipynb` uses `git clone` to obtain the latest committed source every time Run All is clicked. `app.py` contains Gradio UI; `database.py` contains SQLite transactions; `medimate_core.py` validates inputs.

**User experience (45 seconds).** Enter a full name, show the strawberry-cream interface, switch ID/EN and select WIB, WITA, or WIT.

**Set up a daily intake plan (90 seconds).** In **My Medicines**, add a medicine and its initial stock. Then open **Schedule**, select that medicine, enter units per intake (such as 1), choose 2 times per day, and set the first and second time to 08:00 and 20:00. Save. The Schedule and Dashboard tabs show two independent entries.

**Confirm per time (80 seconds).** In Intake Tracker choose the date, select **08:00**, and click **Taken**. Confirm 20:00 is still **Not recorded**. Show that inventory decreases only by the configured number for 08:00. Record 20:00 separately. Click Taken again for 08:00 to show that it doesn't reduce stock twice. Clear one intake and observe the correct reversal.

**Edit and local time (45 seconds).** Select an existing medicine in **My Medicines**; show that its details appear automatically and save a new low-stock threshold. In **Intake Tracker**, show the Recorded at column and switch WIB → WITA → WIT: the displayed time changes, but the underlying record does not.

**Inventory and analytics (60 seconds).** Show expiring batches, inventory status and recorded intake graph, then export a backup for storage beyond the Colab runtime.

**GitHub update example (40 seconds).** Modify a safe UI heading in `app.py`, commit it on GitHub and Run All again. Explain how the notebook fetches the newest commit instead of using embedded source files.

**Closing (30 seconds).** Highlight one-button launching, GitHub-based source updates, independent per-time intake records and core Python rules without ML.
