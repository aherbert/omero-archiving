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
This script finds all images within OMERO that are tagged for archiving,
identifies their original files and prepares them for archiving. The source
images for all the files are then tagged as pending. A job file is created in
the New folder of the Job folder workflow. New jobs must be manually Approved
or Declined.

Any jobs files in the Declined folder have the pending tag removed from their
images and the job file is moved to Finished.

Any job files in the Approved folder have the pending tag removed from their
images, the archived tag applied and the job file is moved to Running.
"""
import sys
import os
import shutil
import time
import configparser
from stat import *

import re
import platform
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import COMMASPACE, formatdate

from optparse import OptionParser, OptionGroup

from omero.gateway import BlitzGateway, MapAnnotationWrapper
from omero.rtypes import *  # noqa
from omero.sys import Parameters, Filter

import gdsc.omero

###############################################################################

def init_options():
    """Initialise the program options"""

    parser = OptionParser(usage="usage: %prog [options] list",
                          description="Program to process tagged images for "
                                      "file archiving",
                          add_help_option=True, version="%prog 1.0")

    parser.add_option("--no_delete", dest="no_delete",
                     action="store_true", default=False,
                     help="Do not delete the %s tag" %
                     gdsc.omero.TAG_TO_ARCHIVE)
    parser.add_option("--ignore", dest="ignore",
                     action="store_true", default=False,
                     help="Ignore missing files (continue updating tags)")

    group = OptionGroup(parser, "Archive")
    group.add_option("--archive_log", dest="archive_log",
                     default=gdsc.omero.ARCHIVE_LOG,
                     help="Directory for file archive logs [%default]")
    group.add_option("--archive_job", dest="archive_job",
                     default=gdsc.omero.ARCHIVE_JOB,
                     help="Directory for archive jobs [%default]")
    group.add_option("--to_archive", dest="to_archive",
                     default=gdsc.omero.TO_ARCHIVE_REGISTER,
                     help="To-Archive register [%default]")
    parser.add_option_group(group)

    group = OptionGroup(parser, "OMERO")
    group.add_option("-u", "--username", dest="username",
                     default=gdsc.omero.USERNAME,
                     help="OMERO username [%default]")
    group.add_option("-p", "--password", dest="password",
                     default=gdsc.omero.PASSWORD, help="OMERO password")
    group.add_option("--host", dest="host", default=gdsc.omero.HOST,
                     help="OMERO host [%default]")
    group.add_option("--port", dest="port", default=gdsc.omero.PORT,
                     help="OMERO port [%default]")
    group.add_option("--repository", dest="repository",
                     default=gdsc.omero.REPOSITORY,
                     help="OMERO managed repository [%default]")
    group.add_option("--files", dest="files",
                     default=gdsc.omero.LEGACY_FILES,
                     help="OMERO legacy files directory [%default]")
    group.add_option("--pixels", dest="pixels",
                     default=gdsc.omero.LEGACY_PIXELS,
                     help="OMERO legacy pixels directory [%default]")

    parser.add_option_group(group)

    return parser

###############################################################################

def log(msg):
    """
    Print a message
    @param msg: The message
    """
    print(msg)

def warn(msg):
    """
    Print a warning message
    @param msg: The message
    """
    print("WARNING:", msg)

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

def process_reviewed(adminConn, input, output, job_status, archived, register):
    """
    Any jobs files in the input folder have the pending tag removed from
    their images and the job file is moved to the output folder. Optionally
    tag the images as archived.
    @param adminConn: The admin connection to OMERO
    @param input: The input folder
    @param output: The output folder
    @param job_status: The output job status
    @param archived: Set to true to tag as archived
    @param register: The archive register used to store file paths
    """
    global options
    job_dir = os.path.join(options.archive_job, input)
    _, _, filenames = next(os.walk(job_dir), (None, None, []))
    count = len(filenames)
    log("%d %s job%s" % (count, input,
                         gdsc.omero.pleural(count)))
    if not count:
        return

    for filename in filenames:
        job_file = os.path.join(job_dir, filename)
        log("Processing job " + job_file)

        # Read the job file
        job = configparser.RawConfigParser(delimiters='=')
        job.optionxform = lambda option: option
        job.read(job_file)

        # Read the username
        omename = job.get(gdsc.omero.JOB_INFO, 'omename')

        # suConn to the user
        conn = adminConn.suConn(omename, ttl=gdsc.omero.TIMEOUT)
        if not conn:
            raise Exception("Failed to connect to OMERO as user ID '%s'" %
                            omename)

        gid = int(job.get(gdsc.omero.JOB_INFO, 'group id'))
        linked_id = job.get(gdsc.omero.JOB_INFO, 'owner id')
        linked_omename = job.get(gdsc.omero.JOB_INFO, 'owner omename')

        qs = conn.getQueryService()
        # Use the actual SERVICE_OPTS so that when we set the group it is
        # correct when saving a new tag
        service_opts = conn.SERVICE_OPTS  #.copy()
        service_opts.setOmeroGroup(gid)

        # All images marked as True were newly tagged in this job.
        # Otherwise they were part of a set where some are already tagged.
        image_ids = []
        for (image, status) in job.items(gdsc.omero.JOB_IMAGES):
            if status != 'True':
                continue
            match = re.search("\(([0-9]+)\)$", image)
            if not match:
                raise Exception("Cannot identify image ID in text: " + image)
            image_ids.append(int(match.group(1)))

        # There may be no images that require tag updates
        if image_ids:
            # Remove the pending tag
            log("Deleting tag: %s" % gdsc.omero.TAG_PENDING)

            # Get the link Ids and then delete objects
            hql = "select link.id " \
                    "from ImageAnnotationLink link " \
                    "where link.child.class is MapAnnotation " \
                    "and link.child.name = :value " \
                    "and link.parent.id in (:values)"

            params = Parameters()
            params.map = {}
            params.map["values"] = rlist([rlong(x) for x in image_ids])
            params.map["value"] = rstring(gdsc.omero.TAG_PENDING)

            link_ids = [x[0].val for x in
                          qs.projection(hql, params, service_opts)]

            if link_ids:
                handle = conn.deleteObjects('ImageAnnotationLink', link_ids)
                cb = omero.callbacks.CmdCallbackI(conn.c, handle)
                while not cb.block(500):
                    log(".")
                r = cb.getResponse()
                cb.close(True)
                if isinstance(r, omero.cmd.ERR):
                    raise Exception("Failed to remove links: %s" % cb.getResponse())

            # Add the archived tag
            if archived:
                log("Applying tag: %s" % gdsc.omero.TAG_ARCHIVED)

                # Find the archived tag
                tag_id = 0
                tags = list(conn.getObjects(
                    "MapAnnotation",
                    attributes={'name':gdsc.omero.TAG_ARCHIVED,"ns":"archiving"})
                )

                # Discarding any that can not be linked
                # This is when the group is read-only and the querying user is not
                # the owner of the tag
                for tag in tags:
                    # Check the annotation class since the HQL was returning
                    # BooleanAnnotationWrapper previously created with the same name
                    if (tag.canLink() and
                        type(tag) == omero.gateway.MapAnnotationWrapper and
                        getUserId(tag.getDescription()) == linked_id):
                        tag_id = tag.id
                        break

                if not tag_id:
                    # Create if missing
                    tag = omero.gateway.MapAnnotationWrapper(conn)
                    tag.setName(gdsc.omero.TAG_ARCHIVED)
                    tag.setNs("archiving")
                    tag.setDescription("Owner : " + str(linked_id) + " : " +
                                      linked_omename)
                    tag.setValue([[gdsc.omero.TAG_ARCHIVED,"True"]])
                    tag.save()
                    tag_id = tag.getId()
                    if tag_id == 0:
                        raise Exception("Failed to create tag: " +
                                        gdsc.omero.TAG_ARCHIVED)

                links = []
                for image_id in image_ids:
                    link = omero.model.ImageAnnotationLinkI()
                    link.parent = omero.model.ImageI(image_id, False)
                    link.child = omero.model.MapAnnotationI(tag_id, False)
                    links.append(link)

                if links:
                    try:
                        # Will fail if any of the links already exist
                        savedLinks = conn.getUpdateService().saveAndReturnArray(
                            links, service_opts)
                    except omero.ValidationException as x:
                        # Allow this to stop the program
                        raise x
            else:
                # These are not archived so remove the notes tag from all the images
                log("Removing tag: %s" % gdsc.omero.TAG_ARCHIVE_NOTE)

                # Get the link Ids and then delete objects
                hql = "select link.id " \
                        "from ImageAnnotationLink link " \
                        "where link.child.class is MapAnnotation " \
                        "and link.child.name = :value " \
                        "and link.parent.id in (:values)"
                p = Parameters()
                p.map = {}
                p.map['value'] = rstring(gdsc.omero.TAG_ARCHIVE_NOTE)
                p.map["values"] = rlist([rlong(x) for x in image_ids])

                link_ids = [x[0].val for x in
                            qs.projection(hql, p, service_opts)]

                if link_ids:
                    handle = conn.deleteObjects('ImageAnnotationLink', link_ids)
                    cb = omero.callbacks.CmdCallbackI(conn.c, handle)
                    while not cb.block(500):
                        log(".")
                    r = cb.getResponse()
                    cb.close(True)
                    if isinstance(r, omero.cmd.ERR):
                        warn("Failed to remove links: %s" % cb.getResponse())

        conn._closeSession()

        # Mark files with output status
        paths = []
        for (path, status) in job.items(gdsc.omero.JOB_FILES):
            job.set(gdsc.omero.JOB_FILES, path, job_status)

            if archived:
                continue

            # This is a Declined job and the path should not be archived.
            # We can delete the ARK file. As a double-check the Ark file
            # should only contain initial information such as omero details
            # and file sizes.
            # If it contains more than one section then it has been processed
            # by an archiving script.
            ark_file = gdsc.omero.get_ark_path(options.archive_log, path, False)
            if os.path.exists(ark_file):
                config = configparser.RawConfigParser(delimiters='=')
                config.read(ark_file)
                if len(config.sections()) > 1:
                    warn("File for declined job appears to have been archived: %s" % ark_file)
                    continue
                os.remove(ark_file)

            # Add to paths not archived
            paths.append(path)

        # Update the archive register
        if paths:
            register.remove_list(paths)

        # Update the job file
        job.set(gdsc.omero.JOB_INFO, 'status', job_status)
        with open(job_file, 'w') as f:
            job.write(f)

        # e-mail job file to user
        email_results(get_option(job, 'email', gdsc.omero.JOB_INFO),
                          job_file, input)

        # Move to output directory
        dir = os.path.join(options.archive_job, output)
        log("Moving %s to %s" % (job_file, dir))
        shutil.move(job_file, dir)

def process_approved(conn):
    """
    Any job files in the Approved folder have the pending tag removed from
    their images, the archived tag applied and the job file is moved to Running.
    @param conn: The admin connection to OMERO
    """
    process_reviewed(conn,
                     gdsc.omero.JOB_APPROVED,
                     gdsc.omero.JOB_RUNNING,
                     gdsc.omero.JOB_RUNNING,
                     True, None)

def process_declined(conn, register):
    """
    Any jobs files in the Declined folder have the pending tag removed from
    their images and the job file is moved to Finished.
    @param conn: The admin connection to OMERO
    @param register: The archive register used to store file paths
    """
    process_reviewed(conn,
                     gdsc.omero.JOB_DECLINED,
                     gdsc.omero.JOB_FINISHED,
                     gdsc.omero.JOB_DECLINED,
                     False, register)

def email_admin(job_dir, filenames):
    """
    E-mail admin to indicate that new jobs require approval.
    @param job_dir: the number of jobs
    @param filenames: the filenames
    """
    count = len(filenames)

    # Get the size of files to archive
    filesizes = []
    for filename in filenames:
        job_file = os.path.join(job_dir, filename)
        job = configparser.RawConfigParser(delimiters='=')
        job.read(job_file)
        omename = job.get(gdsc.omero.JOB_INFO, 'owner omename')
        size = job.get(gdsc.omero.JOB_INFO, 'total size')
        filesizes.append("%s : %s : %s" % (filename, omename, size))

    send_to = gdsc.omero.ADMIN_EMAILS

    msg = MIMEMultipart()
    msg['From'] = gdsc.omero.ADMIN_EMAIL
    msg['To'] = COMMASPACE.join(send_to)
    msg['Date'] = formatdate(localtime=True)
    msg['Subject'] = '[OMERO Job] Archive Job : ' + gdsc.omero.JOB_NEW
    msg.attach(MIMEText("""OMERO Archive Job : %s

