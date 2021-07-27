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
This script processes all the files listed on the command line and outputs
the Arkivum information obtained from the REST API.
"""
import sys
import os
import re
import requests
import urllib

# Get rid of the Unverified HTTPS request warning
try:
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except:
    pass

from optparse import OptionParser, OptionGroup

import gdsc.omero
import pprint

###############################################################################

def init_options():
    """Initialise the program options"""

    parser = OptionParser(usage="usage: %prog [options] file [file2 ...]",
                          description="Program to print Arkivum file info",
                          add_help_option=True, version="%prog 1.0")

    group = OptionGroup(parser, "Archive")
    group.add_option("--arkivum_root", dest="arkivum_root",
                     default=gdsc.omero.ARKIVUM_ROOT,
                     help="Arkivum root (for the mounted appliance) [%default]")
    group.add_option("--arkivum_path", dest="arkivum_path",
                     default=gdsc.omero.ARKIVUM_PATH,
                     help="Arkivum path (directory for OMERO files) [%default]")
    parser.add_option_group(group)

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

def get_info(rel_path):
    """
    Get the file information from the Arkivum REST API
    @param rel_path: The path to the file on the Arkivum server
    """
    url = ('https://'+gdsc.omero.ARKIVUM_SERVER+
          '/api/2/files/fileInfo/'+urllib.quote(rel_path))
    # Do not verify the SSL certificate
    r = requests.get(url, verify=False)

    # What to do here? Arkivum has a 10 minute delay
    # between copying a file and the ingest starting. So it may
    # not show in the API just yet.
    if r.status_code == 200:
        try:
            return r.json()
        except:
            pass
    else:
        error("REST API response code: " + str(r.status_code))
    return {}

def process(path):
    """
    Get information on the file from the Arkivum server
    @param path: The file path
    """
    global options

    log("Processing file: " + path)

    # Try to determine the files relative path on the Arkivum appliance from
    # the input path, E.g
    #
    # Original path:
    # /OMERO/ManagedRepository/user1_1/2/016-04/04/16-57-37.543/__utm.gif
    #
    # Relative path on Arkivum appliance
    # [options.arkivum_path]/OMERO/ManagedRepository/user1_1/2/016-04/04/16-57-37.543/__utm.gif
    #
    # Path on mounted appliance filesystem
    # [options.arkivum_root]/[options.arkivum_path]/OMERO/ManagedRepository/user1_1/2/016-04/04/16-57-37.543/__utm.gif

    # Strip the Arkivum root if the input file was a file on the mounted FS
    if path.startswith(options.arkivum_root):
        path = path[len(options.arkivum_root):]
        # Do nothing else so the script can be used to query any file

    else:
        # Make relative
        if path.startswith('/'):
            path = path[1:]

        # Add the path prefix for the storage location on the Arkivum appliance.
        # This can happen if the input file was the original OMERO location.
        if not path.startswith(options.arkivum_path):
            path = os.path.join(options.arkivum_path, path)

    # Make relative
    if path.startswith('/'):
        path = path[1:]

    # Make sure there are no extra directory dividers as this breaks the API
    path = re.sub('\/+','/', path)

    log("Arkivum relative path: " + path)

    # Connect to the Arkivum server and get the file information
    info = get_info(path)
    if len(info):
        pp.pprint(info)
    else:
        error("No information available")

def check_dir(path, carp=True):
    """
    Check the path exists
    @param path: The path
    @param carp: Die if the path does not exist, otherwise warn
    """
    if not os.path.isdir(path):
        if carp:
            die("Path is not a directory: %s" % path)
        else:
            error("Path is not a directory: %s" % path)

# Gather our code in a main() function
def main():
    parser = init_options()
    global options
    global pp
    (options, args) = parser.parse_args()
    pp = pprint.PrettyPrinter(indent=2)

    check_dir(options.arkivum_root)
    check_dir(os.path.join(options.arkivum_root, options.arkivum_path))

    try:
        # For each file
        for path in args:
            process(path)

    except Exception as e:
        die("An error occurred: %s" % e)

# Standard boilerplate to call the main() function to begin
# the program.
if __name__ == '__main__':
    main()
