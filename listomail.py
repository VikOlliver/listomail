#!/usr/bin/env python3
"""
listomail - simple modular mailing list manager

Phase: 2 Support multiple mail server accounts

Copyright (C) 2026 Vik Olliver <vik@diamondage.co.nz>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import argparse
import configparser
from datetime import datetime
import email
from email.header import decode_header
from email.utils import parseaddr
import imaplib
from pathlib import Path
import re
import subprocess
import sys
import time


EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
)
VERSION = "0.2"

# ----------------------------
# Utility functions
# ----------------------------

def debug(msg):
    """
    Purpose:
        Simple debug output helper (Phase 2).

    Inputs:
        msg (str): message to print

    Returns:
        None

    Side effects:
        prints to stdout if enabled
    """
    print(f"[listomail V{VERSION}] {msg}")


def read_lines(path):
    """
    Purpose:
        Reads a text file and yields cleaned (line_number, value) pairs.
        Lines starting with # are treated as comments.

    Inputs:
        path (Path): file path

    Returns:
        list[tuple[int, str]]

    Side effects:
        None
    """
    results = []

    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            results.append((lineno, line))

    return results


def valid_email(addr):
    """
    Purpose:
        Basic email validation (intentionally simple).

    Inputs:
        addr (str): email address

    Returns:
        bool
    """
    return bool(EMAIL_RE.match(addr))

def get_text_body(msg):
    """
    Purpose:
        Extract the payloads from a RFC822 message

    Inputs:
        msg: 

    Returns:
        list of decoded payloads
    """

    if not msg.is_multipart():

        payload = msg.get_payload(decode=True)

        charset = msg.get_content_charset() or "utf-8"

        return payload.decode(
            charset,
            errors="replace"
        )

    for part in msg.walk():

        if part.get_content_type() != "text/plain":
            continue

        if part.get_filename():
            continue

        payload = part.get_payload(decode=True)

        charset = part.get_content_charset() or "utf-8"

        return payload.decode(
            charset,
            errors="replace"
        )

    return ""

class ListDirectory:
    """
    Purpose:
        Represents a single mailing list directory.

    Inputs:
        directory (str|Path): list directory path

    Returns:
        ListDirectory object

    Side effects:
        None
    """

    def __init__(self, directory):
        self.directory = Path(directory)

        self.address = None
        self.members = []
        self.list_name = None
        self.config = None
        self.imap_server = None
        self.imap_port = None
        self.imap_username = None
        self.imap_password = None
        self.imap_folder = "INBOX"
        self.smtp_batch_size = None
        self.msmtp_account = None
        self.smtp_rate_limit = 0
        self.state_dir = self.directory / "state"
        self.seen_file = self.state_dir / "seen.txt"
        self.reject_log = self.state_dir / "reject.log"
                
    def is_member(self, address):
        """
        Purpose:
            Determine whether an email address belongs
            to a list member.

        Inputs:
            address (str)

        Returns:
            bool
        """
        return address.lower() in self.member_set
    
    # ----------------------------
    # List loading
    # ----------------------------

    def load_config(self):
        """
        Purpose:
            Loads list.conf into memory.
            Sets, and if necessary creates, the state file seen.txt

        Inputs:
            None

        Returns:
            None

        Side effects:
            Updates self.config and self.address.
        """

        path = self.directory / "list.conf"

        if not path.exists():
            raise ValueError("Missing list.conf")

        config = configparser.ConfigParser()
        config.read(path)

        self.config = config

        self.address = config["list"]["address"]
        self.imap_server = config["imap"]["server"]
        self.imap_port = int(config["imap"]["port"])
        self.imap_username = config["imap"]["username"]
        self.imap_password = config["imap"]["password"]
        self.imap_folder = config["imap"].get(
            "folder",
            "INBOX"
        )

        # Cleanly default the batch size to everything
        try:
            self.smtp_batch_size = config["list"].getint("smtp_batch_size", fallback=0)
            
        except ValueError:
            print("Invalid smtp_batch_size in list.conf")
            sys.exit(1)
            
        self.list_name = config["list"].get("list_name")
        if not self.list_name:
            raise ValueError("Missing required setting: [list] list_name")

        # If no SMTP rate limit (msgs per hour) is set, use zero to indicate no limit
        try:
            self.smtp_rate_limit = config["list"].getint("smtp_rate_limit", fallback=0)

        except ValueError:
            print("Invalid smtp_rate_limit in list.conf")
            sys.exit(1)

        # If there is a specific msmtp account specified, use that
        self.msmtp_account = config["list"].get("msmtp_account", "").strip()
        if self.msmtp_account:
            print(f"Using account '{self.msmtp_account}' to send mail via msmtp")
        else:
            print("Using default msmpt account to send mail via msmtp")
            
    
        # Make sure somewhere exists to save email message states etc.
        self.state_dir.mkdir(exist_ok=True)
        if not self.seen_file.exists():
            self.seen_file.touch()      
        
        
    def load_members(self):
        """
        Purpose:
            Loads members.txt.

        Inputs:
            None

        Returns:
            list[str]

        Side effects:
            Updates self.members.
        """

        path = self.directory / "members.txt"

        if not path.exists():
            raise ValueError("Missing members.txt")

        members = []
        dedupe = set()

        for lineno, addr in read_lines(path):

            if not valid_email(addr):
                debug(
                    f"Line {lineno}: invalid address '{addr}'"
                )
                continue

            key = addr.lower()

            if key in dedupe:
                debug(
                    f"Line {lineno}: duplicate '{addr}'"
                )
                continue

            dedupe.add(key)
            members.append(addr)

        self.members = members

        self.member_set = {
            member.lower()
            for member in self.members
        }
        debug(f"Loaded {len(self.member_set)} members")
        

    def load_seen(self):
        """
        Purpose:
            Loads already seen message IDs from the seen.txt file

        Inputs:
            None

        Returns:
            None

        Side effects:
            Updates self.seen_set
        """
        self.seen_set = set()

        if self.seen_file.exists():
            with open(self.seen_file, "r", encoding="utf-8") as f:
                for line in f:
                    # Tidy the whitespace and ignore blank lines or comments
                    # to prevent pollution of the header file.
                    msgid = line.strip()
                    if not line:
                        continue
                    if line.startswith("#"):
                        continue
                    if msgid:
                        self.seen_set.add(msgid)

    # Convenient fast lookup using above message ID list
    def is_seen(self, message_id):
        return message_id in self.seen_set

    # And this marks a message as seen (unless we already have, which is Inception Level)
    def mark_seen(self, message_id):
        if message_id in self.seen_set:
            return

        self.seen_set.add(message_id)

        with open(self.seen_file, "a", encoding="utf-8") as f:
            f.write(message_id + "\n")
            
    # Adds message details to the reject log for manual debugging/analysis
    def log_reject(self, sender, subject, message_id, reason):
        with open(self.reject_log, "a", encoding="utf-8") as f:
            f.write(
                f"{datetime.now().isoformat(timespec='seconds')}\n"
                f"From: {sender or '(none)'}\n"
                f"Subject: {subject or '(none)'}\n"
                f"Message-ID: {message_id or '(none)'}\n"
                f"Reason: {reason}\n"
                "\n"
            )

    def connect_imap(self):
        """
        Purpose:
            Connect to IMAP server.

        Inputs:
            None

        Returns:
            IMAP4_SSL connection

        Side effects:
            Opens network connection.
        """

        debug(
            f"Connecting to IMAP "
            f"{self.imap_server}:{self.imap_port}"
        )

        conn = imaplib.IMAP4_SSL(
            self.imap_server,
            self.imap_port
        )

        conn.login(
            self.imap_username,
            self.imap_password
        )

        return conn

    def connect_imap(self):
        """
        Purpose:
            Connect to IMAP server.

        Inputs:
            None

        Returns:
            IMAP4_SSL connection

        Side effects:
            Opens network connection.
        """

        debug(
            f"Connecting to IMAP "
            f"{self.imap_server}:{self.imap_port}"
        )

        conn = imaplib.IMAP4_SSL(
            self.imap_server,
            self.imap_port
        )

        conn.login(
            self.imap_username,
            self.imap_password
        )

        return conn

    def load(self):
        """
        Purpose:
            Loads all list configuration.

        Inputs:
            None

        Returns:
            None

        Side effects:
            Updates object state.
        """

        self.load_config()
        self.load_members()
        self.load_seen()
    
# ----------------------------
# CHECK COMMAND
# ----------------------------

def cmd_check(listdir):
    """
    Purpose:
        Validate a list directory configuration.

    Inputs:
        listdir (Path): list directory

    Returns:
        int: exit code
    """
    debug(f"Checking list directory: {listdir}")

    errors = []
    warnings = []

    lst = ListDirectory(listdir)
    lst.load()

    if lst.address:
        print(f"List: {lst.address}\n")

    print(f"Members: {len(lst.members)}\n")

    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"  {w}")
        print()

    if errors:
        print("Errors:")
        for e in errors:
            print(f"  {e}")
        print()
        return 1

    print("No errors found.\n")
    return 0


def cmd_fetch(listdir, body_flag):
    """
    Purpose:
        Fetch message headers from IMAP.

    Inputs:
        listdir (Path): list directory

    Returns:
        int: exit code

    Side effects:
        Network access only.
    """

    lst = ListDirectory(listdir)
    lst.load()

    conn = lst.connect_imap()

    try:

        status, _ = conn.select(lst.imap_folder)

        if status != "OK":
            print("Unable to open mailbox")
            return 1

        status, data = conn.search(None, "ALL")

        if status != "OK":
            print("Search failed")
            return 1

        msg_ids = data[0].split()

        print(f"\n=== Listomail V{VERSION} Fetch ===\n")
        print(f"Messages found: {len(msg_ids)}\n")

        for msg_id in msg_ids:

            status, msg_data = conn.fetch(
                msg_id,
                "(RFC822)"
            )

            if status != "OK":
                continue

            raw = msg_data[0][1]

            msg = email.message_from_bytes(raw)

            sender = msg.get("From", "")
            sender_name, sender_address = parseaddr(sender)
            authorized = lst.is_member(sender_address)
            subject = msg.get("Subject", "")
            message_id = msg.get("Message-ID", "")
            date = msg.get("Date", "")

            print(f"Message {msg_id.decode()}")
            print(f"  From: {sender}")
            print(f"  Subject: {subject}")
            print(f"  Message-ID: {message_id}")
            print(f"  Date: {date}")
            print()
            if authorized:
                print("  Status: AUTHORIZED")
            else:
                print("  Status: REJECT")

            print()

            print()
            print("Multipart:", msg.is_multipart())
            print()

            if body_flag:
                if msg.is_multipart():
                    body = get_text_body(msg)

                    print("---- BODY ----")
                    print(body)
                    print("\nParts:")

                    for part in msg.walk():
                        print("Part:", part.get_content_type())
                else:
                    body = msg.get_payload(decode=True)
                    charset = msg.get_content_charset()

                    if charset is None:
                        charset = "utf-8"

                    print(body.decode(charset, errors="replace"))


    finally:
        conn.logout()

    return 0
    
    
# ----------------------------
# RUN COMMAND (SKELETON)
# ----------------------------

def cmd_send(listdir, message_file, subject=None):
    """
    Purpose:
        Send an administrative or test message to all list members.

    Inputs:
        listdir (Path): list directory
        message_file (str|Path): file containing message body
        subject (str|None): optional subject line

    Returns:
        int: exit code

    Side effects:
        Sends email via msmtp (one per recipient)

    Notes:
        This is intentionally simple:
        - no IMAP
        - no state tracking
        - no retries
        - per-recipient delivery for privacy and reliability
    """

    lst = ListDirectory(listdir)
    lst.load()

    message_file = Path(message_file)

    if not message_file.exists():
        print(f"ERROR: message file not found: {message_file}")
        return 1

    with open(message_file, "r", encoding="utf-8") as f:
        body = f.read()

    if subject is None:
        subject = "Listomail message"

    debug(f"Sending message to {len(lst.members)} recipients")

    msg = f"""From: {lst.address}
