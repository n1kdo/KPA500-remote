#
# http server.
#
import os


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

    def __init__(self, content_dir):
        self.content_dir = content_dir

    def serve_content(self, writer, filename):
        filename = self.content_dir + filename
        try:
            content_length = os.stat(filename)[6]
            if not isinstance(content_length, int):
                if content_length.isdigit():
                    content_length = int(content_length)
                else:
                    content_length = -1
        except OSError:
            content_length = -1
        if content_length < 0:
            response = b'<html><body><p>404.  Means &quot;no got&quot;.</p></body></html>'
            http_status = 404
            return self.send_simple_response(writer, http_status, self.CT_TEXT_HTML, response), http_status
        else:
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
            except Exception as e:
                print(type(e), e)
            return content_length, http_status

    def start_response(self, writer, http_status=200, content_type=None, response_size=0, extra_headers=None):
        status_text = self.HTTP_STATUS_TEXT.get(http_status) or 'Confused'
        protocol = 'HTTP/1.0'
        writer.write('{} {} {}\r\n'.format(protocol, http_status, status_text).encode('utf-8'))
        if content_type is not None and len(content_type) > 0:
            writer.write('Content-type: {}; charset=UTF-8\r\n'.format(content_type).encode('utf-8'))
        if response_size > 0:
            writer.write('Content-length: {}\r\n'.format(response_size).encode('utf-8'))
        if extra_headers is not None:
            for header in extra_headers:
                writer.write('{}\r\n'.format(header).encode('utf-8'))
        writer.write(b'\r\n')

    def send_simple_response(self, writer, http_status=200, content_type=None, response=None, extra_headers=None):
        content_length = len(response) if response else 0
        self.start_response(writer, http_status, content_type, content_length, extra_headers)
        if response is not None and len(response) > 0:
            writer.write(response)
        return content_length

    @classmethod
    def unpack_args(cls, s):
        args_dict = {}
        if s is not None:
            args_list = s.split('&')
            for arg in args_list:
                arg_parts = arg.split('=')
                if len(arg_parts) == 2:
                    args_dict[arg_parts[0]] = arg_parts[1]
        return args_dict




