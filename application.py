# coding: utf-8

# pylint: disable=missing-docstring
# pylint: disable=line-too-long
# pylint: disable=invalid-name
# pylint: disable=broad-except
# pylint: disable=too-few-public-methods
# pylint: disable=logging-format-interpolation, consider-using-f-string, logging-fstring-interpolation

import os
import traceback
import time
import logging
import asyncio
import signal
import json
import random
import csv
import uuid
# ~ import concurrent.futures

from types import SimpleNamespace

import hypercorn.config  # pylint: disable=import-error
import hypercorn.asyncio  # pylint: disable=import-error

from flask_sqlalchemy import SQLAlchemy  # pylint: disable=import-error

from flask import Flask, Markup, render_template  # pylint: disable=import-error
from flask.views import View  # pylint: disable=import-error
from flask_admin import AdminIndexView, Admin  # pylint: disable=import-error
from flask_admin.contrib.sqla import ModelView  # pylint: disable=import-error

import websockets  # pylint: disable=import-error

HTTP_HOST = '0.0.0.0'
HTTP_PORT = 5005
WS_HOST = '0.0.0.0'
WS_PORT = 5006

here = os.path.dirname(os.path.abspath(__file__))

DATA_PATH = os.path.join(here, "data")
DB_FILENAME = "catalog.02.sqlite"

SECRET_KEY = os.environ.get('Q_CATALOG_SECRET_KEY', 'development key')
LOG_LEVEL = os.environ.get('Q_CATALOG_LOG_LEVEL', 'WARNING')

CHUNK_SIZE_BYTES = 128 * 1024
CSV_ENCODING = "utf-8"
CSV_DELIMITER = ","
CSV_QUOTECHAR = '"'
CSV_ENDLINE = '\n'

db__ = SQLAlchemy()

def set_logging(log_level):
    fmt_ = logging.Formatter('[%(asctime)s]'
                             # ~ '%(name)s:'
                             '%(levelname)s:'
                             '%(funcName)s() '
                             '%(filename)s:'
                             '%(lineno)d: '
                             '%(message)s ')

    ch = logging.StreamHandler()
    ch.setFormatter(fmt_)
    logger_ = logging.getLogger()
    logger_.handlers = []
    logger_.addHandler(ch)
    logger_.setLevel(log_level)


def init_db(flask_app):

    db__.init_app(flask_app)

    flask_app.db = db__

    with flask_app.app_context():
        db__.create_all()
        db__.session.commit()  # pylint: disable=no-member
        logging.warning(f"db initialized. {db__}")


def init_views(flask_app):

    class FileTransfer(View):

        def __init__(self):

            self.template = 'index.html'
            self.context = dict(
                ws_url=f"ws://{WS_HOST}:{WS_PORT}",
                chunk_size_bytes=CHUNK_SIZE_BYTES,
                csv_encoding=CSV_ENCODING,
                csv_delimiter=CSV_DELIMITER,
                csv_quotechar=CSV_QUOTECHAR,
            )

        def dispatch_request(self):

            logging.info(f"pid:{os.getpid()}")
            return render_template(self.template, **self.context)


    # ~ admin = Admin(flask_app, index_view=AdminIndexView())
    # ~ admin.add_view(CatalogView(Catalog, app.flask_app.db.session))

    admin = Admin(flask_app, index_view=AdminIndexView())
    admin.add_view(CatalogView(Catalog, flask_app.db.session))

    flask_app.add_url_rule("/", view_func=FileTransfer.as_view("/index"))

    return admin


def generate_id():

    return str(uuid.uuid4())

class Catalog(db__.Model):

    __tablename__ = 'catalog'

    db = db__

    Id = db.Column(db.Unicode, primary_key=True, nullable=False, default=generate_id)
    Name = db.Column(db.Unicode, nullable=False)
    Price = db.Column(db.Unicode, nullable=False)

    # ~ properties = db.Column(db.Unicode, default='{}')

    @classmethod
    def store_csv_row(cls, row, db_session, do_commit=False):

        new_cntr = 0
        mod_cntr = 0
        err_cntr = 0
        try:
            old_c = None
            if row.get('Id') is not None:
                old_Id = row.pop('Id')
                q = db_session.query(cls)  # pylint: disable=no-member
                old_c = q.filter_by(Id=old_Id).first()
            if old_c:
                for k, v in row.items():
                    setattr(old_c, k, v)
                # ~ old_c.update(row)
                if do_commit:
                    db_session.commit()  # pylint: disable=no-member

                mod_cntr += 1
            else:
                c = cls(**row)
                db_session.add(c)  # pylint: disable=no-member
                if do_commit:
                    db_session.commit()  # pylint: disable=no-member

                new_cntr += 1

        except Exception as e:
            err_cntr += 1
            if do_commit:
                db_session.rollback()  # pylint: disable=no-member
            logging.error(f"{e}")

        return new_cntr, mod_cntr, err_cntr



class CatalogView(ModelView):

    can_view_details = True
    can_export = True
    export_max_rows = 10 * 1000
    export_types = ['csv', ]

    # ~ column_exclude_list = ('id', )
    column_list = ('id', 'Name', 'Price')