Awaiting review : %s job%s

Please log on to the OMERO server and check the directory:
%s

%s

Jobs should be moved to either of the following directories:
%s
%s

---
OMERO @ %s """ % (gdsc.omero.JOB_NEW, count, gdsc.omero.pleural(count),
                  job_dir, "\n".join(filesizes),
                  os.path.join(options.archive_job, gdsc.omero.JOB_APPROVED),
                  os.path.join(options.archive_job, gdsc.omero.JOB_DECLINED),
                  platform.node())))

    smtpObj = smtplib.SMTP('localhost')
    smtpObj.sendmail(gdsc.omero.ADMIN_EMAIL, send_to, msg.as_string())
    smtpObj.quit()

def process_new():
    """
    Count the number of new jobs files requiring approval and e-mail admin
    """
    global options
    job_dir = os.path.join(options.archive_job, gdsc.omero.JOB_NEW)
    _, _, filenames = next(os.walk(job_dir), (None, None, []))
    count = len(filenames)
    log("%d %s job%s" % (count, gdsc.omero.JOB_NEW,
                         gdsc.omero.pleural(count)))
    if count:
        email_admin(job_dir, filenames)

def process(register, conn, omename, groups, linked_id, linked_omename,
            linked_email):
    """
    Find all the files associated with the tagged images, add to the archive
    register and then mark the images as archived
    @param register: The archive register used to store file paths
    @param conn: The connection to OMERO as the user
    @param omename: The user omename
    @param groups: The collection of groups and images to process
    @param linked_id: The id of the user who linked the images
    @param linked_omename: The omename of the user who linked the images
    @param linked_email: The email of the user who linked the images
    """
    global options, job_id, job_name

    linked_by = "%d : %s" % (linked_id, linked_omename)
    log("-=-=-=-")
    log("Processing user %s" % omename)
    if linked_id != conn.getUserId():
        log("Linked by user %s" % linked_by)

    qs = conn.getQueryService()
    # Use the actual SERVICE_OPTS so that when we set the group it is
    # correct when saving a new tag
    service_opts = conn.SERVICE_OPTS  #.copy()

    # For each group
    for gid in groups:
        service_opts.setOmeroGroup(gid)
        id_set = groups[gid]
        log("-=-=-=-")
        log("Processing user %s, group %s" % (omename, gid))
        log("Image Ids: %s" % list(id_set))

        # We need:
        # List of files associated with the images (for archiving)
        # List of the images associated with the files (for tagging)
        # At least one image Id per file (for the archive record file)
        image_paths = {}
        image_ids = {}

        # Version 5.0 : imported fileset
        # Version 4.0 : pixels file and legacy original files

        # Get all the filesets with these images
        hql = "select i.fileset.id from Image i " \
                "where i.fileset is not null " \
                "and i.id in (:values) " \
                "group by i.fileset.id"
        params = Parameters()
        params.map = {}
        params.map["values"] = rlist([rlong(i) for i in id_set])

        fileset_ids = [x[0].val for x in
                       qs.projection(hql, params, service_opts)]

        if fileset_ids:
            log("Fileset Ids: %s" % fileset_ids)

            params = Parameters()
            params.map = {}
            params.map["values"] = rlist([rlong(i) for i in fileset_ids])

            # List all the images associated with the filesets
            hql = "select i.id, i.fileset.id, i.details.owner.id " \
                "from Image i " \
                "where i.fileset.id in (:values) order by i.id"
            # Store an image Id for each fileset
            fileset_to_image_id = {}
            for x in qs.projection(hql, params, service_opts):
                image_id, fileset_id, owner_id = x[0].val, x[1].val, x[2].val
                log("Fileset %d Image : %s" % (fileset_id, image_id))
                image_ids[image_id] = owner_id
                if not fileset_id in fileset_to_image_id:
                    fileset_to_image_id[fileset_id] = image_id

            # List the files associated with the filesets
            hql = "select f.originalFile.path, f.originalFile.name, " \
                "f.fileset.id from FilesetEntry f " \
                "where f.fileset.id in (:values)"
            for x in qs.projection(hql, params, service_opts):
                path, name, fileset_id = x[0].val, x[1].val, x[2].val
                path = os.path.join(options.repository, path, name)
                log("Fileset %d Path : %s" % (fileset_id, path))
                image_paths[path] = fileset_to_image_id[fileset_id]

        new_ids = image_ids.keys()

        # ---------------------------------------------------------------------
        # Note: Pyramids
        # The only way to check if an image has a pyramid file through
        # the API is via the RawPixelsStore. This has a method
        # requiresPixelsPyramid()
        # http://downloads.openmicroscopy.org/omero/5.1.4/api/slice2html/omero/api/PyramidService.html#requiresPixelsPyramid
        # This returns 'Whether or not this raw pixels store requires a backing
        # pixels pyramid to provide sub-resolutions of the data.'
        # However Josh stated that the way OMERO checks is to try and find the
        # pyramid file on disk. So we can just look for Pyramid files in the
        # filesystem.
        # ---------------------------------------------------------------------

        if new_ids:
            # Check for Pixel files for the 5.0 images, e.g. in case of pyramids

            hql = "select p.id, p.image.id, p.details.owner.id " \
                    "from Pixels p " \
                    "where p.image.id in (:values) order by p.id"
            params = Parameters()
            params.map = {}
            params.map["values"] = rlist([rlong(id) for id in new_ids])

            for x in qs.projection(hql, params, service_opts):
                pixels_id, image_id, owner_id = x[0].val, x[1].val, x[2].val
                path = gdsc.omero.get_legacy_path(options.pixels, pixels_id)
                # Check for _pyramid file
                if os.path.exists(path + '_pyramid'):
                    path = path + '_pyramid'
                # Check for pixel file (Q. Is this possible for a type 5.0 file?)
                elif not os.path.exists(path):
                    path = ''
                if path:
                    log("Fileset Image %s Pixel File : %s" % (image_id, path))
                    image_paths[path] = image_id
                    # Add to the output set
                    image_ids[image_id] = owner_id

        # Any images not yet processed are Version 4.0 format, i.e. Pixels and
        # archived original files
        old_ids = id_set.difference(new_ids)

        if old_ids:
            log("Non-Fileset Image Ids: %s" % list(old_ids))

            # List the original files associated with the images
            hql = "select DISTINCT o.id, o.name, i.id " \
                    "from OriginalFile o join o.pixelsFileMaps m " \
                    "join m.child p join p.image i " \
                    "where i.id in (:values) order by o.id"
            params = Parameters()
            params.map = {}
            params.map["values"] = rlist([rlong(id) for id in old_ids])

            file_ids = []
            for x in qs.projection(hql, params, service_opts):
                file_id, name, image_id = x[0].val, x[1].val, x[2].val
                path = gdsc.omero.get_legacy_path(options.files, file_id)
                log("Original File %s : %s" % (name, path))
                image_paths[path] = image_id
                file_ids.append(file_id)

            if file_ids:
                # List the (extra) images associated with the original files
                hql = "select DISTINCT i.id " \
                        "from OriginalFile o join o.pixelsFileMaps m " \
                        "join m.child p join p.image i " \
                        "where o.id in (:values) order by i.id"
                params = Parameters()
                params.map = {}
                params.map["values"] = rlist([rlong(id) for id in file_ids])

                for x in qs.projection(hql, params, service_opts):
                    image_id = x[0].val
                    if image_id not in old_ids:
                        old_ids.add(image_id)

            # List all the pixel files associated with the old images
            hql = "select p.id, p.image.id, p.details.owner.id " \
                    "from Pixels p " \
                    "where p.image.id in (:values) order by p.id"
            params = Parameters()
            params.map = {}
            params.map["values"] = rlist([rlong(id) for id in old_ids])

            for x in qs.projection(hql, params, service_opts):
                pixels_id, image_id, owner_id = x[0].val, x[1].val, x[2].val
                path = gdsc.omero.get_legacy_path(options.pixels, pixels_id)
                # Check for pyramid files
                if os.path.exists(path + '_pyramid'):
                    path = path + '_pyramid'
                log("Image %s Pixel File : %s" % (image_id, path))
                image_paths[path] = image_id
                # Add all the Version 4.0 images to the output set
                image_ids[image_id] = owner_id

        log("-=-=-=-")

        # Find the archived tag
        tag_id = 0
        tags = list(conn.getObjects(
                "MapAnnotation",
                attributes={'name':gdsc.omero.TAG_PENDING,"ns":"archiving"})
        )

        # Discarding any that can not be linked
        # This is when the group is read-only and the querying user is not
        # the owner of the tag
        for tag in tags:
            # Check the annotation class since the HQL was returning
            # BooleanAnnotationWrapper previously created with the same name
            if (tag.canLink() and
                type(tag) == omero.gateway.MapAnnotationWrapper and
                getUserId(tag.getDescription()) == linked_id):
                tag_id = tag.id
                break

        if not tag_id:
            # Create if missing
            tag = omero.gateway.MapAnnotationWrapper(conn)
            tag.setName(gdsc.omero.TAG_PENDING)
            tag.setNs("archiving")
            tag.setDescription("Owner : " + str(linked_id) + " : " +
                               linked_omename)
            tag.setValue([[gdsc.omero.TAG_PENDING,"True"]])
            tag.save()
            tag_id = tag.getId()
            if tag_id == 0:
                raise Exception("Failed to create tag: " +
                                gdsc.omero.TAG_PENDING)

        # Create an archiving job file ...
        job_file = os.path.join(options.archive_job, gdsc.omero.JOB_NEW,
                                job_name + str(job_id))
        job_id = job_id + 1
        log("Creating archive job: %s" % job_file)
        job = configparser.RawConfigParser(delimiters='=')
        job.optionxform = lambda option: option
        job.add_section(gdsc.omero.JOB_INFO)
        job.add_section(gdsc.omero.JOB_IMAGES)
        job.add_section(gdsc.omero.JOB_FILES)
        job.set(gdsc.omero.JOB_INFO, 'user id', str(conn.getUserId()))
        job.set(gdsc.omero.JOB_INFO, 'omename', omename)
        job.set(gdsc.omero.JOB_INFO, 'group id', str(gid))
        job.set(gdsc.omero.JOB_INFO, 'owner id', str(linked_id))
        job.set(gdsc.omero.JOB_INFO, 'owner omename', linked_omename)
        job.set(gdsc.omero.JOB_INFO, 'email', linked_email)
        job.set(gdsc.omero.JOB_INFO, 'created', time.strftime("%c"))
        job.set(gdsc.omero.JOB_INFO, 'status', gdsc.omero.JOB_NEW)

        # Get the archive note(s)
        # select a.mapValue does not work so we select the entire object
        hql = "select a " \
                "from MapAnnotation a " \
                "where a.id in (" \
                "select distinct link.child.id " \
                "from ImageAnnotationLink link " \
                "where link.child.class is MapAnnotation " \
                "and link.child.name = :value " \
                "and link.parent.id in (:values))"

        params = Parameters()
        params.map = {}
        params.map["value"] = rstring(gdsc.omero.TAG_ARCHIVE_NOTE)
        params.map["values"] = rlist([rlong(x) for x in image_ids])

        # These are the keys to ignore
        ignore_keys = [ 'Owner', 'Owner id' ]
        # This is the number of times a key has been seen
        key_count = {}
        # Process all the map annotations
        for result in qs.projection(hql, params, service_opts):
            # How is the list returned?
            #print result[0].val
            # List of ::omero::model::NamedValue
            for x in result[0].val.mapValue:
                key = x.name
                if key in ignore_keys:
                    continue
                c = key_count.get(key, 0)
                if c:
                    key = key + str(c)
                job.set(gdsc.omero.JOB_INFO, key.lower(), x.value)
                key_count[x.name] = c + 1

        log("Applying tag: %s" % gdsc.omero.TAG_PENDING)

        # Select the images which are already tagged as archived (or pending)
        hql = "select distinct link.parent.id " \
                "from ImageAnnotationLink link " \
                "where link.child.class is MapAnnotation " \
                "and link.child.name in (:tags) " \
                "and link.parent.id in (:values)"

        params = Parameters()
        params.map = {}
        params.map["tags"] = rlist([rstring(gdsc.omero.TAG_ARCHIVED),
                                    rstring(gdsc.omero.TAG_PENDING)])
        params.map["values"] = rlist([rlong(x) for x in image_ids])

        ignore = set()
        for result in qs.projection(hql, params, service_opts):
            ignore.add(result[0].val)

        # Get the image name,project,dataset for the job file
        iname = {}
        project = {}
        dataset = {}

        # Get the name
        hql = "select i.id, i.name " \
                "from Image i " \
                "where i.id in (:values)"

        params = Parameters()
        params.map = {}
        params.map["values"] = rlist([rlong(x) for x in image_ids])

        for result in qs.projection(hql, params, service_opts):
            iname[result[0].val] = result[1].val

        # Get all the dataset names containing the images
        hql = "select distinct l.parent.name " \
                "from DatasetImageLink l " \
                "where l.child.id in (:values)"

        dnames = []
        for result in qs.projection(hql, params, service_opts):
            dnames.append(result[0].val)

        # Get the projects for each dataset
        if dnames:
            hql = "select l.child.name, l.parent.name " \
                    "from ProjectDatasetLink l " \
                    "where l.child.name in (:values)"

            params = Parameters()
            params.map = {}
            params.map["values"] = rlist([rstring(x) for x in dnames])

            # Store the first project for each dataset
            for result in qs.projection(hql, params, service_opts):
                if result[0].val not in project:
                    project[result[0].val] = result[1].val

            if project:
                # Get the images for the datasets that have a project
                hql = "select l.child.id, l.parent.name " \
                        "from DatasetImageLink l " \
                        "where l.child.id in (:values) " \
                        "and l.parent.name in (:names)"

                params = Parameters()
                params.map = {}
                params.map["values"] = rlist([rlong(x) for x in image_ids])
                params.map["names"] = rlist([rstring(x) for x in project])

                for result in qs.projection(hql, params, service_opts):
                    if result[0].val not in dataset:
                        dataset[result[0].val] = result[1].val

            # Get the datasets for the remaining images
            # (these are datasets with no parent project)
            remaining = set(image_ids).difference(dataset.keys())
            if remaining:
                hql = "select l.child.id, l.parent.name " \
                        "from DatasetImageLink l " \
                        "where l.child.id in (:values)"

                params = Parameters()
                params.map = {}
                params.map["values"] = rlist([rlong(x) for x in remaining])

                for result in qs.projection(hql, params, service_opts):
                    if result[0].val not in dataset:
                        dataset[result[0].val] = result[1].val

        # Tag all the images as pending (if not already)
        links = []
        for image_id in image_ids:
            skip = image_id in ignore

            # Build the key:
            # [Project]/[Dataset] ID : Name
            ds = dataset.get(image_id, "")
            pr = project.get(ds, "")
            key = "/%s/%s/%s (%d)" % (pr, ds, iname.get(image_id, ""),
                                      image_id)

            # Record if the image was tagged for archiving this time
            # (i.e. not skipped)
            job.set(gdsc.omero.JOB_IMAGES, key,
                    str(not skip))
            if skip:
                continue
            log("Tagging image " + key)
            link = omero.model.ImageAnnotationLinkI()
            link.parent = omero.model.ImageI(image_id, False)
            link.child = omero.model.MapAnnotationI(tag_id, False)
            links.append(link)

        if links:
            try:
                # Will fail if any of the links already exist
                savedLinks = conn.getUpdateService().saveAndReturnArray(
                    links, service_opts)
            except omero.ValidationException as x:
                # Allow this to stop the program
                raise x

        # Record the files
        total_size = 0
        file_paths = []
        for path in image_paths:
            # Ignore symlinks (these may be files obtained from in-place import
            # or already archived and linked to a new location)
            if os.path.islink(path):
                warn("Skipping symlink: %s" % path)
                job.set(gdsc.omero.JOB_FILES, path, gdsc.omero.JOB_IGNORE)
                continue

            job.set(gdsc.omero.JOB_FILES, path, gdsc.omero.JOB_NEW)

            r = 0
            if os.path.isfile(path):
                r = os.stat(path)
            else:
                msg = "File does not exist: %s" % path
                if options.ignore:
                    # Allow the script to continue updating tags
                    error(msg)
                else:
                    raise Exception(msg)

            file_paths.append(path)

            # Initialise the .ark files with a connected image ID
            ark_file = gdsc.omero.get_ark_path(options.archive_log, path, True)
            config = configparser.RawConfigParser(delimiters='=')
            config.read(ark_file)
            if not config.has_section(gdsc.omero.ARK_SOURCE):
                config.add_section(gdsc.omero.ARK_SOURCE)
            image_id = image_paths[path]
            config.set(gdsc.omero.ARK_SOURCE, 'image', str(image_id))
            config.set(gdsc.omero.ARK_SOURCE, 'owner', str(image_ids[image_id]))
            config.set(gdsc.omero.ARK_SOURCE, 'linked by', linked_by)
            config.set(gdsc.omero.ARK_SOURCE, 'path', path)

            if r:
                total_size = total_size + r.st_size
                config.set(gdsc.omero.ARK_SOURCE, 'bytes', str(r.st_size))
                config.set(gdsc.omero.ARK_SOURCE, 'size',
                           gdsc.omero.convert(r.st_size))
                config.set(gdsc.omero.ARK_SOURCE, 'last modified',
                        time.ctime(r.st_mtime))
            with open(ark_file, 'w') as f:
                config.write(f)

        # Add to the register
        register.add_list(file_paths)

        job.set(gdsc.omero.JOB_INFO, 'total bytes', str(total_size))
        job.set(gdsc.omero.JOB_INFO, 'total size', gdsc.omero.convert(total_size))

        log("Saving archive job: %s" % job_file)
        with open(job_file, 'w') as f:
            job.write(f)

        # Optionally disable removal of to-archive tag
        # (allows repeat execution of the script on the same images)
        if options.no_delete:
            log("Skipping deleting tag: %s" % gdsc.omero.TAG_TO_ARCHIVE)
            continue

        # Remove the to-archive tag from all the images
        # Get the link Ids and then delete objects
        hql = "select link.id " \
                "from ImageAnnotationLink link " \
                "where link.child.class is MapAnnotation " \
                "and link.child.name = :value " \
                "and link.parent.id in (:values)"

        params = Parameters()
        params.map = {}
        params.map["values"] = rlist([rlong(x) for x in image_ids])
        params.map["value"] = rstring(gdsc.omero.TAG_TO_ARCHIVE)

        link_ids = [x[0].val for x in
                       qs.projection(hql, params, service_opts)]

        if link_ids:
            handle = conn.deleteObjects('ImageAnnotationLink', link_ids)
            cb = omero.callbacks.CmdCallbackI(conn.c, handle)
            log("Deleting tag: %s" % gdsc.omero.TAG_TO_ARCHIVE)
            while not cb.block(500):
                log(".")
            r = cb.getResponse()
            cb.close(True)
            if isinstance(r, omero.cmd.ERR):
                raise Exception("Failed to remove links: %s" % cb.getResponse())

def getUserId(description):
    """
    Get the user Id from the tag description

    @param description: The tag description
    """
    tokens = description.split(':')
    if tokens and len(tokens) > 2:
        try:
            return int(tokens[1])
        except:
            pass
    return 0

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
            warn("Path is not a directory: %s" % path)

# Gather our code in a main() function
def main():
    parser = init_options()
    global options, job_id, job_name

    (options, args) = parser.parse_args()

    try:
        pid_file = gdsc.omero.PIDFile(
            os.path.join(options.archive_job,
                         os.path.basename(__file__) + '.pid'))
    except Exception as e:
        die("Cannot start process: %s" % e)

    job_id = 1
    job_name = time.strftime("%Y%m%d_%H%M%S.")

    conn = None
    try:
        # Check the OMERO directories exist.
        # They may not exist if nothing has been imported yet
        check_dir(options.repository, 0)
        check_dir(options.files, 0)
        # This is for OMERO 4 legacy images stored as pixels
        check_dir(options.pixels, 0)
        check_dir(options.archive_log)
        check_dir(options.archive_job)
        check_dir(os.path.join(options.archive_job, gdsc.omero.JOB_NEW))
        check_dir(os.path.join(options.archive_job, gdsc.omero.JOB_APPROVED))
        check_dir(os.path.join(options.archive_job, gdsc.omero.JOB_DECLINED))

        # Open the archive register
        register = gdsc.omero.Register(options.to_archive)

        # Connect to OMERO
        log("Creating OMERO gateway")
        conn = BlitzGateway(options.username, options.password,
                            host=options.host, port=options.port)

        log( "Connecting to OMERO ...")
        if not conn.connect():
            raise Exception("Failed to connect to OMERO: %s" %
                            conn.getLastError())

        if not conn.isAdmin():
            raise Exception("Require ADMIN privaledges")

        # Get all images that have the to-archive tag
        hql = "select link.details.owner.omeName, " \
                "link.details.owner.id, " \
                "link.details.group.id, link.parent.id, " \
                "link.child.description " \
                "from ImageAnnotationLink link " \
                "where link.child.class is MapAnnotation " \
                "and link.child.name = :value"
        params = Parameters()
        params.map = {}
        params.map["value"] = rstring(gdsc.omero.TAG_TO_ARCHIVE)

        qs = conn.getQueryService()
        service_opts = conn.SERVICE_OPTS.copy()
        # Generic group for query across all of OMERO
        service_opts.setOmeroGroup(-1)

        # Build a collection of the tagged images
        # Group by linked_id, omename and group
        linked = {}
        count = 0
        for x in qs.projection(hql, params, service_opts):
            omename, oid, gid, id, description = (x[0].val, x[1].val, x[2].val,
                                                  x[3].val, x[4].val)
            #print omename, oid, gid, id, description
            linked_id = getUserId(description)
            if not linked_id:
                linked_id = oid
            count = count + 1

            if linked_id in linked:
                tagged = linked[linked_id]
            else:
                tagged = {}
                linked[linked_id] = tagged

            if omename in tagged:
                groups = tagged[omename]
            else:
                groups = {}
                tagged[omename] = groups

            if gid in groups:
                images = groups[gid]
            else:
                images = set()
                groups[gid] = images

            images.add(id)

        log("%d image%s tagged by %d user%s" % (
            count, gdsc.omero.pleural(count),
            len(linked), gdsc.omero.pleural(len(linked))))

        # Get an e-mail address for the user who linked the images
        dic_omename = {}
        dic_email = {}
        if linked:
            hql = "select id, email, omeName from Experimenter e " \
                    "where e.id in (:values)"
            params = Parameters()
            params.map = {}
            params.map["values"] = rlist([rlong(i) for i in linked])

            for x in qs.projection(hql, params, service_opts):
                dic_email[x[0].val] = x[1].val;
                dic_omename[x[0].val] = x[2].val;

        # For each user
        for linked_id in linked:
            tagged = linked[linked_id];
            for omename in tagged:
                # suConn to the user
                conn2 = conn.suConn(omename, ttl=gdsc.omero.TIMEOUT)
                if not conn2:
                    raise Exception("Failed to connect to OMERO as user ID '%s'"
                                    % omename)
                process(register, conn2, omename, tagged[omename], linked_id,
                        dic_omename[linked_id], dic_email[linked_id])
                conn2._closeSession()

        # Process the pending jobs
        process_new()
        process_declined(conn, register)
        process_approved(conn)

    except Exception as e:
        fatal("An error occurred: %s" % e)
    finally:
        if conn:
            conn._closeSession()

    pid_file.delete()

# Standard boilerplate to call the main() function to begin
# the program.
if __name__ == '__main__':
    main()
