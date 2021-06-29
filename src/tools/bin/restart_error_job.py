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
This script processes all the job files listed on the command line. The files 
are moved to the running directory and the error flags removed from the job file
(allowing it to restart).
"""
import sys
import os
import shutil
import configparser

from optparse import OptionParser, OptionGroup

import gdsc.omero

###############################################################################


def init_options():
    """Initialise the program options"""

    parser = OptionParser(usage="usage: %prog [options] list",
                          description="Program to restart error job files",
                          add_help_option=True, version="%prog 1.0")

    group = OptionGroup(parser, "Archive")
    group.add_option("--archive_job", dest="archive_job",
                     default=gdsc.omero.ARCHIVE_JOB,
                     help="Directory for archive jobs [%default]")
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
    
def fatal(msg):
    """
    Print a fatal error
    @param msg: The message
    """
    print("FATAL:", msg)
    
def die(msg):
    """
    Print a fatal error then exit
    @param msg: The message
    """
    fatal(msg)
    sys.exit(1)

###############################################################################
    
def process_job(job_file):
    """
    Process the archive job file
    @param job_file: The job file path
    """
    global options

    log("Processing job " + job_file)
    
    if not os.path.exists(job_file):
        raise Exception("File does not exist: " + job_file);

    # Open the job file
    job = configparser.RawConfigParser()
    job.optionxform = lambda option: option
    job.read(job_file)
    
    if (job.has_option(gdsc.omero.JOB_INFO, 'error')):
        job.remove_option(gdsc.omero.JOB_INFO, 'error')
    
    # Count the number of files to restart
    count = 0
    size = 0
    for (path, status) in job.items(gdsc.omero.JOB_FILES):
        if status == gdsc.omero.JOB_ERROR:
            count = count + 1
            status = gdsc.omero.JOB_RUNNING
            job.set(gdsc.omero.JOB_FILES, path, status)
        if status == gdsc.omero.JOB_RUNNING:
            size = size + 1

    if size:
        job.set(gdsc.omero.JOB_INFO, 'status', gdsc.omero.JOB_RUNNING)
        
    # Process the files
    log("  Restarting %d error file%s (total of %d running file%s)" % 
        (
         count, '' if count == 1 else 's',
         size, '' if size == 1 else 's'
         ))

    # Save changes to the job file
    with open(job_file, 'w') as f:
        job.write(f)

    # Move to the running folder
    current_dir = os.path.dirname(os.path.abspath(job_file))
    dir = os.path.join(options.archive_job, gdsc.omero.JOB_RUNNING)
    if current_dir != dir:
        log("  Moving %s to %s" % (job_file, dir))
        shutil.move(job_file, dir)        
    else:
        log("  File %s already in %s" % (job_file, dir))
        
def check_dir(path, carp=True):
    """
    Check the path exists
    @param path: The path
    @param carp: Raise exception if the path does not exist, otherwise warn
    """
    if not os.path.isdir(path):
        if carp:
            raise Exception("Path is not a directory: %s" % path)
        else:
            error("Path is not a directory: %s" % path)

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

# Gather our code in a main() function
def main():
    
    parser = init_options()
    
    global options
    (options, args) = parser.parse_args()

    # Get the job files
    filenames = args
    
    n = len(filenames)
    if not n:
        die("No job files specified")

    try:
        pid_file = gdsc.omero.PIDFile(
            os.path.join(options.archive_job, 
                         os.path.basename(__file__) + '.pid'))
    except Exception as e:
        die("Cannot start process: %s" % e)
        
    banner("Restart Error Jobs")

    try:

        check_dir(options.archive_job)
        check_dir(os.path.join(options.archive_job, gdsc.omero.JOB_RUNNING))
        check_dir(os.path.join(options.archive_job, gdsc.omero.JOB_ERROR))

        log("Processing %d job%s" % (n, gdsc.omero.pleural(n)))
    
        for path in filenames:
            process_job(path)
            
    except Exception as e:
        fatal("An error occurred: %s" % e)
            
    pid_file.delete()
            

# Standard boilerplate to call the main() function to begin
# the program.
if __name__ == '__main__':
    main()
