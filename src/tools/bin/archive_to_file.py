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
This script processes all the files listed in the archive register. A checksum
is computed, the file copied to the archive, a checksum made to confirm
the copy and the original removed. A symbolic link is made from the original
location to the archived file.
"""
import sys
import os
import shutil
import time
import configparser
import hashlib
from stat import *
from zlib import adler32

import re
import platform
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import COMMASPACE, formatdate

from optparse import OptionParser, OptionGroup

import gdsc.omero

###############################################################################


def init_options():
    """Initialise the program options"""

    parser = OptionParser(usage="usage: %prog [options] list",
                          description="Program to archive files to a file store",
                          add_help_option=True, version="%prog 1.0")

    group = OptionGroup(parser, "Archive")
    group.add_option("--archive_log", dest="archive_log",
                     default=gdsc.omero.ARCHIVE_LOG,
                     help="Directory for archive logs [%default]")
    group.add_option("--archive_job", dest="archive_job",
                     default=gdsc.omero.ARCHIVE_JOB,
                     help="Directory for archive jobs [%default]")
    group.add_option("--archive_root", dest="archive_root",
                     default=gdsc.omero.ARCHIVE_ROOT,
                     help="Archive root (path to copy files) [%default]")
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

def validate_email(userEmail):
    """
    Checks that a valid email address is present
    @param userEmail: The e-mail address
    """
    # Validate with a regular expression. Not perfect but it will do.
    return re.match("^[a-zA-Z0-9._%-]+@[a-zA-Z0-9._%-]+.[a-zA-Z]{2,6}$",
                    userEmail)

def send_email(userEmail, job_file, result):
    """
    E-mail the result to the user.

    @param userEmail: The e-mail address
    @param job_file : The job file
    @param result   : The result status
    """
    send_to = []
    # Comment this out to prevent admin receiving all the emails
    send_to.extend(gdsc.omero.ADMIN_EMAILS)
    if validate_email(userEmail):
        send_to.append(userEmail)
    if not send_to:
        return

    name = os.path.basename(job_file)

    msg = MIMEMultipart()
    msg['From'] = gdsc.omero.ADMIN_EMAIL
    msg['To'] = COMMASPACE.join(send_to)
    msg['Date'] = formatdate(localtime=True)
    msg['Subject'] = '[OMERO Job] Archive Job : ' + result
    msg.attach(MIMEText("""OMERO Archive Job : %s
Result : %s

Your archive job file is attached.

