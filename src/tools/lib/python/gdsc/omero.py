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

"""Contains common functionality for the GDSC OMERO python scripts"""

import os
import sys

# Default username for the omero connection
USERNAME = 'user'
# Default password for the omero connection
PASSWORD = 'password'
# Default omero host
HOST = 'omero.host.com'
# Default omero port
PORT = 4064
# The address to send emails from
ADMIN_EMAIL = 'admin@host.com'
# The addresses to send administrator emails to
ADMIN_EMAILS = [ADMIN_EMAIL]
# OMERO timeout (in milliseconds). Set to 1 hour.
TIMEOUT = 60 * 60 * 1000

# Archive tags
TAG_ARCHIVE_NOTE = "ARCHIVE NOTE"
TAG_ARCHIVED = "ARCHIVED"
TAG_PENDING = "ARCHIVE-PENDING"
TAG_TO_ARCHIVE = "TO-ARCHIVE"
TAG_FROM_ARCHIVE = "FROM-ARCHIVE"

# Details of OMERO's file storage system
OMERO_ROOT = '/OMERO'
REPOSITORY = OMERO_ROOT + '/ManagedRepository/'
LEGACY_FILES = OMERO_ROOT + '/Files/'
LEGACY_PIXELS = OMERO_ROOT + '/Pixels/'

# Details of the archiving process
ARCHIVE = OMERO_ROOT + '/Archive'
ARCHIVE_LOG = ARCHIVE + '/Log'
ARCHIVE_JOB = ARCHIVE + '/Job'
TO_ARCHIVE_REGISTER = ARCHIVE + '/to_archive_register'
ARCHIVED_REGISTER = ARCHIVE + '/archived_register'

# Where to archive (for the File Archiver).
ARCHIVE_ROOT = OMERO_ROOT + '/Archive'

# Arkivum server for REST API
ARKIVUM_SERVER = 'ark.host.com:8443'
# Arkivum root (for the mounted appliance)
ARKIVUM_ROOT = '/arkivum'
# Arkivum path (directory to copy files)
ARKIVUM_PATH = 'omero'

# Keys for the archiving records
ARK_SOURCE = 'Source'
ARK_FILE_ARCHIVER = 'File Archiver'
ARK_ARKIVUM_ARCHIVER = 'Arkivum Archiver'
JOB_INFO = 'Info'
JOB_IMAGES = 'Images'
JOB_FILES = 'Files'
JOB_IGNORE = 'Ignore'
JOB_NEW = 'New'
JOB_APPROVED = 'Approved'
JOB_DECLINED = 'Declined'
JOB_RUNNING = 'Running'
JOB_FINISHED = 'Finished'
JOB_ERROR = 'Error'

##############################################################################

def bytes_per_pixel(pixel_type):
    """
    Return the number of bytes per pixel for the given pixel type

    @param pixel_type:  The OMERO pixel type
    @type pixel_type:   String
    """
    if (pixel_type == "int8" or pixel_type == "uint8"):
        return 1
    elif (pixel_type == "int16" or pixel_type == "uint16"):
        return 2
    elif (pixel_type == "int32" or
          pixel_type == "uint32" or
          pixel_type == "float"):
        return 4
    elif pixel_type == "double":
        return 8
    else:
        raise Exception("Unknown pixel type: %s" % (pixel_type))


def get_byte_size(img):
    """
    Return the total byte size of the image

    @param img:  The ImageWrapper object
    """
    (x, y, c, z, t) = (img.getSizeX(), img.getSizeY(), img.getSizeC(),
                       img.getSizeZ(), img.getSizeT())
    return x * y * c * z * t * bytes_per_pixel(img.getPixelsType())


##############################################################################

def convert(number, verbosity=100, raw_bytes=False):
    """
    Convert bytes into human-readable representation

    @param number:     The number of bytes_per_pixel
    @param verbosity:  The verbosity of the readable format
    @param raw_bytes:  Do not translate to human readable bytes
    """
    if raw_bytes:
        return '%d Byte%s' % (number, number != 1 and 's' or '')
    if number == 0:
        return '0 Bytes'
    negative = ''
    if number < 0:
        negative = '-'
        number = -number
    assert 0 < number < 1 << 110, 'number out of range'
    ordered = reversed(tuple(format_bytes(partition_number(number, 1 << 10))))
    data = []
    count = 0
    for item in ordered:
        if item[0] != '0':
            data.append(item)
            if count >= verbosity:
                break
            count += 1
    cleaned = negative + ', '.join(data)
    return cleaned


def partition_number(number, base):
    """Continually divide number by base until zero."""
    div, mod = divmod(number, base)
    yield mod
    while div:
        div, mod = divmod(div, base)
        yield mod


