#
# lightweight http server for MicroPython IOT things.
#

__author__ = 'J. B. Otterson'
__copyright__ = """
Copyright 2022, J. B. Otterson N1KDO.
Redistribution and use in source and binary forms, with or without modification, 
are permitted provided that the following conditions are met:
  1. Redistributions of source code must retain the above copyright notice, 
     this list of conditions and the following disclaimer.
  2. Redistributions in binary form must reproduce the above copyright notice, 
     this list of conditions and the following disclaimer in the documentation 
     and/or other materials provided with the distribution.
THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND 
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,
INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, 
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE 
OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED
OF THE POSSIBILITY OF SUCH DAMAGE.
"""
__version__ = '0.9.0'

import gc
import json
import os
import re

from utils import milliseconds, safe_int, upython
if upython:
    import micro_logging as logging
else:
    import logging


class HttpServer:
    BUFFER_SIZE = 4096
    CT_TEXT_TEXT = 'text/text'
    CT_TEXT_HTML = 'text/html'
    CT_APP_JSON = 'application/json'
    CT_APP_WWW_FORM = 'application/x-www-form-urlencoded'
    CT_MULTIPART_FORM = 'multipart/form-data'

    FILE_EXTENSION_TO_CONTENT_TYPE_MAP = {
        'gif': 'image/gif',
        'html': CT_TEXT_HTML,
        'ico': 'image/vnd.microsoft.icon',
        'json': CT_APP_JSON,
        'jpeg': 'image/jpeg',
        'jpg': 'image/jpeg',
        'png': 'image/png',
        'txt': CT_TEXT_TEXT,
        '*': 'application/octet-stream',
    }
    HYPHENS = '--'
    HTTP_STATUS_TEXT = {
        200: 'OK',
        201: 'Created',
        202: 'Accepted',
        204: 'No Content',
        301: 'Moved Permanently',
        302: 'Moved Temporarily',
        304: 'Not Modified',
        400: 'Bad Request',
        401: 'Unauthorized',
        403: 'Forbidden',
        404: 'Not Found',
        409: 'Conflict',
        500: 'Internal Server Error',
        501: 'Not Implemented',
        502: 'Bad Gateway',
        503: 'Service Unavailable',
    }
    MP_START_BOUND = 1
    MP_HEADERS = 2
    MP_DATA = 3
    MP_END_BOUND = 4

    DANGER_ZONE_FILE_NAMES = [
        'config.html',
        'files.html',
    ]

    def __init__(self, content_dir):
        self.content_dir = content_dir
        self.uri_map = {}
        self.buffer = bytearray(self.BUFFER_SIZE)

    def add_uri_callback(self, uri, callback):
        self.uri_map[uri] = callback

    def serve_content(self, writer, filename):
        filename = self.content_dir + filename
        try:
            content_length = os.stat(filename)[6]
            content_length = safe_int(content_length, -1)
        except OSError:
            content_length = -1
        if content_length < 0:
            response = b'<html><body><p>404 -- File not found.</p></body></html>'
            http_status = 404
            return self.send_simple_response(writer, http_status, self.CT_TEXT_HTML, response), http_status
        extension = filename.split('.')[-1]
        content_type = self.FILE_EXTENSION_TO_CONTENT_TYPE_MAP.get(extension)
        if content_type is None:
            content_type = self.FILE_EXTENSION_TO_CONTENT_TYPE_MAP.get('*')
        http_status = 200
        self.start_response(writer, 200, content_type, content_length)
        try:
            with open(filename, 'rb', self.BUFFER_SIZE) as infile:
                while True:
                    buffer = infile.read(self.BUFFER_SIZE)
                    writer.write(buffer)
                    if len(buffer) < self.BUFFER_SIZE:
                        break
        except Exception as exc:
            logging.error('{type(exc)} {exc}', 'http_server:serve_content')
        return content_length, http_status

    def start_response(self, writer, http_status=200, content_type=None, response_size=0, extra_headers=None):
        status_text = self.HTTP_STATUS_TEXT.get(http_status) or 'Confused'
        protocol = 'HTTP/1.0'
        writer.write(f'{protocol} {http_status} {status_text}\r\n'.encode('utf-8'))
        writer.write('Access-Control-Allow-Origin: *\n'.encode('utf-8'))  # CORS override
        if content_type is not None and len(content_type) > 0:
            writer.write(f'Content-type: {content_type}; charset=UTF-8\r\n'.encode('utf-8'))
        if response_size > 0:
            writer.write(f'Content-length: {response_size}\r\n'.encode('utf-8'))
        if extra_headers is not None:
            for header in extra_headers:
                writer.write(f'{header}\r\n'.encode('utf-8'))
        writer.write(b'\r\n')

    def send_simple_response(self, writer, http_status=200, content_type=None, response=None, extra_headers=None):
        content_length = len(response) if response else 0
        self.start_response(writer, http_status, content_type, content_length, extra_headers)
        if response is not None and len(response) > 0:
            writer.write(response)
        return content_length

    @classmethod
    def unpack_args(cls, value):
        args_dict = {}
        if value is not None:
            args_list = value.split('&')
            for arg in args_list:
                arg_parts = arg.split('=')
                if len(arg_parts) == 2:
                    args_dict[arg_parts[0]] = arg_parts[1]
        return args_dict

    async def serve_http_client(self, reader, writer):
        t0 = milliseconds()
        http_status = 418  # can only make tea, sorry.
        bytes_sent = 0
        partner = writer.get_extra_info('peername')[0]
        logging.debug(f'web client connected from {partner}', 'http_server:serve_http_client')
        request_line = await reader.readline()
        request = request_line.decode().strip()
        logging.debug(f'request: {request}', 'http_server:serve_http_client')
        pieces = request.split(' ')
        if len(pieces) != 3:  # does the http request line look approximately correct?
            http_status = 400
            response = b'Bad Request !=3'
            bytes_sent = self.send_simple_response(writer, http_status, self.CT_TEXT_HTML, response)
        else:
            verb = pieces[0]
            target = pieces[1]
            protocol = pieces[2]
            # should validate protocol here...
            if '?' in target:
                pieces = target.split('?')
                target = pieces[0]
                query_args = pieces[1]
            else:
                query_args = ''
            if verb not in ['GET', 'POST']:
                http_status = 400
                response = b'<html><body><p>only GET and POST are supported</p></body></html>'
                bytes_sent = self.send_simple_response(writer, http_status, self.CT_TEXT_HTML, response)
            elif protocol not in ['HTTP/1.0', 'HTTP/1.1']:
                http_status = 400
                response = b'that protocol is not supported'
                bytes_sent = self.send_simple_response(writer, http_status, self.CT_TEXT_HTML, response)
            else:
                # get HTTP request headers
                request_content_length = 0
                request_content_type = ''
                request_headers = {}
                while True:
                    header = await reader.readline()
                    if len(header) == 0:
                        # empty header line, eof?
                        break
                    if header == b'\r\n':
                        # blank line at end of headers
                        break
                    # process headers.  look for those we are interested in.
                    parts = header.decode().strip().split(':', 1)
                    header_name = parts[0].strip()
                    header_value = parts[1].strip()
                    request_headers[header_name] = header_value
                    if header_name == 'Content-Length':
                        request_content_length = int(header_value)
                    elif header_name == 'Content-Type':
                        request_content_type = header_value

                args = {}
                if verb == 'GET':
                    args = self.unpack_args(query_args)
                elif verb == 'POST':
                    if request_content_length > 0:
                        if request_content_type == self.CT_APP_WWW_FORM:
                            data = await reader.read(request_content_length)
                            args = self.unpack_args(data.decode())
                        elif request_content_type == self.CT_APP_JSON:
                            data = await reader.read(request_content_length)
                            args = json.loads(data.decode())
                        elif not request_content_type.startswith('multipart/form-data;'):
                            logging.warning(f'warning: unhandled content_type {request_content_type}',
                                            'http_server:serve_http_client')
                            logging.warning(f'request_content_length={request_content_length}',
                                            'http_server:serve_http_client')
                else:  # bad request
                    http_status = 400
                    response = b'only GET and POST are supported'
                    logging.warning(response, 'http_server:serve_http_client')
                    bytes_sent = self.send_simple_response(writer, http_status, self.CT_TEXT_TEXT, response)

                if verb in ('GET', 'POST'):
                    callback = self.uri_map.get(target)
                    if callback is not None:
                        bytes_sent, http_status = await callback(self, verb, args, reader, writer, request_headers)
                    else:
                        content_file = target[1:] if target[0] == '/' else target
                        bytes_sent, http_status = self.serve_content(writer, content_file)

        await writer.drain()
        writer.close()
        await writer.wait_closed()
        elapsed = milliseconds() - t0
        if http_status == 200:
            logging.info(f'{partner} {request} {http_status} {bytes_sent} {elapsed} ms',
                         'http_server:serve_http_client')
        else:
            logging.info(f'{partner} {request} {http_status} {bytes_sent} {elapsed} ms',
                         'http_server:serve_http_client')
        gc.collect()

