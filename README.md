# q_catalog_ws
Simple demo web app using python, asyncio, sqlalchemy, flask, flask-admin, websockets, hypercorn all together.

It shows how to use [Flask](https://flask.palletsprojects.com) (and its rich framework) with 
an [ASGI](https://asgi.readthedocs.io/en/latest/) http server exploiting the full power of 
asyncio for total parallelization, e.g., in websockets communication, http requests, etc.

This is not packed up as a python wheel, so:

* clone the repo, 
* install the requirements (in a virtualenv) **pip install flask_sqlalchemy websockets hypercorn flask_admin**,
* run **python3 application.py**, 
* open the browser at **http:*localhost*:5005**

