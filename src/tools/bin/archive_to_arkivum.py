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
is computed, the file copied to Arkivum, and a checksum made to confirm
the copy. The original is removed when the file has been confirmed as ingested
by Arkivum and a symbolic link is made from the original location to the
archived file.
"""
import sys
import os
import shutil
import time
import configparser
import hashlib
import requests
import urllib
# Get rid of the Unverified HTTPS request warning
try:
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except:
    pass
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
                          description="Program to archive files to Arkivum",
                          add_help_option=True, version="%prog 1.0")

    group = OptionGroup(parser, "Archive")
    group.add_option("--archive_log", dest="archive_log",
                     default=gdsc.omero.ARCHIVE_LOG,
                     help="Directory for archive logs [%default]")
    group.add_option("--archive_job", dest="archive_job",
                     default=gdsc.omero.ARCHIVE_JOB,
                     help="Directory for archive jobs [%default]")
    group.add_option("--arkivum_root", dest="arkivum_root",
                     default=gdsc.omero.ARKIVUM_ROOT,
                     help="Arkivum root (for the mounted appliance) [%default]")
    group.add_option("--arkivum_path", dest="arkivum_path",
                     default=gdsc.omero.ARKIVUM_PATH,
                     help="Arkivum path (directory to copy files) [%default]")
    group.add_option("--to_archive", dest="to_archive",
                     default=gdsc.omero.TO_ARCHIVE_REGISTER,
                     help="To-Archive register [%default]")
    group.add_option("--archived", dest="archived",
                     default=gdsc.omero.ARCHIVED_REGISTER,
                     help="Archived register [%default]")
    parser.add_option_group(group)

    group = OptionGroup(parser, "Arkivum")
    # Decide if this should be:
    # amber (copied to data centres)
    # green (tape sent to escrow)
    group.add_option("--state", dest="state",
                     default='green',
                     help="Replication state for deletion [%default]")
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

def addState(state, size):
    """
    Increment the count of files in their given state
    @param state: The state
    @param size: The byte size of the file
    """
    global state_count, state_size
    state_count[state] = get_key_number(state_count, state) + 1
    state_size[state] = get_key_number(state_size, state) + size

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

def get_info(rel_path):
    """
    Get the file information from the Arkivum REST API
    @param rel_path: The path to the file on the Arkivum server
    """
    # Do not verify the SSL certificate
    r = requests.get('https://'+
                     gdsc.omero.ARKIVUM_SERVER+
                        '/api/2/files/fileInfo/'+urllib.quote(rel_path),
                     verify=False)

    # What to do here? Arkivum has a 10 minute delay
    # between copying a file and the ingest starting. So it may
    # not show in the API just yet.
    if r.status_code == 200:
        try:
            return r.json()
        except:
            pass
    else:
        error("REST API response code: "+str(r.status_code))
    return {}

def get_option(config, option, section = gdsc.omero.ARK_ARKIVUM_ARCHIVER):
    """
    Get the option from the Arkivum section (or return None)
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
    config = configparser.RawConfigParser()
    config.read(ark_file)
    if not config.has_section(gdsc.omero.ARK_ARKIVUM_ARCHIVER):
        config.add_section(gdsc.omero.ARK_ARKIVUM_ARCHIVER)

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

        directory = os.path.join(options.arkivum_root,
                                 options.arkivum_path, path[index:])
        if not os.path.exists(directory):
            os.makedirs(directory)

        # Checksum the file & copy to the archive
        ark_path = os.path.join(directory, filename)

        log("  Archive path = " + ark_path)

        # Store the relative path to the file from the base Arkivum directory
        rel_path = os.path.join(options.arkivum_path, path[index:], filename)

        # Use the Arkivum default checksums; MD5 and Adler32
        md5Digest = get_option(config, 'md5')
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

            # Copy to Arkivum and checksum
            log("  Copying to Arkivum")

            md5Hasher = hashlib.md5()
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
                        adler32sum = adler32(buf, adler32sum)
                        buf = f.read(blocksize)

            md5Digest = md5Hasher.hexdigest()
            adler32Digest = str(adler32sum & 0xffffffff)

            config.set(gdsc.omero.ARK_ARKIVUM_ARCHIVER, 'md5', md5Digest)
            config.set(gdsc.omero.ARK_ARKIVUM_ARCHIVER, 'adler32',
                       adler32Digest)
            config.set(gdsc.omero.ARK_ARKIVUM_ARCHIVER, 'size', str(size))
            config.set(gdsc.omero.ARK_ARKIVUM_ARCHIVER, 'path', ark_path)

            r = os.stat(ark_path)
            timestamp = r.st_mtime
            config.set(gdsc.omero.ARK_ARKIVUM_ARCHIVER, 'copied',
                    time.ctime(timestamp))
            config.set(gdsc.omero.ARK_ARKIVUM_ARCHIVER, 'timestamp',
                       str(timestamp))

            file_copied = True

        elif not (size and md5Digest and adler32Digest):

            # This occurs when the path to Arkivum already exists.
            # (Possible if the first copy failed part way through.)
            # Compute the checksum on the original file so the script will
            # error later if Arkivum has a bad copy.
            log("  Computing checksums")

            md5Hasher = hashlib.md5()
            adler32sum = 1
            size = 0
            blocksize = 65536
            with open(full_path, 'rb') as f:
                buf = f.read(blocksize)
                while len(buf) > 0:
                    size = size + len(buf)
                    md5Hasher.update(buf)
                    adler32sum = adler32(buf, adler32sum)
                    buf = f.read(blocksize)

            md5Digest = md5Hasher.hexdigest()
            adler32Digest = str(adler32sum & 0xffffffff)

            config.set(gdsc.omero.ARK_ARKIVUM_ARCHIVER, 'md5', md5Digest)
            config.set(gdsc.omero.ARK_ARKIVUM_ARCHIVER, 'adler32',
                       adler32Digest)
            config.set(gdsc.omero.ARK_ARKIVUM_ARCHIVER, 'size', str(size))
            config.set(gdsc.omero.ARK_FILE_ARCHIVER, 'path', ark_path)


        # Report the checksums
        log("  MD5 = " + md5Digest)
        log("  Adler32 = " + adler32Digest)
        log("  Size = %d" % size)

        # Checksum the archive copy
        log("  Verifying transfer ...")

        # Connect to the Arkivum server and get the file information
        info = get_info(rel_path)

        # Arkivum has a 10 minute ingest delay which means that the API
        # may not have a response directly after a file copy. In this case
        # it is fine to just return Running. Re-running this later should find
        # the file.
        if (len(info) == 0):
            msg = "No file information available from Arkivum"
            if (file_copied or
                time.time() - timestamp < 600):
                # Initial copy / less than 10 minutes
                error(msg)
                addState('unknown', size)
                return gdsc.omero.JOB_RUNNING
            else:
                # Arkivum should have responded
                raise Exception(msg)

        ingestState = get_key(info, 'ingestState')
        log("  Ingest state = " + ingestState)
        if ingestState != 'FINAL':
            # Wait until Arkivum has processed the file
            msg = "Waiting for ingest to complete"
            if (file_copied or
                time.time() - timestamp < 6000):
                # Initial copy / less than 100 minutes
                log("  " + msg)
            else:
                # Arkivum should have ingested by now so show an error
                error(msg)
            addState('initial', size)
            return gdsc.omero.JOB_RUNNING

        size2 = get_key(info, 'size')

        # Compare size
        if (size != size2):
            raise Exception("Archived file has different size: %d != %d" %
                            (size, size2))

        log("  Size OK")

        # Compare checksums
        md5Digest2 = get_key(info, 'md5')

        # Note:
        # The adler32 value is used by Arkivum but not available via the API.
        # For now we will just store it but not check it.

        if (md5Digest != md5Digest2):
            raise Exception("Archived file has different checksum")

        log("  MD5 OK")

        # Get the archive state
        state = get_key(info, 'replicationState')

        log("  Arkivum replication state = " + state)
        # TODO? - log when the file changes state, e.g. red > amber > green
        config.set(gdsc.omero.ARK_ARKIVUM_ARCHIVER, 'State', state)

        # summarise the amount of data in each replication state
        addState(state, size)

        if state == options.state:
            # Delete the original if the archiving is complete
            os.remove(full_path)

            status = "Archived"
            config.set(gdsc.omero.ARK_ARKIVUM_ARCHIVER, 'Archived',
                    time.ctime())
            archived = True

            # Create a symlink to the Arkivum location allowing access
            # (albeit at a reduced speed if the file is not on the appliance)
            # This is only available on unix
            try:
                os.symlink(ark_path, full_path)
                log("  Created link from original path to Arkivum")
            except:
                pass
        else:
            status = "Pending"

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
    job = configparser.RawConfigParser()
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

    global options, state_count, state_size, file_status, paths
    state_count = {}
    state_size = {}
    file_status = {}
    paths = []
    (options, args) = parser.parse_args()

    try:
        pid_file = gdsc.omero.PIDFile(
            os.path.join(options.archive_job,
                         os.path.basename(__file__) + '.pid'))
    except Exception as e:
        die("Cannot start process: %s" % e)

    banner("Archive Files to Arkivum")

    try:
        check_dir(options.archive_log)
        check_dir(options.arkivum_root)
        check_dir(os.path.join(options.arkivum_root, options.arkivum_path))
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

        # Summarise the amount of data in each replication state
        banner("Replication State Summary")
        for key in state_count:
            bytes = state_size[key]
            log("State %s : %d file%s : %d byte%s (%s)" % (key,
                state_count[key], gdsc.omero.pleural(state_count[key]),
                bytes, gdsc.omero.pleural(bytes), gdsc.omero.convert(bytes)))

    except Exception as e:
        fatal("An error occurred: %s" % e)

    pid_file.delete()


# Standard boilerplate to call the main() function to begin
# the program.
if __name__ == '__main__':
    main()