#
# common file operations callbacks, here because just about every app will use them...
#


def valid_filename(filename):
    if filename is None:
        return False
    match = re.match('^[a-zA-Z0-9](?:[a-zA-Z0-9._-]*[a-zA-Z0-9])?.[a-zA-Z0-9_-]+$', filename)
    if match is None:
        return False
    if match.group(0) != filename:
        return False
    extension = filename.split('.')[-1].lower()
    if HttpServer.FILE_EXTENSION_TO_CONTENT_TYPE_MAP.get(extension) is None:
        return False
    return True


def file_size(filename):
    try:
        return os.stat(filename)[6]
    except OSError:
        return -1


# noinspection PyUnusedLocal
async def api_get_files_callback(http, verb, args, reader, writer, request_headers=None):
    if verb == 'GET':
        payload = os.listdir(http.content_dir)
        response = json.dumps(payload).encode('utf-8')
        http_status = 200
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    else:
        http_status = 400
        response = b'only GET permitted'
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_upload_file_callback(http, verb, args, reader, writer, request_headers=None):
    if verb == 'POST':
        boundary = None
        request_content_type = request_headers.get('Content-Type') or ''
        if ';' in request_content_type:
            pieces = request_content_type.split(';')
            request_content_type = pieces[0]
            boundary = pieces[1].strip()
            if boundary.startswith('boundary='):
                boundary = boundary[9:]
        if request_content_type != http.CT_MULTIPART_FORM or boundary is None:
            response = b'multipart boundary or content type error'
            http_status = 400
        else:
            response = b'unhandled problem'
            http_status = 500
            request_content_length = int(request_headers.get('Content-Length') or '0')
            remaining_content_length = request_content_length
            logging.info(f'upload content length {request_content_length}', 'main:api_upload_file_callback')
            start_boundary = http.HYPHENS + boundary
            end_boundary = start_boundary + http.HYPHENS
            state = http.MP_START_BOUND
            filename = None
            output_file = None
            writing_file = False
            more_bytes = True
            leftover_bytes = []
            while more_bytes:
                buffer = await reader.read(HttpServer.BUFFER_SIZE)
                remaining_content_length -= len(buffer)
                if remaining_content_length == 0:  # < BUFFER_SIZE:
                    more_bytes = False
                if len(leftover_bytes) != 0:
                    buffer = leftover_bytes + buffer
                    leftover_bytes = []
                start = 0
                while start < len(buffer):
                    if state == http.MP_DATA:
                        if not output_file:
                            output_file = open(http.content_dir + 'uploaded_' + filename, 'wb')
                            writing_file = True
                        end = len(buffer)
                        for i in range(start, len(buffer) - 3):
                            if buffer[i] == 13 and buffer[i + 1] == 10 and buffer[i + 2] == 45 and \
                                    buffer[i + 3] == 45:
                                end = i
                                writing_file = False
                                break
                        if end == HttpServer.BUFFER_SIZE:
                            if buffer[-1] == 13:
                                leftover_bytes = buffer[-1:]
                                buffer = buffer[:-1]
                                end -= 1
                            elif buffer[-2] == 13 and buffer[-1] == 10:
                                leftover_bytes = buffer[-2:]
                                buffer = buffer[:-2]
                                end -= 2
                            elif buffer[-3] == 13 and buffer[-2] == 10 and buffer[-1] == 45:
                                leftover_bytes = buffer[-3:]
                                buffer = buffer[:-3]
                                end -= 3
                        output_file.write(buffer[start:end])
                        if not writing_file:
                            state = http.MP_END_BOUND
                            output_file.close()
                            output_file = None
                            response = f'Uploaded {filename} successfully'.encode('utf-8')
                            http_status = 201
                        start = end + 2
                    else:  # must be reading headers or boundary
                        line = ''
                        for i in range(start, len(buffer) - 1):
                            if buffer[i] == 13 and buffer[i + 1] == 10:
                                line = buffer[start:i].decode('utf-8')
                                start = i + 2
                                break
                        if state == http.MP_START_BOUND:
                            if line == start_boundary:
                                state = http.MP_HEADERS
                            else:
                                logging.error(f'expecting start boundary, got {line}', 'main:api_upload_file_callback')
                        elif state == http.MP_HEADERS:
                            if len(line) == 0:
                                state = http.MP_DATA
                            elif line.startswith('Content-Disposition:'):
                                pieces = line.split(';')
                                fn = pieces[2].strip()
                                if fn.startswith('filename="'):
                                    filename = fn[10:-1]
                                    if not valid_filename(filename):
                                        response = b'bad filename'
                                        http_status = 500
                                        more_bytes = False
                                        start = len(buffer)
                        elif state == http.MP_END_BOUND:
                            if line == end_boundary:
                                state = http.MP_START_BOUND
                            else:
                                logging.error(f'expecting end boundary, got {line}', 'main:api_upload_file_callback')
                        else:
                            http_status = 500
                            response = f'unmanaged state {state}'.encode('utf-8')
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    else:
        response = b'PUT only.'
        http_status = 400
        bytes_sent = http.send_simple_response(writer, http_status, http.CT_TEXT_TEXT, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_remove_file_callback(http, verb, args, reader, writer, request_headers=None):
    filename = args.get('filename')
    if valid_filename(filename) and filename not in HttpServer.DANGER_ZONE_FILE_NAMES:
        filename = http.content_dir + filename
        try:
            os.remove(filename)
            http_status = 200
            response = f'removed {filename}'.encode('utf-8')
        except OSError as ose:
            http_status = 409
            response = str(ose).encode('utf-8')
    else:
        http_status = 409
        response = b'bad file name'
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    return bytes_sent, http_status


# noinspection PyUnusedLocal
async def api_rename_file_callback(http, verb, args, reader, writer, request_headers=None):
    filename = args.get('filename')
    newname = args.get('newname')
    if valid_filename(filename) and valid_filename(newname):
        filename = http.content_dir + filename
        newname = http.content_dir + newname
        if file_size(newname) >= 0:
            http_status = 409
            response = f'new file {newname} already exists'.encode('utf-8')
        else:
            try:
                os.remove(newname)
            except OSError:
                pass  # swallow exception.
            try:
                os.rename(filename, newname)
                http_status = 200
                response = f'renamed {filename} to {newname}'.encode('utf-8')
            except Exception as ose:
                http_status = 409
                response = str(ose).encode('utf-8')
    else:
        http_status = 409
        response = b'bad file name'
    bytes_sent = http.send_simple_response(writer, http_status, http.CT_APP_JSON, response)
    return bytes_sent, http_status
