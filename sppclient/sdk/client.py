
import ConfigParser
import json
import logging
import os
import re
import tempfile
import time

import requests
from requests.auth import HTTPBasicAuth

try:
    import urllib3
except ImportError:
    from requests.packages import urllib3

try:
    import http.client as http_client
except ImportError:
    # Python 2
    import httplib as http_client

# Uncomment this to see requests and responses.
# http_client.HTTPConnection.debuglevel = 1
urllib3.disable_warnings()

resource_to_endpoint = {
    'corehv': 'api/hypervisor',
    'coresite': 'api/site',
    'spphv': 'ngp/hypervisor',
    'sppsla': 'ngp/slapolicy',
    'storage': 'ngp/storage',
    'corestorage': 'api/storage',
    'endeavour': 'api/endeavour',
}

resource_to_listfield = {
    'identityuser': 'users',
    'identitycredential': 'users',
}

def build_url(baseurl, restype=None, resid=None, path=None, endpoint=None):
    url = baseurl

    if restype is not None:
        ep = resource_to_endpoint.get(restype, None)
        if not ep:
            if endpoint is not None:
                ep = endpoint
            else:
                ep = restype

        url = url + "/" + ep

    if resid is not None:
        url = url + "/" + str(resid)

    if path is not None:
        if not path.startswith('/'):
            path = '/' + path
        url = url + path

    return url

def raise_response_error(r, *args, **kwargs):
    r.raise_for_status()

def pretty_print(data):
    return logging.info(json.dumps(data, sort_keys=True,indent=4, separators=(',', ': ')))
    
class SppSession(object):
    def __init__(self, url, username=None, password=None, sessionid=None):
        self.url = url
        self.api_url = url + ''
        self.ses_url = url + '/api'
        self.username = username
        self.password = password
        self.sessionid = sessionid

        self.conn = requests.Session()
        self.conn.verify = False
        self.conn.hooks.update({'response': raise_response_error})

        if not self.sessionid:
            if self.username and self.password:
                self.login()
            else:
                raise Exception('Please provide login credentials.')

        self.conn.headers.update({'X-Endeavour-Sessionid': self.sessionid})
        self.conn.headers.update({'Content-Type': 'application/json'})
        self.conn.headers.update({'Accept': 'application/json'})

    def login(self):
        r = self.conn.post("%s/endeavour/session" % self.ses_url, auth=HTTPBasicAuth(self.username, self.password))
        self.sessionid = r.json()['sessionid']

    def logout(self):
        r = self.conn.delete("%s/endeavour/session" % self.ses_url)
    
    def __repr__(self):
        return 'SppSession: user: %s' % self.username

    def get(self, restype=None, resid=None, path=None, params={}, endpoint=None, url=None):
        if url is None:
            url = build_url(self.api_url, restype, resid, path, endpoint)

        return json.loads(self.conn.get(url, params=params).content)

    def stream_get(self, restype=None, resid=None, path=None, params={}, endpoint=None, url=None, outfile=None):
        if url is None:
            url = build_url(self.api_url, restype, resid, path, endpoint)

        r = self.conn.get(url, params=params)
        logging.info("headers: %s" % r.headers)

        # The response header Content-Disposition contains default file name
        #   Content-Disposition: attachment; filename=log_1490030341274.zip
        default_filename = re.findall('filename=(.+)', r.headers['Content-Disposition'])[0]

        if not outfile:
            if not default_filename:
                raise Exception("Couldn't get the file name to save the contents.")

            outfile = os.path.join(tempfile.mkdtemp(), default_filename)

        with open(outfile, 'wb') as fd:
            for chunk in r.iter_content(chunk_size=64*1024):
                fd.write(chunk)

        return outfile

    def delete(self, restype=None, resid=None, path=None, params={}, endpoint=None, url=None):
        if url is None:
            url = build_url(self.api_url, restype, resid, path, endpoint)

        resp = self.conn.delete(url, params=params)

        return json.loads(resp.content) if resp.content else None

    def post(self, restype=None, resid=None, path=None, data={}, params={}, endpoint=None, url=None):
        if url is None:
            url = build_url(self.api_url, restype, resid, path, endpoint)

        logging.info(json.dumps(data, indent=4))
        r = self.conn.post(url, json=data, params=params)

        if r.content:
            return json.loads(r.content)

        return {}
    
    def put(self, restype=None, resid=None, path=None, data={}, params={}, endpoint=None, url=None):
        if url is None:
            url = build_url(self.api_url, restype, resid, path, endpoint)

        logging.info(json.dumps(data, indent=4))
        r = self.conn.put(url, json=data, params=params)

        if r.content:
            return json.loads(r.content)

        return {}

class SppAPI(object):
    def __init__(self, spp_session, restype=None, endpoint=None):
        self.spp_session = spp_session
        self.restype = restype
        self.endpoint = endpoint
        self.list_field = resource_to_listfield.get(restype, self.restype + 's')

    def get(self, resid=None, path=None, params={}, url=None):
        return self.spp_session.get(restype=self.restype, resid=resid, path=path, params=params, url=url)

    def stream_get(self, resid=None, path=None, params={}, url=None, outfile=None):
        return self.spp_session.stream_get(restype=self.restype, resid=resid, path=path,
                                           params=params, url=url, outfile=outfile)

    def delete(self, resid):
         return self.spp_session.delete(restype=self.restype, resid=resid)

    def list(self):
        return self.spp_session.get(restype=self.restype)[self.list_field]

    def post(self, resid=None, path=None, data={}, params={}, url=None):
        return self.spp_session.post(restype=self.restype, resid=resid, path=path, data=data,
                                     params=params, url=url)
                                     
    def put(self, resid=None, path=None, data={}, params={}, url=None):
        return self.spp_session.put(restype=self.restype, resid=resid, path=path, data=data,
                                     params=params, url=url)

class AssociationAPI(SppAPI):
    def __init__(self, spp_session):
        super(AssociationAPI, self).__init__(spp_session, 'association')

    def get_using_resources(self, restype, resid):
        return self.get(path="resource/%s/%s" % (restype, resid), params={"action": "listUsingResources"})

class LogAPI(SppAPI):
    def __init__(self, spp_session):
        super(LogAPI, self).__init__(spp_session, 'log')

    def download_logs(self, outfile=None):
        return self.stream_get(path="download/diagnostics", outfile=outfile)
