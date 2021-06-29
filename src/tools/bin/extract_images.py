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
This script extracts images from OMERO to OME TIFF/XML.
"""
import os
import errno
import sys
import locale
locale.setlocale(locale.LC_ALL, '')

from datetime import datetime
from optparse import OptionParser
from optparse import OptionGroup

from omero.gateway import BlitzGateway, FileAnnotationWrapper
from omero.rtypes import *  # noqa

import gdsc.omero

PARAM_OUT_DIRECTORY = "out_dir"
PARAM_USER_ID = "user_id"
PARAM_GROUP = "group"
PARAM_IDS = "IDs"
PARAM_OME_XML = "ome_xml"
PARAM_ORIGINAL = "original"
PARAM_ANNOTATION = "annotation"
PARAM_DEBUG = "debug"
PARAM_FORCE = "force"
PARAM_NO_IMAGE = "no_image"

###############################################################################

def init_options():
    """Initialise the program options"""

    parser = OptionParser(usage="usage: %prog [options] ImageId "
                          "[ImageId2 ...]", description="Program to extract "
                          "images from OMERO to OME TIF/XML",
                          add_help_option=True, version="%prog 1.0")

    group = OptionGroup(parser, "Image Selection")
    group.add_option("-x", "--%s" % PARAM_OME_XML, dest="ome_xml",
                     action="store_true",
                     default=False, help="Extract OME XML [%default]")
    group.add_option("-o", "--%s" % PARAM_ORIGINAL, dest="original",
                     action="store_true",
                     default=False, help="Extract original archive image "
                                         "[%default]")
    group.add_option("-a", "--%s" % PARAM_ANNOTATION, dest="annotation",
                     action="store_true",
                     default=False, help="Extract image file annotations "
                                         "[%default]")
    group.add_option("-n", "--%s" % PARAM_NO_IMAGE, dest="no_image",
                     action="store_true",
                     default=False, help="Do not extract image file "
                     "[%default]")
    group.add_option("--dir", "--%s" % PARAM_OUT_DIRECTORY, dest="out_dir",
                     default='.', help="Output directory [%default]")
    group.add_option("--%s" % PARAM_USER_ID, default="root",
                     dest=PARAM_USER_ID, help="OMERO user ID [%default]")
    group.add_option("--%s" % PARAM_GROUP, default=None, dest=PARAM_GROUP,
                     help="OMERO user group [%default]")
    group.add_option("-f", "--%s" % PARAM_FORCE, dest="force",
                     action="store_true",
                     default=False, help="Overwrite local files [%default]")
    group.add_option("--file", dest="filename",
                     help="Read IDs from FILE", metavar="FILE")
    parser.add_option_group(group)

    group = OptionGroup(parser, "OMERO")
    group.add_option("-u", "--username", dest="username",
                     default=gdsc.omero.USERNAME, help="OMERO username "
                     "[%default]")
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


def create_name(name, output_dir, ome_xml):
    """
    Create the filename for the output file.

    @param name:       The filename
    @param output_dir: The output directory
    @param ome_xml:    True if OME XML
    """
    (base, ext) = gdsc.omero.splitext(name)
    name = base.replace(' ', '_')

    if ome_xml:
        extension = '.ome'
    else:
        extension = '.ome.tif'

    return "%s%s" % (os.path.join(output_dir, name), extension)


def getFileAnnotations(img):
    """
    Returns the file annotations
    """
    annotations = []
    for ann in img.listAnnotations():
        if type(ann) is FileAnnotationWrapper:
            annotations.append(ann)
    if len(annotations):
        print("  Image has %d file annotations" % len(annotations))
    return annotations


def process_image(conn, image_id, params):
    """
    Extract the specified image into local OME file.

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

    if not params[PARAM_NO_IMAGE]:
        if params[PARAM_ORIGINAL] and img.countArchivedFiles():
            # Extract the original files
            print("  Extracting original file")

            for of in img.getArchivedFiles():
                # Ignore all files except the actual original file
                name = os.path.basename(of.getName())
                if name != image_name:
                    continue

                # Create output filename
                output_name = os.path.join(params[PARAM_OUT_DIRECTORY], name)

                # Check for existing files
                if os.path.isfile(output_name) and not params[PARAM_FORCE]:
                    print("  File exists %s" % output_name)
                else:
                    print("  Saving %s" % output_name)

                    out = open(output_name, 'wb')

                    # Read the file
                    for buf in of.getFileInChunks():
                        out.write(buf)

                    # Clean-up
                    out.close()

                    return_value = True

                break  # since the original file has been processed

        else:
            # Use the export to OME-TIFF option
            ome_xml = params[PARAM_OME_XML]

            # Create output filename
            output_name = create_name(image_name, params[PARAM_OUT_DIRECTORY],
                                      ome_xml)

            # Check for existing files
            if os.path.isfile(output_name) and not params[PARAM_FORCE]:
                print("  File exists %s" % output_name)
            else:
                print("  Generating remote image")

                e = conn.createExporter()
                e.addImage(image_id)

                # Use a finally block to ensure clean-up of the exporter
                try:
                    if ome_xml:
                        e.generateXml()
                    else:
                        e.generateTiff()

                    print("  Saving %s" % output_name)

                    out = open(output_name, 'wb')

                    # Read the file
                    read = 0
                    blocksize = 1048576
                    while True:
                        buf = e.read(read, blocksize)
                        out.write(buf)
                        if len(buf) < blocksize:
                            break
                        read += len(buf)

                    # Clean-up
                    out.close()

                finally:
                    e.close()

                return_value = True

    # Optionally extract the annotation files
    annotations = getFileAnnotations(img)
    if annotations and params[PARAM_ANNOTATION]:
        for ann in annotations:
            # Create output filename
            output_name = os.path.join(params[PARAM_OUT_DIRECTORY],
                                       "%s_%s" % (image_name, os.path.basename(
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
    For each image defined in the script parameters, extract the image locally.
    Returns the number of images processed.

    @param conn:   The BlitzGateway connection
    @param params: The script parameters
    """
    count = 0
    total = len(params[PARAM_IDS])
    for index, image_id in enumerate(params[PARAM_IDS]):
        print("Image %d / %d" % (index+1, total))
        if process_image(conn, image_id, params):
            count += 1

    return count


def add_param(params, name, value, debug):
    params[name] = value
    if debug:
        print("  %s = %s" % (name.replace('_', ' ').title(), value))


# Gather our code in a main() function
def main():
    parser = init_options()
    (options, args) = parser.parse_args()
    if len(args) < 1 and not options.filename:
        parser.print_help()
        sys.exit()

    # Initialise the parameters
    params = {}
    if options.debug:
        print("Parameters ...")
    add_param(params, PARAM_OME_XML, options.ome_xml, options.debug)
    add_param(params, PARAM_ORIGINAL, options.original, options.debug)
    add_param(params, PARAM_ANNOTATION, options.annotation, options.debug)
    add_param(params, PARAM_NO_IMAGE, options.no_image, options.debug)
    add_param(params, PARAM_OUT_DIRECTORY, options.out_dir, options.debug)
    add_param(params, PARAM_USER_ID, options.user_id, options.debug)
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

    if options.filename:
        args = []
        f = open(options.filename)
        for arg in f:
            args.append(arg.rstrip())
        f.close()

    ids = []
    for arg in args:
        if arg.isdigit():
            if options.verbosity > 1:
                print('Process Image ID %s' % arg)
            ids.append(int(arg))

    params[PARAM_IDS] = ids

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

        # Log-in as different user
        ttl = gdsc.omero.TIMEOUT * 10
        if options.user_id != 'root':
            if options.verbosity:
                print("Switching to user %s" % options.user_id)
            conn = conn.suConn(options.user_id, group=options.group, ttl=ttl)
            if not conn:
                raise Exception("Failed to connect to OMERO as user ID '%s'" %
                                options.user_id)
        else:
            conn.getSession().setTimeToIdle(rlong(ttl))
            # Cross group support
            conn.SERVICE_OPTS.setOmeroGroup(-1)

        if options.verbosity:
            print("Processing images")

        result = run(conn, params)

        if result >= 0:
            print("Processed %s image%s" % (result, result != 1 and 's' or ''))
    except Exception as e:
        print("An error occurred: %s" % e)
    finally:
        if conn:
            conn.close()

# Standard boilerplate to call the main() function to begin the program.
if __name__ == '__main__':
    main()
