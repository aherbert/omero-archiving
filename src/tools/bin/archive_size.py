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
This script processes all the files listed in the a file list and checks
the files still exist. Can be used to check the register of files archived
from OMERO.
"""
import sys
import os
import time
from stat import *
import fileinput

from optparse import OptionParser, OptionGroup

import gdsc.omero

###############################################################################


def init_options():
    """Initialise the program options"""

    parser = OptionParser(usage="usage: %prog [options] list [list2 ...]",
                          description="Total the size of files in a file list",
                          add_help_option=True, version="%prog 1.0")

    parser.add_option("-v", "--verbose", dest="verbose", default=False,
                      action='store_true', help="Verbose mode")

    return parser

###############################################################################

def log(msg):
    """
    Print a message
    @param msg: The message
    """
    print(msg)

def error(msg):
    """
    Print an error message
    @param msg: The message
    """
    print("ERROR:", msg)

def die(msg):
    """
    Print an error then exit
    @param msg: The message
    """
    print("FATAL:", msg)
    sys.exit(1)

###############################################################################

def pleural(count):
    """
    Convenience method to return an s if the count is not 1
    @param count: The count
    """
    return '' if count == 1 else 's'

# Gather our code in a main() function
def main():
    parser = init_options()
    global options
    (options, args) = parser.parse_args()

    if not args:
        parser.print_help()
        sys.exit(0)

    try:
        files = 0
        size = 0
        for path in fileinput.input(args):
            path = path.rstrip('\r\n')
            if os.path.isfile(path):
                r = os.stat(path)
                files = files + 1
                size = size + r.st_size
                if options.verbose:
                    print ("%s : %d (%s) : %s" % (path, r.st_size,
                           gdsc.omero.convert(r.st_size),
                           time.ctime(r.st_mtime)))
            else:
                error("File does not exist: %s" % path)

        print ("%d files : %d (%s)" % (files, size,
                gdsc.omero.convert(size)))
    except Exception as e:
        die("An error occurred: %s" % e)

# Standard boilerplate to call the main() function to begin
# the program.
if __name__ == '__main__':
    main()
