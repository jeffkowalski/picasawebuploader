#! /usr/bin/python2
#
# Upload directories of videos and pictures to Picasa Web Albums
#
# Requires:
#   Python 2.7
#   gdata 2.0 python library
#   sips command-line image processing tools.
#
# Copyright (C) 2011 Jack Palevich, All Rights Reserved
#
# Contains code from http://nathanvangheem.com/news/moving-to-picasa-update

import sys
if sys.version_info < (2,7):
    sys.stderr.write("This script requires Python 2.7 or newer.\n")
    sys.stderr.write("Current version: " + sys.version + "\n")
    sys.stderr.flush()
    sys.exit(1)

import argparse
import atom
import atom.service
import filecmp
import gdata
import gdata.photos.service
import gdata.media
import gdata.geo
import gdata.gauth
import getpass
import httplib2
import os
#import pyexiv2
import subprocess
import tempfile
import time
import webbrowser

from datetime import datetime, timedelta
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage
from gdata.photos.service import GPHOTOS_INVALID_ARGUMENT, GPHOTOS_INVALID_CONTENT_TYPE, GooglePhotosException

PICASA_MAX_FREE_IMAGE_DIMENSION = 2048
PICASA_MAX_VIDEO_SIZE_BYTES = 104857600
PICASA_MAX_PICTURES_PER_ALBUM = 2000
PICASA_MAX_RET_ENTRY = 1000

try:
    from PIL import Image
    HAS_PIL_IMAGE = True
except:
    HAS_PIL_IMAGE = False

class VideoEntry(gdata.photos.PhotoEntry):
    pass

gdata.photos.VideoEntry = VideoEntry

def InsertVideo(self, album_or_uri, video, filename_or_handle, content_type='image/jpeg'):
    """Copy of InsertPhoto which removes protections since it *should* work"""
    try:
        assert(isinstance(video, VideoEntry))
    except AssertionError:
        raise GooglePhotosException({'status':GPHOTOS_INVALID_ARGUMENT,
            'body':'`video` must be a gdata.photos.VideoEntry instance',
            'reason':'Found %s, not PhotoEntry' % type(video)
        })
    try:
        majtype, mintype = content_type.split('/')
        #assert(mintype in SUPPORTED_UPLOAD_TYPES)
    except (ValueError, AssertionError):
        raise GooglePhotosException({'status':GPHOTOS_INVALID_CONTENT_TYPE,
            'body':'This is not a valid content type: %s' % content_type,
            'reason':'Accepted content types:'
        })
    if isinstance(filename_or_handle, (str, unicode)) and \
        os.path.exists(filename_or_handle): # it's a file name
        mediasource = gdata.MediaSource()
        mediasource.setFile(filename_or_handle, content_type)
    elif hasattr(filename_or_handle, 'read'):# it's a file-like resource
        if hasattr(filename_or_handle, 'seek'):
            filename_or_handle.seek(0) # rewind pointer to the start of the file
        # gdata.MediaSource needs the content length, so read the whole image
        file_handle = StringIO.StringIO(filename_or_handle.read())
        name = 'image'
        if hasattr(filename_or_handle, 'name'):
            name = filename_or_handle.name
        mediasource = gdata.MediaSource(file_handle, content_type,
            content_length=file_handle.len, file_name=name)
    else: #filename_or_handle is not valid
        raise GooglePhotosException({'status':GPHOTOS_INVALID_ARGUMENT,
            'body':'`filename_or_handle` must be a path name or a file-like object',
            'reason':'Found %s, not path name or object with a .read() method' % \
            type(filename_or_handle)
        })

    if isinstance(album_or_uri, (str, unicode)): # it's a uri
        feed_uri = album_or_uri
    elif hasattr(album_or_uri, 'GetFeedLink'): # it's a AlbumFeed object
        feed_uri = album_or_uri.GetFeedLink().href

    try:
        return self.Post(video, uri=feed_uri, media_source=mediasource,
            converter=None)
    except gdata.service.RequestError, e:
        raise GooglePhotosException(e.args[0])

gdata.photos.service.PhotosService.InsertVideo = InsertVideo

