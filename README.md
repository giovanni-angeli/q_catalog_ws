# q_catalog
Simple demo web app using Flask-admin, sqlalchemy, socketio.

this is not packed up as a python wheel, so:

* clone the repo, 
* install the requirements (in a virtualenv) **pip install flask_sqlalchemy flask_socketio flask_admin**,
* run **python server.py**, 
* open the browser at **http:*localhost*:5000**

this is just a P.O.C so there are many
### Possible Improvements:

use an ASGI http server, e.g. [hypercorn](https://pypi.org/project/hypercorn/) or [uvicorn](https://www.uvicorn.org/)
(see this as an example: [merp](https://github.com/giovanni-angeli/merp))

#### Security

* Use HTTPS in the communication.
* Authentication and Authorization: only authorized users can upload or download files.
* Server-Side Validation on each uploaded chunk to ensure its integrity (e.g., SHA256).
* Rate Limiting to prevent abuse and protect.

#### Usability/availability
 
* periodic cleaning of temporary files eventually left over.
* change the db backend for a real multi-user deploy, e.g from file-based sqlite to a pg server
* add a policy of table pagination/rotation to avoid the db table to grow undefinitely
* design a user friendly HTML interface 
* zip data on client and unzip on server

#### Test

* add a test suite based on a client impelemented in python

### Possible Optimizations:

* store records in the db in 'bulk' not record-by-record.
* build chunks on client by rows and store them in db on server on the fly i.e. without saving file on disk.
* recover of interrupted sessions.

### Possible Variations:

* allow the users to upload the csv files in batch mode, e.g. email-ing or ftp-ing them and receiveing a confirmation email report off-line.
* use websockets python module instead of socketio