class WSinstance:

    def __init__(self, websocket, path, parent):

        self.websocket = websocket
        self.path = path
        self.parent = parent

        self.status = 'IDLE'
        self.pre_paused_status = self.status
        self.background_tasks = set()

        self.file = SimpleNamespace(
            name=None,
            size=0,
            byte_cntr=0,
            line_cntr=0,
            chunk_cntr=0)

    async def __pause(self):

        while self.status in ('PAUSE'):
            await asyncio.sleep(.1)

    async def __dump_from_csv_file_to_db(self):  # pylint: disable=too-many-locals

        t0 = time.time()
        new_cntr = 0
        mod_cntr = 0
        err_cntr = 0
        row_cntr = 0
        f_pth = os.path.join(DATA_PATH, self.file.file_name)
        with self.parent.appplication.flask_app.app_context():
            with open(f_pth, encoding=CSV_ENCODING) as f:

                csv_reader = csv.DictReader(f, delimiter=CSV_DELIMITER, quotechar=CSV_QUOTECHAR)
                db_session = self.parent.appplication.flask_app.db.session

                for row in csv_reader:

                    await asyncio.sleep(.0001) # let the context switch

                    if self.status in ('PAUSE'):
                        await self.__pause()
                    elif self.status in ('STOP'):
                        break

                    new_cntr_, mod_cntr_, err_cntr_ = Catalog.store_csv_row(row, db_session, do_commit=True)

                    new_cntr += new_cntr_
                    mod_cntr += mod_cntr_
                    err_cntr += err_cntr_
                    row_cntr += 1

                    dt = time.time() - t0
                    if row_cntr % 100 == 0:
                        pld_ = f"{self.status}<br/>"
                        pld_ = f"{new_cntr} new and {mod_cntr} modified records, {err_cntr} errors. <br/>dt:{round(dt, 1)}  (s)..."
                        msg_ = {'type': 'record_stored_ack', 'payload': Markup(pld_), 'target': 'db_dump_msg'}

                        await self.send_message(msg_)

                        logging.debug(msg_)

        return (new_cntr, mod_cntr, err_cntr, row_cntr)

    async def send_message(self, message: dict) -> None:

        _ = json.dumps(message)
        await self.websocket.send(_)

    async def handle_message(self, message: dict) -> None:

        logging.info(f"self.status:{self.status}, message:{message}."[:300])

        type_ = message.get('type')
        payload = message.get('payload')

        if type_ == "txt":
            pld = f"{random.choice(('OK', 'NOK', '-'))} [{time.asctime()}]"
            answer = {"type": "generic_ack", "payload": Markup(pld), 'target': 'generic_msg'}

        elif type_ == "start_file_upload":
            answer = await self.START_FILE_UPLOAD(payload)
        elif type_ == "upload_chunk":
            answer = await self.UPLOAD_CHUNK(payload)
        elif type_ == "file_uploaded":
            answer = await self.FILE_UPLOADED(payload)
        elif type_ == "pause":
            answer = await self.PAUSE(payload)
        elif type_ == "stop":
            answer = await self.STOP(payload)

        await self.send_message(answer)

    async def PAUSE(self, payload: dict) -> dict:  # pylint: disable=unused-argument

        if self.status in ('PAUSE'):
            self.status = self.pre_paused_status
        else:
            self.pre_paused_status = self.status
            self.status = 'PAUSE'

        answer = {"type": "generic_ack", "payload": f"OK status:{self.status}", 'target': 'generic_msg'}
        return answer

    async def STOP(self, payload: dict) -> dict:  # pylint: disable=unused-argument

        self.status = 'IDLE'
        answer = {"type": "generic_ack", "payload": 'OK', 'target': 'generic_msg'}
        return answer

    async def START_FILE_UPLOAD(self, payload: dict) -> dict:

        if self.status in ('IDLE', ):
            self.status = 'FILE_UPLOAD'
            self.file.file_size = payload.get('file_size')
            self.file.file_name = payload.get('file_name')
            self.file.byte_cntr = 0
            self.file.line_cntr = 0
            self.file.chunk_cntr = 0

            f_pth = os.path.join(DATA_PATH, self.file.file_name)
            with open(f_pth, 'w', encoding=CSV_ENCODING):
                pass
            msg_ = Markup(f"{payload}")
        else:
            msg_ = Markup(f"ERR: {self.status} not allowed.")

        answer = {"type": "start_file_upload_ack", "payload": msg_, 'target': 'xfer_file_msg'}

        return answer

    async def UPLOAD_CHUNK(self, payload: dict) -> dict:

        if self.status in ('FILE_UPLOAD', ):

            chunk_ = payload.get('chunk', '')
            self.file.byte_cntr  += len(chunk_)
            self.file.line_cntr  += chunk_.count(CSV_ENDLINE)
            self.file.chunk_cntr += 1

            if chunk_:

                f_pth = os.path.join(DATA_PATH, self.file.file_name)
                with open(f_pth, 'a', encoding=CSV_ENCODING) as f:
                    f.write(chunk_)

            msg_ = f"{self.file.byte_cntr}/{self.file.file_size} bytes, "
            msg_ += f"{self.file.line_cntr } lines, "
            msg_ += f"{self.file.chunk_cntr} chunks transferred."
            if self.file.byte_cntr >= self.file.file_size:
                msg_ = 'OK ' + msg_+ " FILE_UPLOADED."

            msg_ = Markup(msg_)
        else:
            msg_ = Markup(f"ERR: {self.status} not allowed.")

        answer = {"type": "upload_chunk_ack", "payload": msg_, 'target': 'xfer_file_msg'}
        return answer

    async def FILE_UPLOADED(self, payload: dict) -> dict:  # pylint: disable=unused-argument

        if self.status in ('FILE_UPLOAD', ):

            self.status = 'DUMP_FILE_TO_DB'

            t0 = time.time()
            result = await self.__dump_from_csv_file_to_db()
            new_cntr, mod_cntr, err_cntr, row_cntr = result

            msg_ = f"new_cntr:{new_cntr}, mod_cntr:{mod_cntr}, err_cntr:{err_cntr}, row_cntr:{row_cntr}"
            msg_ += f"<br/>file stored. dt:{round(time.time() - t0, 1)} (s)"
            msg_ = Markup(msg_)

            logging.info(msg_)

            self.status = 'IDLE'

        else:

            msg_ = Markup(f"ERR: {self.status} not allowed.")

        answer = {"type": "file_uploaded_ack", "payload": msg_, 'target': 'db_dump_msg'}

        return answer


