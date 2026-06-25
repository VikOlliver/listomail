# Listomail

A minimal IMAP-based mailing list processor written in Python and desparation. It utilises and existing email account accessed by msmtp and fetchmail.

Listomail fetches incoming email from an IMAP inbox, applies simple policy rules (membership and duplicate detection), and redistributes messages to a mailing list via SMTP using BCC-style delivery.

It is designed to be:

- Simple
- Dependency-light
- Cron-friendly
- Easy to debug without a database

---

## Features (current)

- IMAP mailbox polling
- Sender authorisation via member list
- Duplicate suppression via Message-ID tracking (seen.txt)
- SMTP broadcast via SMTP envelope fan-out (atomic send)
- Basic reject logging
- Optional message deletion after successful processing

## Features (Imminent)

- Gmail-compatible multipart email support (basic text extraction)

---

## Directory structure

```
examples/<listname>/
    list.conf
    members.txt
    state/
        seen.txt
        reject.log
```

---

## Processing model

Each email is processed through a simple pipeline:

1. Fetch message via IMAP
2. Extract headers (From, Subject, Message-ID)
3. Skip if already seen
4. Reject if sender is not a member
5. Extract message body (plain text preferred)
6. Send to list via single SMTP call
7. Mark Message-ID as seen
8. Optionally delete from IMAP

---

## Design principles

- No database
- No queue system
- Append-only state files
- Fail-safe processing (no premature deletion)
- Clear separation of:
  - configuration (list.conf)
  - membership (members.txt)
  - runtime state (state/)

---

## MIME handling

Listomail currently supports basic multipart email:

- Prefers text/plain
- Falls back to raw payload if necessary
- HTML and attachments are ignored at this stage

Future versions may extend this to full MIME preservation.

---

## Reject handling

Rejected messages (e.g. non-members) are logged to:

```
state/reject.log
```

Each entry includes:

- Timestamp
- Sender
- Subject
- Message-ID
- Reason for rejection

---

## Operational notes

- Designed for cron execution
- Safe for repeated runs (idempotent via Message-ID tracking)
- Requires working IMAP and SMTP credentials
- SMTP delivery uses BCC for atomic broadcast

---

## Known limitations

- No attachment forwarding
- No HTML rendering
- No bounce parsing beyond basic detection
- No retry queue or persistent error handling system

---

## Future work (roadmap)

- Better MIME/attachment handling
- Bounce parsing (DSN extraction)
- Structured logging
- Optional moderation mode
- Message archiving system
- Web/admin interface (optional, long-term, would rather avoid...)

---

## Philosophy

> Keep it as simple as possible, but no simpler.
