#!/usr/bin/env python

import os
import getpass
import unittest
from yarn.api import env, run

env.host_string = os.environ["IP_ADDR"]
env.host_port = 2222
env.password = "123456"

class TestConnection(unittest.TestCase):

    def test_simple_connection(self):
        run("uptime")

    
