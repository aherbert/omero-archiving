# OMERO Archiving

Provides tools for archiving images from [OMERO](https://www.openmicroscopy.org/omero/).

The tools provided here are a proof-of-concept archiving process. They are
provided for free in the event that someone may find them useful. The archiving
process is still in a development phase and has not been tested in a production
environment. The process may not be scalable and has missing features such as
a robust unarchiving process. This is due to the fact that the archiving
solution used by the prototype has an automatic file retrieval process that
is triggered by a file access event. If the file is not available locally it
is restored. Thus tools for unarchiving are unecessary.

A simpler solution to archiving data from OMERO is to expand the OMERO storage
capacity. This removes the requirement to free space in the OMERO file system.

An alternative to archiving from OMERO is to use the OMERO 5 in-place import feature. This allows OMERO
to serve image files but not managed their image data. The data can be managed
by any suitable archiving system.

[![License: 0BSD](https://img.shields.io/badge/License-0BSD-blue.svg)](https://opensource.org/licenses/0BSD)

## Table of contents
1. [Introduction](#introduction)
1. [Archiving images from OMERO to Arkivum](#archiving-to-arkivum)
1. [Archiving images from OMERO to file](#archiving-to-file)
1. [Archiving Details](#archiving-details)
  1. [OMERO import formats](#omero-import-formats)
  1. [Archiving workflow](#archiving-workflow)
  1. [OMERO archiving scripts](#omero-archiving-scripts)
  1. [Archiving scripts](#archiving-scripts)
  1. [Email notifications](#emails)
  1. [Archive register](#archive-register)
1. [Installation](#installation)


## Introduction

OMERO is used to store and manage microscope images. Images are imported,
metadata extracted from the images and thumbnails generated. The images
can be browsed using OMERO clients and the metadata viewed. The image can be
opened and the image pixels viewed.

Archiving is used when instant access to the pixel data is
no longer required. In this case valuable storage space can be
regained by extracting the image data from OMERO and moving it to a low cost
storage medium for long term archiving.

OMERO provides storage of image pixel data and associated meta-data as separate physical entities, by storing meta-
data in cache files and a database. This can be exploited to allow images to be safely archived from
OMERO to a remote data archiving system. The OMERO image browsing features using the image
metadata remain functional. Attempts to access the pixel data will safely fail;
if the pixel data cannot be found then OMERO will wait and the request can be
cancelled.

This archiving strategy applies to files physically managed by OMERO, that is they
have been copied into the OMERO file repository. OMERO
version 5 introduced in-place import where files can be imported without being
copied into the OMERO managed file repository. This process creates symbolic
links from the OMERO managed file repository to the file location. The archiving
stratgey is a reverse of the in-place import. The managed files are moved
out of the managed repository and symbolic links created from the original
location to the archive location. If the archive location has low or zero availability the
behaviour of OMERO is identical to the file being missing; it will wait. If
the archive location has high availablity then OMERO will function as if the
file is in the managed repository. This can be exploited to unarchive images
by returning files to the archive location.

## Archiving images from OMERO to Arkivum <a name="archiving-to-arkivum"></a>

[Arkivum](https://arkivum.com/) provides a digital data asset archiving solution.
An installation consists of a local file store that contains a virtual file
system. Files can be copied into the file store and these are then ingested
by the system and archived. The archive status of files can be queried using
a REST API. The archive process involves exporting data to remote
data centres and back-up to tape via an Escrow provider. The data may then be deleted locally when
safely archived. The REST API may be used to query the status of the archived
file. A request for archived data involves attempting to access the file.
If it is not available locally a process of replication begins that will restore
the file.

Archiving from OMERO to Arkivum involves a two step process:

1. Mark images for archiving
2. Identify image files and move them to Arkivum

Images are tagged for archiving using a custom OMERO script run within the
client. The OMERO permissions model allows a user to tag another user's images
if the group is read-write or read-annotate. This is not allowed for a read-only
or private group. At this permission level admin users or group owners may view
other user's images but not annotate them. Note that if a group's permissions
are lowered to private or read-only then tagging across users is not allowed
and any existing cross-user tags are removed. For this reason long-term
archiving tags should be applied by the image owner; these will not be removed
if group permissions are modified. The OMERO group viewing permissions are
respected to control archive requests. A user may tag their own images. An admin
user or group owner is allowed to tag other user's images. This is done by
using a sudo connection to switch to the image owner to apply the tag.

Warning: Archiving tags may be removed by certain actions within the OMERO
system. An example is to move an image from one group to another group. It is
recommended to move images to an appropriately organised storage structure
(user, dataset and project) before initiating the archive process. This
minimises the chance of accidentally removing the archive tag metadata from
archived images.

A background automated archiving script identifies all the physical files
(original files and/or pixel files) associated with a tagged image and records them in a register. The
tag is then updated to indicate the image is archived. Any other images associated with the same
files are also tagged, e.g. for image filesets. The files to be archived are copied to Arkivum, and when
successfully ingested the original files can be deleted. A symbolic link from the original location to
the mounted Arkivum appliance allows OMERO to access the image data. If the file is cached locally
by Arkivum then the access of archived data is transparent. If not then a request to open the file will
initiate a request for Arkivum to restore the local cache from remote data centres. The image data
will become available when Arkivum completes the data replication. The time for this process is
variable but can be monitored by administrators; the user must repeatedly return later and try to
open the image until successful.

This process was presented at the 2016 OMERO Users Meeting:
[Archiving images from OMERO to Arkivum (presentation slides)](https://downloads.openmicroscopy.org/presentations/2016/Users-Meeting/Lightning-Talks/Alex%20Herbert%20-%20Archiving%20images%20from%20OMERO%20to%20Arkivum.pdf)

## Archiving images from OMERO to file <a name="archiving-to-file"></a>

The process of archiving to file is similar to archiving to Arkivum.
The image files to be archived are identified and then copied to a file store.
The copy is verified with checksums and then the original files can be deleted.
Administration of the file store can then use an archiving strategy of choice,
for example all data can be back-up to tape and the file store removed.
Unarchiving will require the correct image files are identified and returned to
the same location.

A script to perform archiving to file is provided in the [tools/bin](src/tools/bin) directory.

## Archiving Details <a name="archiving-details"></a>

### Locations

The archiving process uses a file based record of all archiving activity. The process
uses job files which are managed through a workflow in the `/Archive/Job`
directory. Archiving records are stored in the `/Archive/Log` directory. The
directory structure is as shown below:

    Archive/
    ├── Job
    │   ├── Approved
    │   ├── Declined
    │   ├── Error
    │   ├── Finished
    │   ├── New
    │   └── Running
    ├── Log
    ├── archive_register
    └── to_archive_register

The following table describes locations important for archiving.

Location | Description
--- | ---
`/OMERO` | The OMERO filesystem
`/OMERO/Files` | The OMERO managed files repository (OMERO v4 original files store)
`/OMERO/Pixels` | The OMERO managed pixels repository (OMERO v4 pixels store)
`/OMERO/ManagedRepository` | The OMERO managed image filesets repository (OMERO v5 image store)
`/OMERO/Archive` | The directory used by the archiving process.
`/OMERO/Archive/Log` | The directory used by the archiving process. Mirrors the structure of the OMERO managed repository starting at `/OMERO` for every file that has been archived. In the directory corresponding to the archived file `xxx` is a `xxx.ark` file containing details of the corresponding archived file.
`/OMERO/Archive/Job` | The directory used by the archiving process to process archiving jobs.
`/OMERO/Archive/to_archive_register` | The register of all files to be archived (archiving in process).
`/OMERO/Archive/archive_register` | The register of all files that have been archived.
`OMERO_DIST` | OMERO server distribution
`OMERO_DIST/lib/scripts` | OMERO scripts location

### OMERO import formats <a name="omero-import-formats"></a>

OMERO version 4 imports read image files and converted them into a universal
pixel format. This was stored in the OMERO filesystem. This did not allow access
to the original image files; and accuracy was fixed by the compatibility of
BioFormats at image import. Optionally the original image files could also be
stored allowing access to the original data but thus duplicating the storage
requirements. The image pixel data is stored in `/Pixels` and original data
in `/Files`.

OMERO version 5 imports create a fileset of images. These are stored using the
original file format in `/ManagedRepository`. Accuracy of reading metadata and
pixels is determined by the current runtime version of BioFormats. This allows
compatibility to be improved with software updates. The original files can be
extracted.

The archiving scripts can identify image files from version 4 or version 5
imports. In addition the scripts can identify all images that use the same
original source files by resolving one-to-many and many-to-many relationships.
This allows 1 image to be tagged for archiving, the entire set of image files
archived and then all dependent images can be marked as archived.

### Archiving workflow <a name="archiving-workflow"></a>

The archiving process is run on the OMERO server as a daily task. The process
uses job files which are managed through a workflow in the `/Archive/Job`
directory.

Location | Description
--- | ---
`/New` | Contained new archiving jobs awaiting review.
`/Approved` | New archiving jobs are manually put here if approved. They will transition to Running.
`/Declined` | New archiving jobs are manually put here if declined. They will transition to Finished.
`/Running` | Currently running archiving jobs.
`/Error` | Archive jobs that have errored. Require manual investigation of error logs. Can be restarted by placing in Running.
`/Finished` | Archive jobs that have finished. The jobs file will contain the archiving status.

To initiate archiving a job file has to be created and put into the `New` folder.
Currently the only mechanism to do this is a scan of the OMERO server for any
images that has been tagged with `TO-ARCHIVE`. These images are used to create a
job file of all the images that should be archived and their corresponding files.

An example archive file is shown below:

```
[Info]
user id = 453
omename = user123
group id = 4
owner id = 453
owner omename = user123
email = user123@host.com
created = Mon Nov 28 15:59:57 2016
status = Declined
expiry = 2026-11-28
description = testing
total bytes = 70
total size = 70 Bytes

[Images]
/P1/images/__utm.gif (159118) = True
/P1/images/__utm2.gif (159119) = True

[Files]
/OMERO/ManagedRepository/user123_453/2016-11/28/15-50-04.707/__utm2.gif = Declined
/OMERO/ManagedRepository/user123_453/2016-11/28/15-50-03.954/__utm.gif = Declined
```

The job file contains the OMERO user details, the images and their files, and
the archiving status of the files. This archive job was declined and the
files remain in the original location in the OMERO managed repository.

### OMERO Archiving scripts <a name="omero-archiving-scripts"></a>

The OMERO script [Archive_Images.py](src/scripts/archiving/Archive_Images.py) can be used
to tag images with the `TO-ARCHIVE` tag. This script is usually run through the
OMERO Insight client using the in-built scripts functionality. It allows
a set of images or datasets to be tagged. All images in a dataset are tagged.
The script also adds a tag containing notes about the archive. This is
retained throughout the archiving process where as the `TO-ARCHIVE` tag will
be transitioned through `ARCHIVE-PENDING` to `ARCHIVED`.

To allow testing without using OMERO Insight the script can be run on the command-line
by passing arguments. The OMERO connection details from the library
defaults can be overridden and the IDs must be specified. Optionally the datatype
to tag can be specified, otherwise the default is `Image`.

```
> python3 Archive_Images.py 123 --datatype=Dataset --expiry=25 --description="Dataset superseded by 456"
Creating OMERO gateway
Connecting to OMERO ...
Processing 1 image
Applying tag: 63 ARCHIVE NOTE
Applying tag: 62 TO-ARCHIVE
New 1 : Existing 0 : Error 0
```

You can verify the tags have been added via the OMERO Insight client. The tags
will be displayed for the image in the `Key-Value Pairs` table of annotations.
The tags are created as map annotations in the `archiving` namespace. They are
not created as tag annotations. This prevents the tag from being removed using
the OMERO Insight client. It also prevents manually creating a `TO-ARCHIVE` tag
in the Insight client and adding it to images.

Tags on images still in the `TO-ARCHIVE` state can be removed using the
[Clear_Archive_Tag.py](src/scripts/archiving/Clear_Archive_Tag.py) script:

```
> python3 Clear_Archive_Tag.py 123 --datatype=Dataset
Creating OMERO gateway
Connecting to OMERO ...
Processing 1 image
Removing tag: TO-ARCHIVE
Removing tag: ARCHIVE NOTE
Removed 2 : Error 0
```

This script is used to prevent images marked in error for
archiving from being archived. If the archiving process has started then the
archiving tag will have been changed and the process cannot be stopped.

Note: If arguments are not specified then the scripts will run as an
OMERO script as if called by the OMERO scripting service. This will error
outside of the OMERO scripting service.

### Archiving scripts <a name="archiving-scripts"></a>

The archiving script [process_archive_images.py](src/tools/bin/process_archive_images.py)
performs the following steps:

1. Finds all images in OMERO that are tagged for archiving,
identifies their original files and prepares them for archiving. The source
images for all the files are then tagged as pending. A job file is created in
the New folder of the Job folder workflow. New jobs must be manually Approved
or Declined. E-mails an administrator that new job file exist.
2. Any jobs files in the Declined folder have the pending tag removed from their
images and the job file is moved to Finished. E-mails the user the job has
been declined.
3. Any job files in the Approved folder have the pending tag removed from their
images, the archived tag applied and the job file is moved to Running.

This process has a manual confirmation step. This prevents a user from triggering
the archive process on images by mistake. It was envisioned that archiving would
be a low frequency event and the manual process of approval would not be time
consuming.

Processing of the Running jobs depends on the archive strategy. Typically the
files will be copied somewhere outside of OMERO, and when confirmed to be safely
copied the original files can be removed. The archiving result can be e-mailed
to the user.

The archiving script [archive_to_arkivum.py](src/tools/bin/archive_to_arkivum.py)
will copy files to a configured Arkivum server and confirm archiving using the
Arkivum REST API. The script [archive_to_file.py](src/tools/bin/archive_to_file.py)
will copy the file to an external file system.

### E-mail notifications <a name="emails"></a>

The archiving scripts send e-mails to the user and administrator at certain
stages of the archive process. This uses the python `smtplib` module and sends
e-mail via `localhost`. The library must be able to connect and send e-mail
through a SMTP relay on the host machine.

The [send_mail.py](src/tools/bin/send_mail.py) script can be used to test
if the localhost is correctly configured to send e-mails. The script uses
an unencrypted connection and assumes that the `smptlib` can connect using:

    smtplib.SMTP('localhost')

If the host machine requires a secure connection to the local SMTP relay when
running on the host machine then the scripts will require updating in all
locations that use `smtplib`.

### Archive register <a name="archive-register"></a>

All archiving scripts use a file based data store to hold information on the
files that are currently in the archiving process and those that have been
archived. These are the archive resgisters located in `/OMERO/Archive`.
This solution may not scale. The scripts access the information
through an API and thus the implementation of the archive register can be
changed.


## Installation

1. Copy the tagging scripts into your OMERO installation:

        OMERO_DIST/lib/scripts

1. Update your list of installed scripts by examining the list of scripts
   in OMERO.insight or OMERO.web, or by running the following command:

        path/to/bin/omero script list

1. Copy the archiving scripts into a known location. This will be added to the path
   of the task executing the archiving scripts.

        [path]/tools/bin

1. Copy the library functions used by the scripts into a known location. This
   will be added to the python path of the task executing the archiving scripts.

        [path]/tools/lib

1. Update the details stored in the library script.

        [path]/tools/lib/gdsc/omero.py

  This includes the username, hostname and port for the connection to OMERO.
  This must be an admin user and the password is contained in the library file.
  This is **not secure** unless the location of the file can be protected by the
  permissions model of the host platform. If this is not possible an alternative
  solution must be implemented. The connection requires administrator permissions
  in order to apply tags to images and search for image files as any omero user.

  From OMERO 5.4 it is possible to create restricted admin users. Some scripts
  may run within the permissions permitted of a restricted admin user. For
  example some scripts only need to read the data of any user while others
  require tagging images as the user (`sudo` permissions). This functionality
  has not been investigated as the system was developed before restricted
  administrator users were introduced.

1. Create the directory structure used by the archiving job workflow.

        cd /path/to/OMERO
        mkdir Archive
        cd Archive && mkdir Job log
        cd Job && mkdir New Approved Declined Running Error Finished

1. Configure the archiving control script to run the archiving process. This should set up the
   environment variables to add the OMERO python libraries and the archiving
   libraries to the python path. It should then run the archiving scripts.
   An example is provided as [omero_to_arkivum.sh](src/tools/bin/archive_to_file.py).

1. Test the localhost can relay e-mails via a SMTP server. Use the
   `send_mail.py` script to test the system is correctly configured.

        send_mail.py user@somewhere.com

1. Test the script by running the archiving control script. The scripts currently
   log message to standard output.

   The archiving scripts create a PID file to prevent two instances executing
   concurrently. This prevents corruption of the `/Archive` directory state.

   Testing can be performed by running the script manually on the server.

1. The script can be executed in a scheduled task. On a unix
   based system this can be done in a cron job and the output captured:

       # Run the script to copy all tagged OMERO images to Arkivum
       # Daily processing @4:10am
       10     4  *  *  *  omero [path]/tools/bin/omero_to_arkivum.sh >> /var/omero/arkivum.log 2>&1
