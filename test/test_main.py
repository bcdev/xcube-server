import json
import os
import unittest

from tornado.testing import AsyncHTTPTestCase

from xcts.main import new_service, new_application

NETCDF_TEST_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'precip_and_temp.nc')


# For usage of the tornado.testing.AsyncHTTPTestCase see http://www.tornadoweb.org/en/stable/testing.html

@unittest.skipIf(os.environ.get('CATE_DISABLE_WEB_TESTS', None) == '1', 'CATE_DISABLE_WEB_TESTS = 1')
class ServerTest(AsyncHTTPTestCase):
    def get_app(self):
        return new_application()

    def test_base_url(self):
        response = self.fetch('/')
        self.assertEqual(response.code, 200)
        json_dict = json.loads(response.body.decode('utf-8'))
        self.assertIn('name', json_dict)
        self.assertIn('version', json_dict)
        self.assertIn('description', json_dict)


class ServiceSmokeTest(unittest.TestCase):

    def test_start_stop_service(self):
        service = new_service(args=['--port', '20001'])
        service.stop()