def OAuth2Login(client_secrets, credential_store, email):
    scope='https://picasaweb.google.com/data/'
    user_agent='picasawebuploader'

    storage = Storage(credential_store)
    credentials = storage.get()
    if credentials is None or credentials.invalid:
        flow = flow_from_clientsecrets(client_secrets, scope=scope, redirect_uri='urn:ietf:wg:oauth:2.0:oob')
        uri = flow.step1_get_authorize_url()
        webbrowser.open(uri)
        code = raw_input('Enter the authentication code: ').strip()
        credentials = flow.step2_exchange(code)

    if (credentials.token_expiry - datetime.utcnow()) < timedelta(minutes=5):
        http = httplib2.Http()
        http = credentials.authorize(http)
        credentials.refresh(http)

    storage.put(credentials)

    gd_client = gdata.photos.service.PhotosService(source=user_agent,
                                                   email=email,
                                                   additional_headers={'Authorization' : 'Bearer %s' % credentials.access_token})

    return gd_client

def protectWebAlbums(gd_client):
    albums = gd_client.GetUserFeed()
    for album in albums.entry:
        #print 'title: %s, number of photos: %s, id: %s summary: %s access: %s\n' % (album.title.text,
        # album.numphotos.text, album.gphoto_id.text, album.summary.text, album.access.text)
        needUpdate = False
        if album.access.text != 'protected' and album.title.text not in ['Auto Backup', 'Profile Photos', 'Scrapbook Photos']:
            album.access.text = 'protected'
            needUpdate = True
        # print album
        if needUpdate:
            print "Updating " + album.title.text
            try:
                updated_album = gd_client.Put(album, album.GetEditLink().href,
                        converter=gdata.photos.AlbumEntryFromString)
            except gdata.service.RequestError, e:
                print "Could not update album: " + str(e)

def getWebAlbums(gd_client):
    albums = gd_client.GetUserFeed()
    d = {}
    for album in albums.entry:
        title = album.title.text
        if title in d:
          print "Duplicate web album:" + title
        else:
          d[title] = album
        # print 'title: %s, number of photos: %s, id: %s' % (album.title.text,
        #    album.numphotos.text, album.gphoto_id.text)
        #print vars(album)
    return d

def findAlbum(gd_client, title):
    albums = gd_client.GetUserFeed()
    for album in albums.entry:
        if album.title.text == title:
            return album
    return None

def createAlbum(gd_client, title, dry_run):
    print "Creating album " + title
    # public, private, protected. private == "anyone with link"
    if dry_run:
        return None
    album = gd_client.InsertAlbum(title=title, summary='', access='protected')
    return album

def findOrCreateAlbum(gd_client, title, dry_run):
    delay = 1
    while True:
        try:
            album = findAlbum(gd_client, title)
            if not album:
                album = createAlbum(gd_client, title, dry_run)
            return album
        except gdata.photos.service.GooglePhotosException, e:
            print "Caught exception " + str(e)
            print "sleeping for " + str(delay) + " seconds"
            time.sleep(delay)
            delay = delay * 2

def getWebPhotosForAlbum(gd_client, album):
    total = int(album.numphotos.text)
    ret = 0
    start = 1
    p = []
    while start <= total:
        if total - start + 1 > PICASA_MAX_RET_ENTRY:
            ret = PICASA_MAX_RET_ENTRY
        else:
            ret = total - start + 1

        photos = gd_client.GetFeed(
                '/data/feed/api/user/%s/albumid/%s?kind=photo&start-index=%d&max-results=%d' % (
                gd_client.email, album.gphoto_id.text, start, ret))

        start += ret
        p += photos.entry

    if total != len(p):
        print ('Only %d photos retrieved from album %s, total %d' %
            (len(p), album.title.text, total))
    # else:
    #     print ('All %d photos retrieved in album %s' % (total, album.title.text))

    return p

allExtensions = {}

# key: extension, value: type
knownExtensions = {
    '.png': 'image/png',
    '.jpe': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.jpg': 'image/jpeg',
    '.tif': 'image/tiff',
    '.tiff': 'image/tiff',
    '.avi': 'video/avi',
    '.wmv': 'video/wmv',
    '.3gp': 'video/3gp',
    '.m4v': 'video/m4v',
    '.mp4': 'video/mp4',
    '.mov': 'video/mov'
    }

