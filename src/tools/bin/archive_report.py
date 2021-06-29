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
This script processes all the files listed in the archive register to produce
a report of the amount of data archived.
"""
import sys
import os
import configparser
import traceback

from optparse import OptionParser, OptionGroup

import gdsc.omero

###############################################################################

def init_options():
    """Initialise the program options"""

    parser = OptionParser(usage="usage: %prog [options] list",
                          description="Report on the archived files",
                          add_help_option=True, version="%prog 1.0")

    group = OptionGroup(parser, "Archive")
    group.add_option("--archive_log", dest="archive_log",
                     default=gdsc.omero.ARCHIVE_LOG,
                     help="Directory for archive logs [%default]")
    group.add_option("--to_archive", dest="to_archive", 
                     default=gdsc.omero.TO_ARCHIVE_REGISTER,
                     help="To-Archive register [%default]")
    group.add_option("--archived", dest="archived", 
                     default=gdsc.omero.ARCHIVED_REGISTER,
                     help="Archived register [%default]")
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

def banner(title):
    """
    Write a banner
    @param title the banner title
    """
    size = len(title)
    banner = '-=' * int(size/2)
    if (len(banner) < size):
        banner = banner + '-'
    log(banner)
    log(title)
    log(banner)

def summarise(report):
    """
    Summarise the reported archive usage
    @param report: The reported archive usage
    """
    banner(report['name'])
    total = report['count'] - report['missing']
    log("%d / %d file%s" % (total, report['count'], 
                            gdsc.omero.pleural(report['count'])))
    log("%d byte%s (%s)" % (report['bytes'], 
                            gdsc.omero.pleural(report['bytes']),
                            gdsc.omero.convert(report['bytes'])))
    
def build_report(name, items):
    """
    Build a summary of the archived paths using the .ark files
    @param name: The name of the set
    @param items: The set of archive paths
    """
    global options
    report = {}
    report['name'] = name
    report['count'] = len(items)
    
    sum = 0
    missing = 0
    for path in items:
        ark_file = gdsc.omero.get_ark_path(options.archive_log, path)
        if not os.path.isfile(ark_file):
            error("Missing archive record for '%s' file: %s" % (name, path))
            missing = missing + 1
        else:
            config = configparser.RawConfigParser()
            config.read(ark_file)
            # Can get 'image', 'owner', 'linked by', 'path', 'bytes'
            sum = sum + int(config.get(gdsc.omero.ARK_SOURCE, 'bytes'))
    
    report['bytes'] = sum
    report['missing'] = missing
    
    return report

# Gather our code in a main() function
def main():
    parser = init_options()
    global options
    (options, args) = parser.parse_args()

    try:
        # Open the registers
        register = gdsc.omero.Register(options.to_archive)
        archived = gdsc.omero.Register(options.archived)

    except Exception as e:
        die("An error occurred: %s" % e)
        
    # Check for files in the To-Archive and Archived register
    intersect = register.items.intersection(archived.items)
    if intersect:
        size = len(intersect)
        error("%d file%s already archived, ignoring" % (size, 
              '' if size == 1 else 's'))
        register.remove_list(list(intersect))

    try:
        to_archive = build_report('To archive', register.items)
        archived = build_report('Archived', archived.items)
        
        summarise(to_archive)
        summarise(archived)

    except Exception as e:
        traceback.print_exc()
        die("An error occurred: %s" % e)

# Standard boilerplate to call the main() function to begin
# the program.
if __name__ == '__main__':
    main()
