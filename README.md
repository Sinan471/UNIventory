# UNIventory

UNIventory is a university resource reuse and asset management prototype. It helps staff discover available resources, request transfers, track custody and maintenance, and review sustainability outcomes.

Developed for COSC 336, Khalifa University, by Sinan Saleem, Jesher Jebson and Jessica John.

## Run the demo

The application is in [univentory](univentory/). Follow the [setup instructions](univentory/README.md#quick-start-local-development) and the [demo guide](univentory/DEMO_GUIDE.md) for sample accounts and scenarios. The demo uses synthetic records and development sign-in.

**The demo reset command deletes the local SQLite database.** Back up any data you want to keep before using it.

## Current scope and limitations

The integrated prototype covers asset records, catalogue search, requests, approvals, transfers, maintenance, reporting and sustainability views. Assistance features use rule-based fallbacks; a live AI model is not configured. KU sign-in requires university registration, and automatic hold expiry requires a scheduled worker. See the [demo guide](univentory/DEMO_GUIDE.md#7-honest-limits) and [implementation review](univentory/docs/PLAN_REVIEW.md#6-open-items-not-done) for details and outstanding work.

## Project documents

The phase documents are in the repository root. The [application README](univentory/README.md) describes setup, testing and technical documentation. Older handoff notes describe earlier development snapshots; consult the implementation review for the later integration review.

