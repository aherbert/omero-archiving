#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.

# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
# REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
# INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
# LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE
# OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
# PERFORMANCE OF THIS SOFTWARE.
# ------------------------------------------------------------------------------

"""
This script tests sending an email from Python to test the localhost SMTP server
is correctly configured.
"""

import sys
from os.path import basename
from os import getpid
from optparse import OptionParser
from optparse import OptionGroup
import smtplib

# Gather our code in a main() function
def main():
    prog = basename(sys.argv[0])

    parser = OptionParser(usage="usage: %prog e-mail [e-mail2 ...]",
        description="Program to send a test e-mail to the given addresses",
        add_help_option=False)

    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit()

    (options, args) = parser.parse_args()

    sender = 'anon@host.com'
    receivers = []

    for arg in args:
      receivers.append(arg)

    message = """From: Test <%s>
To: %s
Subject: SMTP e-mail test

This is a test e-mail message from %s.
""" % (sender, ", ".join(receivers), prog)

    smtpObj = smtplib.SMTP('localhost')
    smtpObj.sendmail(sender, receivers, message)
    smtpObj.quit()
    print("Successfully sent email")

# Standard boilerplate to call the main() function to begin
# the program.
if __name__ == '__main__':
    main()