---
OMERO @ %s """ % (name, result, platform.node())))

    with open(job_file, "rb") as f:
        name = name + '.txt'
        part = MIMEApplication(
            f.read(),
            Name=name
        )
        part['Content-Disposition'] = ('attachment; filename="%s"' % name)
        msg.attach(part)

    smtpObj = smtplib.SMTP('localhost')
    smtpObj.sendmail(gdsc.omero.ADMIN_EMAIL, send_to, msg.as_string())
    smtpObj.quit()

def email_results(userEmail, job_file, result):
    """
    E-mail the result to the user.

    @param userEmail: The e-mail address
    @param job_file : The job file
    @param result   : The result status
    """
    send_email(userEmail, job_file, result)

def get_key(j, key):
    """
    Get the key value from the dictionary object
    @param j: The dictionary object
    @param key: The key value (or empty string)
    """
    return j[key] if key in j else '';

def get_key_number(j, key):
    """
    Get the key value from the dictionary object
    @param j: The dictionary object
    @param key: The key value (or zero)
    """
    return j[key] if key in j else 0;

def get_option(config, option, section = gdsc.omero.ARK_FILE_ARCHIVER):
    """
    Get the option from the Archive section (or return None)
    @param config: The ConfigParser
    @param option: The option
    @param section: The section
    """
    if config.has_option(section, option):
        return config.get(section, option)
    return None

def process(path):
    """
    Archive the file
    @param path: The file path
    """
    global options, state_count, state_size

    log("Processing file " + path)

    if os.path.islink(path):
        warn("Skipping symlink: %s" % path)
        return gdsc.omero.JOB_IGNORE

    r = os.stat(path)
    if not S_ISREG(r.st_mode):
        raise Exception("File does not exist: %s" % path)

    # Record steps to the .ark file
    ark_file = gdsc.omero.get_ark_path(options.archive_log, path)
    if not os.path.isfile(ark_file):
        raise Exception("Missing archive record file: %s" % ark_file)
    log("  Archive record = " + ark_file)
    config = configparser.RawConfigParser(delimiters='=')
    config.read(ark_file)
    if not config.has_section(gdsc.omero.ARK_FILE_ARCHIVER):
        config.add_section(gdsc.omero.ARK_FILE_ARCHIVER)

    archived = False

    try:
        # Create the path in the archive
        full_path = path
        drive, path = os.path.splitdrive(path)
        path, filename = os.path.split(path)

        # Check path is relative (so can be joined)
        index = 0
        while os.path.isabs(path[index:]):
            index = index + 1

        directory = os.path.join(options.archive_root, path[index:])
        if not os.path.exists(directory):
            os.makedirs(directory)

        # Checksum the file & copy to the archive
        ark_path = os.path.join(directory, filename)

        log("  Archive path = " + ark_path)

        # Get the checksums
        md5Digest = get_option(config, 'md5')
        sha256Digest = get_option(config, 'sha256')
        adler32Digest = get_option(config, 'adler32')
        size = get_option(config, 'size')
        if size:
            try:
                size = int(size)
            except:
                pass

        # Store when the file was copied
        file_copied = False
        try:
            timestamp = float(get_option(config, 'timestamp'))
        except:
            timestamp = 0

        if not (os.path.exists(ark_path)):

            # Copy to archive and checksum
            log("  Copying to archive")

            md5Hasher = hashlib.md5()
            sha256Hasher = hashlib.sha256()
            adler32sum = 1
            size = 0
            blocksize = 65536
            with open(full_path, 'rb') as f:
                with open(ark_path, 'wb') as f2:
                    buf = f.read(blocksize)
                    while len(buf) > 0:
                        size = size + len(buf)
                        f2.write(buf)
                        md5Hasher.update(buf)
                        sha256Hasher.update(buf)
                        adler32sum = adler32(buf, adler32sum)
                        buf = f.read(blocksize)

            md5Digest = md5Hasher.hexdigest()
            sha256Digest = sha256Hasher.hexdigest()
            adler32Digest = str(adler32sum & 0xffffffff)

            config.set(gdsc.omero.ARK_FILE_ARCHIVER, 'md5', md5Digest)
            config.set(gdsc.omero.ARK_FILE_ARCHIVER, 'sha256', sha256Digest)
            config.set(gdsc.omero.ARK_FILE_ARCHIVER, 'adler32',
                       adler32Digest)
            config.set(gdsc.omero.ARK_FILE_ARCHIVER, 'size', str(size))
            config.set(gdsc.omero.ARK_FILE_ARCHIVER, 'path', ark_path)

            r = os.stat(ark_path)
            timestamp = r.st_mtime
            config.set(gdsc.omero.ARK_FILE_ARCHIVER, 'copied',
                    time.ctime(timestamp))
            config.set(gdsc.omero.ARK_FILE_ARCHIVER, 'timestamp',
                       str(timestamp))

            file_copied = True

        elif not (size and md5Digest and sha256Digest and adler32Digest):

            # This occurs when the path to the archive already exists.
            # (Possible if the first copy failed part way through.)
            # Compute the checksum on the original file so the script will
            # error later if the archive has a bad copy.
            log("  Computing checksums")

            md5Hasher = hashlib.md5()
            sha256Hasher = hashlib.sha256()
            adler32sum = 1
            size = 0
            blocksize = 65536
            with open(full_path, 'rb') as f:
                buf = f.read(blocksize)
                while len(buf) > 0:
                    size = size + len(buf)
                    md5Hasher.update(buf)
                    sha256Hasher.update(buf)
                    adler32sum = adler32(buf, adler32sum)
                    buf = f.read(blocksize)

            md5Digest = md5Hasher.hexdigest()
            sha256Digest = sha256Hasher.hexdigest()
            adler32Digest = str(adler32sum & 0xffffffff)

            config.set(gdsc.omero.ARK_FILE_ARCHIVER, 'md5', md5Digest)
            config.set(gdsc.omero.ARK_FILE_ARCHIVER, 'sha256', sha256Digest)
            config.set(gdsc.omero.ARK_FILE_ARCHIVER, 'adler32',
                       adler32Digest)
            config.set(gdsc.omero.ARK_FILE_ARCHIVER, 'size', str(size))
            config.set(gdsc.omero.ARK_FILE_ARCHIVER, 'path', ark_path)


        # Report the checksums
        log("  MD5 = " + md5Digest)
        log("  SHA256 = " + sha256Digest)
        log("  Adler32 = " + adler32Digest)
        log("  Size = %d" % size)

        # Checksum the archive copy
        log("  Verifying transfer")
        md5Hasher = hashlib.md5()
        sha256Hasher = hashlib.sha256()
        adler32sum2 = 1
        with open(ark_path, 'rb') as f:
            buf = f.read(blocksize)
            while len(buf) > 0:
                md5Hasher.update(buf)
                sha256Hasher.update(buf)
                adler32sum2 = adler32(buf, adler32sum2)
                buf = f.read(blocksize)

        if (md5Digest != md5Hasher.hexdigest() or
            sha256Digest != sha256Hasher.hexdigest() or
            adler32sum != adler32sum2):
            raise Exception("Archived file has different checksum")

        # Delete the original if the archiving is complete
        os.remove(full_path)

        status = "Archived"
        r = os.stat(ark_path)
        config.set(gdsc.omero.ARK_FILE_ARCHIVER, 'Archived',
                   time.ctime(r.st_mtime))
        archived = True

        # Create a symlink to the archive location allowing access from
        # a back-up restore.
        # This is only available on unix
        try:
            os.symlink(ark_path, full_path)
            log("  Created link from original path to archive")
        except:
            pass

        log("  Status = " + status)

    finally:
        # Record the stage we reached
        with open(ark_file, 'w') as f:
            config.write(f)

    if archived:
        return gdsc.omero.JOB_FINISHED
    return gdsc.omero.JOB_RUNNING

def process_job(job_file):
    """
    Process the archive job file
    @param job_file: The job file path
    """
    global options, file_status, paths

    log("Processing job " + job_file)

    # Open the job file
    job = configparser.RawConfigParser(delimiters='=')
    job.optionxform = lambda option: option
    job.read(job_file)

    # Clear previous job errors
    if (job.has_option(gdsc.omero.JOB_INFO, 'error')):
        job.remove_option(gdsc.omero.JOB_INFO, 'error')

    # Count the number of files to process
    size = 0
    for (path, status) in job.items(gdsc.omero.JOB_FILES):
        if path in file_status:
            # This has already been done
            continue
        if status == gdsc.omero.JOB_RUNNING:
            size = size + 1

    if size:
        job.set(gdsc.omero.JOB_INFO, 'status', gdsc.omero.JOB_RUNNING)

    # Process the files
    log("Processing %d file%s" % (size, '' if size == 1 else 's'))

    error_flag = False
    running = 0
    for (path, status) in job.items(gdsc.omero.JOB_FILES):

        new_status = file_status.get(path)
        if new_status:
            # To prevent double processing of files, update the status
            # if this is not the first time we see this file.
            #
            # Note: this appears to be poor management of the status as it is
            # replicated through all job files which must be kept in sync.
            # However the status can be determined in this script in the
            # process() method. This allows a job file to have its status set
            # to running for all files to allow restarting the job.
            # Also note that tagging of images for archiving has respected
            # the many-to-many image-to-file relationship and should prevent
            # an image that has been tagged as archived from being processed
            # again. This only occurs when the tag has been added again
            # for testing or when testing by manually
            # manipulating the job files.
            job.set(gdsc.omero.JOB_FILES, path, new_status)
            status = new_status

            if status == gdsc.omero.JOB_RUNNING:
                # This is still running
                running = running + 1

        elif status == gdsc.omero.JOB_RUNNING:
            # This is the first time we process this 'running' file

            try:
                # The process method returns the status or throws an exception
                status = process(path)
                if status == gdsc.omero.JOB_FINISHED:
                    # This has been archived
                    # Build a list of paths that have been archived
                    paths.append(path)
                else:
                    # This is still running
                    running = running + 1

            except Exception as e:
                status = gdsc.omero.JOB_ERROR
                # Record the error in the job file
                job.set(gdsc.omero.JOB_INFO, 'error', str(e))
                error("An error occurred: %s" % e)

            # Record the status of this file the first time it is processed
            file_status[path] = status

            # Record the status change in the job file
            if status != gdsc.omero.JOB_RUNNING:
                job.set(gdsc.omero.JOB_FILES, path, status)

        if status == gdsc.omero.JOB_ERROR:
            error_flag = True
            break

    # If finished or error then move the job file
    dir = ''
    email_address = ''
    if error_flag:
        dir = os.path.join(options.archive_job, gdsc.omero.JOB_ERROR)
        # If an error then only email the admin
    elif running == 0:
        dir = os.path.join(options.archive_job, gdsc.omero.JOB_FINISHED)
        # Only email the user when finished
        email_address = get_option(job, 'email', gdsc.omero.JOB_INFO)

    if dir:
        # This is complete
        status = os.path.basename(dir)
        job.set(gdsc.omero.JOB_INFO, 'complete', time.strftime("%c"))
        job.set(gdsc.omero.JOB_INFO, 'status', status)

    # Save changes to the job file
    with open(job_file, 'w') as f:
        job.write(f)

    if dir:
        # This is complete. E-mail the job file to the user/admin
        email_results(email_address, job_file, status)

        # Move to the processed folder
        log("Moving %s to %s" % (job_file, dir))
        shutil.move(job_file, dir)


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

    global options, file_status, paths
    file_status = {}
    paths = []
    (options, args) = parser.parse_args()

    try:
        pid_file = gdsc.omero.PIDFile(
            os.path.join(options.archive_job,
                         os.path.basename(__file__) + '.pid'))
    except Exception as e:
        die("Cannot start process: %s" % e)

    banner("Archive Files to File Store")

    try:
        check_dir(options.archive_log)
        check_dir(options.archive_root)
        check_dir(options.archive_job)
        check_dir(os.path.join(options.archive_job, gdsc.omero.JOB_RUNNING))
        check_dir(os.path.join(options.archive_job, gdsc.omero.JOB_FINISHED))
        check_dir(os.path.join(options.archive_job, gdsc.omero.JOB_ERROR))

        # Get the running job files
        job_dir = os.path.join(options.archive_job, gdsc.omero.JOB_RUNNING)
        _, _, filenames = next(os.walk(job_dir), (None, None, []))

        n = len(filenames)
        log("Processing %d job%s" % (n, gdsc.omero.pleural(n)))

        for path in filenames:
            process_job(os.path.join(job_dir, path))

        # Open the registers
        register = gdsc.omero.Register(options.to_archive, False)
        archived = gdsc.omero.Register(options.archived)

        # Add all running files to the to_archive register.
        # Note: If the script errors part way through the jobs then this
        # will be incomplete. The register is only used for reporting so
        # this is not a blocker.
        # TODO - create a script that can create the to_archive register from
        # the currently running job files
        running = []
        for (k, v) in file_status.items():
            if v == gdsc.omero.JOB_RUNNING:
                running.append(k)
        register.save(running)

        # Add archived files to the archived register
        size = len(paths)
        if size:
            log("Archived %d file%s" % (size, '' if size == 1 else 's'))
            archived.add_list(paths)

    except Exception as e:
        fatal("An error occurred: %s" % e)

    pid_file.delete()


# Standard boilerplate to call the main() function to begin
# the program.
if __name__ == '__main__':
    main()
