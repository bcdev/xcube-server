import unittest

from test.helpers import RequestParamsMock
from xcube_server.errors import ServiceBadRequestError
from xcube_server.reqparams import RequestParams


class RequestParamsTest(unittest.TestCase):
    def test_to_int(self):
        self.assertEqual(2123, RequestParams.to_int('x', '2123'))
        with self.assertRaises(ServiceBadRequestError):
            RequestParams.to_int('x', None)
        with self.assertRaises(ServiceBadRequestError):
            RequestParams.to_int('x', 'bibo')

    def test_to_float(self):
        self.assertEqual(-0.2, RequestParams.to_float('x', '-0.2'))
        with self.assertRaises(ServiceBadRequestError):
            RequestParams.to_float('x', None)
        with self.assertRaises(ServiceBadRequestError):
            RequestParams.to_float('x', 'bibo')

    def test_get_query_argument(self):
        rp = RequestParamsMock()
        self.assertEqual('bert', rp.get_query_argument('s', 'bert'))
        self.assertEqual(234, rp.get_query_argument_int('i', 234))
        self.assertEqual(0.2, rp.get_query_argument_float('f', 0.2))

        rp = RequestParamsMock(s='bibo', i='465', f='0.1')
        self.assertEqual('bibo', rp.get_query_argument('s', None))
        self.assertEqual(465, rp.get_query_argument_int('i', None))
        self.assertEqual(465., rp.get_query_argument_float('i', None))
        self.assertEqual(0.1, rp.get_query_argument_float('f', None))
