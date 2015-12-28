picasawebuploader
=================

A script that uploads photos to Google Photos / Google+ / Picasa Web Albums

+ Resizes large images to be less than the free limit (2048 x 2048)
+ Uploads all directories under a given directory
+ restartable
+ Creates the albums as "protected"
+ Automatically retries when Google data service errors out.

To Do
-----

+ Use multiple threads for uploading.
+ Add Progress UI
+ Deal with duplicate picture and folder names, both on local and web collections.
  + Currently we just throw an exception when we detect duplicate names.
+ Deal with 'Error: 17 REJECTED_USER_LIMIT' errors.

Installation
------------

+ Prerequisites:
  + Python 2.7
  + Google Data APIs http://code.google.com/apis/gdata/
    + gdata-2.0.16 for Python
  + The PIL library for Python or BSD "sips" image processing program.
	+ PIL is available on most UNIX like systems.
    + "sips" comes pre-installed on OSX.
  + pyexiv2 module for writing correct EXIF data

Authentication
--------------

You need to use OAuth2 for authentication. Here is how to set it up:

1. First create a project through the Google Developer Console: at https://console.developers.google.com/
2. Under that project, create a new Client ID of type "Installed Application" under APIs & auth -> Credentials
3. Once the Client ID has been created you should click "Download JSON" and save the file as $HOME/.config/picasawebuploader/client_secrets.json (you can change the location in main.py)

The first time you run the application you will be asked to authorize your application through your web browser. Once you do this you will get a code which you have to copy and paste into the application.

You're done.

Known Problems
--------------

Picasa Web Albums appears to have an undocumented upload quota system that
limits uploads to a certain number of bytes per month.

Do a web search for REJECTED_USER_LIMIT to see the various discussions about
this. From reading the web forums it appears that the upload quota is reset
occasionally (possibly monthly). If you start getting REJECTED_USER_LIMIT
errors when you run this script you may have to wait a month to upload new
pictures.

Some people have reported that paying for yearly web storage will remove the
upload quota.