def getContentType(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in knownExtensions:
        return knownExtensions[ext]
    else:
        return None

def accumulateSeenExtensions(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in allExtensions:
        allExtensions[ext] = allExtensions[ext] + 1
    else:
        allExtensions[ext] = 1

def isMediaFilename(filename):
    accumulateSeenExtensions(filename)
    return getContentType(filename) != None

def visit(arg, dirname, names):
    basedirname = os.path.basename(dirname)
    if basedirname.startswith('.'):
        return
    mediaFiles = [name for name in names
                  if not name.startswith('.') and
                  isMediaFilename(name) and
                  os.path.isfile(os.path.join(dirname, name))]
    count = len(mediaFiles)
    if count <= 0:
        subdirs = [name for name in names
                   if not name.startswith('.') and
                   os.path.isdir(os.path.join(dirname, name))]
        if len(subdirs) <= 0:
            print ('No media in directory %s' % dirname)
    elif count <= PICASA_MAX_PICTURES_PER_ALBUM:
        arg[dirname] = {'files': sorted(mediaFiles)}
    else:
        print ('There are more than %d files(count %d) in directory %s, please split the directory' %
            (PICASA_MAX_PICTURES_PER_ALBUM, count, dirname))
        exit()

def findMedia(source):
    hash = {}
    os.path.walk(source, visit, hash)
    return hash

def findDupDirs(photos):
    d = {}
    for i in photos:
        base = os.path.basename(i)
        if base in d:
            print "Duplicate " + base + ":\n" + i + ":\n" + d[base]
            dc = filecmp.dircmp(i, d[base])
            print dc.diff_files
        d[base] = i
    # print [len(photos[i]['files']) for i in photos]

def toBaseName(photos):
    d = {}
    for i in photos:
        base = os.path.basename(i)
        if base in d:
            print "Duplicate " + base + ":\n" + i + ":\n" + d[base]['path']
#            raise Exception("duplicate base")
        p = photos[i]
        p['path'] = i
        d[base] = p
    return d

def compareLocalToWeb(local, web):
    localOnly = []
    both = []
    webOnly = []
    for i in local:
        if i in web:
            both.append(i)
        else:
            localOnly.append(i)
    for i in web:
        if i not in local:
            print ('Album is present only on the web: %s' % i)
            webOnly.append(i)
    print("localDir/webAlbums : {} / {}".format( len(local), len(web)))
    print("(localonly/both/webonly: {} / {} / {}".format ( len(localOnly), len(both), len(webOnly)))
    return {'localOnly' : localOnly, 'both' : both, 'webOnly' : webOnly}

def compareLocalToWebDir(localAlbum, webPhotoDict):
    localOnly = []
    both = []
    webOnly = []
    for i in localAlbum:
        if i in webPhotoDict:
            both.append(i)
        else:
            localOnly.append(i)
    for i in webPhotoDict:
        if i not in localAlbum:
            webOnly.append(i)
    return {'localOnly' : localOnly, 'both' : both, 'webOnly' : webOnly}

def syncDirs(gd_client, dirs, local, web, no_resize, dry_run):
    ii = 0
    for dir in dirs:
        ii = ii + 1
        print "Syncing: {} of {} {}".format( ii, len(dirs), dir )
        syncDir(gd_client, local[dir]['files'], local[dir]['path'], web[dir], no_resize, dry_run)

def syncDir(gd_client, afiles, apath, webAlbum, no_resize, dry_run):
  webPhotos = getWebPhotosForAlbum(gd_client, webAlbum)
  webPhotoDict = {}
  duplicated = []
  for photo in webPhotos:
    title = photo.title.text
    if title in webPhotoDict:
      print "Duplicate web photo: " + webAlbum.title.text + " " + title
      duplicated.append(photo)
    else:
      webPhotoDict[title] = photo

  # delete duplicated photos
  for photo in duplicated:
    title = photo.title.text
    print "Delete duplicate web photo: " + webAlbum.title.text + " " + title
#    gd_client.Delete(photo)

  # upload local only photos
  report = compareLocalToWebDir(afiles, webPhotoDict)
  localOnly = report['localOnly']
  for f in localOnly:
    localPath = os.path.join(apath, f)
    upload(gd_client, localPath, webAlbum, f, no_resize, dry_run)

def uploadDirs(gd_client, dirs, local, no_resize, dry_run):
    ii = 0
    for dir in dirs:
        ii = ii + 1
        print "Uploading: {} of {} {}".format( ii, len(dirs), dir )
        uploadDir(gd_client, dir, local[dir]['files'], local[dir]['path'], no_resize, dry_run)

def uploadDir(gd_client, dir, afiles, apath, no_resize, dry_run):
  webAlbum = findOrCreateAlbum(gd_client, dir or "Default", dry_run)
  for f in afiles:
    localPath = os.path.join(apath, f)
    upload(gd_client, localPath, webAlbum, f, no_resize, dry_run)

# Global used for a temp directory
gTempDir = ''

def getTempPath(localPath):
    baseName = os.path.basename(localPath)
    global gTempDir
    if gTempDir == '':
        gTempDir = tempfile.mkdtemp('imageshrinker')
    tempPath = os.path.join(gTempDir, baseName)
    return tempPath

def imageMaxDimension(path):
  output = subprocess.check_output(['gm', 'identify', '-format', '%w %h', path])
  lines = output.strip().split()
  w = int(lines[0])
  h = int(lines[1])
  return max(w,h)

def shrinkIfNeeded(path, maxDimension):
  if imageMaxDimension(path) > maxDimension:
    print "Shrinking " + path
    imagePath = getTempPath(path)
    subprocess.check_call(['gm', 'convert', '-resize', '%sX%s' % (maxDimension, maxDimension), path, imagePath])
    return imagePath
  return path

def imageMaxDimensionByPIL(path):
  img = Image.open(path)
  (w,h) = img.size
  return max(w,h)

def shrinkIfNeededByPIL(path, maxDimension):
    if imageMaxDimensionByPIL(path) > maxDimension:
        print "Shrinking " + path
        imagePath = getTempPath(path)
        img = Image.open(path)
        (w,h) = img.size
        if (w>h):
            img2 = img.resize((maxDimension, (h*maxDimension)/w), Image.ANTIALIAS)
        else:
            img2 = img.resize(((w*maxDimension)/h, maxDimension), Image.ANTIALIAS)
        img2.save(imagePath, 'JPEG', quality=99)

        # now copy EXIF data from original to new
        #src_image = pyexiv2.ImageMetadata(path)
        #src_image.read()
        #dst_image = pyexiv2.ImageMetadata(imagePath)
        #dst_image.read()
        #src_image.copy(dst_image, exif=True)
        ## overwrite image size based on new image
        #dst_image["Exif.Photo.PixelXDimension"] = img2.size[0]
        #dst_image["Exif.Photo.PixelYDimension"] = img2.size[1]
        #dst_image.write()

        return imagePath
    return path

def upload(gd_client, localPath, album, fileName, no_resize, dry_run):
    print "Uploading " + localPath
    if dry_run:
        return

    contentType = getContentType(fileName)

    if contentType.startswith('image/'):
        if no_resize:
            imagePath = localPath
        else:
            imagePath = shrinkIfNeeded(localPath, PICASA_MAX_FREE_IMAGE_DIMENSION)

        isImage = True
        picasa_photo = gdata.photos.PhotoEntry()
    else:
        size = os.path.getsize(localPath)

        # tested by cpbotha on 2013-05-24
        # this limit still exists
        if size > PICASA_MAX_VIDEO_SIZE_BYTES:
            print "## Video file too big to upload: " + str(fileName) + " : " + str(size) + " > " + str(PICASA_MAX_VIDEO_SIZE_BYTES)
            return
        imagePath = localPath
        isImage = False
        picasa_photo = VideoEntry()
    picasa_photo.title = atom.Title(text=fileName)
    picasa_photo.summary = atom.Summary(text='', summary_type='text')
    delay = 1
    while True:
        try:
            if isImage:
                gd_client.InsertPhoto(album, picasa_photo, imagePath, content_type=contentType)
            else:
                gd_client.InsertVideo(album, picasa_photo, imagePath, content_type=contentType)
            break
        except gdata.photos.service.GooglePhotosException, e:
          print "Got exception " + str(e)
          print "retrying in " + str(delay) + " seconds"
          time.sleep(delay)
          delay = delay * 2

    # delete the temp file that was created if we shrank an image:
    if imagePath != localPath:
        os.remove(imagePath)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Upload pictures to picasa web albums / Google+.')
    parser.add_argument('--email', help='the google account email to use (example@gmail.com)', required=True)
    parser.add_argument('--source', help='the directory to upload', required=True)
    parser.add_argument(
          '--no-resize',
          help="Do not resize images, i.e., upload photos with original size.",
          action='store_true')
    parser.add_argument('--dry-run', help='take no action, just print steps', action='store_true')

    args = parser.parse_args()

    if args.no_resize:
        print "*** Images will be uploaded at original size."

    else:
        print "*** Images will be resized to 2048 pixels."

    email = args.email

    # options for oauth2 login
    configdir = os.path.expanduser('~/.config/picasawebuploader')
    client_secrets = os.path.join(configdir, 'client_secrets.json')
    credential_store = os.path.join(configdir, 'credentials.dat')

    gd_client = OAuth2Login(client_secrets, credential_store, email)
    #protectWebAlbums(gd_client)
    webAlbums = getWebAlbums(gd_client)
    localAlbums = toBaseName(findMedia(args.source))
    albumDiff = compareLocalToWeb(localAlbums, webAlbums)
    syncDirs(gd_client, albumDiff['both'], localAlbums, webAlbums, args.no_resize, args.dry_run)
    uploadDirs(gd_client, albumDiff['localOnly'], localAlbums, args.no_resize, args.dry_run)