To: {lst.address}
Subject: {subject}

{body}
"""

    try:
        # Send to list members. Use specific msmtp accoutn if specified.
        cmd = ["msmtp"]
        if lst.msmtp_account:
            cmd.append("--account=" + lst.msmtp_account)
        cmd.extend(lst.members)
        subprocess.run(
            cmd,
            input = msg.encode("utf-8"),
            check = True
        )

    except subprocess.CalledProcessError as e:
        print(f"ERROR sending message: {e}")
        return 1

    print(f"\nSend complete.\n")

    return 0

def cmd_redistribute(listdir, dry_run=False, delete=False):
    """
    Purpose:
        Send messages in the list's email inbox to all members
        Some fiddling of From: field needed because these days
        that needs to be the same as the sending account.

    Inputs:
        listdir (Path): list directory
        dry_run:    If True, go through the motions but do not send emails.
        delete:     If True, delete messages from inbox after successfully completing send

    Returns:
        int: exit code

    Side effects:
        Sends email via msmtp (one per recipient)

    Notes:
        This is intentionally simple:
        - no IMAP
        - no state tracking
        - no retries
        - Uses "Sender:" to please the member's mail server
        - recipient list delivery (not BCC) for privacy and reliability
    """

    lst = ListDirectory(listdir)
    lst.load()

    conn = lst.connect_imap()

    try:
        conn.select(lst.imap_folder)

        status, data = conn.search(None, "ALL")

        if status != "OK":
            print("IMAP search failed")
            return 1

        msg_ids = data[0].split()

        print(f"[listomail] Messages found: {len(msg_ids)}")

        for msg_id in msg_ids:

            status, msg_data = conn.fetch(
                msg_id,
                "(RFC822)"
            )

            if status != "OK":
                continue

            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            # --- headers ---
            from_header = msg.get("From", "")
            subject = msg.get("Subject", "")
            message_id = msg.get("Message-ID", "")

            # If we've seen this one before, don't send it
            if lst.is_seen(message_id):
                print(f" Status: SEEN\nRejecting {message_id}")
                lst.log_reject(from_header, subject, message_id, "Message already seen")
                continue

            name, sender_addr = parseaddr(from_header)

            authorized = lst.is_member(sender_addr)

            print("\nMessage", msg_id.decode())
            print(" From:", from_header)
            print(" Subject:", subject)

            if not authorized:
                print(" Status: REJECT")
                lst.log_reject(from_header, subject, message_id, "Unauthorised sender")
                continue

            print(" Status: AUTHORIZED")

            # --- body extraction ---
            body = get_text_body(msg)

            # --- build outgoing message with a compliant sender name ---
            if name:
                from_display = f"{name} via {lst.list_name}"
            else:
                from_display = f"{sender_addr} via {lst.list_name}"

            outgoing = f"""From: {from_display} <{lst.address}>
