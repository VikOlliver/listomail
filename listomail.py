#!/usr/bin/env python3
"""
listomail - simple modular mailing list manager

Phase: 1 (check + run skeleton)

Copyright (C) 2026 Vik Olliver <vik@diamondage.co.nz>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import argparse
import email
from email.header import decode_header
from email.utils import parseaddr
import imaplib
import re
import sys
import configparser
import subprocess
from pathlib import Path


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
        Simple debug output helper (Phase 1).

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
        self.config = None
        self.imap_server = None
        self.imap_port = None
        self.imap_username = None
        self.imap_password = None
        self.imap_folder = "INBOX"
        
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
        seen = set()

        for lineno, addr in read_lines(path):

            if not valid_email(addr):
                debug(
                    f"Line {lineno}: invalid address '{addr}'"
                )
                continue

            key = addr.lower()

            if key in seen:
                debug(
                    f"Line {lineno}: duplicate '{addr}'"
                )
                continue

            seen.add(key)
            members.append(addr)

        self.members = members

        self.member_set = {
            member.lower()
            for member in self.members
        }
        debug(f"Loaded {len(self.member_set)} members")
        
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

def cmd_run(listdir):
    """
    Purpose:
        Execute one processing cycle for a list (stub version).

    Inputs:
        listdir (Path): list directory

    Returns:
        int: exit code

    Notes:
        Phase 1 stub only:
        - no IMAP
        - no SMTP
        - no state tracking
    """

    debug(f"Running list: {listdir}")

    lst = ListDirectory(listdir)
    lst.load()

    print("\n=== Listomail Run (stub) ===\n")
    print(f"List: {lst.address}")
    print(f"Members: {len(lst.members)}\n")

    debug("Step 1: would connect to IMAP (not implemented)")
    debug("Step 2: would fetch unseen messages")
    debug("Step 3: would validate sender")
    debug("Step 4: would distribute via SMTP")
    debug("Step 5: would update state.db")

    print("\nRun complete (stub).\n")
    return 0


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

    failures = 0

    for recipient in lst.members:

        debug(f"Sending to {recipient}")

        msg = f"""From: {lst.address}
To: {lst.address}
Subject: {subject}

{body}
"""

        try:
            subprocess.run(
                ["msmtp", recipient],
                input=msg.encode("utf-8"),
                check=True
            )
        except subprocess.CalledProcessError as e:
            print(f"ERROR sending to {recipient}: {e}")
            failures += 1

    print(f"\nSend complete. Failures: {failures}\n")

    return 1 if failures else 0

def cmd_redistribute(listdir, dry_run=False):
    """
    Purpose:
        Send messages in the list's email inbox to all members

    Inputs:
        listdir (Path): list directory
        dry_run:    If True, go through the motions but do not send emails.

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
        - per-recipient delivery for privacy and reliability
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

            name, sender_addr = parseaddr(from_header)

            authorized = lst.is_member(sender_addr)

            print("\nMessage", msg_id.decode())
            print(" From:", from_header)
            print(" Subject:", subject)

            if not authorized:
                print(" Status: REJECT")
                continue

            print(" Status: AUTHORIZED")

            # --- body extraction ---
            body = get_text_body(msg)

            # --- build outgoing message ---
            outgoing = f"""From: {from_header}
Sender: {lst.address}
To: {lst.address}
Reply-To: {lst.address}
Subject: {subject}

{body}
"""

            print(f"From Header:\n{outgoing}");

            # --- send to list members ---
            for recipient in lst.members:

                if dry_run:
                    print(f"Would send to {recipient}")
                else:
                    print(f"Recipient: {recipient}")
                    subprocess.run(
                        ["msmtp", recipient],
                        input=outgoing.encode("utf-8"),
                        check=True
                    )

            print(" Redistributed")

    finally:
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
    
    p_run = sub.add_parser("run")
    p_run.add_argument("directory", nargs="?", default=".")

    p_send = sub.add_parser("send")
    p_send.add_argument("directory")
    p_send.add_argument("message_file")
    p_send.add_argument("--subject", default=None)

    p_redist = sub.add_parser("redistribute")
    p_redist.add_argument("--dry-run", 
        help="Display message body/bodies",
        action="store_true",
        default=None)
    p_redist.add_argument("directory")

    args = parser.parse_args()

    if args.cmd == "check":
        return cmd_check(Path(args.directory).resolve())

    if args.cmd == "fetch":
        return cmd_fetch(
            Path(args.directory).resolve(),
            args.body
        )
    if args.cmd == "run":
        return cmd_run(Path(args.directory).resolve())

    if args.cmd == "send":
        return cmd_send(
            Path(args.directory).resolve(),
            args.message_file,
            args.subject
        )

    if args.cmd == "redistribute":
        return cmd_redistribute(Path(args.directory).resolve(), args.dry_run)


    parser.print_help()
    return 1

if __name__ == "__main__":
    sys.exit(main())