def format_bytes(parts):
    """Format partitioned bytes into human-readable strings."""
    for power, number in enumerate(parts):
        yield "%s %s" % (number, format_suffix(power, number))


def format_suffix(power, number):
    """Compute the suffix for a certain power of bytes."""
    result = (PREFIX[power] + 'byte').capitalize()
    if number != 1:
        result += 's'
    return result

PREFIX = ' kilo mega giga tera peta exa zetta yotta bronto geop'.split(' ')


###############################################################################
def splitext(filename):
    """
    Splits a filename into base and extension.
    Handles .ome.tiff as an extension.
    """
    (base, ext) = os.path.splitext(filename)
    # Special case if a .ome.tif since only the .tif will be removed
    if base.endswith('.ome'):
        base = base.replace('.ome', '')
        ext = '.ome' + ext
    return (base, ext)


def is_run_mode():
    """
    Check the command-line arguments contain the word 'run'
    """
    for arg in sys.argv:
        if arg == 'run':
            return True
    return False


def get_legacy_path(prefix, id):
    """
    Get the path to a file Id within the legacy filesystem.
    Adapted from ome/io/nio/AbstractFileSystemService.java
    @param prefix:  The legacy file system root path
    @param id: The file Id
    """
    suffix = ""
    remaining = id
    dirno = 0

    while (remaining > 999):
        remaining /= 1000
        if (remaining > 0):
            dirno = remaining % 1000
            suffix = os.path.join("Dir-%03d" % dirno, suffix)

    return os.path.join(prefix, suffix, str(id))


def get_ark_path(ark_dir, path, dir_check=False):
    """
    Get the path to an archive record for the given file path
    @param ark_dir: The archive record directory
    @param path: The file path
    """
    ark_path = os.path.join(ark_dir, make_non_absolute(path) + '.ark')
    if dir_check:
        directory, filename = os.path.split(ark_path)
        if not os.path.exists(directory):
            os.makedirs(directory)
    return ark_path


def make_non_absolute(path):
    """
    Make a path non-absolute (so it can be joined to a base directory)
    @param path: The file path
    """
    drive, path = os.path.splitdrive(path)
    index = 0
    while os.path.isabs(path[index:]):
        index = index + 1
    return path[index:]


def pleural(count):
    """
    Convenience method to return an s if the count is not 1
    @param count: The count
    """
    return '' if count == 1 else 's'

###############################################################################
class Register:
    """
    Records unique entries to a register file
    """

    def __init__(self, path, read=True):
        """
        Create a register associated with a file. If the file exists it will
        be read. Each entry is on a single line in the file.
        @param path:  The file
        @param read:  Set to true to read the current file contents
        """
        self.items = set()
        self.path = path
        # Read the current contents
        if read and os.path.isfile(path):
            with open(path, "r") as f:
                for line in f:
                    self.items.add(line.strip())
        # Check the file can be written to
        with open(path, "a") as f:
            pass

    def add(self, item):
        """
        Add an entry to the register
        @param item:  The item
        """
        item = str(item)
        if item not in self.items:
            self.items.add(item)
            with open(self.path, "a") as f:
                f.write(item)
                f.write('\n')

    def add_list(self, items):
        """
        Add entries to the register
        @param items:  The list of items
        """
        new = []
        for item in items:
            item = str(item)
            if item not in self.items:
                self.items.add(item)
                new.append(item)
        if new:
            with open(self.path, "a") as f:
                for item in new:
                    f.write(item)
                    f.write('\n')

    def save(self, items):
        """
        Save entries to the register, replacing the current contents
        @param items:  The list of items
        """
        self.items.clear()
        self.items.update(items)
        with open(self.path, "w") as f:
            for item in self.items:
                f.write(item)
                f.write('\n')

    def size(self):
        """Get the number of items in the register"""
        return len(self.items)

    def remove_list(self, items):
        """
        Remove entries from the register
        @param items:  The list of items
        """
        self.items.difference_update(items)
        with open(self.path, "w") as f:
            for item in self.items:
                f.write(item)
                f.write('\n')

###############################################################################
class PIDFile:
    """
    Records the process ID to a file
    """

    def __init__(self, path):
        """
        Create a PIDFile. If the file exists an exception is thrown.
        @param path:  The file
        """
        self.path = None
        if os.path.isfile(path):
            raise Exception("PID file exists: " + path)
        # Record the PID in the file
        with open(path, "a") as f:
            f.write(str(os.getpid()))
            f.write('\n')
        self.path = path

    def delete(self):
        """
        Delete the PID file
        """
        if self.path:
            os.remove(self.path)
            self.path = None

