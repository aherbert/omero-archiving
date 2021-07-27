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
This script extracts image information from OMERO
"""
import os
import errno
import sys
import locale
locale.setlocale(locale.LC_ALL, '')

from datetime import datetime
from optparse import OptionParser
from optparse import OptionGroup

from omero.gateway import BlitzGateway, FileAnnotationWrapper, ImageWrapper
from omero.rtypes import *  # noqa
from omero.sys import Parameters

import gdsc.omero

PARAM_IDS = "IDs"
PARAM_PIXELS = "Pixels"

###############################################################################


def init_options():
    """Initialise the program options"""

    parser = OptionParser(usage="usage: %prog [options] ImageId "
                          "[ImageId2 ...]", description="Program to extract "
                          "images info from OMERO",
                          add_help_option=True, version="%prog 1.0")

    group = OptionGroup(parser, "Image Selection")
    group.add_option("--file", dest="filename",
                     help="Read IDs from FILE", metavar="FILE")
    group.add_option("--raw", dest="raw", default=False, action='store_true',
                     help="IDs correspond to raw pixels files")
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


def process_pixels(conn, pid, params):
    """
    Extract info for the specified pixels

    @param conn:     The BlitzGateway connection
    @param pid:      The source OMERO Pixels Id
    @param params:   The script parameters
    """
    q = conn.getQueryService()
    p = q.find('Pixels', pid, conn.SERVICE_OPTS)
    if p is None:
        return False
    img = ImageWrapper(conn, p.image)
    return process_image_info(conn, img, params)

def process_image(conn, image_id, params):
    """
    Extract info for the specified image

    @param conn:     The BlitzGateway connection
    @param image_id: The source OMERO Image Id
    @param params:   The script parameters
    """
    img = conn.getObject("Image", image_id)
    if not img:
        print("  ERROR: Unknown Image ID = %s" % image_id)
        return False
    return process_image_info(conn, img, params)

def process_image_info(conn, img, params):
    """
    Extract info for the specified image

    @param conn:     The BlitzGateway connection
    @param img:      The source OMERO Image Id
    @param params:   The script parameters
    """
    image_name = os.path.basename(img.getName())
    print("  Image ID = %s" % img.getId())
    o = img.getOwner()
    print("  Owner = %s (%s)" % (o.getName(), o.getFullName()))
    print("  Group =", img.getDetails().getGroup().getName())
    print("  Image name = %s" % image_name)
    print("  Import date = %s" % img.getDate())
    for p in img.listParents():
        if p.getParent():
            print("  Project\Dataset = %s\%s" % (p.getParent().getName(), p.getName()))
        else:
            print("  Dataset =", p.getName())
    (x, y, c, z, t) = (img.getSizeX(), img.getSizeY(), img.getSizeC(),
                       img.getSizeZ(), img.getSizeT())
    print("  Dimensions = x%s,y%s,z%s,c%s,t%s" % (x, y, c, z, t))
    bytes = x * y * c * z * t * gdsc.omero.bytes_per_pixel(img.getPixelsType())
    print("  Byte size = %s (%s)" % (
        locale.format("%d", bytes, True), gdsc.omero.convert(bytes)))

    print("  Pixels ID =", img.getPixelsId())
    pyramid = img.requiresPixelsPyramid()
    print("  Pyramid =", img.requiresPixelsPyramid())

    fileset = img.getFileset()       # will be None for pre-FS images
    if fileset:
        fsId = fileset.getId()
        fileCount = img.countFilesetFiles()
        print("  Fileset files =", fileCount)

        for origFile in fileset.listFiles():
            name = origFile.getName()
            path = origFile.getPath()
            print("  File =", os.path.join(options.repository, path, name))

        if pyramid:
            path = gdsc.omero.get_legacy_path(options.pixels, img.getPixelsId())
            path = path + '_pyramid'
            print("  Pyramid file =", path)

        #print "\nList images"
        #for fsImage in fileset.copyImages():
        #    print fsImage.getId(), fsImage.getName()
    else:
        path = gdsc.omero.get_legacy_path(options.pixels, img.getPixelsId())

        # Q. What about pyramids?
        if pyramid:
            # Sometimes the pixels file is a pyramid, we cannot check for the
            # file since we may not have access to the path. Just assume the
            # API knows what it is.
            path = path + '_pyramid'
        print("  Pixels file =", path)

        for of in img.getImportedImageFiles():
            name = os.path.basename(of.getName())
            print("  Original File = %s (%s)" % (
                gdsc.omero.get_legacy_path(options.files,
                                           of.getId()), name))

    # Optionally extract the annotation files
    annotations = getFileAnnotations(img)
    if annotations:
        for ann in annotations:
            name = os.path.basename(ann.getFileName())
            print("  File Annotation = %s (%s)" % (
                gdsc.omero.get_legacy_path(options.files,
                                           ann.getFile().getId()), name))

    return True

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
        if params[PARAM_PIXELS]:
            print("Pixels %d / %d" % (index+1, total))
            if process_pixels(conn, image_id, params):
                count += 1
        else:
            print("Image %d / %d" % (index+1, total))
            if process_image(conn, image_id, params):
                count += 1

    return count


# Gather our code in a main() function
def main():
    parser = init_options()
    global options
    (options, args) = parser.parse_args()
    if len(args) < 1 and not options.filename:
        parser.print_help()
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
            ids.append(int(arg))

    params = {}
    params[PARAM_IDS] = ids
    params[PARAM_PIXELS] = options.raw

    # Connect to OMERO
    conn = None
    try:
        conn = BlitzGateway(options.username, options.password,
                            host=options.host, port=options.port)

        if not conn.connect():
            raise Exception("Failed to connect to OMERO: %s" %
                            conn.getLastError())

        if not conn.isAdmin():
            raise Exception("Require ADMIN privaledges")

        # Generic group for query across all of OMERO
        conn.SERVICE_OPTS.setOmeroGroup(-1)

        ttl = gdsc.omero.TIMEOUT * 10
        conn.getSession().setTimeToIdle(rlong(ttl))

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