Sender: {lst.address}
To: {lst.address}
Reply-To: {lst.address}
Subject: {subject}
List-Id: {lst.list_name} <{lst.address.replace("@", "-")}>
List-Post: <mailto:{lst.address}>
Precedence: list
X-Original-From: {from_header}

{body}
"""
            # Send to list members. Use specific msmtp accoutn if specified.
            cmd = ["msmtp"]
            if lst.msmtp_account:
                cmd.append("--account=" + lst.msmtp_account)
            cmd.extend(lst.members)
            sent_ok = True

# Messages are only marked as seen if all SMTP batches succeed.
# A later batch failure may result in duplicate delivery to earlier
# recipients on retry. This is a deliberate trade-off to avoid
# maintaining per-recipient delivery state.

            # Create sublists of a sizer that won't annoy the mailservers
            # Batch size of zero just sends the whole list in one transaction
            if lst.smtp_batch_size == 0:
                batch_size = len(lst.members)
            else:
                batch_size = lst.smtp_batch_size
        
            # Use this delay between batches. Note: if batch size exceeds
            # rate limit of msgs per hr, this will not rate limit. So use batches.
            if lst.smtp_rate_limit > 0:
                rate_limit_delay = 3600 * lst.smtp_batch_size / lst.smtp_rate_limit
            else:
                rate_limit_delay = 0

            for i in range(0, len(lst.members), batch_size):

                recipients = lst.members[i:i + batch_size]
                cmd = ["msmtp"] + recipients
                
                try:
                    if dry_run:
                        print(f"Would send to: {', '.join(recipients)} with {rate_limit_delay} rate limiting delay.")
                    else:
                        print(
                            f"Sending batch "
                            f"{i // batch_size + 1} "
                            f"({len(recipients)} recipients)..."
                        )

                        subprocess.run(
                            cmd,
                            input=outgoing.encode("utf-8"),
                            check=True,
                            capture_output=True
                        )
                        # Having sent it, we need to limit the send rate by waiting
                        if rate_limit_delay > 0:
                            print(f"Delaying for {rate_limit_delay} seconds to limit send rate")
                            # We want to tickle the IMAP every 60 seconds so that the connection doesn't fail
                            interval = 60
                            remaining_time = rate_limit_delay
                            while remaining_time > 0:
                                sleep_time = min(interval, remaining_time)
                                time.sleep(sleep_time)
                                conn.noop()
                                remaining_time -= sleep_time

                except subprocess.CalledProcessError as e:
                    sent_ok = False

                    print(
                        f"[listomail] SMTP failed "
                        f"(exit {e.returncode})"
                    )

                    if e.stderr:
                        print(
                            e.stderr.decode(
                                "utf-8",
                                errors="replace"
                            )
                        )

                    break
                    
            # --- Check for successful send ---
            if sent_ok:
                print(" Redistributed")
                if dry_run:
                    print("Would have marked as 'seen'.")
                else:
                    lst.mark_seen(message_id)
                if delete:
                    if dry_run:
                        print("Would have deleted message.")
                    else:
                        conn.store(msg_id, "+FLAGS", "\\Deleted")

    finally:
        if delete:
            print("[listomail] Expunging deleted messages")
            conn.expunge();
        conn.logout()

    return 0


# ----------------------------
# CLI
# ----------------------------

def main():
    parser = argparse.ArgumentParser(prog="listomail")

    sub = parser.add_subparsers(dest="cmd")

    p_check = sub.add_parser("check")
    p_check.add_argument("directory", nargs="?", default=".")

    p_fetch = sub.add_parser("fetch")
    p_fetch.add_argument(
        "directory",
        nargs="?",
        default="."
    )
    p_fetch.add_argument("--body",
        action="store_true",
        help="Display message body/bodies"
    )
    
    p_send = sub.add_parser("send")
    p_send.add_argument("directory")
    p_send.add_argument("message_file")
    p_send.add_argument("--subject", default=None)

    p_redist = sub.add_parser("redistribute")
    p_redist.add_argument("--dry-run", 
        help="Display message body/bodies",
        action="store_true",
        default=None)
    p_redist.add_argument(
        "--delete",
        action="store_true",
        help="Delete successfully redistributed messages from IMAP"
    )
    p_redist.add_argument("directory")

    args = parser.parse_args()

    if args.cmd == "check":
        return cmd_check(Path(args.directory).resolve())

    if args.cmd == "fetch":
        return cmd_fetch(
            Path(args.directory).resolve(),
            args.body
        )
    if args.cmd == "send":
        return cmd_send(
            Path(args.directory).resolve(),
            args.message_file,
            args.subject
        )

    if args.cmd == "redistribute":
        return cmd_redistribute(
            Path(args.directory).resolve(),
            args.dry_run,
            args.delete
        )


    parser.print_help()
    return 1

if __name__ == "__main__":
    sys.exit(main())

