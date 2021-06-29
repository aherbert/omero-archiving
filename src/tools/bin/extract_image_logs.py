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
This script extracts any image log file annotations to file.
"""
import os
import errno
import sys
import locale
import re
locale.setlocale(locale.LC_ALL, '')

from datetime import datetime
from optparse import OptionParser
from optparse import OptionGroup

from omero.gateway import BlitzGateway
from omero.rtypes import *  # noqa

import gdsc.omero

PARAM_OUT_DIRECTORY = "out_dir"
PARAM_IDS = "IDs"
PARAM_DEBUG = "debug"
PARAM_FORCE = "force"

###############################################################################

def init_options():
    """Initialise the program options"""

    parser = OptionParser(usage="usage: %prog [options] list_file",
        description="Program to extract image .log files from OMERO to "
                    "file. List file record is: ImageId,user_id",
        add_help_option=True, version="%prog 1.0")

    group = OptionGroup(parser, "Image Selection")
    group.add_option("--dir", "--%s" % PARAM_OUT_DIRECTORY, dest="out_dir",
                     default='.', help="Output directory [%default]")
    group.add_option("-f", "--%s" % PARAM_FORCE, dest="force",
                     action="store_true",
                     default=False, help="Overwrite local files [%default]")
    group.add_option("--file", dest="filename",
                     help="Read IDs from FILE", metavar="FILE")
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
    parser.add_option_group(group)

    group = OptionGroup(parser, "Debugging")
    group.add_option("-d", "--debug", dest="debug", action="store_true",
                     default=False, help="debug info")
    group.add_option("-v", dest="verbosity", action="count", default=0,
                     help="verbosity")
    parser.add_option_group(group)

    return parser

###############################################################################


def getFileAnnotations(img):
    """
    Returns the file annotations
    """
    annotations = []
    for ann in img.listAnnotations():
        if type(ann) is omero.gateway.FileAnnotationWrapper:
            annotations.append(ann)
    if len(annotations):
        print("  Image has %d file annotations" % len(annotations))
    return annotations


def process_image(conn, image_id, params):
    """
    Extract the specified image's log files into local files.

    @param conn:     The BlitzGateway connection
    @param image_id: The source OMERO Image Id
    @param params:   The script parameters
    """
    conn.keepAlive()
    img = conn.getObject("Image", image_id)
    if not img:
        print("  ERROR: Unknown Image ID = %s" % image_id)
        return False

    image_name = os.path.basename(img.getName())
    print("  Image ID = %s" % image_id)
    print("  Image name = %s" % image_name)
    (x, y, c, z, t) = (img.getSizeX(), img.getSizeY(), img.getSizeC(),
                       img.getSizeZ(), img.getSizeT())
    print("  Dimensions = x%s,y%s,z%s,c%s,t%s" % (x, y, c, z, t))
    bytes = x * y * c * z * t * gdsc.omero.bytes_per_pixel(img.getPixelsType())
    print("  Byte size = %s (%s)" % (
        locale.format("%d", bytes, True), gdsc.omero.convert(bytes)))

    start = datetime.now()

    return_value = False

    # Extract the log files annotation files
    annotations = getFileAnnotations(img)
    if annotations:
        for ann in annotations:
            # Check for .log suffix
            if not re.match('.*\.[lL][oO][gG]$', ann.getFileName()):
                continue

            # Create output filename
            output_name = os.path.join(params[PARAM_OUT_DIRECTORY],
                                       "%d-%s" % (image_id,
                                                  os.path.basename(
                                                      ann.getFileName())))
            output_name = output_name.replace(' ', '_')
            if os.path.isfile(output_name) and not params[PARAM_FORCE]:
                print("  File exists %s" % output_name)
            else:
                print("  Saving %s" % output_name)

                out = open(output_name, 'wb')
                for buf in ann.getFileInChunks():
                    out.write(buf)
                out.close()

                return_value = True

    print("  Processing time = %s" % (datetime.now() - start))
    return return_value


def run(conn, params):
    """
    For each image defined in the script parameters, extract the image log
    locally. Returns the number of images processed.

    @param conn:   The BlitzGateway connection
    @param params: The script parameters
    """
    global options
    count = 0

    for user_id, ids in iter(params[PARAM_IDS].items()):
        # Log-in as different user
        if options.verbosity:
            print("Switching to user %s" % user_id)
        ttl = gdsc.omero.TIMEOUT * 10
        userConn = conn.suConn(user_id, ttl=ttl)
        if not userConn:
            raise Exception("Failed to connect to OMERO as user ID '%s'" %
                            user_id)
        total = len(ids)
        for index, id in enumerate(ids):
            print("Image %d / %d" % (index+1, total))
            if process_image(userConn, id, params):
                count += 1
        userConn._closeSession()

        conn.keepAlive()

    return count


def add_param(params, name, value, debug):
    params[name] = value
    if debug:
        print("  %s = %s" % (name.replace('_', ' ').title(), value))


# Gather our code in a main() function
def main():
    global options
    parser = init_options()
    (options, args) = parser.parse_args()
    if len(args) < 1:
        parser.print_help()
        sys.exit()

    # Initialise the parameters
    params = {}
    if options.debug:
        print("Parameters ...")
    add_param(params, PARAM_OUT_DIRECTORY, options.out_dir, options.debug)
    add_param(params, PARAM_FORCE, options.force, options.debug)
    add_param(params, PARAM_DEBUG, options.debug, options.debug)
    if options.debug:
        print("")

    if not os.path.isdir(params[PARAM_OUT_DIRECTORY]):
        # Try to create output directory
        try:
            os.makedirs(params[PARAM_OUT_DIRECTORY])
        except OSError as e:
            if e.errno != errno.EEXIST:
                print ("Directory does not exist: %s" %
                       params[PARAM_OUT_DIRECTORY])
                sys.exit()

    images = {}
    f = open(args[0])
    for line in f:
        (id, user_id) = line.rstrip().split(',')
        id = int(id)
        if options.verbosity > 1:
            print('Process Image ID %d (%s)' % (id, user_id))
        ids = images.get(user_id, [])
        ids.append(id)
        images[user_id] = ids
    f.close()

    params[PARAM_IDS] = images

    # Connect to OMERO
    conn = None
    try:
        if options.verbosity:
            print("Creating OMERO gateway")
        conn = BlitzGateway(options.username, options.password,
                            host=options.host, port=options.port)

        if options.verbosity:
            print("Connecting to OMERO")
        if not conn.connect():
            raise Exception("Failed to connect to OMERO: %s" %
                            conn.getLastError())

        ttl = gdsc.omero.TIMEOUT * 10
        conn.getSession().setTimeToIdle(rlong(ttl))

        if options.verbosity:
            print("Processing images")

        result = run(conn, params)

        if result >= 0:
            print("Processed %s image%s with log files" % 
                  (result, result != 1 and 's' or ''))
    except Exception as e:
        print("An error occurred: %s" % e)
    finally:
        if conn:
            conn.close()


# Standard boilerplate to call the main() function to begin the program.
if __name__ == '__main__':
    main()