class WSserver:

    def __init__(self, appplication, host, port):

        self.appplication = appplication
        self.host = host
        self.port = port

        self.ws_instances = {}

    async def new_client_handler(self, websocket, path):
        try:
            logging.info(f"appending instance. websocket:{websocket}, path:{path}, pid:{os.getpid()}.")

            ws_instance = WSinstance(websocket, path, parent=self)
            self.ws_instances[websocket] = ws_instance
            async for message in websocket:  # start listening for messages from ws client
                try:
                    message = json.loads(message)
                    task = asyncio.create_task(ws_instance.handle_message(message))

                    # Add task to the set. This creates a strong reference.
                    ws_instance.background_tasks.add(task)

                    # To prevent keeping references to finished tasks forever,
                    # make each task remove its own reference from the set after
                    # completion:
                    def _done_callback(tsk_):
                        if self.ws_instances.get(websocket):
                            self.ws_instances[websocket].background_tasks.discard(tsk_)
                    task.add_done_callback(_done_callback)

                except websockets.exceptions.ConnectionClosedOK:
                    logging.info("")
                except websockets.exceptions.ConnectionClosedError:
                    logging.warning("")

        except BaseException:
            logging.error(traceback.format_exc())
        finally:
            if websocket in self.ws_instances:
                logging.info("removing instance. websocket:{}, path:{}.".format(websocket, path))
                self.ws_instances.pop(websocket)

    def run(self):

        asyncio.ensure_future(websockets.serve(self.new_client_handler, self.host, self.port))


class Application:

    def __init__(self, data_path, db_filename, host, port):

        self.host = host
        self.port = port
        self.db_filename = db_filename
        self.data_path = data_path

        flask_app_config = dict(
            DEBUG=True,
            SQLALCHEMY_DATABASE_URI=f'sqlite:///{data_path}/{db_filename}',
            SECRET_KEY=SECRET_KEY)

        self.__version__ = None

        os.makedirs(data_path, exist_ok=True)

        _here = os.path.dirname(os.path.abspath(__file__))
        self.flask_app = Flask(__name__, template_folder=os.path.join(_here, "templates"))
        self.flask_app.config.update(flask_app_config)

        init_db(self.flask_app)

        init_views(self.flask_app)

        logging.info(f"{__name__} ver.:{self.version}")

    @property
    def version(self):

        if self.__version__ is None:
            _here = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(_here, 'VERSION'), encoding='utf-8') as version_file:
                self.__version__ = version_file.read().strip()

        return self.__version__

    def run_until_complete(self):

        hypercorn_config = hypercorn.config.Config()
        hypercorn_config.bind = f"{self.host}:{self.port}"
        hypercorn_config.loglevel = LOG_LEVEL

        shutdown_event = asyncio.Event()

        def _signal_handler(*_):
            shutdown_event.set()
        asyncio.get_event_loop().add_signal_handler(signal.SIGTERM, _signal_handler)
        asyncio.get_event_loop().add_signal_handler(signal.SIGINT, _signal_handler)

        coro = hypercorn.asyncio.serve(self.flask_app, hypercorn_config, shutdown_trigger=shutdown_event.wait)
        asyncio.get_event_loop().run_until_complete(coro)

        logging.warning("exiting... ")


def main():

    set_logging(LOG_LEVEL)

    app = Application(data_path=DATA_PATH, db_filename=DB_FILENAME, host=HTTP_HOST, port=HTTP_PORT)
    ws = WSserver(appplication=app, host=WS_HOST, port=WS_PORT)
    ws.run()
    app.run_until_complete()


if __name__ == "__main__":
    main()
